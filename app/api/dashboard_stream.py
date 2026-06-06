"""
Dashboard Server-Sent Events — snapshot polling yerine tek kalıcı bağlantı.
GET /api/dashboard/stream?account_id=&fields=prices,wallet,bots,kpis
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import require_auth, require_account_access
from app.db.session import get_db
from app.db.models import Account

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

_SSE_INTERVAL_SEC = float(os.environ.get("DASHBOARD_SSE_INTERVAL_SEC", "3"))
_SSE_ENABLED = os.environ.get("DASHBOARD_SSE_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
_DEFAULT_FIELDS = ["prices", "wallet", "bots", "kpis"]
_ALLOWED = frozenset(_DEFAULT_FIELDS)


def dashboard_sse_enabled() -> bool:
    return _SSE_ENABLED


def _parse_fields(fields_param: Optional[str]) -> List[str]:
    if not fields_param or not fields_param.strip():
        return _DEFAULT_FIELDS.copy()
    parts = [p.strip().lower() for p in fields_param.split(",") if p.strip()]
    invalid = [p for p in parts if p not in _ALLOWED]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_FIELDS",
                "message": "Unknown SSE fields",
                "invalid_fields": invalid,
                "allowed": sorted(_ALLOWED),
            },
        )
    return parts or _DEFAULT_FIELDS.copy()


async def _build_sse_payload(
    account_id: int, fields: List[str], db: Session, request_id: str
) -> dict:
    """Snapshot ile uyumlu { ok, data, meta }."""
    from app.api.routes import (
        _enrich_snapshot_wallet_with_bot_locked,
        _get_snapshot_wallet_cached,
    )
    from app.services.dashboard_snapshot import (
        fetch_prices,
        fetch_bots_and_account_kpis,
        fetch_finance_pnl,
    )

    t0 = time.perf_counter()
    data: dict = {"server_ts": time.time()}
    tasks = []
    names: List[str] = []
    if "prices" in fields:
        tasks.append(fetch_prices())
        names.append("prices")
    if "bots" in fields or "kpis" in fields:
        tasks.append(fetch_bots_and_account_kpis(account_id, db))
        names.append("bots")
    if "kpis" in fields:
        tasks.append(fetch_finance_pnl(account_id, db))
        names.append("pnl")

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    by_name = {}
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            by_name[name] = {"_error": str(res)}
        else:
            by_name[name] = res

    if "prices" in fields:
        raw = by_name.get("prices", {})
        data["prices"] = raw if isinstance(raw, dict) and "_error" not in raw else {}

    bots_raw = by_name.get("bots", {})
    if "bots" in fields and isinstance(bots_raw, dict) and "_error" not in bots_raw:
        data["bots"] = bots_raw.get("bots") or []

    if "kpis" in fields:
        pnl_raw = by_name.get("pnl", {})
        account_kpis = bots_raw.get("account", {}) if isinstance(bots_raw, dict) else {}
        pnl = pnl_raw if isinstance(pnl_raw, dict) and "_error" not in pnl_raw else {}
        data["kpis"] = {"account": account_kpis, "pnl": pnl}

    if "wallet" in fields:
        try:
            from app.services.test_account import is_test_account

            if is_test_account(account_id, db):
                from app.services.wallet_display import build_test_account_wallet

                data["wallet"] = build_test_account_wallet(account_id, db)
            else:
                wallet_cached, wallet_ts_iso, _src, _age = _get_snapshot_wallet_cached(
                    account_id, db
                )
                if wallet_cached:
                    wallet = dict(wallet_cached)
                    if wallet_ts_iso:
                        wallet["ts"] = wallet_ts_iso
                    _enrich_snapshot_wallet_with_bot_locked(wallet, account_id, db)
                    data["wallet"] = wallet
                else:
                    data["wallet"] = {}
        except Exception as e:
            logger.debug("dashboard_sse wallet skip account_id=%s: %s", account_id, e)
            data["wallet"] = {}

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {
        "ok": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "server_ms": round(elapsed_ms, 2),
            "transport": "sse",
        },
    }


@router.get("/dashboard/stream")
async def dashboard_stream(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
    fields: Optional[str] = Query(
        None, description="Comma-separated: prices,wallet,bots,kpis"
    ),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """SSE kanalı — dashboard snapshot verisi (auth + account erişimi zorunlu)."""
    if not _SSE_ENABLED:
        raise HTTPException(status_code=503, detail="Dashboard SSE disabled")
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    requested = _parse_fields(fields)
    request_id = getattr(request.state, "request_id", None) or ""

    async def event_generator() -> AsyncIterator[str]:
        from app.db.session import SessionLocal

        try:
            while True:
                if await request.is_disconnected():
                    break
                tick_db = SessionLocal()
                try:
                    payload = await _build_sse_payload(
                        account_id, requested, tick_db, request_id
                    )
                    yield f"data: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"
                except Exception as e:
                    logger.warning(
                        "dashboard_sse tick error account_id=%s: %s: %s",
                        account_id,
                        type(e).__name__,
                        e,
                    )
                    err = {"ok": False, "error": str(e)[:200]}
                    yield f"event: error\ndata: {json.dumps(err)}\n\n"
                finally:
                    tick_db.close()
                await asyncio.sleep(_SSE_INTERVAL_SEC)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
