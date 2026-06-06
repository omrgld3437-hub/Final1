"""
FILE: models_v2.py
VERSION: v1
DATE: 2026-01-21
CHANGE: DCA Bot V2 models - bidirectional grid + trailing + profit cycle + compound
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class BotV2(Base):
    """Bot V2 main table"""
    __tablename__ = "bots_v2"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False)  # BTCUSDT
    mode = Column(String(20), default="paper")  # paper/live
    status = Column(String(20), default="STOPPED")  # STOPPED/RUNNING/PAUSED

    # Budget
    budget_usdt_initial = Column(Float, nullable=False)
    budget_usdt_current = Column(Float, nullable=False)  # equity
    base_alloc_pct = Column(Float, nullable=False)  # 0-100

    # Reference price
    ref_price_mode = Column(String(20), default="market_now")  # market_now/custom
    ref_price = Column(Float)

    # Settings
    polling_interval_ms = Column(Integer, default=2000)
    slippage_bps = Column(Integer, default=10)  # basis points
    max_active_orders = Column(Integer, default=10)
    taker_fee_bps = Column(Integer, default=10)  # 0.1%
    maker_fee_bps = Column(Integer, default=5)

    # Risk limits
    stop_loss_pct = Column(Float, nullable=True)
    pause_if_balance_below_usdt = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    kill_switch = Column(Boolean, default=False)

    # Cycle settings
    on_cycle_complete = Column(String(20), default="restart_compound")
    reset_ref_price_mode = Column(String(20), default="market_now")
    carry_over_balances = Column(Boolean, default=True)
    max_cycles_per_day = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    balances = relationship("BotBalanceV2", back_populates="bot", uselist=False, cascade="all, delete-orphan")
    grids = relationship("BotGridV2", back_populates="bot", cascade="all, delete-orphan", order_by="BotGridV2.idx")
    cycles = relationship("BotCycleV2", back_populates="bot", cascade="all, delete-orphan")
    trades = relationship("BotTradeV2", back_populates="bot", cascade="all, delete-orphan")
    state = relationship("BotStateV2", back_populates="bot", uselist=False, cascade="all, delete-orphan")


class BotBalanceV2(Base):
    """Bot balance snapshot"""
    __tablename__ = "bot_balances_v2"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots_v2.id"), nullable=False, index=True, unique=True)
    base_asset = Column(String(20), nullable=False)  # BTC
    quote_asset = Column(String(20), nullable=False)  # USDT
    base_free = Column(Float, default=0.0)
    quote_free = Column(Float, default=0.0)
    base_value_usdt = Column(Float, default=0.0)  # computed
    total_value_usdt = Column(Float, default=0.0)  # equity snapshot
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot = relationship("BotV2", back_populates="balances")


class BotGridV2(Base):
    """Grid level configuration and state"""
    __tablename__ = "bot_grids_v2"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots_v2.id"), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # UP_SELL / DOWN_BUY
    idx = Column(Integer, nullable=False)  # order
    trigger_type = Column(String(10), nullable=False)  # PCT / PRICE
    trigger_value = Column(Float, nullable=False)
    trigger_price_abs = Column(Float, nullable=False)  # computed at start/reset
    qty_pct = Column(Float, nullable=False)  # % of available
    trailing_pct = Column(Float, nullable=False)
    min_exec_usdt = Column(Float, default=10.0)
    enabled = Column(Boolean, default=True)

    # State
    state = Column(String(20), default="IDLE")  # IDLE/ARMED/TRAILING/EXECUTED/SKIPPED
    armed_at_price = Column(Float, nullable=True)
    extreme_price = Column(Float, nullable=True)  # peak for UP, dip for DOWN
    threshold_price = Column(Float, nullable=True)  # extreme * (1 ± trailing_pct)

    # Execution results
    executed_qty = Column(Float, default=0.0)
    executed_quote = Column(Float, default=0.0)
    executed_avg_price = Column(Float, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot = relationship("BotV2", back_populates="grids")


class BotCycleV2(Base):
    """Profit cycle tracking"""
    __tablename__ = "bot_cycles_v2"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots_v2.id"), nullable=False, index=True)
    cycle_no = Column(Integer, nullable=False)
    start_ts = Column(DateTime, nullable=False)
    end_ts = Column(DateTime, nullable=True)
    direction = Column(String(20), nullable=True)  # UP / DOWN / MIXED

    # Sell batch (UP grids)
    sell_avg_price = Column(Float, nullable=True)
    sell_total_qty = Column(Float, default=0.0)
    sell_total_quote = Column(Float, default=0.0)

    # Buy batch (DOWN grids)
    buy_avg_price = Column(Float, nullable=True)
    buy_total_qty = Column(Float, default=0.0)
    buy_total_quote = Column(Float, default=0.0)

    # Profit mode
    profit_mode = Column(String(20), nullable=True)  # REBUY / RESELL
    realized_pnl_usdt = Column(Float, default=0.0)
    fees_usdt = Column(Float, default=0.0)

    # Status
    status = Column(String(20), default="OPEN")  # OPEN / CLOSED
    snapshots = Column(JSON, nullable=True)  # optional state snapshots

    bot = relationship("BotV2", back_populates="cycles")


class BotTradeV2(Base):
    """Trade execution records"""
    __tablename__ = "bot_trades_v2"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots_v2.id"), nullable=False, index=True)
    cycle_id = Column(Integer, ForeignKey("bot_cycles_v2.id"), nullable=True, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # BUY / SELL
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    quote_qty = Column(Float, nullable=False)

    # Fees
    fee_asset = Column(String(10), default="USDT")
    fee_qty = Column(Float, default=0.0)
    fee_usdt = Column(Float, default=0.0)

    # Metadata
    reason = Column(String(50), nullable=False)  # GRID_UP_i, GRID_DOWN_i, PROFIT_REBUY, PROFIT_RESELL, INITIAL_ALLOC
    order_id = Column(String(100), nullable=True)  # Binance order ID (live)
    mode = Column(String(20), default="paper")  # paper/live

    bot = relationship("BotV2", back_populates="trades")


class BotStateV2(Base):
    """Engine runtime state (persisted)"""
    __tablename__ = "bot_state_v2"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots_v2.id"), nullable=False, index=True, unique=True)
    state_json = Column(JSON, nullable=False)  # serialized state machine
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot = relationship("BotV2", back_populates="state")


