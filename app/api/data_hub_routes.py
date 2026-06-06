"""
FILE: data_hub_routes.py
VERSION: v2.0
DATE: 2026-01-23
CHANGE: Rate-limit safe with cache + TTL + in-flight dedupe + degrade mode
"""
from fastapi import APIRouter, Depends, Query, Request
from typing import Literal
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import time
import uuid
import logging
from app.db.session import get_db
from app.services.data_hub import data_hub

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/data/hub")
async def get_data_hub(
    account_id: Optional[int] = Query(None, description="Unused; balance from /api/binance/wallet only"),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    1s hub snapshot: prices, mini, coin_list, ts, data_status, stale_age_ms.
    No balance (use /api/binance/wallet). Cache-first; no Binance REST per request.
    """
    request_id = str(uuid.uuid4())[:8]
    try:
        hub_data = await data_hub.get_hub_data(None)
        hub_data["request_id"] = request_id
        if "mini" not in hub_data:
            hub_data["mini"] = {}
        if hub_data.get("data_status") == "stale":
            logger.warning(
                f"[DataHub] Stale (request_id={request_id}, "
                f"reason={hub_data.get('stale_reason', 'unknown')}, "
                f"age_ms={hub_data.get('stale_age_ms', 0)})"
            )
        return JSONResponse(content=hub_data)
    except Exception as e:
        logger.exception(f"[DataHub] Error (request_id={request_id}): {e}")
        return JSONResponse(
            status_code=200,
            content={
                "prices": {},
                "mini": {},
                "coin_list": [],
                "symbols": [],
                "ts": time.time(),
                "data_status": "empty",
                "stale_reason": "error",
                "stale_age_ms": 0,
                "request_id": request_id
            }
        )

@router.get("/datahub/status")
async def get_datahub_status():
    """WS state and stale counts for operators / UI indicator."""
    return data_hub.get_status()

@router.get("/data/prices")
async def get_prices():
    """Get all cached prices"""
    return data_hub.get_all_prices()

@router.get("/data/coin-list")
async def get_coin_list(
    scope: Literal["usdt", "all"] = Query("usdt", description="usdt = *USDT only, all = all TRADING pairs"),
):
    """Get cached coin list (top 100) + symbols from Binance exchangeInfo. scope=usdt (default) or all."""
    symbols = data_hub.get_symbols_for_scope(scope)
    return {
        "coins": data_hub.get_coin_list(),
        "symbols": symbols,
        "scope": scope,
        "ts": data_hub.coin_list_ts if scope == "usdt" else data_hub.all_symbols_ts,
    }
