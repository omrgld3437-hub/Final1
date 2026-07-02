"""Bot oturum event id + since_id list_events."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.botengine.bot_session import resolve_bot_session_start_event_id
from app.botengine.state_store import list_events


def _row(eid, ts, etype, msg, meta="{}"):
    return (eid, ts, etype, msg, meta)


def test_resolve_bot_session_start_event_id_after_stop():
    db = MagicMock()

    def execute_side_effect(q, params=None):
        sql = str(q)
        result = MagicMock()
        if "STOP" in sql and "ORDER BY id DESC" in sql:
            result.fetchone.return_value = (10,)
            return result
        if "START" in sql and "ORDER BY id ASC" in sql:
            result.fetchall.return_value = [
                _row(
                    42,
                    "2026-06-13T10:00:00Z",
                    "INFO",
                    "COMMAND_EXECUTED START",
                    "{}",
                )
            ]
            return result
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        return result

    db.execute.side_effect = execute_side_effect
    assert resolve_bot_session_start_event_id(db, 7, {}) == 42


def test_list_events_since_id_filters_old_rows():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        _row(100, "2026-06-13T12:00:00Z", "INFO", "new", "{}"),
        _row(50, "2026-06-13T11:00:00Z", "INFO", "old", "{}"),
    ]
    out = list_events(db, 1, limit=10, since_id=80)
    assert len(out) == 2
    assert db.execute.call_args[0][1]["sid"] == 80
