"""Market data and portfolio state collection for Dynamic Param Score Engine."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BtcReferenceData,
    BotContext,
    Candle,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
from app.services.dynamic_param_score import constants as C

logger = logging.getLogger(__name__)

_KLINES_CACHE: Dict[tuple, tuple] = {}
_KLINES_TTL = {"5m": 60.0, "15m": 180.0, "1h": 600.0, "4h": 1200.0, "1m": 20.0}


def _parse_symbol(symbol: str) -> Tuple[str, str, str]:
    s = (symbol or "").upper().strip().replace("/", "").replace("-", "")
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "TRY", "BTC", "ETH"):
        if s.endswith(q) and len(s) > len(q):
            return s, s[: -len(q)], q
    return s + "USDT", s, "USDT"


async def _fetch_klines(symbol: str, interval: str, limit: int) -> List[Candle]:
    total = int(limit)
    if total <= C.BINANCE_KLINES_MAX_PER_REQUEST:
        return await _fetch_klines_single(symbol, interval, total)
    return await _fetch_klines_paginated(symbol, interval, total)


async def _fetch_klines_single(
    symbol: str,
    interval: str,
    limit: int,
    *,
    end_time_ms: Optional[int] = None,
) -> List[Candle]:
    key = (symbol.upper(), interval.lower(), int(limit), end_time_ms)
    now = time.time()
    cached = _KLINES_CACHE.get(key)
    ttl = _KLINES_TTL.get(interval.lower(), 60.0)
    if cached and now - cached[1] < ttl:
        return cached[0]
    try:
        from app.services.binance_rest_log import rest_source
        from app.services.binance_spot import public_get_json

        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        with rest_source("dynamic_param_score.klines"):
            data = await public_get_json(
                "/api/v3/klines",
                params,
                testnet=False,
            )
        if not isinstance(data, list):
            return cached[0] if cached else []
        out: List[Candle] = []
        for c in data:
            try:
                out.append(
                    Candle(
                        t=int(c[0]),
                        o=float(c[1]),
                        h=float(c[2]),
                        l=float(c[3]),
                        c=float(c[4]),
                        v=float(c[5]),
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue
        if out:
            _KLINES_CACHE[key] = (out, now)
        return out or (cached[0] if cached else [])
    except Exception as e:
        logger.warning("DPS klines fetch failed %s %s: %s", symbol, interval, e)
        return cached[0] if cached else []


async def _fetch_klines_paginated(symbol: str, interval: str, total_limit: int) -> List[Candle]:
    """Fetch more than 1000 candles via backward pagination."""
    cache_key = (symbol.upper(), interval.lower(), int(total_limit), "paginated")
    now = time.time()
    cached = _KLINES_CACHE.get(cache_key)
    ttl = _KLINES_TTL.get(interval.lower(), 60.0)
    if cached and now - cached[1] < ttl:
        return cached[0]

    remaining = int(total_limit)
    end_time: Optional[int] = None
    batches: List[Candle] = []
    max_batch = C.BINANCE_KLINES_MAX_PER_REQUEST

    while remaining > 0:
        batch_size = min(remaining, max_batch)
        chunk = await _fetch_klines_single(
            symbol, interval, batch_size, end_time_ms=end_time
        )
        if not chunk:
            break
        batches = chunk + batches
        remaining -= len(chunk)
        if len(chunk) < batch_size:
            break
        end_time = chunk[0].t - 1

    # Dedupe by timestamp, keep order
    seen: set = set()
    out: List[Candle] = []
    for c in batches:
        if c.t in seen:
            continue
        seen.add(c.t)
        out.append(c)
    out.sort(key=lambda x: x.t)
    if len(out) > total_limit:
        out = out[-total_limit:]
    if out:
        _KLINES_CACHE[cache_key] = (out, now)
    return out or (cached[0] if cached else [])


async def _fetch_orderbook_top(symbol: str) -> Optional[Dict[str, float]]:
    try:
        from app.services.binance_rest_log import rest_source
        from app.services.binance_spot import public_get_json

        with rest_source("dynamic_param_score.orderbook"):
            data = await public_get_json(
                "/api/v3/ticker/bookTicker",
                {"symbol": symbol.upper()},
                testnet=False,
            )
        if not isinstance(data, dict):
            return None
        bid = float(data.get("bidPrice") or 0)
        ask = float(data.get("askPrice") or 0)
        if bid > 0 and ask > bid:
            return {"bid": bid, "ask": ask}
    except Exception:
        pass
    return None


def _return_pct(candles: List[Candle], n: int) -> Optional[float]:
    if len(candles) < n + 1:
        return None
    a, b = candles[-n - 1].c, candles[-1].c
    if a <= 0:
        return None
    return (b - a) / a * 100.0


def _last_positive_close(candles: Optional[List[Candle]]) -> float:
    if not candles:
        return 0.0
    for c in reversed(candles):
        if c.c and c.c > 0:
            return float(c.c)
    return 0.0


def _volume_from_klines_24h(c1h: Optional[List[Candle]]) -> tuple[float, float]:
    """Estimate 24h base + quote volume from hourly candles when DataHub cache is empty."""
    if not c1h:
        return 0.0, 0.0
    seg = c1h[-24:] if len(c1h) >= 24 else c1h
    base_vol = 0.0
    quote_vol = 0.0
    for c in seg:
        if c.v and c.v > 0 and c.c and c.c > 0:
            base_vol += float(c.v)
            quote_vol += float(c.v) * float(c.c)
    return base_vol, quote_vol


def _enrich_market_bundle_from_klines(
    *,
    price: float,
    vol: float,
    qvol: float,
    c5: Optional[List[Candle]],
    c1h: Optional[List[Candle]],
) -> tuple[float, float, float, Optional[str]]:
    """
    DPS/Param Assistant must not treat missing DataHub ticker as NO_DATA/LOW_LIQUIDITY
    when Binance klines already provide price and volume context.
    Returns (price, vol, qvol, price_source_tag).
    """
    price_source: Optional[str] = None
    if price <= 0:
        for candles in (c5, c1h):
            px = _last_positive_close(candles)
            if px > 0:
                price = px
                price_source = "klines_close"
                break
    if qvol <= 0 and vol <= 0:
        base_vol, quote_vol = _volume_from_klines_24h(c1h)
        if base_vol > 0:
            vol = base_vol
        if quote_vol > 0:
            qvol = quote_vol
    elif qvol <= 0 and vol > 0 and price > 0:
        qvol = vol * price
    return price, vol, qvol, price_source


async def _btc_reference() -> Optional[BtcReferenceData]:
    try:
        c1h = await _fetch_klines("BTCUSDT", "1h", C.KLINES_LIMIT_1H)
        c4h = await _fetch_klines("BTCUSDT", "4h", C.KLINES_LIMIT_4H)
        if not c1h:
            return None
        from app.botengine.dynamic import indicators as dyn_ind

        closes = [c.c for c in c1h]
        ema200 = dyn_ind.ema_last(closes, 200) if len(closes) >= 200 else None
        price = c1h[-1].c
        crash = None
        if len(closes) >= 7:
            rets = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(-6, 0) if closes[i - 1] > 0]
            crash = min(rets) if rets else None
        return BtcReferenceData(
            candles_1h=c1h,
            candles_4h=c4h or None,
            return_1h_pct=_return_pct(c1h, 1),
            return_4h_pct=_return_pct(c4h, 1) if c4h else _return_pct(c1h, 4),
            return_24h_pct=_return_pct(c1h, 24),
            price=price,
            ema200_1h=ema200,
            crash_velocity=crash,
        )
    except Exception as e:
        logger.warning("BTC reference fetch failed: %s", e)
        return None


async def collect_market_data(symbol: str) -> MarketDataBundle:
    sym, base, quote = _parse_symbol(symbol)
    from app.services.market_data import get_price_with_meta, get_ticker_24h

    meta = get_price_with_meta(sym) or {}
    ticker = get_ticker_24h(sym)
    price = float(meta.get("price") or ticker.get("lastPrice") or 0)
    vol = float(meta.get("volume24h") or 0)
    qvol = float(meta.get("quoteVolume24h") or vol * price if price else 0)

    c5, c15, c1h, c4h, c1m, ob, btc = await _gather_parallel(sym)
    price, vol, qvol, price_source = _enrich_market_bundle_from_klines(
        price=price,
        vol=vol,
        qvol=qvol,
        c5=c5,
        c1h=c1h,
    )
    data_window = {
        "window_days": C.DATA_WINDOW_DAYS,
        "5m": {"actual": len(c5 or []), "expected": C.KLINES_LIMIT_5M},
        "15m": {"actual": len(c15 or []), "expected": C.KLINES_LIMIT_15M},
        "1h": {"actual": len(c1h or []), "expected": C.KLINES_LIMIT_1H},
        "4h": {"actual": len(c4h or []), "expected": C.KLINES_LIMIT_4H},
        "1m": {"actual": len(c1m or []), "expected": C.KLINES_LIMIT_1M},
    }
    if price_source:
        data_window["price_source"] = price_source
    if (meta.get("price") or ticker.get("lastPrice") or 0) in (0, None, "") and qvol > 0:
        data_window["volume_source"] = "klines_1h"
    bundle = MarketDataBundle(
        symbol=sym,
        base_asset=base,
        quote_asset=quote,
        candles_1m=c1m or None,
        candles_5m=c5 or None,
        candles_15m=c15 or None,
        candles_1h=c1h or None,
        candles_4h=c4h or None,
        ticker_price=price,
        orderbook_top=ob,
        volume_24h=vol,
        quote_volume_24h=qvol,
        btc_reference_data=btc,
        market_timestamp=int(time.time() * 1000),
        data_window=data_window,
    )
    return bundle


async def _gather_parallel(sym: str):
    import asyncio

    return await asyncio.gather(
        _fetch_klines(sym, "5m", C.KLINES_LIMIT_5M),
        _fetch_klines(sym, "15m", C.KLINES_LIMIT_15M),
        _fetch_klines(sym, "1h", C.KLINES_LIMIT_1H),
        _fetch_klines(sym, "4h", C.KLINES_LIMIT_4H),
        _fetch_klines(sym, "1m", C.KLINES_LIMIT_1M),
        _fetch_orderbook_top(sym),
        _btc_reference(),
    )


def default_exchange_constraints(symbol: str) -> ExchangeConstraints:
    """Sensible defaults; live bot path should pass real filters."""
    return ExchangeConstraints(
        min_notional=DEFAULT_MIN_NOTIONAL_USDT,
        step_size=0.0001,
        tick_size=0.01,
        min_qty=0.0001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )


def portfolio_from_budget(budget: float, price: float = 0.0) -> PortfolioState:
    """Fresh start portfolio for param assistant."""
    return PortfolioState(
        base_balance=0.0,
        quote_balance=budget,
        base_value_usdt=0.0,
        quote_value_usdt=budget,
        total_equity_usdt=budget,
        current_base_exposure_frac=0.0,
        open_orders_count=0,
        open_buy_orders_count=0,
        open_sell_orders_count=0,
    )


def portfolio_from_user_scenario(
    *,
    quote_budget_usdt: float,
    price: float = 0.0,
    base_balance_usdt: Optional[float] = None,
    quote_balance_usdt: Optional[float] = None,
    base_alloc_frac: Optional[float] = None,
) -> PortfolioState:
    """Build portfolio like Param Assistant UI (base + quote balances)."""
    total = max(float(quote_budget_usdt or 0.0), 0.0)
    px = max(float(price or 0.0), 0.0)
    if base_alloc_frac is not None and total > 0:
        base_val = total * max(0.0, min(1.0, float(base_alloc_frac)))
        quote_val = total - base_val
    elif base_balance_usdt is not None:
        base_val = max(0.0, float(base_balance_usdt))
        quote_val = float(quote_balance_usdt) if quote_balance_usdt is not None else max(0.0, total - base_val)
        total = base_val + quote_val
    else:
        base_val = 0.0
        quote_val = float(quote_balance_usdt) if quote_balance_usdt is not None else total
        total = base_val + quote_val
    base_qty = base_val / px if px > 0 and base_val > 0 else 0.0
    exp = base_val / total if total > 0 else 0.0
    return PortfolioState(
        base_balance=base_qty,
        quote_balance=quote_val,
        base_value_usdt=base_val,
        quote_value_usdt=quote_val,
        total_equity_usdt=total,
        current_base_exposure_frac=exp,
        open_orders_count=0,
        open_buy_orders_count=0,
        open_sell_orders_count=0,
    )


def portfolio_from_bot_state(state: Dict[str, Any], price: float) -> PortfolioState:
    """Build portfolio from live bot engine state."""
    base = float(state.get("base_balance") or 0.0)
    quote = float(state.get("quote_balance") or 0.0)
    base_val = base * price if price > 0 else 0.0
    quote_val = quote
    total = base_val + quote_val
    exp = base_val / total if total > 0 else 0.0
    open_orders = state.get("open_orders") or []
    buy_n = sum(1 for o in open_orders if str(o.get("side", "")).upper() == "BUY")
    sell_n = sum(1 for o in open_orders if str(o.get("side", "")).upper() == "SELL")
    avg_entry = state.get("avg_entry_price") or state.get("average_entry_price")
    return PortfolioState(
        base_balance=base,
        quote_balance=quote,
        base_value_usdt=base_val,
        quote_value_usdt=quote_val,
        total_equity_usdt=total,
        current_base_exposure_frac=exp,
        average_entry_price=float(avg_entry) if avg_entry else None,
        unrealized_pnl_pct=state.get("unrealized_pnl_pct"),
        realized_pnl_cycle_pct=state.get("realized_pnl_cycle_pct"),
        open_orders_count=len(open_orders),
        open_buy_orders_count=buy_n,
        open_sell_orders_count=sell_n,
    )


def resolve_first_start_flags(
    *,
    run_source: str,
    portfolio: PortfolioState,
    first_start_buy_only: Optional[bool] = None,
) -> tuple[bool, bool]:
    """Param Assistant ilk kurulum: base yok → is_first_start; varsayılan sadece alış grid."""
    from app.services.dynamic_param_score.consumer_policy import (
        policy_for,
        resolve_first_start_flags as _resolve,
    )

    return _resolve(policy_for(run_source), portfolio, first_start_buy_only=first_start_buy_only)


def build_bot_context(
    *,
    run_source: str,
    budget_usdt: float,
    portfolio: PortfolioState,
    first_start_buy_only: Optional[bool] = None,
    allow_live: bool = True,
    allow_no_trade: bool = True,
    bot_id: Optional[int] = None,
    current_round_id: Optional[str] = None,
    previous_round_id: Optional[str] = None,
    last_rebalance_round_id: Optional[str] = None,
) -> BotContext:
    """Generic BotContext builder — prefer build_param_assistant_context / build_dynamic_round_context."""
    from app.services.dynamic_param_score.consumer_policy import (
        build_dynamic_round_context,
        build_param_assistant_context,
        normalize_run_source,
    )

    rs = normalize_run_source(run_source)
    if rs == "param_assistant":
        ctx = build_param_assistant_context(
            budget_usdt=budget_usdt,
            portfolio=portfolio,
            first_start_buy_only=first_start_buy_only,
            allow_live=allow_live,
            allow_no_trade=allow_no_trade,
        )
        return ctx
    cycle_id = int(current_round_id or 1)
    return build_dynamic_round_context(
        budget_usdt=budget_usdt,
        cycle_id=cycle_id,
        bot_id=bot_id,
        last_rebalance_round_id=last_rebalance_round_id,
        allow_live=allow_live,
        allow_no_trade=allow_no_trade,
    )
