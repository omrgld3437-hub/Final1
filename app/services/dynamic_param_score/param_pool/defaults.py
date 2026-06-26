"""V1 param template pool — programmatic generation of versioned templates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from app.services.dynamic_param_score.param_pool.models import (
    BudgetTier,
    ExposureTier,
    FeeTier,
    HeadroomTier,
    ParamTemplate,
    ProfileFamily,
)

POOL_VERSION_ID = "v1.0.0"
POOL_VERSION_V2 = "v2.0.0"
POOL_VERSION_V3 = "v3.0.0"
POOL_VERSION_V4 = "v4.0.0"

# Score band definitions: (min, max, label)
SCORE_BANDS: List[Tuple[int, int, str]] = [
    (0, 9, "BLOCKED"),
    (10, 19, "EXTREME_RISK"),
    (20, 29, "VERY_DEFENSIVE"),
    (30, 39, "DEFENSIVE_LOW"),
    (40, 49, "DEFENSIVE_HIGH"),
    (50, 59, "BALANCED_LOW"),
    (60, 69, "BALANCED_HIGH"),
    (70, 79, "ACTIVE_LOW"),
    (80, 89, "ACTIVE_HIGH"),
    (90, 100, "HIGH_CONFIDENCE"),
]

_PROFILE_REGIMES: Dict[str, List[str]] = {
    ProfileFamily.NO_TRADE.value: [
        RegimeTag.NO_DATA.value,
        RegimeTag.NO_TRADE.value,
        RegimeTag.DUMP_RISK.value,
        RegimeTag.LOW_LIQUIDITY.value,
        RegimeTag.SPREAD_UNSAFE.value,
    ],
    ProfileFamily.WAIT.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_LOW_VOL.value,
        RegimeTag.HIGH_VOL_UNSTABLE.value,
        RegimeTag.BREAKOUT_RISK.value,
        RegimeTag.TRENDING_DOWN.value,
    ],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_LOW_VOL.value,
        RegimeTag.RANGE_HIGH_VOL.value,
        RegimeTag.TRENDING_DOWN.value,
    ],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: [
        RegimeTag.TRENDING_DOWN.value,
        RegimeTag.HIGH_VOL_UNSTABLE.value,
        RegimeTag.BREAKOUT_RISK.value,
    ],
    ProfileFamily.DEFENSIVE_GRID.value: [
        RegimeTag.TRENDING_DOWN.value,
        RegimeTag.HIGH_VOL_UNSTABLE.value,
        RegimeTag.BREAKOUT_RISK.value,
        RegimeTag.RANGE_LOW_VOL.value,
    ],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_LOW_VOL.value,
    ],
    ProfileFamily.BALANCED_GRID.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_LOW_VOL.value,
        RegimeTag.RANGE_HIGH_VOL.value,
    ],
    ProfileFamily.ACTIVE_RANGE_GRID.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_HIGH_VOL.value,
    ],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_HIGH_VOL.value,
    ],
    ProfileFamily.TREND_TRAILING.value: [
        RegimeTag.TRENDING_UP.value,
    ],
    ProfileFamily.BREAKOUT_PROTECTION.value: [
        RegimeTag.BREAKOUT_RISK.value,
        RegimeTag.HIGH_VOL_UNSTABLE.value,
    ],
    ProfileFamily.RECOVERY_SELL.value: [
        RegimeTag.TRENDING_DOWN.value,
        RegimeTag.DUMP_RISK.value,
        RegimeTag.BALANCED_RANGE.value,
    ],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [
        RegimeTag.BALANCED_RANGE.value,
        RegimeTag.RANGE_LOW_VOL.value,
        RegimeTag.RANGE_HIGH_VOL.value,
    ],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [
        RegimeTag.HIGH_VOL_UNSTABLE.value,
        RegimeTag.RANGE_HIGH_VOL.value,
        RegimeTag.BREAKOUT_RISK.value,
    ],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [
        RegimeTag.LOW_LIQUIDITY.value,
        RegimeTag.SPREAD_UNSAFE.value,
    ],
}

_PROFILE_ACTION: Dict[str, str] = {
    ProfileFamily.NO_TRADE.value: FinalAction.NO_TRADE.value,
    ProfileFamily.WAIT.value: FinalAction.WAIT.value,
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: FinalAction.SELL_MANAGEMENT_ONLY.value,
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: FinalAction.DEFENSIVE_GRID.value,
    ProfileFamily.DEFENSIVE_GRID.value: FinalAction.DEFENSIVE_GRID.value,
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: FinalAction.BALANCED_GRID.value,
    ProfileFamily.BALANCED_GRID.value: FinalAction.BALANCED_GRID.value,
    ProfileFamily.ACTIVE_RANGE_GRID.value: FinalAction.ACTIVE_GRID.value,
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: FinalAction.ACTIVE_GRID.value,
    ProfileFamily.TREND_TRAILING.value: FinalAction.TREND_TRAILING.value,
    ProfileFamily.BREAKOUT_PROTECTION.value: FinalAction.WAIT.value,
    ProfileFamily.RECOVERY_SELL.value: FinalAction.SELL_MANAGEMENT_ONLY.value,
    ProfileFamily.LOW_FEE_WIDE_GRID.value: FinalAction.BALANCED_GRID.value,
    ProfileFamily.ACTIVE_DEFENSIVE_GRID.value: FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    ProfileFamily.HIGH_VOL_PROTECTION.value: FinalAction.DEFENSIVE_GRID.value,
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: FinalAction.WAIT.value,
}

_PROFILE_SCORE_RANGES: Dict[str, List[Tuple[int, int]]] = {
    ProfileFamily.NO_TRADE.value: [(0, 19), (0, 9)],
    ProfileFamily.WAIT.value: [(20, 59), (40, 59)],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [(50, 79)],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: [(20, 39)],
    ProfileFamily.DEFENSIVE_GRID.value: [(30, 49), (40, 54)],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [(55, 69), (60, 69)],
    ProfileFamily.BALANCED_GRID.value: [(50, 74), (55, 69)],
    ProfileFamily.ACTIVE_RANGE_GRID.value: [(70, 89)],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [(80, 100), (90, 100)],
    ProfileFamily.TREND_TRAILING.value: [(65, 95)],
    ProfileFamily.BREAKOUT_PROTECTION.value: [(45, 70)],
    ProfileFamily.RECOVERY_SELL.value: [(30, 65)],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [(55, 69), (60, 69)],
    ProfileFamily.ACTIVE_DEFENSIVE_GRID.value: [(55, 75), (60, 69)],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [(40, 75)],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [(0, 59)],
}

_PROFILE_BUDGETS: Dict[str, List[str]] = {
    ProfileFamily.NO_TRADE.value: [b.value for b in BudgetTier],
    ProfileFamily.WAIT.value: [b.value for b in BudgetTier],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [
        BudgetTier.SMALL.value,
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: [
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.DEFENSIVE_GRID.value: [
        BudgetTier.SMALL.value,
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
        BudgetTier.SMALL.value,
    ],
    ProfileFamily.BALANCED_GRID.value: [
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
        BudgetTier.SMALL.value,
    ],
    ProfileFamily.ACTIVE_RANGE_GRID.value: [
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
        BudgetTier.WHALE.value,
        BudgetTier.STANDARD.value,
    ],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
        BudgetTier.WHALE.value,
    ],
    ProfileFamily.TREND_TRAILING.value: [
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.BREAKOUT_PROTECTION.value: [
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.RECOVERY_SELL.value: [
        BudgetTier.SMALL.value,
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
    ],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [
        BudgetTier.SMALL.value,
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [
        BudgetTier.SMALL.value,
        BudgetTier.STANDARD.value,
        BudgetTier.MEDIUM.value,
        BudgetTier.LARGE.value,
    ],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [b.value for b in BudgetTier],
}

_PROFILE_EXPOSURE: Dict[str, List[str]] = {
    ProfileFamily.NO_TRADE.value: [e.value for e in ExposureTier],
    ProfileFamily.WAIT.value: [e.value for e in ExposureTier],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [
        ExposureTier.TARGET_BASE.value,
        ExposureTier.HIGH_BASE.value,
        ExposureTier.OVEREXPOSED.value,
    ],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.DEFENSIVE_GRID.value: [
        ExposureTier.NO_BASE.value,
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.BALANCED_GRID.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.ACTIVE_RANGE_GRID.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.TREND_TRAILING.value: [
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
        ExposureTier.HIGH_BASE.value,
    ],
    ProfileFamily.BREAKOUT_PROTECTION.value: [e.value for e in ExposureTier],
    ProfileFamily.RECOVERY_SELL.value: [
        ExposureTier.HIGH_BASE.value,
        ExposureTier.OVEREXPOSED.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [
        ExposureTier.NO_BASE.value,
        ExposureTier.LOW_BASE.value,
        ExposureTier.TARGET_BASE.value,
    ],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [e.value for e in ExposureTier],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [e.value for e in ExposureTier],
}

_PROFILE_HEADROOM: Dict[str, List[str]] = {
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [
        HeadroomTier.NO_HEADROOM.value,
        HeadroomTier.LOW_HEADROOM.value,
    ],
    ProfileFamily.RECOVERY_SELL.value: [
        HeadroomTier.NO_HEADROOM.value,
        HeadroomTier.LOW_HEADROOM.value,
    ],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: [
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.DEFENSIVE_GRID.value: [
        HeadroomTier.LOW_HEADROOM.value,
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.BALANCED_GRID.value: [
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.ACTIVE_RANGE_GRID.value: [HeadroomTier.GOOD_HEADROOM.value],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [HeadroomTier.GOOD_HEADROOM.value],
    ProfileFamily.TREND_TRAILING.value: [
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [
        HeadroomTier.MEDIUM_HEADROOM.value,
        HeadroomTier.GOOD_HEADROOM.value,
    ],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [h.value for h in HeadroomTier],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [h.value for h in HeadroomTier],
}

_PROFILE_FEE: Dict[str, List[str]] = {
    ProfileFamily.ACTIVE_RANGE_GRID.value: [
        FeeTier.FEE_GOOD.value,
        FeeTier.FEE_EXCELLENT.value,
    ],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: [
        FeeTier.FEE_GOOD.value,
        FeeTier.FEE_EXCELLENT.value,
    ],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: [
        FeeTier.FEE_OK.value,
        FeeTier.FEE_GOOD.value,
        FeeTier.FEE_EXCELLENT.value,
    ],
    ProfileFamily.BALANCED_GRID.value: [
        FeeTier.FEE_OK.value,
        FeeTier.FEE_GOOD.value,
        FeeTier.FEE_EXCELLENT.value,
    ],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: [
        FeeTier.FEE_BAD.value,
        FeeTier.FEE_WEAK.value,
        FeeTier.FEE_OK.value,
    ],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: [
        FeeTier.FEE_WEAK.value,
        FeeTier.FEE_OK.value,
    ],
    ProfileFamily.HIGH_VOL_PROTECTION.value: [f.value for f in FeeTier],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: [f.value for f in FeeTier],
}

_PROFILE_RISK: Dict[str, List[str]] = {
    ProfileFamily.NO_TRADE.value: ["BLOCKED", "DEFENSIVE", "CAUTION", "NORMAL", "SAFE"],
    ProfileFamily.ACTIVE_RANGE_GRID.value: ["NORMAL", "SAFE"],
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: ["NORMAL", "SAFE"],
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: ["CAUTION", "NORMAL", "SAFE"],
    ProfileFamily.BALANCED_GRID.value: ["CAUTION", "NORMAL", "SAFE"],
    ProfileFamily.DEFENSIVE_GRID.value: ["DEFENSIVE", "CAUTION", "NORMAL"],
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: ["DEFENSIVE", "CAUTION"],
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: ["CAUTION", "NORMAL", "DEFENSIVE"],
    ProfileFamily.TREND_TRAILING.value: ["NORMAL", "SAFE", "CAUTION"],
    ProfileFamily.LOW_FEE_WIDE_GRID.value: ["NORMAL", "CAUTION"],
    ProfileFamily.HIGH_VOL_PROTECTION.value: ["DEFENSIVE", "CAUTION", "NORMAL"],
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: ["BLOCKED", "DEFENSIVE", "CAUTION", "NORMAL"],
}

_BUDGET_EQUITY: Dict[str, Tuple[float, Optional[float]]] = {
    BudgetTier.NANO.value: (0, 24.99),
    BudgetTier.MICRO.value: (25, 49.99),
    BudgetTier.SMALL.value: (50, 99.99),
    BudgetTier.STANDARD.value: (100, 249.99),
    BudgetTier.MEDIUM.value: (250, 999.99),
    BudgetTier.LARGE.value: (1000, 4999.99),
    BudgetTier.WHALE.value: (5000, None),
}

_PROFILE_TARGETS: Dict[str, int] = {
    ProfileFamily.NO_TRADE.value: 10,
    ProfileFamily.WAIT.value: 10,
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: 20,
    ProfileFamily.RECOVERY_SELL.value: 10,
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: 10,
    ProfileFamily.DEFENSIVE_GRID.value: 20,
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: 25,
    ProfileFamily.BALANCED_GRID.value: 25,
    ProfileFamily.LOW_FEE_WIDE_GRID.value: 20,
    ProfileFamily.ACTIVE_RANGE_GRID.value: 20,
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: 10,
    ProfileFamily.TREND_TRAILING.value: 15,
    ProfileFamily.BREAKOUT_PROTECTION.value: 10,
    ProfileFamily.HIGH_VOL_PROTECTION.value: 10,
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: 5,
}


def _default_rebalance_policy(profile: str) -> dict:
    from app.services.dynamic_param_score.rebalance import (
        DEFAULT_REBALANCE_POLICY,
        DISABLED_REBALANCE_POLICY,
    )
    from app.services.dynamic_param_score.param_pool.models import ProfileFamily

    if profile in (
        ProfileFamily.NO_TRADE.value,
        ProfileFamily.WAIT.value,
        ProfileFamily.LOW_LIQUIDITY_WAIT.value,
        ProfileFamily.MICRO_BUDGET_WAIT.value,
    ):
        return dict(DISABLED_REBALANCE_POLICY)
    if profile in (
        ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        ProfileFamily.RECOVERY_SELL.value,
        ProfileFamily.OVEREXPOSED_REDUCTION.value,
    ):
        pol = dict(DEFAULT_REBALANCE_POLICY)
        pol.update({"buy_rebalance_allowed": False, "sell_rebalance_allowed": True})
        return pol
    return dict(DEFAULT_REBALANCE_POLICY)


def _base_params_for_profile(profile: str, budget: str) -> Dict[str, Any]:
    """Default param dict per profile family."""
    if profile == ProfileFamily.NO_TRADE.value:
        return {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _default_rebalance_policy(profile)}
    if profile == ProfileFamily.WAIT.value:
        return {
            "buy_grid_count": 0,
            "sell_grid_count": 0,
            "cancel_existing_buy_orders": True,
            "cancel_existing_sell_orders": False,
            "rebalance_policy": _default_rebalance_policy(profile),
        }
    if profile in (
        ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        ProfileFamily.RECOVERY_SELL.value,
    ):
        sell_n = 3 if budget in (BudgetTier.SMALL.value, BudgetTier.MICRO.value) else 4
        return {
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.42,
            "buy_grid_count": 0,
            "sell_grid_count": sell_n,
            "sell_spacing_mode": "atr_mult",
            "sell_spacing_atr_mult": 0.75,
            "sell_spacing_min_pct": 0.45,
            "sell_spacing_max_pct": 3.0,
            "sell_distribution": "balanced",
            "trailing_enabled": True,
            "trailing_side": "sell",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "take_profit_pct": 1.35,
            "max_base_exposure_extra": 0.06,
            "max_base_exposure_cap": 0.56,
            "cancel_existing_buy_orders": True,
            "cancel_existing_sell_orders": False,
        }
    if profile == ProfileFamily.ULTRA_DEFENSIVE_GRID.value:
        return {
            "base_alloc_mode": "fixed",
            "base_alloc_frac": 0.12,
            "buy_grid_count": 2,
            "sell_grid_count": 2,
            "buy_spacing_atr_mult": 1.4,
            "sell_spacing_atr_mult": 1.1,
            "buy_spacing_min_pct": 0.65,
            "sell_spacing_min_pct": 0.55,
            "buy_distribution": "front_light",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.18,
            "max_base_exposure_extra": 0.04,
            "max_base_exposure_cap": 0.35,
            "trailing_enabled": False,
            "rebuy_enabled": False,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.DEFENSIVE_GRID.value:
        buy_n = 2 if budget == BudgetTier.SMALL.value else 3
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.18,
            "base_alloc_max": 0.32,
            "buy_grid_count": buy_n,
            "sell_grid_count": 3,
            "buy_spacing_atr_mult": 1.1,
            "sell_spacing_atr_mult": 0.9,
            "buy_spacing_min_pct": 0.55,
            "sell_spacing_min_pct": 0.45,
            "buy_distribution": "front_light",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.22,
            "max_base_exposure_extra": 0.05,
            "max_base_exposure_cap": 0.45,
            "trailing_enabled": False,
            "rebuy_enabled": False,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.LOW_FEE_WIDE_GRID.value:
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.28,
            "base_alloc_max": 0.40,
            "buy_grid_count": 2,
            "sell_grid_count": 2,
            "buy_spacing_atr_mult": 1.35,
            "sell_spacing_atr_mult": 1.15,
            "buy_spacing_min_pct": 0.55,
            "sell_spacing_min_pct": 0.50,
            "spacing_friction_mult": 4.0,
            "buy_distribution": "front_light",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.18,
            "max_base_exposure_extra": 0.05,
            "max_base_exposure_cap": 0.48,
            "trailing_enabled": False,
            "rebuy_enabled": True,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.CAUTIOUS_BALANCED_GRID.value:
        buy_n = 3 if budget in (BudgetTier.SMALL.value, BudgetTier.STANDARD.value) else 4
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.35,
            "base_alloc_max": 0.48,
            "buy_grid_count": buy_n,
            "sell_grid_count": buy_n,
            "buy_spacing_atr_mult": 0.90,
            "sell_spacing_atr_mult": 0.80,
            "buy_spacing_min_pct": 0.45,
            "sell_spacing_min_pct": 0.45,
            "buy_distribution": "front_light",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.25,
            "max_base_exposure_extra": 0.08,
            "max_base_exposure_cap": 0.62,
            "trailing_enabled": True,
            "trailing_side": "both",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": True,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.BALANCED_GRID.value:
        buy_n = 3 if budget == BudgetTier.SMALL.value else 4
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.38,
            "base_alloc_max": 0.52,
            "buy_grid_count": buy_n,
            "sell_grid_count": buy_n,
            "buy_spacing_atr_mult": 0.85,
            "sell_spacing_atr_mult": 0.75,
            "buy_spacing_min_pct": 0.45,
            "sell_spacing_min_pct": 0.45,
            "buy_distribution": "balanced",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.28,
            "max_base_exposure_extra": 0.09,
            "max_base_exposure_cap": 0.68,
            "trailing_enabled": True,
            "trailing_side": "both",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": True,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.ACTIVE_RANGE_GRID.value:
        buy_n = 5 if budget in (BudgetTier.MEDIUM.value, BudgetTier.LARGE.value) else 4
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.48,
            "base_alloc_max": 0.62,
            "buy_grid_count": buy_n,
            "sell_grid_count": buy_n,
            "buy_spacing_atr_mult": 0.70,
            "sell_spacing_atr_mult": 0.65,
            "buy_spacing_min_pct": 0.45,
            "sell_spacing_min_pct": 0.45,
            "buy_distribution": "balanced",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.22,
            "max_base_exposure_extra": 0.10,
            "max_base_exposure_cap": 0.72,
            "trailing_enabled": True,
            "trailing_side": "both",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": True,
            "resell_enabled": True,
            "min_range_score": 70,
            "min_fee_efficiency_score": 70,
            "min_liquidity_score": 70,
            "min_spread_score": 70,
        }
    if profile == ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value:
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.52,
            "base_alloc_max": 0.65,
            "buy_grid_count": 6,
            "sell_grid_count": 6,
            "buy_spacing_atr_mult": 0.65,
            "sell_spacing_atr_mult": 0.60,
            "buy_spacing_min_pct": 0.45,
            "sell_spacing_min_pct": 0.45,
            "buy_distribution": "balanced",
            "sell_distribution": "balanced",
            "max_quote_to_spend_per_buy_frac": 0.20,
            "max_base_exposure_extra": 0.10,
            "max_base_exposure_cap": 0.75,
            "trailing_enabled": True,
            "trailing_side": "both",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": True,
            "resell_enabled": True,
            "min_range_score": 75,
            "min_fee_efficiency_score": 75,
            "min_liquidity_score": 75,
            "min_spread_score": 75,
        }
    if profile == ProfileFamily.TREND_TRAILING.value:
        return {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.45,
            "base_alloc_max": 0.65,
            "buy_grid_count": 3,
            "sell_grid_count": 3,
            "buy_spacing_atr_mult": 0.80,
            "sell_spacing_atr_mult": 0.70,
            "trailing_enabled": True,
            "trailing_side": "both",
            "trailing_atr_mult": 0.45,
            "min_trailing_pct": 0.35,
            "max_base_exposure_extra": 0.08,
            "max_base_exposure_cap": 0.70,
            "rebuy_enabled": True,
            "resell_enabled": True,
        }
    if profile == ProfileFamily.BREAKOUT_PROTECTION.value:
        return {
            "buy_grid_count": 0,
            "sell_grid_count": 0,
            "cancel_existing_buy_orders": True,
            "cancel_existing_sell_orders": False,
        }
    if profile == ProfileFamily.HIGH_VOL_PROTECTION.value:
        return {
            "buy_grid_count": 1,
            "sell_grid_count": 1,
            "buy_spacing_atr_mult": 1.5,
            "sell_spacing_atr_mult": 1.3,
            "buy_spacing_min_pct": 0.80,
            "sell_spacing_min_pct": 0.70,
            "spacing_friction_mult": 3.5,
            "trailing_enabled": False,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "max_base_exposure_extra": 0.03,
            "max_base_exposure_cap": 0.40,
        }
    if profile == ProfileFamily.LOW_LIQUIDITY_WAIT.value:
        return {
            "buy_grid_count": 0,
            "sell_grid_count": 0,
            "cancel_existing_buy_orders": True,
            "cancel_existing_sell_orders": False,
        }
    return {"buy_grid_count": 0, "sell_grid_count": 0}


def _hard_limits_for_profile(profile: str) -> Dict[str, Any]:
    if profile in (ProfileFamily.NO_TRADE.value, ProfileFamily.WAIT.value):
        return {"buy_grid_allowed": False, "max_buy_levels": 0}
    if profile in (
        ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        ProfileFamily.RECOVERY_SELL.value,
    ):
        return {
            "buy_grid_allowed": False,
            "max_buy_levels": 0,
            "requires_has_base": True,
            "requires_sell_min_notional": True,
        }
    if profile in (
        ProfileFamily.ACTIVE_RANGE_GRID.value,
        ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value,
    ):
        return {"buy_grid_allowed": True, "min_sub_scores_enforced": True}
    return {}


def _priority_for_profile(profile: str, score_min: int) -> int:
    base = {
        ProfileFamily.NO_TRADE.value: 100,
        ProfileFamily.SELL_MANAGEMENT_ONLY.value: 90,
        ProfileFamily.RECOVERY_SELL.value: 88,
        ProfileFamily.WAIT.value: 85,
        ProfileFamily.BREAKOUT_PROTECTION.value: 82,
        ProfileFamily.ULTRA_DEFENSIVE_GRID.value: 70,
        ProfileFamily.DEFENSIVE_GRID.value: 65,
        ProfileFamily.CAUTIOUS_BALANCED_GRID.value: 75,
        ProfileFamily.BALANCED_GRID.value: 72,
        ProfileFamily.ACTIVE_RANGE_GRID.value: 80,
        ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: 78,
        ProfileFamily.TREND_TRAILING.value: 76,
        ProfileFamily.LOW_FEE_WIDE_GRID.value: 74,
        ProfileFamily.HIGH_VOL_PROTECTION.value: 83,
        ProfileFamily.LOW_LIQUIDITY_WAIT.value: 86,
    }.get(profile, 50)
    return base + min(score_min // 10, 5)


def _make_template(
    profile: str,
    regime: str,
    budget: str,
    exposure: str,
    headroom: str,
    fee: str,
    score_min: int,
    score_max: int,
    risk_states: Sequence[str],
    suffix: str = "",
) -> ParamTemplate:
    eq_min, eq_max = _BUDGET_EQUITY[budget]
    params = _base_params_for_profile(profile, budget)
    if "rebalance_policy" not in params:
        params = {**params, "rebalance_policy": _default_rebalance_policy(profile)}
    key_parts = [
        regime,
        budget,
        f"{score_min}_{score_max}",
        profile.replace("_PROFILE", "").replace("_GRID", ""),
    ]
    if exposure != ExposureTier.TARGET_BASE.value:
        key_parts.append(exposure)
    if headroom:
        key_parts.append(headroom)
    if suffix:
        key_parts.append(suffix)
    template_key = "_".join(key_parts)

    min_sub = {
        "min_range_score": int(params.pop("min_range_score", 0) or 0),
        "min_liquidity_score": int(params.pop("min_liquidity_score", 0) or 0),
        "min_spread_score": int(params.pop("min_spread_score", 0) or 0),
        "min_fee_efficiency_score": int(params.pop("min_fee_efficiency_score", 0) or 0),
    }

    mn_mult = 10.0 if budget in (BudgetTier.NANO.value, BudgetTier.MICRO.value, BudgetTier.SMALL.value) else 20.0
    action = _PROFILE_ACTION[profile]
    deployable = action not in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)
    requires_sellable_base = action == FinalAction.SELL_MANAGEMENT_ONLY.value

    return ParamTemplate(
        template_key=template_key,
        version=POOL_VERSION_ID,
        profile_family=profile,
        final_action=action,
        supported_regimes=[regime],
        allowed_risk_states=list(risk_states),
        score_min=score_min,
        score_max=score_max,
        budget_tiers=[budget],
        exposure_tiers=[exposure],
        headroom_tiers=[headroom] if headroom else [h.value for h in HeadroomTier],
        fee_tiers=[fee] if fee else [f.value for f in FeeTier],
        min_equity_usdt=eq_min,
        max_equity_usdt=eq_max,
        min_notional_multiple=mn_mult,
        min_headroom_multiple=0.0,
        min_range_score=min_sub["min_range_score"],
        min_liquidity_score=min_sub["min_liquidity_score"],
        min_spread_score=min_sub["min_spread_score"],
        min_fee_efficiency_score=min_sub["min_fee_efficiency_score"],
        params=params,
        hard_limits=_hard_limits_for_profile(profile),
        priority=_priority_for_profile(profile, score_min),
        deployable=deployable,
        requires_sellable_base=requires_sellable_base,
        status="active",
    )


def _generate_profile_variants(profile: str, target: int) -> List[ParamTemplate]:
    templates: List[ParamTemplate] = []
    regimes = _PROFILE_REGIMES.get(profile, [RegimeTag.BALANCED_RANGE.value])
    budgets = _PROFILE_BUDGETS.get(profile, [BudgetTier.STANDARD.value])
    exposures = _PROFILE_EXPOSURE.get(profile, [ExposureTier.TARGET_BASE.value])
    headrooms = _PROFILE_HEADROOM.get(profile, [h.value for h in HeadroomTier])
    fees = _PROFILE_FEE.get(profile, [f.value for f in FeeTier])
    score_ranges = _PROFILE_SCORE_RANGES.get(profile, [(50, 69)])
    risks = _PROFILE_RISK.get(profile, ["CAUTION", "NORMAL", "SAFE", "DEFENSIVE"])

    idx = 0
    for regime in regimes:
        for budget in budgets:
            for score_min, score_max in score_ranges:
                for exposure in exposures:
                    for headroom in headrooms:
                        fee = fees[idx % len(fees)]
                        t = _make_template(
                            profile,
                            regime,
                            budget,
                            exposure,
                            headroom,
                            fee,
                            score_min,
                            score_max,
                            risks,
                        )
                        templates.append(t)
                        idx += 1
                        if len(templates) >= target:
                            return templates[:target]
    return templates[:target]


def _pinned_templates() -> List[ParamTemplate]:
    """Explicit high-priority templates required by regression tests."""
    sell_mgmt = ParamTemplate(
        template_key="BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        final_action=FinalAction.SELL_MANAGEMENT_ONLY.value,
        supported_regimes=[
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_LOW_VOL.value,
            RegimeTag.RANGE_HIGH_VOL.value,
        ],
        allowed_risk_states=["CAUTION", "NORMAL", "DEFENSIVE"],
        score_min=60,
        score_max=69,
        budget_tiers=[BudgetTier.SMALL.value],
        exposure_tiers=[ExposureTier.TARGET_BASE.value, ExposureTier.HIGH_BASE.value],
        headroom_tiers=[HeadroomTier.NO_HEADROOM.value, HeadroomTier.LOW_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_BAD.value, FeeTier.FEE_WEAK.value, FeeTier.FEE_OK.value],
        min_equity_usdt=50,
        max_equity_usdt=99,
        min_notional_multiple=10,
        min_headroom_multiple=0,
        min_liquidity_score=50,
        min_spread_score=50,
        params={
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.42,
            "buy_grid_count": 0,
            "sell_grid_count": 3,
            "sell_spacing_mode": "atr_mult",
            "sell_spacing_atr_mult": 0.75,
            "sell_spacing_min_pct": 0.45,
            "sell_spacing_max_pct": 3.0,
            "sell_distribution": "balanced",
            "trailing_enabled": True,
            "trailing_side": "sell",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "take_profit_pct": 1.35,
            "max_base_exposure_extra": 0.06,
            "max_base_exposure_cap": 0.56,
            "cancel_existing_buy_orders": True,
        },
        hard_limits={
            "buy_grid_allowed": False,
            "max_buy_levels": 0,
            "requires_sell_min_notional": True,
        },
        priority=95,
        status="active",
        notes="SOL 50 USDT headroom yok + base var senaryosu",
    )
    cautious = ParamTemplate(
        template_key="BALANCED_RANGE_STANDARD_60_69_CAUTION_GRID",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.CAUTIOUS_BALANCED_GRID.value,
        final_action=FinalAction.BALANCED_GRID.value,
        supported_regimes=[RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_LOW_VOL.value],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE"],
        score_min=60,
        score_max=69,
        budget_tiers=[BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value],
        exposure_tiers=[ExposureTier.LOW_BASE.value, ExposureTier.TARGET_BASE.value],
        headroom_tiers=[HeadroomTier.MEDIUM_HEADROOM.value, HeadroomTier.GOOD_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_OK.value, FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value],
        min_equity_usdt=100,
        max_equity_usdt=None,
        min_notional_multiple=20,
        min_fee_efficiency_score=50,
        min_liquidity_score=60,
        min_spread_score=60,
        params=_base_params_for_profile(
            ProfileFamily.CAUTIOUS_BALANCED_GRID.value, BudgetTier.STANDARD.value
        ),
        hard_limits={},
        priority=85,
        status="active",
    )
    active = ParamTemplate(
        template_key="RANGE_HIGH_VOL_MEDIUM_75_89_ACTIVE_GRID",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.ACTIVE_RANGE_GRID.value,
        final_action=FinalAction.ACTIVE_GRID.value,
        supported_regimes=[RegimeTag.RANGE_HIGH_VOL.value, RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL", "SAFE"],
        score_min=75,
        score_max=89,
        budget_tiers=[BudgetTier.MEDIUM.value, BudgetTier.LARGE.value, BudgetTier.WHALE.value],
        exposure_tiers=[ExposureTier.LOW_BASE.value, ExposureTier.TARGET_BASE.value],
        headroom_tiers=[HeadroomTier.GOOD_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value],
        min_equity_usdt=250,
        min_notional_multiple=40,
        min_range_score=70,
        min_fee_efficiency_score=70,
        min_liquidity_score=70,
        min_spread_score=70,
        min_exposure_safety_score=65,
        params=_base_params_for_profile(
            ProfileFamily.ACTIVE_RANGE_GRID.value, BudgetTier.MEDIUM.value
        ),
        hard_limits={"buy_grid_allowed": True, "min_sub_scores_enforced": True},
        priority=88,
        status="active",
    )
    dump_no_trade = ParamTemplate(
        template_key="DUMP_RISK_ANY_NO_TRADE",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.NO_TRADE.value,
        final_action=FinalAction.NO_TRADE.value,
        supported_regimes=[RegimeTag.DUMP_RISK.value],
        allowed_risk_states=["BLOCKED", "DEFENSIVE", "CAUTION", "NORMAL", "SAFE"],
        score_min=0,
        score_max=100,
        budget_tiers=[b.value for b in BudgetTier],
        exposure_tiers=[e.value for e in ExposureTier],
        headroom_tiers=[h.value for h in HeadroomTier],
        fee_tiers=[f.value for f in FeeTier],
        min_equity_usdt=0,
        min_notional_multiple=0,
        params={"buy_grid_count": 0, "sell_grid_count": 0, "cancel_existing_buy_orders": True},
        hard_limits={"buy_grid_allowed": False, "max_buy_levels": 0},
        deployable=False,
        priority=200,
        status="active",
        notes="DUMP_RISK override",
    )
    fee_bad_wait = ParamTemplate(
        template_key="BALANCED_RANGE_60_69_FEE_BAD_WAIT",
        version=POOL_VERSION_V3,
        profile_family=ProfileFamily.ACTIVE_DEFENSIVE_GRID.value,
        final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        supported_regimes=[
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_LOW_VOL.value,
            RegimeTag.RANGE_HIGH_VOL.value,
        ],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE"],
        score_min=60,
        score_max=69,
        budget_tiers=[b.value for b in BudgetTier],
        exposure_tiers=[ExposureTier.NO_BASE.value, ExposureTier.LOW_BASE.value],
        headroom_tiers=[h.value for h in HeadroomTier],
        fee_tiers=[FeeTier.FEE_BAD.value],
        min_equity_usdt=25,
        min_notional_multiple=5,
        min_liquidity_score=60,
        min_spread_score=70,
        min_data_quality_score=80,
        min_exposure_safety_score=60,
        params={
            "base_alloc_frac": 0.45,
            "buy_grid_count": 2,
            "sell_grid_count": 2,
            "buy_spacing_mode": "fixed",
            "buy_spacing_min_pct": 1.50,
            "buy_spacing_max_pct": 4.0,
            "sell_spacing_mode": "fixed",
            "sell_spacing_min_pct": 1.20,
            "sell_spacing_max_pct": 4.0,
            "buy_distribution": "back_heavy",
            "sell_distribution": "back_heavy",
            "trailing_enabled": True,
            "min_trailing_pct": 0.35,
            "rebuy_enabled": True,
            "resell_enabled": True,
            "take_profit_pct": 2.0,
            "max_base_exposure_extra": 0.08,
            "dps_engine_version": "DPS_ENGINE_V2",
        },
        hard_limits={"buy_grid_allowed": True},
        deployable=True,
        priority=115,
        status="active",
        notes="Fee verimi düşük — genişletilmiş ACTIVE_DEFENSIVE_GRID (bekleme yok)",
    )
    fee_bad_sell_mgmt = ParamTemplate(
        template_key="BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        final_action=FinalAction.SELL_MANAGEMENT_ONLY.value,
        supported_regimes=[
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_LOW_VOL.value,
            RegimeTag.RANGE_HIGH_VOL.value,
        ],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE"],
        score_min=60,
        score_max=69,
        budget_tiers=[
            BudgetTier.SMALL.value,
            BudgetTier.STANDARD.value,
            BudgetTier.MEDIUM.value,
            BudgetTier.LARGE.value,
        ],
        exposure_tiers=[ExposureTier.TARGET_BASE.value, ExposureTier.HIGH_BASE.value],
        headroom_tiers=[HeadroomTier.NO_HEADROOM.value, HeadroomTier.LOW_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_BAD.value, FeeTier.FEE_WEAK.value],
        min_equity_usdt=50,
        min_notional_multiple=8,
        min_liquidity_score=60,
        min_spread_score=70,
        min_data_quality_score=80,
        min_exposure_safety_score=60,
        params={
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.42,
            "buy_grid_count": 0,
            "sell_grid_count": 3,
            "sell_spacing_mode": "atr_mult",
            "sell_spacing_atr_mult": 0.90,
            "sell_spacing_min_pct": 0.55,
            "sell_spacing_max_pct": 3.5,
            "sell_distribution": "balanced",
            "trailing_enabled": True,
            "trailing_side": "sell",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "take_profit_pct": 1.35,
            "max_base_exposure_extra": 0.04,
            "max_base_exposure_cap": 0.56,
            "cancel_existing_buy_orders": True,
        },
        hard_limits={
            "requires_has_base": True,
            "buy_grid_allowed": False,
            "max_buy_levels": 0,
            "requires_sell_min_notional": True,
        },
        requires_sellable_base=True,
        deployable=True,
        priority=104,
        status="active",
        notes="Fee/headroom nedeniyle yalnızca satış yönetimi",
    )
    fee_weak_wide = ParamTemplate(
        template_key="BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.LOW_FEE_WIDE_GRID.value,
        final_action=FinalAction.BALANCED_GRID.value,
        supported_regimes=[
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_LOW_VOL.value,
            RegimeTag.RANGE_HIGH_VOL.value,
        ],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE"],
        score_min=60,
        score_max=69,
        budget_tiers=[
            BudgetTier.SMALL.value,
            BudgetTier.STANDARD.value,
            BudgetTier.MEDIUM.value,
            BudgetTier.LARGE.value,
        ],
        exposure_tiers=[
            ExposureTier.NO_BASE.value,
            ExposureTier.LOW_BASE.value,
            ExposureTier.TARGET_BASE.value,
        ],
        headroom_tiers=[HeadroomTier.MEDIUM_HEADROOM.value, HeadroomTier.GOOD_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_WEAK.value, FeeTier.FEE_OK.value],
        min_equity_usdt=50,
        min_notional_multiple=10,
        min_headroom_multiple=2.0,
        min_liquidity_score=60,
        min_spread_score=70,
        min_data_quality_score=80,
        min_exposure_safety_score=60,
        params=_base_params_for_profile(
            ProfileFamily.LOW_FEE_WIDE_GRID.value, BudgetTier.STANDARD.value
        ),
        hard_limits={"buy_grid_allowed": True},
        priority=103,
        status="active",
        notes="Düşük fee — geniş aralıklı dengeli grid",
    )
    overexposed_recovery = ParamTemplate(
        template_key="OVEREXPOSED_ANY_RECOVERY_SELL",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.RECOVERY_SELL.value,
        final_action=FinalAction.SELL_MANAGEMENT_ONLY.value,
        supported_regimes=[
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_LOW_VOL.value,
            RegimeTag.RANGE_HIGH_VOL.value,
            RegimeTag.TRENDING_DOWN.value,
            RegimeTag.HIGH_VOL_UNSTABLE.value,
        ],
        allowed_risk_states=["DEFENSIVE", "CAUTION", "NORMAL"],
        score_min=30,
        score_max=100,
        budget_tiers=[b.value for b in BudgetTier if b != BudgetTier.NANO],
        exposure_tiers=[ExposureTier.OVEREXPOSED.value],
        headroom_tiers=[h.value for h in HeadroomTier],
        fee_tiers=[f.value for f in FeeTier],
        min_equity_usdt=25,
        min_notional_multiple=5,
        params={
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.80,
            "buy_grid_count": 0,
            "sell_grid_count": 4,
            "sell_spacing_mode": "atr_mult",
            "sell_spacing_atr_mult": 0.85,
            "sell_spacing_min_pct": 0.50,
            "sell_spacing_max_pct": 3.5,
            "sell_distribution": "balanced",
            "trailing_enabled": True,
            "trailing_side": "sell",
            "min_trailing_pct": 0.35,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "take_profit_pct": 1.20,
            "max_base_exposure_extra": 0.0,
            "max_base_exposure_cap": 0.80,
            "cancel_existing_buy_orders": True,
        },
        hard_limits={
            "requires_has_base": True,
            "buy_grid_allowed": False,
            "max_buy_levels": 0,
            "requires_sell_min_notional": True,
        },
        priority=112,
        status="active",
        notes="Aşırı maruz — kontrollü base azaltma",
    )
    trending_down_defensive = ParamTemplate(
        template_key="TRENDING_DOWN_50_69_DEFENSIVE_WAIT_OR_SELL",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.RECOVERY_SELL.value,
        final_action=FinalAction.SELL_MANAGEMENT_ONLY.value,
        supported_regimes=[RegimeTag.TRENDING_DOWN.value],
        allowed_risk_states=["DEFENSIVE", "CAUTION", "NORMAL"],
        score_min=50,
        score_max=69,
        budget_tiers=[
            BudgetTier.SMALL.value,
            BudgetTier.STANDARD.value,
            BudgetTier.MEDIUM.value,
            BudgetTier.LARGE.value,
        ],
        exposure_tiers=[
            ExposureTier.TARGET_BASE.value,
            ExposureTier.HIGH_BASE.value,
            ExposureTier.OVEREXPOSED.value,
        ],
        headroom_tiers=[h.value for h in HeadroomTier],
        fee_tiers=[f.value for f in FeeTier],
        min_equity_usdt=50,
        min_notional_multiple=5,
        params={
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.45,
            "buy_grid_count": 0,
            "sell_grid_count": 3,
            "sell_spacing_atr_mult": 0.90,
            "sell_spacing_min_pct": 0.55,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "cancel_existing_buy_orders": True,
        },
        hard_limits={
            "requires_has_base": True,
            "requires_sell_min_notional": True,
            "buy_grid_allowed": False,
            "max_buy_levels": 0,
        },
        requires_sellable_base=True,
        priority=108,
        status="active",
        notes="Aşağı trend — aktif alış yok, base varsa satış yönetimi",
    )
    active_good_fee = ParamTemplate(
        template_key="RANGE_HIGH_VOL_70_89_ACTIVE_GOOD_FEE",
        version=POOL_VERSION_ID,
        profile_family=ProfileFamily.ACTIVE_RANGE_GRID.value,
        final_action=FinalAction.ACTIVE_GRID.value,
        supported_regimes=[RegimeTag.RANGE_HIGH_VOL.value, RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL", "SAFE"],
        score_min=70,
        score_max=89,
        budget_tiers=[
            BudgetTier.MEDIUM.value,
            BudgetTier.LARGE.value,
            BudgetTier.WHALE.value,
        ],
        exposure_tiers=[ExposureTier.LOW_BASE.value, ExposureTier.TARGET_BASE.value],
        headroom_tiers=[HeadroomTier.GOOD_HEADROOM.value],
        fee_tiers=[FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value],
        min_equity_usdt=250,
        min_notional_multiple=40,
        min_range_score=70,
        min_fee_efficiency_score=65,
        min_liquidity_score=70,
        min_spread_score=70,
        params=_base_params_for_profile(
            ProfileFamily.ACTIVE_RANGE_GRID.value, BudgetTier.MEDIUM.value
        ),
        hard_limits={"buy_grid_allowed": True, "min_sub_scores_enforced": True},
        priority=89,
        status="active",
        notes="RANGE_HIGH_VOL 70–89 aktif grid — iyi fee",
    )
    return [
        sell_mgmt,
        cautious,
        active,
        dump_no_trade,
        fee_bad_wait,
        fee_bad_sell_mgmt,
        fee_weak_wide,
        overexposed_recovery,
        trending_down_defensive,
        active_good_fee,
    ]


def build_v1_pool(target_count: int | None = None) -> List[ParamTemplate]:
    """Build V1 pool — delegates to generator for 50k scale."""
    from app.services.dynamic_param_score.param_pool.generator import (
        POOL_TARGET_V1,
        generate_pool,
    )

    return generate_pool(target_count or POOL_TARGET_V1)


def build_v2_pool(target_count: int | None = None) -> List[ParamTemplate]:
    """Build V2 pool — 50k base + 50k precision expansion."""
    from app.services.dynamic_param_score.param_pool.precision_generator import (
        POOL_TARGET_V2,
        generate_pool_v2,
    )

    return generate_pool_v2(target_count or POOL_TARGET_V2)


def build_v3_pool(target_count: int | None = None) -> List[ParamTemplate]:
    """Build DPS Engine V2 pool — migrated 100k + 100k coverage-gap profiles."""
    from app.services.dynamic_param_score.param_generator.param_library_builder import (
        POOL_TARGET_V3,
        build_dps_v2_pool,
        resolve_pool_build_target,
    )

    target = target_count if target_count is not None else resolve_pool_build_target()
    return build_dps_v2_pool(total_target=target, migrate_legacy=target >= POOL_TARGET_V3)


def build_v4_pool(target_count: int | None = None) -> List[ParamTemplate]:
    """Build DPS Engine V4 pool — 200k migrated v3 + 100k shelf-routed profiles."""
    from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
        POOL_TARGET_V4,
        build_dps_v4_pool,
        resolve_pool_build_target_v4,
    )

    target = target_count if target_count is not None else resolve_pool_build_target_v4()
    return build_dps_v4_pool(total_target=target, migrate_v3=target >= 50_000)
