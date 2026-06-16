"""
Bot çalışma oturumu süresi (started_at) — bağlantı/worker yeniden başlatmada sıfırlanmaz.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_STATE_KEY = "bot_run_started_at"
_COLD_START_RE = re.compile(r"COMMAND_EXECUTED.*\bSTART\b", re.I)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_connectivity_resume_start(
    cmd_payload: Optional[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
) -> bool:
    payload = cmd_payload if isinstance(cmd_payload, dict) else {}
    st = state if isinstance(state, dict) else {}
    if payload.get("connectivity_resume"):
        return True
    if (st.get("_connectivity_resume_reason") or "").strip():
        return True
    return False


def should_refresh_bot_started_at(
    bot: Any, *, connectivity_resume: bool = False
) -> bool:
    """Yalnızca durdurulmuş bot yeniden başlatılınca DB started_at yenilenir."""
    if connectivity_resume:
        return False
    prev = (getattr(bot, "status", None) or "").strip().lower()
    if prev in ("running", "paused_error"):
        return False
    return True


def touch_bot_started_at(bot: Any, *, connectivity_resume: bool = False) -> None:
    if getattr(bot, "started_at", None) is None:
        bot.started_at = datetime.now(timezone.utc)
        return
    if should_refresh_bot_started_at(bot, connectivity_resume=connectivity_resume):
        bot.started_at = datetime.now(timezone.utc)


def mark_bot_run_started(
    state: Dict[str, Any], *, connectivity_resume: bool = False
) -> None:
    """State'te oturum başlangıcı — UI süre sayacı tek kaynak."""
    if connectivity_resume:
        return
    state[_STATE_KEY] = _utc_now_iso()


def assign_bot_run_id(
    state: Dict[str, Any],
    *,
    command_id: Optional[int] = None,
    request_id: Optional[str] = None,
    connectivity_resume: bool = False,
) -> str:
    """Cold start için emir kimliği. Connectivity resume aynı canlı run_id'yi korur."""
    if connectivity_resume and (state.get("run_id") or "").strip():
        return str(state["run_id"]).strip()
    if command_id is not None:
        run_id = f"cmd{int(command_id)}"
    else:
        rid = "".join(ch for ch in str(request_id or "") if ch.isalnum())[-12:]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        run_id = f"req{rid}" if rid else f"run{ts}"
    state["run_id"] = run_id
    return run_id


def clear_bot_run_started(state: Dict[str, Any]) -> None:
    state.pop(_STATE_KEY, None)


def _normalize_iso_z(iso: Optional[str]) -> Optional[str]:
    if not iso or not isinstance(iso, str):
        return None
    s = iso.strip()
    if not s:
        return None
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    elif "T" in s and not s.endswith("Z") and "+" not in s[-7:] and "-" not in s[10:]:
        s = s + "Z"
    return s


def _parse_iso_ms(iso: Optional[str]) -> int:
    norm = _normalize_iso_z(iso)
    if not norm:
        return 0
    try:
        t = datetime.fromisoformat(norm.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return int(t.timestamp() * 1000)
    except Exception:
        return 0


def _last_stop_event_id(db: "Session", bot_id: int) -> int:
    from sqlalchemy import text

    row = db.execute(
        text("""
            SELECT id FROM bot_engine_events
            WHERE bot_id = :bid AND event_type = 'INFO'
              AND message LIKE '%COMMAND_EXECUTED%' AND message LIKE '%STOP%'
            ORDER BY id DESC LIMIT 1
        """),
        {"bid": int(bot_id)},
    ).fetchone()
    return int(row[0]) if row else 0


def _first_cold_start_after_stop(db: "Session", bot_id: int, last_stop_id: int) -> Optional[Dict[str, Any]]:
    from sqlalchemy import text

    from app.botengine.state_store import normalize_event_ts_iso_z

    rows = db.execute(
        text("""
            SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
            WHERE bot_id = :bid AND id > :stop_id AND event_type = 'INFO'
              AND message LIKE '%COMMAND_EXECUTED%' AND message LIKE '%START%'
            ORDER BY id ASC LIMIT 32
        """),
        {"bid": int(bot_id), "stop_id": int(last_stop_id)},
    ).fetchall()
    for row in rows:
        meta: Dict[str, Any] = {}
        if row[4]:
            try:
                meta = json.loads(row[4])
            except Exception:
                meta = {}
        if meta.get("connectivity_resume"):
            continue
        return {
            "id": row[0],
            "ts": normalize_event_ts_iso_z(row[1]),
            "type": row[2],
            "message": row[3] or "",
            "meta": meta,
        }
    return None


def resolve_bot_session_start_event_id(
    db: "Session",
    bot_id: int,
    state: Optional[Dict[str, Any]] = None,
) -> int:
    """Son manuel STOP sonrası ilk soğuk START event id (0 = bilinmiyor)."""
    last_stop_id = _last_stop_event_id(db, int(bot_id))
    start_ev = _first_cold_start_after_stop(db, int(bot_id), last_stop_id)
    if start_ev:
        return int(start_ev.get("id") or 0)
    st = state if isinstance(state, dict) else {}
    run_iso = (st.get(_STATE_KEY) or "").strip()
    if not run_iso:
        return 0
    run_ms = _parse_iso_ms(run_iso)
    if run_ms <= 0:
        return 0
    from app.botengine.state_store import list_events

    for ev in list_events(db, int(bot_id), limit=500):
        ts_ms = _parse_iso_ms(ev.get("ts"))
        if ts_ms <= 0 or ts_ms + 5000 < run_ms:
            continue
        if (ev.get("type") or "").upper() != "INFO":
            continue
        raw = ev.get("message") or ""
        if not _COLD_START_RE.search(raw):
            continue
        meta = ev.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if meta.get("connectivity_resume"):
            continue
        return int(ev.get("id") or 0)
    return 0


def infer_bot_run_started_at_from_events(db: "Session", bot_id: int) -> Optional[str]:
    """Son STOP sonrası ilk soğuk START (connectivity_resume değil)."""
    last_stop_id = _last_stop_event_id(db, int(bot_id))
    start_ev = _first_cold_start_after_stop(db, int(bot_id), last_stop_id)
    if start_ev and start_ev.get("ts"):
        return _normalize_iso_z(str(start_ev["ts"]))
    return None


def heal_bot_run_started_at(
    db: "Session", bot_id: int, account_id: int, state: Dict[str, Any]
) -> Dict[str, Any]:
    if (state.get(_STATE_KEY) or "").strip():
        return state
    inferred = infer_bot_run_started_at_from_events(db, bot_id)
    if inferred:
        state[_STATE_KEY] = inferred
        try:
            from app.botengine.state_store import save_state

            save_state(db, int(bot_id), int(account_id), state)
        except Exception:
            pass
    return state


def bot_run_started_at_iso(
    bot: Any, state: Optional[Dict[str, Any]], db: Optional["Session"] = None
) -> Optional[str]:
    """
    UI/API süre alanı: state oturum başlangıcı; yoksa DB; running ise event'ten heal.
    """
    st = state if isinstance(state, dict) else {}
    if db is not None and (getattr(bot, "status", None) or "").lower() == "running":
        st = heal_bot_run_started_at(db, int(bot.id), int(bot.account_id), st)
    st_iso = _normalize_iso_z(st.get(_STATE_KEY))
    db_dt = getattr(bot, "started_at", None)
    db_iso = None
    if db_dt is not None:
        try:
            db_iso = _normalize_iso_z(db_dt.isoformat())
        except Exception:
            db_iso = None
    if st_iso and db_iso:
        return st_iso if _parse_iso_ms(st_iso) <= _parse_iso_ms(db_iso) else db_iso
    return st_iso or db_iso
