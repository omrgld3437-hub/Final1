"""
Flash Home (mobile-first) – Patch H.
GET /api/home/fast: no Binance, cached prices + KPIs + last wallet snapshot.
POST /api/home/wallet/refresh: Binance wallet refresh with TTL + inflight dedup + cooldown.
GET /api/home/wallet/status: inflight, last_live_at, cooldown_until.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.auth import require_auth, require_account_access
from app.core.config import get_config
from app.core.logging_helpers import log_wallet_trace
from app.core.errors import AppError
from app.db.session import get_db
from app.db.models import Account, AssetSnapshot

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory state (per account)
_fast_cache: Dict[int, Dict[str, Any]] = {}  # account_id -> { payload, expires_at (monotonic) }
_wallet_refresh_inflight: Dict[int, asyncio.Task] = {}
_wallet_last_live_at: Dict[int, float] = {}  # monotonic time of last successful fetch
_wallet_last_live_at_iso: Dict[int, str] = {}  # ISO8601 for status endpoint
_wallet_cooldown_until: Dict[int, float] = {}  # monotonic deadline
_wallet_last_error_code: Dict[int, Optional[str]] = {}
_wallet_refresh_locks: Dict[int, asyncio.Lock] = {}
_in_memory_wallet: Dict[int, Tuple[Dict, float]] = {}  # account_id -> (minimal_wallet_dict, ts_monotonic)


def _get_lock(account_id: int) -> asyncio.Lock:
    if account_id not in _wallet_refresh_locks:
        _wallet_refresh_locks[account_id] = asyncio.Lock()
    return _wallet_refresh_locks[account_id]


def _sort_and_cap_assets(assets: List[Dict], max_n: int) -> List[Dict]:
    """Sort by value desc (usdt_value or total_usd or value_usd), cap to max_n. Put null at end."""
    def _val(a: Dict) -> float:
        v = a.get("usdt_value")
        if v is not None:
            return float(v)
        v = a.get("total_usd") or a.get("value_usd")
        return float(v) if v is not None else -1.0
    with_val = [(a, _val(a)) for a in assets]
    with_val.sort(key=lambda x: (x[1] < 0, -x[1]))
    return [x[0] for x in with_val[:max_n]]


def _minimal_wallet_from_breakdown(
    total_usd_value: float,
    breakdown_json: Optional[str],
    max_assets: int,
) -> Dict[str, Any]:
    """Build minimal wallet payload from AssetSnapshot.breakdown_json."""
    assets: List[Dict[str, Any]] = []
    try:
        breakdown = json.loads(breakdown_json or "{}") if breakdown_json else {}
    except Exception:
        breakdown = {}
    for asset, data in (breakdown or {}).items():
        if not isinstance(data, dict):
            continue
        free = float(data.get("free") or 0)
        locked = float(data.get("locked") or 0)
        usd_val = data.get("usdValue")
        usdt_value = float(usd_val) if usd_val is not None else None
        if free <= 0 and locked <= 0:
            continue
        assets.append({
            "asset": asset,
            "free": free,
            "locked": locked,
            "usdt_value": round(usdt_value, 2) if usdt_value is not None else None,
        })
    assets = _sort_and_cap_assets(assets, max_assets)
    return {
        "total_usd": round(total_usd_value, 2),
        "assets": assets,
    }


def _get_last_wallet_snapshot_with_new_session(account_id: int, max_assets: int) -> Tuple[Optional[Dict], Optional[str]]:
    """Thread-safe: create new session, read last snapshot, close. Used from run_in_executor."""
    from app.db.base import SessionLocal
    db = SessionLocal()
    try:
        return _get_last_wallet_snapshot_sync(db, account_id, max_assets)
    finally:
        db.close()


def _enrich_minimal_wallet_with_bot_locked(wallet: Dict[str, Any], account_id: int, db: Session) -> None:
    """Add locked_usd, bot_locked_usd, available_usd and per-asset bot_locked so strip/table show correctly."""
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
    if not wallet or not isinstance(wallet.get("assets"), list):
        return
    bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
    free_usd_tot = 0.0
    locked_usd_tot = 0.0
    total_bot_locked_usd = 0.0
    for a in wallet["assets"]:
        asset = (a.get("asset") or "").strip()
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
    wallet["free_usd"] = round(free_usd_tot, 2)
    wallet["locked_usd"] = round(locked_usd_tot, 2)
    wallet["bot_locked_usd"] = round(total_bot_locked_usd, 2)
    wallet["available_usd"] = round(max(0.0, free_usd_tot - total_bot_locked_usd), 2)


def _get_last_wallet_snapshot_sync(db: Session, account_id: int, max_assets: int) -> Tuple[Optional[Dict], Optional[str]]:
    """Sync DB read: last AssetSnapshot by account_id. Returns (minimal_wallet_dict, ts_iso) or (None, None)."""
    try:
        row = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(desc(AssetSnapshot.timestamp))
            .limit(1)
            .first()
        )
        if not row:
            return (None, None)
        ts_iso = row.timestamp.isoformat() if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=timezone.utc).isoformat()
        if not ts_iso.endswith("Z"):
            ts_iso = ts_iso.replace("+00:00", "Z") if "+00:00" in ts_iso else ts_iso + "Z"
        minimal = _minimal_wallet_from_breakdown(
            row.total_usd_value,
            row.breakdown_json,
            max_assets,
        )
        return (minimal, ts_iso)
    except Exception as e:
        logger.warning("[home] get_last_wallet_snapshot error account_id=%s: %s", account_id, e)
        return (None, None)


def _get_prices_minimal_sync() -> Dict[str, Any]:
    """Get cached prices from DataHub only (no network)."""
    try:
        from app.services.data_hub import data_hub
        return data_hub.get_all_prices() or {}
    except Exception as e:
        logger.debug("[home] get_all_prices error: %s", e)
        return {}


async def _get_kpis_minimal(account_id: int, db: Session) -> Dict[str, Any]:
    """Async wrapper: run DB-heavy KPI fetch in thread."""
    loop = asyncio.get_running_loop()
    try:
        from app.services.dashboard_snapshot import fetch_bots_and_account_kpis, fetch_finance_pnl
        bots_raw, pnl_raw = await asyncio.gather(
            fetch_bots_and_account_kpis(account_id, db),
            fetch_finance_pnl(account_id, db),
        )
    except Exception as e:
        logger.debug("[home] get_kpis_minimal error: %s", e)
        return {}
    bots = bots_raw if isinstance(bots_raw, dict) and "_error" not in bots_raw else {}
    pnl = pnl_raw if isinstance(pnl_raw, dict) and "_error" not in pnl_raw else {}
    account_kpis = bots.get("account") or {}
    return {
        "total_bots": account_kpis.get("total_bots", 0),
        "active_bots": account_kpis.get("active_bots", 0),
        "total_pnl_usd": round(float(account_kpis.get("total_pnl_usd") or 0), 2),
        "daily_bot_pnl_usd": round(float(account_kpis.get("daily_bot_pnl_usd") or 0), 2),
        "realized_pnl": round(float(pnl.get("realized_pnl", 0) or 0), 2),
        "unrealized_pnl": round(float(pnl.get("unrealized_pnl", 0) or 0), 2),
    }


def _is_wallet_refresh_inflight(account_id: int) -> bool:
    task = _wallet_refresh_inflight.get(account_id)
    if task is None:
        return False
    if task.done():
        _wallet_refresh_inflight.pop(account_id, None)
        return False
    return True


@router.get("/home/config")
async def home_config():
    """Feature flag and policy for Flash Home (no auth required for config)."""
    cfg = get_config()
    return {
        "ok": True,
        "data": {
            "flash_home_enabled": cfg.get("flash_home_enabled", True),
            "refresh_policy": {
                "ttl_sec": cfg.get("wallet_live_ttl_sec", 5),
                "cooldown_sec": cfg.get("wallet_cooldown_sec", 30),
            },
        },
    }


@router.get("/home/fast")
async def home_fast(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Fast homepage payload: NO Binance. Cached prices + minimal KPIs + last wallet snapshot.
    Contract: { ok, data, meta } with meta.request_id, server_ms, payload_bytes, cache, stale, generated_at.
    """
    t0 = time.perf_counter()
    request_id = getattr(request.state, "request_id", None) or ""
    require_account_access(current, account_id)

    cfg = get_config()
    cache_ttl_sec = cfg.get("home_fast_cache_ttl_sec", 2)
    max_assets = cfg.get("home_fast_max_assets", 20)
    warn_bytes = cfg.get("home_fast_warn_bytes", 200000)

    # Memory cache hit
    now_mono = time.monotonic()
    if account_id in _fast_cache:
        entry = _fast_cache[account_id]
        if entry.get("expires_at", 0) > now_mono:
            payload_bytes = entry.get("payload_bytes", b"")
            if isinstance(payload_bytes, bytes):
                payload_len = len(payload_bytes)
            else:
                payload_bytes = (payload_bytes or b"").encode("utf-8") if isinstance(payload_bytes, str) else b""
                payload_len = len(payload_bytes)
            data_out = dict(entry.get("data") or {})
            wc = data_out.get("wallet_cached")
            if wc and isinstance(wc, dict):
                wc = dict(wc)
                wc_assets = wc.get("assets")
                if isinstance(wc_assets, list):
                    wc = dict(wc, assets=[dict(a) for a in wc_assets if isinstance(a, dict)])
                _enrich_minimal_wallet_with_bot_locked(wc, account_id, db)
                data_out["wallet_cached"] = wc
            server_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "home_fast_served event=home_fast_served account_id=%s request_id=%s server_ms=%.2f payload_bytes=%s cache=memory",
                account_id, request_id, server_ms, payload_len,
            )
            wc = data_out.get("wallet_cached")
            if wc and isinstance(wc, dict):
                log_wallet_trace(
                    event="wallet_payload_out",
                    request_id=request_id or "",
                    account_id=account_id,
                    source="home_fast_cached",
                    keys_configured=True,
                    asset_count=len(wc.get("assets") or []),
                    total_usd=wc.get("total_usd"),
                    cache_hit=True,
                    upstream_call=False,
                    duration_ms=server_ms,
                )
            return {
                "ok": True,
                "data": data_out,
                "meta": {
                    "request_id": request_id,
                    "server_ms": round(server_ms, 2),
                    "payload_bytes": payload_len,
                    "stale": entry.get("data", {}).get("prices_ready") is False,
                    "cache": "memory",
                    "generated_at": entry.get("generated_at", ""),
                },
            }

    # Build payload: prices (DataHub only), KPIs (DB), wallet_cached (DB)
    prices = await asyncio.get_running_loop().run_in_executor(None, _get_prices_minimal_sync)
    prices_ready = bool(prices)

    wallet_cached, wallet_cached_at = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: _get_last_wallet_snapshot_with_new_session(account_id, max_assets),
    )
    if wallet_cached:
        _enrich_minimal_wallet_with_bot_locked(wallet_cached, account_id, db)
    kpis = await _get_kpis_minimal(account_id, db)
    inflight = _is_wallet_refresh_inflight(account_id)

    data = {
        "prices": prices,
        "kpis": kpis,
        "wallet_cached": wallet_cached,
        "wallet_cached_at": wallet_cached_at,
        "prices_ready": prices_ready,
        "wallet_live_inflight": inflight,
    }
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload_bytes = json.dumps({"ok": True, "data": data}, separators=(",", ":")).encode("utf-8")
    payload_len = len(payload_bytes)
    if payload_len > warn_bytes:
        logger.warning("[home] home_fast payload_bytes=%s > warn=%s account_id=%s", payload_len, warn_bytes, account_id)

    # Cap payload size: trim prices if needed (keep only top symbols)
    if payload_len > 250000:
        data["prices"] = dict(list(prices.items())[:200])
        data["wallet_cached"] = wallet_cached
        payload_bytes = json.dumps({"ok": True, "data": data}, separators=(",", ":")).encode("utf-8")
        payload_len = len(payload_bytes)

    server_ms = (time.perf_counter() - t0) * 1000
    _fast_cache[account_id] = {
        "data": data,
        "expires_at": now_mono + cache_ttl_sec,
        "payload_bytes": payload_bytes,
        "generated_at": generated_at,
    }

    logger.info(
        "home_fast_served event=home_fast_served account_id=%s request_id=%s server_ms=%.2f payload_bytes=%s cache=db",
        account_id, request_id, server_ms, payload_len,
    )
    if wallet_cached and isinstance(wallet_cached, dict):
        log_wallet_trace(
            event="wallet_payload_out",
            request_id=request_id or "",
            account_id=account_id,
            source="home_fast_cached",
            keys_configured=True,
            asset_count=len(wallet_cached.get("assets") or []),
            total_usd=wallet_cached.get("total_usd"),
            cache_hit=False,
            upstream_call=False,
            duration_ms=server_ms,
        )
    return {
        "ok": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "server_ms": round(server_ms, 2),
            "payload_bytes": payload_len,
            "stale": not prices_ready,
            "cache": "db",
            "generated_at": generated_at,
        },
    }


def _is_rate_limit_error(e: Exception) -> bool:
    if hasattr(e, "response") and e.response is not None:
        sc = getattr(e.response, "status_code", None)
        if sc in (429, 418):
            return True
    return False


def _cooldown_sec_for_rate_limit(e: Exception, default_sec: float = 30) -> float:
    """418 IP banned: use parsed 'banned until' + buffer; else default (429 or unknown)."""
    try:
        from app.services.binance_spot import BinanceIPBannedError
        if isinstance(e, BinanceIPBannedError):
            now = time.time()
            sec = max(60, min(600, e.banned_until_ts - now + 10))
            return sec
    except Exception:
        pass
    if hasattr(e, "response") and e.response is not None and getattr(e.response, "status_code", None) == 418:
        try:
            body = (getattr(e.response, "text", "") or "")[:300]
            import re
            m = re.search(r"IP banned until (\d+)", body)
            if m:
                banned_ms = int(m.group(1))
                until_sec = banned_ms / 1000.0 + 60.0
                return max(60, min(600, until_sec - time.time() + 10))
        except Exception:
            pass
        return 300.0  # 5 min when 418 but unparseable
    return default_sec


async def _do_wallet_refresh(account_id: int, db: Session, request_id: str, force: bool) -> Dict[str, Any]:
    """Call Binance wallet fetch, write AssetSnapshot, update in-memory state. Used inside lock. Timeout 6s (2.5s connect + 3s read)."""
    from app.api.routes import _fetch_wallet_uncached

    cfg = get_config()
    max_assets = cfg.get("home_fast_max_assets", 20)
    WALLET_REFRESH_TIMEOUT = 6.0  # 2.5s connect + 3s read total budget
    t0 = time.perf_counter()
    try:
        wallet_raw = await asyncio.wait_for(_fetch_wallet_uncached(account_id, db), timeout=WALLET_REFRESH_TIMEOUT)
    except asyncio.TimeoutError:
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.warning(
            "wallet_refresh_attempt error_code=BINANCE_TIMEOUT duration_ms=%.0f request_id=%s account_id=%s",
            duration_ms, request_id, account_id,
        )
        _wallet_last_error_code[account_id] = "BINANCE_TIMEOUT"
        _wallet_cooldown_until[account_id] = time.monotonic() + cfg.get("wallet_cooldown_sec", 30)
        return {"_error": "timeout", "code": "BINANCE_TIMEOUT"}
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        err_str = str(e)
        try:
            from app.services.binance_spot import BinanceIPBannedError
            if isinstance(e, BinanceIPBannedError):
                code = "BINANCE_IP_BANNED"
                cooldown_sec = _cooldown_sec_for_rate_limit(e, 300)
                _wallet_last_error_code[account_id] = code
                _wallet_cooldown_until[account_id] = time.monotonic() + cooldown_sec
                logger.warning(
                    "wallet_refresh_attempt error_code=%s cooldown_sec=%.0f duration_ms=%.0f request_id=%s account_id=%s",
                    code, cooldown_sec, duration_ms, request_id, account_id,
                )
                return {"_error": err_str}
        except Exception:
            pass
        if _is_rate_limit_error(e):
            code = "BINANCE_RATE_LIMIT"
            cooldown_sec = _cooldown_sec_for_rate_limit(e, cfg.get("wallet_cooldown_sec", 30))
            _wallet_last_error_code[account_id] = code
            _wallet_cooldown_until[account_id] = time.monotonic() + cooldown_sec
            logger.warning(
                "wallet_refresh_attempt error_code=%s cooldown_sec=%.0f duration_ms=%.0f request_id=%s account_id=%s",
                code, cooldown_sec, duration_ms, request_id, account_id,
            )
            return {"_error": err_str}
        elif "-1021" in err_str or "timestamp" in err_str.lower():
            code = "CLOCK_DRIFT"
            _wallet_last_error_code[account_id] = code
            _wallet_cooldown_until[account_id] = time.monotonic() + cfg.get("wallet_cooldown_sec", 30)
            logger.warning(
                "wallet_refresh_attempt error_code=%s duration_ms=%.0f request_id=%s account_id=%s",
                code, duration_ms, request_id, account_id,
            )
            return {"_error": "Sunucu saati Binance ile uyuşmuyor (-1021). Windows: w32tm /resync ile NTP senkronizasyonu yapın.", "code": code}
        else:
            from app.services.binance_assets import KEY_ERROR_CODES
            code = err_str if isinstance(e, ValueError) else type(e).__name__
            _wallet_last_error_code[account_id] = code
            logger.warning(
                "wallet_refresh_attempt error_code=%s duration_ms=%.0f request_id=%s account_id=%s",
                code, duration_ms, request_id, account_id,
            )
            out = {"_error": err_str}
            if isinstance(e, ValueError) and code in KEY_ERROR_CODES:
                out["code"] = code
                out["_error_code"] = code
            return out

    if not isinstance(wallet_raw, dict) or wallet_raw.get("_error"):
        return wallet_raw

    # Write AssetSnapshot
    try:
        total_usd = float(wallet_raw.get("total_usd") or 0)
        breakdown = {}
        for a in (wallet_raw.get("assets") or []):
            asset = (a.get("asset") or "").strip()
            if not asset:
                continue
            free = float(a.get("free") or 0)
            locked = float(a.get("locked") or 0)
            value_usd = a.get("total_usd") or a.get("value_usd")
            usd_val = float(value_usd) if value_usd is not None else None
            price_used = a.get("price_usd")
            breakdown[asset] = {
                "free": free,
                "locked": locked,
                "total": free + locked,
                "usdValue": usd_val,
                "priceUsed": float(price_used) if price_used is not None else None,
            }
        snap = AssetSnapshot(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            total_usd_value=total_usd,
            breakdown_json=json.dumps(breakdown),
            source="binance",
        )
        db.add(snap)
        db.commit()
    except Exception as e:
        logger.warning("[home] wallet refresh write snapshot failed account_id=%s: %s", account_id, e)
        try:
            db.rollback()
        except Exception:
            pass

    duration_ms = (time.perf_counter() - t0) * 1000
    ts_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _wallet_last_live_at[account_id] = time.monotonic()
    _wallet_last_live_at_iso[account_id] = ts_iso
    _wallet_cooldown_until.pop(account_id, None)
    _wallet_last_error_code.pop(account_id, None)
    # Return full wallet (locked_usd, bot_locked_usd, assets[].locked, assets[].bot_locked) so strip and table show correctly
    out = dict(wallet_raw)
    out["ts"] = ts_iso
    assets_out = (out.get("assets") or [])[:]
    out["assets"] = _sort_and_cap_assets(assets_out, max_assets)
    _in_memory_wallet[account_id] = (out, time.monotonic())
    asset_count = len(out.get("assets") or [])
    logger.info(
        "wallet_refresh_success asset_count=%s total_usd=%s request_id=%s account_id=%s duration_ms=%.0f",
        asset_count, out.get("total_usd"), request_id, account_id, duration_ms,
    )
    return out


@router.post("/home/wallet/refresh")
async def home_wallet_refresh(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    force: int = Query(0, description="1 to bypass TTL (still respects cooldown and inflight)"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Start wallet refresh if allowed (TTL + cooldown + inflight dedup). May call Binance.
    Returns wallet_live when done; or skipped/inflight with cached.
    """
    t0 = time.perf_counter()
    request_id = getattr(request.state, "request_id", None) or ""
    require_account_access(current, account_id)

    cfg = get_config()
    ttl_sec = cfg.get("wallet_live_ttl_sec", 5)
    cooldown_sec = cfg.get("wallet_cooldown_sec", 30)
    max_assets = cfg.get("home_fast_max_assets", 20)
    now_mono = time.monotonic()

    # Cached response for skip cases (enrich DB snapshot with bot_locked so strip/table show correctly)
    wallet_cached, wallet_cached_at = None, None
    w = _get_last_wallet_snapshot_sync(db, account_id, max_assets)
    if w[0]:
        _enrich_minimal_wallet_with_bot_locked(w[0], account_id, db)
        wallet_cached, wallet_cached_at = w[0], w[1]
    if _in_memory_wallet.get(account_id):
        mem_w, _ = _in_memory_wallet[account_id]
        wallet_cached = wallet_cached or mem_w
        wallet_cached_at = wallet_cached_at or mem_w.get("ts")

    # Cooldown
    cooldown_until = _wallet_cooldown_until.get(account_id)
    if cooldown_until is not None and now_mono < cooldown_until and force != 1:
        server_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s skipped=true reason=cooldown server_ms=%.2f",
            account_id, request_id, server_ms,
        )
        return {
            "ok": True,
            "data": {
                "wallet_live": wallet_cached,
                "wallet_live_at": wallet_cached_at,
                "skipped": True,
                "inflight": False,
                "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
            },
            "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
        }

    # TTL skip (unless force)
    last_at = _wallet_last_live_at.get(account_id)
    if last_at is not None and (now_mono - last_at) < ttl_sec and force != 1:
        server_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s skipped=true reason=ttl server_ms=%.2f",
            account_id, request_id, server_ms,
        )
        return {
            "ok": True,
            "data": {
                "wallet_live": wallet_cached,
                "wallet_live_at": wallet_cached_at,
                "skipped": True,
                "inflight": False,
                "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
            },
            "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
        }

    # Inflight dedup
    if _is_wallet_refresh_inflight(account_id):
        server_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s skipped=true reason=inflight server_ms=%.2f",
            account_id, request_id, server_ms,
        )
        return {
            "ok": True,
            "data": {
                "wallet_live": wallet_cached,
                "wallet_live_at": wallet_cached_at,
                "skipped": True,
                "inflight": True,
                "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
            },
            "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
        }

    lock = _get_lock(account_id)
    async with lock:
        if _is_wallet_refresh_inflight(account_id):
            server_ms = (time.perf_counter() - t0) * 1000
            return {
                "ok": True,
                "data": {
                    "wallet_live": wallet_cached,
                    "wallet_live_at": wallet_cached_at,
                    "skipped": True,
                    "inflight": True,
                    "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
                },
                "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
            }
        task = asyncio.create_task(_do_wallet_refresh(account_id, db, request_id, force))
        _wallet_refresh_inflight[account_id] = task

    try:
        result = await asyncio.wait_for(task, timeout=8.0)  # inner budget 6s + margin
    except asyncio.TimeoutError:
        result = {"_error": "timeout"}
    finally:
        if account_id in _wallet_refresh_inflight and _wallet_refresh_inflight[account_id] == task:
            _wallet_refresh_inflight.pop(account_id, None)

    server_ms = (time.perf_counter() - t0) * 1000
    if result.get("_error"):
        last_code = _wallet_last_error_code.get(account_id)
        err_str = str(result.get("_error", ""))
        # API anahtarı yok/geçersiz: manager panelinde hata kalabalığı olmasın (DEBUG)
        is_api_key_error = "401" in err_str or "Unauthorized" in err_str or "Invalid API-key" in err_str or "invalid_api_key" in err_str.lower()
        if is_api_key_error:
            logger.debug(
                "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s error=api_key_invalid server_ms=%.2f",
                account_id, request_id, server_ms,
            )
        else:
            logger.info(
                "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s skipped=false inflight=false error=%s server_ms=%.2f",
                account_id, request_id, err_str, server_ms,
            )
        return {
            "ok": True,
            "data": {
                "wallet_live": wallet_cached,
                "wallet_live_at": wallet_cached_at,
                "skipped": False,
                "inflight": False,
                "stale": True,
                "last_error_code": last_code,
                "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
            },
            "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
        }

    logger.info(
        "home_wallet_refresh event=home_wallet_refresh account_id=%s request_id=%s skipped=false inflight=false server_ms=%.2f",
        account_id, request_id, server_ms,
    )
    if result and isinstance(result, dict):
        log_wallet_trace(
            event="wallet_payload_out",
            request_id=request_id or "",
            account_id=account_id,
            source="wallet_refresh_live",
            keys_configured=True,
            asset_count=len(result.get("assets") or []),
            total_usd=result.get("total_usd"),
            free_usd=result.get("free_usd"),
            locked_usd=result.get("locked_usd"),
            cache_hit=False,
            upstream_call=True,
            duration_ms=server_ms,
        )
    return {
        "ok": True,
        "data": {
            "wallet_live": result,
            "wallet_live_at": result.get("ts"),
            "skipped": False,
            "inflight": False,
            "refresh_policy": {"ttl_sec": ttl_sec, "cooldown_sec": cooldown_sec},
        },
        "meta": {"request_id": request_id, "server_ms": round(server_ms, 2)},
    }


@router.get("/home/wallet/status")
async def home_wallet_status(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Return inflight, last_live_at, cooldown_until, last_error_code, keys_configured, last_snapshot_at (no Binance call)."""
    request_id = getattr(request.state, "request_id", None) or ""
    require_account_access(current, account_id)
    cfg = get_config()
    cooldown_sec = cfg.get("wallet_cooldown_sec", 30)
    now_mono = time.monotonic()
    cooldown_until = _wallet_cooldown_until.get(account_id)
    last_iso = _wallet_last_live_at_iso.get(account_id)
    cooldown_iso = None
    if cooldown_until is not None and cooldown_until > now_mono:
        from datetime import timedelta
        cooldown_iso = (datetime.now(timezone.utc) + timedelta(seconds=cooldown_until - now_mono)).isoformat().replace("+00:00", "Z")

    keys_configured = False
    last_snapshot_at = None
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            ek = getattr(acc, "api_key_enc", None)
            es = getattr(acc, "api_secret_enc", None)
            keys_configured = bool(ek and es and (not isinstance(ek, str) or ek.strip()) and (not isinstance(es, str) or es.strip()))
        row = db.query(AssetSnapshot).filter(AssetSnapshot.account_id == account_id).order_by(desc(AssetSnapshot.timestamp)).limit(1).first()
        if row and row.timestamp:
            last_snapshot_at = row.timestamp.isoformat().replace("+00:00", "Z") if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception as e:
        logger.debug("[home] wallet/status keys/snapshot check error: %s", e)

    return {
        "ok": True,
        "data": {
            "inflight": _is_wallet_refresh_inflight(account_id),
            "last_live_at": last_iso,
            "cooldown_until": cooldown_iso,
            "last_error_code": _wallet_last_error_code.get(account_id),
            "keys_configured": keys_configured,
            "last_snapshot_at": last_snapshot_at,
        },
        "meta": {"request_id": request_id},
    }
