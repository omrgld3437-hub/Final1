"""
Dynamic Mode Cycle Manager — builds and applies the per-cycle snapshot.

Flow per cycle (called from orchestrator BEFORE strategy.tick()):

    1. dynamic_overlay_allowed(state) -> False on cycle 1 (first tur manual)
    2. need_recompute(state)  -> True if no snapshot, or _dynamic_recompute_needed flag set
    2. build_snapshot(adapter, state, cfg)
         a. collect features (klines/spread)
         b. obtain V6 regime, direction and safety telemetry
         c. freeze/resolve the bot's immutable initial reference
         d. calculate independent up/down regime multipliers
         e. apply reference x multiplier and safety guards
         f. record into state['dynamic_snapshot']
    3. apply_overlay(cfg, snapshot)  -> mutate cfg in-place for THIS tick only

Snapshot schema (lives at state['dynamic_snapshot']):

    {
        "cycle_id": int,
        "built_at_ms": int,
        "data_fresh": bool,
        "stale_reason": str | None,
        "regime": str,
        "regime_state": {"current","candidate","candidate_streak"},
        "features": {...},                 # MarketFeatures.to_dict()
        "raw": {...},                      # V6 candidate (diagnostic only)
        "baseline": {...},                 # immutable initial reference
        "multiplier": {...},               # direction/confidence/factors
        "applied": {...},                  # baseline x multiplier
        "reasons": [str, ...],             # human-readable explanations
        "clamps": [str, ...],
        "fallbacks": [str, ...],
        "history": [ {cycle_id, regime, atr_pct_5m, ...} ],  # ring buffer, max 20
    }

History gives the operator a "last 20 cycles" view to spot oscillation /
drift without external tooling.
"""

from __future__ import annotations
import copy
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic.features import collect_features, MarketFeatures
from app.botengine.dynamic.regime_multiplier import build_regime_multiplier_overlay
from app.services.dynamic_param_score.engine import get_engine as get_dps_engine
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
FIRST_DYNAMIC_CYCLE_ID = 2


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
    """Dynamic overlay starts after the first manual cycle is complete."""
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
) -> BotContext:
    return build_dynamic_round_context(
        budget_usdt=budget,
        cycle_id=cycle_id,
        bot_id=int(state.get("bot_id") or 0) or None,
        last_rebalance_round_id=state.get("_dynamic_last_rebalance_turn"),
        allow_live=True,
        allow_no_trade=allow_no_trade,
    )


def _build_round_multiplier_overlay(
    state: Dict[str, Any],
    decision: Any,
    cfg_dict: Dict[str, Any],
    *,
    constraints: Any,
    portfolio: Any,
) -> Dict[str, Any]:
    """Apply V6 regime signals to the frozen initial config, never to last round."""
    reference_cfg = _reference_cfg(state, cfg_dict)
    applied, multiplier_meta = build_regime_multiplier_overlay(
        reference_cfg,
        decision,
        constraints=constraints,
        portfolio=portfolio,
    )
    telemetry = getattr(decision, "telemetry", None) or {}
    applied["target_allocation"] = {
        "source": "regime_multiplier",
        "base_alloc_pct": applied.get("base_alloc_pct"),
        "quote_alloc_pct": applied.get("quote_alloc_pct"),
    }
    # V6's absolute-profile order plan is deliberately not executed here. Its
    # regime/safety signals are consumed, while all sizing stays reference-based.
    applied["rebalance_plan"] = None
    applied["order_intent_plan"] = None
    applied["intent_execution_enabled"] = False
    multiplier_meta["candidate_v6_rebalance_plan"] = telemetry.get("rebalance_plan")
    state["_dynamic_multiplier_current"] = multiplier_meta
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
        "source": "dynamic_regime_multiplier",
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
    """Map DPS decision → (applied overlay, reasons, fallbacks, pending)."""
    from app.botengine.dynamic import start_retry_policy as srp
    from app.services.dynamic_param_score.result_type import result_type_from_decision

    fallbacks: list = []
    reasons: list = [decision.explain]
    pool_meta = (decision.telemetry or {}).get("param_pool") or {}
    sel_ctx = pool_meta.get("selection_context") or {}
    route_key = str(sel_ctx.get("route_key") or "")
    result_type = result_type_from_decision(decision, bot_context=ctx)
    deployable = bool(decision.deployable and decision.params)

    if deployable:
        srp.on_successful_deploy(state)
        rsp.on_deployable_round_start(state)
        applied = _build_round_multiplier_overlay(
            state,
            decision,
            cfg_dict,
            constraints=constraints,
            portfolio=portfolio,
        )
        multiplier = state.get("_dynamic_multiplier_current") or {}
        scores = multiplier.get("direction_scores") or {}
        factors = multiplier.get("multipliers") or {}
        reasons.append(
            "Başlangıç referansı × rejim çarpanı: "
            f"{multiplier.get('regime') or 'UNKNOWN'} · "
            f"yukarı {float(scores.get('up') or 0) * 100:.0f}% / "
            f"aşağı {float(scores.get('down') or 0) * 100:.0f}% · "
            f"alış mesafe ×{float(factors.get('buy_distance') or 1):.2f}, "
            f"satış mesafe ×{float(factors.get('sell_distance') or 1):.2f}"
        )
        _log_dynamic_event(
            state,
            "DYNAMIC_TURN_STARTED",
            symbol=str((cfg_dict.get("symbol") or "")).upper(),
            context={"symbol": str((cfg_dict.get("symbol") or "")).upper()},
        )
        return applied, reasons, fallbacks, False

    if rsp.is_hard_safety_block(decision):
        codes = rsp.blocking_codes(decision)
        srp.mark_start_blocked(
            state,
            cycle_id=cycle_id,
            result_type=result_type,
            deployable=deployable,
            block_reasons=codes,
            route_key=route_key,
            risk_state=str(decision.risk_state or ""),
        )
        applied = _build_round_multiplier_overlay(
            state,
            decision,
            cfg_dict,
            constraints=constraints,
            portfolio=portfolio,
        )
        applied["buy_disabled"] = True
        applied["cancel_existing_buy_orders"] = True
        applied["intent_execution_enabled"] = False
        fallbacks = ["dps_hard_safety_pending"]
        reasons.extend(decision.blocking_reasons or [])
        primary = codes[0] if codes else "START_BLOCKED_RETRY_PENDING"
        _log_dynamic_event(
            state,
            "DYNAMIC_TURN_BLOCKED",
            symbol=str((cfg_dict.get("symbol") or "")).upper(),
            context={
                "symbol": str((cfg_dict.get("symbol") or "")).upper(),
                "technical_reason": primary,
            },
        )
        return applied, reasons, fallbacks, True

    if srp.is_turn_start_blocked(result_type=result_type, deployable=deployable):
        codes = rsp.blocking_codes(decision) + list(decision.blocking_reasons or [])
        entry = srp.mark_start_blocked(
            state,
            cycle_id=cycle_id,
            result_type=result_type,
            deployable=deployable,
            block_reasons=codes,
            route_key=route_key,
            risk_state=str(decision.risk_state or ""),
        )
        applied = _build_round_multiplier_overlay(
            state,
            decision,
            cfg_dict,
            constraints=constraints,
            portfolio=portfolio,
        )
        applied["buy_disabled"] = True
        applied["cancel_existing_buy_orders"] = True
        applied["intent_execution_enabled"] = False
        fallbacks = ["start_blocked_retry_pending"]
        reasons.append(srp.START_BLOCKED_RETRY_PENDING)
        after_min = int((entry.get("retry_after_minutes") or 10))
        _log_dynamic_event(
            state,
            "RETRY_PENDING",
            symbol=str((cfg_dict.get("symbol") or "")).upper(),
            context={
                "symbol": str((cfg_dict.get("symbol") or "")).upper(),
                "minutes": after_min,
                "technical_reason": entry.get("last_block_reason"),
            },
        )
        return applied, reasons, fallbacks, True

    # Non-deployable but not blocked — show recommendation only, no auto deploy
    applied = _build_round_multiplier_overlay(
        state,
        decision,
        cfg_dict,
        constraints=constraints,
        portfolio=portfolio,
    )
    applied["buy_disabled"] = True
    applied["cancel_existing_buy_orders"] = True
    applied["intent_execution_enabled"] = False
    fallbacks = ["dps_non_deployable_reference"]
    reasons.append(f"result_type={result_type}")
    return applied, reasons, fallbacks, False


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
        stale_multiplier = copy.deepcopy(prev_snap.get("multiplier") or {})
        stale_multiplier["stale_reuse"] = True
        stale_multiplier["grid_count_invariant"] = {
            "buy_initial": reference_buy_count,
            "buy_applied": len(applied.get("buy_grids") or []),
            "sell_initial": reference_sell_count,
            "sell_applied": len(applied.get("sell_grids") or []),
            "preserved": (
                len(applied.get("buy_grids") or []) == reference_buy_count
                and len(applied.get("sell_grids") or []) == reference_sell_count
            ),
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
            "multiplier": stale_multiplier,
            "reasons": [
                f"DATA_STALE: {features.error} — acil durum, {int(rsp.ROUND_START_RETRY_SEC / 60)}dk sonra yeniden denenecek"
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
    ctx = _build_dps_context(state, cfg_dict, cycle_id, budget or portfolio.total_equity_usdt)

    decision = get_dps_engine().calculate_decision(
        symbol=symbol,
        market_data=market,
        portfolio_state=portfolio,
        exchange_constraints=constraints,
        bot_context=ctx,
    )

    applied, reasons, fallbacks, round_pending = _resolve_round_decision(
        state,
        decision,
        cfg_dict,
        cycle_id=cycle_id,
        market=market,
        portfolio=portfolio,
        constraints=constraints,
        ctx=ctx,
    )
    multiplier_meta = state.pop("_dynamic_multiplier_current", None) or {}
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
            "route_key": (
                ((decision.telemetry or {}).get("param_pool") or {}).get("selection_context") or {}
            ).get("route_key"),
            "telemetry": decision.telemetry,
            "candidate_v6_rebalance_plan": (decision.telemetry or {}).get("rebalance_plan"),
            "multiplier": multiplier_meta,
        },
        "start_watchlist": srp.get_watchlist(state),
        "churn_preserve_orders": preserve,
        "churn_reasons": churn_reasons,
        "features": features.to_dict(),
        "raw": decision.params.to_dict() if decision.params else None,
        "baseline": _fallback_from_base(reference_cfg),
        "applied": applied,
        "multiplier": multiplier_meta,
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
                "applied_base_alloc_pct": applied.get("base_alloc_pct"),
                "buy_distance_factor": (multiplier_meta.get("multipliers") or {}).get(
                    "buy_distance"
                ),
                "sell_distance_factor": (multiplier_meta.get("multipliers") or {}).get(
                    "sell_distance"
                ),
                "stale": False,
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
    similar runtime safety fields are never overlaid. max_buy_levels is copied
    from the immutable baseline only, so dynamic mode cannot alter grid count.
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
