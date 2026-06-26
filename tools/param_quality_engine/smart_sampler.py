"""Katman 2 — Smart Coverage Sampling."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Dict, List, Set

from tools.param_quality_engine.config import SAMPLING_CELL_DIMS


def _cell_key(p: Dict[str, Any]) -> str:
    return "|".join(str(p.get(d) or "") for d in SAMPLING_CELL_DIMS)


def _grid_width(p: Dict[str, Any]) -> float:
    buy = p.get("buy_grid_pcts") or []
    sell = p.get("sell_grid_pcts") or []
    vals = [float(x) for x in buy + sell if x]
    if len(vals) < 2:
        return float(vals[0]) if vals else 0.0
    return max(vals) - min(vals)


def _min_notional_proximity(p: Dict[str, Any]) -> float:
    """Lower = closer to min-notional edge (small budget + few grids)."""
    budget = float(p.get("min_budget_required") or 25)
    grids = int(p.get("buy_grid_count") or 0) + int(p.get("sell_grid_count") or 0)
    return budget / max(grids, 1)


def _fee_risk_score(p: Dict[str, Any]) -> float:
    fee = p.get("fee_class") or "normal_fee"
    first = float((p.get("buy_grid_pcts") or p.get("sell_grid_pcts") or [99])[0])
    base = {"fee_bad": 100, "high_fee": 60, "normal_fee": 20, "low_fee": 5}.get(fee, 20)
    return base + max(0, 3.0 - first) * 10


def select_representatives(
    profiles: List[Dict[str, Any]],
    *,
    sample_per_cell: int = 7,
) -> List[Dict[str, Any]]:
    """Pick representative profiles from each scenario cell."""
    cells: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in profiles:
        cells[_cell_key(p)].append(p)

    selected: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def _pick(pool: List[Dict[str, Any]], key_fn, reverse: bool = True) -> None:
        if not pool:
            return
        ranked = sorted(pool, key=key_fn, reverse=reverse)
        pid = str(ranked[0].get("profile_id") or "")
        if pid and pid not in seen:
            seen.add(pid)
            selected.append(ranked[0])

    pick_fns = [
        (lambda p: float(p.get("score_prior") or 0), True),
        (lambda p: float(p.get("score_prior") or 0), False),
        (lambda p: float(p.get("score_prior") or 0), None),  # median
        (lambda p: _grid_width(p), False),
        (lambda p: _grid_width(p), True),
        (lambda p: _min_notional_proximity(p), True),
        (lambda p: _fee_risk_score(p), True),
    ]

    for cell_profiles in cells.values():
        for i, (key_fn, reverse) in enumerate(pick_fns[:sample_per_cell]):
            if reverse is None:
                scores = sorted(float(p.get("score_prior") or 0) for p in cell_profiles)
                med = statistics.median(scores) if scores else 0
                _pick(cell_profiles, lambda p, m=med: -abs(float(p.get("score_prior") or 0) - m), True)
            else:
                _pick(cell_profiles, key_fn, reverse)

    return selected


def audit_sample_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    """Scenario-fit checks on a single representative profile."""
    issues: List[str] = []
    structure = p.get("structure") or "neither"
    buy = p.get("buy_grid_pcts") or []
    sell = p.get("sell_grid_pcts") or []

    if structure == "lower_lows_only" and buy and sell:
        if float(buy[0]) <= float(sell[0]) * 1.05:
            issues.append("lower_lows_buy_not_wider")
    if structure == "higher_highs_only" and buy and sell:
        if float(sell[0]) <= float(buy[0]) * 1.05:
            issues.append("higher_highs_sell_not_wider")
    if p.get("fee_class") == "fee_bad":
        asset_min = 1.2 if p.get("asset_class") == "BTC_ETH_MAJOR" else 1.8
        first = float((buy or sell or [0])[0])
        if first < asset_min * 1.05:
            issues.append("fee_bad_not_widened")
    if p.get("budget_class") in ("10_25", "25_50"):
        total_grids = int(p.get("buy_grid_count") or 0) + int(p.get("sell_grid_count") or 0)
        if total_grids > 6:
            issues.append("small_budget_too_many_grids")

    return {
        "profile_id": p.get("profile_id"),
        "issues": issues,
        "ok": len(issues) == 0,
    }


def run_smart_sample_audit(
    profiles: List[Dict[str, Any]],
    *,
    sample_per_cell: int = 7,
) -> Dict[str, Any]:
    representatives = select_representatives(profiles, sample_per_cell=sample_per_cell)
    results = [audit_sample_profile(p) for p in representatives]
    failed = [r for r in results if not r["ok"]]

    return {
        "layer": "smart-sample",
        "total_pool_profiles": len(profiles),
        "cells_in_pool": len({_cell_key(p) for p in profiles}),
        "representatives_selected": len(representatives),
        "sample_per_cell": sample_per_cell,
        "audit_results": results,
        "failed_count": len(failed),
        "failed_samples": failed[:100],
        "all_pass": len(failed) == 0,
        "SMART_SAMPLE_AUDIT_SUMMARY": {
            "representatives_tested": len(representatives),
            "failed": len(failed),
            "pass_rate_pct": round(100.0 * (len(results) - len(failed)) / max(len(results), 1), 4),
        },
    }
