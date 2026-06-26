"""Repair param pool SQLite/JSONL artifacts — normalize WAIT/NO_TRADE + SELL_MANAGEMENT metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_ID
from app.services.dynamic_param_score.param_pool.manifest import (
    build_manifest,
    pool_checksum,
    write_manifest,
    write_sha256_sidecar,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SQLITE_PATH,
    write_jsonl,
    write_pool_sqlite,
)
from app.services.dynamic_param_score.param_pool.validators import validate_pool
from app.services.dynamic_param_score.param_pool.versioning import (
    clear_pool_cache,
    load_version_templates,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair param pool artifacts in-place")
    parser.add_argument("--version", default=POOL_VERSION_ID)
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--jsonl", default=str(DEFAULT_SQLITE_PATH.parent / "param_pool_v1.jsonl"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    args = parser.parse_args()

    clear_pool_cache()
    templates = load_version_templates(args.version)
    active = [t for t in templates if t.status == "active"]
    ok, errors = validate_pool(active)
    if not ok:
        print("FAIL: validator errors:", file=sys.stderr)
        for e in errors[:25]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    manifest = build_manifest(active, args.version, notes="Repaired metadata normalization")
    checksum = pool_checksum(active)
    sqlite_path = Path(args.sqlite)
    jsonl_path = Path(args.jsonl)
    manifest_path = Path(args.manifest)

    write_jsonl(active, jsonl_path)
    write_pool_sqlite(active, sqlite_path, args.version, manifest=manifest)
    write_manifest(manifest_path, manifest)
    write_sha256_sidecar(manifest_path, checksum)
    clear_pool_cache()

    print(f"OK: repaired {len(active)} active templates")
    print(f"  sqlite:   {sqlite_path}")
    print(f"  jsonl:    {jsonl_path}")
    print(f"  manifest: {manifest_path}")
    print(f"  checksum: {checksum[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
