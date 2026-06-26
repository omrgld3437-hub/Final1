"""Deterministic factories for Dynamic Param Score deep tests."""

from __future__ import annotations

import math
import random
from typing import List, Optional

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BtcReferenceData,
    BotContext,
    Candle,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)

RANDOM_SEED = 42


def make_candles(
    start_price: float = 100.0,
    count: int = 288,
    pattern: str = "balanced_range",
    volatility_pct: float = 0.8,
    volume: float = 1000.0,
    interval_ms: int = 300_000,
) -> List[Candle]:
    rng = random.Random(RANDOM_SEED + hash(pattern) % 10000)
    out: List[Candle] = []
    price = start_price
    for i in range(count):
        if pattern == "balanced_range":
            price = start_price * (1 + (volatility_pct / 100.0) * math.sin(i / 3.0))
        elif pattern == "range_high_vol":
            price = start_price * (1 + (volatility_pct * 2 / 100.0) * math.sin(i / 2.0))
        elif pattern == "trending_down":
            price = start_price * (1 - 0.004 * i)
        elif pattern == "trending_up":
            price = start_price * (1 + 0.003 * i)
        elif pattern == "dump_risk":
            price = start_price * math.exp(-0.018 * i)
        elif pattern == "high_vol_unstable":
            price = start_price * (1 + rng.uniform(-0.03, 0.03))
        elif pattern == "low_liquidity":
            price = start_price * (1 + 0.001 * math.sin(i / 5.0))
        elif pattern == "flat_dead_market":
            price = start_price
        elif pattern == "breakout_risk":
            price = start_price * (1 + 0.002 * i + 0.01 * math.sin(i))
        elif pattern == "bad_data_gaps":
            if i % 17 == 0:
                continue
            price = start_price * (1 + 0.002 * math.sin(i / 4.0))
        elif pattern == "zero_volume":
            price = start_price * (1 + 0.001 * math.sin(i / 3.0))
            volume = 0.0
        elif pattern == "spread_shock":
            price = start_price * (1 + 0.005 * math.sin(i / 2.0))
        else:
            price = start_price * (1 + 0.001 * math.sin(i / 3.0))

        if pattern == "bad_data_gaps" and i % 23 == 0:
            c = 0.0
        else:
            c = max(price, 0.0001)
        rng_pct = c * (volatility_pct / 200.0)
        vol = 0.0 if pattern == "zero_volume" else volume
        out.append(
            Candle(
                t=i * interval_ms,
                o=c,
                h=c + rng_pct,
                l=max(c - rng_pct, 0.0001),
                c=c,
                v=vol,
            )
        )
    return out


def _btc_reference(pattern: str = "normal") -> BtcReferenceData:
    if pattern == "dump":
        return BtcReferenceData(
            return_1h_pct=-5.0,
            return_4h_pct=-8.0,
            return_24h_pct=-15.0,
            crash_velocity=-4.0,
            price=60000.0,
            ema200_1h=65000.0,
        )
    return BtcReferenceData(
        return_1h_pct=0.5,
        return_4h_pct=1.0,
        return_24h_pct=2.0,
        crash_velocity=0.2,
        price=65000.0,
        ema200_1h=64000.0,
    )


def make_market_bundle(
    *,
    symbol: str = "SOLUSDT",
    price: float = 100.0,
    pattern: str = "balanced_range",
    quote_vol: float = 100_000_000.0,
    spread_pct: float = 0.04,
    btc_pattern: str = "normal",
    data_quality: str = "good",
) -> MarketDataBundle:
    if data_quality == "bad":
        candles = make_candles(price, pattern="bad_data_gaps")
    elif data_quality == "zero_vol":
        candles = make_candles(price, pattern="zero_volume")
    else:
        candles = make_candles(price, pattern=pattern)

    candles_1h = make_candles(price, count=168, pattern=pattern)
    half_spread = price * (spread_pct / 100.0) / 2.0
    base = symbol.replace("USDT", "").replace("USD", "") or "SOL"
    return MarketDataBundle(
        symbol=symbol,
        base_asset=base,
        quote_asset="USDT",
        candles_5m=candles,
        candles_15m=candles[::3][:100] if len(candles) > 30 else candles,
        candles_1h=candles_1h,
        ticker_price=price,
        volume_24h=quote_vol / price if price else 1e6,
        quote_volume_24h=quote_vol,
        market_timestamp=candles[-1].t if candles else 0,
        orderbook_top={"bid": price - half_spread, "ask": price + half_spread},
        btc_reference_data=_btc_reference(btc_pattern),
    )


def make_portfolio_state(
    *,
    budget_usdt: float = 50.0,
    base_exposure_frac: float = 0.425,
    open_buy_orders: int = 0,
    open_sell_orders: int = 0,
    unrealized_pnl_pct: float = 0.0,
    average_entry_price: Optional[float] = None,
    price: float = 100.0,
) -> PortfolioState:
    base_val = budget_usdt * base_exposure_frac
    quote_val = budget_usdt * (1.0 - base_exposure_frac)
    return PortfolioState(
        base_balance=base_val / price if price else 0.0,
        quote_balance=quote_val,
        base_value_usdt=base_val,
        quote_value_usdt=quote_val,
        total_equity_usdt=budget_usdt,
        current_base_exposure_frac=base_exposure_frac,
        open_orders_count=open_buy_orders + open_sell_orders,
        open_buy_orders_count=open_buy_orders,
        open_sell_orders_count=open_sell_orders,
        unrealized_pnl_pct=unrealized_pnl_pct,
        average_entry_price=average_entry_price,
    )


def make_constraints(
    *,
    min_notional: float = DEFAULT_MIN_NOTIONAL_USDT,
    maker_fee_pct: float = 0.1,
    taker_fee_pct: float = 0.1,
    estimated_slippage_pct: float = 0.05,
    step_size: float = 0.001,
    tick_size: float = 0.01,
    min_qty: float = 0.001,
) -> ExchangeConstraints:
    return ExchangeConstraints(
        min_notional=min_notional,
        maker_fee_pct=maker_fee_pct,
        taker_fee_pct=taker_fee_pct,
        estimated_slippage_pct=estimated_slippage_pct,
        step_size=step_size,
        tick_size=tick_size,
        min_qty=min_qty,
    )


def make_context(
    *,
    run_source: str = "param_assistant",
    budget_usdt: float = 50.0,
    is_first_start: bool = True,
    previous_round_id: Optional[str] = None,
    current_round_id: Optional[str] = None,
) -> BotContext:
    return BotContext(
        run_source=run_source,
        budget_usdt=budget_usdt,
        is_first_start=is_first_start,
        previous_round_id=previous_round_id,
        current_round_id=current_round_id,
        allow_live=True,
        allow_no_trade=True,
    )


def make_bot_params(**overrides):
    """Minimal valid BotParams for overlay/feasibility tests."""
    from app.services.dynamic_param_score.models import BotParams

    defaults = dict(
        base_alloc_frac=0.45,
        quote_alloc_frac=0.55,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=1.2,
        sell_grid_spacing_pct=1.2,
        buy_qty_distribution=[0.5, 0.5],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.4,
        take_profit_pct=1.0,
        stop_new_buys_below_score=50,
        max_base_exposure_frac=0.56,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.5,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )
    defaults.update(overrides)
    return BotParams(**defaults)
