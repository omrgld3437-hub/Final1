"""Grid formula unit tests — cost + ATR + scenario deterministic path."""

from __future__ import annotations

from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
from app.services.dynamic_param_score.v5.generator.grid_formula import compute_grid_spacing


def test_example_route_low_vol_squeeze_range_upper_defensive():
    """User example: A1 R3 D2 S2 V2 K1 L1 — sell closer, buy deeper, cost-safe."""
    parts = V5RouteParts(
        asset="A1_BTC_CORE",
        regime="R3_LOW_VOL_SQUEEZE",
        direction="D2_NEUTRAL_BIAS",
        structure="S2_RANGE_UPPER",
        volatility="V2_LOW",
        risk="K1_DEFENSIVE",
        liquidity="L1_HIGH_LIQUIDITY_LOW_COST",
    )
    grid = compute_grid_spacing(parts)
    gr = grid.grid_reasoning

    assert gr.vol_grid_pct >= 2.0
    assert gr.scenario_grid_pct >= 2.35
    assert gr.selected_base_first_grid_pct >= gr.min_grid_by_cost_pct
    assert gr.sell_first_grid_pct < gr.buy_first_grid_pct
    assert grid.sell_grid_levels_pct[0] == gr.sell_first_grid_pct
    assert grid.buy_grid_levels_pct[0] == gr.buy_first_grid_pct
    assert grid.sell_grid_levels_pct[0] >= gr.min_grid_by_cost_pct
    assert grid.buy_grid_levels_pct[0] >= gr.min_grid_by_cost_pct
    # Geometric expansion
    assert grid.sell_grid_levels_pct[1] > grid.sell_grid_levels_pct[0]
    assert grid.buy_grid_levels_pct[1] > grid.buy_grid_levels_pct[0]
    assert gr.reason


def test_crash_buy_deeper_than_sell():
    parts = V5RouteParts(
        asset="A3_MAJOR_ALT",
        regime="R8_CRASH",
        direction="D3_DOWN_BIAS",
        structure="S5_LOWER_LOWS",
        volatility="V5_SHOCK",
        risk="K1_DEFENSIVE",
        liquidity="L3_LOW_LIQUIDITY_HIGH_COST",
    )
    grid = compute_grid_spacing(parts)
    assert grid.buy_grid_levels_pct[0] >= grid.sell_grid_levels_pct[0]


def test_every_shelf_has_grid_reasoning():
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_shelf

    parts = V5RouteParts(
        asset="A2_ETH_CORE",
        regime="R2_BALANCED_RANGE",
        direction="D1_UP_BIAS",
        structure="S1_RANGE_MID",
        volatility="V3_NORMAL",
        risk="K2_NORMAL_CONTROLLED",
        liquidity="L2_NORMAL_LIQUIDITY_NORMAL_COST",
    )
    shelf = generate_shelf(parts)
    assert shelf.base_template.grid_reasoning
    assert "cost_floor_pct" in shelf.base_template.grid_reasoning
    assert shelf.generation_meta.deterministic_formula_version == "DPLV5_FORMULA_2"
