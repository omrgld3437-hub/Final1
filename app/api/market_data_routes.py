"""
FILE: market_data_routes.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: Market data REST endpoints (snapshot)
"""
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
import logging

# Optional Binance imports - will be added later
try:
    from app.services.binance_market_data import get_market_data
except ImportError:
    get_market_data = None

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/market-data/snapshot")
async def get_market_snapshot(
    symbols: Optional[str] = Query(None, description="Comma-separated symbols (e.g., BTCUSDT,ETHUSDT)")
):
    """
    Get price snapshot for symbols (REST endpoint)
    """
    try:
        if not get_market_data:
            return {}
        
        market_data = get_market_data()
        
        if not symbols:
            return {}
        
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return {}
        
        snapshot = await market_data.get_snapshot(symbol_list)
        return snapshot
        
    except Exception as e:
        logger.error(f"[MarketData] Snapshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
