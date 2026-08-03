"""Technical indicator computation for Dynamic Param Score Engine."""

from __future__ import annotations

import math
import time
from typing import List, Optional, Sequence

from app.botengine.dynamic import indicators as dyn_ind
from app.services.dynamic_param_score.models import (
    BtcReferenceData,
    Candle,
    IndicatorSnapshot,
    MarketDataBundle,
    PortfolioState,
)
from app.services.dynamic_param_score.utils import clamp, normalize_score


def _candles_to_dicts(candles: Optional[Sequence[Candle]]) -> List[dict]:
    if not candles:
        return []
    return [{"t": c.t, "o": c.o, "h": c.h, "l": c.l, "c": c.c, "v": c.v} for c in candles]


def _returns_pct(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    a, b = closes[-n - 1], closes[-1]
    if a <= 0:
        return None
    return (b - a) / a * 100.0


def _realized_vol(closes: List[float], window: int) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    rets = []
    for i in range(-window, 0):
        if closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * 100.0 if var >= 0 else None


def _max_gap_ms(candles: List[Candle], expected_ms: int) -> int:
    if len(candles) < 2:
        return 0
    gaps = [candles[i].t - candles[i - 1].t for i in range(1, len(candles))]
    return max((g - expected_ms for g in gaps if g > expected_ms * 1.5), default=0)


def _hh_ll(candles: List[dict], lookback: int = 20) -> tuple[Optional[bool], Optional[bool]]:
    if len(candles) < lookback:
        return None, None
    seg = candles[-lookback:]
    highs = [c["h"] for c in seg]
    lows = [c["l"] for c in seg]
    mid = lookback // 2
    hh = max(highs[mid:]) > max(highs[:mid])
    ll = min(lows[mid:]) < min(lows[:mid])
    return hh, ll


def _consecutive_red(candles: List[dict], max_n: int = 10) -> float:
    if not candles:
        return 0.0
    n = 0
    for c in reversed(candles[-max_n:]):
        if c["c"] < c["o"]:
            n += 1
        else:
            break
    return n / max_n


def _drawdown_from_high(closes: List[float]) -> Optional[float]:
    if not closes:
        return None
    peak = max(closes)
    cur = closes[-1]
    if peak <= 0:
        return None
    return (peak - cur) / peak * 100.0


def _crash_velocity(closes: List[float], window: int = 6) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    rets = []
    for i in range(-window, 0):
        if closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100.0)
    if not rets:
        return None
    return min(rets)


def _volume_consistency(vols: List[float]) -> Optional[float]:
    if len(vols) < 5:
        return None
    m = sum(vols) / len(vols)
    if m <= 0:
        return 0.0
    var = sum((v - m) ** 2 for v in vols) / len(vols)
    cv = math.sqrt(var) / m
    return clamp(1.0 - min(cv, 2.0) / 2.0, 0.0, 1.0)


def _z_score(closes: List[float], window: int = 20) -> Optional[float]:
    if len(closes) < window:
        return None
    seg = closes[-window:]
    m = sum(seg) / len(seg)
    var = sum((x - m) ** 2 for x in seg) / len(seg)
    if var <= 0:
        return 0.0
    return (closes[-1] - m) / math.sqrt(var)


def _mean_reversion_ratio(closes: List[float], window: int = 30) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    crossings = 0
    m = sum(closes[-window:]) / window
    for i in range(-window, 0):
        if (closes[i] - m) * (closes[i - 1] - m) < 0:
            crossings += 1
    return crossings / window


def _range_stability(candles: List[dict], window: int = 20) -> Optional[float]:
    if len(candles) < window:
        return None
    ranges = [(c["h"] - c["l"]) / c["c"] * 100.0 for c in candles[-window:] if c["c"] > 0]
    if not ranges:
        return None
    m = sum(ranges) / len(ranges)
    var = sum((r - m) ** 2 for r in ranges) / len(ranges)
    cv = math.sqrt(var) / m if m > 0 else 1.0
    return clamp(1.0 - min(cv, 1.5), 0.0, 1.0)


def _vol_percentile(atr_pct: Optional[float], hist_atrs: List[float]) -> Optional[float]:
    if atr_pct is None or not hist_atrs:
        return None
    below = sum(1 for a in hist_atrs if a <= atr_pct)
    return below / len(hist_atrs) * 100.0


def _atr_pct_history(
    candles: List[dict], *, period: int = 14, first_index: int = 20
) -> List[float]:
    """Return the legacy expanding Wilder-ATR% series in O(n), not O(n²).

    The old implementation called ``atr_pct(candles[:i])`` for every prefix.
    With the live 2,016-candle window that rebuilt roughly two million true
    ranges twice per V6 decision and made one decision take 15–30 seconds.
    Wilder ATR is recursive, so the identical valid-candle result can be
    produced in one pass.
    """
    if len(candles) < period:
        return []
    trs = dyn_ind.true_ranges(candles)
    if len(trs) != len(candles) or len(trs) < period:
        # Malformed rows are not expected from Binance, but retain the precise
        # legacy semantics for custom callers rather than guessing alignment.
        return [
            value
            for i in range(first_index, len(candles))
            for value in [dyn_ind.atr_pct(candles[: i + 1], period)]
            if value is not None and value > 0
        ]
    atr_value = sum(trs[:period]) / period
    out: List[float] = []
    for i in range(period - 1, len(candles)):
        if i >= period:
            atr_value = (atr_value * (period - 1) + trs[i]) / period
        if i < first_index:
            continue
        close = float(candles[i].get("c") or 0.0)
        value = (atr_value / close * 100.0) if close > 0 else 0.0
        if value > 0:
            out.append(value)
    return out


def compute_indicators(
    market: MarketDataBundle,
    portfolio: PortfolioState,
) -> IndicatorSnapshot:
    snap = IndicatorSnapshot()
    c5 = _candles_to_dicts(market.candles_5m)
    c15 = _candles_to_dicts(market.candles_15m)
    c1h = _candles_to_dicts(market.candles_1h)
    closes_5m = dyn_ind._closes(c5) if c5 else []
    closes_1h = dyn_ind._closes(c1h) if c1h else []
    closes_15m = dyn_ind._closes(c15) if c15 else []

    snap.candle_count_5m = len(c5)
    snap.candle_count_15m = len(c15)
    snap.candle_count_1h = len(c1h)
    snap.data_gap_max_ms = max(
        _max_gap_ms(list(market.candles_5m or []), 300_000),
        _max_gap_ms(list(market.candles_1h or []), 3_600_000),
    )
    if c5:
        # ``market_timestamp`` canlı akışta "şimdi", geçmiş-testinde ise kararın
        # verildiği simülasyon zamanıdır. Duvar saatini doğrudan kullanmak geçmiş
        # mumları hatalı biçimde stale sayıp V6'yı NO_DATA/WAIT'e kilitliyordu.
        # Alanı olmayan eski çağrılarda canlı davranış aynen korunur.
        as_of_ms = int(market.market_timestamp or time.time() * 1000)
        snap.data_freshness_sec = max(0.0, (as_of_ms - c5[-1]["t"]) / 1000.0)
    snap.price_valid = market.ticker_price > 0

    # Trend
    snap.ema20_5m = dyn_ind.ema_last(closes_5m, 20) if closes_5m else None
    snap.ema50_5m = dyn_ind.ema_last(closes_5m, 50) if closes_5m else None
    snap.ema200_1h = dyn_ind.ema_last(closes_1h, 200) if closes_1h else None
    snap.ema20_slope_5m = dyn_ind.ema_slope_pct(closes_5m, 20, 5) if closes_5m else None
    snap.ema50_slope_5m = dyn_ind.ema_slope_pct(closes_5m, 50, 5) if closes_5m else None
    if snap.ema200_1h and market.ticker_price > 0:
        snap.price_vs_ema200_pct = (market.ticker_price - snap.ema200_1h) / snap.ema200_1h * 100.0
    snap.adx_1h = dyn_ind.adx(c1h, 14) if c1h else None
    hh, ll = _hh_ll(c5) if c5 else (None, None)
    snap.higher_highs = hh
    snap.lower_lows = ll

    # Volatility
    snap.atr14_pct_5m = dyn_ind.atr_pct(c5, 14) if c5 else None
    snap.atr14_pct_1h = dyn_ind.atr_pct(c1h, 14) if c1h else None
    snap.realized_vol_24h = _realized_vol(closes_5m, min(288, len(closes_5m) - 1)) if closes_5m else None
    snap.realized_vol_7d = _realized_vol(closes_1h, min(168, len(closes_1h) - 1)) if closes_1h else None
    if snap.atr14_pct_5m and c5:
        hist = _atr_pct_history(c5, period=14, first_index=20)
        snap.volatility_percentile = _vol_percentile(snap.atr14_pct_5m, hist)
    if c5:
        snap.high_low_range_pct = (c5[-1]["h"] - c5[-1]["l"]) / c5[-1]["c"] * 100.0 if c5[-1]["c"] > 0 else None

    # Range
    snap.bb_width_5m = dyn_ind.bollinger_band_width(c5, 20) if c5 else None
    if c5 and len(closes_5m) >= 20:
        window = closes_5m[-20:]
        mid = sum(window) / 20
        sd = dyn_ind._safe_stdev(window)
        if sd and sd > 0 and mid > 0:
            upper = mid + 2 * sd
            lower = mid - 2 * sd
            snap.price_in_bb = (closes_5m[-1] - lower) / (upper - lower) if upper > lower else 0.5
    snap.mean_reversion_ratio = _mean_reversion_ratio(closes_5m) if closes_5m else None
    snap.z_score_5m = _z_score(closes_5m) if closes_5m else None
    snap.range_stability = _range_stability(c5) if c5 else None

    # Momentum
    snap.rsi14_5m = dyn_ind.rsi(c5, 14) if c5 else None
    snap.rsi14_1h = dyn_ind.rsi(c1h, 14) if c1h else None
    snap.roc_5m = _returns_pct(closes_5m, 12) if closes_5m else None
    snap.return_1h_pct = _returns_pct(closes_5m, 12) if closes_5m else None
    snap.return_4h_pct = _returns_pct(closes_15m, 16) if closes_15m else _returns_pct(closes_5m, 48) if closes_5m else None
    snap.return_24h_pct = _returns_pct(closes_1h, 24) if closes_1h else None

    # Liquidity
    snap.quote_volume_24h = market.quote_volume_24h
    if c5:
        vols = dyn_ind._volumes(c5[-48:])
        snap.volume_consistency = _volume_consistency(vols)
        snap.zero_volume_ratio = sum(1 for v in vols if v <= 0) / len(vols)
        m = sum(vols) / len(vols) if vols else 0
        snap.volume_spike_abnormality = max(vols) / m if m > 0 else 1.0

    # Spread
    if market.orderbook_top:
        bid = float(market.orderbook_top.get("bid") or 0)
        ask = float(market.orderbook_top.get("ask") or 0)
        if bid > 0 and ask > bid:
            snap.orderbook_spread_pct = (ask - bid) / ((ask + bid) / 2) * 100.0
    snap.total_friction_pct = snap.orderbook_spread_pct or 0.05

    # Drawdown
    if closes_1h:
        snap.drawdown_7d_pct = _drawdown_from_high(closes_1h[-168:]) if len(closes_1h) >= 24 else None
        snap.drawdown_30d_pct = (
            _drawdown_from_high(closes_1h[-168:])
            if len(closes_1h) >= 168
            else _drawdown_from_high(closes_1h)
        )
    snap.crash_velocity = _crash_velocity(closes_5m) if closes_5m else None
    snap.consecutive_red_pressure = _consecutive_red(c5) if c5 else 0.0

    # BTC
    btc = market.btc_reference_data
    if btc:
        snap.btc_return_1h = btc.return_1h_pct
        snap.btc_return_4h = btc.return_4h_pct
        snap.btc_return_24h = btc.return_24h_pct
        if btc.ema200_1h and btc.price:
            snap.btc_below_ema200 = btc.price < btc.ema200_1h
        snap.btc_crash_velocity = btc.crash_velocity

    return snap


def score_data_quality(ind: IndicatorSnapshot) -> int:
    score = 100
    if not ind.price_valid:
        score -= 50
    if ind.candle_count_5m < 50:
        score -= 30
    elif ind.candle_count_5m < 100:
        score -= 10
    if ind.candle_count_1h < 50:
        score -= 15
    if ind.data_gap_max_ms > 600_000:
        score -= 20
    if ind.data_freshness_sec > 600:
        score -= 15
    return int(clamp(score, 0, 100))


def score_liquidity(ind: IndicatorSnapshot) -> int:
    qv = ind.quote_volume_24h or 0
    if qv <= 0:
        return 10
    if qv >= 50_000_000:
        base = 95
    elif qv >= 10_000_000:
        base = 85
    elif qv >= 1_000_000:
        base = 70
    elif qv >= 100_000:
        base = 50
    else:
        base = 25
    if ind.volume_consistency is not None:
        base = int(base * (0.6 + 0.4 * ind.volume_consistency))
    if ind.zero_volume_ratio and ind.zero_volume_ratio > 0.1:
        base -= 15
    return int(clamp(base, 0, 100))


def score_spread(ind: IndicatorSnapshot, fee_slippage: float) -> int:
    spread = ind.orderbook_spread_pct if ind.orderbook_spread_pct is not None else fee_slippage
    if spread <= 0.03:
        return 95
    if spread <= 0.08:
        return 80
    if spread <= 0.15:
        return 60
    if spread <= 0.30:
        return 40
    if spread <= 0.50:
        return 25
    return 10


def score_exposure_safety(portfolio: PortfolioState) -> int:
    exp = portfolio.current_base_exposure_frac
    if exp <= 0.35:
        base = 90
    elif exp <= 0.55:
        base = 75
    elif exp <= 0.70:
        base = 55
    elif exp <= 0.85:
        base = 30
    else:
        base = 10
    if portfolio.open_buy_orders_count > 3:
        base -= 10
    if portfolio.unrealized_pnl_pct is not None and portfolio.unrealized_pnl_pct < -5:
        base -= 15
    return int(clamp(base, 0, 100))
