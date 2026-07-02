"""Param Assistant user-flow E2E — coin + budget + analyze (black-box HTTP)."""

from __future__ import annotations

import pytest

from tools.param_pool.param_assistant_e2e_lib import (
    acceptance_passes,
    compute_acceptance_flags,
    run_user_flow_case,
)

pytestmark = [pytest.mark.e2e, pytest.mark.network]


USER_FLOW_MATRIX = [
    ("BTCUSDT", 50.0, "first_start", False),
    ("SOLUSDT", 100.0, "first_start", False),
    ("ADAUSDT", 50.0, "has_base", False),
    ("ASRUSDT", 100.0, "first_start", False),
    ("SFPUSDT", 50.0, "only_base", False),
    ("PROVEUSDT", 100.0, "first_start", True),
]


@pytest.fixture(scope="module")
def user_flow_rows(param_assistant_client, network_available):
    if not network_available:
        pytest.skip("Binance network unavailable for live Param Assistant E2E")
    rows = []
    for symbol, budget, scenario, fs in USER_FLOW_MATRIX:
        rows.append(
            run_user_flow_case(
                param_assistant_client,
                symbol=symbol,
                scenario=scenario,
                budget=budget,
                first_start_buy_only=fs,
            )
        )
    compute_acceptance_flags(rows)
    return rows


def test_user_flow_http_ok(user_flow_rows):
    for row in user_flow_rows:
        assert row.get("http_status", 200) == 200, row
        assert row.get("ok") is not False, row


def test_user_flow_returns_result_type(user_flow_rows):
    for row in user_flow_rows:
        assert row.get("result_type"), f"missing result_type: {row}"


def test_user_flow_hard_invariants(user_flow_rows):
    failures = []
    for row in user_flow_rows:
        for f in row.get("invariant_failures") or []:
            failures.append(
                f"{row['symbol']}@{row['budget']}:{row['scenario']} "
                f"{f['code']} expected={f['expected']} got={f['got']}"
            )
    assert not failures, "\n".join(failures)


def test_user_flow_final_acceptance(user_flow_rows):
    flags = compute_acceptance_flags(user_flow_rows)
    assert acceptance_passes(flags), flags
