"""V6 full catalog static + path simulation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dynamic_param_v6.v6_simulation_common import (
    EXPECTED_PROFILE_COUNT,
    REPORT_DIR,
    assert_catalog_count,
    load_catalog_profiles,
    run_path_simulation_all,
    run_static_validation_all,
    simulate_profile_path,
    validate_profile_static,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG_FILE = ROOT / "data" / "dynamic_param_v6" / "dplv6_profile_catalog.json"


@pytest.fixture(scope="module")
def catalog_profiles():
    profiles = load_catalog_profiles()
    assert_catalog_count(profiles)
    return profiles


def test_catalog_count_and_unique_ids(catalog_profiles):
    assert len(catalog_profiles) == EXPECTED_PROFILE_COUNT
    ids = [p.profile_id for p in catalog_profiles]
    assert len(set(ids)) == EXPECTED_PROFILE_COUNT


def test_catalog_json_envelope():
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    assert raw.get("profile_count") == EXPECTED_PROFILE_COUNT or len(raw.get("profiles", [])) == EXPECTED_PROFILE_COUNT


def test_all_profiles_static_invariants(catalog_profiles):
    results, counter = run_static_validation_all(catalog_profiles)
    failures = [r for r in results if not r.ok]
    if failures:
        sample = failures[:5]
        msgs = [f"{r.profile_id}: {r.errors}" for r in sample]
        pytest.fail(f"{len(failures)} static failures; samples: {msgs}")
    assert not counter


def test_pb11_profiles_preserve_profit_loop(catalog_profiles):
    pb11 = [p for p in catalog_profiles if p.scenario.behavior_id == "PB11"]
    assert pb11, "expected PB11 profiles in catalog"
    broken = []
    for p in pb11:
        r = validate_profile_static(p)
        if "ERROR_PB11_LOOP_BROKEN" in r.errors:
            broken.append(p.profile_id)
    assert not broken, f"PB11 loop broken: {broken[:10]}"


def test_path_simulation_sample(catalog_profiles):
    """Quick path dry-run on first 20 profiles (full run via CLI tool)."""
    sample = catalog_profiles[:20]
    results, _ = run_path_simulation_all(sample, budgets=(500,), paths={"PATH_CRASH_BOUNCE": [100, 88, 76, 82, 90, 84, 92]})
    errors = [r for r in results if not r.ok]
    assert not errors, f"path errors: {errors[:3]}"


def test_single_profile_path_metrics():
    profiles = load_catalog_profiles()
    p = next(x for x in profiles if x.scenario.behavior_id == "PB11")
    row = simulate_profile_path(
        p,
        path_name="PATH_CRASH_BOUNCE",
        prices=[100, 88, 76, 82, 90, 84, 92],
        budget=500,
    )
    assert row.events["sell_orders_created"] >= 0
    assert "ERROR_PB11_LOOP_BROKEN" not in row.errors


@pytest.mark.slow
def test_full_catalog_simulation_reports_exist():
    """After running simulate_all_v6_profiles.py, report files should exist."""
    static_json = REPORT_DIR / "all_profiles_static_validation.json"
    if not static_json.is_file():
        pytest.skip("run tools/dynamic_param_v6/simulate_all_v6_profiles.py first")
    data = json.loads(static_json.read_text(encoding="utf-8"))
    assert data.get("profile_count") == EXPECTED_PROFILE_COUNT


def test_report_summary_loads_catalog_counts():
    from tools.dynamic_param_v6.v6_simulation_common import (
        load_catalog_simulation_counts,
        merge_report_summary,
    )

    counts = load_catalog_simulation_counts()
    if counts.get("profiles_tested", 0) == 0:
        pytest.skip("catalog simulation artifacts not generated yet")
    agg = merge_report_summary({"summary": {"profiles_tested": 0, "path_simulations": 0}})
    assert agg["summary"]["profiles_tested"] == EXPECTED_PROFILE_COUNT
    assert agg["summary"]["path_simulations"] == EXPECTED_PROFILE_COUNT * 5 * 10
