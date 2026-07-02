"""E2E: Param Assistant 50-coin × 3-budget user-flow audit (black-box HTTP)."""

from __future__ import annotations

import os

import pytest

from tools.param_pool.param_assistant_e2e_lib import ParamAssistantHttpClient
from tools.param_pool.param_assistant_user_flow_50coin_lib import (
    final_acceptance_passes,
    run_single_analysis,
    run_50coin_matrix,
    solusdt_regression_checks,
    summarize_runs,
)

pytestmark = [pytest.mark.e2e, pytest.mark.network]

# Quick smoke: 3 coins × 1 budget. Full 150 via PA_50COIN_FULL=1
SMOKE_MATRIX = [
    ("BTCUSDT", 100.0),
    ("SOLUSDT", 1000.0),
    ("ADAUSDT", 50.0),
]


@pytest.fixture(scope="module")
def audit_client(network_available) -> ParamAssistantHttpClient:
    if not network_available:
        pytest.skip("Binance network unavailable for Param Assistant E2E")
    return ParamAssistantHttpClient()


@pytest.fixture(scope="module")
def audit_runs(audit_client) -> list:
    if os.environ.get("PA_50COIN_FULL") == "1":
        from tools.param_pool.param_assistant_user_flow_50coin_lib import (
            DEFAULT_BUDGETS,
            auto50_symbols,
        )

        return run_50coin_matrix(
            audit_client, auto50_symbols(), DEFAULT_BUDGETS, mode="test-local"
        )
    runs = []
    for sym, budget in SMOKE_MATRIX:
        runs.append(run_single_analysis(audit_client, sym, budget, mode="test-local"))
    return runs


def test_user_flow_http_success(audit_runs):
    for r in audit_runs:
        assert r.get("http_status") == 200, r
        assert r.get("response_success"), r


def test_user_flow_has_result_type(audit_runs):
    for r in audit_runs:
        assert r.get("result_type"), f"missing result_type: {r.get('symbol')}"


def test_solusdt_regression_no_blockers(audit_runs):
    """SOLUSDT @ 1000 — section 15 regression when in matrix."""
    issues = solusdt_regression_checks(audit_runs)
    blockers = [a for a in issues if a.level == "BLOCKER"]
    assert not blockers, [a.to_dict() for a in blockers]


def test_no_buy_2grid_50_50_deployable(audit_runs):
    for r in audit_runs:
        codes = [a.get("code") for a in (r.get("anomalies") or [])]
        assert "BUY_2_GRID_50_50_FORBIDDEN" not in codes or not r.get("deployable")


@pytest.mark.skipif(os.environ.get("PA_50COIN_FULL") != "1", reason="Set PA_50COIN_FULL=1 for full 150")
def test_full_150_acceptance(audit_runs):
    summary = summarize_runs(audit_runs)
    assert summary.get("total_runs") == 150
    assert final_acceptance_passes(summary), summary.get("anomaly_counts")
