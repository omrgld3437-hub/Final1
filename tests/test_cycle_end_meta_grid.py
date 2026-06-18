"""CYCLE_END meta — grid dolum sayacı reset öncesi state'ten okunmalı."""

from types import SimpleNamespace

from app.botengine.execution import _build_cycle_end_meta, _grid_utilization
from app.botengine.strategies.dca_grid_trailing import cycle_reset_after_fill


def test_build_cycle_end_meta_reads_grid_fired_before_reset():
    config = SimpleNamespace(sell_grids=[{}, {}], buy_grids=[{}, {}])
    state = {
        "sell_grid_fired": [False, True],
        "buy_grid_fired": [True, False],
        "_cycle_price_high": 70.0,
        "_cycle_price_low": 62.0,
        "completed_cycle_dual_pnls": [{"cash_pnl_usdt": 0.5}],
    }
    ledger = {"started_at": "2026-06-08T16:08:43+00:00"}
    base_meta = {"cycle_id": 3, "pnl_usdt_net": 0.55}

    meta_before = _build_cycle_end_meta(state, config, ledger, base_meta)
    assert meta_before["sell_grids_fired"] == 1
    assert meta_before["buy_grids_fired"] == 1
    assert meta_before["sell_grids_total"] == 2
    assert meta_before["buy_grids_total"] == 2

    cycle_reset_after_fill(state, 68.0, 2, 2, symbol="SOLUSDT")
    assert _grid_utilization(state, config)["sell_grids_fired"] == 0
    assert _grid_utilization(state, config)["buy_grids_fired"] == 0

    meta_after_reset = _build_cycle_end_meta(state, config, ledger, base_meta)
    assert meta_after_reset["sell_grids_fired"] == 0
    assert meta_after_reset["buy_grids_fired"] == 0
