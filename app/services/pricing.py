# app/services/pricing.py
from __future__ import annotations
from typing import Dict, Any, List
import httpx
import asyncio

BINANCE_PUBLIC = "https://api.binance.com"

# Basit public price fetch (UI tickerbar için)
async def fetch_binance_price(symbol: str) -> float | None:
    url = f"{BINANCE_PUBLIC}/api/v3/ticker/price"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            return float(data["price"])
    except:
        return None

async def build_tickerbar() -> List[Dict[str, Any]]:
    """
    UI'daki üst bar için örnek:
    USDTTRY, EURTRY, BTCUSDT, ETHUSDT... vs
    BTC/USD, ETH/USD gibi label gösterimi frontend'de yapılabilir.
    """
    symbols = [
        ("USDTTRY", "USDT/TRY"),
        ("EURTRY", "EUR/TRY"),
        ("BTCUSDT", "BTC/USD"),
        ("ETHUSDT", "ETH/USD"),
        ("GBPTRY", "GBP/TRY"),
    ]

    # Altınlar Binance'te yoksa: sabit placeholder ya da kendi kaynağın.
    # Şimdilik None döndürüyoruz; UI "—" gösterebilir.
    pseudo = [
        ("XAUTRY", "Gram Altın (TL)"),
        ("XAUUSD", "Ons Altın (USD)"),
    ]

    async def one(sym: str, label: str):
        # Altınlar için şimdilik None
        if sym in {"XAUTRY", "XAUUSD"}:
            return {"symbol": sym, "label": label, "price": None, "chg_pct": None}
        
        # EUR/TRY ve GBP/TRY için conversion
        if sym == "EURTRY":
            eur_usdt = await fetch_binance_price("EURUSDT")
            usdt_try = await fetch_binance_price("USDTTRY")
            if eur_usdt and usdt_try:
                price = eur_usdt * usdt_try
                return {"symbol": sym, "label": label, "price": price, "chg_pct": None}
            return {"symbol": sym, "label": label, "price": None, "chg_pct": None}
        
        if sym == "GBPTRY":
            gbp_usdt = await fetch_binance_price("GBPUSDT")
            usdt_try = await fetch_binance_price("USDTTRY")
            if gbp_usdt and usdt_try:
                price = gbp_usdt * usdt_try
                return {"symbol": sym, "label": label, "price": price, "chg_pct": None}
            return {"symbol": sym, "label": label, "price": None, "chg_pct": None}
        
        price = await fetch_binance_price(sym)
        return {"symbol": sym, "label": label, "price": price, "chg_pct": None}

    tasks = [one(s, l) for s, l in symbols] + [one(s, l) for s, l in pseudo]
    return await asyncio.gather(*tasks)

