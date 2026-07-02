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


def _btc_trend_cooldown_inp():
    return _base_inp(
        symbol="BTCUSDT",
        adx_1h=36,
        rsi_5m=53.1,
        rsi_1h=65.6,
        ema20_slope=0.01,
        ema50_slope=0.03,
        price_vs_ema200_pct=2.03,
        roc_5m=0.02,
        higher_highs=True,
        lower_lows=False,
        atr_5m_pct=0.20,
        atr_1h_pct=0.77,
        volatility_percentile=63.18,
        bb_width=1.02,
        bb_position=0.59,
        z_score=0.36,
        range_stability=0.44,
        return_1h_pct=0.02,
        return_4h_pct=-0.54,
        return_24h_pct=2.6,
        drawdown_7d_pct=0.32,
        spread_pct=0.0,
        volume_24h=1_500_000_000.0,
        volume_consistency=0.95,
        asset_fragility_class="F0",
    )


def _overextended_top_inp():
    return _base_inp(
        symbol="TOPUSDT",
        adx_1h=30,
        rsi_5m=68,
        rsi_1h=72,
        ema20_slope=-0.02,
        ema50_slope=0.05,
        price_vs_ema200_pct=6.5,
        roc_5m=-0.1,
        higher_highs=True,
        lower_lows=False,
        volatility_percentile=62,
        atr_1h_pct=1.5,
        bb_position=0.82,
        z_score=1.2,
        range_stability=0.45,
        return_4h_pct=2.2,
        return_24h_pct=5.5,
        spread_pct=0.01,
        volume_24h=100_000_000.0,
        volume_consistency=0.9,
        volume_spike=2.8,
        asset_fragility_class="F1",
    )


def test_btc_trend_cooldown_not_r6_top_distribution_act():
    result, params, display, notes, scenario = _run(_btc_trend_cooldown_inp())
    _assert_global_invariants("BTC trend cooldown", result, params, display, notes)
    profile = result.profile
    title_blob = " ".join(
        str(v or "").lower()
        for v in (
            display.get("regime_headline"),
            display.get("market_status_plain"),
            display.get("regime_strategy_why"),
            scenario.get("label"),
        )
    )
    assert scenario["regime_id"] == "R1"
    assert scenario["sub_profile_hint"] == "R1_STD_TREND_COOLDOWN"
    assert scenario["regime_id"] not in ("R6", "R8")
    assert scenario["sub_profile_hint"] != "R5_DEF_PARABOLIC_OVEREXTENDED"
    assert not (scenario["severity"] == "ACT" and profile.base_allocation_pct >= 70)
    assert profile.base_allocation_pct in (55, 60, 65)
    assert profile.quote_allocation_pct in (35, 40, 45)
    assert params.max_base_exposure_frac <= 0.80
    assert [(abs(g.distance_pct), g.amount_pct) for g in profile.buy_grids] == [
        (2, 15),
        (4, 30),
        (7, 55),
    ]
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (2, 10),
        (4, 15),
        (7, 20),
        (11, 25),
        (16, 30),
    ]
    assert params.rebuy_trigger_pct in (2.5, 3.0)
    assert params.rebuy_trail_pct in (0.8, 1.1)
    assert params.resell_trigger_pct in (2.0, 2.5)
    assert params.resell_trail_pct in (0.8, 1.1)
    assert "düşüş sonrası toparlanma" not in title_blob
    assert "tepe" not in title_blob
    assert "dağılım" not in title_blob


def test_no_profile_can_be_act_and_top_distribution_with_high_base():
    result, params, display, notes, scenario = _run(_overextended_top_inp())
    _assert_global_invariants("overextended top", result, params, display, notes)
    text = " ".join(
        str(v or "").lower()
        for v in (
            display.get("regime_headline"),
            display.get("market_status_plain"),
            display.get("regime_strategy_why"),
            scenario.get("label"),
        )
    )
    if any(term in text for term in ("tepe", "dağılım", "geri çekilme riski", "aşırı")):
        assert scenario["severity"] != "ACT"
        assert result.profile.base_allocation_pct <= 55
        assert params.max_base_exposure_frac <= 0.65
        assert result.profile.modules.get("new_buys_status") in ("restricted", "defensive", "paused")


def _clean_breakout_act_inp():
    return _base_inp(
        symbol="BREAKUSDT",
        adx_1h=34.0,
        rsi_5m=64.0,
        rsi_1h=66.0,
        ema20_slope=0.35,
        ema50_slope=0.22,
        price_vs_ema200_pct=4.5,
        roc_5m=0.8,
        higher_highs=True,
        lower_lows=False,
        atr_1h_pct=1.4,
        volatility_percentile=55.0,
        bb_width=2.8,
        bb_position=0.68,
        z_score=0.8,
        range_stability=0.48,
        return_1h_pct=0.9,
        return_4h_pct=1.8,
        return_24h_pct=4.8,
        drawdown_7d_pct=0.0,
        spread_pct=0.01,
        volume_24h=200_000_000.0,
        volume_consistency=0.92,
        asset_fragility_class="F1",
    )


def test_clean_breakout_act_not_capped_by_overextended_guard():
    result, params, display, notes, scenario = _run(_clean_breakout_act_inp())
    _assert_global_invariants("clean breakout", result, params, display, notes)
    assert scenario["regime_id"] in ("R5", "R1")
    assert scenario["sub_profile_hint"] == "R5_ACT_CLEAN_BREAKOUT"
    assert scenario["severity"] == "ACT"
    assert 70 <= result.profile.base_allocation_pct <= 75
    assert params.sell_grid_count >= 5
    assert "Temiz breakout" in display["regime_headline"]


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
        assert scenario["severity"] != "ACT"
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
