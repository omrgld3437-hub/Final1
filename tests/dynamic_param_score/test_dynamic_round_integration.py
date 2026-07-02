"""Dynamic round integration — round independence."""

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from tests.dynamic_param_score.conftest import (
    constraints,
    ctx,
    downtrend,
    market_bundle,
    portfolio,
    ranging,
)


def test_round_independence():
    engine = DynamicParamScoreEngine()
    m1 = market_bundle(candles_5m=ranging())
    d1 = engine.calculate_decision(
        "BTCUSDT", m1, portfolio(1000, 0.2), constraints(), ctx("dynamic_round_start", 1000)
    )

    m2 = market_bundle(candles_5m=downtrend(), candles_1h=downtrend(168))
    p2 = portfolio(1000, exposure=0.5)
    d2 = engine.calculate_decision(
        "BTCUSDT", m2, p2, constraints(), ctx("dynamic_round_start", 1000)
    )

    assert d1.decision_id != d2.decision_id
    if d1.params and d2.params:
        changed = (
            d1.params.buy_grid_spacing_pct != d2.params.buy_grid_spacing_pct
            or d1.params.base_alloc_frac != d2.params.base_alloc_frac
        )
        assert changed
