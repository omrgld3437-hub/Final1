"""
Bot Models - Config and Slot for Trailing Grid DCA Bot
"""

from typing import Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import json


class SlotState(Enum):
    WAIT = "WAIT"
    TRIGGERED = "TRIGGERED"
    TRAIL = "TRAIL"
    EXECUTED = "EXECUTED"


class QtyMode(Enum):
    FIXED_BASE_QTY = "FIXED_BASE_QTY"
    PCT_OF_BASE_BALANCE = "PCT_OF_BASE_BALANCE"
    PCT_OF_INITIAL_BASE = "PCT_OF_INITIAL_BASE"
    FIXED_QUOTE_NOTIONAL = "FIXED_QUOTE_NOTIONAL"
    PCT_OF_QUOTE_BALANCE = "PCT_OF_QUOTE_BALANCE"
    PCT_OF_INITIAL_QUOTE = "PCT_OF_INITIAL_QUOTE"


class ProceedsMode(Enum):
    ALL_UP_SELL_PROCEEDS = "ALL_UP_SELL_PROCEEDS"
    PCT_OF_AVAILABLE_QUOTE = "PCT_OF_AVAILABLE_QUOTE"
    SELL_ALL_DOWN_BOUGHT_BASE = "SELL_ALL_DOWN_BOUGHT_BASE"
    PCT_OF_BASE_BALANCE = "PCT_OF_BASE_BALANCE"


@dataclass
class GridSlot:
    """Grid slot with trailing logic"""

    slot_id: int
    direction: str  # "UP" or "DOWN"
    target_price: float
    state: SlotState = SlotState.WAIT
    peak_price: Optional[float] = None  # For UP slots
    trough_price: Optional[float] = None  # For DOWN slots
    qty: float = 0.0
    notional_quote: float = 0.0
    executed_price: Optional[float] = None
    executed_qty: float = 0.0
    executed_notional: float = 0.0
    fee: float = 0.0
    pnl: float = 0.0

    def to_dict(self):
        d = asdict(self)
        d["state"] = (
            self.state.value if isinstance(self.state, SlotState) else self.state
        )
        return d


@dataclass
class TrailingGridConfig:
    """Trailing Grid DCA Bot Configuration"""

    # General
    symbol: str
    base_asset: str  # e.g., BTC
    quote_asset: str  # e.g., USDT
    mode: str = "paper"  # paper or live
    bot_budget_quote: float = 1000.0
    alloc_base_pct: float = 50.0
    alloc_quote_pct: float = 50.0

    # UP Grid (sell side)
    up_grid_count: int = 5
    up_grid_step_pct: float = 1.0  # or custom array
    up_grid_steps: Optional[List[float]] = None  # Custom steps
    up_sell_qty_mode: str = "PCT_OF_BASE_BALANCE"
    up_sell_qty_value: float = 20.0  # percentage or fixed
    up_sell_trailing_pct: float = 1.0

    # DOWN Grid (buy side)
    down_grid_count: int = 5
    down_grid_step_pct: float = 1.0
    down_grid_steps: Optional[List[float]] = None
    down_buy_qty_mode: str = "PCT_OF_QUOTE_BALANCE"
    down_buy_qty_value: float = 20.0
    down_buy_trailing_pct: float = 1.0

    # Profit REBUY
    rebuy_trigger_drop_from_avg_sell_pct: float = 1.5
    rebuy_trailing_up_pct: float = 1.0
    rebuy_use_proceeds_mode: str = "ALL_UP_SELL_PROCEEDS"
    rebuy_use_proceeds_value: float = 100.0

    # Profit RESELL
    resell_trigger_rise_from_avg_buy_pct: float = 2.0
    resell_trailing_down_pct: float = 1.0
    resell_sell_mode: str = "SELL_ALL_DOWN_BOUGHT_BASE"
    resell_sell_value: float = 100.0

    # Risk/market rules
    min_notional_quote: float = 10.0
    max_slippage_pct: float = 0.5
    cooldown_ms: int = 1000
    price_stale_ms: int = 3000
    fee_rate: float = 0.001  # 0.1%

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "TrailingGridConfig":
        data = json.loads(json_str) if json_str else {}
        # Convert string enums back if needed
        return cls(**data)

    def validate(self) -> List[str]:
        """Validate configuration, return list of errors"""
        errors = []
        if self.alloc_base_pct + self.alloc_quote_pct != 100.0:
            errors.append("alloc_base_pct + alloc_quote_pct must equal 100")
        if self.up_grid_count < 1:
            errors.append("up_grid_count must be >= 1")
        if self.down_grid_count < 1:
            errors.append("down_grid_count must be >= 1")
        if self.up_sell_trailing_pct <= 0:
            errors.append("up_sell_trailing_pct must be > 0")
        if self.down_buy_trailing_pct <= 0:
            errors.append("down_buy_trailing_pct must be > 0")
        return errors


# Legacy compatibility
@dataclass
class Slot:
    """Legacy slot representation (for backward compatibility)"""

    slot_id: int
    price: float
    qty: float = 0.0
    filled: bool = False
    side: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class BotConfig:
    """Legacy bot configuration"""

    symbol: str
    base_asset: str
    quote_asset: str
    grid_count: int = 10
    upper_price: float = 0.0
    lower_price: float = 0.0
    order_amount: float = 0.0
    mode: str = "paper"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> "BotConfig":
        data = json.loads(json_str) if json_str else {}
        # CRITICAL: Filter out invalid fields (account_id, bot_id, etc.)
        valid_fields = {
            "symbol",
            "base_asset",
            "quote_asset",
            "grid_count",
            "upper_price",
            "lower_price",
            "order_amount",
            "mode",
        }
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        # Explicitly remove account_id and bot_id if they exist
        filtered.pop("account_id", None)
        filtered.pop("bot_id", None)
        filtered.pop("id", None)
        return cls(**filtered)
