"""
Hata Asistani kaynakli chat mesajlari icin otomatik tani ve guvenli aksiyon katmani.

Bu servis kullanici adina genis sistem yetkisi kullanmaz. Sadece ilgili kullanicinin
hesabindaki botu inceler, guvenli durumlarda START komutu kuyruga alir ve sohbet
icine net bir admin/sistem cevabi yazar.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Account, Bot, ChatMessage, ChatThread


ACK_MESSAGE_DELAY_SEC = 2.0
FINAL_MESSAGE_DELAY_SEC = 9.0

RECOVERABLE_START_CODES = {
    "BINANCE_UNREACHABLE",
    "BINANCE_RATE_LIMIT",
    "CONNECTIVITY_LOST",
    "CONNECTIVITY_PAUSED",
    "BOT_LOOP_AUTO_RESTART",
    "LOOP_TASK_MISSING",
    "TICK_STALE_CRIT",
    "TICK_STALE_WARN",
    "NO_TICK_YET",
    "ORDER_TIMEOUT",
    "PRICE_STALE_OR_MISSING",
}

BLOCKED_START_CODES = {
    "API_UNAUTHORIZED",
    "ACCOUNT_KEYS_EMPTY",
    "ACCOUNT_KEYS_DECRYPT_FAIL",
    "ACCOUNT_KEYS_MISSING",
    "CLOCK_DRIFT",
    "INSUFFICIENT_BALANCE",
    "INSUFFICIENT_QUOTE",
    "BINANCE_FREE_QUOTE_INSUFFICIENT",
    "BINANCE_FREE_BASE_INSUFFICIENT",
    "VIRTUAL_BUDGET_INSUFFICIENT",
    "GRID_NOTIONAL_TOO_LOW",
    "MIN_NOTIONAL",
    "MIN_NOTIONAL_AFTER_CAP",
    "LOT_SIZE",
    "SAFE_STOP",
    "DAILY_LOSS_LIMIT",
    "MAX_BUY_LEVELS_EXCEEDED",
}

ERROR_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "API_UNAUTHORIZED": {
        "title": "API/IP yetki hatasi",
        "severity": "critical",
        "auto": "Bot guvenli beklemede kalir; otomatik baslatma yapilmadi.",
        "actions": [
            "Binance API anahtarinin Spot trade izni acik olmali.",
            "Sunucu IP adresi Binance whitelist icinde olmali.",
            "Anahtar yenilendiyse hesap ayarlarindan tekrar kaydedilmeli.",
        ],
    },
    "ACCOUNT_KEYS_EMPTY": {
        "title": "API anahtari yok",
        "severity": "critical",
        "auto": "Otomatik islem yapilmadi; anahtar olmadan emir gondermek guvenli degil.",
        "actions": ["Hesap ayarlarindan Binance API key/secret ekleyin.", "Kayit sonrasi botu yeniden baslatin."],
    },
    "ACCOUNT_KEYS_DECRYPT_FAIL": {
        "title": "API anahtari cozumlenemedi",
        "severity": "critical",
        "auto": "Otomatik islem yapilmadi; anahtar tekrar kaydedilmeli.",
        "actions": ["API anahtarini silip tekrar kaydedin.", "Sorun surerse admin veri sifreleme durumunu kontrol etmeli."],
    },
    "ACCOUNT_KEYS_MISSING": {
        "title": "API anahtari eksik",
        "severity": "critical",
        "auto": "Otomatik islem yapilmadi.",
        "actions": ["Binance API bilgilerini kaydedin.", "Spot izinleri ve IP whitelist tamamlaninca botu baslatin."],
    },
    "CLOCK_DRIFT": {
        "title": "Sunucu saat farki",
        "severity": "critical",
        "auto": "Emir gonderimi durdurulur; saat duzelmeden otomatik baslatma yapilmadi.",
        "actions": ["Sunucu saat senkronizasyonunu kontrol edin.", "Saat duzeldikten sonra botu tekrar baslatin."],
    },
    "BINANCE_UNREACHABLE": {
        "title": "Binance baglantisi kesik",
        "severity": "critical",
        "auto": "Canli baglanti tekrar kontrol edilir; duzeldiyse bot START kuyruguna alinabilir.",
        "actions": ["Binance erisimi ve IP whitelist kontrol edilmeli.", "Gecici kesintiyse sistem yeniden deneyecek."],
    },
    "BINANCE_RATE_LIMIT": {
        "title": "Binance rate limit",
        "severity": "warn",
        "auto": "Kisa bekleme sonrasi devam beklenir; bot durduysa START kuyruga alinabilir.",
        "actions": ["Birkaç dakika bekleyin.", "Ayni anda cok fazla bot/istek varsa azaltin."],
    },
    "INSUFFICIENT_BALANCE": {
        "title": "Yetersiz bakiye",
        "severity": "critical",
        "auto": "Otomatik baslatma yapilmadi; bakiye tamamlanmadan bot tekrar durur.",
        "actions": ["USDT/base bakiyesini tamamlayin.", "Bot butcesini veya grid yuzdelerini dusurun."],
    },
    "INSUFFICIENT_QUOTE": {
        "title": "Yetersiz quote bakiye",
        "severity": "warn",
        "auto": "Otomatik baslatma yapilmadi.",
        "actions": ["Serbest USDT bakiyesini artirin.", "Alim grid paylarini dusurun."],
    },
    "BINANCE_FREE_QUOTE_INSUFFICIENT": {
        "title": "Cuzdanda yeterli USDT yok",
        "severity": "warn",
        "auto": "Otomatik baslatma yapilmadi.",
        "actions": ["Serbest quote bakiyesini artirin.", "Bot butcesini mevcut bakiyeye gore dusurun."],
    },
    "BINANCE_FREE_BASE_INSUFFICIENT": {
        "title": "Cuzdanda yeterli coin yok",
        "severity": "warn",
        "auto": "Otomatik baslatma yapilmadi.",
        "actions": ["Satilacak base bakiyesini kontrol edin.", "Manuel transfer/satis sonrasi botu tekrar degerlendirin."],
    },
    "MIN_NOTIONAL": {
        "title": "Minimum emir tutari alti",
        "severity": "warn",
        "auto": "Parametre duzeltmesi gerekir; otomatik baslatma yapilmadi.",
        "actions": ["Grid emir tutarini en az Binance minimumuna cikarin.", "Butceyi veya ilgili grid yuzdesini artirin."],
    },
    "MIN_NOTIONAL_AFTER_CAP": {
        "title": "Cap sonrasi minimum tutar alti",
        "severity": "warn",
        "auto": "Parametre/bakiye duzeltmesi gerekir.",
        "actions": ["Bakiye sinirini ve grid paylarini kontrol edin.", "Butceyi artirin veya grid sayisini azaltin."],
    },
    "LOT_SIZE": {
        "title": "Lot/step uyumsuzlugu",
        "severity": "warn",
        "auto": "Parametre duzeltmesi gerekir.",
        "actions": ["Sembol stepSize/minQty kurallarina uygun miktar kullanin.", "Butce veya grid payini artirin."],
    },
    "GRID_NOTIONAL_TOO_LOW": {
        "title": "Grid tutari dusuk",
        "severity": "warn",
        "auto": "Bot baslatilmadi; once parametre duzeltmesi gerekir.",
        "actions": ["Parametre Asistani ile daha yuksek notional ureten set uygulayin.", "Butceyi artirin veya grid sayisini azaltin."],
    },
    "SAFE_STOP": {
        "title": "Guvenli durdurma",
        "severity": "critical",
        "auto": "Otomatik baslatma yapilmadi; once sebep netlestirilmeli.",
        "actions": ["Son motor loglarindaki SAFE_STOP nedenini okuyun.", "Kismi emir veya bakiye tutarsizligi varsa admin kontrolu gerekir."],
    },
    "DAILY_LOSS_LIMIT": {
        "title": "Gunluk zarar limiti",
        "severity": "critical",
        "auto": "Risk limiti nedeniyle otomatik baslatma yapilmadi.",
        "actions": ["Piyasa ve risk limitleri incelenmeli.", "Limit sifirlanmadan manuel onayla devam edin."],
    },
    "BOT_LOOP_TOPLEVEL_EXCEPTION": {
        "title": "Bot dongusu hata verdi",
        "severity": "warn",
        "auto": "Bot calisiyorsa izlenir; durduysa guvenli START kuyruga alinabilir.",
        "actions": ["Worker log tekrar eden exception icin kontrol edilmeli.", "Tekrarlarsa parametre ve son emir kayitlari incelenmeli."],
    },
    "BOT_LOOP_TRDCA_EXCEPTION": {
        "title": "Strateji dongusu hata verdi",
        "severity": "warn",
        "auto": "Bot calisiyorsa izlenir; durduysa guvenli START denenebilir.",
        "actions": ["Strateji logundaki satir ve son state incelenmeli.", "Tekrarlarsa parametre seti gozden gecirilmeli."],
    },
    "BOT_TICK_EXCEPTION": {
        "title": "Tick hatasi",
        "severity": "warn",
        "auto": "Cogu durumda bot calismaya devam eder; durum izlenir.",
        "actions": ["Son tick logu kontrol edilmeli.", "Arka arkaya tekrar ederse bot yeniden baslatma degerlendirilir."],
    },
    "RUN_ACTION_EXCEPTION": {
        "title": "Aksiyon calisma hatasi",
        "severity": "warn",
        "auto": "Bot durduysa guvenli baslatma degerlendirilir.",
        "actions": ["Son emir/aksiyon logu incelenmeli.", "Bakiye, min notional ve API izinleri kontrol edilmeli."],
    },
    "BOT_LOOP_AUTO_RESTART": {
        "title": "Dongu otomatik yeniden baslatiliyor",
        "severity": "critical",
        "auto": "Worker zaten bot dongusunu acmaya calisir; ek START yalniz bot durduysa kuyruga alinir.",
        "actions": ["10-60 saniye icinde yeni tick beklenir.", "Gelmezse worker sureci kontrol edilmeli."],
    },
    "LOOP_TASK_MISSING": {
        "title": "Bot dongusu bulunamadi",
        "severity": "critical",
        "auto": "Bot running ise worker kendi kurtarma mekanizmasi beklenir; worker kapaliysa admin aksiyonu gerekir.",
        "actions": ["Worker calisiyor mu kontrol edin.", "Gerekirse worker restart yapin."],
    },
    "TICK_STALE_CRIT": {
        "title": "Tick kritik gecikti",
        "severity": "critical",
        "auto": "Worker ve son tick durumu kontrol edilir.",
        "actions": ["Worker heartbeat ve bot_engine_state last_tick_at kontrol edilmeli.", "Devam ederse worker restart gerekir."],
    },
    "PRICE_STALE_OR_MISSING": {
        "title": "Fiyat verisi bayat/yok",
        "severity": "warn",
        "auto": "Emir gonderilmez; veri akisi toparlaninca bot devam eder.",
        "actions": ["Market data baglantisini kontrol edin.", "Sembolun aktif oldugunu dogrulayin."],
    },
    "REPEATED_ORDER_FAIL": {
        "title": "Tekrarlayan emir hatasi",
        "severity": "warn",
        "auto": "Parametre/bakiye kontrolu gerekir.",
        "actions": ["Son Binance hata kodunu inceleyin.", "Grid miktari, butce ve min notional ayarlarini duzeltin."],
    },
}

DEFAULT_PLAYBOOK = {
    "title": "Tanimli olmayan hata",
    "severity": "warn",
    "auto": "Otomatik riskli islem yapilmadi; tani kaydi admin sohbetine eklendi.",
    "actions": ["Son bot loglarini inceleyin.", "Hata tekrarlanirsa admin tarafinda state ve worker loglari kontrol edilmeli."],
}


def _worker_process_alive() -> bool:
    try:
        root = Path(__file__).resolve().parents[2]
        pid_path = root / ".run" / "worker.pid"
        if not pid_path.is_file():
            return False
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _clean_code(code: Any) -> str:
    s = str(code or "").strip().upper()
    s = re.sub(r"[^A-Z0-9_:-]+", "", s)
    return s[:64]


def extract_error_codes(message: str, assistant_context: Optional[Dict[str, Any]]) -> List[str]:
    codes: List[str] = []
    ctx = assistant_context if isinstance(assistant_context, dict) else {}
    for item in ctx.get("reports") or []:
        if isinstance(item, dict):
            c = _clean_code(item.get("code") or item.get("error_code"))
            if c:
                codes.append(c)
    for c in ctx.get("codes") or []:
        cc = _clean_code(c)
        if cc:
            codes.append(cc)
    for m in re.finditer(r"\[([A-Z][A-Z0-9_:-]{2,64})\]", message or ""):
        codes.append(_clean_code(m.group(1)))
    for m in re.finditer(r"\b(?:HA-[A-Z0-9_-]+|[A-Z][A-Z0-9_]{3,64})\b", message or ""):
        c = _clean_code(m.group(0))
        if c and not c.startswith("HA-") and c not in {"USDT", "BTC", "ETH", "BNB"}:
            codes.append(c)
    out: List[str] = []
    seen = set()
    for c in codes:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:8]


def _resolve_bot(
    db: Session,
    account_id: int,
    message: str,
    assistant_context: Optional[Dict[str, Any]],
) -> Optional[Bot]:
    ctx = assistant_context if isinstance(assistant_context, dict) else {}
    bot_id = None
    for v in (
        (ctx.get("ctx") or {}).get("botId") if isinstance(ctx.get("ctx"), dict) else None,
        ctx.get("bot_id"),
    ):
        try:
            if v:
                bot_id = int(str(v).strip().lstrip("#"))
                break
        except Exception:
            pass
    if bot_id is None:
        m = re.search(r"#(\d+)", message or "")
        if m:
            bot_id = int(m.group(1))
    q = db.query(Bot).filter(Bot.account_id == int(account_id))
    if bot_id is not None:
        bot = q.filter(Bot.id == bot_id).first()
        if bot:
            return bot
    symbol = ""
    for v in (
        (ctx.get("ctx") or {}).get("symbol") if isinstance(ctx.get("ctx"), dict) else None,
        ctx.get("symbol"),
    ):
        if v:
            symbol = str(v).strip().upper()
            break
    if not symbol:
        m = re.search(r"\b([A-Z0-9]{3,20}(?:USDT|USDC|FDUSD|BUSD|TRY|BTC|ETH))\b", message or "")
        if m:
            symbol = m.group(1).upper()
    if symbol:
        bot = q.filter(Bot.symbol == symbol).order_by(Bot.id.desc()).first()
        if bot:
            return bot
    return q.order_by(Bot.id.desc()).first()


def _load_state(db: Session, bot_id: int) -> Dict[str, Any]:
    try:
        from app.botengine.state_store import load_state

        return load_state(db, bot_id) or {}
    except Exception:
        return {}


def _recent_events(db: Session, bot_id: int, limit: int = 8) -> List[Dict[str, Any]]:
    try:
        from app.botengine.state_store import list_events

        return list_events(db, bot_id, limit=limit) or []
    except Exception:
        return []


def _insert_engine_command(
    db: Session,
    account_id: int,
    bot_id: int,
    command: str,
    payload: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Optional[int]:
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload or {}, ensure_ascii=False) if payload else None
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    params = {
        "created_at": now,
        "account_id": int(account_id),
        "bot_id": int(bot_id),
        "command": command,
        "payload_json": payload_json,
        "request_id": request_id,
    }
    if getattr(dialect, "name", "") == "postgresql":
        row = db.execute(
            text(
                """
                INSERT INTO bot_engine_commands (created_at, account_id, bot_id, command, payload_json, status, request_id)
                VALUES (:created_at, :account_id, :bot_id, :command, :payload_json, 'PENDING', :request_id)
                RETURNING id
                """
            ),
            params,
        ).fetchone()
        db.commit()
        return int(row[0]) if row and row[0] else None
    db.execute(
        text(
            """
            INSERT INTO bot_engine_commands (created_at, account_id, bot_id, command, payload_json, status, request_id)
            VALUES (:created_at, :account_id, :bot_id, :command, :payload_json, 'PENDING', :request_id)
            """
        ),
        params,
    )
    db.commit()
    row = db.execute(text("SELECT last_insert_rowid()")).fetchone()
    return int(row[0]) if row and row[0] else None


def _append_bot_event(db: Session, bot: Bot, code: str, action: str, tracking_code: str) -> None:
    try:
        from app.botengine.state_store import append_event

        append_event(
            db,
            int(bot.id),
            int(bot.account_id),
            "HEALTH_WARN",
            f"Hata Asistani oto cozumleyici: {action}",
            {
                "error_code": code or "AUTO_RESOLVER",
                "health_code": code or "AUTO_RESOLVER",
                "source": "bot_error_assistant_auto_resolver",
                "tracking_code": tracking_code,
                "auto_action": action,
            },
        )
    except Exception:
        pass


async def _probe_connectivity(db: Session, bot: Bot) -> Tuple[Optional[Dict[str, str]], bool]:
    try:
        from app.services.binance_connectivity import sync_bot_connectivity_on_view

        fail = await sync_bot_connectivity_on_view(
            db, bot, source="error_assistant_auto_resolver", force_probe=True
        )
        return fail, fail is None
    except Exception as exc:
        return {"error_code": "CONNECTIVITY_PROBE_FAILED", "message": str(exc)[:180]}, False


def _action_allowed(codes: Iterable[str], bot_status: str, worker_alive: bool, probe_ok: bool) -> Tuple[bool, str]:
    code_set = {c for c in codes if c}
    if not code_set:
        return False, "Hata kodu netlesmeden otomatik START guvenli kabul edilmedi."
    if code_set & BLOCKED_START_CODES:
        return False, "Hata tipi manuel duzeltme gerektiriyor."
    if not worker_alive:
        return False, "Worker calismiyor; komut calismadan once worker yeniden baslatilmali."
    if bot_status not in {"paused_error", "paused", "stopped"}:
        return False, "Bot zaten calisir durumda veya otomatik START gerektirmiyor."
    if code_set and not (code_set & RECOVERABLE_START_CODES):
        return False, "Bu hata kodu icin otomatik START guvenli kabul edilmedi."
    if not probe_ok and (code_set & {"BINANCE_UNREACHABLE", "BINANCE_RATE_LIMIT", "CONNECTIVITY_LOST", "CONNECTIVITY_PAUSED"}):
        return False, "Canli Binance kontrolu henuz basarili degil."
    return True, "Guvenli START kosullari saglandi."


def _format_playbook_lines(codes: List[str]) -> List[str]:
    lines: List[str] = []
    for code in codes[:4]:
        p = ERROR_PLAYBOOK.get(code, DEFAULT_PLAYBOOK)
        lines.append(f"- [{code}] {p['title']}. {p.get('auto') or ''}".strip())
        for action in (p.get("actions") or [])[:3]:
            lines.append(f"  • {action}")
    if not lines:
        p = DEFAULT_PLAYBOOK
        lines.append(f"- [AUTO_RESOLVER] {p['title']}: {p['auto']}")
        for action in p["actions"]:
            lines.append(f"  • {action}")
    return lines


def _tracking_code(bot: Optional[Bot], codes: List[str]) -> str:
    prefix = "HA"
    bid = f"B{bot.id}" if bot else "GEN"
    main = (codes[0] if codes else "AUTO").replace("_", "-")[:18]
    tail = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{bid}-{main}-{tail}"


def _scheduled_chat_message(thread_id: int, body: str, delay_sec: float) -> ChatMessage:
    return ChatMessage(
        thread_id=thread_id,
        sender_type="admin",
        body=body,
        created_at=datetime.utcnow() + timedelta(seconds=delay_sec),
    )


async def handle_error_assistant_chat(
    *,
    db: Session,
    thread: ChatThread,
    user_message: ChatMessage,
    account: Account,
    message_body: str,
    assistant_context: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    codes = extract_error_codes(message_body, assistant_context)
    bot = _resolve_bot(db, int(account.id), message_body, assistant_context)
    state = _load_state(db, int(bot.id)) if bot else {}
    state_code = _clean_code(state.get("last_error_code")) if state else ""
    if state_code and state_code not in codes:
        codes.insert(0, state_code)
    tracking = _tracking_code(bot, codes)
    worker_alive = _worker_process_alive()
    bot_status = (getattr(bot, "status", "") or "bilinmiyor").lower() if bot else "bulunamadi"

    ack = (
        "Tamam, bildirimi aldım. Botu ve son kayıtları kontrol ediyorum.\n"
        f"Takip: {tracking}\n"
        f"Kod: {', '.join('[' + c + ']' for c in codes) if codes else '[AUTO_RESOLVER]'}"
    )
    db.add(_scheduled_chat_message(thread.id, ack, ACK_MESSAGE_DELAY_SEC))
    db.commit()

    probe_fail: Optional[Dict[str, str]] = None
    probe_ok = False
    if bot:
        probe_fail, probe_ok = await _probe_connectivity(db, bot)
        if probe_fail:
            probe_code = _clean_code(probe_fail.get("error_code"))
            if probe_code and probe_code not in codes:
                codes.insert(0, probe_code)

    command_id: Optional[int] = None
    action_lines: List[str] = []
    allowed, reason = _action_allowed(codes, bot_status, worker_alive, probe_ok)
    if bot and allowed:
        try:
            bot.status = "running"
            if not getattr(bot, "started_at", None):
                bot.started_at = datetime.now(timezone.utc)
            if state:
                state.pop("last_error_code", None)
                state.pop("health_error_since", None)
                state.pop("backoff_until", None)
                state["_error_assistant_auto_start_at"] = datetime.now(timezone.utc).isoformat()
                state["_error_assistant_tracking_code"] = tracking
                try:
                    from app.botengine.state_store import save_state

                    save_state(db, int(bot.id), int(bot.account_id), state)
                except Exception:
                    pass
            db.commit()
            command_id = _insert_engine_command(
                db,
                int(bot.account_id),
                int(bot.id),
                "START",
                payload={
                    "source": "bot_error_assistant_auto_resolver",
                    "tracking_code": tracking,
                    "error_codes": codes,
                    "resume_reason": "Hata Asistani otomatik cozumleyici",
                },
                request_id=request_id,
            )
            action_lines.append(f"Botu güvenli gördüğüm için yeniden başlatma kuyruğuna aldım. Komut #{command_id}.")
            _append_bot_event(db, bot, codes[0] if codes else "AUTO_RESOLVER", "START_QUEUED", tracking)
        except Exception as exc:
            action_lines.append(f"Yeniden başlatmayı denedim ama tamamlanmadı: {str(exc)[:160]}")
    else:
        action_lines.append(f"Şu an botu otomatik başlatmadım: {reason}")

    recent = _recent_events(db, int(bot.id), limit=5) if bot else []
    recent_lines = []
    for ev in recent[:3]:
        ev_code = _clean_code((ev.get("meta") or {}).get("error_code") or (ev.get("meta") or {}).get("health_code"))
        label = ev_code or ev.get("type") or "EVENT"
        msg = str(ev.get("message") or "").strip()
        recent_lines.append(f"- {label}: {msg[:140]}")

    diagnosis = [
        f"Takip: {tracking}",
        f"Bot: {(bot.symbol if bot else 'bulunamadı')}{(' (#' + str(bot.id) + ')') if bot else ''}",
        f"Durum: {bot_status}",
        f"Worker: {'çalışıyor' if worker_alive else 'çalışmıyor'}",
        f"Bağlantı kontrolü: {'temiz görünüyor' if probe_ok else 'henüz temiz değil veya bu hata için şart değil'}",
    ]
    if probe_fail:
        diagnosis.append(
            "Bağlantı sonucu: "
            + _clean_code(probe_fail.get("error_code"))
            + " - "
            + str(probe_fail.get("message") or "")[:180]
        )
    if recent_lines:
        diagnosis.append("Son motor kayıtları:")
        diagnosis.extend(recent_lines)

    final_body = (
        "Kontrol ettim.\n"
        + "\n".join(diagnosis)
        + "\n\n"
        + "\n".join(action_lines)
        + "\n\nBuna göre notlarım:\n"
        + "\n".join(_format_playbook_lines(codes))
        + "\n\nBen bu kaydı takip koduyla admin ekranına aldım. Güvenli olan adımı uyguladım; riskli kısım varsa manuel kontrol bekliyor."
    )
    db.add(_scheduled_chat_message(thread.id, final_body[:2000], FINAL_MESSAGE_DELAY_SEC))
    thread.updated_at = datetime.utcnow()
    db.commit()
    if bot:
        _append_bot_event(db, bot, codes[0] if codes else "AUTO_RESOLVER", "DIAGNOSIS_WRITTEN", tracking)
    return {
        "tracking_code": tracking,
        "codes": codes,
        "bot_id": int(bot.id) if bot else None,
        "command_id": command_id,
        "worker_alive": worker_alive,
        "probe_ok": probe_ok,
    }
