"""
Binance LOT_SIZE-safe base quantity formatting (bot engine).
Uses step_size_str from exchangeInfo — float log10 precision is not reliable.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, Optional, Tuple


def step_decimals(step_str: str) -> int:
    s = str(step_str or "").strip()
    if not s or "e" in s.lower():
        try:
            s = format(Decimal(str(step_str)), "f")
        except Exception:
            return 8
    if "." in s:
        frac = s.split(".")[-1]
        return len(frac.rstrip("0") or frac)
    return 0


def quantize_qty_down(value: float, step_str: str) -> Tuple[float, str]:
    """Floor quantity to LOT_SIZE step; return (float, string for API)."""
    if value <= 0:
        return 0.0, "0"
    try:
        step_d = Decimal(str(step_str).strip() or "0.00001")
        if step_d <= 0:
            step_d = Decimal("0.00001")
        value_d = Decimal(str(value))
        q = (value_d / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d
        if q <= 0:
            return 0.0, "0"
        decimals = step_decimals(step_str or "0.00001")
        qty_str = format(q, f".{decimals}f")
        return float(q), qty_str
    except Exception:
        import math

        step = float(step_str) if step_str else 0.00001
        if step <= 0:
            step = 0.00001
        q = math.floor(value / step) * step
        decimals = step_decimals(str(step))
        qty_str = format(Decimal(str(round(q, decimals))), f".{decimals}f")
        return float(qty_str), qty_str


def normalize_symbol_filters(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure string + float fields for adapter / execution."""
    step_str = str(raw.get("step_size_str") or raw.get("stepSize") or "").strip()
    if not step_str:
        step_f = float(raw.get("step_size") or 0.00001)
        step_str = (
            format(Decimal(str(step_f)), "f").rstrip("0").rstrip(".") or "0.00001"
        )
    min_str = str(raw.get("min_qty_str") or raw.get("minQty") or "").strip() or step_str
    tick_str = (
        str(raw.get("tick_size_str") or raw.get("tickSize") or "0.01").strip() or "0.01"
    )
    return {
        "step_size_str": step_str,
        "min_qty_str": min_str,
        "tick_size_str": tick_str,
        "step_size": float(raw.get("step_size") or step_str),
        "min_qty": float(raw.get("min_qty") or min_str),
        "tick_size": float(raw.get("tick_size") or tick_str),
        "min_notional": float(raw.get("min_notional") or raw.get("minNotional") or 5.0),
        "base_asset": raw.get("base_asset") or raw.get("baseAsset"),
        "quote_asset": raw.get("quote_asset") or raw.get("quoteAsset"),
    }


def validate_market_sell_qty(
    qty: float,
    filters: Dict[str, Any],
    price: Optional[float],
) -> Tuple[Optional[str], float, str]:
    """
    Preflight SELL quantity against exchange LOT_SIZE / MIN_NOTIONAL.
    Returns (skip_reason, adjusted_qty, qty_str). skip_reason is None when OK.
    """
    norm = normalize_symbol_filters(filters)
    step_str = norm["step_size_str"]
    min_qty = norm["min_qty"]
    min_notional = norm["min_notional"]

    qty_f, qty_str = quantize_qty_down(qty, step_str)
    if qty_f <= 0 or qty_str == "0":
        return "LOT_SIZE", 0.0, "0"
    if qty_f + 1e-15 < min_qty:
        return "LOT_SIZE", qty_f, qty_str
    if price and price > 0:
        notional = qty_f * price
        if notional + 1e-8 < min_notional:
            return "MIN_NOTIONAL", qty_f, qty_str
    return None, qty_f, qty_str
