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
from typing import Any, Dict

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import strategy_engine as se
from app.botengine.dynamic import risk_engine as risk
from app.botengine.dynamic.features import collect_features, MarketFeatures

logger = logging.getLogger(__name__)

HISTORY_MAX = 20
FIRST_DYNAMIC_CYCLE_ID = 2


def dynamic_overlay_allowed(state: Dict[str, Any]) -> bool:
    """Dynamic overlay starts after the first manual cycle is complete."""
    try:
        cycle_id = int(state.get("cycle_id") or 1)
    except (TypeError, ValueError):
        cycle_id = 1
    return cycle_id >= FIRST_DYNAMIC_CYCLE_ID


def need_recompute(state: Dict[str, Any]) -> bool:
    """True if no snapshot yet, or cycle changed, or explicit flag set."""
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
    }


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
        logger.info(
            "DYN_STALE bot_id=%s symbol=%s cycle=%s err=%s — falling back to prev applied",
            state.get("bot_id"),
            symbol,
            cycle_id,
            features.error,
        )
        applied = dict(prev_applied) if prev_applied else _fallback_from_base(cfg_dict)
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
                f"DATA_STALE: {features.error} — using {'prev applied' if prev_applied else 'manual cfg'}"
            ],
            "clamps": [],
            "fallbacks": ["data_stale_fallback"],
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

    # 3. Regime
    regime_result = reg.classify(features, prev_regime_state)
    new_regime_state = reg.update_regime_state(prev_regime_state, regime_result)

    # 4. Suggest
    pos = _position_state(state, cfg_dict)
    suggestion = se.suggest(features, regime_result, cfg_dict, pos)

    # 5. Smooth vs prev applied (EMA blend on scalars). Alpha scales with regime
    #    confidence: low confidence → stickier (stay near prev), avoiding large
    #    swings driven by an uncertain regime call. (0.5 at confidence 0.5.)
    _alpha = se.alpha_for_confidence(regime_result.confidence)
    suggestion = se.smooth_against_prev(suggestion, prev_applied, alpha=_alpha)

    # 6. Risk engine (clamps + rate limiter)
    clamped = risk.apply_safety(suggestion, cfg_dict, prev_applied)

    snap = {
        "cycle_id": cycle_id,
        "built_at_ms": int(time.time() * 1000),
        "data_fresh": True,
        "stale_reason": None,
        "regime": regime_result.regime,
        "regime_state": new_regime_state,
        "features": features.to_dict(),
        "raw": suggestion.to_dict(),
        "applied": clamped.to_dict(),
        "reasons": suggestion.reasons,
        "clamps": clamped.clamps,
        "fallbacks": clamped.fallbacks,
        "history": _push_history(
            prev_snap.get("history") or [],
            {
                "cycle_id": cycle_id,
                "regime": regime_result.regime,
                "regime_confidence": regime_result.confidence,
                "atr_pct_5m": features.atr_pct_5m,
                "adx_1h": features.adx_1h,
                "applied_base_alloc_pct": clamped.base_alloc_pct,
                "applied_trail_pct": clamped.sell_trigger_trailing_pct,
                "applied_grid_step_first": (
                    clamped.buy_grids[0].get("buy_grid_pct")
                    if clamped.buy_grids
                    else None
                ),
                "stale": False,
                "ts": int(time.time() * 1000),
            },
        ),
    }
    return snap


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
