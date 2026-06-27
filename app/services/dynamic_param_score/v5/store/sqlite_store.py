"""V5 SQLite store and seed."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
from app.services.dynamic_param_score.v5.domain.types import V5Shelf
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_shelf

POOL_VERSION_V5 = "v5.0.0"
DEFAULT_V5_DIR = Path("data/param_pool/v5")
DEFAULT_V5_SQLITE_PATH = DEFAULT_V5_DIR / "dynamic_param_v5.sqlite"
DEFAULT_V5_MANIFEST_PATH = DEFAULT_V5_DIR / "dynamic_param_v5_generation_manifest.json"
DEFAULT_V5_ROUTE_INDEX_PATH = DEFAULT_V5_DIR / "dynamic_param_v5_route_index.json"
GENERATED_SHELVES_PATH = Path("generated/dynamic_param_v5_shelves.json")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dynamic_param_v5_shelves (
    shelf_id TEXT PRIMARY KEY,
    route_key TEXT NOT NULL UNIQUE,
    asset_class TEXT NOT NULL,
    regime TEXT NOT NULL,
    direction TEXT NOT NULL,
    structure TEXT NOT NULL,
    volatility TEXT NOT NULL,
    risk_posture TEXT NOT NULL,
    liquidity_cost TEXT NOT NULL,
    scenario_title TEXT,
    scenario_description TEXT,
    base_template_json TEXT NOT NULL,
    resolver_policy_json TEXT NOT NULL,
    fallback_policy_json TEXT NOT NULL,
    validation_policy_json TEXT NOT NULL,
    generation_meta_json TEXT NOT NULL,
    source_logic_hash TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_v5_route_key ON dynamic_param_v5_shelves(route_key);
CREATE INDEX IF NOT EXISTS idx_v5_shelf_id ON dynamic_param_v5_shelves(shelf_id);

CREATE TABLE IF NOT EXISTS dynamic_param_v5_route_index (
    route_key TEXT PRIMARY KEY,
    shelf_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (shelf_id) REFERENCES dynamic_param_v5_shelves(shelf_id)
);

CREATE TABLE IF NOT EXISTS dynamic_param_v5_generation_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_version TEXT NOT NULL,
    total_shelves INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    random_used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dynamic_param_v5_validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shelf_id TEXT,
    route_key TEXT,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
"""


def init_v5_database(db_path: Path = DEFAULT_V5_SQLITE_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()


def shelf_to_row(shelf: V5Shelf) -> tuple:
    d = shelf.to_dict()
    rp = shelf.route_parts
    return (
        shelf.shelf_id,
        shelf.route_key,
        rp.asset,
        rp.regime,
        rp.direction,
        rp.structure,
        rp.volatility,
        rp.risk,
        rp.liquidity,
        shelf.scenario_title,
        shelf.scenario_description,
        json.dumps(d["base_template"], separators=(",", ":")),
        json.dumps(d["resolver_policy"], separators=(",", ":")),
        json.dumps(d["fallback_policy"], separators=(",", ":")),
        json.dumps(d["validation_policy"], separators=(",", ":")),
        json.dumps(d["generation_meta"], separators=(",", ":")),
        shelf.generation_meta.source_logic_hash,
    )


def seed_shelves_to_db(
    shelves: List[V5Shelf],
    db_path: Path = DEFAULT_V5_SQLITE_PATH,
    batch_size: int = 5000,
) -> int:
    init_v5_database(db_path)
    insert_sql = """
        INSERT OR REPLACE INTO dynamic_param_v5_shelves (
            shelf_id, route_key, asset_class, regime, direction, structure,
            volatility, risk_posture, liquidity_cost, scenario_title,
            scenario_description, base_template_json, resolver_policy_json,
            fallback_policy_json, validation_policy_json, generation_meta_json,
            source_logic_hash
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    index_sql = "INSERT OR REPLACE INTO dynamic_param_v5_route_index (route_key, shelf_id) VALUES (?,?)"
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM dynamic_param_v5_route_index")
        conn.execute("DELETE FROM dynamic_param_v5_shelves")
        for i in range(0, len(shelves), batch_size):
            batch = shelves[i : i + batch_size]
            conn.executemany(insert_sql, [shelf_to_row(s) for s in batch])
            conn.executemany(index_sql, [(s.route_key, s.shelf_id) for s in batch])
            conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM dynamic_param_v5_shelves").fetchone()[0]
    if count != EXPECTED_V5_SHELF_COUNT:
        raise ValueError(f"DB seed count mismatch: {count}")
    return count


def load_shelf_by_route_key(
    route_key: str,
    db_path: Path = DEFAULT_V5_SQLITE_PATH,
) -> Optional[Dict[str, Any]]:
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM dynamic_param_v5_shelves WHERE route_key = ?",
            (route_key,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def load_route_index_from_db(db_path: Path = DEFAULT_V5_SQLITE_PATH) -> Dict[str, str]:
    if not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT route_key, shelf_id FROM dynamic_param_v5_route_index"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def shelf_count_in_db(db_path: Path = DEFAULT_V5_SQLITE_PATH) -> int:
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM dynamic_param_v5_shelves").fetchone()[0]
