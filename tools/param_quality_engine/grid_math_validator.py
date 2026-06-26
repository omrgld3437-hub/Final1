"""Grid math validation — asset-class rules and critical failures."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.param_generator.candidate_validator import (
    hard_validate_profile,
    soft_validate_profile,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    MAX_TRAILING_FRAC,
    MIN_GRID_SPACING,
    MIN_NET_ROOM,
)


REASON_MAP = {
    "buy_first_grid_below_asset_min": "FIRST_GRID_TOO_LOW",
    "sell_first_grid_below_asset_min": "FIRST_GRID_TOO_LOW",
    "buy_first_grid_below_1pct": "FIRST_GRID_BELOW_1PCT",
    "sell_first_grid_below_1pct": "FIRST_GRID_BELOW_1PCT",
    "buy_grid_spacing_too_tight": "GRID_SPACING_TOO_LOW",
    "sell_grid_spacing_too_tight": "GRID_SPACING_TOO_LOW",
    "buy_trailing_too_high": "TRAILING_TOO_CLOSE",
    "sell_trailing_too_high": "TRAILING_TOO_CLOSE",
    "buy_net_room_too_small": "NET_ROOM_TOO_LOW",
    "sell_net_room_too_small": "NET_ROOM_TOO_LOW",
    "fee_bad_must_not_wait": "FEE_BAD_NOT_WIDENED",
    "buy_second_grid_ratio_fail": "SECOND_GRID_RATIO_FAIL",
    "sell_second_grid_ratio_fail": "SECOND_GRID_RATIO_FAIL",
}


def _extra_grid_checks(profile: Dict[str, Any]) -> List[str]:
    """Spec red-flag checks beyond hard_validate_profile."""
    failures: List[str] = []
    asset = profile.get("asset_class") or "MID_CAP"
    asset_min = ASSET_MIN_GRID.get(asset, 1.80)

    for side in ("buy", "sell"):
        grids = profile.get(f"{side}_grid_pcts") or []
        if not grids:
            continue
        first = float(grids[0])
        trail = float(profile.get(f"{side}_trailing_pct") or 0)
        if first < 1.0:
            failures.append("FIRST_GRID_BELOW_1PCT")
        if first in (0.5, 0.6, 0.7) or first < 0.8:
            failures.append("DAR_SCALP_GRID")
        if len(grids) >= 2:
            gap = grids[1] - grids[0]
            if gap < MIN_GRID_SPACING.get(asset, 1.5) - 0.01:
                failures.append("GRID_SPACING_TOO_LOW")
            if abs(grids[1] / max(first, 0.01) - 2.0) < 0.15 and len(grids) == 2:
                dist = profile.get(f"{side}_distribution") or []
                if len(dist) == 2 and abs(dist[0] - dist[1]) < 3:
                    failures.append("FIFTY_FIFTY_CLOSE_GRIDS")
        max_frac = MAX_TRAILING_FRAC.get(asset, 0.28)
        if trail > first * max_frac + 0.01:
            failures.append("TRAILING_TOO_CLOSE")
        min_net = MIN_NET_ROOM.get(asset, 1.0)
        if trail > 0 and (first - trail) < min_net - 0.01:
            failures.append("NET_ROOM_TOO_LOW")

    if profile.get("fee_class") == "fee_bad":
        fa = str(profile.get("final_action") or "").upper()
        deployable = profile.get("deployable")
        if deployable is False or fa in ("NO_TRADE", "WAIT", "SAFE_WAIT"):
            pass
        else:
            first = float((profile.get("buy_grid_pcts") or profile.get("sell_grid_pcts") or [0])[0])
            if first < asset_min * 1.05:
                failures.append("FEE_BAD_NOT_WIDENED")

    vol = profile.get("volatility_bin") or ""
    if vol in ("75_90", "90_100"):
        first = float((profile.get("buy_grid_pcts") or [99])[0])
        if first < asset_min:
            failures.append("HIGH_VOL_NARROW_GRID")

    budget = profile.get("budget_class") or ""
    if budget in ("10_25", "25_50"):
        first = float((profile.get("buy_grid_pcts") or [99])[0])
        if first < asset_min:
            failures.append("SMALL_BUDGET_NARROW_GRID")

    return failures


def _is_management_only_profile(profile: Dict[str, Any]) -> bool:
    fa = str(profile.get("final_action") or "").upper()
    if profile.get("deployable") is False:
        return True
    if fa in ("NO_TRADE", "WAIT", "SAFE_WAIT", "SELL_MANAGEMENT_ONLY"):
        return True
    pid = str(profile.get("profile_id") or "").upper()
    return "NO_DATA" in pid or "NO_TRADE" in pid


def validate_profile_grid_math(profile: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    if _is_management_only_profile(profile):
        buy_n = int(profile.get("buy_grid_count") or 0)
        sell_n = int(profile.get("sell_grid_count") or 0)
        if buy_n == 0 and sell_n == 0:
            return True, [], []
    hard_ok, hard_errs = hard_validate_profile(profile)
    soft_score, soft_warns = soft_validate_profile(profile)
    mapped = [REASON_MAP.get(e, e.upper()) for e in hard_errs]
    mapped.extend(_extra_grid_checks(profile))
    if _is_management_only_profile(profile):
        mapped = [m for m in mapped if m not in ("FEE_BAD_NOT_WIDENED", "SMALL_BUDGET_NARROW_GRID")]
    critical = [m for m in mapped if m in {
        "FIRST_GRID_BELOW_1PCT", "DAR_SCALP_GRID", "FEE_BAD_NOT_WIDENED",
        "FIFTY_FIFTY_CLOSE_GRIDS", "SMALL_BUDGET_NARROW_GRID",
    }]
    ok = hard_ok and not critical
    return ok, list(dict.fromkeys(mapped)), soft_warns


def audit_all_profiles(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    passed = 0
    failed = 0
    critical_failures = 0
    warnings = 0
    reason_counts: Counter = Counter()
    bad_samples: List[Dict[str, Any]] = []

    for p in profiles:
        ok, errs, soft_warns = validate_profile_grid_math(p)
        warnings += len(soft_warns)
        for e in errs:
            reason_counts[e] += 1
        if ok:
            passed += 1
        else:
            failed += 1
            if any(
                x in errs
                for x in (
                    "FIRST_GRID_BELOW_1PCT",
                    "FEE_BAD_NOT_WIDENED",
                    "DAR_SCALP_GRID",
                    "FIFTY_FIFTY_CLOSE_GRIDS",
                )
            ):
                critical_failures += 1
            if len(bad_samples) < 300:
                bad_samples.append({
                    "profile_id": p.get("profile_id"),
                    "errors": errs,
                    "warnings": soft_warns,
                })

    pass_rate = round(100.0 * passed / max(len(profiles), 1), 4)
    return {
        "total_profiles": len(profiles),
        "passed": passed,
        "failed": failed,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "failure_reasons": dict(reason_counts),
        "bad_samples": bad_samples[:100],
        "pass_rate_pct": pass_rate,
        "status": "pass" if pass_rate >= 99.0 and critical_failures == 0 else "fail",
    }
