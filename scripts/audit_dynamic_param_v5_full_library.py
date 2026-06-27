#!/usr/bin/env python3
"""Full evidence-based V5 audit — expands DYNAMIC_PARAM_V5_FULL_REBUILD_AND_AUDIT.md."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)


def git_info() -> dict:
    try:
        return {
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
            "commit": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        }
    except Exception:
        return {"branch": "unknown", "commit": "unknown"}


def load_json(name: str) -> dict:
    p = REPORTS / name
    return json.loads(p.read_text()) if p.exists() else {}


def run_pytest() -> dict:
    try:
        out = subprocess.check_output(
            ["python3", "-m", "pytest", "tests/dynamic_param_v5/", "-q", "--tb=no"],
            cwd=str(ROOT),
            text=True,
            timeout=600,
        )
        line = [l for l in out.strip().splitlines() if "passed" in l][-1] if out else ""
        passed = "failed" not in line and "passed" in line
        n = line.split()[0] if line else "0"
        return {"passed": passed, "passed_count": n, "total": n, "output_line": line}
    except subprocess.CalledProcessError as e:
        return {"passed": False, "output": e.stdout + e.stderr}


def main() -> None:
    from app.services.dynamic_param_score.v5.audit.db_consistency import audit_db_json_consistency
    from app.services.dynamic_param_score.v5.audit.determinism import audit_determinism
    from app.services.dynamic_param_score.v5.audit.distribution_audit import audit_distributions
    from app.services.dynamic_param_score.v5.audit.grid_audit import audit_grid_logic
    from app.services.dynamic_param_score.v5.audit.live_samples import run_live_samples
    from app.services.dynamic_param_score.v5.audit.r8_r15_audit import audit_r8_r15
    from app.services.dynamic_param_score.v5.audit.report_writer import write_full_audit_report
    from app.services.dynamic_param_score.v5.audit.scenario_fit import audit_scenario_fit
    from app.services.dynamic_param_score.v5.audit.v4_leak import audit_v4_leak
    from app.services.dynamic_param_score.v5.generator.generate_shelves import FORMULA_VERSION, generate_all_v5_shelves
    from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index

    t0 = time.perf_counter()
    print("Loading shelves for audit...")
    json_path = ROOT / "generated/dynamic_param_v5_shelves.json"
    if json_path.exists():
        from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
        from app.services.dynamic_param_score.v5.domain.types import (
            V5BaseTemplate,
            V5FallbackPolicy,
            V5GenerationMeta,
            V5ResolverPolicy,
            V5Shelf,
        )

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        shelves = []
        for d in raw:
            rp = V5RouteParts.from_dict(d["route_parts"])
            bt = d["base_template"]
            shelves.append(
                V5Shelf(
                    version="DPLV5",
                    shelf_id=d["shelf_id"],
                    route_key=d["route_key"],
                    route_parts=rp,
                    scenario_title=d["scenario_title"],
                    scenario_description=d["scenario_description"],
                    base_template=V5BaseTemplate(**bt),
                    resolver_policy=V5ResolverPolicy(**d["resolver_policy"]),
                    fallback_policy=V5FallbackPolicy(**d["fallback_policy"]),
                    validation_policy=d["validation_policy"],
                    generation_meta=V5GenerationMeta(**d["generation_meta"]),
                )
            )
    else:
        shelves = generate_all_v5_shelves()

    index = build_v5_route_index(shelves)
    print(f"Loaded {len(shelves)} shelves")

    print("Scenario-fit audit...")
    scenario_fit = audit_scenario_fit(shelves).to_dict()
    (REPORTS / "dynamic_param_v5_scenario_fit.json").write_text(json.dumps(scenario_fit, indent=2))

    print("Grid logic audit...")
    grid_audit = audit_grid_logic(shelves)
    (REPORTS / "dynamic_param_v5_grid_audit.json").write_text(json.dumps(grid_audit, indent=2))

    print("Distribution audit...")
    distribution = audit_distributions(shelves)
    (REPORTS / "dynamic_param_v5_distribution_audit.json").write_text(json.dumps(distribution, indent=2))

    print("R8/R15 audit...")
    r8_r15 = audit_r8_r15(shelves, index)
    (REPORTS / "dynamic_param_v5_fallback_policy_audit.json").write_text(json.dumps(r8_r15, indent=2))

    print("DB consistency...")
    db_consistency = audit_db_json_consistency()
    (REPORTS / "dynamic_param_v5_db_consistency.json").write_text(json.dumps(db_consistency, indent=2))

    print("Determinism (double generate — may take ~60s)...")
    determinism = audit_determinism()
    (REPORTS / "dynamic_param_v5_determinism.json").write_text(json.dumps(determinism, indent=2))

    print("V4 leak test...")
    v4_leak = audit_v4_leak()
    (REPORTS / "dynamic_param_v5_legacy_cleanup_report.md").write_text(
        f"# V4 Leak Report\n\n```json\n{json.dumps(v4_leak, indent=2)}\n```\n"
    )

    print("Live-style samples...")
    live_samples = run_live_samples(index)
    (REPORTS / "dynamic_param_v5_live_samples.json").write_text(json.dumps(live_samples, indent=2))

    print("Pytest...")
    test_summary = run_pytest()
    (REPORTS / "dynamic_param_v5_test_results.md").write_text(
        f"# V5 Test Results\n\n```json\n{json.dumps(test_summary, indent=2)}\n```\n"
    )

    manifest = load_json("dynamic_param_v5_generation_manifest.json")
    if not manifest:
        manifest = load_json("../generated/dynamic_param_v5_generation_manifest.json")
    manifest_path = ROOT / "generated/dynamic_param_v5_generation_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    overall = write_full_audit_report(
        REPORTS / "DYNAMIC_PARAM_V5_FULL_REBUILD_AND_AUDIT.md",
        git_info=git_info(),
        manifest=manifest,
        bench=load_json("dynamic_param_v5_lookup_benchmark.json"),
        sim=load_json("dynamic_param_v5_resolver_simulation.json"),
        scenario_fit=scenario_fit,
        grid_audit=grid_audit,
        distribution=distribution,
        r8_r15=r8_r15,
        db_consistency=db_consistency,
        determinism=determinism,
        v4_leak=v4_leak,
        live_samples=live_samples,
        test_summary=test_summary,
        formula_version=FORMULA_VERSION,
    )

    elapsed = time.perf_counter() - t0
    print(f"Audit complete in {elapsed:.1f}s — PASS={overall}")
    if not overall:
        sys.exit(1)


if __name__ == "__main__":
    main()
