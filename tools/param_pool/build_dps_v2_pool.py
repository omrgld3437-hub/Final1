#!/usr/bin/env python3
"""Build DPS Engine V2 parameter library (200k profiles) — JSONL + SQLite + manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_generator.param_library_builder import (
    POOL_TARGET_V3,
    POOL_VERSION_V3,
    build_dps_v2_pool,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import build_selection_index
from app.services.dynamic_param_score.param_pool.manifest import (
    build_manifest,
    pool_checksum,
    write_manifest,
    write_sha256_sidecar,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import write_jsonl, write_pool_sqlite
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DPS Engine V2 200k param library")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "param_pool" / "v3",
    )
    args = parser.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    jsonl_path = out / "param_pool_v3.jsonl"
    sqlite_path = out / "param_pool_v3.sqlite"
    manifest_path = out / "param_pool_v3.manifest.json"
    index_path = out / "param_pool_v3.selection_index.json"

    print(f"Building DPS Engine V2 pool ({POOL_TARGET_V3} profiles)...")
    pool = build_dps_v2_pool()
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
        POOL_VERSION_V3,
        schema_version="2.0",
        notes="DPS Engine V2 — migrated 100k + coverage-gap 100k, ACTIVE_DEFENSIVE philosophy",
        base_pool_version="v2.0.0",
        added_template_count=100_000,
    )

    write_jsonl(active, jsonl_path)
    write_pool_sqlite(active, sqlite_path, pool_version=POOL_VERSION_V3)
    write_manifest(manifest_path, manifest)
    write_sha256_sidecar(jsonl_path)

    profiles = [
        (t.params or {}).get("dps_profile", {})
        | {"profile_id": t.template_key, "template_key": t.template_key}
        for t in active
        if (t.params or {}).get("dps_profile")
    ]
    index = build_selection_index(profiles)
    index_path.write_text(json.dumps(index), encoding="utf-8")

    print(f"JSONL: {jsonl_path}")
    print(f"SQLite: {sqlite_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Index keys: {len(index)}")
    print(f"Checksum: {checksum[:16]}...")

    return 0 if len(active) == POOL_TARGET_V3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
