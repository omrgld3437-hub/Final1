"""Mandatory V4 acceptance test package (sections 15.1–15.8)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.dynamic_param_score.audit_v4.acceptance_v4 import (
    audit_critical_route_coverage,
    audit_crash_fallback_chain,
    audit_profile_fingerprints,
    audit_route_manifest,
    run_eth_lower_lows_defensive_audit,
    run_mandatory_acceptance_suite,
    run_re_like_downtrend_audit,
)
from app.services.dynamic_param_score.audit_v4.auditor import (
    load_v4_templates_sampled,
    run_random_profile_logic_audit,
    run_random_signature_selection_audit,
)
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    clean_route_key,
    is_forbidden_fallback,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    MANDATORY_CRITICAL_ROUTES,
    ROUTE_MANIFEST_TOTAL,
    enumerate_critical_routes,
    enumerate_shelf_routes,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)

V4_SQLITE = Path(DEFAULT_V4_SQLITE_PATH)
V4_INDEX = Path(DEFAULT_V4_SELECTION_INDEX_PATH)
HAS_V4_POOL = V4_SQLITE.exists() and V4_INDEX.exists()
AUDIT_SEED = 20260626
AUDIT_SAMPLE = 1000


# --- 15.1 Route manifest ---


def test_route_manifest_total_10710():
    report = audit_route_manifest()
    assert report["route_manifest_total"] == 10710
    assert report["route_manifest_total"] == ROUTE_MANIFEST_TOTAL
    assert report["route_key_parts"] == 5
    assert report["budget_in_route"] == 0
    assert report["fee_in_route"] == 0
    assert report["invalid_route_key"] == 0
    assert report["pass"] is True


def test_clean_route_excludes_budget_fee():
    rk = clean_route_key("A1", "R6", "S2", "V3", "DEFENSIVE")
    parts = rk.split("|")
    assert len(parts) == 5
    assert not any(p.startswith("B") for p in parts)
    assert not any(p.startswith("F") for p in parts)


# --- 15.2 Critical route coverage ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_critical_routes_not_empty():
    report = audit_critical_route_coverage(V4_INDEX, min_critical=100)
    assert report["critical_routes_checked"] >= 100
    assert report["mandatory_route_empty"] == 0
    assert report["pass"] is True
    if report.get("optional_route_empty_total", 0) > 0:
        assert report["status"] == "warning"
        assert report["extended_pass"] is False
    else:
        assert report.get("extended_pass") is True


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_mandatory_critical_routes_populated():
    raw = json.loads(V4_INDEX.read_text(encoding="utf-8"))
    index = raw.get("index_by_route_key") or raw.get("route_index") or {}
    for rk in MANDATORY_CRITICAL_ROUTES:
        assert len(index.get(rk) or []) >= 3, f"empty mandatory shelf: {rk}"


# --- 15.3 Random profile logic ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_random_profile_logic_audit():
    templates, _ = load_v4_templates_sampled(
        str(V4_SQLITE), sample_size=AUDIT_SAMPLE, seed=AUDIT_SEED
    )
    report = run_random_profile_logic_audit(templates, sample_size=AUDIT_SAMPLE, seed=AUDIT_SEED)
    assert report["schema_fail"] == 0
    assert report["ladder_null_fail"] == 0
    assert report["distribution_fail"] == 0
    assert report["trailing_fail"] == 0
    assert report["directional_critical_fail"] == 0
    assert report["exposure_violation"] == 0
    assert report["min_notional_critical_fail"] == 0
    assert report["fee_contradiction"] == 0
    assert report["pass"] is True


# --- 15.4 Random signature selection ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_random_signature_selection_audit():
    templates, _ = load_v4_templates_sampled(
        str(V4_SQLITE), sample_size=AUDIT_SAMPLE, seed=AUDIT_SEED
    )
    report = run_random_signature_selection_audit(
        templates, sample_size=AUDIT_SAMPLE, seed=AUDIT_SEED
    )
    assert report["invalid_fallback"] == 0
    assert report["zero_candidate_but_selected"] == 0
    assert report["selection_trace_missing"] == 0
    assert report["pass"] is True


# --- 15.5 RE-like downtrend ---


def test_re_like_downtrend_100_scenarios():
    report = run_re_like_downtrend_audit(sample_size=100, seed=AUDIT_SEED)
    assert report["wrong_balanced_regime"] == 0
    assert report["wrong_low_volatility"] == 0
    assert report["base_alloc_above_35"] == 0
    assert report["buy_grid_not_wider_than_sell"] == 0
    assert report["equal_two_grid_distribution"] == 0
    assert report["trailing_too_large"] == 0
    assert report["pass"] is True


# --- 15.6 ETH lower-lows defensive ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_eth_lower_lows_defensive_selection():
    templates, _ = load_v4_templates_sampled(str(V4_SQLITE), sample_size=200, seed=AUDIT_SEED)
    report = run_eth_lower_lows_defensive_audit(templates)
    assert report["exact_candidate_count"] > 0
    assert report["runtime_safe_profile_generated"] is False
    assert report["max_exposure_above_50"] == 0
    assert report["distribution_equal_fail"] == 0
    assert report["pass"] is True


# --- 15.7 Crash fallback ---


def test_crash_fallback_never_balanced():
    report = audit_crash_fallback_chain()
    assert report["r8_to_r2_fallback"] == 0
    assert report["r8_to_r1_fallback"] == 0
    assert report["r8_to_r3_fallback"] == 0
    assert report["invalid_fallback"] == 0
    assert report["pass"] is True


def test_forbidden_r7_to_r2_fallback():
    assert is_forbidden_fallback("R7", "R2")
    assert is_forbidden_fallback("R8", "R2")
    assert is_forbidden_fallback("R8", "R1")
    assert is_forbidden_fallback("R8", "R3")


# --- 15.8 Duplicate fingerprint ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_profile_fingerprint_duplicate_rates():
    templates, meta = load_v4_templates_sampled(
        str(V4_SQLITE), sample_size=5000, seed=AUDIT_SEED
    )
    report = audit_profile_fingerprints(templates, pool_total=meta.get("profiles_total", 300_000))
    assert report["near_duplicate_rate"] <= 0.25
    assert report["critical_duplicate_rate"] <= 0.10


# --- 16 Final acceptance suite ---


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
@pytest.mark.slow
def test_mandatory_acceptance_suite_final():
    if os.getenv("DPS_FULL_ACCEPTANCE") != "1":
        pytest.skip("Set DPS_FULL_ACCEPTANCE=1 for full suite (needs seeded DEFENSIVE shelves)")
    suite = run_mandatory_acceptance_suite(
        profiles_path=str(V4_SQLITE),
        index_path=V4_INDEX,
        sample_size=AUDIT_SAMPLE,
        seed=AUDIT_SEED,
    )
    assert suite["route_manifest_total"] == 10710
    assert suite["budget_in_route"] == 0
    assert suite["fee_in_route"] == 0
    assert suite["critical_route_empty"] == 0
    assert suite["distribution_fail"] == 0
    assert suite["trailing_too_large"] == 0
    assert suite["directional_critical_fail"] == 0
    assert suite["invalid_fallback"] == 0
    assert suite["r8_to_r2_fallback"] == 0
    assert suite["pass"] is True


def test_shelf_route_count_matches_theory():
    routes = enumerate_shelf_routes()
    assert len(routes) == 10710
    assert len(set(routes)) == 10710


def test_extended_coverage_seed_acceptance_parity():
    """Seed post-index and acceptance must share manifest + gap count."""
    from app.services.dynamic_param_score.param_generator.extended_coverage_v4 import (
        audit_extended_coverage_from_index,
        audit_extended_coverage_from_sqlite,
    )
    from app.services.dynamic_param_score.param_pool.sqlite_store import (
        DEFAULT_V4_SELECTION_INDEX_PATH,
        DEFAULT_V4_SQLITE_PATH,
    )

    if not DEFAULT_V4_SQLITE_PATH.is_file() or not DEFAULT_V4_SELECTION_INDEX_PATH.is_file():
        pytest.skip("V4 pool not present")

    idx_report = audit_extended_coverage_from_index(DEFAULT_V4_SELECTION_INDEX_PATH)
    sql_report = audit_extended_coverage_from_sqlite(DEFAULT_V4_SQLITE_PATH)
    acceptance = audit_critical_route_coverage(DEFAULT_V4_SELECTION_INDEX_PATH)

    assert idx_report["optional_route_empty_total"] == sql_report["optional_route_empty_total"]
    assert acceptance["optional_route_empty_total"] == idx_report["optional_route_empty_total"]
    assert acceptance["extended_pass"] == idx_report["extended_pass"]


def test_critical_route_list_at_least_100():
    assert len(enumerate_critical_routes(min_count=100)) >= 100


def test_r15_derivation_never_uses_r2():
    from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
        derive_source_route_candidates,
    )

    for target in (
        "A1|R15|S2|V1|DEFENSIVE",
        "A1|R15|S2|V4|NORMAL",
    ):
        sources = derive_source_route_candidates(target)
        assert sources
        assert not any("|R2|" in s for s in sources)


def test_seed_report_mandatory_vs_optional_fields():
    from app.services.dynamic_param_score.param_generator.critical_shelf_seeder_v4 import (
        _finalize_seed_report,
    )

    report = _finalize_seed_report(
        routes_checked=["A1|R6|S2|V3|DEFENSIVE", "A1|R15|S2|V1|NORMAL"],
        templates_by_route={"A1|R6|S2|V3|DEFENSIVE": ["a"] * 5},
        routes_seed_failed=[],
        min_profiles=3,
        optional_empty_total=24,
        optional_empty_total_routes=["A1|R7|S8|V1|DEFENSIVE"] * 24,
    )
    assert report["mandatory_route_empty"] == 0
    assert report["optional_route_empty_this_run"] == 1
    assert report["optional_route_empty_total"] == 24
    assert report["pass"] is True
    assert report["seed_target_pass"] is False
    assert report["status"] == "warning"
    assert report["extended_pass"] is False
