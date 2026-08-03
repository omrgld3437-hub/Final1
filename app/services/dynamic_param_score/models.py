"""Data models for Dynamic Param Score Engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class RegimeTag(str, Enum):
    NO_DATA = "NO_DATA"
    NO_TRADE = "NO_TRADE"
    DUMP_RISK = "DUMP_RISK"
    TRENDING_DOWN = "TRENDING_DOWN"
    HIGH_VOL_UNSTABLE = "HIGH_VOL_UNSTABLE"
    RANGE_LOW_VOL = "RANGE_LOW_VOL"
    RANGE_HIGH_VOL = "RANGE_HIGH_VOL"
    BALANCED_RANGE = "BALANCED_RANGE"
    TRENDING_UP = "TRENDING_UP"
    BREAKOUT_RISK = "BREAKOUT_RISK"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    SPREAD_UNSAFE = "SPREAD_UNSAFE"


class RiskState(str, Enum):
    SAFE = "SAFE"
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    BLOCKED = "BLOCKED"


class FinalAction(str, Enum):
    NO_TRADE = "NO_TRADE"
    WAIT = "WAIT"
    WAIT_SAFETY = "WAIT_SAFETY"
    SAFE_WAIT = "SAFE_WAIT"
    SELL_MANAGEMENT_ONLY = "SELL_MANAGEMENT_ONLY"
    RECOVERY_SELL = "RECOVERY_SELL"
    DEFENSIVE_GRID = "DEFENSIVE_GRID"
    BALANCED_GRID = "BALANCED_GRID"
    LOW_FEE_WIDE_GRID = "LOW_FEE_WIDE_GRID"
    ACTIVE_DEFENSIVE_GRID = "ACTIVE_DEFENSIVE_GRID"
    ACTIVE_GRID = "ACTIVE_GRID"
    TREND_TRAILING = "TREND_TRAILING"
    INITIAL_ENTRY = "INITIAL_ENTRY"
    CONTROLLED_GRID = "CONTROLLED_GRID"


class ScoreBucket(str, Enum):
    BLOCKED = "BLOCKED"
    EXTREME_RISK = "EXTREME_RISK"
    VERY_DEFENSIVE = "VERY_DEFENSIVE"
    DEFENSIVE_LOW = "DEFENSIVE_LOW"
    DEFENSIVE_HIGH = "DEFENSIVE_HIGH"
    BALANCED_LOW = "BALANCED_LOW"
    BALANCED_HIGH = "BALANCED_HIGH"
    ACTIVE_LOW = "ACTIVE_LOW"
    ACTIVE_HIGH = "ACTIVE_HIGH"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"


RunSource = Literal["param_assistant", "dynamic_round_start"]


@dataclass
class Candle:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Candle":
        return cls(
            t=int(d.get("t") or 0),
            o=float(d.get("o") or 0),
            h=float(d.get("h") or 0),
            l=float(d.get("l") or 0),
            c=float(d.get("c") or 0),
            v=float(d.get("v") or 0),
        )


@dataclass
class BtcReferenceData:
    candles_1h: Optional[List[Candle]] = None
    candles_4h: Optional[List[Candle]] = None
    return_1h_pct: Optional[float] = None
    return_4h_pct: Optional[float] = None
    return_24h_pct: Optional[float] = None
    price: Optional[float] = None
    ema200_1h: Optional[float] = None
    volatility_1h: Optional[float] = None
    crash_velocity: Optional[float] = None


@dataclass
class MarketDataBundle:
    symbol: str
    base_asset: str
    quote_asset: str
    ticker_price: float
    volume_24h: float
    quote_volume_24h: float
    market_timestamp: int
    candles_5m: Optional[List[Candle]] = None
    candles_15m: Optional[List[Candle]] = None
    candles_1h: Optional[List[Candle]] = None
    candles_4h: Optional[List[Candle]] = None
    candles_1m: Optional[List[Candle]] = None
    orderbook_top: Optional[Dict[str, Any]] = None
    btc_reference_data: Optional[BtcReferenceData] = None
    data_window: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("candles_1m", "candles_5m", "candles_15m", "candles_1h", "candles_4h"):
            if d.get(k):
                d[k] = [asdict(c) for c in getattr(self, k) or []]
        if self.btc_reference_data:
            d["btc_reference_data"] = asdict(self.btc_reference_data)
        return d


@dataclass
class PortfolioState:
    base_balance: float
    quote_balance: float
    base_value_usdt: float
    quote_value_usdt: float
    total_equity_usdt: float
    current_base_exposure_frac: float
    open_orders_count: int = 0
    open_buy_orders_count: int = 0
    open_sell_orders_count: int = 0
    average_entry_price: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    realized_pnl_cycle_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExchangeConstraints:
    min_notional: float
    step_size: float
    tick_size: float
    min_qty: float
    taker_fee_pct: float
    maker_fee_pct: float
    estimated_slippage_pct: float

    @property
    def total_fee_slippage_pct(self) -> float:
        return self.maker_fee_pct + self.estimated_slippage_pct

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BotContext:
    run_source: RunSource
    budget_usdt: float
    is_first_start: bool = False
    first_start_buy_only: bool = False
    previous_round_id: Optional[str] = None
    current_round_id: Optional[str] = None
    last_rebalance_round_id: Optional[str] = None
    user_risk_level: str = "normal"
    allow_live: bool = True
    allow_no_trade: bool = True
    bot_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BotParams:
    base_alloc_frac: float
    quote_alloc_frac: float
    buy_grid_count: int
    sell_grid_count: int
    buy_grid_spacing_pct: float
    sell_grid_spacing_pct: float
    buy_qty_distribution: List[float]
    sell_qty_distribution: List[float]
    trailing_enabled: bool
    trailing_callback_pct: float
    take_profit_pct: float
    stop_new_buys_below_score: int
    max_base_exposure_frac: float
    max_quote_to_spend_per_buy_frac: float
    downtrend_buy_throttle: bool
    min_cycle_profit_after_fee_pct: float
    emergency_no_buy: bool
    cancel_existing_buy_orders: bool
    cancel_existing_sell_orders: bool
    reason_code: str
    buy_disabled: bool = False
    sell_only_mode: bool = False
    rebuy_enabled: bool = True
    resell_enabled: bool = True
    selected_template_key: Optional[str] = None
    pool_version: Optional[str] = None
    management_mode: Optional[str] = None
    rebalance_policy: Optional[Dict[str, Any]] = None
    buy_grid_ladder_pcts: Optional[List[float]] = None
    sell_grid_ladder_pcts: Optional[List[float]] = None
    rebuy_trigger_pct: Optional[float] = None
    rebuy_trail_pct: Optional[float] = None
    resell_trigger_pct: Optional[float] = None
    resell_trail_pct: Optional[float] = None
    buy_grid_trail_pct: Optional[float] = None
    sell_grid_trail_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubScores:
    trend_score: int = 50
    volatility_score: int = 50
    range_score: int = 50
    liquidity_score: int = 50
    spread_score: int = 50
    momentum_score: int = 50
    mean_reversion_score: int = 50
    drawdown_risk_score: int = 50
    btc_market_risk_score: int = 50
    exposure_safety_score: int = 50
    fee_efficiency_score: int = 50
    data_quality_score: int = 50

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class SafetyGateResult:
    gate_id: str
    passed: bool
    action: str
    reason_code: str
    message: str
    adjustments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DynamicParamDecision:
    decision_id: str
    symbol: str
    timestamp: int
    run_source: RunSource
    final_action: str
    deployable: bool
    param_score: int
    confidence_score: int
    risk_score: int
    regime_tag: str
    risk_state: str
    selected_profile_name: str
    selected_profile_bucket: str
    params: Optional[BotParams]
    safety_gates: List[SafetyGateResult]
    blocking_reasons: List[str]
    warnings: List[str]
    explain: str
    telemetry: Dict[str, Any]
    action_detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["params"] = self.params.to_dict() if self.params else None
        d["safety_gates"] = [g.to_dict() for g in self.safety_gates]
        return d

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:24]


@dataclass
class IndicatorSnapshot:
    """Raw computed indicators for scoring and explain."""
    ema20_5m: Optional[float] = None
    ema50_5m: Optional[float] = None
    ema200_1h: Optional[float] = None
    ema20_slope_5m: Optional[float] = None
    ema50_slope_5m: Optional[float] = None
    price_vs_ema200_pct: Optional[float] = None
    adx_1h: Optional[float] = None
    higher_highs: Optional[bool] = None
    lower_lows: Optional[bool] = None
    atr14_pct_5m: Optional[float] = None
    atr14_pct_1h: Optional[float] = None
    realized_vol_24h: Optional[float] = None
    realized_vol_7d: Optional[float] = None
    volatility_percentile: Optional[float] = None
    high_low_range_pct: Optional[float] = None
    bb_width_5m: Optional[float] = None
    price_in_bb: Optional[float] = None
    mean_reversion_ratio: Optional[float] = None
    z_score_5m: Optional[float] = None
    range_stability: Optional[float] = None
    rsi14_5m: Optional[float] = None
    rsi14_1h: Optional[float] = None
    roc_5m: Optional[float] = None
    return_1h_pct: Optional[float] = None
    return_4h_pct: Optional[float] = None
    return_24h_pct: Optional[float] = None
    quote_volume_24h: Optional[float] = None
    volume_consistency: Optional[float] = None
    zero_volume_ratio: Optional[float] = None
    volume_spike_abnormality: Optional[float] = None
    orderbook_spread_pct: Optional[float] = None
    total_friction_pct: Optional[float] = None
    drawdown_7d_pct: Optional[float] = None
    drawdown_30d_pct: Optional[float] = None
    crash_velocity: Optional[float] = None
    consecutive_red_pressure: Optional[float] = None
    btc_return_1h: Optional[float] = None
    btc_return_4h: Optional[float] = None
    btc_return_24h: Optional[float] = None
    btc_below_ema200: Optional[bool] = None
    btc_crash_velocity: Optional[float] = None
    candle_count_5m: int = 0
    candle_count_15m: int = 0
    candle_count_1h: int = 0
    data_gap_max_ms: int = 0
    data_freshness_sec: float = 0.0
    price_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
