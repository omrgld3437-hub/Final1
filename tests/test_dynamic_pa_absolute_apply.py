"""Dynamic Mode applies the same absolute V6/PA plan (no regime multipliers)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.botengine.dynamic import cycle_manager as cm
from app.botengine.dynamic import start_retry_policy as srp
from app.botengine.dynamic import round_start_policy as rsp
from app.services.dynamic_param_score.models import DynamicParamDecision, FinalAction
from tests.dynamic_param_score.factories import make_bot_params


def _cfg() -> dict:
    return {
        "symbol": "SOLUSDT",
        "initial_capital_usdt": 1000.0,
        "base_alloc_pct": 40.0,
        "quote_alloc_pct": 60.0,
        "sell_grids": [
            {"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 3.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 4.0, "sell_qty_pct_of_base": 25.0},
        ],
        "buy_grids": [
            {"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 4.0, "buy_qty_pct_of_quote": 25.0},
        ],
        "sell_trigger_trailing_pct": 0.4,
        "buy_trigger_trailing_pct": 0.4,
        "max_buy_levels": 4,
    }


def test_dynamic_overlay_allowed_on_cycle_1():
    assert cm.dynamic_overlay_allowed({"cycle_id": 1}) is True
    assert cm.FIRST_DYNAMIC_CYCLE_ID == 1


def test_absolute_deployable_uses_v6_grids_not_baseline():
    state = {
        "bot_id": 11,
        "cycle_id": 1,
        "quote_balance": 500.0,
        "base_balance": 5.0,
        "initial_allocation_done": True,
        "dynamic_snapshot": {},
    }
    params = make_bot_params(
        buy_grid_count=4,
        sell_grid_count=4,
        base_alloc_frac=0.70,
        quote_alloc_frac=0.30,
        buy_qty_distribution=[0.4, 0.3, 0.2, 0.1],
        sell_qty_distribution=[0.2, 0.3, 0.3, 0.2],
        buy_grid_ladder_pcts=[2.0, 4.0, 6.0, 9.0],
        sell_grid_ladder_pcts=[2.0, 4.0, 7.0, 10.0],
        buy_grid_trail_pct=0.75,
        sell_grid_trail_pct=1.0,
        pool_version="v6",
    )
    decision = DynamicParamDecision(
        decision_id="abs-1",
        symbol="SOLUSDT",
        timestamp=1,
        run_source="dynamic_round_start",
        final_action=FinalAction.BALANCED_GRID.value,
        deployable=True,
        param_score=80,
        confidence_score=85,
        risk_score=20,
        regime_tag="R1",
        risk_state="NORMAL",
        selected_profile_name="R1_STRONG_UPTREND",
        selected_profile_bucket="STD",
        params=params,
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain="deployable absolute",
        telemetry={
            "pool_version": "v6",
            "net_profile": {
                "key": "R1_STRONG_UPTREND",
                "headline": "Sistem Güçlü Yükseliş Trendi Algıladı",
            },
            "rebalance_plan": {
                "rebalance_decision": "SKIP",
                "rebalance_skipped_reason": "SMALL_BASE_QUOTE_DELTA",
                "current_base_frac": 0.5,
                "target_base_frac": 0.7,
            },
            "order_intent_plan": {"total_buy_quote_usdt": 0},
            "intent_execution_enabled": False,
            "v6_display": {"scenario_identity": {"regime_id": "R1"}},
        },
    )
    features = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
    market = SimpleNamespace(ticker_price=100.0)
    portfolio = SimpleNamespace(
        total_equity_usdt=1000.0,
        quote_value_usdt=500.0,
        base_value_usdt=500.0,
        current_base_exposure_frac=0.5,
    )
    engine = MagicMock()
    engine.calculate_decision.return_value = decision

    with patch.object(cm, "collect_features", new=AsyncMock(return_value=features)), patch.object(
        cm, "collect_market_data", new=AsyncMock(return_value=market)
    ), patch.object(cm, "portfolio_from_bot_state", return_value=portfolio), patch.object(
        cm, "get_dps_engine", return_value=engine
    ):
        snapshot = asyncio.run(cm.build_snapshot(state, _cfg(), price=100.0))

    applied = snapshot["applied"]
    assert snapshot["round_pending"] is False
    assert applied["plan_source"] == "param_assistant_absolute"
    assert applied["intent_execution_enabled"] is True
    assert applied["rebalance_plan"] is not None
    assert applied["base_alloc_pct"] == pytest.approx(70.0)
    assert applied["quote_alloc_pct"] == pytest.approx(30.0)
    assert len(applied["buy_grids"]) == 4
    assert len(applied["sell_grids"]) == 4
    assert applied["buy_grids"][0]["buy_grid_pct"] == pytest.approx(2.0)
    assert applied["sell_grids"][-1]["sell_grid_pct"] == pytest.approx(10.0)
    assert applied["buy_trigger_trailing_pct"] == pytest.approx(0.75)
    assert applied["sell_trigger_trailing_pct"] == pytest.approx(1.0)
    # Must not keep the frozen form baseline distances.
    assert applied["buy_grids"][0]["buy_grid_pct"] != _cfg()["buy_grids"][0]["buy_grid_pct"]
    assert snapshot["pa_plan"]["profile_key"] == "R1_STRONG_UPTREND"
    assert state["target_budgets"]["source"] == "param_assistant_absolute"


def test_non_deployable_pauses_round_with_fixed_30m_retry():
    state = {
        "bot_id": 12,
        "cycle_id": 3,
        "quote_balance": 500.0,
        "base_balance": 0.0,
        "dynamic_snapshot": {},
    }
    decision = DynamicParamDecision(
        decision_id="block-1",
        symbol="SOLUSDT",
        timestamp=1,
        run_source="dynamic_round_start",
        final_action=FinalAction.NO_TRADE.value,
        deployable=False,
        param_score=10,
        confidence_score=20,
        risk_score=90,
        regime_tag="R8",
        risk_state="DEFENSIVE",
        selected_profile_name="R8_HARD_BLOCK",
        selected_profile_bucket="DEF",
        params=make_bot_params(buy_grid_count=4, sell_grid_count=4, pool_version="v6"),
        safety_gates=[],
        blocking_reasons=["operator_profile_auto_apply_disabled"],
        warnings=[],
        explain="kapalı",
        telemetry={
            "pool_version": "v6",
            "net_profile": {"key": "R8_HARD_BLOCK", "headline": "Kapalı"},
            "v6_display": {},
        },
    )
    features = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
    market = SimpleNamespace(ticker_price=100.0)
    portfolio = SimpleNamespace(
        total_equity_usdt=500.0,
        quote_value_usdt=500.0,
        base_value_usdt=0.0,
        current_base_exposure_frac=0.0,
    )
    engine = MagicMock()
    engine.calculate_decision.return_value = decision

    with patch.object(cm, "collect_features", new=AsyncMock(return_value=features)), patch.object(
        cm, "collect_market_data", new=AsyncMock(return_value=market)
    ), patch.object(cm, "portfolio_from_bot_state", return_value=portfolio), patch.object(
        cm, "get_dps_engine", return_value=engine
    ):
        snapshot = asyncio.run(cm.build_snapshot(state, _cfg(), price=100.0))

    assert snapshot["round_pending"] is True
    assert snapshot["applied"]["buy_disabled"] is True
    assert snapshot["applied"]["intent_execution_enabled"] is False
    assert snapshot["applied"]["rebalance_plan"] is None
    wl = srp.get_watchlist(state)
    assert wl is not None
    assert float(wl["retry_after_minutes"]) == pytest.approx(30.0)
    assert rsp.ROUND_START_RETRY_SEC == pytest.approx(1800.0)


def test_retry_after_minutes_fixed_30():
    assert srp.retry_after_minutes(["NO_TRADE"], result_type="no_trade") == pytest.approx(30.0)
    assert srp.retry_after_minutes(
        ["DATA_STALE"],
        result_type="no_trade",
        fixed_retry_minutes=srp.NON_DEPLOYABLE_RETRY_MINUTES,
    ) == pytest.approx(30.0)
