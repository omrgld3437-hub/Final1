"""Atmosphere + deploy decision layer invariants."""

from __future__ import annotations

from app.services.dynamic_param_score.atmosphere import (
    REGIME_TEXT,
    enforce_buy_distribution_on_params,
    regime_text_for_explanation,
    build_distribution_context,
)
from app.services.dynamic_param_score.distribution_policy import DistributionContext
from app.services.dynamic_param_score.models import BotParams, SubScores
from app.services.dynamic_param_score.result_type import resolve_result_type
from app.services.dynamic_param_score.models import BotContext, FinalAction


def test_regime_text_r5_not_balanced_range():
    txt = regime_text_for_explanation("A3|R5|D1|S2|V3|K2|L1", "BALANCED_RANGE")
    assert "kırılım" in txt.lower()
    assert "dengeli aralık" not in txt.lower()
    assert txt == REGIME_TEXT["R5"]


def test_buy_distribution_never_50_50_after_enforce():
    params = BotParams(
        base_alloc_frac=0.55,
        quote_alloc_frac=0.45,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=3.0,
        sell_grid_spacing_pct=3.0,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.4, 0.6],
        trailing_enabled=True,
        trailing_callback_pct=0.5,
        take_profit_pct=2.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.6,
        max_quote_to_spend_per_buy_frac=0.45,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.5,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    sub = SubScores(btc_market_risk_score=70, liquidity_score=80, spread_score=85)
    ctx = build_distribution_context(sub=sub, ind=None, risk_state="NORMAL", route_key="A3|R5|D1|S2|V3|K2|L1")
    assert enforce_buy_distribution_on_params(params, ctx)
    assert params.buy_qty_distribution[0] <= 0.40
    assert params.buy_qty_distribution[1] >= 0.60


def test_fee_bad_not_deployable_grid_result_type():
    from app.services.dynamic_param_score.models import BotParams

    params = BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=3,
        sell_grid_spacing_pct=3,
        buy_qty_distribution=[0.4, 0.6],
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
    rt = resolve_result_type(
        deployable=True,
        final_action=FinalAction.BALANCED_GRID.value,
        params=params,
        feasibility_meta={"fee_bad_rebalance_deferred": True, "full_deployable": False},
        bot_context=BotContext(run_source="param_assistant", budget_usdt=1000.0),
        blocking_reasons=[],
        has_recommendation_ui=True,
    )
    assert rt == "controlled_grid"


def test_exposure_gate_blocks_deployable():
    from app.services.dynamic_param_score.action_detail import is_deployable

    assert not is_deployable(
        FinalAction.BALANCED_GRID.value,
        None,
        {"exposure_hard_cap_breach": True, "worst_case_base_exposure_frac": 0.65, "max_base_exposure_frac": 0.60},
    )
