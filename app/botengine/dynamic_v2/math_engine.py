"""Deterministic Decimal mathematics for market features and constraints."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Iterable, List, Sequence

from .models import Candle, ONE, ZERO, decimal_value


D = Decimal
EPSILON = D("0.000000000001")


def clip(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(maximum, value))


def clip01(value: Decimal) -> Decimal:
    return clip(value, ZERO, ONE)


def mean(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    return sum(items, ZERO) / D(len(items)) if items else ZERO


def median(values: Sequence[Decimal]) -> Decimal:
    items = sorted(values)
    if not items:
        return ZERO
    middle = len(items) // 2
    if len(items) % 2:
        return items[middle]
    return (items[middle - 1] + items[middle]) / D("2")


def robust_z(value: Decimal, history: Sequence[Decimal]) -> Decimal:
    med = median(history)
    mad = median([abs(x - med) for x in history])
    return clip((value - med) / (D("1.4826") * mad + EPSILON), D("-5"), D("5"))


def log_returns(candles: Sequence[Candle]) -> List[Decimal]:
    out: List[Decimal] = []
    for previous, current in zip(candles, candles[1:]):
        if previous.close > ZERO and current.close > ZERO:
            out.append((current.close / previous.close).ln())
    return out


def true_ranges(candles: Sequence[Candle]) -> List[Decimal]:
    out: List[Decimal] = []
    for previous, current in zip(candles, candles[1:]):
        out.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return out


def atr_percentage(candles: Sequence[Candle], period: int = 14) -> Decimal:
    if not candles or candles[-1].close <= ZERO:
        return ZERO
    ranges = true_ranges(candles)
    selected = ranges[-period:]
    return mean(selected) / candles[-1].close if selected else ZERO


def realized_volatility(returns: Sequence[Decimal]) -> Decimal:
    return mean([value * value for value in returns]).sqrt() if returns else ZERO


def downside_volatility(returns: Sequence[Decimal]) -> Decimal:
    return (
        mean([min(value, ZERO) ** 2 for value in returns]).sqrt()
        if returns
        else ZERO
    )


def upside_volatility(returns: Sequence[Decimal]) -> Decimal:
    return (
        mean([max(value, ZERO) ** 2 for value in returns]).sqrt()
        if returns
        else ZERO
    )


def wick_ratios(candle: Candle) -> tuple[Decimal, Decimal]:
    candle_range = candle.high - candle.low
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    return upper / (candle_range + EPSILON), lower / (candle_range + EPSILON)


def spread(best_bid: Decimal, best_ask: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    if best_bid <= ZERO or best_ask <= best_bid:
        raise ValueError("invalid best bid/ask")
    mid = (best_bid + best_ask) / D("2")
    percentage = (best_ask - best_bid) / mid
    return mid, percentage, percentage * D("10000")


def order_book_imbalance(bid_depth: Decimal, ask_depth: Decimal) -> Decimal:
    return (bid_depth - ask_depth) / (bid_depth + ask_depth + EPSILON)


def quantize_multiplier(
    raw: Decimal, minimum: Decimal, maximum: Decimal
) -> Decimal:
    clipped = clip(raw, minimum, maximum)
    return (clipped * D("10")).quantize(ONE, rounding=ROUND_HALF_UP) / D("10")


def quantize_base_step(raw_percentage_points: Decimal) -> Decimal:
    step = (raw_percentage_points / D("5")).quantize(
        ONE, rounding=ROUND_HALF_UP
    ) * D("5")
    return clip(step, D("-20"), D("20"))


def normalize_weights(values: Sequence[Decimal]) -> List[Decimal]:
    if not values:
        return []
    if any(value < ZERO for value in values):
        raise ValueError("negative weight")
    total = sum(values, ZERO)
    if total <= ZERO:
        equal = ONE / D(len(values))
        result = [equal for _ in values]
    else:
        result = [value / total for value in values]
    result[-1] += ONE - sum(result, ZERO)
    return result


def relative_change(old: Decimal, new: Decimal) -> Decimal:
    return abs(new - old) / max(abs(old), EPSILON)


def apply_deadband(old: Decimal, new: Decimal, threshold: Decimal) -> Decimal:
    return old if relative_change(old, new) < threshold else new


def limit_relative_change(
    old: Decimal, new: Decimal, maximum_change: Decimal
) -> Decimal:
    if old == ZERO:
        return new
    low = old * (ONE - maximum_change)
    high = old * (ONE + maximum_change)
    return clip(new, min(low, high), max(low, high))


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= ZERO:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def floor_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    return floor_to_step(value, tick)


def tanh_decimal(value: Decimal) -> Decimal:
    # Decimal.exp keeps the calculation out of binary float.
    capped = clip(value, D("-20"), D("20"))
    exp_twice = (D("2") * capped).exp()
    return (exp_twice - ONE) / (exp_twice + ONE)


def percentile_rank(value: Decimal, history: Sequence[Decimal]) -> Decimal:
    if not history:
        return ZERO
    less = sum(1 for item in history if item < value)
    equal = sum(1 for item in history if item == value)
    return clip01((D(less) + D(equal) / D("2")) / D(len(history)))


def decimal_sequence(values: Iterable[object]) -> List[Decimal]:
    return [decimal_value(value) for value in values]
