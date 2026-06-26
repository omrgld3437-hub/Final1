#!/usr/bin/env python3
"""Manually prune dynamic param score decision logs on disk."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.log_retention import (
    directory_size_bytes,
    log_dir_path,
    prune_log_directory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune DPS decision JSON logs")
    parser.add_argument("--max-mb", type=float, default=1024, help="Trigger cap (default 1024 = 1GB)")
    parser.add_argument("--target-mb", type=float, default=100, help="Target size after prune")
    parser.add_argument("--force", action="store_true", help="Prune even if below max cap")
    args = parser.parse_args()

    log_dir = log_dir_path(ROOT)
    before = directory_size_bytes(log_dir)
    print(f"Log dir: {log_dir}")
    print(f"Before: {before / (1024*1024):.1f} MB")

    if args.force:
        result = prune_log_directory(
            log_dir,
            max_bytes=0,
            target_bytes=int(args.target_mb * 1024 * 1024),
        )
    else:
        result = prune_log_directory(
            log_dir,
            max_bytes=int(args.max_mb * 1024 * 1024),
            target_bytes=int(args.target_mb * 1024 * 1024),
        )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
