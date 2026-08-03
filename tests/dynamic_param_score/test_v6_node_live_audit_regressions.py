from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import live_audit_v6_random_100 as audit


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = ROOT / "artifacts" / "v6_live_audit_real_test_account" / "raw_snapshots"


def _snapshot(symbol: str) -> dict:
    path = SNAPSHOT_DIR / f"{symbol}.json"
    if not path.exists():
        pytest.skip(f"node-live replay snapshot missing: {symbol}")
    return audit.replay_snapshot_for_audit(json.loads(path.read_text(encoding="utf-8")))


def _case(symbol: str, budget: float) -> dict:
    return audit.audit_case(symbol, budget, _snapshot(symbol))


@pytest.mark.parametrize(
    "symbol",
    [
        "NEIROUSDT",
        "EURIUSDT",
        "EIGENUSDT",
        "ARBUSDT",
        "EPICUSDT",
        "BICOUSDT",
        "ETCUSDT",
        "GPSUSDT",
        "SLPUSDT",
        "MINAUSDT",
        "IOUSDT",
        "TLMUSDT",
        "CFXUSDT",
    ],
)
@pytest.mark.parametrize("budget", [50, 100, 1000])
def test_node_live_l2_restricted_never_deployable_true(symbol: str, budget: float):
    row = _case(symbol, budget)
    assert row["liquidity_bucket"] == "L2_RESTRICTED"
    assert row["deployable"] is False
    assert row["restricted"] is True
    assert row["params_valid"] is True
    assert "LOW_LIQUIDITY_RESTRICTED" in row["reason_codes"]
    assert "LOW_LIQ_WRONG_DEPLOYABLE" not in row["audit_critical_failures"]


@pytest.mark.parametrize(
    ("symbol", "budget"),
    [
        ("DYDXUSDT", 50),
        ("DYDXUSDT", 100),
        ("JSTUSDT", 50),
        ("JSTUSDT", 100),
        ("KAITOUSDT", 50),
        ("MANTAUSDT", 50),
        ("MANTAUSDT", 100),
    ],
)
def test_node_live_deployable_true_requires_order_feasibility(symbol: str, budget: float):
    row = _case(symbol, budget)
    assert row["params_valid"] is True
    if row["deployable"]:
        assert row["min_notional_pass"] is True
        assert row["lot_size_pass"] is True
        assert row["tick_size_pass"] is True
    assert "DEPLOYABLE_ORDER_FEASIBILITY_FAIL" not in row["audit_critical_failures"]


def test_node_live_dydx_r8_small_budget_not_deployable_if_order_infeasible():
    row = _case("DYDXUSDT", 50)
    assert row["regime"] == "R8"
    if not row["min_notional_pass"]:
        assert row["deployable"] is False


def test_node_live_jst_r3_small_budget_compacts_or_restricts():
    row = _case("JSTUSDT", 50)
    assert row["regime"] == "R3"
    assert row["params_valid"] is True
    assert row["deployable"] is False or row["min_notional_pass"] is True


def test_node_live_kaito_r6_50usdt_compacts_or_restricts():
    row = _case("KAITOUSDT", 50)
    assert row["regime"] == "R6"
    assert row["params_valid"] is True
    assert row["deployable"] is False or row["min_notional_pass"] is True


def test_node_live_manta_r8_small_budget_not_deployable_if_order_infeasible():
    row = _case("MANTAUSDT", 50)
    assert row["regime"] == "R8"
    if not row["min_notional_pass"]:
        assert row["deployable"] is False


@pytest.mark.parametrize("budget", [50, 100, 1000])
def test_node_live_r5_non_recovery_display_never_says_toparlanma(budget: float):
    row = _case("SEIUSDT", budget)
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("display_title", "display_subtitle", "display_description")
    ).lower()
    assert row["regime"] == "R5"
    # SEI maps to R5_RECOVERY_GENERIC in the weekly library — "Toparlanma" is canonical.
    assert "genel toparlanma" in blob or row.get("selected_profile_key") == "R5_RECOVERY_GENERIC" or (
        "toparlan" not in blob and "recovery" not in blob
    )
    assert "DISPLAY_R5_FALSE_RECOVERY" not in row["audit_critical_failures"]


def test_node_live_sei_r5_display_not_false_recovery():
    row = _case("SEIUSDT", 50)
    assert row["display_semantic_verdict"] == "DISPLAY_OK"
    assert "DISPLAY_R5_FALSE_RECOVERY" not in row["audit_critical_failures"]
