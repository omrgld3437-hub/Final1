"""
Per-bot lightweight health checks (worker ~60s). Emits HEALTH_WARN / HEALTH_CRITICAL to bot_engine_events.
Does not stop bots for recoverable faults — alerts only; loop crashes are auto-restarted while status=running.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_config
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Throttle duplicate health events per bot (seconds)
_WARN_EMIT_INTERVAL = 300.0
_CRIT_EMIT_INTERVAL = 120.0

_CRITICAL_ERROR_CODES = frozenset({
    "API_UNAUTHORIZED",
    "BINANCE_UNREACHABLE",
    "SAFE_STOP",
    "ACCOUNT_KEYS_MISSING",
    "WORKER_ONLY_OPERATION",
})

# Tick/loop exceptions: bot running kalır ve döngü devam eder / yeniden başlar.
# Bunlar durduruldu statüsü üretmemeli; aktif takip için sarı uyarı seviyesindedir.
_RECOVERABLE_LOOP_ERRORS = frozenset({
    "BOT_LOOP_TOPLEVEL_EXCEPTION",
    "BOT_LOOP_TRDCA_EXCEPTION",
    "BOT_TICK_EXCEPTION",
    "RUN_ACTION_EXCEPTION",
})

_FATAL_PAUSE_CODES = frozenset({
    "API_UNAUTHORIZED",
    "ACCOUNT_KEYS_MISSING",
    "INSUFFICIENT_BALANCE",
    "SAFE_STOP",
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
        "title": "Bot döngüsü yok — kurtarma bekleniyor",
        "cause": "Veritabanında çalışıyor görünüyor ama engine içinde aktif döngü yok; worker otomatik yeniden başlatmayı dener.",
        "actions": [
            "10–60 sn bekleyin; BOT_LOOP_AUTO_RESTART logu gelmeli.",
            "Gelmezse worker sürecini kontrol edin.",
        ],
    },
    "REPEATED_ORDER_FAIL": {
        "severity": "warn",
        "title": "Tekrarlayan emir hatası",
        "cause": "Son 15 dakikada birden fazla Binance emir reddi.",
        "actions": [
            "Logda binance kodunu kontrol edin (LOT_SIZE / MIN_NOTIONAL / -2010).",
            "Bütçe, grid yüzdesi ve min tutarı (≈10 USDT) artırın.",
            "Worker yeniden başlatıldıysa Resetle ile uyarıyı temizleyin.",
        ],
    },
    "LOT_SIZE": {
        "severity": "warn",
        "title": "Lot / step filtresi (LOT_SIZE)",
        "cause": "Emir miktarı Binance lot step veya minimum adım kurallarına uymuyor (-1013).",
        "actions": [
            "Grid base/quote yüzdesini veya bot bütçesini artırın.",
            "Sembol minQty ve stepSize değerine uygun miktar kullanın.",
            "Logdaki ilgili grid satırını (Satış/Alım #n) kontrol edin.",
        ],
    },
    "MIN_NOTIONAL": {
        "severity": "warn",
        "title": "Minimum tutar (MIN_NOTIONAL)",
        "cause": "Emir notional değeri Binance minimum işlem tutarının altında.",
        "actions": [
            "Grid emir tutarını veya bütçeyi artırın (en az ~10 USDT önerilir).",
            "İlk alım ve grid yüzdelerini gözden geçirin.",
        ],
    },
    "MIN_NOTIONAL_AFTER_CAP": {
        "severity": "warn",
        "title": "Minimum tutar (cap sonrası)",
        "cause": "Bakiye sınırına göre küçültülen emir yine de minimum tutarın altında kaldı.",
        "actions": [
            "Serbest USDT veya base bakiyesini artırın.",
            "Grid yüzdesini düşürüp bütçeyi yükseltin.",
        ],
    },
    "ORDER_FAILED": {
        "severity": "warn",
        "title": "Emir gönderilemedi",
        "cause": "Binance emir isteği reddedildi veya ağ hatası oluştu.",
        "actions": [
            "Logdaki binance kod ve mesajına bakın.",
            "API anahtarı, IP beyaz listesi ve Spot izinlerini doğrulayın.",
        ],
    },
    "INSUFFICIENT_QUOTE": {
        "severity": "warn",
        "title": "Yetersiz USDT",
        "cause": "Emir için yeterli serbest quote (USDT) yok.",
        "actions": [
            "Cüzdan USDT bakiyesini ve bot bütçesini kontrol edin.",
            "Grid alım yüzdelerini düşürün.",
        ],
    },
    "ORDER_TIMEOUT": {
        "severity": "warn",
        "title": "Emir zaman aşımı",
        "cause": "Binance emir yanıtı zaman aşımına uğradı.",
        "actions": [
            "Ağ bağlantısını kontrol edin; birkaç dakika sonra tekrar denenecek.",
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
    "BOT_CONTINUES_ON_ERROR": {
        "severity": "warn",
        "title": "Tick hatası — bot çalışıyor",
        "cause": "Tick sırasında toparlanabilir bir hata oluştu; bot durdurulmadı, döngü çalışmaya devam ediyor.",
        "actions": [
            "Logdaki hata detayına bakın.",
            "Sorun sürerse grid bütçesi, API veya worker kaynağını kontrol edin.",
        ],
    },
    "BOT_LOOP_AUTO_RESTART": {
        "severity": "critical",
        "title": "Bot döngüsü yeniden başlatılıyor",
        "cause": "Engine döngüsü beklenmedik şekilde sonlandı; veritabanında çalışıyor görünüyor — worker döngüyü yeniden açıyor.",
        "actions": [
            "Birkaç saniye bekleyin; tick ve loglar devam etmeli.",
            "Tekrarlanırsa worker sürecini ve Binance bağlantısını kontrol edin.",
        ],
    },
    "PRICE_STALE_OR_MISSING": {
        "severity": "warn",
        "title": "Fiyat verisi yok / bayat",
        "cause": "Piyasa fiyatı okunamadı; bu tick'te emir gönderilmedi, döngü bekleyerek devam ediyor.",
        "actions": [
            "Market data / worker WS bağlantısını kontrol edin.",
            "Sembolün Binance'te aktif olduğundan emin olun.",
        ],
    },
    "REPEATED_LOCK_BUSY": {
        "severity": "warn",
        "title": "Tekrarlayan kilit meşgul",
        "cause": "Son 15 dakikada sembol kilidi nedeniyle birden fazla tick atlandı.",
        "actions": [
            "Aynı hesapta başka bot veya işlem kilidi tutuyor olabilir.",
            "Gerekirse diğer botları durdurun veya kilidi serbest bırakın.",
        ],
    },
    "REPEATED_SLIPPAGE": {
        "severity": "warn",
        "title": "Tekrarlayan kayma uyarısı",
        "cause": "Son 15 dakikada birden fazla yüksek kayma (slippage) kaydı.",
        "actions": [
            "Volatil piyasa veya düşük likidite olabilir.",
            "Grid aralığı veya bütçeyi gözden geçirin.",
        ],
    },
    "CONNECTIVITY_DEGRADED": {
        "severity": "warn",
        "title": "Bağlantı zayıf (backoff)",
        "cause": "Bot geçici backoff modunda; emirler sınırlı veya gecikmeli olabilir.",
        "actions": [
            "Binance API ve ağı kontrol edin.",
            "Düzelince otomatik devam eder.",
        ],
    },
    "WALLET_SNAPSHOT_STALE": {
        "severity": "warn",
        "title": "Cüzdan verisi güncel değil",
        "cause": "Dashboard spot bakiyesi son canlı Binance cüzdan yenilemesinden değil, eski snapshot'tan gösteriliyor.",
        "actions": [
            "Dashboard Binance sekmesinde cüzdan yenilemesini kontrol edin.",
            "API anahtarı, IP beyaz listesi ve Spot okuma iznini doğrulayın.",
            "Bot tick atıyorsa işlem döngüsü devam eder; bu uyarı cüzdan görünürlüğü içindir.",
        ],
    },
    "INSUFFICIENT_BALANCE": {
        "severity": "critical",
        "title": "Yetersiz bakiye — bot durduruldu",
        "cause": "Emir gönderilemedi: Binance hesabında yeterli serbest bakiye yok. Bot manuel olarak yeniden başlatılmalı.",
        "actions": [
            "Binance cüzdanına yeterli USDT ekleyin (bot bütçesini karşılayacak kadar).",
            "Bütçeyi düşürmek istiyorsanız 'Ayarlar' bölümünden initial_capital_usdt'yi güncelleyin.",
            "Hazır olunca 'Başlat' butonuna basarak botu yeniden çalıştırın.",
        ],
    },
}

_STATE_SKIP_HEALTH_KEYS = frozenset({
    "LOT_SIZE",
    "MIN_NOTIONAL",
    "MIN_NOTIONAL_AFTER_CAP",
    "ORDER_FAILED",
    "INSUFFICIENT_QUOTE",
    "ORDER_TIMEOUT",
})

_CONNECTIVITY_HEALTH_DEDUP_KEYS = frozenset({
    "API_UNAUTHORIZED",
    "ACCOUNT_KEYS_MISSING",
    "BINANCE_UNREACHABLE",
})

def _wallet_snapshot_warn_age_sec() -> float:
    try:
        return float(get_config().get("wallet_snapshot_warn_age_sec", 900))
    except Exception:
        return float(os.getenv("WALLET_SNAPSHOT_WARN_AGE_SEC", "900"))


def _account_wallet_stale_alert(db: Optional[Session], account_id: int) -> Optional[Dict[str, Any]]:
    """Return warning when the latest spot wallet snapshot is old enough to be user-visible stale."""
    if db is None or not account_id:
        return None
    try:
        from sqlalchemy import desc
        from app.db.models import Account, AssetSnapshot

        acc = db.query(Account).filter(Account.id == int(account_id)).first()
        if not acc:
            return None
        if not (getattr(acc, "api_key_enc", None) and getattr(acc, "api_secret_enc", None)):
            return None
        row = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == int(account_id))
            .order_by(desc(AssetSnapshot.timestamp))
            .limit(1)
            .first()
        )
        now = datetime.now(timezone.utc)
        if not row or not getattr(row, "timestamp", None):
            age_s: Optional[float] = None
            ts_iso = None
        else:
            ts = row.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_s = max(0.0, (now - ts).total_seconds())
            ts_iso = ts.isoformat().replace("+00:00", "Z")
        threshold_s = _wallet_snapshot_warn_age_sec()
        if age_s is not None and age_s < threshold_s:
            return None
        tmpl = _HEALTH_MESSAGES["WALLET_SNAPSHOT_STALE"]
        meta = {
            "snapshot_age_s": round(age_s, 1) if age_s is not None else None,
            "last_snapshot_at": ts_iso,
            "threshold_s": threshold_s,
        }
        if age_s is None:
            msg = "Cüzdan verisi henüz canlı snapshot üretmedi"
        else:
            msg = f"Cüzdan verisi güncel değil: son snapshot {age_s / 60:.0f} dk önce"
        return _alert_from_tmpl("WALLET_SNAPSHOT_STALE", "warn", tmpl, meta, message=msg)
    except Exception as e:
        logger.debug("health_watch wallet stale account_id=%s: %s", account_id, e)
        return None


def _recent_event_with_code(db: Session, bot_id: int, code: str, within_sec: float = 900.0) -> bool:
    """True if SKIP/ERROR log already documents this code (skip duplicate HEALTH emit)."""
    try:
        from app.botengine.state_store import list_events

        c = (code or "").strip().upper()
        if not c:
            return False
        cutoff = time.time() - within_sec
        for ev in list_events(db, bot_id, limit=30):
            ty = (ev.get("type") or "").upper()
            if ty not in ("SKIP_REASON", "ERROR"):
                continue
            meta = ev.get("meta") or {}
            ec = (meta.get("skip_reason") or meta.get("error_code") or "").strip().upper()
            if ec != c:
                continue
            ts = ev.get("ts")
            if not ts:
                return True
            try:
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


def _count_recent_events(
    db: Session,
    bot_id: int,
    *,
    types: Optional[Tuple[str, ...]] = None,
    message_contains: Optional[str] = None,
    within_sec: float = 900.0,
) -> int:
    try:
        from app.botengine.state_store import list_events

        cutoff = time.time() - within_sec
        n = 0
        for ev in list_events(db, bot_id, limit=50):
            ty = (ev.get("type") or "").upper()
            if types and ty not in types:
                continue
            if message_contains and message_contains.lower() not in str(ev.get("message") or "").lower():
                continue
            ts = ev.get("ts")
            if ts:
                try:
                    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    if t.timestamp() < cutoff:
                        continue
                except Exception:
                    pass
            n += 1
        return n
    except Exception:
        return 0


def _recent_initial_fill(db: Session, bot_id: int, within_sec: float = 600.0) -> bool:
    try:
        from app.botengine.state_store import list_events

        cutoff = time.time() - within_sec
        for ev in list_events(db, bot_id, limit=25):
            if (ev.get("type") or "").upper() != "ORDER_FILLED":
                continue
            meta = ev.get("meta") or {}
            if meta.get("reason") != "initial_allocation":
                continue
            ts = ev.get("ts")
            if not ts:
                return True
            try:
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


def emit_resilience_continue(
    db: Session,
    bot_id: int,
    account_id: int,
    error_code: str,
    detail: str,
    *,
    error_id: Optional[str] = None,
    loop_id: Optional[str] = None,
) -> None:
    """Tick absorbed: uyarı logu + bot çalışmaya devam bilgisi (throttled)."""
    from app.botengine.state_store import append_event, load_state, save_state

    code = (error_code or "BOT_TICK_EXCEPTION").strip().upper()
    state = load_state(db, bot_id) or {}
    emit_map = state.setdefault("_resilience_last_emit", {})
    if not isinstance(emit_map, dict):
        emit_map = {}
        state["_resilience_last_emit"] = emit_map
    now = time.time()
    if now - float(emit_map.get(code) or 0) < 90.0:
        return
    emit_map[code] = now
    short = (detail or "")[:240]
    meta = {
        "health_code": "BOT_CONTINUES_ON_ERROR",
        "error_code": code,
        "continues_running": True,
        "error_id": error_id,
        "loop_id": loop_id,
    }
    append_event(
        db,
        bot_id,
        account_id,
        "HEALTH_WARN",
        f"Tick hatası ({code}) — bot çalışmaya devam ediyor" + (f" · {short}" if short else ""),
        meta,
    )
    append_event(
        db,
        bot_id,
        account_id,
        "INFO",
        f"Dayanıklılık: {code} kaydedildi, döngü durmadan devam ediyor",
        {"event_kind": "BOT_RESILIENCE", "error_code": code, **meta},
    )
    try:
        save_state(db, bot_id, account_id, state)
    except Exception:
        pass


def _parse_db_ts(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            if s.isdigit():
                return int(s)
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


def _worker_started_ts() -> Optional[int]:
    try:
        from pathlib import Path

        p = Path(__file__).resolve().parents[2] / ".run" / "worker.started_at"
        if p.is_file():
            return int(float(p.read_text(encoding="utf-8").strip()))
    except Exception:
        pass
    return None


def _compute_unreachable_sec(
    state: Optional[Dict[str, Any]],
    now: Optional[float] = None,
    *,
    updated_at_ts: Optional[int] = None,
) -> int:
    """Son tick / state güncellemesi / worker başlangıcından bu yana geçen süre (sn)."""
    now_ts = int(now if now is not None else time.time())
    estimates: List[int] = []
    last_tick = _parse_last_tick_ts(state)
    if last_tick is not None:
        estimates.append(now_ts - last_tick)
    if updated_at_ts is not None:
        estimates.append(now_ts - updated_at_ts)
    ws = _worker_started_ts()
    if ws is not None:
        estimates.append(now_ts - ws)
    if estimates:
        return max(1, max(estimates))
    return 1


def _format_tr_duration(seconds: Optional[int]) -> str:
    sec = max(1, int(seconds or 1))
    if sec < 60:
        return f"{sec} saniye"
    mins, rem = divmod(sec, 60)
    if mins < 60:
        if rem >= 30:
            return f"{mins} dakika {rem} saniye"
        if mins == 1:
            return "1 dakika"
        return f"{mins} dakika"
    hours, mins = divmod(mins, 60)
    if mins > 0:
        return f"{hours} saat {mins} dakika"
    if hours == 1:
        return "1 saat"
    return f"{hours} saat"


def humanize_restart_reason(reason: str, *, unavailable_sec: Optional[int] = None) -> str:
    """Teknik restart_reason kodunu Türkçe kullanıcı mesajına çevirir."""
    r = (reason or "").strip()
    low = r.lower()
    if not r:
        dur = _format_tr_duration(unavailable_sec)
        return f"Sunucu yeniden başlatıldığı için bot otomatik yeniden başlatıldı. {dur} erişim alınamadı."
    if "worker_poll" in low or "engine_tick" in low or "ensure_running_bots" in low:
        dur = _format_tr_duration(unavailable_sec)
        return (
            f"Sunucu yeniden başlatıldığı için bot otomatik yeniden başlatıldı. "
            f"{dur} erişim alınamadı."
        )
    if low in ("loop_exit", "loop_crash", "loop_exception"):
        dur = _format_tr_duration(unavailable_sec)
        return (
            f"Bot döngüsü beklenmedik şekilde sonlandı; worker otomatik yeniden başlattı. "
            f"{dur} erişim alınamadı."
        )
    return r


def emit_loop_auto_restart(
    db: Session,
    bot_id: int,
    account_id: int,
    reason: str,
    *,
    loop_id: Optional[str] = None,
) -> None:
    """Loop crashed but DB still running — worker restarting task."""
    from app.botengine.state_store import append_event, load_state, save_state

    state = load_state(db, bot_id) or {}
    emit_map = state.setdefault("_resilience_last_emit", {})
    if not isinstance(emit_map, dict):
        emit_map = {}
        state["_resilience_last_emit"] = emit_map
    now = time.time()
    last_emit = float(emit_map.get("BOT_LOOP_AUTO_RESTART") or 0)
    worker_started = _worker_started_ts()
    new_worker_boot = bool(worker_started and last_emit > 0 and last_emit < worker_started)
    if not new_worker_boot and now - last_emit < 60.0:
        return
    emit_map["BOT_LOOP_AUTO_RESTART"] = now
    updated_at_ts: Optional[int] = None
    try:
        from sqlalchemy import text

        row = db.execute(
            text("SELECT updated_at FROM bot_engine_state WHERE bot_id = :bid"),
            {"bid": bot_id},
        ).fetchone()
        if row:
            updated_at_ts = _parse_db_ts(row[0])
    except Exception:
        pass
    unavailable_sec = _compute_unreachable_sec(state, now, updated_at_ts=updated_at_ts)
    human = humanize_restart_reason(reason, unavailable_sec=unavailable_sec)
    meta = {
        "health_code": "BOT_LOOP_AUTO_RESTART",
        "restart_reason": reason,
        "restart_reason_label": human,
        "unavailable_sec": unavailable_sec,
        "loop_id": loop_id,
        "continues_running": True,
    }
    append_event(
        db,
        bot_id,
        account_id,
        "HEALTH_CRITICAL",
        "Bot döngüsü sonlandı — worker otomatik yeniden başlatıyor (çalışmaya devam)",
        meta,
    )
    append_event(
        db,
        bot_id,
        account_id,
        "INFO",
        human,
        {"event_kind": "BOT_RESILIENCE", **meta},
    )
    try:
        save_state(db, bot_id, account_id, state)
    except Exception:
        pass
    try:
        from app.db.models import Bot
        from app.services.binance_connectivity import mark_pending_connectivity_stable

        bot = db.query(Bot).filter(Bot.id == int(bot_id)).first()
        if bot and (bot.status or "").lower() == "running":
            mark_pending_connectivity_stable(
                db, bot, state, previous_error="WORKER_RESTART",
            )
            save_state(db, bot_id, account_id, state)
    except Exception as flush_ex:
        logger.debug("mark_pending_connectivity_stable bot_id=%s: %s", bot_id, flush_ex)


def emit_price_stale(db: Session, bot_id: int, account_id: int, symbol: str) -> None:
    from app.botengine.state_store import append_event

    append_event(
        db,
        bot_id,
        account_id,
        "HEALTH_WARN",
        f"Fiyat yok veya bayat — {symbol} tick atlandı, döngü devam ediyor",
        {
            "health_code": "PRICE_STALE_OR_MISSING",
            "symbol": symbol,
            "continues_running": True,
        },
    )


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

    # Binance bağlantı hatası — bot durdurulmuş/pause olsa da göster (manager + bot log).
    # Geçici kesintilerde (< _TRANSIENT_OUTAGE_LOG_DELAY_SEC) CRITICAL gösterme.
    try:
        import time as _time
        from app.services.binance_connectivity import (
            active_failure,
            _first_fail_ts_by_account,
            _TRANSIENT_OUTAGE_LOG_DELAY_SEC,
        )
        bfail = active_failure(bot.account_id)
        if bfail:
            first_fail = _first_fail_ts_by_account.get(int(bot.account_id), 0)
            fail_age = _time.time() - first_fail if first_fail > 0 else _TRANSIENT_OUTAGE_LOG_DELAY_SEC + 1
            if fail_age >= _TRANSIENT_OUTAGE_LOG_DELAY_SEC:
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
    if not any(a.get("code") == "BINANCE_UNREACHABLE" for a in alerts):
        wallet_alert = _account_wallet_stale_alert(db, bot.account_id)
        if wallet_alert:
            alerts.append(wallet_alert)

    if status == "paused_insufficient_balance":
        tmpl = _HEALTH_MESSAGES["INSUFFICIENT_BALANCE"]
        alerts.append(_alert_from_tmpl("INSUFFICIENT_BALANCE", "critical", tmpl, {}))
        return alerts

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
    backoff_until = float(state.get("backoff_until") or 0)
    if backoff_until > now and status == "running":
        tmpl = _HEALTH_MESSAGES.get("CONNECTIVITY_DEGRADED")
        if tmpl:
            alerts.append(_alert_from_tmpl(
                "CONNECTIVITY_DEGRADED", "warn", tmpl,
                {"backoff_until": backoff_until},
            ))

    price_stale_since = int(state.get("price_stale_since") or 0)
    if price_stale_since and (now - price_stale_since) >= 90:
        tmpl = _HEALTH_MESSAGES["PRICE_STALE_OR_MISSING"]
        alerts.append(_alert_from_tmpl(
            "PRICE_STALE_OR_MISSING", "warn", tmpl,
            {"price_stale_since": price_stale_since, "stale_s": now - price_stale_since},
        ))

    if err_code:
        stale_after_ack = ack_at > 0 and (not err_since or err_since <= ack_at)
        if not stale_after_ack:
            if err_code in _RECOVERABLE_LOOP_ERRORS:
                tmpl = _HEALTH_MESSAGES["BOT_CONTINUES_ON_ERROR"]
                alerts.append(_alert_from_tmpl(
                    "BOT_CONTINUES_ON_ERROR", "warn", tmpl,
                    {"error_code": err_code, "continues_running": True},
                    message=f"Tick hatası ({err_code}) — bot çalışmaya devam ediyor",
                ))
            elif err_code in _CRITICAL_ERROR_CODES or err_code in _FATAL_PAUSE_CODES:
                tmpl = _HEALTH_MESSAGES["STATE_ERROR"]
                alerts.append(_alert_from_tmpl(
                    "STATE_ERROR", "critical", tmpl,
                    {"error_code": err_code},
                    message=f"Kritik hata: {err_code}",
                ))
            elif err_code in _STATE_SKIP_HEALTH_KEYS:
                tmpl = _HEALTH_MESSAGES[err_code]
                alerts.append(_alert_from_tmpl(
                    err_code,
                    str(tmpl.get("severity") or "warn"),
                    tmpl,
                    {"error_code": err_code},
                    message=str(tmpl.get("title") or err_code),
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
        if started and (now - started) > 120 and not _recent_initial_fill(db, bot.id):
            tmpl = _HEALTH_MESSAGES["FIRST_BUY_STUCK"]
            alerts.append(_alert_from_tmpl("FIRST_BUY_STUCK", "warn", tmpl, {"initial_allocation_done": False}))

    loop_ok = _loop_task_alive(bot.id)
    if loop_ok is False:
        # A fresh tick proves the scheduler is advancing this bot. In newer scheduler
        # modes there may be no long-lived per-bot task to inspect, so do not raise
        # a false critical while the state is actively updating.
        if last_tick is None or tick_age is None or tick_age >= crit_thresh:
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
            if meta.get("preflight"):
                continue
            if skip in ("LOT_SIZE", "MIN_NOTIONAL", "MIN_NOTIONAL_AFTER_CAP"):
                if not meta.get("binance_code"):
                    continue
            if skip not in ("ORDER_FAILED", "LOT_SIZE", "MIN_NOTIONAL", "INSUFFICIENT_QUOTE"):
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

    lock_busy_n = _count_recent_events(db, bot.id, types=("LOCK_BUSY", "LOCK_LEASE_EXPIRED"), within_sec=900.0)
    if lock_busy_n >= 5:
        tmpl = _HEALTH_MESSAGES["REPEATED_LOCK_BUSY"]
        alerts.append(_alert_from_tmpl(
            "REPEATED_LOCK_BUSY", "warn", tmpl, {"lock_skip_count": lock_busy_n, "window_min": 15},
        ))

    slip_n = _count_recent_events(db, bot.id, types=("SLIPPAGE_WARN",), within_sec=900.0)
    if slip_n >= 3:
        tmpl = _HEALTH_MESSAGES["REPEATED_SLIPPAGE"]
        alerts.append(_alert_from_tmpl(
            "REPEATED_SLIPPAGE", "warn", tmpl, {"slippage_count": slip_n, "window_min": 15},
        ))

    return alerts


_UNSET = object()


def evaluate_bot_health_lite(
    bot,
    state: Optional[Dict[str, Any]],
    *,
    account_failure=_UNSET,
    account_wallet_alert: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """List view için DB-sorgusuz health değerlendirmesi.

    evaluate_bot_health'in event tarayan kısımlarını (list_events, _count_recent_events,
    _recent_initial_fill) atlar. account_failure önceden çözülmüşse paylaşılmış olarak
    geçirilebilir; aksi halde bir kez içeride çözülür. /bots listesinde bot başına ek
    SQL çağırılmamasını sağlar.
    """
    state = state or {}
    status = (bot.status or "stopped").lower()
    alerts: List[Dict[str, Any]] = []

    if account_failure is _UNSET:
        try:
            from app.services.binance_connectivity import active_failure
            account_failure = active_failure(bot.account_id)
        except Exception:
            account_failure = None
    if account_failure:
        # Geçici kesintilerde CRITICAL gösterme (aynı filtre evaluate_bot_health'te de var)
        try:
            import time as _time
            from app.services.binance_connectivity import (
                _first_fail_ts_by_account,
                _TRANSIENT_OUTAGE_LOG_DELAY_SEC,
            )
            first_fail = _first_fail_ts_by_account.get(int(bot.account_id), 0)
            fail_age = _time.time() - first_fail if first_fail > 0 else _TRANSIENT_OUTAGE_LOG_DELAY_SEC + 1
        except Exception:
            fail_age = _TRANSIENT_OUTAGE_LOG_DELAY_SEC + 1
        if fail_age >= _TRANSIENT_OUTAGE_LOG_DELAY_SEC:
            tmpl = _HEALTH_MESSAGES["BINANCE_UNREACHABLE"]
            alerts.append(_alert_from_tmpl(
                "BINANCE_UNREACHABLE", "critical", tmpl,
                {
                    "error_code": account_failure.get("error_code"),
                    "source": account_failure.get("source"),
                },
                message=account_failure.get("message") or tmpl.get("title"),
            ))
    if not any(a.get("code") == "BINANCE_UNREACHABLE" for a in alerts) and account_wallet_alert:
        alerts.append(dict(account_wallet_alert))

    # paused_insufficient_balance: status running değil ama kullanıcıya kritik bildir
    if status == "paused_insufficient_balance":
        tmpl = _HEALTH_MESSAGES["INSUFFICIENT_BALANCE"]
        alerts.append(_alert_from_tmpl(
            "INSUFFICIENT_BALANCE", "critical", tmpl, {},
        ))
        return alerts

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
            alerts.append(_alert_from_tmpl(
                "NO_TICK_YET", "warn", tmpl,
                {"tick_age_s": None, "interval_s": interval},
            ))
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

    backoff_until = float(state.get("backoff_until") or 0)
    if backoff_until > now:
        tmpl = _HEALTH_MESSAGES.get("CONNECTIVITY_DEGRADED")
        if tmpl:
            alerts.append(_alert_from_tmpl(
                "CONNECTIVITY_DEGRADED", "warn", tmpl, {"backoff_until": backoff_until},
            ))

    price_stale_since = int(state.get("price_stale_since") or 0)
    if price_stale_since and (now - price_stale_since) >= 90:
        tmpl = _HEALTH_MESSAGES["PRICE_STALE_OR_MISSING"]
        alerts.append(_alert_from_tmpl(
            "PRICE_STALE_OR_MISSING", "warn", tmpl,
            {"price_stale_since": price_stale_since, "stale_s": now - price_stale_since},
        ))

    err_code = (state.get("last_error_code") or "").strip()
    ack_at = int(state.get("health_ack_at") or 0)
    err_since = int(state.get("health_error_since") or 0)
    if err_code:
        stale_after_ack = ack_at > 0 and (not err_since or err_since <= ack_at)
        if not stale_after_ack:
            if err_code in _RECOVERABLE_LOOP_ERRORS:
                tmpl = _HEALTH_MESSAGES["BOT_CONTINUES_ON_ERROR"]
                alerts.append(_alert_from_tmpl(
                    "BOT_CONTINUES_ON_ERROR", "warn", tmpl,
                    {"error_code": err_code, "continues_running": True},
                    message=f"Tick hatası ({err_code}) — bot çalışmaya devam ediyor",
                ))
            elif err_code in _CRITICAL_ERROR_CODES or err_code in _FATAL_PAUSE_CODES:
                tmpl = _HEALTH_MESSAGES["STATE_ERROR"]
                alerts.append(_alert_from_tmpl(
                    "STATE_ERROR", "critical", tmpl,
                    {"error_code": err_code},
                    message=f"Kritik hata: {err_code}",
                ))
            elif err_code in _STATE_SKIP_HEALTH_KEYS:
                tmpl = _HEALTH_MESSAGES[err_code]
                alerts.append(_alert_from_tmpl(
                    err_code,
                    str(tmpl.get("severity") or "warn"),
                    tmpl,
                    {"error_code": err_code},
                    message=str(tmpl.get("title") or err_code),
                ))
            else:
                tmpl = _HEALTH_MESSAGES["STATE_ERROR_WARN"]
                alerts.append(_alert_from_tmpl(
                    "STATE_ERROR_WARN", "warn", tmpl,
                    {"error_code": err_code},
                    message=f"Uyarı kodu: {err_code}",
                ))

    loop_ok = _loop_task_alive(bot.id)
    if loop_ok is False:
        # A fresh tick proves the scheduler is advancing this bot. In newer scheduler
        # modes there may be no long-lived per-bot task to inspect, so do not raise
        # a false critical while the state is actively updating.
        if last_tick is None or tick_age is None or tick_age >= crit_thresh:
            tmpl = _HEALTH_MESSAGES["LOOP_TASK_MISSING"]
            alerts.append(_alert_from_tmpl("LOOP_TASK_MISSING", "critical", tmpl, {}))

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
        ec = ((a.get("meta") or {}).get("error_code") or code or "").strip().upper()
        if ec in (_STATE_SKIP_HEALTH_KEYS | _CONNECTIVITY_HEALTH_DEDUP_KEYS) and _recent_event_with_code(db, bot.id, ec):
            continue
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
