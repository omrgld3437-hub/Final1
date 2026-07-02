"""Black-box API tests for Param Assistant — mirrors UI POST /calculate."""

from __future__ import annotations

import pytest

from tools.param_pool.param_assistant_e2e_lib import (
    acceptance_passes,
    build_user_request,
    check_hard_invariants,
    compute_acceptance_flags,
    expand_scenario,
    extract_audit_row,
    run_user_flow_case,
)

pytestmark = [pytest.mark.network]


@pytest.fixture(scope="module")
def blackbox_client(param_assistant_client, network_available):
    if not network_available:
        pytest.skip("Binance network unavailable")
    return param_assistant_client


def test_calculate_user_payload_shape(blackbox_client):
    spec = expand_scenario("first_start", 100.0)
    payload = build_user_request(spec, "BTCUSDT")
    assert payload["dry_run"] is True
    assert payload["budget"] == 100.0
    status, body = blackbox_client.post_calculate(payload)
    assert status == 200, body
    row = extract_audit_row(
        body, symbol="BTCUSDT", budget=100.0, scenario="first_start", request=payload
    )
    assert row["result_type"]
    assert row["invariant_failures"] == check_hard_invariants(row)


@pytest.mark.parametrize(
    "symbol,budget,scenario",
    [
        ("ETHUSDT", 50.0, "first_start"),
        ("SOLUSDT", 100.0, "has_base"),
        ("TONUSDT", 1000.0, "normal_budget"),
    ],
)
def test_param_assistant_blackbox_matrix(blackbox_client, symbol, budget, scenario):
    row = run_user_flow_case(
        blackbox_client,
        symbol=symbol,
        scenario=scenario,
        budget=budget,
    )
    assert row.get("http_status", 200) == 200
    assert not row.get("invariant_failures"), row


def test_no_one_grid_deployable_blackbox(blackbox_client):
    rows = []
    for symbol in ("BTCUSDT", "SOLUSDT", "ADAUSDT"):
        rows.append(
            run_user_flow_case(blackbox_client, symbol=symbol, scenario="first_start", budget=50.0)
        )
    flags = compute_acceptance_flags(rows)
    assert flags["one_grid_deployable_violation"] == 0
    assert acceptance_passes(flags)
