"""V5 test suite — generation, identity, resolver, legacy guard."""

from __future__ import annotations

import os

import pytest

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.domain.math_utils import is_approx_100, round2
from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts, make_route_key, make_shelf_id
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves, generate_shelf
from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index, lookup_exact_v5_shelf
from app.services.dynamic_param_score.v5.resolver.resolve_dynamic_param_v5 import resolve_dynamic_param_v5
from app.services.dynamic_param_score.v5.domain.types import V5ResolveInput
from app.services.dynamic_param_score.v5.store.sqlite_store import shelf_count_in_db, DEFAULT_V5_SQLITE_PATH
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf


@pytest.fixture(scope="module")
def v5_shelves():
    return generate_all_v5_shelves()


@pytest.fixture(scope="module")
def v5_index(v5_shelves):
    return build_v5_route_index(v5_shelves)


def test_expected_shelf_count_constant():
    assert EXPECTED_V5_SHELF_COUNT == 192780


def test_route_identity_standard():
    parts = V5RouteParts(
        asset="A1_BTC_CORE",
        regime="R3_LOW_VOL_SQUEEZE",
        direction="D2_NEUTRAL_BIAS",
        structure="S2_RANGE_UPPER",
        volatility="V2_LOW",
        risk="K1_DEFENSIVE",
        liquidity="L1_HIGH_LIQUIDITY_LOW_COST",
    )
    assert make_route_key(parts) == "A1|R3|D2|S2|V2|K1|L1"
    assert make_shelf_id(parts) == "DPLV5_A1_R3_D2_S2_V2_K1_L1"


def test_generation_count(v5_shelves):
    assert len(v5_shelves) == 192780


def test_unique_keys(v5_shelves):
    assert len({s.route_key for s in v5_shelves}) == 192780
    assert len({s.shelf_id for s in v5_shelves}) == 192780


def test_all_shelves_valid(v5_shelves):
    invalid = [s for s in v5_shelves if not validate_shelf(s).ok]
    assert invalid == []


def test_exact_lookup_all_routes(v5_shelves, v5_index):
    for shelf in v5_shelves:
        found = lookup_exact_v5_shelf(v5_index, shelf.route_key)
        assert found.shelf_id == shelf.shelf_id


def test_r8_forbids_r2_fallback(v5_shelves):
    for shelf in v5_shelves:
        if shelf.route_parts.regime == "R8_CRASH":
            assert "R2_BALANCED_RANGE" in shelf.fallback_policy.forbidden_fallbacks


def test_r15_never_from_r2(v5_shelves):
    for shelf in v5_shelves:
        if shelf.route_parts.regime == "R15_SPECIAL_STRESS_TRANSITION":
            assert "R2_BALANCED_RANGE" in shelf.fallback_policy.forbidden_fallbacks
            assert "R12_CAPITULATION_REACTION" in shelf.fallback_policy.nearest_safe_dimensions


def test_defensive_forbids_raw_normal(v5_shelves):
    for shelf in v5_shelves:
        if shelf.route_parts.risk == "K1_DEFENSIVE":
            assert "K2_NORMAL_CONTROLLED_RAW" in shelf.fallback_policy.forbidden_fallbacks


def test_resolver_exact_all_routes(v5_shelves, v5_index):
    exact = 0
    for shelf in v5_shelves:
        inp = V5ResolveInput(
            symbol="BTCUSDT",
            route_parts=shelf.route_parts,
            budget_usdt=500,
            min_notional_usdt=10,
            current_base_pct=45,
            current_quote_pct=55,
            maker_fee_pct=0.1,
            taker_fee_pct=0.1,
            spread_pct=0.05,
            slippage_pct=0.03,
            rounding_pct=0.01,
            data_quality={"price_valid": True, "freshness_sec": 30, "candle_count5m": 100, "data_gap_sec": 0},
        )
        result = resolve_dynamic_param_v5(inp, v5_index)
        assert result.selection_type == "EXACT_V5"
        assert result.shelf_id == shelf.shelf_id
        exact += 1
    assert exact == 192780


def test_trailing_hard_limit(v5_shelves):
    for shelf in v5_shelves:
        t = shelf.base_template
        assert t.sell_trailing_pct <= round2(t.sell_grid_levels_pct[0] * 0.30) + 0.01
        assert t.buy_trailing_pct <= round2(t.buy_grid_levels_pct[0] * 0.30) + 0.01


def test_db_seed_count():
    if not DEFAULT_V5_SQLITE_PATH.exists():
        pytest.skip("V5 DB not seeded")
    assert shelf_count_in_db() == 192780


def test_no_legacy_v4_runtime_when_v5_enabled(monkeypatch):
    monkeypatch.setenv("PARAM_POOL_VERSION", "v5.0.0")
    from app.services.dynamic_param_score.param_pool.versioning import resolve_pool_version

    assert resolve_pool_version() == "v5.0.0"
    from app.services.dynamic_param_score.v5.bridge import v5_pool_enabled

    assert v5_pool_enabled()


def test_v5_bridge_select(monkeypatch):
    monkeypatch.setenv("PARAM_POOL_VERSION", "v5.0.0")
    from app.services.dynamic_param_score.models import (
        BotContext,
        ExchangeConstraints,
        IndicatorSnapshot,
        PortfolioState,
        RegimeTag,
        SubScores,
    )
    from app.services.dynamic_param_score.v5.bridge import v5_select_and_render

    sub = SubScores(
        range_score=60,
        liquidity_score=70,
        spread_score=70,
        fee_efficiency_score=70,
        volatility_score=50,
        data_quality_score=80,
        btc_market_risk_score=50,
        exposure_safety_score=60,
    )
    ind = IndicatorSnapshot(
        return_24h_pct=0.5,
        atr14_pct_5m=1.0,
        atr14_pct_1h=1.2,
        orderbook_spread_pct=0.1,
        rsi14_1h=50,
        price_in_bb=0.5,
    )
    portfolio = PortfolioState(
        base_balance=0.002,
        quote_balance=400,
        base_value_usdt=100,
        quote_value_usdt=400,
        total_equity_usdt=500,
        current_base_exposure_frac=0.2,
    )
    constraints = ExchangeConstraints(
        min_notional=10,
        step_size=0.0001,
        tick_size=0.01,
        min_qty=0.0001,
        maker_fee_pct=0.1,
        taker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )
    ctx = BotContext(run_source="param_assistant", budget_usdt=500, bot_id=1)
    selection, params, bucket = v5_select_and_render(
        65,
        RegimeTag.BALANCED_RANGE,
        "NORMAL",
        sub,
        ind,
        portfolio,
        constraints,
        ctx,
        500,
        10,
        symbol="BTCUSDT",
    )
    assert selection.selected_template_key.startswith("DPLV5_")
    assert params is not None
    assert selection.selection_context.get("selection_type") == "EXACT_V5"
    assert "DPLV4_" not in (selection.selected_template_key or "")
