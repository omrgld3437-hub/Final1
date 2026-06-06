"""
Price Hub - Cache populated by DataHub bulk refresh. No per-symbol Binance REST calls.
"""
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta


class PriceHub:
    """Centralized price cache and manager"""

    def __init__(self):
        self._cache: Dict[str, Dict] = {}  # symbol -> {price, updated_at}
        self._cache_ttl = 5  # seconds

    def update_price(self, symbol: str, price: float):
        """Update price in cache"""
        self._cache[symbol] = {
            "price": price,
            "updated_at": datetime.utcnow()
        }

    def get_price(self, symbol: str) -> Optional[float]:
        """Get price from cache if fresh"""
        if symbol not in self._cache:
            return None
        
        cached = self._cache[symbol]
        age = (datetime.utcnow() - cached["updated_at"]).total_seconds()
        
        if age > self._cache_ttl:
            return None
        
        return cached["price"]

    async def fetch_price(self, symbol: str, client: Optional[object] = None) -> Optional[float]:
        """Fetch price via DataHub bulk refresh. No per-symbol REST calls."""
        cached = self.get_price(symbol)
        if cached:
            return cached
        try:
            from app.services.data_hub import data_hub
            await data_hub.refresh_all_prices_bulk()
            p = data_hub.get_price(symbol)
            if p is not None:
                self.update_price(symbol, float(p))
                return float(p)
        except Exception:
            pass
        return None

    def get_all_prices(self) -> Dict[str, float]:
        """Get all cached prices"""
        now = datetime.utcnow()
        result = {}
        for symbol, data in self._cache.items():
            age = (now - data["updated_at"]).total_seconds()
            if age <= self._cache_ttl:
                result[symbol] = data["price"]
        return result


# Global instance
price_hub = PriceHub()
