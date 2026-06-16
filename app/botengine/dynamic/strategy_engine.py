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
    sell_grids: List[Dict[str, float]]   # [{sell_grid_pct, sell_qty_pct_of_base}, ...]
    buy_grids: List[Dict[str, float]]    # [{buy_grid_pct, buy_qty_pct_of_quote}, ...]
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

K_ATR_GRID_STEP = 0.7    # grid step% ≈ K_ATR × ATR%
K_ATR_TRAIL = 1.0        # trailing% ≈ K_ATR_TRAIL × ATR%
DEFAULT_GRID_COUNT_RANGING = None  # use whatever base_cfg has
ATR_FLOOR_PCT = 0.15     # tiny coin guard
ATR_CEIL_PCT = 6.0       # cap insane vol

# Per-regime tuning multipliers
REGIME_TUNING = {
    reg.LOW_VOL_RANGING: {
        "step_mult": 0.8,        # tighter grid in calm conditions
        "trail_mult": 0.8,
        "base_pct_target": 50.0, # balanced
        "tp_rise_mult": 0.9,
        "buy_levels_mult": 1.0,
    },
    reg.HIGH_VOL_RANGING: {
        "step_mult": 1.4,
        "trail_mult": 1.3,
        "base_pct_target": 40.0, # less base, more cash
        "tp_rise_mult": 1.1,
        "buy_levels_mult": 0.7,
    },
    reg.TRENDING_UP: {
        "step_mult": 1.2,
        "trail_mult": 1.4,       # ride the trend
        "base_pct_target": 60.0,
        "tp_rise_mult": 1.6,
        "buy_levels_mult": 0.8,  # don't keep adding into a runup
    },
    reg.TRENDING_DOWN: {
        "step_mult": 1.5,
        "trail_mult": 1.2,
        "base_pct_target": 25.0, # PROTECT CASH — falling knife protection
        "tp_rise_mult": 1.3,
        "buy_levels_mult": 0.5,  # very few new buys
    },
    reg.SQUEEZE: {
        "step_mult": 0.9,
        "trail_mult": 1.0,
        "base_pct_target": 45.0,
        "tp_rise_mult": 1.0,
        "buy_levels_mult": 0.9,
    },
    reg.BREAKOUT: {
        "step_mult": 1.6,
        "trail_mult": 1.5,
        "base_pct_target": 50.0,
        "tp_rise_mult": 1.5,
        "buy_levels_mult": 0.6,
    },
    reg.DUMP_RISK: {
        "step_mult": 2.0,
        "trail_mult": 1.0,
        "base_pct_target": 15.0, # mostly quote
        "tp_rise_mult": 1.0,
        "buy_levels_mult": 0.3,
    },
    reg.UNKNOWN: {
        "step_mult": 1.0,
        "trail_mult": 1.0,
        "base_pct_target": 50.0,
        "tp_rise_mult": 1.0,
        "buy_levels_mult": 1.0,
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


def _build_grid_levels(
    base_step_pct: float,
    base_grids: List[Dict[str, Any]],
    field_pct: str,
    field_qty: str,
    *,
    step_mult: float,
    distribution_growth: float = 1.15,
) -> List[Dict[str, float]]:
    """
    Build grid levels: trigger percentages are geometric in `base_step_pct`,
    qty distribution is geometric in `distribution_growth` (r<=1.5 hard guard
    enforced upstream by risk engine).

    Returns same length as `base_grids` so existing UI / state shapes stay
    intact — we only swap the numbers, not the count.

    Capital deployment: we preserve the manual template's TOTAL qty% (the sum of
    the user's per-grid qty figures) and only re-shape how it is distributed.
    Manual configs deliberately rarely sum to 100 (the user keeps a reserve);
    forcing the sum to 100 here would silently deploy far more capital than the
    user asked for. We fall back to 100 only when the template carries no usable
    qty numbers at all.
    """
    n = max(0, len(base_grids))
    if n == 0:
        return []
    step = max(0.05, base_step_pct * step_mult)
    # Total qty% the user intended to deploy across this side's ladder.
    manual_total = 0.0
    for g in base_grids:
        q = g.get(field_qty)
        if q is None:
            q = g.get("qty_pct")
        try:
            qf = float(q)
        except (TypeError, ValueError):
            qf = 0.0
        if qf > 0:
            manual_total += qf
    if manual_total <= 0:
        manual_total = 100.0
    levels: List[Dict[str, float]] = []
    # Trigger %: level i = step * (i+1) (linear in count, but step itself is
    # vol-scaled). This is safer than purely geometric trigger % (which can
    # explode for vol-heavy coins).
    # Quantity: geometric with `distribution_growth`, scaled to `manual_total`.
    weights = [distribution_growth ** i for i in range(n)]
    wsum = sum(weights)
    for i in range(n):
        levels.append(
            {
                field_pct: round(step * (i + 1), 4),
                field_qty: round((weights[i] / wsum) * manual_total, 4),
            }
        )
    return levels


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

    sell_grids = _build_grid_levels(
        base_step,
        base_sell_grids,
        "sell_grid_pct",
        "sell_qty_pct_of_base",
        step_mult=tuning["step_mult"],
        distribution_growth=1.10,  # sells: gentler, sell-into-strength
    )
    # Buys: distribution growth slightly higher (cost averaging) but ≤1.3
    buy_grids = _build_grid_levels(
        base_step,
        base_buy_grids,
        "buy_grid_pct",
        "buy_qty_pct_of_quote",
        step_mult=tuning["step_mult"],
        distribution_growth=1.20,
    )
    reasons.append(
        f"sell_grids n={len(sell_grids)} step_mult={tuning['step_mult']}"
    )
    reasons.append(
        f"buy_grids n={len(buy_grids)} step_mult={tuning['step_mult']}"
    )

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

    # ---- Position-state defensive overrides ----
    if position_state:
        fired = int(position_state.get("buy_levels_fired") or 0)
        mbl = max(1, int(position_state.get("max_buy_levels") or 1))
        used_ratio = fired / mbl
        if used_ratio >= 0.7:
            # Near max buy levels — go super defensive on new buys
            for g in buy_grids:
                g["buy_qty_pct_of_quote"] = round(g["buy_qty_pct_of_quote"] * 0.5, 4)
            reasons.append(
                f"DEFENSIVE: buy_levels {fired}/{mbl} → halved buy qty distribution"
            )

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
