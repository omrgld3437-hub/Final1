"""Param pool registry and validation tests."""

from __future__ import annotations

from app.services.dynamic_param_score.param_pool.defaults import (
    POOL_VERSION_V2,
    POOL_VERSION_V3,
    build_v1_pool,
)
from app.services.dynamic_param_score.param_pool.registry import (
    assert_pool_valid,
    get_active_pool,
    load_pool,
)
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def test_v1_pool_size_in_target_range():
    pool = build_v1_pool()
    assert 49_000 <= len(pool) <= 50_500


def test_active_pool_loads():
    import os

    version, templates = get_active_pool()
    assert version.version_id in (POOL_VERSION_V2, POOL_VERSION_V3)
    min_size = 99_000 if os.environ.get("DPS_FULL_POOL") == "1" else 500
    assert len(templates) >= min_size
    assert all(t.status == "active" for t in templates)


def test_pool_validation_passes():
    assert_pool_valid()
    pool = load_pool()
    ok, errors = validate_pool(pool)
    assert ok, errors[:5]


def test_pinned_templates_present():
    pool = build_v1_pool()
    keys = {t.template_key for t in pool}
    assert "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT" in keys
    assert "BALANCED_RANGE_STANDARD_60_69_CAUTION_GRID" in keys
    assert "RANGE_HIGH_VOL_MEDIUM_75_89_ACTIVE_GRID" in keys
    assert "DUMP_RISK_ANY_NO_TRADE" in keys
    assert "OVEREXPOSED_ANY_RECOVERY_SELL" in keys
    assert "BALANCED_RANGE_60_69_FEE_BAD_WAIT" in keys
