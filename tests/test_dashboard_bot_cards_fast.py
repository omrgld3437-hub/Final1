from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.dashboard_snapshot import _fetch_bot_cards_fast_sync


def test_fast_bot_card_uses_live_price_and_state_without_history_queries():
    bot = SimpleNamespace(
        id=1,
        account_id=3,
        symbol="SOLUSDT",
        status="running",
        bot_code="389091",
        config_json='{"budget_usd": 200}',
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [bot]
    state = {
        "initial_allocation_done": True,
        "base_balance": 2,
        "quote_balance": 100,
        "cycle_id": 3,
        "daily_ref_usd": 240,
        "last_tick_at": "2026-07-26T07:00:00Z",
    }

    with (
        patch("app.db.base.SessionLocal", return_value=db),
        patch(
            "app.botengine.state_store.load_states_bulk",
            return_value={1: state},
        ),
        patch(
            "app.services.data_hub.data_hub.get_price_with_meta",
            return_value={"price": 75, "is_stale": False},
        ),
    ):
        cards = _fetch_bot_cards_fast_sync(3)

    assert len(cards) == 1
    assert cards[0]["current_usd"] == 250
    assert cards[0]["total_pnl_usd"] == 50
    assert cards[0]["total_pnl_pct"] == 25
    assert cards[0]["daily_pnl_usd"] == 10
    assert cards[0]["total_cycles_completed"] == 2
    assert cards[0]["display_status"] == "running"
    db.close.assert_called_once()


def test_fast_bot_card_marks_unallocated_running_bot_as_starting():
    bot = SimpleNamespace(
        id=4,
        account_id=3,
        symbol="AVAXUSDT",
        status="running",
        bot_code=None,
        config_json='{"initial_capital_usdt": 300}',
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [bot]

    with (
        patch("app.db.base.SessionLocal", return_value=db),
        patch(
            "app.botengine.state_store.load_states_bulk",
            return_value={4: {"initial_allocation_done": False}},
        ),
        patch(
            "app.services.data_hub.data_hub.get_price_with_meta",
            return_value={"price": 25, "is_stale": False},
        ),
    ):
        cards = _fetch_bot_cards_fast_sync(3)

    assert cards[0]["current_usd"] == 300
    assert cards[0]["display_status"] == "starting"
