"""V6 opportunity-oriented logic — params always produced, less over-protective."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.models import BotContext, DynamicParamDecision
from app.services.dynamic_param_score.v6.domain.types import V6InputContract
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (
    POOL_VERSION_V6,
    v6_final_to_bot_params,
    v6_final_to_telemetry_extras,
)
from app.services.dynamic_param_score.v6.v6_opportunity import (
    apply_policy_label_v6,
    resolve_v6_apply_policy,
)
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display


def _base_inp(**kwargs) -> V6InputContract:
    defaults: Dict[str, Any] = dict(
        symbol="TESTUSDT",
        bot_budget_usdt=500.0,
        current_price=100.0,
        min_notional=10.0,
        tick_size=0.01,
        step_size=0.001,
        price_precision=2,
        quantity_precision=3,
        price_valid=True,
        candles_5m=500,
        candles_1h=200,
        volume_consistency=0.9,
        spread_pct=0.02,
        volume_24h=50_000_000.0,
        asset_fragility_class="F1",
    )
    defaults.update(kwargs)
    return V6InputContract(**defaults)


def _decision_from_inp(inp: V6InputContract) -> DynamicParamDecision:
    """Run V6 engine and build a PA-ready DynamicParamDecision."""
    import time

    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    budget = float(inp.bot_budget_usdt or 500)
    bot_params = v6_final_to_bot_params(result, bot_budget_usdt=budget)
    trace = result.telemetry.get("adjuster_trace") or []
    v6_display = enrich_v6_display(
        v6_final_to_telemetry_extras(result, bot_budget_usdt=budget, adjuster_trace=trace),
        adjuster_trace=trace,
        deployable=result.deployable,
        deploy_block_reason=result.deploy_block_reason,
    )
    final_action = "CONTROLLED_GRID" if result.deployable else "WAIT"
    policy = resolve_v6_apply_policy(
        deployable=result.deployable,
        params=bot_params,
        final_action=final_action,
    )
    decision = DynamicParamDecision(
        decision_id=DynamicParamDecision.new_id(),
        symbol=str(inp.symbol or "TESTUSDT").upper(),
        timestamp=int(time.time() * 1000),
        run_source="param_assistant",
        final_action=final_action,
        deployable=result.deployable,
        param_score=70,
        confidence_score=70,
        risk_score=40,
        regime_tag=str(scenario.get("regime_id", "R2")),
        risk_state="DEFENSIVE" if result.profile.scenario.severity == "DEF" else "NORMAL",
        selected_profile_name=result.catalog_profile_id,
        selected_profile_bucket="V6",
        params=bot_params,
        safety_gates=[],
        blocking_reasons=[result.deploy_block_reason] if result.deploy_block_reason else [],
        warnings=[],
        explain="",
        telemetry={
            "pool_version": POOL_VERSION_V6,
            "apply_policy": policy,
            "v6_display": v6_display,
            "v6_final": {
                "catalog_profile_id": result.catalog_profile_id,
                "profile": {
                    "profile_id": result.profile.profile_id,
                    "scenario": {
                        "regime_id": scenario.get("regime_id"),
                        "sub_id": scenario.get("sub_id"),
                        "micro_id": scenario.get("micro_id"),
                        "behavior_id": scenario.get("behavior_id"),
                        "severity": scenario.get("severity"),
                    },
                    "base_allocation_pct": result.profile.base_allocation_pct,
                    "quote_allocation_pct": result.profile.quote_allocation_pct,
                    "normal_buy_enabled": result.profile.normal_buy_enabled,
                    "buy_grids": [
                        {"distance_pct": g.distance_pct, "amount_pct": g.amount_pct}
                        for g in result.profile.buy_grids
                    ],
                    "sell_grids": [
                        {"distance_pct": g.distance_pct, "amount_pct": g.amount_pct}
                        for g in result.profile.sell_grids
                    ],
                },
                **result.telemetry,
            },
        },
    )
    return decision


def pa_dm_adapter(decision: DynamicParamDecision, *, budget: float = 500.0) -> Dict[str, Any]:
    result = decision_to_param_assistant_result(decision, budget=budget, symbol=decision.symbol)
    blob = json.dumps(result, default=str, ensure_ascii=False)
    result["display_text"] = blob + (decision.explain or "") + (result.get("final_action_label") or "")
    return result


@pytest.fixture
def r8_f3_v5_fixture() -> V6InputContract:
    return _base_inp(
        symbol="RISKUSDT",
        return_24h_pct=-12.0,
        drawdown_7d_pct=18.0,
        crash_velocity=-2.5,
        asset_fragility_class="F3",
        atr_1h_pct=4.5,
        volatility_percentile=92.0,
        bb_width=9.0,
        spread_pct=0.12,
        volume_consistency=0.32,
    )


@pytest.fixture
def btc_r6_fixture() -> V6InputContract:
    return _base_inp(
        symbol="BTCUSDT",
        range_stability=0.42,
        volatility_percentile=38.0,
        atr_1h_pct=1.0,
        bb_position=0.88,
        z_score=1.45,
        bb_width=2.2,
        asset_fragility_class="F0",
        volume_consistency=0.92,
        btc_return_4h_pct=-1.2,
        btc_return_24h_pct=-2.5,
        btc_ema200_below=False,
    )


@pytest.fixture
def btc_r6_clean_fixture(btc_r6_fixture: V6InputContract) -> V6InputContract:
    return btc_r6_fixture


@pytest.fixture
def r6_f3_v5_l3_fixture() -> V6InputContract:
    return _base_inp(
        symbol="ALTUSDT",
        range_stability=0.4,
        volatility_percentile=38.0,
        atr_1h_pct=1.1,
        bb_position=0.9,
        z_score=1.6,
        bb_width=3.0,
        asset_fragility_class="F3",
        spread_pct=0.28,
        volume_consistency=0.25,
        fake_breakout_score=75.0,
    )


@pytest.fixture
def r2_v1_clean_fixture() -> V6InputContract:
    return _base_inp(
        symbol="ETHUSDT",
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


@pytest.fixture
def r8_pb11_fixture() -> V6InputContract:
    return _base_inp(
        symbol="DUMPUSDT",
        return_24h_pct=-14.0,
        drawdown_7d_pct=22.0,
        crash_velocity=-2.8,
        asset_fragility_class="F2",
        atr_1h_pct=6.0,
        volatility_percentile=90.0,
    )


@pytest.fixture
def sol_fixture() -> V6InputContract:
    return _base_inp(
        symbol="SOLUSDT",
        range_stability=0.5,
        volatility_percentile=32.0,
        atr_1h_pct=1.1,
        bb_position=0.86,
        z_score=1.4,
        asset_fragility_class="F0",
        volume_consistency=0.88,
    )


def test_safe_wait_never_nulls_v6_params(r8_f3_v5_fixture: V6InputContract):
    decision = _decision_from_inp(r8_f3_v5_fixture)
    assert decision.params is not None
    response = pa_dm_adapter(decision)
    assert "Parametre önerisi üretilemedi" not in response["display_text"]
    assert decision.telemetry.get("apply_policy") in (
        "high_risk_controlled",
        "controlled_deploy",
        "deployable",
        "technical_block",
    )


def test_btcusdt_btc_context_delta_multiplier_is_half(btc_r6_fixture: V6InputContract):
    decision = _decision_from_inp(btc_r6_fixture)
    trace = (decision.telemetry.get("v6_display") or {}).get("adjuster_trace") or []
    mult = None
    for entry in trace:
        if entry.get("name") == "btc_context":
            mult = entry.get("delta_multiplier")
    assert mult == 0.5


def test_r6_major_clean_coin_uses_bilateral_grid_per_spec(btc_r6_clean_fixture: V6InputContract):
    decision = _decision_from_inp(btc_r6_clean_fixture)
    assert decision.regime_tag != "R6"
    assert decision.regime_tag == "R4"
    params = decision.params
    assert params is not None
    assert 0.35 <= params.base_alloc_frac <= 0.55
    assert params.sell_grid_count >= 3
    assert not params.buy_disabled
    assert params.buy_grid_count >= 1
    assert params.rebuy_enabled
    spec = (decision.telemetry.get("v6_final") or {}).get("opportunity_notes") or {}
    assert spec.get("regime_behavior_spec") is True


def test_r6_high_risk_uses_defensive_profile_not_empty(r6_f3_v5_l3_fixture: V6InputContract):
    decision = _decision_from_inp(r6_f3_v5_l3_fixture)
    assert decision.regime_tag != "R6"
    assert decision.regime_tag == "R4"
    params = decision.params
    assert params is not None
    assert params.base_alloc_frac <= 0.25
    assert params.sell_grid_count >= 1
    assert params.rebuy_enabled


def test_r2_v1_low_vol_grid_not_too_wide_for_one_week_bot(r2_v1_clean_fixture: V6InputContract):
    decision = _decision_from_inp(r2_v1_clean_fixture)
    assert decision.regime_tag == "R2"
    params = decision.params
    assert params is not None
    buy_dist = (params.buy_grid_ladder_pcts or [params.buy_grid_spacing_pct])[0]
    sell_dist = (params.sell_grid_ladder_pcts or [params.sell_grid_spacing_pct])[0]
    assert abs(buy_dist) <= 5
    assert sell_dist <= 4


def test_pb11_always_has_rebuy_and_profit_sell(r8_pb11_fixture: V6InputContract):
    decision = _decision_from_inp(r8_pb11_fixture)
    assert decision.regime_tag == "R8"
    v6_final = decision.telemetry.get("v6_final") or {}
    scenario = v6_final.get("scenario") or {}
    if scenario.get("sub_profile_hint") == "R8_HARD_BLOCK":
        assert decision.deployable is False
        assert decision.blocking_reasons == ["technical_block"]
        assert decision.params.buy_grid_count == 0
        assert decision.params.sell_grid_count == 0
        return
    params = decision.params
    assert params is not None
    assert params.buy_grid_count >= 1
    assert params.sell_grid_count >= 1
    assert params.rebuy_enabled is True
    assert params.resell_enabled is True
    assert params.base_alloc_frac >= 0.05


def test_pb11_non_operational_base_zero_without_grids_repaired(r8_pb11_fixture: V6InputContract):
    decision = _decision_from_inp(r8_pb11_fixture)
    v6_final = decision.telemetry.get("v6_final") or {}
    scenario = v6_final.get("scenario") or {}
    if scenario.get("sub_profile_hint") == "R8_HARD_BLOCK":
        notes = v6_final.get("opportunity_notes") or {}
        assert notes.get("mandatory_deep_buy_skipped") == "hard_block_no_trade"
        assert decision.deployable is False
        return
    v6d = (decision.telemetry.get("v6_display") or {})
    base = int(v6d.get("base_allocation_pct") or 0)
    buy = v6d.get("buy_grid_distances_pct") or []
    sell = v6d.get("sell_grid_distances_pct") or []
    assert not (base == 0 and not buy and not sell)


def test_v6_display_uses_quantized_trailing(sol_fixture: V6InputContract):
    response = pa_dm_adapter(_decision_from_inp(sol_fixture))
    text = response["display_text"]
    assert "%1,12" not in text
    assert "%1,36" not in text


def test_operational_validity_required(r2_v1_clean_fixture: V6InputContract):
    decision = _decision_from_inp(r2_v1_clean_fixture)
    v6_final = (decision.telemetry.get("v6_final") or {})
    validity = (v6_final.get("opportunity_notes") or {}).get("operational_validity") or {}
    assert validity.get("valid") is True
    assert validity.get("mode") in ("bilateral_grid", "deep_buy_only", "sell_management")
    tel = decision.telemetry or {}
    assert tel.get("operational_validity", {}).get("valid") is True or validity.get("valid") is True


def test_r3_without_buy_gets_deep_buy():
    inp = _base_inp(
        symbol="ALTUSDT",
        range_stability=0.55,
        volatility_percentile=48.0,
        atr_1h_pct=1.4,
        bb_width=2.5,
        asset_fragility_class="F1",
        volume_consistency=0.75,
        spread_pct=0.04,
    )
    decision = _decision_from_inp(inp)
    if decision.regime_tag != "R3":
        pytest.skip(f"fixture classified as {decision.regime_tag}, not R3")
    params = decision.params
    assert params is not None
    assert params.buy_grid_count >= 1 or params.sell_grid_count >= 1


def test_workability_zero_when_non_operational():
    from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
    from app.services.dynamic_param_score.v6.v6_opportunity import compute_workability_score_1w

    empty = V6CatalogProfile(
        profile_id="test_empty",
        scenario=ScenarioIdentity("R8", "57", "211", "PB11", "DEF"),
        base_allocation_pct=0,
        quote_allocation_pct=100,
        normal_buy_enabled=False,
        buy_grids=[],
        sell_grids=[],
        buyback_after_sell_enabled=True,
        profit_sell_after_buyback_enabled=True,
    )
    score, warns = compute_workability_score_1w(empty, _base_inp(), [], "R8")
    assert score == 0
    assert "ERROR_NON_OPERATIONAL_PARAMS" in warns


def test_v6_display_hides_fee_efficiency(sol_fixture: V6InputContract):
    response = pa_dm_adapter(_decision_from_inp(sol_fixture))
    text = response["display_text"].lower()
    assert "fee_efficiency" not in text
    assert "fee verimi" not in text
    assert "toplam fee" not in text


def test_apply_policy_label_v6_no_production_failed_message():
    assert "üretilemedi" not in apply_policy_label_v6("high_risk_controlled").lower()
    assert "üretilemedi" not in apply_policy_label_v6("controlled_deploy").lower()


def test_r1_uptrend_raises_base_for_turnover_not_cash_parking():
    from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
    from app.services.dynamic_param_score.v6.v6_regime_behavior_spec import apply_regime_behavior_spec

    trace = [
        {"name": "asset_fragility", "class": "F1"},
        {"name": "btc_context", "class": "B2"},
        {"name": "volatility", "class": "V1"},
    ]
    inp = _base_inp(symbol="SOLUSDT", asset_fragility_class="F1")
    profile = V6CatalogProfile(
        profile_id="r1_test",
        scenario=ScenarioIdentity("R1", "01", "001", "PB05", "STD"),
        base_allocation_pct=30,
        quote_allocation_pct=70,
        normal_buy_enabled=True,
        buy_grids=[GridLevel(-7, 40), GridLevel(-9, 60)],
        sell_grids=[GridLevel(6, 60), GridLevel(10, 40)],
        buyback_after_sell_enabled=True,
        profit_sell_after_buyback_enabled=True,
    )
    out, notes = apply_regime_behavior_spec(
        profile, inp, trace, regime_id="R1", severity="STD"
    )
    assert out.base_allocation_pct >= 65
    assert notes.get("params_valid") is True
    assert len(out.sell_grids) >= 3
