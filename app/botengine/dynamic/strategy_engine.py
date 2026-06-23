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
from app.botengine.dynamic import cycle_duration as cd


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
    stance: Optional[Dict[str, Any]] = None  # Stance.to_dict() — posture transparency
    duration: Optional[Dict[str, Any]] = None  # DurationSizing.to_dict() — cycle-time target

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Behaviour STANCE — continuous passive↔aggressive posture from a risk/reward
# model. The discrete REGIME_TUNING table sets the coarse posture; the stance
# refines it *continuously* within the regime so two e.g. TRENDING_UP cycles
# with different liquidity / momentum / chaos get different aggression. The
# stance only nudges scalars (alloc, trailing, take-profit) — never the grid
# STEP width, which stays a pure ATR/regime/fee function — so it reinforces
# (never reverses) the regime's defensive/bullish bias.
# -----------------------------------------------------------------------------

STANCE_DEFENSIVE = "DEFENSIVE"
STANCE_BALANCED = "BALANCED"
STANCE_AGGRESSIVE = "AGGRESSIVE"

# How far stance is allowed to move each scalar (bounded; risk engine clamps too).
STANCE_BASE_SWING_PP = 8.0     # ±pp on base allocation at stance ±1
STANCE_TRAIL_SWING = 0.25      # ±25% on sell-trail at stance ±1 (ride vs lock)
STANCE_TP_SWING = 0.30         # ±30% on TP-rise at stance ±1 (let run vs bank)

# Per-regime structural risk used by the stance (broad posture, not the
# near-term knife signal — that lives in cycle_gate).
_REGIME_STANCE_RISK = {
    reg.DUMP_RISK: 1.0,
    reg.TRENDING_DOWN: 0.85,
    reg.HIGH_VOL_RANGING: 0.45,
    reg.BREAKOUT: 0.45,
    reg.SQUEEZE: 0.30,
    reg.LOW_VOL_RANGING: 0.10,
    reg.TRENDING_UP: 0.10,
    reg.UNKNOWN: 0.40,
}

# ATR "sweet spot" for grid trading: enough movement to fill grids, not chaos.
_ATR_SWEET_PCT = 1.0
_ATR_SWEET_HALFWIDTH = 1.6  # supportive band ≈ [ -0.6 .. 2.6 ]%

# "Ranging-ness" used by the stance reward. The legacy hard cliff at ADX_TRENDING
# (25) zeroed all grid reward the instant ADX nudged to 25.x — a 3-point overshoot
# killed a perfectly good ranging tape (e.g. RSI~60, ATR 0.4%). Use a soft RAMP:
# ranging = 1 at ADX ≤ ADX_RANGING (20), 0 at ADX ≥ _ADX_RANGE_HI (35), linear
# between. Reward decays gracefully into a trend instead of snapping to 0.
_ADX_RANGE_HI = 35.0

# Momentum reconciliation: a TRENDING_DOWN / DUMP regime call is *contradicted* by
# bullish momentum (RSI pressing high while the 1h slope is not strongly negative).
# When that happens we discount the regime's defensive push instead of de-risking
# into strength.
_RSI_BULLISH_REF = 52.0
_SLOPE_NOT_FALLING = -0.3
_CONTRADICTION_RISK_MULT = 0.5


@dataclass
class Stance:
    score: float          # -1 (defensive) .. +1 (aggressive)
    label: str
    reward_score: float   # 0..1 grid-friendliness
    risk_score: float     # 0..1 broad downside/chaos risk
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "label": self.label,
            "reward_score": round(self.reward_score, 4),
            "risk_score": round(self.risk_score, 4),
            "reasons": list(self.reasons),
        }


def _c01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _atr_fitness(atr_pct: Optional[float]) -> float:
    """1.0 at the grid sweet spot, decaying toward 0 as ATR is too dead or too
    chaotic (triangular kernel)."""
    if atr_pct is None or atr_pct <= 0:
        return 0.4
    d = abs(float(atr_pct) - _ATR_SWEET_PCT)
    return _c01(1.0 - d / _ATR_SWEET_HALFWIDTH)


def compute_stance(features: MarketFeatures, regime_result: "reg.RegimeResult") -> Stance:
    """Continuous behaviour posture from reward (grid-friendliness) minus risk
    (downtrend strength + chaos). Pure; defensive on missing data."""
    adx = features.adx_1h
    atr = features.atr_pct_5m
    spread = features.spread_pct
    slope = features.ema_slope_1h_pct
    rv = features.realized_vol_5m
    regime = regime_result.regime
    rsi_min = min(
        [r for r in (features.rsi_1h, features.rsi_5m) if r is not None],
        default=None,
    )

    # ---- reward (grid-friendliness) ----
    # Grid trading earns in RANGES, not trends: a healthy ATR and tight spread
    # only help when the market is actually ranging. ATR-fitness and liquidity
    # are GATED by ranging-ness. The gate is a SOFT RAMP (see _ADX_RANGE_HI), not
    # a hard cliff at ADX_TRENDING — reward decays into a trend instead of
    # snapping to 0 the instant ADX crosses 25.
    if adx is not None:
        ranging = _c01((_ADX_RANGE_HI - adx) / (_ADX_RANGE_HI - reg.ADX_RANGING))
    else:
        ranging = 0.5
    atr_fit = _atr_fitness(atr)
    liq = (1.0 - _c01((spread - 0.03) / 0.40)) if spread is not None else 0.6
    reward = _c01(ranging * (0.6 * atr_fit + 0.4 * liq))

    # ---- risk: regime + (downtrend × strength) + chaos ----
    regime_risk = _REGIME_STANCE_RISK.get(regime, 0.4)
    # Momentum reconciliation: don't go defensive into bullish momentum. If a
    # DOWN/DUMP regime is contradicted by RSI (high) + a non-falling slope, halve
    # the structural regime risk it contributes.
    contradiction = (
        regime in (reg.TRENDING_DOWN, reg.DUMP_RISK)
        and rsi_min is not None
        and rsi_min > _RSI_BULLISH_REF
        and (slope is None or slope > _SLOPE_NOT_FALLING)
    )
    if contradiction:
        regime_risk *= _CONTRADICTION_RISK_MULT
    downtrend = _c01(-slope / 1.0) if (slope is not None and slope < 0) else 0.0
    strength = _c01((adx - reg.ADX_RANGING) / 30.0) if adx is not None else 0.3
    chaos = _c01((rv - 1.2) / 2.5) if rv is not None else 0.0
    risk = _c01(0.45 * regime_risk + 0.30 * (downtrend * strength) + 0.25 * chaos)

    score = max(-1.0, min(1.0, reward - risk))
    if score >= 0.25:
        label = STANCE_AGGRESSIVE
    elif score <= -0.25:
        label = STANCE_DEFENSIVE
    else:
        label = STANCE_BALANCED

    reasons = [
        f"stance={label} score={score:+.2f} (reward={reward:.2f} − risk={risk:.2f})",
        f"reward: ranging={ranging:.2f} atr_fit={atr_fit:.2f} liq={liq:.2f}",
        f"risk: regime={regime_risk:.2f} downtrend×str={downtrend * strength:.2f} chaos={chaos:.2f}",
    ]
    if contradiction:
        reasons.append(
            f"momentum çelişkisi: rejim={regime} ama RSI={rsi_min:.0f} (>{_RSI_BULLISH_REF:.0f}) "
            f"& eğim düşmüyor → savunma yarıya indirildi"
        )
    return Stance(score=score, label=label, reward_score=reward, risk_score=risk, reasons=reasons)


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
    depth-bounded by the caller). Trigger % of level i = step × (i+1).

    IMPORTANT (fixes the "grid welded to manual floor" defect): the trigger % is
    the DYNAMIC step alone. The manual template is a *reference* for grid COUNT
    and per-level QTY distribution only — it is NOT a floor on the step. The
    economic fee/spread floor and the depth cap (applied by the caller in
    `_resolve_grid_step`) are the real lower/upper guards; the manual trigger no
    longer pins the geometry, so the grid actually breathes with vol/duration.

    Returns same length as `base_grids` so existing UI / state shapes stay
    intact — we only swap the numbers, not the count.

    Capital deployment: we preserve the user's per-grid qty percentages exactly
    (defensive regimes use allocation / spacing, not qty drift). Falls back to an
    even 100% split only when the template has no usable qty numbers.
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
        qty = manual_qtys[i] if has_manual_qty else (100.0 / n)
        levels.append(
            {
                field_pct: round(dynamic_pct, 4),
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

    # Continuous behaviour posture (passive↔aggressive) that refines the discrete
    # regime tuning. Only nudges scalars (alloc / trailing / TP), never grid step.
    stance = compute_stance(features, regime_result)
    reasons.extend(stance.reasons)

    base_sell_grids = list(base_cfg.get("sell_grids") or [])
    base_buy_grids = list(base_cfg.get("buy_grids") or [])
    fee_floor = _fee_aware_min_step(base_cfg, features)
    atr_clamped = _atr_clamped(features.atr_pct_5m)

    # ---- Cycle-duration-targeted distances (primary) ----
    # Size grid span / take-profit / trailing / re-entry so the cycle is EXPECTED
    # to complete within [1,7] days at the CURRENT volatility (regime-aware target).
    # This replaces the legacy ATR×regime grid step, which was structurally welded
    # to the manual template floor. Falls back to the ATR path only if vol is
    # unavailable. Pure/analytic — no backtest.
    recent_days = None
    if position_state:
        recent_days = position_state.get("recent_cycle_days")
    ds = cd.compute(
        features, regime_result.regime, regime_result.confidence, recent_days
    )
    reasons.extend(ds.reasons)

    if ds.ok:
        # deepest grid level = ds.grid_span_pct → per-level step = span / n, then
        # bounded by the economic floor (fees/spread) and the depth cap.
        n_sell = max(1, len(base_sell_grids))
        n_buy = max(1, len(base_buy_grids))
        sell_step = _resolve_grid_step(ds.grid_span_pct / n_sell, len(base_sell_grids), fee_floor)
        buy_step = _resolve_grid_step(ds.grid_span_pct / n_buy, len(base_buy_grids), fee_floor)
        tp_rise = ds.profit_exit_rise_pct * (1.0 + stance.score * STANCE_TP_SWING)
        tp_drop = ds.profit_exit_drop_pct
        re_drop = ds.profit_reentry_drop_pct
        re_rise = ds.profit_reentry_rise_pct
        # trailing anchored to the actual first grid step
        trail_raw = max(0.15, cd.TRAIL_FRAC * buy_step)
    else:
        # Fallback: legacy ATR×regime sizing (vol unavailable).
        base_step = _base_grid_step_pct(features)
        raw_step = base_step * tuning["step_mult"]
        sell_step = _resolve_grid_step(raw_step, len(base_sell_grids), fee_floor)
        buy_step = _resolve_grid_step(raw_step, len(base_buy_grids), fee_floor)
        tp_rise = max(0.5, 2.5 * atr_clamped * tuning["tp_rise_mult"] * (1.0 + stance.score * STANCE_TP_SWING))
        tp_drop = max(0.15, 0.4 * atr_clamped)
        re_drop = max(0.5, 2.0 * atr_clamped)
        re_rise = max(0.15, 0.4 * atr_clamped)
        trail_raw = K_ATR_TRAIL * atr_clamped * tuning["trail_mult"]
        reasons.append(f"FALLBACK ATR sizing: raw_step={raw_step:.3f} fee_floor={fee_floor:.3f}")

    reasons.append(
        f"grid_step → sell={sell_step:.3f} buy={buy_step:.3f} (fee_floor={fee_floor:.3f})"
    )
    reasons.append("grid_qty: manual percentages preserved")

    sell_grids = _build_grid_levels(
        sell_step, base_sell_grids, "sell_grid_pct", "sell_qty_pct_of_base"
    )
    buy_grids = _build_grid_levels(
        buy_step, base_buy_grids, "buy_grid_pct", "buy_qty_pct_of_quote"
    )
    reasons.append(f"sell_grids n={len(sell_grids)} buy_grids n={len(buy_grids)}")

    # ---- Trailing %s ----
    # Stance widens the SELL trail when aggressive (ride the move) and tightens it
    # when defensive (lock profit faster). Buy trail stays neutral (its job is
    # bounce-confirmation, not posture). Floor at 0.15% (below = spot noise).
    sell_trail = max(0.15, round(trail_raw * (1.0 + stance.score * STANCE_TRAIL_SWING), 4))
    buy_trail = max(0.15, round(trail_raw, 4))
    reasons.append(f"trailing: sell={sell_trail:.3f} buy={buy_trail:.3f}")

    # ---- Base / Quote allocation ----
    # Low-confidence damping (anti-whipsaw): pull the regime's base target toward
    # neutral 50 when the regime call is uncertain, so a coin-flip regime cannot
    # swing allocation ±15pp cycle-to-cycle. Stance (feature-driven) keeps full
    # weight; only the discrete regime deviation is damped.
    regime_target = tuning["base_pct_target"]
    conf = regime_result.confidence
    try:
        conf_w = max(0.0, min(1.0, (float(conf) - 0.4) / 0.4))
    except (TypeError, ValueError):
        conf_w = 0.5
    target_base = 50.0 + (regime_target - 50.0) * conf_w
    base_pct = max(10.0, min(80.0, target_base + stance.score * STANCE_BASE_SWING_PP))
    quote_pct = round(100.0 - base_pct, 4)
    reasons.append(
        f"base/quote={base_pct:.1f}/{quote_pct:.1f} "
        f"(regime target={regime_target:.0f} conf_damped→{target_base:.1f} + stance {stance.score:+.2f}×{STANCE_BASE_SWING_PP})"
    )

    # clamp TP/re-entry into sane positive ranges (risk engine re-clamps to bounds)
    tp_rise = max(0.30, round(tp_rise, 4))
    tp_drop = max(0.10, round(tp_drop, 4))
    re_drop = max(0.30, round(re_drop, 4))
    re_rise = max(0.10, round(re_rise, 4))
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
        stance=stance.to_dict(),
        duration=ds.to_dict() if ds.ok else None,
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
