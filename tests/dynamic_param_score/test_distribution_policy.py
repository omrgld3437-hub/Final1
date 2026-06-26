"""Tests for risk-aware grid distribution policy and deploy invariants."""

from __future__ import annotations

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.action_detail import is_deployable
from app.services.dynamic_param_score.distribution_policy import (
    DistributionContext,
    TWO_GRID_EXTREME,
    TWO_GRID_NORMAL,
    is_buy_distribution_valid,
    is_two_grid_distribution_valid,
    is_three_grid_distribution_valid,
    resolve_three_grid_weights,
    resolve_two_grid_weights,
    trim_side_distribution_for_context,
)
from app.services.dynamic_param_score.models import BotContext, BotParams, FinalAction
from app.services.dynamic_param_score.result_type import resolve_result_type


def _params(**kwargs) -> BotParams:
    base = dict(
        base_alloc_frac=0.40,
        quote_alloc_frac=0.60,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.5,
        sell_grid_spacing_pct=2.5,
        buy_qty_distribution=[0.4, 0.6],
        sell_qty_distribution=[0.12, 0.28, 0.60][:2],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.53,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )
    base.update(kwargs)
    return BotParams(**base)


def test_two_grid_never_50_50():
    assert not is_two_grid_distribution_valid([50, 50])
    assert not is_two_grid_distribution_valid([0.5, 0.5])


def test_two_grid_40_60_allowed_in_normal_range():
    ctx = DistributionContext(
        risk_state="NORMAL",
        liquidity_score=70,
        spread_score=70,
        volatility_score=45,
    )
    weights = resolve_two_grid_weights(ctx)
    assert weights == TWO_GRID_NORMAL
    assert is_two_grid_distribution_valid(weights, ctx=ctx)


def test_two_grid_30_70_for_defensive_lower_lows():
    ctx = DistributionContext(
        risk_state="DEFENSIVE",
        lower_lows=True,
        btc_market_risk_score=35,
        vol_code="V4",
    )
    weights = resolve_two_grid_weights(ctx)
    assert weights == (30, 70)


def test_two_grid_25_75_for_extreme_risk():
    ctx = DistributionContext(
        risk_state="DEFENSIVE",
        vol_code="V5",
        liquidity_score=30,
    )
    assert resolve_two_grid_weights(ctx) == TWO_GRID_EXTREME


def test_three_grid_defensive_not_equalish():
    bad = [30, 35, 35]
    assert not is_three_grid_distribution_valid(bad, ctx=DistributionContext(risk_state="DEFENSIVE"))
    good = resolve_three_grid_weights(DistributionContext(risk_state="DEFENSIVE", lower_lows=True))
    assert is_three_grid_distribution_valid(good, ctx=DistributionContext(risk_state="DEFENSIVE"))
    assert good[-1] >= 50


def test_trim_three_to_two_uses_context_not_slice():
    ctx = DistributionContext(risk_state="NORMAL", liquidity_score=70, spread_score=70)
    out = trim_side_distribution_for_context([12, 28, 60], 2, ctx)
    assert out == [40, 60]
    ctx_def = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    out_def = trim_side_distribution_for_context([12, 28, 60], 2, ctx_def)
    assert out_def == [30, 70]


def test_one_grid_not_deployable():
    params = _params(buy_grid_count=1, sell_grid_count=2, buy_qty_distribution=[1.0])
    meta = {"single_probe_only": True}
    assert not is_deployable(FinalAction.ACTIVE_DEFENSIVE_GRID.value, params, meta)


def test_deployable_requires_min_two_buy_grids():
    params = _params(buy_grid_count=1, sell_grid_count=2)
    assert not is_deployable(FinalAction.BALANCED_GRID.value, params, {})


def test_invalid_distribution_not_deployable():
    params = _params()
    assert not is_deployable(
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        params,
        {"distribution_invalid": True},
    )


def test_single_probe_result_type():
    ctx = BotContext(run_source="param_assistant", budget_usdt=100.0)
    params = _params(buy_grid_count=1, sell_grid_count=0, buy_qty_distribution=[1.0])
    rt = resolve_result_type(
        deployable=False,
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        params=params,
        feasibility_meta={"single_probe_only": True},
        bot_context=ctx,
        blocking_reasons=[],
        has_recommendation_ui=True,
    )
    assert rt == "single_probe_recommendation"


def test_first_start_buy_only_result_type():
    ctx = BotContext(
        run_source="param_assistant",
        budget_usdt=1000.0,
        is_first_start=True,
        first_start_buy_only=True,
    )
    params = _params(buy_grid_count=2, sell_grid_count=0, sell_qty_distribution=[])
    rt = resolve_result_type(
        deployable=True,
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        params=params,
        feasibility_meta={"first_start_buy_only": True},
        bot_context=ctx,
        blocking_reasons=[],
        has_recommendation_ui=True,
    )
    assert rt == "first_start_buy_only"
