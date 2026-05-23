"""
FILE: spot_engine.py
VERSION: v1.0
DATE: 2026-01-22
CHANGE: YENİ - Bağımsız Spot Trading Engine - Flash Hızında
"""
from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
import math
import time
import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from app.services.binance_assets import BinanceKeys, get_account_keys
from app.services.binance_spot import BINANCE_API, BINANCE_TESTNET, _public_get, _signed_request

logger = logging.getLogger(__name__)

# ============================================================
# FLASH HIZLI CACHE - In-Memory Cache Layer
# ============================================================
class SpotCache:
    """Ultra-fast in-memory cache for spot trading data"""
    
    def __init__(self):
        self.prices: Dict[str, Tuple[float, float]] = {}  # symbol -> (price, timestamp)
        self.balances: Dict[int, Tuple[Dict, float]] = {}  # account_id -> (data, timestamp)
        self.filters: Dict[str, Tuple[Dict, float]] = {}   # symbol -> (data, timestamp)
        
        # TTL constants (seconds)
        self.PRICE_TTL = 1.0      # 1 second - very fresh
        self.BALANCE_TTL = 2.0    # 2 seconds
        self.FILTER_TTL = 3600.0  # 1 hour - rarely changes
        
    def get_price(self, symbol: str) -> Optional[float]:
        """Get cached price if fresh"""
        if symbol not in self.prices:
            return None
        price, ts = self.prices[symbol]
        if time.time() - ts > self.PRICE_TTL:
            del self.prices[symbol]
            return None
        return price
    
    def set_price(self, symbol: str, price: float):
        """Cache price"""
        self.prices[symbol] = (price, time.time())
    
    def get_balance(self, account_id: int) -> Optional[Dict]:
        """Get cached balance if fresh"""
        if account_id not in self.balances:
            return None
        data, ts = self.balances[account_id]
        if time.time() - ts > self.BALANCE_TTL:
            del self.balances[account_id]
            return None
        return data
    
    def set_balance(self, account_id: int, data: Dict):
        """Cache balance"""
        self.balances[account_id] = (data, time.time())
    
    def get_filters(self, symbol: str) -> Optional[Dict]:
        """Get cached filters if fresh"""
        if symbol not in self.filters:
            return None
        data, ts = self.filters[symbol]
        if time.time() - ts > self.FILTER_TTL:
            del self.filters[symbol]
            return None
        return data
    
    def set_filters(self, symbol: str, data: Dict):
        """Cache filters"""
        self.filters[symbol] = (data, time.time())

# Global cache instance
spot_cache = SpotCache()

# 400 cooldown: 3x 400 for a symbol -> 30s cooldown, skip Binance in that window
_BINANCE_400_COUNT: Dict[str, int] = {}
_BINANCE_400_LAST: Dict[str, float] = {}
_BINANCE_400_COOLDOWN_SEC = 30.0
_BINANCE_400_THRESHOLD = 3


def _record_binance_400(symbol: str) -> None:
    now = time.time()
    _BINANCE_400_COUNT[symbol] = _BINANCE_400_COUNT.get(symbol, 0) + 1
    if _BINANCE_400_COUNT[symbol] >= _BINANCE_400_THRESHOLD:
        _BINANCE_400_LAST[symbol] = now


def _is_symbol_in_400_cooldown(symbol: str) -> bool:
    last = _BINANCE_400_LAST.get(symbol)
    if last is None:
        return False
    if time.time() - last > _BINANCE_400_COOLDOWN_SEC:
        _BINANCE_400_LAST.pop(symbol, None)
        _BINANCE_400_COUNT.pop(symbol, None)
        return False
    return True


# ============================================================
# SPOT ENGINE - Flash Hızlı Trading Motoru
# ============================================================
@dataclass
class SpotData:
    """Spot trading data container"""
    symbol: str
    price: float
    price_change_24h: float
    base_asset: str
    quote_asset: str
    base_balance: float
    quote_balance: float
    tick_size: str
    step_size: str
    min_notional: str
    timestamp: float

class SpotEngine:
    """Bağımsız Spot Trading Engine - Flash Hızında"""
    
    def __init__(self, keys: BinanceKeys):
        self.keys = keys
        self.base_url = BINANCE_TESTNET if keys.testnet else BINANCE_API
        self.client = None
    
    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=10.0)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    def _default_spot_data(self, symbol: str) -> SpotData:
        """Hata veya geçersiz sembol için sıfırlı SpotData."""
        sym = (symbol or "BTCUSDT").upper()
        base = sym.replace("USDT", "") or "BTC"
        return SpotData(
            symbol=sym,
            price=0.0,
            price_change_24h=0.0,
            base_asset=base,
            quote_asset="USDT",
            base_balance=0.0,
            quote_balance=0.0,
            tick_size="0.01",
            step_size="0.00001",
            min_notional="5",
            timestamp=time.time()
        )

    async def get_quick_data(self, symbol: str, account_id: int) -> SpotData:
        """
        FLASH HIZLI: Tek çağrı ile tüm spot trading verilerini getir
        - Price (public, cached)
        - Filters (cached, 1 hour)
        - Balance (signed, cached)
        - 24h ticker (public, cached)
        Herhangi bir hata durumunda varsayılan (sıfırlı) SpotData döner, exception fırlatmaz.
        """
        start_time = time.time()
        symbol = symbol.upper()
        try:
            return await self._get_quick_data_impl(symbol, account_id, start_time)
        except Exception as e:
            logger.warning("get_quick_data error for %s: %s", symbol, e)
            return self._default_spot_data(symbol)

    async def _get_quick_data_impl(self, symbol: str, account_id: int, start_time: float) -> SpotData:
        
        # 1. Get price: cache -> DataHub -> price_hub -> public ticker (skip Binance if 400 cooldown)
        price = spot_cache.get_price(symbol)
        if price is None and _is_symbol_in_400_cooldown(symbol):
            price = 0.0
        if price is None:
            try:
                from app.services.data_hub import data_hub
                price = data_hub.get_price(symbol)  # float | None, serve-stale for UI
                if price and price > 0:
                    spot_cache.set_price(symbol, price)
            except Exception as e:
                logger.warning(f"Price fetch error for {symbol}: {e}")
                price = 0.0
        
        # 2. Get filters (cached, 1 hour) — market_data önce
        filters = spot_cache.get_filters(symbol)
        if filters is None:
            try:
                from app.services.market_data import get_symbol_filters
                cached = get_symbol_filters(symbol)
                if cached:
                    filters = {
                        "tickSize": str(cached.get("tick_size", "0.01")),
                        "stepSize": str(cached.get("step_size", "0.00001")),
                        "minNotional": str(cached.get("min_notional", "5")),
                        "baseAsset": cached.get("baseAsset") or symbol.replace("USDT", ""),
                        "quoteAsset": cached.get("quoteAsset") or "USDT",
                    }
                    spot_cache.set_filters(symbol, filters)
            except Exception:
                pass
        if filters is None:
            filters = {
                "tickSize": "0.01",
                "stepSize": "0.00001",
                "minNotional": "5",
                "baseAsset": symbol.replace("USDT", ""),
                "quoteAsset": "USDT",
            }
            spot_cache.set_filters(symbol, filters)
        
        # 3. Get balance (signed, cached)
        balance_data = spot_cache.get_balance(account_id)
        if balance_data is None:
            try:
                from app.services.binance_spot import get_wallet
                wallet_data = await get_wallet(self.keys, tag="spot_engine")
                balances = wallet_data.get("balances", [])
                
                base_asset = filters.get("baseAsset", symbol.replace("USDT", ""))
                quote_asset = filters.get("quoteAsset", "USDT")
                
                base_balance = 0.0
                quote_balance = 0.0
                
                for b in balances:
                    asset = b.get("asset")
                    free = float(b.get("free", 0))
                    if asset == base_asset:
                        base_balance = free
                    elif asset == quote_asset:
                        quote_balance = free
                
                balance_data = {
                    "base": base_balance,
                    "quote": quote_balance
                }
                spot_cache.set_balance(account_id, balance_data)
            except Exception as e:
                logger.warning(f"Balance fetch error for account {account_id}: {e}")
                balance_data = {"base": 0.0, "quote": 0.0}
        
        # 4. 24h change: market_data cache only
        price_change_24h = 0.0
        try:
            from app.services.market_data import get_ticker_24h
            t = get_ticker_24h(symbol)
            price_change_24h = float(t.get("priceChangePercent") or 0)
        except Exception as e:
            logger.debug(f"24h ticker cache miss for {symbol}: {e}")
        
        elapsed = (time.time() - start_time) * 1000
        logger.debug("[SPOT_ENGINE] quick_data: symbol=%s, t=%.1fms", symbol, elapsed)
        
        return SpotData(
            symbol=symbol,
            price=price,
            price_change_24h=price_change_24h,
            base_asset=filters.get("baseAsset", ""),
            quote_asset=filters.get("quoteAsset", "USDT"),
            base_balance=balance_data.get("base", 0.0),
            quote_balance=balance_data.get("quote", 0.0),
            tick_size=filters.get("tickSize", "0.01"),
            step_size=filters.get("stepSize", "0.00001"),
            min_notional=filters.get("minNotional", "5"),
            timestamp=time.time()
        )
    
    def _step_decimals(self, step_str: str) -> int:
        """stepSize string'tan ondalık basamak sayısı (örn. '0.001' -> 3)."""
        if not step_str:
            return 8
        s = step_str.strip().rstrip("0").rstrip(".")
        if "." in s:
            return len(s.split(".")[-1])
        if int(float(step_str)) >= 1:
            return 0
        return 8

    def _quantize_to_step(self, value: float, step_str: str) -> str:
        """Binance LOT_SIZE uyumu: quantity'yi step_size'a yuvarlar, gereksiz hassasiyet kaldırılır."""
        if value <= 0:
            return "0"
        step = float(step_str) if step_str else 0.00001
        if step <= 0:
            step = 0.00001
        decimals = self._step_decimals(step_str or "0.00001")
        q = math.floor(value / step) * step
        q = round(q, decimals)
        if q <= 0:
            return "0"
        fmt = f"%.{decimals}f" % q
        return fmt.rstrip("0").rstrip(".") or "0"

    def _quantize_price(self, value: float, tick_str: str) -> str:
        """Fiyatı tick_size hassasiyetine yuvarlar. Binance PRICE_FILTER uyumu (fazla hassasiyet hatası önlenir)."""
        if value <= 0:
            return "0"
        try:
            from decimal import ROUND_HALF_UP
            tick_d = Decimal(str(tick_str).strip() or "0.01")
            if tick_d <= 0:
                tick_d = Decimal("0.01")
            value_d = Decimal(str(value))
            p = (value_d / tick_d).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_d
            decimals = self._step_decimals(tick_str or "0.01")
            s = f"{float(p):.{decimals}f}"
            return s.rstrip("0").rstrip(".") or "0"
        except Exception:
            decimals = self._step_decimals(tick_str or "0.01")
            tick = float(tick_str) if tick_str else 0.01
            if tick <= 0:
                tick = 0.01
            p = round(round(value / tick) * tick, decimals)
            return (f"%.{decimals}f" % p).rstrip("0").rstrip(".") or "0"

    async def _get_symbol_filters(self, symbol: str) -> Dict[str, str]:
        """Sembol için step_size, tick_size (cache veya exchange info)."""
        symbol = symbol.upper()
        filters = spot_cache.get_filters(symbol)
        if filters:
            return {
                "step_size": filters.get("stepSize") or "0.00001",
                "tick_size": filters.get("tickSize") or "0.01",
            }
        try:
            from app.services.market_data import get_symbol_filters
            cached = get_symbol_filters(symbol)
            if cached:
                out = {
                    "step_size": str(cached.get("step_size", "0.00001")),
                    "tick_size": str(cached.get("tick_size", "0.01")),
                }
                spot_cache.set_filters(symbol, out)
                return out
        except Exception as e:
            logger.debug("Symbol filters cache for %s: %s", symbol, e)
        return {"step_size": "0.00001", "tick_size": "0.01"}

    async def place_order(
        self,
        symbol: str,
        side: str,  # BUY or SELL
        order_type: str,  # MARKET or LIMIT
        quantity: Optional[float] = None,
        quote_order_qty: Optional[float] = None,
        price: Optional[float] = None,
        *,
        allow_web: bool = False,
    ) -> Dict[str, Any]:
        """
        Place spot order - FLASH HIZLI
        Binance imza: parametreler decimal string (bilimsel gösterim yok), LOT_SIZE/PRICE_FILTER hassasiyetine uygun.
        Bot emirleri worker-only; kullanıcı kaynaklı spot emir (UI Al/Sat) allow_web=True ile API'den verilebilir.
        """
        from app.core.config import is_worker_role
        from app.core.errors import AppError
        if not allow_web and not is_worker_role():
            raise AppError(
                "WORKER_ONLY_OPERATION",
                "Order placement is only allowed on worker process. Web/API cannot place orders.",
                status_code=403,
            )
        symbol = symbol.upper()
        filters = await self._get_symbol_filters(symbol)
        step_size = filters.get("step_size") or "0.00001"
        tick_size = filters.get("tick_size") or "0.01"

        def _fmt_num(x: float) -> str:
            """Binance uyumlu: bilimsel gösterim yok."""
            if x == 0:
                return "0"
            s = f"{x:.15f}".rstrip("0").rstrip(".")
            return s if s else "0"

        def _fmt_quote_qty(q: float) -> str:
            """USDT quoteOrderQty: float artıkları kaldırır, Binance hassasiyet sınırına uyar (en fazla 8 ondalık)."""
            if q <= 0:
                return "0"
            q = round(float(q), 8)
            return ("%.8f" % q).rstrip("0").rstrip(".") or "0"

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "recvWindow": "5000",
        }
        
        if order_type.upper() == "LIMIT":
            if not price or not quantity:
                raise ValueError("LIMIT orders require price and quantity")
            params["price"] = self._quantize_price(float(price), tick_size)
            params["quantity"] = self._quantize_to_step(float(quantity), step_size)
            params["timeInForce"] = "GTC"
        elif order_type.upper() == "MARKET":
            if side.upper() == "BUY":
                if not quote_order_qty:
                    raise ValueError("MARKET BUY requires quote_order_qty")
                params["quoteOrderQty"] = _fmt_quote_qty(float(quote_order_qty))
            else:  # SELL
                if not quantity:
                    raise ValueError("MARKET SELL requires quantity")
                params["quantity"] = self._quantize_to_step(float(quantity), step_size)
        
        result = await _signed_request(self.client, "POST", "/api/v3/order", self.keys, params)
        
        # Invalidate balance cache after order (clear all for safety)
        spot_cache.balances.clear()
        
        return result

    async def get_commission_rates(self) -> Optional[Dict[str, Any]]:
        """Binance GET /sapi/v1/asset/tradeFee - gerçek zamanlı maker/taker oranı."""
        if _signed_request is None:
            return None
        try:
            # Returns list of { symbol, makerCommission, takerCommission }; use first or aggregate
            data = await _signed_request(self.client, "GET", "/sapi/v1/asset/tradeFee", self.keys, {})
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                maker = float(first.get("makerCommission", 0.001))
                taker = float(first.get("takerCommission", 0.001))
                return {
                    "maker": maker,
                    "taker": taker,
                    "maker_pct": round(maker * 100, 4),
                    "taker_pct": round(taker * 100, 4)
                }
        except Exception as e:
            logger.debug("get_commission_rates error: %s", e)
        return None
