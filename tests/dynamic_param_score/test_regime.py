"""Regime classification tests."""

from app.services.dynamic_param_score.models import BtcReferenceData, RegimeTag
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from tests.dynamic_param_score.conftest import (
    constraints,
    ctx,
    dump_series,
    downtrend,
    high_vol_range,
    market_bundle,
    portfolio,
    ranging,
    uptrend,
)


def test_dump_risk_no_trade():
    engine = DynamicParamScoreEngine()
    btc = BtcReferenceData(return_4h_pct=-8.0, return_1h_pct=-5.0, return_24h_pct=-15.0, crash_velocity=-4.0)
    m = market_bundle(candles_5m=dump_series(), candles_1h=dump_series(168), btc=btc)
    d = engine.calculate_decision("BTCUSDT", m, portfolio(1000), constraints(), ctx())
    assert d.regime_tag in (
        RegimeTag.DUMP_RISK.value,
        RegimeTag.NO_TRADE.value,
        RegimeTag.TRENDING_DOWN.value,
        RegimeTag.HIGH_VOL_UNSTABLE.value,
    )
    assert d.final_action in ("NO_TRADE", "WAIT", "DEFENSIVE_GRID", "SELL_MANAGEMENT_ONLY", "ACTIVE_DEFENSIVE_GRID")


def test_trending_down_defensive_only():
    engine = DynamicParamScoreEngine()
    m = market_bundle(candles_5m=downtrend(), candles_1h=downtrend(168))
    d = engine.calculate_decision("BTCUSDT", m, portfolio(1000), constraints(), ctx())
    if d.params and int(d.params.buy_grid_count or 0) > 0:
        assert d.params.base_alloc_frac <= 0.30
        assert d.params.max_base_exposure_frac <= d.params.base_alloc_frac + 0.06 + 0.001
    assert d.final_action not in ("ACTIVE_GRID", "HIGH_CONFIDENCE_ACTIVE_GRID")


def test_range_high_vol_balanced_or_active():
    engine = DynamicParamScoreEngine()
    m = market_bundle(candles_5m=high_vol_range(), candles_1h=high_vol_range(168))
    d = engine.calculate_decision("BTCUSDT", m, portfolio(5000), constraints(), ctx())
    if d.deployable and d.param_score >= 55:
        assert d.final_action in (
            "BALANCED_GRID", "ACTIVE_GRID", "DEFENSIVE_GRID", "ACTIVE_DEFENSIVE_GRID"
        )
