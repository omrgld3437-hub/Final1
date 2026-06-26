#!/usr/bin/env python3
"""Repair V4 param pool — schema backfill, ladders, fee, min-notional (batch SQLite update)."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import normalize_route_key
from app.services.dynamic_param_score.param_generator.library_repair_v4 import repair_v4_template
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_MANIFEST_PATH,
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
    load_templates_by_keys,
)


def _template_from_row(row: sqlite3.Row) -> ParamTemplate:
    meta = json.loads(row["metadata_json"] or "{}")
    params = json.loads(row["params_json"] or "{}")
    hard_limits = json.loads(row["hard_limits_json"] or "{}")
    return ParamTemplate(
        template_key=row["template_key"],
        version=row["pool_version"],
        profile_family=row["profile_family"],
        final_action=row["final_action"],
        score_min=int(row["score_min"]),
        score_max=int(row["score_max"]),
        priority=int(row["priority"]),
        status=row["status"],
        params=params,
        hard_limits=hard_limits,
        **{k: v for k, v in meta.items() if k in ParamTemplate.model_fields},
    )


def repair_sqlite_batch(
    sqlite_path: Path,
    *,
    batch_size: int = 2000,
    limit: int | None = None,
) -> dict:
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    stats = {"repaired": 0, "batches": 0, "errors": 0}
    try:
        keys = [
            str(r[0])
            for r in conn.execute(
                "SELECT template_key FROM param_templates WHERE status = 'active' ORDER BY id"
            ).fetchall()
        ]
        if limit:
            keys = keys[:limit]

        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i : i + batch_size]
            templates = load_templates_by_keys(sqlite_path, batch_keys)
            for tmpl in templates:
                try:
                    fixed = repair_v4_template(tmpl)
                    dps = (fixed.params or {}).get("dps_profile") or {}
                    conn.execute(
                        """
                        UPDATE param_templates
                        SET params_json = ?, final_action = ?, profile_family = ?
                        WHERE template_key = ?
                        """,
                        (
                            json.dumps(fixed.params, separators=(",", ":")),
                            fixed.final_action,
                            fixed.profile_family,
                            fixed.template_key,
                        ),
                    )
                    stats["repaired"] += 1
                except Exception:
                    stats["errors"] += 1
            conn.commit()
            stats["batches"] += 1
    finally:
        conn.close()
    stats["total_keys"] = len(keys) if limit is None else min(limit, len(keys))
    return stats


def rebuild_selection_index(sqlite_path: Path, index_path: Path) -> dict:
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    index: dict[str, list[str]] = defaultdict(list)
    count = 0
    try:
        for row in conn.execute(
            "SELECT template_key, params_json FROM param_templates WHERE status = 'active'"
        ):
            params = json.loads(row["params_json"] or "{}")
            dps = params.get("dps_profile") or {}
            rk = normalize_route_key(str(dps.get("route_key") or params.get("route_key") or ""))
            if not rk:
                continue
            index[rk].append(str(row["template_key"]))
            count += 1
    finally:
        conn.close()

    payload = {
        "version": "v4.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles_indexed": count,
        "routes": len(index),
        "index_by_route_key": dict(index),
    }
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"profiles_indexed": count, "routes": len(index), "path": str(index_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair V4 param pool SQLite + selection index")
    parser.add_argument("--sqlite", default=str(DEFAULT_V4_SQLITE_PATH))
    parser.add_argument("--index", default=str(DEFAULT_V4_SELECTION_INDEX_PATH))
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=0, help="Repair only first N templates (0=all)")
    parser.add_argument("--backup", action="store_true", help="Copy sqlite to .bak before repair")
    parser.add_argument("--rebuild-index", action="store_true", default=True)
    parser.add_argument("--no-rebuild-index", dest="rebuild_index", action="store_false")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"Missing sqlite: {sqlite_path}", file=sys.stderr)
        return 1

    if args.backup:
        bak = sqlite_path.with_suffix(sqlite_path.suffix + ".bak")
        shutil.copy2(sqlite_path, bak)
        print(f"Backup: {bak}")

    limit = args.limit if args.limit > 0 else None
    stats = repair_sqlite_batch(sqlite_path, batch_size=args.batch_size, limit=limit)
    print(json.dumps(stats, indent=2))

    if args.rebuild_index:
        idx_stats = rebuild_selection_index(sqlite_path, Path(args.index))
        print(json.dumps(idx_stats, indent=2))

    return 0 if stats.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
