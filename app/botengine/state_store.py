"""
Bot engine state persistence: bot_engine_state (snapshot), bot_engine_events (append-only).
"""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def normalize_event_ts_iso_z(ts: Any) -> str:
    """Event ts → UTC ISO string with Z suffix (UI parse/sort tek kaynak)."""
    if ts is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(ts, datetime):
        dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif "+" not in s[10:] and s.count("-") <= 2 and "T" in s:
        s = s + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_to_json_serializable(obj: Any) -> Any:
    """Return a deep copy of obj with datetime/date converted to ISO string for JSON.dumps."""
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    if isinstance(obj, dict):
        return {k: _state_to_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_state_to_json_serializable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        return float(obj) if isinstance(obj, (int, float)) else str(obj)
    except Exception:
        return None


def load_state_json_extract(db: Session, bot_id: int, json_path: str) -> Any:
    """Tek JSON alanı — tüm state_json parse etmez (leaderboard vb.)."""
    row = db.execute(
        text(
            "SELECT json_extract(state_json, :path) FROM bot_engine_state WHERE bot_id = :bid"
        ),
        {"path": json_path, "bid": bot_id},
    ).fetchone()
    if not row:
        return None
    return row[0]


def load_state(db: Session, bot_id: int) -> Optional[Dict[str, Any]]:
    """Load state snapshot for bot. Returns None if not found."""
    row = db.execute(
        text("SELECT state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at FROM bot_engine_state WHERE bot_id = :bid"),
        {"bid": bot_id},
    ).fetchone()
    if not row:
        logger.debug("BOT_STATE_LOADED bot_id=%s result=None", bot_id)
        return None
    raw = row[0]
    state = json.loads(raw) if isinstance(raw, str) and raw else {}
    try:
        from app.botengine.state_trim import trim_bot_state_for_persist

        trim_bot_state_for_persist(state)
    except Exception:
        pass
    state["cycle_id"] = state.get("cycle_id") or row[1] or 1
    state["mode"] = state.get("mode") or row[2] or "IDLE"
    state["last_tick_at"] = row[3]
    state["last_error_code"] = row[4]
    state["retry_at"] = row[5]
    updated_at = row[6]

    # Ensure state_version exists (for optimistic locking)
    if "state_version" not in state:
        state["state_version"] = 0

    # Instrument log
    state_ver = state.get("state_version", 0)
    ia_done = state.get("initial_allocation_done", False)
    base_qty = state.get("initial_alloc_base_qty", 0)
    base_price = state.get("initial_alloc_price", 0)
    state_hash = hashlib.sha1((raw or "").encode()).hexdigest()[:8] if raw else "empty"
    logger.debug(
        "BOT_STATE_LOADED bot_id=%s ver=%s ia_done=%s base_qty=%s price=%s updated_at=%s hash=%s",
        bot_id, state_ver, ia_done, base_qty, base_price, updated_at, state_hash
    )
    return state


def save_state(db: Session, bot_id: int, account_id: int, state: Dict[str, Any]) -> None:
    """Upsert state snapshot."""
    from app.botengine.state_trim import trim_bot_state_for_persist

    trim_bot_state_for_persist(state)
    # Increment state_version for optimistic locking
    old_ver = state.get("state_version", 0)
    state["state_version"] = old_ver + 1

    # Pre-save instrument: state must be JSON-serializable (no datetime objects)
    state_ver = state.get("state_version", 0)
    ia_done = state.get("initial_allocation_done", False)
    base_qty = state.get("initial_alloc_base_qty", 0)
    base_price = state.get("initial_alloc_price", 0)
    try:
        state_serializable = _state_to_json_serializable(state)
        js = json.dumps(state_serializable, ensure_ascii=False)
        state_hash = hashlib.sha1(js.encode()).hexdigest()[:8]
    except Exception as e:
        logger.warning("BOT_STATE_SAVING json.dumps failed bot_id=%s err=%s", bot_id, e)
        js = "{}"
        state_hash = "error"
    logger.debug(
        "BOT_STATE_SAVING bot_id=%s ver=%s->%s ia_done=%s base_qty=%s price=%s hash=%s",
        bot_id, old_ver, state_ver, ia_done, base_qty, base_price, state_hash
    )

    now = datetime.utcnow()
    db.execute(
        text("""
            INSERT INTO bot_engine_state (bot_id, account_id, state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at)
            VALUES (:bid, :aid, :js, :cid, :mode, :lt, :err, :retry, :upd)
            ON CONFLICT(bot_id) DO UPDATE SET
                state_json = :js, cycle_id = :cid, mode = :mode, last_tick_at = :lt,
                last_error_code = :err, retry_at = :retry, updated_at = :upd
        """),
        {
            "bid": bot_id,
            "aid": account_id,
            "js": js,
            "cid": state.get("cycle_id", 1),
            "mode": state.get("mode", "IDLE"),
            "lt": state.get("last_tick_at"),
            "err": state.get("last_error_code"),
            "retry": state.get("retry_at"),
            "upd": now,
        },
    )
    db.commit()

    # Post-save verify: re-read and log
    verify_row = db.execute(
        text("SELECT state_json, updated_at FROM bot_engine_state WHERE bot_id = :bid"),
        {"bid": bot_id},
    ).fetchone()
    if verify_row:
        verify_raw = verify_row[0]
        verify_hash = hashlib.sha1((verify_raw or "").encode()).hexdigest()[:8] if verify_raw else "empty"
        verify_updated = verify_row[1]
        verify_state = json.loads(verify_raw) if isinstance(verify_raw, str) and verify_raw else {}
        verify_ia_done = verify_state.get("initial_allocation_done", False)
        logger.debug(
            "BOT_STATE_SAVED bot_id=%s ver=%s ia_done=%s hash=%s updated_at=%s verify_ia_done=%s verify_hash=%s",
            bot_id, state_ver, ia_done, state_hash, verify_updated, verify_ia_done, verify_hash
        )
    else:
        logger.warning("BOT_STATE_SAVED bot_id=%s verify_failed=row_not_found", bot_id)


# Event types we log to DB (skip noisy routine events)
_LOGGED_EVENT_TYPES = frozenset({
    "ERROR", "SKIP_REASON", "ORDER_FILLED", "ORDER_ATTEMPT", "SLIPPAGE_WARN", "LOCK_BUSY",
    "INFO", "BOT_ACTION", "CYCLE_END", "CYCLE_START", "HEALTH_WARN", "HEALTH_CRITICAL",
})

# SKIP_REASON values that are routine/expected — log file only, not bot UI event stream
_SILENT_SKIP_REASONS = frozenset({
    "PRICE_STALE_OR_MISSING",
    "IDEMPOTENT_LOCK",
})


def queue_engine_event(
    state: Dict[str, Any],
    event_type: str,
    message: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Queue event from strategy tick (no db); flushed by orchestrator after tick."""
    q = state.setdefault("_pending_engine_events", [])
    if len(q) >= 24:
        return
    q.append({"type": (event_type or "").strip(), "message": message or "", "meta": meta or {}})


def flush_queued_events(
    db: Session,
    bot_id: int,
    account_id: int,
    state: Dict[str, Any],
) -> None:
    pending = state.pop("_pending_engine_events", None) or []
    for ev in pending:
        append_event(db, bot_id, account_id, ev.get("type") or "INFO", ev.get("message") or "", ev.get("meta"))


def append_event(
    db: Session,
    bot_id: int,
    account_id: int,
    event_type: str,
    message: str = "",
    meta: Optional[Dict[str, Any]] = None,
    ts: Optional[datetime] = None,
) -> None:
    """Append one event to bot_engine_events. Only important types are stored (no TICK, no IDEMPOTENT_LOCK noise)."""
    import os
    ty = (event_type or "").strip()
    if ty == "TICK" or ty not in _LOGGED_EVENT_TYPES:
        return
    if ty == "SKIP_REASON":
        skip_code = str((meta or {}).get("skip_reason") or "").strip()
        if skip_code in _SILENT_SKIP_REASONS or "IDEMPOTENT_LOCK" in (message or ""):
            return
    if os.getenv("RAM_PROBE_ENABLED") == "1" and ty == "ORDER_FILLED":
        try:
            from app.observability.ram_probe import probe_event_store
            probe_event_store(before_write=True, write_to_log=True)
        except Exception:
            pass
    try:
        meta_js = json.dumps(meta or {}, ensure_ascii=False)
    except Exception:
        meta_js = "{}"
    db.execute(
        text("""
            INSERT INTO bot_engine_events (bot_id, account_id, ts, event_type, message, meta_json)
            VALUES (:bid, :aid, :ts, :ty, :msg, :meta)
        """),
        {
            "bid": bot_id,
            "aid": account_id,
            "ts": ts if ts is not None else datetime.utcnow(),
            "ty": event_type[:64],
            "msg": (message or "")[:2000],
            "meta": meta_js,
        },
    )
    db.commit()
    if os.getenv("RAM_PROBE_ENABLED") == "1" and ty == "ORDER_FILLED":
        try:
            from app.observability.ram_probe import probe_event_store
            probe_event_store(before_write=False, write_to_log=True)
        except Exception:
            pass


def list_events(
    db: Session,
    bot_id: int,
    limit: int = 200,
    after_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Last N events, optionally after_id."""
    if after_id is not None:
        q = text("""
            SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
            WHERE bot_id = :bid AND id > :aid ORDER BY id DESC LIMIT :lim
        """)
        rows = db.execute(q, {"bid": bot_id, "aid": after_id, "lim": limit}).fetchall()
    else:
        q = text("""
            SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
            WHERE bot_id = :bid ORDER BY id DESC LIMIT :lim
        """)
        rows = db.execute(q, {"bid": bot_id, "lim": limit}).fetchall()
    out = []
    for r in rows:
        meta = {}
        if r[4]:
            try:
                meta = json.loads(r[4])
            except Exception:
                pass
        out.append({
            "id": r[0],
            "ts": normalize_event_ts_iso_z(r[1]),
            "type": r[2],
            "message": r[3] or "",
            "meta": meta,
        })
    return out


def get_events_diagnostic_summary(
    db: Session,
    bot_id: int,
    limit: int = 80,
) -> Dict[str, Any]:
    """
    Son N event'i çekip teşhis özeti döndürür: event_type sayıları, SKIP_REASON dağılımı, son birkaç satır.
    Bot loop başlarken log'a yazılmak üzere kullanılır.
    """
    events = list_events(db, bot_id, limit=limit, after_id=None)
    by_type: Dict[str, int] = {}
    skip_reasons: Dict[str, int] = {}
    last_lines: List[Dict[str, Any]] = []
    for e in events:
        t = e.get("type") or "unknown"
        by_type[t] = by_type.get(t, 0) + 1
        if t == "SKIP_REASON":
            meta = e.get("meta") or {}
            reason = "unknown"
            if isinstance(meta, dict) and meta.get("skip_reason"):
                reason = str(meta["skip_reason"])[:64]
            else:
                msg = (e.get("message") or "").strip()
                reason = msg.split()[0] if msg else "unknown"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    for e in events[:15]:
        last_lines.append({
            "id": e.get("id"),
            "type": e.get("type"),
            "message": (e.get("message") or "")[:120],
        })
    return {
        "total": len(events),
        "by_type": by_type,
        "skip_reasons": skip_reasons,
        "last_events": last_lines,
    }


def ensure_state_row(db: Session, bot_id: int, account_id: int, symbol: str) -> None:
    """Ensure bot_engine_state has a row for bot; init from skeleton if missing."""
    from app.botengine.models import build_state_skeleton
    row = db.execute(text("SELECT 1 FROM bot_engine_state WHERE bot_id = :bid"), {"bid": bot_id}).fetchone()
    if row:
        return
    sk = build_state_skeleton(bot_id, account_id, symbol)
    save_state(db, bot_id, account_id, sk)
