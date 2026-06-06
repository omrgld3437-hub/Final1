"""Grid panel planned qty stays fixed after sells (grid_reference_base, not live balance)."""

from app.botengine.grid_view import compute_grid_profit_view


def _cfg():
    return {
        "sell_grids": [
            {"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 40.0},
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 60.0},
        ],
        "buy_grids": [],
        "sell_trigger_trailing_pct": 0.5,
    }


def test_planned_sell_qty_uses_reference_base_not_remaining_balance():
    state = {
        "reference_price": 2092.64,
        "grid_reference_base": 0.013,
        "base_balance": 0.0001,
        "quote_balance": 50.0,
        "sell_grid_fired": [True, False],
        "buy_grid_fired": [],
        "sell_grid_trigger_price": [2113.57, None],
        "sell_grid_peak_price": [2120.0, None],
        "sell_grid_fill_price": [2107.77, None],
        "sell_history": [{"grid_index": 0, "qty": 0.0052, "price": 2107.77}],
        "buy_history": [],
    }
    grid_points, _, _ = compute_grid_profit_view(state, _cfg(), price=2100.0)
    sell = [p for p in grid_points if p["type"] == "sell"]
    assert len(sell) == 2
    assert sell[0]["planned_base_qty"] == 0.0052
    assert sell[1]["planned_base_qty"] == round(0.013 * 0.6, 8)


def test_planned_sell_qty_before_any_fill():
    state = {
        "reference_price": 2092.64,
        "grid_reference_base": 0.013,
        "base_balance": 0.013,
        "quote_balance": 50.0,
        "sell_grid_fired": [False, False],
        "buy_grid_fired": [],
        "sell_history": [],
        "buy_history": [],
    }
    grid_points, _, _ = compute_grid_profit_view(state, _cfg(), price=2100.0)
    sell = [p for p in grid_points if p["type"] == "sell"]
    assert sell[0]["planned_base_qty"] == round(0.013 * 0.4, 8)
    assert sell[1]["planned_base_qty"] == round(0.013 * 0.6, 8)


def test_profit_points_avg_cost_grid_only_uses_execution_price():
    """Ortalama maliyet: yalnız grid fill; execution_price varsa fill price yerine o kullanılır."""
    state = {
        "reference_price": 2092.64,
        "base_balance": 0.01,
        "quote_balance": 50.0,
        "sell_grid_fired": [True],
        "buy_grid_fired": [],
        "sell_history": [
            {
                "grid_index": 0,
                "qty": 0.01,
                "price": 2121.7136,
                "execution_price": 2123.4407,
            },
        ],
        "buy_history": [],
    }
    cfg = {
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 100.0}],
        "buy_grids": [],
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
    }
    _, profit_points, meta = compute_grid_profit_view(state, cfg, price=2100.0)
    assert meta.get("avg_sell_grid") == 2123.4407
    assert len(profit_points) == 1
    assert profit_points[0]["type"] == "reentry"
    assert profit_points[0]["average_cost"] == 2123.4407
    assert profit_points[0]["trigger_price"] == round(2123.4407 * 0.99, 4)
