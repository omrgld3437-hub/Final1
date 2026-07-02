"""Profile selection tests."""

from app.services.dynamic_param_score.profiles import build_params, select_profile_family
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import RegimeTag, RiskState
from tests.dynamic_param_score.conftest import constraints, market_bundle, portfolio


def test_trending_down_profile():
    name, action = select_profile_family(
        RegimeTag.TRENDING_DOWN, RiskState.DEFENSIVE.value, 55
    )
    assert action == "DEFENSIVE_GRID"
    m = market_bundle()
    ind = compute_indicators(m, portfolio())
    p = build_params(name, 55, RegimeTag.TRENDING_DOWN, ind, 0.15)
    assert p is not None
    assert p.base_alloc_frac <= 0.30


def test_blocked_no_trade():
    name, action = select_profile_family(
        RegimeTag.DUMP_RISK, RiskState.BLOCKED.value, 10
    )
    assert action == "NO_TRADE"
    assert name == "NO_TRADE_PROFILE"
