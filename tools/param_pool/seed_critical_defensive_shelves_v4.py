#!/usr/bin/env python3
"""Seed mandatory DEFENSIVE critical shelves in the V4 SQLite pool."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_generator.critical_shelf_seeder_v4 import (  # noqa: E402
    seed_critical_shelves_sqlite,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (  # noqa: E402
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed critical DEFENSIVE V4 shelves")
    parser.add_argument("--sqlite", default=str(DEFAULT_V4_SQLITE_PATH))
    parser.add_argument("--index", default=str(DEFAULT_V4_SELECTION_INDEX_PATH))
    parser.add_argument("--per-route", type=int, default=30)
    parser.add_argument("--min-critical", type=int, default=100)
    parser.add_argument(
        "--scope",
        choices=("mandatory", "extended", "all"),
        default="extended",
        help="mandatory=release gate only; extended=100-route coverage (warning on gaps)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail exit code when optional_route_empty_total > 0 (post-index manifest)",
    )
    parser.add_argument(
        "--export-gaps",
        default="",
        help="Directory for extended coverage gap JSON/CSV export",
    )
    parser.add_argument(
        "--gaps-only",
        action="store_true",
        help="Seed only extended manifest routes below min profile count",
    )
    parser.add_argument(
        "--no-clone",
        action="store_true",
        help="Legacy in-place convert (mandatory scope always uses this)",
    )
    args = parser.parse_args()

    export_dir = Path(args.export_gaps) if args.export_gaps else None

    stats = seed_critical_shelves_sqlite(
        Path(args.sqlite),
        Path(args.index),
        per_route=args.per_route,
        min_critical=args.min_critical,
        scope=args.scope,
        export_gaps_dir=export_dir,
        gaps_only=args.gaps_only,
        clone_mode=not args.no_clone,
    )
    if not stats.get("pass"):
        stats["exit_code"] = 1
    elif args.strict and not stats.get("extended_pass"):
        stats["exit_code"] = 1
    else:
        stats["exit_code"] = 0
    print(json.dumps(stats, indent=2))
    return int(stats["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
