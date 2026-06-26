"""Worker SQLite pool — NullPool avoids QueuePool exhaustion with many bot loops."""

from __future__ import annotations

import os


def test_worker_sqlite_uses_nullpool(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/test_worker_pool.db")
    monkeypatch.setenv("DATABASE_ROLE", "worker")
    import importlib

    import app.db.base as base

    importlib.reload(base)
    from sqlalchemy.pool import NullPool

    assert base.engine.pool.__class__ is NullPool


def test_ensure_running_bots_does_not_close_caller_db(monkeypatch):
    """ensure_running_bots must not close the session owned by the caller."""
    import asyncio
    from unittest.mock import MagicMock, patch

    closed = {"called": False}

    class _FakeSession:
        def close(self):
            closed["called"] = True

        def query(self, *a, **k):
            m = MagicMock()
            m.filter.return_value.all.return_value = []
            return m

        def commit(self):
            pass

    db = _FakeSession()
    with patch("app.db.models.Bot"), patch(
        "app.services.perf_chart_state.seed_perf_chart_state_on_bot_start"
    ), patch("app.botengine.orchestrator._engine_tick_task", None), patch(
        "app.botengine.orchestrator.asyncio.create_task"
    ):
        from app.botengine.orchestrator import ensure_running_bots

        asyncio.get_event_loop().run_until_complete(
            ensure_running_bots(db, recovery_source="test")
        )
    assert closed["called"] is False
