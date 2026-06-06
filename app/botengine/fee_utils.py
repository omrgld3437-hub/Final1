"""Binance spot fill commission → USDT normalization."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def symbol_base_asset(symbol: str) -> str:
    sym = (symbol or "").upper()
    for quote in ("USDT", "BUSD", "USDC", "FDUSD", "TRY", "BTC", "ETH"):
        if sym.endswith(quote) and len(sym) > len(quote):
            return sym[: -len(quote)]
    return ""


def commission_to_usdt(
    fee: float,
    fee_asset: str,
    symbol: str,
    fill_price: float,
) -> float:
    """
    Binance spot: BUY komisyonu genelde base coin (ETH), SELL komisyonu quote (USDT).
    fee: commission miktarı (Binance fills[].commission).
    """
    try:
        amount = float(fee or 0)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0:
        return 0.0
    asset = (fee_asset or "USDT").strip().upper()
    if asset == "USDT":
        return amount
    try:
        px = float(fill_price or 0)
    except (TypeError, ValueError):
        px = 0.0
    base = symbol_base_asset(symbol)
    if base and asset == base and px > 0:
        return amount * px
    try:
        from app.services.price_hub import price_hub

        pair = asset + "USDT"
        p = price_hub.get_price(pair) or price_hub.get_price("USDT" + asset)
        if p is not None and float(p) > 0:
            return amount * float(p)
    except Exception:
        pass
    return 0.0


def parse_fill_commission(
    fills: List[Dict[str, Any]],
    symbol: str,
    fill_price: float,
) -> Tuple[float, str, float]:
    """Returns (fee_raw, fee_asset, fee_usdt)."""
    if not fills:
        return 0.0, "USDT", 0.0
    fee_raw = 0.0
    for f in fills:
        if not isinstance(f, dict):
            continue
        try:
            fee_raw += float(f.get("commission") or 0)
        except (TypeError, ValueError):
            pass
    fee_asset = (fills[0].get("commissionAsset") or "USDT").strip().upper()
    fee_usdt = commission_to_usdt(fee_raw, fee_asset, symbol, fill_price)
    return fee_raw, fee_asset, fee_usdt
