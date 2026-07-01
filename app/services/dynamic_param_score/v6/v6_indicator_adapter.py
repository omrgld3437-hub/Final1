"""Map V5 indicator snapshot + exchange constraints → V6 input contract."""

from __future__ import annotations

from typing import Optional

from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    MarketDataBundle,
)
from app.services.dynamic_param_score.v6.domain.types import V6InputContract


MAJOR_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"})


def _fragility_class(
    ind: IndicatorSnapshot,
    spread_pct: Optional[float],
    vol_pct: Optional[float],
    *,
    symbol: str = "",
) -> str:
    score = 0.0
    vc = ind.volume_consistency
    if vc is not None:
        if vc < 0.35:
            score += 60
        elif vc < 0.55:
            score += 35
        elif vc < 0.75:
            score += 15
    sp = spread_pct or 0
    if sp > 0.25:
        score += 60
    elif sp > 0.10:
        score += 35
    elif sp > 0.03:
        score += 15
    if vol_pct is not None and vol_pct >= 90:
        score += 55
    elif vol_pct is not None and vol_pct >= 70:
        score += 35
    if ind.zero_volume_ratio and ind.zero_volume_ratio > 0:
        score = max(score, 85)
    if score >= 75:
        cls = "F3"
    elif score >= 50:
        cls = "F2"
    elif score >= 25:
        cls = "F1"
    else:
        cls = "F0"
    sym = symbol.upper()
    if sym in MAJOR_SYMBOLS:
        if cls == "F3" and score < 90:
            cls = "F2"
        if cls in ("F2", "F3") and score < 85:
            cls = "F1"
    return cls


def build_v6_input_contract(
    *,
    symbol: str,
    bot_budget_usdt: float,
    current_price: float,
    ind: IndicatorSnapshot,
    market: MarketDataBundle,
    exchange: ExchangeConstraints,
) -> V6InputContract:
    btc = market.btc_reference_data
    spread = ind.orderbook_spread_pct
    gap_sec = (ind.data_gap_max_ms or 0) / 1000.0
    return V6InputContract(
        symbol=symbol.upper(),
        bot_budget_usdt=float(bot_budget_usdt),
        current_price=float(current_price),
        min_notional=float(exchange.min_notional or 10),
        tick_size=float(exchange.tick_size or 0.01),
        step_size=float(exchange.step_size or 0.00001),
        price_precision=8,
        quantity_precision=8,
        adx_1h=ind.adx_1h,
        rsi_5m=ind.rsi14_5m,
        rsi_1h=ind.rsi14_1h,
        ema20_slope=ind.ema20_slope_5m,
        ema50_slope=ind.ema50_slope_5m,
        ema20_5m=ind.ema20_5m,
        ema50_5m=ind.ema50_5m,
        ema200_1h=ind.ema200_1h,
        price_vs_ema200_pct=ind.price_vs_ema200_pct,
        roc_5m=ind.roc_5m,
        higher_highs=ind.higher_highs,
        lower_lows=ind.lower_lows,
        atr_5m_pct=ind.atr14_pct_5m,
        atr_1h_pct=ind.atr14_pct_1h,
        vol_24h=ind.realized_vol_24h,
        vol_7d=ind.realized_vol_7d,
        volatility_percentile=ind.volatility_percentile,
        bb_width=ind.bb_width_5m,
        bb_position=ind.price_in_bb,
        z_score=ind.z_score_5m,
        mean_reversion_score=ind.mean_reversion_ratio,
        range_stability=ind.range_stability,
        hl_range_pct=ind.high_low_range_pct,
        return_1h_pct=ind.return_1h_pct,
        return_4h_pct=ind.return_4h_pct,
        return_24h_pct=ind.return_24h_pct,
        drawdown_7d_pct=ind.drawdown_7d_pct,
        drawdown_30d_pct=ind.drawdown_30d_pct,
        crash_velocity=ind.crash_velocity,
        red_pressure=ind.consecutive_red_pressure,
        spread_pct=spread,
        volume_24h=ind.quote_volume_24h,
        volume_consistency=ind.volume_consistency,
        volume_spike=ind.volume_spike_abnormality,
        zero_volume_flag=1 if (ind.zero_volume_ratio or 0) > 0 else 0,
        btc_ema200_below=ind.btc_below_ema200 if ind.btc_below_ema200 is not None else None,
        btc_crash_velocity=ind.btc_crash_velocity,
        btc_return_1h_pct=ind.btc_return_1h,
        btc_return_4h_pct=ind.btc_return_4h,
        btc_return_24h_pct=ind.btc_return_24h,
        data_freshness_sec=ind.data_freshness_sec,
        data_gap_sec=gap_sec,
        candles_5m=ind.candle_count_5m or 0,
        candles_15m=ind.candle_count_15m or 0,
        candles_1h=ind.candle_count_1h or 0,
        price_valid=bool(ind.price_valid),
        support_distance_pct=getattr(ind, "support_distance_pct", None),
        resistance_distance_pct=getattr(ind, "resistance_distance_pct", None),
        support_strength_score=getattr(ind, "support_strength_score", None),
        resistance_strength_score=getattr(ind, "resistance_strength_score", None),
        pump_score=float(getattr(ind, "pump_score", 0) or 0),
        dump_score=float(getattr(ind, "dump_score", 0) or 0),
        fake_bounce_score=float(getattr(ind, "fake_bounce_score", 0) or 0),
        fake_breakout_score=float(getattr(ind, "fake_breakout_score", 0) or 0),
        asset_fragility_class=_fragility_class(ind, spread, ind.volatility_percentile, symbol=symbol),
    )
