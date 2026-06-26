"""Selection trace telemetry contract tests."""

from __future__ import annotations

import os

import pytest

from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
    FAST_TEST_POOL_TARGET_V4,
    POOL_VERSION_V4,
    build_dps_v4_pool,
)
from app.services.dynamic_param_score.param_pool.selector import select_template


@pytest.fixture(scope="module")
def v4_pool():
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    return build_dps_v4_pool(total_target=FAST_TEST_POOL_TARGET_V4, migrate_v3=False)


def test_selection_trace_fields_populated(v4_pool):
    assert v4_pool
    sub = SubScores(
        trend_score=45,
        volatility_score=50,
        range_score=55,
        liquidity_score=60,
        spread_score=55,
        fee_efficiency_score=40,
        exposure_safety_score=60,
        data_quality_score=80,
        btc_market_risk_score=50,
        drawdown_risk_score=50,
        mean_reversion_score=50,
    )
    ind = IndicatorSnapshot(
        orderbook_spread_pct=0.02,
        atr14_pct_1h=1.2,
        lower_lows=False,
        higher_highs=True,
    )
    portfolio = PortfolioState(
        total_equity_usdt=100.0,
        quote_balance=45.0,
        quote_value_usdt=45.0,
        base_balance=0.01,
        base_value_usdt=55.0,
        current_base_exposure_frac=0.55,
    )
    constraints = ExchangeConstraints(
        min_notional=5.0,
        step_size=0.001,
        tick_size=0.01,
        min_qty=0.001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )
    sel = select_template(
        param_score=17,
        regime=RegimeTag.BALANCED_RANGE,
        risk_state=RiskState.DEFENSIVE.value,
        sub=sub,
        ind=ind,
        portfolio=portfolio,
        constraints=constraints,
        budget_usdt=100.0,
        min_notional=5.0,
        symbol="ETHUSDT",
    )
    ctx = sel.selection_context or {}
    assert ctx.get("exact_route_candidate_count") is not None
    assert ctx.get("scored_candidate_count") is not None
    assert ctx.get("route_key")
    assert ctx.get("market_signature")

    scored = int(ctx.get("scored_candidate_count") or 0)
    has_profile = bool(sel.selected_template_key)
    runtime_safe = bool(ctx.get("runtime_safe_profile_generated"))
    if has_profile and scored <= 0 and not runtime_safe and not sel.fallback_used:
        pytest.fail("zero_candidate_but_selected")


def test_cost_resolver_fee_floor_when_no_live_fee():
    from app.services.dynamic_param_score.param_generator.v4_resolvers import resolve_cost

    cost = resolve_cost(
        constraints=ExchangeConstraints(
            min_notional=5.0,
            step_size=0.001,
            tick_size=0.01,
            min_qty=0.001,
            taker_fee_pct=0.0,
            maker_fee_pct=0.0,
            estimated_slippage_pct=0.0,
        ),
        spread_pct=0.0,
        fee_efficiency_score=20,
    )
    assert cost.fee_data_available is False
    assert cost.total_cost_pct >= 1.2
    assert cost.cost_floor_pct >= 1.2
