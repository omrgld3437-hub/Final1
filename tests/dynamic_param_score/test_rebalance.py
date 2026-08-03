"""Rebalance planner — 15pp threshold + one-shot orders."""

from __future__ import annotations

from app.services.dynamic_param_score.models import (
    BotParams,
    FinalAction,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.rebalance import (
    RebalanceMode,
    SafetyContext,
    apply_rebalance_safety,
    calculate_allocation_drift,
    plan_rebalance,
    rebalance_delta_total_pp,
)
from tests.dynamic_param_score.conftest import constraints, portfolio


def _ctx(**kwargs) -> SafetyContext:
    defaults = dict(
        risk_state=RiskState.NORMAL.value,
        regime=RegimeTag.BALANCED_RANGE.value,
        final_action=FinalAction.BALANCED_GRID.value,
        param_score=65,
        sub_scores=SubScores(fee_efficiency_score=70, exposure_safety_score=80, liquidity_score=75),
        headroom_usdt=50.0,
        min_notional=5.0,
    )
    defaults.update(kwargs)
    return SafetyContext(**defaults)


def test_drift_50_to_70_target():
    d = calculate_allocation_drift(0.50, 0.70, 1000.0)
    assert d["drift_frac"] == 0.20
    assert d["required_quote_usdt"] == 200.0
    assert rebalance_delta_total_pp(0.50, 0.70) == 40.0


def test_deadband_skips_small_drift():
    pf = portfolio(1000, 0.52)
    plan = plan_rebalance(
        target_base_frac=0.53,
        current_base_frac=0.52,
        portfolio=pf,
        bot_params=None,
        constraints=constraints(),
        safety_context=_ctx(),
    )
    assert plan.rebalance_decision == "SKIP"
    assert not plan.orders


def test_oneshot_buy_rebalance_single_order():
    pf = portfolio(1000, 0.50)
    sub = SubScores(fee_efficiency_score=75, exposure_safety_score=85, liquidity_score=80)
    params = BotParams(
        base_alloc_frac=0.70,
        quote_alloc_frac=0.30,
        buy_grid_count=3,
        sell_grid_count=3,
        buy_grid_spacing_pct=0.45,
        sell_grid_spacing_pct=0.45,
        buy_qty_distribution=[0.33, 0.33, 0.34],
        sell_qty_distribution=[0.33, 0.33, 0.34],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.75,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )
    plan = plan_rebalance(
        target_base_frac=0.70,
        current_base_frac=0.50,
        portfolio=pf,
        bot_params=params,
        constraints=constraints(),
        safety_context=_ctx(sub_scores=sub, headroom_usdt=200.0),
    )
    plan = apply_rebalance_safety(
        plan, _ctx(sub_scores=sub, headroom_usdt=200.0), params, constraints(), total_equity_usdt=1000.0
    )
    assert plan.rebalance_decision == "EXECUTE"
    assert len(plan.orders) == 1
    assert plan.orders[0].side == "BUY"
    assert plan.orders[0].order_type == "MARKETABLE_LIMIT"


def test_fee_bad_blocks_buy_rebalance():
    pf = portfolio(1000, 0.50)
    sub = SubScores(fee_efficiency_score=15, liquidity_score=80)
    plan = plan_rebalance(
        target_base_frac=0.70,
        current_base_frac=0.50,
        portfolio=pf,
        bot_params=None,
        constraints=constraints(),
        safety_context=_ctx(sub_scores=sub, headroom_usdt=200.0),
    )
    assert plan.rebalance_decision == "DEFER"
    assert plan.blocked
    assert not plan.orders


def test_overweight_triggers_sell_rebalance():
    pf = portfolio(1000, 0.78)
    plan = plan_rebalance(
        target_base_frac=0.50,
        current_base_frac=0.78,
        portfolio=pf,
        bot_params=None,
        constraints=constraints(),
        safety_context=_ctx(final_action=FinalAction.SELL_MANAGEMENT_ONLY.value),
    )
    assert "SELL" in plan.rebalance_action
    assert plan.required_base_usdt > 0
    assert len(plan.orders) == 1


def test_rebalance_oneshot_is_single_order_not_grid_ladder():
    """order_intent katmanı kaldırıldı; rebalance planı tek seferlik emir üretir."""
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(0.70, 0.50, pf, None, constraints(), _ctx(headroom_usdt=300.0))
    if plan.orders:
        assert len(plan.orders) == 1
        assert "ONESHOT" in str(plan.rebalance_action).upper() or "BUY" in str(
            plan.rebalance_action
        ).upper()
