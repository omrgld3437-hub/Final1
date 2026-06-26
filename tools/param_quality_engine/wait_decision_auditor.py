"""WAIT decision audit — hard safety only."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from tools.param_quality_engine.config import INVALID_WAIT_REASONS, VALID_HARD_WAIT_REASONS

_INTENTIONAL_NO_TRADE_FAMILIES = frozenset({
    "NO_TRADE_PROFILE",
    "WAIT_PROFILE",
    "MICRO_BUDGET_WAIT_PROFILE",
    "LOW_LIQUIDITY_WAIT_PROFILE",
    "VOL_EXTREME_SAFE_WAIT_PROFILE",
    "VOL_LOW_NOISE_WAIT_PROFILE",
    "ORDERBOOK_TIGHT_WAIT_PROFILE",
})


def _is_intentional_management_profile(profile: Dict[str, Any]) -> bool:
    family = str(profile.get("profile_family") or "")
    if family in _INTENTIONAL_NO_TRADE_FAMILIES:
        return True
    fa = str(profile.get("final_action") or "").upper()
    if fa in ("NO_TRADE", "WAIT") and profile.get("deployable") is False:
        return True
    pid = str(profile.get("profile_id") or profile.get("template_key") or "").upper()
    if "DUMP_RISK" in pid or "NO_TRADE" in pid:
        return True
    return False


def audit_profile_wait(profile: Dict[str, Any]) -> Dict[str, Any]:
    fa = str(profile.get("final_action") or profile.get("safety_level") or "").upper()
    issues: List[str] = []

    if _is_intentional_management_profile(profile):
        return {
            "profile_id": profile.get("profile_id"),
            "final_action": fa,
            "invalid_wait_reasons": [],
            "is_invalid_wait": False,
            "intentional_management": True,
        }

    if fa in ("WAIT", "NO_TRADE", "SAFE_WAIT", "WAIT_SAFETY"):
        fee = profile.get("fee_class") or ""
        if fee == "fee_bad":
            issues.append("fee_bad")
        if profile.get("budget_class") in ("10_25", "25_50"):
            issues.append("small_budget")
        regime = str(profile.get("regime") or "").lower()
        if "balanced" in regime:
            issues.append("balanced_range")
        if profile.get("volatility_bin") in ("0_10", "10_25"):
            issues.append("low_volatility")
        first = float((profile.get("buy_grid_pcts") or [99])[0]) if profile.get("buy_grid_pcts") else 99.0
        if first < 1.5 and profile.get("buy_grid_count", 0) > 0:
            issues.append("grid_too_close")

    invalid = [i for i in issues if i in INVALID_WAIT_REASONS]
    return {
        "profile_id": profile.get("profile_id"),
        "final_action": fa,
        "invalid_wait_reasons": invalid,
        "is_invalid_wait": bool(invalid and fa.startswith(("WAIT", "NO_TRADE", "SAFE"))),
    }


def audit_all_profiles(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    invalid_waits = 0
    valid_waits = 0
    intentional = 0
    reason_counts: Counter = Counter()
    fee_bad_wait = 0
    deployable_fee_bad = 0

    for p in profiles:
        r = audit_profile_wait(p)
        if r.get("intentional_management"):
            intentional += 1
            continue
        if p.get("fee_class") == "fee_bad":
            fa = str(p.get("final_action") or "").upper()
            if fa in ("WAIT", "NO_TRADE") and p.get("deployable") is not False:
                fee_bad_wait += 1
            elif "DEFENSIVE" in fa or "ACTIVE" in fa or "GRID" in fa:
                deployable_fee_bad += 1
        if r["is_invalid_wait"]:
            invalid_waits += 1
            for reason in r["invalid_wait_reasons"]:
                reason_counts[reason] += 1
        elif str(p.get("final_action") or "").upper() in ("WAIT", "NO_TRADE", "SAFE_WAIT"):
            valid_waits += 1

    return {
        "total_profiles": len(profiles),
        "invalid_wait_profiles": invalid_waits,
        "intentional_management_profiles": intentional,
        "valid_hard_wait_profiles": valid_waits,
        "invalid_wait_reasons": dict(reason_counts),
        "fee_bad_wait_count": fee_bad_wait,
        "fee_bad_active_defensive_count": deployable_fee_bad,
        "valid_hard_wait_reasons": sorted(VALID_HARD_WAIT_REASONS),
        "invalid_wait_reasons_spec": sorted(INVALID_WAIT_REASONS),
        "pass": invalid_waits == 0 and fee_bad_wait == 0,
    }
