#!/usr/bin/env python3
"""Generate route coverage CSV from selection index."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.audit_v4.full_pool_audit import build_route_coverage  # noqa: E402
from app.services.dynamic_param_score.param_pool.sqlite_store import DEFAULT_V4_SELECTION_INDEX_PATH  # noqa: E402


def main() -> int:
    cov = build_route_coverage(DEFAULT_V4_SELECTION_INDEX_PATH, violations=[])
    rows = cov.get("rows") or []
    out = ROOT / "reports" / "param_pool_route_coverage.csv"
    out.parent.mkdir(exist_ok=True)
    if rows:
        with out.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
