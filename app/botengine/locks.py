"""
Account+symbol lease lock for multi-bot (Bot Engine v5).
DB-backed; dynamic lease (default 10s) + heartbeat renew every 3s.
If renew fails => fail safe: stop submits, release if possible.
Single source of truth: TTL from app.core.constants.
"""

from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, AsyncGenerator, Callable, Optional

# Re-export for callers
__all__ = [
    "trade_lock_symbol",
    "try_acquire_symbol_lock",
    "release_symbol_lock",
    "renew_symbol_lock",
    "lease_still_valid",
    "symbol_lock_with_heartbeat",
    "HEARTBEAT_RENEWAL_INTERVAL_SEC",
]

from sqlalchemy import text

from app.core.constants import (
    ACCOUNT_TRADE_LOCK_SYMBOL,
    DEFAULT_LEASE_TTL_SEC,
    LOCK_HEARTBEAT_SEC,
)


def trade_lock_symbol(account_id: int, trading_symbol: Optional[str] = None) -> str:
    """Per-account order lock key. Same account_id => same lock (independent users use different accounts)."""
    return ACCOUNT_TRADE_LOCK_SYMBOL


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Re-export for orchestrator and tests (same values as core.constants)
HEARTBEAT_RENEWAL_INTERVAL_SEC = LOCK_HEARTBEAT_SEC


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def try_acquire_symbol_lock(
    db: "Session",
    account_id: int,
    symbol: str,
    bot_id: int,
    ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
) -> bool:
    """
    Acquire (account_id, symbol) lock for bot_id. Returns True if acquired, False if busy.
    Lease expires after ttl_sec; expired locks can be re-acquired by any bot.
    """
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    now = _utcnow()
    lease_until = now + timedelta(seconds=ttl_sec)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    lease_s = lease_until.strftime("%Y-%m-%d %H:%M:%S")

    # 1) UPDATE if row exists and (expired or we already own it)
    r = db.execute(
        text("""
            UPDATE symbol_locks
            SET owner_bot_id = :bid, lease_until = :lease, updated_at = :upd
            WHERE account_id = :aid AND symbol = :sym
              AND (lease_until < :now OR owner_bot_id = :bid)
        """),
        {
            "aid": account_id,
            "sym": symbol,
            "bid": bot_id,
            "lease": lease_s,
            "upd": now_s,
            "now": now_s,
        },
    )
    if r.rowcount and r.rowcount > 0:
        db.commit()
        logger.info(
            "lock_acquire_ok account_id=%s bot_id=%s symbol=%s lease_until=%s",
            account_id,
            bot_id,
            symbol,
            lease_s,
        )
        return True

    # 2) No row? INSERT (we hold the lock)
    exists = db.execute(
        text("SELECT 1 FROM symbol_locks WHERE account_id = :aid AND symbol = :sym"),
        {"aid": account_id, "sym": symbol},
    ).fetchone()
    if not exists:
        try:
            db.execute(
                text("""
                    INSERT INTO symbol_locks (account_id, symbol, owner_bot_id, lease_until, updated_at)
                    VALUES (:aid, :sym, :bid, :lease, :upd)
                """),
                {
                    "aid": account_id,
                    "sym": symbol,
                    "bid": bot_id,
                    "lease": lease_s,
                    "upd": now_s,
                },
            )
            db.commit()
            logger.info(
                "lock_acquire_ok account_id=%s bot_id=%s symbol=%s lease_until=%s",
                account_id,
                bot_id,
                symbol,
                lease_s,
            )
            return True
        except Exception:
            db.rollback()
            logger.info(
                "lock_acquire_busy account_id=%s bot_id=%s symbol=%s error_code=insert_conflict",
                account_id,
                bot_id,
                symbol,
            )
            return False

    logger.info(
        "lock_acquire_busy account_id=%s bot_id=%s symbol=%s lease_until=held_by_other",
        account_id,
        bot_id,
        symbol,
    )
    return False


def renew_symbol_lock(
    db: "Session",
    account_id: int,
    symbol: str,
    bot_id: int,
    ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
) -> bool:
    """Extend lease for held lock. Returns True if renewed."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    now = _utcnow()
    lease_until = now + timedelta(seconds=ttl_sec)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    lease_s = lease_until.strftime("%Y-%m-%d %H:%M:%S")
    r = db.execute(
        text("""
            UPDATE symbol_locks
            SET lease_until = :lease, updated_at = :upd
            WHERE account_id = :aid AND symbol = :sym AND owner_bot_id = :bid AND lease_until > :now
        """),
        {
            "aid": account_id,
            "sym": symbol,
            "bid": bot_id,
            "lease": lease_s,
            "upd": now_s,
            "now": now_s,
        },
    )
    if r.rowcount and r.rowcount > 0:
        db.commit()
        logger.debug(
            "lock_heartbeat_ok account_id=%s bot_id=%s symbol=%s lease_until=%s",
            account_id,
            bot_id,
            symbol,
            lease_s,
        )
        return True
    return False


def force_unlock_symbol(db: "Session", account_id: int, symbol: str) -> int:
    """Admin: clear lock if lease expired. Returns count of rows cleared."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    r = db.execute(
        text("""
            UPDATE symbol_locks
            SET owner_bot_id = 0, lease_until = :now, updated_at = :now
            WHERE account_id = :aid AND symbol = :sym AND lease_until < :now
        """),
        {"aid": account_id, "sym": symbol, "now": now_s},
    )
    if r.rowcount and r.rowcount > 0:
        db.commit()
    return r.rowcount or 0


def lease_still_valid(db: "Session", account_id: int, symbol: str, bot_id: int) -> bool:
    """Return True if bot_id still holds a valid lease for (account_id, symbol). Call before submit to avoid double-submit after heartbeat failure."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row = db.execute(
        text("""
            SELECT 1 FROM symbol_locks
            WHERE account_id = :aid AND symbol = :sym AND owner_bot_id = :bid AND lease_until > :now
        """),
        {"aid": account_id, "sym": symbol, "bid": bot_id, "now": now_s},
    ).fetchone()
    return row is not None


def release_symbol_lock(
    db: "Session", account_id: int, symbol: str, bot_id: int
) -> None:
    """Release lock held by bot_id for (account_id, symbol). Idempotent."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        text("""
            UPDATE symbol_locks
            SET owner_bot_id = 0, lease_until = :now, updated_at = :now
            WHERE account_id = :aid AND symbol = :sym AND owner_bot_id = :bid
        """),
        {"aid": account_id, "sym": symbol, "bid": bot_id, "now": now_s},
    )
    db.commit()


def get_db_session() -> "Session":
    """Get a new DB session for lock ops (caller closes)."""
    from app.db.base import SessionLocal

    return SessionLocal()


@asynccontextmanager
async def symbol_lock_with_heartbeat(
    account_id: int,
    symbol: str,
    bot_id: int,
    ttl_sec: int = DEFAULT_LEASE_TTL_SEC,
    heartbeat_interval_sec: float = HEARTBEAT_RENEWAL_INTERVAL_SEC,
    get_db: Optional[Callable[[], "Session"]] = None,
) -> AsyncGenerator[bool, None]:
    """
    Acquire (account_id, symbol) lock for bot_id; run heartbeat renewal in background.
    On exit (finally): always release lock. If heartbeat renew fails, yield False and caller should fail safe.
    """
    db_factory = get_db or get_db_session
    db = db_factory()
    acquired = False
    try:
        acquired = try_acquire_symbol_lock(db, account_id, symbol, bot_id, ttl_sec)
        if not acquired:
            yield False
            return
        stop_heartbeat = asyncio.Event()
        renew_failed = asyncio.Event()

        async def _heartbeat_loop() -> None:
            while not stop_heartbeat.is_set():
                await asyncio.sleep(heartbeat_interval_sec)
                if stop_heartbeat.is_set():
                    break
                try:
                    _db = db_factory()
                    try:
                        ok = renew_symbol_lock(_db, account_id, symbol, bot_id, ttl_sec)
                        if not ok:
                            renew_failed.set()
                            logger.warning(
                                "lock_heartbeat_fail account_id=%s bot_id=%s symbol=%s error_code=renew_failed",
                                account_id,
                                bot_id,
                                symbol,
                            )
                            return
                    finally:
                        _db.close()
                except Exception as e:
                    logger.warning(
                        "lock_heartbeat_fail account_id=%s bot_id=%s symbol=%s error_code=renew_error err=%s",
                        account_id,
                        bot_id,
                        symbol,
                        e,
                    )
                    renew_failed.set()
                    return
            return

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            yield True
        finally:
            stop_heartbeat.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
            if renew_failed.is_set():
                logger.warning(
                    "lock_release_ok account_id=%s bot_id=%s symbol=%s after_heartbeat_fail=true",
                    account_id,
                    bot_id,
                    symbol,
                )
    finally:
        if acquired:
            try:
                _db = db_factory()
                try:
                    release_symbol_lock(_db, account_id, symbol, bot_id)
                    logger.info(
                        "lock_release_ok account_id=%s bot_id=%s symbol=%s",
                        account_id,
                        bot_id,
                        symbol,
                    )
                finally:
                    _db.close()
            except Exception as e:
                logger.warning(
                    "lock_release_error account_id=%s bot_id=%s symbol=%s error_code=release_failed err=%s",
                    account_id,
                    bot_id,
                    symbol,
                    e,
                )
        try:
            db.close()
        except Exception:
            pass
