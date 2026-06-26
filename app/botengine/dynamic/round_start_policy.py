"""
Dynamic Mode round-start policy — active-by-default, hard-safety wait + 15m retry.

Philosophy:
- Profit from volatility: deploy grids unless hard safety blocks.
- Each tur gets independent DPS inputs (orchestrator rebuilds snapshot per cycle_id).
- Soft WAIT/NO_TRADE from scoring → prefer ACTIVE_DEFENSIVE overlay when possible.
- Hard safety (dump, stale data, dangerous spread) → pending retry every 15 minutes.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.models import DynamicParamDecision, FinalAction

# 15 minutes — operator retry for blocked round starts
ROUND_START_RETRY_SEC = float(os.getenv("DYN_ROUND_START_RETRY_SEC", "900"))

HARD_BLOCKING_CODES = frozenset(
    {
        "DUMP_RISK",
        "DATA_STALE",
        "DATA_GAP",
        "SPREAD_DANGEROUS",
        "PRICE_INVALID",
        "EXCHANGE_FILTER_FAIL",
        "BALANCE_INSUFFICIENT",
        "CRASH_FILTER",
        "API_ORDER_REJECTED",
        "MIN_NOTIONAL_HARD_FAIL",
        "NO_VALID_GRID_AFTER_MIN_NOTIONAL",
    }
)

SOFT_WAIT_ACTIONS = frozenset(
    {
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.NO_TRADE.value,
        "SAFE_WAIT",
        "DATA_STALE_SAFE_WAIT",
    }
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def blocking_codes(decision: DynamicParamDecision) -> List[str]:
    out: List[str] = []
    for r in decision.blocking_reasons or []:
        out.append(str(r).strip().upper())
    for g in decision.safety_gates or []:
        if not getattr(g, "passed", True):
            code = str(getattr(g, "reason_code", "") or "").strip().upper()
            if code:
                out.append(code)
    return out


def is_hard_safety_block(decision: DynamicParamDecision) -> bool:
    """True when round start must defer (emergency only)."""
    codes = blocking_codes(decision)
    if any(c in HARD_BLOCKING_CODES for c in codes):
        return True
    fa = str(decision.final_action or "").upper()
    if fa == FinalAction.NO_TRADE.value and "DUMP_RISK" in codes:
        return True
    if decision.regime_tag in ("DUMP_RISK", "CRASH_RISK"):
        return True
    return False


def should_force_active(decision: DynamicParamDecision) -> bool:
    """Soft wait — convert to defensive grid instead of sitting idle."""
    if decision.deployable and decision.params:
        return False
    if is_hard_safety_block(decision):
        return False
    fa = str(decision.final_action or "").upper()
    return fa in SOFT_WAIT_ACTIONS or not decision.deployable


def get_pending(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = state.get("_dynamic_round_pending")
    return p if isinstance(p, dict) and p.get("active") else None


def mark_pending(
    state: Dict[str, Any],
    *,
    cycle_id: int,
    reason: str,
    codes: Optional[List[str]] = None,
) -> None:
    now = _now_ms()
    retry_ms = int(now + ROUND_START_RETRY_SEC * 1000)
    state["_dynamic_round_pending"] = {
        "active": True,
        "cycle_id": int(cycle_id),
        "reason": reason,
        "codes": list(codes or [])[:12],
        "since_ms": now,
        "next_retry_ms": retry_ms,
        "retry_count": int((get_pending(state) or {}).get("retry_count") or 0) + 1,
    }
    state["_dynamic_recompute_needed"] = False


def clear_pending(state: Dict[str, Any]) -> None:
    state.pop("_dynamic_round_pending", None)


def retry_due(state: Dict[str, Any], *, now_ms: Optional[int] = None) -> bool:
    p = get_pending(state)
    if not p:
        return False
    now = now_ms or _now_ms()
    return now >= int(p.get("next_retry_ms") or 0)


def need_round_start_retry(state: Dict[str, Any]) -> bool:
    """Orchestrator: force DPS rebuild when 15m retry elapsed."""
    p = get_pending(state)
    if not p:
        return False
    cur = int(state.get("cycle_id") or 1)
    if int(p.get("cycle_id") or 0) != cur:
        clear_pending(state)
        return False
    if retry_due(state):
        state["_dynamic_recompute_needed"] = True
        p["next_retry_ms"] = int(_now_ms() + ROUND_START_RETRY_SEC * 1000)
        return True
    return False


def schedule_next_retry(state: Dict[str, Any]) -> None:
    p = get_pending(state)
    if p:
        p["next_retry_ms"] = int(_now_ms() + ROUND_START_RETRY_SEC * 1000)


def on_deployable_round_start(state: Dict[str, Any]) -> None:
    clear_pending(state)
    state.pop("_dynamic_cycle_hold", None)
    state.pop("_dynamic_cycle_engaged", None)
