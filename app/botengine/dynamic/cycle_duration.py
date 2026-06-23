"""
Dynamic Mode — Cycle-Duration-Targeted Sizing.

At every NEW cycle boundary, size the cycle's DISTANCES (grid span, take-profit,
trailing, re-entry) so that — given the *current* volatility — the cycle is
EXPECTED to complete within [MIN_DAYS, MAX_DAYS] (default 1..7 days), centered on
a regime-aware target.

Design constraints (from product owner):
  * NO backtest at the boundary. Pure analytic, O(1), microseconds. Every bot can
    compute its own sizing concurrently with zero shared state / no governance
    limit / no contention.
  * "Veriler doğru olsun": sizing is a pure function of fresh, real features
    (ATR / regime). Caller must pass features it already validated as fresh; on
    missing/invalid vol we fall back to a safe neutral sizing.
  * Cycle overrun (took > MAX_DAYS) → only WIDEN the next cycle's grid (deeper
    DCA reach so the average cost drops faster → next cycle closes sooner). We
    never touch the open position here (that is the strategy's job).

Theory
------
Treat log-price over a cycle as a driftless random walk with daily volatility
σ_d (%). A grid cycle closes when price first achieves a FAVORABLE excursion of
size G above the (DCA-lowered) average cost — i.e. `profit_exit_rise`. By the
reflection principle the EXPECTED maximum favorable excursion of a driftless walk
over a horizon of T days is

    E[ max_{0<=t<=T} W_t ] = σ_d · sqrt(2T/π)

So to make a cycle "reach its take-profit" in ~T_target days we set the favorable
barrier to exactly that expected maximum:

    G(T) = σ_d · sqrt(2 · T_target / π)                      (c = sqrt(2/π) ≈ 0.798)

This is the inversion of the first-passage relation  T ≈ (G / (c·σ_d))² . Every
other distance is derived from G so the whole geometry breathes coherently with
volatility — which structurally fixes the legacy defect where the grid step was
welded to the manual 1% template floor regardless of vol/regime.

Volatility estimate (daily %, range→std de-biased)
--------------------------------------------------
    σ_d ≈ ATR_1h% · sqrt(24)  · ATR_TO_STD          (primary; smooth)
    σ_d ≈ ATR_5m% · sqrt(288) · ATR_TO_STD          (fallback)
ATR is a *range* proxy (~1.6× the per-bar return std), so we multiply by
ATR_TO_STD ≈ 0.6 to recover a standard-deviation-like daily vol. The exact
constant is not critical: G is clamped to the risk-engine bounds and the target
is a heuristic, not a guarantee — but the calibration lands real majors (σ_d ≈
3–6 %/day) at G ≈ 4–8 % for a ~3-day cycle, which is the intended regime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.botengine.dynamic import regime as reg

# ---- Target window (days) ---------------------------------------------------

MIN_DAYS = 1.0
MAX_DAYS = 7.0
T_CENTER = 3.0  # neutral target (also the low-confidence fallback)

# Per-regime target cycle duration (days). Defensive regimes want to close FAST
# on any bounce (don't hold a bag into a downtrend); bullish regimes let winners
# run a little longer. All inside [MIN_DAYS, MAX_DAYS].
T_REGIME = {
    reg.LOW_VOL_RANGING: 3.0,
    reg.HIGH_VOL_RANGING: 2.5,
    reg.TRENDING_UP: 4.5,
    reg.TRENDING_DOWN: 1.5,
    reg.DUMP_RISK: 1.0,
    reg.BREAKOUT: 3.5,
    reg.SQUEEZE: 3.0,
    reg.UNKNOWN: 3.0,
}

# ---- Volatility model -------------------------------------------------------

ATR_TO_STD = 0.6           # range → std de-bias factor
BARS_PER_DAY_1H = 24.0
BARS_PER_DAY_5M = 288.0
SIGMA_FLOOR_PCT = 0.20     # never size on ~0 vol (degenerate tiny grids)
SIGMA_CEIL_PCT = 60.0      # cap absurd vol so G clamps gracefully

C_EXCURSION = math.sqrt(2.0 / math.pi)  # ≈ 0.7979

# ---- Distance shaping (all derived from G) ----------------------------------

GRID_SPAN_FRAC = 0.8       # deepest grid level = SPAN_FRAC × G (grid a touch
                           # tighter than the TP so DCA fills *within* the swing)
GRID_SPAN_FRAC_MAX = 1.2   # overrun feedback may widen up to this
TRAIL_FRAC = 0.35          # trailing ≈ TRAIL_FRAC × first grid step
TP_DROP_FRAC = 0.5         # profit_exit_drop ≈ TP_DROP_FRAC × trailing give-back
REENTRY_RISE_FRAC = 0.4    # small confirmation hop on re-entry

# Hard bounds mirrored from risk_engine.BOUNDS (kept local to avoid an import
# cycle: risk_engine imports strategy_engine which imports this module).
TP_RISE_BOUNDS = (0.30, 15.0)
TRAIL_BOUNDS = (0.15, 5.0)
TP_DROP_BOUNDS = (0.10, 5.0)
REENTRY_DROP_BOUNDS = (0.30, 15.0)
REENTRY_RISE_BOUNDS = (0.10, 5.0)

# Confidence below which the regime's target is fully de-weighted toward T_CENTER
# (anti-whipsaw: a coin-flip regime call must not swing the cycle geometry).
CONF_FLOOR = 0.40
CONF_FULL = 0.80


def _clamp(x: float, lo: float, hi: float) -> float:
    if x != x:  # NaN
        return lo
    return lo if x < lo else (hi if x > hi else x)


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        x = float(v)
        return x if x == x and math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _median(xs: Sequence[float]) -> Optional[float]:
    vals = sorted(x for x in xs if isinstance(x, (int, float)) and x == x)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


@dataclass
class DurationSizing:
    """Result of one duration-targeted sizing pass."""

    sigma_d_pct: float           # estimated daily volatility (%)
    t_target_days: float         # regime/confidence/overrun-adjusted target
    favorable_excursion_pct: float  # G — also the take-profit rise
    grid_span_pct: float         # deepest grid level distance (SPAN_FRAC × G…)
    span_frac: float             # the (possibly overrun-widened) span fraction
    profit_exit_rise_pct: float
    profit_exit_drop_pct: float
    profit_reentry_drop_pct: float
    profit_reentry_rise_pct: float
    sell_trailing_base_pct: float  # pre-stance trailing base
    buy_trailing_base_pct: float
    ok: bool = True              # False → caller should keep its own fallback
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sigma_d_pct": round(self.sigma_d_pct, 4),
            "t_target_days": round(self.t_target_days, 3),
            "favorable_excursion_pct": round(self.favorable_excursion_pct, 4),
            "grid_span_pct": round(self.grid_span_pct, 4),
            "span_frac": round(self.span_frac, 4),
            "profit_exit_rise_pct": round(self.profit_exit_rise_pct, 4),
            "ok": self.ok,
        }


def daily_vol_pct(features: Any) -> Optional[float]:
    """Estimate daily volatility (%) from ATR. Returns None if no usable ATR."""
    atr_1h = _f(getattr(features, "atr_pct_1h", None))
    atr_5m = _f(getattr(features, "atr_pct_5m", None))
    sigma: Optional[float] = None
    if atr_1h is not None and atr_1h > 0:
        sigma = atr_1h * math.sqrt(BARS_PER_DAY_1H) * ATR_TO_STD
    elif atr_5m is not None and atr_5m > 0:
        sigma = atr_5m * math.sqrt(BARS_PER_DAY_5M) * ATR_TO_STD
    if sigma is None:
        return None
    return _clamp(sigma, SIGMA_FLOOR_PCT, SIGMA_CEIL_PCT)


def regime_target_days(regime: str, confidence: float) -> float:
    """Regime-aware cycle-duration target, de-weighted toward T_CENTER when the
    regime call is low-confidence (anti-whipsaw)."""
    base_t = T_REGIME.get(regime, T_CENTER)
    c = _clamp(_f(confidence) or 0.5, 0.0, 1.0)
    conf_w = _clamp((c - CONF_FLOOR) / (CONF_FULL - CONF_FLOOR), 0.0, 1.0)
    t = T_CENTER + (base_t - T_CENTER) * conf_w
    return _clamp(t, MIN_DAYS, MAX_DAYS)


def favorable_excursion_pct(sigma_d: float, t_days: float) -> float:
    """G(T) = σ_d · sqrt(2T/π) — expected max favorable excursion over T days."""
    t = _clamp(t_days, MIN_DAYS, MAX_DAYS)
    return sigma_d * C_EXCURSION * math.sqrt(t)


def _overrun_adjust(
    t_target: float, span_frac: float, recent_days: Sequence[float]
) -> tuple:
    """Closed-loop feedback from realized cycle durations.

    * median > MAX_DAYS  → cycles get stuck → WIDEN the grid span (deeper DCA →
      lower average cost → next cycle reaches take-profit sooner). Owner choice:
      "sadece sonraki turu genişlet". We do NOT shrink the take-profit here.
    * median < MIN_DAYS  → churning too fast (fee bleed) → lengthen the target
      so G grows and the cycle banks a bigger, fee-worthy move.
    Returns (t_target', span_frac', reason|None).
    """
    med = _median(list(recent_days or []))
    if med is None or med <= 0:
        return t_target, span_frac, None
    if med > MAX_DAYS:
        widen = _clamp(med / MAX_DAYS, 1.0, 1.5)
        sf = _clamp(span_frac * widen, GRID_SPAN_FRAC, GRID_SPAN_FRAC_MAX)
        return t_target, sf, (
            f"overrun: son turlar medyan {med:.1f}g > {MAX_DAYS:.0f}g → grid genişletildi "
            f"(span×{widen:.2f}→{sf:.2f})"
        )
    if med < MIN_DAYS:
        slow = _clamp(MIN_DAYS / med, 1.0, 2.0)
        t = _clamp(t_target * slow, MIN_DAYS, MAX_DAYS)
        return t, span_frac, (
            f"churn: son turlar medyan {med:.2f}g < {MIN_DAYS:.0f}g → hedef uzatıldı "
            f"({t_target:.1f}→{t:.1f}g)"
        )
    return t_target, span_frac, None


def compute(
    features: Any,
    regime: str,
    confidence: float,
    recent_cycle_days: Optional[Sequence[float]] = None,
) -> DurationSizing:
    """Pure duration-targeted sizing. Never raises; on missing volatility returns
    `ok=False` with neutral numbers so the caller keeps its own fallback."""
    reasons: List[str] = []
    sigma = daily_vol_pct(features)
    if sigma is None:
        return DurationSizing(
            sigma_d_pct=0.0,
            t_target_days=T_CENTER,
            favorable_excursion_pct=0.0,
            grid_span_pct=0.0,
            span_frac=GRID_SPAN_FRAC,
            profit_exit_rise_pct=TP_RISE_BOUNDS[0],
            profit_exit_drop_pct=TP_DROP_BOUNDS[0],
            profit_reentry_drop_pct=REENTRY_DROP_BOUNDS[0],
            profit_reentry_rise_pct=REENTRY_RISE_BOUNDS[0],
            sell_trailing_base_pct=TRAIL_BOUNDS[0],
            buy_trailing_base_pct=TRAIL_BOUNDS[0],
            ok=False,
            reasons=["duration: ATR yok → nötr sizing (fallback)"],
        )

    t_target = regime_target_days(regime, confidence)
    span_frac = GRID_SPAN_FRAC
    t_target, span_frac, fb_reason = _overrun_adjust(
        t_target, span_frac, recent_cycle_days or []
    )
    if fb_reason:
        reasons.append(fb_reason)

    g = favorable_excursion_pct(sigma, t_target)
    grid_span = span_frac * g

    tp_rise = _clamp(g, *TP_RISE_BOUNDS)
    # trailing is anchored to the *first* grid step (≈ grid_span / typical n=3);
    # the caller re-derives the exact per-step trailing once it knows the grid
    # count, but a sensible default keeps standalone callers correct.
    first_step_guess = grid_span / 3.0
    trail_base = _clamp(TRAIL_FRAC * max(first_step_guess, 0.15), *TRAIL_BOUNDS)
    tp_drop = _clamp(max(TP_DROP_BOUNDS[0], TP_DROP_FRAC * trail_base), *TP_DROP_BOUNDS)
    re_drop = _clamp(g, *REENTRY_DROP_BOUNDS)
    re_rise = _clamp(max(REENTRY_RISE_BOUNDS[0], REENTRY_RISE_FRAC * trail_base), *REENTRY_RISE_BOUNDS)

    reasons.append(
        f"duration: σ_d≈{sigma:.2f}%/g · T*={t_target:.1f}g → G={g:.2f}% "
        f"(tahmini tur≈{t_target:.1f}g, hedef [{MIN_DAYS:.0f}-{MAX_DAYS:.0f}])"
    )
    reasons.append(
        f"distances: grid_span={grid_span:.2f}% tp_rise={tp_rise:.2f}% "
        f"trail≈{trail_base:.2f}% reentry_drop={re_drop:.2f}%"
    )

    return DurationSizing(
        sigma_d_pct=sigma,
        t_target_days=t_target,
        favorable_excursion_pct=g,
        grid_span_pct=grid_span,
        span_frac=span_frac,
        profit_exit_rise_pct=tp_rise,
        profit_exit_drop_pct=tp_drop,
        profit_reentry_drop_pct=re_drop,
        profit_reentry_rise_pct=re_rise,
        sell_trailing_base_pct=trail_base,
        buy_trailing_base_pct=trail_base,
        ok=True,
        reasons=reasons,
    )


def predicted_days(sigma_d: float, favorable_excursion: float) -> float:
    """Inverse of G(T): T ≈ (G / (c·σ_d))² — for logging / sanity only."""
    if sigma_d <= 0:
        return float("inf")
    return (favorable_excursion / (C_EXCURSION * sigma_d)) ** 2
