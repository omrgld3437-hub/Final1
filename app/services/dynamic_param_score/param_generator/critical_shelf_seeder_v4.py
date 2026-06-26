"""Seed mandatory DEFENSIVE / critical shelves from sibling or derived regime profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    REGIME_SHELVES,
    dplv4_profile_id_clean,
    normalize_route_key,
)
from app.services.dynamic_param_score.param_generator.library_repair_v4 import (
    repair_v4_template,
)
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    SCENARIO_SPECS,
    interpolate_range,
    scale_grids,
)
from app.services.dynamic_param_score.param_generator.v4_resolvers import _trim_distribution
from app.services.dynamic_param_score.param_generator.extended_coverage_v4 import (
    audit_extended_coverage_from_index,
    audit_extended_coverage_from_sqlite,
    measure_extended_coverage,
    write_gap_exports,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    EXTENDED_COVERAGE_MIN_COUNT,
    MANDATORY_CRITICAL_ROUTES,
    MANDATORY_ROUTE_SET,
    MIN_PROFILES_PER_SHELF,
    derive_source_route_candidates,
    extended_coverage_manifest,
    is_mandatory_route,
    sibling_normal_route,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    insert_param_templates,
    load_templates_by_keys,
)

LoadFn = Callable[[List[str]], List[ParamTemplate]]

SEED_CLONE_SEQ_BASE = 910_000
FORBIDDEN_SOURCE_REGIMES = frozenset({"R2"})


def _route_clone_prefix(target_route: str) -> str:
    parts = normalize_route_key(target_route).split("|")
    if len(parts) != 5:
        return "DPLV4_SEED_"
    a, r, s, v, risk = parts
    return f"DPLV4_{a}_{r}_{s}_{v}_{risk}_"


def _alloc_clone_seqs(
    sqlite_path: Path,
    target_route: str,
    count: int,
    *,
    reserved_keys: set[str],
) -> List[int]:
    """Allocate unique DPLV4 seq suffixes for shelf clones (910000+ range)."""
    prefix = _route_clone_prefix(target_route)
    used: set[int] = set()
    if sqlite_path.is_file():
        import sqlite3

        conn = sqlite3.connect(str(sqlite_path))
        try:
            for (key,) in conn.execute(
                "SELECT template_key FROM param_templates WHERE template_key LIKE ?",
                (prefix + "%",),
            ):
                tail = str(key).rsplit("_", 1)[-1]
                if tail.isdigit():
                    used.add(int(tail))
        finally:
            conn.close()
    for key in reserved_keys:
        if str(key).startswith(prefix):
            tail = str(key).rsplit("_", 1)[-1]
            if tail.isdigit():
                used.add(int(tail))
    seqs: List[int] = []
    n = max([SEED_CLONE_SEQ_BASE, *used, 0]) + 1
    while len(seqs) < count:
        while n in used:
            n += 1
        seqs.append(n)
        used.add(n)
        n += 1
    return seqs


def _clone_template_for_target(
    source: ParamTemplate,
    target_route: str,
    method: str,
    *,
    seq: int,
    reserved_keys: set[str],
) -> ParamTemplate:
    """Clone source profile onto target shelf with a new template_key (source untouched)."""
    parts = normalize_route_key(target_route).split("|")
    if len(parts) != 5:
        raise ValueError(f"invalid target route: {target_route}")
    cell = {
        "asset_code": parts[0],
        "regime_code": parts[1],
        "structure_code": parts[2],
        "vol_code": parts[3],
        "risk_class": parts[4],
    }
    new_key = dplv4_profile_id_clean(cell, seq=seq)
    while new_key in reserved_keys:
        seq += 1
        new_key = dplv4_profile_id_clean(cell, seq=seq)
    reserved_keys.add(new_key)

    params = json.loads(json.dumps(source.params or {}))
    dps = dict(params.get("dps_profile") or {})
    dps = _apply_target_route(dps, target_route)
    dps["seed_derivation"] = f"clone:{method}"
    dps["profile_id"] = new_key
    dps["cloned_from_template_key"] = source.template_key
    params["dps_profile"] = dps
    params["route_key"] = target_route
    params["scenario"] = dps.get("scenario")
    params["profile_id"] = new_key

    cloned = source.model_copy(
        update={
            "template_key": new_key,
            "params": params,
            "notes": (source.notes or "") + f";seed_clone:{method}",
        }
    )
    return repair_v4_template(cloned)


def _find_source_keys(
    target: str,
    templates_by_route: Dict[str, List[str]],
) -> Tuple[List[str], str]:
    """Return (template_keys, derivation_method)."""
    target = normalize_route_key(target)
    parts = target.split("|")
    asset = parts[0] if len(parts) >= 1 else ""
    regime = parts[1] if len(parts) >= 5 else ""
    structure = parts[2] if len(parts) >= 5 else ""
    vol = parts[3] if len(parts) >= 5 else ""
    risk = parts[4] if len(parts) >= 5 else "NORMAL"

    # R2/R4 DEFENSIVE shelves: clone from downtrend cluster (never from R2 source for R15).
    if regime in ("R2", "R4") and risk in ("DEFENSIVE", "CAUTION"):
        asset_candidates = [asset]
        if asset == "A2":
            asset_candidates.extend(["A1", "A3"])
        elif asset == "A1":
            asset_candidates.append("A2")
        elif asset == "A3":
            asset_candidates.extend(["A2", "A4"])
        vol_alts = [vol, "V4", "V3", "V5", "V2"]
        for src_asset in asset_candidates:
            for src_regime in ("R7", "R12", "R6"):
                for src_struct in (structure, "S2", "S1", "S3"):
                    for src_vol in vol_alts:
                        candidate = f"{src_asset}|{src_regime}|{src_struct}|{src_vol}|{risk}"
                        keys = list(templates_by_route.get(normalize_route_key(candidate)) or [])
                        if keys:
                            return keys, f"defensive_cluster:{candidate}"
        for src_asset in asset_candidates:
            for src_regime in ("R7", "R12", "R6"):
                prefix = f"{src_asset}|{src_regime}|"
                for rk, keys in sorted(templates_by_route.items()):
                    if rk.startswith(prefix) and keys and risk in rk:
                        return list(keys), f"defensive_regime_prefix:{prefix}"
        # Same route NORMAL risk profiles are valid clone sources for DEFENSIVE target.
        normal_target = f"{asset}|{regime}|{structure}|{vol}|NORMAL"
        keys = list(templates_by_route.get(normalize_route_key(normal_target)) or [])
        if keys:
            return keys, f"same_route_normal:{normal_target}"

    for candidate in derive_source_route_candidates(target):
        if regime != "R2" and "|R2|" in candidate:
            continue
        keys = list(templates_by_route.get(candidate) or [])
        if keys:
            return keys, f"derived:{candidate}"

    parts = target.split("|")
    if len(parts) == 5:
        prefix = f"{parts[0]}|{parts[1]}|{parts[2]}|"
        for rk, keys in templates_by_route.items():
            if "|R2|" in rk:
                continue
            if rk.startswith(prefix) and keys:
                return list(keys), f"prefix:{prefix}"

        prefix = f"{parts[0]}|{parts[1]}|"
        for rk, keys in sorted(templates_by_route.items()):
            if "|R2|" in rk:
                continue
            if rk.startswith(prefix) and keys:
                return list(keys), f"regime_prefix:{prefix}"

        # R15 last resort: same asset + structure from downtrend cluster (never R2).
        if parts[1] == "R15":
            for src_r in ("R12", "R7", "R6"):
                prefix = f"{parts[0]}|{src_r}|{parts[2]}|"
                for rk, keys in templates_by_route.items():
                    if "|R2|" in rk:
                        continue
                    if rk.startswith(prefix) and keys:
                        return list(keys), f"r15_cluster:{src_r}"

    return [], "none"


def _apply_r15_recovery_behavior(out: Dict[str, Any], *, risk: str) -> Dict[str, Any]:
    """Transform derived profile into RECOVERY_AFTER_DUMP behavior (not a raw R12/R7 copy)."""
    spec = SCENARIO_SPECS["RECOVERY_AFTER_DUMP"]
    variant = abs(hash(str(out.get("profile_id") or out.get("route_key") or "0"))) % 7
    base = interpolate_range(spec.base_range[0], spec.base_range[1], variant)
    quote = interpolate_range(spec.quote_range[0], spec.quote_range[1], variant)
    if risk == "DEFENSIVE":
        base = min(base, 0.40)
        quote = max(quote, 0.60)
    total = base + quote
    if total > 0:
        base, quote = base / total, quote / total

    buy_grids = scale_grids(spec.buy_grids, variant)
    sell_grids = scale_grids(spec.sell_grids, variant)
    buy_dist = list(_trim_distribution(list(spec.buy_dist), len(buy_grids)))
    sell_dist = list(_trim_distribution(list(spec.sell_dist), len(sell_grids)))
    buy_trail = interpolate_range(spec.buy_trail_range[0], spec.buy_trail_range[1], variant)
    sell_trail = interpolate_range(spec.sell_trail_range[0], spec.sell_trail_range[1], variant)

    out.update(
        {
            "regime": "RECOVERY_AFTER_DUMP",
            "regime_code": "R15",
            "scenario": "RECOVERY_AFTER_DUMP",
            "base_alloc_frac": round(base, 4),
            "quote_alloc_frac": round(quote, 4),
            "buy_grid_ladder_pcts": buy_grids,
            "sell_grid_ladder_pcts": sell_grids,
            "buy_grid_pcts": buy_grids,
            "sell_grid_pcts": sell_grids,
            "buy_grid_count": len(buy_grids),
            "sell_grid_count": len(sell_grids),
            "buy_distribution": buy_dist,
            "sell_distribution": sell_dist,
            "buy_trailing_pct": buy_trail,
            "sell_trailing_pct": sell_trail,
            "max_base_exposure_frac": round(min(float(out.get("max_base_exposure_frac") or 0.5), 0.50), 4),
            "rebuy_enabled": False,
            "recovery_confirmation_required": True,
            "grid_bias": "RECOVERY_SELL_BIAS",
            "derivation_regime": "R15_RECOVERY",
        }
    )
    return out


def _apply_target_route(profile: Dict[str, Any], target_route: str) -> Dict[str, Any]:
    parts = normalize_route_key(target_route).split("|")
    if len(parts) != 5:
        return dict(profile)
    asset, regime, structure, vol, risk = parts
    out = dict(profile)
    out["route_key"] = target_route
    out["asset_code"] = asset
    out["regime_code"] = regime
    out["structure_code"] = structure
    out["vol_code"] = vol
    out["risk_class"] = risk
    regime_name = REGIME_SHELVES.get(regime, "BALANCED_RANGE")
    out["regime"] = regime_name
    out["scenario"] = regime_name

    if regime == "R15":
        out = _apply_r15_recovery_behavior(out, risk=risk)
    elif risk == "DEFENSIVE":
        base = float(out.get("base_alloc_frac") or 0.5)
        out["base_alloc_frac"] = round(min(base, 0.35), 4)
        out["quote_alloc_frac"] = round(1.0 - float(out["base_alloc_frac"]), 4)
        max_exp = float(out.get("max_base_exposure_frac") or 0.7)
        if regime == "R7":
            out["max_base_exposure_frac"] = round(min(max_exp, 0.40), 4)
        elif regime == "R8":
            out["max_base_exposure_frac"] = round(min(max_exp, 0.25), 4)
        else:
            out["max_base_exposure_frac"] = round(min(max_exp, 0.50), 4)

    return out


def count_extended_coverage_gaps(
    templates_by_route: Dict[str, List[str]],
    *,
    min_critical: int = 100,
    min_profiles: int = 3,
) -> Tuple[int, List[str]]:
    """Deprecated wrapper — use measure_extended_coverage()."""
    report = measure_extended_coverage(
        templates_by_route,
        min_count=min_critical,
        min_profiles=min_profiles,
    )
    return report["optional_route_empty_total"], list(report["optional_empty_routes_total"])


def _finalize_seed_report(
    *,
    routes_checked: List[str],
    templates_by_route: Dict[str, List[str]],
    routes_seed_failed: List[str],
    min_profiles: int,
    optional_empty_total: int = 0,
    optional_empty_total_routes: Optional[List[str]] = None,
    r15_derived_from_r2: int = 0,
) -> Dict[str, Any]:
    mandatory_empty: List[str] = []
    optional_empty: List[str] = []
    for rk in routes_checked:
        n = len(templates_by_route.get(rk) or [])
        if n >= min_profiles:
            continue
        if is_mandatory_route(rk):
            mandatory_empty.append(rk)
        else:
            optional_empty.append(rk)

    mandatory_fail = len(mandatory_empty)
    optional_fail = len(optional_empty)
    if mandatory_fail:
        status = "fail"
    elif optional_fail:
        status = "warning"
    else:
        status = "ok"

    return {
        "mandatory_route_empty": mandatory_fail,
        "mandatory_empty_routes": mandatory_empty,
        "optional_route_empty_this_run": optional_fail,
        "optional_empty_routes_this_run": optional_empty,
        "optional_route_empty_total": optional_empty_total,
        "optional_empty_routes_total": optional_empty_total_routes or [],
        "optional_route_empty": optional_fail,
        "optional_empty_routes": optional_empty,
        "routes_seed_failed": routes_seed_failed,
        "r15_derived_from_r2": r15_derived_from_r2,
        "status": status,
        "pass": mandatory_fail == 0,
        "seed_target_pass": mandatory_fail == 0 and optional_fail == 0,
        "extended_pass": mandatory_fail == 0 and optional_empty_total == 0,
        "critical_route_empty": mandatory_fail,
    }


def seed_critical_shelves_in_templates(
    templates_by_route: Dict[str, List[str]],
    load_fn: LoadFn,
    *,
    per_route: int = 30,
    critical_routes: Optional[List[str]] = None,
    min_profiles: int = 3,
    min_critical_for_total: int = 100,
    sqlite_path: Optional[Path] = None,
    clone_mode: bool = True,
) -> Tuple[List[ParamTemplate], Dict[str, Any]]:
    """Clone or derive profiles onto empty critical shelves."""
    routes = list(critical_routes or MANDATORY_CRITICAL_ROUTES)
    inserted: List[ParamTemplate] = []
    seed_failed: List[str] = []
    stats: Dict[str, Any] = {
        "routes_checked": len(routes),
        "routes_seeded": 0,
        "profiles_converted": 0,
        "profiles_cloned": 0,
        "routes_already_ok": 0,
        "derivation_methods": {},
        "r15_derived_from_r2": 0,
        "clone_mode": clone_mode,
    }

    need = max(min_profiles, per_route // 3)
    reserved_keys: set[str] = set()

    for target in routes:
        target = normalize_route_key(target)
        existing = templates_by_route.get(target) or []
        shortage = need - len(existing)
        if shortage <= 0:
            stats["routes_already_ok"] += 1
            continue

        source_keys, method = _find_source_keys(target, templates_by_route)
        if not source_keys:
            seed_failed.append(target)
            continue
        target_regime = normalize_route_key(target).split("|")[1] if "|" in target else ""
        if target_regime == "R15" and "|R2|" in method:
            seed_failed.append(target)
            continue

        stats["derivation_methods"][target] = method
        if "|R2|" in method:
            stats["r15_derived_from_r2"] += 1

        seqs = (
            _alloc_clone_seqs(
                sqlite_path or Path("/dev/null"),
                target,
                shortage,
                reserved_keys=reserved_keys,
            )
            if clone_mode and sqlite_path is not None
            else list(range(SEED_CLONE_SEQ_BASE, SEED_CLONE_SEQ_BASE + shortage))
        )

        created = 0
        for i in range(shortage):
            src_key = source_keys[i % len(source_keys)]
            loaded = load_fn([src_key])
            if not loaded:
                continue
            src_tmpl = loaded[0]
            if clone_mode:
                cloned = _clone_template_for_target(
                    src_tmpl,
                    target,
                    method,
                    seq=seqs[i],
                    reserved_keys=reserved_keys,
                )
                inserted.append(cloned)
                templates_by_route.setdefault(target, []).append(cloned.template_key)
                stats["profiles_cloned"] += 1
            else:
                if src_tmpl.template_key in reserved_keys:
                    continue
                params = dict(src_tmpl.params or {})
                dps = dict(params.get("dps_profile") or {})
                dps = _apply_target_route(dps, target)
                dps["seed_derivation"] = method
                params["dps_profile"] = dps
                params["route_key"] = target
                params["scenario"] = dps.get("scenario")
                fixed = repair_v4_template(src_tmpl.model_copy(update={"params": params}))
                inserted.append(fixed)
                reserved_keys.add(fixed.template_key)
                templates_by_route.setdefault(target, []).append(fixed.template_key)
                src_route = method.split(":", 1)[1] if ":" in method else sibling_normal_route(target)
                old_list = templates_by_route.get(src_route) or []
                if fixed.template_key in old_list:
                    old_list.remove(fixed.template_key)
                stats["profiles_converted"] += 1
            created += 1

        if created:
            stats["routes_seeded"] += 1
        else:
            seed_failed.append(target)

    run_report = _finalize_seed_report(
        routes_checked=routes,
        templates_by_route=templates_by_route,
        routes_seed_failed=seed_failed,
        min_profiles=need,
        optional_empty_total=0,
        optional_empty_total_routes=[],
        r15_derived_from_r2=stats.get("r15_derived_from_r2", 0),
    )
    stats.update(run_report)
    stats["mandatory_routes"] = len(MANDATORY_CRITICAL_ROUTES)
    return inserted, stats


def _rebuild_selection_index(sqlite_path: Path, index_path: Path) -> None:
    import sqlite3
    from collections import defaultdict
    from datetime import datetime, timezone

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    index: dict[str, list[str]] = defaultdict(list)
    count = 0
    try:
        for row in conn.execute(
            "SELECT template_key, params_json FROM param_templates WHERE status = 'active'"
        ):
            params = json.loads(row["params_json"] or "{}")
            dps = params.get("dps_profile") or {}
            rk = normalize_route_key(str(dps.get("route_key") or params.get("route_key") or ""))
            if not rk:
                continue
            index[rk].append(str(row["template_key"]))
            count += 1
    finally:
        conn.close()
    payload = {
        "version": "v4.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles_indexed": count,
        "routes": len(index),
        "index_by_route_key": dict(index),
    }
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def seed_critical_shelves_sqlite(
    sqlite_path: Path,
    index_path: Path,
    *,
    per_route: int = 30,
    min_critical: int = 100,
    scope: str = "extended",
    export_gaps_dir: Optional[Path] = None,
    gaps_only: bool = False,
    clone_mode: bool = True,
) -> Dict[str, Any]:
    """
    Seed critical shelves in SQLite.

    scope:
      - mandatory: only MANDATORY_CRITICAL_ROUTES (release gate)
      - extended: enumerate_critical_routes(min_critical) — optional gaps → warning
      - all: same as extended with higher min_critical if passed
    """
    if scope == "mandatory":
        routes = list(MANDATORY_CRITICAL_ROUTES)
        clone_mode = True
    else:
        routes = extended_coverage_manifest(min_count=min_critical)

    if gaps_only and scope != "mandatory":
        pre = audit_extended_coverage_from_sqlite(sqlite_path, min_count=min_critical)
        gap_routes = list(pre.get("optional_empty_routes_total") or [])
        if gap_routes:
            routes = gap_routes
        stats_gap_prefilter = {
            "gaps_only": True,
            "gap_routes_targeted": len(routes),
        }
    else:
        stats_gap_prefilter = {"gaps_only": False}

    import sqlite3

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    templates_by_route: Dict[str, List[str]] = {}
    try:
        for row in conn.execute(
            "SELECT template_key, params_json FROM param_templates WHERE status = 'active'"
        ):
            params = json.loads(row["params_json"] or "{}")
            dps = params.get("dps_profile") or {}
            rk = normalize_route_key(str(dps.get("route_key") or params.get("route_key") or ""))
            if not rk:
                continue
            templates_by_route.setdefault(rk, []).append(str(row[0]))
    finally:
        conn.close()

    to_insert, stats = seed_critical_shelves_in_templates(
        templates_by_route,
        lambda keys: load_templates_by_keys(sqlite_path, keys),
        per_route=per_route,
        critical_routes=routes,
        min_critical_for_total=min_critical if scope != "mandatory" else 100,
        sqlite_path=sqlite_path,
        clone_mode=clone_mode,
    )
    stats.update(stats_gap_prefilter)

    if to_insert:
        if clone_mode:
            stats["templates_inserted"] = insert_param_templates(sqlite_path, to_insert)
        else:
            conn = sqlite3.connect(str(sqlite_path))
            try:
                for tmpl in to_insert:
                    conn.execute(
                        "UPDATE param_templates SET params_json = ?, final_action = ? WHERE template_key = ?",
                        (
                            json.dumps(tmpl.params, separators=(",", ":")),
                            tmpl.final_action,
                            tmpl.template_key,
                        ),
                    )
                conn.commit()
                stats["templates_updated"] = len(to_insert)
            finally:
                conn.close()

    _rebuild_selection_index(sqlite_path, index_path)

    post_index = audit_extended_coverage_from_sqlite(
        sqlite_path,
        min_count=min_critical if scope != "mandatory" else EXTENDED_COVERAGE_MIN_COUNT,
    )
    stats["optional_route_empty_total"] = post_index["optional_route_empty_total"]
    stats["optional_empty_routes_total"] = post_index["optional_empty_routes_total"]
    stats["extended_pass"] = post_index["extended_pass"]
    stats["coverage_source"] = post_index["source"]
    stats["extended_manifest_route_count"] = post_index["extended_manifest_route_count"]
    if post_index.get("gap_records"):
        stats["gap_records"] = post_index["gap_records"]
        if export_gaps_dir is not None:
            stats["gap_exports"] = write_gap_exports(
                post_index["gap_records"],
                export_gaps_dir,
            )

    if stats.get("mandatory_route_empty", 0):
        stats["status"] = "fail"
    elif stats.get("optional_route_empty_total", 0):
        stats["status"] = "warning"
    elif stats.get("optional_route_empty_this_run", 0):
        stats["status"] = "warning"
    else:
        stats["status"] = "ok"

    stats["scope"] = scope
    stats["critical_routes_checked"] = len(routes)
    stats["pass"] = stats.get("mandatory_route_empty", 0) == 0
    stats["exit_code"] = 0 if stats.get("pass") else 1
    return stats