#!/usr/bin/env python3
"""Simulate all 2,295 DPLV6 profiles — static validation + synthetic path dry-run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.dynamic_param_v6.v6_simulation_common import (  # noqa: E402
    EXPECTED_PROFILE_COUNT,
    REPORT_DIR,
    aggregate_findings,
    assert_catalog_count,
    ensure_report_dir,
    load_catalog_profiles,
    merge_report_summary,
    path_results_to_rows,
    render_logic_errors_report,
    run_path_simulation_all,
    run_static_validation_all,
    static_results_to_rows,
    utc_now_iso,
    write_csv,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="V6 full catalog static + path simulation")
    parser.add_argument("--skip-path", action="store_true", help="Only run static validation")
    parser.add_argument("--path-sample", type=int, default=0, help="Limit profiles for path sim (0=all)")
    args = parser.parse_args()

    ensure_report_dir()
    profiles = load_catalog_profiles()
    assert_catalog_count(profiles)
    print(f"Loaded {len(profiles)} profiles (expected {EXPECTED_PROFILE_COUNT})")

    static_results, static_counter = run_static_validation_all(profiles)
    static_errors = sum(1 for r in static_results if not r.ok)
    print(f"Static validation: {static_errors} profiles with errors")

    static_json = {
        "generated_at": utc_now_iso(),
        "profile_count": len(profiles),
        "profiles_with_errors": static_errors,
        "error_histogram": dict(static_counter),
        "results": static_results_to_rows(static_results),
    }
    write_json(REPORT_DIR / "all_profiles_static_validation.json", static_json)
    write_csv(
        REPORT_DIR / "all_profiles_static_validation.csv",
        static_results_to_rows(static_results),
        [
            "profile_id",
            "regime_id",
            "behavior_id",
            "severity",
            "base_pct",
            "quote_pct",
            "error_count",
            "warning_count",
            "errors",
            "warnings",
            "ok",
        ],
    )

    path_results = []
    path_counter = {}
    if not args.skip_path:
        path_profiles = profiles
        if args.path_sample > 0:
            path_profiles = profiles[: args.path_sample]
            print(f"Path simulation sample: {len(path_profiles)} profiles")
        path_results, path_counter = run_path_simulation_all(path_profiles)
        path_errors = sum(1 for r in path_results if not r.ok)
        print(f"Path simulation: {len(path_results)} runs, {path_errors} with errors")

        path_rows = path_results_to_rows(path_results)
        write_json(
            REPORT_DIR / "all_profiles_path_simulation.json",
            {
                "generated_at": utc_now_iso(),
                "runs": len(path_results),
                "runs_with_errors": path_errors,
                "error_histogram": dict(path_counter),
                "results": path_rows,
            },
        )
        fieldnames = list(path_rows[0].keys()) if path_rows else ["profile_id"]
        write_csv(REPORT_DIR / "all_profiles_path_simulation.csv", path_rows, fieldnames)

    agg = aggregate_findings(static_results, path_results)
    agg = merge_report_summary(agg, static_results=static_results, path_results=path_results)
    write_json(REPORT_DIR / "critical_findings.json", agg)
    report_md = render_logic_errors_report(
        agg,
        static_results=static_results,
        path_results=path_results,
    )
    (REPORT_DIR / "logic_errors_report.md").write_text(report_md, encoding="utf-8")

    static_fail = static_errors > 0
    path_error_runs = sum(1 for r in path_results if not r.ok) if path_results else 0
    if static_fail:
        print("FAIL: static catalog invariant errors", file=sys.stderr)
        return 1
    if path_error_runs:
        print(f"NOTE: {path_error_runs} path simulation runs flagged ERROR_* (see reports)")
    print(f"Reports written to {REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
