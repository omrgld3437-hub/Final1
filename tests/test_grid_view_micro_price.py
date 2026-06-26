"""Micro-price (PEPE) grid view — round(., 4) sıfırlama regresyonu."""

from __future__ import annotations

from app.botengine.grid_view import _round_price, compute_grid_profit_view


def _pepe_cfg():
    return {
        "sell_grids": [],
        "buy_grids": [
            {"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 30},
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 30},
            {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 40},
        ],
        "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 2.0,
        "profit_exit_drop_pct": 0.3,
    }


def test_round_price_pepe_not_zeroed():
    p = 0.00000253
    assert _round_price(p) == 0.00000253
    assert _round_price(p * 0.99) is not None
    assert _round_price(p * 0.99) > 0


def test_pepe_fired_buy_grid_preserves_prices():
    ref = 0.00000270
    fill = 0.00000251
    trough = 0.00000248
    state = {
        "reference_price": ref,
        "cycle_grid_side": "BUY",
        "buy_grid_fired": [True, True, True],
        "buy_grid_trigger_price": [0.00000267, 0.00000265, 0.00000262],
        "buy_grid_trough_price": [trough, trough, trough],
        "buy_grid_fill_price": [fill, fill, fill],
        "buy_history": [
            {"grid_index": 0, "qty": 1000, "price": fill},
            {"grid_index": 1, "qty": 1000, "price": fill},
            {"grid_index": 2, "qty": 1000, "price": fill},
        ],
        "quote_balance": 0.57,
        "base_balance": 77842297.22,
    }
    grid_points, profit_points, meta = compute_grid_profit_view(
        state, _pepe_cfg(), price=0.00000253
    )
    assert meta.get("ref_display") == ref
    buys = [p for p in grid_points if p["type"] == "buy"]
    assert len(buys) == 3
    for bp in buys:
        assert bp["fired"] is True
        assert bp["trigger_price"] is not None and bp["trigger_price"] > 0
        assert bp["anchor"] is not None and bp["anchor"] > 0
        assert bp["execution_price"] is not None and bp["execution_price"] > 0

    assert profit_points
    pe = profit_points[0]
    assert pe["type"] == "profit_exit"
    assert pe["average_cost"] is not None and pe["average_cost"] > 0
    assert pe["trigger_price"] is not None and pe["trigger_price"] > 0
