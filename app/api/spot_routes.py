"""
FILE: spot_routes.py
VERSION: v1.0
DATE: 2026-01-22
CHANGE: YENİ - Bağımsız Spot Trading Engine Routes - Flash Hızında
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from typing import Optional, Dict, Tuple, Set
from pydantic import BaseModel
import asyncio
import os
import re
import time
import logging
import httpx

from app.db.session import get_db
from app.db.models import Account
from app.api.auth import require_auth, get_account_or_403, get_client_ip
from app.api.routes import invalidate_wallet_cache, invalidate_open_orders_cache
from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
from app.services.binance_spot import invalidate_account_cache_for_keys
from app.services import audit as audit_svc
from app.services.spot_engine import SpotEngine
from app.core.errors import AppError as AppErrorBase
try:
    from app.services.binance_assets import get_account_keys
except ImportError:
    get_account_keys = None

logger = logging.getLogger(__name__)
router = APIRouter()

# Semboller: Binance'te yok veya 500 üreten çiftler – blacklist + base==quote
INVALID_QUICK_DATA_SYMBOLS = frozenset({
    "USDTUSDT", "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT"
})

# In-flight dedupe: (account_id, symbol) -> asyncio.Task (quick_data)
_SPOT_INFLIGHT: Dict[Tuple[int, str], asyncio.Task] = {}
# Fiyat SSOT: sembol başına tek uçuş (account_id gerekmez)
_PRICE_INFLIGHT: Dict[str, asyncio.Task] = {}
_SPOT_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}(USDT|BUSD|BTC|ETH|FDUSD)$")
# Hata log rate-limit: symbol -> last_log_ts
_ERROR_LOG_LAST: Dict[str, float] = {}
_ERROR_LOG_INTERVAL = 10.0

# ExchangeInfo valid symbols cache (TTL 300s)
_VALID_SPOT_SYMBOLS: Optional[Set[str]] = None
_VALID_SPOT_SYMBOLS_TS: float = 0
_VALID_SPOT_SYMBOLS_TTL = 300.0


def _is_invalid_spot_symbol(symbol: str) -> bool:
    """Blacklist + base==quote (USDTUSDT vb.)."""
    if not symbol or not isinstance(symbol, str):
        return True
    s = symbol.upper().strip()
    if s in INVALID_QUICK_DATA_SYMBOLS:
        return True
    # base == quote (e.g. USDTUSDT)
    if len(s) >= 8 and s.endswith("USDT"):
        base = s[:-4] or ""
        if base and (s == base + "USDT" and base == "USDT"):
            return True
    if s == "USDTUSDT" or (len(s) >= 6 and s[:4] == s[-4:] and s[:4] == "USDT"):
        return True
    return False


def _normalize_spot_trading_symbol(symbol: str) -> Optional[str]:
    """BTC → BTCUSDT; geçersiz/boş sembolde None (Binance çağrısı yapılmaz)."""
    sym = (symbol or "").upper().strip()
    if not sym or _is_invalid_spot_symbol(sym):
        return None
    if _SPOT_SYMBOL_RE.match(sym):
        return sym
    if re.match(r"^[A-Z0-9]{2,10}$", sym):
        candidate = sym + "USDT"
        if _SPOT_SYMBOL_RE.match(candidate) and not _is_invalid_spot_symbol(candidate):
            return candidate
    return None


async def _get_valid_spot_symbols_async() -> Set[str]:
    """ExchangeInfo cache'ten geçerli sembol seti; TTL 300s."""
    global _VALID_SPOT_SYMBOLS, _VALID_SPOT_SYMBOLS_TS
    now = time.time()
    if _VALID_SPOT_SYMBOLS is not None and (now - _VALID_SPOT_SYMBOLS_TS) < _VALID_SPOT_SYMBOLS_TTL:
        return _VALID_SPOT_SYMBOLS
    try:
        from app.services.market_data import get_symbols
        symbols = set(get_symbols("all"))
        if symbols:
            _VALID_SPOT_SYMBOLS = symbols
            _VALID_SPOT_SYMBOLS_TS = now
            return _VALID_SPOT_SYMBOLS
    except Exception:
        pass
    _VALID_SPOT_SYMBOLS = _VALID_SPOT_SYMBOLS or set()
    _VALID_SPOT_SYMBOLS_TS = now
    return _VALID_SPOT_SYMBOLS

def _default_quick_data_response(symbol: str):
    import time
    sym = (symbol or "BTCUSDT").upper()
    base = sym.replace("USDT", "") or "BTC"
    return {
        "symbol": sym,
        "price": 0.0,
        "priceChange24h": 0.0,
        "baseAsset": base,
        "quoteAsset": "USDT",
        "baseBalance": 0.0,
        "quoteBalance": 0.0,
        "baseLockedByBots": 0.0,
        "quoteLockedByBots": 0.0,
        "baseAvailable": 0.0,
        "quoteAvailable": 0.0,
        "filters": {
            "tickSize": "0.01",
            "stepSize": "0.00001",
            "minQty": "0.00001",
            "minNotional": "5"
        },
        "ts": time.time()
    }

# ============================================================
# SPOT ENGINE ENDPOINTS - Flash Hızlı
# ============================================================

@router.get("/spot/quick_data")
async def get_spot_quick_data(
    account_id: int = Query(..., description="Account ID"),
    symbol: str = Query(..., description="Trading pair symbol (e.g., BTCUSDT)"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    FLASH HIZLI: Tek istek ile tüm spot trading verilerini getir.
    Auth zorunlu; account ownership doğrulanır.
    """
    get_account_or_403(current, account_id, db)
    sym = (symbol or "").upper().strip()
    if _is_invalid_spot_symbol(sym):
        return {"ok": False, "error_code": "INVALID_SYMBOL", "symbol": sym}
    valid = await _get_valid_spot_symbols_async()
    if valid and sym not in valid:
        return {"ok": False, "error_code": "INVALID_SYMBOL", "symbol": sym}
    key = (account_id, sym)
    if key in _SPOT_INFLIGHT:
        try:
            return await _SPOT_INFLIGHT[key]
        except Exception:
            _SPOT_INFLIGHT.pop(key, None)
    async def _do():
        try:
            from app.services.test_account import is_test_account
            if is_test_account(account_id, db):
                from app.services.wallet_display import build_test_account_wallet
                from app.services.test_spot_paper import spot_balances_from_wallet
                from app.services.market_data import get_ticker_24h
                from app.botengine.virtual_wallet import get_bot_locked_balances_for_account

                wallet = build_test_account_wallet(account_id, db)
                bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
                base_asset = sym.replace("USDT", "") if sym.endswith("USDT") else sym
                quote_asset = "USDT"
                bal = spot_balances_from_wallet(wallet, base_asset, quote_asset, bot_locked)
                price = 0.0
                try:
                    from app.services.data_hub import data_hub
                    price = float(data_hub.get_price(sym) or 0)
                except Exception:
                    price = 0.0
                price_change_24h = 0.0
                try:
                    t = get_ticker_24h(sym)
                    price_change_24h = float(t.get("priceChangePercent") or 0)
                except Exception:
                    pass
                if get_account_keys is None:
                    flt = {"tick_size": "0.01", "step_size": "0.00001", "min_qty": "0.00001", "min_notional": "5"}
                else:
                    try:
                        keys = await get_account_keys(account_id, db)
                        async with SpotEngine(keys) as engine:
                            flt = await engine._get_symbol_filters(sym)
                    except Exception:
                        flt = {"tick_size": "0.01", "step_size": "0.00001", "min_qty": "0.00001", "min_notional": "5"}
                return {
                    "ok": True,
                    "symbol": sym,
                    "price": price,
                    "priceChange24h": price_change_24h,
                    "baseAsset": base_asset,
                    "quoteAsset": quote_asset,
                    "baseBalance": bal["base_balance"],
                    "quoteBalance": bal["quote_balance"],
                    "baseLockedByBots": round(bal["base_locked"], 8),
                    "quoteLockedByBots": round(bal["quote_locked"], 8),
                    "baseAvailable": round(bal["base_available"], 8),
                    "quoteAvailable": round(bal["quote_available"], 8),
                    "filters": {
                        "tickSize": flt.get("tick_size", "0.01"),
                        "stepSize": flt.get("step_size", "0.00001"),
                        "minQty": flt.get("min_qty", "0.00001"),
                        "minNotional": flt.get("min_notional", "5"),
                    },
                    "ts": time.time(),
                    "paper": True,
                }
            if get_account_keys is None:
                return _default_quick_data_response(sym)
            keys = await get_account_keys(account_id, db)
            bot_locked = get_bot_locked_balances_for_account(db, account_id)
            async with SpotEngine(keys) as engine:
                spot_data = await engine.get_quick_data(symbol, account_id)
                base_locked = float(bot_locked.get(spot_data.base_asset, 0) or 0)
                quote_locked = float(bot_locked.get(spot_data.quote_asset, 0) or 0)
                base_available = max(0.0, spot_data.base_balance - base_locked)
                quote_available = max(0.0, spot_data.quote_balance - quote_locked)
                return {
                    "ok": True,
                    "symbol": spot_data.symbol,
                    "price": spot_data.price,
                    "priceChange24h": spot_data.price_change_24h,
                    "baseAsset": spot_data.base_asset,
                    "quoteAsset": spot_data.quote_asset,
                    "baseBalance": spot_data.base_balance,
                    "quoteBalance": spot_data.quote_balance,
                    "baseLockedByBots": round(base_locked, 8),
                    "quoteLockedByBots": round(quote_locked, 8),
                    "baseAvailable": round(base_available, 8),
                    "quoteAvailable": round(quote_available, 8),
                    "filters": {
                        "tickSize": spot_data.tick_size,
                        "stepSize": spot_data.step_size,
                        "minQty": spot_data.min_qty,
                        "minNotional": spot_data.min_notional
                    },
                    "ts": spot_data.timestamp
                }
        except Exception as e:
            from app.services.binance_assets import KEY_ERROR_CODES
            def _is_keys_missing(ex):
                if ex is None:
                    return False
                s = str(ex).strip()
                if any(c in s for c in KEY_ERROR_CODES):
                    return True
                args = getattr(ex, "args", ()) or ()
                if any(any(c in str(x) for c in KEY_ERROR_CODES) for x in args):
                    return True
                return _is_keys_missing(getattr(ex, "__cause__", None))
            if _is_keys_missing(e):
                logger.debug("Spot quick_data for %s: account keys not configured", sym)
            else:
                now = time.time()
                if now - _ERROR_LOG_LAST.get(sym, 0) > _ERROR_LOG_INTERVAL:
                    _ERROR_LOG_LAST[sym] = now
                    from app.services.binance_spot import is_transient_upstream_error
                    log_fn = logger.debug if is_transient_upstream_error(e) else logger.warning
                    log_fn("Spot quick_data error for %s: %s", sym, e)
            return _default_quick_data_response(sym)
        finally:
            _SPOT_INFLIGHT.pop(key, None)
    task = asyncio.create_task(_do())
    _SPOT_INFLIGHT[key] = task
    return await task

class SpotOrderRequest(BaseModel):
    account_id: int
    symbol: str
    side: str  # BUY or SELL
    type: str  # MARKET or LIMIT
    quantity: Optional[float] = None
    quote_order_qty: Optional[float] = None
    price: Optional[float] = None

@router.post("/spot/order")
async def place_spot_order(
    request_body: SpotOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    FLASH HIZLI: Place spot order. Auth zorunlu; account ownership doğrulanır.
    """
    request_id = getattr(request.state, "request_id", None) or ""
    try:
        get_account_or_403(current, request_body.account_id, db)
    except HTTPException as e:
        if e.status_code == 403:
            logger.warning(
                "spot_order_403 account_id=%s current_user_id=%s current_account_id=%s request_id=%s detail=%s",
                request_body.account_id, current.get("user_id"), current.get("account_id"), request_id,
                (e.detail.get("error_code") if isinstance(e.detail, dict) else str(e.detail)[:80]),
            )
        raise
    acc = db.query(Account).filter(Account.id == request_body.account_id).first()
    from app.services.test_account import is_test_account
    if is_test_account(request_body.account_id, db):
        try:
            from app.services.test_spot_paper import execute_test_paper_order
            from app.services.spot_engine import spot_cache

            result = execute_test_paper_order(
                db,
                request_body.account_id,
                request_body.symbol,
                request_body.side,
                request_body.type,
                quantity=request_body.quantity,
                quote_order_qty=request_body.quote_order_qty,
                price=request_body.price,
            )
            spot_cache.invalidate_balance(request_body.account_id)
            await invalidate_wallet_cache(request_body.account_id)
            await invalidate_open_orders_cache(request_body.account_id)
            meta = {
                "symbol": request_body.symbol,
                "side": request_body.side,
                "type": request_body.type,
                "order_id": result.get("orderId"),
                "paper": True,
            }
            audit_svc.log_event(
                db, actor_type="admin" if current.get("is_admin") else "user", event_type="SPOT_ORDER_CREATE", severity="INFO",
                actor_user_id=current.get("user_id"), target_user_id=acc.user_id if acc else None, target_account_id=request_body.account_id,
                ip=get_client_ip(request), device_id=current.get("device_id"),
                request_id=getattr(request.state, "request_id", None),
                meta=meta,
            )
            return {"success": True, "order": result}
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": "VALIDATION_ERROR", "detail": str(e)})
    try:
        keys = await get_account_keys(request_body.account_id, db)
        bot_locked = get_bot_locked_balances_for_account(db, request_body.account_id)
        async with SpotEngine(keys) as engine:
            spot_data = await engine.get_quick_data(request_body.symbol, request_body.account_id)
            base_available = max(0.0, spot_data.base_balance - float(bot_locked.get(spot_data.base_asset, 0) or 0))
            quote_available = max(0.0, spot_data.quote_balance - float(bot_locked.get(spot_data.quote_asset, 0) or 0))
            side = (request_body.side or "").upper()
            order_qty = request_body.quantity
            if side == "BUY":
                if request_body.quote_order_qty is not None and request_body.quote_order_qty > 0:
                    if quote_available < request_body.quote_order_qty:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "INSUFFICIENT_AVAILABLE_BALANCE",
                                "detail": "Bot bakiyesi kilitli; kullanılabilir quote bakiyesi yetersiz.",
                                "available_quote": round(quote_available, 2),
                                "required": request_body.quote_order_qty,
                            },
                        )
                elif request_body.quantity is not None and request_body.quantity > 0 and spot_data.price > 0:
                    required_quote = request_body.quantity * spot_data.price
                    if quote_available < required_quote:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "INSUFFICIENT_AVAILABLE_BALANCE",
                                "detail": "Bot bakiyesi kilitli; kullanılabilir quote bakiyesi yetersiz.",
                                "available_quote": round(quote_available, 2),
                                "required_quote": round(required_quote, 2),
                            },
                        )
            elif side == "SELL" and order_qty is not None and order_qty > 0:
                from decimal import Decimal
                sym_filters = await engine._get_symbol_filters(request_body.symbol)
                qty_str = engine._quantize_to_step(float(order_qty), sym_filters["step_size"])
                avail_str = engine._quantize_to_step(base_available, sym_filters["step_size"]) if base_available > 0 else "0"
                qty_d = Decimal(qty_str)
                avail_d = Decimal(avail_str)
                if avail_d > 0 and qty_d > avail_d:
                    qty_str = avail_str
                    qty_d = avail_d
                if qty_d <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "LOT_SIZE",
                            "detail": f"Miktar lot adımına uymuyor (step={sym_filters['step_size']}, min={sym_filters['min_qty']}).",
                            "step_size": sym_filters["step_size"],
                            "min_qty": sym_filters["min_qty"],
                            "available_base": round(base_available, 8),
                        },
                    )
                order_qty = float(qty_d)
                if base_available < order_qty:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "INSUFFICIENT_AVAILABLE_BALANCE",
                            "detail": "Bot bakiyesi kilitli; kullanılabilir base bakiyesi yetersiz.",
                            "available_base": round(base_available, 8),
                            "required": order_qty,
                        },
                    )
            result = await engine.place_order(
                symbol=request_body.symbol,
                side=request_body.side,
                order_type=request_body.type,
                quantity=order_qty,
                quote_order_qty=request_body.quote_order_qty,
                price=request_body.price,
                allow_web=True,
            )
            order_id = result.get("orderId") if isinstance(result, dict) else getattr(result, "orderId", None)
            executed_qty = result.get("executedQty") if isinstance(result, dict) else getattr(result, "executedQty", None)
            cum_quote = result.get("cummulativeQuoteQty") or result.get("cumulativeQuoteQty") if isinstance(result, dict) else getattr(result, "cummulativeQuoteQty", None) or getattr(result, "cumulativeQuoteQty", None)
            price_val = result.get("price") if isinstance(result, dict) else getattr(result, "price", None)
            meta = {
                "symbol": request_body.symbol,
                "side": request_body.side,
                "type": request_body.type,
                "order_id": order_id,
                "quantity": order_qty,
                "price": request_body.price or price_val,
                "quote_order_qty": request_body.quote_order_qty,
                "executed_qty": executed_qty,
                "executed_value_usdt": float(cum_quote) if cum_quote is not None else None,
                "user_agent": (request.headers.get("user-agent") or "")[:200],
            }
            audit_svc.log_event(
                db, actor_type="admin" if current.get("is_admin") else "user", event_type="SPOT_ORDER_CREATE", severity="INFO",
                actor_user_id=current.get("user_id"), target_user_id=acc.user_id if acc else None, target_account_id=request_body.account_id,
                ip=get_client_ip(request), device_id=current.get("device_id"),
                request_id=getattr(request.state, "request_id", None),
                meta=meta,
            )
            await invalidate_wallet_cache(request_body.account_id)
            await invalidate_open_orders_cache(request_body.account_id)
            await invalidate_account_cache_for_keys(keys)
            return {
                "success": True,
                "order": result
            }
    except AppErrorBase:
        raise
    except ValueError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Spot order validation error: {e}")
        raise HTTPException(status_code=400, detail={"error": "VALIDATION_ERROR", "detail": str(e)})
    except httpx.HTTPStatusError as e:
        import logging
        logger = logging.getLogger(__name__)
        status = e.response.status_code
        error_data = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = error_data.get("msg", e.response.text) if error_data else e.response.text
        logger.error(f"Spot order Binance API error: {status} - {error_msg}")
        if error_data.get("code") == -1013 or "LOT_SIZE" in (error_msg or ""):
            from app.services.spot_engine import spot_cache
            spot_cache.invalidate_filters((request_body.symbol or "").upper())
        # Binance 4xx (parametre/hassasiyet vb.) -> 400; 5xx/ağ -> 502
        status_code = 400 if 400 <= status < 500 else 502
        raise HTTPException(
            status_code=status_code,
            detail={"error": "BINANCE_API_ERROR", "detail": error_msg, "code": error_data.get("code")}
        )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.exception(f"Spot order error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={"error": "SPOT_ORDER_FAILED", "detail": str(e)}
        )

BINANCE_PUBLIC = "https://api.binance.com"

# Klines cache: (symbol, interval, limit) -> (data, ts). TTL by interval (seconds).
KLINES_CACHE: dict = {}
KLINES_TTL_BY_INTERVAL = {
    "1m": 30, "3m": 45, "5m": 60, "15m": 120, "30m": 180,
    "1h": 300, "2h": 600, "4h": 600, "1d": 1800, "1w": 1800,
}
KLINES_INFLIGHT: dict = {}  # (symbol, interval, limit) -> asyncio.Task

def _klines_cache_ttl(interval: str) -> float:
    return float(KLINES_TTL_BY_INTERVAL.get(interval.lower(), 60))


def _klines_stale_fallback(symbol: str, interval: str) -> list:
    """Binance 418/429 veya ağ hatasında son bilinen mumları döndür (grafik boş kalmasın)."""
    best = None
    best_ts = 0.0
    sym = (symbol or "").upper()
    iv = (interval or "").lower()
    for key, (data, ts) in KLINES_CACHE.items():
        if not data or not isinstance(key, tuple) or len(key) < 2:
            continue
        if key[0] == sym and key[1] == iv:
            if ts > best_ts:
                best_ts = ts
                best = data
    return best if isinstance(best, list) else []


@router.get("/spot/klines")
async def get_spot_klines(
    symbol: str = Query(..., description="Trading pair (e.g. BTCUSDT)"),
    interval: str = Query("5m", description="Kline interval: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w"),
    limit: int = Query(48, ge=1, le=500, description="Number of candles"),
    end_time: Optional[int] = Query(None, description="Optional end time (ms). For backfill: older candles before this time."),
):
    """Public: Kline verisi (grafik). Geçersiz sembolde Binance çağrılmadan [] döner."""
    symbol = _normalize_spot_trading_symbol(symbol)
    if not symbol:
        return []
    interval = (interval or "5m").lower()
    cache_key = (symbol, interval, limit, end_time if end_time is not None else "latest")
    now = time.time()
    ttl = _klines_cache_ttl(interval)
    if cache_key in KLINES_CACHE:
        data, ts = KLINES_CACHE[cache_key]
        if now - ts < ttl:
            logger.debug("Klines cache hit %s", cache_key)
            return data
    if cache_key in KLINES_INFLIGHT:
        try:
            return await KLINES_INFLIGHT[cache_key]
        except Exception:
            pass
        KLINES_INFLIGHT.pop(cache_key, None)

    async def _fetch():
        stale = _klines_stale_fallback(symbol, interval)
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            if end_time is not None:
                params["endTime"] = end_time
            from app.services.binance_rest_log import rest_source
            from app.services.binance_spot import public_get_json, BinanceIPBannedError, DependencyFailure
            with rest_source("spot_routes.klines"):
                data = await public_get_json("/api/v3/klines", params, testnet=False)
            if not isinstance(data, list):
                return stale or []
            out = [{"t": c[0], "o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4]), "v": float(c[5])} for c in data]
            KLINES_CACHE[cache_key] = (out, time.time())
            return out
        except (BinanceIPBannedError, DependencyFailure) as e:
            if stale:
                logger.debug("Klines blocked symbol=%s interval=%s — serving stale cache", symbol, interval)
                return stale
            if isinstance(e, DependencyFailure) and "client error" in str(e).lower():
                logger.debug("Klines client error symbol=%s interval=%s: %s", symbol, interval, e)
            return []
        except Exception as e:
            logger.debug("Klines error symbol=%s interval=%s: %s", symbol, interval, e)
            if stale:
                return stale
            return []
        finally:
            KLINES_INFLIGHT.pop(cache_key, None)

    task = asyncio.create_task(_fetch())
    KLINES_INFLIGHT[cache_key] = task
    return await task


@router.get("/spot/ticker_24h")
async def get_spot_ticker_24h(
    symbol: str = Query(..., description="Trading pair (e.g. BTCUSDT)"),
):
    """24 saat özeti — DataHub (WS/REST); eksikse tek sembol REST doldurur."""
    sym = (symbol or "").upper().strip()
    if _is_invalid_spot_symbol(sym):
        return {"lowPrice": None, "highPrice": None, "priceChangePercent": None, "lastPrice": None, "available": False}
    try:
        from app.services.data_hub import data_hub
        from app.services.market_data import get_ticker_24h

        data_hub.pin_symbols([sym])
        out = get_ticker_24h(sym)
        if not out.get("available"):
            await data_hub.ensure_symbol_ticker_24h(sym)
            out = get_ticker_24h(sym)
        return out
    except Exception:
        pass
    return {"lowPrice": None, "highPrice": None, "priceChangePercent": None, "lastPrice": None, "available": False}


# Commission (tradeFee) cache: account_id -> (rates_dict, ts). TTL 30 min.
_commission_cache: Dict[int, Tuple[dict, float]] = {}
_COMMISSION_CACHE_TTL = 1800.0


@router.get("/spot/commission")
async def get_spot_commission(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Hesaba ait komisyon oranları. Auth zorunlu; account ownership doğrulanır."""
    get_account_or_403(current, account_id, db)
    default_rates = {"maker": 0.001, "taker": 0.001, "maker_pct": 0.1, "taker_pct": 0.1}
    now = time.time()
    if account_id in _commission_cache:
        cached, ts = _commission_cache[account_id]
        if now - ts < _COMMISSION_CACHE_TTL:
            return cached
    try:
        if get_account_keys is None:
            return default_rates
        keys = await get_account_keys(account_id, db)
        from app.services.spot_engine import SpotEngine
        async with SpotEngine(keys) as engine:
            rates = await engine.get_commission_rates()
            if rates:
                _commission_cache[account_id] = (rates, time.time())
                return rates
    except Exception as e:
        logger.debug("Commission fetch failed, using default: %s", e)
    return default_rates

async def _resolve_public_spot_price(sym: str) -> Dict:
    """DataHub/spot_cache — API anahtarı ve SpotEngine yok."""
    from app.services.market_data import resolve_price_fast

    if sym in _PRICE_INFLIGHT:
        try:
            return await _PRICE_INFLIGHT[sym]
        except Exception:
            _PRICE_INFLIGHT.pop(sym, None)

    async def _do() -> Dict:
        try:
            price, source, is_stale = resolve_price_fast(sym)
            if price is not None and price > 0:
                return {
                    "ok": True,
                    "symbol": sym,
                    "price": price,
                    "cached": source == "spot_cache",
                    "source": source,
                    "is_stale": is_stale,
                }
            valid = await _get_valid_spot_symbols_async()
            if valid and sym not in valid:
                return {"ok": False, "error_code": "INVALID_SYMBOL", "symbol": sym}
            return {"ok": True, "symbol": sym, "price": 0.0, "source": "none", "is_stale": True}
        finally:
            _PRICE_INFLIGHT.pop(sym, None)

    task = asyncio.create_task(_do())
    _PRICE_INFLIGHT[sym] = task
    return await task


@router.get("/spot/price")
async def get_spot_price(
    account_id: int = Query(..., description="Account ID"),
    symbol: str = Query(..., description="Trading pair symbol"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """
    Fiyat yalnızca DataHub/spot_cache (SSOT). Auth + rate limit; API key çekilmez.
    """
    get_account_or_403(current, account_id, db)
    sym = (symbol or "").upper().strip()
    if _is_invalid_spot_symbol(sym) or not _SPOT_SYMBOL_RE.match(sym):
        return {"ok": False, "error_code": "INVALID_SYMBOL", "symbol": sym}

    from app.core.security.endpoint_rate_limit import check_endpoint_rate_limit

    uid = int(current.get("user_id") or 0)
    allowed, retry = check_endpoint_rate_limit(
        f"spot_price:u{uid}",
        limit=int(os.getenv("SPOT_PRICE_RATE_LIMIT", "90")),
        window_sec=float(os.getenv("SPOT_PRICE_RATE_WINDOW_SEC", "10")),
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla fiyat isteği. Lütfen kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": str(retry)},
        )

    return await _resolve_public_spot_price(sym)

