"""Profile gating and ACTIVE_GRID eligibility."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction, RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.profiles import select_profile_family
from tests.dynamic_param_score.factories import (
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)


def _good_sub(**overrides) -> SubScores:
    base = SubScores(
        range_score=80,
        liquidity_score=80,
        spread_score=80,
        fee_efficiency_score=75,
        exposure_safety_score=75,
        data_quality_score=80,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_score_60_69_never_active_grid():
    engine = DynamicParamScoreEngine()
    market = make_market_bundle()
    d = engine.calculate_decision(
        "SOLUSDT",
        market,
        make_portfolio_state(budget_usdt=50),
        make_constraints(),
        make_context(budget_usdt=50),
    )
    if 60 <= d.param_score < 70:
        assert d.final_action != FinalAction.ACTIVE_GRID.value


@pytest.mark.parametrize(
    "field,value",
    [
        ("range_score", 50),
        ("liquidity_score", 50),
        ("spread_score", 50),
        ("fee_efficiency_score", 50),
        ("exposure_safety_score", 50),
        ("data_quality_score", 50),
    ],
)
def test_active_grid_requires_each_subscore(field, value):
    sub = _good_sub(**{field: value})
    _, action = select_profile_family(
        RegimeTag.BALANCED_RANGE,
        RiskState.NORMAL.value,
        75,
        sub,
        budget_usdt=500,
        min_notional=5,
    )
    assert action != FinalAction.ACTIVE_GRID


def test_small_budget_blocks_active_grid():
    sub = _good_sub()
    _, action = select_profile_family(
        RegimeTag.BALANCED_RANGE,
        RiskState.NORMAL.value,
        78,
        sub,
        budget_usdt=50,
        min_notional=5,
    )
    assert action != FinalAction.ACTIVE_GRID


def test_trending_down_forbids_active_and_trailing():
    engine = DynamicParamScoreEngine()
    market = make_market_bundle(pattern="trending_down")
    d = engine.calculate_decision(
        "SOLUSDT",
        market,
        make_portfolio_state(budget_usdt=200),
        make_constraints(),
        make_context(budget_usdt=200),
    )
    assert d.final_action not in (
        FinalAction.ACTIVE_GRID.value,
        FinalAction.TREND_TRAILING.value,
    )
    if d.params:
        assert d.params.base_alloc_frac <= 0.30 + 0.01
        assert d.params.max_base_exposure_frac <= d.params.base_alloc_frac + 0.06 + 0.02


def test_dump_risk_suppresses_trading():
    engine = DynamicParamScoreEngine()
    market = make_market_bundle(pattern="dump_risk")
    d = engine.calculate_decision(
        "SOLUSDT",
        market,
        make_portfolio_state(budget_usdt=100),
        make_constraints(),
        make_context(budget_usdt=100),
    )
    assert d.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)
    assert not d.deployable or (d.params and d.params.buy_grid_count == 0)
