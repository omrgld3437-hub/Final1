"""
Dashboard Bootstrap — single fast endpoint for initial load (desktop + mobile).
GET /api/dashboard/bootstrap?account_id=...
Returns: prices (cached), kpis (cached/derived), wallet_cached (DB snapshot), wallet_status.
MUST NOT call Binance. Target <300ms typical.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import require_auth, require_account_access
from app.db.session import get_db
from app.db.models import Account

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/dashboard/bootstrap")
async def dashboard_bootstrap(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Single boot endpoint: cached prices, kpis, wallet_cached, wallet_status.
    No Binance. Fast (<300ms typical). Same response shape for desktop and mobile.
    """
    t0 = time.perf_counter()
    request_id = getattr(request.state, "request_id", None) or ""
    require_account_access(current, account_id)

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Account not found")

    # keys_configured from Account
    ek = getattr(account, "api_key_enc", None)
    es = getattr(account, "api_secret_enc", None)
    keys_configured = bool(
        ek
        and es
        and (not isinstance(ek, str) or ek.strip())
        and (not isinstance(es, str) or es.strip())
    )

    # Wallet status: last_error_code, cooldown_until from home state (if loaded)
    last_error_code = None
    cooldown_until_iso = None
    try:
        import app.api.routes.home as home_mod

        last_error_code = getattr(home_mod, "_wallet_last_error_code", {}).get(
            account_id
        )
        cooldown_until = getattr(home_mod, "_wallet_cooldown_until", {}).get(account_id)
        if cooldown_until is not None:
            from datetime import timedelta

            now_mono = time.monotonic()
            if cooldown_until > now_mono:
                delta_sec = cooldown_until - now_mono
                cooldown_until_iso = (
                    (
                        datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
                        + timedelta(seconds=delta_sec)
                    )
                    .isoformat()
                    .replace("+00:00", "Z")
                )
    except Exception:
        pass

    wallet_status = {
        "keys_configured": keys_configured,
        "last_error_code": last_error_code,
        "cooldown_until": cooldown_until_iso,
    }

    loop = asyncio.get_running_loop()
    max_assets = 20

    # Prices: sync DataHub (no network)
    def _get_prices():
        try:
            from app.services.data_hub import data_hub

            return data_hub.get_all_prices() or {}
        except Exception:
            return {}

    # Wallet: test paper veya snapshot+bot_locked enrich (bootstrap'ta ham snapshot ETH total=0 hatası önlenir)
    def _get_wallet():
        try:
            from app.api.routes.home import _get_wallet_cached_enriched_with_new_session

            return _get_wallet_cached_enriched_with_new_session(account_id, max_assets)
        except Exception as e:
            logger.debug("[bootstrap] wallet snapshot error: %s", e)
            return (None, None)

    from app.services.dashboard_snapshot import fetch_bot_cards_fast

    prices_task = loop.run_in_executor(None, _get_prices)
    wallet_task = loop.run_in_executor(None, _get_wallet)
    bots_task = asyncio.create_task(fetch_bot_cards_fast(account_id))
    prices, wallet_result, bots = await asyncio.gather(
        prices_task, wallet_task, bots_task
    )
    wallet_cached, wallet_cached_at = wallet_result

    # İlk çizimde ağır geçmiş/KPI sorgusu yok; canlı kanal bunları arkada yeniler.
    try:
        total_current = sum(float(bot.get("current_usd") or 0) for bot in bots)
        total_initial = sum(float(bot.get("initial_usd") or 0) for bot in bots)
        kpis = {
            "total_bots": len(bots),
            "active_bots": sum(
                1
                for bot in bots
                if str(bot.get("display_status") or bot.get("status")).lower()
                in ("running", "starting")
            ),
            "total_pnl_usd": round(total_current - total_initial, 2),
        }
    except Exception:
        kpis = {}

    server_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "dashboard_bootstrap_served account_id=%s request_id=%s server_ms=%.2f",
        account_id,
        request_id,
        server_ms,
    )

    return {
        "ok": True,
        "data": {
            "prices": prices,
            "bots": bots,
            "kpis": kpis,
            "wallet_cached": wallet_cached,
            "wallet_cached_at": wallet_cached_at,
            "wallet_status": wallet_status,
        },
        "meta": {
            "request_id": request_id,
            "server_ms": round(server_ms, 2),
        },
    }
