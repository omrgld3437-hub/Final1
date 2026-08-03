import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.bots_engine import _wallet_for_bot_delete
from app.botengine.state_store import append_event, save_state
from app.db.schema_guard import cleanup_orphaned_bot_runtime_rows
from app.http_error_policy import should_persist_http_exception


def _runtime_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE bots (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE bot_engine_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER NOT NULL UNIQUE,
                    account_id INTEGER,
                    state_json TEXT,
                    cycle_id INTEGER,
                    mode TEXT,
                    last_tick_at TEXT,
                    last_error_code TEXT,
                    retry_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE bot_engine_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER NOT NULL,
                    account_id INTEGER,
                    ts TEXT,
                    event_type TEXT,
                    message TEXT,
                    meta_json TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE TABLE bot_virtual_wallet (id INTEGER PRIMARY KEY, bot_id INTEGER)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE bot_perf_chart_state (bot_id INTEGER PRIMARY KEY)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE bot_public_metrics (id INTEGER PRIMARY KEY, bot_id INTEGER)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE order_intents (id INTEGER PRIMARY KEY, bot_id INTEGER)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE symbol_locks (id INTEGER PRIMARY KEY, owner_bot_id INTEGER)"
            )
        )
    return engine


def test_deleted_bot_cannot_recreate_state_or_events():
    engine = _runtime_engine()
    session = sessionmaker(bind=engine)()
    try:
        save_state(session, 99, 3, {"cycle_id": 1, "mode": "IDLE"})
        append_event(session, 99, 3, "ERROR", "late worker event")
        assert session.execute(text("SELECT count(*) FROM bot_engine_state")).scalar() == 0
        assert session.execute(text("SELECT count(*) FROM bot_engine_events")).scalar() == 0
    finally:
        session.close()


def test_orphan_runtime_cleanup_keeps_live_bot_rows():
    engine = _runtime_engine()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO bots(id, account_id) VALUES (1, 3)"))
        for table, key in (
            ("bot_engine_state", "bot_id"),
            ("bot_engine_events", "bot_id"),
            ("bot_virtual_wallet", "bot_id"),
            ("bot_perf_chart_state", "bot_id"),
            ("bot_public_metrics", "bot_id"),
            ("order_intents", "bot_id"),
            ("symbol_locks", "owner_bot_id"),
        ):
            conn.execute(text(f"INSERT INTO {table}({key}) VALUES (1)"))
            conn.execute(text(f"INSERT INTO {table}({key}) VALUES (8)"))

    assert cleanup_orphaned_bot_runtime_rows(engine) == 7
    with engine.connect() as conn:
        for table in (
            "bot_engine_state",
            "bot_engine_events",
            "bot_virtual_wallet",
            "bot_perf_chart_state",
            "bot_public_metrics",
            "order_intents",
            "symbol_locks",
        ):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1


def test_delete_wallet_retries_transient_binance_timeout(monkeypatch):
    calls = 0

    async def fake_get_wallet(_keys, tag):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError(tag)
        return {"balances": []}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.api.bots_engine.asyncio.sleep", no_sleep)
    result = asyncio.run(_wallet_for_bot_delete(object(), fake_get_wallet))
    assert result == {"balances": []}
    assert calls == 3


def test_admin_error_filter_keeps_only_actionable_http_failures():
    assert not should_persist_http_exception(
        401, {"error_code": "INVALID_CREDENTIALS"}
    )
    assert not should_persist_http_exception(404, {"error_code": "NOT_FOUND"})
    assert should_persist_http_exception(400, {"error_code": "CONVERT_FAILED"})
    assert should_persist_http_exception(500, {"error_code": "INTERNAL_ERROR"})
