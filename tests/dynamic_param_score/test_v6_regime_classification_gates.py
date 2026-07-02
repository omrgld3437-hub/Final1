"""V6 regime classification + R4/R8 sub-profile regression tests."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.v6.constants import TRAILING_CODES
from app.services.dynamic_param_score.v6.engine import V6Engine
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
    assert params.resell_trigger_pct == pytest.approx(3.5)
    assert params.resell_trail_pct == pytest.approx(1.1)

    ui = pa_dm_adapter(decision)["ui_config"]
    assert ui["down"]["trail_pct"] == pytest.approx(1.1)
    assert ui["up"]["trail_pct"] == pytest.approx(1.1)


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
    assert profile.normal_buy_enabled is False
    assert profile.buy_grids == []
    assert [g.distance_pct for g in profile.sell_grids] == [5, 10, 18]
    assert [g.amount_pct for g in profile.sell_grids] == [45, 35, 20]
    assert profit_pct_from_code(profile.buyback_trigger_code) == pytest.approx(8.0)
    assert trailing_pct_from_code(profile.buyback_trailing_code) == pytest.approx(1.4)
    assert profit_pct_from_code(profile.profit_sell_trigger_code) == pytest.approx(5.0)
    assert trailing_pct_from_code(profile.profit_sell_trailing_code) == pytest.approx(1.4)
    assert notes.get("params_valid") is True
    assert "PARABOLIC_PUMP" in (notes.get("reason_codes") or [])
    assert notes.get("new_buys_status") == "paused"


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
    assert profile.normal_buy_enabled is False
    assert profile.buy_grids == []
    assert [g.distance_pct for g in profile.sell_grids] == [2, 5, 9]
    assert [g.amount_pct for g in profile.sell_grids] == [45, 35, 20]
    assert profit_pct_from_code(profile.buyback_trigger_code) == pytest.approx(6.0)
    assert trailing_pct_from_code(profile.buyback_trailing_code) == pytest.approx(1.4)
    assert profit_pct_from_code(profile.profit_sell_trigger_code) == pytest.approx(2.5)
    assert trailing_pct_from_code(profile.profit_sell_trailing_code) == pytest.approx(0.5)
    assert notes.get("params_valid") is True
    assert notes.get("new_buys_status") == "paused"


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
    assert "alış kapalı" in op.lower() or "satış" in op.lower()


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
