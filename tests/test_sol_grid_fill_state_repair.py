from app.botengine.grid_view import compute_grid_profit_view
from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing


def _sol_cfg():
    return DcaGridTrailingConfig(
        {
            "symbol": "SOLUSDT",
            "initial_capital_usdt": 50.0,
            "base_alloc_pct": 55.0,
            "quote_alloc_pct": 45.0,
            "sell_grids": [
                {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 60.0},
                {"sell_grid_pct": 4.0, "sell_qty_pct_of_base": 40.0},
            ],
            "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 100.0}],
            "buy_trigger_trailing_pct": 0.5,
            "sell_trigger_trailing_pct": 0.5,
            "max_buy_levels": 1,
            "min_notional_guard": 10.0,
        }
    )


def test_tick_repairs_filled_buy_grid_flags_from_history_and_ledger():
    state = {
        "bot_id": 9,
        "cycle_id": 1,
        "mode": "TRAIL_BUY_GRID",
        "_trail_buy_grid_index": 0,
        "reference_price": 77.94,
        "initial_allocation_done": True,
        "base_balance": 0.647,
        "quote_balance": 0.15397,
        "sell_grid_fired": [False, False],
        "sell_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [None, None],
        "buy_grid_fired": [False],
        "buy_grid_trigger_price": [77.1606],
        "buy_grid_trough_price": [75.94],
        "buy_grid_fill_price": [None],
        "buy_grid_min_notional_blocked": {"0": {"notional": 0.154, "min_notional": 10.0}},
        "active_health_skips": {
            "MIN_NOTIONAL": {
                "active": True,
                "side": "BUY",
                "grid_indices": [0],
            }
        },
        "sell_history": [],
        "buy_history": [
            {
                "grid_index": 0,
                "qty": 0.295,
                "price": 75.97,
                "execution_price": 76.3197,
            }
        ],
        "cycle_ledger_current": {
            "fills": [
                {
                    "side": "BUY",
                    "reason": "trail_buy_grid",
                    "slot_id": 0,
                    "qty": 0.295,
                    "price": 75.97,
                }
            ]
        },
    }

    actions, _ = tick_dca_grid_trailing(state, _sol_cfg(), 76.7, 0.647, 0.15397)

    assert actions == []
    assert state["buy_grid_fired"][0] is True
    assert state["buy_grid_fill_price"][0] == 75.97
    assert state["mode"] == "IDLE"
    assert "buy_grid_min_notional_blocked" not in state
    assert "active_health_skips" not in state


def test_grid_view_does_not_show_unfunded_buy_as_waiting_or_triggered():
    state = {
        "reference_price": 77.94,
        "quote_balance": 0.15397,
        "base_balance": 0.647,
        "buy_grid_fired": [False],
        "buy_grid_trigger_price": [77.1606],
        "buy_grid_trough_price": [75.94],
        "buy_grid_fill_price": [None],
        "sell_grid_fired": [False, False],
        "sell_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [None, None],
        "sell_history": [],
        "buy_history": [],
    }

    grid_points, _, _ = compute_grid_profit_view(state, _sol_cfg().to_dict(), 76.7)
    buy = [p for p in grid_points if p["type"] == "buy"][0]

    assert buy["status"] == "devre_disi"
    assert buy["disabled"] is True
    assert buy["disabled_reason"] == "insufficient_quote"
