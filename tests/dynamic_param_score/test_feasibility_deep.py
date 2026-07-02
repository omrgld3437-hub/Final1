"""Feasibility math — headroom, min-notional, worst-case exposure."""

from __future__ import annotations

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.feasibility import (
    allowed_buy_quote_usdt,
    buy_ladder_budget_usdt,
    exposure_headroom_quote_usdt,
)
from app.services.dynamic_param_score.models import FinalAction
from tests.dynamic_param_score.factories import (
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)


def test_buy_ladder_not_full_quote():
    from tests.dynamic_param_score.factories import make_bot_params, make_context

    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=100)
    params = make_bot_params(max_base_exposure_frac=0.56)
    max_exp = 0.56
    headroom = exposure_headroom_quote_usdt(pf, max_exp)
    ladder = buy_ladder_budget_usdt(
        pf,
        params,
        make_context(budget_usdt=50, is_first_start=False),
        profile_name="BALANCED_RANGE_GRID_PROFILE",
    )
    assert ladder <= headroom + 0.01
    assert ladder < pf.quote_value_usdt


def test_headroom_below_min_notional_closes_buy():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.47, price=100)
    market = make_market_bundle()
    d = engine.calculate_decision(
        "SOLUSDT",
        market,
        pf,
        make_constraints(min_notional=5),
        make_context(budget_usdt=50),
    )
    headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
    if headroom < 5.0:
        assert d.params is None or d.params.buy_grid_count == 0
        assert d.final_action in (
            FinalAction.WAIT.value,
            FinalAction.NO_TRADE.value,
            FinalAction.BALANCED_GRID.value,
            FinalAction.SELL_MANAGEMENT_ONLY.value,
        )
        if d.params and d.params.sell_grid_count > 0 and d.params.buy_grid_count == 0:
            assert d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value


def test_worst_case_exposure_within_cap():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(),
        make_portfolio_state(budget_usdt=50),
        make_constraints(),
        make_context(budget_usdt=50),
    )
    if not d.params or d.params.buy_grid_count == 0:
        return
    worst = float(d.telemetry.get("worst_case_base_exposure_frac") or 0)
    cap = float(d.params.max_base_exposure_frac)
    assert worst <= cap + 0.02


def test_sell_grid_min_notional():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(),
        make_portfolio_state(budget_usdt=50),
        make_constraints(min_notional=5),
        make_context(budget_usdt=50),
    )
    if not d.deployable or not d.params or d.params.sell_grid_count == 0:
        return
    sell_budget = 50.0 * d.params.base_alloc_frac
    for w in d.params.sell_qty_distribution:
        assert sell_budget * w >= 5.0 - 0.05


def test_buy_grid_min_notional():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(),
        make_portfolio_state(budget_usdt=50),
        make_constraints(min_notional=5),
        make_context(budget_usdt=50),
    )
    if not d.deployable or not d.params or d.params.buy_grid_count == 0:
        return
    ladder = float(d.telemetry.get("buy_ladder_budget_usdt") or 0)
    for w in d.params.buy_qty_distribution:
        assert ladder * w >= 5.0 - 0.05


def test_allowed_buy_quote_matches_execution_cap():
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.54, price=100)
    allowed = allowed_buy_quote_usdt(pf, max_base_exposure_frac=0.56, current_price=100)
    assert allowed <= 1.0 + 0.01
    assert allowed < 5.0
