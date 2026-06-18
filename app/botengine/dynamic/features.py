"""
Market-feature collector for Dynamic Mode.

Responsibilities:
  * Fetch klines (cached, async-safe, dual timeframe: 5m for short-term, 1h for trend).
  * Pull spread + 24h volume.
  * Compute volatility / trend / regime features in one place so callers get a
    flat, easy-to-log dict.

Failure policy:
  * Network or parser errors NEVER raise. We return a `MarketFeatures` with
    `data_fresh=False` and `error` populated. Callers must check `data_fresh`
    and, if False, freeze Dynamic Mode (fall back to last snapshot / manual cfg).
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from app.botengine.dynamic import indicators as ind

logger = logging.getLogger(__name__)


# Klines cache: small in-process TTL cache so multiple bots on the same symbol
# don't fan out duplicate REST calls. Cycle starts are infrequent enough that
# this cache adds zero risk.
_KLINES_CACHE: Dict[tuple, tuple] = {}  # (sym, interval, limit) -> (data, ts)
_KLINES_TTL = {
    "1m": 20.0,
    "5m": 60.0,
    "15m": 180.0,
    "1h": 600.0,
    "4h": 1200.0,
}


def _ttl_for(interval: str) -> float:
    return _KLINES_TTL.get((interval or "").lower(), 60.0)


@dataclass
class MarketFeatures:
    """Flat feature bag passed to regime classifier + strategy engine."""

    symbol: str
    price: float
    # Volatility
    atr_pct_5m: Optional[float] = None
    atr_pct_1h: Optional[float] = None
    bbw_5m: Optional[float] = None
    bbw_1h: Optional[float] = None
    realized_vol_5m: Optional[float] = None
    ret_5m_last: Optional[float] = None  # last CLOSED 5m return % (fast-drop signal)
    # Trend
    adx_1h: Optional[float] = None
    ema_slope_1h_pct: Optional[float] = None
    rsi_1h: Optional[float] = None
    rsi_5m: Optional[float] = None
    # Microstructure / volume
    spread_pct: Optional[float] = None
    spread_bps: Optional[float] = None  # spread_pct × 100 (leaderboard/UI key)
    volume_24h_usdt: Optional[float] = None
    volume_zscore_5m: Optional[float] = None
    wick_body_ratio_5m: Optional[float] = None
    # Meta
    data_fresh: bool = True
    fetched_at_ms: int = 0
    sources: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def _fetch_klines(symbol: str, interval: str, limit: int) -> Optional[List[dict]]:
    """Cached klines fetch using project's binance_spot.public_get_json."""
    key = (symbol.upper(), interval.lower(), int(limit))
    now = time.time()
    cached = _KLINES_CACHE.get(key)
    if cached and (now - cached[1] < _ttl_for(interval)):
        return cached[0]
    try:
        from app.services.binance_rest_log import rest_source
        from app.services.binance_spot import public_get_json

        with rest_source("dynamic_mode.klines"):
            data = await public_get_json(
                "/api/v3/klines",
                {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)},
                testnet=False,
            )
        if not isinstance(data, list) or not data:
            return cached[0] if cached else None
        parsed: List[dict] = []
        for c in data:
            try:
                parsed.append(
                    {
                        "t": int(c[0]),
                        "o": float(c[1]),
                        "h": float(c[2]),
                        "l": float(c[3]),
                        "c": float(c[4]),
                        "v": float(c[5]),
                    }
                )
            except (TypeError, ValueError, IndexError):
                continue
        if not parsed:
            return cached[0] if cached else None
        _KLINES_CACHE[key] = (parsed, now)
        if len(_KLINES_CACHE) > 256:
            # cheap eviction: drop oldest entry
            try:
                _KLINES_CACHE.pop(next(iter(_KLINES_CACHE)))
            except StopIteration:
                pass
        return parsed
    except Exception as e:
        logger.debug(
            "DYN_FEATURES_KLINES_FAIL symbol=%s interval=%s err=%s", symbol, interval, e
        )
        return cached[0] if cached else None


def _fetch_ticker_24h(symbol: str) -> Dict[str, Any]:
    try:
        from app.services.market_data import get_ticker_24h

        return get_ticker_24h(symbol) or {}
    except Exception as e:
        logger.debug("DYN_FEATURES_TICKER24H_FAIL symbol=%s err=%s", symbol, e)
        return {}


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def collect_features(symbol: str, last_price: float) -> MarketFeatures:
    """
    Build the feature set used by the regime classifier and strategy engine.

    Pull policy:
      * 5m klines x 120 (covers ATR/RSI/BBW comfortably).
      * 1h klines x 100 (covers ADX/EMA-slope).
      * 24h ticker for volume and bid/ask spread.

    Any of these may fail; we mark data_fresh=False if the core (5m or price)
    is missing. Partial data still produces a usable MarketFeatures with some
    fields = None, which downstream code treats defensively.
    """
    f = MarketFeatures(
        symbol=symbol.upper(),
        price=float(last_price or 0.0),
        fetched_at_ms=int(time.time() * 1000),
    )
    if not f.symbol or f.price <= 0:
        f.data_fresh = False
        f.error = "no_symbol_or_price"
        return f

    k5 = await _fetch_klines(f.symbol, "5m", 120)
    k1h = await _fetch_klines(f.symbol, "1h", 100)
    ticker = _fetch_ticker_24h(f.symbol)

    # If 5m is missing we cannot make a safe call — mark stale.
    if not k5 or len(k5) < 30:
        f.data_fresh = False
        f.error = "no_5m_klines"
        f.sources["k5_len"] = len(k5) if k5 else 0
        f.sources["k1h_len"] = len(k1h) if k1h else 0
        return f

    f.sources["k5_len"] = len(k5)
    f.sources["k1h_len"] = len(k1h) if k1h else 0

    # OHLC-based indicators run on CLOSED candles only — the last kline from
    # Binance is the still-forming interval; including it injects intra-candle
    # noise into ATR/RSI/BBW/ADX and can flip a regime on a transient spike.
    # volume_zscore has its own forming-candle exclusion, so it keeps the full
    # series.
    k5c = k5[:-1] if len(k5) > 1 else k5

    # Volatility
    f.atr_pct_5m = ind.atr_pct(k5c, 14)
    f.bbw_5m = ind.bollinger_band_width(k5c, 20, 2.0)
    f.realized_vol_5m = ind.realized_vol_pct(k5c, 30)
    f.wick_body_ratio_5m = ind.avg_wick_body_ratio(k5c, 10)
    f.rsi_5m = ind.rsi(k5c, 14)
    f.volume_zscore_5m = ind.volume_zscore(k5, 20)

    # Last CLOSED 5m return % — single-bar fast-drop signal (DUMP detection).
    closes_5c = [float(c["c"]) for c in k5c]
    if len(closes_5c) >= 2 and closes_5c[-2] > 0:
        f.ret_5m_last = (closes_5c[-1] / closes_5c[-2] - 1.0) * 100.0

    if k1h and len(k1h) >= 40:
        k1hc = k1h[:-1] if len(k1h) > 1 else k1h
        f.atr_pct_1h = ind.atr_pct(k1hc, 14)
        f.bbw_1h = ind.bollinger_band_width(k1hc, 20, 2.0)
        f.adx_1h = ind.adx(k1hc, 14)
        closes_1h = [float(c["c"]) for c in k1hc]
        f.ema_slope_1h_pct = ind.ema_slope_pct(closes_1h, 20, 5)
        f.rsi_1h = ind.rsi(k1hc, 14)

    # 24h volume + spread proxy
    bid = _safe_float(ticker.get("bidPrice")) or _safe_float(ticker.get("bid"))
    ask = _safe_float(ticker.get("askPrice")) or _safe_float(ticker.get("ask"))
    if bid and ask and bid > 0 and ask > 0 and ask >= bid:
        mid = (ask + bid) / 2.0
        if mid > 0:
            f.spread_pct = (ask - bid) / mid * 100.0
            f.spread_bps = f.spread_pct * 100.0
    quote_vol = _safe_float(ticker.get("quoteVolume")) or _safe_float(
        ticker.get("volume_quote")
    )
    if quote_vol is not None:
        f.volume_24h_usdt = quote_vol

    return f
