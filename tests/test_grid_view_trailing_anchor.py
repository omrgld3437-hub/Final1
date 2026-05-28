"""Grid trailing dip/tepe: UI view uses state only (motor min/max günceller)."""
from app.botengine.grid_view import compute_grid_profit_view


def _buy_cfg():
    return {
        "sell_grids": [],
        "buy_grids": [
            {"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 50.0},
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 50.0},
        ],
        "buy_trigger_trailing_pct": 0.3,
    }


def test_trailing_buy_dip_state_only_ignores_higher_live_price():
    state = {
        "reference_price": 2090.95,
        "quote_balance": 50.0,
        "base_balance": 0.013,
        "buy_grid_fired": [False, False],
        "sell_grid_fired": [],
        "buy_grid_trigger_price": [2070.0, 2050.0],
        "buy_grid_trough_price": [1995.93, 1995.93],
        "sell_history": [],
        "buy_history": [],
        "mode": "TRAIL_BUY_GRID",
    }
    grid_points, _, _ = compute_grid_profit_view(state, _buy_cfg(), price=2025.0)
    buys = [p for p in grid_points if p["type"] == "buy"]
    for bp in buys:
        assert bp["anchor"] == 1995.93


def test_trailing_buy_dip_state_only_not_live_price():
    state = {
        "reference_price": 2090.95,
        "quote_balance": 50.0,
        "base_balance": 0.013,
        "buy_grid_fired": [False, False],
        "sell_grid_fired": [],
        "buy_grid_trigger_price": [2070.0, 2050.0],
        "buy_grid_trough_price": [1990.18, 1990.18],
        "sell_history": [],
        "buy_history": [],
        "mode": "TRAIL_BUY_GRID",
    }
    grid_points, _, _ = compute_grid_profit_view(state, _buy_cfg(), price=1991.70)
    buys = [p for p in grid_points if p["type"] == "buy"]
    for bp in buys:
        assert bp["anchor"] == 1990.18
        assert bp["execution_price"] == round(1990.18 * 1.003, 4)


def test_trailing_sell_peak_state_only_ignores_lower_live_price():
    state = {
        "reference_price": 2090.95,
        "grid_reference_base": 0.013,
        "base_balance": 0.013,
        "quote_balance": 50.0,
        "sell_grid_fired": [False],
        "buy_grid_fired": [],
        "sell_grid_trigger_price": [2110.0],
        "sell_grid_peak_price": [2140.0],
        "sell_history": [],
        "buy_history": [],
        "mode": "TRAIL_SELL_GRID",
    }
    cfg = {
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 100.0}],
        "buy_grids": [],
        "sell_trigger_trailing_pct": 0.5,
    }
    grid_points, _, _ = compute_grid_profit_view(state, cfg, price=2080.0)
    sell0 = [p for p in grid_points if p["type"] == "sell"][0]
    assert sell0["anchor"] == 2140.0
