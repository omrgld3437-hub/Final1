"""
Pure technical indicators for Dynamic Mode.

All functions are SIDE-EFFECT FREE and take plain candle lists. A "candle" is a
dict with keys: t (open-time ms), o, h, l, c, v (floats). Input order: oldest
first, latest last.

Return semantics:
  * Return None when there is not enough data (callers MUST handle None).
  * Never raise on bad input; clamp/skip silently. Indicators run on a tick path.
"""

from __future__ import annotations
import math
from typing import Iterable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _closes(candles: Sequence[dict]) -> List[float]:
    return [float(c["c"]) for c in candles if c.get("c") is not None]


def _highs(candles: Sequence[dict]) -> List[float]:
    return [float(c["h"]) for c in candles if c.get("h") is not None]


def _lows(candles: Sequence[dict]) -> List[float]:
    return [float(c["l"]) for c in candles if c.get("l") is not None]


def _volumes(candles: Sequence[dict]) -> List[float]:
    return [float(c.get("v") or 0.0) for c in candles]


def _safe_mean(xs: Iterable[float]) -> Optional[float]:
    xs = list(xs)
    if not xs:
        return None
    return sum(xs) / len(xs)


def _safe_stdev(xs: Iterable[float]) -> Optional[float]:
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) if var >= 0 else None


# ---------------------------------------------------------------------------
# EMA — building block for trend slope and smoothing
# ---------------------------------------------------------------------------


def ema(values: Sequence[float], period: int) -> Optional[List[float]]:
    """Classic EMA. Returns None if data is shorter than period."""
    if not values or period <= 1 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    out: List[float] = []
    # Seed with SMA of first `period` values
    sma_seed = sum(values[:period]) / period
    out.append(sma_seed)
    for v in values[period:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def ema_last(values: Sequence[float], period: int) -> Optional[float]:
    series = ema(values, period)
    return series[-1] if series else None


# ---------------------------------------------------------------------------
# ATR — average true range (primary volatility input)
# ---------------------------------------------------------------------------


def true_ranges(candles: Sequence[dict]) -> List[float]:
    """TR_i = max(H-L, |H - C_prev|, |L - C_prev|)."""
    tr: List[float] = []
    prev_close: Optional[float] = None
    for c in candles:
        try:
            h = float(c["h"])
            lo = float(c["l"])
            cl = float(c["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if prev_close is None:
            tr.append(h - lo)
        else:
            tr.append(max(h - lo, abs(h - prev_close), abs(lo - prev_close)))
        prev_close = cl
    return tr


def atr(candles: Sequence[dict], period: int = 14) -> Optional[float]:
    """Wilder ATR over the last `period` candles. None if not enough data."""
    tr = true_ranges(candles)
    if len(tr) < period:
        return None
    # Wilder smoothing
    atr_val = sum(tr[:period]) / period
    for x in tr[period:]:
        atr_val = (atr_val * (period - 1) + x) / period
    return atr_val if atr_val >= 0 else None


def atr_pct(candles: Sequence[dict], period: int = 14) -> Optional[float]:
    """ATR as percentage of last close (0..100)."""
    a = atr(candles, period)
    closes = _closes(candles)
    if a is None or not closes or closes[-1] <= 0:
        return None
    return (a / closes[-1]) * 100.0


# ---------------------------------------------------------------------------
# Bollinger Band Width — squeeze / expansion detector
# ---------------------------------------------------------------------------


def bollinger_band_width(
    candles: Sequence[dict], period: int = 20, mult: float = 2.0
) -> Optional[float]:
    """BBW = (upper - lower) / mid, expressed as percentage. None if insufficient."""
    closes = _closes(candles)
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    sd = _safe_stdev(window)
    if sd is None or mid <= 0:
        return None
    upper = mid + mult * sd
    lower = mid - mult * sd
    return (upper - lower) / mid * 100.0


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def rsi(candles: Sequence[dict], period: int = 14) -> Optional[float]:
    closes = _closes(candles)
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# ADX — trend strength
# ---------------------------------------------------------------------------


def adx(candles: Sequence[dict], period: int = 14) -> Optional[float]:
    """Wilder ADX. Returns None if not enough data."""
    n = len(candles)
    if n < period * 2 + 1:
        return None
    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)
    if not (len(highs) == len(lows) == len(closes) == n):
        return None
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    tr_list: List[float] = []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr_list.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    if len(tr_list) < period:
        return None
    atr_s = sum(tr_list[:period])
    plus_s = sum(plus_dm[:period])
    minus_s = sum(minus_dm[:period])
    dx_values: List[float] = []
    for i in range(period, len(tr_list)):
        atr_s = atr_s - (atr_s / period) + tr_list[i]
        plus_s = plus_s - (plus_s / period) + plus_dm[i]
        minus_s = minus_s - (minus_s / period) + minus_dm[i]
        if atr_s <= 0:
            continue
        plus_di = 100.0 * plus_s / atr_s
        minus_di = 100.0 * minus_s / atr_s
        denom = plus_di + minus_di
        if denom <= 0:
            continue
        dx = 100.0 * abs(plus_di - minus_di) / denom
        dx_values.append(dx)
    if len(dx_values) < period:
        return None
    adx_val = sum(dx_values[:period]) / period
    for x in dx_values[period:]:
        adx_val = (adx_val * (period - 1) + x) / period
    return adx_val


# ---------------------------------------------------------------------------
# Realized volatility (log-return std, NOT annualized; we just need a relative)
# ---------------------------------------------------------------------------


def realized_vol_pct(candles: Sequence[dict], lookback: int = 30) -> Optional[float]:
    """Stdev of log returns over the last `lookback` candles, ×100."""
    closes = _closes(candles)
    if len(closes) < lookback + 1:
        return None
    rets: List[float] = []
    for i in range(len(closes) - lookback, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev > 0 and cur > 0:
            rets.append(math.log(cur / prev))
    sd = _safe_stdev(rets)
    return (sd * 100.0) if sd is not None else None


# ---------------------------------------------------------------------------
# Trend slope: normalized EMA-slope between two recent EMA values
# ---------------------------------------------------------------------------


def ema_slope_pct(
    values: Sequence[float], period: int = 20, lookback: int = 5
) -> Optional[float]:
    """(EMA_now - EMA_{lookback ago}) / EMA_{lookback ago} × 100. None if insufficient."""
    series = ema(values, period)
    if series is None or len(series) < lookback + 1:
        return None
    a = series[-1]
    b = series[-1 - lookback]
    if b <= 0:
        return None
    return (a - b) / b * 100.0


# ---------------------------------------------------------------------------
# Volume z-score — relative volume spike detector
# ---------------------------------------------------------------------------


def volume_zscore(candles: Sequence[dict], lookback: int = 20) -> Optional[float]:
    vols = _volumes(candles)
    if len(vols) < lookback + 1:
        return None
    window = vols[-lookback - 1 : -1]  # exclude the current (still-forming) candle
    m = _safe_mean(window)
    sd = _safe_stdev(window)
    if m is None or sd is None or sd <= 0:
        return None
    return (vols[-1] - m) / sd


# ---------------------------------------------------------------------------
# Candle body / wick ratio — chop detector
# ---------------------------------------------------------------------------


def avg_wick_body_ratio(candles: Sequence[dict], lookback: int = 10) -> Optional[float]:
    """High wick ratio suggests chop / fake moves. Returns None if data thin."""
    if len(candles) < lookback:
        return None
    ratios: List[float] = []
    for c in candles[-lookback:]:
        try:
            h = float(c["h"])
            lo = float(c["l"])
            o = float(c["o"])
            cl = float(c["c"])
        except (KeyError, TypeError, ValueError):
            continue
        body = abs(cl - o)
        rng = h - lo
        if rng <= 0:
            continue
        wick = rng - body
        ratios.append(wick / rng)
    return _safe_mean(ratios)
