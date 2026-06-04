"""
API Routes - REST Endpoints
"""
import requests
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, update, desc
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel
import time
import asyncio
import os
import logging
import httpx

TR_TZ = ZoneInfo("Europe/Istanbul")
logger = logging.getLogger(__name__)
_snapshot_wallet_refresh_tasks: Dict[int, asyncio.Task] = {}
_snapshot_wallet_refresh_last_at: Dict[int, float] = {}
_SNAPSHOT_WALLET_REFRESH_GAP_SEC = float(os.environ.get("SNAPSHOT_WALLET_REFRESH_GAP_SEC", "30"))

from app.db.session import get_db
from app.db.base import SessionLocal
from app.db.models import Account, Bot, Trade, PnlSnapshot, User, ChatThread, ErrorLog, AssetSnapshot
from app.services.encryption import (
    encrypt_account_api_key,
    encrypt_account_api_secret,
    encrypt_account_ip_whitelist,
    encrypt_text,
)
from app.api.auth import require_auth, require_account_access, get_client_ip, verify_password
from app.services import audit as audit_svc
from app.utils.account_code import generate_account_code
from app.utils.tz_utils import turkey_today_start_utc, turkey_today_date_str
# Binance kaldırıldı – sonra temiz kurulum ile eklenecek
from app.services.price_hub import price_hub
from app.services.pnl_service import PnlService
from app.bot.manager import bot_manager
from app.bot.ledger import Ledger
from app.botengine.state_store import load_state
from app.bot.models import BotConfig
from app.services.data_hub import data_hub
from app.error_logging import persist_error as error_logging_persist
from app.core.logging_helpers import log_wallet_trace

router = APIRouter()

# ---------------------------------------------------------------------------
# /api/log-error rate-limiter: IP başına dakikada max 30 istek (sliding-window)
# ---------------------------------------------------------------------------
_LOG_ERROR_RL_LOCK = __import__("threading").Lock()
_LOG_ERROR_RL: Dict[str, "collections.deque"] = {}  # type: ignore[type-arg]
_LOG_ERROR_RL_MAX = 30
_LOG_ERROR_RL_WINDOW = 60.0

import collections as _collections
import re as _re

_SENSITIVE_URL_RE = _re.compile(
    r"([?&])(token|password|passwd|secret|key|auth|reset_code|code|session)[^&]*",
    _re.IGNORECASE,
)

def _sanitize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    return _SENSITIVE_URL_RE.sub(r"\1\2=[REDACTED]", url)

def _check_log_error_rate_limit(client_ip: str) -> bool:
    """True = allowed. Sliding-window per IP."""
    now = time.time()
    with _LOG_ERROR_RL_LOCK:
        q = _LOG_ERROR_RL.get(client_ip)
        if q is None:
            q = _collections.deque()
            _LOG_ERROR_RL[client_ip] = q
        cutoff = now - _LOG_ERROR_RL_WINDOW
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= _LOG_ERROR_RL_MAX:
            return False
        q.append(now)
        # Eski IP'leri bellek sızdırmasın diye temizle (periyodik)
        if len(_LOG_ERROR_RL) > 2000:
            stale = [k for k, v in _LOG_ERROR_RL.items() if not v or v[-1] < cutoff]
            for k in stale:
                del _LOG_ERROR_RL[k]
        return True


# Frontend error reporting (no auth required; optional Bearer for user/account)
@router.post("/log-error")
async def api_log_error(
    request: Request,
    body: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
):
    """Accept frontend error reports and persist to error_logs. Optional Bearer token for user_id/account_id."""
    try:
        # Rate-limit kontrolü
        client_ip = None
        if request.client:
            client_ip = (request.client.host or "")[:50]
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = (forwarded.split(",")[0].strip() or client_ip or "")[:50]
        ip_key = client_ip or "unknown"
        if not _check_log_error_rate_limit(ip_key):
            return {"ok": False, "throttled": True}

        payload = body or {}
        # Payload boyut sınırı
        message = (payload.get("message") or "").strip()[:1000] or "(no message)"
        source = (payload.get("source") or "frontend")[:32]
        raw_detail = payload.get("detail")
        detail = (str(raw_detail)[:4000] if raw_detail is not None else None)
        raw_path = (payload.get("path") or "")[:512]
        path = _sanitize_url(raw_path)
        raw_ctx = payload.get("context")
        context: Optional[Dict[str, Any]] = None
        if isinstance(raw_ctx, dict):
            # URL alanlarındaki hassas parametreleri temizle
            context = {}
            for k, v in raw_ctx.items():
                if k == "url" and isinstance(v, str):
                    context[k] = _sanitize_url(v)
                elif isinstance(v, str):
                    context[k] = v[:512]
                else:
                    context[k] = v

        user_id = None
        account_id = None
        is_admin = False
        auth = request.headers.get("Authorization") or request.headers.get("authorization") or ""
        if auth.startswith("Bearer "):
            try:
                from app.api.auth import _session_get
                session = _session_get(auth[7:].strip())
                if session:
                    user_id = session.get("user_id")
                    account_id = session.get("account_id")
                    is_admin = bool(session.get("is_admin"))
            except Exception:
                pass
        user_agent = (request.headers.get("user-agent") or "")[:512]
        # Kimliksiz istekler ayrı seviyede loglanır (gürültü önleme)
        log_level = "error" if user_id else "warning"
        error_logging_persist(
            db,
            source,
            message,
            detail=detail,
            path=path,
            method="POST",
            user_id=user_id,
            account_id=account_id,
            user_agent=user_agent,
            client_ip=client_ip,
            context=context,
            is_admin=is_admin,
            level=log_level,
        )
        import json as _json
        _ctx_str = ""
        try:
            _ctx_str = _json.dumps(context, ensure_ascii=False, default=str)[:3500] if context else ""
        except Exception:
            _ctx_str = str(context)[:3500] if context else ""
        _detail_str = (str(detail)[:1500] if detail is not None else "")
        _req_id = (request.headers.get("X-Request-ID") or request.headers.get("X-Request-Id") or "")[:64]
        logger.warning(
            "ADMIN_PANEL_CLIENT_ERROR source=%s message=%s path=%s detail=%s context=%s "
            "user_id=%s account_id=%s is_admin=%s ip=%s request_id=%s ua=%s",
            source[:32],
            message[:500],
            path[:512],
            _detail_str,
            _ctx_str,
            user_id,
            account_id,
            is_admin,
            client_ip,
            _req_id,
            user_agent[:120] if user_agent else "",
        )
        return {"ok": True}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("log-error endpoint failed: %s", e)
        return {"ok": False}


@router.get("/error-logs")
async def api_error_logs_test_account(
    account_id: int = Query(..., description="Account ID"),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Son hata logları (sadece test hesabı). Anasayfada 'tüm sistem hataları' için."""
    from app.services.test_account import is_test_account
    # Test kullanıcısı kendi oturumundaki hesaba erişiyorsa query'deki account_id uyuşmasa bile session account_id kullan (403 önle)
    session_account_id = current.get("account_id")
    if session_account_id is not None and is_test_account(session_account_id, db):
        if session_account_id != account_id:
            account_id = session_account_id
    else:
        require_account_access(current, account_id)
    if not is_test_account(account_id, db):
        raise HTTPException(status_code=403, detail="Bu özellik sadece test hesabında kullanılabilir.")
    rows = (
        db.query(ErrorLog)
        .filter(ErrorLog.account_id == account_id)
        .order_by(desc(ErrorLog.id))
        .limit(limit)
        .all()
    )
    out = []
    for r in rows or []:
        ctx = None
        if getattr(r, "context_json", None):
            try:
                ctx = json.loads(r.context_json)
            except Exception:
                pass
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() + "Z" if getattr(r.created_at, "isoformat", None) else None,
            "source": getattr(r, "source", None),
            "level": getattr(r, "level", None),
            "message": (r.message or "")[:500],
            "detail": (r.detail or "")[:1000] if r.detail else None,
            "path": getattr(r, "path", None),
            "request_id": getattr(r, "request_id", None),
            "context": ctx,
        })
    return {"items": out}


class TestDailySpotRefBody(BaseModel):
    account_id: int
    ref_usd: float
    date: Optional[str] = None


@router.post("/binance/test-daily-spot-ref")
async def api_test_daily_spot_ref_sync(
    body: TestDailySpotRefBody,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Test hesabı: dashboard günlük spot referansını sunucuya yazar (admin tile ile aynı)."""
    from app.services.test_account import is_test_account
    from app.services.test_account_kpi import set_test_daily_spot_ref_usd

    account_id = int(body.account_id)
    session_account_id = current.get("account_id")
    if session_account_id is not None and is_test_account(session_account_id, db):
        if session_account_id != account_id:
            account_id = session_account_id
    else:
        require_account_access(current, account_id)
    if not is_test_account(account_id, db):
        raise HTTPException(status_code=403, detail="Bu özellik sadece test hesabında kullanılabilir.")
    set_test_daily_spot_ref_usd(account_id, float(body.ref_usd), body.date)
    return {"ok": True, "account_id": account_id, "ref_usd": round(float(body.ref_usd), 2)}


# POST /api/error-logs/clear -> main.py'de tanımlı (404 önlemek için doğrudan app'te)


# Account Management
@router.post("/accounts")
async def create_account(
    name: str,
    exchange: str = "BINANCE",
    mode: str = "paper",
    db: Session = Depends(get_db)
):
    """Create new account (API key/secret kaldırıldı - sonra entegre edilecek)"""
    # Generate unique account code
    account_code = generate_account_code(db)
    
    account = Account(
        account_code=account_code,
        name=name,
        exchange=exchange,
        api_key_enc=encrypt_text(""),
        api_secret_enc=encrypt_text(""),
        mode=mode
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return {
        "id": account.id,
        "account_code": account.account_code,
        "name": account.name,
        "exchange": account.exchange,
        "mode": account.mode,
        "created_at": account.created_at.isoformat() if account.created_at else None
    }


@router.get("/accounts")
async def list_accounts(db: Session = Depends(get_db)):
    """List all accounts"""
    accounts = db.query(Account).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "exchange": a.exchange,
            "mode": a.mode,
            "created_at": a.created_at.isoformat() if a.created_at else None
        }
        for a in accounts
    ]


@router.get("/accounts/by-code/{account_code}")
async def get_account_by_code(
    account_code: str,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Resolve 6-digit account code to account details. Auth required; only own account or admin."""
    account = db.query(Account).filter(Account.account_code == account_code.strip()).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account.id)
    return {
        "id": account.id,
        "account_code": account.account_code,
        "name": account.name,
        "exchange": account.exchange,
        "mode": account.mode,
        "created_at": account.created_at.isoformat() if account.created_at else None
    }


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Get account details. Auth required; only own account or admin."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    return {
        "id": account.id,
        "account_code": account.account_code,
        "name": account.name,
        "exchange": account.exchange,
        "mode": account.mode,
        "created_at": account.created_at.isoformat() if account.created_at else None
    }


def _parse_public_ip_response(text: str, is_json: bool = False) -> Optional[str]:
    """Metin veya JSON yanıtından geçerli IPv4/IPv6 adresini çıkarır."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if is_json:
        try:
            data = json.loads(s)
            ip = (data.get("ip") or "").strip()
            return ip if ip and len(ip) <= 45 else None
        except (TypeError, ValueError):
            return None
    if "\n" in s:
        s = s.split("\n")[0].strip()
    if s and len(s) <= 45 and all(c.isalnum() or c in ".:" for c in s):
        return s
    return None


async def _fetch_server_public_ip() -> Optional[str]:
    """Önbellekli sunucu dış IP (startup keşfi + periyodik yenileme)."""
    from app.services.server_public_ip import get_server_public_ip

    return await get_server_public_ip()


@router.get("/accounts/{account_id}/settings")
async def get_account_settings(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Hesap ayarları: sunucu dış IP (otomatik), hesap adı (API key/secret döndürülmez). Auth required."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    server_public_ip = await _fetch_server_public_ip()
    user_phone = None
    if account.user_id:
        u = db.query(User).filter(User.id == account.user_id).first()
        if u:
            user_phone = u.phone
    from app.services.test_account import is_test_account, account_has_binance_keys, clear_first_login_if_keys_configured
    if is_test_account(account_id, db):
        has_binance_keys = True  # Test hesabında Binance uyarısı gösterme; paper 10k USDT
    else:
        has_binance_keys = account_has_binance_keys(account)
    if has_binance_keys:
        clear_first_login_if_keys_configured(account, db)
    spot_favorites = []
    raw = getattr(account, "spot_favorites_json", None)
    if raw:
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                spot_favorites = [str(s).strip().upper() for s in arr if s and str(s).strip()]
        except (TypeError, ValueError):
            pass
    return {
        "account_id": account.id,
        "account_name": account.name,
        "current_ip": client_ip or "—",
        "server_public_ip": server_public_ip or "—",
        "is_first_login": account.is_first_login if hasattr(account, 'is_first_login') else False,
        "user_phone": user_phone or "",
        "has_binance_keys": has_binance_keys,
        "spot_favorites": spot_favorites,
        "isolate_from_admin": getattr(account, "isolate_from_admin", False),
    }


class SettingsUpdateBody(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    name: Optional[str] = None
    api_ip_whitelist: Optional[str] = None
    is_first_login: Optional[bool] = None
    isolate_from_admin: Optional[bool] = None
    password: Optional[str] = None
    new_password: Optional[str] = None


@router.patch("/accounts/{account_id}/settings")
async def update_account_settings(
    account_id: int,
    body: SettingsUpdateBody = Body(...),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """API key / API secret / hesap ismi / IP whitelist / is_first_login güncelle. Auth required."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    if body.password is not None or body.new_password is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PASSWORD_USE_AUTH_ENDPOINT",
                "message": "Şifre değişikliği PATCH /settings ile yapılamaz. POST /api/auth/change-password kullanın.",
            },
        )
    try:
        if body.api_key is not None:
            account.api_key_enc = encrypt_account_api_key(account_id, body.api_key or "")
        if body.api_secret is not None:
            account.api_secret_enc = encrypt_account_api_secret(account_id, body.api_secret or "")
    except ValueError as e:
        msg = str(e)
        if "BINANCE_MASTER_KEY" in msg or "environment" in msg.lower():
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": "ENCRYPTION_NOT_CONFIGURED",
                    "message": "Şifreleme anahtarı (BINANCE_MASTER_KEY) .env dosyasında tanımlı değil. API anahtarı kaydedilemiyor.",
                    "fix": "Proje kökünde .env dosyası oluşturun veya açın; BINANCE_MASTER_KEY= ile en az 32 karakterlik bir anahtar ekleyin. Anahtar üretmek için: python -c \"import secrets; print(secrets.token_urlsafe(24))\"  Çalıştırdıktan sonra web/manager servisini yeniden başlatın.",
                },
            )
        raise HTTPException(status_code=400, detail={"error_code": "ENCRYPTION_ERROR", "message": msg})
    if body.name is not None and body.name.strip():
        account.name = body.name.strip()
    if body.api_ip_whitelist is not None:
        raw_wl = (body.api_ip_whitelist or "").strip()
        account.api_ip_whitelist = encrypt_account_ip_whitelist(account_id, raw_wl) if raw_wl else ""
    if body.is_first_login is not None:
        account.is_first_login = body.is_first_login
    if body.isolate_from_admin is not None:
        val = bool(body.isolate_from_admin)
        db.execute(update(Account).where(Account.id == account_id).values(isolate_from_admin=val))
    from app.services.test_account import account_has_binance_keys
    keys_updated = body.api_key is not None or body.api_secret is not None
    if account_has_binance_keys(account):
        account.is_first_login = False
    try:
        db.commit()
        if body.isolate_from_admin is not None:
            db.refresh(account)
    except Exception as e:
        logger.exception("Account settings commit failed: %s", e)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"error_code": "SAVE_FAILED", "message": "Ayarlar kaydedilirken veritabanı hatası oluştu."},
        )
    if keys_updated and account_has_binance_keys(account):
        try:
            from app.services.transaction_history_file_store import clear_tx_history_bootstrap
            import asyncio
            from app.db.base import SessionLocal

            clear_tx_history_bootstrap(account_id)

            async def _bootstrap_tx_after_keys() -> None:
                db_bg = SessionLocal()
                try:
                    from app.services.transaction_history_file_store import bootstrap_tx_history_from_binance

                    await bootstrap_tx_history_from_binance(db_bg, account_id, force=True)
                finally:
                    db_bg.close()

            asyncio.create_task(_bootstrap_tx_after_keys())
        except Exception as boot_ex:
            logger.warning("tx_history bootstrap after keys account_id=%s: %s", account_id, boot_ex)
    return {"ok": True, "message": "Ayarlar güncellendi."}


class SpotFavoritesBody(BaseModel):
    symbols: List[str] = []


def _get_account_bot_total_equity_initial(db: Session, account_id: int) -> tuple:
    """Hesaptaki tüm botların anlık bakiye toplamı ve başlangıç sermayesi toplamı (dashboard summary ile aynı mantık)."""
    bots = db.query(Bot).filter(Bot.account_id == account_id).all()
    total_equity = 0.0
    total_initial = 0.0
    _today_date = turkey_today_date_str()
    for bot in bots:
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, account_id)
        cfg = {}
        try:
            cfg = json.loads(bot.config_json or "{}")
        except Exception:
            pass
        initial_usd = float(cfg.get("budget_usd") or cfg.get("bot_budget_quote") or cfg.get("initial_capital_usdt") or 0)
        current_usd = pnl_data.get("total_usd", initial_usd) if not pnl_data.get("error") else initial_usd
        sym = (bot.symbol or "").strip().upper()
        strategy_id = (cfg.get("strategy_id") or "").strip().lower()
        if sym and sym != "MULTI" and strategy_id not in ("trdca_pro", "multi_asset_rebalance"):
            try:
                state = load_state(db, bot.id) or {}
                base_b = float(state.get("base_balance") or 0)
                quote_b = float(state.get("quote_balance") or 0)
                price = float(pnl_data.get("current_price") or 0) if pnl_data else 0
                if price <= 0:
                    price = float(price_hub.get_price(bot.symbol) or 0)
                if price > 0 and (base_b != 0 or quote_b != 0):
                    current_usd = base_b * price + quote_b
            except Exception:
                pass
        total_equity += current_usd
        total_initial += initial_usd
    return (round(total_equity, 2), round(total_initial, 2))


@router.get("/accounts/{account_id}/bot-performance")
async def get_bot_performance(
    account_id: int,
    period: str = Query("all", description="daily | weekly | monthly | all"),
    refresh: int = Query(0, description="1 = cache atla, store'dan yeniden hesapla"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Bot performans: hesap geneli günlük K/Z toplamı (bot_daily_pnl); mevcut + silinen botlar."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    p = (period or "all").strip().lower()
    if p == "total":
        p = "all"
    try:
        from app.services.bot_performance_service import get_account_performance_breakdown
        return get_account_performance_breakdown(db, account_id, p, force_refresh=bool(refresh))
    except Exception as e:
        logger.exception("bot-performance error: %s", e)
        raise HTTPException(status_code=500, detail="Performans hesaplanamadı.")


@router.get("/accounts/{account_id}/transaction-history/revision")
async def get_transaction_history_revision(
    account_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """İşlem geçmişi sürümü — hafif poll (şifreli dosya açılmaz)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    try:
        from app.services.transaction_history_file_store import (
            ensure_tx_history_fresh_from_db,
            get_public_revision,
        )

        return get_public_revision(account_id)
    except Exception as e:
        logger.debug("transaction-history revision account_id=%s: %s", account_id, e)
        return {"revision": "0", "latest_time": "", "count": 0}


def _get_test_account_tx_history(
    db: Session,
    account_id: int,
    period: str = "weekly",
    type_filter: str = "all",
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Test (paper) hesabı işlem geçmişi: Trade tablosundaki simüle bot emirleri."""
    from datetime import timedelta
    from app.utils.tz_utils import turkey_today_start_utc
    from sqlalchemy import desc

    # Yatırım/çekim: test hesabında yok
    tf = (type_filter or "all").strip().lower()
    if tf in ("deposit", "withdraw", "depositwithdraw"):
        return {"items": [], "total": 0, "page": page, "per_page": per_page,
                "total_pages": 0, "is_test": True}

    # Dönem aralığı
    today_start = turkey_today_start_utc()
    end_dt = datetime.utcnow()
    period_days = {"daily": 1, "weekly": 7, "monthly": 30, "all": None}
    days = period_days.get(period, 7)
    start_dt = (today_start - timedelta(days=days - 1)) if days is not None else (end_dt - timedelta(days=365))

    q = db.query(Trade).filter(
        Trade.account_id == account_id,
        Trade.ts >= start_dt,
        Trade.ts <= end_dt,
    )
    if tf in ("buy",):
        q = q.filter(Trade.side == "BUY")
    elif tf in ("sell",):
        q = q.filter(Trade.side == "SELL")

    total = q.count()
    offset = (page - 1) * per_page
    trades = q.order_by(desc(Trade.ts)).offset(offset).limit(per_page).all()

    # Bot isimlerini çöz
    bot_ids = {t.bot_id for t in trades if t.bot_id}
    bot_map: dict = {}
    if bot_ids:
        bots = db.query(Bot).filter(Bot.id.in_(bot_ids), Bot.account_id == account_id).all()
        bot_map = {b.id: (b.symbol or "?") for b in bots}

    items = []
    for t in trades:
        qty = float(t.qty or 0)
        price = float(t.price or 0)
        fee = float(t.fee or 0)
        quote_qty = round(qty * price, 4)
        bid = t.bot_id
        ts_iso = (t.ts.isoformat() + "Z") if t.ts else None
        side_u = (t.side or "BUY").upper()
        source = ("Bot " + bot_map[bid]) if bid and bid in bot_map else ("Bot" if bid else "Kullanıcı")
        items.append({
            "id": f"paper_{t.id}",
            "trade_id": t.order_id or f"paper_{t.id}",
            "order_id": t.order_id or f"paper_{t.id}",
            "time": ts_iso,
            "type": "buy" if side_u == "BUY" else "sell",
            "side": side_u,
            "symbol": t.symbol or "—",
            # _txDisplayAmounts qty + price + quote_qty alanlarını okur
            "qty": round(qty, 8),
            "price": round(price, 8),
            "quote_qty": quote_qty,
            # finance_reports uyumluluğu için executed_qty / avg_price de taşı
            "executed_qty": round(qty, 8),
            "avg_price": round(price, 8),
            "commission": round(fee, 8),
            "commission_usdt": round(fee, 4),
            "commission_asset": t.fee_asset or "USDT",
            "fills_count": 1,
            "bot_id": bid,
            "is_bot": bid is not None,
            "source": "bot" if bid else "spot",
            "source_label": source,
            "platform": "TraderTrailing",
            "is_paper": True,
            "type_label": ("Simüle Alış" if side_u == "BUY" else "Simüle Satış"),
        })

    total_pages = max(1, -(-total // per_page)) if total > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "is_test": True,
        "revision": "0",
    }


@router.get("/accounts/{account_id}/transaction-history")
async def get_transaction_history(
    account_id: int,
    period: str = Query("weekly", description="daily | weekly | monthly | all"),
    type_filter: str = Query("all", description="all | buy | sell | deposit | withdraw"),
    source_filter: str = Query("all", description="all | spot | bot"),
    page: int = Query(1, ge=1, description="Page number"),
    sync: int = Query(0, description="1 = sync trades from Binance first"),
    revision: Optional[str] = Query(None, description="İstemci revision — eşleşirse DB sync atlanır"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """İşlem geçmişi: günlük/haftalık/aylık/genel, tür ve kaynak filtresi, sayfalama (20 işlem/sayfa)."""
    import os
    from app.core.security.endpoint_rate_limit import check_endpoint_rate_limit

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)

    uid = int(current.get("user_id") or 0)
    allowed, retry = check_endpoint_rate_limit(
        f"tx_history:u{uid}:a{account_id}",
        limit=int(os.getenv("TX_HISTORY_RATE_LIMIT", "30")),
        window_sec=float(os.getenv("TX_HISTORY_RATE_WINDOW_SEC", "60")),
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="İşlem geçmişi istek limiti aşıldı.",
            headers={"Retry-After": str(retry)},
        )
    if sync:
        allowed_sync, retry_sync = check_endpoint_rate_limit(
            f"tx_history_sync:u{uid}:a{account_id}",
            limit=int(os.getenv("TX_HISTORY_SYNC_RATE_LIMIT", "3")),
            window_sec=float(os.getenv("TX_HISTORY_SYNC_RATE_WINDOW_SEC", "300")),
        )
        if not allowed_sync:
            raise HTTPException(
                status_code=429,
                detail="Senkron istek limiti aşıldı.",
                headers={"Retry-After": str(retry_sync)},
            )

    try:
        from app.services.transaction_history_file_store import (
            bootstrap_tx_history_from_binance,
            ensure_tx_history_fresh_from_db,
            get_public_revision,
            is_tx_history_bootstrapped,
        )

        current_rev = str(get_public_revision(account_id).get("revision") or "0")
        rev_match = revision is not None and str(revision).strip() == current_rev

        if sync:
            try:
                ensure_tx_history_fresh_from_db(db, account_id, force=True)
            except Exception:
                pass
            try:
                await bootstrap_tx_history_from_binance(db, account_id, force=True)
            except Exception as e:
                logger.warning("transaction-history bootstrap failed: %s", e)
        elif not rev_match and is_tx_history_bootstrapped(account_id):
            try:
                ensure_tx_history_fresh_from_db(db, account_id)
            except Exception:
                pass
    except Exception:
        pass
    from app.services.transaction_history_service import TransactionHistoryService
    p = (period or "weekly").strip().lower()
    tf = (type_filter or "all").strip().lower()
    sf = (source_filter or "all").strip().lower()
    if p not in ("daily", "weekly", "monthly", "all"):
        p = "weekly"
    if tf in ("deposit", "withdraw", "depositwithdraw"):
        from app.services.transaction_history_file_store import (
            ledger_has_deposit_withdraw,
            query_transactions,
            upsert_deposit_withdraw,
        )

        if sync or not ledger_has_deposit_withdraw(account_id):
            from app.api.finance_reports import _fetch_deposit_withdraw, _normalize_deposit, _normalize_withdraw
            from app.utils.tz_utils import parse_binance_ms_to_utc_naive

            start_time, end_time = TransactionHistoryService.get_date_range(p)
            try:
                deposits, withdrawals = await _fetch_deposit_withdraw(account_id, start_time, end_time, None, db)
            except Exception as e:
                logger.warning("transaction-history deposit/withdraw fetch failed: %s", e)
                deposits, withdrawals = [], []
            for d in deposits:
                t = parse_binance_ms_to_utc_naive(d.get("insertTime"))
                if t is None:
                    continue
                row = _normalize_deposit(d, t)
                upsert_deposit_withdraw(
                    account_id,
                    order_id=str(row.get("order_id") or row.get("symbol") or d.get("insertTime") or ""),
                    time=t,
                    side="DEPOSIT",
                    symbol=row.get("symbol") or "",
                    qty=float(row.get("executed_qty") or 0),
                )
            for w in withdrawals:
                t = parse_binance_ms_to_utc_naive(w.get("applyTime") or w.get("completeTime"))
                if t is None:
                    continue
                row = _normalize_withdraw(w, t)
                upsert_deposit_withdraw(
                    account_id,
                    order_id=str(row.get("order_id") or row.get("symbol") or w.get("applyTime") or w.get("completeTime") or ""),
                    time=t,
                    side="WITHDRAW",
                    symbol=row.get("symbol") or "",
                    qty=float(row.get("executed_qty") or 0),
                )

        eff_tf = tf if tf != "depositwithdraw" else "depositwithdraw"
        return query_transactions(
            account_id,
            period=p,
            type_filter=eff_tf,
            source_filter=sf,
            page=page,
            per_page=TransactionHistoryService.PER_PAGE,
        )
    # Test (paper) hesabı: Binance trade yok, Trade tablosundan paper bot işlemlerini döndür
    from app.services.test_account import is_test_account
    if is_test_account(account_id, db):
        return _get_test_account_tx_history(db, account_id, period=p, type_filter=tf, page=page)

    return TransactionHistoryService.get_transactions(db, account_id, period=p, type_filter=tf, source_filter=sf, page=page)


@router.get("/accounts/{account_id}/spot-favorites")
async def get_spot_favorites(
    account_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Hesap için spot favori semboller (tek kaynak: sunucu). Önbellek yok."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    raw = getattr(account, "spot_favorites_json", None) or ""
    arr = []
    try:
        parsed = json.loads(raw) if raw else []
        if isinstance(parsed, list):
            arr = [str(s).strip().upper() for s in parsed if s and str(s).strip()]
    except (TypeError, ValueError):
        pass
    return JSONResponse(
        content={"symbols": arr},
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@router.put("/accounts/{account_id}/spot-favorites")
async def put_spot_favorites(
    account_id: int,
    body: SpotFavoritesBody = Body(...),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Hesap spot favorilerini güncelle (tek kaynak: sunucu)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    symbols = [str(s).strip().upper() for s in (body.symbols or []) if s and str(s).strip()]
    if not hasattr(account, "spot_favorites_json"):
        raise HTTPException(status_code=500, detail="spot_favorites column not available; run scripts/migrations/migrate_spot_favorites.py")
    account.spot_favorites_json = json.dumps(symbols)
    try:
        db.commit()
        db.refresh(account)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Kaydedilemedi.")
    return {"ok": True, "symbols": symbols}


class ChatReopenBody(BaseModel):
    account_id: int


@router.post("/chat/reopen")
async def chat_reopen(body: ChatReopenBody = Body(...), db: Session = Depends(get_db)):
    """Reopen chat thread after admin ended it. User 'Yeni sohbet başlat'."""
    account = db.query(Account).filter(Account.id == body.account_id).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    thread = db.query(ChatThread).filter(ChatThread.user_id == user.id).first()
    if not thread:
        return {"success": True, "message": "Sohbet hazır"}
    thread.ended_at = None
    thread.locked_at = None
    thread.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Sohbet yeniden açıldı"}


class DeleteAccountRequest(BaseModel):
    """Şifre ile hesap silme – mevcut şifre zorunlu."""
    password: str


@router.post("/accounts/{account_id}/delete")
async def delete_account_with_password(
    account_id: int,
    body: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Hesabı sil. Mevcut şifre zorunlu. Bot varsa reddeder. Log/işlem geçmişi silinmez; silinen hesap aynı tel ile yeniden açılınca sıfırdan yeni hesap oluşturulur."""
    from app.db.models import User

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_access(current, account_id)
    if not account.user_id:
        raise HTTPException(status_code=400, detail="Bu hesap kullanıcıya bağlı değil.")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Kullanıcı bulunamadı.")
    if not verify_password((body.password or "").strip(), getattr(user, "password_hash", None)):
        raise HTTPException(status_code=400, detail="Şifre hatalı.")
    bots = db.query(Bot).filter(Bot.account_id == account_id).all()
    if bots:
        raise HTTPException(
            status_code=400,
            detail=f"Hesapta {len(bots)} bot var. Önce botları silin."
        )
    try:
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        user.account_id = None
        db.query(Trade).filter(Trade.account_id == account_id).delete()
        db.query(PnlSnapshot).filter(PnlSnapshot.account_id == account_id).delete()
        try:
            from app.db.models import FinancialPortfolio
            fp = db.query(FinancialPortfolio).filter(FinancialPortfolio.account_id == account_id).first()
            if fp:
                db.delete(fp)
        except Exception:
            pass
        db.delete(account)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Hesap silinemedi: {e}")
    return {"ok": True, "message": "Hesap silindi."}


# Price Updates
@router.get("/prices")
async def get_prices(
    symbols: str = Query(..., description="Comma-separated list of symbols (e.g., BTCUSDT,ETHUSDT)")
):
    """Get prices for multiple symbols - optimized for real-time updates"""
    try:
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return {}
        
        # Get prices from price_hub cache first
        result = {}
        symbols_to_fetch = []
        
        for symbol in symbol_list:
            cached_price = price_hub.get_price(symbol)
            if cached_price is not None:
                result[symbol] = cached_price
            else:
                symbols_to_fetch.append(symbol)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching prices: {str(e)}")


@router.get("/binance/prices")
async def get_binance_prices(
    symbols: str = Query(...),
    account_id: int = Query(None)
):
    """Binance kaldırıldı – boş fiyat"""
    return {}


# Login sayfasi kripto fiyatlari – CORS olmadan backend uzerinden (Binance tarayicidan CORS vermiyor)
LOGIN_CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LTC", "XRP"]


@router.get("/login-crypto")
async def get_login_crypto():
    """Login sayfasindaki kripto listesi — DataHub cache (Binance REST bypass)."""
    try:
        from app.services.data_hub import data_hub
        data = {}
        for sym in LOGIN_CRYPTO_SYMBOLS:
            pair = sym + "USDT"
            meta = data_hub.get_price_with_meta(pair)
            if not meta:
                continue
            data[sym] = {
                "price": str(meta.get("price") or "0"),
                "priceChangePercent": float(meta.get("change24h") or 0),
            }
        if data:
            return data
    except Exception:
        pass
    return _login_crypto_fallback()


def _login_crypto_fallback():
    """Binance ulasilamazsa bos/placeholder."""
    return {s: {"price": "0", "priceChangePercent": 0} for s in LOGIN_CRYPTO_SYMBOLS}


# Gram altin: 1 ons = 31.1034768 gram
_OZ_TO_GRAM = 31.1034768


@router.get("/login-forex")
async def get_login_forex():
    """Login sayfasindaki döviz/altin (USD/EUR/gram altin TRY). Paralel istek ile SLOW_REQUEST azaltilir."""
    usd_try = None
    eur_try = None
    gold_gram_try = None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"}
            r_usd, r_eur, r_gold = await asyncio.gather(
                client.get("https://api.exchangerate-api.com/v4/latest/USD"),
                client.get("https://api.exchangerate-api.com/v4/latest/EUR"),
                client.get("https://data-asg.goldprice.org/dbXRates/USD", headers=headers),
            )
            if r_usd.status_code == 200:
                data = r_usd.json()
                if isinstance(data.get("rates"), dict):
                    usd_try = data["rates"].get("TRY")
            if r_eur.status_code == 200:
                data = r_eur.json()
                if isinstance(data.get("rates"), dict):
                    eur_try = data["rates"].get("TRY")

            xau_usd = None
            if r_gold.status_code == 200:
                gold = r_gold.json()
                if isinstance(gold.get("xauPrice"), (int, float)):
                    xau_usd = float(gold["xauPrice"])
                elif isinstance(gold.get("items"), list) and gold["items"] and isinstance(gold["items"][0].get("xauPrice"), (int, float)):
                    xau_usd = float(gold["items"][0]["xauPrice"])
            if xau_usd is None:
                try:
                    from app.services.data_hub import data_hub
                    p = data_hub.get_price("PAXGUSDT")
                    if p is not None:
                        xau_usd = float(p)
                except (TypeError, ValueError):
                    pass

            if xau_usd is not None and usd_try is not None:
                gold_gram_try = (xau_usd / _OZ_TO_GRAM) * float(usd_try)
    except Exception:
        pass
    return {"usd_try": usd_try, "eur_try": eur_try, "gold_gram_try": gold_gram_try}


@router.get("/binance/ticker/24hr")
async def get_binance_24h_ticker(
    symbol: str = Query(...),
    account_id: int = Query(None),
    db: Session = Depends(get_db)
):
    """Binance kaldırıldı – minimal ticker"""
    return {"symbol": symbol, "price": 0.0, "volume": 0.0, "quoteVolume": 0.0, "priceChangePercent": 0.0, "volumePercent": 0.0}


@router.get("/binance/exchange_info")
async def get_binance_exchange_info(
    symbol: str = Query(...),
    account_id: int = Query(None),
    db: Session = Depends(get_db)
):
    """Binance kaldırıldı – default exchange info"""
    s = symbol.strip().upper()
    base = s.replace("USDT", "").replace("BTC", "").replace("ETH", "") or "BTC"
    return {"symbol": s, "status": "TRADING", "baseAsset": base, "quoteAsset": "USDT", "filters": []}


@router.get("/binance/symbols/search")
async def search_binance_symbols(q: str = Query(""), account_id: int = Query(None), db: Session = Depends(get_db)):
    """Binance kaldırıldı – boş arama"""
    return {"query": q or "", "symbols": []}


@router.get("/pricing/summary")
async def api_pricing_summary():
    """Üst ticker şeridi: canlı FX, metals, crypto. Cache TTL + in-flight dedupe."""
    from fastapi.responses import JSONResponse
    from app.services.pricing_summary import get_summary
    data = await get_summary()
    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Bot Management
@router.get("/bots")
async def list_bots(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """List bots for account. Auth required."""
    require_account_access(current, account_id)
    bots = db.query(Bot).filter(Bot.account_id == account_id).all()
    return [
        {
            "id": b.id,
            "account_id": b.account_id,
            "symbol": b.symbol,
            "mode": b.mode,
            "status": b.status,
            "started_at": b.started_at.isoformat() if b.started_at else None
        }
        for b in bots
    ]


@router.get("/bots/{bot_id}/status")
async def get_bot_status(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Get bot status. Auth required."""
    require_account_access(current, account_id)
    engine = bot_manager.get_bot(bot_id, account_id)
    if not engine:
        # Try to load from DB
        engine = bot_manager.load_bot_from_db(db, bot_id, account_id)
    
    if not engine:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    return engine.get_status()


@router.get("/bots/{bot_id}/slots")
async def get_bot_slots(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Get bot grid slots. Auth required."""
    require_account_access(current, account_id)
    engine = bot_manager.get_bot(bot_id, account_id)
    if not engine:
        engine = bot_manager.load_bot_from_db(db, bot_id, account_id)
    
    if not engine:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    slots = engine.get_slots()
    return [s.to_dict() for s in slots]


@router.get("/bots/{bot_id}/trades")
async def get_bot_trades(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Get bot trades. Auth required."""
    require_account_access(current, account_id)
    return Ledger.get_trades_dict(db, bot_id, account_id, limit)


@router.get("/bots/{bot_id}/pnl")
async def get_bot_pnl(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Get bot PnL. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    pnl_data = PnlService.calculate_bot_pnl(db, bot_id, account_id)
    return pnl_data


@router.post("/bots")
async def create_bot(
    account_id: int,
    symbol: str,
    config_json: str = "{}",
    mode: str = "paper",
    db: Session = Depends(get_db)
):
    """Create new bot"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    bot = Bot(
        account_id=account_id,
        symbol=symbol,
        mode=mode,
        config_json=config_json,
        status="stopped"
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    
    return {
        "id": bot.id,
        "account_id": bot.account_id,
        "symbol": bot.symbol,
        "mode": bot.mode,
        "status": bot.status
    }


@router.post("/bots/create")
async def create_bot_with_config(
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Create new bot with full trailing grid config - accepts JSON body. Auth required."""
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    
    account_id = body.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")
    require_account_access(current, int(account_id))
    
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Get config_json from body
    config_json = body.get("config_json", "{}")
    if isinstance(config_json, dict):
        config_json = json.dumps(config_json)
    
    # Parse and validate config
    try:
        config_data = json.loads(config_json)
        strategy_id = (config_data.get("strategy_id") or "").strip().lower()
        # Botlar her zaman canlı modda oluşturulur — test hesabında paper zorunlu
        mode = "live"
        from app.db.models import User
        from app.services.test_account import is_test_account_username, TEST_PAPER_BALANCE_USDT
        test_user = db.query(User).filter(User.account_id == account_id).first()
        if test_user and is_test_account_username(getattr(test_user, "username", None)):
            mode = "paper"
            config_data["paper_mode"] = True
            config_data["mode"] = "paper"
            budget = float(config_data.get("budget_usd") or config_data.get("initial_capital_usdt") or config_data.get("budget_usdt") or 0)
            if budget <= 0 or budget > TEST_PAPER_BALANCE_USDT:
                config_data["budget_usd"] = TEST_PAPER_BALANCE_USDT
                config_data["initial_capital_usdt"] = TEST_PAPER_BALANCE_USDT
                if "budget_usdt" in config_data:
                    config_data["budget_usdt"] = TEST_PAPER_BALANCE_USDT
            config_json = json.dumps(config_data, ensure_ascii=False)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid config_json")
    
    symbol = (config_data.get("symbol") or "").upper().strip()
    if strategy_id == "trdca_pro":
        raise HTTPException(status_code=400, detail="TRDCA Pro+ strategy is no longer available. Use Trailing DCA Bot.")
    elif strategy_id == "multi_asset_rebalance":
        # Multi-asset rebalance: symbol = MULTI, validate assets
        from app.botengine.models import config_multi_asset_from_payload
        try:
            multi_cfg = config_multi_asset_from_payload(config_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid multi_asset config: {e}")
        if len(multi_cfg.assets) < 2:
            raise HTTPException(status_code=400, detail="At least 2 assets required")
        if len(multi_cfg.assets) > 10:
            raise HTTPException(status_code=400, detail="At most 10 assets allowed")
        total_pct = sum(a.get("target_pct", 0) for a in multi_cfg.assets)
        if abs(total_pct - 100.0) > 0.01:
            raise HTTPException(status_code=400, detail="Target percentages must sum to 100")
        symbols_seen = set()
        for a in multi_cfg.assets:
            s = (a.get("symbol") or "").upper()
            if s in symbols_seen:
                raise HTTPException(status_code=400, detail=f"Duplicate symbol: {s}")
            symbols_seen.add(s)
        symbol = "MULTI"
        config_json = json.dumps(multi_cfg.to_dict(), ensure_ascii=False)
    else:
        if not symbol:
            symbol = (config_data.get("symbol") or "").upper().strip() or "BTCUSDT"
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required in config_json")
        from app.botengine.models import config_from_ui_payload
        cfg = config_from_ui_payload(config_data)
        from app.botengine.config_validate import validate_dca_grid_notionals
        ok_grid, grid_err, _, _ = validate_dca_grid_notionals(cfg)
        if not ok_grid:
            raise HTTPException(status_code=400, detail=grid_err)
        stored = cfg.to_dict()
        stored["strategy_id"] = "dca_grid_trailing"
        config_json = json.dumps(stored, ensure_ascii=False)
        config_data = stored
    
    bot = Bot(
        account_id=account_id,
        symbol=symbol,
        mode=mode,
        config_json=config_json,
        status="stopped"
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    
    # İşlem geçmişi: bot oluşturma (admin hesapta işlem yaptıysa "Admin" görünsün)
    config_summary = {k: v for k, v in config_data.items() if k not in ("api_key", "api_secret", "password", "token")}
    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_CREATE", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=account.user_id, target_account_id=account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={
            "bot_id": bot.id, "account_id": account_id, "symbol": symbol, "mode": mode,
            "config_summary": config_summary,
            "user_agent": (request.headers.get("user-agent") or "")[:200],
        },
    )
    
    return {
        "bot_id": bot.id,
        "id": bot.id,
        "account_id": bot.account_id,
        "symbol": bot.symbol,
        "mode": bot.mode,
        "status": bot.status
    }


@router.delete("/bots/{bot_id}")
async def delete_bot(
    request: Request,
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Delete a bot. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    symbol_saved = getattr(bot, "symbol", None) or ""
    acc = db.query(Account).filter(Account.id == account_id).first()
    
    # İşlem geçmişi: bot silme (admin hesapta işlem yaptıysa "Admin" görünsün)
    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_DELETE", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=acc.user_id if acc else None, target_account_id=account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"bot_id": bot_id, "account_id": account_id, "symbol": symbol_saved, "user_agent": (request.headers.get("user-agent") or "")[:200]},
    )
    
    # Stop bot if running
    try:
        if bot.status == "running":
            bot.status = "stopped"
            db.commit()
            invalidate_dashboard_summary_cache(account_id)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error stopping bot before delete: {e}")
        db.rollback()
    
    try:
        from app.services.bot_performance_service import archive_bot_performance
        archive_bot_performance(db, bot_id, account_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("delete_bot archive bot_id=%s: %s", bot_id, e)
    
    # Delete related trades (cascade should handle this, but be explicit)
    try:
        db.query(Trade).filter(Trade.bot_id == bot_id, Trade.account_id == account_id).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error deleting trades: {e}")
        db.rollback()
    
    # Delete related PnL snapshots
    try:
        db.query(PnlSnapshot).filter(PnlSnapshot.bot_id == bot_id, PnlSnapshot.account_id == account_id).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error deleting PnL snapshots: {e}")
        db.rollback()
    
    # Delete bot (use raw SQL to avoid relationship loading issues)
    try:
        # First, delete related records manually to avoid cascade issues with missing tables
        try:
            db.execute(text("DELETE FROM trades WHERE bot_id = :bot_id AND account_id = :account_id"), 
                       {"bot_id": bot_id, "account_id": account_id})
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error deleting trades: {e}")
        
        try:
            db.execute(text("DELETE FROM pnl_snapshots WHERE bot_id = :bot_id AND account_id = :account_id"), 
                       {"bot_id": bot_id, "account_id": account_id})
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error deleting pnl_snapshots: {e}")
        
        # Delete bot using raw SQL to avoid relationship loading
        db.execute(text("DELETE FROM bots WHERE id = :bot_id AND account_id = :account_id"), 
                   {"bot_id": bot_id, "account_id": account_id})
        db.commit()
        invalidate_dashboard_summary_cache(account_id)
        return {"message": "Bot deleted successfully"}
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"Error deleting bot: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting bot: {str(e)}")


@router.post("/bots/{bot_id}/start")
async def start_bot(
    request: Request,
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Start a bot. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    if bot.status == "running":
        return {"message": "Bot is already running", "status": bot.status}
    
    try:
        from app.botengine.state_store import ensure_state_row, load_state, save_state
        from app.services.perf_chart_state import seed_perf_chart_state_on_bot_start
        from app.api.bots_engine import _insert_engine_command
        from app.botengine.bot_session import mark_bot_run_started, touch_bot_started_at
        ensure_state_row(db, bot.id, account_id, (bot.symbol or "").upper() or "BTCUSDT")

        bot.status = "running"
        touch_bot_started_at(bot, connectivity_resume=False)
        db.commit()
        invalidate_dashboard_summary_cache(account_id)
        seed_perf_chart_state_on_bot_start(db, bot.id)
        cmd_id = _insert_engine_command(db, account_id, bot.id, "START", request_id=getattr(request.state, "request_id", None))
        st = load_state(db, bot.id) or {}
        mark_bot_run_started(st, connectivity_resume=False)
        save_state(db, bot.id, account_id, st)
        account = db.query(Account).filter(Account.id == account_id).first()
        audit_svc.log_event(
            db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_START", severity="INFO",
            actor_user_id=current.get("user_id"), target_user_id=account.user_id if account else None, target_account_id=account_id,
            ip=get_client_ip(request), device_id=current.get("device_id"),
            request_id=getattr(request.state, "request_id", None),
            meta={"bot_id": bot.id, "account_id": account_id, "symbol": getattr(bot, "symbol", "") or ""},
        )
        return {"message": "Bot started successfully", "status": "running", "command_id": cmd_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error starting bot: {str(e)}")


@router.post("/bots/{bot_id}/stop")
async def stop_bot(
    request: Request,
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Stop a bot. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    if bot.status not in ("running", "paused"):
        return {"message": "Bot is not running or paused", "status": bot.status}

    try:
        from app.api.bots_engine import _insert_engine_command
        bot.status = "stopped"
        db.commit()
        invalidate_dashboard_summary_cache(account_id)
        _insert_engine_command(db, account_id, bot.id, "STOP", request_id=getattr(request.state, "request_id", None))
        account = db.query(Account).filter(Account.id == account_id).first()
        audit_svc.log_event(
            db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_STOP", severity="INFO",
            actor_user_id=current.get("user_id"), target_user_id=account.user_id if account else None, target_account_id=account_id,
            ip=get_client_ip(request), device_id=current.get("device_id"),
            request_id=getattr(request.state, "request_id", None),
            meta={"bot_id": bot.id, "account_id": account_id, "symbol": getattr(bot, "symbol", "") or ""},
        )
        return {"message": "Bot stopped successfully", "status": "stopped"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")


@router.post("/bots/{bot_id}/pause")
async def pause_bot(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Pause a running bot. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.status != "running":
        return {"message": "Bot is not running", "status": bot.status}
    try:
        bot.status = "paused"
        db.commit()
        return {"message": "Bot paused", "status": "paused"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bots/{bot_id}/resume")
async def resume_bot(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Resume a paused bot. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.status not in ("paused", "paused_error"):
        return {"message": "Bot is not paused", "status": bot.status}
    try:
        from app.botengine.state_store import load_state, save_state
        from app.api.bots_engine import _insert_engine_command

        state = load_state(db, bot.id) or {}
        state.pop("last_error_code", None)
        state.pop("health_error_since", None)
        state.pop("backoff_until", None)
        save_state(db, bot.id, account_id, state)
        bot.status = "running"
        db.commit()
        cmd_id = _insert_engine_command(db, account_id, bot.id, "START")
        return {"message": "Bot resumed", "status": "running", "command_id": cmd_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# In-memory cache for /api/price (symbol -> (price, ts)), TTL 2s, max keys for RAM
_price_cache: Dict[str, tuple] = {}
_PRICE_CACHE_MAX_KEYS = 200

def _price_cache_evict():
    if len(_price_cache) <= _PRICE_CACHE_MAX_KEYS:
        return
    by_ts = sorted(_price_cache.items(), key=lambda x: x[1][1])
    for k, _ in by_ts[: len(_price_cache) - _PRICE_CACHE_MAX_KEYS]:
        _price_cache.pop(k, None)

@router.get("/price")
async def api_price(symbol: str = Query(..., description="Symbol (e.g., BTCUSDT)")) -> Dict:
    """Binance kaldırıldı – sadece cache veya 0"""
    sym = symbol.strip().upper().replace("/", "").replace(" ", "")
    if not sym:
        return {"symbol": symbol, "price": 0.0}
    if sym.endswith("USD") and sym != "USDT" and "USDT" not in sym:
        sym = sym.replace("USD", "USDT")
    now = time.time()
    if sym in _price_cache:
        p, ts = _price_cache[sym]
        if now - ts < 2.0 and p is not None:
            return {"symbol": symbol, "price": float(p)}
    if sym in _price_cache:
        p, _ = _price_cache[sym]
        if p is not None:
            return {"symbol": symbol, "price": float(p)}
    _price_cache_evict()
    return {"symbol": symbol, "price": 0.0}


@router.get("/dashboard/bot_detail")
async def dashboard_bot_detail(
    bot_id: int = Query(..., description="Bot ID"),
    account_id: int = Query(..., description="Account ID"),
    after_id: int = Query(0, description="Get events after this ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Get full bot detail with grids, profit triggers, events, trades. Auth required."""
    require_account_access(current, account_id)
    import json as _json
    try:
        bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        config = {}
        try:
            config = _json.loads(bot.config_json or "{}")
        except Exception:
            pass
        alloc = config.get("allocation", {})
        base_pct = alloc.get("base_pct", 50)
        quote_pct = alloc.get("quote_pct", 50)
        budget_usd = float(config.get("budget_usd") or config.get("bot_budget_quote") or 0)
        up_cfg = config.get("up", {})
        down_cfg = config.get("down", {})
        profit_cfg = config.get("profit", {})
        up_grids = up_cfg.get("grids", [])
        down_grids = down_cfg.get("grids", [])
        pnl_data = PnlService.calculate_bot_pnl(db, bot_id, account_id)
        if pnl_data.get("error"):
            pnl_data = {"total_usd": 0.0, "realized": 0.0, "unrealized": 0.0, "daily": 0.0, "monthly": 0.0, "current_price": 0.0}
        trades = Ledger.get_trades_dict(db, bot_id, account_id, 50)
        ref_price = pnl_data.get("current_price") or 0.0
        
        # Calculate profit mechanism states from trades (trades is list of dicts from Ledger.get_trades_dict)
        sell_trades = [t for t in trades if isinstance(t, dict) and t.get("side") == "SELL"]
        buy_trades = [t for t in trades if isinstance(t, dict) and t.get("side") == "BUY"]
        sell_avg_price = None
        buy_avg_price = None
        if sell_trades:
            sell_avg_price = sum(t.get("price", 0) * t.get("qty", 0) for t in sell_trades) / sum(t.get("qty", 0) for t in sell_trades) if sum(t.get("qty", 0) for t in sell_trades) > 0 else None
        if buy_trades:
            buy_avg_price = sum(t.get("price", 0) * t.get("qty", 0) for t in buy_trades) / sum(t.get("qty", 0) for t in buy_trades) if sum(t.get("qty", 0) for t in buy_trades) > 0 else None
        
        # Determine profit mechanism states
        profit_mode = "NONE"
        profit_armed = False
        profit_extreme = None
        profit_threshold = None
        rebuy_state = "IDLE"
        rebuy_extreme = None
        rebuy_threshold = None
        resell_state = "IDLE"
        resell_extreme = None
        resell_threshold = None
        
        if sell_avg_price and buy_avg_price and ref_price:
            # Check rebuy (buy after sell at lower price)
            if "rebuy_trigger_pct" in profit_cfg:
                trigger_pct = profit_cfg.get("rebuy_trigger_pct", 0.8)
                trigger_price = sell_avg_price * (1 - trigger_pct / 100)
                if ref_price <= trigger_price:
                    rebuy_state = "ARMED"
                    rebuy_extreme = ref_price
                    trail_pct = profit_cfg.get("rebuy_trail_pct", 0.35)
                    rebuy_threshold = rebuy_extreme * (1 + trail_pct / 100)
                    profit_mode = "REBUY"
                    profit_armed = True
                    profit_extreme = rebuy_extreme
                    profit_threshold = rebuy_threshold
            
            # Check resell (sell after buy at higher price)
            if "resell_trigger_pct" in profit_cfg:
                trigger_pct = profit_cfg.get("resell_trigger_pct", 0.8)
                trigger_price = buy_avg_price * (1 + trigger_pct / 100)
                if ref_price >= trigger_price:
                    resell_state = "ARMED"
                    resell_extreme = ref_price
                    trail_pct = profit_cfg.get("resell_trail_pct", 0.35)
                    resell_threshold = resell_extreme * (1 - trail_pct / 100)
                    profit_mode = "RESELL"
                    profit_armed = True
                    profit_extreme = resell_extreme
                    profit_threshold = resell_threshold
        base_asset = (bot.symbol or "BTCUSDT").replace("USDT", "").replace("BUSD", "").replace("FDUSD", "")
        quote_asset = "USDT"
        if "BUSD" in bot.symbol:
            quote_asset = "BUSD"
        elif "FDUSD" in bot.symbol:
            quote_asset = "FDUSD"
        # Get trades to determine grid states and tracked extremes
        all_trades = db.query(Trade).filter(
            Trade.bot_id == bot_id,
            Trade.account_id == account_id
        ).order_by(Trade.ts.asc()).all()
        
        # Calculate grid states from trades
        up_list = []
        for i, g in enumerate(up_grids):
            trigger_pct = g.get("trigger_pct", 0)
            qty_pct = g.get("qty_pct", 0)
            trigger_price = ref_price * (1 + trigger_pct / 100) if ref_price else 0
            
            # Find trades for this grid slot
            grid_trades = [t for t in all_trades if t.slot_id == i and t.side == "SELL"]
            state = "IDLE"
            executed_price = None
            extreme_price = None  # Peak price after trigger
            threshold_price = None
            armed_at_price = None
            
            if grid_trades:
                # Grid was executed
                state = "EXECUTED"
                executed_price = grid_trades[-1].price
                # Find peak after first trigger
                if len(grid_trades) > 0:
                    first_trigger_price = grid_trades[0].price
                    armed_at_price = first_trigger_price
                    # Find highest price after trigger
                    extreme_price = max(t.price for t in grid_trades)
                    # Calculate threshold (extreme * (1 - trail_pct))
                    trail_pct = up_cfg.get("trail_pct", 0)
                    if extreme_price and trail_pct:
                        threshold_price = extreme_price * (1 - trail_pct / 100)
            elif ref_price and trigger_price and ref_price >= trigger_price:
                # Price reached trigger but not executed yet
                state = "ARMED"
                armed_at_price = ref_price
                extreme_price = ref_price
                trail_pct = up_cfg.get("trail_pct", 0)
                if trail_pct:
                    threshold_price = extreme_price * (1 - trail_pct / 100)
            
            up_list.append({
                "idx": i,
                "trigger_pct": trigger_pct,
                "qty_pct": qty_pct,
                "trigger_price": round(trigger_price, 2),
                "state": state,
                "armed_at_price": round(armed_at_price, 2) if armed_at_price else None,
                "executed_price": round(executed_price, 2) if executed_price else None,
                "extreme_price": round(extreme_price, 2) if extreme_price else None,
                "threshold_price": round(threshold_price, 2) if threshold_price else None
            })
        
        down_list = []
        for i, g in enumerate(down_grids):
            trigger_pct = g.get("trigger_pct", 0)
            qty_pct = g.get("qty_pct", 0)
            trigger_price = ref_price * (1 - trigger_pct / 100) if ref_price else 0
            
            # Find trades for this grid slot
            grid_trades = [t for t in all_trades if t.slot_id == i and t.side == "BUY"]
            state = "IDLE"
            executed_price = None
            extreme_price = None  # Dip price after trigger
            threshold_price = None
            armed_at_price = None
            
            if grid_trades:
                # Grid was executed
                state = "EXECUTED"
                executed_price = grid_trades[-1].price
                # Find dip after first trigger
                if len(grid_trades) > 0:
                    first_trigger_price = grid_trades[0].price
                    armed_at_price = first_trigger_price
                    # Find lowest price after trigger
                    extreme_price = min(t.price for t in grid_trades)
                    # Calculate threshold (extreme * (1 + trail_pct))
                    trail_pct = down_cfg.get("trail_pct", 0)
                    if extreme_price and trail_pct:
                        threshold_price = extreme_price * (1 + trail_pct / 100)
            elif ref_price and trigger_price and ref_price <= trigger_price:
                # Price reached trigger but not executed yet
                state = "ARMED"
                armed_at_price = ref_price
                extreme_price = ref_price
                trail_pct = down_cfg.get("trail_pct", 0)
                if trail_pct:
                    threshold_price = extreme_price * (1 + trail_pct / 100)
            
            down_list.append({
                "idx": i,
                "trigger_pct": trigger_pct,
                "qty_pct": qty_pct,
                "trigger_price": round(trigger_price, 2),
                "state": state,
                "armed_at_price": round(armed_at_price, 2) if armed_at_price else None,
                "executed_price": round(executed_price, 2) if executed_price else None,
                "extreme_price": round(extreme_price, 2) if extreme_price else None,
                "threshold_price": round(threshold_price, 2) if threshold_price else None
            })
        return {
            "bot": {
                "id": bot.id,
                "account_id": bot.account_id,
                "symbol": bot.symbol,
                "mode": (bot.mode or "paper").upper(),
                "status": (bot.status or "stopped").upper(),
                "cycle_no": 0,
                "budget_initial_usd": round(budget_usd, 2),
                "equity_usd": round(pnl_data.get("total_usd", 0), 2),
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "base_free": 0.0,
                "quote_free": 0.0,
                "ref_price": round(ref_price, 2),
                "start_ts": bot.started_at.isoformat() if bot.started_at else None,
                "updated_ts": None
            },
            "strategy": {
                "base_alloc_pct": base_pct,
                "quote_alloc_pct": quote_pct,
                "up_grid_count": len(up_grids),
                "down_grid_count": len(down_grids),
                "up_trail_pct": up_cfg.get("trail_pct"),
                "down_trail_pct": down_cfg.get("trail_pct"),
                "profit_rebuy": {
                    "enabled": "rebuy_trigger_pct" in profit_cfg,
                    "trigger_pct": profit_cfg.get("rebuy_trigger_pct", 0.8),
                    "trailing_pct": profit_cfg.get("rebuy_trail_pct", 0.35),
                    "qty_mode": "use_sold_quote_proceeds",
                    "qty_pct": 100
                },
                "profit_resell": {
                    "enabled": "resell_trigger_pct" in profit_cfg,
                    "trigger_pct": profit_cfg.get("resell_trigger_pct", 0.8),
                    "trailing_pct": profit_cfg.get("resell_trail_pct", 0.35),
                    "qty_mode": "use_bought_base_qty",
                    "qty_pct": 100
                }
            },
            "engine_state": {
                "last_price": round(pnl_data.get("current_price", 0) or 0, 2),
                "active_mode": "NORMAL",
                "active_grid_side": None,
                "active_grid_index": None,
                "tracked_extreme": None,
                "tracked_threshold": None,
                "distance_pct": None
            },
            "grids": {"up": up_list, "down": down_list},
            "profit": {
                "sell_avg_price": round(sell_avg_price, 2) if sell_avg_price else None,
                "buy_avg_price": round(buy_avg_price, 2) if buy_avg_price else None,
                "profit_mode": profit_mode,
                "profit_armed": profit_armed,
                "profit_extreme": round(profit_extreme, 2) if profit_extreme else None,
                "profit_threshold": round(profit_threshold, 2) if profit_threshold else None,
                "rebuy": {
                    "enabled": "rebuy_trigger_pct" in profit_cfg,
                    "state": rebuy_state,
                    "trigger_pct": profit_cfg.get("rebuy_trigger_pct", 0.8),
                    "trailing_pct": profit_cfg.get("rebuy_trail_pct", 0.35),
                    "extreme_price": round(rebuy_extreme, 2) if rebuy_extreme else None,
                    "threshold_price": round(rebuy_threshold, 2) if rebuy_threshold else None
                },
                "resell": {
                    "enabled": "resell_trigger_pct" in profit_cfg,
                    "state": resell_state,
                    "trigger_pct": profit_cfg.get("resell_trigger_pct", 0.8),
                    "trailing_pct": profit_cfg.get("resell_trail_pct", 0.35),
                    "extreme_price": round(resell_extreme, 2) if resell_extreme else None,
                    "threshold_price": round(resell_threshold, 2) if resell_threshold else None
                }
            },
            "pnl": {
                "daily_usd": round(pnl_data.get("daily", 0), 2),
                "monthly_usd": round(pnl_data.get("monthly", 0), 2),
                "realized_usd": round(pnl_data.get("realized", 0), 2),
                "unrealized_usd": round(pnl_data.get("unrealized", 0), 2),
                "total_usd": round(pnl_data.get("total_usd", 0), 2)
            },
            "events": [],
            "trades": trades
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bot detail: {str(e)}")


@router.get("/bots/{bot_id}/detail")
async def get_bot_detail(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Get full bot detail - unified endpoint for bot detail page. Auth required."""
    require_account_access(current, account_id)
    try:
        # Reuse existing dashboard_bot_detail logic but enhance response
        detail = await dashboard_bot_detail(bot_id, account_id, 0, db, current)
        
        # Enhance with balances, cycles, prices
        bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        pnl_data = PnlService.calculate_bot_pnl(db, bot_id, account_id)
        if pnl_data.get("error"):
            pnl_data = {"total_usd": 0.0, "realized": 0.0, "unrealized": 0.0, "daily": 0.0, "monthly": 0.0, "current_price": 0.0}
        
        # Extract base/quote assets
        symbol = bot.symbol or "BTCUSDT"
        base_asset = symbol.replace("USDT", "").replace("BUSD", "").replace("FDUSD", "")
        quote_asset = "USDT"
        if "BUSD" in symbol:
            quote_asset = "BUSD"
        elif "FDUSD" in symbol:
            quote_asset = "FDUSD"
        
        # Get balances (simplified - in real implementation, get from ledger)
        base_qty = 0.0
        quote_qty = 0.0
        try:
            ledger = Ledger(db, bot_id, account_id)
            base_qty = ledger.get_base_balance()
            quote_qty = ledger.get_quote_balance()
        except:
            pass
        
        detail["balances"] = {
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "base_qty": round(base_qty, 8),
            "quote_qty": round(quote_qty, 2),
            "total_value_quote": round(pnl_data.get("total_usd", 0), 2)
        }
        
        # Get live price - try multiple sources
        live_price = 0.0
        
        # 1. Try from engine_state
        engine_last_price = detail.get("engine_state", {}).get("last_price")
        if engine_last_price and engine_last_price > 0:
            live_price = float(engine_last_price)
        
        # 2. Try from PnL data
        if (not live_price or live_price == 0) and pnl_data.get("current_price"):
            live_price = float(pnl_data.get("current_price", 0))
        
        # Get initial price
        initial_price = detail.get("bot", {}).get("ref_price", 0)
        if not initial_price or initial_price == 0:
            initial_price = live_price
        
        # Set prices in detail
        detail["prices"] = {
            "live_price": round(float(live_price), 2),
            "initial_price": round(float(initial_price), 2)
        }
        
        detail["cycles"] = {
            "today": 0,  # TODO: Calculate from trades
            "total": detail.get("bot", {}).get("cycle_no", 0),
            "current_cycle_id": detail.get("bot", {}).get("cycle_no", 0)
        }
        
        detail["last_trade_at"] = None
        try:
            last_trade = db.query(Trade).filter(
                Trade.bot_id == bot_id,
                Trade.account_id == account_id
            ).order_by(Trade.ts.desc()).first()
            if last_trade and hasattr(last_trade, "ts"):
                detail["last_trade_at"] = last_trade.ts.isoformat() + "Z"
        except Exception:
            pass
        
        return detail
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"Error in get_bot_detail: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching bot detail: {str(e)}")


@router.get("/bots/{bot_id}/events")
async def get_bot_events(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """SSE stream for bot events. Auth required."""
    require_account_access(current, account_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    async def event_generator():
        try:
            # Simple polling-based SSE (in production, use proper event queue)
            last_event_id = 0
            while True:
                # Check if bot still exists
                bot_check = db.query(Bot).filter(Bot.id == bot_id).first()
                if not bot_check:
                    break
                
                # Get latest events (simplified - in production, use proper event log)
                # For now, just send heartbeat
                event_data = {
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "type": "heartbeat",
                    "msg": "Bot aktif",
                    "bot_id": bot_id
                }
                
                yield f"data: {json.dumps(event_data)}\n\n"
                await asyncio.sleep(5)  # Send heartbeat every 5s
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_event = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "type": "error",
                "msg": f"SSE error: {str(e)}"
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# Ticker cache for global ticker bar
_ticker_cache = {
    "data": None,
    "updated_at": None
}


@router.get("/ticker")
async def api_ticker():
    """
    Get ticker data for global top bar.
    Returns ALWAYS numeric values or null (never strings).
    NO-CACHE headers to prevent browser caching.
    """
    from datetime import datetime, timezone
    from fastapi.responses import JSONResponse
    import time
    import httpx
    import asyncio
    
    now = datetime.now(timezone.utc)
    server_time_ms = int(time.time() * 1000)
    
    # Check cache (3 second TTL)
    if _ticker_cache["data"] and _ticker_cache["updated_at"]:
        age = (now - _ticker_cache["updated_at"]).total_seconds()
        if age < 3:
            # Return cached but update ts
            cached = _ticker_cache["data"].copy()
            cached["ts"] = now.isoformat()
            cached["server_time_ms"] = server_time_ms
            
            return JSONResponse(
                content=cached,
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    
    # Populate prices from DataHub (gram altın ve portföy özeti için gerekli)
    prices = {}
    try:
        from app.services.data_hub import data_hub
        all_prices = data_hub.get_all_prices()
        if all_prices:
            for sym, data in all_prices.items():
                if data and isinstance(data.get("price"), (int, float)):
                    prices[sym] = float(data["price"])
    except Exception:
        pass

    # Fallback: USDTTRY veya altın fiyatı yoksa dış API (login-forex)
    gram_altin_try_external = None
    if not prices.get("USDTTRY") or not (prices.get("XAUUSDT") or prices.get("PAXGUSDT")):
        try:
            forex = await get_login_forex()
            if forex.get("usd_try") is not None:
                prices["USDTTRY"] = float(forex["usd_try"])
            if forex.get("gold_gram_try") is not None:
                gram_altin_try_external = float(forex["gold_gram_try"])
        except Exception:
            pass

    # Extract values
    btcusd = prices.get("BTCUSDT")
    ethusd = prices.get("ETHUSDT")
    usdttry = prices.get("USDTTRY")
    
    # EURTRY: try direct EURTRY, fallback to EURUSDT * USDTTRY
    eurtry = prices.get("EURTRY")
    if eurtry is None and usdttry:
        eurusdt = prices.get("EURUSDT")
        if eurusdt:
            eurtry = eurusdt * usdttry
    
    # GBPTRY: try direct GBPTRY, fallback to GBPUSDT * USDTTRY
    gbptry = prices.get("GBPTRY")
    if gbptry is None and usdttry:
        gbpusdt = prices.get("GBPUSDT")
        if gbpusdt:
            gbptry = gbpusdt * usdttry
    
    # Gold: Try XAUUSDT first, then PAXGUSDT
    ons_altin_usd = prices.get("XAUUSDT") or prices.get("PAXGUSDT")
    
    # GRAM_ALTIN_TRY: dış API'den gelen değer yoksa DataHub ile hesapla (1 ONS = 31.1034768 gram)
    gram_altin_try = gram_altin_try_external if gram_altin_try_external is not None else None
    if gram_altin_try is None and ons_altin_usd and usdttry:
        gram_altin_try = (ons_altin_usd * usdttry) / _OZ_TO_GRAM
    
    # Build result (all keys present, numeric or null)
    result = {
        "ts": now.isoformat(),
        "server_time_ms": server_time_ms,
        "USDTTRY": usdttry,
        "EURTRY": eurtry,
        "GBPTRY": gbptry,
        "BTCUSD": btcusd,
        "ETHUSD": ethusd,
        "GRAM_ALTIN_TRY": gram_altin_try,
        "ONS_ALTIN_USD": ons_altin_usd
    }
    
    # Update cache
    _ticker_cache["data"] = result
    _ticker_cache["updated_at"] = now
    
    return JSONResponse(
        content=result,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


# Wallet total_usd cache for dashboard summary (TTL 2s)
_wallet_total_cache: Dict[int, tuple] = {}  # account_id -> (total_usd, ts)
WALLET_CACHE_TTL = 2.0
_WALLET_CACHE_MAX_KEYS = 50

# Full dashboard summary response cache (SLOW_REQUEST azaltmak için)
_dashboard_summary_cache: Dict[int, tuple] = {}  # account_id -> (response_dict, ts)
DASHBOARD_SUMMARY_CACHE_TTL = 20.0  # seconds
_DASHBOARD_SUMMARY_CACHE_MAX_KEYS = 100


def invalidate_dashboard_summary_cache(account_id: int) -> None:
    """Drop cached dashboard summary after bot/account mutations."""
    try:
        _dashboard_summary_cache.pop(int(account_id), None)
    except Exception:
        pass

def _is_binance_invalid_key(exc: Exception) -> bool:
    """True if upstream error is 401 or 400 with Binance code -2015 (Invalid API-key, IP, or permissions)."""
    resp = getattr(exc, "response", None)
    if not resp:
        return False
    sc = getattr(resp, "status_code", None)
    if sc == 401:
        return True
    if sc == 400:
        try:
            body = resp.json() if callable(getattr(resp, "json", None)) else None
            if isinstance(body, dict) and body.get("code") == -2015:
                return True
        except Exception:
            pass
    return False


# Wallet full response: 2s TTL + in-flight dedupe; 429/upstream hata → serve stale
_wallet_response_cache: Dict[int, tuple] = {}  # account_id -> (response_dict, ts)
_wallet_cache_lock = asyncio.Lock()
WALLET_RESPONSE_CACHE_TTL = 30.0
_wallet_inflight: Dict[int, asyncio.Task] = {}  # account_id -> task (in-flight dedupe)

# Open-orders: TTL + in-flight dedupe; 429/418 → serve stale (weight tasarrufu, IP ban riski azaltma)
_open_orders_cache: Dict[tuple, tuple] = {}  # (account_id, symbol or "") -> (response_dict, ts)
_open_orders_cache_lock = asyncio.Lock()
OPEN_ORDERS_CACHE_TTL = 30.0
_OPEN_ORDERS_CACHE_MAX_KEYS = 100
_open_orders_inflight: Dict[tuple, asyncio.Task] = {}  # (account_id, sym) -> task

# Cache stats for /debug/metrics (hits/misses)
_wallet_cache_hits = 0
_wallet_cache_misses = 0
_open_orders_cache_hits = 0
_open_orders_cache_misses = 0

# Upstream error log throttle: invalid_api_key için 5 dk, diger (rate_limit) için 60s
_upstream_error_log_ts: Dict[tuple, float] = {}
_upstream_error_log_lock = asyncio.Lock()
_UPSTREAM_ERROR_LOG_THROTTLE_SEC = 60.0
_UPSTREAM_ERROR_LOG_THROTTLE_INVALID_KEY_SEC = 300.0


async def _should_log_upstream_error(endpoint: str, account_id: int, reason: str) -> bool:
    """Aynı endpoint/account/reason için True döner (WARNING yazılacak); throttle süresi dolmamışsa False."""
    key = (endpoint, account_id, reason)
    now = time.time()
    throttle = _UPSTREAM_ERROR_LOG_THROTTLE_INVALID_KEY_SEC if reason == "invalid_api_key" else _UPSTREAM_ERROR_LOG_THROTTLE_SEC
    async with _upstream_error_log_lock:
        last = _upstream_error_log_ts.get(key)
        if last is not None and (now - last) < throttle:
            return False
        _upstream_error_log_ts[key] = now
        if len(_upstream_error_log_ts) > 500:
            cutoff = now - _UPSTREAM_ERROR_LOG_THROTTLE_SEC * 2
            to_del = [k for k, t in _upstream_error_log_ts.items() if t < cutoff]
            for k in to_del:
                del _upstream_error_log_ts[k]
        return True


def get_binance_cache_stats() -> dict:
    """Return cache hit/miss counts for observability."""
    total_w = _wallet_cache_hits + _wallet_cache_misses
    total_o = _open_orders_cache_hits + _open_orders_cache_misses
    return {
        "wallet": {"hits": _wallet_cache_hits, "misses": _wallet_cache_misses, "hit_rate": round(_wallet_cache_hits / total_w, 2) if total_w else 0},
        "open_orders": {"hits": _open_orders_cache_hits, "misses": _open_orders_cache_misses, "hit_rate": round(_open_orders_cache_hits / total_o, 2) if total_o else 0},
    }


async def invalidate_wallet_cache(account_id: int) -> None:
    """Remove wallet cache for account (e.g. after spot order). Used by spot_routes."""
    async with _wallet_cache_lock:
        _wallet_response_cache.pop(account_id, None)
        _wallet_total_cache.pop(account_id, None)
        _wallet_inflight.pop(account_id, None)
    invalidate_dashboard_summary_cache(account_id)
    try:
        from app.api.routes.home import invalidate_home_wallet_cache
        invalidate_home_wallet_cache(account_id)
    except Exception:
        pass


async def invalidate_open_orders_cache(account_id: int) -> None:
    """Remove open-orders cache for account (e.g. after spot order). Used by spot_routes."""
    async with _open_orders_cache_lock:
        for key in list(_open_orders_cache.keys()):
            if key[0] == account_id:
                del _open_orders_cache[key]
        for key in list(_open_orders_inflight.keys()):
            if key[0] == account_id:
                del _open_orders_inflight[key]


# Günlük KPI referansı: botlar için lazy ref (cüzdan günlük değişimi AssetSnapshot ile gün başı bakiyesinden hesaplanır)
_daily_kpi_ref: Dict[int, dict] = {}  # account_id -> {ref_date: str, bots_ref_usd: float}


def _turkey_date_str() -> str:
    """Türkiye saatinde bugünün tarihi YYYY-MM-DD."""
    return datetime.now(TR_TZ).strftime("%Y-%m-%d")


# Dashboard Bootstrap — tek hızlı endpoint (appBoot). Subroute yüklenmezse bu fallback yanıt verir; 404 olmaz.
@router.get("/dashboard/bootstrap")
async def api_dashboard_bootstrap(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Initial load: prices (cached), kpis, wallet_cached, wallet_status. Subroute varsa ona delege et."""
    require_account_access(current, account_id)
    try:
        from app.api.routes import dashboard_bootstrap as db_mod
        return await db_mod.dashboard_bootstrap(request, account_id=account_id, db=db, current=current)
    except Exception as e:
        logger.warning("Dashboard bootstrap delegate failed, returning minimal: %s", e)
    request_id = getattr(request.state, "request_id", None) or ""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    prices = {}
    try:
        prices = data_hub.get_all_prices() or {}
    except Exception:
        pass
    wallet_cached, wallet_cached_at = None, None
    try:
        from app.api.routes.home import _get_wallet_cached_enriched_with_new_session
        wallet_cached, wallet_cached_at = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _get_wallet_cached_enriched_with_new_session(account_id, 20)
        )
    except Exception:
        pass
    kpis = {}
    try:
        from app.api.routes.home import _get_kpis_minimal
        kpis = await _get_kpis_minimal(account_id, db)
    except Exception:
        pass
    ek = getattr(account, "api_key_enc", None)
    es = getattr(account, "api_secret_enc", None)
    keys_configured = bool(ek and es and (not isinstance(ek, str) or ek.strip()) and (not isinstance(es, str) or es.strip()))
    return {
        "ok": True,
        "data": {
            "prices": prices,
            "kpis": kpis,
            "wallet_cached": wallet_cached,
            "wallet_cached_at": wallet_cached_at,
            "wallet_status": {"keys_configured": keys_configured, "last_error_code": None, "cooldown_until": None},
        },
        "meta": {"request_id": request_id, "server_ms": 0},
    }


# Dashboard Summary
@router.get("/dashboard/summary")
async def api_dashboard_summary(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Single source of truth: account + bots + KPIs. Auth required; only own account or admin."""
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    now = time.time()
    if account_id in _dashboard_summary_cache:
        cached, ts = _dashboard_summary_cache[account_id]
        if now - ts < DASHBOARD_SUMMARY_CACHE_TTL:
            return cached
        if len(_dashboard_summary_cache) > _DASHBOARD_SUMMARY_CACHE_MAX_KEYS:
            cutoff = now - DASHBOARD_SUMMARY_CACHE_TTL * 2
            for aid in [a for a, (_, t) in _dashboard_summary_cache.items() if t < cutoff]:
                _dashboard_summary_cache.pop(aid, None)

    from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
    is_test = is_test_account(account_id, db)
    binance_equity = 0.0
    if is_test:
        binance_equity = float(TEST_PAPER_BALANCE_USDT)
    now = time.time()
    if not is_test and account_id in _wallet_total_cache:
        total_usd, ts = _wallet_total_cache[account_id]
        if now - ts < WALLET_CACHE_TTL:
            binance_equity = total_usd
    if binance_equity == 0.0 and not is_test:
        try:
            from app.services.binance_assets import get_account_keys
            from app.services.binance_spot import get_wallet
            from app.services.wallet_pricing import build_wallet_price_map
            keys = await get_account_keys(account_id, db)
            wallet_data = await asyncio.wait_for(get_wallet(keys, tag="dashboard_summary"), timeout=6.0)
            balances = wallet_data.get("balances") or []
            price_map = await build_wallet_price_map(balances, testnet=keys.testnet)
            resp = _wallet_response(account_id, balances, price_map)
            binance_equity = resp["total_usd"]
            _wallet_total_cache[account_id] = (binance_equity, time.time())
        except ValueError:
            pass
        except Exception:
            pass

    bots = db.query(Bot).filter(Bot.account_id == account_id).all()
    total_bots = len(bots)
    from app.services.bot_status_utils import count_running_bots

    active_bots = count_running_bots(bots)
    import json as _json
    total_bot_equity_usd = 0.0
    total_bot_initial_usd = 0.0  # Sum of all bot initial balances
    daily_pnl_usd_acc = 0.0
    cycles_today = 0
    bots_array = []
    _today_start = turkey_today_start_utc()
    _today_date = _today_start.strftime("%Y-%m-%d")

    for bot in bots:
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, account_id)
        initial_usd = 0.0
        try:
            cfg = _json.loads(bot.config_json or "{}")
            initial_usd = float(cfg.get("budget_usd") or cfg.get("bot_budget_quote") or cfg.get("initial_capital_usdt") or 0)
        except Exception:
            pass
        current_usd = pnl_data.get("total_usd", 0.0) if not pnl_data.get("error") else 0.0
        daily_bot = pnl_data.get("daily", 0.0) if not pnl_data.get("error") else 0.0
        daily_pnl_pct = float(pnl_data.get("daily_pnl_pct") or 0.0) if not pnl_data.get("error") else 0.0
        _sym = (bot.symbol or "").strip().upper()
        _strategy_id = (_json.loads(bot.config_json or "{}").get("strategy_id") or "").strip().lower()
        _state = load_state(db, bot.id) or {}
        _ia_done = bool(_state.get("initial_allocation_done"))
        from app.services.bot_equity import compute_bot_equity_usd
        if _sym and _sym != "MULTI" and _strategy_id not in ("trdca_pro", "multi_asset_rebalance"):
            try:
                current_usd = compute_bot_equity_usd(db, bot, _state, pnl_data, initial_usd=initial_usd)
                if _ia_done:
                    _ref_date = _state.get("daily_ref_date")
                    _ref_usd = float(_state.get("daily_ref_usd") or 0)
                    if _ref_date == _today_date and _ref_usd > 0:
                        daily_bot = current_usd - _ref_usd
                        daily_pnl_pct = (daily_bot / _ref_usd) * 100.0
                elif (bot.status or "").lower() == "running":
                    current_usd = 0.0
                    daily_bot = 0.0
                    daily_pnl_pct = 0.0
            except Exception:
                pass
        elif _sym == "MULTI" or _strategy_id in ("trdca_pro", "multi_asset_rebalance"):
            try:
                current_usd = compute_bot_equity_usd(db, bot, _state, pnl_data, initial_usd=initial_usd)
            except Exception:
                pass
        daily_pnl_usd_acc += daily_bot
        if not pnl_data.get("error"):
            total_bot_equity_usd += current_usd
            total_bot_initial_usd += initial_usd

        last_t = db.query(Trade).filter(
            Trade.bot_id == bot.id,
            Trade.account_id == account_id
        ).order_by(Trade.ts.desc()).first()
        last_trade_at = last_t.ts.isoformat() + "Z" if last_t and getattr(last_t, "ts", None) else None

        total_pnl_usd_bot = current_usd - initial_usd
        total_pnl_pct_bot = (total_pnl_usd_bot / initial_usd * 100) if initial_usd > 0 else 0.0
        cycles = Ledger.get_cycle_ids(db, bot.id, account_id)
        total_cycles_completed = max(cycles) if cycles else 0
        _state_cycle_id = int(_state.get("cycle_id") or 0)
        if _state_cycle_id > total_cycles_completed:
            total_cycles_completed = _state_cycle_id
        try:
            bot_config = _json.loads(bot.config_json or "{}")
        except Exception:
            bot_config = {}
        _display_status = (bot.status or "stopped")
        if (_display_status or "").lower() == "running" and not _ia_done and current_usd <= 0.01:
            _display_status = "starting"
        bots_array.append({
            "bot_id": bot.id,
            "id": bot.id,
            "bot_code": getattr(bot, "bot_code", None) or str(bot.id),
            "symbol": bot.symbol,
            "config": bot_config,
            "status": bot.status or "stopped",
            "display_status": _display_status,
            "initial_allocation_done": _ia_done,
            "base_balance": round(float(_state.get("base_balance") or 0), 8),
            "quote_balance": round(float(_state.get("quote_balance") or 0), 8),
            "budget_usd": round(initial_usd, 2),
            "initial_usd": round(initial_usd, 2),
            "current_usd": round(current_usd, 2),
            "daily_pnl_usd": round(daily_bot, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "total_pnl_usd": round(total_pnl_usd_bot, 2),
            "total_pnl_pct": round(total_pnl_pct_bot, 2),
            "account_id": account_id,
            "last_trade_at": last_trade_at,
            "total_cycles_completed": total_cycles_completed,
            "cycle_id": int(_state.get("cycle_id") or total_cycles_completed or 1),
        })

    user_name = None
    user_surname = None
    user_phone = None
    if account.user_id:
        u = db.query(User).filter(User.id == account.user_id).first()
        if u:
            user_name = u.name
            user_surname = u.surname
            user_phone = u.phone
    # Günlük PnL (botlar): sadece o gün tamamlanan turların (cycle) kârlarının toplamı
    daily_bot_pnl_usd_kpi = PnlService.daily_realized_from_cycles_completed_today(db, account_id)
    today_tr = _turkey_date_str()
    today_start_utc = turkey_today_start_utc()
    # Cüzdan günlük değişimi: gün başı (Türkiye 00:00) bakiyesine göre; AssetSnapshot ile doğru referans
    ref_cuzdan = None
    try:
        last_before_today = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id, AssetSnapshot.timestamp < today_start_utc)
            .order_by(desc(AssetSnapshot.timestamp))
            .first()
        )
        if last_before_today and getattr(last_before_today, "total_usd_value", None) is not None:
            ref_cuzdan = float(last_before_today.total_usd_value)
        else:
            first_today = (
                db.query(AssetSnapshot)
                .filter(AssetSnapshot.account_id == account_id, AssetSnapshot.timestamp >= today_start_utc)
                .order_by(AssetSnapshot.timestamp.asc())
                .first()
            )
            if first_today and getattr(first_today, "total_usd_value", None) is not None:
                ref_cuzdan = float(first_today.total_usd_value)
    except Exception:
        pass
    if ref_cuzdan is None:
        ref_cuzdan = binance_equity  # Snapshot yoksa değişim 0
    daily_wallet_pnl_usd = binance_equity - ref_cuzdan
    daily_wallet_pnl_pct = (daily_wallet_pnl_usd / ref_cuzdan * 100.0) if ref_cuzdan and ref_cuzdan > 0 else 0.0
    # Bot günlük % için lazy ref (ilk istekte mevcut bakiye = ref)
    ref = _daily_kpi_ref.get(account_id)
    if ref is None or ref.get("ref_date") != today_tr:
        ref = {"ref_date": today_tr, "bots_ref_usd": total_bot_equity_usd}
        _daily_kpi_ref[account_id] = ref
    ref_bots = ref["bots_ref_usd"]
    daily_bot_pnl_pct_kpi = (daily_bot_pnl_usd_kpi / ref_bots * 100.0) if ref_bots and ref_bots > 0 else 0.0

    out = {
        "account": {
            "id": account.id,
            "account_code": getattr(account, "account_code", None) or None,
            "name": account.name,
            "user_name": user_name,
            "user_surname": user_surname,
            "user_phone": user_phone,
            "spot_balance_usd": round(binance_equity, 2),
            "bots_balance_usd": round(total_bot_equity_usd, 2),
            "bots_initial_usd": round(total_bot_initial_usd, 2),
            "daily_bot_pnl_usd": round(daily_bot_pnl_usd_kpi, 2),
            "daily_wallet_pnl_usd": round(daily_wallet_pnl_usd, 2),
            "daily_bot_pnl_pct": round(daily_bot_pnl_pct_kpi, 2),
            "daily_wallet_pnl_pct": round(daily_wallet_pnl_pct, 2),
            "daily_pnl_usd": round(daily_bot_pnl_usd_kpi, 2),
            "total_pnl_usd": round(total_bot_equity_usd - total_bot_initial_usd, 2),
        },
        "account_code": getattr(account, "account_code", None) or None,
        "account_name": account.name,
        "user_name": user_name,
        "user_surname": user_surname,
        "user_phone": user_phone,
        "total_bots": total_bots,
        "active_bots": active_bots,
        "active_bots_count": active_bots,
        "daily_bot_pnl_usd": round(daily_bot_pnl_usd_kpi, 2),
        "daily_wallet_pnl_usd": round(daily_wallet_pnl_usd, 2),
        "daily_bot_pnl_pct": round(daily_bot_pnl_pct_kpi, 2),
        "daily_wallet_pnl_pct": round(daily_wallet_pnl_pct, 2),
        "daily_pnl_usd": round(daily_bot_pnl_usd_kpi, 2),
        "total_pnl_usd": round(total_bot_equity_usd - total_bot_initial_usd, 2),
        "total_profit_usd": round(total_bot_equity_usd - total_bot_initial_usd, 2),
        "total_balance_usd": round(total_bot_equity_usd, 2),
        "cycles_today_count": cycles_today,
        "bots": bots_array,
        "is_test_account": is_test,
    }
    _dashboard_summary_cache[account_id] = (out, time.time())
    return out


SNAPSHOT_TASK_TIMEOUT = 3.0

# Max assets to return in snapshot wallet (cache-only); matches home_fast_max_assets intent
SNAPSHOT_WALLET_MAX_ASSETS = 20


def _snapshot_wallet_from_asset_row(row) -> Dict[str, Any]:
    """Build minimal wallet dict from AssetSnapshot row (breakdown_json + total_usd_value). Cache-only path."""
    total_usd = float(getattr(row, "total_usd_value", 0) or 0)
    assets: List[Dict[str, Any]] = []
    try:
        breakdown = json.loads(row.breakdown_json or "{}") if getattr(row, "breakdown_json", None) else {}
    except Exception:
        breakdown = {}
    for asset, data in (breakdown or {}).items():
        if not isinstance(data, dict):
            continue
        free = float(data.get("free") or 0)
        locked = float(data.get("locked") or 0)
        bot_locked = float(data.get("bot_locked") or 0)
        total = float(data.get("total") or 0)
        if total <= 0:
            total = free + locked + bot_locked
        usd_val = data.get("usdValue")
        usdt_value = float(usd_val) if usd_val is not None else None
        if total <= 0 and free <= 0 and locked <= 0 and (usdt_value is None or usdt_value <= 0):
            continue
        assets.append({
            "asset": asset,
            "free": free,
            "locked": locked,
            "total": total if total > 0 else None,
            "bot_locked": bot_locked if bot_locked > 0 else None,
            "usdt_value": round(usdt_value, 2) if usdt_value is not None else None,
        })
    # Sort by usdt_value desc, cap
    with_val = [(a, (a.get("usdt_value") if a.get("usdt_value") is not None else -1.0)) for a in assets]
    with_val.sort(key=lambda x: (x[1] < 0, -x[1]))
    assets = [x[0] for x in with_val[:SNAPSHOT_WALLET_MAX_ASSETS]]
    return {"total_usd": round(total_usd, 2), "assets": assets}


def _enrich_snapshot_wallet_with_bot_locked(wallet: Dict[str, Any], account_id: int, db: Session) -> None:
    """
    Snapshot cüzdanına bot kilitli ve kilitli USD alanlarını ekler (strip ve varlık tablosu doğru göstersin).
    Test hesabında tek kaynak: build_test_account_wallet (paper 10k + bot satırları).
    """
    from app.services.test_account import is_test_account
    from app.services.wallet_display import build_test_account_wallet

    if is_test_account(account_id, db):
        rebuilt = build_test_account_wallet(account_id, db)
        if rebuilt and wallet is not None:
            wallet.clear()
            wallet.update(rebuilt)
        return
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
    if not wallet or not isinstance(wallet.get("assets"), list):
        return
    bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
    free_usd_tot = 0.0
    locked_usd_tot = 0.0
    total_bot_locked_usd = 0.0
    snapshot_assets = set()
    for a in wallet["assets"]:
        asset = (a.get("asset") or "").strip()
        if not asset:
            continue
        snapshot_assets.add(asset)
        free = float(a.get("free") or 0)
        locked = float(a.get("locked") or 0)
        usdt_value = a.get("usdt_value")
        total_val = float(usdt_value) if usdt_value is not None else 0.0
        total_qty = free + locked
        price = (total_val / total_qty) if total_qty > 0 else 0.0
        free_val = free * price
        locked_val = locked * price
        a["free_usd"] = round(free_val, 2)
        a["locked_usd"] = round(locked_val, 2)
        a["total_usd"] = round(total_val, 2) if usdt_value is not None else None
        bot_locked_qty = float(bot_locked.get(asset, 0) or 0)
        bot_locked_val = min(bot_locked_qty * price, free_val) if price > 0 else 0.0
        available_qty = max(0.0, free - bot_locked_qty)
        available_val = max(0.0, free_val - bot_locked_val)
        a["bot_locked"] = round(bot_locked_qty, 8)
        a["available"] = round(available_qty, 8)
        a["bot_locked_usd"] = round(bot_locked_val, 2)
        a["available_usd"] = round(available_val, 2)
        free_usd_tot += free_val
        locked_usd_tot += locked_val
        total_bot_locked_usd += bot_locked_val

    # Snapshot listesi düşük değerli varlıkları kesebilir. Botun tuttuğu coin
    # snapshot'ta yoksa bile cüzdanda görünmeli; aksi halde ETH gibi açık bot
    # varlıkları tabloda kaybolur ve kullanılabilir bakiye yanlış görünür.
    try:
        prices_map = data_hub.get_all_prices() or {}
    except Exception:
        prices_map = {}
    stable = {"USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"}
    for asset, bl_qty in bot_locked.items():
        if not asset or asset in snapshot_assets:
            continue
        bl_qty = float(bl_qty or 0)
        if bl_qty <= 0:
            continue
        if asset in stable:
            price = 1.0
        else:
            price = None
            for quote in ("USDT", "BUSD", "FDUSD", "USDC"):
                raw = prices_map.get(f"{asset}{quote}")
                if raw is not None and float(raw) > 0:
                    price = float(raw)
                    break
        if price is None:
            continue
        bl_val = round(bl_qty * price, 2)
        total_bot_locked_usd += bl_val
        wallet["assets"].append({
            "asset": asset,
            "free": 0.0,
            "locked": 0.0,
            "total": bl_qty,
            "bot_locked": round(bl_qty, 8),
            "available": 0.0,
            "free_usd": 0.0,
            "locked_usd": 0.0,
            "total_usd": bl_val,
            "usdt_value": bl_val,
            "bot_locked_usd": bl_val,
            "available_usd": 0.0,
            "_synthetic": True,
        })
        wallet["total_usd"] = round((wallet.get("total_usd") or 0) + bl_val, 2)
    wallet["free_usd"] = round(free_usd_tot, 2)
    wallet["locked_usd"] = round(locked_usd_tot, 2)
    wallet["bot_locked_usd"] = round(total_bot_locked_usd, 2)
    wallet["available_usd"] = round(max(0.0, free_usd_tot - total_bot_locked_usd), 2)


def _get_snapshot_wallet_cached(account_id: int, db: Session):
    """
    Cache-only wallet for snapshot: read last AssetSnapshot. No Binance call.
    Returns (wallet_dict or None, ts_iso or None, source "db_snapshot"|"none", age_sec or None).
    """
    try:
        row = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(desc(AssetSnapshot.timestamp))
            .limit(1)
            .first()
        )
        if not row:
            return (None, None, "none", None)
        ts = getattr(row, "timestamp", None)
        if not ts:
            return (None, None, "none", None)
        ts_utc = None
        if hasattr(ts, "tzinfo"):
            ts_utc = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
            ts_iso = ts_utc.isoformat()
        else:
            ts_iso = str(ts)
        if not ts_iso.endswith("Z"):
            ts_iso = ts_iso.replace("+00:00", "Z") if "+00:00" in ts_iso else ts_iso + "Z"
        wallet = _snapshot_wallet_from_asset_row(row)
        now = time.time()
        try:
            ts_epoch = ts_utc.timestamp() if ts_utc is not None else now
        except Exception:
            ts_epoch = now
        age_sec = round(now - ts_epoch, 2) if ts_epoch else None
        return (wallet, ts_iso, "db_snapshot", age_sec)
    except Exception as e:
        logging.getLogger(__name__).warning("[snapshot] wallet cache read error account_id=%s: %s", account_id, e)
        return (None, None, "none", None)


def _schedule_snapshot_wallet_refresh(account_id: int, request_id: str) -> bool:
    now = time.monotonic()
    task = _snapshot_wallet_refresh_tasks.get(account_id)
    if task and not task.done():
        return False
    last = _snapshot_wallet_refresh_last_at.get(account_id, 0.0)
    if now - last < _SNAPSHOT_WALLET_REFRESH_GAP_SEC:
        return False
    _snapshot_wallet_refresh_last_at[account_id] = now

    async def _runner() -> None:
        db2 = SessionLocal()
        try:
            from app.api.routes.home import _do_wallet_refresh
            await _do_wallet_refresh(account_id, db2, request_id or "snapshot-stale", True)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "snapshot_wallet_refresh_failed account_id=%s request_id=%s error=%s",
                account_id, request_id, str(exc)[:200],
            )
        finally:
            try:
                db2.close()
            except Exception:
                pass
            cur = _snapshot_wallet_refresh_tasks.get(account_id)
            if cur is asyncio.current_task():
                _snapshot_wallet_refresh_tasks.pop(account_id, None)

    try:
        _snapshot_wallet_refresh_tasks[account_id] = asyncio.create_task(_runner())
        return True
    except RuntimeError:
        return False


@router.get("/dashboard/snapshot")
async def api_dashboard_snapshot(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    fields: Optional[str] = Query(None, description="Comma-separated: prices,wallet,bots,kpis. Default: prices,kpis"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Aggregated dashboard snapshot. Contract: { ok, data, meta }.
    Optional fields param (SNAPSHOT_FIELDS_ENABLED): prices, wallet, bots, kpis. Invalid field -> 400 INVALID_FIELDS.
    """
    t0 = time.perf_counter()
    request_id = getattr(request.state, "request_id", None) or ""
    from app.core.constants import MAX_SNAPSHOT_BYTES, SNAPSHOT_FIELDS_ENABLED, SNAPSHOT_TRIM_ENABLED
    try:
        from app.api.utils.fields import parse_snapshot_fields, ALLOWED_SNAPSHOT_FIELDS
    except ImportError:
        _ALLOWED = {"prices", "wallet", "bots", "kpis"}
        _DEFAULT = ["prices", "kpis"]
        def parse_snapshot_fields(fields_param):
            if not fields_param or not fields_param.strip():
                return (_DEFAULT.copy(), None)
            parts = [p.strip().lower() for p in fields_param.split(",") if p.strip()]
            invalid = [p for p in parts if p not in _ALLOWED]
            return ([], invalid) if invalid else (parts or _DEFAULT.copy(), None)
        ALLOWED_SNAPSHOT_FIELDS = _ALLOWED

    if SNAPSHOT_FIELDS_ENABLED:
        requested_fields, invalid = parse_snapshot_fields(fields)
        if invalid is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "ok": False,
                    "error": {
                        "error_code": "INVALID_FIELDS",
                        "error_id": str(__import__("uuid").uuid4()),
                        "request_id": request_id,
                        "message": "Unknown snapshot fields",
                        "details": {"invalid_fields": invalid, "allowed": list(ALLOWED_SNAPSHOT_FIELDS)},
                    },
                },
            )
    else:
        requested_fields = ["prices", "wallet", "bots", "kpis"]

    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        from app.services.dashboard_snapshot import (
            fetch_prices,
            fetch_bots_and_account_kpis,
            fetch_finance_pnl,
        )
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "error": "Snapshot service unavailable (missing app.services.dashboard_snapshot). Deploy or git pull."},
        ) from e

    _log = logging.getLogger(__name__)

    def _is_api_key_error(e):
        s = str(e)
        return "401" in s or "Unauthorized" in s or "Invalid API-key" in s or "invalid_api_key" in s.lower()

    async def _safe(coro, name):
        try:
            return await asyncio.wait_for(coro, timeout=SNAPSHOT_TASK_TIMEOUT)
        except asyncio.TimeoutError:
            _log.warning("[snapshot] %s timeout", name)
            return {"_error": "timeout"}
        except Exception as e:
            if name == "wallet" and _is_api_key_error(e):
                _log.debug("[snapshot] wallet error (API key invalid): %s", e)
            else:
                _log.warning("[snapshot] %s error: %s", name, e)
            return {"_error": str(e)}

    need_prices = "prices" in requested_fields
    need_wallet = "wallet" in requested_fields or "kpis" in requested_fields
    need_bots = "bots" in requested_fields or "kpis" in requested_fields
    need_pnl = "kpis" in requested_fields

    # Snapshot is cache-only for wallet: no live Binance call. Live refresh is POST /api/home/wallet/refresh only.
    tasks = []
    task_names = []
    if need_prices:
        tasks.append(_safe(fetch_prices(), "prices"))
        task_names.append("prices")
    if need_bots:
        tasks.append(_safe(fetch_bots_and_account_kpis(account_id, db), "bots"))
        task_names.append("bots")
    if need_pnl:
        tasks.append(_safe(fetch_finance_pnl(account_id, db), "pnl"))
        task_names.append("pnl")

    SNAPSHOT_OVERALL_TIMEOUT = 10.0  # avoid 499 (client disconnect): cap total wait
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks) if tasks else asyncio.sleep(0),
            timeout=SNAPSHOT_OVERALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        results = [{"_error": "timeout"}] * len(tasks) if tasks else []
    if not isinstance(results, (list, tuple)) or len(results) != len(tasks):
        results = [{"_error": "timeout"}] * len(tasks) if tasks else []
    by_name = dict(zip(task_names, results))

    prices_raw = by_name.get("prices", {})
    bots_raw = by_name.get("bots", {})
    pnl_raw = by_name.get("pnl", {})

    prices = prices_raw if isinstance(prices_raw, dict) and "_error" not in prices_raw else {}
    pnl = pnl_raw if isinstance(pnl_raw, dict) and "_error" not in pnl_raw else {}

    # Wallet: cache-only (DB AssetSnapshot). Never call Binance here.
    wallet = {}
    wallet_error = ""
    wallet_source = "none"
    wallet_age_sec = None
    wallet_ts_iso = None
    keys_configured = False
    wallet_refresh_scheduled = False
    if need_wallet:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            ek = getattr(acc, "api_key_enc", None)
            es = getattr(acc, "api_secret_enc", None)
            keys_configured = bool(ek and es and (not isinstance(ek, str) or ek.strip()) and (not isinstance(es, str) or es.strip()))
        wallet_cached, wallet_ts_iso, wallet_source, wallet_age_sec = _get_snapshot_wallet_cached(account_id, db)
        from app.services.test_account import is_test_account
        is_test_wallet = is_test_account(account_id, db)
        if is_test_wallet:
            from app.services.wallet_display import build_test_account_wallet

            wallet = build_test_account_wallet(account_id, db)
            wallet_ts_iso = wallet.get("ts")
            wallet_source = "test_paper"
        elif wallet_cached:
            wallet = dict(wallet_cached)
            if wallet_ts_iso:
                wallet["ts"] = wallet_ts_iso
            _enrich_snapshot_wallet_with_bot_locked(wallet, account_id, db)
        else:
            wallet = {
                "keys_configured": keys_configured,
                "_error": {
                    "error_code": "WALLET_NOT_READY",
                    "detail": "No cached snapshot yet",
                    "request_id": request_id,
                },
                "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        try:
            stale_threshold_sec = float(os.environ.get("WALLET_SNAPSHOT_WARN_AGE_SEC", "900"))
        except Exception:
            stale_threshold_sec = 900.0
        if keys_configured and not is_test_wallet and (wallet_age_sec is None or float(wallet_age_sec) >= stale_threshold_sec):
            wallet_refresh_scheduled = _schedule_snapshot_wallet_refresh(account_id, request_id)

    # On wallet error: use last-known total_usd from cache so UI does not flash to 0 (stale fallback)
    SNAPSHOT_WALLET_STALE_FALLBACK_SEC = 120.0
    last_known_total = None
    if wallet_error and account_id in _wallet_total_cache:
        total_usd, ts = _wallet_total_cache[account_id]
        if (time.time() - ts) < SNAPSHOT_WALLET_STALE_FALLBACK_SEC and (total_usd is not None and total_usd > 0):
            last_known_total = float(total_usd)

    bots = []
    account_kpis = {}
    if isinstance(bots_raw, dict) and "_error" not in bots_raw:
        bots = bots_raw.get("bots") or []
        account_kpis = bots_raw.get("account") or {}
        if wallet and "total_usd" in wallet:
            if is_test_account(account_id, db):
                account_kpis["spot_balance_usd"] = wallet.get("spot_kpi_total_usd") or wallet.get("total_usd", 0)
            else:
                account_kpis["spot_balance_usd"] = wallet.get("total_usd", 0)
        elif last_known_total is not None:
            account_kpis["spot_balance_usd"] = last_known_total
        today_tr = _turkey_date_str()
        total_bot_equity = float(bots_raw.get("total_bot_equity_usd", 0) or 0)
        if is_test_account(account_id, db) and wallet.get("daily_wallet_pnl_usd") is not None:
            daily_wallet_pnl_usd = float(wallet.get("daily_wallet_pnl_usd") or 0)
            daily_wallet_pnl_pct = float(wallet.get("daily_wallet_pnl_pct") or 0)
        else:
            if is_test_account(account_id, db) and wallet:
                binance_equity = float(
                    wallet.get("spot_kpi_total_usd") or wallet.get("total_usd") or 0
                )
            else:
                binance_equity = float(wallet.get("total_usd", 0) or 0) if wallet else (last_known_total or 0.0)
            today_start_utc = turkey_today_start_utc()
            ref_cuzdan = None
            try:
                last_before_today = (
                    db.query(AssetSnapshot)
                    .filter(AssetSnapshot.account_id == account_id, AssetSnapshot.timestamp < today_start_utc)
                    .order_by(desc(AssetSnapshot.timestamp))
                    .first()
                )
                if last_before_today and getattr(last_before_today, "total_usd_value", None) is not None:
                    ref_cuzdan = float(last_before_today.total_usd_value)
                else:
                    first_today = (
                        db.query(AssetSnapshot)
                        .filter(AssetSnapshot.account_id == account_id, AssetSnapshot.timestamp >= today_start_utc)
                        .order_by(AssetSnapshot.timestamp.asc())
                        .first()
                    )
                    if first_today and getattr(first_today, "total_usd_value", None) is not None:
                        ref_cuzdan = float(first_today.total_usd_value)
            except Exception:
                pass
            if ref_cuzdan is None:
                ref_cuzdan = binance_equity
            daily_wallet_pnl_usd = binance_equity - ref_cuzdan
            daily_wallet_pnl_pct = (daily_wallet_pnl_usd / ref_cuzdan * 100.0) if ref_cuzdan and ref_cuzdan > 0 else 0.0
        ref = _daily_kpi_ref.get(account_id)
        if ref is None or ref.get("ref_date") != today_tr:
            ref = {"ref_date": today_tr, "bots_ref_usd": total_bot_equity}
            _daily_kpi_ref[account_id] = ref
        ref_bots = ref.get("bots_ref_usd") or 0
        daily_bot_pnl_usd_kpi = bots_raw.get("daily_bot_pnl_usd_kpi") or 0
        daily_bot_pnl_pct_kpi = (daily_bot_pnl_usd_kpi / ref_bots * 100.0) if ref_bots and ref_bots > 0 else 0.0
        account_kpis["daily_wallet_pnl_usd"] = round(daily_wallet_pnl_usd, 2)
        account_kpis["daily_wallet_pnl_pct"] = round(daily_wallet_pnl_pct, 2)
        account_kpis["daily_bot_pnl_usd"] = round(daily_bot_pnl_usd_kpi, 2)
        account_kpis["daily_bot_pnl_pct"] = round(daily_bot_pnl_pct_kpi, 2)

    from app.services.test_account import is_test_account
    account_kpis["is_test_account"] = is_test_account(account_id, db)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    stale_symbols_count = 0
    prices_ready = True
    try:
        from app.services.data_hub import data_hub
        st = data_hub.get_status()
        stale_symbols_count = st.get("stale_symbols_count", 0)
        prices_ready = bool(data_hub.prices)
    except Exception:
        pass

    data: Dict[str, Any] = {}
    if "prices" in requested_fields:
        data["prices"] = prices
    if need_wallet:
        # Contract: snapshot always returns wallet when wallet or kpis requested (cache-only, never live).
        data["wallet"] = dict(wallet) if wallet else {}
    if "bots" in requested_fields:
        data["bots"] = bots
    if "kpis" in requested_fields:
        data["kpis"] = {"account": account_kpis, "pnl": pnl}
    data["server_ts"] = time.time()

    trimmed_fields: List[str] = []
    if SNAPSHOT_TRIM_ENABLED:
        payload_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
        for _ in range(4):  # max trim rounds: bots, wallet, prices
            if len(payload_bytes) <= MAX_SNAPSHOT_BYTES:
                break
            if "bots" in data and data.get("bots"):
                data["bots"] = []
                trimmed_fields.append("bots")
            elif "wallet" in data and data.get("wallet"):
                data["wallet"] = {}
                trimmed_fields.append("wallet")
            elif data.get("prices"):
                in_wallet = set()
                for b in (data.get("wallet") or {}).get("assets") or []:
                    sym = (b or {}).get("asset") or ""
                    if sym and sym != "USDT":
                        in_wallet.add(f"{sym}USDT")
                        in_wallet.add(sym)
                trimmed_prices = dict(list(data["prices"].items())[:100])
                for k, v in (data.get("prices") or {}).items():
                    if k in in_wallet and k not in trimmed_prices:
                        trimmed_prices[k] = v
                data["prices"] = trimmed_prices
                if "prices" not in trimmed_fields:
                    trimmed_fields.append("prices")
            payload_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
    else:
        payload_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")

    meta = {
        "request_id": request_id,
        "server_ms": round(elapsed_ms, 2),
        "payload_bytes": len(payload_bytes),
        "trimmed_fields": trimmed_fields,
        "stale": not prices_ready or stale_symbols_count > 0,
    }
    if need_wallet:
        meta["wallet_source"] = wallet_source
        meta["wallet_age_sec"] = wallet_age_sec
        meta["wallet_ts_iso"] = wallet_ts_iso
        meta["wallet_refresh_scheduled"] = wallet_refresh_scheduled

    _log.info(
        "snapshot_served wallet_source=%s wallet_age_sec=%s request_id=%s payload_bytes=%s server_ms=%s fields=%s",
        wallet_source if need_wallet else "n/a", wallet_age_sec if need_wallet else None, request_id,
        len(payload_bytes), round(elapsed_ms, 2), requested_fields,
    )
    if "wallet" in data and data.get("wallet") and isinstance(data["wallet"], dict):
        w = data["wallet"]
        err = w.get("_error")
        err_code = None
        if isinstance(err, dict):
            err_code = err.get("error_code") or err.get("code") or str(err)[:64]
        elif isinstance(err, str) and err:
            err_code = err[:64]
        log_wallet_trace(
            event="wallet_payload_out",
            request_id=request_id or "",
            account_id=account_id,
            source="snapshot_wallet",
            keys_configured=w.get("keys_configured", True),
            asset_count=len(w.get("assets") or []),
            total_usd=w.get("total_usd"),
            free_usd=w.get("free_usd"),
            locked_usd=w.get("locked_usd"),
            error_code=err_code,
            cache_hit=False,
            duration_ms=round(elapsed_ms, 2),
        )
    try:
        from app.observability.metrics_stubs import record_snapshot
        record_snapshot(round(elapsed_ms, 2), len(payload_bytes))
    except Exception:
        pass
    try:
        from app.observability.ram_capture import log_ram_event

        log_ram_event(
            "dashboard_snapshot",
            {
                "account_id": account_id,
                "fields": requested_fields,
                "server_ms": round(elapsed_ms, 2),
                "payload_bytes": len(payload_bytes),
                "prices_keys": len(prices) if isinstance(prices, dict) else 0,
                "bots_count": len(bots) if isinstance(bots, list) else 0,
                "trimmed_fields": trimmed_fields,
            },
            component="web",
        )
    except Exception:
        pass

    return {"ok": True, "data": data, "meta": meta}


def _map_binance_error(e: Exception):
    """Map Binance/httpx errors to HTTPException with error_code, retry_after; re-raise HTTPException."""
    if isinstance(e, HTTPException):
        raise e
    status = 502
    error_code = "BINANCE_UPSTREAM_ERROR"
    message = str(e) or "Upstream error"
    retry_after = 10
    if hasattr(e, "response") and getattr(e, "response", None):
        resp = e.response
        if getattr(resp, "status_code", None):
            sc = resp.status_code
            if sc in (401, 403):
                # 403 kullanıyoruz; HTTP 401 frontend'de oturum sonu sanılıp login'e atıyor
                status = 403
                error_code = "BINANCE_AUTH"
            elif sc in (429, 418):
                status = 429
                error_code = "BINANCE_RATE_LIMIT"
                try:
                    ra = getattr(resp, "headers", None) and resp.headers.get("Retry-After")
                    if ra is not None:
                        retry_after = int(ra) if str(ra).isdigit() else 10
                except Exception:
                    pass
            elif sc == 400:
                status = 400
                error_code = "BINANCE_BAD_REQUEST"
                try:
                    body = resp.json() if getattr(resp, "json", None) else None
                    if isinstance(body, dict) and body.get("msg"):
                        message = str(body["msg"]).strip()
                except Exception:
                    pass
            elif 500 <= sc < 600:
                error_code = "BINANCE_UPSTREAM_ERROR"
                status = 502
    detail = {"error_code": error_code, "message": message, "details": {}, "retry_after": retry_after}
    if status == 429:
        detail["retry_after"] = retry_after
    raise HTTPException(status_code=status, detail=detail)


# Fiat para birimleri: kur (rate) bilgisi bazen yanlışlıkla bakiye gibi gelirse listeden çıkar.
# 1 TRY/EUR/GBP < 1 USD olduğu için total_usd > total_qty ise formül yanlış demektir (FX contamination).
FIAT_ASSETS = {"TRY", "EUR", "GBP"}


def _resolve_asset_price_usd(asset: str, free: float, locked: float, prices: dict) -> tuple:
    """
    Returns (free_val, locked_val) in USD or (None, None) if unpriced.
    Tries: {asset}USDT, {asset}BUSD, {asset}FDUSD, {asset}USDC (quote per 1 base),
    then USDT{asset} (asset per 1 USDT -> value = amount / price).
    prices: symbol -> float (from 24h weightedAvgPrice/lastPrice).
    """
    # USDT per 1 asset (e.g. BTCUSDT -> 97000): value_usd = amount * price
    for quote in ("USDT", "BUSD", "FDUSD", "USDC"):
        raw = prices.get(f"{asset}{quote}")
        if raw is not None and float(raw) > 0:
            p = float(raw)
            return (free * p, locked * p)
    # Asset per 1 USDT (e.g. USDTTRY): value_usd = amount / price
    raw_inv = prices.get(f"USDT{asset}")
    if raw_inv is not None and float(raw_inv) > 0:
        p = float(raw_inv)
        return (free / p, locked / p)
    return (None, None)


def _wallet_response(
    account_id: int,
    balances: list,
    prices: dict,
    bot_locked: Optional[Dict[str, float]] = None,
) -> dict:
    """
    Build wallet response: assets[], total_usd, free_usd, locked_usd, bot_locked_usd, available_usd, unpriced_assets[].
    Kaynak: SADECE Binance /api/v3/account balances.
    bot_locked: per-asset qty locked by bots (virtual wallets, bileşik bakiye dahil).
    total_bot_locked_usd = bot equity (base*price + quote); harici alım/satım için available = free_usd - total_bot_locked_usd.
    """
    stable = {"USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"}
    assets = []
    unpriced_assets = []
    total_usd = 0.0
    free_usd = 0.0
    locked_usd = 0.0
    total_bot_locked_usd = 0.0
    processed_assets = set()
    for b in balances:
        asset = (b.get("asset") or "").strip()
        free = float(b.get("free") or 0)
        locked = float(b.get("locked") or 0)
        if free <= 0 and locked <= 0:
            continue
        bot_locked_qty = float((bot_locked or {}).get(asset, 0) or 0)
        if asset in stable:
            price_usd = 1.0
            free_val = free * 1.0
            locked_val = locked * 1.0
        else:
            free_val, locked_val = _resolve_asset_price_usd(asset, free, locked, prices)
            if free_val is None:
                unpriced_assets.append(asset)
                available_qty = max(0.0, free - bot_locked_qty)
                assets.append({
                    "asset": asset,
                    "free": free,
                    "locked": locked,
                    "total": free + locked,
                    "bot_locked": round(bot_locked_qty, 8),
                    "available": round(available_qty, 8),
                    "price_usd": None,
                    "value_usd": None,
                    "free_usd": None,
                    "locked_usd": None,
                    "total_usd": None,
                    "bot_locked_usd": None,
                    "available_usd": None,
                })
                continue
            total_qty = free + locked
            price_usd = (free_val + locked_val) / total_qty if total_qty > 0 else None
        total_val = free_val + locked_val
        total_qty = free + locked
        if asset in FIAT_ASSETS and total_qty > 0 and total_val > total_qty:
            continue
        processed_assets.add(asset)
        bot_locked_val = bot_locked_qty * (price_usd if price_usd is not None else 1.0)
        available_val = max(0.0, free_val - bot_locked_val)
        available_qty = max(0.0, free - bot_locked_qty)
        value_usd = round(total_val, 2)
        free_usd_rounded = round(free_val, 2)
        locked_usd_rounded = round(locked_val, 2)
        total_bot_locked_usd += bot_locked_val
        assets.append({
            "asset": asset,
            "free": free,
            "locked": locked,
            "total": total_qty,
            "bot_locked": round(bot_locked_qty, 8),
            "available": round(available_qty, 8),
            "price_usd": round(price_usd, 8) if price_usd is not None else None,
            "value_usd": value_usd,
            "free_usd": free_usd_rounded,
            "locked_usd": locked_usd_rounded,
            "total_usd": value_usd,
            "bot_locked_usd": round(bot_locked_val, 2),
            "available_usd": round(available_val, 2),
        })
        total_usd += value_usd
        free_usd += free_usd_rounded
        locked_usd += locked_usd_rounded
    for asset, qty in (bot_locked or {}).items():
        if not asset or float(qty or 0) <= 0:
            continue
        if asset in processed_assets:
            continue
        if asset in stable:
            price_usd = 1.0
            value_usd = float(qty) * price_usd
        else:
            free_val, locked_val = _resolve_asset_price_usd(asset, float(qty), 0.0, prices)
            if free_val is None:
                continue
            price_usd = free_val / float(qty) if float(qty) > 0 else None
            value_usd = free_val
        total_bot_locked_usd += value_usd
        total_usd += round(value_usd, 2)
        assets.append({
            "asset": asset,
            "free": 0.0,
            "locked": 0.0,
            "total": float(qty),
            "bot_locked": round(float(qty), 8),
            "available": 0.0,
            "price_usd": round(price_usd, 8) if price_usd is not None else None,
            "value_usd": round(value_usd, 2),
            "free_usd": 0.0,
            "locked_usd": 0.0,
            "total_usd": round(value_usd, 2),
            "bot_locked_usd": round(value_usd, 2),
            "available_usd": 0.0,
            "_synthetic": True,
        })
    available_usd = max(0.0, free_usd - total_bot_locked_usd)
    ts_iso = datetime.utcnow().isoformat() + "Z"
    ts_ms = int(time.time() * 1000)
    return {
        "account_id": account_id,
        "total_usd": round(total_usd, 2),
        "free_usd": round(free_usd, 2),
        "locked_usd": round(locked_usd, 2),
        "bot_locked_usd": round(total_bot_locked_usd, 2),
        "available_usd": round(available_usd, 2),
        "assets": assets,
        "unpriced_assets": unpriced_assets,
        "ts": ts_iso,
        "ts_ms": ts_ms,
        "data_status": "fresh",
    }


async def _fetch_wallet_uncached(account_id: int, db: Session):
    """
    Tek kaynak: Binance /api/v3/account.
    Fiyat: ticker/24hr (weightedAvgPrice > lastPrice) Binance UI'ya yakın; yoksa DataHub + ticker/price.
    Test hesabında: API key yok; 10.000 USDT paper bakiye döner (Binance uyarısı kalkar, KPI 10k gösterir).
    """
    from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
    if is_test_account(account_id, db):
        from app.services.wallet_display import build_test_account_wallet

        return build_test_account_wallet(account_id, db)
    from app.services.binance_assets import get_account_keys
    from app.services.binance_spot import get_wallet
    from app.services.wallet_pricing import build_wallet_price_map
    keys = await get_account_keys(account_id, db)
    wallet_data = await get_wallet(keys, tag="wallet_snapshot")
    balances = wallet_data.get("balances") or []
    price_map = await build_wallet_price_map(balances, testnet=keys.testnet)
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
    bot_locked = get_bot_locked_balances_for_account(db, account_id)
    out = _wallet_response(account_id, balances, price_map, bot_locked=bot_locked)
    out["keys_configured"] = True
    try:
        from app.services.binance_connectivity import note_binance_success
        note_binance_success(account_id)
    except Exception:
        pass
    return out


def _get_request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None) if hasattr(request, "state") else None


@router.get("/binance/wallet")
async def api_binance_wallet(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Binance spot cüzdan. Sözleşme: 200 + account_id, total_usd, free_usd, locked_usd, assets[], ts.
    assets[] Binance GET /api/v3/account balances'tan (total=free+locked > 0).
    TTL 2.0s + in-flight dedupe. Cache hit veya upstream 429/timeout → 200 (stale olabilir).
    Anahtar yoksa 200 + boş assets[], keys_configured=False.
    Auth: require_auth + require_account_access. 401/403 → standard JSON { error_code, message }.
    """
    require_account_access(current, account_id)
    import logging
    log = logging.getLogger(__name__)
    request_id = _get_request_id(request)
    now = time.time()

    task = None
    is_creator = False
    async with _wallet_cache_lock:
        if account_id in _wallet_response_cache:
            cached, ts = _wallet_response_cache[account_id]
            if now - ts < WALLET_RESPONSE_CACHE_TTL:
                global _wallet_cache_hits
                _wallet_cache_hits += 1
                log.info("wallet cache_hit=true upstream_call=false account_id=%s request_id=%s age_sec=%.2f", account_id, request_id, now - ts)
                log_wallet_trace(
                    event="wallet_payload_out",
                    request_id=request_id or "",
                    account_id=account_id,
                    source="binance_wallet",
                    keys_configured=cached.get("keys_configured", True),
                    asset_count=len(cached.get("assets") or []),
                    total_usd=cached.get("total_usd"),
                    free_usd=cached.get("free_usd"),
                    locked_usd=cached.get("locked_usd"),
                    cache_hit=True,
                    upstream_call=False,
                    age_sec=round(now - ts, 2),
                )
                return cached
        if account_id in _wallet_inflight:
            task = _wallet_inflight[account_id]
            log.info("wallet cache_hit=false upstream_call=false in_flight_reuse account_id=%s request_id=%s", account_id, request_id)
        else:
            global _wallet_cache_misses
            _wallet_cache_misses += 1
            task = asyncio.create_task(_fetch_wallet_uncached(account_id, db))
            _wallet_inflight[account_id] = task
            is_creator = True
            log.info("wallet cache_hit=false upstream_call=true account_id=%s request_id=%s", account_id, request_id)

    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(task, timeout=12.0)
    except Exception as e:
        if is_creator:
            async with _wallet_cache_lock:
                if account_id in _wallet_inflight and _wallet_inflight[account_id] == task:
                    del _wallet_inflight[account_id]
        if isinstance(e, ValueError):
            code = str(e)
            if code == "ACCOUNT_NOT_FOUND":
                raise HTTPException(status_code=404, detail={"error_code": code, "message": "Account not found"})
            from app.services.binance_assets import KEY_ERROR_CODES
            if code in KEY_ERROR_CODES:
                out = _wallet_response(account_id, [], {})
                out["keys_configured"] = False
                if code == "ACCOUNT_KEYS_DECRYPT_FAIL":
                    out["message"] = "API anahtarları decrypt edilemedi. MASTER_KEY veya env farklı olabilir. Anahtarı Ayarlar üzerinden yeniden kaydedin."
                    out["_error_code"] = code
                else:
                    out["message"] = "Binance API anahtarları tanımlı değil. Ayarlar üzerinden API Key ve Secret ekleyin."
                return out
            raise HTTPException(status_code=400, detail={"error_code": "ACCOUNT_ERROR", "message": code})
        # Serve stale: 429/401/400(-2015)/5xx/timeout → 200 + cache if exists, else 200 + boş/stale (UI'a 429 göndermiyoruz)
        upstream_status = getattr(getattr(e, "response", None), "status_code", None)
        invalid_key = _is_binance_invalid_key(e)
        async with _wallet_cache_lock:
            if account_id in _wallet_response_cache:
                cached, _ = _wallet_response_cache[account_id]
                stale = dict(cached)
                stale["data_status"] = "stale"
                stale["stale_reason"] = "invalid_api_key" if invalid_key else "upstream_rate_limit"
                stale["retry_after"] = 10
                if invalid_key:
                    stale["message"] = "Binance API anahtarı veya IP izni geçersiz (401/-2015). Binance hesabında API Key ve IP kısıtlamasını kontrol edin."
                try:
                    from app.services.binance_connectivity import note_binance_failure
                    err_code = "API_UNAUTHORIZED" if invalid_key else "BINANCE_UNREACHABLE"
                    note_binance_failure(
                        account_id,
                        err_code,
                        stale.get("message") or "Hesap bakiyesi alınamadı",
                        "wallet_stale",
                    )
                except Exception:
                    pass
                if invalid_key:
                    log.debug("wallet serve_stale=200 cache_hit=true upstream_failed account_id=%s reason=invalid_api_key", account_id)
                else:
                    log.debug("wallet serve_stale=200 cache_hit=true upstream_failed account_id=%s request_id=%s reason=%s error=%s", account_id, request_id, stale["stale_reason"], type(e).__name__)
                return stale
        # Cache boş + upstream hata → UI'a 429 göndermiyoruz; 200 + boş cüzdan + stale metadata
        reason = "invalid_api_key" if invalid_key else "upstream_rate_limit"
        if invalid_key:
            log.debug("wallet upstream_error reason=invalid_api_key account_id=%s (API anahtarı yok/geçersiz; manager logda gösterme)", account_id)
        elif await _should_log_upstream_error("wallet", account_id, reason):
            log.warning(
                "wallet upstream_error status=%s reason=%s source=upstream cache_empty=true account_id=%s request_id=%s error=%s (200+boş/stale dönülüyor)",
                upstream_status if upstream_status is not None else "?",
                reason,
                account_id, request_id, type(e).__name__,
            )
        else:
            log.debug("wallet upstream_error throttled account_id=%s reason=%s", account_id, reason)
        out = _wallet_response(account_id, [], {})
        out["keys_configured"] = True
        out["data_status"] = "stale"
        out["stale_reason"] = "invalid_api_key" if invalid_key else "upstream_rate_limit"
        out["retry_after"] = 10
        out["request_id"] = request_id
        out["message"] = (
            "Binance API anahtarı veya IP izni geçersiz (401/-2015). Binance hesabında API Key ve IP kısıtlamasını kontrol edin."
            if invalid_key
            else "Upstream geçici hata; veri boş veya güncel değil. Kısa süre sonra tekrar denenecek."
        )
        try:
            from app.services.binance_connectivity import note_binance_failure
            err_code = "API_UNAUTHORIZED" if invalid_key else "BINANCE_UNREACHABLE"
            note_binance_failure(account_id, err_code, out["message"], "wallet")
        except Exception:
            pass
        return out

    if is_creator:
        latency_ms = (time.perf_counter() - t0) * 1000
        async with _wallet_cache_lock:
            _wallet_response_cache[account_id] = (out, time.time())
            _wallet_total_cache[account_id] = (out.get("total_usd") or 0, time.time())
            _dashboard_summary_cache.pop(account_id, None)  # next /dashboard/summary sees fresh wallet
            if len(_wallet_response_cache) > _WALLET_CACHE_MAX_KEYS:
                oldest = min(_wallet_response_cache.items(), key=lambda x: x[1][1])
                aid = oldest[0]
                _wallet_response_cache.pop(aid, None)
                _wallet_total_cache.pop(aid, None)
            if account_id in _wallet_inflight and _wallet_inflight[account_id] == task:
                del _wallet_inflight[account_id]
        log_wallet_trace(
            event="wallet_payload_out",
            request_id=request_id or "",
            account_id=account_id,
            source="binance_wallet",
            keys_configured=out.get("keys_configured", True),
            asset_count=len(out.get("assets") or []),
            total_usd=out.get("total_usd"),
            free_usd=out.get("free_usd"),
            locked_usd=out.get("locked_usd"),
            cache_hit=False,
            upstream_call=True,
            duration_ms=round(latency_ms, 2),
        )
        log.info(
            "wallet cache_hit=false upstream_call=true upstream_ok account_id=%s latency_ms=%.0f request_id=%s total_usd=%s",
            account_id, latency_ms, request_id, out.get("total_usd"),
        )
        try:
            from app.services.binance_connectivity import note_binance_success
            note_binance_success(account_id)
        except Exception:
            pass
    return out


@router.get("/debug/wallet/diag")
async def api_debug_wallet_diag(
    request: Request,
    account_id: int = Query(..., description="Account ID to diagnose"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    One-shot diagnostic: keys, last snapshot, in-memory cache, live fetch (3s timeout).
    Auth: same user or admin. Returns full diag for root-cause analysis.
    """
    require_account_access(current, account_id)
    request_id = _get_request_id(request)
    active_account_id = current.get("account_id")
    result: Dict[str, Any] = {
        "request_id": request_id,
        "account_id_requested": account_id,
        "active_account_id_from_auth": active_account_id,
        "resolved_account_id": account_id,
        "keys_configured": False,
        "key_len": None,
        "secret_len": None,
        "decrypt_ok": None,
        "last_error_code": None,
        "last_snapshot_at": None,
        "snapshot_total_usd": None,
        "snapshot_asset_count": None,
        "wallet_cache_age_sec": None,
        "wallet_cache_total_usd": None,
        "wallet_cache_asset_count": None,
        "live_fetch": None,
    }
    from app.db.models import AssetSnapshot
    from app.services.binance_assets import get_account_keys
    acc = db.query(Account).filter(Account.id == account_id).first()
    if acc:
        ek = getattr(acc, "api_key_enc", None)
        es = getattr(acc, "api_secret_enc", None)
        result["key_len"] = len(ek or "")
        result["secret_len"] = len(es or "")
        result["keys_configured"] = bool(
            result["key_len"] > 0 and result["secret_len"] > 0
            and (not isinstance(ek, str) or ek.strip())
            and (not isinstance(es, str) or es.strip())
        )
        if result["keys_configured"]:
            try:
                keys = await get_account_keys(account_id, db)
                result["decrypt_ok"] = bool(keys and keys.get("api_key") and keys.get("api_secret"))
            except Exception as e:
                result["decrypt_ok"] = False
                result["decrypt_error"] = str(e)[:200]
                result["last_error_code"] = str(e) if isinstance(e, ValueError) else type(e).__name__
    row = db.query(AssetSnapshot).filter(AssetSnapshot.account_id == account_id).order_by(desc(AssetSnapshot.timestamp)).limit(1).first()
    if row:
        result["last_snapshot_at"] = row.timestamp.isoformat().replace("+00:00", "Z") if row.timestamp.tzinfo else str(row.timestamp)
        result["snapshot_total_usd"] = row.total_usd_value
        try:
            bd = json.loads(row.breakdown_json or "{}")
            result["snapshot_asset_count"] = sum(
                1 for v in (bd or {}).values()
                if isinstance(v, dict) and ((float(v.get("free") or 0) + float(v.get("locked") or 0)) > 0)
            )
        except Exception:
            result["snapshot_asset_count"] = None
    now = time.time()
    async with _wallet_cache_lock:
        if account_id in _wallet_response_cache:
            cached, ts = _wallet_response_cache[account_id]
            result["wallet_cache_age_sec"] = round(now - ts, 2)
            result["wallet_cache_total_usd"] = cached.get("total_usd")
            result["wallet_cache_asset_count"] = len(cached.get("assets") or [])
    try:
        live = await asyncio.wait_for(_fetch_wallet_uncached(account_id, db), timeout=3.0)
        if isinstance(live, dict) and live.get("_error"):
            ec = live.get("code") or live.get("_error_code")
            if ec and result.get("last_error_code") is None:
                result["last_error_code"] = ec
            result["live_fetch"] = {"ok": False, "error": str(live.get("_error", ""))[:200], "error_code": ec}
        else:
            result["live_fetch"] = {
                "ok": True,
                "total_usd": live.get("total_usd") if isinstance(live, dict) else None,
                "asset_count": len(live.get("assets") or []) if isinstance(live, dict) else 0,
            }
    except asyncio.TimeoutError:
        result["live_fetch"] = {"ok": False, "error": "timeout", "error_code": "TIMEOUT"}
    except Exception as e:
        result["live_fetch"] = {"ok": False, "error": str(e)[:200], "error_code": type(e).__name__}
    return {"ok": True, "data": result}


def _open_orders_response(account_id: int, orders: list, keys_configured: bool = True) -> dict:
    return {"account_id": account_id, "orders": orders, "count": len(orders), "keys_configured": keys_configured}


async def _fetch_open_orders_uncached(account_id: int, symbol: Optional[str], db: Session) -> dict:
    from app.services.test_account import is_test_account
    if is_test_account(account_id, db):
        return _open_orders_response(account_id, [], True)
    from app.services.binance_assets import get_account_keys
    from app.services.binance_spot import get_open_orders
    keys = await get_account_keys(account_id, db)
    orders = await get_open_orders(keys, symbol)
    return _open_orders_response(account_id, orders, True)


@router.get("/binance/open-orders")
async def api_binance_open_orders(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    symbol: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Binance açık emirler: TTL 2s + in-flight dedupe; 429 → serve stale. Anahtar yoksa 200 + boş liste."""
    import logging
    log = logging.getLogger(__name__)
    request_id = _get_request_id(request)
    now = time.time()
    cache_key = (account_id, (symbol or "").strip())

    task = None
    is_creator = False
    async with _open_orders_cache_lock:
        if cache_key in _open_orders_cache:
            cached, ts = _open_orders_cache[cache_key]
            if now - ts < OPEN_ORDERS_CACHE_TTL:
                global _open_orders_cache_hits
                _open_orders_cache_hits += 1
                log.debug("open_orders cache_hit=true upstream_call=false account_id=%s request_id=%s", account_id, request_id)
                return cached
        if cache_key in _open_orders_inflight:
            task = _open_orders_inflight[cache_key]
            log.debug("open_orders cache_hit=false upstream_call=false in_flight_reuse account_id=%s request_id=%s", account_id, request_id)
        else:
            global _open_orders_cache_misses
            _open_orders_cache_misses += 1
            task = asyncio.create_task(_fetch_open_orders_uncached(account_id, symbol or None, db))
            _open_orders_inflight[cache_key] = task
            is_creator = True
            log.debug("open_orders cache_hit=false upstream_call=true account_id=%s request_id=%s", account_id, request_id)

    try:
        out = await asyncio.wait_for(task, timeout=12.0)
    except ValueError as e:
        if is_creator:
            async with _open_orders_cache_lock:
                if cache_key in _open_orders_inflight and _open_orders_inflight[cache_key] == task:
                    del _open_orders_inflight[cache_key]
        code = str(e)
        if code == "ACCOUNT_NOT_FOUND":
            raise HTTPException(status_code=404, detail={"error_code": code, "message": "Account not found"})
        from app.services.binance_assets import KEY_ERROR_CODES
        if code in KEY_ERROR_CODES:
            return _open_orders_response(account_id, [], False)
        raise HTTPException(status_code=400, detail={"error_code": "ACCOUNT_ERROR", "message": code})
    except Exception as e:
        if is_creator:
            async with _open_orders_cache_lock:
                if cache_key in _open_orders_inflight and _open_orders_inflight[cache_key] == task:
                    del _open_orders_inflight[cache_key]
        upstream_status = getattr(getattr(e, "response", None), "status_code", None)
        invalid_key = _is_binance_invalid_key(e)
        async with _open_orders_cache_lock:
            if cache_key in _open_orders_cache:
                cached, _ = _open_orders_cache[cache_key]
                stale = dict(cached)
                stale["data_status"] = "stale"
                stale["stale_reason"] = "invalid_api_key" if invalid_key else "upstream_rate_limit"
                stale["retry_after"] = 10
                if invalid_key:
                    stale["message"] = "Binance API anahtarı veya IP izni geçersiz (401/-2015). Binance hesabında API Key ve IP kısıtlamasını kontrol edin."
                if invalid_key:
                    log.debug("open_orders serve_stale=200 cache_hit=true upstream_failed account_id=%s reason=invalid_api_key", account_id)
                else:
                    log.debug("open_orders serve_stale=200 cache_hit=true upstream_failed account_id=%s request_id=%s reason=%s error=%s", account_id, request_id, stale["stale_reason"], type(e).__name__)
                return stale
        # Cache boş + upstream hata → UI'a 429 göndermiyoruz; 200 + boş liste + stale metadata
        reason = "invalid_api_key" if invalid_key else "upstream_rate_limit"
        if invalid_key:
            log.debug("open_orders upstream_error reason=invalid_api_key account_id=%s (API anahtarı yok/geçersiz; manager logda gösterme)", account_id)
        elif await _should_log_upstream_error("open_orders", account_id, reason):
            log.warning(
                "open_orders upstream_error status=%s reason=%s source=upstream cache_empty=true account_id=%s request_id=%s error=%s (200+boş/stale dönülüyor)",
                upstream_status if upstream_status is not None else "?",
                reason,
                account_id, request_id, type(e).__name__,
            )
        else:
            log.debug("open_orders upstream_error throttled account_id=%s reason=%s", account_id, reason)
        out = _open_orders_response(account_id, [], True)
        out["data_status"] = "stale"
        out["stale_reason"] = "invalid_api_key" if invalid_key else "upstream_rate_limit"
        out["retry_after"] = 10
        out["request_id"] = request_id
        out["message"] = (
            "Binance API anahtarı veya IP izni geçersiz (401/-2015). Binance hesabında API Key ve IP kısıtlamasını kontrol edin."
            if invalid_key
            else "Upstream geçici hata; veri boş veya güncel değil. Kısa süre sonra tekrar denenecek."
        )
        return out

    if is_creator:
        async with _open_orders_cache_lock:
            _open_orders_cache[cache_key] = (out, time.time())
            if len(_open_orders_cache) > _OPEN_ORDERS_CACHE_MAX_KEYS:
                oldest_key = min(_open_orders_cache.items(), key=lambda x: x[1][1])[0]
                _open_orders_cache.pop(oldest_key, None)
            if cache_key in _open_orders_inflight and _open_orders_inflight[cache_key] == task:
                del _open_orders_inflight[cache_key]
    return out


class OrderRequest(BaseModel):
    account_id: int
    symbol: str
    side: str  # BUY or SELL
    type: str  # MARKET or LIMIT
    quantity: Optional[float] = None
    quote_order_qty: Optional[float] = None
    price: Optional[float] = None
    time_in_force: str = "GTC"


@router.post("/binance/order")
async def place_binance_order(order: OrderRequest, request: Request, db: Session = Depends(get_db)):
    """Binance spot emir: signed POST /api/v3/order. Worker-only: web returns 403 WORKER_ONLY_OPERATION."""
    try:
        from app.core.errors import AppError
        from app.services.binance_assets import get_account_keys
        from app.services.binance_spot import place_order as binance_place_order
        keys = await get_account_keys(order.account_id, db)
        payload = {
            "symbol": (order.symbol or "").upper(),
            "side": (order.side or "BUY").upper(),
            "type": (order.type or "MARKET").upper(),
            "timeInForce": order.time_in_force or "GTC",
        }
        if order.quantity is not None:
            payload["quantity"] = str(order.quantity)
        if order.quote_order_qty is not None:
            payload["quoteOrderQty"] = str(order.quote_order_qty)
        if order.price is not None:
            payload["price"] = str(order.price)
        result = await binance_place_order(keys, payload)
        return result
    except AppError:
        raise
    except ValueError as e:
        code = str(e)
        if code == "ACCOUNT_NOT_FOUND":
            raise HTTPException(status_code=404, detail={"error_code": code, "message": "Account not found"})
        from app.services.binance_assets import KEY_ERROR_CODES
        if code in KEY_ERROR_CODES:
            raise HTTPException(status_code=400, detail={"error_code": code, "message": "Binance API anahtarları bu hesap için tanımlı değil veya geçersiz. Ayarlar üzerinden API Key ve Secret ekleyin."})
        raise HTTPException(status_code=400, detail={"error_code": "ACCOUNT_ERROR", "message": code})
    except Exception as e:
        _map_binance_error(e)


@router.delete("/binance/order")
async def cancel_binance_order(
    account_id: int = Query(...),
    symbol: str = Query(...),
    order_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """Binance emir iptali: DELETE /api/v3/order."""
    try:
        from app.services.binance_assets import get_account_keys
        from app.services.binance_spot import cancel_order
        keys = await get_account_keys(account_id, db)
        result = await cancel_order(keys, symbol, order_id)
        return {
            "success": True,
            "status": result.get("status", "CANCELED"),
            "symbol": result.get("symbol", symbol),
            "orderId": result.get("orderId", order_id),
            "message": "Emir iptal edildi",
        }
    except ValueError as e:
        code = str(e)
        if code == "ACCOUNT_NOT_FOUND":
            raise HTTPException(status_code=404, detail={"error_code": code, "message": "Account not found"})
        from app.services.binance_assets import KEY_ERROR_CODES
        if code in KEY_ERROR_CODES:
            raise HTTPException(
                status_code=400,
                detail={"error_code": code, "message": "Binance API anahtarları tanımlı değil. Ayarlardan API Key ve Secret ekleyin."}
            )
        raise HTTPException(status_code=400, detail={"error_code": "ACCOUNT_ERROR", "message": code})
    except Exception as e:
        _map_binance_error(e)


@router.get("/binance/fee-rates")
async def get_binance_fee_rates(account_id: int = Query(...), db: Session = Depends(get_db)):
    """Binance kaldırıldı – varsayılan fee"""
    return {"fee_rates": {"taker": 0.001, "maker": 0.001, "taker_pct": 0.1, "maker_pct": 0.1}}


@router.get("/binance/order-history")
async def get_binance_order_history(
    account_id: int = Query(...),
    symbol: Optional[str] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """Binance kaldırıldı – boş emir/trade listesi"""
    return {"account_id": account_id, "orders": [], "trades": [], "orders_count": 0, "trades_count": 0}


@router.get("/binance/coin-list")
async def get_binance_coin_list(limit: int = Query(100), db: Session = Depends(get_db)):
    """Binance kaldırıldı – boş coin listesi"""
    return {"coins": [], "count": 0, "limit": limit}


# ============================================================
# PERFORMANCE HOTFIX: Backend Cache for Modal Bootstrap
# ============================================================
# In-memory cache for modal data (capped for RAM stability)
_modal_cache = {
    "prices": {},      # symbol -> {price, ts}
    "balances": {},    # account_id -> {data, ts}
    "filters": {},     # symbol -> {data, ts}
}
CACHE_TTL_PRICE = 2      # 2 seconds
CACHE_TTL_BALANCE = 3   # 3 seconds
CACHE_TTL_FILTER = 6 * 60 * 60  # 6 hours
_MODAL_CACHE_MAX_PRICES = 200
_MODAL_CACHE_MAX_BALANCES = 40
_MODAL_CACHE_MAX_FILTERS = 120

def _get_cached_price(symbol: str) -> Optional[float]:
    """Get cached price if fresh"""
    entry = _modal_cache["prices"].get(symbol)
    if not entry:
        return None
    age = time.time() - entry["ts"]
    if age > CACHE_TTL_PRICE:
        del _modal_cache["prices"][symbol]
        return None
    return entry["price"]

def _set_cached_price(symbol: str, price: float):
    """Cache price (max entries to limit RAM)."""
    _modal_cache["prices"][symbol] = {"price": price, "ts": time.time()}
    if len(_modal_cache["prices"]) > _MODAL_CACHE_MAX_PRICES:
        oldest = min(_modal_cache["prices"].items(), key=lambda x: x[1]["ts"])
        del _modal_cache["prices"][oldest[0]]

def _get_cached_balance(account_id: int) -> Optional[Dict]:
    """Get cached balance if fresh"""
    entry = _modal_cache["balances"].get(account_id)
    if not entry:
        return None
    age = time.time() - entry["ts"]
    if age > CACHE_TTL_BALANCE:
        del _modal_cache["balances"][account_id]
        return None
    return entry["data"]

def _set_cached_balance(account_id: int, data: Dict):
    """Cache balance (max entries to limit RAM)."""
    _modal_cache["balances"][account_id] = {"data": data, "ts": time.time()}
    if len(_modal_cache["balances"]) > _MODAL_CACHE_MAX_BALANCES:
        oldest = min(_modal_cache["balances"].items(), key=lambda x: x[1]["ts"])
        del _modal_cache["balances"][oldest[0]]

def _get_cached_filters(symbol: str) -> Optional[Dict]:
    """Get cached filters if fresh"""
    entry = _modal_cache["filters"].get(symbol)
    if not entry:
        return None
    age = time.time() - entry["ts"]
    if age > CACHE_TTL_FILTER:
        del _modal_cache["filters"][symbol]
        return None
    return entry["data"]

def _set_cached_filters(symbol: str, data: Dict):
    """Cache filters (max entries to limit RAM)."""
    _modal_cache["filters"][symbol] = {"data": data, "ts": time.time()}
    if len(_modal_cache["filters"]) > _MODAL_CACHE_MAX_FILTERS:
        oldest = min(_modal_cache["filters"].items(), key=lambda x: x[1]["ts"])
        del _modal_cache["filters"][oldest[0]]

@router.get("/binance/spot_modal_bootstrap")
async def get_spot_modal_bootstrap(
    account_id: int = Query(...),
    symbol: str = Query(...),
    db: Session = Depends(get_db)
):
    """Binance kaldırıldı – minimal bootstrap (price 0, boş bakiye)"""
    s = symbol.strip().upper()
    base = s.replace("USDT", "").replace("BTC", "").replace("ETH", "") or "BTC"
    return {
        "symbol": s,
        "price": 0.0,
        "filters": {"tickSize": "0.01", "stepSize": "0.00001", "minNotional": "5", "baseAsset": base, "quoteAsset": "USDT"},
        "balances": {"baseFree": 0.0, "quoteFree": 0.0, "base": base, "quote": "USDT"},
        "ts": time.time()
    }
