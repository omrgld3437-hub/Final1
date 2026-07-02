"""Regression: SOLUSDT 50 USDT — BALANCED_GRID/WAIT, exposure-safe grids."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.feasibility import allowed_buy_quote_usdt
from app.services.dynamic_param_score.models import (
    FinalAction,
    MarketDataBundle,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.profiles import select_profile_family
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles, portfolio
from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state


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


def test_sol_50_usdt_balanced_range():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        pf,
        constraints(),
        ctx("param_assistant", 50),
    )
    assert d.final_action != FinalAction.ACTIVE_GRID.value
    assert d.final_action in (
        FinalAction.WAIT.value,
        FinalAction.NO_TRADE.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.SELL_MANAGEMENT_ONLY.value,
    )
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert d.deployable
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count >= 2
    elif d.deployable and d.params:
        assert d.params.buy_grid_count >= 1
        assert d.params.sell_grid_count >= 1
    assert d.confidence_score <= 60
    if d.params:
        assert d.params.buy_grid_count <= 3
        assert d.params.sell_grid_count <= 3
        min_n = constraints().min_notional
        ladder = float(d.telemetry.get("buy_ladder_budget_usdt") or 0)
        if d.params.buy_grid_count > 0 and ladder > 0:
            for w in d.params.buy_qty_distribution:
                assert ladder * w >= min_n - 0.01
        sell_budget = 50.0 * d.params.base_alloc_frac
        if d.params.sell_grid_count > 0 and sell_budget > 0:
            for w in d.params.sell_qty_distribution:
                assert sell_budget * w >= min_n - 0.01
        worst = float(d.telemetry.get("worst_case_base_exposure_frac") or 0)
        cap = float(d.params.max_base_exposure_frac)
        assert worst <= cap + 0.02
        headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
        if headroom < min_n:
            assert d.params.buy_grid_count == 0


def test_sol_50_usdt_not_active_grid_at_score_band():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(50),
        constraints(),
        ctx("param_assistant", 50),
    )
    if d.param_score < 70:
        assert d.final_action != FinalAction.ACTIVE_GRID.value


def test_sol_50_usdt_worst_case_exposure_within_cap():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(50),
        constraints(),
        ctx("param_assistant", 50),
    )
    if not d.deployable or not d.params:
        return
    worst = float(d.telemetry.get("worst_case_base_exposure_frac") or 0)
    cap = float(d.params.max_base_exposure_frac)
    assert worst <= cap + 0.02


def test_sol_50_usdt_buy_ladder_below_full_quote():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(50),
        constraints(),
        ctx("param_assistant", 50),
    )
    if not d.deployable or not d.params:
        return
    ladder = float(d.telemetry.get("buy_ladder_budget_usdt") or 0)
    quote_pool = 50.0 * float(d.params.quote_alloc_frac)
    assert ladder <= quote_pool + 0.01


def test_active_grid_requires_subscores():
    sub = SubScores(
        range_score=80,
        liquidity_score=80,
        spread_score=80,
        fee_efficiency_score=20,
        exposure_safety_score=80,
        data_quality_score=80,
    )
    name, action = select_profile_family(
        RegimeTag.BALANCED_RANGE,
        RiskState.NORMAL.value,
        75,
        sub,
        budget_usdt=500,
        min_notional=5,
    )
    assert action != FinalAction.ACTIVE_GRID.value
    assert name != "ACTIVE_RANGE_GRID_PROFILE"


def test_execution_exposure_cap():
    pf = PortfolioState(
        base_balance=0.5,
        quote_balance=50.0,
        base_value_usdt=50.0,
        quote_value_usdt=50.0,
        total_equity_usdt=100.0,
        current_base_exposure_frac=0.5,
        open_orders_count=0,
        open_buy_orders_count=0,
        open_sell_orders_count=0,
    )
    allowed = allowed_buy_quote_usdt(pf, max_base_exposure_frac=0.54, current_price=100.0)
    assert allowed == 4.0
    assert allowed < 5.0


def test_sol_50_adapter_sell_management_or_bilateral():
    from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result

    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        pf,
        constraints(),
        ctx("param_assistant", 50),
    )
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert r["ok"] is True
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert r["sell_management_only"] is True
        assert r["apply_policy"] == "allow"
        assert len(r["ui_config"]["up"]["grids"]) >= 2
        assert len(r["ui_config"]["down"]["grids"]) == 0
    elif d.deployable and r["ui_config"]:
        assert len(r["ui_config"]["up"]["grids"]) >= 1
        assert len(r["ui_config"]["down"]["grids"]) >= 1
    elif d.params and d.params.buy_grid_count == 0:
        assert r["ui_config"] is None
        assert not d.deployable
