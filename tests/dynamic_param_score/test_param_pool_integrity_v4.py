"""V4 param pool integrity — full scan gates (disk pool required for integration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.dynamic_param_score.audit_v4.full_pool_audit import (
    analyze_duplicates,
    build_fallback_map,
    iter_sqlite_profiles,
)
from app.services.dynamic_param_score.audit_v4.auditor import (
    _profile_dict,
    audit_profile_distribution,
    audit_trailing,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)

V4_SQLITE = Path(DEFAULT_V4_SQLITE_PATH)
V4_INDEX = Path(DEFAULT_V4_SELECTION_INDEX_PATH)
HAS_V4_POOL = V4_SQLITE.exists() and V4_INDEX.exists()


def test_v4_pool_files_exist_when_integration():
    if not HAS_V4_POOL:
        pytest.skip("V4 pool not on disk")
    manifest = V4_SQLITE.parent / "param_pool_v4.manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("template_count") == 300_000


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_all_profile_ids_unique_in_stream():
    seen: set[str] = set()
    dup = 0
    total = 0
    for batch in iter_sqlite_profiles(V4_SQLITE, batch_size=5000):
        for tmpl in batch:
            total += 1
            if tmpl.template_key in seen:
                dup += 1
            seen.add(tmpl.template_key)
        if total >= 50000:
            break
    assert dup == 0, f"duplicate profile_id in first 50k: {dup}"
    assert total >= 50000


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_sampled_profiles_have_valid_route_keys():
    bad = 0
    n = 0
    for batch in iter_sqlite_profiles(V4_SQLITE, batch_size=2000):
        for tmpl in batch:
            p = _profile_dict(tmpl)
            rk = str(p.get("route_key") or "")
            parts = rk.split("|")
            if len(parts) != 5:
                bad += 1
            n += 1
        if n >= 10000:
            break
    assert bad == 0, f"invalid route_key in sample: {bad}"


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_no_fifty_fifty_in_sampled_profiles():
    fails = 0
    n = 0
    for batch in iter_sqlite_profiles(V4_SQLITE, batch_size=2000):
        for tmpl in batch:
            p = _profile_dict(tmpl)
            dist_fails = audit_profile_distribution(p)
            if any("fifty_fifty" in c for c in dist_fails):
                fails += 1
            n += 1
        if n >= 20000:
            break
    assert fails == 0


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_no_equal_three_grid_in_sampled_profiles():
    fails = 0
    n = 0
    for batch in iter_sqlite_profiles(V4_SQLITE, batch_size=2000):
        for tmpl in batch:
            p = _profile_dict(tmpl)
            dist_fails = audit_profile_distribution(p)
            if any("equal_three" in c for c in dist_fails):
                fails += 1
            n += 1
        if n >= 20000:
            break
    assert fails == 0


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 sqlite pool not present")
def test_trailing_cap_in_sampled_profiles():
    fails = 0
    n = 0
    for batch in iter_sqlite_profiles(V4_SQLITE, batch_size=2000):
        for tmpl in batch:
            p = _profile_dict(tmpl)
            if audit_trailing(p):
                fails += 1
            n += 1
        if n >= 20000:
            break
    assert fails == 0


def test_fallback_map_r8_never_r2():
    fb = build_fallback_map()
    r8 = fb.get("r8_crash_audit") or {}
    assert r8.get("r8_to_r2_fallback", 0) == 0
    assert r8.get("pass") is True


def test_r15_source_order():
    fb = build_fallback_map()
    assert fb.get("r15_source_order") == ["R12", "R7", "R6"]
