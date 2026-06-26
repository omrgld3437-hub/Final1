"""Sub-score computation and ParamScore aggregation."""

from __future__ import annotations

from typing import List, Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.indicators import (
    score_data_quality,
    score_exposure_safety,
    score_liquidity,
    score_spread,
)
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    SubScores,
)
from app.services.dynamic_param_score.utils import clamp, invert_score, normalize_score


def _trend_score(ind: IndicatorSnapshot) -> int:
    score = 50
    if ind.price_vs_ema200_pct is not None:
        score += normalize_score(ind.price_vs_ema200_pct, -5, 8) * 0.3 - 15
    if ind.ema20_slope_5m is not None:
        score += normalize_score(ind.ema20_slope_5m, -1.5, 1.5) * 0.25 - 12.5
    if ind.ema50_slope_5m is not None:
        score += normalize_score(ind.ema50_slope_5m, -1.0, 1.0) * 0.2 - 10
    if ind.adx_1h is not None:
        # Strong trend in either direction reduces grid suitability slightly
        adx_pen = max(0, normalize_score(ind.adx_1h, 15, 40) - 50) * 0.15
        score -= adx_pen
    if ind.higher_highs:
        score += 8
    if ind.lower_lows:
        score -= 12
    return int(clamp(score, 0, 100))


def _volatility_score(ind: IndicatorSnapshot) -> int:
    atr = ind.atr14_pct_5m
    if atr is None:
        return 45
    # Sweet spot for grid: 0.5% - 2.5%
    if 0.5 <= atr <= 2.5:
        base = 85
    elif 0.3 <= atr < 0.5 or 2.5 < atr <= 4.0:
        base = 65
    elif atr < 0.3:
        base = 40
    elif atr <= 6.0:
        base = 45
    else:
        base = 20
    if ind.volatility_percentile is not None and ind.volatility_percentile > 90:
        base -= 15
    return int(clamp(base, 0, 100))


def _range_score(ind: IndicatorSnapshot) -> int:
    score = 50
    if ind.bb_width_5m is not None:
        score += normalize_score(ind.bb_width_5m, 1.0, 6.0) * 0.25 - 12.5
    if ind.range_stability is not None:
        score += ind.range_stability * 25
    if ind.mean_reversion_ratio is not None:
        score += normalize_score(ind.mean_reversion_ratio, 0.1, 0.5) * 0.2 - 10
    if ind.adx_1h is not None and ind.adx_1h < 20:
        score += 10
    return int(clamp(score, 0, 100))


def _momentum_score(ind: IndicatorSnapshot) -> int:
    score = 50
    if ind.rsi14_5m is not None:
        # Neutral RSI best for grid
        dist = abs(ind.rsi14_5m - 50)
        score += (50 - dist) * 0.5
    if ind.roc_5m is not None:
        score += normalize_score(-abs(ind.roc_5m), -5, 0) * 0.2
    if ind.return_1h_pct is not None:
        if -2 <= ind.return_1h_pct <= 2:
            score += 10
        elif ind.return_1h_pct < -5:
            score -= 20
    return int(clamp(score, 0, 100))


def _mean_reversion_score(ind: IndicatorSnapshot) -> int:
    score = 50
    if ind.z_score_5m is not None:
        z = abs(ind.z_score_5m)
        if z < 1.0:
            score += 15
        elif z < 2.0:
            score += 5
        else:
            score -= 10
    if ind.mean_reversion_ratio is not None:
        score += normalize_score(ind.mean_reversion_ratio, 0.15, 0.45) * 0.3 - 15
    return int(clamp(score, 0, 100))


def _drawdown_risk_score(ind: IndicatorSnapshot) -> int:
    """Higher = safer (less drawdown risk)."""
    score = 80
    if ind.drawdown_7d_pct is not None:
        score -= min(ind.drawdown_7d_pct * 2.5, 40)
    if ind.drawdown_30d_pct is not None:
        score -= min(ind.drawdown_30d_pct * 1.5, 30)
    if ind.crash_velocity is not None and ind.crash_velocity < -2:
        score -= min(abs(ind.crash_velocity) * 8, 35)
    if ind.consecutive_red_pressure is not None:
        score -= ind.consecutive_red_pressure * 25
    return int(clamp(score, 0, 100))


def _btc_market_risk_score(ind: IndicatorSnapshot) -> int:
    score = 70
    for ret in (ind.btc_return_1h, ind.btc_return_4h, ind.btc_return_24h):
        if ret is not None and ret < -3:
            score -= 15
        elif ret is not None and ret < -1:
            score -= 5
    if ind.btc_below_ema200:
        score -= 15
    if ind.btc_crash_velocity is not None and ind.btc_crash_velocity < -2:
        score -= 20
    return int(clamp(score, 0, 100))


def _fee_efficiency_score(ind: IndicatorSnapshot, constraints: ExchangeConstraints) -> int:
    atr = ind.atr14_pct_5m or 1.0
    spread = max(float(ind.orderbook_spread_pct or 0.0), 0.0)
    friction = constraints.total_fee_slippage_pct * 2 + spread / 2.0
    min_spacing = max(friction * C.FEE_SPACING_MULTIPLIER, C.MIN_SPACING_FLOOR_PCT)
    ratio = atr / min_spacing if min_spacing > 0 else 1.0
    if ratio >= 3.0:
        return 90
    if ratio >= 2.0:
        return 75
    if ratio >= 1.5:
        return 55
    if ratio >= 1.0:
        return 35
    return 15


def compute_sub_scores(
    ind: IndicatorSnapshot,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
) -> SubScores:
    return SubScores(
        trend_score=_trend_score(ind),
        volatility_score=_volatility_score(ind),
        range_score=_range_score(ind),
        liquidity_score=score_liquidity(ind),
        spread_score=score_spread(ind, constraints.total_fee_slippage_pct),
        momentum_score=_momentum_score(ind),
        mean_reversion_score=_mean_reversion_score(ind),
        drawdown_risk_score=_drawdown_risk_score(ind),
        btc_market_risk_score=_btc_market_risk_score(ind),
        exposure_safety_score=score_exposure_safety(portfolio),
        fee_efficiency_score=_fee_efficiency_score(ind, constraints),
        data_quality_score=score_data_quality(ind),
    )


def _trend_adjusted(trend: int, regime_down: bool) -> int:
    if regime_down:
        return invert_score(trend)
    return trend


def compute_param_score(sub: SubScores, regime_down: bool = False) -> int:
    trend_adj = _trend_adjusted(sub.trend_score, regime_down)
    raw = (
        C.W_RANGE * sub.range_score
        + C.W_VOLATILITY * sub.volatility_score
        + C.W_LIQUIDITY * sub.liquidity_score
        + C.W_SPREAD * sub.spread_score
        + C.W_MEAN_REVERSION * sub.mean_reversion_score
        + C.W_TREND * trend_adj
        + C.W_MOMENTUM * sub.momentum_score
        + C.W_EXPOSURE_SAFETY * sub.exposure_safety_score
        + C.W_FEE_EFFICIENCY * sub.fee_efficiency_score
        + C.W_BTC_MARKET_RISK * sub.btc_market_risk_score
        + C.W_DATA_QUALITY * sub.data_quality_score
    )
    if sub.drawdown_risk_score < C.DRAWDOWN_RISK_PENALTY:
        raw -= C.PENALTY_DRAWDOWN_LT_30
    if sub.btc_market_risk_score < C.BTC_RISK_PENALTY:
        raw -= C.PENALTY_BTC_RISK_LT_25
    if sub.exposure_safety_score < C.EXPOSURE_SAFETY_PENALTY:
        raw -= C.PENALTY_EXPOSURE_LT_35
    if sub.data_quality_score < 50:
        raw -= C.PENALTY_DATA_LT_50
    return int(clamp(raw, 0, 100))


def score_bucket(param_score: int) -> str:
    from app.services.dynamic_param_score.models import ScoreBucket

    if param_score <= C.BUCKET_BLOCKED_MAX:
        return ScoreBucket.BLOCKED.value
    if param_score <= C.BUCKET_EXTREME_RISK_MAX:
        return ScoreBucket.EXTREME_RISK.value
    if param_score <= C.BUCKET_VERY_DEFENSIVE_MAX:
        return ScoreBucket.VERY_DEFENSIVE.value
    if param_score <= C.BUCKET_DEFENSIVE_LOW_MAX:
        return ScoreBucket.DEFENSIVE_LOW.value
    if param_score <= C.BUCKET_DEFENSIVE_HIGH_MAX:
        return ScoreBucket.DEFENSIVE_HIGH.value
    if param_score <= C.BUCKET_BALANCED_LOW_MAX:
        return ScoreBucket.BALANCED_LOW.value
    if param_score <= C.BUCKET_BALANCED_HIGH_MAX:
        return ScoreBucket.BALANCED_HIGH.value
    if param_score <= C.BUCKET_ACTIVE_LOW_MAX:
        return ScoreBucket.ACTIVE_LOW.value
    if param_score <= C.BUCKET_ACTIVE_HIGH_MAX:
        return ScoreBucket.ACTIVE_HIGH.value
    return ScoreBucket.HIGH_CONFIDENCE.value


def compute_confidence_score(
    sub: SubScores,
    param_score: int,
    *,
    warnings: Optional[List[str]] = None,
    gates: Optional[List] = None,
    feasibility_meta: Optional[dict] = None,
    profile_name: Optional[str] = None,
    final_action: Optional[str] = None,
    min_notional: float = C.DEFAULT_MIN_NOTIONAL_USDT,
) -> int:
    fm = feasibility_meta or {}
    mn_feas = 90
    buy_reason = str(fm.get("adjusted_buy_grid_count_reason") or "")
    if fm.get("min_notional_adjusted"):
        mn_feas = 55
    elif fm.get("min_notional_feasible") is False and "headroom" in buy_reason:
        mn_feas = 65
    elif fm.get("min_notional_feasible") is False:
        mn_feas = 25

    parts = [
        sub.data_quality_score,
        sub.liquidity_score,
        sub.spread_score,
        sub.fee_efficiency_score,
        sub.exposure_safety_score,
        mn_feas,
    ]
    base = sum(parts) / len(parts)

    if warnings:
        base -= min(20, 5 * len(warnings))
    if gates:
        adj = sum(1 for g in gates if not getattr(g, "passed", True))
        base -= min(20, 5 * adj)
    if 60 <= param_score < 70 and final_action in ("ACTIVE_GRID", "BALANCED_GRID"):
        base -= 10
    if final_action == "ACTIVE_GRID" and param_score < 75:
        base -= 10
    if profile_name == "ACTIVE_RANGE_GRID_PROFILE" and param_score < 75:
        base -= 10
    if sub.fee_efficiency_score < 30:
        base -= 8
    elif sub.fee_efficiency_score < 50:
        base -= 5
    if fm.get("min_notional_adjusted"):
        base -= 10
    headroom = float(fm.get("exposure_headroom_quote_usdt") or 999)
    ladder = float(fm.get("buy_ladder_budget_usdt") or headroom)
    if ladder < float(min_notional) * 2 and headroom < float(min_notional) * 4:
        base -= 15
    if "reduced_to" in buy_reason:
        base -= 8
    if fm.get("exposure_gate_adjusted"):
        base -= 5

    return int(clamp(base, 0, 100))


def compute_risk_score(sub: SubScores) -> int:
    """Higher = riskier environment."""
    danger = (
        invert_score(sub.drawdown_risk_score) * 0.3
        + invert_score(sub.btc_market_risk_score) * 0.2
        + invert_score(sub.exposure_safety_score) * 0.25
        + invert_score(sub.volatility_score) * 0.15
        + invert_score(sub.spread_score) * 0.1
    )
    return int(clamp(danger, 0, 100))
