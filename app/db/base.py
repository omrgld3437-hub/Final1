"""
SQLAlchemy Base
Varsayilan: veritabani ~/.trader/dca.db konumunda (proje silinip yeniden kurulunca korunur).
WAL mode: concurrent reads during writes. Separate engines for web (read-heavy) vs worker (write-heavy).
"""

from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Kalici konum: proje silinip yeniden kurulunca veritabani korunur
_DB_DIR = Path.home() / ".trader"
_DB_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT_DB = _DB_DIR / "dca.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB.as_posix()}")


def _sqlite_wal_init(conn, connection_record):
    """On first connect: WAL mode + NORMAL synchronous for concurrent read/write."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")


def _create_engine_for_role(role: str):
    """Create engine with pool_pre_ping, WAL for SQLite, optional PG statement timeout."""
    is_sqlite = "sqlite" in DATABASE_URL
    opts = dict(
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    if is_sqlite:
        # timeout: wait up to 30s for lock (avoids "database is locked" on concurrent access)
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False, "timeout": 30},
            **opts,
        )
        event.listen(engine, "connect", _sqlite_wal_init)
    else:
        # PostgreSQL: optional statement timeout (ms)
        stmt_timeout = os.getenv("PG_STATEMENT_TIMEOUT_MS")
        connect_args = {}
        if stmt_timeout and stmt_timeout.isdigit():
            connect_args["options"] = f"-c statement_timeout={stmt_timeout}"
        engine = create_engine(DATABASE_URL, connect_args=connect_args or None, **opts)
    return engine


# Role: web (read-heavy) vs worker (write-heavy). Each process gets its own engine.
_DB_ROLE = os.getenv("DATABASE_ROLE", "web").strip().lower()
engine = _create_engine_for_role(_DB_ROLE)
engine_web = engine_worker = engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
