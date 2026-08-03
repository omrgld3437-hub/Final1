"""Dynamic Mode turn-start block + retry/watchlist policy (START_BLOCKED_RETRY_PENDING)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

START_BLOCKED_RETRY_PENDING = "START_BLOCKED_RETRY_PENDING"
WATCHLIST_PAUSED = "WATCHLIST_PAUSED"

MAX_RETRY_MINUTES = float(os.getenv("DYN_MAX_RETRY_MINUTES", "30"))
# Non-deployable / R8 Kapalı / WAIT → fixed 30 minute rescan (operator contract).
NON_DEPLOYABLE_RETRY_MINUTES = float(os.getenv("DYN_NON_DEPLOYABLE_RETRY_MINUTES", "30"))
REBALANCE_COOLDOWN_TURNS = int(os.getenv("DYN_REBALANCE_COOLDOWN_TURNS", "2"))

# Minutes until next retry by primary block reason
_REASON_RETRY_MINUTES: Dict[str, float] = {
    "SPREAD_UNSAFE": NON_DEPLOYABLE_RETRY_MINUTES,
    "SPREAD_HIGH": NON_DEPLOYABLE_RETRY_MINUTES,
    "SPREAD_DANGEROUS": NON_DEPLOYABLE_RETRY_MINUTES,
    "LOW_LIQUIDITY": NON_DEPLOYABLE_RETRY_MINUTES,
    "LIQUIDITY_LOW": NON_DEPLOYABLE_RETRY_MINUTES,
    "DATA_STALE": NON_DEPLOYABLE_RETRY_MINUTES,
    "DATA_GAP": NON_DEPLOYABLE_RETRY_MINUTES,
    "DUMP_RISK": NON_DEPLOYABLE_RETRY_MINUTES,
    "CRASH_FILTER": NON_DEPLOYABLE_RETRY_MINUTES,
    "BTC_CRASH": NON_DEPLOYABLE_RETRY_MINUTES,
    "EXPOSURE_HARD_CAP_BREACH": NON_DEPLOYABLE_RETRY_MINUTES,
    "INVALID_DISTRIBUTION": NON_DEPLOYABLE_RETRY_MINUTES,
    "DISTRIBUTION_INVALID": NON_DEPLOYABLE_RETRY_MINUTES,
    "MIN_GRID_COUNT_NOT_MET": NON_DEPLOYABLE_RETRY_MINUTES,
    "NO_SELLABLE_BASE": NON_DEPLOYABLE_RETRY_MINUTES,
    "REBALANCE_SAFETY_BLOCKED": NON_DEPLOYABLE_RETRY_MINUTES,
    "NO_TRADE": NON_DEPLOYABLE_RETRY_MINUTES,
    "OPERATOR_PROFILE_AUTO_APPLY_DISABLED": NON_DEPLOYABLE_RETRY_MINUTES,
    "NON_DEPLOYABLE": NON_DEPLOYABLE_RETRY_MINUTES,
    "START_BLOCKED": NON_DEPLOYABLE_RETRY_MINUTES,
}

_BLOCKED_RESULT_TYPES = frozenset(
    {
        "no_trade",
        "management_decision",
        "recommended_grid",
        "single_probe_recommendation",
    }
)

_START_BLOCK_CODES = frozenset(
    {
        "SPREAD_UNSAFE",
        "SPREAD_HIGH",
        "SPREAD_DANGEROUS",
        "LOW_LIQUIDITY",
        "LIQUIDITY_LOW",
        "DUMP_RISK",
        "DATA_STALE",
        "DATA_GAP",
        "EXPOSURE_HARD_CAP_BREACH",
        "INVALID_DISTRIBUTION",
        "DISTRIBUTION_INVALID",
        "MIN_GRID_COUNT_NOT_MET",
        "NO_SELLABLE_BASE",
        "REBALANCE_SAFETY_BLOCKED",
    }
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def rebalance_delta_total_pp(current_base_frac: float, target_base_frac: float) -> float:
    """Total percentage-point drift across base + quote legs."""
    cur_b = float(current_base_frac or 0.0) * 100.0
    cur_q = (1.0 - float(current_base_frac or 0.0)) * 100.0
    tgt_b = float(target_base_frac or 0.0) * 100.0
    tgt_q = (1.0 - float(target_base_frac or 0.0)) * 100.0
    return abs(cur_b - tgt_b) + abs(cur_q - tgt_q)


def is_turn_start_blocked(*, result_type: str, deployable: bool) -> bool:
    rt = str(result_type or "").strip().lower()
    if rt == "deployable_grid" and deployable:
        return False
    if rt == "first_start_buy_only" and deployable:
        return False
    if rt in _BLOCKED_RESULT_TYPES:
        return True
    return not deployable


def primary_block_reason(codes: Sequence[str], result_type: str = "") -> str:
    upper = [str(c).strip().upper() for c in (codes or []) if c]
    for code in upper:
        if code in _START_BLOCK_CODES:
            return code
    rt = str(result_type or "").upper()
    if rt == "NO_TRADE":
        return "NO_TRADE"
    if rt in ("MANAGEMENT_DECISION", "RECOMMENDED_GRID", "SINGLE_PROBE_RECOMMENDATION"):
        return rt
    return upper[0] if upper else "START_BLOCKED"


def retry_after_minutes(
    block_reasons: Sequence[str],
    *,
    result_type: str = "",
    retry_count: int = 1,
    fixed_retry_minutes: Optional[float] = None,
) -> float:
    if fixed_retry_minutes is not None:
        return float(fixed_retry_minutes)
    # Operator contract: non-deployable / R8 pause always rescans on a fixed 30m cadence.
    primary = primary_block_reason(block_reasons, result_type)
    return float(_REASON_RETRY_MINUTES.get(primary, NON_DEPLOYABLE_RETRY_MINUTES))


def get_watchlist(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wl = state.get("_dynamic_start_watchlist")
    return wl if isinstance(wl, dict) and wl.get("active") else None


def mark_start_blocked(
    state: Dict[str, Any],
    *,
    cycle_id: int,
    result_type: str,
    deployable: bool,
    block_reasons: Optional[List[str]] = None,
    route_key: str = "",
    risk_state: str = "",
    fixed_retry_minutes: Optional[float] = None,
) -> Dict[str, Any]:
    """Queue coin for retry — no orders, no turn deploy."""
    now = _now_ms()
    prev = get_watchlist(state) or {}
    retry_count = int(prev.get("retry_count") or 0) + 1
    reasons = [str(r) for r in (block_reasons or [])]
    after_min = retry_after_minutes(
        reasons,
        result_type=result_type,
        retry_count=retry_count,
        fixed_retry_minutes=(
            fixed_retry_minutes
            if fixed_retry_minutes is not None
            else NON_DEPLOYABLE_RETRY_MINUTES
        ),
    )
    retry_ms = int(now + after_min * 60_000)
    entry = {
        "active": True,
        "status": START_BLOCKED_RETRY_PENDING,
        "cycle_id": int(cycle_id),
        "result_type": result_type,
        "deployable": bool(deployable),
        "block_reasons": reasons[:20],
        "last_block_reason": primary_block_reason(reasons, result_type),
        "retry_policy": START_BLOCKED_RETRY_PENDING,
        "retry_count": retry_count,
        "consecutive_block_count": retry_count,
        "last_retry_at_ms": now,
        "next_retry_at_ms": retry_ms,
        "retry_after_minutes": after_min,
        "last_route_key": prev.get("new_route_key") or route_key,
        "new_route_key": route_key,
        "last_risk_state": prev.get("new_risk_state") or risk_state,
        "new_risk_state": risk_state,
        "retry_success": False,
        "turn_started_after_retry": False,
        "since_ms": int(prev.get("since_ms") or now),
    }
    state["_dynamic_start_watchlist"] = entry
    state["_dynamic_round_pending"] = {
        "active": True,
        "cycle_id": int(cycle_id),
        "reason": START_BLOCKED_RETRY_PENDING,
        "codes": reasons[:12],
        "since_ms": now,
        "next_retry_ms": retry_ms,
        "retry_count": retry_count,
    }
    state["_dynamic_recompute_needed"] = False
    return entry


def clear_watchlist(state: Dict[str, Any], *, retry_success: bool = False) -> None:
    wl = get_watchlist(state)
    if wl and retry_success:
        wl["retry_success"] = True
        wl["turn_started_after_retry"] = True
        wl["active"] = False
        wl["status"] = "DEPLOYABLE_GRID"
        state["_dynamic_start_watchlist"] = wl
    else:
        state.pop("_dynamic_start_watchlist", None)
    state.pop("_dynamic_round_pending", None)


def pause_watchlist(state: Dict[str, Any], reason: str) -> None:
    wl = get_watchlist(state) or {}
    wl.update(
        {
            "active": False,
            "status": WATCHLIST_PAUSED,
            "retry_stopped_reason": reason,
        }
    )
    state["_dynamic_start_watchlist"] = wl


def retry_due(state: Dict[str, Any], *, now_ms: Optional[int] = None) -> bool:
    wl = get_watchlist(state)
    if not wl or not wl.get("active"):
        p = state.get("_dynamic_round_pending")
        if isinstance(p, dict) and p.get("active"):
            now = now_ms or _now_ms()
            return now >= int(p.get("next_retry_ms") or 0)
        return False
    now = now_ms or _now_ms()
    return now >= int(wl.get("next_retry_at_ms") or 0)


def need_start_retry(state: Dict[str, Any]) -> bool:
    """Force full DPS re-analysis when retry window elapsed."""
    wl = get_watchlist(state)
    if not wl or not wl.get("active"):
        return False
    cur = int(state.get("cycle_id") or 1)
    if int(wl.get("cycle_id") or 0) != cur:
        clear_watchlist(state)
        return False
    if retry_due(state):
        state["_dynamic_recompute_needed"] = True
        wl["last_retry_at_ms"] = _now_ms()
        after = retry_after_minutes(
            wl.get("block_reasons") or [],
            result_type=str(wl.get("result_type") or ""),
            retry_count=int(wl.get("retry_count") or 1) + 1,
            fixed_retry_minutes=NON_DEPLOYABLE_RETRY_MINUTES,
        )
        wl["next_retry_at_ms"] = int(_now_ms() + after * 60_000)
        wl["retry_after_minutes"] = after
        return True
    return False


def on_successful_deploy(state: Dict[str, Any]) -> None:
    clear_watchlist(state, retry_success=True)
    state.pop("_dynamic_cycle_hold", None)
    state.pop("_dynamic_cycle_engaged", None)
    state.pop("_dynamic_last_rebalance_turn", None)
