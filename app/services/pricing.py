"""
pricing modulu (services/).
Fiyatlar: market_data (DataHub cache) — Binance REST yok.
"""
from __future__ import annotations
from typing import Dict, Any, List
import asyncio

from app.services.market_data import get_price


async def fetch_binance_price(symbol: str) -> float | None:
    return get_price(symbol)


async def build_tickerbar() -> List[Dict[str, Any]]:
    """
    UI'daki üst bar için örnek:
    USDTTRY, EURTRY, BTCUSDT, ETHUSDT... vs
    """
    symbols = [
        ("USDTTRY", "USDT/TRY"),
        ("EURTRY", "EUR/TRY"),
        ("BTCUSDT", "BTC/USD"),
        ("ETHUSDT", "ETH/USD"),
        ("GBPTRY", "GBP/TRY"),
    ]

    pseudo = [
        ("XAUTRY", "Gram Altın (TL)"),
        ("XAUUSD", "Ons Altın (USD)"),
    ]

    async def one(sym: str, label: str):
        if sym in {"XAUTRY", "XAUUSD"}:
            return {"symbol": sym, "label": label, "price": None, "chg_pct": None}
        p = get_price(sym)
        return {"symbol": sym, "label": label, "price": p, "chg_pct": None}

    tasks = [one(sym, label) for sym, label in symbols + pseudo]
    return await asyncio.gather(*tasks)
