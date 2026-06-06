"""Paralel çoklu grid tetik / yürütme."""

import pytest

from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import (
    tick_dca_grid_trailing,
    _try_trigger_buy_grid,
)


def _cfg_two_buy():
    return DcaGridTrailingConfig(
        {
            "symbol": "ETHUSDT",
            "sell_grids": [],
            "buy_grids": [
                {"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0},
                {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 20.0},
            ],
            "sell_trigger_trailing_pct": 0.3,
            "buy_trigger_trailing_pct": 0.3,
            "max_buy_levels": 2,  # İki paralel alış grid'i test ediliyor
        }
    )


def _state_two_buy():
    return {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "reference_price": 2000.0,
        "grid_reference_quote": 100.0,
        "base_balance": 0.05,
        "quote_balance": 100.0,
        "sell_grid_fired": [],
        "buy_grid_fired": [False, False],
        "sell_grid_trigger_price": [],
        "buy_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [],
        "buy_grid_trough_price": [None, None],
        "sell_history": [],
        "buy_history": [],
    }


def test_two_buy_grids_trigger_same_trough_and_exec():
    cfg = _cfg_two_buy()
    state = _state_two_buy()
    # P below both thresholds (1980 and 1960) → both trigger same tick
    tick_dca_grid_trailing(state, cfg, 1950.0, 0.05, 100.0)
    assert state["buy_grid_trigger_price"][0] is not None
    assert state["buy_grid_trigger_price"][1] is not None
    assert state["buy_grid_trough_price"][0] == pytest.approx(1950.0)
    assert state["buy_grid_trough_price"][1] == pytest.approx(1950.0)


def test_two_buy_grids_parallel_execute_different_quote():
    cfg = _cfg_two_buy()
    state = _state_two_buy()
    _try_trigger_buy_grid(state, 0, 1950.0, 1980.0)
    _try_trigger_buy_grid(state, 1, 1950.0, 1960.0)
    exec_thr = 1950.0 * 1.003
    actions, _ = tick_dca_grid_trailing(state, cfg, exec_thr + 1.0, 0.05, 100.0)
    buys = [a for a in actions if a.get("reason") == "trail_buy_grid"]
    assert len(buys) == 2
    assert buys[0]["grid_index"] == 0
    assert buys[1]["grid_index"] == 1
    assert buys[0]["quote_qty"] != buys[1]["quote_qty"]
    assert buys[0]["quote_qty"] == pytest.approx(10.0, rel=0.01)
    assert buys[1]["quote_qty"] > buys[0]["quote_qty"]


def test_outage_triggers_multiple_buy_grids():
    from app.botengine.strategies.grid_outage_recovery import apply_grid_outage_recovery
    from datetime import datetime, timedelta, timezone

    cfg = _cfg_two_buy()
    state = _state_two_buy()
    state["last_tick_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
    apply_grid_outage_recovery(state, cfg, 1960.0, gap_sec=120.0)
    assert state["buy_grid_trigger_price"][0] is not None
    assert state["buy_grid_trigger_price"][1] is not None
    assert state["buy_grid_trough_price"][0] == state["buy_grid_trough_price"][1]
