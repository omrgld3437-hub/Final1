"""Amount distribution validation — full budget deployment rules."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.param_generator.amount_distribution import DISTRIBUTIONS


APPROVED_PATTERNS = {
    2: {(35, 65), (30, 70), (40, 60)},
    3: {(15, 30, 55), (12, 28, 60), (20, 30, 50)},
    4: {(10, 20, 30, 40), (8, 17, 30, 45), (12, 23, 30, 35)},
    5: {(7, 13, 20, 25, 35), (6, 12, 18, 24, 40), (9, 15, 22, 26, 28)},
}


def _norm_dist(dist: List[float]) -> Tuple[int, ...]:
    vals = [int(round(float(x))) for x in dist]
    if sum(vals) == 1 and len(vals) > 1:
        vals = [int(round(float(x) * 100)) for x in dist]
    return tuple(vals)


def validate_distribution(dist: List[float], grid_count: int) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not dist:
        return True, []
    total = sum(float(x) for x in dist)
    if abs(total - 100) > 1.5 and abs(total - 1.0) > 0.02:
        errors.append("DISTRIBUTION_NOT_100")
    norm = _norm_dist(dist)
    n = len(norm)
    if n != grid_count:
        errors.append("DIST_LENGTH_MISMATCH")
    if n == 2 and abs(norm[0] - norm[1]) <= 2:
        errors.append("FIFTY_FIFTY_DIST")
    if n == 3 and max(norm) - min(norm) < 10:
        errors.append("EQUAL_THREE_GRID_DIST")
    if n >= 2 and norm[-1] < norm[0]:
        errors.append("FAR_GRID_LOW_WEIGHT")
    approved = APPROVED_PATTERNS.get(n, set())
    if approved and norm not in approved:
        # allow small rounding drift
        close = any(sum(abs(a - b) for a, b in zip(norm, pat)) <= 3 for pat in approved)
        if not close:
            errors.append("NON_STANDARD_DISTRIBUTION")
    return len(errors) == 0, errors


def audit_all_profiles(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    passed = 0
    failed = 0
    reason_counts: Counter = Counter()

    for p in profiles:
        profile_ok = True
        for side in ("buy", "sell"):
            n = int(p.get(f"{side}_grid_count") or 0)
            dist = p.get(f"{side}_distribution") or []
            if n <= 0:
                continue
            ok, errs = validate_distribution(dist, n)
            if not ok:
                profile_ok = False
                for e in errs:
                    reason_counts[f"{side}_{e}"] += 1
        if profile_ok:
            passed += 1
        else:
            failed += 1

    pass_rate = round(100.0 * passed / max(len(profiles), 1), 4)
    return {
        "total_profiles": len(profiles),
        "passed": passed,
        "failed": failed,
        "failure_reasons": dict(reason_counts),
        "approved_patterns": {str(k): [list(x) for x in v] for k, v in APPROVED_PATTERNS.items()},
        "spec_note": "Quote/base fully allocated across grids; no reserve buckets.",
        "pass_rate_pct": pass_rate,
        "status": "pass" if pass_rate >= 99.0 else "fail",
    }
