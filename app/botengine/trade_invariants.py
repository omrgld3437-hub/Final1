"""Typed, decimal-safe invariants for grid and profit orders.

The strategy persists JSON-compatible floats, but every comparison and percentage
calculation in this module is performed with ``Decimal`` created from strings.
Exchange tick/step rounding belongs to the execution adapter, not here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping, Optional


class OrderType(str, Enum):
    BUY_GRID = "BUY_GRID"
    SELL_GRID = "SELL_GRID"
    PROFIT_SELL = "PROFIT_SELL"
    PROFIT_REBUY = "PROFIT_REBUY"


class CostBasisType(str, Enum):
    INITIAL_REFERENCE = "INITIAL_REFERENCE"
    WEIGHTED_BUY_COST = "WEIGHTED_BUY_COST"
    WEIGHTED_SELL_PRICE = "WEIGHTED_SELL_PRICE"


class OrderStatus(str, Enum):
    WAITING_TRIGGER = "WAITING_TRIGGER"
    TRAILING = "TRAILING"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


EXPECTED_COST_BASIS = {
    OrderType.BUY_GRID: CostBasisType.INITIAL_REFERENCE,
    OrderType.SELL_GRID: CostBasisType.INITIAL_REFERENCE,
    OrderType.PROFIT_SELL: CostBasisType.WEIGHTED_BUY_COST,
    OrderType.PROFIT_REBUY: CostBasisType.WEIGHTED_SELL_PRICE,
}


def decimal_value(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool):
        raise ValueError(f"invalid decimal value: {value!r}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite decimal value: {value!r}")
    return result


def price_from_reference(
    reference_price: Any,
    percentage: Any,
    order_type: OrderType,
) -> Decimal:
    reference = decimal_value(reference_price)
    pct = decimal_value(percentage) / Decimal("100")
    if reference <= 0 or pct < 0:
        raise ValueError("reference price must be positive and percentage non-negative")
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return reference * (Decimal("1") - pct)
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return reference * (Decimal("1") + pct)
    raise ValueError(f"unsupported order type: {order_type!r}")


def trigger_reached(order_type: OrderType, current_price: Any, trigger_price: Any) -> bool:
    current = decimal_value(current_price)
    trigger = decimal_value(trigger_price)
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return current <= trigger
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return current >= trigger
    raise ValueError(f"unsupported order type: {order_type!r}")


def update_extreme(order_type: OrderType, extreme_price: Any, current_price: Any) -> Decimal:
    extreme = decimal_value(extreme_price)
    current = decimal_value(current_price)
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return min(extreme, current)
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return max(extreme, current)
    raise ValueError(f"unsupported order type: {order_type!r}")


def completion_price(order_type: OrderType, extreme_price: Any, trailing_pct: Any) -> Decimal:
    extreme = decimal_value(extreme_price)
    pct = decimal_value(trailing_pct) / Decimal("100")
    if extreme <= 0 or pct < 0:
        raise ValueError("extreme price must be positive and trailing percentage non-negative")
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return extreme * (Decimal("1") + pct)
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return extreme * (Decimal("1") - pct)
    raise ValueError(f"unsupported order type: {order_type!r}")


def completion_reached(
    order_type: OrderType,
    current_price: Any,
    extreme_price: Any,
    trailing_pct: Any,
) -> bool:
    current = decimal_value(current_price)
    threshold = completion_price(order_type, extreme_price, trailing_pct)
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return current >= threshold
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return current <= threshold
    raise ValueError(f"unsupported order type: {order_type!r}")


def weighted_average_price(
    fills: Iterable[Mapping[str, Any]],
    *,
    required_side: Optional[str] = None,
    grid_only: bool = True,
) -> Optional[Decimal]:
    total_qty = Decimal("0")
    total_quote = Decimal("0")
    side_filter = required_side.upper() if required_side else None
    for fill in fills:
        if not isinstance(fill, Mapping):
            continue
        if side_filter and str(fill.get("side") or "").upper() not in ("", side_filter):
            continue
        if grid_only and fill.get("grid_index", fill.get("slot_id")) is None:
            continue
        try:
            qty = decimal_value(fill.get("fill_quantity", fill.get("qty")))
            price = decimal_value(fill.get("fill_price", fill.get("price")))
        except ValueError:
            continue
        if qty <= 0 or price <= 0:
            continue
        total_qty += qty
        total_quote += qty * price
    if total_qty <= 0:
        return None
    return total_quote / total_qty


def validate_cost_basis(order_type: OrderType, cost_basis_type: CostBasisType) -> None:
    expected = EXPECTED_COST_BASIS[order_type]
    if cost_basis_type != expected:
        raise ValueError(
            f"{order_type.value} requires {expected.value}, got {cost_basis_type.value}"
        )


def valid_extreme(order_type: OrderType, trigger_price: Any, extreme_price: Any) -> bool:
    trigger = decimal_value(trigger_price)
    extreme = decimal_value(extreme_price)
    if order_type in (OrderType.BUY_GRID, OrderType.PROFIT_REBUY):
        return extreme <= trigger
    if order_type in (OrderType.SELL_GRID, OrderType.PROFIT_SELL):
        return extreme >= trigger
    return False
