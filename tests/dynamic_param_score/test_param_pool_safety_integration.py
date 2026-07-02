"""Param pool + safety gate integration."""

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


def test_pool_selection_logged_in_telemetry():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT", _sol_market(), pf, constraints(), ctx("param_assistant", 50),
    )
    pool = d.telemetry.get("param_pool") or {}
    assert pool.get("pool_version")
    assert "selected_template_key" in pool
    assert "candidate_count" in pool


def test_safety_gate_after_pool_render():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT", _sol_market(), pf, constraints(), ctx("param_assistant", 50),
    )
    pool = d.telemetry.get("param_pool") or {}
    if pool.get("selected_template_key") == "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT":
        assert d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        if d.params:
            assert d.params.buy_grid_count == 0


def test_no_trade_clears_buy_via_safety():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.0, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT", _sol_market(), pf, constraints(), ctx("param_assistant", 50),
    )
    if d.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        assert d.params is None or d.params.buy_grid_count == 0
