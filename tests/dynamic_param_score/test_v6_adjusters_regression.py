"""V6 adjuster regression tests — BTC B3, F3, V5, L3, conflict."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.adjusters.pipeline import run_adjusters
from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile, V6InputContract
from app.services.dynamic_param_score.v6.v6_apply_delta import apply_delta
from app.services.dynamic_param_score.v6.v6_delta_limiter import cap_total_delta
from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile


def _base_input(**overrides) -> V6InputContract:
    base = dict(
        symbol="TESTUSDT",
        bot_budget_usdt=500.0,
        current_price=1.0,
        min_notional=10.0,
        tick_size=0.01,
        step_size=0.001,
        price_precision=2,
        quantity_precision=3,
        price_valid=True,
        candles_5m=500,
        candles_1h=200,
        range_stability=0.6,
        volatility_percentile=45.0,
        atr_1h_pct=1.0,
        volume_consistency=0.7,
        spread_pct=0.02,
    )
    base.update(overrides)
    return V6InputContract(**base)


def _std_profile(behavior: str = "PB01") -> V6CatalogProfile:
    from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile_by_regime_behavior

    p = get_profile_by_regime_behavior("R2", behavior, "STD")
    assert p is not None, f"missing catalog profile for {behavior}"
    return p


def test_btc_b3_synthetic_fixture_defensive_adjustments():
    """BTC B3 synthetic — staging may show B1; fixture guards B2/B3 adjuster behavior."""
    inp = _base_input(
        btc_ema200_below=True,
        btc_crash_velocity=-2.0,
        btc_return_4h_pct=-4.0,
        btc_return_24h_pct=-7.0,
    )
    delta, _ = run_adjusters(inp)
    assert delta.severity_override == "DEF"
    assert delta.base_delta_steps <= -1
    assert delta.normal_buy_override is True or delta.buy_grid_distance_delta >= 1
    assert delta.buyback_trigger_delta >= 0.5
    assert delta.profit_sell_trigger_delta >= 0.5
    assert delta.buy_trailing_delta_steps >= 1 or delta.sell_trailing_delta_steps >= 1


def test_f3_fragile_coin_adjustments():
    inp = _base_input(
        asset_fragility_class="F3",
        volume_consistency=0.2,
        volume_spike=2.5,
        volatility_percentile=92.0,
        fake_bounce_score=75.0,
    )
    delta, _ = run_adjusters(inp)
    assert delta.base_delta_steps <= -1
    assert delta.buy_grid_distance_delta >= 2
    assert delta.sell_grid_distance_delta >= 1
    assert delta.buyback_trigger_delta >= 0.5
    assert delta.buy_trailing_delta_steps >= 1 or delta.sell_trailing_delta_steps >= 1


def test_v5_extreme_volatility_adjustments():
    inp = _base_input(
        atr_1h_pct=6.0,
        volatility_percentile=95.0,
        bb_width=12.0,
    )
    delta, _ = run_adjusters(inp)
    assert delta.buy_grid_distance_delta >= 3
    assert delta.sell_grid_distance_delta >= 2
    assert delta.buyback_trigger_delta >= 1.0
    assert delta.buy_trailing_delta_steps >= 1
    assert delta.buy_grid_count_delta <= 0


def test_l3_liquidity_adjustments():
    inp = _base_input(
        spread_pct=0.35,
        volume_consistency=0.25,
        zero_volume_flag=0,
    )
    delta, _ = run_adjusters(inp)
    assert delta.buy_grid_count_delta <= 0 or delta.sell_grid_count_delta <= 0
    assert delta.profit_sell_trigger_delta >= 0.5 or delta.normal_buy_override is True


def test_conflict_b3_f3_v5_l3_capped_and_valid():
    inp = _base_input(
        btc_ema200_below=True,
        btc_crash_velocity=-2.5,
        btc_return_4h_pct=-5.0,
        btc_return_24h_pct=-8.0,
        asset_fragility_class="F3",
        volume_consistency=0.2,
        volume_spike=3.0,
        volatility_percentile=95.0,
        fake_bounce_score=80.0,
        atr_1h_pct=6.5,
        bb_width=14.0,
        spread_pct=0.4,
    )
    delta, _ = run_adjusters(inp)
    capped = cap_total_delta(delta, inp, btc_risk=75, volatility_score=85)
    assert capped.base_delta_steps >= -3
    assert capped.buy_trailing_delta_steps <= 3
    assert capped.sell_trailing_delta_steps <= 3
    assert capped.buyback_trigger_delta <= 3.0
    assert capped.profit_sell_trigger_delta <= 3.0

    base = _std_profile("PB01")
    base_before = base.base_allocation_pct
    adjusted = apply_delta(base, capped)
    assert adjusted.base_allocation_pct >= 5
    assert adjusted.base_allocation_pct <= base_before
    assert validate_profile(adjusted) == []
    if adjusted.buy_grids:
        assert abs(adjusted.buy_grids[0].distance_pct) <= 25


def test_major_symbol_fragility_guard_caps_btc_at_f1_unless_extreme():
    from app.services.dynamic_param_score.models import IndicatorSnapshot
    from app.services.dynamic_param_score.v6.v6_indicator_adapter import _fragility_class

    ind = IndicatorSnapshot(
        volume_consistency=0.45,
        orderbook_spread_pct=0.04,
        volatility_percentile=55,
        zero_volume_ratio=0,
    )
    cls = _fragility_class(ind, 0.04, 55, symbol="BTCUSDT")
    assert cls in ("F0", "F1"), f"BTC should not be F2 without extreme score, got {cls}"
    ind_extreme = IndicatorSnapshot(
        volume_consistency=0.2,
        orderbook_spread_pct=0.3,
        volatility_percentile=95,
        zero_volume_ratio=0.1,
    )
    cls_ext = _fragility_class(ind_extreme, 0.3, 95, symbol="BTCUSDT")
    assert cls_ext in ("F2", "F3")


def test_post_sell_buyback_profile_maps_to_bot_params():
    from app.services.dynamic_param_score.v6.v6_botparams_adapter import v6_profile_to_bot_params
    from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile_by_regime_behavior

    p = get_profile_by_regime_behavior("R8", "PB11", "STD")
    assert p is not None
    bp = v6_profile_to_bot_params(p)
    assert bp.buy_grid_count == 1
    assert bp.sell_grid_count >= 1
    assert bp.rebuy_enabled is True
    assert bp.rebuy_trigger_pct is not None
    assert bp.resell_enabled is True
    assert bp.pool_version == "v6"
