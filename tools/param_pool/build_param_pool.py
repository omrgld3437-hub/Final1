"""Param pool build CLI — generate JSONL + SQLite + manifest + checksum."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.defaults import (
    POOL_VERSION_ID,
    POOL_VERSION_V2,
    POOL_VERSION_V3,
    POOL_VERSION_V4,
)
from app.services.dynamic_param_score.param_pool.generator import generate_pool
from app.services.dynamic_param_score.param_pool.manifest import (
    build_manifest,
    pool_checksum,
    write_manifest,
    write_sha256_sidecar,
)
from app.services.dynamic_param_score.param_pool.precision_generator import (
    POOL_TARGET_V2,
    generate_pool_v2,
    load_templates_from_jsonl,
)
from app.services.dynamic_param_score.param_generator.param_library_builder import (
    POOL_TARGET_V3,
    build_dps_v2_pool,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
    POOL_TARGET_V4,
    build_dps_v4_pool,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import write_jsonl, write_pool_sqlite
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Build param template pool artifacts")
    parser.add_argument("--version", default=POOL_VERSION_ID, help="Pool version id")
    parser.add_argument("--target-count", type=int, default=50_000)
    parser.add_argument(
        "--base-pool",
        default=None,
        help="Base pool JSONL for v2 precision expansion (default: generate v1 programmatically)",
    )
    parser.add_argument(
        "--expansion-mode",
        default=None,
        choices=["precision_50k", "none"],
        help="v2 expansion mode (precision_50k adds 50k scenario-specific templates)",
    )
    parser.add_argument(
        "--output-jsonl",
        default=None,
    )
    parser.add_argument(
        "--output-sqlite",
        default=None,
    )
    parser.add_argument(
        "--manifest",
        default=None,
    )
    args = parser.parse_args()

    is_v4 = args.version == POOL_VERSION_V4
    is_v3 = args.version == POOL_VERSION_V3
    is_v2 = args.version == POOL_VERSION_V2 or args.expansion_mode == "precision_50k"
    if args.target_count == 50_000 and is_v2:
        args.target_count = POOL_TARGET_V2
    if is_v3 and args.target_count == 50_000:
        args.target_count = POOL_TARGET_V3
    if is_v4 and args.target_count == 50_000:
        args.target_count = POOL_TARGET_V4

    if args.output_jsonl is None:
        ver_dir = "v4" if is_v4 else ("v3" if is_v3 else ("v2" if is_v2 else "v1"))
        ver_file = ver_dir
        args.output_jsonl = str(ROOT / "data" / "param_pool" / ver_dir / f"param_pool_{ver_file}.jsonl")
    if args.output_sqlite is None:
        ver_dir = "v4" if is_v4 else ("v3" if is_v3 else ("v2" if is_v2 else "v1"))
        ver_file = ver_dir
        args.output_sqlite = str(ROOT / "data" / "param_pool" / ver_dir / f"param_pool_{ver_file}.sqlite")
    if args.manifest is None:
        ver_dir = "v4" if is_v4 else ("v3" if is_v3 else ("v2" if is_v2 else "v1"))
        ver_file = ver_dir
        args.manifest = str(ROOT / "data" / "param_pool" / ver_dir / f"param_pool_{ver_file}.manifest.json")

    if is_v4:
        templates = build_dps_v4_pool(total_target=args.target_count)
        manifest_notes = (
            "DPS Engine V4 — 300k shelf-routed profiles, route_key index, "
            "directional scenario separation"
        )
        schema_version = "4.0"
        base_ver = POOL_VERSION_V3
        added = 100_000
    elif is_v3:
        templates = build_dps_v2_pool()
        manifest_notes = (
            "DPS Engine V2 — 200k profiles, migrated legacy + coverage-gap expansion, "
            "ACTIVE_DEFENSIVE_GRID philosophy"
        )
        schema_version = "2.0"
        base_ver = POOL_VERSION_V2
        added = 100_000
    elif is_v2:
        base_path = Path(args.base_pool) if args.base_pool else None
        base_templates = load_templates_from_jsonl(base_path) if base_path and base_path.exists() else None
        templates = generate_pool_v2(
            args.target_count,
            base_templates=base_templates,
            base_pool_path=base_path,
            expansion_mode=args.expansion_mode or "precision_50k",
        )
        manifest_notes = (
            "50k precision expansion: trend, rebalance, initial-entry, orderbook, "
            "small-budget, recovery, high-confidence active"
        )
        schema_version = "1.1"
        base_ver = "v1.0.0"
        added = max(args.target_count - 50_000, 0)
    else:
        templates = generate_pool(args.target_count)
        manifest_notes = f"Built with target_count={args.target_count}"
        schema_version = "1.0"
        base_ver = None
        added = None

    active = [t for t in templates if t.status == "active"]

    if len(active) < args.target_count:
        print(f"FAIL: active template count {len(active)} < target {args.target_count}", file=sys.stderr)
        return 1

    ok, errors = validate_pool(active)
    if not ok:
        print("FAIL: validator errors:", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    manifest = build_manifest(
        active,
        args.version,
        schema_version=schema_version,
        notes=manifest_notes,
        base_pool_version=base_ver,
        added_template_count=added,
    )
    checksum = pool_checksum(active)
    if not checksum:
        print("FAIL: checksum empty", file=sys.stderr)
        return 1

    jsonl_path = Path(args.output_jsonl)
    sqlite_path = Path(args.output_sqlite)
    manifest_path = Path(args.manifest)

    write_jsonl(active, jsonl_path)
    write_pool_sqlite(active, sqlite_path, args.version, manifest=manifest)
    from app.services.dynamic_param_score.param_pool.sqlite_store import pool_cache_path, write_pool_cache

    write_pool_cache(active, pool_cache_path(sqlite_path), checksum=checksum)
    write_manifest(manifest_path, manifest)
    sha_path = jsonl_path.parent / jsonl_path.name.replace(".jsonl", ".sha256")
    sha_path.write_text(checksum + "\n", encoding="utf-8")

    print(f"OK: {len(active)} active templates")
    print(f"  jsonl:    {jsonl_path}")
    print(f"  sqlite:   {sqlite_path}")
    print(f"  manifest: {manifest_path}")
    print(f"  checksum: {checksum[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
