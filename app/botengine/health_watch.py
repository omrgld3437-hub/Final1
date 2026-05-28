"""
Per-bot lightweight health checks (worker ~60s). Emits HEALTH_WARN / HEALTH_CRITICAL to bot_engine_events.
Does not stop bots — alerts only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Throttle duplicate health events per bot (seconds)
_WARN_EMIT_INTERVAL = 300.0
_CRIT_EMIT_INTERVAL = 120.0

_CRITICAL_ERROR_CODES = frozenset({
    "API_UNAUTHORIZED",
    "BINANCE_UNREACHABLE",
    "SAFE_STOP",
    "BOT_LOOP_TOPLEVEL_EXCEPTION",
    "ACCOUNT_KEYS_MISSING",
    "WORKER_ONLY_OPERATION",
})

_HEALTH_MESSAGES: Dict[str, Dict[str, Any]] = {
    "TICK_STALE_WARN": {
        "severity": "warn",
        "title": "Tick gecikmesi",
        "cause": "Bot çalışıyor görünüyor ancak son tick beklenenden geç geldi.",
        "actions": [
            "Birkaç dakika bekleyin; worker yük altında olabilir.",
            "Logda ERROR veya Atlandı satırlarına bakın.",
            "Sorun sürerse botu durdurup yeniden başlatın.",
        ],
    },
    "TICK_STALE_CRIT": {
        "severity": "critical",
        "title": "Tick durdu",
        "cause": "Bot çalışır durumda ama uzun süredir tick almıyor; grid/emir mantığı işlemiyor olabilir.",
        "actions": [
            "Engine worker'ın çalıştığını doğrulayın (./start.command).",
            "Binance API anahtarı, IP beyaz listesi ve sunucu saatini kontrol edin.",
            "Logdaki kritik hataları inceleyin; gerekirse botu sonlandırıp yeniden oluşturun.",
        ],
    },
    "NO_TICK_YET": {
        "severity": "warn",
        "title": "Henüz tick yok",
        "cause": "Bot başlatıldı ancak henüz ilk tick kaydedilmedi.",
        "actions": [
            "Worker başlatma komutunun işlendiğini kontrol edin.",
            "1–2 dakika bekleyin; ilk alım/tick tamamlanana kadar normal olabilir.",
        ],
    },
    "FIRST_BUY_STUCK": {
        "severity": "warn",
        "title": "İlk alım bekleniyor",
        "cause": "Bot çalışıyor ama ilk base alımı henüz gerçekleşmedi (bakiye/limit engeli olabilir).",
        "actions": [
            "USDT bakiyesi ve bot bütçesini kontrol edin.",
            "Logda MIN_NOTIONAL veya yetersiz bakiye uyarısı var mı bakın.",
            "Minimum 10 USDT grid kuralına uygun bütçe kullanın.",
        ],
    },
    "STATE_ERROR": {
        "severity": "critical",
        "title": "Bot hata durumunda",
        "cause": "Son tick sırasında kritik bir hata kodu kaydedildi.",
        "actions": [
            "Logdaki Hata satırını okuyun.",
            "API anahtarı veya bakiye sorununu giderin.",
            "Düzeldikten sonra botu yeniden başlatmayı deneyin.",
        ],
    },
    "STATE_ERROR_WARN": {
        "severity": "warn",
        "title": "Uyarı kodu aktif",
        "cause": "Bot state'inde çözülmemiş bir uyarı/hata kodu var.",
        "actions": [
            "Son log kayıtlarını inceleyin.",
            "Geçici ağ/limit sorunları bir süre sonra düzelebilir.",
        ],
    },
    "LOOP_TASK_MISSING": {
        "severity": "critical",
        "title": "Bot döngüsü yok",
        "cause": "Veritabanında çalışıyor görünüyor ama engine içinde aktif bot task'ı bulunamadı.",
        "actions": [
            "Botu durdurup tekrar başlatın.",
            "Worker sürecinin çalıştığından emin olun.",
            "Sorun devam ederse sunucuyu yeniden başlatın.",
        ],
    },
    "REPEATED_ORDER_FAIL": {
        "severity": "warn",
        "title": "Tekrarlayan emir hatası",
        "cause": "Son dakikalarda birden fazla emir başarısız/atlandı.",
        "actions": [
            "Bütçe, minimum tutar (10 USDT) ve bakiye yeterliliğini kontrol edin.",
            "Grid yüzdelerini ve bütçeyi artırmayı düşünün.",
        ],
    },
    "BINANCE_UNREACHABLE": {
        "severity": "critical",
        "title": "Binance'e ulaşılamıyor",
        "cause": "Hesap bakiyesi veya piyasa verisi Binance API üzerinden okunamadı.",
        "actions": [
            "İnternet bağlantısını ve sunucu IP beyaz listesini kontrol edin.",
            "Binance API anahtarı ve Spot izinlerini doğrulayın.",
            "Birkaç dakika bekleyip bot sayfasını yenileyin.",
        ],
    },
}


def _expected_tick_interval_sec(bot) -> float:
    try:
        raw = json.loads(bot.config_json or "{}")
    except Exception:
        raw = {}
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    sym = (bot.symbol or "").upper()
    if strategy_id == "trdca_pro":
        return max(1.0, float(raw.get("tick_interval_ms") or 1000) / 1000.0)
    if sym == "MULTI" or strategy_id in ("multi_asset_rebalance",):
        sec = raw.get("interval_sec")
        if sec is not None:
            return max(1.0, float(sec))
        return max(1.0, float(raw.get("tick_interval_ms") or 5000) / 1000.0)
    return max(1.0, float(raw.get("tick_interval_ms") or 2000) / 1000.0)


def _parse_last_tick_ts(state: Optional[Dict[str, Any]]) -> Optional[int]:
    if not state:
        return None
    lt = state.get("last_tick_at")
    if lt is None:
        return None
    if isinstance(lt, (int, float)):
        return int(lt)
    if isinstance(lt, str):
        try:
            if lt.isdigit():
                return int(lt)
            dt = datetime.fromisoformat(lt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    if isinstance(lt, datetime):
        if lt.tzinfo is None:
            lt = lt.replace(tzinfo=timezone.utc)
        return int(lt.timestamp())
    return None


def _bot_started_ts(bot) -> Optional[int]:
    st = getattr(bot, "started_at", None)
    if st is None:
        return None
    if isinstance(st, datetime):
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        return int(st.timestamp())
    return None


def _is_worker_process() -> bool:
    role = os.getenv("DATABASE_ROLE", os.getenv("ROLE", "web")).strip().lower()
    return role == "worker"


def _loop_task_alive(bot_id: int) -> Optional[bool]:
    """None = unknown (v5 scheduler or web process). True/False = legacy worker orchestrator task."""
    if os.getenv("BOT_ENGINE_V5_SCHEDULER", "").strip() == "1":
        return None
    if not _is_worker_process():
        # Web/API cannot see in-process _tasks — avoid false LOOP_TASK_MISSING on /health
        return None
    try:
        from app.botengine.orchestrator import _tasks
        task = _tasks.get(bot_id)
        if task is None:
            return False
        return not task.done()
    except Exception:
        return None


def evaluate_bot_health(bot, state: Optional[Dict[str, Any]], db: Session) -> List[Dict[str, Any]]:
    """Return active alerts [{level, code, title, message, cause, actions, meta}]. No DB writes."""
    from app.botengine.state_store import load_state

    if state is None:
        state = load_state(db, bot.id) or {}
    status = (bot.status or "stopped").lower()
    alerts: List[Dict[str, Any]] = []

    # Binance bağlantı hatası — bot durdurulmuş/pause olsa da göster (manager + bot log)
    try:
        from app.services.binance_connectivity import active_failure
        bfail = active_failure(bot.account_id)
        if bfail:
            tmpl = _HEALTH_MESSAGES["BINANCE_UNREACHABLE"]
            alerts.append(_alert_from_tmpl(
                "BINANCE_UNREACHABLE", "critical", tmpl,
                {
                    "error_code": bfail.get("error_code"),
                    "source": bfail.get("source"),
                },
                message=bfail.get("message") or tmpl.get("title"),
            ))
    except Exception as e:
        logger.debug("health_watch binance_connectivity bot_id=%s: %s", bot.id, e)

    if status != "running":
        return alerts

    now = int(datetime.now(timezone.utc).timestamp())
    interval = _expected_tick_interval_sec(bot)
    last_tick = _parse_last_tick_ts(state)
    tick_age = (now - last_tick) if last_tick is not None else None

    warn_thresh = max(20.0, interval * 2.5)
    crit_thresh = max(60.0, interval * 5.0)

    if last_tick is None:
        started = _bot_started_ts(bot)
        if started and (now - started) > 90:
            tmpl = _HEALTH_MESSAGES["NO_TICK_YET"]
            alerts.append(_alert_from_tmpl("NO_TICK_YET", "warn", tmpl, {"tick_age_s": None, "interval_s": interval}))
    elif tick_age is not None:
        if tick_age >= crit_thresh:
            tmpl = _HEALTH_MESSAGES["TICK_STALE_CRIT"]
            alerts.append(_alert_from_tmpl(
                "TICK_STALE_CRIT", "critical", tmpl,
                {"tick_age_s": round(tick_age, 1), "interval_s": interval, "threshold_s": crit_thresh},
            ))
        elif tick_age >= warn_thresh:
            tmpl = _HEALTH_MESSAGES["TICK_STALE_WARN"]
            alerts.append(_alert_from_tmpl(
                "TICK_STALE_WARN", "warn", tmpl,
                {"tick_age_s": round(tick_age, 1), "interval_s": interval, "threshold_s": warn_thresh},
            ))

    err_code = (state.get("last_error_code") or "").strip()
    ack_at = int(state.get("health_ack_at") or 0)
    err_since = int(state.get("health_error_since") or 0)
    if err_code:
        stale_after_ack = ack_at > 0 and (not err_since or err_since <= ack_at)
        if not stale_after_ack:
            if err_code in _CRITICAL_ERROR_CODES:
                tmpl = _HEALTH_MESSAGES["STATE_ERROR"]
                alerts.append(_alert_from_tmpl(
                    "STATE_ERROR", "critical", tmpl,
                    {"error_code": err_code},
                    message=f"Kritik hata kodu: {err_code}",
                ))
            else:
                tmpl = _HEALTH_MESSAGES["STATE_ERROR_WARN"]
                alerts.append(_alert_from_tmpl(
                    "STATE_ERROR_WARN", "warn", tmpl,
                    {"error_code": err_code},
                    message=f"Uyarı kodu: {err_code}",
                ))

    ia_done = state.get("initial_allocation_done") is True
    base_bal = float(state.get("base_balance") or 0)
    if not ia_done and base_bal <= 0:
        started = _bot_started_ts(bot)
        if started and (now - started) > 120:
            tmpl = _HEALTH_MESSAGES["FIRST_BUY_STUCK"]
            alerts.append(_alert_from_tmpl("FIRST_BUY_STUCK", "warn", tmpl, {"initial_allocation_done": False}))

    loop_ok = _loop_task_alive(bot.id)
    if loop_ok is False:
        tmpl = _HEALTH_MESSAGES["LOOP_TASK_MISSING"]
        alerts.append(_alert_from_tmpl("LOOP_TASK_MISSING", "critical", tmpl, {}))

    try:
        from app.botengine.state_store import list_events
        recent = list_events(db, bot.id, limit=40)
        fail_count = 0
        cutoff = now - 900
        ack_at = int(state.get("health_ack_at") or 0)
        for ev in recent:
            if (ev.get("type") or "") != "SKIP_REASON":
                continue
            meta = ev.get("meta") or {}
            skip = (meta.get("skip_reason") or meta.get("error_code") or "").upper()
            if skip not in ("ORDER_FAILED", "LOT_SIZE", "MIN_NOTIONAL", "MIN_NOTIONAL_AFTER_CAP", "INSUFFICIENT_QUOTE", "ORDER_TIMEOUT"):
                continue
            ts = ev.get("ts")
            if ts:
                try:
                    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    ev_ts = int(t.timestamp())
                    if ev_ts < cutoff:
                        continue
                    if ack_at and ev_ts <= ack_at:
                        continue
                except Exception:
                    pass
            fail_count += 1
        if fail_count >= 3:
            tmpl = _HEALTH_MESSAGES["REPEATED_ORDER_FAIL"]
            alerts.append(_alert_from_tmpl(
                "REPEATED_ORDER_FAIL", "warn", tmpl,
                {"fail_count": fail_count, "window_min": 15},
            ))
    except Exception as e:
        logger.debug("health_watch recent skips bot_id=%s: %s", bot.id, e)

    return alerts


def _alert_from_tmpl(
    code: str,
    level: str,
    tmpl: Dict[str, Any],
    meta: Dict[str, Any],
    message: Optional[str] = None,
) -> Dict[str, Any]:
    msg = message or tmpl.get("title") or code
    if code.startswith("TICK_STALE") and meta.get("tick_age_s") is not None:
        msg = f"{tmpl.get('title')}: son tick {meta['tick_age_s']:.0f}s önce (beklenen aralık ~{meta.get('interval_s', '?')}s)"
    return {
        "level": level,
        "code": code,
        "title": tmpl.get("title") or code,
        "message": msg,
        "cause": tmpl.get("cause") or "",
        "actions": list(tmpl.get("actions") or []),
        "meta": meta,
    }


def _should_emit(state: Dict[str, Any], code: str, severity: str) -> bool:
    emit_map = state.setdefault("_health_last_emit", {})
    if not isinstance(emit_map, dict):
        emit_map = {}
        state["_health_last_emit"] = emit_map
    now = time.time()
    last = float(emit_map.get(code) or 0)
    interval = _CRIT_EMIT_INTERVAL if severity == "critical" else _WARN_EMIT_INTERVAL
    if now - last < interval:
        return False
    emit_map[code] = now
    return True


def emit_health_alerts(db: Session, bot, state: Dict[str, Any], alerts: List[Dict[str, Any]]) -> int:
    """Throttled append_event for new alerts. Returns count emitted."""
    from app.botengine.state_store import append_event, save_state

    if not alerts:
        return 0
    n = 0
    for a in alerts:
        code = a.get("code") or "HEALTH"
        level = a.get("level") or "warn"
        if not _should_emit(state, code, level):
            continue
        event_type = "HEALTH_CRITICAL" if level == "critical" else "HEALTH_WARN"
        meta = {
            "health_code": code,
            "severity": level,
            "title": a.get("title"),
            "cause": a.get("cause"),
            "actions": a.get("actions"),
            **(a.get("meta") or {}),
        }
        msg = a.get("message") or a.get("title") or code
        append_event(db, bot.id, bot.account_id, event_type, msg, meta)
        n += 1
    if n:
        try:
            save_state(db, bot.id, bot.account_id, state)
        except Exception as e:
            logger.debug("health_watch save_state emit map bot_id=%s: %s", bot.id, e)
    return n


def run_all_bot_health_checks(db: Session) -> int:
    """Worker hook: evaluate + emit for all running bots."""
    from app.db.models import Bot
    from app.botengine.state_store import load_state

    total = 0
    try:
        running = db.query(Bot).filter(Bot.status == "running").all()
        for bot in running:
            try:
                state = load_state(db, bot.id) or {}
                alerts = evaluate_bot_health(bot, state, db)
                total += emit_health_alerts(db, bot, state, alerts)
            except Exception as e:
                logger.warning("health_watch bot_id=%s: %s", bot.id, e)
    except Exception as e:
        logger.warning("health_watch run_all: %s", e)
    return total
