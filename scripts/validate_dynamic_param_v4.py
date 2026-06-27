#!/usr/bin/env python3
"""Validate Dynamic Param V4 — runs acceptance suite + integrity checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.audit_v4.acceptance_v4 import (  # noqa: E402
    audit_crash_fallback_chain,
    audit_route_manifest,
    run_mandatory_acceptance_suite,
)
from app.services.dynamic_param_score.audit_v4.full_pool_audit import (  # noqa: E402
    build_fallback_map,
    build_route_coverage,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (  # noqa: E402
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)


def main() -> int:
    os.environ.setdefault("PARAM_POOL_VERSION", "v4.0.0")
    os.environ.setdefault("PARAM_POOL_LAZY_SHELF", "1")

    sqlite = Path(DEFAULT_V4_SQLITE_PATH)
    index = Path(DEFAULT_V4_SELECTION_INDEX_PATH)
    if not sqlite.exists() or not index.exists():
        print(json.dumps({"pass": False, "error": "v4_pool_missing"}))
        return 2

    manifest = audit_route_manifest()
    crash = audit_crash_fallback_chain()
    fallback = build_fallback_map()
    coverage = build_route_coverage(index, violations=[])
    suite = run_mandatory_acceptance_suite(
        profiles_path=str(sqlite),
        index_path=index,
        sample_size=1000,
        seed=20260626,
    )

    out = {
        "route_manifest": manifest,
        "crash_fallback": crash,
        "fallback_map": {
            "r8_pass": fallback.get("r8_crash_audit", {}).get("pass"),
            "r15_source_order": fallback.get("r15_source_order"),
            "unsafe_count": len(fallback.get("unsafe_fallbacks") or []),
        },
        "coverage": {
            "routes_with_profiles": coverage.get("routes_with_profiles"),
            "routes_empty": coverage.get("routes_empty"),
            "mandatory_empty": coverage.get("mandatory_empty"),
        },
        "acceptance_suite_pass": suite.get("pass"),
        "pass": (
            manifest.get("pass")
            and crash.get("pass")
            and suite.get("pass")
            and not coverage.get("mandatory_empty")
        ),
    }
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
