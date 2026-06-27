#!/usr/bin/env python3
"""Fast index-only resolver coverage for all 10,710 V4 routes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.audit_v4.full_pool_audit import (  # noqa: E402
    fast_resolver_coverage_index,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (  # noqa: E402
    DEFAULT_V4_SELECTION_INDEX_PATH,
)


def main() -> int:
    out = fast_resolver_coverage_index(DEFAULT_V4_SELECTION_INDEX_PATH)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / "param_pool_resolver_simulation.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
