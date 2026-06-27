"""Deterministic V5 grid spacing formula — cost, ATR/vol, scenario, structure/direction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from app.services.dynamic_param_score.v5.domain.math_utils import clamp, round2, round4
from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
from app.services.dynamic_param_score.v5.generator.grid_factory import get_grid_expansion_factor, make_grid_levels
from app.services.dynamic_param_score.v5.generator.modifiers import (
    get_asset_modifier,
    get_direction_modifier,
    get_liquidity_modifier,
    get_risk_modifier,
    get_structure_modifier,
    get_volatility_modifier,
    merge_modifiers,
)
from app.services.dynamic_param_score.v5.generator.regime_profiles import RegimeBaseProfile, get_regime_base_profile

# ATR blend weights (deterministic constants)
SHORT_ATR_WEIGHT = 4.0
LONG_ATR_WEIGHT = 1.8

# Reference ATR % per volatility class (typical shelf baseline, not random)
REFERENCE_ATR: Dict[str, Tuple[float, float]] = {
    "V1_ULTRA_LOW": (0.08, 0.65),
    "V2_LOW": (0.11, 1.00),
    "V3_NORMAL": (0.18, 1.45),
    "V4_HIGH": (0.35, 2.20),
    "V5_SHOCK": (0.55, 3.50),
}

# Asset scales natural ATR reference
ASSET_ATR_SCALE: Dict[str, float] = {
    "A1_BTC_CORE": 0.95,
    "A2_ETH_CORE": 0.97,
    "A3_MAJOR_ALT": 1.00,
    "A4_HIGH_BETA_ALT": 1.08,
    "A5_MEME_SPECULATIVE": 1.15,
    "A6_LOW_LIQUIDITY_ALT": 1.12,
    "A7_STABLE_OR_SPECIAL": 0.88,
}

# Reference execution cost components per liquidity class (shelf baseline)
REFERENCE_COST_COMPONENTS: Dict[str, Dict[str, float]] = {
    "L1_HIGH_LIQUIDITY_LOW_COST": {
        "maker_fee": 0.08,
        "taker_fee": 0.10,
        "spread": 0.03,
        "slippage": 0.015,
        "rounding": 0.005,
        "safety_buffer": 0.05,
    },
    "L2_NORMAL_LIQUIDITY_NORMAL_COST": {
        "maker_fee": 0.08,
        "taker_fee": 0.10,
        "spread": 0.05,
        "slippage": 0.025,
        "rounding": 0.005,
        "safety_buffer": 0.06,
    },
    "L3_LOW_LIQUIDITY_HIGH_COST": {
        "maker_fee": 0.10,
        "taker_fee": 0.10,
        "spread": 0.08,
        "slippage": 0.04,
        "rounding": 0.01,
        "safety_buffer": 0.08,
    },
    "L4_EXECUTION_RISKY": {
        "maker_fee": 0.10,
        "taker_fee": 0.10,
        "spread": 0.12,
        "slippage": 0.06,
        "rounding": 0.01,
        "safety_buffer": 0.10,
    },
}

# Regime scenario minimum first-grid width (prevents too-narrow squeeze grids)
REGIME_SCENARIO_FLOOR: Dict[str, float] = {
    "R3_LOW_VOL_SQUEEZE": 2.40,
    "R2_BALANCED_RANGE": 2.20,
    "R1_STRONG_UPTREND": 2.80,
    "R8_CRASH": 4.50,
    "R9_STRONG_DOWNTREND": 4.00,
    "R10_LOWER_LOWS_DOWNTREND": 4.20,
}

# Volatility class max/min first-grid bounds
VOL_GRID_BOUNDS: Dict[str, Tuple[float, float]] = {
    "V1_ULTRA_LOW": (0.90, 4.50),
    "V2_LOW": (0.90, 5.00),
    "V3_NORMAL": (1.00, 6.50),
    "V4_HIGH": (1.80, 9.00),
    "V5_SHOCK": (2.20, 12.00),
}


@dataclass
class GridReasoning:
    cost_floor_pct: float
    min_grid_by_cost_pct: float
    atr_5m_pct: float
    atr_1h_pct: float
    vol_grid_pct: float
    regime_base_width_pct: float
    scenario_grid_pct: float
    selected_base_first_grid_pct: float
    sell_first_grid_pct: float
    buy_first_grid_pct: float
    expansion_factor: float
    structure_sell_modifier: float
    structure_buy_modifier: float
    direction_sell_modifier: float
    direction_buy_modifier: float
    risk_buy_modifier: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "cost_floor_pct": self.cost_floor_pct,
            "min_grid_by_cost_pct": self.min_grid_by_cost_pct,
            "atr_5m_pct": self.atr_5m_pct,
            "atr_1h_pct": self.atr_1h_pct,
            "vol_grid_pct": self.vol_grid_pct,
            "regime_base_width_pct": self.regime_base_width_pct,
            "scenario_grid_pct": self.scenario_grid_pct,
            "selected_base_first_grid_pct": self.selected_base_first_grid_pct,
            "sell_first_grid_pct": self.sell_first_grid_pct,
            "buy_first_grid_pct": self.buy_first_grid_pct,
            "expansion_factor": self.expansion_factor,
            "structure_sell_modifier": self.structure_sell_modifier,
            "structure_buy_modifier": self.structure_buy_modifier,
            "direction_sell_modifier": self.direction_sell_modifier,
            "direction_buy_modifier": self.direction_buy_modifier,
            "risk_buy_modifier": self.risk_buy_modifier,
            "reason": self.reason,
        }


@dataclass
class GridSpacingResult:
    sell_grid_levels_pct: List[float]
    buy_grid_levels_pct: List[float]
    grid_count: int
    expansion_factor: float
    cost_floor_pct: float
    min_profit_after_cost_floor_pct: float
    execution_safety_buffer_pct: float
    assumed_cost_floor_pct: float
    grid_reasoning: GridReasoning


def _reference_atr(parts: V5RouteParts) -> Tuple[float, float]:
    atr5, atr1 = REFERENCE_ATR[parts.volatility]
    scale = ASSET_ATR_SCALE.get(parts.asset, 1.0)
    return round4(atr5 * scale), round4(atr1 * scale)


def _compute_cost_floor(liquidity: str, cost_floor_shift: float) -> float:
    comp = REFERENCE_COST_COMPONENTS[liquidity]
    total = sum(comp.values()) + cost_floor_shift
    return round2(max(total, 0.12))


def _structure_grid_modifiers(structure: str) -> Tuple[float, float]:
    """Return (sell_modifier, buy_modifier)."""
    mapping = {
        "S1_RANGE_MID": (1.0, 1.0),
        "S2_RANGE_UPPER": (0.95, 1.12),
        "S3_RANGE_LOWER": (1.12, 0.95),
        "S4_HIGHER_HIGHS": (1.04, 0.96),
        "S5_LOWER_LOWS": (0.90, 1.18),
        "S6_BREAKOUT_SETUP": (1.02, 0.98),
        "S7_BREAKOUT_RETEST": (1.0, 1.04),
        "S8_BREAKDOWN": (0.88, 1.20),
        "S9_UNSTRUCTURED_CHOP": (1.05, 1.05),
    }
    return mapping.get(structure, (1.0, 1.0))


def _direction_grid_modifiers(direction: str) -> Tuple[float, float]:
    mapping = {
        "D1_UP_BIAS": (1.05, 0.95),
        "D2_NEUTRAL_BIAS": (1.0, 1.0),
        "D3_DOWN_BIAS": (0.92, 1.10),
    }
    return mapping.get(direction, (1.0, 1.0))


def _risk_buy_modifier(risk: str, parts: V5RouteParts) -> float:
    if risk == "K1_DEFENSIVE":
        return 1.10
    if risk == "K3_AGGRESSIVE":
        dangerous = parts.regime in (
            "R8_CRASH",
            "R9_STRONG_DOWNTREND",
            "R10_LOWER_LOWS_DOWNTREND",
            "R17_DATA_UNCERTAIN_REGIME",
        ) or parts.structure in ("S5_LOWER_LOWS", "S8_BREAKDOWN") or parts.liquidity == "L4_EXECUTION_RISKY"
        return 1.05 if not dangerous else 1.18
    return 1.0


def _scenario_grid_pct(
    regime_base: RegimeBaseProfile,
    parts: V5RouteParts,
    vol_mult: float,
    asset_mult: float,
    liq_mult: float,
    risk_mult: float,
) -> float:
    raw = (
        regime_base.base_grid_width_pct
        * vol_mult
        * asset_mult
        * liq_mult
        * risk_mult
    )
    floor = REGIME_SCENARIO_FLOOR.get(parts.regime, regime_base.base_grid_width_pct * 0.95)
    return round2(max(raw, floor))


def _build_reason_text(parts: V5RouteParts, base: float, sell: float, buy: float) -> str:
    return (
        f"Grid from cost+ATR+scenario max → base {base}% ; "
        f"{parts.structure} sell×structure buy×structure ; "
        f"{parts.direction} direction bias ; "
        f"{parts.risk} buy risk adjust → sell {sell}% buy {buy}%"
    )


def compute_grid_spacing(parts: V5RouteParts) -> GridSpacingResult:
    """Full deterministic grid formula for one V5 shelf."""
    regime_base = get_regime_base_profile(parts.regime)
    modifiers = merge_modifiers(
        get_asset_modifier(parts.asset),
        get_direction_modifier(parts.direction),
        get_structure_modifier(parts.structure),
        get_volatility_modifier(parts.volatility),
        get_risk_modifier(parts.risk),
        get_liquidity_modifier(parts.liquidity),
    )

    atr5, atr1 = _reference_atr(parts)
    vol_grid = round2(atr5 * SHORT_ATR_WEIGHT + atr1 * LONG_ATR_WEIGHT)

    cost_floor = _compute_cost_floor(parts.liquidity, modifiers.cost_floor_shift)
    min_profit = regime_base.min_profit_after_cost_floor_pct
    min_grid_by_cost = round2(cost_floor + min_profit)

    vol_mult = get_volatility_modifier(parts.volatility).grid_width_multiplier
    asset_mult = get_asset_modifier(parts.asset).grid_width_multiplier
    liq_mult = get_liquidity_modifier(parts.liquidity).grid_width_multiplier
    risk_mult = get_risk_modifier(parts.risk).grid_width_multiplier

    scenario_grid = _scenario_grid_pct(
        regime_base, parts, vol_mult, asset_mult, liq_mult, risk_mult
    )

    base_first = round2(max(min_grid_by_cost, vol_grid, scenario_grid))

    # Volatility bounds clamp
    vmin, vmax = VOL_GRID_BOUNDS.get(parts.volatility, (0.90, 8.0))
    base_first = clamp(base_first, vmin, vmax)

    struct_sell, struct_buy = _structure_grid_modifiers(parts.structure)
    dir_sell, dir_buy = _direction_grid_modifiers(parts.direction)
    risk_buy = _risk_buy_modifier(parts.risk, parts)

    sell_first = round2(base_first * struct_sell * dir_sell)
    buy_first = round2(base_first * struct_buy * dir_buy * risk_buy)

    # Re-ensure cost floor after directional adjust
    sell_first = round2(max(sell_first, min_grid_by_cost))
    buy_first = round2(max(buy_first, min_grid_by_cost))

    # Structure ordering: range upper/lower asymmetry must survive cost clamp
    if parts.structure == "S2_RANGE_UPPER" and sell_first >= buy_first:
        sell_first = round2(buy_first * 0.95)
        sell_first = round2(max(sell_first, min_grid_by_cost))
    elif parts.structure == "S3_RANGE_LOWER" and parts.regime not in (
        "R8_CRASH",
        "R9_STRONG_DOWNTREND",
        "R10_LOWER_LOWS_DOWNTREND",
    ):
        if buy_first >= sell_first:
            buy_first = round2(sell_first * 0.96)
            buy_first = round2(max(buy_first, min_grid_by_cost * 0.98))
    elif parts.structure in ("S5_LOWER_LOWS", "S8_BREAKDOWN") or parts.regime in (
        "R8_CRASH",
        "R9_STRONG_DOWNTREND",
        "R10_LOWER_LOWS_DOWNTREND",
    ):
        if buy_first < sell_first * 1.05:
            buy_first = round2(sell_first * 1.08)

    grid_count = int(clamp(round(regime_base.preferred_grid_count + modifiers.grid_count_shift), 2, 4))
    expansion = get_grid_expansion_factor(parts.regime, parts.volatility, parts.risk)

    sell_levels = make_grid_levels(sell_first, grid_count, expansion)
    buy_levels = make_grid_levels(buy_first, grid_count, expansion)

    reasoning = GridReasoning(
        cost_floor_pct=cost_floor,
        min_grid_by_cost_pct=min_grid_by_cost,
        atr_5m_pct=atr5,
        atr_1h_pct=atr1,
        vol_grid_pct=vol_grid,
        regime_base_width_pct=regime_base.base_grid_width_pct,
        scenario_grid_pct=scenario_grid,
        selected_base_first_grid_pct=base_first,
        sell_first_grid_pct=sell_first,
        buy_first_grid_pct=buy_first,
        expansion_factor=expansion,
        structure_sell_modifier=struct_sell,
        structure_buy_modifier=struct_buy,
        direction_sell_modifier=dir_sell,
        direction_buy_modifier=dir_buy,
        risk_buy_modifier=risk_buy,
        reason=_build_reason_text(parts, base_first, sell_first, buy_first),
    )

    return GridSpacingResult(
        sell_grid_levels_pct=sell_levels,
        buy_grid_levels_pct=buy_levels,
        grid_count=grid_count,
        expansion_factor=expansion,
        cost_floor_pct=cost_floor,
        min_profit_after_cost_floor_pct=min_profit,
        execution_safety_buffer_pct=round2(
            REFERENCE_COST_COMPONENTS[parts.liquidity]["safety_buffer"]
        ),
        assumed_cost_floor_pct=cost_floor,
        grid_reasoning=reasoning,
    )
