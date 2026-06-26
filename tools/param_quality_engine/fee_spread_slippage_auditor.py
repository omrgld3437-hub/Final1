"""Fee / spread / slippage net-room audit."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from app.services.dynamic_param_score.param_generator.grid_math import MIN_NET_ROOM


_INTENTIONAL_FAMILIES = frozenset({
    "NO_TRADE_PROFILE",
    "WAIT_PROFILE",
    "MICRO_BUDGET_WAIT_PROFILE",
    "LOW_LIQUIDITY_WAIT_PROFILE",
})


def _skip_fee_bad_wait_check(profile: Dict[str, Any]) -> bool:
    if profile.get("deployable") is False:
        return True
    family = str(profile.get("profile_family") or "")
    if family in _INTENTIONAL_FAMILIES:
        return True
    pid = str(profile.get("profile_id") or profile.get("template_key") or "").upper()
    return "NO_DATA" in pid or "NO_TRADE" in pid or "DUMP_RISK" in pid


DEFAULT_COSTS = {
    "low_fee": {"fee": 0.06, "spread": 0.02, "slippage": 0.03, "buffer": 0.05},
    "normal_fee": {"fee": 0.10, "spread": 0.02, "slippage": 0.04, "buffer": 0.06},
    "high_fee": {"fee": 0.14, "spread": 0.03, "slippage": 0.05, "buffer": 0.07},
    "fee_bad": {"fee": 0.20, "spread": 0.04, "slippage": 0.06, "buffer": 0.08},
}


def audit_profile_fee_spread(profile: Dict[str, Any]) -> Dict[str, Any]:
    asset = profile.get("asset_class") or "MID_CAP"
    fee_class = profile.get("fee_class") or "normal_fee"
    costs = DEFAULT_COSTS.get(fee_class, DEFAULT_COSTS["normal_fee"])
    total_cost = costs["fee"] + costs["spread"] + costs["slippage"] + costs["buffer"]
    min_net = MIN_NET_ROOM.get(asset, 1.2)
    issues: List[str] = []

    for side in ("buy", "sell"):
        grids = profile.get(f"{side}_grid_pcts") or []
        trail = float(profile.get(f"{side}_trailing_pct") or 0)
        if not grids:
            continue
        net_room = grids[0] - trail
        if net_room <= total_cost:
            issues.append(f"{side}_net_room_below_cost")
        if net_room < min_net:
            issues.append(f"{side}_net_room_below_asset_min")

    return {
        "profile_id": profile.get("profile_id"),
        "fee_class": fee_class,
        "total_cost_pct": round(total_cost, 4),
        "min_net_room_required": min_net,
        "issues": issues,
        "ok": len(issues) == 0,
    }


def audit_all_profiles(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    passed = 0
    failed = 0
    reason_counts: Counter = Counter()
    fee_bad_profiles = 0
    wait_count = 0
    active_defensive = 0
    widening_samples: List[float] = []

    for p in profiles:
        if p.get("fee_class") == "fee_bad":
            fee_bad_profiles += 1
            fa = str(p.get("final_action") or "").upper()
            if fa in ("WAIT", "NO_TRADE", "SAFE_WAIT") and not _skip_fee_bad_wait_check(p):
                wait_count += 1
            elif "DEFENSIVE" in fa or "ACTIVE" in fa or "GRID" in fa:
                active_defensive += 1
            first = float((p.get("buy_grid_pcts") or p.get("sell_grid_pcts") or [0])[0])
            asset_min = MIN_NET_ROOM.get(p.get("asset_class", "MID_CAP"), 1.0)
            if first > asset_min:
                widening_samples.append(first)

        r = audit_profile_fee_spread(p)
        if r["ok"]:
            passed += 1
        else:
            failed += 1
            for i in r["issues"]:
                reason_counts[i] += 1

    avg_widen = round(sum(widening_samples) / len(widening_samples), 2) if widening_samples else 0

    return {
        "total_profiles": len(profiles),
        "passed": passed,
        "failed": failed,
        "failure_reasons": dict(reason_counts),
        "fee_bad_profiles": fee_bad_profiles,
        "wait_selected_count": wait_count,
        "active_defensive_count": active_defensive,
        "avg_grid_widening_pct": avg_widen,
        "fee_bad_intentional_no_trade": fee_bad_profiles - fee_bad_wait - active_defensive,
        "pass": wait_count == 0 and fee_bad_wait == 0,
        "status": "pass" if wait_count == 0 and fee_bad_wait == 0 else "fail",
        "pass_rate_pct": round(100.0 * passed / max(len(profiles), 1), 4),
    }
