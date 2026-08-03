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


# Net profile library intentionally uses 0.35 / 0.6 / 0.9 / 1.2 trails.
# Only keep values that are not on the live trailing lattice.
FORBIDDEN_TRAILING_VALUES = {0.88}
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
    scenario = result.telemetry.get("scenario") or {}
    display_base = v6_final_to_telemetry_extras(
        result,
        bot_budget_usdt=float(inp.bot_budget_usdt or 0),
        adjuster_trace=trace,
    )
    scen_id = dict(display_base.get("scenario_identity") or {})
    scen_id.update(
        {
            "canonical_headline": scenario.get("canonical_headline") or scen_id.get("canonical_headline"),
            "headline": scenario.get("headline") or scen_id.get("headline"),
            "selected_profile_key": scenario.get("selected_profile_key")
            or scenario.get("net_profile_key")
            or scen_id.get("selected_profile_key"),
            "net_profile_key": scenario.get("net_profile_key") or scen_id.get("net_profile_key"),
            "sub_profile_hint": scenario.get("sub_profile_hint") or "",
        }
    )
    display_base["scenario_identity"] = scen_id
    display = enrich_v6_display(
        display_base,
        adjuster_trace=trace,
        deployable=result.deployable,
        deploy_block_reason=result.deploy_block_reason,
        opportunity_notes=notes,
    )
    return result, params, display, notes, scenario


def _pct_on_half_step(value: float) -> bool:
    return abs((float(value) * 2) - round(float(value) * 2)) < 1e-9


def _assert_grid_side(levels, *, enabled: bool, allow_reference: bool = False) -> None:
    assert 0 <= len(levels) <= 5
    if not enabled and not (allow_reference and levels):
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
    reference = bool((profile.modules or {}).get("reference_plan_only"))
    _assert_grid_side(
        profile.buy_grids,
        enabled=profile.normal_buy_enabled,
        allow_reference=reference,
    )
    _assert_grid_side(profile.sell_grids, enabled=bool(profile.sell_grids))
    # Fixed weekly 4+4 library contract.
    if (profile.modules or {}).get("grid_contract") == "fixed_4x4":
        assert len(profile.buy_grids) == 4, name
        assert len(profile.sell_grids) == 4, name

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
    assert all(0.5 <= float(v) <= 10.0 for v in profit_values), name

    assert int(display["base_allocation_pct"]) == profile.base_allocation_pct, name
    assert int(display["quote_allocation_pct"]) == profile.quote_allocation_pct, name
    # PA display always shows authored ladders; live BotParams zeros buys when closed.
    assert int(display["buy_grid_count"]) == len(profile.buy_grids), name
    assert int(display["sell_grid_count"]) == len(profile.sell_grids), name
    assert display["buy_grid_distances_pct"] == [abs(g.distance_pct) for g in profile.buy_grids], name
    assert display["sell_grid_distances_pct"] == [g.distance_pct for g in profile.sell_grids], name
    reference = bool((profile.modules or {}).get("reference_plan_only"))
    if reference:
        assert params.buy_grid_count == 0, name
        assert params.sell_grid_count == 0, name
        assert params.buy_grid_ladder_pcts == [], name
        assert params.sell_grid_ladder_pcts == [], name
    elif profile.normal_buy_enabled:
        assert int(display["buy_grid_count"]) == params.buy_grid_count, name
        assert display["buy_grid_distances_pct"] == params.buy_grid_ladder_pcts, name
        assert display["sell_grid_distances_pct"] == params.sell_grid_ladder_pcts, name
    else:
        assert params.buy_grid_count == 0, name
        assert params.buy_grid_ladder_pcts == [], name
        assert display["sell_grid_distances_pct"] == params.sell_grid_ladder_pcts, name
    assert params.buy_disabled is (not profile.normal_buy_enabled), name


def test_v6_golden_tlm_parabolic_pump_locked():
    result, params, display, notes, scenario = _run(_tlm_parabolic_pump_inp())
    _assert_global_invariants("TLM", result, params, display, notes)
    profile = result.profile
    assert scenario["regime_id"] == "R5"
    assert scenario["sub_profile_hint"] == "R5_DEF_PARABOLIC_OVEREXTENDED"
    assert scenario["regime_id"] != "R8"
    assert profile.profile_id == "R5_PARABOLIC_PUMP"
    assert (profile.base_allocation_pct, profile.quote_allocation_pct) == (20, 80)
    assert profile.normal_buy_enabled is True
    assert [(abs(g.distance_pct), g.amount_pct) for g in profile.buy_grids] == [
        (7, 20),
        (10, 20),
        (12, 30),
        (15, 30),
    ]
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (1, 40),
        (2, 30),
        (4, 20),
        (7, 10),
    ]
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    assert (params.rebuy_trigger_pct, params.rebuy_trail_pct) == (10.0, 2.0)
    assert (params.resell_trigger_pct, params.resell_trail_pct) == (3.0, 1.75)


def test_v6_golden_dydx_deep_drawdown_locked():
    result, params, display, notes, scenario = _run(_dydx_deep_drawdown_inp())
    _assert_global_invariants("DYDX", result, params, display, notes)
    profile = result.profile
    assert scenario["regime_id"] == "R8"
    assert scenario["sub_profile_hint"] == "R8_DEF_PANIC"
    assert profile.profile_id == "R8_CRASH_PANIC"
    assert profile.normal_buy_enabled is False
    assert bool((profile.modules or {}).get("reference_plan_only")) is True
    assert [(abs(g.distance_pct), g.amount_pct) for g in profile.buy_grids] == [
        (8, 20),
        (11, 20),
        (13, 30),
        (15, 30),
    ]
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (3, 40),
        (6, 30),
        (10, 20),
        (15, 10),
    ]
    assert params.buy_grid_count == 0
    assert params.sell_grid_count == 0
    assert result.deployable is False


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
    assert profile.profile_id == "R1_TREND_COOLDOWN"
    assert profile.base_allocation_pct == 50
    assert profile.quote_allocation_pct == 50
    assert params.max_base_exposure_frac <= 0.80
    assert [(abs(g.distance_pct), g.amount_pct) for g in profile.buy_grids] == [
        (2, 30),
        (4, 30),
        (7, 20),
        (10, 20),
    ]
    assert [(g.distance_pct, g.amount_pct) for g in profile.sell_grids] == [
        (1, 30),
        (3, 30),
        (5, 20),
        (8, 20),
    ]
    assert params.rebuy_trigger_pct == 4.0
    assert params.rebuy_trail_pct == 0.75
    assert params.resell_trigger_pct == 3.0
    assert params.resell_trail_pct == 0.75
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
    assert result.profile.profile_id == "R5_CLEAN_BREAKOUT"
    assert result.profile.base_allocation_pct == 70
    assert params.sell_grid_count == 4
    assert params.buy_grid_count == 4
    assert "Temiz Breakout" in display["regime_headline"] or "temiz breakout" in display["regime_headline"].lower()


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
        assert profile.profile_id == "R4_LIQUID_VOLATILE_RANGE"
        assert profile.modules.get("new_buys_status") == "active"
        assert abs(profile.buy_grids[0].distance_pct) <= 2
        assert profile.base_allocation_pct == 50
    elif name == "ARPA":
        assert scenario["regime_id"] == "R4"
        assert scenario["sub_profile_hint"] == "R4_RESTRICTED_UNSTABLE"
        assert result.deployable is False
        assert result.deploy_block_reason == "restricted_by_liquidity"
        assert profile.modules.get("new_buys_status") == "restricted"
        assert profile.base_allocation_pct == 20
        assert len(profile.buy_grids) == 4
        assert {"HIGH_SPREAD", "LOW_VOLUME", "UNSTABLE_RANGE"}.issubset(
            set(notes.get("reason_codes") or [])
        )
    elif name == "R2":
        assert scenario["regime_id"] == "R2"
        assert params.buy_grid_count == 4
        assert params.sell_grid_count == 4
        assert params.rebuy_trigger_pct == 3.0
        assert params.resell_trigger_pct == 3.0
    elif name == "R3":
        assert scenario["regime_id"] == "R3"
        assert abs(profile.buy_grids[0].distance_pct) <= 2
        assert profile.sell_grids[0].distance_pct <= 2
        assert params.resell_trigger_pct == 3.0
    elif name == "R7":
        assert scenario["regime_id"] == "R7"
        assert profile.base_allocation_pct == 20
        assert profile.modules.get("new_buys_status") == "restricted"
        assert params.resell_trigger_pct == 3.0


def _display_blob(display, scenario, notes):
    return " ".join(
        str(v or "").lower()
        for v in (
            display.get("regime_headline"),
            display.get("market_status_plain"),
            display.get("regime_strategy_why"),
            display.get("operational_mode_plain"),
            display.get("safety_result_label"),
            scenario.get("label"),
            notes.get("semantic_role"),
        )
    )


def _bnb_r3_compression_inp():
    return _base_inp(
        symbol="BNBUSDT",
        adx_1h=18,
        rsi_1h=53,
        ema20_slope=0.01,
        ema50_slope=0.01,
        price_vs_ema200_pct=1.2,
        roc_5m=0.03,
        higher_highs=False,
        lower_lows=False,
        atr_1h_pct=0.55,
        volatility_percentile=23,
        bb_width=0.78,
        bb_position=0.54,
        z_score=0.12,
        range_stability=0.40,
        return_24h_pct=0.7,
        spread_pct=0.01,
        volume_24h=900_000_000,
        volume_consistency=0.95,
        asset_fragility_class="F0",
    )


def _ada_post_breakout_cooldown_inp():
    return _base_inp(
        symbol="ADAUSDT",
        adx_1h=34,
        rsi_5m=54,
        rsi_1h=61,
        ema20_slope=0.20,
        ema50_slope=0.13,
        price_vs_ema200_pct=5.2,
        roc_5m=0.16,
        higher_highs=False,
        lower_lows=False,
        atr_1h_pct=1.2,
        volatility_percentile=48,
        bb_width=2.2,
        bb_position=0.68,
        z_score=0.76,
        range_stability=0.46,
        return_4h_pct=0.7,
        return_24h_pct=4.2,
        drawdown_7d_pct=0.4,
        spread_pct=0.01,
        volume_24h=260_000_000,
        volume_consistency=0.88,
        asset_fragility_class="F1",
    )


def _aigensyn_recovery_inp():
    return _base_inp(
        symbol="AIGENSYNUSDT",
        adx_1h=30,
        rsi_5m=57,
        rsi_1h=52,
        ema20_slope=0.18,
        ema50_slope=0.12,
        price_vs_ema200_pct=-1.5,
        roc_5m=0.35,
        higher_highs=True,
        lower_lows=False,
        atr_1h_pct=1.7,
        volatility_percentile=58,
        bb_width=3.0,
        bb_position=0.58,
        z_score=0.2,
        range_stability=0.42,
        return_1h_pct=1.0,
        return_4h_pct=1.8,
        return_24h_pct=-7.5,
        drawdown_7d_pct=13,
        red_pressure=0.42,
        spread_pct=0.03,
        volume_24h=8_000_000,
        volume_consistency=0.65,
        asset_fragility_class="F2",
    )


def _r5_high_spread_overextended_inp():
    return _base_inp(
        symbol="WIDEUSDT",
        adx_1h=33,
        rsi_5m=68,
        rsi_1h=71,
        ema20_slope=0.20,
        ema50_slope=0.10,
        price_vs_ema200_pct=7.0,
        roc_5m=-0.05,
        higher_highs=True,
        lower_lows=False,
        atr_1h_pct=2.0,
        volatility_percentile=62,
        bb_width=4.0,
        bb_position=0.84,
        z_score=1.35,
        range_stability=0.44,
        return_4h_pct=2.1,
        return_24h_pct=6.0,
        spread_pct=0.18,
        volume_24h=650_000,
        volume_consistency=0.22,
        zero_volume_flag=1,
        asset_fragility_class="F3",
    )


def _sky_r5_overextended_inp():
    return _base_inp(
        symbol="SKYUSDT",
        adx_1h=31,
        rsi_5m=66,
        rsi_1h=70,
        ema20_slope=0.12,
        ema50_slope=0.10,
        price_vs_ema200_pct=6.4,
        roc_5m=-0.04,
        higher_highs=True,
        lower_lows=False,
        atr_1h_pct=1.5,
        volatility_percentile=58,
        bb_width=3.5,
        bb_position=0.81,
        z_score=1.22,
        range_stability=0.45,
        return_4h_pct=1.9,
        return_24h_pct=5.6,
        volume_spike=2.6,
        spread_pct=0.02,
        volume_24h=18_000_000,
        volume_consistency=0.8,
        asset_fragility_class="F2",
    )


def _cat_low_liq_r4_inp():
    return _base_inp(
        symbol="1000CATUSDT",
        adx_1h=17,
        rsi_1h=49,
        ema20_slope=-0.04,
        ema50_slope=-0.02,
        price_vs_ema200_pct=-0.8,
        higher_highs=False,
        lower_lows=False,
        atr_1h_pct=1.5,
        volatility_percentile=64,
        bb_width=3.6,
        bb_position=0.50,
        z_score=0.0,
        range_stability=0.36,
        return_24h_pct=-0.8,
        spread_pct=0.16,
        volume_24h=480_000,
        volume_consistency=0.20,
        zero_volume_flag=1,
        asset_fragility_class="F3",
    )


def _baby_low_liq_r3_inp():
    return _base_inp(
        symbol="1MBABYDOGEUSDT",
        adx_1h=15,
        rsi_1h=51,
        ema20_slope=-0.01,
        ema50_slope=0.0,
        price_vs_ema200_pct=0.2,
        higher_highs=False,
        lower_lows=False,
        atr_1h_pct=0.70,
        volatility_percentile=22,
        bb_width=0.82,
        bb_position=0.48,
        z_score=-0.05,
        range_stability=0.34,
        return_24h_pct=0.1,
        spread_pct=0.14,
        volume_24h=420_000,
        volume_consistency=0.18,
        zero_volume_flag=1,
        asset_fragility_class="F3",
    )


def _r8_deep_crash_probe_inp():
    return _base_inp(
        symbol="CRASHUSDT",
        adx_1h=36,
        rsi_5m=38,
        rsi_1h=33,
        ema20_slope=-0.7,
        ema50_slope=-0.5,
        price_vs_ema200_pct=-38,
        roc_5m=0.15,
        higher_highs=False,
        lower_lows=True,
        atr_1h_pct=5.5,
        volatility_percentile=94,
        bb_width=10.0,
        bb_position=0.12,
        z_score=-2.6,
        range_stability=0.22,
        return_1h_pct=-2.0,
        return_4h_pct=1.2,
        return_24h_pct=-46,
        drawdown_7d_pct=55,
        drawdown_30d_pct=62,
        crash_velocity=-2.4,
        red_pressure=0.45,
        spread_pct=0.06,
        volume_24h=12_000_000,
        volume_consistency=0.62,
        asset_fragility_class="F2",
    )


def _r8_low_liq_fragile_inp():
    return _base_inp(
        symbol="LOWLIQR8USDT",
        adx_1h=52,
        rsi_5m=38.8,
        rsi_1h=48.2,
        ema20_slope=-0.19,
        ema50_slope=-0.05,
        price_vs_ema200_pct=0.28,
        roc_5m=-1.53,
        higher_highs=True,
        lower_lows=True,
        atr_5m_pct=0.86,
        atr_1h_pct=3.03,
        volatility_percentile=58.57,
        bb_width=2.21,
        bb_position=-0.09,
        z_score=-2.41,
        mean_reversion_score=0.27,
        range_stability=0.0,
        return_1h_pct=-1.53,
        return_4h_pct=-0.57,
        return_24h_pct=0.12,
        drawdown_7d_pct=22.55,
        drawdown_30d_pct=22.55,
        crash_velocity=-1.85,
        red_pressure=0.1,
        spread_pct=0.73,
        volume_24h=144_300,
        volume_consistency=0.21,
        volume_spike=6.54,
        zero_volume_flag=1,
        asset_fragility_class="F3",
    )


def test_bnb_r3_compression_display_not_deep_buy_label():
    result, params, display, notes, scenario = _run(_bnb_r3_compression_inp())
    _assert_global_invariants("BNB R3 compression", result, params, display, notes)
    assert scenario["regime_id"] == "R3"
    assert scenario["sub_profile_hint"] in ("R3_STD_CONTROLLED_COMPRESSION", "R3_STD_UPTREND_COMPRESSION")
    assert result.profile.profile_id in ("R3_CONTROLLED_COMPRESSION", "R3_UPTREND_COMPRESSION")
    assert result.profile.base_allocation_pct in (50, 70)
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    blob = _display_blob(display, scenario, notes)
    assert "derin alış açık" not in blob
    assert "yakın alış gridleri açık" in blob


def test_ada_r5_post_breakout_cooldown_not_recovery_text():
    result, params, display, notes, scenario = _run(_ada_post_breakout_cooldown_inp())
    _assert_global_invariants("ADA post breakout cooldown", result, params, display, notes)
    assert scenario["regime_id"] == "R5"
    assert scenario["sub_profile_hint"] == "R5_STD_POST_BREAKOUT_COOLDOWN"
    assert notes["semantic_role"] == "POST_BREAKOUT_COOLDOWN"
    assert result.profile.base_allocation_pct <= 50
    blob = _display_blob(display, scenario, notes)
    assert "kontrollü soğuma" in blob
    assert "toparlanma aşamasında" not in blob
    assert "coin payı artır" not in blob


def test_aigensyn_recovery_uses_recovery_semantic_not_generic_r5():
    result, params, display, notes, scenario = _run(_aigensyn_recovery_inp())
    _assert_global_invariants("AIGENSYN recovery", result, params, display, notes)
    assert scenario["regime_id"] == "R6"
    assert scenario["sub_profile_hint"] == "R6_RECOVERY_BREAKOUT"
    assert notes["semantic_role"] == "RECOVERY"
    assert result.profile.profile_id == "R6_RECOVERY_BREAKOUT"
    assert result.profile.base_allocation_pct == 70
    blob = _display_blob(display, scenario, notes)
    assert "recovery" in blob or "toparlanma" in blob
    assert "r5" not in blob


def test_r5_high_spread_overextended_becomes_restricted():
    result, params, display, notes, scenario = _run(_r5_high_spread_overextended_inp())
    _assert_global_invariants("high spread R5", result, params, display, notes)
    assert scenario["regime_id"] == "R5"
    assert result.deployable is False
    assert result.deploy_block_reason == "restricted_by_liquidity"
    # Sealed weekly library keeps authored shape; liquidity only blocks deploy.
    assert result.profile.profile_id == "R5_OVEREXTENDED"
    assert result.profile.base_allocation_pct == 40
    assert result.profile.normal_buy_enabled is True
    assert len(result.profile.buy_grids) == 4
    assert notes.get("mandatory_deep_buy_skipped") == "net_profile_sealed_4x4"
    assert notes["semantic_role"] == "OVEREXTENDED_LOW_LIQUIDITY"
    assert {"LOW_LIQUIDITY_RESTRICTED", "RESTRICTED_DEPLOY"}.issubset(set(notes["reason_codes"]))
    assert "restricted" in _display_blob(display, scenario, notes)


def test_sky_r5_overextended_display_not_recovery():
    result, params, display, notes, scenario = _run(_sky_r5_overextended_inp())
    _assert_global_invariants("SKY overextended", result, params, display, notes)
    assert scenario["regime_id"] == "R5"
    assert scenario["sub_profile_hint"] == "R5_DEF_OVEREXTENDED"
    assert notes["semantic_role"] == "OVEREXTENDED_MOMENTUM"
    blob = _display_blob(display, scenario, notes)
    assert "üst bölgede" in blob or "aşırı" in blob
    assert "toparlanma aşamasında" not in blob
    assert "coin payı artır" not in blob


def test_1000cat_r4_low_liq_not_std_display():
    result, params, display, notes, scenario = _run(_cat_low_liq_r4_inp())
    _assert_global_invariants("1000CAT low-liq", result, params, display, notes)
    assert scenario["regime_id"] == "R4"
    assert scenario["sub_profile_hint"] == "R4_RESTRICTED_UNSTABLE"
    assert result.profile.profile_id == "R4_RESTRICTED_UNSTABLE"
    assert result.deployable is False
    assert result.deploy_block_reason == "restricted_by_liquidity"
    assert result.profile.normal_buy_enabled is False
    assert params.buy_grid_count == 0
    assert params.sell_grid_count == 0
    assert display["buy_grid_count"] == 4  # reference plan visible in PA
    assert display["sell_grid_count"] == 4
    assert notes["semantic_role"] == "LOW_LIQUIDITY_RESTRICTED"
    blob = _display_blob(display, scenario, notes)
    assert "restricted" in blob
    assert "normal aktif" not in blob


def test_1mbabydoge_r3_low_liq_compression_restricted():
    result, params, display, notes, scenario = _run(_baby_low_liq_r3_inp())
    _assert_global_invariants("1MBABYDOGE low-liq", result, params, display, notes)
    assert scenario["regime_id"] == "R3"
    assert result.deployable is False
    assert result.deploy_block_reason == "restricted_by_liquidity"
    # Sealed library keeps authored compression shape; liquidity blocks deploy only.
    assert result.profile.base_allocation_pct in (40, 50)
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    assert notes["semantic_role"] == "R3_RESTRICTED_LOW_LIQUIDITY_COMPRESSION"


def test_r8_deep_crash_supports_conditional_probe_metadata():
    result, params, display, notes, scenario = _run(_r8_deep_crash_probe_inp())
    _assert_global_invariants("R8 conditional probe", result, params, display, notes)
    assert scenario["regime_id"] == "R8"
    assert scenario["sub_profile_hint"] == "R8_CAPITULATION_CONDITIONAL_PROBE"
    assert result.profile.profile_id == "R8_CAPITULATION_PROBE"
    assert result.deployable is False
    assert result.deploy_block_reason == "conditional_probe_only"
    # Kapalı reference plan: buys off for live, but 4+4 ladders remain for PA.
    assert result.profile.normal_buy_enabled is False
    assert len(result.profile.buy_grids) == 4
    assert params.buy_grid_count == 0
    probe = notes.get("conditional_probe") or {}
    assert probe.get("enabled") is True
    assert "conditional probe" in _display_blob(display, scenario, notes)


def test_r8_low_liq_restricted_uses_deeper_grid_and_not_crash_copy():
    result, params, display, notes, scenario = _run(_r8_low_liq_fragile_inp())
    _assert_global_invariants("R8 low-liq restricted", result, params, display, notes)
    assert scenario["regime_id"] == "R8"
    assert result.deployable is False
    # Fully closed operator profile → no trade surface (technical_block), not a
    # deployable restricted grid. Semantic role still names liquidity.
    assert result.deploy_block_reason in ("technical_block", "restricted_by_liquidity")
    assert notes["semantic_role"] == "R8_LOW_LIQUIDITY_RESTRICTED"
    from app.services.dynamic_param_score.v6.net_profile_library import (
        PROFILE_COPY,
        canonical_headline_for_key,
    )

    expected_key = "R8_LOW_LIQUIDITY_RESTRICTED"
    expected_headline = canonical_headline_for_key(expected_key)
    assert result.profile.profile_id == expected_key
    assert display["regime_headline"] == f"R8 · {expected_headline}"
    assert display["canonical_headline"] == expected_headline
    assert display["regime_headline"] == f"R8 · {PROFILE_COPY[expected_key][0]}"
    assert result.profile.normal_buy_enabled is False
    assert params.buy_grid_count == 0
    blob = _display_blob(display, scenario, notes)
    assert "likidite/spread riski yüksek" in blob or "restricted" in blob
    assert "crash profilinde" not in blob
    assert "sert düşüşte micro base" not in blob


def test_no_r5_base_le_50_says_coin_pay_increased():
    for factory in (_ada_post_breakout_cooldown_inp, _sky_r5_overextended_inp, _r5_high_spread_overextended_inp):
        result, params, display, notes, scenario = _run(factory())
        _assert_global_invariants(str(factory), result, params, display, notes)
        if scenario["regime_id"] == "R5" and result.profile.base_allocation_pct <= 50:
            blob = _display_blob(display, scenario, notes)
            assert "coin payı artır" not in blob
            assert "coin tabanı tercih edildi" not in blob
            assert "toparlanma aşamasında" not in blob


def test_low_liq_veto_caps_base_and_deployable_across_regimes():
    for factory in (_r5_high_spread_overextended_inp, _cat_low_liq_r4_inp, _baby_low_liq_r3_inp):
        result, params, display, notes, scenario = _run(factory())
        _assert_global_invariants(str(factory), result, params, display, notes)
        assert result.deployable is False
        assert result.deploy_block_reason == "restricted_by_liquidity"
        # Weekly sealed library preserves authored base; veto only blocks deploy.
        assert result.profile.base_allocation_pct <= 50
        assert len(result.profile.buy_grids) == 4
        assert len(result.profile.sell_grids) == 4
        assert "LOW_LIQUIDITY_RESTRICTED" in set(notes["reason_codes"])


def _assert_profit_loop_filled(result, params):
    assert result.profile.buyback_after_sell_enabled is True
    assert result.profile.profit_sell_after_buyback_enabled is True
    assert params.rebuy_enabled is True
    assert params.resell_enabled is True
    assert params.rebuy_trigger_pct is not None
    assert params.resell_trigger_pct is not None
    assert params.rebuy_trail_pct is not None
    assert params.resell_trail_pct is not None


def test_v6_does_not_choose_safest_profile_when_reward_is_high():
    result, params, display, notes, scenario = _run(_clean_breakout_act_inp())
    _assert_global_invariants("risk/reward clean breakout", result, params, display, notes)
    rr = notes["risk_reward"]
    assert notes["profile_resolver_objective"] == "maximize_controlled_risk_reward_not_minimize_risk"
    assert scenario["sub_profile_hint"] == "R5_ACT_CLEAN_BREAKOUT"
    assert scenario["severity"] == "ACT"
    assert result.deployable is True
    assert result.profile.base_allocation_pct >= 70
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    assert rr["reward_score"] > rr["risk_score"]
    assert "safest" not in _display_blob(display, scenario, notes)


def test_v6_std_is_balanced_risk_reward_not_passive():
    result, params, display, notes, scenario = _run(_ada_post_breakout_cooldown_inp())
    _assert_global_invariants("STD balanced cooldown", result, params, display, notes)
    assert scenario["severity"] == "STD"
    assert result.profile.profile_id == "R5_POST_BREAKOUT_COOLDOWN"
    assert result.profile.base_allocation_pct == 50
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    _assert_profit_loop_filled(result, params)
    blob = _display_blob(display, scenario, notes)
    assert "usdt rezervi korunur" in blob
    assert "kâr" in blob or "kar" in blob
    assert "alış kapalı" not in blob


def test_v6_def_still_has_working_profit_loop():
    result, params, display, notes, scenario = _run(_r7_downtrend_inp())
    _assert_global_invariants("DEF working loop", result, params, display, notes)
    assert scenario["severity"] == "DEF"
    assert 15 <= result.profile.base_allocation_pct <= 35
    assert params.buy_grid_count > 0
    assert params.sell_grid_count > 0
    _assert_profit_loop_filled(result, params)
    assert result.profile.modules.get("new_buys_status") == "restricted"


def test_v6_low_vol_grids_are_triggerable():
    result, params, display, notes, scenario = _run(_bnb_r3_compression_inp())
    _assert_global_invariants("low-vol triggerable grids", result, params, display, notes)
    assert scenario["regime_id"] == "R3"
    assert params.buy_grid_ladder_pcts[0] <= 2
    assert params.sell_grid_ladder_pcts[0] <= 2
    assert params.rebuy_trigger_pct <= 4.0
    assert params.resell_trigger_pct <= 4.0
    blob = _display_blob(display, scenario, notes)
    assert "tekrarlanabilir" in blob


def test_v6_high_vol_grids_are_wide_but_not_dead():
    result, params, display, notes, scenario = _run(_doge_like_inp())
    _assert_global_invariants("high-vol working grids", result, params, display, notes)
    assert scenario["regime_id"] == "R4"
    assert 2 <= params.buy_grid_ladder_pcts[0] <= 5
    assert 2 <= params.sell_grid_ladder_pcts[0] <= 6
    assert params.buy_grid_count == 4
    assert params.sell_grid_count == 4
    assert result.profile.base_allocation_pct >= 30
    blob = _display_blob(display, scenario, notes)
    assert "aktif kalır" in blob or "fitillerde" in blob


def test_v6_overextended_liquid_asset_uses_controlled_profit_profile_not_zero_opportunity():
    result, params, display, notes, scenario = _run(_sky_r5_overextended_inp())
    _assert_global_invariants("liquid overextended opportunity", result, params, display, notes)
    assert scenario["regime_id"] == "R5"
    assert notes["semantic_role"] == "OVEREXTENDED_MOMENTUM"
    assert result.deployable is True
    assert 35 <= result.profile.base_allocation_pct <= 50
    assert params.buy_grid_count > 0
    assert params.sell_grid_count >= 4
    _assert_profit_loop_filled(result, params)
    assert "LOW_LIQUIDITY_RESTRICTED" not in set(notes["reason_codes"])
    blob = _display_blob(display, scenario, notes)
    assert "trend devamından pay" in blob


def test_v6_low_liq_restricted_does_not_claim_normal_active_grid():
    result, params, display, notes, scenario = _run(_cat_low_liq_r4_inp())
    _assert_global_invariants("low-liq display contract", result, params, display, notes)
    blob = _display_blob(display, scenario, notes)
    assert result.deployable is False
    assert result.deploy_block_reason == "restricted_by_liquidity"
    assert "restricted" in blob
    assert "normal aktif" not in blob
    assert "uygulanabilir savunmacı profil" not in blob


def test_v6_base_not_over_penalized_when_liquidity_is_good():
    for name, factory, minimum_base in (
        ("BNB", _bnb_r3_compression_inp, 35),
        ("ADA", _ada_post_breakout_cooldown_inp, 40),
        ("SKY", _sky_r5_overextended_inp, 35),
        ("BREAK", _clean_breakout_act_inp, 65),
    ):
        result, params, display, notes, scenario = _run(factory())
        _assert_global_invariants(name, result, params, display, notes)
        assert result.profile.base_allocation_pct >= minimum_base
        assert result.profile.base_allocation_pct > 15
        assert result.deploy_block_reason != "restricted_by_liquidity"
        assert "LOW_LIQUIDITY_RESTRICTED" not in set(notes["reason_codes"])
