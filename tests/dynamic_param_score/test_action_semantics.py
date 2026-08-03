"""Action semantics regression tests."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles, portfolio
from tests.dynamic_param_score.factories import make_portfolio_state
from tests.dynamic_param_score.sol_market_fixture import _sol_market


def test_sell_management_only_when_buy_blocked_sell_feasible():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        pf,
        constraints(),
        ctx("param_assistant", 50),
    )
    headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
    if headroom < 5.0 and d.params and d.params.sell_grid_count > 0:
        assert d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        assert d.deployable
        assert d.params.buy_grid_count == 0


def test_bilateral_grid_required_for_full_grid_modes():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(500, exposure=0.2),
        constraints(),
        ctx("param_assistant", 500),
    )
    if d.final_action in (
        FinalAction.BALANCED_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.ACTIVE_GRID.value,
    ):
        assert d.params.buy_grid_count >= 1
        assert d.params.sell_grid_count >= 1


def test_wait_has_no_grid():
    engine = DynamicParamScoreEngine()
    dump = mk_candles([100.0 * math.exp(-0.02 * i) for i in range(120)], vol=9000.0)
    from tests.dynamic_param_score.conftest import market_bundle

    m = market_bundle(
        symbol="TESTUSDT",
        candles_5m=dump,
        candles_1h=dump,
        price=40,
        quote_vol=1_000_000,
    )
    d = engine.calculate_decision(
        "TESTUSDT",
        m,
        portfolio(30),
        constraints(min_notional=5),
        ctx("param_assistant", 30),
    )
    if d.final_action == FinalAction.WAIT.value and d.params:
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count == 0
