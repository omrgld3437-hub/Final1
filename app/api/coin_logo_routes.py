"""Coin logo prefetch API."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.coin_logo_service import ensure_coin_logo, logo_public_path, normalize_logo_symbol

router = APIRouter(tags=["coins"])


@router.get("/coins/logo/ensure")
async def api_ensure_coin_logo(symbol: str = ""):
    """Logo yoksa bir kez indirmeyi dene (proaktif prefetch)."""
    key = normalize_logo_symbol(symbol)
    if not key:
        return {"ok": False, "symbol": symbol, "url": None}
    ok = ensure_coin_logo(key)
    url = logo_public_path(key) if ok else None
    return {"ok": ok, "symbol": key, "url": url}
