#!/usr/bin/env python3
"""Enhance v3 param pool — coverage gaps, grid/distribution quality, fingerprint diversity."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_generator.amount_distribution import (
    geometric_distribution,
    select_distribution_mode,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    apply_side_structure_multiplier,
    compute_grid_ladder,
    compute_trailing_pct,
    enforce_grid_spacing_minimums,
)
from app.services.dynamic_param_score.param_generator.param_library_builder import (
    DPS_ENGINE_V2,
    _cell_to_template,
)
from app.services.dynamic_param_score.param_generator.scenario_matrix import scenario_key
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    load_templates_from_sqlite,
    write_pool_sqlite,
)
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache
from tools.param_quality_engine.coverage_gap_analyzer import (
    _cell_key_from_profile,
    _required_cells,
    analyze_coverage,
)
from tools.param_quality_engine.profile_normalizer import (
    behavior_fingerprint,
    template_to_audit_profile,
)

_STRUCTURE_SHORT = {
    "HI": "higher_highs_only",
    "LO": "lower_lows_only",
    "BO": "both",
    "NE": "neither",
}


def _approved_dist(n: int, *, fee_class: str, structure: str, risk: str, variant: int) -> List[float]:
    mode = select_distribution_mode(
        risk_level=risk,
        fee_class=fee_class,
        structure=structure,
    )
    modes = ["normal", "defensive", "aggressive"]
    mode = modes[(modes.index(mode) + variant) % len(modes)]
    return geometric_distribution(max(1, n), mode)  # type: ignore[arg-type]


def _variant_idx(key: str) -> int:
    import re

    m = re.search(r"_p(\d+)$", key or "")
    if m:
        return int(m.group(1))
    m2 = re.search(r"_v(\d+)$", key or "")
    return int(m2.group(1)) if m2 else hash(key) % 1000


def _repair_template_params(t: ParamTemplate) -> ParamTemplate:
    p = dict(t.params or {})
    dp = dict(p.get("dps_profile") or {})
    variant = _variant_idx(t.template_key)
    asset = dp.get("asset_class") or p.get("asset_class") or "MID_CAP"
    fee_class = dp.get("fee_class") or "normal_fee"
    structure = dp.get("structure") or "neither"
    risk = dp.get("risk_level") or "NORMAL"

    buy_n = int(dp.get("buy_grid_count") or p.get("buy_grid_count") or 0)
    sell_n = int(dp.get("sell_grid_count") or p.get("sell_grid_count") or 0)

    def _ladder(side: str, n: int, v: int) -> List[float]:
        if n <= 0:
            return []
        sp_key = f"{side}_spacing_min_pct"
        first = float(dp.get(f"{side}_grid_pcts", [None])[0] if dp.get(f"{side}_grid_pcts") else 0) or 0
        if first <= 0:
            atr_mult = float(p.get(f"{side}_spacing_atr_mult") or 0.9)
            first = max(float(p.get(sp_key) or 0.45) * 1.5, 1.2 if asset == "BTC_ETH_MAJOR" else 1.8)
        first = round(first * (1.0 + 0.025 * (v % 17)), 4)
        grids = compute_grid_ladder(first, n, variant_idx=v)
        grids = apply_side_structure_multiplier(grids, side=side, structure=structure, fee_class=fee_class)
        return enforce_grid_spacing_minimums(grids, asset)

    buy_grids = dp.get("buy_grid_pcts") or _ladder("buy", buy_n, variant)
    sell_grids = dp.get("sell_grid_pcts") or _ladder("sell", sell_n, variant + 3)
    buy_n = len(buy_grids) if buy_grids else buy_n
    sell_n = len(sell_grids) if sell_grids else sell_n

    if buy_n > 0:
        p["buy_qty_distribution"] = _approved_dist(buy_n, fee_class=fee_class, structure=structure, risk=risk, variant=variant)
        p["buy_grid_count"] = buy_n
        p["buy_grid_ladder_pcts"] = buy_grids
    if sell_n > 0:
        p["sell_qty_distribution"] = _approved_dist(sell_n, fee_class=fee_class, structure=structure, risk=risk, variant=variant + 1)
        p["sell_grid_count"] = sell_n
        p["sell_grid_ladder_pcts"] = sell_grids

    trail = float(p.get("min_trailing_pct") or compute_trailing_pct(
        (buy_grids or sell_grids or [1.5])[0], asset, fee_class=fee_class
    ))
    p["min_trailing_pct"] = trail

    if dp:
        dp.update({
            "buy_grid_count": buy_n,
            "sell_grid_count": sell_n,
            "buy_grid_pcts": buy_grids,
            "sell_grid_pcts": sell_grids,
            "buy_distribution": [int(x * 100) for x in p.get("buy_qty_distribution") or []],
            "sell_distribution": [int(x * 100) for x in p.get("sell_qty_distribution") or []],
            "buy_trailing_pct": trail,
            "sell_trailing_pct": trail,
        })
        p["dps_profile"] = dp

    updated = t.model_copy(update={"params": p})
    return updated


def _fill_coverage_gaps(templates: List[ParamTemplate], required: Set[str]) -> Tuple[List[ParamTemplate], int]:
    covered = {_cell_key_from_profile(template_to_audit_profile(t)) for t in templates}
    missing = sorted(required - covered)
    added = 0
    out = list(templates)
    seq_base = len(templates) + 1

    for i, key in enumerate(missing):
        parts = key.split("|")
        if len(parts) < 6:
            continue
        for variant_try in range(4):
            cell = {
                "asset_class": parts[0],
                "budget_class": parts[1],
                "regime": parts[2],
                "volatility_bin": parts[3],
                "structure": parts[4],
                "fee_class": parts[5],
                "variant_idx": (i + variant_try) % 5,
            }
            tmpl = _cell_to_template(cell, seq_base + i * 4 + variant_try)
            if tmpl is None:
                continue
            repaired = _repair_template_params(tmpl)
            ck = _cell_key_from_profile(template_to_audit_profile(repaired))
            if ck in required and ck not in covered:
                out.append(repaired)
                covered.add(ck)
                added += 1
                break
    return out, added


def _force_fingerprint_diversity(templates: List[ParamTemplate]) -> List[ParamTemplate]:
    """Ensure each template has a distinct behavior fingerprint via grid perturbation."""
    seen: Dict[str, str] = {}
    out: List[ParamTemplate] = []
    for idx, t in enumerate(templates):
        repaired = _repair_template_params(t)
        fp = behavior_fingerprint(template_to_audit_profile(repaired))
        if fp not in seen:
            seen[fp] = repaired.template_key
            out.append(repaired)
            continue
        p = dict(repaired.params or {})
        variant = idx % 97 + 1
        asset = p.get("asset_class") or "MID_CAP"
        for side, nkey, lkey in (
            ("buy", "buy_grid_count", "buy_grid_ladder_pcts"),
            ("sell", "sell_grid_count", "sell_grid_ladder_pcts"),
        ):
            n = int(p.get(nkey) or 0)
            if n <= 0:
                continue
            first = 1.2 if asset == "BTC_ETH_MAJOR" else 1.8
            first = round(first * (1.0 + 0.018 * variant), 4)
            p[lkey] = enforce_grid_spacing_minimums(
                compute_grid_ladder(first, n, variant_idx=variant + idx), asset
            )
        perturbed = repaired.model_copy(update={"params": p})
        out.append(_repair_template_params(perturbed))
    return out


def enhance_pool(templates: List[ParamTemplate]) -> Tuple[List[ParamTemplate], Dict[str, Any]]:
    repaired = [_repair_template_params(t) for t in templates]
    required = _required_cells()
    total_added = 0
    for _ in range(5):
        repaired, added = _fill_coverage_gaps(repaired, required)
        total_added += added
        cov = analyze_coverage([template_to_audit_profile(t) for t in repaired if t.status == "active"])
        if (cov.get("coverage_required_pct") or 0) >= 95.0:
            break
    repaired = _force_fingerprint_diversity(repaired)

  # fee_bad alignment: deployable fee_bad must be ACTIVE_DEFENSIVE*
    fee_fixed = 0
    for i, t in enumerate(repaired):
        p = dict(t.params or {})
        dp = dict(p.get("dps_profile") or {})
        fee = dp.get("fee_class") or ""
        if fee == "fee_bad" and t.deployable and t.final_action in ("WAIT", "NO_TRADE"):
            repaired[i] = t.model_copy(update={
                "final_action": "ACTIVE_DEFENSIVE_GRID",
                "profile_family": "ACTIVE_DEFENSIVE_GRID_PROFILE",
                "deployable": True,
            })
            fee_fixed += 1

    profiles = [template_to_audit_profile(t) for t in repaired if t.status == "active"]
    fps = {behavior_fingerprint(p) for p in profiles}
    cov = analyze_coverage(profiles)
    near_dup = len(profiles) - len(fps)
    meta = {
        "templates_total": len(repaired),
        "coverage_gaps_added": total_added,
        "fee_bad_action_fixed": fee_fixed,
        "unique_fingerprints": len(fps),
        "near_duplicate_rate_pct": round(100.0 * near_dup / max(len(profiles), 1), 4),
        "coverage_required_pct": cov.get("coverage_required_pct"),
    }
    return repaired, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Enhance param pool quality in-place")
    parser.add_argument("--sqlite", default="data/param_pool/v3/param_pool_v3.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.sqlite)
    templates = load_templates_from_sqlite(path)
    enhanced, meta = enhance_pool(templates)

    print(f"Templates: {meta['templates_total']}")
    print(f"Coverage gaps added: {meta['coverage_gaps_added']}")
    print(f"Unique fingerprints: {meta['unique_fingerprints']}")
    print(f"Coverage required %: {meta['coverage_required_pct']}")
    print(f"Fee_bad action fixed: {meta['fee_bad_action_fixed']}")

    if args.dry_run:
        return 0

    version = enhanced[0].version if enhanced else "v3.0.0"
    write_pool_sqlite(enhanced, path, version)
    clear_pool_cache()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
