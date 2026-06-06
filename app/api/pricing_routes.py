"""
Üst ticker şeridi: GET /api/pricing/summary
Canlı FX, metals, crypto; cache TTL ve in-flight dedupe backend'de.
"""

from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.pricing_summary import get_summary

router = APIRouter()


@router.get("/summary")
async def pricing_summary():
    """
    Ticker bar için tek özet: usdtry, eurtry, gbptry, btcusd, ethusd,
    xauusd, gram_altin_tl, ons_altin_usd, source_status.
    Değer yoksa null; 0 basılmaz. Cache nedeniyle dış API spam yok.
    """
    data = await get_summary()
    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
