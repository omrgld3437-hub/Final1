#!/usr/bin/env python3
"""Generate all 192,780 V5 exact shelves."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import (
    FORMULA_VERSION,
    generate_all_v5_shelves,
)
from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def main() -> None:
    t0 = time.perf_counter()
    print(f"Generating {EXPECTED_V5_SHELF_COUNT} V5 shelves...")
    shelves = generate_all_v5_shelves()
    gen_sec = time.perf_counter() - t0
    print(f"Generated {len(shelves)} shelves in {gen_sec:.2f}s")

    invalid = []
    for shelf in shelves:
        result = validate_shelf(shelf)
        if not result.ok:
            invalid.append({"shelf_id": shelf.shelf_id, "violations": [v.__dict__ for v in result.violations]})

    if invalid:
        write_json(ROOT / "reports/dynamic_param_v5_invalid_shelves.json", invalid)
        raise SystemExit(f"Invalid V5 shelves: {len(invalid)}")

    index = build_v5_route_index(shelves)
    out_dir = ROOT / "generated"
    write_json(out_dir / "dynamic_param_v5_shelves.json", [s.to_dict() for s in shelves])
    write_json(out_dir / "dynamic_param_v5_route_index.json", sorted(index.keys()))
    manifest = {
        "version": "DPLV5",
        "totalShelves": len(shelves),
        "expectedShelves": EXPECTED_V5_SHELF_COUNT,
        "routeIndexSize": len(index),
        "randomUsed": False,
        "formulaVersion": FORMULA_VERSION,
        "generatedAt": shelves[0].generation_meta.generated_at,
        "invalidCount": 0,
        "duplicateRouteCount": 0,
        "duplicateShelfIdCount": 0,
        "generationSeconds": round(gen_sec, 3),
    }
    write_json(out_dir / "dynamic_param_v5_generation_manifest.json", manifest)
    write_json(ROOT / "reports/dynamic_param_v5_generation_manifest.json", manifest)
    print(f"Wrote generated/*.json — {len(shelves)} shelves, index {len(index)}")


if __name__ == "__main__":
    main()
