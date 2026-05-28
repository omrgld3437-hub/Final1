"""
Per-account Binance upstream failure tracker.
Failures persist to .run/ (cross-process). Bot log events written synchronously on probe/view.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUN_DIR = _PROJECT_ROOT / ".run"

_FAILURE_TTL_SEC = 180.0
_BOT_EVENT_THROTTLE_SEC = 300.0
_PROBE_THROTTLE_SEC = 30.0

_lock = threading.Lock()
_by_account: Dict[int, Dict[str, Any]] = {}
_last_emit_by_bot: Dict[int, float] = {}
_last_probe_by_bot: Dict[int, float] = {}
_last_auto_resume_by_account: Dict[int, float] = {}

_AUTO_RESUME_THROTTLE_SEC = 45.0
_AUTO_RESUME_ERROR_CODES = frozenset({
    "API_UNAUTHORIZED",
    "BINANCE_UNREACHABLE",
    "BINANCE_RATE_LIMIT",
})


def _fail_path(account_id: int) -> Path:
    return _RUN_DIR / f"binance_fail_{int(account_id)}.json"


def _persist_failure(account_id: int, rec: Dict[str, Any]) -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        _fail_path(account_id).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("binance_connectivity persist account_id=%s: %s", account_id, e)


def _clear_persisted_failure(account_id: int) -> None:
    try:
        p = _fail_path(account_id)
        if p.exists():
            p.unlink()
    except Exception as e:
        logger.debug("binance_connectivity clear persist account_id=%s: %s", account_id, e)


def _load_persisted_failure(account_id: int) -> Optional[Dict[str, Any]]:
    try:
        p = _fail_path(account_id)
        if not p.exists():
            return None
        rec = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(rec, dict):
            return None
        if time.time() - float(rec.get("last_fail_ts") or 0) > _FAILURE_TTL_SEC:
            _clear_persisted_failure(account_id)
            return None
        return rec
    except Exception:
        return None


def _classify_binance_error(exc: Exception) -> Tuple[str, str]:
    s = str(exc or "").lower()
    resp = getattr(exc, "response", None)
    sc = getattr(resp, "status_code", None) if resp else None
    if sc in (401, 403) or "401" in s or "unauthorized" in s or "-2015" in s or "invalid api-key" in s:
        return (
            "API_UNAUTHORIZED",
            "Binance API anahtarı geçersiz veya IP beyaz listesinde değil (401/-2015).",
        )
    if sc in (429, 418) or "rate limit" in s:
        return ("BINANCE_RATE_LIMIT", "Binance istek limiti aşıldı; kısa süre sonra tekrar denenecek.")
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in s:
        return ("BINANCE_UNREACHABLE", "Binance API zaman aşımı — sunucu IP veya ağ bağlantısını kontrol edin.")
    return ("BINANCE_UNREACHABLE", f"Binance API isteği başarısız: {type(exc).__name__}")


def note_binance_failure(
    account_id: int,
    error_code: str,
    message: str,
    source: str = "",
    *,
    emit_async: bool = True,
) -> None:
    if not account_id:
        return
    now = time.time()
    aid = int(account_id)
    code = (error_code or "BINANCE_UNREACHABLE").strip()
    msg = (message or "Binance API isteği başarısız")[:500]
    rec = {
        "error_code": code,
        "message": msg,
        "source": (source or "")[:64],
        "since_ts": now,
        "last_fail_ts": now,
    }
    with _lock:
        prev = _by_account.get(aid) or {}
        rec["since_ts"] = prev.get("since_ts") or now
        _by_account[aid] = rec
    _persist_failure(aid, rec)
    if emit_async:
        _emit_bot_events_async(aid, code, msg, source)


def note_binance_success(account_id: int, *, schedule_resume: bool = True) -> None:
    if not account_id:
        return
    aid = int(account_id)
    with _lock:
        _by_account.pop(aid, None)
    _clear_persisted_failure(aid)
    if schedule_resume:
        _schedule_auto_resume_after_success(aid)


def _schedule_auto_resume_after_success(account_id: int) -> None:
    """Bağlantı düzelince paused_error (API) botlarını worker START komutu ile devam ettir."""
    now = time.time()
    with _lock:
        if now - _last_auto_resume_by_account.get(account_id, 0.0) < _AUTO_RESUME_THROTTLE_SEC:
            return
        _last_auto_resume_by_account[account_id] = now

    def _run() -> None:
        try:
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                n = try_auto_resume_paused_bots(db, account_id)
                if n:
                    logger.info(
                        "connectivity auto-resume account_id=%s resumed=%s",
                        account_id,
                        n,
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning("connectivity auto-resume account_id=%s: %s", account_id, e)

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"binance-auto-resume-{account_id}",
    ).start()


def _connectivity_resume_reason(state: Dict[str, Any], previous_error: str) -> Tuple[str, Dict[str, Any]]:
    """API düzelince bot logunda gösterilecek kısa açıklama."""
    buy_triggers = state.get("buy_grid_trigger_price") or []
    sell_triggers = state.get("sell_grid_trigger_price") or []
    active_buy = [i + 1 for i, t in enumerate(buy_triggers) if t is not None]
    active_sell = [i + 1 for i, t in enumerate(sell_triggers) if t is not None]
    cycle_id = int(state.get("cycle_id") or 1)
    ctx: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "active_buy_grids": active_buy,
        "active_sell_grids": active_sell,
        "mode": state.get("mode"),
        "previous_error": previous_error,
    }
    parts: List[str] = []
    if previous_error == "API_UNAUTHORIZED":
        parts.append("Binance API/IP kesintisi giderildi.")
    elif previous_error:
        parts.append(f"Önceki hata: {previous_error}.")
    if active_buy:
        grids = ", ".join(str(g) for g in active_buy)
        parts.append(
            f"Kesinti öncesi alt alım grid tetikteydi (seviye {grids}). "
            "Bağlantı dönünce fiyat tetik üstüne çıkmış olabilir; bir sonraki tick'te grid yeniden değerlendirilir "
            f"(Tur {cycle_id} aynı kalır, yeni tur açılmaz)."
        )
    elif active_sell:
        grids = ", ".join(str(g) for g in active_sell)
        parts.append(
            f"Kesinti öncesi üst satış grid tetikteydi (seviye {grids}); "
            f"Tur {cycle_id} devam edecek, kopma sonrası grid değerlendirmesi yapılır."
        )
    else:
        parts.append(
            f"Tur {cycle_id} ve grid durumu korunur; kopma sonrası değerlendirme bir sonraki tick'te yazılır."
        )
    return " ".join(parts), ctx


def try_auto_resume_paused_bots(db: "Session", account_id: int) -> int:
    """
    Binance erişimi düzeldiğinde API_UNAUTHORIZED vb. ile durmuş botları running + START komutu.
    """
    from datetime import datetime, timezone

    from app.db.models import Bot
    from app.botengine.state_store import append_event, load_state, save_state

    if not account_id:
        return 0
    aid = int(account_id)
    bots = (
        db.query(Bot)
        .filter(Bot.account_id == aid, Bot.status == "paused_error")
        .all()
    )
    if not bots:
        return 0
    resumed = 0
    for bot in bots:
        state = load_state(db, bot.id) or {}
        err = (state.get("last_error_code") or "").strip()
        if err not in _AUTO_RESUME_ERROR_CODES:
            continue
        last_ar = float(state.get("_connectivity_auto_resume_at") or 0)
        if time.time() - last_ar < 90.0:
            continue
        if _recent_connectivity_recovered(db, bot.id):
            continue
        state.pop("last_error_code", None)
        state.pop("health_error_since", None)
        state.pop("backoff_until", None)
        state["_connectivity_auto_resume_at"] = time.time()
        resume_reason, grid_ctx = _connectivity_resume_reason(state, err)
        state["_connectivity_resume_reason"] = resume_reason
        save_state(db, bot.id, aid, state)
        bot.status = "running"
        if not getattr(bot, "started_at", None):
            bot.started_at = datetime.now(timezone.utc)
        db.commit()
        conn_meta: Dict[str, Any] = {
            "error_code": "CONNECTIVITY_RECOVERED",
            "previous_error": err,
            "connectivity_resume": True,
            "resume_reason": resume_reason,
            "cycle_id": grid_ctx.get("cycle_id"),
            "active_buy_grids": grid_ctx.get("active_buy_grids"),
            "active_sell_grids": grid_ctx.get("active_sell_grids"),
            "symbol": state.get("symbol") or getattr(bot, "symbol", None),
            "base_balance": round(float(state.get("base_balance") or 0), 10),
            "quote_balance": round(float(state.get("quote_balance") or 0), 2),
            "initial_allocation_done": bool(state.get("initial_allocation_done")),
        }
        cse = float(state.get("cycle_start_equity") or 0)
        if cse > 0:
            conn_meta["cycle_start_equity"] = round(cse, 2)
        append_event(
            db,
            bot.id,
            aid,
            "INFO",
            f"Tur {int(grid_ctx.get('cycle_id') or state.get('cycle_id') or 1)} tekrar aktif edildi — bot sorunsuz çalışmaya devam ediyor.",
            conn_meta,
        )
        try:
            from app.api.bots_engine import _insert_engine_command

            start_payload = json.dumps(
                {
                    "connectivity_resume": True,
                    "resume_reason": resume_reason,
                    "cycle_id": grid_ctx.get("cycle_id"),
                },
                ensure_ascii=False,
            )
            _insert_engine_command(db, aid, bot.id, "START", payload_json=start_payload)
        except Exception as cmd_ex:
            logger.warning(
                "connectivity auto-resume START cmd bot_id=%s: %s",
                bot.id,
                cmd_ex,
            )
        resumed += 1
    return resumed


async def run_connectivity_auto_resume_pass(db: "Session") -> int:
    """Worker: paused_error hesaplarında probe OK ise otomatik devam."""
    from app.db.models import Bot

    rows = (
        db.query(Bot.account_id)
        .filter(Bot.status == "paused_error")
        .distinct()
        .all()
    )
    total = 0
    for (aid,) in rows:
        if not aid:
            continue
        ok, _, _ = await probe_account_binance(int(aid), db)
        if ok:
            note_binance_success(int(aid), schedule_resume=False)
            total += try_auto_resume_paused_bots(db, int(aid))
    return total


def active_failure(account_id: int) -> Optional[Dict[str, Any]]:
    if not account_id:
        return None
    aid = int(account_id)
    with _lock:
        rec = _by_account.get(aid)
    if not rec:
        rec = _load_persisted_failure(aid)
        if rec:
            with _lock:
                _by_account[aid] = rec
    if not rec:
        return None
    if time.time() - float(rec.get("last_fail_ts") or 0) > _FAILURE_TTL_SEC:
        note_binance_success(aid)
        return None
    return dict(rec)


def _recent_connectivity_pause_info(db: "Session", bot_id: int, within_sec: float = 300.0) -> bool:
    """True if Tur beklemeye alındı INFO was logged recently."""
    try:
        from app.botengine.state_store import list_events

        cutoff = time.time() - within_sec
        for ev in list_events(db, bot_id, limit=40):
            if (ev.get("type") or "") != "INFO":
                continue
            meta = ev.get("meta") or {}
            if (meta.get("error_code") or "").strip() != "CONNECTIVITY_PAUSED":
                continue
            ts = ev.get("ts")
            if not ts:
                continue
            try:
                from datetime import datetime, timezone

                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    return True
            except Exception:
                return True
        return False
    except Exception:
        return False


def _recent_connectivity_recovered(db: "Session", bot_id: int, within_sec: float = 120.0) -> bool:
    try:
        from app.botengine.state_store import list_events

        cutoff = time.time() - within_sec
        for ev in list_events(db, bot_id, limit=20):
            if (ev.get("type") or "") != "INFO":
                continue
            meta = ev.get("meta") or {}
            if (meta.get("error_code") or "").strip() != "CONNECTIVITY_RECOVERED":
                continue
            ts = ev.get("ts")
            if not ts:
                return True
            try:
                from datetime import datetime, timezone

                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    return True
            except Exception:
                return True
        return False
    except Exception:
        return False


def emit_tur_connectivity_paused_info(
    db: "Session",
    bot_id: int,
    account_id: int,
    upstream_error: str = "",
) -> bool:
    """Engine log: Tur X beklemeye alındı (Bilgi) — uyarılardan önce yazılır."""
    from app.botengine.state_store import append_event, load_state

    if _recent_connectivity_pause_info(db, bot_id):
        return False
    state = load_state(db, bot_id) or {}
    cycle_id = int(state.get("cycle_id") or 1)
    append_event(
        db,
        bot_id,
        account_id,
        "INFO",
        f"Tur {cycle_id} beklemeye alındı. Bağlantı yok",
        {
            "error_code": "CONNECTIVITY_PAUSED",
            "connectivity_pause": True,
            "cycle_id": cycle_id,
            "upstream_error": (upstream_error or "BINANCE_UNREACHABLE").strip(),
        },
    )
    return True


def _recent_connectivity_event(db: "Session", bot_id: int, error_code: str, within_sec: float = 300.0) -> bool:
    """True if same connectivity error was logged recently (avoid log spam)."""
    try:
        from app.botengine.state_store import list_events

        code = (error_code or "BINANCE_UNREACHABLE").strip()
        cutoff = time.time() - within_sec
        for ev in list_events(db, bot_id, limit=30):
            if (ev.get("type") or "") not in ("ERROR", "HEALTH_CRITICAL", "HEALTH_WARN"):
                continue
            meta = ev.get("meta") or {}
            ec = (meta.get("error_code") or meta.get("health_code") or "").strip()
            if ec not in (code, "CONNECTIVITY_LOST"):
                continue
            ts = ev.get("ts")
            if not ts:
                continue
            try:
                from datetime import datetime, timezone

                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    return True
            except Exception:
                return False
        return False
    except Exception:
        return False


def emit_connectivity_events_for_bot(
    db: "Session",
    bot: Any,
    error_code: str,
    message: str,
    source: str = "",
    *,
    force: bool = False,
) -> bool:
    """Write INFO pause + HEALTH_WARN + ERROR to bot_engine_events (sync). Returns True if emitted."""
    from app.botengine.state_store import append_event, load_state, save_state

    bot_id = int(bot.id)
    account_id = int(bot.account_id)
    now = time.time()
    code = (error_code or "BINANCE_UNREACHABLE").strip()
    if not force:
        last = _last_emit_by_bot.get(bot_id, 0.0)
        if now - last < _BOT_EVENT_THROTTLE_SEC:
            return False
        if _recent_connectivity_event(db, bot_id, code):
            _last_emit_by_bot[bot_id] = now
            return False
    elif _recent_connectivity_event(db, bot_id, code, within_sec=30.0):
        return False

    short_msg = (message or "").strip()
    if len(short_msg) > 180:
        short_msg = "hesap bakiyesi veya piyasa verisi alınamadı"
    log_msg = f"Binance bağlantı hatası — {short_msg}"
    meta_base = {
        "error_code": code,
        "source": source or "upstream",
        "health_code": "BINANCE_UNREACHABLE",
        "cycle_id": int((load_state(db, bot_id) or {}).get("cycle_id") or 1),
    }
    try:
        emit_tur_connectivity_paused_info(db, bot_id, account_id, code)
        warn_meta = {
            **meta_base,
            "health_code": "CONNECTIVITY_LOST",
            "title": "Bağlantı kesildi",
            "cause": short_msg,
            "severity": "warn",
        }
        append_event(
            db,
            bot_id,
            account_id,
            "HEALTH_WARN",
            f"Binance bağlantısı yok — {short_msg}",
            warn_meta,
        )
        append_event(db, bot_id, account_id, "ERROR", log_msg, meta_base)
        state = load_state(db, bot_id) or {}
        state["last_error_code"] = code
        state["health_error_since"] = int(now)
        save_state(db, bot_id, account_id, state)
        _last_emit_by_bot[bot_id] = now
        logger.info(
            "binance_connectivity bot_event bot_id=%s account_id=%s code=%s source=%s",
            bot_id,
            account_id,
            code,
            source,
        )
        return True
    except Exception as e:
        logger.warning("binance_connectivity emit bot_id=%s: %s", bot_id, e)
        return False


async def probe_account_binance(account_id: int, db: "Session") -> Tuple[bool, str, str]:
    """Live Binance /account probe. Returns (ok, error_code, message)."""
    from app.services.test_account import is_test_account

    if is_test_account(account_id, db):
        return True, "", ""
    try:
        from app.services.binance_assets import get_account_keys
        from app.services.binance_spot import get_wallet

        keys = await get_account_keys(account_id, db)
        await asyncio.wait_for(get_wallet(keys, tag="connectivity_probe"), timeout=8.0)
        return True, "", ""
    except Exception as e:
        return False, *_classify_binance_error(e)


async def sync_bot_connectivity_on_view(
    db: "Session",
    bot: Any,
    source: str = "bot_view",
    *,
    force_probe: bool = False,
) -> Optional[Dict[str, str]]:
    """
    Called from bots /health and /events when operator views bot page.
    Probes Binance, writes bot_engine_events on failure, returns failure dict or None.
    """
    bot_id = int(bot.id)
    account_id = int(bot.account_id)
    now = time.time()
    if not force_probe:
        last_probe = _last_probe_by_bot.get(bot_id, 0.0)
        if now - last_probe < _PROBE_THROTTLE_SEC:
            fail = active_failure(account_id)
            if fail:
                emit_connectivity_events_for_bot(
                    db,
                    bot,
                    fail.get("error_code") or "BINANCE_UNREACHABLE",
                    fail.get("message") or "",
                    fail.get("source") or source,
                    force=(source == "events_load"),
                )
            return fail
    _last_probe_by_bot[bot_id] = now

    ok, code, msg = await probe_account_binance(account_id, db)
    if ok:
        note_binance_success(account_id, schedule_resume=False)
        try:
            try_auto_resume_paused_bots(db, account_id)
        except Exception as ar_ex:
            logger.debug("connectivity auto-resume on_view account_id=%s: %s", account_id, ar_ex)
        return None

    note_binance_failure(account_id, code, msg, source, emit_async=False)
    emit_connectivity_events_for_bot(db, bot, code, msg, source, force=(source == "events_load"))
    return {"error_code": code, "message": msg, "source": source}


def _emit_bot_events_async(account_id: int, error_code: str, message: str, source: str) -> None:
    def _run() -> None:
        try:
            from app.db.session import SessionLocal
            from app.db.models import Bot

            db = SessionLocal()
            try:
                bots = (
                    db.query(Bot)
                    .filter(
                        Bot.account_id == account_id,
                        Bot.status.in_(
                            ("running", "paused_error", "paused_insufficient_balance", "stopped", "paused")
                        ),
                    )
                    .all()
                )
                for bot in bots:
                    emit_connectivity_events_for_bot(db, bot, error_code, message, source)
            finally:
                db.close()
        except Exception as e:
            logger.warning("binance_connectivity emit async account_id=%s: %s", account_id, e)

    threading.Thread(target=_run, daemon=True, name="binance-bot-event").start()
