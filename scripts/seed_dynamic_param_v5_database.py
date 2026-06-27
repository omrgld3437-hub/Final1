#!/usr/bin/env python3
"""Seed V5 shelves into SQLite database."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.store.sqlite_store import (
    DEFAULT_V5_MANIFEST_PATH,
    DEFAULT_V5_SQLITE_PATH,
    seed_shelves_to_db,
    shelf_count_in_db,
)


def main() -> None:
    t0 = time.perf_counter()
    shelves_path = ROOT / "generated/dynamic_param_v5_shelves.json"
    if shelves_path.exists():
        print("Loading shelves from generated JSON...")
        raw = json.loads(shelves_path.read_text(encoding="utf-8"))
        from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
        from app.services.dynamic_param_score.v5.domain.types import (
            V5BaseTemplate,
            V5FallbackPolicy,
            V5GenerationMeta,
            V5ResolverPolicy,
            V5Shelf,
        )

        shelves = []
        for d in raw:
            rp = V5RouteParts.from_dict(d["route_parts"])
            bt = d["base_template"]
            base = V5BaseTemplate(**bt)
            shelves.append(
                V5Shelf(
                    version="DPLV5",
                    shelf_id=d["shelf_id"],
                    route_key=d["route_key"],
                    route_parts=rp,
                    scenario_title=d["scenario_title"],
                    scenario_description=d["scenario_description"],
                    base_template=base,
                    resolver_policy=V5ResolverPolicy(**d["resolver_policy"]),
                    fallback_policy=V5FallbackPolicy(**d["fallback_policy"]),
                    validation_policy=d["validation_policy"],
                    generation_meta=V5GenerationMeta(**d["generation_meta"]),
                )
            )
    else:
        print("Generating shelves...")
        shelves = generate_all_v5_shelves()

    count = seed_shelves_to_db(shelves, DEFAULT_V5_SQLITE_PATH)
    sec = time.perf_counter() - t0
    db_count = shelf_count_in_db(DEFAULT_V5_SQLITE_PATH)
    report = {
        "seeded": count,
        "dbCount": db_count,
        "expected": EXPECTED_V5_SHELF_COUNT,
        "sqlitePath": str(DEFAULT_V5_SQLITE_PATH),
        "seconds": round(sec, 2),
        "pass": db_count == EXPECTED_V5_SHELF_COUNT,
    }
    out = ROOT / "reports/dynamic_param_v5_database_seed_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# V5 Database Seed Report\n\n"
        f"- Seeded: {count}\n"
        f"- DB count: {db_count}\n"
        f"- Expected: {EXPECTED_V5_SHELF_COUNT}\n"
        f"- Path: {DEFAULT_V5_SQLITE_PATH}\n"
        f"- Duration: {sec:.2f}s\n"
        f"- PASS: {report['pass']}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
