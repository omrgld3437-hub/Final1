"""V6 regime classification + R4/R8 sub-profile regression tests."""

from __future__ import annotations

import pytest

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.v6.constants import TRAILING_CODES
from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
from app.services.dynamic_param_score.v6.engine import V6Engine, _apply_v4_host_base_cap, _low_liq_reason_codes
from app.services.dynamic_param_score.v6.v6_quantizer import profit_pct_from_code, trailing_pct_from_code
from app.services.dynamic_param_score.v6.v6_regime_behavior_spec import (
    apply_regime_behavior_spec,
    resolve_regime_template,
)
from app.services.dynamic_param_score.v6.v6_scenario_classifier import classify_scenario
from tests.dynamic_param_score.test_v6_opportunity_oriented_logic import (
    _base_inp,
    _decision_from_inp,
    pa_dm_adapter,
)


def _eth_like_inp() -> object:
    return _base_inp(
        symbol="ETHUSDT",
        adx_1h=32.3,
        rsi_5m=80.1,
        rsi_1h=78.0,
        ema20_slope=0.81,
        ema50_slope=0.56,
        price_vs_ema200_pct=6.15,
        roc_5m=2.66,
        return_24h_pct=6.75,
        return_4h_pct=3.5,
        return_1h_pct=1.2,
        higher_highs=True,
        lower_lows=False,
        volatility_percentile=72.0,
        atr_1h_pct=2.8,
        bb_position=0.82,
        z_score=1.5,
        range_stability=0.38,
        bb_width=4.5,
        volume_consistency=0.88,
        spread_pct=0.02,
        volume_24h=500_000_000.0,
        asset_fragility_class="F1",
    )


def _profile_for_host_cap(regime: str, behavior: str, severity: str, base: int) -> V6CatalogProfile:
    return V6CatalogProfile(
        profile_id=f"{regime}_{behavior}_{severity}",
        scenario=ScenarioIdentity(regime, "01", "001", behavior, severity),
        base_allocation_pct=base,
        quote_allocation_pct=100 - base,
        normal_buy_enabled=True,
        buy_grids=[GridLevel(-10, 100)],
        sell_grids=[GridLevel(6, 100)],
    )


def _arpa_like_inp() -> object:
    return _base_inp(
        symbol="ARPAUSDT",
        volatility_percentile=68.0,
        atr_1h_pct=2.5,
        range_stability=0.06,
        bb_width=5.0,
        spread_pct=0.25,
        volume_consistency=0.28,
        volume_24h=137_900.0,
        zero_volume_flag=1,
        adx_1h=22.0,
        rsi_1h=52.0,
        asset_fragility_class="F3",
    )


def _doge_like_inp() -> object:
    return _base_inp(
        symbol="DOGEUSDT",
        adx_1h=21.3,
        rsi_5m=58.0,
        rsi_1h=68.3,
        price_vs_ema200_pct=0.48,
        volatility_percentile=65.0,
        atr_1h_pct=2.2,
        range_stability=0.42,
        bb_width=3.8,
        spread_pct=0.01,
        volume_consistency=0.85,
        volume_24h=46_600_000.0,
        zero_volume_flag=0,
        asset_fragility_class="F2",
    )


def _btc_high_momentum_inp() -> object:
    return _base_inp(
        symbol="BTCUSDT",
        adx_1h=32.4,
        rsi_1h=70.1,
        ema20_slope=0.5,
        ema50_slope=0.4,
        price_vs_ema200_pct=2.47,
        return_24h_pct=4.08,
        return_4h_pct=2.0,
        higher_highs=True,
        lower_lows=False,
        volatility_percentile=68.0,
        atr_1h_pct=1.8,
        range_stability=0.48,
        bb_width=3.5,
        spread_pct=0.01,
        volume_consistency=0.95,
        volume_24h=2_000_000_000.0,
        asset_fragility_class="F0",
    )


def _sol_pullback_inp() -> object:
    return _base_inp(
        symbol="SOLUSDT",
        bot_budget_usdt=500.0,
        current_price=81.0,
        adx_1h=36.7,
        rsi_5m=37.8,
        rsi_1h=63.3,
        ema20_slope=-0.38,
        ema50_slope=-0.10,
        ema20_5m=81.16,
        ema50_5m=81.07,
        ema200_1h=73.04,
        price_vs_ema200_pct=10.38,
        roc_5m=-1.2,
        higher_highs=False,
        lower_lows=True,
        atr_5m_pct=0.46,
        atr_1h_pct=1.37,
        vol_24h=0.23,
        vol_7d=0.81,
        volatility_percentile=81.46,
        bb_width=1.95,
        bb_position=0.12,
        z_score=-1.57,
        mean_reversion_score=0.3,
        range_stability=0.5,
        hl_range_pct=0.3,
        return_1h_pct=-1.2,
        return_4h_pct=-0.49,
        return_24h_pct=4.78,
        drawdown_7d_pct=2.1,
        drawdown_30d_pct=2.1,
        crash_velocity=-0.54,
        red_pressure=0,
        spread_pct=0.01,
        volume_24h=334_100_000.0,
        volume_consistency=0.65,
        volume_spike=3.2,
        zero_volume_flag=0,
        btc_return_1h_pct=-0.26,
        btc_return_4h_pct=0.69,
        btc_return_24h_pct=3.76,
        btc_crash_velocity=-0.26,
        btc_ema200_below=False,
        data_freshness_sec=102,
        data_gap_sec=0,
        candles_5m=2016,
        candles_15m=672,
        candles_1h=240,
        price_valid=True,
        asset_fragility_class="F1",
    )


def _bnb_overheat_cooldown_inp() -> object:
    return _base_inp(
        symbol="BNBUSDT",
        bot_budget_usdt=500.0,
        current_price=573.0,
        adx_1h=44.2,
        rsi_5m=59.1,
        rsi_1h=73.7,
        ema20_slope=0.08,
        ema50_slope=0.09,
        ema20_5m=572.77,
        ema50_5m=571.12,
        ema200_1h=559.88,
        price_vs_ema200_pct=2.42,
        roc_5m=-0.11,
        higher_highs=False,
        lower_lows=False,
        atr_5m_pct=0.16,
        atr_1h_pct=0.52,
        vol_24h=0.10,
        vol_7d=0.36,
        volatility_percentile=61.62,
        bb_width=0.45,
        bb_position=0.61,
        z_score=0.44,
        mean_reversion_score=0.1,
        range_stability=0.53,
        hl_range_pct=0.19,
        return_1h_pct=-0.11,
        return_4h_pct=0.92,
        return_24h_pct=2.88,
        drawdown_7d_pct=0.09,
        drawdown_30d_pct=0.09,
        crash_velocity=-0.09,
        red_pressure=0.2,
        spread_pct=0.0,
        volume_24h=59_700_000.0,
        volume_consistency=0.66,
        volume_spike=3.81,
        zero_volume_flag=0,
        btc_return_1h_pct=-0.03,
        btc_return_4h_pct=0.81,
        btc_return_24h_pct=2.03,
        btc_crash_velocity=-0.07,
        btc_ema200_below=False,
        data_freshness_sec=212,
        data_gap_sec=0,
        candles_5m=2016,
        candles_15m=672,
        candles_1h=240,
        price_valid=True,
        asset_fragility_class="F0",
    )


def _tlm_parabolic_pump_inp() -> object:
    return _base_inp(
        symbol="TLMUSDT",
        return_1h_pct=14.95,
        return_4h_pct=44.4,
        return_24h_pct=119.96,
        adx_1h=59.0,
        rsi_1h=72.5,
        ema20_slope=5.9,
        ema50_slope=4.28,
        price_vs_ema200_pct=97.89,
        higher_highs=True,
        lower_lows=False,
        atr_5m_pct=5.94,
        atr_1h_pct=11.26,
        volatility_percentile=95.0,
        bb_position=0.87,
        z_score=1.52,
        spread_pct=0.15,
        volume_24h=46_500_000.0,
        volume_consistency=0.8,
        crash_velocity=-2.0,
        asset_fragility_class="F1",
    )


def _dydx_deep_drawdown_inp() -> object:
    return _base_inp(
        symbol="DYDXUSDT",
        return_1h_pct=-0.09,
        return_4h_pct=-3.88,
        return_24h_pct=-27.26,
        price_vs_ema200_pct=-11.62,
        ema20_slope=-0.63,
        ema50_slope=-0.46,
        rsi_5m=39.7,
        rsi_1h=37.4,
        higher_highs=False,
        lower_lows=True,
        drawdown_7d_pct=43.27,
        drawdown_30d_pct=43.27,
        adx_1h=32.5,
        spread_pct=0.04,
        volume_24h=14_300_000.0,
        volume_consistency=0.7,
        zero_volume_flag=0,
        crash_velocity=-2.0,
        asset_fragility_class="F1",
    )


def _avax_upper_band_spike_inp() -> object:
    return _base_inp(
        symbol="AVAXUSDT",
        adx_1h=20.2,
        rsi_5m=64.2,
        rsi_1h=49.4,
        price_vs_ema200_pct=3.8,
        bb_position=0.83,
        z_score=1.37,
        volume_spike=7.37,
        range_stability=0.58,
        volatility_percentile=38.0,
        atr_1h_pct=0.68,
        spread_pct=0.01,
        volume_24h=70_000_000.0,
        volume_consistency=0.39,
        asset_fragility_class="F1",
    )


def _doge_live_cooldown_inp() -> object:
    return _base_inp(
        symbol="DOGEUSDT",
        adx_1h=43.0,
        rsi_5m=47.6,
        rsi_1h=53.3,
        ema20_slope=-0.03,
        ema50_slope=-0.02,
        price_vs_ema200_pct=3.02,
        bb_position=0.31,
        z_score=-0.8,
        return_24h_pct=1.2,
        return_4h_pct=-0.2,
        roc_5m=-0.15,
        higher_highs=False,
        lower_lows=False,
        volume_spike=7.25,
        spread_pct=0.01,
        volume_24h=41_300_000.0,
        volume_consistency=0.25,
        zero_volume_flag=0,
        asset_fragility_class="F1",
    )


def _alcx_hard_block_inp() -> object:
    return _base_inp(
        symbol="ALCXUSDT",
        rsi_5m=35.1,
        rsi_1h=32.0,
        ema20_slope=-0.54,
        ema50_slope=-0.30,
        price_vs_ema200_pct=-12.0,
        roc_5m=-2.6,
        lower_lows=True,
        higher_highs=False,
        atr_1h_pct=3.32,
        bb_position=0.03,
        z_score=-1.93,
        return_24h_pct=-6.25,
        drawdown_7d_pct=31.4,
        drawdown_30d_pct=31.4,
        spread_pct=0.44,
        zero_volume_flag=1,
        volume_24h=500_000.0,
        volume_consistency=0.2,
        crash_velocity=-1.2,
        asset_fragility_class="F3",
    )


def _nfp_crash_block_inp() -> object:
    return _base_inp(
        symbol="NFPUSDT",
        rsi_5m=30.0,
        rsi_1h=31.3,
        ema20_slope=-1.26,
        ema50_slope=-0.71,
        price_vs_ema200_pct=-20.02,
        roc_5m=-4.58,
        return_4h_pct=-6.64,
        return_24h_pct=-22.16,
        drawdown_7d_pct=85.89,
        drawdown_30d_pct=85.89,
        crash_velocity=-3.64,
        atr_1h_pct=8.42,
        spread_pct=0.54,
        lower_lows=True,
        higher_highs=False,
        volume_24h=800_000.0,
        volume_consistency=0.2,
        zero_volume_flag=1,
        asset_fragility_class="F3",
    )


def test_eth_like_not_r4_std():
    classified = classify_scenario(_eth_like_inp())
    assert classified.regime_id in ("R1", "R5"), f"ETH-like should be R1/R5, got {classified.regime_id}"


def test_eth_like_base_not_ultra_defensive():
    decision = _decision_from_inp(_eth_like_inp())
    assert decision.params is not None
    assert decision.params.base_alloc_frac >= 0.40, "ETH momentum base should not be ultra-defensive"


def test_arpa_like_restricted_not_normal_r4():
    classified = classify_scenario(_arpa_like_inp())
    assert classified.regime_id != "R4" or classified.sub_profile_hint in (
        "R4_RESTRICTED_UNSTABLE",
        "R4_DEF_LOW_LIQUIDITY",
    )
    trace = [{"name": "asset_fragility", "class": "F3"}, {"name": "volatility", "class": "V4"}]
    tpl, reasons, deployable = resolve_regime_template(
        "R4", "STD", _arpa_like_inp(), trace, sub_profile_hint=classified.sub_profile_hint
    )
    assert "R4_RESTRICTED_UNSTABLE" in reasons or "R4_DEF_LOW_LIQUIDITY" in reasons
    assert deployable is False


def test_doge_like_first_buy_not_too_far():
    decision = _decision_from_inp(_doge_like_inp())
    params = decision.params
    assert params is not None
    buy_dist = (params.buy_grid_ladder_pcts or [params.buy_grid_spacing_pct])[0]
    assert abs(buy_dist) <= 4, f"DOGE first buy {buy_dist}% too far"
    assert params.base_alloc_frac >= 0.28


def test_btc_high_momentum_runs_trend_gate_before_r4():
    classified = classify_scenario(_btc_high_momentum_inp())
    assert classified.regime_id in ("R1", "R5", "R4"), classified.regime_id
    if classified.regime_id == "R4":
        assert classified.sub_profile_hint in ("R4_DEF_OVERHEATED", "R4_STD_LIQUID")


def test_sol_strong_uptrend_pullback_uses_r1_std_pullback():
    inp = _sol_pullback_inp()
    classified = classify_scenario(inp)
    assert classified.regime_id == "R1"
    assert classified.sub_profile_hint == "R1_STD_PULLBACK"

    decision = _decision_from_inp(inp)
    params = decision.params
    assert params is not None
    assert decision.selected_profile_name.endswith("_STD")
    assert params.base_alloc_frac == pytest.approx(0.60)
    assert params.quote_alloc_frac == pytest.approx(0.40)
    assert params.max_base_exposure_frac == pytest.approx(0.80)
    assert params.buy_grid_ladder_pcts == [2, 5, 9]
    assert params.buy_qty_distribution == [0.15, 0.30, 0.55]
    assert params.sell_grid_ladder_pcts == [3, 6, 10, 15, 21]
    assert params.sell_qty_distribution == [0.10, 0.15, 0.20, 0.25, 0.30]
    assert params.rebuy_trigger_pct == pytest.approx(3.5)
    assert params.rebuy_trail_pct == pytest.approx(1.1)
    assert params.resell_trigger_pct == pytest.approx(3.0)


def test_sol_r1_act_blocked_when_short_term_structure_is_pullback():
    inp = _base_inp(
        symbol="SOLUSDT",
        adx_1h=41.9,
        rsi_5m=51.1,
        rsi_1h=66.1,
        ema20_slope=0.04,
        ema50_slope=0.07,
        price_vs_ema200_pct=10.25,
        roc_5m=-0.3,
        higher_highs=False,
        lower_lows=True,
        atr_5m_pct=0.28,
        atr_1h_pct=0.87,
        volatility_percentile=51.1,
        bb_width=0.78,
        bb_position=0.41,
        z_score=-0.38,
        mean_reversion_score=0.2,
        range_stability=0.59,
        return_1h_pct=-0.3,
        return_4h_pct=1.03,
        return_24h_pct=2.33,
        drawdown_7d_pct=0.22,
        drawdown_30d_pct=0.22,
        crash_velocity=-0.15,
        red_pressure=0.2,
        spread_pct=0.01,
        volume_24h=149_900_000,
        volume_consistency=0.4,
        volume_spike=7.34,
        zero_volume_flag=0,
        asset_fragility_class="F1",
    )
    classified = classify_scenario(inp)
    assert classified.regime_id == "R1"
    assert classified.sub_profile_hint == "R1_STD_PULLBACK"

    decision = _decision_from_inp(inp)
    params = decision.params
    assert params is not None
    scenario = (decision.telemetry.get("v6_display") or {}).get("scenario_identity") or {}
    notes = ((decision.telemetry.get("v6_final") or {}).get("opportunity_notes") or {})
    assert scenario["regime_id"] == "R1"
    assert scenario["severity"] == "STD"
    assert notes["sub_profile_hint"] == "R1_STD_PULLBACK"
    assert decision.selected_profile_name.endswith("_STD")
    assert params.base_alloc_frac == pytest.approx(0.60)
    assert params.quote_alloc_frac == pytest.approx(0.40)
    assert params.buy_grid_ladder_pcts == [2, 5, 9]
    assert params.sell_grid_ladder_pcts == [3, 6, 10, 15, 21]
    assert params.resell_trail_pct == pytest.approx(1.1)
    v6d = decision.telemetry.get("v6_display") or {}
    display_blob = " ".join(
        str(v6d.get(key) or "").lower()
        for key in ("market_status_plain", "regime_strategy_why", "grid_plan_plain")
    )
    assert "pullback" in display_blob or "geri çekilme" in display_blob
    assert "aktif fırsat" not in display_blob
    assert "coin tarafı orta-yüksek" in display_blob

    ui = pa_dm_adapter(decision)["ui_config"]
    assert ui["down"]["trail_pct"] == pytest.approx(1.1)
    assert ui["up"]["trail_pct"] == pytest.approx(1.1)


def test_min_notional_default_is_not_changed_by_v6_profile_rules():
    assert DEFAULT_MIN_NOTIONAL_USDT == pytest.approx(10.0)


def test_avax_upper_band_volume_spike_rejects_easy_r2_and_locks_profit_profile():
    inp = _avax_upper_band_spike_inp()
    classified = classify_scenario(inp)
    assert classified.regime_id == "R3"
    assert classified.sub_profile_hint == "R3_STD_UPPER_BAND_PROFIT_LOCK"

    decision = _decision_from_inp(inp)
    params = decision.params
    assert params is not None
    assert params.base_alloc_frac == pytest.approx(0.50)
    assert params.quote_alloc_frac == pytest.approx(0.50)
    assert params.buy_grid_ladder_pcts == [2, 4, 7, 11]
    assert params.buy_qty_distribution == [0.15, 0.25, 0.30, 0.30]
    assert params.sell_grid_ladder_pcts == [2, 4, 7, 10, 14]
    assert params.sell_qty_distribution == [0.25, 0.25, 0.20, 0.15, 0.15]
    notes = ((decision.telemetry.get("v6_final") or {}).get("opportunity_notes") or {})
    assert "UPPER_BAND_PROFIT_LOCK" in notes.get("reason_codes", [])


def test_doge_high_volume_low_spread_is_not_low_liq_restricted():
    decision = _decision_from_inp(_doge_live_cooldown_inp())
    params = decision.params
    assert params is not None
    notes = ((decision.telemetry.get("v6_final") or {}).get("opportunity_notes") or {})
    assert "LOW_LIQUIDITY_RESTRICTED" not in set(notes.get("reason_codes") or [])
    assert decision.deployable is True
    assert params.base_alloc_frac >= 0.30
    assert params.buy_grid_count > 0


def test_bnb_low_realized_vol_overheat_cooldown_avoids_dead_r4_grid():
    inp = _bnb_overheat_cooldown_inp()
    classified = classify_scenario(inp)
    assert classified.regime_id == "R3"
    assert classified.sub_profile_hint == "R3_STD_UPTREND_OVERHEAT_COOLDOWN"

    decision = _decision_from_inp(inp)
    params = decision.params
    assert params is not None
    scenario = (decision.telemetry.get("v6_display") or {}).get("scenario_identity") or {}
    notes = ((decision.telemetry.get("v6_final") or {}).get("opportunity_notes") or {})
    assert scenario["regime_id"] == "R3"
    assert scenario["severity"] == "STD"
    assert notes["sub_profile_hint"] == "R3_STD_UPTREND_OVERHEAT_COOLDOWN"
    assert decision.selected_profile_name.endswith("_STD")
    assert params.base_alloc_frac == pytest.approx(0.50)
    assert params.quote_alloc_frac == pytest.approx(0.50)
    assert params.buy_grid_ladder_pcts == [2, 4, 7, 11]
    assert params.buy_qty_distribution == [0.10, 0.20, 0.30, 0.40]
    assert params.sell_grid_ladder_pcts == [2, 4, 7, 11, 16]
    assert params.sell_qty_distribution == [0.10, 0.15, 0.20, 0.25, 0.30]
    assert params.rebuy_trigger_pct == pytest.approx(3.0)
    assert params.rebuy_trail_pct == pytest.approx(1.1)
    assert params.resell_trigger_pct == pytest.approx(2.5)
    assert params.resell_trail_pct == pytest.approx(0.8)

    v6d = decision.telemetry.get("v6_display") or {}
    display_blob = " ".join(
        str(v6d.get(key) or "").lower()
        for key in ("market_status_plain", "regime_strategy_why", "grid_plan_plain")
    )
    assert "rsi yüksek" in display_blob
    assert "momentum soğuyor" in display_blob
    assert "sert yukarı-aşağı" not in display_blob
    assert "+21%" not in display_blob
    assert "-20%" not in display_blob


def test_tlm_parabolic_pump_vetoes_r8_and_uses_micro_profile():
    inp = _tlm_parabolic_pump_inp()
    classified = classify_scenario(inp)
    assert classified.regime_id != "R8"
    assert classified.regime_id in ("R5", "R1", "R4")
    assert classified.sub_profile_hint == "R5_DEF_PARABOLIC_OVEREXTENDED"

    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    profile = result.profile
    notes = result.telemetry.get("opportunity_notes") or {}
    assert scenario.get("regime_id") == "R5"
    assert profile.base_allocation_pct == 5
    assert profile.quote_allocation_pct == 95
    assert profile.normal_buy_enabled is True
    assert [(g.distance_pct, g.amount_pct) for g in profile.buy_grids] == [(-35, 100)]
    assert [g.distance_pct for g in profile.sell_grids] == [6, 14]
    assert [g.amount_pct for g in profile.sell_grids] == [60, 40]
    assert profit_pct_from_code(profile.buyback_trigger_code) == pytest.approx(8.0)
    assert trailing_pct_from_code(profile.buyback_trailing_code) == pytest.approx(1.4)
    assert profit_pct_from_code(profile.profit_sell_trigger_code) == pytest.approx(5.0)
    assert trailing_pct_from_code(profile.profit_sell_trailing_code) == pytest.approx(1.4)
    assert notes.get("params_valid") is True
    assert "PARABOLIC_PUMP" in (notes.get("reason_codes") or [])
    assert notes.get("new_buys_status") == "deep_probe"
    assert notes.get("mandatory_deep_buy_applied") is True
    assert notes.get("micro_base_sell_grid_compacted") is True


def test_r8_hard_block_disables_buys_profit_loop_and_deploy():
    from app.services.dynamic_param_score.v6.v6_botparams_adapter import v6_final_to_bot_params

    for inp in (_alcx_hard_block_inp(), _nfp_crash_block_inp()):
        classified = classify_scenario(inp)
        assert classified.regime_id == "R8"
        assert classified.sub_profile_hint == "R8_HARD_BLOCK"

        result = V6Engine().run(inp)
        params = v6_final_to_bot_params(result, bot_budget_usdt=float(inp.bot_budget_usdt or 0))
        notes = result.telemetry.get("opportunity_notes") or {}
        assert result.deployable is False
        assert result.deploy_block_reason == "technical_block"
        assert result.profile.base_allocation_pct == 0
        assert result.profile.quote_allocation_pct == 100
        assert result.profile.normal_buy_enabled is False
        assert result.profile.buy_grids == []
        assert result.profile.sell_grids == []
        assert result.profile.buyback_after_sell_enabled is False
        assert result.profile.profit_sell_after_buyback_enabled is False
        assert params.buy_grid_count == 0
        assert params.sell_grid_count == 0
        assert params.rebuy_enabled is False
        assert params.resell_enabled is False
        assert notes.get("semantic_role") == "R8_HARD_BLOCK"


def test_dydx_deep_drawdown_uses_r8_def_standard_grid():
    inp = _dydx_deep_drawdown_inp()
    classified = classify_scenario(inp)
    assert classified.regime_id == "R8"

    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    profile = result.profile
    notes = result.telemetry.get("opportunity_notes") or {}
    assert scenario.get("regime_id") == "R8"
    assert profile.base_allocation_pct == 5
    assert profile.quote_allocation_pct == 95
    assert profile.normal_buy_enabled is True
    assert [(g.distance_pct, g.amount_pct) for g in profile.buy_grids] == [(-28, 100)]
    assert [g.distance_pct for g in profile.sell_grids] == [2, 5, 9]
    assert [g.amount_pct for g in profile.sell_grids] == [45, 35, 20]
    assert profit_pct_from_code(profile.buyback_trigger_code) == pytest.approx(6.0)
    assert trailing_pct_from_code(profile.buyback_trailing_code) == pytest.approx(1.4)
    assert profit_pct_from_code(profile.profit_sell_trigger_code) == pytest.approx(2.5)
    assert trailing_pct_from_code(profile.profit_sell_trailing_code) == pytest.approx(0.5)
    assert notes.get("params_valid") is True
    assert notes.get("new_buys_status") == "deep_probe"
    assert notes.get("mandatory_deep_buy_applied") is True


def test_trailing_values_always_on_lattice():
    valid = set(TRAILING_CODES.values())
    fixtures = [_eth_like_inp(), _arpa_like_inp(), _doge_like_inp(), _btc_high_momentum_inp(), _sol_pullback_inp()]
    for inp in fixtures:
        decision = _decision_from_inp(inp)
        v6d = (decision.telemetry.get("v6_display") or {})
        for key in (
            "sell_trailing_pct",
            "buy_trailing_pct",
            "rebuy_trailing_pct",
            "profit_sell_trailing_pct",
            "post_sell_buyback_trailing_pct",
            "post_buyback_profit_sell_trailing_pct",
        ):
            val = v6d.get(key)
            if val is not None:
                assert float(val) in valid, f"{key}={val} not on lattice for {inp.symbol}"
        params = decision.params
        if params and params.rebuy_trail_pct is not None:
            assert float(params.rebuy_trail_pct) in valid
        if params and params.resell_trail_pct is not None:
            assert float(params.resell_trail_pct) in valid
        ui = pa_dm_adapter(decision).get("ui_config") or {}
        for side in ("up", "down"):
            val = (ui.get(side) or {}).get("trail_pct")
            if val:
                assert float(val) in valid


def test_v4_trailing_tier_map_is_fixed():
    assert TRAILING_CODES["T1"] == pytest.approx(0.5)
    assert TRAILING_CODES["T2"] == pytest.approx(0.8)
    assert TRAILING_CODES["T3"] == pytest.approx(1.1)
    assert TRAILING_CODES["T4"] == pytest.approx(1.4)
    assert max(TRAILING_CODES.values()) <= 2.5


def test_v4_host_base_cap_for_r7_and_r8_profiles():
    inp = _base_inp(
        symbol="CAPUSDT",
        price_valid=True,
        data_gap_sec=0,
        data_freshness_sec=120,
        candles_5m=288,
        spread_pct=0.2,
        crash_velocity=-0.9,
        return_4h_pct=-3.0,
    )

    r7, r7_notes = _apply_v4_host_base_cap(_profile_for_host_cap("R7", "PB08", "ACT", 30), inp, {})
    assert r7.base_allocation_pct == 25
    assert r7.quote_allocation_pct == 75
    assert r7_notes["v4_host_base_cap"]["reason"] == "V4_HOST_R7_BASE_CAP"

    r8_pb13, r8_notes = _apply_v4_host_base_cap(_profile_for_host_cap("R8", "PB13", "ACT", 20), inp, {})
    assert r8_pb13.base_allocation_pct == 15
    assert r8_pb13.quote_allocation_pct == 85
    assert r8_notes["v4_host_base_cap"]["reason"] == "V4_HOST_R8_PB13_BASE_CAP"

    r8_pb12, pb12_notes = _apply_v4_host_base_cap(_profile_for_host_cap("R8", "PB12", "ACT", 20), inp, {})
    assert r8_pb12.base_allocation_pct == 15
    assert r8_pb12.quote_allocation_pct == 85
    assert pb12_notes["v4_host_base_cap"]["reason"] == "V4_HOST_R8_PB12_ACT_CONDITIONAL_BASE_CAP"

    allowed_inp = _base_inp(
        symbol="CAPUSDT",
        price_valid=True,
        data_gap_sec=0,
        data_freshness_sec=120,
        candles_5m=288,
        spread_pct=0.1,
        crash_velocity=-0.3,
        return_1h_pct=0.4,
        return_4h_pct=-1.2,
        fake_bounce_score=70,
    )
    allowed, allowed_notes = _apply_v4_host_base_cap(_profile_for_host_cap("R8", "PB12", "ACT", 20), allowed_inp, {})
    assert allowed.base_allocation_pct == 20
    assert "v4_host_base_cap" not in allowed_notes


def test_f3_low_volume_consistency_is_restricted_even_with_mid_volume():
    inp = _base_inp(
        symbol="FRAGUSDT",
        asset_fragility_class="F3",
        volume_24h=5_500_000,
        volume_consistency=0.14,
        spread_pct=0.03,
        zero_volume_flag=0,
    )
    reasons = _low_liq_reason_codes(inp)
    assert "F3_FRAGILITY" in reasons
    assert "LOW_VOLUME_CONSISTENCY" in reasons
    assert "LOW_LIQUIDITY_RESTRICTED" in reasons


def test_f2_zero_volume_consistency_is_restricted_with_low_mid_volume():
    inp = _base_inp(
        symbol="FRAG2USDT",
        asset_fragility_class="F2",
        volume_24h=3_300_000,
        volume_consistency=0.0,
        spread_pct=0.02,
        zero_volume_flag=0,
    )
    reasons = _low_liq_reason_codes(inp)
    assert "F2_FRAGILITY" in reasons
    assert "LOW_VOLUME_CONSISTENCY" in reasons
    assert "LOW_LIQUIDITY_RESTRICTED" in reasons


def test_output_allocation_summary_matches_detail():
    decision = _decision_from_inp(_eth_like_inp())
    v6d = decision.telemetry.get("v6_display") or {}
    response = pa_dm_adapter(decision)
    ui = response.get("ui_config") or {}
    strat = (ui.get("allocation_display") or {}).get("strategic_target") or {}
    assert int(v6d.get("base_allocation_pct") or 0) == int(strat.get("base_pct") or -1)
    assert int(v6d.get("quote_allocation_pct") or 0) == int(strat.get("quote_pct") or -1)


def test_r8_buy_disabled_text_not_bilateral():
    inp = _base_inp(
        symbol="CRASHUSDT",
        return_24h_pct=-14.0,
        drawdown_7d_pct=22.0,
        crash_velocity=-2.8,
        asset_fragility_class="F2",
        atr_1h_pct=6.0,
        volatility_percentile=90.0,
    )
    decision = _decision_from_inp(inp)
    v6d = decision.telemetry.get("v6_display") or {}
    op = str(v6d.get("operational_mode_plain") or "")
    assert "iki yönlü" not in op.lower()
    assert "alış kapalı" in op.lower() or "satış" in op.lower() or "izleme" in op.lower()


def test_r8_trailing_sell_at_least_half_pct():
    inp = _base_inp(
        symbol="CRASHUSDT",
        return_24h_pct=-14.0,
        drawdown_7d_pct=22.0,
        crash_velocity=-2.8,
    )
    result = V6Engine().run(inp)
    trail = trailing_pct_from_code(result.profile.sell_trailing_code)
    assert trail >= 0.5
    first_sell = result.profile.sell_grids[0].distance_pct if result.profile.sell_grids else 0
    assert first_sell >= 2


def test_params_valid_always_true_after_spec():
    from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile

    prof = V6CatalogProfile(
        profile_id="gate_test",
        scenario=ScenarioIdentity("R4", "01", "001", "PB02", "STD"),
        base_allocation_pct=30,
        quote_allocation_pct=70,
        normal_buy_enabled=True,
        buy_grids=[GridLevel(-5, 50), GridLevel(-8, 50)],
        sell_grids=[GridLevel(5, 50), GridLevel(8, 50)],
        buyback_after_sell_enabled=True,
        profit_sell_after_buyback_enabled=True,
    )
    trace = [{"name": "asset_fragility", "class": "F1"}, {"name": "volatility", "class": "V3"}]
    _, notes = apply_regime_behavior_spec(
        prof, _doge_like_inp(), trace, regime_id="R4", severity="STD", sub_profile_hint="R4_FRAGILE_BUT_LIQUID"
    )
    assert notes.get("params_valid") is True


def _btc_r3_uptrend_compression_inp() -> object:
    """Live BTCUSDT low-vol squeeze above EMA200 — R3 uptrend compression, not R1 cooldown."""
    return _base_inp(
        symbol="BTCUSDT",
        adx_1h=36.0,
        rsi_5m=54.8,
        rsi_1h=66.4,
        ema20_slope=0.06,
        ema50_slope=0.05,
        price_vs_ema200_pct=2.14,
        roc_5m=0.16,
        higher_highs=False,
        lower_lows=False,
        atr_5m_pct=0.17,
        atr_1h_pct=0.79,
        volatility_percentile=51.6,
        bb_width=0.41,
        bb_position=0.63,
        z_score=0.54,
        range_stability=0.56,
        return_1h_pct=0.16,
        return_4h_pct=0.63,
        return_24h_pct=2.73,
        drawdown_7d_pct=0.21,
        spread_pct=0.0,
        volume_24h=1_500_000_000.0,
        volume_consistency=0.55,
        asset_fragility_class="F0",
    )


def test_btc_r3_uptrend_compression_label_not_directionless():
    classified = classify_scenario(_btc_r3_uptrend_compression_inp())
    assert classified.regime_id == "R3"
    assert classified.sub_profile_hint == "R3_STD_UPTREND_COMPRESSION"
    assert classified.label == "Yukarı eğilimli sıkışma / kontrollü soğuma"
    assert "Yönsüz" not in classified.label


def test_btc_r3_uptrend_compression_display_copy():
    from app.services.dynamic_param_score.v6.v6_pa_display import contextual_market_status_plain

    trace = [{"name": "volatility", "class": "V1"}]
    status = contextual_market_status_plain(
        "R3",
        trace,
        sub_profile_hint="R3_STD_UPTREND_COMPRESSION",
        scenario_name="Yukarı eğilimli sıkışma / kontrollü soğuma",
    )
    assert "Yukarı eğilimli sıkışma" in status
    assert "derin alış açık" not in status.lower()
    assert "Yakın alış gridleri açık" in status
    assert "son kademe daha derin destek" in status
