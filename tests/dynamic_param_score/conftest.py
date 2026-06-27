"""Shared test fixtures for Dynamic Param Score Engine."""

from __future__ import annotations

import math
import os
from typing import List

import pytest

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BtcReferenceData,
    BotContext,
    Candle,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V3
from app.services.dynamic_param_score.param_pool.sqlite_store import DEFAULT_V3_SQLITE_PATH
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache, load_indexed_pool

_V3_POOL_SNAPSHOT: list | None = None
_V3_INDEXED_SNAPSHOT = None
FAST_TEST_POOL_SIZE = int(os.environ.get("DPS_TEST_POOL_SIZE", "6000"))


@pytest.fixture(scope="session", autouse=True)
def _warm_param_pool_cache():
    """Preload param pool once per session — fast 6k subset by default (not full 200k)."""
    global _V3_POOL_SNAPSHOT, _V3_INDEXED_SNAPSHOT
    from app.services.dynamic_param_score.param_pool import versioning
    from app.services.dynamic_param_score.param_generator.param_library_builder import (
        FAST_TEST_POOL_TARGET,
        POOL_TARGET_V3,
        build_dps_v2_pool,
    )
    from app.services.dynamic_param_score.param_generator.pool_disk_cache import try_load_v3_pool_from_disk

    os.environ.setdefault("PARAM_POOL_MODE", "programmatic")
    os.environ.setdefault("PARAM_POOL_VERSION", POOL_VERSION_V3)
    clear_pool_cache()

    use_disk_full = os.environ.get("DPS_FULL_POOL") == "1"
    use_sqlite = os.environ.get("DPS_USE_SQLITE") == "1" and DEFAULT_V3_SQLITE_PATH.exists()

    if use_disk_full:
        _V3_POOL_SNAPSHOT = try_load_v3_pool_from_disk() or build_dps_v2_pool(
            total_target=POOL_TARGET_V3,
            migrate_legacy=True,
        )
    elif use_sqlite:
        os.environ["PARAM_POOL_MODE"] = "auto"
        _V3_POOL_SNAPSHOT = versioning.load_version_templates(POOL_VERSION_V3)
    else:
        # Fast default: ~6k templates — never load 1GB+ SQLite during pytest
        _V3_POOL_SNAPSHOT = build_dps_v2_pool(
            migrate_legacy=False,
            total_target=FAST_TEST_POOL_SIZE,
            new_target=max(500, FAST_TEST_POOL_SIZE - 80),
        )

    versioning._CACHED_POOLS[POOL_VERSION_V3] = _V3_POOL_SNAPSHOT  # noqa: SLF001
    _V3_INDEXED_SNAPSHOT = load_indexed_pool(POOL_VERSION_V3)
    versioning._CACHED_INDEXED_POOLS[POOL_VERSION_V3] = _V3_INDEXED_SNAPSHOT  # noqa: SLF001
    yield _V3_POOL_SNAPSHOT
    clear_pool_cache()
    _V3_POOL_SNAPSHOT = None
    _V3_INDEXED_SNAPSHOT = None


@pytest.fixture(scope="session")
def v3_pool(_warm_param_pool_cache):
    """Shared session pool (fast ~6k default)."""
    return _warm_param_pool_cache


@pytest.fixture(autouse=True)
def _restore_v3_pool_after_test():
    """Tests call clear_pool_cache(); restore session snapshots without rebuilding indexes."""
    yield
    if _V3_POOL_SNAPSHOT is None:
        return
    from app.services.dynamic_param_score.param_pool import versioning

    versioning._CACHED_POOLS[POOL_VERSION_V3] = _V3_POOL_SNAPSHOT  # noqa: SLF001
    if _V3_INDEXED_SNAPSHOT is not None:
        versioning._CACHED_INDEXED_POOLS[POOL_VERSION_V3] = _V3_INDEXED_SNAPSHOT  # noqa: SLF001


def mk_candles(
    closes: List[float],
    interval_ms: int = 300_000,
    vol: float = 1000.0,
) -> List[Candle]:
    out = []
    for i, c in enumerate(closes):
        rng = c * 0.004
        out.append(
            Candle(
                t=i * interval_ms,
                o=c,
                h=c + rng,
                l=c - rng,
                c=c,
                v=vol,
            )
        )
    return out


def ranging(n: int = 200, base: float = 100.0, amp: float = 0.003) -> List[Candle]:
    return mk_candles([base * (1 + amp * math.sin(i / 3.0)) for i in range(n)])


def uptrend(n: int = 200, base: float = 100.0, slope: float = 0.003) -> List[Candle]:
    return mk_candles([base * (1 + slope * i) for i in range(n)])


def downtrend(n: int = 200, base: float = 100.0, slope: float = 0.004) -> List[Candle]:
    return mk_candles([base * (1 - slope * i) for i in range(n)])


def dump_series(n: int = 200, base: float = 100.0) -> List[Candle]:
    """Steep synthetic dump with elevated volume."""
    return mk_candles([base * math.exp(-0.015 * i) for i in range(n)], vol=8000.0)


def high_vol_range(n: int = 200, base: float = 100.0) -> List[Candle]:
    return mk_candles([base * (1 + 0.015 * math.sin(i / 2.0)) for i in range(n)], vol=3000.0)


def market_bundle(
    symbol: str = "BTCUSDT",
    candles_5m: List[Candle] | None = None,
    candles_1h: List[Candle] | None = None,
    price: float = 100.0,
    quote_vol: float = 50_000_000.0,
    btc: BtcReferenceData | None = None,
) -> MarketDataBundle:
    c5 = candles_5m or ranging()
    c1h = candles_1h or ranging(168, price)
    return MarketDataBundle(
        symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        candles_5m=c5,
        candles_15m=c5[::3][:100] if len(c5) > 30 else c5,
        candles_1h=c1h,
        ticker_price=price if price else c5[-1].c,
        volume_24h=quote_vol / price if price else 1e6,
        quote_volume_24h=quote_vol,
        market_timestamp=c5[-1].t,
        btc_reference_data=btc,
        orderbook_top={"bid": price * 0.9998, "ask": price * 1.0002},
    )


def portfolio(
    budget: float = 1000.0,
    exposure: float = 0.0,
    open_buys: int = 0,
) -> PortfolioState:
    base_val = budget * exposure
    quote_val = budget * (1 - exposure)
    return PortfolioState(
        base_balance=base_val / 100.0 if exposure else 0,
        quote_balance=quote_val,
        base_value_usdt=base_val,
        quote_value_usdt=quote_val,
        total_equity_usdt=budget,
        current_base_exposure_frac=exposure,
        open_orders_count=open_buys,
        open_buy_orders_count=open_buys,
        open_sell_orders_count=0,
    )


def constraints(min_notional: float = DEFAULT_MIN_NOTIONAL_USDT) -> ExchangeConstraints:
    return ExchangeConstraints(
        min_notional=min_notional,
        step_size=0.0001,
        tick_size=0.01,
        min_qty=0.0001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )


def ctx(run_source: str = "param_assistant", budget: float = 1000.0) -> BotContext:
    from app.services.dynamic_param_score.data_collector import build_bot_context

    return build_bot_context(
        run_source=run_source,
        budget_usdt=budget,
        portfolio=portfolio(budget),
        allow_live=True,
        allow_no_trade=True,
    )
