"""Critical shelf seeder — clone mode fills gaps without moving source profiles."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services.dynamic_param_score.param_generator.critical_shelf_seeder_v4 import (
    _clone_template_for_target,
    _find_source_keys,
    seed_critical_shelves_in_templates,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    _SCHEMA_SQL,
    insert_param_templates,
    load_templates_by_keys,
)


def _minimal_template(key: str, route_key: str) -> ParamTemplate:
    parts = route_key.split("|")
    params = {
        "route_key": route_key,
        "buy_grid_count": 3,
        "sell_grid_count": 2,
        "dps_profile": {
            "route_key": route_key,
            "profile_id": key,
            "asset_code": parts[0],
            "regime_code": parts[1],
            "structure_code": parts[2],
            "vol_code": parts[3],
            "risk_class": parts[4],
            "base_alloc_frac": 0.35,
            "quote_alloc_frac": 0.65,
            "buy_distribution": [12, 28, 60],
            "sell_distribution": [35, 65],
            "buy_grid_ladder_pcts": [3.0, 7.0, 14.0],
            "sell_grid_ladder_pcts": [2.0, 5.0],
            "buy_grid_count": 3,
            "sell_grid_count": 2,
        },
    }
    return ParamTemplate(
        template_key=key,
        version="v4.0.0",
        profile_family="DEFENSIVE_GRID_PROFILE",
        final_action="ACTIVE_DEFENSIVE_GRID",
        supported_regimes=["TRENDING_DOWN"],
        allowed_risk_states=["DEFENSIVE"],
        budget_tiers=["100_250"],
        exposure_tiers=["EXPOSURE_OK"],
        headroom_tiers=["HEADROOM_OK"],
        fee_tiers=["FEE_OK"],
        min_equity_usdt=50.0,
        min_notional_multiple=1.0,
        score_min=20,
        score_max=60,
        params=params,
        priority=50,
        status="active",
    )


def _write_fixture_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    src_route = "A1|R7|S8|V2|DEFENSIVE"
    templates = [
        _minimal_template(f"DPLV4_A1_R7_S8_V2_DEFENSIVE_{i:06d}", src_route)
        for i in range(1, 6)
    ]
    insert_param_templates(path, templates)


def test_find_source_keys_never_returns_r2_route():
    by_route = {
        "A1|R2|S8|V2|DEFENSIVE": ["bad_key"],
        "A1|R7|S8|V2|DEFENSIVE": ["good_key"],
    }
    keys, method = _find_source_keys("A1|R7|S8|V1|DEFENSIVE", by_route)
    assert keys == ["good_key"]
    assert "|R2|" not in method


def test_clone_template_keeps_source_key_and_new_route():
    src_route = "A1|R7|S8|V2|DEFENSIVE"
    target = "A1|R7|S8|V1|DEFENSIVE"
    src = _minimal_template("DPLV4_A1_R7_S8_V2_DEFENSIVE_000001", src_route)
    reserved: set[str] = {src.template_key}
    cloned = _clone_template_for_target(
        src,
        target,
        "derived:A1|R7|S8|V2|DEFENSIVE",
        seq=910001,
        reserved_keys=reserved,
    )
    assert cloned.template_key != src.template_key
    assert cloned.template_key.startswith("DPLV4_A1_R7_S8_V1_DEFENSIVE_")
    assert cloned.params["route_key"] == target
    assert cloned.params["dps_profile"]["cloned_from_template_key"] == src.template_key
    assert "|R2|" not in cloned.params["dps_profile"].get("seed_derivation", "")


def test_seed_clone_fills_empty_shelf(tmp_path: Path):
    db = tmp_path / "pool.sqlite"
    _write_fixture_sqlite(db)
    target = "A1|R7|S8|V1|DEFENSIVE"
    by_route = {
        "A1|R7|S8|V2|DEFENSIVE": [f"DPLV4_A1_R7_S8_V2_DEFENSIVE_{i:06d}" for i in range(1, 6)]
    }
    inserted, stats = seed_critical_shelves_in_templates(
        by_route,
        lambda keys: load_templates_by_keys(db, keys),
        per_route=9,
        critical_routes=[target],
        sqlite_path=db,
        clone_mode=True,
    )
    assert len(inserted) == 3
    assert stats["profiles_cloned"] == 3
    n = insert_param_templates(db, inserted)
    assert n == 3
    conn = sqlite3.connect(str(db))
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM param_templates WHERE json_extract(params_json, '$.route_key') = ?",
            (target,),
        ).fetchone()[0]
        assert cnt == 3
        src_cnt = conn.execute(
            "SELECT COUNT(*) FROM param_templates WHERE json_extract(params_json, '$.route_key') = ?",
            ("A1|R7|S8|V2|DEFENSIVE",),
        ).fetchone()[0]
        assert src_cnt == 5
    finally:
        conn.close()
