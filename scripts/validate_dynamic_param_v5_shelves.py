#!/usr/bin/env python3
"""Validate V5 shelf library."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index, lookup_exact_v5_shelf
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf


def main() -> None:
    shelves = generate_all_v5_shelves()
    assert len(shelves) == EXPECTED_V5_SHELF_COUNT

    blockers = critical = major = minor = 0
    invalid = []
    for shelf in shelves:
        r = validate_shelf(shelf)
        if not r.ok:
            invalid.append(shelf.shelf_id)
            for v in r.violations:
                if v.severity == "BLOCKER":
                    blockers += 1
                elif v.severity == "CRITICAL":
                    critical += 1
                elif v.severity == "MAJOR":
                    major += 1
                else:
                    minor += 1

    index = build_v5_route_index(shelves)
    misses = 0
    for shelf in shelves:
        try:
            lookup_exact_v5_shelf(index, shelf.route_key)
        except KeyError:
            misses += 1

    report = {
        "totalShelves": len(shelves),
        "invalidCount": len(invalid),
        "exactLookupMissCount": misses,
        "blockerCount": blockers,
        "criticalCount": critical,
        "majorCount": major,
        "minorCount": minor,
        "pass": len(invalid) == 0 and misses == 0 and blockers == 0 and critical == 0,
    }
    out = ROOT / "reports/dynamic_param_v5_validation_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
