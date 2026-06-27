"""Deterministic parameter modifiers for V5 shelf generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


DistributionMode = Literal[
    "balanced",
    "front_light",
    "front_medium",
    "deep",
    "trend_hold",
    "risk_reduce",
    "crash_deep",
    "restricted",
]


@dataclass
class ParamModifiers:
    grid_width_multiplier: float = 1.0
    sell_grid_bias: float = 1.0
    buy_grid_bias: float = 1.0
    base_pct_shift: float = 0.0
    quote_pct_shift: float = 0.0
    exposure_multiplier: float = 1.0
    active_buy_ladder_multiplier: float = 1.0
    trailing_multiplier: float = 1.0
    tp_multiplier: float = 1.0
    grid_count_shift: float = 0.0
    cost_floor_shift: float = 0.0
    sell_distribution_mode: DistributionMode = "balanced"
    buy_distribution_mode: DistributionMode = "balanced"


NEUTRAL_MODIFIERS = ParamModifiers()


def merge_modifiers(*mods: ParamModifiers) -> ParamModifiers:
    acc = NEUTRAL_MODIFIERS
    for m in mods:
        acc = ParamModifiers(
            grid_width_multiplier=acc.grid_width_multiplier * m.grid_width_multiplier,
            sell_grid_bias=acc.sell_grid_bias * m.sell_grid_bias,
            buy_grid_bias=acc.buy_grid_bias * m.buy_grid_bias,
            base_pct_shift=acc.base_pct_shift + m.base_pct_shift,
            quote_pct_shift=acc.quote_pct_shift + m.quote_pct_shift,
            exposure_multiplier=acc.exposure_multiplier * m.exposure_multiplier,
            active_buy_ladder_multiplier=acc.active_buy_ladder_multiplier
            * m.active_buy_ladder_multiplier,
            trailing_multiplier=acc.trailing_multiplier * m.trailing_multiplier,
            tp_multiplier=acc.tp_multiplier * m.tp_multiplier,
            grid_count_shift=acc.grid_count_shift + m.grid_count_shift,
            cost_floor_shift=acc.cost_floor_shift + m.cost_floor_shift,
            sell_distribution_mode=m.sell_distribution_mode
            if m.sell_distribution_mode != "balanced" or acc.sell_distribution_mode == "balanced"
            else acc.sell_distribution_mode,
            buy_distribution_mode=m.buy_distribution_mode
            if m.buy_distribution_mode != "balanced" or acc.buy_distribution_mode == "balanced"
            else acc.buy_distribution_mode,
        )
    return acc


def get_asset_modifier(asset: str) -> ParamModifiers:
    mapping = {
        "A1_BTC_CORE": ParamModifiers(
            grid_width_multiplier=0.95,
            exposure_multiplier=1.02,
            cost_floor_shift=-0.02,
        ),
        "A2_ETH_CORE": ParamModifiers(
            grid_width_multiplier=0.97,
            exposure_multiplier=1.0,
            cost_floor_shift=-0.01,
        ),
        "A3_MAJOR_ALT": ParamModifiers(grid_width_multiplier=1.0),
        "A4_HIGH_BETA_ALT": ParamModifiers(
            grid_width_multiplier=1.08,
            exposure_multiplier=0.92,
            trailing_multiplier=0.95,
        ),
        "A5_MEME_SPECULATIVE": ParamModifiers(
            grid_width_multiplier=1.12,
            exposure_multiplier=0.82,
            active_buy_ladder_multiplier=0.78,
            cost_floor_shift=0.06,
            sell_distribution_mode="risk_reduce",
        ),
        "A6_LOW_LIQUIDITY_ALT": ParamModifiers(
            grid_width_multiplier=1.18,
            exposure_multiplier=0.75,
            active_buy_ladder_multiplier=0.68,
            grid_count_shift=-0.5,
            cost_floor_shift=0.10,
            buy_distribution_mode="restricted",
        ),
        "A7_STABLE_OR_SPECIAL": ParamModifiers(
            grid_width_multiplier=0.88,
            exposure_multiplier=0.90,
            grid_count_shift=-0.25,
        ),
    }
    return mapping.get(asset, NEUTRAL_MODIFIERS)


def get_direction_modifier(direction: str) -> ParamModifiers:
    mapping = {
        "D1_UP_BIAS": ParamModifiers(
            base_pct_shift=6,
            quote_pct_shift=-6,
            sell_grid_bias=1.05,
            buy_grid_bias=0.95,
            sell_distribution_mode="trend_hold",
            buy_distribution_mode="front_medium",
        ),
        "D2_NEUTRAL_BIAS": NEUTRAL_MODIFIERS,
        "D3_DOWN_BIAS": ParamModifiers(
            base_pct_shift=-8,
            quote_pct_shift=8,
            sell_grid_bias=0.92,
            buy_grid_bias=1.10,
            active_buy_ladder_multiplier=0.82,
            sell_distribution_mode="risk_reduce",
            buy_distribution_mode="deep",
        ),
    }
    return mapping.get(direction, NEUTRAL_MODIFIERS)


def get_structure_modifier(structure: str) -> ParamModifiers:
    mapping = {
        "S1_RANGE_MID": NEUTRAL_MODIFIERS,
        "S2_RANGE_UPPER": ParamModifiers(
            sell_grid_bias=0.94,
            buy_grid_bias=1.06,
            base_pct_shift=-3,
            quote_pct_shift=3,
            sell_distribution_mode="front_medium",
            buy_distribution_mode="deep",
        ),
        "S3_RANGE_LOWER": ParamModifiers(
            sell_grid_bias=1.06,
            buy_grid_bias=0.94,
            base_pct_shift=3,
            quote_pct_shift=-3,
            buy_distribution_mode="front_medium",
            sell_distribution_mode="deep",
        ),
        "S4_HIGHER_HIGHS": ParamModifiers(
            sell_grid_bias=1.04,
            buy_grid_bias=0.96,
            sell_distribution_mode="trend_hold",
        ),
        "S5_LOWER_LOWS": ParamModifiers(
            sell_grid_bias=0.90,
            buy_grid_bias=1.14,
            exposure_multiplier=0.88,
            active_buy_ladder_multiplier=0.75,
            buy_distribution_mode="deep",
            sell_distribution_mode="risk_reduce",
        ),
        "S6_BREAKOUT_SETUP": ParamModifiers(
            grid_width_multiplier=0.96,
            sell_distribution_mode="trend_hold",
        ),
        "S7_BREAKOUT_RETEST": ParamModifiers(
            grid_width_multiplier=1.02,
            buy_distribution_mode="front_medium",
        ),
        "S8_BREAKDOWN": ParamModifiers(
            sell_grid_bias=0.88,
            buy_grid_bias=1.12,
            exposure_multiplier=0.72,
            active_buy_ladder_multiplier=0.65,
            sell_distribution_mode="risk_reduce",
            buy_distribution_mode="crash_deep",
        ),
        "S9_UNSTRUCTURED_CHOP": ParamModifiers(
            grid_width_multiplier=1.05,
            trailing_multiplier=0.92,
        ),
    }
    return mapping.get(structure, NEUTRAL_MODIFIERS)


def get_volatility_modifier(volatility: str) -> ParamModifiers:
    mapping = {
        "V1_ULTRA_LOW": ParamModifiers(
            grid_width_multiplier=0.88,
            trailing_multiplier=0.85,
            tp_multiplier=0.92,
        ),
        "V2_LOW": ParamModifiers(
            grid_width_multiplier=0.94,
            trailing_multiplier=0.90,
        ),
        "V3_NORMAL": NEUTRAL_MODIFIERS,
        "V4_HIGH": ParamModifiers(
            grid_width_multiplier=1.10,
            exposure_multiplier=0.92,
            trailing_multiplier=1.05,
            tp_multiplier=1.08,
        ),
        "V5_SHOCK": ParamModifiers(
            grid_width_multiplier=1.16,
            exposure_multiplier=0.78,
            active_buy_ladder_multiplier=0.72,
            trailing_multiplier=1.02,
            grid_count_shift=-0.25,
        ),
    }
    return mapping.get(volatility, NEUTRAL_MODIFIERS)


def get_risk_modifier(risk: str) -> ParamModifiers:
    mapping = {
        "K1_DEFENSIVE": ParamModifiers(
            base_pct_shift=-10,
            quote_pct_shift=10,
            exposure_multiplier=0.72,
            active_buy_ladder_multiplier=0.62,
            trailing_multiplier=0.85,
            tp_multiplier=0.95,
            grid_count_shift=-0.25,
            sell_distribution_mode="risk_reduce",
            buy_distribution_mode="deep",
        ),
        "K2_NORMAL_CONTROLLED": ParamModifiers(
            exposure_multiplier=0.95,
            active_buy_ladder_multiplier=0.90,
        ),
        "K3_AGGRESSIVE": ParamModifiers(
            base_pct_shift=10,
            quote_pct_shift=-10,
            exposure_multiplier=1.16,
            active_buy_ladder_multiplier=1.18,
            trailing_multiplier=1.08,
            tp_multiplier=1.12,
            grid_count_shift=0.25,
            sell_distribution_mode="trend_hold",
            buy_distribution_mode="front_medium",
        ),
    }
    return mapping.get(risk, NEUTRAL_MODIFIERS)


def get_liquidity_modifier(liquidity: str) -> ParamModifiers:
    mapping = {
        "L1_HIGH_LIQUIDITY_LOW_COST": ParamModifiers(
            cost_floor_shift=-0.04,
            grid_count_shift=0.25,
        ),
        "L2_NORMAL_LIQUIDITY_NORMAL_COST": NEUTRAL_MODIFIERS,
        "L3_LOW_LIQUIDITY_HIGH_COST": ParamModifiers(
            grid_width_multiplier=1.10,
            grid_count_shift=-0.5,
            cost_floor_shift=0.08,
            exposure_multiplier=0.88,
            active_buy_ladder_multiplier=0.80,
        ),
        "L4_EXECUTION_RISKY": ParamModifiers(
            grid_width_multiplier=1.15,
            grid_count_shift=-0.75,
            cost_floor_shift=0.12,
            exposure_multiplier=0.70,
            active_buy_ladder_multiplier=0.60,
            buy_distribution_mode="restricted",
            sell_distribution_mode="risk_reduce",
        ),
    }
    return mapping.get(liquidity, NEUTRAL_MODIFIERS)
