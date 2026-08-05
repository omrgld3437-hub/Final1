"""V6 regime stickiness — soft family flips need persistence; hard escapes immediate."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.v6_regime_stickiness import (
    CROSS_SOFT_CONFIRM_SEC,
    SOFT_FAMILY_CONFIRM_SEC,
    apply_regime_stickiness,
    clear_stickiness_for_tests,
)
from app.services.dynamic_param_score.v6.v6_scenario_classifier import ClassifiedScenario


def _sc(
    regime: str,
    *,
    hint: str = "",
    label: str = "",
    hard_block: bool = False,
) -> ClassifiedScenario:
    return ClassifiedScenario(
        regime_id=regime,
        sub_id="01",
        micro_id="001",
        behavior_id="STD",
        label=label or regime,
        sub_profile_hint=hint,
        hard_block=hard_block,
        hard_block_reasons=("TEST",) if hard_block else (),
        matched_gates=("test",),
    )


def setup_function() -> None:
    clear_stickiness_for_tests()


def test_first_observation_locks_regime() -> None:
    out, meta = apply_regime_stickiness(
        _sc("R3", hint="R3_STD_UPTREND_COMPRESSION", label="sıkışma"),
        sticky_key="pa:ETHUSDT",
        now_ts=1_000.0,
    )
    assert out.regime_id == "R3"
    assert meta["accepted"] is True
    assert meta.get("held") is False


def test_uptrend_family_flip_held_until_confirm_window() -> None:
    t0 = 10_000.0
    apply_regime_stickiness(
        _sc("R3", hint="R3_STD_UPTREND_COMPRESSION", label="sıkışma"),
        sticky_key="pa:ETHUSDT",
        now_ts=t0,
    )
    held, meta = apply_regime_stickiness(
        _sc("R1", hint="R1_STD_TREND_COOLDOWN", label="yukarı soğuma"),
        sticky_key="pa:ETHUSDT",
        now_ts=t0 + 60.0,
    )
    assert held.regime_id == "R3"
    assert meta["held"] is True
    assert meta["accepted"] is False
    assert meta["confirm_sec"] == float(SOFT_FAMILY_CONFIRM_SEC)

    accepted, meta2 = apply_regime_stickiness(
        _sc("R1", hint="R1_STD_TREND_COOLDOWN", label="yukarı soğuma"),
        sticky_key="pa:ETHUSDT",
        # Candidate started at t0+60; confirm window is measured from that.
        now_ts=t0 + 60.0 + SOFT_FAMILY_CONFIRM_SEC + 5.0,
    )
    assert accepted.regime_id == "R1"
    assert meta2["accepted"] is True
    assert meta2["held"] is False


def test_hard_block_escapes_immediately() -> None:
    t0 = 20_000.0
    apply_regime_stickiness(
        _sc("R1", label="yukarı"),
        sticky_key="pa:BTCUSDT",
        now_ts=t0,
    )
    out, meta = apply_regime_stickiness(
        _sc("R8", label="crash", hard_block=True),
        sticky_key="pa:BTCUSDT",
        now_ts=t0 + 10.0,
    )
    assert out.regime_id == "R8"
    assert out.hard_block is True
    assert meta.get("escape") == "hard"


def test_r7_escape_from_uptrend_is_immediate() -> None:
    t0 = 30_000.0
    apply_regime_stickiness(
        _sc("R5", label="breakout"),
        sticky_key="dm:2:ETHUSDT",
        now_ts=t0,
    )
    out, meta = apply_regime_stickiness(
        _sc("R7", label="düşüş"),
        sticky_key="dm:2:ETHUSDT",
        now_ts=t0 + 15.0,
    )
    assert out.regime_id == "R7"
    assert meta.get("escape") == "downtrend"


def test_seed_from_previous_snapshot_prev_regime() -> None:
    t0 = 40_000.0
    held, meta = apply_regime_stickiness(
        _sc("R1", label="yukarı"),
        sticky_key="dm:9:SOLUSDT",
        prev_regime_id="R3",
        prev_sub_profile_hint="R3_STD_UPTREND_COMPRESSION",
        prev_regime_label="sıkışma",
        now_ts=t0 + 30.0,
    )
    assert held.regime_id == "R3"
    assert meta["held"] is True


def test_uptrend_to_r6_requires_cross_soft_window() -> None:
    t0 = 50_000.0
    apply_regime_stickiness(
        _sc("R1", hint="R1_STD_PULLBACK", label="pullback"),
        sticky_key="pa:RECOVERYUSDT",
        now_ts=t0,
    )
    held, meta = apply_regime_stickiness(
        _sc("R6", hint="R6_RECOVERY_ACT", label="toparlanma"),
        sticky_key="pa:RECOVERYUSDT",
        now_ts=t0 + 120.0,
    )
    assert held.regime_id == "R1"
    assert meta["held"] is True
    assert meta["confirm_sec"] == float(CROSS_SOFT_CONFIRM_SEC)
    assert meta["confirm_remaining_sec"] > 0
    assert meta["candidate_regime_id"] == "R6"

    accepted, meta2 = apply_regime_stickiness(
        _sc("R6", hint="R6_RECOVERY_ACT", label="toparlanma"),
        sticky_key="pa:RECOVERYUSDT",
        now_ts=t0 + 120.0 + CROSS_SOFT_CONFIRM_SEC + 5.0,
    )
    assert accepted.regime_id == "R6"
    assert meta2["accepted"] is True
    assert meta2["confirm_remaining_sec"] == 0.0
