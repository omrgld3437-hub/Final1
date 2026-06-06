"""
TRDCA PRO+ (Trailing Rebalancing + Trailing DCA/Grid).
Snapshot-driven strategy: strategy_tick(snapshot, state) -> (next_state, decision).
Consumption/advance only in apply_fills. Two motors: DCA + TRB; arbitration picks 0/1 intent per tick.
"""

from __future__ import annotations
import hashlib
import json
import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.models import TrdcaProConfig
from app.botengine.strategies.base import Strategy

logger = logging.getLogger(__name__)

# --- Types (spec) ---
# Snapshot: ts (ms), balances_free, prices_last, filters, open_order, fills?
# Decision: NOOP | RESUME_PENDING | SAFE_STOP | ACTIONS([BatchIntent])
# BatchIntent: kind, source, batch_id, legs[], notional_estimate
# Reason: error_code, error_id, request_id, detail?


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _hash_id(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
    return h.hexdigest()[:32]


def _request_id(bot_id: int, ts_ms: int) -> str:
    return f"{bot_id}:{ts_ms}"


def _reason(error_code: str, request_id_str: str, detail: Any = None) -> Dict[str, Any]:
    return {
        "error_code": error_code,
        "error_id": str(uuid.uuid4()),
        "request_id": request_id_str,
        "detail": detail,
    }


def _basket_price(
    weights: Dict[str, float], prices: Dict[str, float], quote_asset: str
) -> Optional[float]:
    total = 0.0
    for asset, w in weights.items():
        if asset == quote_asset:
            total += w * 1.0
            continue
        p = (
            prices.get(asset)
            if asset in prices
            else prices.get(f"{asset}{quote_asset}")
        )
        if p is None or _num(p) <= 0:
            return None
        total += w * _num(p)
    return total


def _floor_to_step(qty: float, step_size: float) -> float:
    if step_size <= 0 or qty <= 0:
        return 0.0
    n = math.floor(qty / step_size)
    return round(n * step_size, max(0, -int(round(math.log10(step_size)))))


def _get_filters(filters: Dict[str, Any], symbol: str) -> Dict[str, float]:
    s = filters.get(symbol) or {}
    return {
        "minQty": _num(s.get("minQty") or s.get("min_qty")),
        "stepSize": _num(s.get("stepSize") or s.get("step_size") or 0.00001),
        "minNotional": _num(s.get("minNotional") or s.get("min_notional") or 5),
    }


# --- Validate / normalize batch ---
def validate_and_normalize_batch(
    snapshot: Dict[str, Any],
    state: Dict[str, Any],
    config: TrdcaProConfig,
    batch_intent: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Validate batch and normalize quantities. Returns (ok, normalized_batch, error)."""
    legs = batch_intent.get("legs") or []
    quote_asset = state.get("quote_asset") or config.quote_asset
    prices = snapshot.get("prices_last") or {}
    filters = snapshot.get("filters") or {}
    if not legs:
        return False, None, "INVALID_BATCH_NO_LEGS"
    max_legs = int(getattr(config, "trb_max_batch_legs", 8) or 8)
    if len(legs) > max_legs:
        return False, None, f"INVALID_BATCH_MAX_LEGS len={len(legs)} max={max_legs}"
    for leg in legs:
        sym = (leg.get("symbol") or "").upper()
        side = (leg.get("side") or "").upper()
        qty = _num(leg.get("qty"))
        f = _get_filters(filters, sym)
        if qty <= 0:
            return False, None, f"INVALID_BATCH_LEG_QTY symbol={sym}"
        base = sym.replace(quote_asset, "") if quote_asset in sym else sym
        price = prices.get(base) or prices.get(sym)
        if not price or _num(price) <= 0:
            return False, None, f"INVALID_BATCH_NO_PRICE symbol={sym}"
        price_f = _num(price)
        notional = qty * price_f if side == "SELL" else qty * price_f
        min_notional_leg = f.get("minNotional") or getattr(
            config, "min_notional_guard", 10.0
        )
        if notional < _num(min_notional_leg):
            return (
                False,
                None,
                f"INVALID_BATCH_MIN_NOTIONAL symbol={sym} notional={notional} min={min_notional_leg}",
            )
        step = f.get("stepSize") or 0.00001
        if step > 0:
            leg["qty"] = _floor_to_step(qty, step)
    return True, batch_intent, None


# --- DCA motor (pure) ---
def _dca_armed_none() -> Dict[str, Any]:
    return {
        "type": "NONE",
        "level_idx": None,
        "peak_or_trough": None,
        "started_at_ts": None,
    }


def dca_tick(
    snapshot: Dict[str, Any],
    state: Dict[str, Any],
    config: TrdcaProConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    DCA motor tick. Returns (state_patch, proposal).
    proposal: { source, want_action, valid, action, intent_id, reason, priority, just_triggered, triggered_at_ts, notional_estimate, impact_score, meta?, exec_basket_price? }
    """
    patch: Dict[str, Any] = {"dca": (state.get("dca") or {}).copy()}
    proposal = {
        "source": "DCA",
        "want_action": False,
        "valid": True,
        "action": None,
        "intent_id": "",
        "reason": "",
        "priority": 0,
        "just_triggered": False,
        "triggered_at_ts": 0,
        "notional_estimate": 0.0,
        "impact_score": 0.0,
        "meta": None,
        "exec_basket_price": None,
    }
    if not getattr(config, "dca_enabled", True):
        return patch, proposal

    ts_ms = int(_num(snapshot.get("ts") or 0))
    prices = snapshot.get("prices_last") or {}
    quote_asset = state.get("quote_asset") or config.quote_asset
    prices_asset = {}
    for k, v in prices.items():
        if isinstance(v, (int, float)) and v > 0:
            if k == quote_asset:
                prices_asset[k] = 1.0
            elif k.endswith(quote_asset):
                prices_asset[k.replace(quote_asset, "")] = float(v)
            else:
                prices_asset[k] = float(v)
    if quote_asset not in prices_asset:
        prices_asset[quote_asset] = 1.0

    weights = getattr(config, "dca_coin_weights", None) or {}
    price_null_assets = set()
    for asset in weights or {}:
        if asset == quote_asset:
            continue
        p = prices_asset.get(asset)
        if p is None or _num(p) <= 0:
            price_null_assets.add(asset)
    patch["price_null_assets"] = price_null_assets

    basket = _basket_price(weights, prices_asset, quote_asset)
    if basket is None or basket <= 0:
        return patch, proposal

    anchor = _num(state.get("anchor_price"))
    if not anchor or anchor <= 0:
        anchor = basket
        # Prompt: "anchor set init, DCA does not mutate anchor" — do not write anchor_price here

    dca = patch["dca"]
    grid_up = getattr(config, "dca_grid_up_levels_pct", [1, 2, 3])
    grid_down = getattr(config, "dca_grid_down_levels_pct", [1, 2, 3])
    up_consumed = dca.get("grid_up_consumed") or [False] * len(grid_up)
    down_consumed = dca.get("grid_down_consumed") or [False] * len(grid_down)
    up_consumed = list(up_consumed) + [False] * (len(grid_up) - len(up_consumed))
    down_consumed = list(down_consumed) + [False] * (
        len(grid_down) - len(down_consumed)
    )
    dca["grid_up_consumed"] = up_consumed[: len(grid_up)]
    dca["grid_down_consumed"] = down_consumed[: len(grid_down)]

    armed = dca.get("armed") or _dca_armed_none()
    vwap_sell = dca.get("vwap_sell")
    vwap_buy = dca.get("vwap_buy")
    sell_trail = _num(getattr(config, "dca_sell_trail_back_pct", 0.8)) / 100.0
    buy_trail = _num(getattr(config, "dca_buy_trail_up_pct", 0.8)) / 100.0
    dip_trigger = _num(getattr(config, "dca_post_sell_dip_trigger_pct", 2)) / 100.0
    dip_trail = _num(getattr(config, "dca_post_sell_dip_trail_up_pct", 0.8)) / 100.0
    profit_trigger = _num(getattr(config, "dca_post_buy_profit_trigger_pct", 2)) / 100.0
    profit_trail = (
        _num(getattr(config, "dca_post_buy_profit_sell_trail_back_pct", 0.8)) / 100.0
    )
    buy_buffer = _num(getattr(config, "dca_buy_buffer_pct", 0.2)) / 100.0

    # Precedence: 1) POSTSELL_DIP 2) POSTBUY_PEAK 3) UP_SELL smallest k 4) DOWN_BUY smallest k
    chosen_type = None
    chosen_level_idx = None
    target_notional = 0.0

    # 1) POSTSELL_DIP
    if vwap_sell and (
        armed.get("type") == "POSTSELL_DIP"
        or (basket <= vwap_sell.get("price", 0) * (1 - dip_trigger))
    ):
        _num(vwap_sell.get("price"))
        if armed.get("type") == "POSTSELL_DIP":
            trough = _num(armed.get("peak_or_trough")) or basket
            trough = min(trough, basket)
            dca["armed"] = {
                "type": "POSTSELL_DIP",
                "level_idx": None,
                "peak_or_trough": trough,
                "started_at_ts": armed.get("started_at_ts") or ts_ms,
            }
            if basket >= trough * (1 + dip_trail):
                chosen_type = "POSTSELL_DIP"
                target_notional = _num(
                    getattr(config, "dca_post_sell_dip_buy_notional_usdt", 200)
                )
        else:
            dca["armed"] = {
                "type": "POSTSELL_DIP",
                "level_idx": None,
                "peak_or_trough": basket,
                "started_at_ts": ts_ms,
            }

    if (
        chosen_type is None
        and vwap_buy
        and (
            armed.get("type") == "POSTBUY_PEAK"
            or (basket >= vwap_buy.get("price", 0) * (1 + profit_trigger))
        )
    ):
        _num(vwap_buy.get("price"))
        if armed.get("type") == "POSTBUY_PEAK":
            peak = _num(armed.get("peak_or_trough")) or basket
            peak = max(peak, basket)
            dca["armed"] = {
                "type": "POSTBUY_PEAK",
                "level_idx": None,
                "peak_or_trough": peak,
                "started_at_ts": armed.get("started_at_ts") or ts_ms,
            }
            if basket <= peak * (1 - profit_trail):
                chosen_type = "POSTBUY_PEAK"
                target_notional = _num(
                    getattr(config, "dca_post_buy_profit_sell_notional_usdt", 200)
                )
        else:
            dca["armed"] = {
                "type": "POSTBUY_PEAK",
                "level_idx": None,
                "peak_or_trough": basket,
                "started_at_ts": ts_ms,
            }

    if chosen_type is None:
        for k in range(len(grid_up)):
            if up_consumed[k]:
                continue
            thr = anchor * (1 + _num(grid_up[k]) / 100.0)
            if basket >= thr:
                if armed.get("type") == "UP_SELL" and armed.get("level_idx") == k:
                    peak = _num(armed.get("peak_or_trough")) or basket
                    peak = max(peak, basket)
                    dca["armed"] = {
                        "type": "UP_SELL",
                        "level_idx": k,
                        "peak_or_trough": peak,
                        "started_at_ts": armed.get("started_at_ts") or ts_ms,
                    }
                    if basket <= peak * (1 - sell_trail):
                        chosen_type = "UP_SELL"
                        chosen_level_idx = k
                        target_notional = _num(
                            (
                                getattr(
                                    config, "dca_grid_up_notional_usdt", [200, 200, 200]
                                )[k]
                                if k
                                < len(getattr(config, "dca_grid_up_notional_usdt", []))
                                else 200
                            )
                        )
                        break
                else:
                    dca["armed"] = {
                        "type": "UP_SELL",
                        "level_idx": k,
                        "peak_or_trough": basket,
                        "started_at_ts": ts_ms,
                    }
                break

    if chosen_type is None:
        for k in range(len(grid_down)):
            if down_consumed[k]:
                continue
            thr = anchor * (1 - _num(grid_down[k]) / 100.0)
            if basket <= thr:
                if armed.get("type") == "DOWN_BUY" and armed.get("level_idx") == k:
                    trough = _num(armed.get("peak_or_trough")) or basket
                    trough = min(trough, basket)
                    dca["armed"] = {
                        "type": "DOWN_BUY",
                        "level_idx": k,
                        "peak_or_trough": trough,
                        "started_at_ts": armed.get("started_at_ts") or ts_ms,
                    }
                    if basket >= trough * (1 + buy_trail):
                        chosen_type = "DOWN_BUY"
                        chosen_level_idx = k
                        target_notional = _num(
                            (
                                getattr(
                                    config,
                                    "dca_grid_down_notional_usdt",
                                    [200, 200, 200],
                                )[k]
                                if k
                                < len(
                                    getattr(config, "dca_grid_down_notional_usdt", [])
                                )
                                else 200
                            )
                        )
                        break
                else:
                    dca["armed"] = {
                        "type": "DOWN_BUY",
                        "level_idx": k,
                        "peak_or_trough": basket,
                        "started_at_ts": ts_ms,
                    }
                break

    if chosen_type is None:
        proposal["reason"] = "NONE"
        return patch, proposal

    # Build batch legs (oransal)
    filters = snapshot.get("filters") or {}
    legs = []
    bot_id = int(_num(state.get("bot_id") or 0))
    config_hash = state.get("config_hash") or _hash_id(
        json.dumps(config.to_dict(), sort_keys=True)
    )
    anchor_id = state.get("anchor_id") or _hash_id(
        config_hash,
        state.get("basket_weights_hash", ""),
        anchor,
        state.get("anchor_set_ts_bucket", 0),
    )
    state.get("basket_weights_hash") or _hash_id(json.dumps(weights, sort_keys=True))
    batch_id = _hash_id(
        bot_id, "DCA", chosen_type, chosen_level_idx, anchor_id, config_hash
    )
    intent_id = _hash_id(bot_id, "DCA", batch_id, anchor_id, config_hash)

    is_sell = chosen_type in ("UP_SELL", "POSTBUY_PEAK")
    if is_sell:
        alloc_notional = target_notional
    else:
        alloc_notional = target_notional * (1 - buy_buffer)

    for asset, w in weights.items():
        if w <= 0:
            continue
        sym = f"{asset}{quote_asset}"
        price = prices_asset.get(asset) or prices_asset.get(sym)
        if not price or price <= 0:
            continue
        f = _get_filters(filters, sym)
        step = f.get("stepSize") or 0.00001
        part = alloc_notional * w / price if price else 0
        qty = _floor_to_step(part, step)
        if qty <= 0:
            continue
        side = "SELL" if is_sell else "BUY"
        coid = f"DCA-{batch_id}-{len(legs)}-{sym}-{side}"
        legs.append({"symbol": sym, "side": side, "qty": qty, "client_order_id": coid})

    if not legs:
        proposal["want_action"] = False
        proposal["valid"] = False
        proposal["reason"] = "NO_LEGS"
        return patch, proposal

    batch = {
        "kind": "BATCH_MARKET_ORDERS",
        "source": "DCA",
        "batch_id": batch_id,
        "legs": legs,
        "notional_estimate": target_notional,
    }
    ok, normalized, err = validate_and_normalize_batch(snapshot, state, config, batch)
    if not ok:
        proposal["want_action"] = False
        proposal["valid"] = False
        proposal["reason"] = err or "INVALID_BATCH"
        return patch, proposal

    proposal["want_action"] = True
    proposal["action"] = normalized
    proposal["intent_id"] = intent_id
    proposal["reason"] = chosen_type
    proposal["priority"] = 90
    proposal["just_triggered"] = True
    proposal["triggered_at_ts"] = ts_ms
    proposal["notional_estimate"] = target_notional
    proposal["impact_score"] = target_notional
    proposal["meta"] = {
        "reason_code": f"DCA_{chosen_type}",
        "armed_type": chosen_type,
        "level_idx": chosen_level_idx,
    }
    proposal["exec_basket_price"] = basket
    return patch, proposal


# --- TRB motor (simplified: gap + trail, single-step plan) ---
def trb_tick(
    snapshot: Dict[str, Any],
    state: Dict[str, Any],
    config: TrdcaProConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """TRB motor tick. Returns (state_patch, proposal)."""
    patch: Dict[str, Any] = {"trb": (state.get("trb") or {}).copy()}
    proposal = {
        "source": "TRB",
        "want_action": False,
        "valid": True,
        "action": None,
        "intent_id": "",
        "reason": "",
        "priority": 0,
        "just_triggered": False,
        "triggered_at_ts": 0,
        "notional_estimate": 0.0,
        "impact_score": 0.0,
        "meta": None,
        "exec_basket_price": None,
    }
    if not getattr(config, "trb_enabled", True):
        return patch, proposal

    ts_ms = int(_num(snapshot.get("ts") or 0))
    balances = snapshot.get("balances_free") or {}
    prices = snapshot.get("prices_last") or {}
    quote_asset = state.get("quote_asset") or config.quote_asset
    target_weights_raw = getattr(config, "trb_target_weights_all", None) or {}
    if not target_weights_raw:
        return patch, proposal
    # Target weights normalizasyonu: toplam 1 olsun, base varlıklar orantılı dağılsın
    tw_sum = sum(_num(v) for v in target_weights_raw.values())
    target_weights = (
        {k: _num(v) / tw_sum for k, v in target_weights_raw.items()}
        if tw_sum > 0
        else target_weights_raw
    )

    price_null_assets = set()
    for asset in target_weights:
        if asset == quote_asset:
            continue
        p = prices.get(asset) or prices.get(f"{asset}{quote_asset}")
        if p is None or _num(p) <= 0:
            price_null_assets.add(asset)
    patch["price_null_assets"] = price_null_assets

    total_value = 0.0
    for asset, w in target_weights.items():
        if asset == quote_asset:
            free = _num(balances.get(asset))
            total_value += free
        else:
            sym = f"{asset}{quote_asset}"
            p = prices.get(asset) or prices.get(sym)
            if p is None or _num(p) <= 0:
                continue
            free = _num(balances.get(asset))
            total_value += free * _num(p)
    if total_value <= 0:
        return patch, proposal

    gap_arm_pct = _num(getattr(config, "trb_gap_arm_pct", 3)) / 100.0
    trail_back_pct = _num(getattr(config, "trb_trail_back_pct", 0.6)) / 100.0
    trb = patch["trb"]
    trb_state = trb.get("trb_state") or "IDLE"
    gap_peak = _num(trb.get("gap_peak_pct"))

    current_weights = {}
    for asset, w in target_weights.items():
        if asset == quote_asset:
            current_weights[asset] = (
                _num(balances.get(asset)) / total_value if total_value else 0
            )
        else:
            sym = f"{asset}{quote_asset}"
            p = prices.get(asset) or prices.get(sym)
            if p is None or _num(p) <= 0:
                continue
            current_weights[asset] = (
                (_num(balances.get(asset)) * _num(p)) / total_value
                if total_value
                else 0
            )
    gap_pct = 0.0
    for asset in target_weights:
        tw = _num(target_weights.get(asset))
        cw = current_weights.get(asset) or 0
        gap_pct = max(gap_pct, abs(tw - cw))

    # Initial allocation: tüm base asset'ler 0 iken (100% quote) hemen alım yap
    base_sum = sum(
        _num(balances.get(a)) * _num(prices.get(a) or prices.get(f"{a}{quote_asset}"))
        for a in target_weights
        if a != quote_asset
    )
    is_initial_allocation = base_sum <= 0 and _num(balances.get(quote_asset)) > 0

    if trb_state == "IDLE":
        if gap_pct >= gap_arm_pct:
            trb["trb_state"] = "TRAIL"
            trb["gap_peak_pct"] = gap_pct
            trb["trb_triggered_at_ts"] = ts_ms
            # İlk tahsis: IDLE->TRAIL geçişinde hemen plan yap ve execute et (2. tick bekleme)
            if is_initial_allocation:
                trb_state = (
                    "TRAIL"  # Aşağıdaki TRAIL bloğuna düş, aynı tick'te alım yap
                )
            else:
                proposal["reason"] = "IDLE"
                return patch, proposal
        else:
            proposal["reason"] = "IDLE"
            return patch, proposal

    if trb_state == "TRAIL":
        trb["gap_peak_pct"] = max(gap_peak, gap_pct)
        # İlk tahsis: 100% quote iken hemen al; trail_back için gap düşmeyi bekleme
        gap_ok = gap_pct <= gap_peak * (1 - trail_back_pct) or (
            is_initial_allocation and gap_pct >= gap_arm_pct
        )
        if gap_ok:
            plan = trb.get("plan")
            if not plan:
                plan_id = _hash_id(state.get("bot_id"), "TRB", ts_ms, gap_peak)
                steps = _trb_build_steps(
                    state,
                    config,
                    balances,
                    prices,
                    target_weights,
                    total_value,
                    quote_asset,
                    snapshot,
                )
                if not steps:
                    proposal["reason"] = "NO_STEPS"
                    return patch, proposal
                trb["plan"] = {
                    "plan_id": plan_id,
                    "plan_weights_hash": _hash_id(
                        json.dumps(target_weights, sort_keys=True)
                    ),
                    "created_at_ts": ts_ms,
                    "step_idx": 0,
                    "steps": steps,
                }
                plan = trb["plan"]
            if plan and plan.get("steps"):
                step_idx = int(plan.get("step_idx") or 0)
                steps = plan.get("steps") or []
                if step_idx < len(steps):
                    batch = steps[step_idx]
                    bot_id = int(_num(state.get("bot_id") or 0))
                    intent_id = _hash_id(
                        bot_id, "TRB", batch.get("batch_id"), plan.get("plan_id")
                    )
                    proposal["want_action"] = True
                    proposal["action"] = batch
                    proposal["intent_id"] = intent_id
                    proposal["reason"] = "TRB_STEP"
                    proposal["priority"] = 70
                    proposal["just_triggered"] = step_idx == 0
                    proposal["triggered_at_ts"] = plan.get("created_at_ts") or ts_ms
                    proposal["notional_estimate"] = _num(batch.get("notional_estimate"))
                    proposal["impact_score"] = proposal["notional_estimate"]
                    proposal["meta"] = {
                        "reason_code": "TRB_STEP",
                        "armed_type": None,
                        "level_idx": None,
                    }
        proposal["reason"] = proposal["reason"] or "TRAIL"
    return patch, proposal


def _trb_legs_signature(sell_legs: List[Dict], buy_legs: List[Dict]) -> str:
    """Deterministic signature from leg content (symbol, side, qty) for restart-safe batch_id."""
    combined = []
    for leg in sell_legs + buy_legs:
        combined.append(
            (leg.get("symbol", ""), leg.get("side", ""), _num(leg.get("qty")))
        )
    combined.sort(key=lambda x: (x[0], x[1]))
    return _hash_id(json.dumps(combined, sort_keys=True))


def _trb_build_steps(
    state: Dict[str, Any],
    config: TrdcaProConfig,
    balances: Dict[str, float],
    prices: Dict[str, Any],
    target_weights: Dict[str, float],
    total_value: float,
    quote_asset: str,
    snapshot: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build TRB steps: SELL_ONLY_THEN_BUY => first step SELL legs only, second step BUY legs; max_batch_legs respected."""
    filters = snapshot.get("filters") or {}
    max_legs = int(getattr(config, "trb_max_batch_legs", 8) or 8)
    sell_first = bool(getattr(config, "trb_sell_first", True))
    step_mode = (
        (getattr(config, "trb_step_mode", None) or "SELL_ONLY_THEN_BUY").strip().upper()
    )

    sell_legs = []
    buy_legs = []
    for asset in sorted(target_weights.keys()):
        tw = _num(target_weights.get(asset))
        if asset == quote_asset:
            current = _num(balances.get(asset))
            target_val = total_value * tw
            delta = target_val - current
            if abs(delta) < _num(getattr(config, "trb_min_leg_notional_usdt", 10)):
                continue
            # quote delta: positive = need more quote (sell others), negative = excess quote (buy others)
            pass
        else:
            sym = f"{asset}{quote_asset}"
            p = prices.get(asset) or prices.get(sym)
            if not p or _num(p) <= 0:
                continue
            current_qty = _num(balances.get(asset))
            current_val = current_qty * _num(p)
            target_val = total_value * tw
            delta_val = target_val - current_val
            if abs(delta_val) < _num(getattr(config, "trb_min_leg_notional_usdt", 10)):
                continue
            f = _get_filters(filters, sym)
            step = f.get("stepSize") or 0.00001
            qty = abs(delta_val) / _num(p)
            qty = _floor_to_step(qty, step)
            if qty <= 0:
                continue
            side = "SELL" if delta_val < 0 else "BUY"
            leg = {"symbol": sym, "side": side, "qty": qty}
            if side == "SELL":
                sell_legs.append(leg)
            else:
                buy_legs.append(leg)

    # Restart-safe batch_id from plan content (not wall-clock) so same state → same batch_id
    plan_weights_hash = _hash_id(json.dumps(target_weights, sort_keys=True))
    legs_sig = _trb_legs_signature(sell_legs, buy_legs)
    batch_id = _hash_id(state.get("bot_id"), "TRB", plan_weights_hash, legs_sig)

    def assign_coids(leg_list: List[Dict], base_idx: int) -> None:
        for i, leg in enumerate(leg_list):
            sym = leg.get("symbol", "")
            side = leg.get("side", "BUY")
            leg["client_order_id"] = f"TRB-{batch_id}-{base_idx + i}-{sym}-{side}"

    steps = []
    if step_mode == "SELL_ONLY_THEN_BUY" and sell_first:
        if sell_legs:
            sell_chunk = sell_legs[:max_legs]
            assign_coids(sell_chunk, 0)
            notional = sum(
                _num(l.get("qty"))
                * _num(prices.get((l.get("symbol") or "").replace(quote_asset, "")))
                for l in sell_chunk
            )
            steps.append(
                {
                    "kind": "BATCH_MARKET_ORDERS",
                    "source": "TRB",
                    "batch_id": batch_id,
                    "legs": sell_chunk,
                    "notional_estimate": notional,
                }
            )
        if buy_legs:
            buy_chunk = buy_legs[:max_legs]
            assign_coids(buy_chunk, len(sell_legs))
            notional = sum(
                _num(l.get("qty"))
                * _num(prices.get((l.get("symbol") or "").replace(quote_asset, "")))
                for l in buy_chunk
            )
            steps.append(
                {
                    "kind": "BATCH_MARKET_ORDERS",
                    "source": "TRB",
                    "batch_id": batch_id,
                    "legs": buy_chunk,
                    "notional_estimate": notional,
                }
            )
    else:
        all_legs = (sell_legs + buy_legs)[:max_legs]
        if all_legs:
            assign_coids(all_legs, 0)
            notional = sum(
                _num(l.get("qty"))
                * _num(prices.get((l.get("symbol") or "").replace(quote_asset, "")))
                for l in all_legs
            )
            steps.append(
                {
                    "kind": "BATCH_MARKET_ORDERS",
                    "source": "TRB",
                    "batch_id": batch_id,
                    "legs": all_legs,
                    "notional_estimate": notional,
                }
            )
    return steps


# --- Arbitration ---
def arbitrate(
    snapshot: Dict[str, Any],
    state: Dict[str, Any],
    prop_dca: Dict[str, Any],
    prop_trb: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return winning proposal or None. Tie-break: priority, just_triggered, impact_score, triggered_at_ts asc, lexicographic (source, batch_id)."""
    candidates = []
    if prop_dca.get("want_action") and prop_dca.get("valid"):
        candidates.append(prop_dca)
    if prop_trb.get("want_action") and prop_trb.get("valid"):
        candidates.append(prop_trb)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def key(p):
        return (
            -(p.get("priority") or 0),
            -int(p.get("just_triggered") or False),
            -(p.get("impact_score") or 0),
            p.get("triggered_at_ts") or 0,
            p.get("source") or "",
            p.get("action", {}).get("batch_id") or "",
        )

    candidates.sort(key=key)
    return candidates[0]


# --- apply_fills ---
def apply_fills(
    state: Dict[str, Any],
    fills: List[Dict[str, Any]],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply fills to state. Clear active_intent only when ALL legs FILLED; else SAFE_STOP. Use commit_snapshot for pending cleanup."""
    state = dict(state)
    active = state.get("active_intent")
    if not active:
        return state

    expected_legs = active.get("legs") or []
    len(expected_legs)
    status_map = {}
    for leg in expected_legs:
        coid = leg.get("client_order_id")
        status_map[coid] = "UNKNOWN"
    for f in fills:
        coid = f.get("client_order_id")
        if coid not in status_map:
            continue
        st = (f.get("status") or "").upper()
        if st == "FILLED":
            status_map[coid] = "FILLED"
        elif st in ("PARTIALLY_FILLED", "CANCELED", "CANCELLED", "REJECTED"):
            status_map[coid] = "PARTIAL"

    bot_id = int(_num(state.get("bot_id") or 0))
    snapshot_ts = int(_num(snapshot.get("ts") or 0))
    request_id_str = _request_id(bot_id, snapshot_ts)

    if any(v == "PARTIAL" for v in status_map.values()):
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = {
            "error_code": "PARTIAL_BATCH_EXECUTION",
            "error_id": str(uuid.uuid4()),
            "request_id": request_id_str,
            "detail": status_map,
        }
        state["last_tick_ts"] = snapshot_ts
        return state

    if not all(v == "FILLED" for v in status_map.values()):
        return state

    state["last_tick_ts"] = snapshot_ts
    commit = active.get("commit_snapshot") or {}
    pq = _num(state.get("pending_quote_committed")) - _num(
        commit.get("commit_quote_total")
    )
    if pq < 0:
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = _reason(
            "PENDING_CLEANUP_MISMATCH",
            request_id_str,
            {
                "detail": "pending_quote_committed would go negative",
                "before": state.get("pending_quote_committed"),
                "commit_quote_total": commit.get("commit_quote_total"),
            },
        )
        return state
    state["pending_quote_committed"] = pq
    for asset, amt in (commit.get("commit_base_total_by_asset") or {}).items():
        state["pending_base_committed"] = state.get("pending_base_committed") or {}
        before_a = _num(state["pending_base_committed"].get(asset)) - _num(amt)
        if before_a < 0:
            state["mode"] = "SAFE_STOP"
            state["last_reason"] = _reason(
                "PENDING_CLEANUP_MISMATCH",
                request_id_str,
                {
                    "detail": "pending_base_committed would go negative",
                    "asset": asset,
                    "before": state["pending_base_committed"].get(asset),
                    "commit_amt": amt,
                },
            )
            return state
        state["pending_base_committed"][asset] = before_a

    source = active.get("source")
    meta = active.get("meta") or {}
    if source == "DCA":
        dca = (state.get("dca") or {}).copy()
        level_idx = meta.get("level_idx")
        armed_type = meta.get("armed_type")
        if level_idx is not None and armed_type == "UP_SELL":
            consumed = list(dca.get("grid_up_consumed") or [])
            if level_idx < len(consumed):
                consumed[level_idx] = True
            dca["grid_up_consumed"] = consumed
        if level_idx is not None and armed_type == "DOWN_BUY":
            consumed = list(dca.get("grid_down_consumed") or [])
            if level_idx < len(consumed):
                consumed[level_idx] = True
            dca["grid_down_consumed"] = consumed
        exec_basket = active.get("exec_basket_price")
        if exec_basket is not None:
            notional = _num(
                active.get("commit_snapshot", {}).get("commit_quote_total")
            ) or _num(commit.get("commit_quote_total"))
            if "SELL" in str(meta.get("reason_code", "")):
                dca["vwap_sell"] = {"price": exec_basket, "notional": notional}
            else:
                dca["vwap_buy"] = {"price": exec_basket, "notional": notional}
        dca["armed"] = _dca_armed_none()
        state["dca"] = dca
    elif source == "TRB":
        trb = (state.get("trb") or {}).copy()
        plan = trb.get("plan")
        if plan:
            step_idx = int(plan.get("step_idx") or 0) + 1
            steps = plan.get("steps") or []
            if step_idx >= len(steps):
                trb["plan"] = None
                trb["trb_state"] = "IDLE"
                trb["gap_peak_pct"] = 0.0
                trb["trb_cycles_count"] = int(trb.get("trb_cycles_count") or 0) + 1
            else:
                plan = dict(plan)
                plan["step_idx"] = step_idx
                trb["plan"] = plan
        state["trb"] = trb

    state["active_intent"] = None
    return state


def _build_commit_snapshot(
    batch_intent: Dict[str, Any], prices: Dict[str, Any], quote_asset: str
) -> Dict[str, Any]:
    commit_quote_by_leg = {}
    commit_base_by_leg = {}
    commit_quote_total = 0.0
    commit_base_total_by_asset = {}
    for leg in batch_intent.get("legs") or []:
        coid = leg.get("client_order_id")
        sym = (leg.get("symbol") or "").upper()
        side = (leg.get("side") or "").upper()
        qty = _num(leg.get("qty"))
        base = sym.replace(quote_asset, "") if quote_asset in sym else sym
        price = _num(prices.get(base) or prices.get(sym))
        if side == "BUY":
            notional = qty * price if price else 0
            commit_quote_by_leg[coid] = notional
            commit_quote_total += notional
        else:
            commit_base_by_leg[coid] = qty
            commit_base_total_by_asset[base] = (
                commit_base_total_by_asset.get(base, 0) + qty
            )
    return {
        "commit_quote_by_leg": commit_quote_by_leg,
        "commit_base_by_leg": commit_base_by_leg,
        "commit_quote_total": commit_quote_total,
        "commit_base_total_by_asset": commit_base_total_by_asset,
    }


# --- strategy_tick ---
def strategy_tick(
    snapshot: Dict[str, Any],
    state: Dict[str, Any],
    config: TrdcaProConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Main entry: (snapshot, state, config) -> (next_state, decision).
    decision: { type: NOOP | RESUME_PENDING | SAFE_STOP | ACTIONS, actions?: [BatchIntent], reason?: Reason, debug?: any }
    """
    state = dict(state)
    bot_id = int(_num(state.get("bot_id") or 0))
    ts_ms = int(_num(snapshot.get("ts") or 0))
    request_id = _request_id(bot_id, ts_ms)
    quote_asset = state.get("quote_asset") or config.quote_asset

    if (
        not snapshot.get("ts")
        or not isinstance(snapshot.get("balances_free"), dict)
        or not isinstance(snapshot.get("prices_last"), dict)
    ):
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = _reason(
            "SNAPSHOT_INVALID", request_id, "missing critical fields"
        )
        state["last_tick_ts"] = ts_ms
        return state, {
            "type": "SAFE_STOP",
            "reason": state["last_reason"],
            "debug": {"bot_id": bot_id, "ts": ts_ms},
        }
    if "filters" not in snapshot or "open_order" not in snapshot:
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = _reason(
            "SNAPSHOT_INVALID", request_id, "missing filters or open_order"
        )
        state["last_tick_ts"] = ts_ms
        return state, {
            "type": "SAFE_STOP",
            "reason": state["last_reason"],
            "debug": {"bot_id": bot_id, "ts": ts_ms},
        }

    if ts_ms <= int(_num(state.get("last_tick_ts") or 0)):
        return state, {"type": "NOOP", "debug": {"bot_id": bot_id, "ts": ts_ms}}

    mode = state.get("mode") or "RUNNING"
    if mode == "SAFE_STOP":
        return state, {
            "type": "SAFE_STOP",
            "reason": state.get("last_reason"),
            "debug": {"bot_id": bot_id},
        }
    if mode == "RESUME_PENDING":
        return state, {
            "type": "RESUME_PENDING",
            "reason": state.get("last_reason"),
            "debug": {"bot_id": bot_id},
        }

    if snapshot.get("fills"):
        state = apply_fills(state, snapshot["fills"], snapshot)

    if snapshot.get("open_order"):
        state["last_tick_ts"] = ts_ms
        return state, {"type": "NOOP", "debug": {"bot_id": bot_id, "open_order": True}}

    active = state.get("active_intent")
    ack_timeout_ms = getattr(config, "ack_timeout_sec", 5) * 1000
    if active and active.get("status") == "SENT":
        send_ms = int(_num(active.get("send_time_ms") or 0))
        if ts_ms - send_ms < ack_timeout_ms:
            state["mode"] = "RESUME_PENDING"
            state["last_reason"] = _reason("ORDER_ACK_WAIT", request_id)
            state["last_tick_ts"] = ts_ms
            return state, {
                "type": "RESUME_PENDING",
                "reason": state["last_reason"],
                "debug": {"bot_id": bot_id},
            }
        # ACK timeout: distinguish "no ack" vs "some legs never reported" (UNKNOWN forever)
        reason_code = (
            "UNKNOWN_LEGS_ACK_TIMEOUT" if snapshot.get("fills") else "ORDER_ACK_TIMEOUT"
        )
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = _reason(reason_code, request_id)
        state["last_tick_ts"] = ts_ms
        return state, {
            "type": "SAFE_STOP",
            "reason": state["last_reason"],
            "debug": {"bot_id": bot_id},
        }

    dca_patch, prop_dca = dca_tick(snapshot, state, config)
    trb_patch, prop_trb = trb_tick(snapshot, state, config)
    for k, v in dca_patch.items():
        state[k] = v
    for k, v in trb_patch.items():
        state[k] = v

    # Data health gate: merge price_null_strikes, SAFE_STOP on limit breach
    null_union = set(dca_patch.get("price_null_assets") or []) | set(
        trb_patch.get("price_null_assets") or []
    )
    all_assets = (
        set(getattr(config, "trb_target_weights_all", None) or {})
        | set(getattr(config, "dca_coin_weights", None) or {})
        | {quote_asset}
    )
    strikes = dict(state.get("price_null_strikes") or {})
    for asset in all_assets:
        if asset in null_union:
            strikes[asset] = strikes.get(asset, 0) + 1
        else:
            strikes[asset] = 0
    state["price_null_strikes"] = strikes
    state.pop("price_null_assets", None)
    strike_limit = int(_num(getattr(config, "price_null_strike_limit", 10)) or 10)
    if strike_limit > 0 and (max(strikes.values()) >= strike_limit):
        state["mode"] = "SAFE_STOP"
        state["last_reason"] = _reason(
            "MARKET_DATA_INCOMPLETE",
            request_id,
            {"strikes": strikes, "limit": strike_limit},
        )
        state["last_tick_ts"] = ts_ms
        return state, {
            "type": "SAFE_STOP",
            "reason": state["last_reason"],
            "debug": {"bot_id": bot_id, "ts": ts_ms},
        }

    if prop_dca.get("want_action"):
        ok, norm, err = validate_and_normalize_batch(
            snapshot, state, config, prop_dca.get("action") or {}
        )
        if not ok:
            prop_dca["want_action"] = False
            prop_dca["valid"] = False
    if prop_trb.get("want_action"):
        ok, norm, err = validate_and_normalize_batch(
            snapshot, state, config, prop_trb.get("action") or {}
        )
        if not ok:
            prop_trb["want_action"] = False
            prop_trb["valid"] = False

    winner = arbitrate(snapshot, state, prop_dca, prop_trb)
    if not winner:
        state["last_tick_ts"] = ts_ms
        return state, {"type": "NOOP", "debug": {"bot_id": bot_id, "ts": ts_ms}}

    action = winner.get("action")
    if not action or not action.get("legs"):
        state["last_tick_ts"] = ts_ms
        return state, {"type": "NOOP", "debug": {"bot_id": bot_id}}

    commit = _build_commit_snapshot(
        action, snapshot.get("prices_last") or {}, quote_asset
    )
    state["active_intent"] = {
        "source": action.get("source"),
        "intent_id": winner.get("intent_id"),
        "batch_id": action.get("batch_id"),
        "legs": list(action.get("legs", [])),
        "legs_expected": len(action.get("legs", [])),
        "commit_snapshot": commit,
        "meta": winner.get("meta"),
        "exec_basket_price": winner.get("exec_basket_price"),
        "send_time_ms": ts_ms,
        "status": "SENT",
    }
    state["pending_quote_committed"] = state.get(
        "pending_quote_committed", 0
    ) + commit.get("commit_quote_total", 0)
    for asset, amt in (commit.get("commit_base_total_by_asset") or {}).items():
        state["pending_base_committed"] = state.get("pending_base_committed") or {}
        state["pending_base_committed"][asset] = (
            state["pending_base_committed"].get(asset, 0) + amt
        )
    state["arb_last"] = {
        "ts": ts_ms,
        "winner": action.get("source"),
        "loser": "TRB" if action.get("source") == "DCA" else "DCA",
    }
    state["last_tick_ts"] = ts_ms

    return state, {
        "type": "ACTIONS",
        "actions": [action],
        "debug": {
            "bot_id": bot_id,
            "ts": ts_ms,
            "winner": action.get("source"),
            "batch_id": action.get("batch_id"),
            "legs_count": len(action.get("legs", [])),
            "notional_estimate": action.get("notional_estimate"),
        },
    }


class TrdcaProStrategy(Strategy):
    """TRDCA PRO+ strategy. Use tick_snapshot(snapshot, state, config) from orchestrator."""

    strategy_id = "trdca_pro"

    def tick(
        self,
        state: Dict[str, Any],
        config: Any,
        price: float,
        base_balance: float,
        quote_balance: float,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Legacy interface: no-op (orchestrator must call tick_snapshot for TRDCA)."""
        return [], 5.0

    def tick_snapshot(
        self,
        snapshot: Dict[str, Any],
        state: Dict[str, Any],
        config: TrdcaProConfig,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Snapshot-driven tick. Returns (next_state, decision)."""
        return strategy_tick(snapshot, state, config)

    def apply_fills_snapshot(
        self,
        state: Dict[str, Any],
        fills: List[Dict[str, Any]],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply batch fills to state (called by engine when snapshot.fills present)."""
        return apply_fills(state, fills, snapshot)
