"""Decimal-safe contracts used by Dynamic Mode V2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence


ZERO = Decimal("0")
ONE = Decimal("1")


def decimal_value(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif value is None or isinstance(value, bool):
        raise ValueError(f"invalid decimal: {value!r}")
    else:
        result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"non-finite decimal: {value!r}")
    return result


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


class GridRuntimeState(str, Enum):
    WAITING_UNTRIGGERED = "WAITING_UNTRIGGERED"
    TRIGGERED = "TRIGGERED"
    TRAILING_ACTIVE = "TRAILING_ACTIVE"
    ORDER_SUBMITTING = "ORDER_SUBMITTING"
    ORDER_OPEN = "ORDER_OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROFIT_CYCLE_ACTIVE = "PROFIT_CYCLE_ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELED_PENDING_RECONCILIATION = "CANCELED_PENDING_RECONCILIATION"
    ERROR_RECONCILIATION = "ERROR_RECONCILIATION"


@dataclass(frozen=True)
class Candle:
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = ZERO
    closed: bool = True


@dataclass(frozen=True)
class DataQualityResult:
    completeness: Decimal
    freshness: Decimal
    consistency: Decimal
    sequence: Decimal
    outlier: Decimal
    exchange_connection: Decimal
    score: Decimal
    safe_for_full_update: bool
    safe_for_reducing_only: bool
    reasons: Sequence[str] = ()

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class MarketFeatureSnapshot:
    trend_by_timeframe: Mapping[str, Decimal]
    trend_confidence_by_timeframe: Mapping[str, Decimal]
    trend_stability_by_timeframe: Mapping[str, Decimal]
    closure_factor_by_timeframe: Mapping[str, Decimal]
    volatility_by_timeframe: Mapping[str, Decimal]
    downside_volatility_by_timeframe: Mapping[str, Decimal]
    upside_volatility_by_timeframe: Mapping[str, Decimal]
    atr_pct: Decimal
    spread_pct: Decimal
    spread_bps: Decimal
    slippage_pct: Decimal
    depth_percentile: Decimal
    liquidity_instability: Decimal
    mean_reversion_score: Decimal
    failed_breakout_score: Decimal
    bounded_price_score: Decimal
    negative_jump_risk: Decimal
    positive_jump_risk: Decimal
    wick_noise_score: Decimal
    trade_reversal_frequency: Decimal
    long_term_volatility_percentile: Decimal
    jump_frequency_percentile: Decimal
    wick_frequency_percentile: Decimal
    beta_percentile: Decimal
    spread_instability_percentile: Decimal
    listing_age_penalty: Decimal
    support_strength: Decimal
    resistance_strength: Decimal
    data_quality: Decimal


@dataclass(frozen=True)
class ContinuousMarketState:
    trend_score: Decimal
    upward_trend_strength: Decimal
    downward_trend_strength: Decimal
    range_strength: Decimal
    volatility_score: Decimal
    downside_volatility_score: Decimal
    upside_volatility_score: Decimal
    liquidity_risk: Decimal
    coin_risk: Decimal
    negative_jump_risk: Decimal
    positive_jump_risk: Decimal
    micro_noise: Decimal
    spread_risk: Decimal
    support_strength: Decimal
    resistance_strength: Decimal
    data_quality: Decimal
    regime_stability: Decimal
    change_intensity: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class TurnReferenceParameters:
    target_base_ratio: Decimal
    target_quote_ratio: Decimal
    buy_grid_trigger_percentages: Sequence[Decimal]
    sell_grid_trigger_percentages: Sequence[Decimal]
    buy_grid_amounts: Sequence[Decimal]
    sell_grid_amounts: Sequence[Decimal]
    buy_grid_trailing_percentage: Decimal
    sell_grid_trailing_percentage: Decimal
    profit_buy_trigger_percentage: Decimal
    profit_sell_trigger_percentage: Decimal
    profit_buy_trailing_percentage: Decimal
    profit_sell_trailing_percentage: Decimal
    buy_anchor_price: Decimal
    sell_anchor_price: Decimal
    reference_buy_utilization: Decimal = ONE
    reference_sell_utilization: Decimal = ONE
    created_at: datetime = field(default_factory=utc_now)
    source: str = "parameter_assistant"
    formula_version: str = "dynamic-v2.0.0"

    def __post_init__(self) -> None:
        if self.target_base_ratio + self.target_quote_ratio != ONE:
            raise ValueError("reference base + quote must equal 1")
        if not self.buy_grid_trigger_percentages or not self.sell_grid_trigger_percentages:
            raise ValueError("both grid sides must contain at least one grid")
        if len(self.buy_grid_trigger_percentages) != len(self.buy_grid_amounts):
            raise ValueError("buy grid count mismatch")
        if len(self.sell_grid_trigger_percentages) != len(self.sell_grid_amounts):
            raise ValueError("sell grid count mismatch")

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class BalanceSnapshot:
    free_base: Decimal
    locked_base: Decimal
    free_quote: Decimal
    locked_quote: Decimal
    mid_price: Decimal
    snapshot_id: str
    observed_at: datetime

    @property
    def total_base(self) -> Decimal:
        return self.free_base + self.locked_base

    @property
    def total_quote(self) -> Decimal:
        return self.free_quote + self.locked_quote

    @property
    def portfolio_value(self) -> Decimal:
        return self.total_base * self.mid_price + self.total_quote

    @property
    def current_base_ratio(self) -> Decimal:
        total = self.portfolio_value
        return (self.total_base * self.mid_price / total) if total > ZERO else ZERO


@dataclass(frozen=True)
class GridSnapshot:
    grid_id: str
    side: str
    index: int
    status: GridRuntimeState
    trigger_percentage: Decimal
    amount: Decimal
    filled_amount: Decimal = ZERO
    protected_amount: Decimal = ZERO
    exchange_order_id: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: List[str] = field(default_factory=list)

    def reject(self, code: str) -> None:
        self.valid = False
        self.errors.append(code)

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass
class DynamicParameterCandidate:
    target_base_ratio: Decimal
    target_quote_ratio: Decimal
    buy_grid_trigger_percentages: List[Decimal]
    sell_grid_trigger_percentages: List[Decimal]
    buy_grid_amount_weights: List[Decimal]
    sell_grid_amount_weights: List[Decimal]
    buy_grid_amounts: List[Decimal]
    sell_grid_amounts: List[Decimal]
    buy_grid_trailing_percentage: Decimal
    sell_grid_trailing_percentage: Decimal
    profit_buy_trigger_percentage: Decimal
    profit_sell_trigger_percentage: Decimal
    profit_buy_trailing_percentage: Decimal
    profit_sell_trailing_percentage: Decimal
    confidence: Decimal
    risk_flags: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)
    validation_result: ValidationResult = field(default_factory=ValidationResult)
    multipliers: Dict[str, Any] = field(default_factory=dict)
    analysis_run_id: str = ""
    decision_id: str = ""
    state_version: int = 0
    idempotency_key: str = ""
    formula_version: str = "dynamic-v2.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class BudgetLedger:
    target_budget: Decimal
    consumed_budget: Decimal
    protected_budget: Decimal
    remaining_budget: Decimal
    over_target: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return json_value(asdict(self))
