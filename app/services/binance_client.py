"""
FILE: binance_client.py
Sync facade for bot engines: uses binance_spot as single gateway (sync_public/sync_signed).
All Binance HTTP goes through binance_spot; no duplicate signature logic.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from app.services.binance_spot import (
    _sync_public_get,
    _sync_signed_request,
)
from app.services.binance_assets import BinanceKeys

logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    def __init__(self, message: str, code: Optional[int] = None):
        self.message = message
        self.code = code
        super().__init__(message)


class InsufficientBalanceError(BinanceAPIError):
    pass


class InvalidAPIKeyError(BinanceAPIError):
    pass


class NetworkError(BinanceAPIError):
    pass


def _keys(api_key: str, api_secret: str, testnet: bool = False) -> BinanceKeys:
    return BinanceKeys(api_key=api_key, api_secret=api_secret, testnet=testnet)


class BinanceClient:
    """Sync Binance Spot client for bots. All HTTP via binance_spot (single gateway)."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self._keys = _keys(api_key, api_secret, testnet)

    def get_ticker_price(self, symbol: str) -> float:
        """Current price from DataHub cache only. No per-symbol Binance REST."""
        try:
            from app.services.data_hub import data_hub
            p = data_hub.get_price(symbol.upper())
            return float(p) if p is not None and float(p) > 0 else 0.0
        except Exception as e:
            logger.warning("get_ticker_price %s: %s", symbol, e)
            return 0.0

    def get_exchange_info(self, symbol: str) -> Dict:
        """Exchange info for symbol (filters: LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL). Sync via binance_spot."""
        try:
            data = _sync_public_get("/api/v3/exchangeInfo", {"symbol": symbol.upper()}, self._keys.testnet)
            if not data or "symbols" not in data:
                return {"filters": []}
            for s in data.get("symbols", []):
                if s.get("symbol") == symbol.upper():
                    return {"filters": s.get("filters", [])}
            return {"filters": []}
        except Exception as e:
            logger.warning("get_exchange_info %s: %s", symbol, e)
            return {"filters": []}

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: Optional[float] = None,
        quote_order_qty: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place market order (sync)."""
        payload = {"symbol": symbol.upper(), "side": side.upper(), "type": "MARKET"}
        if quantity is not None:
            payload["quantity"] = str(quantity)
        if quote_order_qty is not None:
            payload["quoteOrderQty"] = str(quote_order_qty)
        try:
            return _sync_signed_request("POST", "/api/v3/order", self._keys, payload)
        except Exception as e:
            err_str = str(e).lower()
            if "insufficient" in err_str or "balance" in err_str:
                raise InsufficientBalanceError(str(e)) from e
            if "api-key" in err_str or "unauthorized" in err_str or "401" in str(e):
                raise InvalidAPIKeyError(str(e)) from e
            if "network" in err_str or "timeout" in err_str or "connection" in err_str:
                raise NetworkError(str(e)) from e
            raise BinanceAPIError(str(e)) from e

    def get_balance(self, asset: str) -> float:
        """Free balance for asset (sync)."""
        try:
            data = _sync_signed_request("GET", "/api/v3/account", self._keys, {})
            for b in data.get("balances", []):
                if (b.get("asset") or "").strip().upper() == asset.strip().upper():
                    return float(b.get("free", 0) or 0)
            return 0.0
        except Exception as e:
            logger.warning("get_balance %s: %s", asset, e)
            raise
