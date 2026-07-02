"""V4 clean route_key + resolver architecture acceptance tests."""

from __future__ import annotations

import os

import pytest

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import ExchangeConstraints, FinalAction, RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    clean_route_key,
    clean_fallback_keys,
    is_forbidden_fallback,
    normalize_route_key,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import market_signature_v4_from_live
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    SCENARIO_SPECS,
    validate_scenario_direction,
)
from app.services.dynamic_param_score.param_generator.v4_resolvers import (
    generate_runtime_safe_profile,
    resolve_capacity,
    resolve_cost,
)
from app.services.dynamic_param_score.param_generator.v4_scoring import (
    base_quote_fit_score,
    hard_reject_v4,
    structure_fit_score,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
    FAST_TEST_POOL_TARGET_V4,
    POOL_VERSION_V4,
    build_dps_v4_pool,
)


@pytest.fixture(scope="module")
def v4_pool():
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    return build_dps_v4_pool(total_target=FAST_TEST_POOL_TARGET_V4, migrate_v3=False)


def test_clean_route_key_does_not_include_budget():
    rk = clean_route_key("A1", "R6", "S2", "V3", "NORMAL")
    assert rk == "A1|R6|S2|V3|NORMAL"
    assert "B" not in rk.split("|")


def test_clean_route_key_does_not_include_fee():
    rk = clean_route_key("A1", "R6", "S2", "V3", "NORMAL")
    assert "|F" not in rk
    assert len(rk.split("|")) == 5


def test_normalize_legacy_7_part_route():
    legacy = "A1|B3|R6|S2|V3|F3|NORMAL"
    assert normalize_route_key(legacy) == "A1|R6|S2|V3|NORMAL"


def test_budget_resolver_calculates_buy_sell_capacity():
    cap = resolve_capacity(
        budget=50.0,
        base_alloc_frac=0.30,
        quote_alloc_frac=0.70,
        min_notional=5.0,
        profile_buy_n=3,
        profile_sell_n=3,
    )
    assert cap.base_value == pytest.approx(15.0, rel=0.01)
    assert cap.quote_value == pytest.approx(35.0, rel=0.01)
    assert cap.buy_grid_capacity >= 1
    assert cap.sell_grid_capacity <= 3


def test_cost_resolver_widens_grid_on_fee_bad():
    cost = resolve_cost(
        constraints=ExchangeConstraints(
            min_notional=5.0,
            step_size=0.0001,
            tick_size=0.01,
            min_qty=0.0001,
            taker_fee_pct=0.2,
            maker_fee_pct=0.2,
            estimated_slippage_pct=0.1,
        ),
        spread_pct=0.08,
        fee_efficiency_score=20,
    )
    assert cost.grid_widening_multiplier >= 1.15
    assert cost.fee_tier == "FEE_BAD"


def test_lower_lows_routes_to_down_profile():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime="TRENDING_DOWN",
        risk_level="NORMAL",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=0.97,
    )
    assert sig["route_key"] == "A1|R6|S2|V3|NORMAL"
    assert sig["direction_bias"] == "DOWN_BIAS"


def test_higher_highs_routes_to_up_profile():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime="TRENDING_UP",
        risk_level="NORMAL",
        volatility_percentile=55.0,
        lower_lows=False,
        higher_highs=True,
        fee_efficiency_score=60,
        atr_1h_pct=1.1,
    )
    assert "R9" in sig["route_key"] or "R10" in sig["route_key"]
    assert sig["structure_code"] == "S3"
    assert sig["direction_bias"] == "UP_BIAS"


def test_lower_lows_buy_grid_wider_than_sell():
    spec = SCENARIO_SPECS["LOWER_LOWS_WEAK_DOWN_RANGE"]
    ok, _ = validate_scenario_direction(
        spec, 0.30, 0.70, [1.80, 4.00, 8.00], [1.25, 3.00]
    )
    assert ok


def test_higher_highs_sell_grid_wider_than_buy():
    spec = SCENARIO_SPECS["HIGHER_HIGHS_WEAK_UP_RANGE"]
    ok, _ = validate_scenario_direction(
        spec, 0.60, 0.40, [1.20, 2.80], [2.00, 4.60, 9.00]
    )
    assert ok


def test_crash_does_not_fallback_to_balanced():
    assert is_forbidden_fallback("R8", "R2")
    assert is_forbidden_fallback("CRASH_RISK", "BALANCED_RANGE")


def test_low_budget_reduces_grid_count_not_spacing():
    cap = resolve_capacity(
        budget=17.5,
        base_alloc_frac=0.30,
        quote_alloc_frac=0.70,
        min_notional=5.0,
        profile_buy_n=3,
        profile_sell_n=3,
    )
    assert cap.buy_grid_capacity <= 2


def test_ladder_fields_not_null_runtime_safe():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime="TRENDING_DOWN",
        risk_level="NORMAL",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
    )
    prof = generate_runtime_safe_profile(
        sig,
        budget=50.0,
        min_notional=5.0,
        constraints=ExchangeConstraints(
            min_notional=5.0,
            step_size=0.0001,
            tick_size=0.01,
            min_qty=0.0001,
            taker_fee_pct=0.1,
            maker_fee_pct=0.1,
            estimated_slippage_pct=0.05,
        ),
        spread_pct=0.03,
        fee_efficiency_score=55,
    )
    assert prof["buy_grid_ladder_pcts"]
    assert prof["sell_grid_ladder_pcts"]
    assert prof.get("fallback_generated") is True


def test_structure_fit_zero_rejected():
    tmpl = ParamTemplate(
        template_key="T",
        version="v4",
        profile_family="BALANCED_GRID",
        final_action=FinalAction.BALANCED_GRID.value,
        score_min=0,
        score_max=100,
        supported_regimes=[RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL"],
        budget_tiers=["SMALL"],
        exposure_tiers=["LOW_BASE"],
        headroom_tiers=["HIGH_HEADROOM"],
        fee_tiers=["STANDARD"],
        min_equity_usdt=10.0,
        min_notional_multiple=1.0,
        params={
            "buy_grid_ladder_pcts": [1.5, 3.0],
            "sell_grid_ladder_pcts": [1.5, 3.0],
            "dps_profile": {
                "structure_code": "S3",
                "regime_code": "R9",
                "buy_grid_ladder_pcts": [1.5, 3.0],
                "sell_grid_ladder_pcts": [1.5, 3.0],
            },
        },
        deployable=True,
    )
    sig = {"structure_code": "S2", "regime_code": "R6", "direction_bias": "DOWN_BIAS", "grid_bias": "BUY_WIDER_SELL_CLOSER"}
    assert hard_reject_v4(tmpl, sig) == "structure_fit_zero"
    assert structure_fit_score("S3", "S2") == 0.0


def test_runtime_safe_profile_when_route_missing():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime="TRENDING_DOWN",
        risk_level="NORMAL",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
    )
    p = generate_runtime_safe_profile(
        sig,
        budget=50.0,
        min_notional=5.0,
        constraints=ExchangeConstraints(
            min_notional=5.0,
            step_size=0.0001,
            tick_size=0.01,
            min_qty=0.0001,
            taker_fee_pct=0.1,
            maker_fee_pct=0.1,
            estimated_slippage_pct=0.05,
        ),
        spread_pct=0.03,
        fee_efficiency_score=55,
    )
    assert p["route_key"]
    assert p["fallback_generated"]


def test_dynamic_mode_and_assistant_same_engine():
    assert hasattr(DynamicParamScoreEngine, "select_profile")
    assert hasattr(DynamicParamScoreEngine, "calculate_decision")


def test_frontend_reads_final_action():
    from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
    from app.services.dynamic_param_score.models import DynamicParamDecision, BotParams

    params = BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=1.5,
        sell_grid_spacing_pct=1.5,
        buy_qty_distribution=[0.35, 0.65],
        sell_qty_distribution=[0.35, 0.65],
        trailing_enabled=True,
        trailing_callback_pct=0.4,
        take_profit_pct=2.0,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.7,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=1.0,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
        buy_disabled=False,
        sell_only_mode=False,
        buy_grid_ladder_pcts=[1.5, 3.0],
        sell_grid_ladder_pcts=[1.5, 3.0],
    )
    dec = DynamicParamDecision(
        decision_id="x",
        symbol="ETHUSDT",
        timestamp=0,
        run_source="test",
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        deployable=True,
        param_score=62,
        confidence_score=70,
        risk_score=30,
        regime_tag="TRENDING_DOWN",
        risk_state="NORMAL",
        selected_profile_name="ACTIVE_DEFENSIVE_GRID",
        selected_profile_bucket="BALANCED_HIGH",
        params=params,
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain={},
        telemetry={"param_pool": {"selection_context": {}}},
    )
    out = decision_to_param_assistant_result(dec, budget=50.0, symbol="ETHUSDT")
    assert out["final_action"] == FinalAction.ACTIVE_DEFENSIVE_GRID.value


def test_ethusdt_lower_lows_signature():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime="TRENDING_DOWN",
        risk_level="NORMAL",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=0.97,
    )
    assert sig["route_key"] == "A1|R6|S2|V3|NORMAL"
    assert sig["grid_bias"] == "BUY_WIDER_SELL_CLOSER"


def test_candidate_count_under_500(v4_pool):
    from app.services.dynamic_param_score.param_pool.sqlite_store import ParamPool
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

    pool = ParamPool(pool_version=POOL_VERSION_V4, templates=v4_pool)
    pool.build_memory_indexes()
    sig = market_signature_v4_from_live(
        symbol="BTCUSDT",
        budget=75.0,
        regime="BALANCED_RANGE",
        risk_level="NORMAL",
        volatility_percentile=50.0,
        lower_lows=False,
        higher_highs=False,
        fee_efficiency_score=60,
    )
    cands = pool.query_dps_signature_candidates(sig)
    assert len(cands) <= 500
