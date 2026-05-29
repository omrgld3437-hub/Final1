"""Market data SSOT — fiyat/24h okuma (Binance REST doğrudan değil, DataHub cache)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def get_price(symbol: str) -> Optional[float]:
    from app.services.data_hub import data_hub
    return data_hub.get_price(symbol)


def resolve_price_fast(symbol: str) -> Tuple[Optional[float], str, bool]:
    """
    Spot/UI fiyat: spot_cache → DataHub (stale dahil).
    Returns (price, source, is_stale). Binance REST yok.
    """
    from app.services.spot_engine import spot_cache
    from app.services.data_hub import data_hub

    sym = (symbol or "").strip().upper()
    if not sym:
        return None, "none", False
    cached = spot_cache.get_price(sym)
    if cached is not None and cached > 0:
        return cached, "spot_cache", False
    meta = data_hub.get_price_with_meta(sym)
    if meta and (meta.get("price") or 0) > 0:
        p = float(meta["price"])
        spot_cache.set_price(sym, p)
        return p, "data_hub", bool(meta.get("is_stale"))
    return None, "none", False


def get_price_with_meta(symbol: str) -> Optional[Dict[str, Any]]:
    from app.services.data_hub import data_hub
    return data_hub.get_price_with_meta(symbol)


def get_all_prices() -> Dict[str, Dict[str, Any]]:
    from app.services.data_hub import data_hub
    return data_hub.get_all_prices()


def get_price_map_flat() -> Dict[str, float]:
    """Sembol → USDT fiyat (DataHub cache). Cüzdan/finance USD değerlemesi."""
    out: Dict[str, float] = {}
    for sym, meta in (get_all_prices() or {}).items():
        if not isinstance(meta, dict):
            continue
        try:
            p = float(meta.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            out[str(sym).upper()] = p
    for stable in ("USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"):
        out.setdefault(stable, 1.0)
        out.setdefault(f"{stable}USDT", 1.0)
    return out


def get_ticker_24h(symbol: str) -> Dict[str, Any]:
    """
    24s özet — yalnızca DataHub cache. Binance'e istek atmaz.
    spot_routes / bot detail / UI için.
    """
    sym = (symbol or "").upper().strip()
    from app.services.data_hub import data_hub
    meta = data_hub.get_price_with_meta(sym)
    pct = data_hub.get_change24h_pct(sym)
    if not meta and pct is None:
        return {
            "lowPrice": None,
            "highPrice": None,
            "priceChangePercent": None,
            "lastPrice": None,
            "is_stale": True,
            "available": False,
        }
    return {
        "lowPrice": float(meta.get("low24h") or 0) if meta and meta.get("low24h") is not None else None,
        "highPrice": float(meta.get("high24h") or 0) if meta and meta.get("high24h") is not None else None,
        "priceChangePercent": round(pct, 2) if pct is not None else None,
        "lastPrice": float(meta.get("price") or 0) if meta and meta.get("price") else None,
        "is_stale": bool(meta.get("is_stale")) if meta else True,
        "available": pct is not None,
    }


def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    """exchangeInfo cache — Binance REST yok."""
    from app.services.data_hub import data_hub
    return data_hub.get_symbol_filters_cached(symbol)


def get_coin_list() -> List[Dict[str, Any]]:
    from app.services.data_hub import data_hub
    return data_hub.get_coin_list()


def get_symbols(scope: str = "usdt") -> List[str]:
    from app.services.data_hub import data_hub
    return data_hub.get_symbols_for_scope(scope)


def import_from_peer_snapshot(prices: Dict[str, Any]) -> int:
    """Worker: web sürecindeki /api/data/prices snapshot'ını yerel cache'e kopyala."""
    from app.services.data_hub import data_hub
    return data_hub.import_prices_snapshot(prices)


async def refresh_worker_symbol_from_web(symbol: str) -> Optional[float]:
    """Worker: tek sembol fiyatı web'den çek (slim cache miss sonrası)."""
    import os
    import httpx
    from app.services.data_hub import data_hub

    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    base = (os.getenv("WEB_INTERNAL_URL") or "http://127.0.0.1:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"{base}/api/data/prices",
                params={"slim": 1, "symbols": sym},
            )
        if r.status_code == 200:
            import_from_peer_snapshot(r.json())
            data_hub.pin_symbols([sym])
            return data_hub.get_price(sym)
    except Exception:
        pass
    return None


def hub_status() -> Dict[str, Any]:
    from app.services.data_hub import data_hub
    return data_hub.get_status()
