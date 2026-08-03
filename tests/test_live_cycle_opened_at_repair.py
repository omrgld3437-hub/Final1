from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.bots_engine import _heal_cycle_opened_at_state


def _db_with_first_trade(trade):
    db = MagicMock()
    (
        db.query.return_value.filter.return_value.order_by.return_value.first
    ).return_value = trade
    return db


def test_missing_cycle_opened_at_is_repaired_from_first_cycle_trade():
    first_trade_at = datetime(2026, 7, 26, 6, 3, 7)
    db = _db_with_first_trade(SimpleNamespace(ts=first_trade_at))
    bot = SimpleNamespace(
        id=1,
        account_id=3,
        started_at=datetime(2026, 7, 26, 6, 2, 57),
    )
    state = {
        "cycle_id": 1,
        "initial_allocation_done": True,
        "bot_run_started_at": "2026-07-26T06:02:58.471630Z",
    }

    with patch("app.botengine.state_store.save_state") as save_state:
        _heal_cycle_opened_at_state(db, bot, state)

    assert state["cycle_opened_at"] == "2026-07-26T06:03:07+00:00"
    save_state.assert_called_once_with(db, 1, 3, state)


def test_first_cycle_uses_bot_session_when_no_trade_exists():
    db = _db_with_first_trade(None)
    bot = SimpleNamespace(
        id=7,
        account_id=2,
        started_at=datetime(2026, 7, 26, 6, 2, 57),
    )
    state = {
        "cycle_id": 1,
        "initial_allocation_done": True,
        "bot_run_started_at": "2026-07-26T06:02:58.471630Z",
    }

    with patch("app.botengine.state_store.save_state"):
        _heal_cycle_opened_at_state(db, bot, state)

    assert datetime.fromisoformat(state["cycle_opened_at"]) == datetime(
        2026, 7, 26, 6, 2, 58, 471630, tzinfo=timezone.utc
    )


def test_unallocated_cycle_is_not_given_a_fake_start_time():
    db = _db_with_first_trade(None)
    bot = SimpleNamespace(id=8, account_id=2, started_at=None)
    state = {"cycle_id": 1, "initial_allocation_done": False}

    with patch("app.botengine.state_store.save_state") as save_state:
        _heal_cycle_opened_at_state(db, bot, state)

    assert "cycle_opened_at" not in state
    db.query.assert_not_called()
    save_state.assert_not_called()
