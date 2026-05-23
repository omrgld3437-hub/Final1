"""
Piyasa verisi — tek okuma kaynağı (SSOT read).

Binance'e REST/WS ile giden tek ingest: app.services.data_hub (REST leader + WS).
Bu modül dışındaki kod Binance public ticker/price çağırmamalı; cache'ten okur.

Signed veri (cüzdan, emir): app.services.binance_spot (hesap bazlı cache).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_price(symbol: str) -> Optional[float]:
    from app.services.data_hub import data_hub
    return data_hub.get_price(symbol)


def get_price_with_meta(symbol: str) -> Optional[Dict[str, Any]]:
    from app.services.data_hub import data_hub
    return data_hub.get_price_with_meta(symbol)


def get_all_prices() -> Dict[str, Dict[str, Any]]:
    from app.services.data_hub import data_hub
    return data_hub.get_all_prices()


def get_price_map_flat() -> Dict[str, float]:
    """symbol -> price (USD/USDT paritesi). Cüzdan / snapshot için."""
    out: Dict[str, float] = {}
    for sym, d in get_all_prices().items():
        p = d.get("price") if isinstance(d, dict) else None
        if p is not None and float(p) > 0:
            out[sym.upper()] = float(p)
    return out


def get_ticker_24h(symbol: str) -> Dict[str, Any]:
    """
    24s özet — yalnızca DataHub cache. Binance'e istek atmaz.
    spot_routes / bot detail / UI için.
    """
    sym = (symbol or "").upper().strip()
    meta = get_price_with_meta(sym)
    if not meta:
        return {
            "lowPrice": 0.0,
            "highPrice": 0.0,
            "priceChangePercent": 0.0,
            "lastPrice": 0.0,
            "is_stale": True,
        }
    return {
        "lowPrice": float(meta.get("low24h") or 0),
        "highPrice": float(meta.get("high24h") or 0),
        "priceChangePercent": float(meta.get("change24h") or 0),
        "lastPrice": float(meta.get("price") or 0),
        "is_stale": bool(meta.get("is_stale")),
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


def hub_status() -> Dict[str, Any]:
    from app.services.data_hub import data_hub
    return data_hub.get_status()
