"""Re-entry must compound into base qty when Binance lot step would keep qty flat."""

import pytest

from app.botengine.execution import _boost_reentry_quote_to_next_lot


def test_reentry_quote_boosts_to_next_lot_step_when_qty_would_stay_flat():
    state = {
        "sell_history": [{"grid_index": 0, "qty": 0.0061, "price": 2011.06}],
    }
    boost = _boost_reentry_quote_to_next_lot(
        state,
        quote_qty=12.267466,
        price=1987.22,
        available_quote=25.0,
        filters={"step_size_str": "0.0001"},
        buffer_pct=0.0,
    )
    assert boost is not None
    assert boost["target_qty"] == pytest.approx(0.0062)
    assert boost["new_quote_qty"] == pytest.approx(0.0062 * 1987.22)


def test_reentry_quote_does_not_boost_when_existing_quote_already_buys_more():
    state = {
        "sell_history": [{"grid_index": 0, "qty": 0.0061, "price": 2011.06}],
    }
    boost = _boost_reentry_quote_to_next_lot(
        state,
        quote_qty=12.5,
        price=1987.22,
        available_quote=25.0,
        filters={"step_size_str": "0.0001"},
        buffer_pct=0.0,
    )
    assert boost is None


def test_reentry_quote_does_not_boost_without_available_compound_quote():
    state = {
        "sell_history": [{"grid_index": 0, "qty": 0.0061, "price": 2011.06}],
    }
    boost = _boost_reentry_quote_to_next_lot(
        state,
        quote_qty=12.267466,
        price=1987.22,
        available_quote=12.29,
        filters={"step_size_str": "0.0001"},
        buffer_pct=0.0,
    )
    assert boost is None
