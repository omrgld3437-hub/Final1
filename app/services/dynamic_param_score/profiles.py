"""Profile selection and parameter curve computation."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import (
    BotParams,
    FinalAction,
    IndicatorSnapshot,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.utils import clamp, distribute_weights, scale


PROFILE_NO_TRADE = "NO_TRADE_PROFILE"
PROFILE_DEFENSIVE = "DEFENSIVE_GRID_PROFILE"
PROFILE_BALANCED = "BALANCED_GRID_PROFILE"
PROFILE_ACTIVE = "ACTIVE_RANGE_GRID_PROFILE"
PROFILE_TREND = "TREND_TRAILING_PROFILE"


def _active_grid_eligible(
    sub: SubScores,
    param_score: int,
    regime: RegimeTag,
    risk_state: str,
    budget_usdt: float,
    min_notional: float,
) -> bool:
    if param_score < C.ACTIVE_GRID_MIN_PARAM_SCORE:
        return False
    if risk_state not in C.ACTIVE_GRID_ALLOWED_RISK:
        return False
    if regime not in (RegimeTag.BALANCED_RANGE, RegimeTag.RANGE_HIGH_VOL):
        return False
    if int(sub.fee_efficiency_score or 0) < C.FEE_EFF_ACTIVE_FORBIDDEN:
        return False
    if budget_usdt < min_notional * 10:
        return False
    if budget_usdt <= C.SMALL_BUDGET_75_USDT:
        return False
    for key, minimum in C.ACTIVE_GRID_MIN_SUB.items():
        if int(getattr(sub, key, 0) or 0) < minimum:
            return False
    return True


def select_profile_family(
    regime: RegimeTag,
    risk_state: str,
    param_score: int,
    sub: Optional[SubScores] = None,
    budget_usdt: float = 1000.0,
    min_notional: float = C.DEFAULT_MIN_NOTIONAL_USDT,
) -> Tuple[str, str]:
    """Return (profile_name, final_action)."""
    sub = sub or SubScores()
    budget = max(float(budget_usdt or 0.0), 0.0)
    min_n = max(float(min_notional or C.DEFAULT_MIN_NOTIONAL_USDT), 1.0)

    if risk_state == RiskState.BLOCKED.value or regime in (
        RegimeTag.NO_DATA,
        RegimeTag.NO_TRADE,
        RegimeTag.DUMP_RISK,
    ):
        return PROFILE_NO_TRADE, FinalAction.NO_TRADE.value

    if param_score < 15:
        return PROFILE_NO_TRADE, FinalAction.NO_TRADE.value

    if regime == RegimeTag.TRENDING_DOWN or risk_state == RiskState.DEFENSIVE.value:
        return PROFILE_DEFENSIVE, FinalAction.DEFENSIVE_GRID.value

    if regime == RegimeTag.TRENDING_UP and param_score >= 65:
        return PROFILE_TREND, FinalAction.TREND_TRAILING.value

    if regime in (RegimeTag.RANGE_HIGH_VOL, RegimeTag.BALANCED_RANGE):
        if _active_grid_eligible(sub, param_score, regime, risk_state, budget, min_n):
            return PROFILE_ACTIVE, FinalAction.ACTIVE_GRID.value
        if int(sub.fee_efficiency_score or 0) < C.FEE_EFF_CAUTIOUS:
            if budget <= C.SMALL_BUDGET_50_USDT or budget < min_n * 10:
                return PROFILE_BALANCED, FinalAction.WAIT.value
            return PROFILE_BALANCED, FinalAction.BALANCED_GRID.value
        if param_score >= 45:
            return PROFILE_BALANCED, FinalAction.BALANCED_GRID.value
        return PROFILE_DEFENSIVE, FinalAction.DEFENSIVE_GRID.value

    if regime == RegimeTag.RANGE_LOW_VOL:
        return PROFILE_BALANCED, FinalAction.BALANCED_GRID.value

    if regime == RegimeTag.HIGH_VOL_UNSTABLE:
        if param_score >= 50:
            return PROFILE_DEFENSIVE, FinalAction.DEFENSIVE_GRID.value
        return PROFILE_NO_TRADE, FinalAction.WAIT.value

    if regime == RegimeTag.BREAKOUT_RISK:
        if param_score >= 55:
            return PROFILE_DEFENSIVE, FinalAction.WAIT.value
        return PROFILE_NO_TRADE, FinalAction.NO_TRADE.value

    if param_score >= 60:
        return PROFILE_BALANCED, FinalAction.BALANCED_GRID.value
    if param_score >= 30:
        return PROFILE_DEFENSIVE, FinalAction.DEFENSIVE_GRID.value
    return PROFILE_NO_TRADE, FinalAction.NO_TRADE.value


def _apply_budget_grid_caps(
    buy_n: int,
    sell_n: int,
    budget_usdt: float,
    min_notional: float,
) -> Tuple[int, int]:
    budget = max(float(budget_usdt or 0.0), 0.0)
    min_n = max(float(min_notional or C.DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    if budget <= C.SMALL_BUDGET_75_USDT:
        buy_n = min(buy_n, C.SMALL_BUDGET_MAX_GRID_COUNT)
        sell_n = min(sell_n, C.SMALL_BUDGET_MAX_GRID_COUNT)
    if budget <= C.SMALL_BUDGET_50_USDT:
        buy_n = min(buy_n, 3)
        sell_n = min(sell_n, 3)
    if budget < min_n * 10:
        buy_n = min(buy_n, 2)
        sell_n = min(sell_n, 2)
    return max(buy_n, 0), max(sell_n, 0)


def _grid_counts(profile: str, param_score: int) -> Tuple[int, int]:
    if profile == PROFILE_DEFENSIVE:
        buy = int(scale(param_score, 15, 45, 3, 6))
        sell = int(scale(param_score, 15, 45, 2, 4))
    elif profile == PROFILE_BALANCED:
        buy = int(scale(param_score, 45, 75, 4, 7))
        sell = int(scale(param_score, 45, 75, 3, 6))
    elif profile == PROFILE_ACTIVE:
        buy = int(scale(param_score, 70, 90, 5, 9))
        sell = int(scale(param_score, 70, 90, 4, 8))
    elif profile == PROFILE_TREND:
        buy = int(scale(param_score, 65, 95, 2, 5))
        sell = int(scale(param_score, 65, 95, 2, 5))
    else:
        buy, sell = 0, 0
    return max(buy, 0), max(sell, 0)


def _alloc_and_exposure(
    profile: str,
    param_score: int,
    regime: RegimeTag,
) -> Tuple[float, float, float]:
    if profile == PROFILE_DEFENSIVE:
        base = scale(param_score, 15, 45, 0.08, 0.28)
        extra = scale(param_score, 15, 45, 0.03, 0.06)
    elif profile == PROFILE_BALANCED:
        base = scale(param_score, 45, 75, 0.30, 0.52)
        extra = scale(param_score, 45, 75, 0.06, 0.10)
    elif profile == PROFILE_ACTIVE:
        base = scale(param_score, 70, 90, 0.45, 0.65)
        extra = scale(param_score, 70, 90, 0.08, 0.12)
    elif profile == PROFILE_TREND:
        base = scale(param_score, 65, 95, 0.45, 0.70)
        extra = min(0.10, scale(param_score, 65, 95, 0.06, 0.10))
    else:
        return 0.0, 1.0, 0.0

    base = min(base, C.MAX_BASE_ALLOC_FRAC)
    max_exp = min(base + extra, C.MAX_BASE_EXPOSURE_FRAC)
    if regime == RegimeTag.TRENDING_DOWN:
        base = min(base, C.TRENDING_DOWN_MAX_BASE_ALLOC)
        max_exp = min(max_exp, base + C.TRENDING_DOWN_MAX_EXPOSURE_EXTRA)
    return base, 1.0 - base, max_exp


def _grid_spacing(
    profile: str,
    atr_pct: float,
    fee_slippage: float,
) -> Tuple[float, float, float]:
    fee_floor = 2 * fee_slippage
    min_spacing = max(fee_floor * C.FEE_SPACING_MULTIPLIER, C.MIN_SPACING_FLOOR_PCT)
    atr = max(atr_pct, 0.1)

    if profile == PROFILE_DEFENSIVE:
        buy_s = clamp(atr * 1.2, min_spacing, 4.5)
        sell_s = clamp(atr * 0.9, min_spacing, 3.5)
        trail = 0.0
    elif profile == PROFILE_BALANCED:
        buy_s = clamp(atr * 0.9, min_spacing, 3.0)
        sell_s = clamp(atr * 0.75, min_spacing, 2.5)
        trail = 0.0
    elif profile == PROFILE_ACTIVE:
        buy_s = clamp(atr * 0.65, min_spacing, 2.2)
        sell_s = clamp(atr * 0.55, min_spacing, 2.0)
        trail = 0.0
    elif profile == PROFILE_TREND:
        buy_s = clamp(atr * 0.8, min_spacing, 3.0)
        sell_s = clamp(atr * 0.7, min_spacing, 2.5)
        trail = clamp(atr * 0.45, 0.25, 2.5)
    else:
        return 0.0, 0.0, 0.0
    return buy_s, sell_s, trail


def _max_quote_per_buy(profile: str, regime: RegimeTag) -> float:
    cap = C.MAX_QUOTE_PER_BUY_FRAC
    if profile == PROFILE_DEFENSIVE:
        cap = min(cap, 0.25)
    if regime == RegimeTag.TRENDING_DOWN:
        cap = min(cap, C.TRENDING_DOWN_MAX_QUOTE_PER_BUY)
    return cap


def build_params(
    profile: str,
    param_score: int,
    regime: RegimeTag,
    ind: IndicatorSnapshot,
    fee_slippage: float,
    budget_usdt: float = 1000.0,
    min_notional: float = C.DEFAULT_MIN_NOTIONAL_USDT,
) -> Optional[BotParams]:
    if profile == PROFILE_NO_TRADE:
        return None

    base, quote, max_exp = _alloc_and_exposure(profile, param_score, regime)
    buy_n, sell_n = _grid_counts(profile, param_score)
    buy_n, sell_n = _apply_budget_grid_caps(buy_n, sell_n, budget_usdt, min_notional)
    atr = ind.atr14_pct_5m or 1.0
    buy_sp, sell_sp, trail = _grid_spacing(profile, atr, fee_slippage)
    max_q = _max_quote_per_buy(profile, regime)

    max_level = 0.25 if profile == PROFILE_DEFENSIVE else 0.30
    if profile == PROFILE_ACTIVE:
        max_level = C.MAX_SINGLE_LEVEL_WEIGHT
    buy_dist = distribute_weights(buy_n, max_level)
    sell_dist = distribute_weights(sell_n, max_level)

    if (
        quote >= 0.40
        and buy_n < 3
        and float(budget_usdt or 0) > C.SMALL_BUDGET_75_USDT
    ):
        buy_n = 3
        buy_dist = distribute_weights(buy_n, max_level)

    trailing = profile == PROFILE_TREND
    tp = clamp(sell_sp * 1.5, 0.5, 5.0)
    min_profit = max(buy_sp * 0.3, fee_slippage * 2)

    return BotParams(
        base_alloc_frac=round(base, 4),
        quote_alloc_frac=round(quote, 4),
        buy_grid_count=buy_n,
        sell_grid_count=sell_n,
        buy_grid_spacing_pct=round(buy_sp, 4),
        sell_grid_spacing_pct=round(sell_sp, 4),
        buy_qty_distribution=[round(x, 4) for x in buy_dist],
        sell_qty_distribution=[round(x, 4) for x in sell_dist],
        trailing_enabled=trailing,
        trailing_callback_pct=round(trail, 4),
        take_profit_pct=round(tp, 4),
        stop_new_buys_below_score=30,
        max_base_exposure_frac=round(max_exp, 4),
        max_quote_to_spend_per_buy_frac=round(max_q, 4),
        downtrend_buy_throttle=regime == RegimeTag.TRENDING_DOWN,
        min_cycle_profit_after_fee_pct=round(min_profit, 4),
        emergency_no_buy=False,
        cancel_existing_buy_orders=regime == RegimeTag.DUMP_RISK,
        cancel_existing_sell_orders=False,
        reason_code=f"{profile}:{regime.value}",
    )
