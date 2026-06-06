"""
FILE: schema_guard.py
VERSION: v1
DATE: 2026-01-26
CHANGE: Startup schema guard for SQLite - add missing device columns without migration.
        Fixes "no such column devices.approved_at" on existing DBs.
        scripts/migrations/init_db.py create_all is unchanged; new installs get full schema from models.
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# devices tablosunda olması gereken kolonlar (id zaten PK, sadece eksikleri ekliyoruz)
DEVICES_COLUMNS = [
    ("user_id", "INTEGER"),
    ("device_id", "VARCHAR(64)"),
    ("label", "VARCHAR(255)"),
    ("user_agent_hash", "VARCHAR(64)"),
    ("last_ip", "VARCHAR(50)"),
    ("last_seen_at", "DATETIME"),
    ("created_at", "DATETIME"),
    ("approved_at", "DATETIME"),
    ("revoked_at", "DATETIME"),
    ("is_initial", "BOOLEAN"),
]

# Opsiyonel kolonlar (yoksa eklenir; VARCHAR/INTEGER SQLite uyumlu)
DEVICES_OPTIONAL_COLUMNS = [
    ("is_admin_device", "BOOLEAN"),
    ("approved_by", "INTEGER"),
]


def _get_existing_columns(conn, table: str) -> set:
    """Return set of column names for table (SQLite PRAGMA table_info)."""
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in result.fetchall()}


def ensure_devices_columns(engine):
    """
    If devices table exists, add any missing columns to the devices table.
    Safe to call multiple times; only adds missing columns.
    """
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
        ))
        if not result.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "devices")
        for col_name, col_type in DEVICES_COLUMNS:
            if col_name in existing:
                continue
            try:
                # SQLite: ADD COLUMN supports LIMITED subset; use TEXT for datetime/boolean for compatibility
                if col_type == "DATETIME":
                    sql_type = "TEXT"
                elif col_type == "BOOLEAN":
                    sql_type = "INTEGER"
                else:
                    sql_type = col_type
                conn.execute(text(f"ALTER TABLE devices ADD COLUMN {col_name} {sql_type}"))
                conn.commit()
                logger.info("schema_guard: added column devices.%s", col_name)
            except Exception as e:
                logger.warning("schema_guard: could not add devices.%s: %s", col_name, e)
                conn.rollback()
        for col_name, col_type in DEVICES_OPTIONAL_COLUMNS:
            if col_name in existing:
                continue
            try:
                sql_type = "INTEGER" if col_type == "BOOLEAN" else col_type
                conn.execute(text(f"ALTER TABLE devices ADD COLUMN {col_name} {sql_type}"))
                conn.commit()
                logger.info("schema_guard: added optional column devices.%s", col_name)
            except Exception as e:
                logger.debug("schema_guard: optional devices.%s: %s", col_name, e)
                conn.rollback()


def ensure_audit_events_table(engine):
    """Create audit_events table if it does not exist (mevcut DB'ler için)."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ))
        if result.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE audit_events (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME,
                    actor_type VARCHAR(20) NOT NULL,
                    actor_user_id INTEGER,
                    target_user_id INTEGER,
                    target_account_id INTEGER,
                    event_type VARCHAR(64) NOT NULL,
                    severity VARCHAR(16) NOT NULL DEFAULT 'INFO',
                    ip VARCHAR(50),
                    ip_masked INTEGER DEFAULT 0,
                    device_id VARCHAR(64),
                    user_agent_hash VARCHAR(64),
                    request_id VARCHAR(64),
                    session_token_prefix VARCHAR(16),
                    meta_json TEXT,
                    admin_reason VARCHAR(255),
                    FOREIGN KEY(actor_user_id) REFERENCES users (id),
                    FOREIGN KEY(target_user_id) REFERENCES users (id),
                    FOREIGN KEY(target_account_id) REFERENCES accounts (id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_audit_events_created_at ON audit_events (created_at)"))
            conn.execute(text("CREATE INDEX ix_audit_events_actor_type ON audit_events (actor_type)"))
            conn.execute(text("CREATE INDEX ix_audit_events_event_type ON audit_events (event_type)"))
            conn.execute(text("CREATE INDEX ix_audit_events_target_account_id ON audit_events (target_account_id)"))
            conn.execute(text("CREATE INDEX ix_audit_events_target_user_id ON audit_events (target_user_id)"))
            conn.execute(text("CREATE INDEX ix_audit_events_account_created ON audit_events (target_account_id, created_at)"))
            conn.execute(text("CREATE INDEX ix_audit_events_user_created ON audit_events (target_user_id, created_at)"))
            conn.execute(text("CREATE INDEX ix_audit_events_type_created ON audit_events (event_type, created_at)"))
            conn.commit()
            logger.info("schema_guard: created table audit_events")
        except Exception as e:
            logger.warning("schema_guard: could not create audit_events: %s", e)
            conn.rollback()


def ensure_chat_threads_rating(engine):
    """Add rating and reopened_at columns to chat_threads if missing."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_threads'"
        ))
        if not result.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "chat_threads")
        if "rating" not in existing:
            try:
                conn.execute(text("ALTER TABLE chat_threads ADD COLUMN rating INTEGER"))
                conn.commit()
                logger.info("schema_guard: added column chat_threads.rating")
            except Exception as e:
                logger.warning("schema_guard: could not add chat_threads.rating: %s", e)
                conn.rollback()
        existing = _get_existing_columns(conn, "chat_threads")
        if "reopened_at" not in existing:
            try:
                conn.execute(text("ALTER TABLE chat_threads ADD COLUMN reopened_at DATETIME"))
                conn.commit()
                logger.info("schema_guard: added column chat_threads.reopened_at")
            except Exception as e:
                logger.warning("schema_guard: could not add chat_threads.reopened_at: %s", e)
                conn.rollback()
        conn.commit()


def ensure_chat_ratings_table(engine):
    """Create chat_ratings table if missing (kullanıcının her sohbet sonundaki puanları, ortalama için)."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_ratings'"
        ))
        if result.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE chat_ratings (
                    id INTEGER NOT NULL PRIMARY KEY,
                    thread_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    created_at DATETIME,
                    FOREIGN KEY(thread_id) REFERENCES chat_threads (id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_chat_ratings_thread_id ON chat_ratings (thread_id)"))
            conn.commit()
            logger.info("schema_guard: created table chat_ratings")
        except Exception as e:
            logger.warning("schema_guard: could not create chat_ratings: %s", e)
            conn.rollback()


def ensure_accounts_isolate_from_admin(engine):
    """Add isolate_from_admin to accounts if missing (kullanıcı 'Adminden İzole Ol' seçeneği)."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
        ))
        if not result.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "accounts")
        if "isolate_from_admin" in existing:
            conn.commit()
            return
        try:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN isolate_from_admin INTEGER DEFAULT 0"))
            conn.commit()
            logger.info("schema_guard: added column accounts.isolate_from_admin")
        except Exception as e:
            logger.warning("schema_guard: could not add accounts.isolate_from_admin: %s", e)
            conn.rollback()
        conn.commit()


def ensure_pending_registrations_password_hash(engine):
    """Add password_hash to pending_registrations if missing (kayıt şifresini onayda kullanmak için)."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_registrations'"
        ))
        if not result.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "pending_registrations")
        if "password_hash" in existing:
            conn.commit()
            return
        try:
            conn.execute(text("ALTER TABLE pending_registrations ADD COLUMN password_hash VARCHAR(255)"))
            conn.commit()
            logger.info("schema_guard: added column pending_registrations.password_hash")
        except Exception as e:
            logger.warning("schema_guard: could not add pending_registrations.password_hash: %s", e)
            conn.rollback()
        conn.commit()


def ensure_error_logs_table(engine):
    """Create error_logs table if it does not exist; add event_kind, anomaly_code if missing."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='error_logs'"
        ))
        if not result.fetchone():
            try:
                conn.execute(text("""
                    CREATE TABLE error_logs (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        created_at DATETIME NOT NULL,
                        event_kind VARCHAR(16) NOT NULL DEFAULT 'error',
                        anomaly_code VARCHAR(64),
                        source VARCHAR(32) NOT NULL,
                        level VARCHAR(16) NOT NULL DEFAULT 'error',
                        message TEXT NOT NULL,
                        detail TEXT,
                        path VARCHAR(512),
                        method VARCHAR(16),
                        request_id VARCHAR(64),
                        user_id INTEGER,
                        account_id INTEGER,
                        user_agent VARCHAR(512),
                        client_ip VARCHAR(50),
                        context_json TEXT,
                        is_admin INTEGER DEFAULT 0,
                        FOREIGN KEY(user_id) REFERENCES users (id),
                        FOREIGN KEY(account_id) REFERENCES accounts (id)
                    )
                """))
                conn.execute(text("CREATE INDEX ix_error_logs_created_at ON error_logs (created_at)"))
                conn.execute(text("CREATE INDEX ix_error_logs_event_kind ON error_logs (event_kind)"))
                conn.execute(text("CREATE INDEX ix_error_logs_anomaly_code ON error_logs (anomaly_code)"))
                conn.execute(text("CREATE INDEX ix_error_logs_source ON error_logs (source)"))
                conn.execute(text("CREATE INDEX ix_error_logs_request_id ON error_logs (request_id)"))
                conn.execute(text("CREATE INDEX ix_error_logs_user_id ON error_logs (user_id)"))
                conn.execute(text("CREATE INDEX ix_error_logs_account_id ON error_logs (account_id)"))
                conn.commit()
                logger.info("schema_guard: created table error_logs")
            except Exception as e:
                logger.warning("schema_guard: could not create error_logs: %s", e)
                conn.rollback()
            conn.commit()
            return
        # Table exists: ensure event_kind and anomaly_code columns exist (migration)
        try:
            r = conn.execute(text("PRAGMA table_info(error_logs)"))
            cols = [row[1] for row in r.fetchall()]
            if "event_kind" not in cols:
                conn.execute(text("ALTER TABLE error_logs ADD COLUMN event_kind VARCHAR(16) NOT NULL DEFAULT 'error'"))
                conn.commit()
                logger.info("schema_guard: added error_logs.event_kind")
            if "anomaly_code" not in cols:
                conn.execute(text("ALTER TABLE error_logs ADD COLUMN anomaly_code VARCHAR(64)"))
                conn.commit()
                logger.info("schema_guard: added error_logs.anomaly_code")
            # Indexes for new columns (ignore if exist)
            try:
                conn.execute(text("CREATE INDEX ix_error_logs_event_kind ON error_logs (event_kind)"))
                conn.commit()
            except Exception:
                pass
            try:
                conn.execute(text("CREATE INDEX ix_error_logs_anomaly_code ON error_logs (anomaly_code)"))
                conn.commit()
            except Exception:
                pass
        except Exception as e:
            logger.warning("schema_guard: error_logs column migration failed: %s", e)
            conn.rollback()
        conn.commit()


def ensure_bot_engine_tables(engine):
    """Create bot_engine_state and bot_engine_events tables for DCA+Grid+Trailing engine."""
    with engine.connect() as conn:
        for name in ("bot_engine_state", "bot_engine_events"):
            r = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
            ), {"n": name})
            if r.fetchone():
                conn.commit()
                continue
            try:
                if name == "bot_engine_state":
                    conn.execute(text("""
                        CREATE TABLE bot_engine_state (
                            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                            bot_id INTEGER NOT NULL,
                            account_id INTEGER NOT NULL,
                            state_json TEXT,
                            cycle_id INTEGER NOT NULL DEFAULT 1,
                            mode VARCHAR(32) NOT NULL DEFAULT 'IDLE',
                            last_tick_at DATETIME,
                            last_error_code VARCHAR(64),
                            retry_at DATETIME,
                            updated_at DATETIME,
                            UNIQUE(bot_id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_bot_engine_state_bot_id ON bot_engine_state (bot_id)"))
                    conn.execute(text("CREATE INDEX ix_bot_engine_state_account_id ON bot_engine_state (account_id)"))
                else:
                    conn.execute(text("""
                        CREATE TABLE bot_engine_events (
                            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                            bot_id INTEGER NOT NULL,
                            account_id INTEGER NOT NULL,
                            ts DATETIME NOT NULL,
                            event_type VARCHAR(64) NOT NULL,
                            message TEXT,
                            meta_json TEXT
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_bot_engine_events_bot_id ON bot_engine_events (bot_id)"))
                    conn.execute(text("CREATE INDEX ix_bot_engine_events_ts ON bot_engine_events (ts)"))
                conn.commit()
                logger.info("schema_guard: created table %s", name)
            except Exception as e:
                logger.warning("schema_guard: could not create %s: %s", name, e)
                conn.rollback()
            conn.commit()


def ensure_bot_engine_commands_table(engine):
    """Web/Worker ayrımı: start/stop komutları worker tarafından işlenir."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_engine_commands'"
        ))
        if r.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE bot_engine_commands (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    account_id INTEGER NOT NULL,
                    bot_id INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    payload_json TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    error_code TEXT,
                    error_id TEXT,
                    request_id TEXT
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_bot_engine_commands_status ON bot_engine_commands (status)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_bot_engine_commands_bot_id ON bot_engine_commands (bot_id)"
            ))
            conn.commit()
            logger.info("schema_guard: created table bot_engine_commands")
        except Exception as e:
            logger.warning("schema_guard: could not create bot_engine_commands: %s", e)
            conn.rollback()
        conn.commit()


def ensure_bot_perf_chart_state_table(engine):
    """Bot performans grafiği state (baseline, samples, range) – yeni tarayıcıda yüklenebilsin."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_perf_chart_state'"
        ))
        if r.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE bot_perf_chart_state (
                    bot_id INTEGER NOT NULL PRIMARY KEY,
                    chart_payload TEXT,
                    updated_at DATETIME
                )
            """))
            conn.execute(text("CREATE INDEX ix_bot_perf_chart_state_bot_id ON bot_perf_chart_state (bot_id)"))
            conn.commit()
            logger.info("schema_guard: created table bot_perf_chart_state")
        except Exception as e:
            logger.warning("schema_guard: could not create bot_perf_chart_state: %s", e)
            conn.rollback()
        conn.commit()


def ensure_trades_engine_columns(engine):
    """Add order_id, client_order_id, symbol to trades for engine ledger (Patch-1)."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        ))
        if not r.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "trades")
        for col_name, sql_type in [
            ("order_id", "VARCHAR(64)"),
            ("client_order_id", "VARCHAR(64)"),
            ("symbol", "VARCHAR(32)"),
            ("cycle_id", "INTEGER"),
            ("reference_price", "FLOAT"),
        ]:
            if col_name in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col_name} {sql_type}"))
                conn.commit()
                logger.info("schema_guard: added column trades.%s", col_name)
            except Exception as e:
                logger.warning("schema_guard: could not add trades.%s: %s", col_name, e)
                conn.rollback()
        conn.commit()


def ensure_symbol_locks_table(engine):
    """Multi-bot: (account_id, symbol) lease lock. One bot per (account, symbol) can send orders at a time."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='symbol_locks'"
        ))
        if r.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE symbol_locks (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    symbol VARCHAR(32) NOT NULL,
                    owner_bot_id INTEGER NOT NULL,
                    lease_until TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(account_id, symbol)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_symbol_locks_account_symbol ON symbol_locks (account_id, symbol)"
            ))
            conn.commit()
            logger.info("schema_guard: created table symbol_locks")
        except Exception as e:
            logger.warning("schema_guard: could not create symbol_locks: %s", e)
            conn.rollback()
        conn.commit()


def ensure_account_daily_realized_pnl_table(engine):
    """Günlük KPI: Bot silindiğinde o günkü gerçekleşen PnL kaybolmasın diye hesap bazlı cache."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='account_daily_realized_pnl'"
        ))
        if r.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE account_daily_realized_pnl (
                    account_id INTEGER NOT NULL,
                    date_tr TEXT NOT NULL,
                    amount_usd REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, date_tr)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_account_daily_realized_pnl_account_date ON account_daily_realized_pnl (account_id, date_tr)"
            ))
            conn.commit()
            logger.info("schema_guard: created table account_daily_realized_pnl")
        except Exception as e:
            logger.warning("schema_guard: could not create account_daily_realized_pnl: %s", e)
            conn.rollback()
        conn.commit()


def ensure_bot_virtual_wallet_table(engine):
    """Multi-bot: per-bot virtual base/quote sub-wallet for budget check and fill updates."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_virtual_wallet'"
        ))
        if r.fetchone():
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE bot_virtual_wallet (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    symbol VARCHAR(32) NOT NULL,
                    virtual_base REAL NOT NULL DEFAULT 0,
                    virtual_quote REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(bot_id, symbol)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_bot_virtual_wallet_bot_id ON bot_virtual_wallet (bot_id)"
            ))
            conn.commit()
            logger.info("schema_guard: created table bot_virtual_wallet")
        except Exception as e:
            logger.warning("schema_guard: could not create bot_virtual_wallet: %s", e)
            conn.rollback()
        conn.commit()


def ensure_bots_bot_code(engine):
    """Add bot_code column to bots if missing. 6-digit random display id."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bots'"
        ))
        if not r.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "bots")
        if "bot_code" in existing:
            conn.commit()
            return
        try:
            conn.execute(text(
                "ALTER TABLE bots ADD COLUMN bot_code VARCHAR(16)"
            ))
            conn.commit()
            logger.info("schema_guard: added column bots.bot_code")
        except Exception as e:
            logger.warning("schema_guard: could not add bots.bot_code: %s", e)
            conn.rollback()
        conn.commit()


def ensure_core_tables(engine):
    """Create core tables (accounts, bots, etc.) from models if they don't exist. init_db.py ayrıca çalıştırılabilir; yoksa ilk açılışta otomatik oluşturulur."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bots'"
        ))
        if r.fetchone():
            conn.commit()
            return
    from app.db.base import Base
    from app.db import models  # noqa: F401 - register all models
    Base.metadata.create_all(bind=engine)
    logger.info("schema_guard: created core tables (accounts, bots, etc.)")


def run_schema_guard(engine):
    """Entry point: ensure core tables + devices columns + audit_events table + chat_threads.rating + chat_ratings + pending_registrations.password_hash + accounts.isolate_from_admin + error_logs + bot_engine_state/events. Call once at startup."""
    try:
        ensure_core_tables(engine)
        ensure_devices_columns(engine)
        ensure_audit_events_table(engine)
        ensure_chat_threads_rating(engine)
        ensure_chat_ratings_table(engine)
        ensure_pending_registrations_password_hash(engine)
        ensure_accounts_isolate_from_admin(engine)
        ensure_error_logs_table(engine)
        ensure_bot_engine_tables(engine)
        ensure_bot_engine_commands_table(engine)
        ensure_bot_perf_chart_state_table(engine)
        ensure_trades_engine_columns(engine)
        ensure_bots_bot_code(engine)
        ensure_symbol_locks_table(engine)
        ensure_bot_virtual_wallet_table(engine)
        ensure_account_daily_realized_pnl_table(engine)
        ensure_order_intents_table(engine)
        ensure_sessions_table(engine)
        ensure_admin_popups_table(engine)
        ensure_bot_public_metrics_table(engine)
    except Exception as e:
        logger.exception("schema_guard failed: %s", e)


def ensure_bot_public_metrics_table(engine):
    """Leaderboard: bot_public_metrics – profit_pct + sanitized params only (no username/balance)."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_public_metrics'"
        ))
        if not r.fetchone():
            try:
                conn.execute(text("""
                    CREATE TABLE bot_public_metrics (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        bot_id INTEGER NOT NULL UNIQUE,
                        account_id INTEGER NOT NULL,
                        structure_id VARCHAR(64) NOT NULL,
                        profit_pct_all REAL NOT NULL,
                        profit_pct_7d REAL,
                        profit_pct_30d REAL,
                        params_sanitized_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_bpm_structure_profit_all ON bot_public_metrics (structure_id, profit_pct_all DESC)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_bpm_profit_all ON bot_public_metrics (profit_pct_all DESC)"
                ))
                conn.commit()
                logger.info("schema_guard: created table bot_public_metrics")
            except Exception as e:
                logger.warning("schema_guard: could not create bot_public_metrics: %s", e)
                conn.rollback()
        conn.commit()


def ensure_admin_popups_table(engine):
    """Admin pop-up mesajlari ve kullanici kapatma kayitlari."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='admin_popups'"
        ))
        if not r.fetchone():
            try:
                conn.execute(text("""
                    CREATE TABLE admin_popups (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        target VARCHAR(32) NOT NULL,
                        title_key VARCHAR(64) NOT NULL,
                        message TEXT NOT NULL,
                        valid_until DATETIME NOT NULL,
                        created_at DATETIME,
                        created_by INTEGER REFERENCES users(id),
                        max_shows_per_user INTEGER DEFAULT 1
                    )
                """))
                conn.execute(text("CREATE INDEX ix_admin_popups_target ON admin_popups (target)"))
                conn.execute(text("CREATE INDEX ix_admin_popups_valid_until ON admin_popups (valid_until)"))
                conn.commit()
                logger.info("schema_guard: created table admin_popups")
            except Exception as e:
                logger.warning("schema_guard: could not create admin_popups: %s", e)
                conn.rollback()
        # Mevcut tabloya max_shows_per_user ekle (yoksa)
        try:
            rcol = conn.execute(text("PRAGMA table_info(admin_popups)"))
            cols = [row[1] for row in rcol.fetchall()]
            if "max_shows_per_user" not in cols:
                conn.execute(text("ALTER TABLE admin_popups ADD COLUMN max_shows_per_user INTEGER DEFAULT 1"))
                conn.commit()
                logger.info("schema_guard: added column admin_popups.max_shows_per_user")
        except Exception as e:
            logger.warning("schema_guard: admin_popups max_shows_per_user add column: %s", e)
            conn.rollback()
        r2 = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='admin_popup_dismissals'"
        ))
        if not r2.fetchone():
            try:
                conn.execute(text("""
                    CREATE TABLE admin_popup_dismissals (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        popup_id INTEGER NOT NULL REFERENCES admin_popups(id),
                        dismissed_at DATETIME
                    )
                """))
                conn.execute(text("CREATE INDEX ix_admin_popup_dismissals_user_id ON admin_popup_dismissals (user_id)"))
                conn.execute(text("CREATE INDEX ix_admin_popup_dismissals_popup_id ON admin_popup_dismissals (popup_id)"))
                conn.commit()
                logger.info("schema_guard: created table admin_popup_dismissals")
            except Exception as e:
                logger.warning("schema_guard: could not create admin_popup_dismissals: %s", e)
                conn.rollback()
        conn.commit()


def ensure_order_intents_table(engine):
    """Bot Engine v5: intent_id, client_order_id UNIQUE, full state machine. Intent persist BEFORE place_order."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='order_intents'"
        ))
        if r.fetchone():
            ensure_order_intents_v5_columns(engine)
            conn.commit()
            return
        try:
            conn.execute(text("""
                CREATE TABLE order_intents (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL,
                    bot_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL DEFAULT 'MARKET',
                    qty REAL NOT NULL,
                    price REAL NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    binance_order_id TEXT NULL,
                    status TEXT NOT NULL DEFAULT 'NEW',
                    submit_attempts INTEGER NOT NULL DEFAULT 0,
                    last_submit_ts REAL NULL,
                    filled_qty REAL NOT NULL DEFAULT 0,
                    avg_price REAL NULL,
                    last_error_code TEXT NULL,
                    last_error_id TEXT NULL,
                    final_ts REAL NULL,
                    metadata_json TEXT,
                    UNIQUE(intent_id),
                    UNIQUE(client_order_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_order_intents_intent_id ON order_intents (intent_id)"))
            conn.execute(text("CREATE UNIQUE INDEX ix_order_intents_client_order_id ON order_intents (client_order_id)"))
            conn.execute(text("CREATE INDEX ix_order_intents_bot_account ON order_intents (bot_id, account_id)"))
            conn.execute(text("CREATE INDEX ix_order_intents_account_status ON order_intents (account_id, status)"))
            conn.execute(text("CREATE INDEX ix_order_intents_bot_status ON order_intents (bot_id, status)"))
            conn.execute(text("CREATE INDEX ix_order_intents_symbol_status ON order_intents (symbol, status)"))
            conn.execute(text("CREATE INDEX ix_order_intents_binance_order_id ON order_intents (binance_order_id)"))
            conn.commit()
            logger.info("schema_guard: created table order_intents (v5)")
        except Exception as e:
            logger.warning("schema_guard: could not create order_intents: %s", e)
            conn.rollback()
        conn.commit()


def ensure_order_intents_v5_columns(engine):
    """Add v5 columns to existing order_intents table."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='order_intents'"
        ))
        if not r.fetchone():
            conn.commit()
            return
        existing = _get_existing_columns(conn, "order_intents")
        # Map old price_type -> order_type if needed
        for col_name, sql_type in [
            ("order_type", "TEXT"),
            ("price", "REAL"),
            ("submit_attempts", "INTEGER"),
            ("last_submit_ts", "REAL"),
            ("filled_qty", "REAL"),
            ("avg_price", "REAL"),
            ("last_error_code", "TEXT"),
            ("last_error_id", "TEXT"),
            ("final_ts", "REAL"),
        ]:
            if col_name in existing:
                continue
            try:
                default = "0" if col_name in ("submit_attempts", "filled_qty") else "NULL"
                if col_name == "order_type":
                    default = "'MARKET'"
                conn.execute(text(f"ALTER TABLE order_intents ADD COLUMN {col_name} {sql_type} DEFAULT {default}"))
                conn.commit()
                logger.info("schema_guard: added column order_intents.%s", col_name)
            except Exception as e:
                logger.warning("schema_guard: could not add order_intents.%s: %s", col_name, e)
                conn.rollback()
        # Ensure status can hold v5 values (NEW, PERSISTED, SUBMITTING, SUBMITTED, etc.) - no change needed
        # Create v5 indices if missing
        for idx_name, idx_sql in [
            ("ix_order_intents_account_status", "CREATE INDEX ix_order_intents_account_status ON order_intents (account_id, status)"),
            ("ix_order_intents_bot_status", "CREATE INDEX ix_order_intents_bot_status ON order_intents (bot_id, status)"),
            ("ix_order_intents_symbol_status", "CREATE INDEX ix_order_intents_symbol_status ON order_intents (symbol, status)"),
            ("ix_order_intents_binance_order_id", "CREATE INDEX ix_order_intents_binance_order_id ON order_intents (binance_order_id)"),
            ("ix_trades_normalized_account_time", "CREATE INDEX ix_trades_normalized_account_time ON trades_normalized (account_id, time)"),
        ]:
            try:
                r = conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=:n"
                ), {"n": idx_name})
                if r.fetchone():
                    continue
                conn.execute(text(idx_sql))
                conn.commit()
                logger.info("schema_guard: created index %s", idx_name)
            except Exception as e:
                logger.debug("schema_guard: index %s: %s", idx_name, e)
                conn.rollback()
        conn.commit()


def ensure_sessions_table(engine):
    """Shared session store for multi-worker auth. token -> {user_id, account_id, is_admin, boot_id}. Sliding TTL via last_seen_at."""
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_sessions'"
        ))
        if not r.fetchone():
            try:
                conn.execute(text("""
                    CREATE TABLE auth_sessions (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        token_hash VARCHAR(64) NOT NULL UNIQUE,
                        user_id INTEGER NOT NULL,
                        account_id INTEGER,
                        is_admin INTEGER NOT NULL DEFAULT 0,
                        boot_id VARCHAR(32) NOT NULL,
                        device_id VARCHAR(64),
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        last_seen_at TEXT,
                        revoked INTEGER NOT NULL DEFAULT 0
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_auth_sessions_token_hash ON auth_sessions (token_hash)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_auth_sessions_expires ON auth_sessions (expires_at)"
                ))
                conn.commit()
                logger.info("schema_guard: created table auth_sessions")
            except Exception as e:
                logger.warning("schema_guard: could not create auth_sessions: %s", e)
                conn.rollback()
            conn.commit()
            return
        # Table exists: add last_seen_at if missing (sliding TTL)
        existing = _get_existing_columns(conn, "auth_sessions")
        if "last_seen_at" not in existing:
            try:
                conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN last_seen_at TEXT"))
                conn.commit()
                logger.info("schema_guard: added column auth_sessions.last_seen_at")
            except Exception as e:
                logger.warning("schema_guard: could not add auth_sessions.last_seen_at: %s", e)
                conn.rollback()
        if "revoked" not in existing:
            try:
                conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0"))
                conn.commit()
                logger.info("schema_guard: added column auth_sessions.revoked")
            except Exception as e:
                logger.warning("schema_guard: could not add auth_sessions.revoked: %s", e)
                conn.rollback()
        conn.commit()
