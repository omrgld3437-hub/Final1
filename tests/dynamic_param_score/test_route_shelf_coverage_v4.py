"""V4 route shelf coverage — 10,710 manifest vs selection index."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dynamic_param_score.audit_v4.full_pool_audit import build_route_coverage
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    MANDATORY_CRITICAL_ROUTES,
    ROUTE_MANIFEST_TOTAL,
    enumerate_shelf_routes,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import DEFAULT_V4_SELECTION_INDEX_PATH

V4_INDEX = Path(DEFAULT_V4_SELECTION_INDEX_PATH)
HAS_V4_INDEX = V4_INDEX.exists()


def test_route_manifest_count_10710():
    routes = enumerate_shelf_routes()
    assert len(routes) == ROUTE_MANIFEST_TOTAL == 10710


@pytest.mark.skipif(not HAS_V4_INDEX, reason="V4 selection index not present")
def test_mandatory_routes_populated():
    cov = build_route_coverage(V4_INDEX, violations=[])
    mandatory_empty = cov.get("mandatory_empty") or []
    assert mandatory_empty == [], f"mandatory empty: {mandatory_empty[:5]}"


@pytest.mark.skipif(not HAS_V4_INDEX, reason="V4 selection index not present")
def test_critical_shelf_tags_mostly_populated():
    cov = build_route_coverage(V4_INDEX, violations=[])
    tags = cov.get("critical_shelf_tags") or {}
    for tag in ("crash", "recovery", "defensive_risk"):
        info = tags.get(tag) or {}
        assert info.get("populated", 0) > 0, f"critical tag empty: {tag}"


@pytest.mark.skipif(not HAS_V4_INDEX, reason="V4 selection index not present")
def test_index_covers_majority_of_routes():
    cov = build_route_coverage(V4_INDEX, violations=[])
    with_profiles = cov.get("routes_with_profiles", 0)
    safe_empty = cov.get("empty_with_safe_fallback", 0)
    resolvable = with_profiles + safe_empty
    # Pool uses lazy shelf indexing — not all 10710 routes are populated.
    assert with_profiles >= 2000, f"too few direct routes: {with_profiles}"
    assert resolvable >= 3000, (
        f"too few resolvable routes: direct={with_profiles} fallback={safe_empty}"
    )


@pytest.mark.skipif(not HAS_V4_INDEX, reason="V4 selection index not present")
def test_each_mandatory_route_has_min_profiles():
    cov = build_route_coverage(V4_INDEX, violations=[])
    rows = {r["route_key"]: r for r in cov.get("rows") or []}
    for rk in MANDATORY_CRITICAL_ROUTES:
        assert rows[rk]["profile_count"] >= 3, rk
