"""Scoring tests."""

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from tests.dynamic_param_score.conftest import (
    constraints,
    ctx,
    dump_series,
    market_bundle,
    portfolio,
    ranging,
)


def test_dump_risk_low_score():
    engine = DynamicParamScoreEngine()
    m = market_bundle(
        candles_5m=dump_series(),
        candles_1h=dump_series(168, 100),
        price=50,
        quote_vol=5_000_000,
        btc=None,
    )
    m.btc_reference_data = None
    d = engine.calculate_decision("BTCUSDT", m, portfolio(1000), constraints(), ctx())
    assert d.final_action in ("NO_TRADE", "WAIT", "DEFENSIVE_GRID")
    if d.regime_tag == "DUMP_RISK":
        assert not d.deployable


def test_determinism():
    engine = DynamicParamScoreEngine()
    m = market_bundle(candles_5m=ranging())
    p = portfolio(500)
    c = constraints()
    b = ctx()
    d1 = engine.calculate_decision("BTCUSDT", m, p, c, b)
    d2 = engine.calculate_decision("BTCUSDT", m, p, c, b)
    assert d1.param_score == d2.param_score
    assert d1.regime_tag == d2.regime_tag
    assert d1.final_action == d2.final_action
