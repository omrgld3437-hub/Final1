from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_v6_regime_tree import REQUIRED_R5_ROLES, REQUIRED_R8_ROLES, run_audit


@pytest.fixture(scope="module")
def tree_audit(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("v6_tree_audit")
    return run_audit(Path(output_dir))


def _report(tree_audit):
    return tree_audit["report"]


def _nodes(tree_audit):
    return tree_audit["tree"]["nodes"]


def test_v6_regime_tree_has_8_main_regimes(tree_audit):
    assert _report(tree_audit)["counts"]["main_regimes"] == 8


def test_v6_regime_tree_all_main_regimes_have_children(tree_audit):
    regimes = [n for n in _nodes(tree_audit) if n["node_type"] == "regime"]
    assert len(regimes) == 8
    assert all(n["children"] for n in regimes)


def test_v6_regime_tree_all_branches_have_semantic_role(tree_audit):
    branches = [n for n in _nodes(tree_audit) if n["node_type"] != "regime"]
    assert branches
    assert all(str(n.get("semantic_role") or "").strip() for n in branches)


def test_v6_regime_tree_all_leaves_have_valid_profiles(tree_audit):
    report = _report(tree_audit)
    assert report["counts"]["severity_leaf_profiles"] == 2295
    assert report["leaf_profile_failure_count"] == 0


def test_v6_regime_tree_no_unreachable_critical_branches(tree_audit):
    assert _report(tree_audit)["unreachable_branch_count"] == 0


def test_v6_regime_tree_no_duplicate_critical_branches(tree_audit):
    assert _report(tree_audit)["duplicate_branch_count"] == 0


def test_v6_regime_tree_no_misplaced_branches(tree_audit):
    assert _report(tree_audit)["misplaced_branch_count"] == 0


def test_v6_regime_tree_r5_has_required_subroles(tree_audit):
    present = set(_report(tree_audit)["r5_required_subroles_present"])
    assert REQUIRED_R5_ROLES.issubset(present)


def test_v6_regime_tree_r8_has_panic_and_conditional_probe(tree_audit):
    present = set(_report(tree_audit)["r8_required_subroles_present"])
    assert REQUIRED_R8_ROLES.issubset(present)


def test_v6_regime_tree_r6_requires_recovery_semantics(tree_audit):
    roles = set(_report(tree_audit)["roles_by_regime"]["R6"])
    assert roles
    assert all("RECOVERY" in role or role in {"DRAW_DOWN_BOUNCE"} for role in roles)


def test_v6_regime_tree_low_liq_is_adjustment_not_fake_main_regime(tree_audit):
    regimes = {n["regime_id"] for n in _nodes(tree_audit) if n["node_type"] == "regime"}
    assert "LOW_LIQUIDITY_RESTRICTED" not in regimes
    assert "LOW_LIQUIDITY_RESTRICTED" in set(_report(tree_audit)["roles_by_regime"]["R5"])


def test_v6_regime_tree_display_templates_match_semantic_roles(tree_audit):
    nodes = _nodes(tree_audit)
    r5 = [n for n in nodes if n["regime_id"] == "R5" and n["node_type"] == "tactical_behavior"]
    assert any(n["semantic_role"] == "CLEAN_BREAKOUT" and "Temiz breakout" in n["display_title"] for n in r5)
    assert any(n["semantic_role"] == "POST_BREAKOUT_COOLDOWN" and "kontrollü soğuma" in n["display_title"] for n in r5)
    assert any(n["semantic_role"] == "LOW_LIQUIDITY_RESTRICTED" and "restricted" in n["display_title"] for n in r5)


def test_v6_regime_tree_all_severity_variants_exist(tree_audit):
    leaves = [n for n in _nodes(tree_audit) if n["node_type"] == "profile_leaf"]
    grouped = {}
    for n in leaves:
        key = (n["regime_id"], n["scenario_id"], n["micro_scenario_id"], n["tactical_behavior_id"], n["parent_id"])
        grouped.setdefault(key, set()).add(n["severity"])
    assert grouped
    assert all(sevs == {"DEF", "STD", "ACT"} for sevs in grouped.values())


def test_v6_regime_tree_all_leaf_profiles_are_params_valid(tree_audit):
    assert _report(tree_audit)["critical_fail_count"] == 0
    assert _report(tree_audit)["counts"]["checked_leaf_profiles"] == 2295
