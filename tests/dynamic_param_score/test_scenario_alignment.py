"""Scenario alignment — regime unification and runtime fit."""

from __future__ import annotations

from app.services.dynamic_param_score.models import BotParams, RegimeTag, SubScores
from app.services.dynamic_param_score.scenario_alignment import (
    R_CODE_TO_REGIME,
    build_scenario_alignment,
    compute_grid_direction_fit,
    compute_structure_fit,
    regime_code_from_route_key,
    regime_tag_from_v5_route,
    score_applied_vs_shelf,
    score_indicator_param_alignment,
)


def test_regime_unification_r3():
    legacy = RegimeTag.BALANCED_RANGE
    route = "A1|R3|D2|S1|V2|K2|L1"
    mapped = regime_tag_from_v5_route(route, legacy, SubScores(data_quality_score=80))
    assert mapped == RegimeTag.RANGE_LOW_VOL
    assert regime_code_from_route_key(route) == "R3"


def test_structure_fit_lower_lows():
    route = "A3|R10|D3|S5|V3|K1|L1"
    p = BotParams(
        base_alloc_frac=0.4,
        quote_alloc_frac=0.6,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.5,
        sell_grid_spacing_pct=1.2,
        buy_qty_distribution=[0.35, 0.65],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.3,
        take_profit_pct=1.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.55,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=True,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    assert compute_structure_fit(route, p) >= 0.75


def test_applied_vs_shelf_penalizes_grid_trim():
    shelf = BotParams(
        base_alloc_frac=0.52,
        quote_alloc_frac=0.48,
        buy_grid_count=3,
        sell_grid_count=3,
        buy_grid_spacing_pct=1.8,
        sell_grid_spacing_pct=1.8,
        buy_qty_distribution=[0.33, 0.33, 0.34],
        sell_qty_distribution=[0.33, 0.33, 0.34],
        trailing_enabled=True,
        trailing_callback_pct=0.3,
        take_profit_pct=1.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.62,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    applied = BotParams(
        base_alloc_frac=0.52,
        quote_alloc_frac=0.48,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.2,
        sell_grid_spacing_pct=2.0,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.3,
        take_profit_pct=1.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.62,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    score, notes = score_applied_vs_shelf(shelf, applied)
    assert score < 100
    assert "buy_grid_count_adjusted" in notes


def test_build_scenario_alignment_combined():
    p = BotParams(
        base_alloc_frac=0.52,
        quote_alloc_frac=0.48,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.0,
        sell_grid_spacing_pct=2.0,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.3,
        take_profit_pct=1.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.62,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    align = build_scenario_alignment(
        route_key="A1|R3|D2|S1|V2|K2|L1",
        regime_tag=RegimeTag.RANGE_LOW_VOL.value,
        legacy_regime_tag=RegimeTag.BALANCED_RANGE.value,
        final_action="CONTROLLED_GRID",
        params=p,
        pre_safety_params=p,
        ind=None,
        sub=SubScores(liquidity_score=80, spread_score=80, fee_efficiency_score=55),
        feasibility_meta={},
        shelf_scenario_fit=92.0,
    )
    assert align["combined_score"] >= 70
    assert align["aligned"] is True
    assert align["regime_code"] == "R3"
