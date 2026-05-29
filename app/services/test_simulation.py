"""
Test hesabı paper simülasyonu: gerçek hesaba yakın komisyon, kayma, emir/tick gecikmesi.
Yalnızca test hesabı / paper_mode bot yürütmesi için kullanılır.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Binance spot varsayılan taker (~0.1%); dashboard fee_rates ile uyumlu
TEST_TAKER_FEE_RATE = 0.001
TEST_SLIPPAGE_BPS = 5
TEST_ORDER_LATENCY_MS_MIN = 120
TEST_ORDER_LATENCY_MS_MAX = 450
TEST_TICK_JITTER_FRAC = 0.10


def taker_fee_rate(config_fee: Optional[float] = None) -> float:
    if config_fee is not None and float(config_fee) > 0:
        return min(0.01, max(0.0, float(config_fee)))
    return TEST_TAKER_FEE_RATE


def slippage_fill_price(side: str, mid_price: float, slippage_bps: int = TEST_SLIPPAGE_BPS) -> float:
    """Market emir: alış biraz yukarı, satış biraz aşağı."""
    mid = float(mid_price or 0)
    if mid <= 0:
        return 0.0
    slip = max(0, int(slippage_bps)) / 10000.0
    side_u = (side or "").upper()
    if side_u == "BUY":
        return mid * (1.0 + slip)
    if side_u == "SELL":
        return mid * (1.0 - slip)
    return mid


def _quantize(qty: float, step: str = "0.00000001") -> float:
    try:
        return float(Decimal(str(qty)).quantize(Decimal(str(step)), rounding=ROUND_DOWN))
    except Exception:
        return round(float(qty), 8)


def _base_from_symbol(symbol: str) -> str:
    sym = (symbol or "").upper()
    for q in ("USDT", "BUSD", "USDC", "FDUSD"):
        if sym.endswith(q) and len(sym) > len(q):
            return sym[: -len(q)]
    return sym.replace("USDT", "")


def build_paper_market_fill(
    symbol: str,
    side: str,
    *,
    quote_qty: Optional[float] = None,
    base_qty: Optional[float] = None,
    mid_price: float,
    fee_rate: float = TEST_TAKER_FEE_RATE,
    slippage_bps: int = TEST_SLIPPAGE_BPS,
    client_order_id: str = "",
    step_size: str = "0.00000001",
) -> Dict[str, Any]:
    """
    Binance market fill benzeri yanıt: taker komisyon (BUY→base, SELL→USDT), kayma, fills[].
    """
    sym = (symbol or "").upper()
    side_u = (side or "").upper()
    base = _base_from_symbol(sym)
    fee_rate = taker_fee_rate(fee_rate)
    fill_px = slippage_fill_price(side_u, float(mid_price), slippage_bps)
    if fill_px <= 0:
        raise ValueError(f"Price stale or missing for {sym}")

    if side_u == "BUY":
        quote_in = float(quote_qty or 0)
        if quote_in <= 0:
            raise ValueError("quote_qty required for BUY")
        gross_base = quote_in / fill_px
        fee_base = gross_base * fee_rate
        net_base = _quantize(max(0.0, gross_base - fee_base), step_size)
        if net_base <= 0:
            raise ValueError("Miktar çok küçük (komisyon sonrası)")
        cum_quote = round(quote_in, 8)
        fills = [
            {
                "price": str(fill_px),
                "qty": str(net_base),
                "commission": str(round(fee_base, 12)),
                "commissionAsset": base,
            }
        ]
    elif side_u == "SELL":
        qty_in = float(base_qty or 0)
        if qty_in <= 0:
            raise ValueError("base_qty required for SELL")
        net_base = _quantize(qty_in, step_size)
        gross_quote = net_base * fill_px
        fee_usdt = gross_quote * fee_rate
        cum_quote = round(max(0.0, gross_quote - fee_usdt), 8)
        fills = [
            {
                "price": str(fill_px),
                "qty": str(net_base),
                "commission": str(round(fee_usdt, 8)),
                "commissionAsset": "USDT",
            }
        ]
    else:
        raise ValueError(f"Invalid side: {side}")

    return {
        "orderId": int(time.time() * 1000),
        "clientOrderId": client_order_id,
        "symbol": sym,
        "status": "FILLED",
        "executedQty": str(net_base),
        "cummulativeQuoteQty": str(cum_quote),
        "fills": fills,
        "paper": True,
        "simulated": True,
    }


def paper_buy_from_quote(
    quote_in: float,
    mid_price: float,
    symbol: str = "BTCUSDT",
    fee_rate: float = TEST_TAKER_FEE_RATE,
    slippage_bps: int = TEST_SLIPPAGE_BPS,
    step_size: str = "0.00000001",
) -> Tuple[float, float, float, float]:
    """Returns (net_base, cum_quote, fill_price, fee_usdt)."""
    sym = (symbol or "BTCUSDT").upper()
    fill = build_paper_market_fill(
        sym,
        "BUY",
        quote_qty=quote_in,
        mid_price=mid_price,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        step_size=step_size,
    )
    from app.botengine.fee_utils import parse_fill_commission

    net_base = float(fill["executedQty"])
    cum_quote = float(fill["cummulativeQuoteQty"])
    fill_px = float((fill.get("fills") or [{}])[0].get("price") or 0)
    _, _, fee_usdt = parse_fill_commission(fill.get("fills") or [], sym, fill_px)
    return net_base, cum_quote, fill_px, fee_usdt


def paper_sell_from_base(
    base_in: float,
    mid_price: float,
    symbol: str = "BTCUSDT",
    fee_rate: float = TEST_TAKER_FEE_RATE,
    slippage_bps: int = TEST_SLIPPAGE_BPS,
    step_size: str = "0.00000001",
) -> Tuple[float, float, float, float]:
    """Returns (sold_base, net_quote, fill_price, fee_usdt)."""
    sym = (symbol or "BTCUSDT").upper()
    fill = build_paper_market_fill(
        sym,
        "SELL",
        base_qty=base_in,
        mid_price=mid_price,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        step_size=step_size,
    )
    from app.botengine.fee_utils import parse_fill_commission

    sold = float(fill["executedQty"])
    net_quote = float(fill["cummulativeQuoteQty"])
    fill_px = float((fill.get("fills") or [{}])[0].get("price") or 0)
    _, _, fee_usdt = parse_fill_commission(fill.get("fills") or [], sym, fill_px)
    return sold, net_quote, fill_px, fee_usdt


async def await_paper_order_latency() -> None:
    lo = TEST_ORDER_LATENCY_MS_MIN
    hi = max(lo, TEST_ORDER_LATENCY_MS_MAX)
    ms = random.randint(lo, hi)
    await asyncio.sleep(ms / 1000.0)


def sync_paper_order_latency() -> None:
    lo = TEST_ORDER_LATENCY_MS_MIN
    hi = max(lo, TEST_ORDER_LATENCY_MS_MAX)
    time.sleep(random.randint(lo, hi) / 1000.0)


def paper_tick_sleep_seconds(base_wake: float, paper_mode: bool) -> float:
    """Bot tick aralığına hafif jitter (paper)."""
    base = max(0.5, float(base_wake or 1.0))
    if not paper_mode:
        return base
    jitter = base * random.uniform(0, TEST_TICK_JITTER_FRAC)
    return base + jitter
