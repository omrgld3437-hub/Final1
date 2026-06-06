"""
Price Hub - Thin wrapper over DataHub. No per-symbol Binance REST calls.
update_price() DataHub'a yazar (tek SSOT); get_price() doğrudan DataHub'dan okur.
"""

import time as _time
from typing import Dict, Optional


class PriceHub:
    """DataHub üzerinde thin shim — geriye dönük uyumluluk için."""

    def update_price(self, symbol: str, price: float) -> None:
        """DataHub cache'ini doğrudan güncelle."""
        try:
            from app.services.data_hub import data_hub

            sym = (symbol or "").strip().upper()
            if sym and price and float(price) > 0:
                prev = data_hub.prices.get(sym) or {}
                data_hub.prices[sym] = {
                    **prev,
                    "price": float(price),
                    "ts": _time.time(),
                }
        except Exception:
            pass

    def get_price(self, symbol: str) -> Optional[float]:
        """DataHub'dan oku (trading stale eşiği: BinanceAdapter'da 30s). Burada serve-stale yok."""
        try:
            from app.services.data_hub import data_hub

            sym = (symbol or "").strip().upper()
            if not sym:
                return None
            d = data_hub.get_price_with_meta(sym)
            if not d:
                return None
            p = d.get("price")
            if p is None or float(p) <= 0:
                return None
            return float(p)
        except Exception:
            return None

    async def fetch_price(
        self, symbol: str, client: Optional[object] = None
    ) -> Optional[float]:
        """DataHub bulk refresh → get_price. Geriye dönük uyumluluk."""
        p = self.get_price(symbol)
        if p and p > 0:
            return p
        try:
            from app.services.data_hub import data_hub

            await data_hub.refresh_all_prices_bulk()
            return self.get_price(symbol)
        except Exception:
            return None

    def get_all_prices(self) -> Dict[str, float]:
        """Tüm DataHub fiyatları (stale dahil — UI kullanımı için)."""
        try:
            from app.services.data_hub import data_hub

            return {
                sym: float(d.get("price") or 0)
                for sym, d in data_hub.prices.items()
                if d.get("price") and float(d.get("price") or 0) > 0
            }
        except Exception:
            return {}


# Global instance
price_hub = PriceHub()
