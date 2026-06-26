"""Market regime classification for Dynamic Param Score Engine."""

from __future__ import annotations

from typing import Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.utils import clamp


def classify_regime(
    ind: IndicatorSnapshot,
    sub: SubScores,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    param_score: int,
) -> RegimeTag:
    if not ind.price_valid or sub.data_quality_score < 30:
        return RegimeTag.NO_DATA

    if sub.data_quality_score < C.DATA_QUALITY_BLOCKED:
        return RegimeTag.NO_TRADE
    if sub.liquidity_score < C.LIQUIDITY_BLOCKED:
        return RegimeTag.LOW_LIQUIDITY
    if sub.spread_score < C.SPREAD_BLOCKED:
        return RegimeTag.SPREAD_UNSAFE
    if portfolio.total_equity_usdt < constraints.min_notional * C.MIN_EQUITY_NOTIONAL_MULT:
        return RegimeTag.NO_TRADE
    if portfolio.current_base_exposure_frac > 0.85:
        return RegimeTag.NO_TRADE
    if param_score < 15:
        return RegimeTag.NO_TRADE

    # DUMP_RISK
    crash = ind.crash_velocity or 0
    ret24 = ind.return_24h_pct or 0
    dd7 = ind.drawdown_7d_pct or 0
    if ret24 < C.DUMP_RETURN_24H_PCT and crash < -1.5:
        return RegimeTag.DUMP_RISK
    if dd7 > 15 and crash < -1.0:
        return RegimeTag.DUMP_RISK
    if ret24 < -6 and (ind.atr14_pct_5m or 0) > 3:
        return RegimeTag.DUMP_RISK
    btc4 = ind.btc_return_4h or 0
    coin1h = ind.return_1h_pct or 0
    if btc4 < -4 and coin1h < -3:
        return RegimeTag.DUMP_RISK
    if (
        ind.atr14_pct_5m
        and ind.atr14_pct_5m > 5
        and (ind.ema20_slope_5m or 0) < -0.5
        and (ind.volume_spike_abnormality or 1) > 2.5
    ):
        return RegimeTag.DUMP_RISK

    # TRENDING_DOWN — sharp drawdown / lower-lows (EMA200 not required)
    if (
        ind.lower_lows
        and not ind.higher_highs
        and ret24 <= -6
        and dd7 >= 20
    ):
        return RegimeTag.TRENDING_DOWN
    if (
        ind.lower_lows
        and not ind.higher_highs
        and ret24 <= -4
        and dd7 >= 15
        and (ind.z_score_5m or 0) <= -1.5
    ):
        return RegimeTag.TRENDING_DOWN

    # TRENDING_DOWN — classic trend structure
    if (
        ind.price_vs_ema200_pct is not None
        and ind.price_vs_ema200_pct < -1
        and (ind.ema20_slope_5m or 0) < -0.3
        and (ind.ema50_slope_5m or 0) < -0.2
        and (ind.adx_1h or 0) > C.ADX_TREND_THRESHOLD
        and (ind.rsi14_5m or 50) < 45
    ):
        return RegimeTag.TRENDING_DOWN

    # HIGH_VOL_UNSTABLE
    if (
        (ind.volatility_percentile or 0) > C.ATR_PERCENTILE_HIGH
        and sub.range_score < 45
    ) or (
        (ind.atr14_pct_5m or 0) > 5
        and sub.spread_score < 50
    ):
        return RegimeTag.HIGH_VOL_UNSTABLE

    # TRENDING_UP
    if (
        ind.price_vs_ema200_pct is not None
        and ind.price_vs_ema200_pct > 1
        and (ind.ema20_slope_5m or 0) > 0.3
        and (ind.ema50_slope_5m or 0) > 0.15
        and (ind.adx_1h or 0) > C.ADX_TREND_THRESHOLD
        and sub.drawdown_risk_score >= 45
    ):
        return RegimeTag.TRENDING_UP

    vol_pct = float(ind.volatility_percentile if ind.volatility_percentile is not None else sub.volatility_score)
    wide_chop = bool(ind.higher_highs and ind.lower_lows)
    overbought = (ind.z_score_5m or 0) > 1.8 and (ind.price_in_bb or 0.5) > 0.95
    btc_pressure = float(ind.btc_crash_velocity or 0.0) < -0.5

    # RANGE_HIGH_VOL — wide chop / both highs+lows with elevated vol
    if wide_chop and vol_pct >= 70:
        return RegimeTag.RANGE_HIGH_VOL

    if overbought and wide_chop and (btc_pressure or vol_pct >= 70):
        return RegimeTag.RANGE_HIGH_VOL

    # RANGE_HIGH_VOL
    if (
        (ind.adx_1h or 30) < 25
        and sub.range_score >= 55
        and 1.0 <= (ind.atr14_pct_5m or 0) <= 4.0
        and sub.liquidity_score >= 50
    ):
        return RegimeTag.RANGE_HIGH_VOL

    # RANGE_LOW_VOL — never when historical vol is elevated or structure is wide chop
    if (
        (ind.adx_1h or 30) < 20
        and (ind.atr14_pct_5m or 1) < 1.2
        and sub.range_score >= 50
        and vol_pct < 70
        and not wide_chop
        and (ind.atr14_pct_1h or 0) < 1.5
    ):
        return RegimeTag.RANGE_LOW_VOL

    # BREAKOUT_RISK
    if (
        (ind.bb_width_5m or 0) > 5
        and (ind.volume_spike_abnormality or 1) > 2.0
        and (ind.adx_1h or 0) > 25
    ):
        return RegimeTag.BREAKOUT_RISK

    # BALANCED_RANGE default
    if sub.range_score >= 50 and 40 <= param_score <= 80:
        return RegimeTag.BALANCED_RANGE

    return RegimeTag.BALANCED_RANGE


def determine_risk_state(
    regime: RegimeTag,
    param_score: int,
    sub: SubScores,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    *,
    ind: Optional[IndicatorSnapshot] = None,
) -> str:
    from app.services.dynamic_param_score.models import RiskState

    if sub.data_quality_score < C.DATA_QUALITY_BLOCKED:
        return RiskState.BLOCKED.value
    if portfolio.total_equity_usdt < constraints.min_notional * C.MIN_EQUITY_NOTIONAL_MULT:
        return RiskState.BLOCKED.value
    if sub.spread_score < 25:
        return RiskState.BLOCKED.value
    if regime == RegimeTag.DUMP_RISK:
        return RiskState.BLOCKED.value
    if regime in (RegimeTag.LOW_LIQUIDITY, RegimeTag.SPREAD_UNSAFE):
        return RiskState.BLOCKED.value
    if portfolio.current_base_exposure_frac > 0.85:
        return RiskState.BLOCKED.value

    if ind is not None:
        vol_pct = float(
            ind.volatility_percentile if ind.volatility_percentile is not None else sub.volatility_score
        )
        btc_pressure = float(ind.btc_crash_velocity or 0.0) < -0.5
        overbought = (ind.z_score_5m or 0) > 1.8 and (ind.price_in_bb or 0.5) > 0.95
        if btc_pressure and vol_pct >= 75:
            return RiskState.DEFENSIVE.value
        if overbought and btc_pressure and param_score < 72:
            return RiskState.DEFENSIVE.value
        if overbought and vol_pct >= 85 and param_score < 75:
            return RiskState.DEFENSIVE.value

    if (
        regime == RegimeTag.TRENDING_DOWN
        or param_score < 45
        or sub.btc_market_risk_score < 35
        or sub.drawdown_risk_score < 40
        or sub.exposure_safety_score < 50
    ):
        return RiskState.DEFENSIVE.value

    if 45 <= param_score <= 60:
        return RiskState.CAUTION.value

    if (
        param_score > 75
        and sub.liquidity_score >= 60
        and sub.spread_score >= 60
        and sub.exposure_safety_score >= 65
        and sub.drawdown_risk_score >= 60
        and sub.data_quality_score >= 70
    ):
        return RiskState.SAFE.value

    if 60 < param_score <= 75:
        return RiskState.NORMAL.value

    return RiskState.CAUTION.value
