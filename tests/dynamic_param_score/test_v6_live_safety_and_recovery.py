"""P0/P1 V6 live safety, recovery→R6, R2 relaxation, sticky store."""

from __future__ import annotations

import time

from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_botparams_adapter import v6_final_to_bot_params
from app.services.dynamic_param_score.v6.v6_pa_display import format_regime_stickiness_plain
from app.services.dynamic_param_score.v6.v6_regime_stickiness_store import (
    FileStickyStore,
    StickyRecord,
    reset_sticky_store_for_tests,
)
from app.services.dynamic_param_score.v6.v6_scenario_classifier import (
    classify_scenario,
    _r2_balanced_range_ok,
)
from tests.dynamic_param_score.test_v6_opportunity_oriented_logic import _base_inp
from tests.dynamic_param_score.test_v6_regime_classification_gates import (
    _tlm_parabolic_pump_inp,
)


def test_parabolic_keeps_reference_grids_but_disables_live_buys():
    inp = _tlm_parabolic_pump_inp()
    result = V6Engine().run(inp)
    profile = result.profile
    params = v6_final_to_bot_params(result, bot_budget_usdt=float(inp.bot_budget_usdt or 0))
    assert profile.profile_id == "R5_PARABOLIC_PUMP"
    assert len(profile.buy_grids) == 4
    assert len(profile.sell_grids) == 4
    assert bool((profile.modules or {}).get("live_buys_paused")) is True
    assert bool((profile.modules or {}).get("reference_plan_only")) is True
    assert result.deployable is False
    assert params.buy_disabled is True


def test_generic_recovery_maps_to_r6_not_r5():
    """Late heuristic ret24>0 + dd7>5 must land in R6 controlled recovery."""
    inp = _base_inp(
        symbol="RECVUSDT",
        return_24h_pct=2.0,
        return_1h_pct=0.3,
        return_4h_pct=0.5,
        drawdown_7d_pct=8.0,
        volatility_percentile=40.0,
        atr_1h_pct=0.5,
        bb_width=0.8,
        hl_range_pct=0.3,
        range_stability=0.2,
        adx_1h=15.0,
        rsi_1h=50.0,
        rsi_5m=50.0,
        price_vs_ema200_pct=0.5,
        higher_highs=False,
        lower_lows=False,
        ema20_slope=0.05,
        ema50_slope=0.02,
        bb_position=0.5,
        z_score=0.0,
        crash_velocity=0.0,
    )
    classified = classify_scenario(inp)
    assert classified.regime_id == "R6"
    assert classified.sub_profile_hint == "R6_RECOVERY_ACT"
    # Either dedicated late heuristic or earlier recovery_gate — both are R6.
    assert classified.regime_id != "R5"

    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    assert scenario.get("regime_id") == "R6"
    assert result.profile.profile_id == "R6_CONTROLLED_RECOVERY"


def test_r2_relaxed_thresholds_accept_mild_range():
    inp = _base_inp(
        symbol="R2MILDUSDT",
        adx_1h=24.0,
        rsi_1h=43.0,
        rsi_5m=39.0,
        bb_position=0.24,
        z_score=-1.1,
        range_stability=0.48,
        volatility_percentile=30.0,
        volume_spike=3.2,
        price_vs_ema200_pct=5.5,
    )
    assert _r2_balanced_range_ok(inp) is True


def test_file_sticky_store_roundtrip(tmp_path):
    reset_sticky_store_for_tests()
    path = tmp_path / "sticky.json"
    store = FileStickyStore(path)
    now = time.time()
    rec = StickyRecord(
        locked_regime_id="R3",
        locked_sub_hint="R3_STD_UPTREND_COMPRESSION",
        locked_label="sıkışma",
        locked_at=now,
        candidate_regime_id="R1",
        candidate_sub_hint="R1_STD_PULLBACK",
        candidate_label="pullback",
        candidate_since=now,
    )
    store.set("pa:TESTUSDT", rec)
    got = store.get("pa:TESTUSDT")
    assert got is not None
    assert got.locked_regime_id == "R3"
    assert got.candidate_regime_id == "R1"
    assert store.backend_name() == "file"
    reset_sticky_store_for_tests()


def test_stickiness_plain_format():
    text = format_regime_stickiness_plain(
        {
            "held": True,
            "locked_regime_id": "R1",
            "candidate_regime_id": "R6",
            "confirm_remaining_sec": 1800,
        }
    )
    assert "R1" in text and "R6" in text and "dk" in text


def test_r7_conditional_closes_on_weak_liq_high_vol():
    from app.services.dynamic_param_score.v6.net_profile_library import build_profile
    from app.services.dynamic_param_score.v6.v6_live_safety import apply_live_safety_overrides
    from app.services.dynamic_param_score.v6.v6_scenario_classifier import ClassifiedScenario

    classified = ClassifiedScenario(
        regime_id="R7",
        sub_id="01",
        micro_id="001",
        behavior_id="PB10",
        label="Düşüş trendi",
        sub_profile_hint="",
    )
    profile = build_profile("R7_DOWNTREND", classified, "STD")
    assert str((profile.modules or {}).get("automatic_apply_label") or "").startswith("Açık")
    inp = _base_inp(
        symbol="R7WEAKUSDT",
        spread_pct=0.15,
        volume_consistency=0.2,
        volatility_percentile=80.0,
    )
    adjusted, notes = apply_live_safety_overrides(
        profile,
        classified=classified,
        inp=inp,
        opportunity_notes={"reason_codes": []},
    )
    assert bool((adjusted.modules or {}).get("live_buys_paused")) is True
    assert bool((adjusted.modules or {}).get("automatic_apply")) is False
    assert "R7_CONDITIONAL_CLOSED" in (notes.get("reason_codes") or [])
