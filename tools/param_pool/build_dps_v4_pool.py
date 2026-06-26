#!/usr/bin/env python3
"""Build DPS Engine V4 parameter library (300k profiles) — JSONL + SQLite + manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_generator.param_index_builder import (
    build_selection_index,
    build_v4_indexes,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
    POOL_TARGET_V4,
    POOL_VERSION_V4,
    build_dps_v4_pool,
)
from app.services.dynamic_param_score.param_pool.manifest import (
    build_manifest,
    pool_checksum,
    write_manifest,
    write_sha256_sidecar,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import write_jsonl, write_pool_sqlite
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DPS Engine V4 300k param library")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "param_pool" / "v4",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=POOL_TARGET_V4,
        help="Profile count (default 300000)",
    )
    args = parser.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    jsonl_path = out / "param_pool_v4.jsonl"
    sqlite_path = out / "param_pool_v4.sqlite"
    manifest_path = out / "param_pool_v4.manifest.json"
    index_path = out / "param_pool_v4.selection_index.json"

    print(f"Building DPS Engine V4 pool ({args.target} profiles)...")
    pool = build_dps_v4_pool(total_target=args.target)
    active = [t for t in pool if t.status == "active"]
    print(f"Built {len(pool)} templates ({len(active)} active)")

    ok, errors = validate_pool(active)
    if not ok:
        print(f"Validation issues: {len(errors)}", file=sys.stderr)
        for issue in errors[:15]:
            print(f"  - {issue}", file=sys.stderr)

    checksum = pool_checksum(active)
    manifest = build_manifest(
        active,
        POOL_VERSION_V4,
        schema_version="4.0",
        notes="DPS Engine V4 — 200k migrated v3 + 100k shelf-routed scenario profiles",
        base_pool_version="v3.0.0",
        added_template_count=100_000,
    )

    write_jsonl(active, jsonl_path)
    write_pool_sqlite(active, sqlite_path, pool_version=POOL_VERSION_V4)
    write_manifest(manifest_path, manifest)
    write_sha256_sidecar(manifest_path, checksum)
    from app.services.dynamic_param_score.param_pool.sqlite_store import pool_cache_path, write_pool_cache

    write_pool_cache(active, pool_cache_path(sqlite_path), checksum=checksum)

    profiles = [
        (t.params or {}).get("dps_profile", {})
        | {"profile_id": t.template_key, "template_key": t.template_key}
        for t in active
        if (t.params or {}).get("dps_profile")
    ]
    index = build_selection_index(profiles)
    v4_indexes = build_v4_indexes(profiles)
    index_path.write_text(
        json.dumps({"route_index": index, **v4_indexes}),
        encoding="utf-8",
    )

    route_keys = sum(1 for p in profiles if p.get("route_key"))
    ladders_ok = sum(
        1
        for p in profiles
        if p.get("buy_grid_ladder_pcts") and p.get("sell_grid_ladder_pcts")
    )
    print(f"JSONL: {jsonl_path}")
    print(f"SQLite: {sqlite_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Route keys: {route_keys}/{len(profiles)}")
    print(f"Ladder fields: {ladders_ok}/{len(profiles)}")
    print(f"Index keys: {len(index)}")
    print(f"Checksum: {checksum[:16]}...")

    return 0 if len(active) >= min(args.target, POOL_TARGET_V4) else 1


if __name__ == "__main__":
    raise SystemExit(main())
