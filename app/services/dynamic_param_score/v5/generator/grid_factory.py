"""Grid level and distribution factories for V5."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v5.domain.math_utils import (
    clamp,
    is_strictly_increasing,
    round2,
)
from app.services.dynamic_param_score.v5.generator.modifiers import DistributionMode


def make_grid_levels(
    first_width_pct: float,
    grid_count: int,
    expansion: float,
) -> List[float]:
    if grid_count < 1 or grid_count > 5:
        raise ValueError(f"Unsupported gridCount: {grid_count}")
    levels: List[float] = []
    current = first_width_pct
    for i in range(grid_count):
        if i == 0:
            current = first_width_pct
        else:
            current = current * expansion
        levels.append(round2(current))
    if not is_strictly_increasing(levels):
        raise ValueError(f"Grid levels not increasing: {levels}")
    return levels


def get_grid_expansion_factor(regime: str, volatility: str, risk: str) -> float:
    factor = 2.05
    vol_map = {
        "V1_ULTRA_LOW": 1.85,
        "V2_LOW": 1.95,
        "V3_NORMAL": 2.1,
        "V4_HIGH": 2.25,
        "V5_SHOCK": 2.45,
    }
    factor = vol_map.get(volatility, factor)
    if regime == "R8_CRASH":
        factor += 0.25
    if regime == "R9_STRONG_DOWNTREND":
        factor += 0.18
    if regime == "R10_LOWER_LOWS_DOWNTREND":
        factor += 0.2
    if risk == "K1_DEFENSIVE":
        factor += 0.05
    if risk == "K3_AGGRESSIVE":
        factor -= 0.05
    return clamp(round2(factor), 1.6, 2.8)


def ensure_first_grid_above_cost_floor(
    first_grid_pct: float,
    cost_floor_pct: float,
    min_profit_pct: float,
) -> float:
    min_required = cost_floor_pct + min_profit_pct
    return round2(max(first_grid_pct, min_required))


def is_two_grid_equal_allowed(context: dict) -> bool:
    balanced_regime = context["regime"] in (
        "R2_BALANCED_RANGE",
        "R3_LOW_VOL_SQUEEZE",
    )
    neutral_structure = context["structure"] in (
        "S1_RANGE_MID",
        "S9_UNSTRUCTURED_CHOP",
    )
    safe_risk = context["risk"] in ("K1_DEFENSIVE", "K2_NORMAL_CONTROLLED")
    safe_vol = context["volatility"] in (
        "V1_ULTRA_LOW",
        "V2_LOW",
        "V3_NORMAL",
    )
    safe_liquidity = context["liquidity"] in (
        "L1_HIGH_LIQUIDITY_LOW_COST",
        "L2_NORMAL_LIQUIDITY_NORMAL_COST",
    )
    forbidden = (
        context["regime"] in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND")
        or context["structure"] in ("S5_LOWER_LOWS", "S8_BREAKDOWN")
        or context["volatility"] == "V5_SHOCK"
        or context["liquidity"] == "L4_EXECUTION_RISKY"
        or context["risk"] == "K3_AGGRESSIVE"
    )
    return (
        not forbidden
        and balanced_regime
        and neutral_structure
        and safe_risk
        and safe_vol
        and safe_liquidity
    )


def make_distribution(
    grid_count: int,
    mode: DistributionMode,
    context: dict,
) -> List[float]:
    if grid_count == 1:
        return [100.0]
    if grid_count == 2:
        equal_allowed = is_two_grid_equal_allowed(context)
        if equal_allowed and mode == "balanced":
            return [50.0, 50.0]
        if mode in ("deep", "crash_deep"):
            return [28.0, 72.0]
        if mode == "restricted":
            return [35.0, 65.0]
        if mode == "risk_reduce":
            return [60.0, 40.0]
        if mode == "trend_hold":
            return [35.0, 65.0]
        return [45.0, 55.0]
    if grid_count == 3:
        dist_map = {
            "crash_deep": [8.0, 22.0, 70.0],
            "deep": [12.0, 28.0, 60.0],
            "front_light": [15.0, 30.0, 55.0],
            "front_medium": [20.0, 30.0, 50.0],
            "risk_reduce": [35.0, 35.0, 30.0],
            "trend_hold": [15.0, 35.0, 50.0],
            "balanced": [20.0, 30.0, 50.0],
            "restricted": [15.0, 30.0, 55.0],
        }
        return dist_map.get(mode, [15.0, 30.0, 55.0])
    if grid_count == 4:
        dist_map = {
            "crash_deep": [5.0, 15.0, 30.0, 50.0],
            "deep": [8.0, 17.0, 30.0, 45.0],
            "risk_reduce": [30.0, 30.0, 25.0, 15.0],
            "trend_hold": [10.0, 20.0, 30.0, 40.0],
            "restricted": [10.0, 20.0, 30.0, 40.0],
        }
        return dist_map.get(mode, [10.0, 20.0, 30.0, 40.0])
    raise ValueError(f"Unsupported gridCount for distribution: {grid_count}")


def apply_hard_exposure_invariants(input_data: dict) -> dict:
    max_base = input_data["max_base_exposure_pct"]
    active_buy = input_data["active_buy_ladder_max_budget_pct"]
    regime = input_data["regime"]
    structure = input_data["structure"]
    risk = input_data["risk"]
    volatility = input_data["volatility"]
    liquidity = input_data["liquidity"]

    is_defensive = risk == "K1_DEFENSIVE"
    is_lower_lows = regime == "R10_LOWER_LOWS_DOWNTREND" or structure == "S5_LOWER_LOWS"
    is_strong_downtrend = regime == "R9_STRONG_DOWNTREND" or structure == "S8_BREAKDOWN"
    is_crash = regime == "R8_CRASH"
    is_shock = volatility == "V5_SHOCK"
    is_execution_risky = liquidity == "L4_EXECUTION_RISKY"

    if is_defensive and is_lower_lows:
        max_base = min(max_base, 50)
        active_buy = min(active_buy, 30)
    if is_defensive and is_strong_downtrend:
        max_base = min(max_base, 40)
        active_buy = min(active_buy, 24)
    if is_defensive and is_crash:
        max_base = min(max_base, 32)
        active_buy = min(active_buy, 14)
    if is_shock:
        max_base = min(max_base, 48)
        active_buy = min(active_buy, 24)
    if is_execution_risky:
        max_base = min(max_base, 42)
        active_buy = min(active_buy, 18)

    # Aggressive clamp in dangerous scenarios
    if risk == "K3_AGGRESSIVE" and (
        is_crash
        or is_strong_downtrend
        or is_lower_lows
        or regime == "R17_DATA_UNCERTAIN_REGIME"
        or is_execution_risky
    ):
        max_base = min(max_base, 55)
        active_buy = min(active_buy, 28)

    return {
        "max_base_exposure_pct": round2(max_base),
        "active_buy_ladder_max_budget_pct": round2(active_buy),
    }
