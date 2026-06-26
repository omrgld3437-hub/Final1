"""Profile schema validation against audit spec."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from tools.param_quality_engine.config import LEGACY_WAIT_MARKERS, REQUIRED_SCHEMA_FIELDS


def validate_profile_schema(profile: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    for field in REQUIRED_SCHEMA_FIELDS:
        if field not in profile or profile[field] is None:
            errors.append(f"MISSING_FIELD:{field}")
    for side in ("buy", "sell"):
        n = int(profile.get(f"{side}_grid_count") or 0)
        pcts = profile.get(f"{side}_grid_pcts") or []
        dist = profile.get(f"{side}_distribution") or []
        if n <= 0:
            if pcts:
                errors.append(f"GRID_COUNT_MISMATCH:{side}")
            continue
        if len(pcts) != n:
            if len(pcts) > 0 and abs(len(pcts) - n) <= 1:
                pass
            else:
                errors.append(f"GRID_COUNT_MISMATCH:{side}")
        if dist and len(dist) != n:
            errors.append(f"DIST_COUNT_MISMATCH:{side}")
        if any(float(x) <= 0 for x in pcts):
            errors.append(f"ZERO_OR_NEGATIVE_GRID:{side}")
        if dist:
            total = sum(float(x) for x in dist)
            if abs(total - 100) > 1.0 and abs(total - 1.0) > 0.02:
                errors.append(f"DISTRIBUTION_NOT_100:{side}")
    for side in ("buy", "sell"):
        trail = float(profile.get(f"{side}_trailing_pct") or 0)
        if trail < 0:
            errors.append(f"NEGATIVE_TRAILING:{side}")
    pid = str(profile.get("profile_id") or profile.get("template_key") or "")
    if any(m in pid.upper() for m in LEGACY_WAIT_MARKERS):
        errors.append("LEGACY_WAIT_PROFILE_ID")
    if str(profile.get("final_action") or "").upper() in ("WAIT", "NO_TRADE", "SAFE_WAIT"):
        if profile.get("fee_class") == "fee_bad" and profile.get("deployable") is not False:
            if "DEFENSIVE" not in str(profile.get("final_action") or "").upper():
                errors.append("LEGACY_FEE_BAD_WAIT")
    return len(errors) == 0, errors


def audit_all_profiles(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    passed = 0
    failed = 0
    reason_counts: Counter = Counter()
    duplicate_ids: List[str] = []
    seen_ids: Dict[str, int] = {}
    bad_samples: List[Dict[str, Any]] = []

    for p in profiles:
        pid = str(p.get("profile_id") or p.get("template_key") or "")
        if pid in seen_ids:
            duplicate_ids.append(pid)
            reason_counts["DUPLICATE_PROFILE_ID"] += 1
        else:
            seen_ids[pid] = 1
        ok, errs = validate_profile_schema(p)
        if ok:
            passed += 1
        else:
            failed += 1
            for e in errs:
                reason_counts[e.split(":")[0]] += 1
            if len(bad_samples) < 200:
                bad_samples.append({"profile_id": pid, "errors": errs})

    return {
        "total_profiles": len(profiles),
        "passed": passed,
        "failed": failed,
        "duplicate_profile_ids": len(duplicate_ids),
        "duplicate_samples": duplicate_ids[:50],
        "failure_reasons": dict(reason_counts),
        "bad_samples": bad_samples,
        "pass_rate_pct": round(100.0 * passed / max(len(profiles), 1), 4),
    }
