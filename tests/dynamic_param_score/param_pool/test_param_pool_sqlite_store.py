"""Param pool SQLite store tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_ID
from app.services.dynamic_param_score.param_pool.generator import generate_pool
from app.services.dynamic_param_score.param_pool.manifest import build_manifest, pool_checksum, read_manifest
from app.services.dynamic_param_score.param_pool.models import SelectionFeatures
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SQLITE_PATH,
    load_active_pool,
    load_templates_from_sqlite,
    query_candidates,
    write_jsonl,
    write_pool_sqlite,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "param_pool" / "v1"


def test_jsonl_and_sqlite_counts_match():
    if not DEFAULT_SQLITE_PATH.exists():
        return
    sqlite_templates = load_templates_from_sqlite(DEFAULT_SQLITE_PATH)
    jsonl_path = DATA_DIR / "param_pool_v1.jsonl"
    jsonl_count = sum(1 for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip())
    assert len(sqlite_templates) == jsonl_count


def test_manifest_checksum_valid():
    if not DEFAULT_MANIFEST_PATH.exists():
        return
    mf = read_manifest(DEFAULT_MANIFEST_PATH)
    templates = load_templates_from_sqlite(DEFAULT_SQLITE_PATH)
    assert mf.active_template_count == len(templates)
    assert mf.checksum == pool_checksum(templates)


def test_sqlite_indexes_exist():
    if not DEFAULT_SQLITE_PATH.exists():
        return
    conn = sqlite3.connect(str(DEFAULT_SQLITE_PATH))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in rows}
    assert "idx_templates_score" in names
    assert "idx_tags_type_value" in names


def test_query_candidates_fast_enough():
    if not DEFAULT_SQLITE_PATH.exists():
        return
    pool = load_active_pool(POOL_VERSION_ID, memory_index_mode=True)
    features = SelectionFeatures(
        param_score=61,
        regime="BALANCED_RANGE",
        risk_state="DEFENSIVE",
        budget_tier="SMALL",
        exposure_tier="TARGET_BASE",
        headroom_tier="NO_HEADROOM",
        fee_tier="FEE_BAD",
    )
    import time

    start = time.perf_counter()
    for _ in range(50):
        query_candidates(pool, features, mode="memory_index_mode")
    elapsed_ms = (time.perf_counter() - start) / 50 * 1000
    assert elapsed_ms < 500


def test_pool_version_loads_correctly(tmp_path):
    templates = generate_pool(200)
    sqlite_path = tmp_path / "pool.sqlite"
    manifest = build_manifest(templates, "test-v1")
    write_pool_sqlite(templates, sqlite_path, "test-v1", manifest=manifest)
    loaded = load_templates_from_sqlite(sqlite_path)
    assert len(loaded) == 200


def test_missing_pool_fails_safely(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        load_templates_from_sqlite(tmp_path / "missing.sqlite")
