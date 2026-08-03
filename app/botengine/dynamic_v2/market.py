"""Data quality, feature and continuous market-state engines."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Mapping, Optional, Sequence

from .config import DynamicV2Config, FormulaCoefficients
from .math_engine import (
    EPSILON,
    atr_percentage,
    clip,
    clip01,
    downside_volatility,
    log_returns,
    mean,
    realized_volatility,
    spread,
    upside_volatility,
    wick_ratios,
)
from .models import (
    Candle,
    ContinuousMarketState,
    DataQualityResult,
    MarketFeatureSnapshot,
    ONE,
    ZERO,
)


D = Decimal


class MarketDataQualityEngine:
    WEIGHTS = {
        "completeness": D("0.22"),
        "freshness": D("0.22"),
        "consistency": D("0.18"),
        "sequence": D("0.14"),
        "outlier": D("0.12"),
        "exchange_connection": D("0.12"),
    }

    def __init__(self, config: DynamicV2Config):
        self.config = config

    def evaluate(
        self,
        *,
        candles_by_timeframe: Mapping[str, Sequence[Candle]],
        expected_counts: Mapping[str, int],
        max_age_seconds: Mapping[str, int],
        ticker_price: Decimal,
        best_bid: Optional[Decimal],
        best_ask: Optional[Decimal],
        exchange_connected: bool,
        now: Optional[datetime] = None,
    ) -> DataQualityResult:
        now = now or datetime.now(timezone.utc)
        completeness_parts = []
        freshness_parts = []
        ordered = True
        consistent = ticker_price > ZERO
        outlier_scores = []
        reasons = []

        for timeframe, expected in expected_counts.items():
            candles = list(candles_by_timeframe.get(timeframe) or [])
            completeness_parts.append(
                clip01(D(len(candles)) / D(max(1, int(expected))))
            )
            if candles:
                latest = candles[-1].opened_at
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                age = max(D("0"), D(str((now - latest).total_seconds())))
                allowed = D(max(1, int(max_age_seconds.get(timeframe, 3600))))
                freshness_parts.append(clip01(ONE - age / allowed))
                timestamps = [c.opened_at for c in candles]
                ordered = ordered and all(
                    left < right for left, right in zip(timestamps, timestamps[1:])
                )
                for candle in candles:
                    consistent = consistent and (
                        candle.high >= max(candle.open, candle.close)
                        and candle.low <= min(candle.open, candle.close)
                        and candle.low > ZERO
                    )
                returns = log_returns(candles)
                if returns:
                    extreme = max(abs(item) for item in returns)
                    outlier_scores.append(
                        clip01(ONE - max(ZERO, extreme - D("0.10")) / D("0.40"))
                    )
            else:
                freshness_parts.append(ZERO)
                reasons.append(f"MISSING_{timeframe}")

        if best_bid is not None and best_ask is not None:
            consistent = consistent and best_bid > ZERO and best_ask > best_bid
            if ticker_price > ZERO:
                midpoint = (best_bid + best_ask) / D("2")
                consistent = consistent and (
                    abs(midpoint - ticker_price) / ticker_price <= D("0.05")
                )
        else:
            consistent = False
            reasons.append("ORDER_BOOK_MISSING")

        components = {
            "completeness": mean(completeness_parts),
            "freshness": mean(freshness_parts),
            "consistency": ONE if consistent else ZERO,
            "sequence": ONE if ordered else ZERO,
            "outlier": mean(outlier_scores) if outlier_scores else ZERO,
            "exchange_connection": ONE if exchange_connected else ZERO,
        }
        product = ONE
        for name, weight in self.WEIGHTS.items():
            product *= max(components[name], EPSILON) ** weight
        score = clip01(product)
        if score < self.config.data_quality_limited:
            reasons.append("DATA_QUALITY_BLOCKED")
        elif score < self.config.data_quality_full:
            reasons.append("DATA_QUALITY_LIMITED")
        return DataQualityResult(
            completeness=components["completeness"],
            freshness=components["freshness"],
            consistency=components["consistency"],
            sequence=components["sequence"],
            outlier=components["outlier"],
            exchange_connection=components["exchange_connection"],
            score=score,
            safe_for_full_update=score >= self.config.data_quality_full,
            safe_for_reducing_only=(
                self.config.data_quality_limited
                <= score
                < self.config.data_quality_full
            ),
            reasons=tuple(reasons),
        )


class MarketFeatureEngine:
    """Calculates primitive Decimal features.

    Percentile/history inputs are supplied by the collector/repository so this
    module stays deterministic and does not silently invent missing history.
    """

    def calculate_timeframe_volatility(
        self, candles: Sequence[Candle]
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        returns = log_returns(candles)
        return (
            atr_percentage(candles),
            realized_volatility(returns),
            downside_volatility(returns),
            upside_volatility(returns),
        )

    def wick_noise(self, candles: Sequence[Candle]) -> Decimal:
        if not candles:
            return ZERO
        ratios = [mean(wick_ratios(candle)) for candle in candles]
        return clip01(mean(ratios))

    def spread_values(
        self, best_bid: Decimal, best_ask: Decimal
    ) -> tuple[Decimal, Decimal, Decimal]:
        return spread(best_bid, best_ask)


class MarketStateEngine:
    def __init__(self, coefficients: FormulaCoefficients):
        self.coefficients = coefficients

    @staticmethod
    def _weighted(
        values: Mapping[str, Decimal], weights: Mapping[str, Decimal]
    ) -> Decimal:
        denominator = sum(
            (weights.get(key, ZERO) for key in values), ZERO
        )
        if denominator <= ZERO:
            return ZERO
        return sum(
            (values[key] * weights.get(key, ZERO) for key in values), ZERO
        ) / denominator

    def build(
        self,
        features: MarketFeatureSnapshot,
        *,
        previous_coin_risk: Optional[Decimal] = None,
        regime_stability: Decimal = ONE,
        change_intensity: Decimal = ZERO,
    ) -> ContinuousMarketState:
        raw_weights: Dict[str, Decimal] = {}
        for timeframe, base_weight in self.coefficients.trend_timeframe_weights.items():
            if timeframe not in features.trend_by_timeframe:
                continue
            raw_weights[timeframe] = (
                base_weight
                * features.trend_confidence_by_timeframe.get(timeframe, ZERO)
                * features.trend_stability_by_timeframe.get(timeframe, ZERO)
                * features.closure_factor_by_timeframe.get(timeframe, ZERO)
            )
        trend = clip(
            self._weighted(features.trend_by_timeframe, raw_weights), D("-1"), ONE
        )
        volatility = clip01(
            self._weighted(
                features.volatility_by_timeframe,
                self.coefficients.volatility_timeframe_weights,
            )
        )
        down_vol = clip01(
            self._weighted(
                features.downside_volatility_by_timeframe,
                self.coefficients.volatility_timeframe_weights,
            )
        )
        up_vol = clip01(
            self._weighted(
                features.upside_volatility_by_timeframe,
                self.coefficients.volatility_timeframe_weights,
            )
        )
        range_strength = clip01(
            D("0.40") * (ONE - abs(trend))
            + D("0.25") * features.mean_reversion_score
            + D("0.20") * features.failed_breakout_score
            + D("0.15") * features.bounded_price_score
        )
        liquidity = clip01(
            D("0.30") * features.spread_pct
            + D("0.30") * features.slippage_pct
            + D("0.25") * (ONE - features.depth_percentile)
            + D("0.15") * features.liquidity_instability
        )
        new_coin_risk = clip01(
            D("0.25") * features.long_term_volatility_percentile
            + D("0.20") * features.jump_frequency_percentile
            + D("0.15") * features.wick_frequency_percentile
            + D("0.15") * features.beta_percentile
            + D("0.10") * features.spread_instability_percentile
            + D("0.10") * features.slippage_pct
            + D("0.05") * features.listing_age_penalty
        )
        coin_risk = (
            D("0.90") * previous_coin_risk + D("0.10") * new_coin_risk
            if previous_coin_risk is not None
            else new_coin_risk
        )
        spread_risk = clip01(features.spread_pct)
        micro_noise = clip01(
            D("0.35")
            * features.volatility_by_timeframe.get("15M", volatility)
            + D("0.25") * spread_risk
            + D("0.20") * features.wick_noise_score
            + D("0.20") * features.trade_reversal_frequency
        )
        return ContinuousMarketState(
            trend_score=trend,
            upward_trend_strength=max(trend, ZERO),
            downward_trend_strength=max(-trend, ZERO),
            range_strength=range_strength,
            volatility_score=volatility,
            downside_volatility_score=down_vol,
            upside_volatility_score=up_vol,
            liquidity_risk=liquidity,
            coin_risk=clip01(coin_risk),
            negative_jump_risk=clip01(features.negative_jump_risk),
            positive_jump_risk=clip01(features.positive_jump_risk),
            micro_noise=micro_noise,
            spread_risk=spread_risk,
            support_strength=clip01(features.support_strength),
            resistance_strength=clip01(features.resistance_strength),
            data_quality=clip01(features.data_quality),
            regime_stability=clip01(regime_stability),
            change_intensity=clip01(change_intensity),
        )
