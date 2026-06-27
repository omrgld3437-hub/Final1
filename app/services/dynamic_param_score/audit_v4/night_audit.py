#!/usr/bin/env python3
"""Night audit orchestrator — baseline, full scan, simulation, reports."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.audit_v4.full_pool_audit import (  # noqa: E402
    AUDITED_FILES,
    SEVERITY_BLOCKER,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    Violation,
    analyze_duplicates,
    build_fallback_map,
    build_route_coverage,
    fast_resolver_coverage_index,
    generate_markdown_report,
    iter_sqlite_profiles,
    run_full_pool_audit,
    write_audit_artifacts,
)
from app.services.dynamic_param_score.audit_v4.normalized_profile import (  # noqa: E402
    AuditViolation,
    normalize_template,
    profile_id_route_mismatch,
)
from app.services.dynamic_param_score.audit_v4.auditor import (  # noqa: E402
    _profile_dict,
    audit_capacity,
    audit_exposure,
    audit_profile_distribution,
    audit_trailing,
    prepare_v4_lazy_pool_for_selection,
)
from app.services.dynamic_param_score.audit_v4.acceptance_v4 import behavior_fingerprint
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import normalize_route_key
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    ROUTE_MANIFEST_TOTAL,
    enumerate_shelf_routes,
)
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_MANIFEST_PATH,
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)
from app.services.dynamic_param_score.param_pool.manifest import read_manifest


@dataclass
class NightAuditState:
    git_commit: str = ""
    git_branch: str = ""
    started_at: str = ""
    baseline: Dict[str, Any] = field(default_factory=dict)
    final: Dict[str, Any] = field(default_factory=dict)
    fixes_applied: List[str] = field(default_factory=list)
    test_results: List[Dict[str, Any]] = field(default_factory=list)


def _git_info() -> Tuple[str, str]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True
        ).strip()
        return commit, branch
    except Exception:
        return "unknown", "unknown"


def run_baseline_audit(
    sqlite_path: Path,
    index_path: Path,
    *,
    sample_size: int = 8000,
) -> Dict[str, Any]:
    """Read-only baseline — index coverage + stratified sample, no code changes."""
    t0 = time.time()
    violations: List[Violation] = []
    coverage = build_route_coverage(index_path, violations=violations)
    fallback = build_fallback_map()

    manifest_count = 300_000
    if DEFAULT_V4_MANIFEST_PATH.exists():
        try:
            manifest_count = int(read_manifest(DEFAULT_V4_MANIFEST_PATH).template_count or 300_000)
        except Exception:
            pass

    sample_stats: Dict[str, int] = Counter()
    fp_map: Dict[str, List[str]] = defaultdict(list)
    trailing_v: List[Dict] = []
    exposure_v: List[Dict] = []
    base_quote_v: List[Dict] = []
    invalid: List[Dict] = []
    seen_ids: set = set()
    n = 0

    for batch in iter_sqlite_profiles(sqlite_path, batch_size=3000):
        for tmpl in batch:
            n += 1
            pid = tmpl.template_key
            if pid in seen_ids:
                sample_stats["duplicate_id"] += 1
            seen_ids.add(pid)

            rec = normalize_template(tmpl)
            p = _profile_dict(tmpl)
            rk = rec.route_key
            fp = behavior_fingerprint(p)
            fp_map[fp].append(pid)

            mismatch = profile_id_route_mismatch(rec)
            if mismatch:
                sample_stats["profile_id_mismatch"] += 1

            for side in ("buy", "sell"):
                dist = p.get(f"{side}_distribution") or []
                if len(dist) == 2 and abs(dist[0] - dist[1]) < 3:
                    regime = rec.regime_key
                    if regime in ("R6", "R7", "R8", "R12"):
                        sample_stats["fifty_fifty_asymmetric"] += 1
                    else:
                        sample_stats["fifty_fifty_justified_candidate"] += 1

            trail_fails = audit_trailing(p)
            if trail_fails:
                sample_stats["trailing_fail"] += 1
                if len(trailing_v) < 500:
                    trailing_v.append({"profile_id": pid, "route_key": rk, "codes": trail_fails})

            exp_fails = audit_exposure(p)
            if exp_fails:
                sample_stats["exposure_fail"] += 1
                if len(exposure_v) < 500:
                    exposure_v.append({"profile_id": pid, "route_key": rk})

            cap_fails = audit_capacity(p)
            if cap_fails:
                sample_stats["min_notional_fail"] += 1

            base = float(p.get("base_alloc_frac") or 0.5)
            if rec.risk_key == "DEFENSIVE" and rec.regime_key in ("R7", "R8") and base > 0.40:
                sample_stats["defensive_base_high"] += 1
                if len(base_quote_v) < 300:
                    base_quote_v.append(
                        {"profile_id": pid, "route_key": rk, "base_pct": round(base * 100, 1)}
                    )

            if trail_fails or exp_fails or cap_fails:
                rec.validity = "invalid"
                if len(invalid) < 1000:
                    invalid.append(rec.to_dict())

        if n >= sample_size:
            break

    dup = analyze_duplicates(fp_map, defaultdict(Counter))
    rows = coverage.get("rows") or []
    empty_exact = sum(1 for r in rows if r.get("empty"))
    resolver_preview = fast_resolver_coverage_index(index_path, violations=[])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 2),
        "manifest_profiles": manifest_count,
        "sample_scanned": n,
        "unique_ids_in_sample": len(seen_ids),
        "coverage": {
            "routes_enumerated": coverage.get("routes_enumerated"),
            "routes_with_exact_profiles": coverage.get("routes_with_profiles"),
            "routes_empty_exact": empty_exact,
            "empty_with_safe_fallback": coverage.get("empty_with_safe_fallback"),
            "empty_unsafe": coverage.get("empty_unsafe"),
            "mandatory_empty": coverage.get("mandatory_empty"),
            "exact_coverage_pct": round(
                100.0 * coverage.get("routes_with_profiles", 0) / max(ROUTE_MANIFEST_TOTAL, 1),
                2,
            ),
        },
        "duplicate_analysis_sample": dup,
        "sample_violations": dict(sample_stats),
        "r8_audit": fallback.get("r8_crash_audit"),
        "r15_source_order": fallback.get("r15_source_order"),
        "resolver_preview": {
            "routes_simulated": resolver_preview.get("routes_simulated"),
            "no_param_paths": resolver_preview.get("no_param_paths"),
            "unsafe_fallback_count": resolver_preview.get("unsafe_fallback_count"),
            "pass": resolver_preview.get("pass"),
        },
        "baseline_violation_counts": {
            "blocker": len([v for v in violations if v.severity == SEVERITY_BLOCKER]),
            "critical": len([v for v in violations if v.severity == SEVERITY_CRITICAL]),
        },
        "artifacts_preview": {
            "trailing_violations_sample": len(trailing_v),
            "exposure_violations_sample": len(exposure_v),
            "base_quote_issues_sample": len(base_quote_v),
            "invalid_sample": len(invalid),
        },
    }


def write_baseline_report(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cov = data.get("coverage") or {}
    lines = [
        "# Dynamic Param V4 — Baseline Audit (pre-fix)",
        "",
        f"**Generated:** {data.get('generated_at')}",
        f"**Elapsed:** {data.get('elapsed_sec')}s",
        "",
        "## Snapshot",
        "",
        f"- Manifest profiles: **{data.get('manifest_profiles'):,}**",
        f"- Sample scanned: **{data.get('sample_scanned'):,}**",
        f"- Exact route coverage: **{cov.get('exact_coverage_pct')}%** ({cov.get('routes_with_exact_profiles')}/{cov.get('routes_enumerated')})",
        f"- Empty exact shelves: **{cov.get('routes_empty_exact')}**",
        f"- Safe fallback empty: **{cov.get('empty_with_safe_fallback')}**",
        f"- Unsafe empty: **{cov.get('empty_unsafe')}**",
        f"- Mandatory empty: **{len(cov.get('mandatory_empty') or [])}**",
        "",
        "## Duplicate (sample)",
        "",
        f"- Exact duplicate groups (sample): **{(data.get('duplicate_analysis_sample') or {}).get('exact_duplicate_groups', 'N/A')}**",
        f"- Near duplicate (sample): **{(data.get('duplicate_analysis_sample') or {}).get('near_duplicate_count', 'N/A')}**",
        f"- Unique fingerprints (sample): **{(data.get('duplicate_analysis_sample') or {}).get('unique_fingerprints', 'N/A')}**",
        f"- Inflated ratio estimate (sample): **{(data.get('duplicate_analysis_sample') or {}).get('inflated_profile_ratio', 'N/A')}**",
        "",
        "See `param_pool_duplicate_profiles.json` after full scan for details.",
        "",
        "## Sample violations",
        "",
        json.dumps(data.get("sample_violations") or {}, indent=2),
        "",
        "## R8 / R15",
        "",
        f"- R8 pass: {((data.get('r8_audit') or {}).get('pass'))}",
        f"- R15 order: {data.get('r15_source_order')}",
        "",
        "## Resolver preview",
        "",
        json.dumps(data.get("resolver_preview") or {}, indent=2),
        "",
        "*No code or pool modifications were applied in baseline phase.*",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_tests(reports_dir: Path) -> List[Dict[str, Any]]:
    tests = [
        "tests/dynamic_param_score/test_param_pool_integrity_v4.py",
        "tests/dynamic_param_score/test_route_shelf_coverage_v4.py",
        "tests/dynamic_param_score/test_grid_distribution_rules_v4.py",
        "tests/dynamic_param_score/test_fallback_rules_v4.py",
        "tests/dynamic_param_score/test_risk_exposure_rules_v4.py",
        "tests/dynamic_param_score/test_dynamic_param_v4_regression_btc_low_vol_defensive.py",
    ]
    results = []
    for t in tests:
        tpath = ROOT / t
        if not tpath.exists():
            results.append({"test": t, "status": "missing", "exit_code": None})
            continue
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(tpath), "-q", "--tb=line"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        results.append(
            {
                "test": t,
                "exit_code": proc.returncode,
                "stdout_tail": proc.stdout[-800:] if proc.stdout else "",
                "stderr_tail": proc.stderr[-400:] if proc.stderr else "",
            }
        )
    out = reports_dir / "param_pool_test_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="V4 night audit orchestrator")
    parser.add_argument("--reports-dir", default=str(ROOT / "reports"))
    parser.add_argument("--phase", choices=("all", "baseline", "full", "tests"), default="all")
    parser.add_argument("--skip-full-scan", action="store_true")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = DEFAULT_V4_SQLITE_PATH
    index_path = DEFAULT_V4_SELECTION_INDEX_PATH

    state = NightAuditState(
        git_commit=_git_info()[0],
        git_branch=_git_info()[1],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    if args.phase in ("all", "baseline"):
        print("=== BASELINE AUDIT ===")
        state.baseline = run_baseline_audit(sqlite_path, index_path)
        write_baseline_report(state.baseline, reports_dir / "DYNAMIC_PARAM_V4_BASELINE_AUDIT.md")
        (reports_dir / "param_pool_baseline_summary.json").write_text(
            json.dumps(state.baseline, indent=2), encoding="utf-8"
        )

    if args.phase in ("all", "full") and not args.skip_full_scan:
        print("=== FULL POOL AUDIT ===")
        result = run_full_pool_audit(
            sqlite_path=sqlite_path,
            index_path=index_path,
            skip_profile_scan=False,
            skip_resolver_sim=False,
        )
        result.load_meta["git_commit"] = state.git_commit
        result.load_meta["git_branch"] = state.git_branch
        generate_markdown_report(result, report_path=reports_dir / "DYNAMIC_PARAM_V4_FULL_POOL_AUDIT.md")
        artifacts = write_audit_artifacts(result, reports_dir)

        trailing_path = reports_dir / "param_pool_trailing_violations.json"
        trailing_path.write_text(json.dumps(result.grid_violations[:2000], indent=2), encoding="utf-8")

        state.final = {
            "elapsed_sec": result.elapsed_sec,
            "profiles_scanned": result.profile_scan_stats.get("profiles_scanned"),
            "blockers": sum(1 for v in result.violations if v.severity == SEVERITY_BLOCKER),
            "artifacts": {k: str(v) for k, v in artifacts.items()},
        }

    if args.phase in ("all", "tests"):
        print("=== TESTS ===")
        state.test_results = run_tests(reports_dir)

    summary = {
        "git_commit": state.git_commit,
        "git_branch": state.git_branch,
        "started_at": state.started_at,
        "baseline": state.baseline,
        "final": state.final,
        "test_results": state.test_results,
    }
    (reports_dir / "night_audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"git": state.git_commit, "baseline": bool(state.baseline), "final": bool(state.final)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
