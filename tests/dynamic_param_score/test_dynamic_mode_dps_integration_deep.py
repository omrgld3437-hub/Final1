"""Dynamic mode ↔ DPS integration (build_snapshot contract)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.botengine.dynamic.cycle_manager import _no_trade_overlay, build_snapshot
from app.services.dynamic_param_score.models import BotParams, FinalAction


from tests.dynamic_param_score.factories import make_bot_params


def _mock_decision(**kw):
    defaults = dict(
        decision_id="d1",
        param_score=62,
        confidence_score=55,
        risk_score=40,
        regime_tag="BALANCED_RANGE",
        risk_state="NORMAL",
        selected_profile_name="BALANCED_RANGE_GRID_PROFILE",
        final_action=FinalAction.BALANCED_GRID.value,
        deployable=True,
        explain="test explain",
        blocking_reasons=[],
        warnings=[],
        safety_gates=[],
        telemetry={"sub_scores": {}},
        action_detail={},
        params=make_bot_params(),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_build_snapshot_calls_dps_engine():
    decision = _mock_decision()
    mock_engine = MagicMock()
    mock_engine.calculate_decision.return_value = decision
    mock_engine.decision_to_overlay.return_value = {
        "base_alloc_pct": 45,
        "quote_alloc_pct": 55,
        "buy_grids": [{"buy_grid_pct": 1, "buy_qty_pct_of_quote": 50}],
        "sell_grids": [{"sell_grid_pct": 1, "sell_qty_pct_of_base": 50}],
        "max_base_exposure_frac": 0.56,
        "max_buy_levels": 2,
    }

    cfg = {
        "symbol": "SOLUSDT",
        "initial_capital_usdt": 50,
        "budget_usdt": 50,
        "base_alloc_pct": 50,
        "quote_alloc_pct": 50,
        "buy_grids": [
            {"buy_grid_pct": 1, "buy_qty_pct_of_quote": 50},
            {"buy_grid_pct": 2, "buy_qty_pct_of_quote": 50},
        ],
        "sell_grids": [
            {"sell_grid_pct": 1, "sell_qty_pct_of_base": 50},
            {"sell_grid_pct": 2, "sell_qty_pct_of_base": 50},
        ],
        "max_buy_levels": 2,
        "max_base_exposure_frac": 0.80,
    }
    state = {"bot_id": 1, "cycle_id": 2, "dynamic_snapshot": {}}

    with patch("app.botengine.dynamic.cycle_manager.collect_features") as cf, patch(
        "app.botengine.dynamic.cycle_manager.collect_market_data", new_callable=AsyncMock
    ) as cmd, patch(
        "app.botengine.dynamic.cycle_manager.get_dps_engine", return_value=mock_engine
    ):
        cf.return_value = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
        cmd.return_value = SimpleNamespace(ticker_price=100.0)
        snap = await build_snapshot(state, cfg, price=100.0)

    mock_engine.calculate_decision.assert_called_once()
    call_ctx = mock_engine.calculate_decision.call_args
    assert call_ctx[1]["bot_context"].run_source == "dynamic_round_start"
    assert snap["stance"]["source"] == "dynamic_param_score"
    assert snap["dps"]["decision_id"] == "d1"
    assert len(snap["applied"]["buy_grids"]) == 2
    assert len(snap["applied"]["sell_grids"]) == 2
    assert snap["applied"]["max_buy_levels"] == 2
    assert snap["multiplier"]["grid_count_invariant"]["preserved"] is True
    mock_engine.decision_to_overlay.assert_not_called()
    assert snap["fallbacks"] == []


@pytest.mark.asyncio
async def test_soft_wait_snapshot_stays_active_not_idle():
    """Soft WAIT keeps the ladder shape but pauses buy execution until retry."""
    decision = _mock_decision(
        final_action=FinalAction.WAIT.value,
        deployable=False,
        params=None,
        blocking_reasons=["FEE_BAD"],
    )
    mock_engine = MagicMock()
    mock_engine.calculate_decision.side_effect = [decision, decision]

    state = {"bot_id": 1, "cycle_id": 2, "dynamic_snapshot": {}}
    cfg = {
        "symbol": "SOLUSDT",
        "initial_capital_usdt": 50,
        "buy_grids": [{"buy_grid_pct": 1, "buy_qty_pct_of_quote": 25}],
        "sell_grids": [{"sell_grid_pct": 1, "sell_qty_pct_of_base": 25}],
    }
    with patch("app.botengine.dynamic.cycle_manager.collect_features") as cf, patch(
        "app.botengine.dynamic.cycle_manager.collect_market_data", new_callable=AsyncMock
    ) as cmd, patch(
        "app.botengine.dynamic.cycle_manager.get_dps_engine", return_value=mock_engine
    ):
        cf.return_value = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
        cmd.return_value = SimpleNamespace(ticker_price=100.0)
        snap = await build_snapshot(state, cfg, price=100.0)

    assert len(snap["applied"]["buy_grids"]) == len(cfg["buy_grids"])
    assert len(snap["applied"]["sell_grids"]) == len(cfg["sell_grids"])
    assert snap["applied"].get("buy_disabled") is True
    assert snap["applied"].get("cancel_existing_buy_orders") is True
    assert "start_blocked_retry_pending" in snap["fallbacks"]


@pytest.mark.asyncio
async def test_hard_safety_wait_snapshot_preserves_ladder_and_pauses_buys():
    cfg = {
        "symbol": "SOLUSDT",
        "buy_grids": [{"buy_grid_pct": 1, "buy_qty_pct_of_quote": 25}] * 4,
        "sell_grids": [{"sell_grid_pct": 1, "sell_qty_pct_of_base": 25}] * 2,
    }
    decision = _mock_decision(
        final_action=FinalAction.NO_TRADE.value,
        deployable=False,
        regime_tag="DUMP_RISK",
        params=None,
        blocking_reasons=["DUMP_RISK"],
    )
    mock_engine = MagicMock()
    mock_engine.calculate_decision.return_value = decision
    from app.services.dynamic_param_score.safe_overlay import build_no_trade_overlay

    mock_engine.decision_to_overlay.return_value = build_no_trade_overlay(decision)

    state = {"bot_id": 1, "cycle_id": 2, "dynamic_snapshot": {}}
    cfg = {"symbol": "SOLUSDT", "initial_capital_usdt": 50, "buy_grids": [{"buy_grid_pct": 1}], "sell_grids": []}
    with patch("app.botengine.dynamic.cycle_manager.collect_features") as cf, patch(
        "app.botengine.dynamic.cycle_manager.collect_market_data", new_callable=AsyncMock
    ) as cmd, patch(
        "app.botengine.dynamic.cycle_manager.get_dps_engine", return_value=mock_engine
    ):
        cf.return_value = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
        cmd.return_value = SimpleNamespace(ticker_price=100.0)
        snap = await build_snapshot(state, cfg, price=100.0)

    assert len(snap["applied"]["buy_grids"]) == len(cfg["buy_grids"])
    assert snap["applied"].get("max_buy_levels", 0) == len(cfg["buy_grids"])
    assert snap["applied"].get("buy_disabled") is True
    assert snap["applied"].get("cancel_existing_buy_orders") is True
    assert snap.get("round_pending") is True
    assert state.get("_dynamic_round_pending", {}).get("active") is True


def test_safety_gate_result_format():
    from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
    from tests.dynamic_param_score.factories import make_constraints, make_context, make_market_bundle, make_portfolio_state

    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(),
        make_portfolio_state(budget_usdt=50),
        make_constraints(),
        make_context(budget_usdt=50),
    )
    allowed_actions = {"allow", "block", "adjust", "warn", "deny", "pass", "fail", "reduce"}
    for g in d.safety_gates:
        assert g.gate_id
        assert g.reason_code
        assert g.message
        assert isinstance(g.passed, bool)
        assert isinstance(g.adjustments, dict)
