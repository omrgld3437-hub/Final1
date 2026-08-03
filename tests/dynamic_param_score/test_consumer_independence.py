"""Consumer independence — Param Assistant vs Dynamic Mode on shared DPS motor."""

from __future__ import annotations

import pytest

from app.botengine.dynamic import cycle_manager as cm
from app.services.dynamic_param_score import get_engine
from app.services.dynamic_param_score.consumer_policy import (
    build_dynamic_round_context,
    build_param_assistant_context,
    policy_for,
    sanitize_context_for_consumer,
)
from app.services.dynamic_param_score.models import BotContext, BotParams, FinalAction
from app.services.dynamic_param_score.result_type import resolve_result_type
from tests.dynamic_param_score.conftest import constraints, portfolio
from tests.dynamic_param_score.sol_market_fixture import _sol_market


def _sample_params() -> BotParams:
    return BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.0,
        sell_grid_spacing_pct=2.0,
        buy_qty_distribution=[0.4, 0.6],
        sell_qty_distribution=[0.4, 0.6],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.5,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )


def test_shared_engine_singleton():
    assert isinstance(get_engine(), type(cm.get_dps_engine()))
    assert cm.get_dps_engine() is get_engine()


def test_consumer_policies_are_distinct():
    pa = policy_for("param_assistant")
    dm = policy_for("dynamic_round_start")
    assert pa.recommendation_ui is True
    assert dm.recommendation_ui is False
    assert pa.first_start_eligible is True
    assert dm.first_start_eligible is False
    assert pa.soften_extreme_safety_for_ui is True
    assert dm.soften_extreme_safety_for_ui is False


def test_first_start_only_param_assistant():
    p = portfolio(100.0, 0.0)
    pa = build_param_assistant_context(budget_usdt=100.0, portfolio=p)
    dm = build_dynamic_round_context(budget_usdt=100.0, cycle_id=2)
    assert pa.is_first_start is True
    assert pa.first_start_buy_only is True
    assert dm.is_first_start is False
    assert dm.first_start_buy_only is False
    assert dm.run_source == "dynamic_round_start"
    assert pa.run_source == "param_assistant"


def test_sanitize_strips_first_start_from_dynamic_context():
    polluted = BotContext(
        run_source="dynamic_round_start",
        budget_usdt=100.0,
        is_first_start=True,
        first_start_buy_only=True,
    )
    clean = sanitize_context_for_consumer(polluted)
    assert clean.is_first_start is False
    assert clean.first_start_buy_only is False


def test_result_type_differs_by_consumer_with_same_params():
    params = _sample_params()
    pa_ctx = build_param_assistant_context(budget_usdt=100.0, portfolio=portfolio(100.0, 0.0))
    dm_ctx = build_dynamic_round_context(budget_usdt=100.0, cycle_id=2)
    meta = {}

    pa_rt = resolve_result_type(
        deployable=False,
        final_action=FinalAction.BALANCED_GRID.value,
        params=params,
        feasibility_meta=meta,
        bot_context=pa_ctx,
        blocking_reasons=[],
        has_recommendation_ui=policy_for("param_assistant").recommendation_ui,
    )
    dm_rt = resolve_result_type(
        deployable=False,
        final_action=FinalAction.BALANCED_GRID.value,
        params=params,
        feasibility_meta=meta,
        bot_context=dm_ctx,
        blocking_reasons=[],
        has_recommendation_ui=policy_for("dynamic_round_start").recommendation_ui,
    )
    # Param Assistant first-start zero-exposure path surfaces first_start_buy_only;
    # Dynamic Mode round-start surfaces a management decision for the same params.
    assert pa_rt == "first_start_buy_only"
    assert dm_rt == "management_decision"


def test_engine_calls_are_stateless_between_consumers():
    engine = get_engine()
    market = _sol_market()
    pf = portfolio(50.0, 0.0)
    cons = constraints()

    pa_ctx = build_param_assistant_context(budget_usdt=50.0, portfolio=pf)
    dm_ctx = build_dynamic_round_context(budget_usdt=50.0, cycle_id=3, bot_id=99)

    d1 = engine.calculate_decision("SOLUSDT", market, pf, cons, pa_ctx)
    d2 = engine.calculate_decision("SOLUSDT", market, pf, cons, dm_ctx)

    assert d1.run_source == "param_assistant"
    assert d2.run_source == "dynamic_round_start"
    assert d1.decision_id != d2.decision_id
    # V6 telemetry keys consumer via run_source; consumer_id is optional.
    assert (d1.telemetry.get("consumer_id") or d1.run_source) == "param_assistant"
    assert (d2.telemetry.get("consumer_id") or d2.run_source) == "dynamic_round_start"
    # Contexts stay independent: PA is first-start eligible, DM round-start is not.
    assert pa_ctx.is_first_start is True
    assert dm_ctx.is_first_start is False


# Legacy apply_safety_gates consumer-softening test removed with
# app/services/dynamic_param_score/safety.py (V6 owns its own guards).
