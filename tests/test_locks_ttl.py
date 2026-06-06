"""
Unit tests for lock TTL consistency and lease_still_valid (Phase 1 perf hardening).
"""

import pytest

from app.botengine.locks import (
    DEFAULT_LEASE_TTL_SEC,
    HEARTBEAT_RENEWAL_INTERVAL_SEC,
    lease_still_valid,
    trade_lock_symbol,
)
from app.core.constants import ACCOUNT_TRADE_LOCK_SYMBOL


def test_trade_lock_symbol_per_account():
    """Same account always maps to account-level lock key (row is account_id + symbol)."""
    assert trade_lock_symbol(1, "BTCUSDT") == ACCOUNT_TRADE_LOCK_SYMBOL
    assert trade_lock_symbol(1, "MULTI") == ACCOUNT_TRADE_LOCK_SYMBOL
    assert trade_lock_symbol(2, "BTCUSDT") == ACCOUNT_TRADE_LOCK_SYMBOL


def test_ttl_constant_consistency():
    """Single source of truth: TTL 10s, heartbeat 3s (spec constants table)."""
    assert DEFAULT_LEASE_TTL_SEC == 10
    assert HEARTBEAT_RENEWAL_INTERVAL_SEC == 3


def test_lease_still_valid_callable():
    """lease_still_valid exists and is callable (required before submit)."""
    assert callable(lease_still_valid)


@pytest.fixture
def db_session():
    """Session for tests that need DB (schema must have symbol_locks). Skips if DB unavailable."""
    try:
        from sqlalchemy import text
        from app.db.base import SessionLocal

        session = SessionLocal()
        session.execute(text("SELECT 1 FROM symbol_locks LIMIT 1"))
        yield session
        session.rollback()
        session.close()
    except Exception:
        pytest.skip("DB or symbol_locks table not available")


def test_lease_still_valid_returns_false_when_no_lock(db_session):
    """When no lock row exists, lease_still_valid returns False -> submit blocked."""
    ok = lease_still_valid(db_session, account_id=999999, symbol="BTCUSDT", bot_id=99)
    assert ok is False


def test_lease_still_valid_returns_false_when_expired(db_session):
    """When lock row exists but lease_until is in the past, lease_still_valid returns False."""
    from sqlalchemy import text
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    past = (now - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_session.execute(
        text("""
            INSERT OR REPLACE INTO symbol_locks (account_id, symbol, owner_bot_id, lease_until, updated_at)
            VALUES (999998, 'BTCUSDT', 99, :past, :past)
        """),
        {"past": past},
    )
    db_session.commit()
    ok = lease_still_valid(db_session, account_id=999998, symbol="BTCUSDT", bot_id=99)
    assert ok is False
