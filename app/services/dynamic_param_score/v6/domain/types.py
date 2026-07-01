"""V6 domain types — catalog profile, input contract, adjuster deltas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

SeverityMode = Literal["DEF", "STD", "ACT"]


@dataclass
class GridLevel:
    distance_pct: int  # signed, lattice-quantized
    amount_pct: int  # 5% steps, side sums to 100


@dataclass
class ScenarioIdentity:
    regime_id: str  # R1..R8
    sub_id: str  # 01..63 zero-padded
    micro_id: str  # 01..231
    behavior_id: str  # PB01..PB765
    severity: SeverityMode
    terminal_id: str = ""
    name: str = ""


@dataclass
class V6CatalogProfile:
    profile_id: str
    scenario: ScenarioIdentity
    base_allocation_pct: int
    quote_allocation_pct: int
    initial_base_allocation: bool = True
    normal_buy_enabled: bool = True
    buy_grids: List[GridLevel] = field(default_factory=list)
    sell_grids: List[GridLevel] = field(default_factory=list)
    sell_trailing_code: str = "T2"
    buy_trailing_code: str = "T2"
    buyback_after_sell_enabled: bool = False
    buyback_trigger_code: str = "K10"
    buyback_trailing_code: str = "T2"
    profit_sell_after_buyback_enabled: bool = False
    profit_sell_trigger_code: str = "K10"
    profit_sell_trailing_code: str = "T2"
    modules: Dict[str, bool] = field(default_factory=dict)

    def copy(self) -> "V6CatalogProfile":
        return V6CatalogProfile(
            profile_id=self.profile_id,
            scenario=ScenarioIdentity(
                regime_id=self.scenario.regime_id,
                sub_id=self.scenario.sub_id,
                micro_id=self.scenario.micro_id,
                behavior_id=self.scenario.behavior_id,
                severity=self.scenario.severity,
                terminal_id=self.scenario.terminal_id,
                name=self.scenario.name,
            ),
            base_allocation_pct=self.base_allocation_pct,
            quote_allocation_pct=self.quote_allocation_pct,
            initial_base_allocation=self.initial_base_allocation,
            normal_buy_enabled=self.normal_buy_enabled,
            buy_grids=[GridLevel(g.distance_pct, g.amount_pct) for g in self.buy_grids],
            sell_grids=[GridLevel(g.distance_pct, g.amount_pct) for g in self.sell_grids],
            sell_trailing_code=self.sell_trailing_code,
            buy_trailing_code=self.buy_trailing_code,
            buyback_after_sell_enabled=self.buyback_after_sell_enabled,
            buyback_trigger_code=self.buyback_trigger_code,
            buyback_trailing_code=self.buyback_trailing_code,
            profit_sell_after_buyback_enabled=self.profit_sell_after_buyback_enabled,
            profit_sell_trigger_code=self.profit_sell_trigger_code,
            profit_sell_trailing_code=self.profit_sell_trailing_code,
            modules=dict(self.modules),
        )


@dataclass
class AdjusterDelta:
    base_delta_steps: int = 0
    buy_grid_distance_delta: int = 0
    sell_grid_distance_delta: int = 0
    buyback_trigger_delta: float = 0.0
    profit_sell_trigger_delta: float = 0.0
    buy_trailing_delta_steps: int = 0
    sell_trailing_delta_steps: int = 0
    buy_grid_count_delta: int = 0
    sell_grid_count_delta: int = 0
    normal_buy_override: Optional[bool] = None
    severity_override: Optional[SeverityMode] = None
    tags: List[str] = field(default_factory=list)

    def merge(self, other: "AdjusterDelta") -> None:
        self.base_delta_steps += other.base_delta_steps
        self.buy_grid_distance_delta += other.buy_grid_distance_delta
        self.sell_grid_distance_delta += other.sell_grid_distance_delta
        self.buyback_trigger_delta += other.buyback_trigger_delta
        self.profit_sell_trigger_delta += other.profit_sell_trigger_delta
        self.buy_trailing_delta_steps += other.buy_trailing_delta_steps
        self.sell_trailing_delta_steps += other.sell_trailing_delta_steps
        self.buy_grid_count_delta += other.buy_grid_count_delta
        self.sell_grid_count_delta += other.sell_grid_count_delta
        if other.normal_buy_override is not None:
            self.normal_buy_override = other.normal_buy_override
        if other.severity_override is not None:
            self.severity_override = other.severity_override
        self.tags.extend(other.tags)


@dataclass
class V6InputContract:
    symbol: str
    bot_budget_usdt: float
    current_price: float
    min_notional: float
    tick_size: float
    step_size: float
    price_precision: int
    quantity_precision: int
    # Trend / momentum
    adx_1h: Optional[float] = None
    rsi_5m: Optional[float] = None
    rsi_1h: Optional[float] = None
    ema20_slope: Optional[float] = None
    ema50_slope: Optional[float] = None
    ema20_5m: Optional[float] = None
    ema50_5m: Optional[float] = None
    ema200_1h: Optional[float] = None
    price_vs_ema200_pct: Optional[float] = None
    roc_5m: Optional[float] = None
    higher_highs: Optional[bool] = None
    lower_lows: Optional[bool] = None
    # Volatility / range
    atr_5m_pct: Optional[float] = None
    atr_1h_pct: Optional[float] = None
    vol_24h: Optional[float] = None
    vol_7d: Optional[float] = None
    volatility_percentile: Optional[float] = None
    bb_width: Optional[float] = None
    bb_position: Optional[float] = None
    z_score: Optional[float] = None
    mean_reversion_score: Optional[float] = None
    range_stability: Optional[float] = None
    hl_range_pct: Optional[float] = None
    # Return / risk
    return_1h_pct: Optional[float] = None
    return_4h_pct: Optional[float] = None
    return_24h_pct: Optional[float] = None
    drawdown_7d_pct: Optional[float] = None
    drawdown_30d_pct: Optional[float] = None
    crash_velocity: Optional[float] = None
    red_pressure: Optional[float] = None
    # Liquidity (no fee fields)
    spread_pct: Optional[float] = None
    volume_24h: Optional[float] = None
    volume_consistency: Optional[float] = None
    volume_spike: Optional[float] = None
    zero_volume_flag: int = 0
    # BTC context
    btc_ema200_below: Optional[bool] = None
    btc_crash_velocity: Optional[float] = None
    btc_return_1h_pct: Optional[float] = None
    btc_return_4h_pct: Optional[float] = None
    btc_return_24h_pct: Optional[float] = None
    # Data quality
    data_freshness_sec: Optional[float] = None
    data_gap_sec: Optional[float] = None
    candles_5m: int = 0
    candles_15m: int = 0
    candles_1h: int = 0
    price_valid: bool = True
    # Support / resistance
    support_distance_pct: Optional[float] = None
    resistance_distance_pct: Optional[float] = None
    support_strength_score: Optional[float] = None
    resistance_strength_score: Optional[float] = None
    # Fake move scores 0-100
    pump_score: float = 0.0
    dump_score: float = 0.0
    fake_bounce_score: float = 0.0
    fake_breakout_score: float = 0.0
    asset_fragility_class: str = "F1"


@dataclass
class V6FinalProfile:
    catalog_profile_id: str
    final_profile_id: str
    full_param_id: str
    profile: V6CatalogProfile
    deployable: bool
    deploy_block_reason: Optional[str] = None
    adjuster_tags: List[str] = field(default_factory=list)
    telemetry: Dict[str, Any] = field(default_factory=dict)
