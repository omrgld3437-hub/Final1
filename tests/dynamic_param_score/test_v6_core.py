"""Dynamic Param V6 tests — lattice, catalog, engine."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
from app.services.dynamic_param_score.v6.domain.types import V6InputContract
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile
from app.services.dynamic_param_score.v6.v6_quantizer import (
    quantize_base_pct,
    quantize_grid_distance,
    quantize_profile,
    round_to_nearest_5,
)
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_profile_catalog import load_catalog


def test_quantize_base_pct_lattice():
    assert round_to_nearest_5(31.1) == 30
    assert round_to_nearest_5(29.6) == 30
    assert round_to_nearest_5(7.9) == 10
    assert quantize_base_pct(31.1) == 30


def test_quantize_grid_distance_risky_rounding():
    assert quantize_grid_distance(-7.4, is_buy=True) == -8
    assert quantize_grid_distance(7.4, is_buy=False) == 8


def test_profile_validator_rejects_fractional_base():
    p = V6CatalogProfile(
        profile_id="test",
        scenario=ScenarioIdentity("R2", "01", "01", "PB02", "STD"),
        base_allocation_pct=31,
        quote_allocation_pct=69,
        buy_grids=[GridLevel(-7, 40), GridLevel(-10, 60)],
        sell_grids=[GridLevel(5, 60), GridLevel(9, 40)],
        buyback_after_sell_enabled=True,
        profit_sell_after_buyback_enabled=True,
    )
    assert "base_not_5_step" in validate_profile(p)


def test_catalog_seed_loads():
    cat = load_catalog()
    assert len(cat) >= 2295


def test_catalog_profiles_keep_minimum_buy_surface():
    cat = load_catalog()
    closed = [
        profile.profile_id
        for profile in cat.values()
        if not profile.normal_buy_enabled or not profile.buy_grids
    ]
    assert closed == []


def test_engine_runs_with_seed_catalog():
    inp = V6InputContract(
        symbol="MANTAUSDT",
        bot_budget_usdt=500,
        current_price=0.07,
        min_notional=10,
        tick_size=0.0001,
        step_size=0.1,
        price_precision=4,
        quantity_precision=1,
        range_stability=0.7,
        volatility_percentile=40,
        price_valid=True,
        candles_5m=1500,
        candles_1h=220,
    )
    result = V6Engine().run(inp)
    assert result.catalog_profile_id.startswith("DPLV6_")
    assert result.profile.base_allocation_pct % 5 == 0
    assert result.profile.quote_allocation_pct == 100 - result.profile.base_allocation_pct
