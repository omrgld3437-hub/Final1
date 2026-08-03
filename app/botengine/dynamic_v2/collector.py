"""Spot-only market/account data collector and feature adapter."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .math_engine import (
    EPSILON,
    atr_percentage,
    clip,
    clip01,
    downside_volatility,
    log_returns,
    mean,
    percentile_rank,
    realized_volatility,
    tanh_decimal,
    upside_volatility,
)
from .models import Candle, MarketFeatureSnapshot, ONE, ZERO, decimal_value


D = Decimal


TIMEFRAME_LIMITS = {
    "1M": ("1M", 24),
    "1W": ("1w", 104),
    "1D": ("1d", 180),
    "4H": ("4h", 240),
    "1H": ("1h", 360),
    "15M": ("15m", 384),
}


@dataclass(frozen=True)
class CollectedMarketData:
    symbol: str
    collected_at: datetime
    candles_by_timeframe: Mapping[str, Sequence[Candle]]
    best_bid: Decimal
    best_ask: Decimal
    bids: Sequence[tuple[Decimal, Decimal]]
    asks: Sequence[tuple[Decimal, Decimal]]
    trades: Sequence[Mapping[str, Any]]
    exchange_connected: bool
    # DİKKAT — birim: bunlar ORAN'dır, yüzde puanı değil. %0.05 spread = 0.0005.
    # Yüzde puanına çevrim service.py'de yapılır (``* 100``); kısıt katmanı
    # (constraints.py) yüzde puanı bekler. Bu ayrım karışırsa grid aralıkları
    # 100 kat yanlış hesaplanır.
    raw_spread_pct: Decimal
    estimated_buy_slippage_pct: Decimal
    estimated_sell_slippage_pct: Decimal

    @property
    def mid_price(self) -> Decimal:
        return (self.best_bid + self.best_ask) / D("2")


class MarketDataCollector:
    """Collects only Binance spot endpoints and UTC timestamps."""

    CACHE_TTL_SECONDS = 60.0

    def __init__(self) -> None:
        self._cache: Dict[str, tuple[float, CollectedMarketData]] = {}
        self._inflight: Dict[str, asyncio.Task] = {}
        self._cache_lock = asyncio.Lock()

    async def collect(
        self,
        symbol: str,
        *,
        standard_notional: Decimal = D("100"),
    ) -> CollectedMarketData:
        symbol = str(symbol or "").upper()
        now = time.monotonic()
        cached = self._cache.get(symbol)
        if cached and now - cached[0] < self.CACHE_TTL_SECONDS:
            return cached[1]

        creator = False
        async with self._cache_lock:
            cached = self._cache.get(symbol)
            if (
                cached
                and time.monotonic() - cached[0] < self.CACHE_TTL_SECONDS
            ):
                return cached[1]
            task = self._inflight.get(symbol)
            if task is None:
                task = asyncio.create_task(
                    self._collect_uncached(
                        symbol, standard_notional=standard_notional
                    )
                )
                self._inflight[symbol] = task
                creator = True
        try:
            result = await task
            self._cache[symbol] = (time.monotonic(), result)
            return result
        finally:
            if creator:
                async with self._cache_lock:
                    if self._inflight.get(symbol) is task:
                        del self._inflight[symbol]

    async def _collect_uncached(
        self,
        symbol: str,
        *,
        standard_notional: Decimal,
    ) -> CollectedMarketData:
        from app.services.dynamic_param_score.data_collector import _fetch_klines
        from app.services.binance_rest_log import rest_source
        from app.services.binance_spot import public_get_json

        candle_jobs = [
            _fetch_klines(symbol, interval, limit)
            for interval, limit in TIMEFRAME_LIMITS.values()
        ]

        async def depth() -> Any:
            with rest_source("dynamic_mode_v2.depth"):
                return await public_get_json(
                    "/api/v3/depth",
                    {"symbol": symbol, "limit": 100},
                    testnet=False,
                )

        async def trades() -> Any:
            with rest_source("dynamic_mode_v2.trades"):
                return await public_get_json(
                    "/api/v3/trades",
                    {"symbol": symbol, "limit": 500},
                    testnet=False,
                )

        results = await asyncio.gather(
            *candle_jobs, depth(), trades(), return_exceptions=True
        )
        candles_by_timeframe: Dict[str, Sequence[Candle]] = {}
        exchange_connected = True
        for key, raw in zip(TIMEFRAME_LIMITS, results[: len(TIMEFRAME_LIMITS)]):
            if isinstance(raw, Exception):
                raw = []
                exchange_connected = False
            converted = []
            for candle in raw or []:
                converted.append(
                    Candle(
                        opened_at=datetime.fromtimestamp(
                            int(candle.t) / 1000, tz=timezone.utc
                        ),
                        open=decimal_value(candle.o),
                        high=decimal_value(candle.h),
                        low=decimal_value(candle.l),
                        close=decimal_value(candle.c),
                        volume=decimal_value(candle.v),
                    )
                )
            candles_by_timeframe[key] = converted

        raw_depth = results[len(TIMEFRAME_LIMITS)]
        raw_trades = results[len(TIMEFRAME_LIMITS) + 1]
        if isinstance(raw_depth, Exception) or not isinstance(raw_depth, Mapping):
            raw_depth = {}
            exchange_connected = False
        if isinstance(raw_trades, Exception) or not isinstance(raw_trades, list):
            raw_trades = []
            exchange_connected = False
        bids = self._levels(raw_depth.get("bids"))
        asks = self._levels(raw_depth.get("asks"))
        best_bid = bids[0][0] if bids else ZERO
        best_ask = asks[0][0] if asks else ZERO
        raw_spread = (
            (best_ask - best_bid) / ((best_ask + best_bid) / D("2"))
            if best_bid > ZERO and best_ask > best_bid
            else ONE
        )
        mid = (
            (best_bid + best_ask) / D("2")
            if best_bid > ZERO and best_ask > best_bid
            else ZERO
        )
        buy_slippage = self._slippage(
            asks, standard_notional, mid, quote_notional=True
        )
        sell_slippage = self._slippage(
            bids, standard_notional, mid, quote_notional=True
        )
        return CollectedMarketData(
            symbol=symbol,
            collected_at=datetime.now(timezone.utc),
            candles_by_timeframe=candles_by_timeframe,
            best_bid=best_bid,
            best_ask=best_ask,
            bids=bids,
            asks=asks,
            trades=raw_trades,
            exchange_connected=exchange_connected,
            raw_spread_pct=raw_spread,
            estimated_buy_slippage_pct=buy_slippage,
            estimated_sell_slippage_pct=sell_slippage,
        )

    @staticmethod
    def _levels(raw: Any) -> List[tuple[Decimal, Decimal]]:
        result = []
        for row in raw or []:
            try:
                price, quantity = decimal_value(row[0]), decimal_value(row[1])
            except (IndexError, TypeError, ValueError):
                continue
            if price > ZERO and quantity > ZERO:
                result.append((price, quantity))
        return result

    @staticmethod
    def _slippage(
        levels: Sequence[tuple[Decimal, Decimal]],
        notional: Decimal,
        mid: Decimal,
        *,
        quote_notional: bool,
    ) -> Decimal:
        if not levels or notional <= ZERO or mid <= ZERO:
            return ONE
        remaining = notional
        base_filled = ZERO
        quote_filled = ZERO
        for price, quantity in levels:
            level_quote = price * quantity
            take_quote = min(remaining, level_quote) if quote_notional else ZERO
            if take_quote <= ZERO:
                break
            base = take_quote / price
            base_filled += base
            quote_filled += take_quote
            remaining -= take_quote
            if remaining <= ZERO:
                break
        if remaining > ZERO or base_filled <= ZERO:
            return ONE
        average = quote_filled / base_filled
        return abs(average - mid) / mid


class FeatureSnapshotBuilder:
    """Transforms collected spot data into normalized continuous inputs."""

    @staticmethod
    def _trend(candles: Sequence[Candle]) -> tuple[Decimal, Decimal, Decimal]:
        if len(candles) < 20:
            return ZERO, ZERO, ZERO
        closes = [c.close for c in candles]
        returns = log_returns(candles)
        vol = realized_volatility(returns[-30:])
        window = min(30, len(closes) - 1)
        slope = (closes[-1] - closes[-window - 1]) / (
            closes[-window - 1] * D(window) + EPSILON
        )
        short = mean(closes[-10:])
        long = mean(closes[-30:])
        separation = (short - long) / (closes[-1] + EPSILON)
        direction = ONE if slope >= ZERO else D("-1")
        directional_adx = direction * clip01(
            abs(slope) / (vol + EPSILON)
        )
        higher = sum(
            1
            for left, right in zip(closes[-10:], closes[-9:])
            if right > left
        )
        price_structure = D(higher) / D("9") * D("2") - ONE
        previous = candles[-21:-1]
        prior_high = max(c.high for c in previous)
        prior_low = min(c.low for c in previous)
        breakout = (
            ONE
            if closes[-1] > prior_high
            else D("-1")
            if closes[-1] < prior_low
            else ZERO
        )
        normalized_slope = clip(
            slope / (vol + EPSILON), D("-3"), D("3")
        )
        normalized_separation = clip(
            separation / (vol + EPSILON), D("-3"), D("3")
        )
        trend = tanh_decimal(
            D("0.30") * normalized_slope
            + D("0.25") * normalized_separation
            + D("0.20") * directional_adx
            + D("0.15") * price_structure
            + D("0.10") * breakout
        )
        confidence = clip01(D(len(candles)) / D("100"))
        stability = clip01(ONE - vol * D("10"))
        return trend, confidence, stability

    @staticmethod
    def _volatility_percentiles(
        candles: Sequence[Candle],
    ) -> tuple[Decimal, Decimal, Decimal]:
        if len(candles) < 20:
            return ZERO, ZERO, ZERO
        returns = log_returns(candles)
        window = min(20, len(returns))
        current = realized_volatility(returns[-window:])
        current_down = downside_volatility(returns[-window:])
        current_up = upside_volatility(returns[-window:])
        history = []
        down_history = []
        up_history = []
        for end in range(window, len(returns) + 1):
            chunk = returns[end - window : end]
            history.append(realized_volatility(chunk))
            down_history.append(downside_volatility(chunk))
            up_history.append(upside_volatility(chunk))
        atr_values = []
        for end in range(15, len(candles) + 1):
            atr_values.append(atr_percentage(candles[:end], 14))
        atr_rank = percentile_rank(
            atr_percentage(candles, 14), atr_values
        )
        realized_rank = percentile_rank(current, history)
        jump_frequency = mean(
            [
                ONE if abs(value) > D("3") * max(current, EPSILON) else ZERO
                for value in returns[-window:]
            ]
        )
        wick_rank = mean(
            [
                (c.high - c.low) / (c.close + EPSILON)
                for c in candles[-window:]
            ]
        )
        score = clip01(
            D("0.30") * atr_rank
            + D("0.25") * realized_rank
            + D("0.20") * realized_rank
            + D("0.15") * jump_frequency
            + D("0.10") * clip01(wick_rank * D("20"))
        )
        return (
            score,
            percentile_rank(current_down, down_history),
            percentile_rank(current_up, up_history),
        )

    @staticmethod
    def _depth_within(
        levels: Sequence[tuple[Decimal, Decimal]],
        mid: Decimal,
        bps: Decimal,
    ) -> Decimal:
        if mid <= ZERO:
            return ZERO
        width = bps / D("10000")
        return sum(
            (
                price * quantity
                for price, quantity in levels
                if abs(price - mid) / mid <= width
            ),
            ZERO,
        )

    @staticmethod
    def _trade_reversal_frequency(trades: Sequence[Mapping[str, Any]]) -> Decimal:
        directions = []
        for trade in trades:
            maker = trade.get("isBuyerMaker")
            if maker is None:
                continue
            directions.append(-1 if bool(maker) else 1)
        if len(directions) < 2:
            return ZERO
        reversals = sum(
            1 for left, right in zip(directions, directions[1:]) if left != right
        )
        return D(reversals) / D(len(directions) - 1)

    def build(
        self,
        data: CollectedMarketData,
        *,
        data_quality: Decimal,
    ) -> MarketFeatureSnapshot:
        trends: Dict[str, Decimal] = {}
        confidences: Dict[str, Decimal] = {}
        stabilities: Dict[str, Decimal] = {}
        closures: Dict[str, Decimal] = {}
        volatilities: Dict[str, Decimal] = {}
        downs: Dict[str, Decimal] = {}
        ups: Dict[str, Decimal] = {}
        for timeframe, candles in data.candles_by_timeframe.items():
            trend, confidence, stability = self._trend(candles)
            trends[timeframe] = trend
            confidences[timeframe] = confidence
            stabilities[timeframe] = stability
            closures[timeframe] = ONE
            vol, down, up = self._volatility_percentiles(candles)
            volatilities[timeframe] = vol
            downs[timeframe] = down
            ups[timeframe] = up
        candles_1h = data.candles_by_timeframe.get("1H") or []
        candles_15m = data.candles_by_timeframe.get("15M") or []
        returns_1h = log_returns(candles_1h)
        mid = data.mid_price
        bid_depth = self._depth_within(data.bids, mid, D("25"))
        ask_depth = self._depth_within(data.asks, mid, D("25"))
        total_depth = bid_depth + ask_depth
        depth_percentile = clip01(total_depth / (total_depth + D("10000")))
        spread_percentile = clip01(data.raw_spread_pct / D("0.005"))
        slippage = max(
            data.estimated_buy_slippage_pct,
            data.estimated_sell_slippage_pct,
        )
        slippage_percentile = clip01(slippage / D("0.01"))
        recent_high = max((c.high for c in candles_1h[-72:]), default=mid)
        recent_low = min((c.low for c in candles_1h[-72:]), default=mid)
        bounded = (
            clip01(
                ONE
                - abs(mid - (recent_high + recent_low) / D("2"))
                / max(recent_high - recent_low, EPSILON)
            )
            if mid > ZERO
            else ZERO
        )
        sign_changes = (
            sum(
                1
                for left, right in zip(returns_1h, returns_1h[1:])
                if (left > ZERO) != (right > ZERO)
            )
            if len(returns_1h) > 1
            else 0
        )
        mean_reversion = (
            D(sign_changes) / D(len(returns_1h) - 1)
            if len(returns_1h) > 1
            else ZERO
        )
        current_vol = realized_volatility(returns_1h[-24:])
        negative_jump = mean(
            [
                ONE
                if value < -D("3") * max(current_vol, EPSILON)
                else ZERO
                for value in returns_1h[-72:]
            ]
        )
        positive_jump = mean(
            [
                ONE
                if value > D("3") * max(current_vol, EPSILON)
                else ZERO
                for value in returns_1h[-72:]
            ]
        )
        wick_values = [
            (
                (c.high - max(c.open, c.close))
                + (min(c.open, c.close) - c.low)
            )
            / (c.high - c.low + EPSILON)
            for c in candles_15m[-96:]
        ]
        support = (
            clip01(
                ONE - abs(mid - recent_low) / max(mid * D("0.05"), EPSILON)
            )
            if mid > ZERO
            else ZERO
        )
        resistance = (
            clip01(
                ONE - abs(recent_high - mid) / max(mid * D("0.05"), EPSILON)
            )
            if mid > ZERO
            else ZERO
        )
        atr_pct = atr_percentage(candles_1h, 14)
        return MarketFeatureSnapshot(
            trend_by_timeframe=trends,
            trend_confidence_by_timeframe=confidences,
            trend_stability_by_timeframe=stabilities,
            closure_factor_by_timeframe=closures,
            volatility_by_timeframe=volatilities,
            downside_volatility_by_timeframe=downs,
            upside_volatility_by_timeframe=ups,
            atr_pct=atr_pct,
            # Bilinçli: feature katmanındaki ``spread_pct`` 0..1 normalize
            # skordur (yukarıdaki spread_percentile), yüzde değil. Risk
            # ağırlıklarında (market.py) 0..1 bekleniyor. Ham yüzde gerektiğinde
            # ``spread_bps`` veya CollectedMarketData.raw_spread_pct kullanılır.
            spread_pct=spread_percentile,
            spread_bps=data.raw_spread_pct * D("10000"),
            slippage_pct=slippage_percentile,
            depth_percentile=depth_percentile,
            liquidity_instability=clip01(
                abs(bid_depth - ask_depth) / (total_depth + EPSILON)
            ),
            mean_reversion_score=clip01(mean_reversion),
            failed_breakout_score=clip01(mean_reversion * bounded),
            bounded_price_score=bounded,
            negative_jump_risk=clip01(negative_jump),
            positive_jump_risk=clip01(positive_jump),
            wick_noise_score=clip01(mean(wick_values)),
            trade_reversal_frequency=self._trade_reversal_frequency(data.trades),
            long_term_volatility_percentile=volatilities.get("1W", ZERO),
            jump_frequency_percentile=clip01(negative_jump + positive_jump),
            wick_frequency_percentile=clip01(mean(wick_values)),
            beta_percentile=D("0.50"),
            spread_instability_percentile=spread_percentile,
            listing_age_penalty=ZERO,
            support_strength=support,
            resistance_strength=resistance,
            data_quality=data_quality,
        )
