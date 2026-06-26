"""Coverage gap analysis — scenario matrix vs pool."""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any, Dict, List, Set

from app.services.dynamic_param_score.param_generator.scenario_matrix import (
    scenario_cells,
    scenario_key,
    total_primary_combinations,
)

from tools.param_quality_engine.config import REQUIRED_COVERAGE_REGIMES, REQUIRED_COVERAGE_BUDGETS


def _cell_key_from_profile(p: Dict[str, Any]) -> str:
    return scenario_key({
        "asset_class": p.get("asset_class") or "",
        "budget_class": p.get("budget_class") or "",
        "regime": p.get("regime") or "",
        "volatility_bin": p.get("volatility_bin") or "",
        "structure": p.get("structure") or "neither",
        "fee_class": p.get("fee_class") or "",
    })


def _required_cells() -> Set[str]:
    """Primary cells that must be covered for pass (subset of full matrix)."""
    out: Set[str] = set()
    for cell in scenario_cells():
        if cell.get("regime") not in REQUIRED_COVERAGE_REGIMES:
            continue
        if cell.get("budget_class") not in REQUIRED_COVERAGE_BUDGETS:
            continue
        out.add(scenario_key(cell))
    return out


def analyze_coverage(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    expected: Set[str] = {scenario_key(c) for c in scenario_cells()}
    required = _required_cells()
    covered: Counter = Counter()
    for p in profiles:
        covered[_cell_key_from_profile(p)] += 1

    filled_expected = set(covered.keys()) & expected
    filled_required = set(covered.keys()) & required
    missing_required = sorted(required - filled_required)
    missing_total = sorted(expected - set(covered.keys()))

    coverage_total_pct = round(100.0 * len(filled_expected) / max(len(expected), 1), 4)
    coverage_required_pct = round(100.0 * len(filled_required) / max(len(required), 1), 4)

    if coverage_required_pct >= 95:
        status = "pass"
    elif coverage_required_pct >= 90:
        status = "warning"
    else:
        status = "fail"

    return {
        "expected_cells": len(expected),
        "required_cells": len(required),
        "filled_cells": len(filled_expected),
        "filled_required_cells": len(filled_required),
        "missing_required_cells": len(missing_required),
        "missing_cells": len(missing_total),
        "missing_required_cells_sample": missing_required[:100],
        "missing_cells_sample": missing_total[:100],
        "coverage_total_pct": coverage_total_pct,
        "coverage_required_pct": coverage_required_pct,
        "coverage_pct": coverage_required_pct,
        "cells_with_profiles": len(covered),
        "primary_combinations_expected": total_primary_combinations(),
        "status": status,
        "gap_high": coverage_required_pct < 90,
    }


def coverage_matrix_csv(profiles: List[Dict[str, Any]]) -> str:
    covered: Counter = Counter()
    for p in profiles:
        covered[_cell_key_from_profile(p)] += 1
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["cell_key", "profile_count"])
    for key, count in sorted(covered.items()):
        w.writerow([key, count])
    return buf.getvalue()
