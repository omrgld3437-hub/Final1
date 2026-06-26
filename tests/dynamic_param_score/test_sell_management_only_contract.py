"""SELL_MANAGEMENT_ONLY runtime mode — deployable sell-only path."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.adapters import (
    decision_to_param_assistant_result,
    params_to_grid_config,
)
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.action_detail import BILATERAL_GRID_ACTIONS, requires_bilateral_grids
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles
from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state
from tests.dynamic_param_score.test_sol_50_budget import _sol_market


def _sol_portfolio_with_base():
    """50 USDT, ~44% base — headroom often below min-notional for new buys."""
    return make_portfolio_state(budget_usdt=50, base_exposure_frac=0.44, price=67.8)


def test_sell_management_only_is_deployable_without_buy_side():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        _sol_portfolio_with_base(),
        constraints(min_notional=5),
        ctx("param_assistant", 50),
    )
    headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
    if headroom < 5.0 and d.params and d.params.sell_grid_count > 0:
        assert d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        assert d.deployable is True
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count in (2, 3)
        assert d.telemetry.get("sell_management_only") is True


def test_bilateral_rule_does_not_block_sell_management_only():
    assert FinalAction.SELL_MANAGEMENT_ONLY.value not in BILATERAL_GRID_ACTIONS
    assert not requires_bilateral_grids(FinalAction.SELL_MANAGEMENT_ONLY.value)
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        _sol_portfolio_with_base(),
        constraints(),
        ctx("param_assistant", 50),
    )
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert d.deployable
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count > 0


def test_sell_management_only_rebuy_disabled():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        _sol_portfolio_with_base(),
        constraints(),
        ctx("param_assistant", 50),
    )
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value and d.params:
        cfg = params_to_grid_config(d.params)
        assert cfg["rebuy_enabled"] is False
        assert cfg["profit_reentry_drop_pct"] == 0.0
        assert cfg["buy_trigger_trailing_pct"] == 0.0


def test_wait_has_no_buy_and_no_sell_grid():
    engine = DynamicParamScoreEngine()
    dump = mk_candles([100.0 * math.exp(-0.02 * i) for i in range(120)], vol=9000.0)
    m = make_market_bundle(symbol="TESTUSDT", pattern="dump_risk", price=40, quote_vol=1_000_000)
    d = engine.calculate_decision(
        "TESTUSDT",
        m,
        make_portfolio_state(budget_usdt=30, base_exposure_frac=0.0, price=40),
        constraints(min_notional=5),
        ctx("param_assistant", 30),
    )
    if d.final_action == FinalAction.WAIT.value:
        assert not d.deployable
        assert d.params is None or (
            d.params.buy_grid_count == 0 and d.params.sell_grid_count == 0
        )


def test_no_trade_has_no_buy_and_no_sell_grid():
    engine = DynamicParamScoreEngine()
    m = make_market_bundle(pattern="dump_risk", price=50)
    d = engine.calculate_decision(
        "SOLUSDT",
        m,
        make_portfolio_state(budget_usdt=20, base_exposure_frac=0.0),
        constraints(),
        ctx("param_assistant", 20),
    )
    if d.final_action == FinalAction.NO_TRADE.value:
        assert not d.deployable
        assert d.params is None or (
            d.params.buy_grid_count == 0 and d.params.sell_grid_count == 0
        )


def test_sell_management_only_ui_contract():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        _sol_portfolio_with_base(),
        constraints(),
        ctx("param_assistant", 50),
    )
    if d.final_action != FinalAction.SELL_MANAGEMENT_ONLY.value:
        return
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert r["final_action"] == FinalAction.SELL_MANAGEMENT_ONLY.value
    assert r["final_action_label"] == "Sadece satış yönetimi"
    assert r["sell_management_only"] is True
    assert r["apply_policy"] == "allow"
    assert r["ui_config"] is not None
    assert len(r["ui_config"]["down"]["grids"]) == 0
    assert len(r["ui_config"]["up"]["grids"]) >= 2
    assert r["ui_config"]["profit"]["rebuy_enabled"] is False
    assert "satış yönetimi" in (r.get("explain") or "").lower()
