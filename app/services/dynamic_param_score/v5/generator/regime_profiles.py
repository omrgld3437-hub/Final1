"""Regime base profiles for V5 deterministic generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from app.services.dynamic_param_score.v5.generator.modifiers import DistributionMode


@dataclass
class RegimeBaseProfile:
    base_grid_width_pct: float
    preferred_grid_count: int
    target_base_pct: float
    max_exposure_pct: float
    active_buy_ladder_max_pct: float
    trailing_factor: float
    tp_trigger_pct: float
    min_profit_after_cost_floor_pct: float
    distribution_intent: Tuple[DistributionMode, DistributionMode]


def get_regime_base_profile(regime: str) -> RegimeBaseProfile:
    profiles: Dict[str, RegimeBaseProfile] = {
        "R1_STRONG_UPTREND": RegimeBaseProfile(
            3.2, 3, 58, 72, 34, 0.22, 3.2, 0.8, ("trend_hold", "front_medium")
        ),
        "R2_BALANCED_RANGE": RegimeBaseProfile(
            2.4, 3, 50, 62, 32, 0.18, 2.4, 0.7, ("balanced", "balanced")
        ),
        "R3_LOW_VOL_SQUEEZE": RegimeBaseProfile(
            2.2, 3, 45, 56, 28, 0.16, 2.2, 0.7, ("balanced", "deep")
        ),
        "R4_VOLATILE_RANGE": RegimeBaseProfile(
            3.0, 3, 48, 58, 30, 0.19, 2.8, 0.75, ("balanced", "balanced")
        ),
        "R5_PRE_BREAKOUT_COMPRESSION": RegimeBaseProfile(
            2.6, 3, 52, 64, 32, 0.17, 2.6, 0.72, ("front_light", "front_medium")
        ),
        "R6_BREAKOUT_CONTINUATION": RegimeBaseProfile(
            3.4, 3, 60, 70, 36, 0.21, 3.0, 0.78, ("trend_hold", "front_medium")
        ),
        "R7_RECOVERY": RegimeBaseProfile(
            3.0, 3, 52, 60, 30, 0.18, 2.8, 0.75, ("front_medium", "deep")
        ),
        "R8_CRASH": RegimeBaseProfile(
            6.5, 2, 22, 32, 12, 0.12, 3.8, 1.1, ("risk_reduce", "crash_deep")
        ),
        "R9_STRONG_DOWNTREND": RegimeBaseProfile(
            5.4, 2, 25, 40, 16, 0.13, 3.4, 1.0, ("risk_reduce", "deep")
        ),
        "R10_LOWER_LOWS_DOWNTREND": RegimeBaseProfile(
            5.8, 2, 28, 45, 20, 0.13, 3.5, 1.0, ("risk_reduce", "deep")
        ),
        "R11_FAILED_BREAKOUT": RegimeBaseProfile(
            3.8, 3, 38, 50, 24, 0.15, 3.0, 0.85, ("risk_reduce", "deep")
        ),
        "R12_CAPITULATION_REACTION": RegimeBaseProfile(
            4.2, 2, 36, 48, 22, 0.14, 3.2, 0.95, ("risk_reduce", "deep")
        ),
        "R13_HIGH_VOL_DISORDER": RegimeBaseProfile(
            4.0, 2, 35, 46, 20, 0.14, 3.1, 0.95, ("risk_reduce", "restricted")
        ),
        "R14_LOW_LIQUIDITY_DRIFT": RegimeBaseProfile(
            4.4, 2, 32, 42, 18, 0.13, 3.0, 1.0, ("risk_reduce", "restricted")
        ),
        "R15_SPECIAL_STRESS_TRANSITION": RegimeBaseProfile(
            4.6, 2, 34, 46, 20, 0.14, 3.1, 1.0, ("risk_reduce", "deep")
        ),
        "R16_OVEREXTENDED_MOMENTUM": RegimeBaseProfile(
            3.6, 3, 55, 65, 28, 0.20, 3.0, 0.80, ("trend_hold", "front_light")
        ),
        "R17_DATA_UNCERTAIN_REGIME": RegimeBaseProfile(
            4.0, 2, 30, 38, 14, 0.12, 3.0, 1.1, ("risk_reduce", "restricted")
        ),
    }
    if regime not in profiles:
        raise ValueError(f"Missing explicit regime profile: {regime}")
    return profiles[regime]


ALL_REGIMES_HANDLED = True
