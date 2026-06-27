"""Integrity tests for self-healing audit report artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_MD = ROOT / "reports" / "DYNAMIC_PARAM_V5_SELF_HEALING_AUDIT_AND_REPAIR.md"
SNAPSHOT_JSON = ROOT / "reports" / "self_heal_audit_snapshot.json"
DISTRIBUTION_JSON = ROOT / "reports" / "self_heal_distribution_audit.json"
SCENARIO_FIT_JSON = ROOT / "reports" / "self_heal_scenario_fit.json"
LIVE_SAMPLES_JSON = ROOT / "reports" / "self_heal_live_samples.json"
REGRESSION_JSON = ROOT / "reports" / "self_heal_regression_cases.json"

MANDATORY_HEADINGS = [
    "## 1. Yönetici Özeti",
    "## 4. Bilinen Regression Case'ler",
    "## 5. Scenario-Fit Sonuçları",
    "## 6. Distribution Audit",
    "## 7. Live-Style Sample Outputs",
    "## 8. R8/R15 Özel Kuralları",
    "## 10. Final Karar",
]

RENDERED_REQUIRED = [
    "ui_risk_label",
    "route_risk",
    "market_regime_text",
    "pattern_phrase",
    "higher_highs",
    "lower_lows",
    "target_base_pct",
    "max_exposure_pct",
    "worst_exposure_pct",
    "active_buy_ladder_budget_usdt",
    "min_notional_usdt",
    "buy_orders_active",
    "final_action_label",
    "deployable",
    "final_first_buy_grid",
    "final_first_sell_grid",
    "risk_opportunity_text",
]


@pytest.fixture(scope="module")
def report_md_text():
    if not REPORT_MD.exists():
        pytest.skip("self-heal report not generated yet")
    return REPORT_MD.read_text(encoding="utf-8")


def test_report_not_truncated_mid_json(report_md_text):
    assert "equal_2_grid" not in report_md_text or "equal_2_grid_count" in report_md_text
    assert report_md_text.count("```") % 2 == 0
    assert "## 3. Mevcut V5 Durumu" in report_md_text
    assert report_md_text.index("## 4.") < report_md_text.index("## 10.")


def test_mandatory_headings(report_md_text):
    for h in MANDATORY_HEADINGS:
        assert h in report_md_text


def test_snapshot_json_parseable():
    if not SNAPSHOT_JSON.exists():
        pytest.skip("snapshot json missing")
    data = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    assert "simulation" in data
    assert "distribution" in data


def test_distribution_json_complete():
    if not DISTRIBUTION_JSON.exists():
        pytest.skip("distribution json missing")
    data = json.loads(DISTRIBUTION_JSON.read_text(encoding="utf-8"))
    count = data.get("equal_2_grid_count", 0)
    routes = data.get("equal_2_routes") or []
    assert len(routes) == count
    for r in routes:
        assert "justification" in r


def test_scenario_fit_has_sub_scores():
    if not SCENARIO_FIT_JSON.exists():
        pytest.skip("scenario fit json missing")
    data = json.loads(SCENARIO_FIT_JSON.read_text(encoding="utf-8"))
    assert "sub_score_summary" in data
    assert data.get("min_score", 100) <= data.get("avg_score", 100)
    if data.get("total", 0) > 1000:
        assert data.get("min_score", 100) < 100.0 or data.get("below_85_count", 0) == 0


def test_r15_sample_is_r15():
    if not LIVE_SAMPLES_JSON.exists():
        pytest.skip("live samples json missing")
    data = json.loads(LIVE_SAMPLES_JSON.read_text(encoding="utf-8"))
    r15 = next((s for s in data.get("samples", []) if "R15" in s.get("name", "")), None)
    assert r15 is not None
    assert r15.get("actual_regime_code") == "R15", r15
    assert "|R15|" in r15.get("route_key", "")
    assert r15.get("regime_match") is True
    assert not data.get("regime_mismatches")


def test_ada_regression_rendered_fields():
    if not REGRESSION_JSON.exists():
        pytest.skip("regression json missing")
    cases = json.loads(REGRESSION_JSON.read_text(encoding="utf-8"))
    assert len(cases) >= 2
    for case in cases:
        rf = case.get("rendered_fields") or {}
        for key in RENDERED_REQUIRED:
            assert key in rf, f"{case.get('case_id')} missing {key}"


def test_low_vol_sample_regime():
    if not LIVE_SAMPLES_JSON.exists():
        pytest.skip("live samples json missing")
    data = json.loads(LIVE_SAMPLES_JSON.read_text(encoding="utf-8"))
    lv = next((s for s in data.get("samples", []) if "low-vol squeeze" in s.get("name", "").lower()), None)
    assert lv is not None
    assert lv.get("actual_regime_code") == "R3"
    assert lv.get("regime_match") is True
