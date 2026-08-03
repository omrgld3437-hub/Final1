from app.botengine.strategies.dca_grid_trailing import infer_cycle_grid_side
from app.services.data_hub import data_hub
from app.services.price_hub import price_hub


def test_price_hub_never_promotes_stale_cache_to_live_price(monkeypatch):
    monkeypatch.setattr(
        data_hub,
        "get_price_with_meta",
        lambda _symbol: {
            "price": 77.71,
            "ts": 1.0,
            "is_stale": True,
        },
    )

    assert price_hub.get_price("SOLUSDT") is None
    assert price_hub.get_price_with_meta("SOLUSDT")["price"] == 77.71


def test_trigger_flag_alone_does_not_lock_cycle_direction():
    state = {
        "sell_grid_fired": [False],
        "buy_grid_fired": [True],
        "buy_grid_trigger_price": [77.16],
        "buy_grid_trough_price": [75.94],
    }

    assert infer_cycle_grid_side(state) is None


def test_completed_grid_fill_locks_cycle_direction():
    state = {
        "sell_grid_fired": [False],
        "buy_grid_fired": [True],
        "buy_grid_fill_price": [75.97],
        "buy_grid_status": ["COMPLETED"],
    }

    assert infer_cycle_grid_side(state) == "BUY"


def test_non_grid_ledger_fill_does_not_lock_cycle_direction():
    state = {
        "sell_grid_fired": [False],
        "buy_grid_fired": [False],
        "cycle_ledger_current": {
            "fills": [
                {
                    "side": "BUY",
                    "reason": "initial_allocation",
                    "slot_id": 0,
                    "price": 77.71,
                }
            ]
        },
    }

    assert infer_cycle_grid_side(state) is None
