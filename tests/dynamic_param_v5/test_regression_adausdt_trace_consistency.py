"""ADAUSDT live-output regression — trace consistency class fixes."""

from __future__ import annotations

import os

import pytest

from app.services.dynamic_param_score.v5.audit.regression_cases import (
    assert_regression_case_rules,
    run_all_regression_cases,
)
from app.services.dynamic_param_score.v5.audit.trace_consistency import audit_trace_consistency
from app.services.dynamic_param_score.v5.ui_trace import (
    RISK_LABELS,
    build_pattern_phrase,
    risk_label_from_route,
)


@pytest.fixture(autouse=True)
def _v5_env():
    os.environ["PARAM_POOL_VERSION"] = "v5.0.0"
    yield


def test_pattern_phrase_no_false_lower_lows():
    phrase = build_pattern_phrase(higher_highs=True, lower_lows=False, range_stability=0.5)
    assert "alt dip" not in phrase.lower() or "teyidi yok" in phrase.lower()


def test_risk_label_from_route_k2():
    rk = "A3|R6|D1|S4|V3|K2|L2"
    assert risk_label_from_route(rk) == RISK_LABELS["K2"]


def test_trace_consistency_k2_not_defensive():
    rendered = {
        "route_key": "A3|R6|D1|S4|V3|K2|L2",
        "profile_id": "DPLV5_A3_R6_D1_S4_V3_K2_L2",
        "ui_risk_label": "Savunmacı",
        "explanation_risk_label": "Normal kontrollü",
    }
    v = audit_trace_consistency(rendered)
    codes = {x.code for x in v}
    assert "UI_RISK_ROUTE_MISMATCH" in codes


def test_adausdt_regression_cases():
    cases = run_all_regression_cases()
    assert len(cases) >= 2
    all_violations = []
    for case in cases:
        all_violations.extend(case.get("violations") or [])
        all_violations.extend(assert_regression_case_rules(case))
    blockers = [v for v in all_violations if getattr(v, "severity", None) in ("BLOCKER", "CRITICAL")]
    assert not blockers, f"Regression violations: {[getattr(v, 'code', None) for v in blockers]}"
