"""
Central policy for SKIP_REASON / engine events — dedupe, throttle, dashboard health flags.

Prevents log spam from repeated MIN_NOTIONAL, BUY_DISABLED, LOCK_BUSY, etc. while keeping
one actionable row-level alert via state['active_health_skips'] (works with health_lite).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Seconds before the same skip key may be written to bot_engine_events again.
SKIP_LOG_DEDUPE_SEC = 900

# Log a summary line every N suppressed repeats (within dedupe window).
SKIP_SUMMARY_EVERY_N = 40

# Never persist to DB — python logger only at call sites.
SILENT_SKIP_REASONS = frozenset(
    {
        "PRICE_STALE_OR_MISSING",
        "IDEMPOTENT_LOCK",
        "LOCK_BUSY",
    }
)

# Dedupe + optional health row flag.
THROTTLED_SKIP_REASONS = frozenset(
    {
        "MIN_NOTIONAL",
        "MIN_NOTIONAL_AFTER_CAP",
        "BUY_DISABLED",
        "SELL_ONLY_MODE",
        "MAX_BUY_LEVELS_ZERO",
        "EXPOSURE_CAP",
        "LOCK_LEASE_EXPIRED",
        "WEIGHT_DENIED",
        "BINANCE_FREE_QUOTE_INSUFFICIENT",
        "BINANCE_FREE_BASE_INSUFFICIENT",
        "INSUFFICIENT_QUOTE",
        "VIRTUAL_BUDGET_INSUFFICIENT",
        "ORDER_TIMEOUT",
        "INVALID_ACTION",
        "INITIAL_ALLOC_BLOCKED_BY_ACTION",
    }
)

# Surfaced on bot list row via evaluate_bot_health_lite (no event scan).
ROW_HEALTH_SKIP_REASONS = frozenset(
    {
        "MIN_NOTIONAL",
        "MIN_NOTIONAL_AFTER_CAP",
        "LOT_SIZE",
        "ORDER_FAILED",
        "INSUFFICIENT_QUOTE",
        "BINANCE_FREE_QUOTE_INSUFFICIENT",
        "BINANCE_FREE_BASE_INSUFFICIENT",
        "BUY_DISABLED",
        "REPEATED_ORDER_FAIL",
    }
)

# MIN_NOTIONAL on dashboard row — user-visible critical.
_ROW_CRITICAL_SKIP = frozenset(
    {
        "MIN_NOTIONAL",
        "MIN_NOTIONAL_AFTER_CAP",
        "LOT_SIZE",
        "INSUFFICIENT_BALANCE",
    }
)


@dataclass
class SkipLogDecision:
    persist: bool
    meta_patch: Dict[str, Any]


def skip_dedupe_key(skip_reason: str, meta: Optional[Dict[str, Any]]) -> str:
    m = meta or {}
    parts = [(skip_reason or "").strip().upper()]
    for k in ("reason", "side", "grid_index", "cycle_id", "symbol"):
        v = m.get(k)
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    return "|".join(parts)


def _registry(state: Dict[str, Any]) -> Dict[str, Any]:
    reg = state.setdefault("_skip_event_registry", {})
    if not isinstance(reg, dict):
        reg = {}
        state["_skip_event_registry"] = reg
    return reg


def evaluate_skip_log(
    state: Optional[Dict[str, Any]],
    skip_reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> SkipLogDecision:
    """Whether to INSERT a SKIP_REASON row; always updates in-memory health flags when needed."""
    code = (skip_reason or "").strip().upper()
    if not code:
        return SkipLogDecision(persist=False, meta_patch={})
    if code in SILENT_SKIP_REASONS:
        if state is not None and code == "LOCK_BUSY":
            _record_lock_busy_pulse(state)
        return SkipLogDecision(persist=False, meta_patch={})

    m = dict(meta or {})
    if state is not None:
        mark_active_health_skip(state, code, m)

    if state is None or code not in THROTTLED_SKIP_REASONS:
        return SkipLogDecision(persist=True, meta_patch={})

    key = skip_dedupe_key(code, m)
    reg = _registry(state)
    now = time.time()
    entry = reg.get(key)
    if not isinstance(entry, dict):
        entry = {"count": 0, "first_ts": now, "last_logged_ts": 0.0, "last_logged_count": 0}
        reg[key] = entry

    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last_ts"] = now
    count = entry["count"]
    last_logged = float(entry.get("last_logged_ts") or 0.0)
    last_logged_count = int(entry.get("last_logged_count") or 0)

    if count == 1:
        entry["last_logged_ts"] = now
        entry["last_logged_count"] = 1
        return SkipLogDecision(persist=True, meta_patch={"skip_log_key": key})

    elapsed = now - last_logged
    since_last_log = count - last_logged_count
    if elapsed >= SKIP_LOG_DEDUPE_SEC or since_last_log >= SKIP_SUMMARY_EVERY_N:
        entry["last_logged_ts"] = now
        entry["last_logged_count"] = count
        return SkipLogDecision(
            persist=True,
            meta_patch={
                "skip_log_key": key,
                "repeat_count": count,
                "suppressed_since_last": max(0, since_last_log - 1),
            },
        )

    return SkipLogDecision(persist=False, meta_patch={})


def mark_active_health_skip(
    state: Dict[str, Any],
    skip_reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    code = (skip_reason or "").strip().upper()
    if code not in ROW_HEALTH_SKIP_REASONS:
        return
    m = meta or {}
    cycle_id = int(m.get("cycle_id") or state.get("cycle_id") or 1)
    active = state.setdefault("active_health_skips", {})
    if not isinstance(active, dict):
        active = {}
        state["active_health_skips"] = active

    prev = active.get(code) if isinstance(active.get(code), dict) else {}
    grids = list(prev.get("grid_indices") or [])
    gi = m.get("grid_index")
    if gi is not None:
        try:
            gi_n = int(gi)
            if gi_n not in grids:
                grids.append(gi_n)
        except (TypeError, ValueError):
            pass

    active[code] = {
        "active": True,
        "ts": int(time.time()),
        "cycle_id": cycle_id,
        "symbol": m.get("symbol") or prev.get("symbol"),
        "side": m.get("side") or prev.get("side"),
        "grid_indices": sorted(grids),
        "repeat_count": int(prev.get("repeat_count") or 0) + 1,
        "notional": m.get("notional", prev.get("notional")),
        "min_notional": m.get("min_notional", prev.get("min_notional")),
        "reason": m.get("reason") or prev.get("reason"),
    }


def clear_skip_runtime_state(state: Dict[str, Any]) -> None:
    """Call on cycle reset — drop per-tur skip flags."""
    for k in (
        "active_health_skips",
        "_skip_event_registry",
        "sell_grid_min_notional_blocked",
        "buy_grid_min_notional_blocked",
        "_lock_busy_window",
    ):
        state.pop(k, None)


def _record_lock_busy_pulse(state: Dict[str, Any]) -> None:
    now = int(time.time())
    win = state.setdefault("_lock_busy_window", {})
    if not isinstance(win, dict):
        win = {}
        state["_lock_busy_window"] = win
    cutoff = now - 900
    # prune old buckets
    for k in list(win.keys()):
        try:
            if int(k) < cutoff:
                del win[k]
        except (TypeError, ValueError):
            del win[k]
    win[str(now)] = int(win.get(str(now)) or 0) + 1


def lock_busy_count_recent(state: Dict[str, Any], within_sec: float = 900.0) -> int:
    win = state.get("_lock_busy_window") or {}
    if not isinstance(win, dict):
        return 0
    cutoff = int(time.time()) - int(within_sec)
    return sum(int(v) for k, v in win.items() if int(k) >= cutoff)


def grid_min_notional_blocked(
    state: Dict[str, Any], side: str, grid_index: int
) -> bool:
    side_u = (side or "").upper()
    key = "sell_grid_min_notional_blocked" if side_u == "SELL" else "buy_grid_min_notional_blocked"
    blocked = state.get(key) or {}
    if not isinstance(blocked, dict):
        return False
    return str(grid_index) in blocked or grid_index in blocked


def mark_grid_min_notional_blocked(
    state: Dict[str, Any],
    side: str,
    grid_index: int,
    *,
    notional: float,
    min_notional: float,
) -> None:
    side_u = (side or "").upper()
    key = "sell_grid_min_notional_blocked" if side_u == "SELL" else "buy_grid_min_notional_blocked"
    blocked = state.setdefault(key, {})
    if not isinstance(blocked, dict):
        blocked = {}
        state[key] = blocked
    blocked[str(grid_index)] = {
        "notional": round(float(notional), 4),
        "min_notional": float(min_notional),
        "ts": int(time.time()),
    }


def health_alerts_from_active_skips(
    state: Dict[str, Any],
    *,
    ack_at: int = 0,
    health_messages: Dict[str, Dict[str, Any]],
    alert_from_tmpl,
) -> List[Dict[str, Any]]:
    """Build dashboard alerts from state (no DB event scan)."""
    out: List[Dict[str, Any]] = []
    active = state.get("active_health_skips") or {}
    if not isinstance(active, dict):
        return out
    for code, entry in active.items():
        if not isinstance(entry, dict) or not entry.get("active"):
            continue
        ts = int(entry.get("ts") or 0)
        if ack_at and ts <= ack_at:
            continue
        tmpl = health_messages.get(code)
        if not tmpl:
            continue
        level = (
            "critical"
            if code in _ROW_CRITICAL_SKIP
            else ("critical" if tmpl.get("severity") == "critical" else "warn")
        )
        grids = entry.get("grid_indices") or []
        msg = tmpl.get("title") or code
        if grids:
            msg = f"{msg} (grid: {', '.join(str(g + 1) for g in grids)})"
        out.append(
            alert_from_tmpl(
                code,
                level,
                tmpl,
                dict(entry),
                message=msg,
            )
        )
    return out


def merge_skip_meta(
    meta: Optional[Dict[str, Any]], patch: Dict[str, Any]
) -> Dict[str, Any]:
    out = dict(meta or {})
    out.update(patch or {})
    return out
