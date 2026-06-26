"""Exchange filter validation for parameter profiles."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def floor_to_step(qty: float, step_size: float) -> float:
    step = max(float(step_size or 0), 0.0)
    if step <= 0:
        return max(float(qty or 0), 0.0)
    return math.floor(max(float(qty or 0), 0.0) / step) * step


def round_price(price: float, tick_size: float) -> float:
    tick = max(float(tick_size or 0), 0.0)
    if tick <= 0:
        return float(price or 0)
    return round(float(price or 0) / tick) * tick


def validate_grid_notionals(
    side_budget_usdt: float,
    distribution: List[float],
    min_notional: float,
    *,
    price: float = 100.0,
    step_size: float = 0.001,
    min_qty: float = 0.0,
) -> Tuple[bool, List[float]]:
    """Check each grid level meets minNotional after rounding."""
    if side_budget_usdt < min_notional:
        return False, []
    notionals: List[float] = []
    for w in distribution:
        alloc = side_budget_usdt * float(w)
        if price > 0 and step_size > 0:
            qty = floor_to_step(alloc / price, step_size)
            notional = qty * price
        else:
            notional = alloc
        if notional < min_notional - 1e-9:
            return False, notionals
        if min_qty > 0 and price > 0 and qty < min_qty:
            return False, notionals
        notionals.append(notional)
    return True, notionals


def reduce_grid_count_for_notional(
    grid_count: int,
    side_budget_usdt: float,
    min_notional: float,
    distribution_fn,
) -> Tuple[int, List[float], bool]:
    """Reduce grid count until min-notional satisfied — never narrow spacing."""
    n = max(1, int(grid_count))
    while n >= 1:
        dist = distribution_fn(n)
        ok, _ = validate_grid_notionals(side_budget_usdt, dist, min_notional)
        if ok:
            return n, dist, True
        n -= 1
    return 0, [], False


def exchange_filters_valid(
    constraints: Dict[str, Any],
) -> bool:
    return (
        float(constraints.get("min_notional") or 0) > 0
        and float(constraints.get("step_size") or 0) >= 0
        and float(constraints.get("tick_size") or 0) >= 0
    )
