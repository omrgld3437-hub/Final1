"""
Binance Spot adapter for bot engine.
Uses app.services.binance_spot (get_wallet, place_order, get_open_orders, cancel_order, fetch_exchange_info).
Single market-data source: app.services.data_hub for price.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fmt_qty(x: float, step_size: float, *, floor: bool = False, step_str: Optional[str] = None) -> str:
    """LOT_SIZE string for Binance API (sells: floor to step)."""
    from app.botengine.order_qty import quantize_qty_down

    step = step_str or (str(step_size) if step_size else "0.00001")
    if floor:
        _, s = quantize_qty_down(x, step)
        return s
    if x <= 0:
        return "0"
    import math

    precision = max(0, -int(round(math.log10(step_size)))) if step_size > 0 else 8
    q = round(round(x / step_size) * step_size, precision) if step_size > 0 else x
    q = round(q, precision)
    s = f"{q:.15f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_quote(q: float) -> str:
    if q <= 0:
        return "0"
    q = round(float(q), 8)
    return ("%.8f" % q).rstrip("0").rstrip(".") or "0"


class BinanceAdapter:
    """Async adapter over binance_spot + data_hub. Keys from get_account_keys(account_id, db)."""

    def __init__(self, account_id: int, keys: Any, paper_mode: bool = False):
        self.account_id = account_id
        self.keys = keys
        self.paper_mode = paper_mode
        self._filters_cache: Dict[str, Dict[str, Any]] = {}

    async def get_account_balances(self) -> Dict[str, Dict[str, float]]:
        """Asset -> { free, locked }. Paper modda 10.000 USDT sanal bakiye döner."""
        if self.paper_mode:
            from app.services.test_account import TEST_PAPER_BALANCE_USDT
            return {"USDT": {"free": TEST_PAPER_BALANCE_USDT, "locked": 0.0}}
        from app.services.binance_spot import get_wallet
        data = await get_wallet(self.keys, tag="bot_engine")
        out: Dict[str, Dict[str, float]] = {}
        for b in (data.get("balances") or []):
            asset = (b.get("asset") or "").strip()
            if not asset:
                continue
            free = float(b.get("free") or 0)
            locked = float(b.get("locked") or 0)
            out[asset] = {"free": free, "locked": locked}
        return out

    async def get_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        """LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL — data_hub cache, else exchangeInfo REST."""
        from app.botengine.order_qty import normalize_symbol_filters

        symbol = symbol.upper()
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        try:
            from app.services.market_data import get_symbol_filters
            cached = get_symbol_filters(symbol)
            if cached:
                out = normalize_symbol_filters(cached)
                self._filters_cache[symbol] = out
                return out
        except Exception:
            pass
        if not self.paper_mode and self.keys:
            try:
                from app.services.binance_spot import fetch_exchange_info
                info = await fetch_exchange_info(
                    testnet=getattr(self.keys, "testnet", False),
                    force_refresh=False,
                )
                for s in info.get("symbols") or []:
                    if (s.get("symbol") or "").upper() != symbol:
                        continue
                    raw: Dict[str, Any] = {"min_notional": 5.0}
                    for f in s.get("filters") or []:
                        t = f.get("filterType")
                        if t == "LOT_SIZE":
                            raw["step_size_str"] = str(f.get("stepSize") or "0.00001")
                            raw["min_qty_str"] = str(f.get("minQty") or raw["step_size_str"])
                        elif t == "PRICE_FILTER":
                            raw["tick_size_str"] = str(f.get("tickSize") or "0.01")
                        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                            raw["min_notional"] = float(
                                f.get("minNotional") or f.get("notional") or 5
                            )
                    out = normalize_symbol_filters(raw)
                    self._filters_cache[symbol] = out
                    return out
            except Exception as e:
                logger.warning("get_symbol_filters REST fallback %s: %s", symbol, e)
        out = normalize_symbol_filters({})
        self._filters_cache[symbol] = out
        return out

    def get_price(self, symbol: str) -> Optional[float]:
        """
        data_hub only. No direct Binance public ticker fallback.
        Returns None if symbol never seen OR price is stale (bot safety: never trade on stale).
        """
        from app.services.data_hub import data_hub
        d = data_hub.get_price_with_meta(symbol)
        if not d or not isinstance(d, dict):
            return None
        if d.get("is_stale"):
            return None  # Bot must not trade on stale price
        p = d.get("price")
        if p is None or not isinstance(p, (int, float)) or float(p) <= 0:
            return None
        return float(p)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.paper_mode or not self.keys:
            return []
        from app.services.binance_spot import get_open_orders as _go
        return await _go(self.keys, symbol)

    async def get_order_by_client_order_id(self, symbol: str, orig_client_order_id: str) -> Optional[Dict[str, Any]]:
        """Idempotency: Check if order already placed (timeout/crash retry)."""
        if self.paper_mode or not self.keys:
            return None
        from app.services.binance_spot import get_order_by_client_order_id as _goc
        return await _goc(self.keys, symbol, orig_client_order_id)

    async def get_my_trades_for_order(self, symbol: str, order_id: int) -> List[Dict[str, Any]]:
        """Verify fill: return trades with this orderId. Paper mode returns [] (no Binance data)."""
        if self.paper_mode or not self.keys:
            return []
        from app.services.binance_spot import get_my_trades as _gmt
        return await _gmt(self.keys, symbol, limit=50, order_id=order_id)

    async def get_all_orders(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Recent orders for reconciliation (bounded)."""
        if self.paper_mode or not self.keys:
            return []
        from app.services.binance_spot import get_all_orders as _gao
        return await _gao(self.keys, symbol, limit)

    async def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        from app.services.binance_spot import cancel_order as _co
        return await _co(self.keys, symbol, order_id)

    async def place_market_buy(
        self,
        symbol: str,
        quote_amount_usdt: float,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """Market BUY with quoteOrderQty. Returns Binance order response or simulated."""
        symbol = symbol.upper()
        if self.paper_mode:
            return self._simulate_fill(symbol, "BUY", quote_qty=quote_amount_usdt, client_order_id=client_order_id)
        filters = await self.get_symbol_filters(symbol)
        min_notional = filters.get("min_notional") or 5.0
        if quote_amount_usdt < min_notional:
            raise ValueError(f"quote_amount {quote_amount_usdt} < min_notional {min_notional}")
        from app.services.binance_spot import place_order
        payload = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": _fmt_quote(quote_amount_usdt),
            "newClientOrderId": client_order_id[:36],
        }
        return await place_order(self.keys, payload)

    async def place_market_sell(
        self,
        symbol: str,
        quantity: float,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """Market SELL with quantity (base)."""
        symbol = symbol.upper()
        if self.paper_mode:
            return self._simulate_fill(symbol, "SELL", base_qty=quantity, client_order_id=client_order_id)
        from app.botengine.order_qty import validate_market_sell_qty

        filters = await self.get_symbol_filters(symbol)
        price = self.get_price(symbol) or 0.0
        skip_reason, qty_floored, qty_str = validate_market_sell_qty(quantity, filters, price)
        if skip_reason == "LOT_SIZE":
            raise ValueError(
                f"quantity {quantity} below LOT_SIZE min_qty={filters.get('min_qty')} step={filters.get('step_size_str')}"
            )
        if skip_reason == "MIN_NOTIONAL":
            notional = qty_floored * price if price else 0
            raise ValueError(
                f"notional {notional} < min_notional {filters.get('min_notional')}"
            )
        from app.services.binance_spot import place_order
        payload = {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": qty_str,
            "newClientOrderId": client_order_id[:36],
        }
        return await place_order(self.keys, payload)

    def _simulate_fill(
        self,
        symbol: str,
        side: str,
        *,
        base_qty: Optional[float] = None,
        quote_qty: Optional[float] = None,
        client_order_id: str = "",
    ) -> Dict[str, Any]:
        """Paper mode: no real order, return mock fill. Fails when price stale/missing (bot safety)."""
        price = self.get_price(symbol) or 0.0
        if not price or price <= 0:
            raise ValueError(f"Price stale or missing for {symbol}; paper mode refuses fill")
        if side == "BUY" and quote_qty is not None:
            base_qty = quote_qty / price
        elif side == "SELL" and base_qty is not None:
            quote_qty = base_qty * price
        else:
            base_qty = quote_qty = 0.0
        import time
        return {
            "orderId": int(time.time() * 1000),
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "status": "FILLED",
            "executedQty": str(base_qty),
            "cummulativeQuoteQty": str(quote_qty or 0),
            "fills": [{"price": str(price), "qty": str(base_qty), "commission": "0", "commissionAsset": "USDT"}],
        }
