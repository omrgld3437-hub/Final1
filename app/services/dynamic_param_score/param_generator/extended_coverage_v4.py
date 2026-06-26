"""Single source of truth for extended shelf coverage (seed + acceptance)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import normalize_route_key
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    EXTENDED_COVERAGE_MIN_COUNT,
    MIN_PROFILES_PER_SHELF,
    derive_source_route_candidates,
    extended_coverage_manifest,
    is_mandatory_route,
)

FORBIDDEN_DERIVE_REGIMES = frozenset({"R2"})


def route_parts(route_key: str) -> Dict[str, str]:
    parts = normalize_route_key(route_key).split("|")
    if len(parts) != 5:
        return {"route_key": route_key}
    a, r, s, v, risk = parts
    return {
        "route_key": normalize_route_key(route_key),
        "asset": a,
        "regime": r,
        "structure": s,
        "volatility": v,
        "risk": risk,
    }


def load_templates_by_route_from_sqlite(sqlite_path: Path) -> Dict[str, List[str]]:
    import sqlite3

    out: Dict[str, List[str]] = {}
    conn = sqlite3.connect(str(sqlite_path))
    try:
        for template_key, params_json in conn.execute(
            "SELECT template_key, params_json FROM param_templates WHERE status = 'active'"
        ):
            params = json.loads(params_json or "{}")
            dps = params.get("dps_profile") or {}
            rk = normalize_route_key(str(dps.get("route_key") or params.get("route_key") or ""))
            if not rk:
                continue
            out.setdefault(rk, []).append(str(template_key))
    finally:
        conn.close()
    return out


def load_templates_by_route_from_index(index_path: Path) -> Dict[str, List[str]]:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    index = raw.get("index_by_route_key") or raw.get("route_index") or {}
    return {normalize_route_key(k): list(v) for k, v in index.items() if v}


def nearest_source_route(
    target_route: str,
    templates_by_route: Dict[str, List[str]],
) -> Tuple[str, str]:
    """Return (nearest_source_route, planned_seed_action) — never R2."""
    target = normalize_route_key(target_route)
    for candidate in derive_source_route_candidates(target):
        if "|R2|" in candidate:
            continue
        if templates_by_route.get(candidate):
            return candidate, f"derive_from_{candidate}"
    parts = target.split("|")
    if len(parts) == 5 and parts[1] == "R15":
        for src_r in ("R12", "R7", "R6"):
            prefix = f"{parts[0]}|{src_r}|{parts[2]}|"
            for rk, keys in templates_by_route.items():
                if rk.startswith(prefix) and keys and "|R2|" not in rk:
                    return rk, f"r15_cluster_from_{rk}"
    return "", "no_source_available"


def measure_extended_coverage(
    templates_by_route: Dict[str, List[str]],
    *,
    min_count: int = EXTENDED_COVERAGE_MIN_COUNT,
    min_profiles: int = MIN_PROFILES_PER_SHELF,
) -> Dict[str, Any]:
    """Canonical coverage report — used by seed (post-index) and acceptance."""
    manifest = extended_coverage_manifest(min_count=min_count)
    mandatory_empty: List[str] = []
    optional_empty: List[str] = []

    for rk in manifest:
        n = len(templates_by_route.get(rk) or [])
        if n >= min_profiles:
            continue
        if is_mandatory_route(rk):
            mandatory_empty.append(rk)
        else:
            optional_empty.append(rk)

    mandatory_fail = len(mandatory_empty)
    optional_total = len(optional_empty)
    if mandatory_fail:
        status = "fail"
    elif optional_total:
        status = "warning"
    else:
        status = "ok"

    return {
        "extended_manifest_route_count": len(manifest),
        "extended_manifest_min_profiles": min_profiles,
        "mandatory_route_empty": mandatory_fail,
        "mandatory_empty_routes": mandatory_empty,
        "optional_route_empty_total": optional_total,
        "optional_empty_routes_total": optional_empty,
        "critical_route_empty": mandatory_fail,
        "critical_shelves_empty": optional_total,
        "critical_routes_checked": len(manifest),
        "status": status,
        "pass": mandatory_fail == 0,
        "extended_pass": mandatory_fail == 0 and optional_total == 0,
    }


def build_gap_records(
    empty_routes: List[str],
    templates_by_route: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rk in empty_routes:
        parts = route_parts(rk)
        nearest, action = nearest_source_route(rk, templates_by_route)
        rows.append(
            {
                **parts,
                "profile_count": len(templates_by_route.get(rk) or []),
                "reason": "below_min_profiles",
                "nearest_source_route": nearest,
                "planned_seed_action": action,
                "r2_derive_forbidden": True,
            }
        )
    return rows


def audit_extended_coverage_from_index(
    index_path: Path,
    *,
    min_count: int = EXTENDED_COVERAGE_MIN_COUNT,
    min_profiles: int = MIN_PROFILES_PER_SHELF,
) -> Dict[str, Any]:
    by_route = load_templates_by_route_from_index(index_path)
    report = measure_extended_coverage(by_route, min_count=min_count, min_profiles=min_profiles)
    report["source"] = "selection_index"
    report["index_path"] = str(index_path)
    if report["optional_empty_routes_total"]:
        report["gap_records"] = build_gap_records(
            report["optional_empty_routes_total"], by_route
        )
    return report


def audit_extended_coverage_from_sqlite(
    sqlite_path: Path,
    *,
    min_count: int = EXTENDED_COVERAGE_MIN_COUNT,
    min_profiles: int = MIN_PROFILES_PER_SHELF,
) -> Dict[str, Any]:
    by_route = load_templates_by_route_from_sqlite(sqlite_path)
    report = measure_extended_coverage(by_route, min_count=min_count, min_profiles=min_profiles)
    report["source"] = "sqlite"
    report["sqlite_path"] = str(sqlite_path)
    if report["optional_empty_routes_total"]:
        report["gap_records"] = build_gap_records(
            report["optional_empty_routes_total"], by_route
        )
    return report


def write_gap_exports(
    gap_records: List[Dict[str, Any]],
    output_dir: Path,
    *,
    prefix: str = "extended_coverage_gaps",
) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{prefix}.json"
    csv_path = output_dir / f"{prefix}.csv"
    json_path.write_text(json.dumps(gap_records, indent=2), encoding="utf-8")
    if gap_records:
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(gap_records[0].keys()))
            writer.writeheader()
            writer.writerows(gap_records)
    else:
        csv_path.write_text("", encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path)}
