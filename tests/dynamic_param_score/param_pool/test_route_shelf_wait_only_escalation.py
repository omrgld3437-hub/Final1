"""Route shelf must not stop on DEFENSIVE WAIT-only profiles when deployable library exists."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache, load_indexed_pool


V4_SQLITE = (
    Path(__file__).resolve().parents[3] / "data" / "param_pool" / "v4" / "param_pool_v4.sqlite"
)


@pytest.mark.skipif(not V4_SQLITE.exists(), reason="v4 param pool sqlite not present")
def test_defensive_wait_only_shelf_escalates_to_normal_deployable():
    clear_pool_cache()
    pool = load_indexed_pool(POOL_VERSION_V4)

    signature = {
        "asset_code": "A4",
        "regime_code": "R2",
        "structure_code": "S2",
        "vol_code": "V4",
        "risk_class": "DEFENSIVE",
        "route_key": "A4|R2|S2|V4|DEFENSIVE",
    }
    hits, trace = pool.query_route_shelf_with_trace(signature)

    assert trace.get("defensive_fallback_overlay") is True
    assert trace.get("wait_only_escalation") is True
    assert trace.get("fallback_route", "").endswith("|NORMAL")
    assert hits, "NORMAL route should return deployable library templates"
    assert any(t.deployable for t in hits)
    assert all(
        t.final_action not in ("WAIT", "NO_TRADE", "SAFE_WAIT") for t in hits if t.deployable
    )
