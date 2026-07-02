"""Live V4 route classification — RE/USDT-like downtrend scenarios."""

from __future__ import annotations

import random

import pytest

from app.services.dynamic_param_score.models import RegimeTag
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import clean_fallback_keys
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    cap_trailing_pct,
    normalize_side_distribution,
    trailing_too_large,
)
from app.services.dynamic_param_score.param_generator.live_route_classifier_v4 import (
    classify_regime_code_v4,
    classify_vol_code_v4,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    market_signature_v4_from_live,
)
from app.services.dynamic_param_score.param_generator.v4_resolvers import apply_live_route_constraints
from app.services.dynamic_param_score.regime import classify_regime
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    SubScores,
)


def _re_usdt_indicators() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        price_valid=True,
        return_24h_pct=-9.66,
        drawdown_7d_pct=45.13,
        drawdown_30d_pct=45.13,
        atr14_pct_1h=3.82,
        atr14_pct_5m=2.5,
        lower_lows=True,
        higher_highs=False,
        z_score_5m=-2.06,
        price_in_bb=0.05,
        adx_1h=27.5,
        btc_crash_velocity=-0.6,
        crash_velocity=-0.6,
        volatility_percentile=85,
    )


def test_re_usdt_live_signature_not_balanced_r2_v2():
    sig = market_signature_v4_from_live(
        symbol="REUSDT",
        budget=500,
        regime=RegimeTag.BALANCED_RANGE.value,
        risk_level="DEFENSIVE",
        volatility_percentile=85,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=3.82,
        return_24h_pct=-9.66,
        drawdown_7d_pct=45.13,
        drawdown_30d_pct=45.13,
        z_score_5m=-2.06,
        price_in_bb=0.05,
        volatility_score=85,
        btc_crash_velocity=-0.6,
        crash_velocity=-0.6,
    )
    assert sig["regime_code"] in ("R7", "R12", "R6")
    assert sig["regime_code"] != "R2"
    assert sig["vol_code"] in ("V4", "V5")
    assert sig["vol_code"] != "V2"
    assert "DEFENSIVE" in sig["route_key"]


def test_classify_regime_strong_downtrend():
    cls = classify_regime_code_v4(
        regime_tag=RegimeTag.BALANCED_RANGE.value,
        lower_lows=True,
        higher_highs=False,
        return_24h_pct=-9.66,
        drawdown_7d_pct=45.13,
        atr_1h_pct=3.82,
        risk_level="DEFENSIVE",
    )
    assert cls.regime_code == "R7"
    assert cls.scenario == "STRONG_DOWNTREND_RANGE"


def test_vol_code_high_for_re_metrics():
    assert classify_vol_code_v4(atr_1h_pct=3.82, volatility_score=85, return_24h_pct=-9.66) == "V4"


def test_regime_engine_trending_down_before_balanced():
    ind = _re_usdt_indicators()
    sub = SubScores(
        data_quality_score=80,
        liquidity_score=70,
        spread_score=70,
        range_score=55,
        volatility_score=85,
        fee_efficiency_score=55,
        drawdown_risk_score=35,
        btc_market_risk_score=40,
        exposure_safety_score=55,
    )
    portfolio = PortfolioState(
        base_balance=0.0,
        quote_balance=500.0,
        base_value_usdt=0.0,
        quote_value_usdt=500.0,
        total_equity_usdt=500,
        current_base_exposure_frac=0.0,
    )
    from tests.dynamic_param_score.conftest import constraints as dps_constraints

    constraints = dps_constraints()
    tag = classify_regime(ind, sub, portfolio, constraints, param_score=56)
    assert tag == RegimeTag.TRENDING_DOWN


def test_three_grid_near_equal_distribution_fixed():
    dist, changed = normalize_side_distribution([29, 34, 36], defensive=True)
    assert changed
    assert dist == [12, 28, 60]


def test_avax_overbought_btc_pressure_not_r3_v4_normal():
    """AVAX-like: vol pct 91, wide chop, overbought, BTC pressure → defensive shelf."""
    ind = IndicatorSnapshot(
        price_valid=True,
        higher_highs=True,
        lower_lows=True,
        atr14_pct_5m=0.55,
        atr14_pct_1h=1.79,
        volatility_percentile=91.08,
        adx_1h=15.8,
        rsi14_5m=70.3,
        z_score_5m=2.22,
        price_in_bb=1.04,
        return_24h_pct=4.07,
        btc_crash_velocity=-0.97,
        orderbook_spread_pct=0.02,
        quote_volume_24h=17_200_000,
    )
    sub = SubScores(
        trend_score=55,
        volatility_score=70,
        range_score=60,
        liquidity_score=75,
        spread_score=80,
        momentum_score=55,
        mean_reversion_score=50,
        drawdown_risk_score=65,
        btc_market_risk_score=70,
        exposure_safety_score=70,
        fee_efficiency_score=25,
        data_quality_score=75,
    )
    portfolio = PortfolioState(
        base_balance=0.0,
        quote_balance=500.0,
        base_value_usdt=0.0,
        quote_value_usdt=500.0,
        total_equity_usdt=500,
        current_base_exposure_frac=0.0,
    )
    from tests.dynamic_param_score.conftest import constraints as dps_constraints

    constraints = dps_constraints()
    regime = classify_regime(ind, sub, portfolio, constraints, param_score=68)
    assert regime == RegimeTag.RANGE_HIGH_VOL

    from app.services.dynamic_param_score.regime import determine_risk_state

    risk = determine_risk_state(regime, 68, sub, portfolio, constraints, ind=ind)
    assert risk == "DEFENSIVE"

    sig = market_signature_v4_from_live(
        symbol="AVAXUSDT",
        budget=500,
        regime=regime.value,
        risk_level=risk,
        volatility_percentile=91.08,
        lower_lows=True,
        higher_highs=True,
        fee_efficiency_score=25,
        atr_1h_pct=1.79,
        return_24h_pct=4.07,
        drawdown_7d_pct=3.21,
        z_score_5m=2.22,
        price_in_bb=1.04,
        volatility_score=70,
        btc_crash_velocity=-0.97,
    )
    assert sig["regime_code"] in ("R13", "R14", "R4", "R5")
    assert sig["regime_code"] != "R3"
    assert "DEFENSIVE" in sig["route_key"]
    assert sig["vol_code"] in ("V3", "V4")

    from app.services.dynamic_param_score.param_generator.v4_resolvers import (
        generate_runtime_safe_profile,
    )

    profile = generate_runtime_safe_profile(
        sig,
        budget=500,
        min_notional=10,
        constraints=constraints,
        spread_pct=0.02,
        fee_efficiency_score=25,
    )
    assert profile["buy_distribution"] == [12, 28, 60]
    assert float(profile["max_base_exposure_frac"]) <= 0.55
    assert float(profile["base_alloc_frac"]) <= 0.42


def test_wide_chop_high_vol_not_balanced_r2():
    cls = classify_regime_code_v4(
        regime_tag=RegimeTag.BALANCED_RANGE.value,
        lower_lows=True,
        higher_highs=True,
        return_24h_pct=2.0,
        drawdown_7d_pct=8.0,
        atr_1h_pct=3.2,
        risk_level="DEFENSIVE",
        btc_crash_velocity=-0.97,
        volatility_percentile=95.0,
    )
    assert cls.regime_code in ("R4", "R5", "R14")
    assert cls.regime_code != "R2"


def test_two_grid_distribution_ban():
    dist, changed = normalize_side_distribution([50, 50], defensive=True)
    assert changed
    assert dist == [30, 70]


def test_trailing_cap_30pct():
    assert cap_trailing_pct(1.44, 2.43) == pytest.approx(0.729, abs=0.01)
    assert trailing_too_large(1.44, 2.43)


def test_live_route_constraints_caps_base_and_dist():
    merged = apply_live_route_constraints(
        {
            "base_alloc_frac": 0.45,
            "quote_alloc_frac": 0.55,
            "buy_distribution": [50, 50],
            "sell_distribution": [50, 50],
            "buy_grid_ladder_pcts": [3.54, 8.15],
            "sell_grid_ladder_pcts": [2.43, 5.52],
            "buy_trailing_pct": 1.16,
            "sell_trailing_pct": 1.44,
            "risk_class": "NORMAL",
        },
        {
            "regime_code": "R7",
            "structure_code": "S2",
            "risk_class": "DEFENSIVE",
        },
    )
    assert merged["base_alloc_frac"] <= 0.30
    assert merged["buy_distribution"] == [30, 70]
    assert merged["sell_trailing_pct"] <= 2.43 * 0.30 + 1e-6
    assert merged.get("defensive_fallback_overlay")


def test_defensive_fallback_keys_avoid_normal_first():
    keys = clean_fallback_keys("A3|R7|S2|V4|DEFENSIVE")
    normals = [k for k in keys if k.endswith("|NORMAL")]
    assert not normals or keys.index(normals[0]) > 2


@pytest.mark.parametrize("seed", [42])
def test_simulated_lower_lows_defensive_scenarios(seed: int):
    rng = random.Random(seed)
    r2_count = 0
    v2_count = 0
    base_over_cap = 0
    equal_dist = 0
    trailing_fail = 0
    for _ in range(100):
        ret24 = rng.uniform(-18, -6)
        dd7 = rng.uniform(20, 50)
        atr = rng.uniform(3.0, 6.0)
        z = rng.uniform(-3.0, -1.5)
        cls = classify_regime_code_v4(
            regime_tag=RegimeTag.BALANCED_RANGE.value,
            lower_lows=True,
            higher_highs=False,
            return_24h_pct=ret24,
            drawdown_7d_pct=dd7,
            z_score_5m=z,
            atr_1h_pct=atr,
            risk_level="DEFENSIVE",
        )
        if cls.regime_code == "R2":
            r2_count += 1
        vol = classify_vol_code_v4(atr_1h_pct=atr, volatility_score=80, return_24h_pct=ret24)
        if vol == "V2":
            v2_count += 1
        merged = apply_live_route_constraints(
            {
                "base_alloc_frac": 0.45,
                "buy_distribution": [50, 50],
                "buy_grid_ladder_pcts": [3.5, 8.0],
                "buy_trailing_pct": 1.2,
                "risk_class": "NORMAL",
            },
            {
                "regime_code": cls.regime_code,
                "structure_code": "S2",
                "risk_class": "DEFENSIVE",
            },
        )
        if merged["base_alloc_frac"] > 0.35:
            base_over_cap += 1
        if merged.get("buy_distribution") == [50, 50]:
            equal_dist += 1
        if trailing_too_large(merged.get("buy_trailing_pct", 0), 3.5):
            trailing_fail += 1

    assert r2_count == 0
    assert v2_count == 0
    assert base_over_cap == 0
    assert equal_dist == 0
    assert trailing_fail == 0
