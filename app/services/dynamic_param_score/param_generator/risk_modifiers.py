"""Risk and structure modifiers for DPS Engine V2."""

from __future__ import annotations

from typing import Tuple


def structure_side_multipliers(
    structure: str,
) -> Tuple[float, float]:
    """Return (buy_multiplier, sell_multiplier) for grid widening."""
    if structure == "lower_lows_only":
        return 1.25, 1.05
    if structure == "higher_highs_only":
        return 1.05, 1.25
    if structure == "both":
        return 1.18, 1.18
    return 1.0, 1.0


def fee_bad_adjustments(
    fee_class: str,
) -> Tuple[float, int]:
    """Widen grids and optionally reduce grid count for fee_bad."""
    if fee_class == "fee_bad":
        return 1.15, -1
    if fee_class == "high_fee":
        return 1.08, 0
    return 1.0, 0


def volatility_adjustment(volatility_bin: str) -> float:
    mapping = {
        "0_10": 1.0,
        "10_25": 1.02,
        "25_50": 1.05,
        "50_75": 1.10,
        "75_90": 1.15,
        "90_100": 1.22,
    }
    return mapping.get(volatility_bin, 1.05)


def budget_grid_count_cap(budget_class: str, side_budget_usdt: float, min_notional: float) -> int:
    """Max grids feasible without narrowing spacing — reduce count instead."""
    if side_budget_usdt < min_notional * 1.5:
        return 1
    if side_budget_usdt < min_notional * 3:
        return 2
    if budget_class in ("10_25", "25_50") and side_budget_usdt < min_notional * 5:
        return 2
    if budget_class in ("10_25", "25_50", "50_100") and side_budget_usdt < min_notional * 8:
        return 3
    return 4


def safety_level_from_context(
    *,
    fee_class: str,
    regime: str,
    risk_level: str,
) -> str:
    if fee_class == "fee_bad" or regime in ("CRASH_RISK", "LIQUIDITY_THIN_RANGE"):
        return "ACTIVE_DEFENSIVE"
    if risk_level in ("DEFENSIVE", "CAUTION"):
        return "ACTIVE_DEFENSIVE"
    if regime in ("VOLATILE_RANGE", "CHOPPY_RANGE", "BREAKOUT_RISK"):
        return "ACTIVE_CAUTIOUS"
    return "ACTIVE_NORMAL"
