"""Versioned coefficients and hard/soft limits for Dynamic Mode V2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, Mapping

from .models import json_value


D = Decimal


@dataclass(frozen=True)
class FormulaCoefficients:
    version: str = "dynamic-v2.0.0"
    base_market: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "up": D("16"),
            "down": D("-20"),
            "volatility": D("-6"),
            "coin_risk": D("-5"),
            "liquidity": D("-4"),
            "quiet_range": D("5"),
            "down_volatility": D("-8"),
            "up_stability": D("4"),
        }
    )
    buy_distance: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "down_vol": D("0.42"),
            "down": D("0.28"),
            "coin": D("0.12"),
            "liquidity": D("0.08"),
            "negative_jump": D("0.08"),
            "down_x_vol": D("0.14"),
            "vol_x_liquidity": D("0.08"),
            "quiet_range": D("-0.24"),
            "up_quiet": D("-0.10"),
        }
    )
    sell_distance: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "up_vol": D("0.42"),
            "up": D("0.28"),
            "coin": D("0.12"),
            "liquidity": D("0.08"),
            "positive_jump": D("0.08"),
            "up_x_vol": D("0.14"),
            "vol_x_liquidity": D("0.08"),
            "quiet_range": D("-0.24"),
            "down_quiet": D("-0.16"),
        }
    )
    trend_timeframe_weights: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "1M": D("0.05"),
            "1W": D("0.25"),
            "1D": D("0.30"),
            "4H": D("0.25"),
            "1H": D("0.15"),
        }
    )
    volatility_timeframe_weights: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "1W": D("0.05"),
            "1D": D("0.20"),
            "4H": D("0.30"),
            "1H": D("0.30"),
            "15M": D("0.15"),
        }
    )

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class DynamicV2Config:
    enabled: bool = False
    shadow_mode: bool = True
    full_analysis_offset_seconds: int = 60
    blocked_retry_seconds: int = 1800
    micro_check_seconds: int = 300
    minimum_full_analysis_seconds: int = 3600
    data_quality_full: Decimal = D("0.85")
    data_quality_limited: Decimal = D("0.70")
    minimum_confidence: Decimal = D("0.70")
    min_base_ratio: Decimal = D("0.05")
    max_base_ratio: Decimal = D("0.95")
    ratio_band: Decimal = D("0.20")
    base_deadband: Decimal = D("0.01")
    relative_trigger_deadband: Decimal = D("0.03")
    relative_amount_deadband: Decimal = D("0.05")
    relative_trailing_deadband: Decimal = D("0.05")
    relative_profit_deadband: Decimal = D("0.05")
    hourly_base_change: Decimal = D("0.05")
    hourly_trigger_change: Decimal = D("0.15")
    hourly_amount_change: Decimal = D("0.20")
    hourly_trailing_change: Decimal = D("0.15")
    hourly_profit_change: Decimal = D("0.15")
    absolute_min_gap: Decimal = D("0.05")
    spread_gap_factor: Decimal = D("3")
    atr_gap_factor: Decimal = D("0.15")
    min_distance: Decimal = D("0.05")
    max_grid_distance: Decimal = D("50")
    max_adjacent_amount_ratio: Decimal = D("1.60")
    max_single_buy_grid_weight: Decimal = D("0.40")
    max_single_sell_grid_weight: Decimal = D("0.40")
    min_buy_utilization: Decimal = D("0.10")
    max_buy_utilization: Decimal = D("1")
    min_sell_utilization: Decimal = D("0.10")
    max_sell_utilization: Decimal = D("1")
    base_safety_reserve: Decimal = D("0")
    quote_safety_reserve: Decimal = D("0")
    min_buy_trailing: Decimal = D("0.05")
    max_buy_trailing: Decimal = D("5")
    min_sell_trailing: Decimal = D("0.05")
    max_sell_trailing: Decimal = D("5")
    profit_trailing_trigger_ratio: Decimal = D("0.60")
    profit_safety_margin: Decimal = D("0.001")
    score_smoothing_alpha: Decimal = D("0.35")
    risk_reducing_alpha: Decimal = D("0.60")
    risk_increasing_alpha: Decimal = D("0.25")
    soft_rebase_alpha: Decimal = D("0.20")
    soft_rebase_confirmation_hours: int = 3
    minimum_candidate_improvement: Decimal = D("0.01")

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))
