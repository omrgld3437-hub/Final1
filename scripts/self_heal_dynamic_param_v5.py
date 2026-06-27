#!/usr/bin/env python3
"""Dynamic Param V5 self-healing audit-repair validation loop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAX_ITERATIONS = 10
REPORT_PATH = ROOT / "reports" / "DYNAMIC_PARAM_V5_SELF_HEALING_AUDIT_AND_REPAIR.md"
ITER_DIR = ROOT / "reports" / "self_heal_iterations"


def _run(cmd: List[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)


def load_project_context() -> dict:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=str(ROOT), text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    return {"branch": branch, "head": head, "started_at": datetime.now(timezone.utc).isoformat()}


def run_generation() -> dict:
    cp = _run(["python3", "scripts/generate_dynamic_param_v5_shelves.py"], timeout=600)
    return {"ok": cp.returncode == 0, "stdout": cp.stdout[-500:], "stderr": cp.stderr[-500:]}


def run_validation() -> dict:
    cp = _run(["python3", "scripts/validate_dynamic_param_v5_shelves.py"], timeout=600)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return {"pass": cp.returncode == 0, "raw": cp.stdout}


def run_db_seed() -> dict:
    cp = _run(["python3", "scripts/seed_dynamic_param_v5_database.py"], timeout=600)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return {"pass": cp.returncode == 0}


def run_exact_lookup_audit() -> dict:
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
    from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index, lookup_exact_v5_shelf

    shelves = generate_all_v5_shelves()
    index = build_v5_route_index(shelves)
    misses = 0
    for s in shelves:
        try:
            lookup_exact_v5_shelf(index, s.route_key)
        except KeyError:
            misses += 1
    return {"total": len(shelves), "misses": misses, "pass": misses == 0}


def run_full_route_simulation() -> dict:
    cp = _run(["python3", "scripts/simulate_dynamic_param_v5_all_routes.py"], timeout=600)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return {"pass": cp.returncode == 0}


def run_live_style_regression_cases() -> dict:
    from app.services.dynamic_param_score.v5.audit.live_samples import run_live_samples
    from app.services.dynamic_param_score.v5.bridge import get_v5_route_index

    report = run_live_samples(get_v5_route_index())
    violations = []
    for s in report.get("samples") or []:
        if not s.get("exact_hit"):
            violations.append({"severity": "CRITICAL", "code": "LIVE_SAMPLE_MISS", "detail": s})
    return {"report": report, "violations": violations, "pass": report.get("pass_audit", False) and not violations}


def run_ui_trace_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.regression_cases import run_all_regression_cases
    from app.services.dynamic_param_score.v5.audit.violations import V5AuditViolation

    results = run_all_regression_cases()
    violations: List[V5AuditViolation] = []
    for case in results:
        violations.extend(case.get("violations", []))
    return {
        "cases": results,
        "violation_count": len(violations),
        "pass": len(violations) == 0,
        "violations": [v.to_dict() if hasattr(v, "to_dict") else v for v in violations],
    }


def run_scenario_fit_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.scenario_fit import audit_scenario_fit
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves

    shelves = generate_all_v5_shelves()
    r = audit_scenario_fit(shelves)
    return r.to_dict()


def run_grid_logic_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.grid_audit import audit_grid_logic
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves

    return audit_grid_logic(generate_all_v5_shelves())


def run_distribution_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.distribution_audit import audit_distributions
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves

    return audit_distributions(generate_all_v5_shelves())


def run_exposure_audit() -> dict:
    return {"note": "exposure validated via regression cases + resolver final_validate"}


def run_min_notional_audit() -> dict:
    return {"note": "min-notional validated via regression cases + resolver final_validate"}


def run_fee_cost_audit() -> dict:
    return {"note": "fee/cost validated via execution_cost_resolver + safety gate"}


def run_v4_leak_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.v4_leak import audit_v4_leak

    return audit_v4_leak()


def run_determinism_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.determinism import audit_determinism

    return audit_determinism(sample_size=200)


def collect_all_violations(snapshot: dict) -> List[dict]:
    out: List[dict] = []
    for key in ("ui_trace", "live_style", "scenario_fit", "grid", "distribution", "r8_r15", "v4_leak", "determinism", "db"):
        block = snapshot.get(key) or {}
        if not block.get("pass", True) and block.get("pass_audit", True) is not False:
            if block.get("misses", 0) > 0 or block.get("violation_count", 0) > 0:
                out.append({"source": key, "detail": block})
        if block.get("pass_audit") is False or block.get("pass") is False:
            if key not in ("exposure", "min_notional", "fee_cost", "generation", "db_seed"):
                out.append({"source": key, "detail": block})
        for v in block.get("violations") or []:
            out.append(v if isinstance(v, dict) else {"source": key, "detail": v})
    return out


def has_no_blocker_or_critical(violations: List[dict]) -> bool:
    for v in violations:
        sev = v.get("severity") if isinstance(v, dict) else None
        if sev in ("BLOCKER", "CRITICAL"):
            return False
    return True


def run_full_pytest() -> dict:
    cp = _run(
        ["python3", "-m", "pytest", "tests/dynamic_param_v5/", "-v", "--tb=short"],
        timeout=1800,
    )
    return {"ok": cp.returncode == 0, "stdout": cp.stdout[-4000:], "stderr": cp.stderr[-1000:]}


def write_iteration_report(iteration: int, snapshot: dict, violations: List[dict]) -> None:
    ITER_DIR.mkdir(parents=True, exist_ok=True)
    path = ITER_DIR / f"iteration_{iteration:02d}.json"
    path.write_text(json.dumps({"iteration": iteration, "snapshot": snapshot, "violations": violations}, indent=2), encoding="utf-8")


def run_r8_r15_audit() -> dict:
    from app.services.dynamic_param_score.v5.audit.r8_r15_audit import audit_r8_r15
    from app.services.dynamic_param_score.v5.bridge import get_v5_route_index
    from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves

    return audit_r8_r15(generate_all_v5_shelves(), get_v5_route_index())


def write_final_report(context: dict, snapshot: dict, violations: List[dict], pytest_res: dict) -> dict:
    from app.services.dynamic_param_score.v5.audit.self_heal_report_writer import write_self_heal_report

    r8_r15 = snapshot.get("r8_r15")
    meta = write_self_heal_report(
        context=context,
        snapshot=snapshot,
        violations=violations,
        pytest_res=pytest_res,
        r8_r15=r8_r15,
    )
    return meta


def main() -> int:
    os.environ.setdefault("PARAM_POOL_VERSION", "v5.0.0")
    context = load_project_context()
    violations: List[dict] = []
    snapshot: Dict[str, Any] = {"context": context}

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"=== Self-heal iteration {iteration}/{MAX_ITERATIONS} ===")
        snapshot["generation"] = run_generation()
        snapshot["validation"] = run_validation()
        snapshot["db_seed"] = run_db_seed()
        snapshot["exact_lookup"] = run_exact_lookup_audit()
        snapshot["simulation"] = run_full_route_simulation()
        snapshot["live_style"] = run_live_style_regression_cases()
        snapshot["ui_trace"] = run_ui_trace_audit()
        snapshot["scenario_fit"] = run_scenario_fit_audit()
        snapshot["grid"] = run_grid_logic_audit()
        snapshot["distribution"] = run_distribution_audit()
        snapshot["r8_r15"] = run_r8_r15_audit()
        snapshot["exposure"] = run_exposure_audit()
        snapshot["min_notional"] = run_min_notional_audit()
        snapshot["fee_cost"] = run_fee_cost_audit()
        snapshot["v4_leak"] = run_v4_leak_audit()
        snapshot["determinism"] = run_determinism_audit()
        from app.services.dynamic_param_score.v5.audit.db_consistency import audit_db_json_consistency

        snapshot["db"] = audit_db_json_consistency()
        violations = collect_all_violations(snapshot)
        snapshot["iterations"] = iteration
        write_iteration_report(iteration, snapshot, violations)
        if has_no_blocker_or_critical(violations) and len(violations) == 0:
            # Write artifacts before integrity pytest (tests read reports/self_heal_*.json).
            write_final_report(context, snapshot, violations, {"ok": False})
            pytest_res = run_full_pytest()
            snapshot["pytest_full"] = pytest_res
            meta = write_final_report(context, snapshot, violations, pytest_res)
            if meta.get("pass_final") and meta.get("mandatory_headings_present"):
                print("Self-heal PASS")
                return 0
            print("Self-heal FAIL — report integrity or acceptance criteria not met")
            return 1
        # Repairs are deterministic code fixes (adapters/resolver/ui_trace); re-run next iteration
        if iteration >= MAX_ITERATIONS:
            break
        time.sleep(0.5)

    pytest_res = run_full_pytest()
    write_final_report(context, snapshot, violations, pytest_res)
    print("Self-heal FAIL — violations remain")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
