"""
Dynamic Mode Cycle Manager — builds and applies the per-cycle snapshot.

Flow per cycle (called from orchestrator BEFORE strategy.tick()):

    1. dynamic_overlay_allowed(state) -> False on cycle 1 (first tur manual)
    2. need_recompute(state)  -> True if no snapshot, or _dynamic_recompute_needed flag set
    2. build_snapshot(adapter, state, cfg)
         a. collect features (klines/spread)
         b. classify regime (hysteresis vs prev snapshot)
         c. suggest params (strategy engine)
         d. smooth vs prev applied
         e. apply risk engine (clamp + rate limit)
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
        "raw": {...},                      # ParamSuggestion.to_dict()
        "applied": {...},                  # ClampedParams.to_dict()
        "reasons": [str, ...],             # human-readable explanations
        "clamps": [str, ...],
        "fallbacks": [str, ...],
        "history": [ {cycle_id, regime, atr_pct_5m, ...} ],  # ring buffer, max 20
    }

History gives the operator a "last 20 cycles" view to spot oscillation /
drift without external tooling.
"""

from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic.features import collect_features, MarketFeatures
from app.services.dynamic_param_score.engine import get_engine as get_dps_engine
from app.services.dynamic_param_score.data_collector import (
    collect_market_data,
    default_exchange_constraints,
    portfolio_from_bot_state,
)
from app.services.dynamic_param_score.consumer_policy import build_dynamic_round_context
from app.services.dynamic_param_score.safe_overlay import build_data_stale_overlay
from app.services.dynamic_param_score.models import BotContext, MarketDataBundle, FinalAction
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


# Fields the param-assistant REFERENCE may override on top of the bot's live cfg.
# Everything else (fees, symbol, max_buy_levels, safety) stays from the bot cfg.
_REFERENCE_OVERRIDE_FIELDS = (
    "sell_grids",
    "buy_grids",
    "base_alloc_pct",
    "quote_alloc_pct",
)


def set_reference(
    state: Dict[str, Any], config: Dict[str, Any], source: str = "param_assistant"
) -> bool:
    """Explicitly set the dynamic-mode sizing REFERENCE — e.g. when the param
    assistant's optimized config is applied to the bot. Only the STRUCTURAL fields
    (grid count + per-level qty distribution + alloc split) are stored; the
    DISTANCES (grid step / take-profit / trailing) are recomputed every cycle by
    the duration model from the current volatility. Returns True if stored."""
    if not isinstance(config, dict):
        return False
    frozen = {
        k: config.get(k) for k in _REFERENCE_OVERRIDE_FIELDS if config.get(k) is not None
    }
    if not frozen:
        return False
    frozen["_source"] = source
    frozen["_frozen_cycle"] = int(state.get("cycle_id") or 0)
    state["_dynamic_reference"] = frozen
    return True


def _reference_cfg(state: Dict[str, Any], cfg_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the sizing REFERENCE = "param asistanının yaptığı ilk kodlar".

    The reference is the baseline STRUCTURE (grid count, per-level qty
    distribution, alloc split) that every new cycle computes its duration-targeted
    distances from. Resolution order:
      1. An explicit reference at state['_dynamic_reference'] (set by the param
         assistant / API) — wins and is robust to later config_json edits.
      2. Otherwise FREEZE the pristine INITIAL config (config_json, never overlaid)
         as the reference on the first dynamic cycle, so the "initial values" are
         pinned even if the user edits the config mid-run.
    Fees / symbol / safety always come from the live cfg, never the reference."""
    ref = state.get("_dynamic_reference")
    if not (isinstance(ref, dict) and ref):
        # Freeze the pristine initial config as the reference (once).
        set_reference(state, cfg_dict, source="initial_config")
        ref = state.get("_dynamic_reference")
        if not (isinstance(ref, dict) and ref):
            return cfg_dict
    merged = dict(cfg_dict)
    for k in _REFERENCE_OVERRIDE_FIELDS:
        v = ref.get(k)
        if v is not None:
            merged[k] = v
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
    return {
        "source": src or "initial_config",
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
    from app.botengine.dynamic import churn_policy as cp
    from app.botengine.dynamic import start_retry_policy as srp
    from app.services.dynamic_param_score.result_type import result_type_from_decision

    engine = get_dps_engine()
    fallbacks: list = []
    reasons: list = [decision.explain]
    pool_meta = (decision.telemetry or {}).get("param_pool") or {}
    sel_ctx = pool_meta.get("selection_context") or {}
    route_key = str(sel_ctx.get("route_key") or "")
    result_type = result_type_from_decision(decision, bot_context=ctx)
    deployable = bool(decision.deployable and decision.params)

    if deployable and result_type in ("deployable_grid", "first_start_buy_only"):
        srp.on_successful_deploy(state)
        rsp.on_deployable_round_start(state)
        applied = engine.decision_to_overlay(decision) or _fallback_from_base(cfg_dict)
        rb = (decision.telemetry or {}).get("rebalance_plan") or {}
        if rb.get("rebalance_decision") == "EXECUTE":
            state["_dynamic_last_rebalance_turn"] = str(cycle_id)
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
        applied = engine.decision_to_overlay(decision) or _no_trade_overlay(cfg_dict, decision)
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
        applied = _no_trade_overlay(cfg_dict, decision)
        applied["buy_disabled"] = True
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
    applied = engine.decision_to_overlay(decision) or _no_trade_overlay(cfg_dict, decision)
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

    # 1. Features
    features: MarketFeatures = await collect_features(symbol, price)

    # 2. Stale path: re-use previous snapshot's applied params, just bump cycle
    if not features.data_fresh:
        from app.services.dynamic_param_score.safe_overlay import build_data_stale_overlay

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
        applied = build_data_stale_overlay(_fallback_from_base(cfg_dict))
        snap = {
            "cycle_id": cycle_id,
            "built_at_ms": int(time.time() * 1000),
            "data_fresh": False,
            "stale_reason": features.error,
            "regime": (prev_snap.get("regime") or reg.UNKNOWN),
            "regime_state": prev_regime_state,
            "features": features.to_dict(),
            "raw": None,
            "applied": applied,
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
    clamps = [g.reason_code for g in decision.safety_gates if not g.passed]
    from app.botengine.dynamic import start_retry_policy as srp
    from app.services.dynamic_param_score.result_type import result_type_from_decision
    from app.botengine.dynamic import churn_policy as cp

    result_type = result_type_from_decision(decision, bot_context=ctx)
    prev_applied = prev_snap.get("applied") or {}
    rb_plan = (decision.telemetry or {}).get("rebalance_plan") or {}
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
    if preserve:
        applied["cancel_existing_buy_orders"] = False
        applied["cancel_existing_sell_orders"] = False

    if decision.deployable and decision.params:
        if decision.final_action == "SELL_MANAGEMENT_ONLY":
            applied.setdefault("buy_grids", [])
            applied["max_buy_levels"] = 0
            applied["buy_disabled"] = True
            applied["sell_only_mode"] = True
            applied["buy_trigger_trailing_pct"] = 0.0
            applied["profit_reentry_drop_pct"] = 0.0
            applied["profit_reentry_rise_pct"] = 0.0

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
            "rebalance_plan": (decision.telemetry or {}).get("rebalance_plan"),
        },
        "start_watchlist": srp.get_watchlist(state),
        "churn_preserve_orders": preserve,
        "churn_reasons": churn_reasons,
        "features": features.to_dict(),
        "raw": decision.params.to_dict() if decision.params else None,
        "applied": applied,
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
                "stale": False,
                "ts": int(time.time() * 1000),
            },
        ),
    }
    return snap


def _no_trade_overlay(cfg_dict: Dict[str, Any], decision) -> Dict[str, Any]:
    """When DPS says NO_TRADE/WAIT: clear buy side; never preserve stale manual buy grids."""
    base = _fallback_from_base(cfg_dict)
    fa = str(getattr(decision, "final_action", "") or "")
    deploy = bool(getattr(decision, "deployable", False))
    params = getattr(decision, "params", None)

    if fa in ("NO_TRADE", "WAIT") or not deploy:
        base["buy_grids"] = []
        base["buy_trigger_trailing_pct"] = 0.0
        base["profit_reentry_drop_pct"] = 0.0
        base["profit_reentry_rise_pct"] = 0.0
        base["max_buy_levels"] = 0
        if fa == "NO_TRADE":
            base["sell_grids"] = []
    elif params and getattr(params, "emergency_no_buy", False):
        base["buy_grids"] = []
        base["buy_trigger_trailing_pct"] = 0.0
        base["profit_reentry_drop_pct"] = 0.0
        base["profit_reentry_rise_pct"] = 0.0
        base["max_buy_levels"] = max(int(getattr(params, "buy_grid_count", 0) or 0), 0)

    if params:
        if int(getattr(params, "buy_grid_count", 0) or 0) == 0:
            base["buy_grids"] = []
            base["max_buy_levels"] = 0
        if int(getattr(params, "sell_grid_count", 0) or 0) == 0:
            base["sell_grids"] = []
        base["max_base_exposure_frac"] = round(
            float(getattr(params, "max_base_exposure_frac", 0) or 1.0), 4
        )
        base["min_net_profit_rate"] = round(
            float(getattr(params, "min_cycle_profit_after_fee_pct", 0) or 0) / 100.0, 6
        )

    base["clamps"] = list(getattr(decision, "blocking_reasons", None) or [])
    base["fallbacks"] = ["dps_no_trade"]
    return base


def _push_history(existing: Any, entry: Dict[str, Any]) -> list:
    out = list(existing or [])
    out.append(entry)
    if len(out) > HISTORY_MAX:
        out = out[-HISTORY_MAX:]
    return out


def _fallback_from_base(cfg_dict: Dict[str, Any]) -> Dict[str, Any]:
    """If no previous snapshot exists and data is stale, just mirror manual cfg."""
    return {
        "base_alloc_pct": float(cfg_dict.get("base_alloc_pct") or 50.0),
        "quote_alloc_pct": float(cfg_dict.get("quote_alloc_pct") or 50.0),
        "sell_grids": list(cfg_dict.get("sell_grids") or []),
        "buy_grids": list(cfg_dict.get("buy_grids") or []),
        "sell_trigger_trailing_pct": float(
            cfg_dict.get("sell_trigger_trailing_pct") or 0.3
        ),
        "buy_trigger_trailing_pct": float(
            cfg_dict.get("buy_trigger_trailing_pct") or 0.3
        ),
        "profit_exit_rise_pct": float(cfg_dict.get("profit_exit_rise_pct") or 1.0),
        "profit_exit_drop_pct": float(cfg_dict.get("profit_exit_drop_pct") or 0.3),
        "profit_reentry_drop_pct": float(
            cfg_dict.get("profit_reentry_drop_pct") or 1.0
        ),
        "profit_reentry_rise_pct": float(
            cfg_dict.get("profit_reentry_rise_pct") or 0.3
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

    SAFETY: max_buy_levels, daily_loss_limit_usd, dynamic_mode, paper_mode,
    symbol, initial_capital_usdt, fees, tick_interval_ms, max_orders_per_minute
    and similar structural / safety fields are NEVER overlaid.
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
