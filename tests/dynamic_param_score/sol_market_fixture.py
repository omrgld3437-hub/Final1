"""Shared SOLUSDT synthetic market bundle for DPS tests."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.models import MarketDataBundle
from tests.dynamic_param_score.conftest import mk_candles


def _sol_market():
    c5 = mk_candles(
        [67.8 * (1 + 0.001 * math.sin(i / 3.0)) for i in range(288)],
        interval_ms=300_000,
    )
    return MarketDataBundle(
        symbol="SOLUSDT",
        base_asset="SOL",
        quote_asset="USDT",
        candles_5m=c5,
        candles_15m=c5[::3][:100],
        candles_1h=c5[:168],
        ticker_price=67.8,
        volume_24h=3e6,
        quote_volume_24h=228e6,
        market_timestamp=c5[-1].t,
        orderbook_top={"bid": 67.79, "ask": 67.81},
    )
