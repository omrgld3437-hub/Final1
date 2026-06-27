"""DB vs generated JSON consistency audit."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import List

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.store.sqlite_store import DEFAULT_V5_SQLITE_PATH

GENERATED_PATH = Path("generated/dynamic_param_v5_shelves.json")


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_db_json_consistency() -> dict:
    json_path = GENERATED_PATH
    db_path = DEFAULT_V5_SQLITE_PATH
    if not json_path.exists():
        return {"pass_audit": False, "error": "generated JSON missing"}
    if not db_path.exists():
        return {"pass_audit": False, "error": "SQLite DB missing"}

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    json_routes = {item["route_key"]: item for item in raw}
    json_ids = {item["shelf_id"] for item in raw}

    with sqlite3.connect(db_path) as conn:
        db_rows = conn.execute(
            "SELECT shelf_id, route_key, source_logic_hash FROM dynamic_param_v5_shelves"
        ).fetchall()
        db_count = conn.execute("SELECT COUNT(*) FROM dynamic_param_v5_shelves").fetchone()[0]
        index_count = conn.execute("SELECT COUNT(*) FROM dynamic_param_v5_route_index").fetchone()[0]

    db_routes = {r[1]: r[0] for r in db_rows}
    db_ids = {r[0] for r in db_rows}
    hash_mismatches: List[str] = []
    missing_in_db: List[str] = []
    missing_in_json: List[str] = []

    for rk, item in json_routes.items():
        if rk not in db_routes:
            missing_in_db.append(rk)
            continue
        db_hash = next(r[2] for r in db_rows if r[1] == rk)
        jhash = item.get("generation_meta", {}).get("source_logic_hash", "")
        if db_hash != jhash:
            hash_mismatches.append(rk)

    for rk in db_routes:
        if rk not in json_routes:
            missing_in_json.append(rk)

    pass_audit = (
        len(json_routes) == EXPECTED_V5_SHELF_COUNT
        and db_count == EXPECTED_V5_SHELF_COUNT
        and index_count == EXPECTED_V5_SHELF_COUNT
        and len(json_ids) == EXPECTED_V5_SHELF_COUNT
        and len(db_ids) == EXPECTED_V5_SHELF_COUNT
        and not missing_in_db
        and not missing_in_json
        and not hash_mismatches
    )

    return {
        "json_shelf_count": len(json_routes),
        "db_shelf_count": db_count,
        "db_index_count": index_count,
        "expected": EXPECTED_V5_SHELF_COUNT,
        "missing_in_db_count": len(missing_in_db),
        "missing_in_json_count": len(missing_in_json),
        "hash_mismatch_count": len(hash_mismatches),
        "hash_mismatch_samples": hash_mismatches[:20],
        "json_file_sha256": _hash_file(json_path),
        "pass_audit": pass_audit,
    }
