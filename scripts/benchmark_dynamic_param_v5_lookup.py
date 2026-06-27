#!/usr/bin/env python3
"""Benchmark V5 route lookup performance."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index, lookup_exact_v5_shelf


def main() -> None:
    shelves = generate_all_v5_shelves()
    index = build_v5_route_index(shelves)
    times = []
    misses = 0
    t0 = time.perf_counter()
    for shelf in shelves:
        t1 = time.perf_counter()
        try:
            lookup_exact_v5_shelf(index, shelf.route_key)
        except KeyError:
            misses += 1
        times.append((time.perf_counter() - t1) * 1e6)
    total_sec = time.perf_counter() - t0
    times.sort()
    n = len(times)
    report = {
        "totalLookups": n,
        "missCount": misses,
        "totalSeconds": round(total_sec, 3),
        "meanUs": round(statistics.mean(times), 4),
        "p50Us": round(times[n // 2], 4),
        "p95Us": round(times[int(n * 0.95)], 4),
        "p99Us": round(times[int(n * 0.99)], 4),
        "maxUs": round(max(times), 4),
        "expectedShelves": EXPECTED_V5_SHELF_COUNT,
    }
    out = ROOT / "reports/dynamic_param_v5_lookup_benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
