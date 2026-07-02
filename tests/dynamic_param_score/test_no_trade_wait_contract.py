"""NO_TRADE / WAIT / bilateral action semantics."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result, params_to_grid_config
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from tests.dynamic_param_score.conftest import mk_candles, market_bundle
from tests.dynamic_param_score.conftest import constraints, ctx, portfolio
from tests.dynamic_param_score.test_sol_50_budget import _sol_market


def test_wait_never_has_one_sided_grids():
    engine = DynamicParamScoreEngine()
    dump = mk_candles([100.0 * math.exp(-0.02 * i) for i in range(120)], vol=9000.0)
    m = market_bundle(symbol="TESTUSDT", candles_5m=dump, candles_1h=dump, price=40)
    d = engine.calculate_decision("TESTUSDT", m, portfolio(30), constraints(5), ctx("param_assistant", 30))
    if d.final_action == FinalAction.WAIT.value:
        if d.params:
            assert d.params.buy_grid_count == 0
            assert d.params.sell_grid_count == 0
        assert not d.deployable


def test_bilateral_deployable_requires_both_sides():
    engine = DynamicParamScoreEngine()
    from tests.dynamic_param_score.factories import make_portfolio_state

    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        make_portfolio_state(budget_usdt=500, base_exposure_frac=0.2, price=67.8),
        constraints(),
        ctx("param_assistant", 500),
    )
    if d.final_action in (
        FinalAction.BALANCED_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.ACTIVE_GRID.value,
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    ):
        assert d.params.buy_grid_count >= 1
        assert d.params.sell_grid_count >= 1
        assert d.action_detail.get("bilateral_grid_ok") is True


def test_no_trade_not_deployable():
    engine = DynamicParamScoreEngine()
    from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state, make_context, make_constraints

    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(pattern="dump_risk"),
        make_portfolio_state(budget_usdt=30),
        make_constraints(),
        make_context(budget_usdt=30),
    )
    if d.final_action == FinalAction.NO_TRADE.value:
        assert not d.deployable
        assert d.params is None or (d.params.buy_grid_count == 0 and d.params.sell_grid_count == 0)


def test_rebuy_disabled_when_no_buy_grids():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision("SOLUSDT", _sol_market(), portfolio(50), constraints(), ctx("param_assistant", 50))
    if d.params and d.params.buy_grid_count == 0:
        cfg = params_to_grid_config(d.params)
        assert cfg.get("rebuy_enabled") is False
        assert cfg["profit_reentry_drop_pct"] == 0.0
        assert cfg["profit_reentry_rise_pct"] == 0.0


def test_adapter_apply_policy_deny_on_wait():
    engine = DynamicParamScoreEngine()
    from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state, make_context, make_constraints

    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(pattern="dump_risk"),
        make_portfolio_state(budget_usdt=30),
        make_constraints(),
        make_context(budget_usdt=30),
    )
    r = decision_to_param_assistant_result(d, 30, "SOLUSDT")
    if d.final_action in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.NO_TRADE.value,
    ):
        assert r["apply_policy"] in ("safe_wait", "no_trade")
        assert r["decision"] == "management_decision"
