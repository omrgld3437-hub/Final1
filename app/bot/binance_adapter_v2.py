"""
FILE: binance_adapter_v2.py
VERSION: v1
DATE: 2026-01-21
CHANGE: Binance Spot adapter for Bot V2 - paper + live modes with rate limiting
"""
import time
import random
from typing import Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN
# Optional Binance imports - will be added later
try:
    from app.services.binance_client import BinanceClient
except ImportError:
    BinanceClient = None


class BinanceSpotAdapterV2:
    """Binance Spot API adapter for Bot V2 with paper mode simulation"""

    def __init__(self, account_id: int, mode: str = "paper", api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.account_id = account_id
        self.mode = mode
        self.is_paper = mode == "paper"
        
        if not self.is_paper:
            if not api_key or not api_secret:
                raise ValueError("API key and secret required for live mode")
            self.client = BinanceClient(api_key, api_secret)
        else:
            self.client = None
        
        self._rate_limit_delay = 0.1  # 100ms between requests
        self._last_request_time = 0.0
        self._exchange_info_cache = {}
        self._last_price_cache = {}

    def _rate_limit(self):
        """Simple rate limiting"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def get_price(self, symbol: str) -> float:
        """Get current price for symbol"""
        if self.is_paper:
            # In paper mode, return cached price or mock
            if symbol in self._last_price_cache:
                # Add small random walk for realism
                base = self._last_price_cache[symbol]
                change = random.uniform(-0.002, 0.002)  # ±0.2% random walk
                price = base * (1 + change)
                self._last_price_cache[symbol] = price
                return price
            else:
                # First call - fetch real price as starting point
                if self.client:
                    price = self.client.get_ticker_price(symbol)
                else:
                    # Fallback mock price
                    price = 50000.0 if "BTC" in symbol else 3000.0
                self._last_price_cache[symbol] = price
                return price
        else:
            self._rate_limit()
            return self.client.get_ticker_price(symbol)

    def update_price(self, symbol: str, price: float):
        """Update cached price (for paper mode)"""
        if self.is_paper:
            self._last_price_cache[symbol] = price

    def get_exchange_info(self, symbol: str) -> Dict:
        """Get exchange info (stepSize, tickSize, minNotional)"""
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]
        
        if self.is_paper:
            # Default values for paper mode
            info = {
                "stepSize": "0.00001",
                "tickSize": "0.01",
                "minNotional": "10.0",
                "minQty": "0.00001",
                "maxQty": "9000.0"
            }
        else:
            self._rate_limit()
            full_info = self.client.get_exchange_info(symbol)
            filters = {f["filterType"]: f for f in full_info.get("filters", [])}
            info = {
                "stepSize": filters.get("LOT_SIZE", {}).get("stepSize", "0.00001"),
                "tickSize": filters.get("PRICE_FILTER", {}).get("tickSize", "0.01"),
                "minNotional": filters.get("MIN_NOTIONAL", {}).get("minNotional", "10.0"),
                "minQty": filters.get("LOT_SIZE", {}).get("minQty", "0.00001"),
                "maxQty": filters.get("LOT_SIZE", {}).get("maxQty", "9000.0")
            }
        
        self._exchange_info_cache[symbol] = info
        return info

    def apply_precision(self, symbol: str, qty: float, is_price: bool = False) -> float:
        """Apply precision filters (stepSize for qty, tickSize for price)"""
        info = self.get_exchange_info(symbol)
        step = Decimal(info["stepSize"] if not is_price else info["tickSize"])
        value = Decimal(str(qty))
        # Round down to nearest step
        rounded = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN) * step
        return float(rounded)

    def check_min_notional(self, symbol: str, qty: float, price: float) -> Tuple[bool, str]:
        """Check if order meets minimum notional requirement"""
        info = self.get_exchange_info(symbol)
        min_notional = float(info["minNotional"])
        notional = qty * price
        if notional < min_notional:
            return False, f"Notional {notional:.2f} < min {min_notional:.2f}"
        return True, ""

    def place_market_buy(self, symbol: str, quote_amount_usdt: float, 
                        slippage_bps: int = 10, taker_fee_bps: int = 10) -> Dict:
        """
        Place market buy order
        
        Returns:
            {
                "orderId": str,
                "executedQty": float,
                "cumulativeQuoteQty": float,
                "fills": [
                    {"price": float, "qty": float, "commission": float, "commissionAsset": str}
                ],
                "fee_usdt": float
            }
        """
        if self.is_paper:
            # Simulate market buy with slippage
            current_price = self.get_price(symbol)
            slippage_mult = 1 + (slippage_bps / 10000.0)  # e.g., 10 bps = 0.1% = 1.001
            fill_price = current_price * slippage_mult
            
            # Calculate qty
            qty = quote_amount_usdt / fill_price
            qty = self.apply_precision(symbol, qty, is_price=False)
            
            # Check min notional
            ok, msg = self.check_min_notional(symbol, qty, fill_price)
            if not ok:
                raise ValueError(f"Paper buy failed: {msg}")
            
            # Calculate fees
            fee_usdt = quote_amount_usdt * (taker_fee_bps / 10000.0)
            
            # Update cached price slightly
            self.update_price(symbol, fill_price * 0.999)
            
            return {
                "orderId": f"paper_buy_{int(time.time() * 1000)}",
                "executedQty": qty,
                "cumulativeQuoteQty": quote_amount_usdt,
                "fills": [{
                    "price": fill_price,
                    "qty": qty,
                    "commission": fee_usdt,
                    "commissionAsset": "USDT"
                }],
                "fee_usdt": fee_usdt
            }
        else:
            # Live mode - real order
            self._rate_limit()
            quote_qty = self.apply_precision(symbol, quote_amount_usdt, is_price=False)
            
            # Binance API uses quoteOrderQty for market buys
            order = self.client.place_market_order(
                symbol=symbol,
                side="BUY",
                quote_order_qty=quote_qty
            )
            
            # Calculate total fee in USDT
            fills = order.get("fills", [])
            fee_usdt = 0.0
            for fill in fills:
                comm = float(fill.get("commission", 0))
                comm_asset = fill.get("commissionAsset", "USDT")
                if comm_asset == "USDT":
                    fee_usdt += comm
                else:
                    # Convert to USDT (simplified - would need price lookup)
                    fee_usdt += comm * current_price
            
            return {
                "orderId": str(order.get("orderId", "")),
                "executedQty": float(order.get("executedQty", 0)),
                "cumulativeQuoteQty": float(order.get("cummulativeQuoteQty", 0)),
                "fills": fills,
                "fee_usdt": fee_usdt
            }

    def place_market_sell(self, symbol: str, base_qty: float,
                         slippage_bps: int = 10, taker_fee_bps: int = 10) -> Dict:
        """
        Place market sell order
        
        Returns:
            Same format as place_market_buy
        """
        if self.is_paper:
            # Simulate market sell with slippage
            current_price = self.get_price(symbol)
            slippage_mult = 1 - (slippage_bps / 10000.0)  # Sell at slightly lower price
            fill_price = current_price * slippage_mult
            
            # Apply precision
            qty = self.apply_precision(symbol, base_qty, is_price=False)
            
            # Check min notional
            quote_amount = qty * fill_price
            ok, msg = self.check_min_notional(symbol, qty, fill_price)
            if not ok:
                raise ValueError(f"Paper sell failed: {msg}")
            
            # Calculate fees
            fee_usdt = quote_amount * (taker_fee_bps / 10000.0)
            
            # Update cached price slightly
            self.update_price(symbol, fill_price * 1.001)
            
            return {
                "orderId": f"paper_sell_{int(time.time() * 1000)}",
                "executedQty": qty,
                "cumulativeQuoteQty": quote_amount,
                "fills": [{
                    "price": fill_price,
                    "qty": qty,
                    "commission": fee_usdt,
                    "commissionAsset": "USDT"
                }],
                "fee_usdt": fee_usdt
            }
        else:
            # Live mode
            self._rate_limit()
            qty = self.apply_precision(symbol, base_qty, is_price=False)
            
            order = self.client.place_market_order(
                symbol=symbol,
                side="SELL",
                quantity=qty
            )
            
            # Calculate total fee in USDT
            fills = order.get("fills", [])
            fee_usdt = 0.0
            current_price = self.get_price(symbol)
            for fill in fills:
                comm = float(fill.get("commission", 0))
                comm_asset = fill.get("commissionAsset", "USDT")
                if comm_asset == "USDT":
                    fee_usdt += comm
                else:
                    fee_usdt += comm * current_price
            
            return {
                "orderId": str(order.get("orderId", "")),
                "executedQty": float(order.get("executedQty", 0)),
                "cumulativeQuoteQty": float(order.get("cummulativeQuoteQty", 0)),
                "fills": fills,
                "fee_usdt": fee_usdt
            }


