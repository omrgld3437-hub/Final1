"""Exchange filter simulation — lot/tick rounding."""

from __future__ import annotations

from typing import Any, Dict

# Typical Binance spot filters (audit defaults; live overrides via constraints)
DEFAULT_FILTERS: Dict[str, Dict[str, float]] = {
    "BTCUSDT": {"min_notional": 5.0, "step_size": 0.00001, "tick_size": 0.01, "price": 65000},
    "ETHUSDT": {"min_notional": 5.0, "step_size": 0.0001, "tick_size": 0.01, "price": 3500},
    "SOLUSDT": {"min_notional": 5.0, "step_size": 0.001, "tick_size": 0.01, "price": 150},
    "AVAXUSDT": {"min_notional": 5.0, "step_size": 0.01, "tick_size": 0.01, "price": 35},
    "BNBUSDT": {"min_notional": 5.0, "step_size": 0.001, "tick_size": 0.01, "price": 600},
    "ADAUSDT": {"min_notional": 5.0, "step_size": 0.1, "tick_size": 0.0001, "price": 0.45},
    "XRPUSDT": {"min_notional": 5.0, "step_size": 0.1, "tick_size": 0.0001, "price": 0.55},
    "LINKUSDT": {"min_notional": 5.0, "step_size": 0.01, "tick_size": 0.01, "price": 14},
    "AAVEUSDT": {"min_notional": 5.0, "step_size": 0.001, "tick_size": 0.01, "price": 90},
}


def quantize_down(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    import math
    return math.floor(qty / step) * step


def simulate_order_notional(
    *,
    side: str,
    budget_usdt: float,
    grid_pct: float,
    dist_pct: float,
    symbol: str,
    min_notional: float,
) -> Dict[str, Any]:
    f = DEFAULT_FILTERS.get(symbol, DEFAULT_FILTERS["ETHUSDT"])
    price = f["price"]
    step = f["step_size"]
    if side.upper() == "BUY":
        quote = budget_usdt * (dist_pct / 100.0)
        qty = quantize_down(quote / price, step)
        notional = qty * price
    else:
        qty = quantize_down(budget_usdt / price * (dist_pct / 100.0), step)
        notional = qty * price
    return {
        "side": side,
        "symbol": symbol,
        "budget_usdt": budget_usdt,
        "notional_after_round": round(notional, 4),
        "min_notional": min_notional,
        "passes": notional >= min_notional - 1e-6,
        "qty": qty,
    }
