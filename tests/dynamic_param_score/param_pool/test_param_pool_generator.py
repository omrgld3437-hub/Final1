"""Param pool generator tests."""

from __future__ import annotations

from collections import Counter

from app.services.dynamic_param_score.param_pool.generator import (
    POOL_TARGET_V1,
    generate_pool,
    is_logically_valid_template,
)
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def test_generator_produces_50000_templates():
    pool = generate_pool(POOL_TARGET_V1)
    assert len(pool) == POOL_TARGET_V1


def test_generator_has_unique_template_keys():
    pool = generate_pool(POOL_TARGET_V1)
    keys = [t.template_key for t in pool]
    assert len(keys) == len(set(keys))


def test_generator_profile_distribution():
    pool = generate_pool(POOL_TARGET_V1)
    dist = Counter(t.profile_family for t in pool)
    assert len(dist) >= 15
    assert dist["WAIT_PROFILE"] >= 500
    assert dist["SELL_MANAGEMENT_ONLY_PROFILE"] >= 1000


def test_generator_required_coverage():
    pool = generate_pool(POOL_TARGET_V1)
    keys = {t.template_key for t in pool}
    assert "BALANCED_RANGE_60_69_FEE_BAD_WAIT" in keys
    assert "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT" in keys
    assert "DUMP_RISK_ANY_NO_TRADE" in keys


def test_generator_no_logically_invalid_templates():
    pool = generate_pool(5000)
    assert all(is_logically_valid_template(t) for t in pool)


def test_generator_can_scale_to_100000_dry_run():
    from app.services.dynamic_param_score.param_pool.precision_generator import generate_pool_v2

    pool = generate_pool_v2(100_000)
    assert len(pool) == 100_000
    ok, errors = validate_pool(pool)
    assert ok, errors[:5]
