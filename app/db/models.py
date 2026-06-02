"""
FILE: models.py
VERSION: v3
DATE: 2026-01-26
CHANGE: Add Device and DeviceApprovalRequest for device approval / revoke flow
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # Hashed password
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    is_admin = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    is_suspended = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)  # Soft delete flag
    deleted_at = Column(DateTime, nullable=True)  # When account was deleted
    failed_login_attempts = Column(Integer, default=0)
    last_login_at = Column(DateTime, nullable=True)
    last_logout_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(50), nullable=True)
    last_activity_at = Column(DateTime, nullable=True)
    kicked_at = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, unique=True)  # One account per user


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    ip_address = Column(String(50), nullable=False, index=True)
    status = Column(String(20), default="pending")  # pending, approved, rejected
    rejected_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Kayıt sırasında girilen şifrenin hash'i; onayda kullanıcıya bu şifre atanır (yoksa geçici şifre)
    password_hash = Column(String(255), nullable=True)


class BannedIP(Base):
    __tablename__ = "banned_ips"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(50), unique=True, nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    banned_at = Column(DateTime, default=datetime.utcnow)
    unbanned_at = Column(DateTime, nullable=True)


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    status = Column(String(20), default="pending")  # pending, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class Device(Base):
    """Approved devices for a user. device_id is client-generated UUID."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(64), nullable=False, index=True)  # client UUID
    label = Column(String(255), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    last_ip = Column(String(50), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)  # set when created/approved for audit
    revoked_at = Column(DateTime, nullable=True)
    is_initial = Column(Boolean, default=False)  # True = first approved device (e.g. admin PRIMARY)


class DeviceApprovalRequest(Base):
    """Pending new device login - user must approve from existing session."""
    __tablename__ = "device_approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    ip = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, denied, expired
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_device_id = Column(String(64), nullable=True)


class DeviceRevokeAudit(Base):
    """Audit when admin revokes a user's device (e.g. reason=RECOVERY)."""
    __tablename__ = "device_revoke_audits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # target user
    device_id = Column(String(64), nullable=False, index=True)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # admin
    reason = Column(String(64), nullable=True)  # RECOVERY, etc.
    created_at = Column(DateTime, default=datetime.utcnow)


class AllowedIP(Base):
    """İzin verilen IP adresleri – kullanıcı veya admin sadece bu IP'lerden giriş yapabilir."""
    __tablename__ = "allowed_ips"
    __table_args__ = (UniqueConstraint("user_id", "ip", name="uq_allowed_ips_user_ip"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip = Column(String(50), nullable=False, index=True)
    source = Column(String(20), nullable=False, default="manual")  # manual | approved_request | admin_added
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PendingIPRequest(Base):
    """Yeni IP'den giriş denemesi – kullanıcı mevcut oturumdan onaylayıp reddedene kadar bekler."""
    __tablename__ = "pending_ip_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip = Column(String(50), nullable=False, index=True)
    user_agent = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending | approved | denied
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)


class AuditEvent(Base):
    """Güvenlik / işlem geçmişi: giriş, çıkış, cihaz onay, spot, bot, ayar değişiklikleri, admin aksiyonları."""
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_account_created", "target_account_id", "created_at"),
        Index("ix_audit_events_user_created", "target_user_id", "created_at"),
        Index("ix_audit_events_type_created", "event_type", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor_type = Column(String(20), nullable=False, index=True)  # user | admin | system
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    target_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="INFO")  # INFO | WARN | CRITICAL
    ip = Column(String(50), nullable=True)
    ip_masked = Column(Boolean, default=False)  # true = user-facing'de IP gösterilmez (admin aksiyonu)
    device_id = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True)
    session_token_prefix = Column(String(16), nullable=True)  # ilk 6-8 karakter (debug)
    meta_json = Column(Text, nullable=True)  # JSON: orderId, symbol, side, değişen alanlar vb.
    admin_reason = Column(String(255), nullable=True)  # recovery vb.


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    message = Column(String(50), nullable=False)  # Max 50 characters
    ip_address = Column(String(50), nullable=False, index=True)
    status = Column(String(20), default="pending")  # pending, read, replied
    admin_reply = Column(Text, nullable=True)
    ip_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
    replied_at = Column(DateTime, nullable=True)


class ChatThread(Base):
    """One thread per user for admin-user chat. Persists until explicitly cleared."""
    __tablename__ = "chat_threads"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    locked_at = Column(DateTime, nullable=True)  # user cannot send when set
    ended_at = Column(DateTime, nullable=True)  # no one can send when set
    reopened_at = Column(DateTime, nullable=True)  # son "yeni sohbet başlat" zamanı; kullanıcı tarafında ayrış için
    rating = Column(Integer, nullable=True)  # 1-5 when user ends chat with rating
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    """Individual messages in a thread. sender_type: 'user' | 'admin'."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id"), nullable=False, index=True)
    sender_type = Column(String(10), nullable=False)  # 'user' | 'admin'
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)


class ChatRating(Base):
    """Her sohbet sonlandırmasında kullanıcının verdiği puan (1-5). Liste ortalaması için."""
    __tablename__ = "chat_ratings"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("chat_threads.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    created_at = Column(DateTime, default=datetime.utcnow)


class ErrorLog(Base):
    """Olay günlüğü: hatalar (error) + sıra dışı/anormal durumlar (anomaly). Admin panelde listelenir."""
    __tablename__ = "error_logs"
    __table_args__ = (
        # Admin panel "hesap + tarih" sorgularını hızlandırır
        Index("ix_error_logs_account_created", "account_id", "created_at"),
        # Seviye bazlı filtreleme (critical/error/warning)
        Index("ix_error_logs_level_created", "level", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_kind = Column(String(16), nullable=False, default="error", index=True)  # error | anomaly
    anomaly_code = Column(String(64), nullable=True, index=True)  # LOGIN_RATE_LIMIT, REPEATED_LOGIN_FAILURE, vb.
    source = Column(String(32), nullable=False, index=True)  # backend, frontend, binance, ui, server
    level = Column(String(16), nullable=False, default="error")  # error, warning, critical, info
    message = Column(Text, nullable=False)
    detail = Column(Text, nullable=True)  # stack trace veya ek açıklama
    path = Column(String(512), nullable=True)  # endpoint veya sayfa
    method = Column(String(16), nullable=True)
    request_id = Column(String(64), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    user_agent = Column(String(512), nullable=True)
    client_ip = Column(String(50), nullable=True)
    context_json = Column(Text, nullable=True)  # tab, action, button, symbol, bot_id, vs.
    is_admin = Column(Boolean, default=False)  # olay admin tarafından mı oluştu


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_code = Column(String(6), unique=True, nullable=True, index=True)  # 6-digit random code
    name = Column(String(255), nullable=False)
    exchange = Column(String(50), default="BINANCE")
    api_key_enc = Column(Text, nullable=False)  # Encrypted
    api_secret_enc = Column(Text, nullable=False)  # Encrypted
    api_ip_whitelist = Column(Text, nullable=True)  # Comma-separated IPs
    mode = Column(String(20), default="live")  # Always live for now
    is_first_login = Column(Boolean, default=True)  # First login flag
    spot_favorites_json = Column(Text, nullable=True)  # JSON array of symbols, e.g. ["BTCUSDT","ETHUSDT"]
    isolate_from_admin = Column(Boolean, default=False)  # True = admin hesaba giremez, bakiyeler yıldızlı
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)

    bots = relationship("Bot", back_populates="account", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="account")
    pnl_snapshots = relationship("PnlSnapshot", back_populates="account")
    # financial_portfolio relationship - optional, table may not exist in all deployments
    # Use passive_deletes to avoid cascade issues when table doesn't exist
    financial_portfolio = relationship("FinancialPortfolio", back_populates="account", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    # Finance module relationships
    asset_snapshots = relationship("AssetSnapshot", back_populates="account")
    trades_normalized = relationship("TradeNormalized", back_populates="account")
    pnl_positions = relationship("PnlPosition", back_populates="account")
    pnl_realized = relationship("PnlRealized", back_populates="account")


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False)  # e.g., BTCUSDT
    mode = Column(String(20), default="live")
    config_json = Column(Text)  # JSON string
    started_at = Column(DateTime)
    status = Column(String(20), default="stopped")  # stopped, running, paused
    bot_code = Column(String(16), nullable=True, unique=True, index=True)  # 6-digit display id

    account = relationship("Account", back_populates="bots")
    trades = relationship("Trade", back_populates="bot")
    pnl_snapshots = relationship("PnlSnapshot", back_populates="bot")
    trades_normalized = relationship("TradeNormalized", back_populates="bot")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY or SELL
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    fee_asset = Column(String(10), default="USDT")
    slot_id = Column(Integer)  # Grid slot identifier
    reference_price = Column(Float, nullable=True)  # Referans fiyat (gerçekleşme yüzdesi için)
    # Engine ledger (Patch-1): idempotency + reporting
    order_id = Column(String(64), nullable=True, index=True)  # Binance orderId / simulated
    client_order_id = Column(String(64), nullable=True)
    symbol = Column(String(32), nullable=True)
    cycle_id = Column(Integer, nullable=True, default=1)  # Tur/round: 1, 2, 3... (profit-exit/reentry sonrası artar)

    bot = relationship("Bot", back_populates="trades")
    account = relationship("Account", back_populates="trades")


class PnlSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    total_usd = Column(Float, nullable=False)
    realized = Column(Float, default=0.0)
    unrealized = Column(Float, default=0.0)
    daily = Column(Float, default=0.0)
    monthly = Column(Float, default=0.0)

    bot = relationship("Bot", back_populates="pnl_snapshots")
    account = relationship("Account", back_populates="pnl_snapshots")


class FinancialPortfolio(Base):
    __tablename__ = "financial_portfolios"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    items_json = Column(Text)  # JSON array of items: {name, targetWeight, lastValue, quantity}
    last_total_usd = Column(Float, nullable=True)
    current_total_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="financial_portfolio")


class FinancialPortfolioSnapshot(Base):
    __tablename__ = "financial_portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    portfolio_id = Column(Integer, ForeignKey("financial_portfolios.id"), nullable=False, index=True)
    snapshot_ts = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    total_usd = Column(Float, nullable=False)
    items_json = Column(Text)  # JSON array of items at snapshot time
    note = Column(Text, nullable=True)

    account = relationship("Account")
    portfolio = relationship("FinancialPortfolio")


# ============================================
# FINANCE MODULE - Asset Snapshots & Trades
# ============================================

class AssetSnapshot(Base):
    """Portfolio snapshot - zaman serisi için"""
    __tablename__ = "asset_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    total_usd_value = Column(Float, nullable=False)
    breakdown_json = Column(Text)  # JSON: {asset: {free, locked, usdValue, priceUsed}}
    source = Column(String(50), default="rest_snapshot")  # rest_snapshot, websocket, manual

    account = relationship("Account")


class TradeNormalized(Base):
    """Normalized trades from Binance myTrades - tüm işlemler"""
    __tablename__ = "trades_normalized"
    __table_args__ = (
        # Composite unique constraint: same trade_id can exist for different accounts/symbols
        # But within same account+symbol, trade_id must be unique
        UniqueConstraint('account_id', 'symbol', 'trade_id', name='uq_trades_account_symbol_trade'),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    trade_id = Column(String(100), nullable=False, index=True)  # Binance unique tradeId (not unique alone)
    order_id = Column(String(100), nullable=True, index=True)
    side = Column(String(10), nullable=False)  # BUY/SELL
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)
    quote_qty = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    commission_asset = Column(String(10), default="USDT")
    time = Column(DateTime, nullable=False, index=True)
    is_maker = Column(Boolean, default=False)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=True, index=True)
    tags_json = Column(Text, nullable=True)  # JSON: additional tags/metadata

    account = relationship("Account")
    bot = relationship("Bot")


class PnlPosition(Base):
    """Açık pozisyonlar - unrealized PnL için"""
    __tablename__ = "pnl_positions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    avg_entry_price = Column(Float, nullable=False)
    net_qty = Column(Float, nullable=False)  # Positive = long, Negative = short
    cost_basis_usd = Column(Float, nullable=False)
    last_price = Column(Float, nullable=False)
    unrealized_pnl_usd = Column(Float, default=0.0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account")


class PnlRealized(Base):
    """Realized PnL aggregates - günlük/haftalık/aylık cache"""
    __tablename__ = "pnl_realized"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    period_type = Column(String(20), nullable=False, index=True)  # daily/weekly/monthly
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False)
    realized_pnl_usd = Column(Float, default=0.0)
    fees_usd = Column(Float, default=0.0)
    trades_count = Column(Integer, default=0)
    by_symbol_json = Column(Text, nullable=True)  # JSON: {symbol: {pnl, fees, count}}
    by_bot_json = Column(Text, nullable=True)  # JSON: {botId: {pnl, fees, count}}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account")


class AdminPopup(Base):
    """Admin tarafindan yayinlanan pop-up mesajlari. Hedef: ilk giris (first_login) veya normal kullanici (normal_user)."""
    __tablename__ = "admin_popups"

    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(32), nullable=False, index=True)
    title_key = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    valid_until = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Kullanici basina kac kere gosterilecegi; 1 = tek seferlik, 2+ = o kadar kere kapatana kadar tekrar goster
    max_shows_per_user = Column(Integer, nullable=True, default=1)


class AdminPopupDismissal(Base):
    """Kullanici pop-up'i kapatti; tekrar gosterilmez."""
    __tablename__ = "admin_popup_dismissals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    popup_id = Column(Integer, ForeignKey("admin_popups.id"), nullable=False, index=True)
    dismissed_at = Column(DateTime, default=datetime.utcnow)

