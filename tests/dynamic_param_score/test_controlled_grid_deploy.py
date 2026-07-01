"""Controlled grid deploy — SOL-like squeeze scenario."""

from __future__ import annotations

import os

import pytest

from app.services.dynamic_param_score.controlled_deploy import (
    compute_confidence_components,
    fix_buy_distribution,
    market_allows_controlled_grid,
    try_controlled_grid_resolution,
)
from app.services.dynamic_param_score.distribution_policy import DistributionContext
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    SubScores,
)


def _sol_sub() -> SubScores:
    return SubScores(
        range_score=65,
        liquidity_score=82,
        spread_score=90,
        fee_efficiency_score=15,
        volatility_score=40,
        data_quality_score=75,
        btc_market_risk_score=70,
        exposure_safety_score=60,
        trend_score=55,
        drawdown_risk_score=50,
    )


def _sol_ind() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        return_24h_pct=4.4,
        atr14_pct_5m=0.16,
        atr14_pct_1h=1.03,
        orderbook_spread_pct=0.01,
        rsi14_1h=56,
        price_in_bb=0.7,
        volatility_percentile=2.1,
        crash_velocity=-0.11,
        btc_crash_velocity=-0.15,
        lower_lows=False,
        higher_highs=False,
    )


def test_confidence_components_not_collapsed_on_missing_fee():
    sub = _sol_sub()
    comps = compute_confidence_components(sub, param_score=62, fee_data_available=False)
    assert comps["market_suitability_score"] >= 55
    assert comps["final_deploy_confidence"] >= 35


def test_controlled_grid_fixes_distribution_and_deploy():
    sub = _sol_sub()
    ind = _sol_ind()
    params = BotParams(
        base_alloc_frac=0.58,
        quote_alloc_frac=0.42,
        buy_grid_count=2,
        sell_grid_count=3,
        buy_grid_spacing_pct=3.41,
        sell_grid_spacing_pct=3.57,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.15, 0.35, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.66,
        take_profit_pct=2.6,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.608,
        max_quote_to_spend_per_buy_frac=0.45,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.72,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
        buy_grid_ladder_pcts=[3.41, 6.82],
        sell_grid_ladder_pcts=[3.57, 7.5, 15.74],
    )
    portfolio = PortfolioState(
        base_balance=2,
        quote_balance=800,
        base_value_usdt=200,
        quote_value_usdt=800,
        total_equity_usdt=1000,
        current_base_exposure_frac=0.20,
    )
    constraints = ExchangeConstraints(
        min_notional=10,
        step_size=0.01,
        tick_size=0.01,
        min_qty=0.01,
        maker_fee_pct=0.1,
        taker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )
    ctx = BotContext(run_source="param_assistant", budget_usdt=1000)
    feas = {
        "distribution_invalid": True,
        "exposure_hard_cap_breach": True,
        "buy_ladder_budget_usdt": 31.19,
        "deploy_blocked_reason": "INVALID_TWO_GRID_DISTRIBUTION",
        "param_score": 62,
    }
    assert market_allows_controlled_grid(sub, ind, [])
    p, action, deployable, meta = try_controlled_grid_resolution(
        params,
        FinalAction.WAIT_SAFETY.value,
        False,
        sub=sub,
        ind=ind,
        portfolio=portfolio,
        constraints=constraints,
        context=ctx,
        risk_state="NORMAL",
        blocking=[],
        feasibility_meta=feas,
        fee_data_available=False,
    )
    assert not meta.get("distribution_invalid")
    assert p.buy_qty_distribution[0] < 0.45
    assert p.buy_qty_distribution[1] > 0.55
    assert deployable
    assert action == FinalAction.CONTROLLED_GRID.value
    assert meta.get("controlled_grid") is True


def test_fix_buy_distribution_never_50_50():
    params = BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=3,
        sell_grid_spacing_pct=3,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.4, 0.6],
        trailing_enabled=True,
        trailing_callback_pct=0.5,
        take_profit_pct=2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.6,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.5,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    ctx = DistributionContext(risk_state="NORMAL", btc_market_risk_score=70)
    assert fix_buy_distribution(params, dist_ctx=ctx)
    assert params.buy_qty_distribution == [0.4, 0.6]
