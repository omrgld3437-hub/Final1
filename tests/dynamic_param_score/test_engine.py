"""Engine integration tests."""

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from tests.dynamic_param_score.conftest import constraints, ctx, market_bundle, portfolio, ranging


def test_engine_returns_decision():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "BTCUSDT",
        market_bundle(),
        portfolio(1000),
        constraints(),
        ctx(),
    )
    assert 0 <= d.param_score <= 100
    assert d.decision_id
    assert d.explain


def test_param_assistant_and_dynamic_same_input():
    engine = DynamicParamScoreEngine()
    m = market_bundle(candles_5m=ranging())
    p = portfolio(800)
    c = constraints()
    d1 = engine.calculate_decision("BTCUSDT", m, p, c, ctx("param_assistant", 800))
    d2 = engine.calculate_decision("BTCUSDT", m, p, c, ctx("dynamic_round_start", 800))
    assert d1.param_score == d2.param_score
    assert d1.final_action == d2.final_action
    if d1.params and d2.params:
        assert d1.params.base_alloc_frac == d2.params.base_alloc_frac
