"""Regression lock for Dynamic Param V6 final profile behavior."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.v6.constants import TRAILING_CODES
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (
    v6_final_to_bot_params,
    v6_final_to_telemetry_extras,
)
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display
from app.services.dynamic_param_score.v6.v6_quantizer import (
    profit_pct_from_code,
    trailing_pct_from_code,
)
from tests.dynamic_param_score.test_v6_opportunity_oriented_logic import _base_inp
from tests.dynamic_param_score.test_v6_regime_classification_gates import (
    _arpa_like_inp,
    _btc_high_momentum_inp,
    _doge_like_inp,
    _dydx_deep_drawdown_inp,
    _eth_like_inp,
    _sol_pullback_inp,
    _tlm_parabolic_pump_inp,
)


FORBIDDEN_TRAILING_VALUES = {0.35, 0.6, 0.88, 0.9, 1.2}
FORBIDDEN_DISTRIBUTIONS = {
    (50, 50),
    (33, 33, 34),
    (34, 33, 33),
}


def _run(inp):
    result = V6Engine().run(inp)
    params = v6_final_to_bot_params(result, bot_budget_usdt=float(inp.bot_budget_usdt or 0))
    trace = result.telemetry.get("adjuster_trace") or []
    notes = result.telemetry.get("opportunity_notes") or {}
    display = enrich_v6_display(
        v6_final_to_telemetry_extras(
            result,
            bot_budget_usdt=float(inp.bot_budget_usdt or 0),
            adjuster_trace=trace,
        ),
        adjuster_trace=trace,
        deployable=result.deployable,
        deploy_block_reason=result.deploy_block_reason,
        opportunity_notes=notes,
    )
    return result, params, display, notes, result.telemetry.get("scenario") or {}


def _pct_on_half_step(value: float) -> bool:
    return abs((float(value) * 2) - round(float(value) * 2)) < 1e-9


def _assert_grid_side(levels, *, enabled: bool) -> None:
    assert 0 <= len(levels) <= 5
    if not enabled:
        assert levels == []
        return
    if not levels:
        return
    distances = [int(g.distance_pct) for g in levels]
    amounts = [int(g.amount_pct) for g in levels]
    assert all(abs(d) >= 1 for d in distances)
    assert all(abs(d) == int(abs(d)) for d in distances)
    assert all(a % 5 == 0 for a in amounts)
    assert sum(amounts) == 100
    assert tuple(amounts) not in FORBIDDEN_DISTRIBUTIONS


def _assert_global_invariants(name: str, result, params, display, notes) -> None:
    profile = result.profile
    assert result.profile is not None, name
    assert params is not None, name
    assert notes.get("params_valid") is True, name
    assert profile.base_allocation_pct + profile.quote_allocation_pct == 100, name
    assert profile.base_allocation_pct % 5 == 0, name
    assert profile.quote_allocation_pct % 5 == 0, name
    _assert_grid_side(profile.buy_grids, enabled=profile.normal_buy_enabled)
    _assert_grid_side(profile.sell_grids, enabled=bool(profile.sell_grids))

    trailing_values = [
        trailing_pct_from_code(profile.sell_trailing_code),
        trailing_pct_from_code(profile.buy_trailing_code),
        trailing_pct_from_code(profile.buyback_trailing_code),
        trailing_pct_from_code(profile.profit_sell_trailing_code),
    ]
    assert set(trailing_values).issubset(set(TRAILING_CODES.values())), name
    assert not (set(trailing_values) & FORBIDDEN_TRAILING_VALUES), name

    profit_values = [
        profit_pct_from_code(profile.buyback_trigger_code),
        profit_pct_from_code(profile.profit_sell_trigger_code),
    ]
    assert all(_pct_on_half_step(v) for v in profit_values), name
    assert all(0.5 <= float(v) <= 8.0 for v in profit_values), name

    assert int(display["base_allocation_pct"]) == profile.base_allocation_pct, name
    assert int(display["quote_allocation_pct"]) == profile.quote_allocation_pct, name
    assert int(display["buy_grid_count"]) == params.buy_grid_count, name
    assert int(display["sell_grid_count"]) == params.sell_grid_count, name
    assert display["buy_grid_distances_pct"] == params.buy_grid_ladder_pcts, name
    assert display["sell_grid_distances_pct"] == params.sell_grid_ladder_pcts, name
    assert params.buy_disabled is (not profile.normal_buy_enabled), name


def test_v6_golden_tlm_parabolic_pump_locked():
    result, params, display, notes, scenario = _run(_tlm_parabolic_pump_inp())
    _assert_global_invariants("TLM", result, params, display, notes)
    profile = result.profile
    assert scenario["regime_id"] == "R5"
    assert scenario["sub_profile_hint"] == "R5_DEF_PARABOLIC_OVEREXTENDED"
    assert scenario["regime_id"] != "R8"
    assert (profile.base_allocation_pct, profile.quote_allocation_pct) == (5, 95)
    assert profile.normal_buy_enabled is False
    assert profile.modules.get("new_buys_status") == "paused"
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (5, 45),
        (10, 35),
        (18, 20),
    ]
    assert params.buy_grid_count == 0
    assert params.sell_grid_count == 3
    assert (params.rebuy_trigger_pct, params.rebuy_trail_pct) == (8.0, 1.4)
    assert (params.resell_trigger_pct, params.resell_trail_pct) == (5.0, 1.4)


def test_v6_golden_dydx_deep_drawdown_locked():
    result, params, display, notes, scenario = _run(_dydx_deep_drawdown_inp())
    _assert_global_invariants("DYDX", result, params, display, notes)
    profile = result.profile
    assert scenario["regime_id"] == "R8"
    assert (profile.base_allocation_pct, profile.quote_allocation_pct) == (5, 95)
    assert profile.normal_buy_enabled is False
    assert profile.modules.get("new_buys_status") == "paused"
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (2, 45),
        (5, 35),
        (9, 20),
    ]
    assert params.buy_grid_count == 0
    assert params.sell_grid_count == 3
    assert (params.rebuy_trigger_pct, params.rebuy_trail_pct) == (6.0, 1.4)
    assert (params.resell_trigger_pct, params.resell_trail_pct) == (2.5, 0.5)


def _r2_range_inp():
    return _base_inp(
        symbol="R2USDT",
        range_stability=0.72,
        volatility_percentile=28.0,
        atr_1h_pct=0.65,
        bb_width=1.0,
        asset_fragility_class="F0",
        volume_consistency=0.9,
        spread_pct=0.015,
        btc_return_4h_pct=0.5,
        btc_return_24h_pct=1.0,
    )


def _r3_noisy_range_inp():
    return _base_inp(
        symbol="R3USDT",
        range_stability=0.35,
        volatility_percentile=34.0,
        atr_1h_pct=1.1,
        bb_position=0.2,
        z_score=-1.1,
        bb_width=2.0,
        asset_fragility_class="F1",
        volume_consistency=0.85,
        spread_pct=0.02,
    )


def _r7_downtrend_inp():
    return _base_inp(
        symbol="R7USDT",
        ema20_slope=-0.5,
        ema50_slope=-0.3,
        price_vs_ema200_pct=-5.0,
        adx_1h=31.0,
        return_24h_pct=-4.0,
        lower_lows=True,
        higher_highs=False,
        range_stability=0.38,
        volatility_percentile=72.0,
        atr_1h_pct=2.2,
        asset_fragility_class="F3",
        volume_consistency=0.55,
        spread_pct=0.08,
        btc_return_4h_pct=-1.1,
        btc_crash_velocity=-0.5,
    )


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("SOL", _sol_pullback_inp),
        ("ETH", _eth_like_inp),
        ("BTC", _btc_high_momentum_inp),
        ("DOGE", _doge_like_inp),
        ("ARPA", _arpa_like_inp),
        ("R2", _r2_range_inp),
        ("R3", _r3_noisy_range_inp),
        ("R7", _r7_downtrend_inp),
    ],
)
def test_v6_live_and_regime_cases_locked(name, factory):
    result, params, display, notes, scenario = _run(factory())
    _assert_global_invariants(name, result, params, display, notes)
    profile = result.profile

    if name == "SOL":
        assert scenario["regime_id"] == "R1"
        assert scenario["sub_profile_hint"] == "R1_STD_PULLBACK"
        assert profile.normal_buy_enabled is True
        assert profile.base_allocation_pct >= 55
    elif name == "ETH":
        assert scenario["regime_id"] in ("R1", "R5")
        assert profile.base_allocation_pct >= 40
        assert profile.normal_buy_enabled is True
    elif name == "BTC":
        assert scenario["regime_id"] in ("R1", "R4", "R5")
        assert profile.base_allocation_pct >= 35
        assert profile.normal_buy_enabled is True
    elif name == "DOGE":
        assert scenario["regime_id"] == "R4"
        assert profile.modules.get("new_buys_status") == "active"
        assert abs(profile.buy_grids[0].distance_pct) <= 4
        assert 30 <= profile.base_allocation_pct <= 40
    elif name == "ARPA":
        assert scenario["regime_id"] == "R4"
        assert scenario["sub_profile_hint"] == "R4_RESTRICTED_UNSTABLE"
        assert result.deployable is False
        assert result.deploy_block_reason == "restricted_by_liquidity"
        assert profile.modules.get("new_buys_status") == "restricted"
        assert profile.base_allocation_pct <= 15
        assert {"HIGH_SPREAD", "LOW_VOLUME", "UNSTABLE_RANGE"}.issubset(
            set(notes.get("reason_codes") or [])
        )
    elif name == "R2":
        assert scenario["regime_id"] == "R2"
        assert params.buy_grid_count >= 3
        assert params.sell_grid_count >= 3
        assert params.rebuy_trigger_pct <= 2.0
        assert params.resell_trigger_pct <= 2.0
    elif name == "R3":
        assert scenario["regime_id"] == "R3"
        assert abs(profile.buy_grids[0].distance_pct) <= 2
        assert profile.sell_grids[0].distance_pct <= 2
        assert params.resell_trigger_pct <= 1.5
    elif name == "R7":
        assert scenario["regime_id"] == "R7"
        assert profile.base_allocation_pct <= 35
        assert profile.modules.get("new_buys_status") == "restricted"
        assert params.resell_trigger_pct <= 1.5
