"""
Dynamic Strategy Engine — converts market features + regime into PARAMETER
SUGGESTIONS. This module produces only suggestions; the Risk Engine has the
final say on what gets applied.

What we suggest (6 parameters, matches the model fields the existing strategy
already consumes — we do NOT change the strategy's grammar):

    1. base_alloc_pct / quote_alloc_pct (split, sum=100)
    2. sell/buy grid trigger %  (sell_grids[i].sell_grid_pct, buy_grids[i].buy_grid_pct)
    3. sell/buy grid distribution % (qty_pct_of_base / qty_pct_of_quote)
    4. sell/buy_trigger_trailing_pct
    5. profit_exit_rise_pct  (TP trigger)
    6. profit_reentry_drop_pct (re-entry trigger after profit)

Design rules (production-safe):
  * Suggestions are deterministic functions of (features, regime, position_state,
    base_cfg). No global state, no randomness.
  * We always start from the base_cfg (the user's manual config) and nudge from
    there. We never throw it away. This means even a totally broken indicator
    set produces a safe overlay close to manual.
  * Asymmetric defensive bias: in TRENDING_DOWN / DUMP_RISK we lean conservative
    (more quote, narrower base, wider grid, tighter trailing).
  * Manual grid intent is a floor, not a suggestion to discard: Dynamic Mode may
    widen trigger levels, but it does not tighten them below the user's template
    and it preserves the user's grid quantity percentages.
  * EMA-smoothing with previous snapshot (if any) — see `smooth_against_prev`.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from app.botengine.dynamic.features import MarketFeatures
from app.botengine.dynamic import regime as reg


# -----------------------------------------------------------------------------
# Suggestion DTO
# -----------------------------------------------------------------------------


@dataclass
class ParamSuggestion:
    base_alloc_pct: float
    quote_alloc_pct: float
    sell_grids: List[Dict[str, float]]  # [{sell_grid_pct, sell_qty_pct_of_base}, ...]
    buy_grids: List[Dict[str, float]]  # [{buy_grid_pct, buy_qty_pct_of_quote}, ...]
    sell_trigger_trailing_pct: float
    buy_trigger_trailing_pct: float
    profit_exit_rise_pct: float
    profit_exit_drop_pct: float
    profit_reentry_drop_pct: float
    profit_reentry_rise_pct: float
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Coefficient constants (system-defined, NOT user-tunable)
# -----------------------------------------------------------------------------

K_ATR_GRID_STEP = 0.7  # grid step% ≈ K_ATR × ATR%
K_ATR_TRAIL = 1.0  # trailing% ≈ K_ATR_TRAIL × ATR%
DEFAULT_GRID_COUNT_RANGING = None  # use whatever base_cfg has
ATR_FLOOR_PCT = 0.15  # tiny coin guard
ATR_CEIL_PCT = 6.0  # cap insane vol

# Mirror of risk_engine.BOUNDS["grid_step_pct"][1]; kept local to avoid a
# circular import (risk_engine imports this module). MUST stay in sync.
MAX_GRID_STEP_PCT = 8.0

# Economic floor: a grid round-trip must clear fees + min net profit, otherwise
# the grid just churns fees. step_floor ≈ FEE_FLOOR_K × (buy_fee + sell_fee +
# min_net_profit) (as %). Also kept ≥ spread (can't profit inside the spread).
FEE_FLOOR_K = 1.0
SPREAD_FLOOR_MULT = 2.0  # min grid step ≥ this × spread%

# Per-regime tuning multipliers
REGIME_TUNING = {
    reg.LOW_VOL_RANGING: {
        "step_mult": 0.8,  # tighter grid in calm conditions
        "trail_mult": 0.8,
        "base_pct_target": 50.0,  # balanced
        "tp_rise_mult": 0.9,
    },
    reg.HIGH_VOL_RANGING: {
        "step_mult": 1.4,
        "trail_mult": 1.3,
        "base_pct_target": 40.0,  # less base, more cash
        "tp_rise_mult": 1.1,
    },
    reg.TRENDING_UP: {
        "step_mult": 1.2,
        "trail_mult": 1.4,  # ride the trend
        "base_pct_target": 60.0,
        "tp_rise_mult": 1.6,
    },
    reg.TRENDING_DOWN: {
        "step_mult": 1.5,
        "trail_mult": 1.2,
        "base_pct_target": 25.0,  # PROTECT CASH — falling knife protection
        "tp_rise_mult": 1.3,
    },
    reg.SQUEEZE: {
        "step_mult": 0.9,
        "trail_mult": 1.0,
        "base_pct_target": 45.0,
        "tp_rise_mult": 1.0,
    },
    reg.BREAKOUT: {
        "step_mult": 1.6,
        "trail_mult": 1.5,
        "base_pct_target": 50.0,
        "tp_rise_mult": 1.5,
    },
    reg.DUMP_RISK: {
        "step_mult": 2.0,
        "trail_mult": 1.0,
        "base_pct_target": 15.0,  # mostly quote
        "tp_rise_mult": 1.0,
    },
    reg.UNKNOWN: {
        "step_mult": 1.0,
        "trail_mult": 1.0,
        "base_pct_target": 50.0,
        "tp_rise_mult": 1.0,
    },
}


def _atr_clamped(atr_pct: Optional[float]) -> float:
    if atr_pct is None or atr_pct <= 0:
        return 0.5  # safe default if no data
    return max(ATR_FLOOR_PCT, min(ATR_CEIL_PCT, atr_pct))


def _base_grid_step_pct(features: MarketFeatures) -> float:
    """Raw grid step% from ATR%. Always positive."""
    atr_v = _atr_clamped(features.atr_pct_5m)
    return K_ATR_GRID_STEP * atr_v


def _fee_aware_min_step(base_cfg: Dict[str, Any], features: MarketFeatures) -> float:
    """Minimum economically-sensible grid step %: must clear fees + min net
    profit, and never be tighter than the spread."""
    buy_fee = float(base_cfg.get("buy_fee_rate") or base_cfg.get("fee_rate") or 0.001)
    sell_fee = float(base_cfg.get("sell_fee_rate") or base_cfg.get("fee_rate") or 0.001)
    min_profit = float(base_cfg.get("min_net_profit_rate") or 0.0)
    floor = (buy_fee + sell_fee + min_profit) * 100.0 * FEE_FLOOR_K
    sp = features.spread_pct
    if sp is not None and sp > 0:
        floor = max(floor, sp * SPREAD_FLOOR_MULT)
    return max(0.05, round(floor, 4))


def _resolve_grid_step(raw_step: float, n: int, fee_floor: float) -> float:
    """Final per-level step %: clamp the raw ATR-derived step between the
    economic floor and a depth cap so the deepest level (step×n) stays under the
    hard bound — this prevents the degenerate "all levels collapse to 8%" case
    that the risk-engine clamp would otherwise produce for high-ATR coins."""
    if n <= 0:
        return max(0.05, round(raw_step, 4))
    cap = MAX_GRID_STEP_PCT / n  # deepest level = step×n ≤ MAX_GRID_STEP_PCT
    floor_eff = min(max(0.05, fee_floor), cap)
    return round(min(max(raw_step, floor_eff), cap), 4)


def _manual_grid_pct(g: Dict[str, Any], field_pct: str) -> float:
    v = g.get(field_pct)
    if v is None:
        v = g.get("trigger_pct")
    try:
        vf = float(v)
    except (TypeError, ValueError):
        return 0.0
    return vf if vf > 0 else 0.0


def _manual_grid_qty(g: Dict[str, Any], field_qty: str) -> float:
    v = g.get(field_qty)
    if v is None:
        v = g.get("qty_pct")
    try:
        vf = float(v)
    except (TypeError, ValueError):
        return 0.0
    return vf if vf > 0 else 0.0


def _build_grid_levels(
    step_pct: float,
    base_grids: List[Dict[str, Any]],
    field_pct: str,
    field_qty: str,
) -> List[Dict[str, float]]:
    """
    Build grid levels from a PRE-RESOLVED per-level `step_pct` (already fee-/
    depth-bounded by the caller). Trigger % of level i is at least the user's
    manual trigger for that level; Dynamic Mode may widen a level, but never
    pulls it closer to the reference than the template the user opened the bot
    with.

    Returns same length as `base_grids` so existing UI / state shapes stay
    intact — we only swap the numbers, not the count.

    Capital deployment: we preserve the user's per-grid qty percentages exactly.
    The create UI requires side totals to be understandable (usually 100%);
    reshaping them into values like 47.6/52.4 or 36.4/43.6 makes the running
    bot look incompatible with the configuration the user chose. Falls back to
    an even 100% split only when the template has no usable qty numbers.
    """
    n = max(0, len(base_grids))
    if n == 0:
        return []
    step = max(0.05, step_pct)
    manual_qtys = [_manual_grid_qty(g, field_qty) for g in base_grids]
    has_manual_qty = any(q > 0 for q in manual_qtys)
    levels: List[Dict[str, float]] = []
    for i in range(n):
        dynamic_pct = step * (i + 1)
        manual_pct = _manual_grid_pct(base_grids[i], field_pct)
        qty = manual_qtys[i] if has_manual_qty else (100.0 / n)
        levels.append(
            {
                field_pct: round(max(dynamic_pct, manual_pct), 4),
                field_qty: round(qty, 4),
            }
        )
    return levels


def alpha_for_confidence(confidence: float) -> float:
    """Smoothing alpha (weight on the NEW suggestion) scaled by regime
    confidence: low confidence → small alpha → stay closer to the previous
    applied snapshot (less aggressive regime-driven swings). At confidence 0.5
    this returns 0.5 (the previous fixed default), so behaviour is unchanged for
    mid-confidence regimes."""
    try:
        c = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        c = 0.5
    return round(0.3 + 0.4 * c, 4)


def suggest(
    features: MarketFeatures,
    regime_result: reg.RegimeResult,
    base_cfg: Dict[str, Any],
    position_state: Optional[Dict[str, Any]] = None,
) -> ParamSuggestion:
    """
    Produce a ParamSuggestion. `base_cfg` is `cfg.to_dict()` from
    DcaGridTrailingConfig — used for shape (grid counts) and fallback values.
    """
    tuning = REGIME_TUNING.get(regime_result.regime) or REGIME_TUNING[reg.UNKNOWN]
    reasons: List[str] = [
        f"regime={regime_result.regime} (confidence={regime_result.confidence:.2f})"
    ]

    # ---- ATR-based grid step % ----
    atr_clamped = _atr_clamped(features.atr_pct_5m)
    base_step = _base_grid_step_pct(features)
    reasons.append(
        f"atr_pct_5m={features.atr_pct_5m} → clamped={atr_clamped:.3f} → base_step≈{base_step:.3f}%"
    )

    # ---- Build sell/buy grids preserving count from base_cfg ----
    base_sell_grids = list(base_cfg.get("sell_grids") or [])
    base_buy_grids = list(base_cfg.get("buy_grids") or [])

    # Resolve per-level step: ATR×regime, then bounded by the economic floor
    # (fees/spread) and a depth cap (prevents degenerate collapse at high ATR).
    fee_floor = _fee_aware_min_step(base_cfg, features)
    raw_step = base_step * tuning["step_mult"]
    sell_step = _resolve_grid_step(raw_step, len(base_sell_grids), fee_floor)
    buy_step = _resolve_grid_step(raw_step, len(base_buy_grids), fee_floor)
    reasons.append(
        f"grid_step raw={raw_step:.3f} fee_floor={fee_floor:.3f} → sell={sell_step:.3f} buy={buy_step:.3f}"
    )

    reasons.append("grid_qty: manual percentages preserved")

    sell_grids = _build_grid_levels(
        sell_step,
        base_sell_grids,
        "sell_grid_pct",
        "sell_qty_pct_of_base",
    )
    buy_grids = _build_grid_levels(
        buy_step,
        base_buy_grids,
        "buy_grid_pct",
        "buy_qty_pct_of_quote",
    )
    reasons.append(f"sell_grids n={len(sell_grids)} buy_grids n={len(buy_grids)}")

    # ---- Trailing %s ----
    trail_raw = K_ATR_TRAIL * atr_clamped * tuning["trail_mult"]
    # Floor at 0.15% (below this = noise in spot)
    sell_trail = max(0.15, round(trail_raw, 4))
    buy_trail = max(0.15, round(trail_raw, 4))
    reasons.append(f"trailing_raw≈{trail_raw:.3f}% (atr×K×regime_mult)")

    # ---- Base / Quote allocation ----
    target_base = tuning["base_pct_target"]
    # If TRENDING_DOWN + low confidence → still protect cash but not as aggressively.
    if regime_result.regime == reg.TRENDING_DOWN and regime_result.confidence < 0.6:
        target_base = max(target_base, 35.0)
    base_pct = max(10.0, min(80.0, target_base))
    quote_pct = round(100.0 - base_pct, 4)
    reasons.append(f"base/quote target={base_pct:.1f}/{quote_pct:.1f} (regime tuning)")

    # ---- TP / re-entry triggers ----
    # TP rise = "kâr alma için fiyat ne kadar yükselsin?" — vol ölçeklendir.
    tp_rise = max(0.5, 2.5 * atr_clamped * tuning["tp_rise_mult"])
    tp_drop = max(0.15, 0.4 * atr_clamped)
    re_drop = max(0.5, 2.0 * atr_clamped)
    re_rise = max(0.15, 0.4 * atr_clamped)
    reasons.append(
        f"profit_exit rise={tp_rise:.3f} drop={tp_drop:.3f} | reentry drop={re_drop:.3f} rise={re_rise:.3f}"
    )

    # Position-state is intentionally not allowed to reshape grid qty
    # percentages. The structural protection is max_buy_levels, enforced by the
    # strategy/execution path.

    return ParamSuggestion(
        base_alloc_pct=round(base_pct, 4),
        quote_alloc_pct=round(quote_pct, 4),
        sell_grids=sell_grids,
        buy_grids=buy_grids,
        sell_trigger_trailing_pct=sell_trail,
        buy_trigger_trailing_pct=buy_trail,
        profit_exit_rise_pct=round(tp_rise, 4),
        profit_exit_drop_pct=round(tp_drop, 4),
        profit_reentry_drop_pct=round(re_drop, 4),
        profit_reentry_rise_pct=round(re_rise, 4),
        reasons=reasons,
    )


# -----------------------------------------------------------------------------
# EMA smoothing — blend new suggestion with previous applied snapshot
# -----------------------------------------------------------------------------


def smooth_against_prev(
    new: ParamSuggestion,
    prev_applied: Optional[Dict[str, Any]],
    alpha: float = 0.5,
) -> ParamSuggestion:
    """
    EMA blend scalar fields with the previously APPLIED params (post-clamp).
    Grid lists are not blended (their shape is identical so it would just
    shuffle numbers — accept the new ones as-is).
    """
    if not prev_applied:
        new.reasons.append("smoothing: no prev applied — using raw new values")
        return new

    def _b(field: str, cur: float) -> float:
        prev = prev_applied.get(field)
        try:
            prev_f = float(prev)
        except (TypeError, ValueError):
            return cur
        return round((1.0 - alpha) * prev_f + alpha * cur, 4)

    new.base_alloc_pct = _b("base_alloc_pct", new.base_alloc_pct)
    new.quote_alloc_pct = round(100.0 - new.base_alloc_pct, 4)
    new.sell_trigger_trailing_pct = _b(
        "sell_trigger_trailing_pct", new.sell_trigger_trailing_pct
    )
    new.buy_trigger_trailing_pct = _b(
        "buy_trigger_trailing_pct", new.buy_trigger_trailing_pct
    )
    new.profit_exit_rise_pct = _b("profit_exit_rise_pct", new.profit_exit_rise_pct)
    new.profit_exit_drop_pct = _b("profit_exit_drop_pct", new.profit_exit_drop_pct)
    new.profit_reentry_drop_pct = _b(
        "profit_reentry_drop_pct", new.profit_reentry_drop_pct
    )
    new.profit_reentry_rise_pct = _b(
        "profit_reentry_rise_pct", new.profit_reentry_rise_pct
    )
    new.reasons.append(f"smoothing: alpha={alpha} blended with prev_applied")
    return new
