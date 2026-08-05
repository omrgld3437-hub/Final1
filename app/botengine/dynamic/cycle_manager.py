"""
Dynamic Mode Cycle Manager — builds and applies the per-cycle snapshot.

Flow per cycle (called from orchestrator BEFORE strategy.tick()):

    1. dynamic_overlay_allowed(state) -> True for every cycle (Tur 1+)
    2. need_recompute(state)  -> True if no snapshot, new cycle_id, or 30m retry due
    3. build_snapshot(adapter, state, cfg)
         a. collect features (klines/spread)
         b. run the same DPS V6 engine as Param Assistant (dynamic_round_start)
         c. on deployable: apply absolute V6/PA plan (grids, trails, alloc, profit)
         d. on non-deployable / R8 Kapalı: do not start round; buy pause + 30m rescan
         e. record into state['dynamic_snapshot']
    4. apply_overlay(cfg, snapshot)  -> mutate cfg in-place for THIS tick only

Snapshot schema (lives at state['dynamic_snapshot']):

    {
        "cycle_id": int,
        "built_at_ms": int,
        "data_fresh": bool,
        "stale_reason": str | None,
        "regime": str,
        "features": {...},
        "raw": {...},                      # V6 BotParams dict
        "pa_plan": {...},                  # absolute plan metadata
        "applied": {...},                  # absolute overlay (same shape as PA)
        "reasons": [str, ...],
        "clamps": [str, ...],
        "fallbacks": [str, ...],
        "round_pending": bool,
        "history": [ ... ],                # ring buffer, max 20
    }
"""

from __future__ import annotations
import copy
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic.features import collect_features, MarketFeatures
from app.services.dynamic_param_score.engine import (
    DynamicParamScoreEngine,
    get_engine as get_dps_engine,
)
from app.services.dynamic_param_score.data_collector import (
    collect_market_data,
    default_exchange_constraints,
    portfolio_from_bot_state,
)
from app.services.dynamic_param_score.consumer_policy import build_dynamic_round_context
from app.services.dynamic_param_score.models import BotContext, MarketDataBundle
from app.botengine.dynamic import round_start_policy as rsp

logger = logging.getLogger(__name__)

HISTORY_MAX = 20
# Absolute PA apply starts at Tur 1 (no manual-first-cycle exception).
FIRST_DYNAMIC_CYCLE_ID = 1


def _log_dynamic_event(
    state: Dict[str, Any],
    event_type: str,
    *,
    symbol: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Worker: account_id üzerinden kullanıcı işlem geçmişine yazar."""
    try:
        account_id = int(state.get("account_id") or 0)
        if not account_id:
            return
        from app.db.session import SessionLocal
        from app.services.user_readable_activity_logger import log_for_account

        ctx = dict(context or {})
        if symbol:
            ctx.setdefault("symbol", symbol)
        db = SessionLocal()
        try:
            log_for_account(db, account_id, event_type, context=ctx)
        finally:
            db.close()
    except Exception:
        pass


def dynamic_overlay_allowed(state: Dict[str, Any]) -> bool:
    """Dynamic Mode uses the Param Assistant engine on every cycle, including Tur 1."""
    try:
        cycle_id = int(state.get("cycle_id") or 1)
    except (TypeError, ValueError):
        cycle_id = 1
    return cycle_id >= FIRST_DYNAMIC_CYCLE_ID


def need_recompute(state: Dict[str, Any]) -> bool:
    """True only at tur boundary: new cycle_id, explicit tur-start flag, or blocked-start retry."""
    from app.botengine.dynamic import start_retry_policy as srp
    from app.botengine.dynamic import round_start_policy as rsp

    if srp.need_start_retry(state):
        return True
    if rsp.need_round_start_retry(state):
        return True
    snap = state.get("dynamic_snapshot")
    if state.pop("_dynamic_recompute_needed", False):
        return True
    if not isinstance(snap, dict):
        return True
    cur_cycle = int(state.get("cycle_id") or 1)
    snap_cycle = int(snap.get("cycle_id") or 0)
    return snap_cycle != cur_cycle


def _position_state(state: Dict[str, Any], cfg_dict: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "buy_levels_fired": sum(1 for x in (state.get("buy_grid_fired") or []) if x),
        "max_buy_levels": int(cfg_dict.get("max_buy_levels") or 1),
        "base_balance": float(state.get("base_balance") or 0.0),
        "quote_balance": float(state.get("quote_balance") or 0.0),
        "initial_allocation_done": bool(state.get("initial_allocation_done")),
        # realized durations of recent cycles (days) for the duration-feedback loop
        "recent_cycle_days": _recent_cycle_days(state.get("dynamic_snapshot") or {}),
    }


# Immutable round-multiplier baseline. Grid row counts are structural; every other
# dynamic numeric value is recalculated as baseline x current regime multiplier.
_REFERENCE_OVERRIDE_FIELDS = (
    "sell_grids",
    "buy_grids",
    "base_alloc_pct",
    "quote_alloc_pct",
    "sell_trigger_trailing_pct",
    "buy_trigger_trailing_pct",
    "profit_exit_rise_pct",
    "profit_exit_drop_pct",
    "profit_reentry_drop_pct",
    "profit_reentry_rise_pct",
    "max_base_exposure_frac",
    "max_buy_levels",
    "min_net_profit_rate",
    "rebuy_enabled",
    "resell_enabled",
    "buy_disabled",
    "sell_only_mode",
    "cancel_existing_buy_orders",
    "cancel_existing_sell_orders",
    "intent_execution_enabled",
)


def set_reference(
    state: Dict[str, Any], config: Dict[str, Any], source: str = "param_assistant"
) -> bool:
    """Freeze the immutable dynamic-mode baseline used by every future round."""
    if not isinstance(config, dict):
        return False
    frozen = {
        k: copy.deepcopy(config.get(k))
        for k in _REFERENCE_OVERRIDE_FIELDS
        if k in config and config.get(k) is not None
    }
    if not frozen:
        return False
    frozen["_schema_version"] = 2
    frozen["_source"] = source
    frozen["_frozen_cycle"] = int(state.get("cycle_id") or 0)
    state["_dynamic_reference"] = frozen
    return True


def _reference_cfg(state: Dict[str, Any], cfg_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve and migrate the immutable baseline without reading prior overlays."""
    ref = state.get("_dynamic_reference")
    if not (isinstance(ref, dict) and ref):
        set_reference(state, cfg_dict, source="initial_config")
        ref = state.get("_dynamic_reference")
        if not (isinstance(ref, dict) and ref):
            return copy.deepcopy(cfg_dict)

    # References created by the previous structural-only contract are upgraded
    # once from the pristine config_json supplied by the orchestrator.
    if int(ref.get("_schema_version") or 1) < 2:
        upgraded = copy.deepcopy(ref)
        for key in _REFERENCE_OVERRIDE_FIELDS:
            if key not in upgraded and key in cfg_dict:
                upgraded[key] = copy.deepcopy(cfg_dict.get(key))
        upgraded["_schema_version"] = 2
        state["_dynamic_reference"] = upgraded
        ref = upgraded

    merged = copy.deepcopy(cfg_dict)
    for k in _REFERENCE_OVERRIDE_FIELDS:
        v = ref.get(k)
        if v is not None:
            merged[k] = copy.deepcopy(v)
    return merged


def _reference_info(state: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot'a iliştirilen sizing-referans kaynağı (P0-4).

    `param_assistant` → bot, parametre asistanının optimize ettiği config ile açıldı
    ve dinamik mod bu yapıyı referans alıyor. `initial_config` → manuel/ilk-tur
    config'i donduruldu. Meta, asistan job_id/karar/güven gibi izlenebilirlik
    bilgilerini taşır."""
    ref = state.get("_dynamic_reference")
    src = ref.get("_source") if isinstance(ref, dict) else None
    meta = state.get("_dynamic_reference_meta")
    buy_count = len(ref.get("buy_grids") or []) if isinstance(ref, dict) else 0
    sell_count = len(ref.get("sell_grids") or []) if isinstance(ref, dict) else 0
    return {
        "source": src or "initial_config",
        "schema_version": int(ref.get("_schema_version") or 1)
        if isinstance(ref, dict)
        else 1,
        "grid_counts": {"buy": buy_count, "sell": sell_count},
        "meta": meta if isinstance(meta, dict) else {},
    }


def _recent_cycle_days(prev_snap: Dict[str, Any]) -> Any:
    """Derive recent cycle durations (days) from the snapshot history timestamps.
    Each history entry is stamped at its cycle boundary, so consecutive deltas
    approximate cycle durations — fed to the duration controller (overrun → widen,
    churn → lengthen). Returns the last ≤5 positive durations, or None."""
    hist = (prev_snap or {}).get("history") or []
    ts = [
        h.get("ts")
        for h in hist
        if isinstance(h, dict) and isinstance(h.get("ts"), (int, float))
    ]
    if len(ts) < 2:
        return None
    days = []
    for i in range(1, len(ts)):
        d = (ts[i] - ts[i - 1]) / 86400000.0
        if d > 0:
            days.append(round(d, 4))
    return days[-5:] if days else None


def _build_dps_context(
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    cycle_id: int,
    budget: float,
    *,
    allow_no_trade: bool = True,
    prev_snap: Optional[Dict[str, Any]] = None,
) -> BotContext:
    bot_id = int(state.get("bot_id") or 0) or None
    symbol = str(
        (cfg_dict or {}).get("symbol")
        or state.get("symbol")
        or ""
    ).upper()
    prev = prev_snap if isinstance(prev_snap, dict) else {}
    dps = prev.get("dps") if isinstance(prev.get("dps"), dict) else {}
    tel = dps.get("telemetry") if isinstance(dps.get("telemetry"), dict) else {}
    scen = tel.get("scenario") if isinstance(tel.get("scenario"), dict) else {}
    if not scen:
        scen = (
            tel.get("scenario_identity")
            if isinstance(tel.get("scenario_identity"), dict)
            else {}
        )
    prev_regime = str(prev.get("regime") or scen.get("regime_id") or "") or None
    prev_hint = str(scen.get("sub_profile_hint") or "") or None
    prev_label = str(scen.get("label") or "") or None
    sticky_key = f"dm:{bot_id}:{symbol}" if bot_id and symbol else None
    return build_dynamic_round_context(
        budget_usdt=budget,
        cycle_id=cycle_id,
        bot_id=bot_id,
        last_rebalance_round_id=state.get("_dynamic_last_rebalance_turn"),
        allow_live=True,
        allow_no_trade=allow_no_trade,
        regime_sticky_key=sticky_key,
        prev_regime_id=prev_regime,
        prev_sub_profile_hint=prev_hint,
        prev_regime_label=prev_label,
    )


def _build_absolute_pa_overlay(decision: Any) -> Dict[str, Any]:
    """Same absolute grid/alloc/profit plan Param Assistant would apply to the form."""
    overlay = DynamicParamScoreEngine.decision_to_overlay(decision) or {}
    tel = getattr(decision, "telemetry", None) or {}
    if tel.get("rebalance_plan") is not None:
        overlay["rebalance_plan"] = tel.get("rebalance_plan")
    if tel.get("order_intent_plan") is not None:
        overlay["order_intent_plan"] = tel.get("order_intent_plan")
    if tel.get("target_allocation") is not None:
        overlay["target_allocation"] = tel.get("target_allocation")
    else:
        overlay["target_allocation"] = {
            "source": "param_assistant_absolute",
            "base_alloc_pct": overlay.get("base_alloc_pct"),
            "quote_alloc_pct": overlay.get("quote_alloc_pct"),
        }
    # Live DM must execute oneshot rebalance / order intents from the PA plan.
    overlay["intent_execution_enabled"] = True
    overlay["plan_source"] = "param_assistant_absolute"
    net = tel.get("net_profile") or {}
    overlay["selected_template_key"] = (
        overlay.get("selected_template_key")
        or net.get("key")
        or getattr(decision, "selected_profile_name", None)
    )
    return overlay


def _pause_round_overlay(
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    *,
    reason: str,
) -> Dict[str, Any]:
    """Do not start a trading round — keep prior absolute plan if any, buys off."""
    prev = (state.get("dynamic_snapshot") or {}).get("applied") or {}
    if isinstance(prev, dict) and (
        prev.get("buy_grids") or prev.get("sell_grids") or prev.get("base_alloc_pct") is not None
    ):
        applied = copy.deepcopy(prev)
    else:
        applied = _fallback_from_base(_reference_cfg(state, cfg_dict))
    applied["buy_disabled"] = True
    applied["cancel_existing_buy_orders"] = True
    applied["intent_execution_enabled"] = False
    applied["rebalance_plan"] = None
    applied["order_intent_plan"] = None
    applied["plan_source"] = "round_start_paused"
    applied["pause_reason"] = reason
    return applied


def _sync_target_budgets(
    state: Dict[str, Any],
    applied: Dict[str, Any],
    *,
    price: float,
    cycle_id: int,
    portfolio: Any = None,
) -> None:
    """Make the new allocation effective for this round's order sizing."""
    equity = 0.0
    try:
        equity = float(getattr(portfolio, "total_equity_usdt", 0.0) or 0.0)
    except (TypeError, ValueError):
        equity = 0.0
    if equity <= 0:
        try:
            equity = float(state.get("quote_balance") or 0.0) + float(
                state.get("base_balance") or 0.0
            ) * max(float(price or 0.0), 0.0)
        except (TypeError, ValueError):
            equity = 0.0
    if equity <= 0:
        return
    base_frac = max(0.0, float(applied.get("base_alloc_pct") or 0.0)) / 100.0
    quote_frac = max(0.0, float(applied.get("quote_alloc_pct") or 0.0)) / 100.0
    total = base_frac + quote_frac
    if total <= 0:
        return
    base_frac /= total
    quote_frac /= total
    state["target_budgets"] = {
        "equity_usdt": round(equity, 2),
        "target_quote_usdt": round(equity * quote_frac, 2),
        "target_base_usdt": round(equity * base_frac, 2),
        "cycle_id": int(cycle_id),
        "source": "param_assistant_absolute",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ts_ms": int(time.time() * 1000),
    }


def _resolve_round_decision(
    state: Dict[str, Any],
    decision,
    cfg_dict: Dict[str, Any],
    *,
    cycle_id: int,
    market: MarketDataBundle,
    portfolio,
    constraints,
    ctx: BotContext,
) -> tuple:
    """Map DPS decision → (applied overlay, reasons, fallbacks, pending, pa_meta)."""
    from app.botengine.dynamic import start_retry_policy as srp
    from app.services.dynamic_param_score.result_type import result_type_from_decision

    fallbacks: list = []
    reasons: list = [getattr(decision, "explain", "") or ""]
    tel = getattr(decision, "telemetry", None) or {}
    if not isinstance(tel, dict):
        tel = {}
    pool_meta = tel.get("param_pool") or {}
    if not isinstance(pool_meta, dict):
        pool_meta = {}
    sel_ctx = pool_meta.get("selection_context") or {}
    if not isinstance(sel_ctx, dict):
        sel_ctx = {}
    route_key = str(sel_ctx.get("route_key") or "")
    net = tel.get("net_profile") or {}
    if not isinstance(net, dict):
        net = {}
    profile_key = str(
        net.get("key") or getattr(decision, "selected_profile_name", None) or ""
    )
    result_type = result_type_from_decision(decision, bot_context=ctx)
    deployable = bool(decision.deployable and decision.params)
    pa_meta = {
        "source": "param_assistant_absolute",
        "profile_key": profile_key,
        "deployable": deployable,
        "result_type": result_type,
        "headline": net.get("headline"),
    }

    if deployable:
        srp.on_successful_deploy(state)
        rsp.on_deployable_round_start(state)
        applied = _build_absolute_pa_overlay(decision)
        reasons.append(
            f"Parametre Asistanı planı birebir uygulandı: {profile_key or decision.selected_profile_name or '—'}"
        )
        _log_dynamic_event(
            state,
            "DYNAMIC_TURN_STARTED",
            symbol=str((cfg_dict.get("symbol") or "")).upper(),
            context={
                "symbol": str((cfg_dict.get("symbol") or "")).upper(),
                "profile_key": profile_key,
            },
        )
        return applied, reasons, fallbacks, False, pa_meta

    # Non-deployable (R8 Kapalı, hard-block, WAIT/NO_TRADE, …): do not open the round.
    codes = rsp.blocking_codes(decision) + list(decision.blocking_reasons or [])
    if not codes:
        codes = [str(result_type or "NON_DEPLOYABLE").upper()]
    entry = srp.mark_start_blocked(
        state,
        cycle_id=cycle_id,
        result_type=result_type,
        deployable=deployable,
        block_reasons=codes,
        route_key=route_key,
        risk_state=str(decision.risk_state or ""),
        fixed_retry_minutes=srp.NON_DEPLOYABLE_RETRY_MINUTES,
    )
    applied = _pause_round_overlay(
        state,
        cfg_dict,
        reason=str(entry.get("last_block_reason") or "NON_DEPLOYABLE"),
    )
    fallbacks = ["dps_non_deployable_round_paused"]
    reasons.extend(decision.blocking_reasons or [])
    reasons.append(srp.START_BLOCKED_RETRY_PENDING)
    after_min = int(entry.get("retry_after_minutes") or srp.NON_DEPLOYABLE_RETRY_MINUTES)
    pa_meta["retry_after_minutes"] = after_min
    pa_meta["next_retry_at_ms"] = entry.get("next_retry_at_ms")
    _log_dynamic_event(
        state,
        "DYNAMIC_TURN_BLOCKED",
        symbol=str((cfg_dict.get("symbol") or "")).upper(),
        context={
            "symbol": str((cfg_dict.get("symbol") or "")).upper(),
            "technical_reason": entry.get("last_block_reason"),
            "minutes": after_min,
            "profile_key": profile_key,
        },
    )
    return applied, reasons, fallbacks, True, pa_meta


async def build_snapshot(
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    price: float,
) -> Dict[str, Any]:
    """
    Build a new snapshot. Pure async function — no DB writes, no order side
    effects. Returns the snapshot dict; caller is responsible for persisting
    it into state['dynamic_snapshot'] and saving state.

    On data-stale: returns a snapshot with data_fresh=False AND falls back to
    the previous snapshot's applied params (or the base_cfg if none) so the
    cycle has SOMETHING safe to run on.
    """
    cycle_id = int(state.get("cycle_id") or 1)
    symbol = (cfg_dict.get("symbol") or "").upper()
    prev_snap = state.get("dynamic_snapshot") or {}
    prev_regime_state = prev_snap.get("regime_state")
    prev_applied = prev_snap.get("applied") or {}
    reference_cfg = _reference_cfg(state, cfg_dict)

    # 1. Features
    features: MarketFeatures = await collect_features(symbol, price)

    # 2. Stale path: re-use previous snapshot's applied params, just bump cycle
    if not features.data_fresh:
        logger.info(
            "DYN_STALE bot_id=%s symbol=%s cycle=%s err=%s — 15m retry scheduled",
            state.get("bot_id"),
            symbol,
            cycle_id,
            features.error,
        )
        rsp.mark_pending(
            state,
            cycle_id=cycle_id,
            reason=str(features.error or "DATA_STALE"),
            codes=["DATA_STALE"],
        )
        applied = copy.deepcopy(prev_applied) if isinstance(prev_applied, dict) else {}
        reference_buy_count = len(reference_cfg.get("buy_grids") or [])
        reference_sell_count = len(reference_cfg.get("sell_grids") or [])
        if (
            not applied
            or len(applied.get("buy_grids") or []) != reference_buy_count
            or len(applied.get("sell_grids") or []) != reference_sell_count
        ):
            applied = _fallback_from_base(reference_cfg)
        applied["buy_disabled"] = True
        applied["cancel_existing_buy_orders"] = True
        applied["intent_execution_enabled"] = False
        applied["rebalance_plan"] = None
        applied["order_intent_plan"] = None
        pa_plan = {
            "source": "data_stale_pause",
            "stale_reuse": True,
            "grid_counts": {
                "buy_reference": reference_buy_count,
                "buy_applied": len(applied.get("buy_grids") or []),
                "sell_reference": reference_sell_count,
                "sell_applied": len(applied.get("sell_grids") or []),
            },
        }
        snap = {
            "cycle_id": cycle_id,
            "built_at_ms": int(time.time() * 1000),
            "data_fresh": False,
            "stale_reason": features.error,
            "regime": (prev_snap.get("regime") or reg.UNKNOWN),
            "regime_state": prev_regime_state,
            "features": features.to_dict(),
            "raw": None,
            "baseline": _fallback_from_base(reference_cfg),
            "applied": applied,
            "pa_plan": pa_plan,
            "multiplier": {},  # legacy key retained empty for older UI readers
            "reasons": [
                f"DATA_STALE: {features.error} — tur açılmadı, "
                f"{int(rsp.ROUND_START_RETRY_SEC / 60)}dk sonra yeniden denenecek"
            ],
            "clamps": ["DATA_STALE"],
            "fallbacks": ["data_stale_pending_retry"],
            "round_pending": True,
            "reference": _reference_info(state),
            "history": _push_history(
                prev_snap.get("history") or [],
                {
                    "cycle_id": cycle_id,
                    "regime": prev_snap.get("regime") or reg.UNKNOWN,
                    "stale": True,
                    "ts": int(time.time() * 1000),
                },
            ),
        }
        return snap

    # 3–6. Dynamic Param Score Engine (round-independent; no prev-param smoothing)
    budget = float(cfg_dict.get("initial_capital_usdt") or cfg_dict.get("budget_usdt") or 0)
    if budget <= 0:
        budget = float(state.get("quote_balance") or 0) + float(state.get("base_balance") or 0) * price

    market: MarketDataBundle = await collect_market_data(symbol)
    if price > 0:
        market.ticker_price = price

    portfolio = portfolio_from_bot_state(state, market.ticker_price or price)
    if portfolio.total_equity_usdt <= 0 and budget > 0:
        portfolio.total_equity_usdt = budget
        portfolio.quote_value_usdt = budget

    constraints = default_exchange_constraints(symbol)
    ctx = _build_dps_context(
        state,
        cfg_dict,
        cycle_id,
        budget or portfolio.total_equity_usdt,
        prev_snap=prev_snap if isinstance(prev_snap, dict) else None,
    )

    decision = get_dps_engine().calculate_decision(
        symbol=symbol,
        market_data=market,
        portfolio_state=portfolio,
        exchange_constraints=constraints,
        bot_context=ctx,
    )

    applied, reasons, fallbacks, round_pending, pa_meta = _resolve_round_decision(
        state,
        decision,
        cfg_dict,
        cycle_id=cycle_id,
        market=market,
        portfolio=portfolio,
        constraints=constraints,
        ctx=ctx,
    )
    state.pop("_dynamic_multiplier_current", None)
    if decision.deployable and not round_pending:
        _sync_target_budgets(
            state,
            applied,
            price=market.ticker_price or price,
            cycle_id=cycle_id,
            portfolio=portfolio,
        )
    clamps = [g.reason_code for g in decision.safety_gates if not g.passed]
    from app.botengine.dynamic import start_retry_policy as srp
    from app.services.dynamic_param_score.result_type import result_type_from_decision
    from app.botengine.dynamic import churn_policy as cp

    result_type = result_type_from_decision(decision, bot_context=ctx)
    prev_applied = prev_snap.get("applied") or {}
    rb_plan = applied.get("rebalance_plan") or {}
    sym = str((cfg_dict.get("symbol") or "")).upper()
    _log_dynamic_event(
        state,
        "DYNAMIC_TURN_ANALYSIS",
        symbol=sym,
        context={"symbol": sym},
    )
    if rb_plan:
        cur_b = rb_plan.get("current_base_frac")
        tgt_b = rb_plan.get("target_base_frac")
        cur_alloc = (
            f"%{int(float(cur_b or 0) * 100)}/%{int((1 - float(cur_b or 0)) * 100)}"
            if cur_b is not None
            else ""
        )
        tgt_alloc = (
            f"%{int(float(tgt_b or 0) * 100)}/%{int((1 - float(tgt_b or 0)) * 100)}"
            if tgt_b is not None
            else ""
        )
        rb_dec = str(rb_plan.get("rebalance_decision") or "SKIP").upper()
        skip_reason = str(rb_plan.get("rebalance_skipped_reason") or "")
        if rb_dec == "EXECUTE":
            side = str(rb_plan.get("rebalance_side") or "SELL").upper()
            _log_dynamic_event(
                state,
                "REBALANCE_EXECUTED",
                symbol=sym,
                context={"symbol": sym, "side": side},
            )
        elif rb_dec == "DEFER" or skip_reason == "REBALANCE_SAFETY_BLOCKED":
            _log_dynamic_event(
                state,
                "REBALANCE_DEFERRED",
                symbol=sym,
                context={"symbol": sym, "technical_reason": skip_reason or "REBALANCE_SAFETY_BLOCKED"},
            )
        elif skip_reason == "SMALL_BASE_QUOTE_DELTA":
            _log_dynamic_event(
                state,
                "REBALANCE_SKIPPED",
                symbol=sym,
                context={"symbol": sym, "current_alloc": cur_alloc, "target_alloc": tgt_alloc},
            )
        elif cur_alloc and tgt_alloc:
            _log_dynamic_event(
                state,
                "REBALANCE_EVALUATED",
                symbol=sym,
                context={"symbol": sym, "current_alloc": cur_alloc, "target_alloc": tgt_alloc},
            )
    preserve, churn_reasons = cp.should_preserve_orders(
        prev_applied,
        applied,
        rebalance_plan=rb_plan,
        risk_state_changed=str(prev_snap.get("dps", {}).get("risk_state") or "") != str(decision.risk_state),
        route_changed=str((prev_snap.get("dps") or {}).get("route_key") or "") != str(
            ((decision.telemetry or {}).get("param_pool") or {}).get("selection_context", {}).get("route_key") or ""
        ),
        spread_unsafe=decision.regime_tag == "SPREAD_UNSAFE",
        dump_risk=decision.regime_tag == "DUMP_RISK",
        exposure_breach=bool((decision.telemetry or {}).get("exposure_hard_cap_breach")),
    )
    if preserve and not applied.get("buy_disabled"):
        applied["cancel_existing_buy_orders"] = False
        applied["cancel_existing_sell_orders"] = False

    snap = {
        "cycle_id": cycle_id,
        "built_at_ms": int(time.time() * 1000),
        "data_fresh": True,
        "stale_reason": None,
        "regime": decision.regime_tag,
        "regime_confidence": round(decision.confidence_score / 100.0, 4),
        "regime_state": prev_regime_state,
        "stance": {"source": "dynamic_param_score", "final_action": decision.final_action},
        "duration": None,
        "dps": {
            "decision_id": decision.decision_id,
            "param_score": decision.param_score,
            "risk_state": decision.risk_state,
            "deployable": decision.deployable,
            "result_type": result_type,
            "profile": decision.selected_profile_name,
            "profile_key": pa_meta.get("profile_key"),
            "route_key": (
                ((decision.telemetry or {}).get("param_pool") or {}).get("selection_context") or {}
            ).get("route_key"),
            "telemetry": decision.telemetry,
            "rebalance_plan": (decision.telemetry or {}).get("rebalance_plan"),
            "order_intent_plan": (decision.telemetry or {}).get("order_intent_plan"),
        },
        "start_watchlist": srp.get_watchlist(state),
        "churn_preserve_orders": preserve,
        "churn_reasons": churn_reasons,
        "features": features.to_dict(),
        "raw": decision.params.to_dict() if decision.params else None,
        "baseline": _fallback_from_base(reference_cfg),
        "applied": applied,
        "pa_plan": pa_meta,
        "multiplier": {},  # legacy key retained empty for older UI readers
        "reasons": reasons,
        "clamps": clamps,
        "fallbacks": fallbacks,
        "round_pending": round_pending,
        "reference": _reference_info(state),
        "history": _push_history(
            prev_snap.get("history") or [],
            {
                "cycle_id": cycle_id,
                "regime": decision.regime_tag,
                "param_score": decision.param_score,
                "final_action": decision.final_action,
                "profile_key": pa_meta.get("profile_key"),
                "applied_base_alloc_pct": applied.get("base_alloc_pct"),
                "plan_source": applied.get("plan_source"),
                "stale": False,
                "pending": round_pending,
                "ts": int(time.time() * 1000),
            },
        ),
    }
    return snap


def _no_trade_overlay(cfg_dict: Dict[str, Any], decision) -> Dict[str, Any]:
    """Safety overlay that pauses buying without changing frozen grid row counts."""
    base = _fallback_from_base(cfg_dict)
    fa = str(getattr(decision, "final_action", "") or "")
    deploy = bool(getattr(decision, "deployable", False))
    params = getattr(decision, "params", None)

    if fa in ("NO_TRADE", "WAIT") or not deploy:
        base["buy_disabled"] = True
        base["cancel_existing_buy_orders"] = True
        base["intent_execution_enabled"] = False
    elif params and getattr(params, "emergency_no_buy", False):
        base["buy_disabled"] = True
        base["cancel_existing_buy_orders"] = True

    base["clamps"] = list(getattr(decision, "blocking_reasons", None) or [])
    base["fallbacks"] = ["dps_safe_pause_grid_count_preserved"]
    return base


def _push_history(existing: Any, entry: Dict[str, Any]) -> list:
    out = list(existing or [])
    out.append(entry)
    if len(out) > HISTORY_MAX:
        out = out[-HISTORY_MAX:]
    return out


def _fallback_from_base(cfg_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror the immutable baseline without introducing dynamic defaults."""
    def number(key: str, default: float) -> float:
        value = cfg_dict.get(key)
        return float(default if value is None else value)

    return {
        "base_alloc_pct": number("base_alloc_pct", 50.0),
        "quote_alloc_pct": number("quote_alloc_pct", 50.0),
        "sell_grids": copy.deepcopy(list(cfg_dict.get("sell_grids") or [])),
        "buy_grids": copy.deepcopy(list(cfg_dict.get("buy_grids") or [])),
        "sell_trigger_trailing_pct": number("sell_trigger_trailing_pct", 0.3),
        "buy_trigger_trailing_pct": number("buy_trigger_trailing_pct", 0.3),
        "profit_exit_rise_pct": number("profit_exit_rise_pct", 1.0),
        "profit_exit_drop_pct": number("profit_exit_drop_pct", 0.3),
        "profit_reentry_drop_pct": number("profit_reentry_drop_pct", 1.0),
        "profit_reentry_rise_pct": number("profit_reentry_rise_pct", 0.3),
        "max_base_exposure_frac": number("max_base_exposure_frac", 1.0),
        "max_buy_levels": int(
            cfg_dict.get("max_buy_levels")
            if cfg_dict.get("max_buy_levels") is not None
            else len(cfg_dict.get("buy_grids") or [])
        ),
        "min_net_profit_rate": number("min_net_profit_rate", 0.0),
        "rebuy_enabled": bool(cfg_dict.get("rebuy_enabled", True)),
        "resell_enabled": bool(cfg_dict.get("resell_enabled", True)),
        "buy_disabled": bool(cfg_dict.get("buy_disabled", False)),
        "sell_only_mode": bool(cfg_dict.get("sell_only_mode", False)),
        "cancel_existing_buy_orders": bool(
            cfg_dict.get("cancel_existing_buy_orders", False)
        ),
        "cancel_existing_sell_orders": bool(
            cfg_dict.get("cancel_existing_sell_orders", False)
        ),
        "intent_execution_enabled": bool(
            cfg_dict.get("intent_execution_enabled", False)
        ),
        "clamps": [],
        "fallbacks": ["no_prev_snapshot_falling_back_to_manual"],
    }


# ---- Apply overlay onto a live DcaGridTrailingConfig -----------------------


# Fields we are allowed to overlay. We never overlay safety / structural fields.
_OVERLAY_FIELDS = (
    "base_alloc_pct",
    "quote_alloc_pct",
    "sell_grids",
    "buy_grids",
    "sell_trigger_trailing_pct",
    "buy_trigger_trailing_pct",
    "profit_exit_rise_pct",
    "profit_exit_drop_pct",
    "profit_reentry_drop_pct",
    "profit_reentry_rise_pct",
    "max_base_exposure_frac",
    "max_buy_levels",
    "min_net_profit_rate",
    "rebuy_enabled",
    "resell_enabled",
    "buy_disabled",
    "sell_only_mode",
    "cancel_existing_buy_orders",
    "cancel_existing_sell_orders",
    "selected_template_key",
    "pool_version",
    "final_action",
    "management_mode",
    "rebalance_plan",
    "order_intent_plan",
    "target_allocation",
    "intent_execution_enabled",
)


def apply_overlay(cfg: Any, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mutate cfg in-place using snapshot['applied']. Returns a dict of
    {field: (old, new)} for logging. cfg is the live DcaGridTrailingConfig
    object — strategy reads attributes off it.

    SAFETY: daily_loss_limit_usd, dynamic_mode, paper_mode, symbol,
    initial_capital_usdt, fees, tick_interval_ms, max_orders_per_minute and
    similar runtime safety fields are never overlaid. Grid counts / trails /
    alloc come from the absolute Param Assistant plan for this cycle.
    """
    applied = snapshot.get("applied") or {}
    diffs: Dict[str, Any] = {}
    for f in _OVERLAY_FIELDS:
        if f not in applied:
            continue
        new_v = applied[f]
        old_v = getattr(cfg, f, None)
        try:
            setattr(cfg, f, new_v)
            diffs[f] = {"old": old_v, "new": new_v}
        except AttributeError:
            # Field doesn't exist on this cfg variant — skip silently.
            pass
    return diffs
