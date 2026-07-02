"""Order Intent Planner tests."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.models import BotParams, FinalAction
from app.services.dynamic_param_score.order_intent import IntentKind, plan_order_intents
from app.services.dynamic_param_score.rebalance import RebalanceOrder, RebalancePlan
from tests.dynamic_param_score.conftest import constraints, ctx, portfolio


def _params(**kwargs) -> BotParams:
    base = dict(
        base_alloc_frac=0.70,
        quote_alloc_frac=0.30,
        buy_grid_count=3,
        sell_grid_count=3,
        buy_grid_spacing_pct=0.8,
        sell_grid_spacing_pct=0.8,
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
    base.update(kwargs)
    return BotParams(**base)


def test_order_intent_planner_produces_grid_intents():
    pf = portfolio(1000, 0.50)
    pf.base_value_usdt = 500
    pf.quote_value_usdt = 500
    plan = plan_order_intents(
        _params(),
        pf,
        constraints(),
        ctx(budget=1000),
        final_action=FinalAction.BALANCED_GRID.value,
    )
    assert plan.buy_intent_count == 3
    assert plan.sell_intent_count == 3
    assert all(i.kind == IntentKind.GRID_BUY.value for i in plan.intents if i.side == "BUY" and i.source == "grid")
    assert plan.intents[0].price_offset_pct == 0.8


def test_wait_produces_no_intents():
    plan = plan_order_intents(
        _params(buy_grid_count=0, sell_grid_count=0),
        portfolio(100, 0.0),
        constraints(),
        ctx(budget=100),
        final_action=FinalAction.WAIT.value,
    )
    assert plan.buy_intent_count == 0
    assert plan.sell_intent_count == 0


def test_order_intent_respects_ladder_budget_override():
    pf = portfolio(500, 0.0)
    pf.quote_value_usdt = 500
    plan_capped = plan_order_intents(
        _params(buy_qty_distribution=[0.12, 0.28, 0.60]),
        pf,
        constraints(),
        ctx(budget=500),
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        buy_ladder_budget_override=39.12,
    )
    plan_full = plan_order_intents(
        _params(buy_qty_distribution=[0.12, 0.28, 0.60]),
        pf,
        constraints(),
        ctx(budget=500),
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    )
    assert plan_capped.total_buy_quote_usdt < plan_full.total_buy_quote_usdt
    assert plan_capped.total_buy_quote_usdt > 0


def test_rebalance_intents_merged():
    pf = portfolio(1000, 0.50)
    pf.base_value_usdt = 500
    pf.quote_value_usdt = 500
    rb = RebalancePlan(
        rebalance_action="GRADUAL_BUY_REBALANCE",
        rebalance_decision="EXECUTE",
        rebalance_execution_mode="ONESHOT",
        current_base_frac=0.5,
        target_base_frac=0.7,
        drift_frac=0.2,
        drift_abs_frac=0.2,
        required_quote_usdt=200,
        required_base_usdt=0,
        allowed_rebalance_quote_usdt=60,
        allowed_rebalance_base_usdt=0,
        mode="GRADUAL_BUY_REBALANCE",
        deadband_frac=0.05,
        orders=[
            RebalanceOrder(side="BUY", quote_usdt=20, price_offset_pct=0.45),
            RebalanceOrder(side="BUY", quote_usdt=20, price_offset_pct=0.90),
        ],
    )
    plan = plan_order_intents(
        _params(buy_grid_count=0, sell_grid_count=0),
        pf,
        constraints(),
        ctx(budget=1000),
        final_action=FinalAction.BALANCED_GRID.value,
        rebalance_plan=rb,
    )
    rb_intents = [i for i in plan.intents if "REBALANCE" in i.kind]
    assert len(rb_intents) == 2
