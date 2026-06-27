"""Fallback, resolver, and validation policy factories."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts
from app.services.dynamic_param_score.v5.domain.types import (
    V5FallbackPolicy,
    V5ResolverPolicy,
)
from app.services.dynamic_param_score.v5.generator.grid_factory import is_two_grid_equal_allowed


def make_fallback_policy(parts: V5RouteParts) -> V5FallbackPolicy:
    forbidden: List[str] = ["R2_BALANCED_RANGE_RAW"]
    nearest: List[str] = []

    if parts.regime == "R8_CRASH":
        forbidden.extend(["R2_BALANCED_RANGE", "R3_LOW_VOL_SQUEEZE", "R1_STRONG_UPTREND"])
    if parts.regime == "R15_SPECIAL_STRESS_TRANSITION":
        forbidden.extend(["R2_BALANCED_RANGE"])
        nearest = [
            "R12_CAPITULATION_REACTION",
            "R7_RECOVERY",
            "R6_BREAKOUT_CONTINUATION",
        ]
    if parts.risk == "K1_DEFENSIVE":
        forbidden.extend(["K2_NORMAL_CONTROLLED_RAW", "K3_AGGRESSIVE_RAW"])
    if parts.risk == "K2_NORMAL_CONTROLLED":
        forbidden.append("K3_AGGRESSIVE_RAW")

    return V5FallbackPolicy(
        fallback_allowed=True,
        fallback_family=f"same_asset_same_risk_{parts.risk}",
        forbidden_fallbacks=forbidden,
        nearest_safe_dimensions=nearest,
    )


def make_resolver_policy(parts: V5RouteParts) -> V5ResolverPolicy:
    return V5ResolverPolicy(
        budget_policy="scale_grid_by_min_notional",
        position_policy="rebalance_when_safe",
        momentum_policy="clamp_overextended",
        data_quality_policy="reduce_on_stale",
        execution_cost_policy="widen_below_cost_floor",
        btc_context_policy="clamp_alt_on_btc_stress",
        risk_clamp_policy=f"enforce_{parts.risk}",
    )


def make_validation_policy(parts: V5RouteParts) -> dict:
    ctx = {
        "regime": parts.regime,
        "structure": parts.structure,
        "risk": parts.risk,
        "volatility": parts.volatility,
        "liquidity": parts.liquidity,
    }
    rules = {
        "grid_rules": [
            "monotonic_increasing",
            "positive_levels",
            "count_matches_distribution",
        ],
        "exposure_rules": ["max_exposure_within_risk_limits"],
        "trailing_rules": ["trailing_lte_first_grid_30pct"],
        "cost_rules": ["first_grid_above_cost_floor", "tp_above_cost_floor"],
        "special_rules": [],
    }
    if parts.regime == "R8_CRASH":
        rules["special_rules"].append("no_balanced_range_fallback")
    if parts.regime == "R15_SPECIAL_STRESS_TRANSITION":
        rules["special_rules"].append("no_r2_derivation")
    if is_two_grid_equal_allowed(ctx):
        rules["grid_rules"].append("equal_2_grid_justified")
    return rules


def make_scenario_description(parts: V5RouteParts, base_template: dict) -> str:
    return (
        f"V5 exact shelf for {parts.asset} in {parts.regime} with {parts.direction}, "
        f"structure {parts.structure}, volatility {parts.volatility}, "
        f"risk {parts.risk}, liquidity {parts.liquidity}. "
        f"Grid count {base_template.get('preferred_grid_count', 0)}, "
        f"target base {base_template.get('target_base_pct', 0)}%."
    )
