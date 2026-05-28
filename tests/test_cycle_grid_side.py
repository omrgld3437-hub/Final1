"""Tur yön kilidi — ilk başarılı grid fill sonrası tek yön."""
from datetime import datetime, timedelta, timezone

import pytest

from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import (
    apply_fill_to_state,
    tick_dca_grid_trailing,
    get_cycle_grid_side,
)


def _cfg():
    return DcaGridTrailingConfig({
        "symbol": "ETHUSDT",
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 10.0}],
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0}],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
    })


def _base_state():
    return {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "reference_price": 100.0,
        "grid_reference_base": 1.0,
        "grid_reference_quote": 50.0,
        "base_balance": 1.0,
        "quote_balance": 50.0,
        "sell_grid_fired": [False],
        "buy_grid_fired": [False],
        "sell_grid_trigger_price": [None],
        "buy_grid_trigger_price": [None],
        "sell_grid_peak_price": [None],
        "buy_grid_trough_price": [None],
        "sell_history": [],
        "buy_history": [],
    }


def test_bidirectional_before_first_fill():
    cfg = _cfg()
    state = _base_state()
    assert get_cycle_grid_side(state) is None
    actions, _ = tick_dca_grid_trailing(state, cfg, 101.0, 1.0, 50.0)
    assert state["sell_grid_trigger_price"][0] is not None
    actions2, _ = tick_dca_grid_trailing(state, cfg, 99.0, 1.0, 50.0)
    assert state["buy_grid_trigger_price"][0] is not None


def test_lock_sell_clears_buy_triggers():
    cfg = _cfg()
    state = _base_state()
    state["buy_grid_trigger_price"] = [99.0]
    state["buy_grid_trough_price"] = [98.5]
    apply_fill_to_state(
        state, "SELL", 0.1, 101.0, 0.0,
        grid_index=0, reason="trail_sell_grid", execution_price=100.7,
    )
    state["sell_grid_fired"] = [True]
    assert state["cycle_grid_side"] == "SELL"
    assert state["buy_grid_trigger_price"][0] is None
    assert state["buy_grid_trough_price"][0] is None


def test_after_sell_lock_buy_grid_does_not_trigger():
    cfg = _cfg()
    state = _base_state()
    state["cycle_grid_side"] = "SELL"
    state["sell_grid_fired"] = [True]
    state["sell_history"] = [{"grid_index": 0, "qty": 0.1, "price": 101.0}]
    tick_dca_grid_trailing(state, cfg, 98.0, 0.9, 60.0)
    assert state["buy_grid_trigger_price"][0] is None


def test_reentry_only_after_sell_grid_fill():
    cfg = _cfg()
    state = _base_state()
    state["sell_grid_trigger_price"] = [101.0]
    state["sell_grid_peak_price"] = [102.0]
    tick_dca_grid_trailing(state, cfg, 99.0, 0.9, 60.0)
    assert state.get("mode") != "TRAIL_REENTRY_BUY"
    assert state.get("cycle_grid_side") is None
    apply_fill_to_state(
        state, "SELL", 0.1, 101.0, 0.0,
        grid_index=0, reason="trail_sell_grid", execution_price=100.7,
    )
    state["sell_grid_fired"] = [True]
    tick_dca_grid_trailing(state, cfg, 99.0, 0.9, 60.0)
    assert state.get("cycle_grid_side") == "SELL"
    assert state.get("mode") == "TRAIL_REENTRY_BUY"
