"""Kline fallback enrichment for Param Assistant market bundle."""

from __future__ import annotations

from app.services.dynamic_param_score.data_collector import (
    _enrich_market_bundle_from_klines,
    _volume_from_klines_24h,
)
from app.services.dynamic_param_score.models import Candle


def _candle(h: float, v: float) -> Candle:
    return Candle(t=1, o=h, h=h, l=h, c=h, v=v)


def test_enrich_price_from_klines_when_datahub_empty():
    c5 = [_candle(100.0, 10.0)]
    price, vol, qvol, src = _enrich_market_bundle_from_klines(
        price=0.0, vol=0.0, qvol=0.0, c5=c5, c1h=None
    )
    assert price == 100.0
    assert src == "klines_close"


def test_enrich_volume_from_hourly_klines():
    c1h = [_candle(10.0 + i * 0.1, 1000.0) for i in range(24)]
    base, quote = _volume_from_klines_24h(c1h)
    assert base == 24000.0
    assert quote > 0
    price, vol, qvol, _ = _enrich_market_bundle_from_klines(
        price=12.0, vol=0.0, qvol=0.0, c5=None, c1h=c1h
    )
    assert vol == 24000.0
    assert qvol > 0
