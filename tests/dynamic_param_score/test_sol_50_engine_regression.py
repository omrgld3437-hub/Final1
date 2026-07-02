"""SOL 50 USDT param pool regression."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction, MarketDataBundle
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles
from tests.dynamic_param_score.factories import make_portfolio_state


def _sol_market():
    c5 = mk_candles(
        [67.8 * (1 + 0.001 * math.sin(i / 3.0)) for i in range(288)],
        interval_ms=300_000,
    )
    return MarketDataBundle(
        symbol="SOLUSDT",
        base_asset="SOL",
        quote_asset="USDT",
        candles_5m=c5,
        candles_15m=c5[::3][:100],
        candles_1h=c5[:168],
        ticker_price=67.8,
        volume_24h=3e6,
        quote_volume_24h=228e6,
        market_timestamp=c5[-1].t,
        orderbook_top={"bid": 67.79, "ask": 67.81},
    )


def test_sol_50_pool_selects_sell_management_when_headroom_low():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT", _sol_market(), pf, constraints(), ctx("param_assistant", 50),
    )
    pool = d.telemetry.get("param_pool") or {}
    headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
    min_n = constraints().min_notional

    if headroom < min_n and pf.base_value_usdt > 0:
        assert pool.get("selected_template_key") in (
            "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT",
            "FALLBACK_SELL_MANAGEMENT",
        ) or d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value

    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert d.params is not None
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count in (2, 3)


def test_sol_50_never_active_grid():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT", _sol_market(), pf, constraints(), ctx("param_assistant", 50),
    )
    assert d.final_action != FinalAction.ACTIVE_GRID.value
