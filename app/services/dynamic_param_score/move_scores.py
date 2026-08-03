"""Pump / dump / fake-breakout / fake-bounce scores for V6 live path.

Score range: 0–100 (None = insufficient data). Thresholds used by adjusters /
classifier are SCORE_HIGH (70) and SCORE_MEDIUM (40). Formulas use only
indicators already computed from the same candle window — no extra market I/O.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from app.services.dynamic_param_score.utils import clamp, normalize_score

# Shared thresholds (single source — do not duplicate in adjusters/classifier)
SCORE_MIN = 0.0
SCORE_MAX = 100.0
SCORE_HIGH = 70.0
SCORE_MEDIUM = 40.0

# Component floors — missing components must not invent a confident score
_MIN_CORE_COMPONENTS = 2


def _finite(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _clamp_score(v: float) -> float:
    return float(clamp(v, SCORE_MIN, SCORE_MAX))


def _avg(parts: List[float]) -> Optional[float]:
    if len(parts) < _MIN_CORE_COMPONENTS:
        return None
    return sum(parts) / len(parts)


def _wick_ratios(candle: Dict[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    o = _finite(candle.get("o"))
    h = _finite(candle.get("h"))
    l = _finite(candle.get("l"))
    c = _finite(candle.get("c"))
    if None in (o, h, l, c) or h is None or l is None or o is None or c is None:
        return None, None, None
    rng = h - l
    if rng <= 0:
        return 0.0, 0.0, 0.0
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return upper / rng, lower / rng, body / rng


def compute_pump_score(
    *,
    roc_5m: Optional[float],
    return_1h_pct: Optional[float],
    volume_spike: Optional[float],
    rsi_5m: Optional[float],
    z_score: Optional[float],
    bb_position: Optional[float],
    ema20_slope: Optional[float],
) -> Optional[float]:
    """Directional upside acceleration score (0–100) or None if under-specified."""
    roc = _finite(roc_5m)
    ret1 = _finite(return_1h_pct)
    parts: List[float] = []
    if roc is not None:
        parts.append(normalize_score(roc, 0.3, 4.0))
    if ret1 is not None:
        parts.append(normalize_score(ret1, 0.5, 6.0))
    vs = _finite(volume_spike)
    if vs is not None:
        parts.append(normalize_score(vs, 1.5, 5.0))
    rsi = _finite(rsi_5m)
    if rsi is not None:
        parts.append(normalize_score(rsi, 55.0, 85.0))
    z = _finite(z_score)
    if z is not None:
        parts.append(normalize_score(z, 0.5, 2.5))
    bb = _finite(bb_position)
    if bb is not None:
        parts.append(normalize_score(bb, 0.55, 0.95))
    slope = _finite(ema20_slope)
    if slope is not None:
        parts.append(normalize_score(slope, 0.05, 0.40))

    avg = _avg(parts)
    if avg is None:
        return None

    # Require short-term upside; pure hourly drift alone is not a pump.
    if roc is not None and roc <= 0:
        avg *= 0.35
    if ret1 is not None and ret1 < 0 and (roc or 0) > 0:
        avg *= 0.55  # short spike against hourly drift → weaker pump confidence

    # Single-bar dampener: huge roc without volume confirmation
    if roc is not None and roc >= 3.0 and (vs is None or vs < 1.8):
        avg *= 0.65

    return _clamp_score(avg)


def compute_dump_score(
    *,
    roc_5m: Optional[float],
    return_1h_pct: Optional[float],
    volume_spike: Optional[float],
    rsi_5m: Optional[float],
    z_score: Optional[float],
    bb_position: Optional[float],
    ema20_slope: Optional[float],
) -> Optional[float]:
    """Directional downside acceleration score (0–100) or None if under-specified."""
    roc = _finite(roc_5m)
    ret1 = _finite(return_1h_pct)
    parts: List[float] = []
    if roc is not None:
        parts.append(normalize_score(-roc, 0.3, 4.0))
    if ret1 is not None:
        parts.append(normalize_score(-ret1, 0.5, 6.0))
    vs = _finite(volume_spike)
    if vs is not None:
        parts.append(normalize_score(vs, 1.5, 5.0))
    rsi = _finite(rsi_5m)
    if rsi is not None:
        parts.append(normalize_score(100.0 - rsi, 55.0, 85.0))
    z = _finite(z_score)
    if z is not None:
        parts.append(normalize_score(-z, 0.5, 2.5))
    bb = _finite(bb_position)
    if bb is not None:
        parts.append(normalize_score(1.0 - bb, 0.55, 0.95))
    slope = _finite(ema20_slope)
    if slope is not None:
        parts.append(normalize_score(-slope, 0.05, 0.40))

    avg = _avg(parts)
    if avg is None:
        return None

    if roc is not None and roc >= 0:
        avg *= 0.35
    if ret1 is not None and ret1 > 0 and (roc or 0) < 0:
        avg *= 0.55

    if roc is not None and roc <= -3.0 and (vs is None or vs < 1.8):
        avg *= 0.65

    return _clamp_score(avg)


def resolve_pump_dump_conflict(
    pump: Optional[float],
    dump: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """If both sides are high, keep the dominant side and suppress the other."""
    p = _finite(pump)
    d = _finite(dump)
    if p is None or d is None:
        return p, d
    if p >= SCORE_MEDIUM and d >= SCORE_MEDIUM:
        if p >= d:
            return p, _clamp_score(d * 0.35)
        return _clamp_score(p * 0.35), d
    return p, d


def compute_fake_bounce_score(
    *,
    roc_5m: Optional[float],
    return_1h_pct: Optional[float],
    rsi_5m: Optional[float],
    bb_position: Optional[float],
    volume_spike: Optional[float],
    lower_lows: Optional[bool],
) -> Optional[float]:
    """Weak bounce inside a down structure (0–100) or None."""
    roc = _finite(roc_5m)
    ret1 = _finite(return_1h_pct)
    parts: List[float] = []
    if roc is not None and ret1 is not None:
        # Short green against hourly red
        if roc > 0 and ret1 < 0:
            parts.append(normalize_score(roc, 0.2, 2.5))
            parts.append(normalize_score(-ret1, 0.5, 5.0))
        else:
            parts.append(10.0)
    rsi = _finite(rsi_5m)
    if rsi is not None:
        # Bounce from oversold without reclaiming strength
        parts.append(normalize_score(45.0 - abs(rsi - 40.0), 0.0, 20.0))
    bb = _finite(bb_position)
    if bb is not None:
        parts.append(normalize_score(0.45 - abs(bb - 0.35), 0.0, 0.35) if bb < 0.55 else 15.0)
    vs = _finite(volume_spike)
    if vs is not None and vs < 1.5:
        parts.append(55.0)
    elif vs is not None:
        parts.append(25.0)
    if lower_lows is True:
        parts.append(70.0)
    avg = _avg(parts)
    return None if avg is None else _clamp_score(avg)


def compute_fake_breakout_score(
    *,
    candles_5m: Sequence[Dict[str, Any]],
    volume_spike: Optional[float],
    roc_5m: Optional[float],
    return_1h_pct: Optional[float],
    bb_position: Optional[float],
    z_score: Optional[float],
    range_stability: Optional[float],
) -> Optional[float]:
    """Failed range breakout score (0–100) or None if under-specified."""
    if len(candles_5m) < 8:
        return None

    window = list(candles_5m[-20:]) if len(candles_5m) >= 20 else list(candles_5m)
    if len(window) < 8:
        return None

    prior = window[:-3]
    recent = window[-3:]
    if len(prior) < 4:
        return None

    highs = [_finite(c.get("h")) for c in prior]
    lows = [_finite(c.get("l")) for c in prior]
    if any(v is None for v in highs + lows):
        return None
    assert all(v is not None for v in highs + lows)
    range_high = max(highs)  # type: ignore[arg-type]
    range_low = min(lows)  # type: ignore[arg-type]
    if range_high <= range_low:
        return None

    last = recent[-1]
    last_c = _finite(last.get("c"))
    last_h = _finite(last.get("h"))
    last_l = _finite(last.get("l"))
    if None in (last_c, last_h, last_l):
        return None

    pierced_up = last_h is not None and last_h > range_high
    pierced_down = last_l is not None and last_l < range_low
    if not pierced_up and not pierced_down:
        # Still allow score from wick+weak follow-through near band edge
        bb = _finite(bb_position)
        if bb is None or (0.15 < bb < 0.85):
            return _clamp_score(15.0)

    parts: List[float] = []

    # Rejection: pierce then close back inside range
    if pierced_up and last_c is not None and last_c < range_high:
        parts.append(85.0)
    elif pierced_down and last_c is not None and last_c > range_low:
        parts.append(85.0)
    elif pierced_up or pierced_down:
        parts.append(40.0)

    upper_w, lower_w, body_r = _wick_ratios(last)
    if pierced_up and upper_w is not None:
        parts.append(normalize_score(upper_w, 0.35, 0.75))
        if body_r is not None:
            parts.append(normalize_score(1.0 - body_r, 0.3, 0.85))
    if pierced_down and lower_w is not None:
        parts.append(normalize_score(lower_w, 0.35, 0.75))
        if body_r is not None:
            parts.append(normalize_score(1.0 - body_r, 0.3, 0.85))

    vs = _finite(volume_spike)
    if vs is not None:
        # Weak volume on break attempt → more fake
        parts.append(normalize_score(2.2 - vs, 0.0, 1.5) if vs < 2.2 else 15.0)

    roc = _finite(roc_5m)
    ret1 = _finite(return_1h_pct)
    if pierced_up and roc is not None and roc < 0:
        parts.append(70.0)
    if pierced_down and roc is not None and roc > 0:
        parts.append(70.0)
    if pierced_up and ret1 is not None and ret1 < 0.3:
        parts.append(55.0)
    if pierced_down and ret1 is not None and ret1 > -0.3:
        parts.append(55.0)

    # Follow-through: last 3 closes not continuing outside
    closes = [_finite(c.get("c")) for c in recent]
    if pierced_up and all(c is not None for c in closes):
        if closes[-1] is not None and closes[-1] <= range_high:
            parts.append(75.0)
        elif closes[0] is not None and closes[-1] is not None and closes[-1] < closes[0]:
            parts.append(60.0)
    if pierced_down and all(c is not None for c in closes):
        if closes[-1] is not None and closes[-1] >= range_low:
            parts.append(75.0)
        elif closes[0] is not None and closes[-1] is not None and closes[-1] > closes[0]:
            parts.append(60.0)

    z = _finite(z_score)
    if z is not None and abs(z) >= 1.2 and (vs is None or vs < 2.0):
        parts.append(50.0)

    rstab = _finite(range_stability)
    if rstab is not None and rstab >= 0.45 and (pierced_up or pierced_down):
        parts.append(45.0)

    avg = _avg(parts)
    return None if avg is None else _clamp_score(avg)


def compute_move_scores(
    *,
    candles_5m: Sequence[Dict[str, Any]],
    roc_5m: Optional[float],
    return_1h_pct: Optional[float],
    volume_spike: Optional[float],
    rsi_5m: Optional[float],
    z_score: Optional[float],
    bb_position: Optional[float],
    ema20_slope: Optional[float],
    range_stability: Optional[float],
    lower_lows: Optional[bool],
) -> Dict[str, Optional[float]]:
    pump = compute_pump_score(
        roc_5m=roc_5m,
        return_1h_pct=return_1h_pct,
        volume_spike=volume_spike,
        rsi_5m=rsi_5m,
        z_score=z_score,
        bb_position=bb_position,
        ema20_slope=ema20_slope,
    )
    dump = compute_dump_score(
        roc_5m=roc_5m,
        return_1h_pct=return_1h_pct,
        volume_spike=volume_spike,
        rsi_5m=rsi_5m,
        z_score=z_score,
        bb_position=bb_position,
        ema20_slope=ema20_slope,
    )
    pump, dump = resolve_pump_dump_conflict(pump, dump)
    fake_bounce = compute_fake_bounce_score(
        roc_5m=roc_5m,
        return_1h_pct=return_1h_pct,
        rsi_5m=rsi_5m,
        bb_position=bb_position,
        volume_spike=volume_spike,
        lower_lows=lower_lows,
    )
    fake_breakout = compute_fake_breakout_score(
        candles_5m=candles_5m,
        volume_spike=volume_spike,
        roc_5m=roc_5m,
        return_1h_pct=return_1h_pct,
        bb_position=bb_position,
        z_score=z_score,
        range_stability=range_stability,
    )
    return {
        "pump_score": pump,
        "dump_score": dump,
        "fake_bounce_score": fake_bounce,
        "fake_breakout_score": fake_breakout,
    }
