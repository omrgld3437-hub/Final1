"""
FILE: admin.py
VERSION: v4
DATE: 2026-01-22
CHANGE: Fix delete_admin_account - handle missing financial_portfolios table gracefully
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import func, desc, or_
from pydantic import BaseModel
import os
import random

from app.db.session import get_db
from app.db.models import Account, Bot, Trade, PnlSnapshot, User, PasswordResetRequest, AssetSnapshot, ErrorLog, AdminPopup, AdminPopupDismissal
from app.services.encryption import encrypt_text
from app.api.auth import hash_password, generate_password, require_auth, verify_password
from app.services.pnl_service import PnlService
from app.utils.account_code import generate_account_code
import uuid
import logging
import asyncio
import time
import json

logger = logging.getLogger(__name__)

# Admin spot balance 401/API error log throttle: hesap basina en fazla 5 dkda bir
_admin_spot_balance_error_ts: Dict[int, float] = {}
_admin_spot_balance_error_lock: Optional[asyncio.Lock] = None
_ADMIN_SPOT_ERROR_THROTTLE_SEC = 300.0
_ADMIN_ACCOUNTS_LIVE_CONCURRENCY = max(1, int(os.getenv("ADMIN_ACCOUNTS_LIVE_CONCURRENCY", "4")))
_ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC = max(0.0, float(os.getenv("ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC", "15")))
_admin_accounts_full_cache: Dict[str, tuple] = {}
_admin_accounts_full_cache_lock: Optional[asyncio.Lock] = None


def _get_admin_accounts_full_cache_lock() -> asyncio.Lock:
    global _admin_accounts_full_cache_lock
    if _admin_accounts_full_cache_lock is None:
        _admin_accounts_full_cache_lock = asyncio.Lock()
    return _admin_accounts_full_cache_lock


def _get_admin_spot_balance_error_lock() -> asyncio.Lock:
    global _admin_spot_balance_error_lock
    if _admin_spot_balance_error_lock is None:
        _admin_spot_balance_error_lock = asyncio.Lock()
    return _admin_spot_balance_error_lock


async def _get_account_wallet_strip_kpis(account_id: int, db: Session) -> tuple:
    """
    Dashboard Binance strip ile aynı kaynak: total_usd + bot_locked_usd (/api/binance/wallet).
    Returns (total_usd, bot_locked_usd, status). status: ok | no_keys | error.
    """
    try:
        from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
        from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
        from app.services.binance_assets import get_account_keys, KEY_ERROR_CODES, ACCOUNT_NOT_FOUND
        from app.services.binance_spot import get_wallet
        from app.services.wallet_pricing import build_wallet_price_map
        from app.api.routes import _wallet_response

        bot_locked_map = get_bot_locked_balances_for_account(db, account_id) or {}

        if is_test_account(account_id, db):
            from app.services.test_account_kpi import compute_test_account_dashboard_spot_kpi_async

            kpi = await compute_test_account_dashboard_spot_kpi_async(account_id, db)
            return (
                float(kpi.get("spot_strip_total_usd") or 0.0),
                float(kpi.get("bot_locked_usd") or 0.0),
                "ok",
            )

        keys = await get_account_keys(account_id, db)
        wallet_data = await get_wallet(keys, tag="admin_spot_balance")
        balances = wallet_data.get("balances") or []
        price_map = await build_wallet_price_map(balances, testnet=keys.testnet)
        resp = _wallet_response(account_id, balances, price_map, bot_locked=bot_locked_map)
        return (
            float(resp.get("total_usd") or 0.0),
            float(resp.get("bot_locked_usd") or 0.0),
            "ok",
        )
    except ValueError as e:
        msg = str(e).upper()
        if ACCOUNT_NOT_FOUND in msg or any(c in msg for c in KEY_ERROR_CODES):
            logger.info("[Admin] spot balance account_id=%s: %s", account_id, msg)
            return (0.0, 0.0, "no_keys")
        return (0.0, 0.0, "error")
    except Exception as e:
        now = time.time()
        async with _get_admin_spot_balance_error_lock():
            last = _admin_spot_balance_error_ts.get(account_id)
            if last is None or (now - last) >= _ADMIN_SPOT_ERROR_THROTTLE_SEC:
                _admin_spot_balance_error_ts[account_id] = now
                logger.debug(
                    "[Admin] spot balance account_id=%s error: %s (API anahtari gecersiz/izin yok olabilir)",
                    account_id, e,
                )
    return (0.0, 0.0, "error")


async def _get_spot_balance_for_account(account_id: int, db: Session) -> tuple:
    """Fetch Binance wallet total_usd. Returns (total_usd, status)."""
    total, _bot_locked, status = await _get_account_wallet_strip_kpis(account_id, db)
    return (total, status)


def _get_lite_wallet_kpis(account_id: int, db: Session) -> tuple:
    """Cached spot (AssetSnapshot) + bot locked USDT only — no live Binance."""
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account

    bot_locked_map = get_bot_locked_balances_for_account(db, account_id) or {}
    bots_balance = float(bot_locked_map.get("USDT") or 0.0)
    last_snap = (
        db.query(AssetSnapshot)
        .filter(AssetSnapshot.account_id == account_id)
        .order_by(desc(AssetSnapshot.timestamp))
        .first()
    )
    if last_snap and getattr(last_snap, "total_usd_value", None) is not None:
        return (float(last_snap.total_usd_value), bots_balance, "cached")
    return (0.0, bots_balance, "pending")


async def _admin_fetch_live_row_kpis(account_id: int, acct_is_test: bool) -> Dict[str, Any]:
    """Live wallet + bot KPI for one account (isolated DB session, safe for parallel gather)."""
    from app.db.session import SessionLocal

    t0 = time.perf_counter()
    db = SessionLocal()
    test_spot_kpi = None
    spot_balance = 0.0
    bot_locked_usd = 0.0
    spot_balance_status = "error"
    bot_raw: Dict[str, Any] = {}
    try:
        if acct_is_test:
            from app.services.test_account_kpi import compute_test_account_dashboard_spot_kpi_async

            test_spot_kpi = await compute_test_account_dashboard_spot_kpi_async(account_id, db)
            spot_balance = float(test_spot_kpi.get("spot_strip_total_usd") or 0.0)
            bot_locked_usd = float(test_spot_kpi.get("bot_locked_usd") or 0.0)
            spot_balance_status = "ok"
        else:
            spot_balance, bot_locked_usd, spot_balance_status = await _get_account_wallet_strip_kpis(
                account_id, db
            )
        from app.services.dashboard_snapshot import fetch_bots_and_account_kpis

        bot_raw = await fetch_bots_and_account_kpis(account_id, db)
    finally:
        db.close()
    wallet_ms = (time.perf_counter() - t0) * 1000.0
    bot_kpi_error = None
    if bot_raw.get("_error"):
        bot_kpi_error = str(bot_raw.get("_error"))[:300]
    return {
        "spot_balance": spot_balance,
        "bot_locked_usd": bot_locked_usd,
        "spot_balance_status": spot_balance_status,
        "test_spot_kpi": test_spot_kpi,
        "bot_raw": bot_raw,
        "wallet_ms": wallet_ms,
        "wallet_error": spot_balance_status == "error",
        "bot_kpi_error": bot_kpi_error,
    }


async def _admin_fetch_live_rows_parallel(
    account_ids: List[int],
    test_account_ids: set,
) -> Dict[int, Dict[str, Any]]:
    if not account_ids:
        return {}
    sem = asyncio.Semaphore(_ADMIN_ACCOUNTS_LIVE_CONCURRENCY)

    async def _one(aid: int) -> tuple:
        async with sem:
            data = await _admin_fetch_live_row_kpis(aid, aid in test_account_ids)
            return aid, data

    out: Dict[int, Dict[str, Any]] = {}
    results = await asyncio.gather(*[_one(aid) for aid in account_ids], return_exceptions=True)
    for item in results:
        if isinstance(item, Exception):
            logger.warning("[Admin] parallel live row failed: %s", item)
            continue
        aid, data = item
        out[aid] = data
    return out


router = APIRouter()


class AccountCreateRequest(BaseModel):
    name: str
    phone: str = ""
    exchange: str = "BINANCE"


class DismissPasswordResetRequest(BaseModel):
    request_id: int


class ServerExitRequest(BaseModel):
    password: str


class CreatePopupRequest(BaseModel):
    target: str  # first_login | normal_user
    title_key: str  # info | warning | success | maintenance | announcement
    message: str
    valid_until: str  # ISO datetime
    max_shows_per_user: Optional[int] = 1  # 1 = tek seferlik, 2+ = o kadar kere goster


def _require_admin(current: dict = Depends(require_auth)) -> dict:
    """Sadece admin kullanıcı; aksi halde 403. Tüm admin route'larında kullanılır."""
    if not current.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
    return current


@router.get("/admin/accounts")
async def get_admin_accounts(
    request: Request,
    current: dict = Depends(_require_admin),
    suspended: bool = False,
    lite: bool = Query(False, description="Skip live Binance/bot KPI; use cached snapshot for faster list"),
    db: Session = Depends(get_db)
) -> Dict:
    """Get all accounts with metrics for admin panel

    Args:
        suspended: If True, only return accounts with suspended users
        lite: If True, skip live Binance wallet and bot KPI fetches (cached snapshot only)
    """
    t0 = time.perf_counter()
    request_id = getattr(getattr(request, "state", None), "request_id", None) or (
        request.headers.get("X-Request-ID") or request.headers.get("X-Request-Id") or ""
    )
    admin_user_id = current.get("user_id")
    cache_key = f"{admin_user_id}:{int(bool(suspended))}:{int(bool(lite))}"
    if not lite and _ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC > 0:
        now_cache = time.time()
        async with _get_admin_accounts_full_cache_lock():
            cached = _admin_accounts_full_cache.get(cache_key)
            if cached and (now_cache - cached[0]) < _ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC:
                return cached[1]
    wallet_errors: List[int] = []
    bot_kpi_errors: List[Dict] = []
    slow_wallets: List[Dict] = []
    row_errors: List[Dict] = []

    try:
        if suspended:
            accounts = db.query(Account).join(User, Account.user_id == User.id).filter(
                User.is_suspended == True,
                or_(User.is_deleted == False, User.is_deleted.is_(None))
            ).all()
        else:
            accounts = db.query(Account).outerjoin(User, Account.user_id == User.id).filter(
                or_(
                    User.is_suspended == False,
                    User.is_suspended.is_(None),
                    Account.user_id.is_(None)
                )
            ).all()
    except Exception as e:
        logger.error(
            "[Admin] Error querying accounts: %s request_id=%s",
            e, request_id, exc_info=True,
        )
        return {
            "accounts": [],
            "totals": {
                "total_accounts": 0,
                "total_active_bots": 0,
                "total_bots_balance_usd": 0.0,
                "total_spot_balance_usd": 0.0,
            },
            "lite": lite,
        }

    accounts_list: List[Dict] = []
    total_active_bots = 0
    total_bots_balance_usd = 0.0
    total_spot_balance_usd = 0.0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    from app.services.test_account import is_test_account

    work_accounts = [
        a for a in accounts
        if not (admin_user_id is not None and a.user_id == admin_user_id)
    ]
    work_account_ids = [a.id for a in work_accounts]
    bots_by_account: Dict[int, List] = {aid: [] for aid in work_account_ids}
    if work_account_ids:
        for bot in db.query(Bot).filter(Bot.account_id.in_(work_account_ids)).all():
            bots_by_account.setdefault(bot.account_id, []).append(bot)

    test_account_ids = {a.id for a in work_accounts if is_test_account(a.id, db)}

    live_by_account: Dict[int, Dict[str, Any]] = {}
    if not lite and work_account_ids:
        live_by_account = await _admin_fetch_live_rows_parallel(work_account_ids, test_account_ids)
        for aid, live in live_by_account.items():
            if live.get("wallet_error"):
                wallet_errors.append(aid)
            if live.get("wallet_ms", 0) >= 2500:
                slow_wallets.append({"account_id": aid, "wallet_ms": round(live["wallet_ms"])})
            if live.get("bot_kpi_error"):
                bot_kpi_errors.append({"account_id": aid, "error": live["bot_kpi_error"]})

    for account in work_accounts:
        try:
            bots = bots_by_account.get(account.id, [])
            from app.services.bot_status_utils import count_admin_active_bots

            active_bots_count = count_admin_active_bots(bots)

            acct_is_test = account.id in test_account_ids
            test_spot_kpi = None
            if acct_is_test and lite:
                from app.services.test_account_kpi import compute_test_account_dashboard_spot_kpi_async

                test_spot_kpi = await compute_test_account_dashboard_spot_kpi_async(account.id, db)
                spot_balance = float(test_spot_kpi.get("spot_strip_total_usd") or 0.0)
                bot_locked_usd = float(test_spot_kpi.get("bot_locked_usd") or 0.0)
                spot_balance_status = "ok"
            elif lite:
                spot_balance, bot_locked_usd, spot_balance_status = _get_lite_wallet_kpis(account.id, db)
            else:
                live = live_by_account.get(account.id) or {}
                test_spot_kpi = live.get("test_spot_kpi")
                spot_balance = float(live.get("spot_balance") or 0.0)
                bot_locked_usd = float(live.get("bot_locked_usd") or 0.0)
                spot_balance_status = live.get("spot_balance_status") or "error"

            bots_balance = float(bot_locked_usd or 0.0)

            daily_pnl_usd = 0.0
            daily_pnl_pct = 0.0
            if not lite:
                bot_raw = (live_by_account.get(account.id) or {}).get("bot_raw") or {}
                try:
                    if not bot_raw.get("_error"):
                        bots_array = bot_raw.get("bots") or []
                        kpi_active = count_admin_active_bots(bots_array)
                        if kpi_active > active_bots_count:
                            active_bots_count = kpi_active
                        daily_pnl_usd = float(bot_raw.get("daily_bot_pnl_usd_kpi") or 0)
                        ak = bot_raw.get("account") or {}
                        if ak.get("daily_bot_pnl_usd") is not None:
                            daily_pnl_usd = float(ak.get("daily_bot_pnl_usd") or 0)
                        daily_sum = sum(float(b.get("daily_pnl_usd") or 0) for b in bots_array)
                        if abs(daily_sum) > 1e-6:
                            daily_pnl_usd = daily_sum
                        ref_sum = 0.0
                        for b in bots_array:
                            d_usd = float(b.get("daily_pnl_usd") or 0)
                            d_pct = float(b.get("daily_pnl_pct") or 0)
                            if abs(d_pct) > 1e-6:
                                ref_sum += d_usd / (d_pct / 100.0)
                        if ref_sum > 1e-9:
                            daily_pnl_pct = daily_pnl_usd / ref_sum * 100.0
                        elif bots_balance > abs(daily_pnl_usd) + 1e-6:
                            ref_open = bots_balance - daily_pnl_usd
                            daily_pnl_pct = (daily_pnl_usd / ref_open * 100.0) if ref_open > 1e-9 else 0.0
                except Exception as bot_kpi_ex:
                    bot_kpi_errors.append({"account_id": account.id, "error": str(bot_kpi_ex)[:300]})
                    logger.warning(
                        "[Admin] bot KPI merge account_id=%s request_id=%s: %s",
                        account.id, request_id, bot_kpi_ex,
                    )

            total_active_bots += active_bots_count
            total_bots_balance_usd += bots_balance
            total_spot_balance_usd += spot_balance
            total_usd = bots_balance + spot_balance

            daily_wallet_pnl_usd = None
            daily_wallet_pnl_pct = None
            if acct_is_test and test_spot_kpi:
                daily_wallet_pnl_usd = float(test_spot_kpi.get("daily_wallet_pnl_usd") or 0.0)
                daily_wallet_pnl_pct = float(test_spot_kpi.get("daily_wallet_pnl_pct") or 0.0)
            else:
                try:
                    last_before_today = db.query(AssetSnapshot).filter(
                        AssetSnapshot.account_id == account.id,
                        AssetSnapshot.timestamp < today_start
                    ).order_by(desc(AssetSnapshot.timestamp)).first()
                    if last_before_today and getattr(last_before_today, "total_usd_value", None) is not None:
                        ref_cuzdan = float(last_before_today.total_usd_value)
                        daily_wallet_pnl_usd = spot_balance - ref_cuzdan
                        daily_wallet_pnl_pct = (daily_wallet_pnl_usd / ref_cuzdan * 100.0) if ref_cuzdan and ref_cuzdan > 0 else 0.0
                    else:
                        first_today = db.query(AssetSnapshot).filter(
                            AssetSnapshot.account_id == account.id,
                            AssetSnapshot.timestamp >= today_start
                        ).order_by(AssetSnapshot.timestamp.asc()).first()
                        if first_today and getattr(first_today, "total_usd_value", None) is not None:
                            ref_cuzdan = float(first_today.total_usd_value)
                            daily_wallet_pnl_usd = spot_balance - ref_cuzdan
                            daily_wallet_pnl_pct = (daily_wallet_pnl_usd / ref_cuzdan * 100.0) if ref_cuzdan and ref_cuzdan > 0 else 0.0
                except Exception:
                    pass

            user_login_info = None
            user_logout_info = None
            user_username = None
            user_is_suspended = None
            user_id = None
            user_last_login_ip = None
            user_is_online = False
            user_phone = None
            user_created_at = None
            user_name = None
            user_surname = None
            if account.user_id:
                user = db.query(User).filter(User.id == account.user_id).first()
                if user:
                    user_last_login_ip = getattr(user, 'last_login_ip', None) or None
                    user_phone = user.phone
                    user_created_at = user.created_at.isoformat() if user.created_at else None
                    user_name = user.name
                    user_surname = user.surname
                    user_username = user.username
                    if getattr(user, 'last_activity_at', None):
                        cutoff = datetime.utcnow() - timedelta(minutes=3)
                        user_is_online = user.last_activity_at >= cutoff
                    if not user.is_admin:
                        if user.last_login_at:
                            user_login_info = user.last_login_at.isoformat() if hasattr(user.last_login_at, 'isoformat') else str(user.last_login_at)
                        if user.last_logout_at:
                            user_logout_info = user.last_logout_at.isoformat() if hasattr(user.last_logout_at, 'isoformat') else str(user.last_logout_at)
                        user_is_suspended = user.is_suspended
                        user_id = user.id

            if acct_is_test and spot_balance_status != "ok":
                spot_balance_status = "ok"

            accounts_list.append({
                "account_id": account.id,
                "account_code": account.account_code,
                "name": account.name,
                "exchange": account.exchange,
                "created_at": account.created_at.isoformat() if account.created_at else datetime.utcnow().isoformat() + "Z",
                "active_bots": active_bots_count,
                "total_bots": len(bots),
                "bots_balance_usd": round(bots_balance, 2),
                "bot_locked_usd": round(bots_balance, 2),
                "spot_balance_usd": round(spot_balance, 2),
                "spot_kpi_total_usd": round(spot_balance, 2) if acct_is_test else None,
                "spot_balance_status": spot_balance_status,
                "total_usd": round(total_usd, 2),
                "daily_pnl_usd": round(daily_pnl_usd, 2),
                "daily_pnl_pct": round(daily_pnl_pct, 2),
                "daily_bot_pnl_usd": round(daily_pnl_usd, 2),
                "daily_bot_pnl_pct": round(daily_pnl_pct, 2),
                "daily_wallet_pnl_usd": round(daily_wallet_pnl_usd, 2) if daily_wallet_pnl_usd is not None else None,
                "daily_wallet_pnl_pct": round(daily_wallet_pnl_pct, 2) if daily_wallet_pnl_pct is not None else None,
                "admin_isolated": bool(getattr(account, "isolate_from_admin", False)),
                "last_update_ts": datetime.utcnow().isoformat() + "Z",
                "user_last_login_at": user_login_info,
                "user_last_logout_at": user_logout_info,
                "user_username": user_username,
                "user_is_suspended": user_is_suspended,
                "user_id": user_id,
                "user_last_login_ip": user_last_login_ip,
                "user_is_online": user_is_online,
                "user_phone": user_phone,
                "user_created_at": user_created_at,
                "user_name": user_name,
                "user_surname": user_surname,
                "is_test_account": acct_is_test,
            })
        except Exception as e:
            row_errors.append({"account_id": account.id, "error": str(e)[:400]})
            logger.warning(
                "[Admin] account row failed account_id=%s lite=%s request_id=%s error=%s",
                account.id, lite, request_id, e, exc_info=True,
            )

    try:
        accounts_list.sort(key=lambda x: (-x["active_bots"], -x["total_usd"]))
    except Exception as e:
        logger.warning("[Admin] Error sorting accounts: %s request_id=%s", e, request_id)

    duration_ms = (time.perf_counter() - t0) * 1000.0
    log_level = logger.warning if duration_ms >= 3000 or wallet_errors or bot_kpi_errors or row_errors else logger.info
    log_level(
        "ADMIN_ACCOUNTS_LIST duration_ms=%.0f account_rows=%d query_total=%d lite=%s suspended=%s "
        "wallet_errors=%s bot_kpi_error_count=%d slow_wallets=%s row_errors=%s request_id=%s admin_user_id=%s",
        duration_ms,
        len(accounts_list),
        len(accounts),
        lite,
        suspended,
        wallet_errors[:30],
        len(bot_kpi_errors),
        slow_wallets[:15],
        row_errors[:10],
        request_id,
        admin_user_id,
    )
    if bot_kpi_errors:
        logger.warning(
            "ADMIN_ACCOUNTS_LIST bot_kpi_errors=%s request_id=%s",
            json.dumps(bot_kpi_errors[:20], ensure_ascii=False),
            request_id,
        )
    if row_errors:
        logger.warning(
            "ADMIN_ACCOUNTS_LIST row_errors=%s request_id=%s",
            json.dumps(row_errors[:10], ensure_ascii=False),
            request_id,
        )

    try:
        payload = {
            "accounts": accounts_list,
            "totals": {
                "total_accounts": len(accounts_list),
                "total_active_bots": total_active_bots,
                "total_bots_balance_usd": round(total_bots_balance_usd, 2),
                "total_spot_balance_usd": round(total_spot_balance_usd, 2),
                "total_usd": round(total_bots_balance_usd + total_spot_balance_usd, 2),
                "last_update_ts": datetime.utcnow().isoformat() + "Z"
            },
            "lite": lite,
        }
        if not lite and _ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC > 0:
            async with _get_admin_accounts_full_cache_lock():
                _admin_accounts_full_cache[cache_key] = (time.time(), payload)
                if len(_admin_accounts_full_cache) > 32:
                    cutoff = time.time() - _ADMIN_ACCOUNTS_FULL_CACHE_TTL_SEC * 2
                    for k in [x for x, v in _admin_accounts_full_cache.items() if v[0] < cutoff]:
                        del _admin_accounts_full_cache[k]
        return payload
    except Exception as e:
        logger.error("[Admin] Error building response: %s request_id=%s", e, request_id, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_phone(s: str) -> str:
    """Digits only, strip."""
    return "".join(c for c in (s or "").strip() if c.isdigit())


@router.post("/admin/accounts")
async def create_admin_account(
    current: dict = Depends(_require_admin),
    req: AccountCreateRequest = Body(...),
    db: Session = Depends(get_db)
) -> Dict:
    """Create new account + user via admin panel. User gets one-time password."""
    if not (req.name or "").strip():
        raise HTTPException(status_code=400, detail="Ad soyad gerekli")
    phone_clean = _normalize_phone(req.phone or "")
    if not phone_clean:
        raise HTTPException(status_code=400, detail="Telefon numarası gerekli")
    
    exchange = req.exchange or "BINANCE"
    name = req.name.strip()
    parts = name.split(None, 1)
    user_name = parts[0] if parts else name
    user_surname = parts[1] if len(parts) > 1 else ""
    
    existing = db.query(User).filter(
        User.phone == phone_clean,
        or_(User.is_deleted == False, User.is_deleted.is_(None))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu telefon numarası ile zaten bir kullanıcı kayıtlı")
    
    username_base = phone_clean
    username = username_base
    n = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{username_base}_{n}"
        n += 1
    
    pwd = generate_password(user_name, user_surname)
    user = User(
        username=username,
        password_hash=hash_password(pwd),
        name=user_name,
        surname=user_surname,
        phone=phone_clean,
        is_admin=False,
        is_approved=True,
        is_suspended=False,
        must_change_password=True,
        last_login_at=None,
    )
    db.add(user)
    db.flush()
    db.refresh(user)
    
    account_code = generate_account_code(db)
    account = Account(
        account_code=account_code,
        name=name,
        exchange=exchange,
        api_key_enc=encrypt_text(""),
        api_secret_enc=encrypt_text(""),
        mode="live",
        is_first_login=True,
        user_id=user.id,
    )
    db.add(account)
    db.flush()
    db.refresh(account)
    user.account_id = account.id
    db.commit()
    db.refresh(account)
    
    return {
        "account_id": account.id,
        "account_code": account.account_code,
        "name": account.name,
        "exchange": account.exchange,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "active_bots": 0,
        "total_bots": 0,
        "bots_balance_usd": 0.0,
        "spot_balance_usd": 0.0,
        "username": username,
        "generated_password": pwd,
        "total_usd": 0.0,
        "last_update_ts": datetime.utcnow().isoformat() + "Z",
    }


@router.delete("/admin/accounts/{account_id}")
async def delete_admin_account(
    account_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Delete account and all related data - soft delete user"""
    trace_id = str(uuid.uuid4())[:8]
    logger.info(f"[{trace_id}] delete_admin_account: account_id={account_id}")
    
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            logger.warning(f"[{trace_id}] Account {account_id} not found")
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Check if account has bots
        bots = db.query(Bot).filter(Bot.account_id == account_id).all()
        if bots:
            bot_count = len(bots)
            logger.warning(f"[{trace_id}] Cannot delete account {account_id}: has {bot_count} bots")
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete account with existing bots. Please delete {bot_count} bot(s) first."
            )
        
        # Soft delete user if exists
        if account.user_id:
            user = db.query(User).filter(User.id == account.user_id).first()
            if user:
                user.is_deleted = True
                user.deleted_at = datetime.utcnow()
                user.account_id = None  # Remove account reference
                logger.info(f"[{trace_id}] User {user.id} ({user.username}) soft deleted")
        
        # Delete related data manually (avoid cascade issues with missing tables)
        # Delete trades
        db.query(Trade).filter(Trade.account_id == account_id).delete()
        
        # Delete PnL snapshots
        try:
            from app.db.models import PnlSnapshot
            db.query(PnlSnapshot).filter(PnlSnapshot.account_id == account_id).delete()
        except Exception as e:
            logger.warning(f"[{trace_id}] Could not delete PnL snapshots: {e}")
        
        # Try to delete financial_portfolio if table exists
        try:
            from app.db.models import FinancialPortfolio
            portfolio = db.query(FinancialPortfolio).filter(FinancialPortfolio.account_id == account_id).first()
            if portfolio:
                db.delete(portfolio)
        except Exception as e:
            # Table might not exist, ignore
            logger.debug(f"[{trace_id}] FinancialPortfolio table check: {e}")
        
        # Delete account
        db.delete(account)
        db.commit()
        
        logger.info(f"[{trace_id}] Account {account_id} deleted successfully")
        return {"message": "Account deleted successfully", "account_id": account_id}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"[{trace_id}] Error deleting account {account_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "ACCOUNT_DELETE_FAILED",
                "detail": f"Error deleting account: {str(e)}",
                "trace_id": trace_id
            }
        )


@router.post("/admin/password-reset-requests/{request_id}/dismiss")
async def dismiss_password_reset_request_path(
    request_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Mark password reset request as completed/dismissed. Removes from pending list. Idempotent."""
    return _dismiss_password_reset_impl(request_id, db)


@router.post("/admin/dismiss-password-reset-request")
async def dismiss_password_reset_request_body(
    current: dict = Depends(_require_admin),
    req: DismissPasswordResetRequest = Body(...),
    db: Session = Depends(get_db),
) -> Dict:
    """Dismiss password reset request by body (request_id). Use this if path-param version returns 404."""
    return _dismiss_password_reset_impl(req.request_id, db)


def _dismiss_password_reset_impl(request_id: int, db: Session) -> Dict:
    r = db.query(PasswordResetRequest).filter(PasswordResetRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Talep bulunamadı")
    if r.status == "completed":
        return {"success": True, "message": "Talep zaten kapatılmış"}
    r.status = "completed"
    r.completed_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Talep kapatıldı"}


# --- Sunucu sekmesi: istatistikler, lockdown, sunucudan çık (sadece admin) ---
import asyncio
import subprocess
import sys

from app import server_state as svc

_psutil_install_attempted = False


def _install_psutil_sync() -> bool:
    """pip install psutil (bloklayan, executor'da çalıştırılmalı). Başarılı ise True."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "psutil"],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if r.returncode != 0:
            logger.warning("pip install psutil failed: %s", (r.stderr or r.stdout or b"").decode("utf-8", "replace")[:500])
            return False
        logger.info("psutil installed automatically via pip")
        return True
    except Exception as e:
        logger.warning("Auto-install psutil error: %s", e)
        return False


def _collect_psutil_stats():
    """psutil import edilmiş kabul edilir. (mem_mb, mem_total_mb, cpu_percent, net_down, net_up) döner.
    Ağ: sadece gerçek arayüzler (loopback lo/lo0 hariç); bytes_recv = İndirme, bytes_sent = Yükleme."""
    import psutil
    vmem = psutil.virtual_memory()
    mem_mb = round(vmem.used / (1024 * 1024), 2)
    mem_total_mb = round(vmem.total / (1024 * 1024), 2)
    cpu_percent = round(psutil.cpu_percent(interval=0.15), 1)
    network_mbps_down = None
    network_mbps_up = None
    try:
        pernic = psutil.net_io_counters(pernic=True)
        if pernic:
            sent_total = 0
            recv_total = 0
            for iface, net in pernic.items():
                if not iface or (iface.lower().startswith("lo")):
                    continue
                sent_total += getattr(net, "bytes_sent", 0) or 0
                recv_total += getattr(net, "bytes_recv", 0) or 0
            if sent_total or recv_total:
                down_mbps, up_mbps = svc.get_net_rate(sent_total, recv_total)
                if down_mbps is not None and down_mbps >= 0:
                    network_mbps_down = round(min(down_mbps, 100000.0), 2)
                if up_mbps is not None and up_mbps >= 0:
                    network_mbps_up = round(min(up_mbps, 100000.0), 2)
    except Exception:
        net = psutil.net_io_counters()
        if net:
            down_mbps, up_mbps = svc.get_net_rate(net.bytes_sent, net.bytes_recv)
            if down_mbps is not None and down_mbps >= 0:
                network_mbps_down = round(min(down_mbps, 100000.0), 2)
            if up_mbps is not None and up_mbps >= 0:
                network_mbps_up = round(min(up_mbps, 100000.0), 2)
    return mem_mb, mem_total_mb, cpu_percent, network_mbps_down, network_mbps_up


def _get_network_link_and_ip():
    """PC'nin ağ arayüzünden bağlantı hızı (Mbps) ve sunucu IPv4 adresini döner. (link_speed_mbps, server_ip)."""
    import socket
    try:
        import psutil
        af_inet = getattr(socket, "AF_INET", 2)
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        if not addrs:
            return None, None
        best_speed = None
        best_ip = None
        for iface in sorted(addrs.keys()):
            if not iface or iface.lower().startswith("lo"):
                continue
            ip_str = None
            for addr in addrs.get(iface, []):
                if getattr(addr, "family", None) != af_inet:
                    continue
                a = getattr(addr, "address", None) or getattr(addr, "addr", None)
                if a and not a.startswith("127."):
                    ip_str = str(a).strip()
                    break
            if not ip_str:
                continue
            st = (stats or {}).get(iface)
            speed = 0
            if st and getattr(st, "isup", True):
                speed = getattr(st, "speed", 0) or 0
            if speed > 0:
                best_speed = int(speed) if speed == int(speed) else round(speed, 1)
            if best_ip is None:
                best_ip = ip_str
        return best_speed, best_ip
    except Exception as e:
        logger.debug("Network link/IP: %s", e)
        return None, None


@router.get("/admin/breach-alerts")
async def get_breach_alerts(current: dict = Depends(_require_admin)) -> Dict:
    """Güvenlik ihlali uyarılarını döndürür ve listeden temizler. Admin panelde büyük uyarı gösterilir."""
    from app import server_state as svc
    events = svc.get_and_clear_breach_events()
    return {"breach_events": events, "count": len(events)}


def _error_log_row_to_item(row, user_label: Optional[str] = None, account_label: Optional[str] = None, occurrence_count: int = 1) -> Dict:
    """Build API item from ErrorLog row."""
    import json
    ctx = None
    if getattr(row, "context_json", None):
        try:
            ctx = json.loads(row.context_json) if isinstance(row.context_json, str) else row.context_json
        except Exception:
            ctx = None
    return {
        "id": row.id,
        "source": row.source or "",
        "message": row.message or "",
        "detail": getattr(row, "detail", None) or None,
        "path": getattr(row, "path", None) or None,
        "context": ctx,
        "user_label": user_label,
        "account_label": account_label,
        "is_admin": bool(getattr(row, "is_admin", False)),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "occurrence_count": occurrence_count,
        "client_ip": getattr(row, "client_ip", None) or None,
        "user_agent": getattr(row, "user_agent", None) or None,
        "request_id": getattr(row, "request_id", None) or None,
    }


@router.get("/admin/error-logs")
async def get_error_logs(
    current: dict = Depends(_require_admin),
    grouped: bool = Query(True, description="Aynı (source, message, path) gruplanır"),
    max_unique: int = Query(50, ge=1, le=200, description="Maksimum benzersiz hata sayısı"),
    after_id: Optional[int] = Query(None, description="Sadece id > after_id kayıtlar"),
    db: Session = Depends(get_db),
) -> Dict:
    """Hata logları listesi. grouped=true ise aynı (source, message, path) tek satırda occurrence_count ile."""
    try:
        q = db.query(ErrorLog).order_by(desc(ErrorLog.id))
        if after_id is not None:
            q = q.filter(ErrorLog.id > after_id)
        if grouped:
            # Fetch more rows to group; cap for safety
            rows = q.limit(min(max_unique * 20, 2000)).all()
            # Group by (source, message, path)
            seen = {}
            for row in rows:
                key = (row.source or "", row.message or "", row.path or "")
                if key not in seen:
                    seen[key] = []
                seen[key].append(row)
            # Take first max_unique groups (already in desc id order), representative = first of group
            groups = list(seen.items())[:max_unique]
            errors = []
            for _key, group in groups:
                rep = group[0]
                user_label = None
                account_label = None
                if rep.user_id:
                    u = db.query(User).filter(User.id == rep.user_id).first()
                    if u:
                        user_label = u.username or (f"Denenen: {(u.phone or '')[:8]}..." if u.phone else str(u.id))
                if rep.account_id:
                    a = db.query(Account).filter(Account.id == rep.account_id).first()
                    if a:
                        account_label = a.name or a.account_code or str(a.id)
                errors.append(_error_log_row_to_item(rep, user_label=user_label, account_label=account_label, occurrence_count=len(group)))
        else:
            rows = q.limit(max_unique).all()
            errors = []
            for row in rows:
                user_label = None
                account_label = None
                if row.user_id:
                    u = db.query(User).filter(User.id == row.user_id).first()
                    if u:
                        user_label = u.username or (f"Denenen: {(u.phone or '')[:8]}..." if u.phone else str(u.id))
                if row.account_id:
                    a = db.query(Account).filter(Account.id == row.account_id).first()
                    if a:
                        account_label = a.name or a.account_code or str(a.id)
                errors.append(_error_log_row_to_item(row, user_label=user_label, account_label=account_label, occurrence_count=1))
        return {"errors": errors}
    except Exception as e:
        logger.warning("[Admin] get_error_logs failed: %s", e)
        raise HTTPException(status_code=500, detail={"message": str(e)})


@router.get("/admin/error-logs/count")
async def get_error_logs_count(
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Toplam hata sayısı ve en son id (sıfırla sonrası after_id için)."""
    try:
        cnt = db.query(ErrorLog).count()
        latest = db.query(ErrorLog).order_by(desc(ErrorLog.id)).first()
        latest_id = latest.id if latest else None
        return {"count": cnt, "latest_id": latest_id}
    except Exception as e:
        logger.warning("[Admin] get_error_logs_count failed: %s", e)
        return {"count": 0, "latest_id": None}


@router.get("/admin/server/stats")
async def get_server_stats(current: dict = Depends(_require_admin)) -> Dict:
    """Sunucu istatistikleri: uptime, bellek, CPU, istek sayısı, ağ hızı, lockdown. psutil yoksa bir kez otomatik kurulur."""
    global _psutil_install_attempted
    uptime_sec = svc.get_uptime_seconds()
    request_count = svc.get_request_count()
    lockdown = svc.get_lockdown()
    mem_mb = None
    mem_total_mb = None
    cpu_percent = None
    network_mbps_down = None
    network_mbps_up = None
    network_link_mbps = None
    server_ip = None
    psutil_available = False

    try:
        import psutil
        psutil_available = True
        mem_mb, mem_total_mb, cpu_percent, network_mbps_down, network_mbps_up = _collect_psutil_stats()
        network_link_mbps, server_ip = _get_network_link_and_ip()
    except ImportError:
        if not _psutil_install_attempted:
            _psutil_install_attempted = True
            try:
                loop = asyncio.get_event_loop()
                ok = await loop.run_in_executor(None, _install_psutil_sync)
                if ok:
                    if "psutil" in sys.modules:
                        del sys.modules["psutil"]
                    import psutil
                    psutil_available = True
                    mem_mb, mem_total_mb, cpu_percent, network_mbps_down, network_mbps_up = _collect_psutil_stats()
                    network_link_mbps, server_ip = _get_network_link_and_ip()
            except Exception as e:
                logger.warning("psutil auto-install or re-import failed: %s", e)
        if not psutil_available:
            logger.debug("psutil not available (install failed or skipped)")
    except Exception as e:
        logger.warning("Server stats psutil error: %s", e, exc_info=True)

    try:
        server_cwd = os.getcwd() or None
    except Exception:
        server_cwd = None
    if not server_cwd:
        try:
            _dir = os.path.dirname(os.path.abspath(__file__))
            server_cwd = os.path.dirname(os.path.dirname(_dir))
        except Exception:
            pass

    return {
        "uptime_seconds": round(uptime_sec, 1),
        "uptime_formatted": _format_uptime(uptime_sec),
        "request_count": request_count,
        "lockdown": lockdown,
        "memory_mb": mem_mb,
        "memory_total_mb": mem_total_mb,
        "cpu_percent": cpu_percent,
        "network_mbps_down": network_mbps_down,
        "network_mbps_up": network_mbps_up,
        "network_link_mbps": network_link_mbps,
        "server_ip": server_ip,
        "server_cwd": server_cwd,
        "psutil_available": psutil_available,
    }


def _format_uptime(sec: float) -> str:
    s = int(sec)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d > 0:
        return f"{d}g {h}s {m}dk"
    if h > 0:
        return f"{h}s {m}dk {s}sn"
    if m > 0:
        return f"{m}dk {s}sn"
    return f"{s}sn"


class ForceUnlockRequest(BaseModel):
    account_id: int
    symbol: str


@router.post("/admin/force-unlock-symbol")
async def admin_force_unlock_symbol(
    req: ForceUnlockRequest = Body(...),
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Admin: clear symbol lock if lease expired (owner bot not alive). Only clears when lease_until < now."""
    from app.botengine.locks import force_unlock_symbol
    symbol = (req.symbol or "").upper().strip() or "BTCUSDT"
    count = force_unlock_symbol(db, req.account_id, symbol)
    return {"success": True, "cleared": count, "message": f"Cleared {count} expired lock(s) for {symbol}" if count else f"No expired lock for {symbol}"}


@router.post("/admin/server/lockdown")
async def server_lockdown(current: dict = Depends(_require_admin)) -> Dict:
    """Erişimi kapat: sadece admin sayfası ve gerekli API'ler erişilebilir."""
    svc.set_lockdown(True)
    logger.info("Server lockdown enabled by admin")
    return {"success": True, "lockdown": True, "message": "Erişim kapatıldı. Sadece admin erişebilir."}


@router.post("/admin/server/unlock")
async def server_unlock(current: dict = Depends(_require_admin)) -> Dict:
    """Erişimi aç: tüm kullanıcılar tekrar erişebilir."""
    svc.set_lockdown(False)
    logger.info("Server lockdown disabled by admin")
    return {"success": True, "lockdown": False, "message": "Erişim açıldı."}


@router.post("/admin/server/exit")
async def server_exit(
    req: ServerExitRequest = Body(...),
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Sunucuyu kapat (graceful shutdown). Sadece admin; şifre ile onay gerekir. Yanlış şifrede asla kapatma."""
    # Şifre boş veya yoksa reddet
    password = (req.password or "").strip()
    if not password:
        raise HTTPException(status_code=400, detail="Şifre girin. Sunucuyu kapatmak için admin şifrenizi girin.")

    user = db.query(User).filter(User.id == current["user_id"]).first()
    if not user:
        raise HTTPException(status_code=403, detail="Kullanıcı bulunamadı")
    stored_hash = getattr(user, "password_hash", None)
    if not stored_hash or not isinstance(stored_hash, str) or len(stored_hash) < 10:
        raise HTTPException(status_code=403, detail="Admin şifresi tanımlı değil. Önce ayarlardan şifre belirleyin.")

    # Şifre doğrulama: herhangi bir hata = reddet, asla sunucuyu kapatma
    password_valid = False
    try:
        password_valid = bool(verify_password(password, stored_hash))
    except Exception as e:
        logger.warning("Server exit password verification error (rejecting): %s", e)
        raise HTTPException(status_code=400, detail="Şifre doğrulanamadı. Lütfen doğru admin şifresini girin.")

    if not password_valid:
        logger.warning("Server exit rejected: wrong password for user_id=%s", current.get("user_id"))
        raise HTTPException(status_code=400, detail="Yanlış şifre. Sunucuyu kapatmak için admin şifrenizi girin.")

    logger.warning("Server exit confirmed by admin (password OK) - shutting down")
    import os
    import signal
    import threading

    def do_exit():
        import time
        time.sleep(0.5)
        # Ana uvicorn sürecini kapat (worker değil); böylece tüm sunucu kapanır
        try:
            parent_pid = os.getppid()
            os.kill(parent_pid, signal.SIGTERM)
        except Exception:
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=do_exit, daemon=True).start()
    return {"success": True, "message": "Sunucu kapatılıyor..."}


@router.post("/admin/server/restart")
async def server_restart(current: dict = Depends(_require_admin)) -> Dict:
    """Sunucuyu 5 sn sonra kapatıp yeniden başlatır. Unix: run.sh; Windows: calistir.bat/Server Start.bat. Restart işlemi ayrı proses ile yapılır."""
    import os
    import sys
    import subprocess
    import platform

    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(app_dir)
    is_windows = platform.system() == "win32"

    if is_windows:
        restart_script = os.path.join(project_root, "scripts", "restart_server_win.py")
        if not os.path.isfile(restart_script):
            logger.error("Restart script bulunamadı: %s", restart_script)
            raise HTTPException(status_code=500, detail="Restart script bulunamadı (scripts/restart_server_win.py).")
        run_dir = os.path.join(project_root, ".run")
        os.makedirs(run_dir, exist_ok=True)
        log_path = os.path.join(run_dir, "restart_helper.log")
        try:
            log_file = open(log_path, "a", encoding="utf-8")
        except OSError as e:
            logger.warning("Restart log dosyası açılamadı %s: %s", log_path, e)
            log_file = None
        proc = subprocess.Popen(
            [sys.executable, restart_script, str(os.getpid())],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT if log_file else subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        # Başlatma scripti sırasıyla: run.sh (kök), scripts/run.sh, start.command, start
        run_sh = os.path.join(project_root, "run.sh")
        if not os.path.isfile(run_sh):
            run_sh = os.path.join(project_root, "scripts", "run.sh")
        if not os.path.isfile(run_sh):
            run_sh = os.path.join(project_root, "ops", "start.command")
        if not os.path.isfile(run_sh):
            run_sh = os.path.join(project_root, "start.command")
        if not os.path.isfile(run_sh):
            run_sh = os.path.join(project_root, "start")
        restart_script = os.path.join(project_root, "scripts", "restart_server.py")
        if not os.path.isfile(restart_script):
            logger.error("Restart script bulunamadı: %s", restart_script)
            raise HTTPException(status_code=500, detail="Restart script bulunamadı (scripts/restart_server.py).")
        if not os.path.isfile(run_sh):
            logger.error("Başlatma scripti bulunamadı (run.sh, start.command, start): %s", run_sh)
            raise HTTPException(status_code=500, detail="run.sh veya start.command/start bulunamadı. Proje köküne run.sh ekleyin veya start.command kullanın.")
        run_dir = os.path.join(project_root, ".run")
        os.makedirs(run_dir, exist_ok=True)
        log_path = os.path.join(run_dir, "restart_helper.log")
        try:
            log_file = open(log_path, "a", encoding="utf-8")
        except OSError as e:
            logger.warning("Restart log dosyası açılamadı %s: %s", log_path, e)
            log_file = None
        proc = subprocess.Popen(
            [sys.executable, restart_script, str(os.getpid()), run_sh],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT if log_file else subprocess.DEVNULL,
            start_new_session=True,
        )

    if proc.poll() is not None:
        logger.error("Restart helper hemen çıktı, kod=%s", proc.returncode)
        raise HTTPException(status_code=500, detail="Restart yardımcısı başlatılamadı.")

    msg = "Sunucu 5 saniye içinde kapatılıp yeniden başlatılacak."
    logger.warning("Server restart scheduled by admin - helper PID %s, exit in 5 seconds", proc.pid)
    return {"success": True, "message": msg}


# --- Admin Pop-Up mesajlari ---
POPUP_TITLE_KEYS = ("info", "warning", "success", "maintenance", "announcement")


# Spesifik path önce tanımlanmalı (aksi halde GET /admin/popups/5, list route ile eşleşip 405 verebilir)
@router.get("/admin/popups/{popup_id}")
async def get_admin_popup_detail(
    popup_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Tek pop-up detayı + okuyup kapatan kullanıcı listesi."""
    popup = db.query(AdminPopup).filter(AdminPopup.id == popup_id).first()
    if not popup:
        raise HTTPException(status_code=404, detail="Pop-up bulunamadı")
    now = datetime.utcnow()
    dismissals = (
        db.query(AdminPopupDismissal, User)
        .join(User, User.id == AdminPopupDismissal.user_id)
        .filter(AdminPopupDismissal.popup_id == popup_id)
        .order_by(desc(AdminPopupDismissal.dismissed_at))
        .all()
    )
    return {
        "popup": {
            "id": popup.id,
            "target": popup.target,
            "title_key": popup.title_key,
            "message": popup.message,
            "valid_until": popup.valid_until.isoformat() if hasattr(popup.valid_until, "isoformat") else str(popup.valid_until),
            "created_at": popup.created_at.isoformat() if popup.created_at and hasattr(popup.created_at, "isoformat") else str(popup.created_at or ""),
            "is_active": popup.valid_until >= now if hasattr(popup.valid_until, "__ge__") else True,
            "max_shows_per_user": getattr(popup, "max_shows_per_user", None) or 1,
        },
        "dismissals": [
            {
                "user_id": d.user_id,
                "user_name": (u.name or "").strip() + " " + (u.surname or "").strip(),
                "dismissed_at": d.dismissed_at.isoformat() if d.dismissed_at and hasattr(d.dismissed_at, "isoformat") else str(d.dismissed_at or ""),
            }
            for d, u in dismissals
        ],
    }


@router.get("/admin/popups")
async def list_admin_popups(
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Yayindaki ve gecmis pop-up listesi (admin)."""
    now = datetime.utcnow()
    rows = db.query(AdminPopup).order_by(desc(AdminPopup.created_at)).limit(100).all()
    items = []
    for p in rows:
        items.append({
            "id": p.id,
            "target": p.target,
            "title_key": p.title_key,
            "message": p.message,
            "valid_until": p.valid_until.isoformat() if hasattr(p.valid_until, "isoformat") else str(p.valid_until),
            "created_at": p.created_at.isoformat() if p.created_at and hasattr(p.created_at, "isoformat") else str(p.created_at or ""),
            "is_active": p.valid_until >= now if hasattr(p.valid_until, "__ge__") else True,
            "max_shows_per_user": getattr(p, "max_shows_per_user", None) or 1,
        })
    return {"popups": items}


@router.post("/admin/popups")
async def create_admin_popup(
    req: CreatePopupRequest = Body(...),
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Yeni pop-up yayinla (admin). target: first_login | normal_user; title_key: info|warning|success|maintenance|announcement."""
    if req.target not in ("first_login", "normal_user"):
        raise HTTPException(status_code=400, detail="target first_login veya normal_user olmalı")
    if (req.title_key or "").strip() not in POPUP_TITLE_KEYS:
        raise HTTPException(status_code=400, detail="title_key şunlardan biri olmalı: " + ", ".join(POPUP_TITLE_KEYS))
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    try:
        raw = req.valid_until.replace("Z", "+00:00").strip()
        valid_until = datetime.fromisoformat(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Geçerlilik süresi geçerli bir tarih olmalı (örn. 2026-02-15T23:59:00)")
    if valid_until.tzinfo:
        valid_until = valid_until.astimezone(timezone.utc).replace(tzinfo=None)
    if valid_until <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Geçerlilik süresi gelecekte bir tarih olmalı")
    max_shows = req.max_shows_per_user if req.max_shows_per_user is not None else 1
    if max_shows < 1:
        max_shows = 1
    popup = AdminPopup(
        target=req.target,
        title_key=req.title_key.strip(),
        message=message,
        valid_until=valid_until,
        created_by=current.get("user_id"),
        max_shows_per_user=max_shows,
    )
    db.add(popup)
    db.commit()
    db.refresh(popup)
    return {"success": True, "id": popup.id, "message": "Pop-up yayınlandı."}


@router.delete("/admin/popups/{popup_id}")
async def delete_admin_popup(
    popup_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> Dict:
    """Yayindan kaldir: popup silinir, kullaniciya bir daha gosterilmez."""
    popup = db.query(AdminPopup).filter(AdminPopup.id == popup_id).first()
    if not popup:
        raise HTTPException(status_code=404, detail="Pop-up bulunamadı")
    db.query(AdminPopupDismissal).filter(AdminPopupDismissal.popup_id == popup_id).delete()
    db.delete(popup)
    db.commit()
    return {"success": True, "message": "Pop-up kaldırıldı."}
