from __future__ import annotations

from app.services.param_optimizer.indicators import HistoryFeatures
from app.services.param_optimizer.robust_policy import (
    REGIMES,
    ForecastSkill,
    build_robust_forecast,
    build_robust_policy_report,
    build_state_policy,
    deploy_gate,
    forecast_skill_gate,
    markov_forward,
    robust_objective,
)


def _features(**over):
    f = HistoryFeatures()
    f.regime_code = over.pop("regime_code", "LOW_VOL_RANGING")
    f.regime_label = over.pop("regime_label", "Dusuk vol yatay")
    f.confidence = over.pop("confidence", 80)
    f.atr_pct = over.pop("atr_pct", 1.2)
    f.realized_vol_pct = over.pop("realized_vol_pct", 1.1)
    f.daily_range_med_pct = over.pop("daily_range_med_pct", 1.5)
    f.trend_score = over.pop("trend_score", 0.0)
    for k, v in over.items():
        setattr(f, k, v)
    return f


def test_markov_forward_keeps_probability_distribution_normalized():
    gamma = {r: 0.0 for r in REGIMES}
    gamma["LOW_VOL_RANGING"] = 1.0
    transition = {
        src: {dst: (0.8 if src == dst else 0.2 / (len(REGIMES) - 1)) for dst in REGIMES}
        for src in REGIMES
    }

    rows = markov_forward(gamma, transition, 4)

    assert len(rows) == 4
    for row in rows:
        assert abs(sum(row.values()) - 1.0) < 1e-9
        assert set(row) == set(REGIMES)
    assert rows[0]["LOW_VOL_RANGING"] > rows[-1]["LOW_VOL_RANGING"]


def test_skill_gate_passes_only_when_model_beats_baseline_oos():
    actuals = ["LOW_VOL_RANGING", "LOW_VOL_RANGING", "TRENDING_DOWN"]
    good = [
        {"LOW_VOL_RANGING": 0.88, "TRENDING_DOWN": 0.12},
        {"LOW_VOL_RANGING": 0.82, "TRENDING_DOWN": 0.18},
        {"LOW_VOL_RANGING": 0.15, "TRENDING_DOWN": 0.85},
    ]
    bad = [
        {"LOW_VOL_RANGING": 0.10, "TRENDING_DOWN": 0.90},
        {"LOW_VOL_RANGING": 0.20, "TRENDING_DOWN": 0.80},
        {"LOW_VOL_RANGING": 0.90, "TRENDING_DOWN": 0.10},
    ]
    baseline = [{"LOW_VOL_RANGING": 0.67, "TRENDING_DOWN": 0.33}] * 3

    assert forecast_skill_gate(good, actuals, baseline).passed
    failed = forecast_skill_gate(bad, actuals, baseline)
    assert not failed.passed
    assert failed.fallback_used
    assert failed.skill_score <= 0


def test_state_policy_is_vol_forecast_function_not_free_parameter():
    passed = ForecastSkill(0.4, 0.8, 0.5, True, False)
    low = build_robust_forecast(_features(atr_pct=0.8), skill=passed, horizon_steps=3)
    high = build_robust_forecast(_features(atr_pct=4.0), skill=passed, horizon_steps=3)

    low_policy = build_state_policy(low, _features(atr_pct=0.8))
    high_policy = build_state_policy(high, _features(atr_pct=4.0))

    assert high_policy["LOW_VOL_RANGING"].grid_step_pct > low_policy["LOW_VOL_RANGING"].grid_step_pct
    assert high_policy["DUMP_RISK"].grid_step_pct > high_policy["LOW_VOL_RANGING"].grid_step_pct
    assert high_policy["DUMP_RISK"].position_scale < high_policy["LOW_VOL_RANGING"].position_scale


def test_robust_objective_penalizes_left_tail():
    smooth = [4.0, 4.0, 4.0, 4.0, 4.0]
    tail_risky = [14.0, 14.0, 14.0, 14.0, -50.0]

    assert robust_objective(smooth) > robust_objective(tail_risky)


def test_deploy_gate_requires_all_hard_checks():
    skill = ForecastSkill(0.5, 1.0, 0.5, True, False)
    yes = deploy_gate(
        skill=skill,
        oos={"return_pct": 6.0},
        walk_forward={"frac_profitable": 0.7, "total_cycles": 20},
        pbo=0.2,
        deflated_sharpe_ok=True,
        stress_ok=True,
        plateau_ok=True,
    )
    no = deploy_gate(
        skill=skill,
        oos={"return_pct": 6.0},
        walk_forward={"frac_profitable": 0.7, "total_cycles": 20},
        pbo=0.7,
        deflated_sharpe_ok=True,
        stress_ok=True,
        plateau_ok=True,
    )

    assert yes.deploy
    assert not no.deploy
    assert "pbo_ok" in no.reasons


def test_report_falls_back_to_climatology_without_nested_oos_skill():
    result = {
        "oos_result": {"return_pct": 12.0},
        "forecast": {"p05_return_pct": 2.0},
        "walk_forward": {"frac_profitable": 0.8, "total_cycles": 30},
    }

    report = build_robust_policy_report(_features(), result)

    assert report["forecast"]["skill"]["fallback_used"]
    assert not report["deploy_gate"]["deploy"]
    assert "forecast_skill_positive" in report["deploy_gate"]["reasons"]
    assert "LOW_VOL_RANGING" in report["policy"]
