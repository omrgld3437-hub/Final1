"""
Bot engine log — Reset/ack sonrası eski uyarı satırlarını filtrele (UI + API).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_RESILIENCE_CODES = frozenset({
    "BOT_LOOP_AUTO_RESTART",
    "LOOP_TASK_MISSING",
    "BOT_CONTINUES_ON_ERROR",
})


def _is_health_event_type(ty: str) -> bool:
    return (ty or "").upper() in ("HEALTH_WARN", "HEALTH_CRITICAL")


def is_resilience_log_event(ev: Dict[str, Any]) -> bool:
    meta = ev.get("meta") or {}
    if meta.get("event_kind") == "BOT_RESILIENCE":
        return True
    code = str(meta.get("health_code") or meta.get("error_code") or "").upper()
    if code in _RESILIENCE_CODES:
        return True
    raw = str(ev.get("message") or "")
    return bool(
        re.search(r"Dayanıklılık:", raw, re.I)
        or re.search(r"döngü yeniden başlatılıyor", raw, re.I)
        or re.search(r"ensure_running_bots", raw, re.I)
    )


def resolve_event_log_code(ev: Dict[str, Any]) -> str:
    meta = ev.get("meta") or {}
    code = str(meta.get("health_code") or meta.get("error_code") or "").upper()
    if code:
        return code
    if is_resilience_log_event(ev):
        raw = str(ev.get("message") or "")
        if re.search(r"ensure_running_bots|LOOP_TASK", raw, re.I):
            return "LOOP_TASK_MISSING"
        return "BOT_LOOP_AUTO_RESTART"
    return ""


def is_resettable_log_event(ev: Dict[str, Any]) -> bool:
    if not ev:
        return False
    if is_resilience_log_event(ev):
        return True
    ty = (ev.get("type") or "").upper()
    if ty in ("HEALTH_WARN", "HEALTH_CRITICAL", "SLIPPAGE_WARN"):
        return True
    if ty == "ERROR":
        meta = ev.get("meta") or {}
        code = str(meta.get("error_code") or meta.get("health_code") or "").upper()
        if re.search(
            r"API_UNAUTHORIZED|BINANCE_UNREACHABLE|BINANCE_RATE|ACCOUNT_KEYS",
            code,
        ):
            return True
        raw = str(ev.get("message") or "")
        return bool(re.search(r"binance|401|-2015|ulaşılamıyor|api anahtar", raw, re.I))
    if ty == "SKIP_REASON":
        meta = ev.get("meta") or {}
        skip = str(meta.get("skip_reason") or meta.get("error_code") or "").upper()
        if skip in (
            "ORDER_FAILED",
            "LOT_SIZE",
            "MIN_NOTIONAL",
            "MIN_NOTIONAL_AFTER_CAP",
            "INSUFFICIENT_QUOTE",
            "ORDER_TIMEOUT",
        ):
            return True
    if ty == "INFO":
        meta = ev.get("meta") or {}
        code = str(meta.get("error_code") or "").upper()
        if code in ("CONNECTIVITY_RECOVERED", "CONNECTIVITY_PAUSED"):
            return True
        raw = str(ev.get("message") or "")
        if re.search(r"tekrar aktif edildi|beklemeye alındı", raw, re.I):
            return True
    return False


def max_resettable_event_id(events: List[Dict[str, Any]]) -> int:
    mx = 0
    for ev in events or []:
        if not is_resettable_log_event(ev):
            continue
        eid = int(ev.get("id") or 0)
        if eid > mx:
            mx = eid
    return mx


def should_hide_engine_event(ev: Dict[str, Any], dismiss_before_id: int) -> bool:
    """True → UI/API listesinden çıkar."""
    if not dismiss_before_id or not ev:
        return False
    eid = int(ev.get("id") or 0)
    if eid <= 0 or eid > dismiss_before_id:
        return False
    return is_resettable_log_event(ev)


def filter_events_for_dismiss(
    events: List[Dict[str, Any]],
    dismiss_before_id: Optional[int],
) -> List[Dict[str, Any]]:
    if not dismiss_before_id or dismiss_before_id <= 0:
        return list(events or [])
    return [e for e in (events or []) if not should_hide_engine_event(e, int(dismiss_before_id))]
