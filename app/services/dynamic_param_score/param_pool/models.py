"""Param Template Pool — data models and tier classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT


class ProfileSubfamily(str, Enum):
    """Precision v2 subfamilies — metadata under profile_family."""
    PRECISION_INITIAL_ENTRY = "PRECISION_INITIAL_ENTRY_PROFILE"
    GRADUAL_REBALANCE_BUY = "GRADUAL_REBALANCE_BUY_PROFILE"
    GRADUAL_REBALANCE_SELL = "GRADUAL_REBALANCE_SELL_PROFILE"
    PASSIVE_REBALANCE = "PASSIVE_REBALANCE_PROFILE"
    HIGH_MOMENTUM_CONTROLLED_ENTRY = "HIGH_MOMENTUM_CONTROLLED_ENTRY_PROFILE"
    TREND_UP_TRAILING_ENTRY = "TREND_UP_TRAILING_ENTRY_PROFILE"
    TREND_DOWN_RECOVERY_SELL = "TREND_DOWN_RECOVERY_SELL_PROFILE"
    FEE_WEAK_WIDE_GRID = "FEE_WEAK_WIDE_GRID_PROFILE"
    MICRO_BUDGET_SINGLE_ORDER = "MICRO_BUDGET_SINGLE_ORDER_PROFILE"
    SMALL_BUDGET_TWO_STEP_GRID = "SMALL_BUDGET_TWO_STEP_GRID_PROFILE"
    ORDERBOOK_TIGHT_WAIT = "ORDERBOOK_TIGHT_WAIT_PROFILE"
    ORDERBOOK_GOOD_ACTIVE = "ORDERBOOK_GOOD_ACTIVE_PROFILE"
    BTC_SUPPORTIVE_ACTIVE = "BTC_SUPPORTIVE_ACTIVE_PROFILE"
    BTC_PRESSURE_DEFENSIVE = "BTC_PRESSURE_DEFENSIVE_PROFILE"
    VOL_EXTREME_SAFE_WAIT = "VOL_EXTREME_SAFE_WAIT_PROFILE"
    VOL_LOW_NOISE_WAIT = "VOL_LOW_NOISE_WAIT_PROFILE"
    BREAKOUT_RISK_PASSIVE = "BREAKOUT_RISK_PASSIVE_PROFILE"


class ProfileFamily(str, Enum):
    NO_TRADE = "NO_TRADE_PROFILE"
    WAIT = "WAIT_PROFILE"
    SELL_MANAGEMENT_ONLY = "SELL_MANAGEMENT_ONLY_PROFILE"
    ULTRA_DEFENSIVE_GRID = "ULTRA_DEFENSIVE_GRID_PROFILE"
    DEFENSIVE_GRID = "DEFENSIVE_GRID_PROFILE"
    CAUTIOUS_BALANCED_GRID = "CAUTIOUS_BALANCED_GRID_PROFILE"
    BALANCED_GRID = "BALANCED_GRID_PROFILE"
    ACTIVE_RANGE_GRID = "ACTIVE_RANGE_GRID_PROFILE"
    HIGH_CONFIDENCE_ACTIVE_GRID = "HIGH_CONFIDENCE_ACTIVE_GRID_PROFILE"
    TREND_TRAILING = "TREND_TRAILING_PROFILE"
    BREAKOUT_PROTECTION = "BREAKOUT_PROTECTION_PROFILE"
    RECOVERY_SELL = "RECOVERY_SELL_PROFILE"
    LOW_FEE_WIDE_GRID = "LOW_FEE_WIDE_GRID_PROFILE"
    ACTIVE_DEFENSIVE_GRID = "ACTIVE_DEFENSIVE_GRID_PROFILE"
    HIGH_VOL_PROTECTION = "HIGH_VOL_PROTECTION_PROFILE"
    LOW_LIQUIDITY_WAIT = "LOW_LIQUIDITY_WAIT_PROFILE"
    INITIAL_ENTRY = "INITIAL_ENTRY_PROFILE"
    SMALL_BUDGET_SAFE = "SMALL_BUDGET_SAFE_PROFILE"
    MICRO_BUDGET_WAIT = "MICRO_BUDGET_WAIT_PROFILE"
    OVEREXPOSED_REDUCTION = "OVEREXPOSED_REDUCTION_PROFILE"


class LiquidityTier(str, Enum):
    LIQ_BAD = "LIQ_BAD"
    LIQ_WEAK = "LIQ_WEAK"
    LIQ_OK = "LIQ_OK"
    LIQ_GOOD = "LIQ_GOOD"
    LIQ_EXCELLENT = "LIQ_EXCELLENT"


class VolatilityTier(str, Enum):
    VOL_TOO_LOW = "VOL_TOO_LOW"
    VOL_LOW = "VOL_LOW"
    VOL_NORMAL = "VOL_NORMAL"
    VOL_HIGH = "VOL_HIGH"
    VOL_EXTREME = "VOL_EXTREME"


class BtcRiskTier(str, Enum):
    BTC_RISK_BLOCKED = "BTC_RISK_BLOCKED"
    BTC_RISK_HIGH = "BTC_RISK_HIGH"
    BTC_RISK_MEDIUM = "BTC_RISK_MEDIUM"
    BTC_RISK_LOW = "BTC_RISK_LOW"
    BTC_RISK_SUPPORTIVE = "BTC_RISK_SUPPORTIVE"


class OrderRealityTier(str, Enum):
    ORDER_IMPOSSIBLE = "ORDER_IMPOSSIBLE"
    ORDER_TIGHT = "ORDER_TIGHT"
    ORDER_OK = "ORDER_OK"
    ORDER_COMFORTABLE = "ORDER_COMFORTABLE"


class BudgetTier(str, Enum):
    NANO = "NANO"
    MICRO = "MICRO"
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    WHALE = "WHALE"


class ExposureTier(str, Enum):
    NO_BASE = "NO_BASE"
    LOW_BASE = "LOW_BASE"
    TARGET_BASE = "TARGET_BASE"
    HIGH_BASE = "HIGH_BASE"
    OVEREXPOSED = "OVEREXPOSED"


class HeadroomTier(str, Enum):
    NO_HEADROOM = "NO_HEADROOM"
    LOW_HEADROOM = "LOW_HEADROOM"
    MEDIUM_HEADROOM = "MEDIUM_HEADROOM"
    GOOD_HEADROOM = "GOOD_HEADROOM"


class FeeTier(str, Enum):
    FEE_BAD = "FEE_BAD"
    FEE_WEAK = "FEE_WEAK"
    FEE_OK = "FEE_OK"
    FEE_GOOD = "FEE_GOOD"
    FEE_EXCELLENT = "FEE_EXCELLENT"


# Turkish display labels for tiers and profile families
PROFILE_FAMILY_TR: Dict[str, str] = {
    ProfileFamily.NO_TRADE.value: "işlem yok",
    ProfileFamily.WAIT.value: "bekle",
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: "yalnızca satış yönetimi",
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: "ultra savunmacı grid",
    ProfileFamily.DEFENSIVE_GRID.value: "savunmacı grid",
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: "temkinli dengeli grid",
    ProfileFamily.BALANCED_GRID.value: "dengeli grid",
    ProfileFamily.ACTIVE_RANGE_GRID.value: "aktif aralık grid",
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: "yüksek güven aktif grid",
    ProfileFamily.TREND_TRAILING.value: "trend trailing",
    ProfileFamily.BREAKOUT_PROTECTION.value: "kırılım koruması",
    ProfileFamily.RECOVERY_SELL.value: "toparlanma satışı",
    ProfileFamily.LOW_FEE_WIDE_GRID.value: "düşük fee geniş grid",
    ProfileFamily.ACTIVE_DEFENSIVE_GRID.value: "aktif savunmacı grid",
    ProfileFamily.HIGH_VOL_PROTECTION.value: "yüksek volatilite koruması",
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: "düşük likidite bekle",
    ProfileFamily.INITIAL_ENTRY.value: "ilk giriş",
    ProfileFamily.SMALL_BUDGET_SAFE.value: "küçük bütçe güvenli",
    ProfileFamily.MICRO_BUDGET_WAIT.value: "mikro bütçe bekle",
    ProfileFamily.OVEREXPOSED_REDUCTION.value: "aşırı maruz azaltma",
}

BUDGET_TIER_TR: Dict[str, str] = {
    BudgetTier.NANO.value: "nano bütçe (0–24 USDT)",
    BudgetTier.MICRO.value: "mikro bütçe (25–49 USDT)",
    BudgetTier.SMALL.value: "küçük bütçe (50–99 USDT)",
    BudgetTier.STANDARD.value: "standart bütçe (100–249 USDT)",
    BudgetTier.MEDIUM.value: "orta bütçe (250–999 USDT)",
    BudgetTier.LARGE.value: "büyük bütçe (1000–4999 USDT)",
    BudgetTier.WHALE.value: "whale bütçe (5000+ USDT)",
}

EXPOSURE_TIER_TR: Dict[str, str] = {
    ExposureTier.NO_BASE.value: "base yok (0–5%)",
    ExposureTier.LOW_BASE.value: "düşük base (5–25%)",
    ExposureTier.TARGET_BASE.value: "hedef base (25–55%)",
    ExposureTier.HIGH_BASE.value: "yüksek base (55–75%)",
    ExposureTier.OVEREXPOSED.value: "aşırı maruz (75%+)",
}

HEADROOM_TIER_TR: Dict[str, str] = {
    HeadroomTier.NO_HEADROOM.value: "headroom yok",
    HeadroomTier.LOW_HEADROOM.value: "düşük headroom",
    HeadroomTier.MEDIUM_HEADROOM.value: "orta headroom",
    HeadroomTier.GOOD_HEADROOM.value: "iyi headroom",
}

FEE_TIER_TR: Dict[str, str] = {
    FeeTier.FEE_BAD.value: "fee verimsiz (0–29)",
    FeeTier.FEE_WEAK.value: "fee zayıf (30–49)",
    FeeTier.FEE_OK.value: "fee kabul edilebilir (50–64)",
    FeeTier.FEE_GOOD.value: "fee iyi (65–79)",
    FeeTier.FEE_EXCELLENT.value: "fee mükemmel (80–100)",
}


class ParamTemplate(BaseModel):
    template_key: str
    version: str
    profile_family: str
    profile_subfamily: Optional[str] = None
    final_action: str
    supported_regimes: List[str]
    allowed_risk_states: List[str]
    score_min: int
    score_max: int
    budget_tiers: List[str]
    exposure_tiers: List[str]
    headroom_tiers: List[str]
    fee_tiers: List[str]
    liquidity_tiers: List[str] = Field(default_factory=list)
    volatility_tiers: List[str] = Field(default_factory=list)
    btc_risk_tiers: List[str] = Field(default_factory=list)
    order_reality_tiers: List[str] = Field(default_factory=list)
    min_equity_usdt: float
    max_equity_usdt: Optional[float] = None
    min_notional_multiple: float
    min_headroom_multiple: float = 0.0
    min_trend_score: int = 0
    min_range_score: int = 0
    min_liquidity_score: int = 0
    min_spread_score: int = 0
    min_momentum_score: int = 0
    min_fee_efficiency_score: int = 0
    min_exposure_safety_score: int = 0
    min_data_quality_score: int = 0
    min_btc_market_risk_score: int = 0
    min_drawdown_risk_score: int = 0
    min_mean_reversion_score: int = 0
    min_volatility_score: int = 0
    max_spread_pct: Optional[float] = None
    max_total_friction_pct: Optional[float] = None
    max_volatility_pct: Optional[float] = None
    requires_sellable_base: bool = False
    allows_buy_grid: bool = True
    allows_sell_grid: bool = True
    deployable: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)
    hard_limits: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 50
    validation_quality_score: float = 0.0
    coverage_score: float = 0.0
    precision_score: float = 0.0
    safety_score: float = 0.0
    complexity_score: float = 0.0
    selection_priority: int = 0
    status: str = "active"
    notes: Optional[str] = None

    model_config = {"extra": "forbid"}


class ParamPoolVersion(BaseModel):
    version_id: str
    label: str
    template_count: int
    status: str = "active"
    notes: Optional[str] = None


class ParamPoolManifest(BaseModel):
    pool_version: str
    template_count: int
    active_template_count: int
    checksum: str
    created_at: str
    schema_version: str = "1.0"
    profile_distribution: Dict[str, int] = Field(default_factory=dict)
    base_pool_version: Optional[str] = None
    added_template_count: Optional[int] = None
    notes: Optional[str] = None


class SelectionFeatures(BaseModel):
    symbol: str = ""
    param_score: int
    regime: str
    risk_state: str
    budget_tier: str
    exposure_tier: str
    headroom_tier: str
    fee_tier: str
    liquidity_tier: str = ""
    volatility_tier: str = ""
    btc_risk_tier: str = ""
    order_reality_tier: str = ""
    sub_scores: Dict[str, float] = Field(default_factory=dict)
    budget_usdt: float = 0.0
    current_exposure_frac: float = 0.0
    headroom_usdt: float = 0.0
    min_notional: float = DEFAULT_MIN_NOTIONAL_USDT
    has_sellable_base: bool = False
    total_friction_pct: float = 0.0
    atr_pct: float = 1.0
    spread_pct: float = 0.0


class TemplateRejectReason(str, Enum):
    """Categorized hard-filter rejection for telemetry."""

    SCORE = "filtered_out_by_score"
    REGIME = "filtered_out_by_regime"
    RISK = "filtered_out_by_risk"
    BUDGET = "filtered_out_by_budget"
    EXPOSURE = "filtered_out_by_exposure"
    HEADROOM = "filtered_out_by_headroom"
    FEE = "filtered_out_by_fee"
    LIQUIDITY = "filtered_out_by_liquidity"
    VOLATILITY = "filtered_out_by_volatility"
    BTC_RISK = "filtered_out_by_btc_risk"
    ORDER_REALITY = "filtered_out_by_order_reality"
    FRICTION = "filtered_out_by_friction"
    SUBSCORE = "filtered_out_by_subscore"
    MIN_NOTIONAL = "filtered_out_by_min_notional"
    OTHER = "filtered_out_other"


@dataclass
class TemplateEligibility:
    template_key: str
    eligible: bool
    rejection_reasons: List[str] = field(default_factory=list)


@dataclass
class SelectionContext:
    param_score: int
    regime: str
    risk_state: str
    budget_tier: str
    exposure_tier: str
    headroom_tier: str
    fee_tier: str
    equity_usdt: float
    min_notional: float
    headroom_usdt: float
    has_base: bool
    sub_scores: Dict[str, int]
    spread_pct: float = 0.0
    atr_pct: float = 1.0
    liquidity_tier: str = ""
    volatility_tier: str = ""
    btc_risk_tier: str = ""
    order_reality_tier: str = ""
    total_friction_pct: float = 0.0
    has_sellable_base: bool = False
    sellable_base_usdt: float = 0.0
    sell_min_notional_feasible: bool = False
    is_first_start: bool = False


@dataclass
class TemplateSelectionResult:
    pool_version: str
    selected_template_key: Optional[str]
    profile_family: str
    final_action: str
    selection_score: float
    candidate_count: int
    filtered_out: Dict[str, List[str]]
    fallback_used: bool
    fallback_reason: Optional[str]
    template: Optional[ParamTemplate] = None

    filter_summary: Dict[str, int] = field(default_factory=dict)
    selection_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        from app.services.dynamic_param_score import constants as C
        from app.services.dynamic_param_score.param_pool.diagnostics import (
            build_reject_examples,
            build_selection_diagnostics,
        )

        base = {
            "pool_version": self.pool_version,
            "selected_template_key": self.selected_template_key,
            "profile_family": self.profile_family,
            "profile_subfamily": self.template.profile_subfamily if self.template else None,
            "final_action": self.final_action,
            "selection_score": self.selection_score,
            "candidate_count": self.candidate_count,
            "filtered_out_count": len(self.filtered_out),
            "reject_examples": build_reject_examples(
                self.filtered_out,
                limit=C.LOG_REJECT_EXAMPLES_MAX,
            ),
            "filter_summary": self.filter_summary,
            "selection_context": self.selection_context,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
        }
        base["diagnostics"] = build_selection_diagnostics(self)
        ctx = self.selection_context or {}
        base["active_template_count"] = int(ctx.get("active_template_count") or 0)
        base["templates_scanned"] = int(ctx.get("templates_scanned") or 0)
        base["unique_rejected_templates"] = len(self.filtered_out)
        base["reject_events_total"] = sum(len(v) for v in self.filtered_out.values())
        return base


def budget_tier_from_equity(equity_usdt: float) -> str:
    eq = max(float(equity_usdt or 0.0), 0.0)
    if eq < 25:
        return BudgetTier.NANO.value
    if eq < 50:
        return BudgetTier.MICRO.value
    if eq < 100:
        return BudgetTier.SMALL.value
    if eq < 250:
        return BudgetTier.STANDARD.value
    if eq < 1000:
        return BudgetTier.MEDIUM.value
    if eq < 5000:
        return BudgetTier.LARGE.value
    return BudgetTier.WHALE.value


def exposure_tier_from_frac(exposure_frac: float) -> str:
    exp = max(float(exposure_frac or 0.0), 0.0)
    if exp <= 0.05:
        return ExposureTier.NO_BASE.value
    if exp <= 0.25:
        return ExposureTier.LOW_BASE.value
    if exp <= 0.55:
        return ExposureTier.TARGET_BASE.value
    if exp <= 0.75:
        return ExposureTier.HIGH_BASE.value
    return ExposureTier.OVEREXPOSED.value


def headroom_tier_from_usdt(headroom_usdt: float, min_notional: float) -> str:
    hr = max(float(headroom_usdt or 0.0), 0.0)
    mn = max(float(min_notional or DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    if hr < mn:
        return HeadroomTier.NO_HEADROOM.value
    if hr < mn * 2:
        return HeadroomTier.LOW_HEADROOM.value
    if hr < mn * 5:
        return HeadroomTier.MEDIUM_HEADROOM.value
    return HeadroomTier.GOOD_HEADROOM.value


def fee_tier_from_score(fee_efficiency_score: int) -> str:
    s = int(fee_efficiency_score or 0)
    if s < 30:
        return FeeTier.FEE_BAD.value
    if s < 50:
        return FeeTier.FEE_WEAK.value
    if s < 65:
        return FeeTier.FEE_OK.value
    if s < 80:
        return FeeTier.FEE_GOOD.value
    return FeeTier.FEE_EXCELLENT.value


def liquidity_tier_from_score(liquidity_score: int) -> str:
    s = int(liquidity_score or 0)
    if s < 25:
        return LiquidityTier.LIQ_BAD.value
    if s < 45:
        return LiquidityTier.LIQ_WEAK.value
    if s < 65:
        return LiquidityTier.LIQ_OK.value
    if s < 80:
        return LiquidityTier.LIQ_GOOD.value
    return LiquidityTier.LIQ_EXCELLENT.value


def volatility_tier_from_score(volatility_score: int, atr_pct: float = 1.0) -> str:
    s = int(volatility_score or 0)
    atr = float(atr_pct or 1.0)
    if s < 20 or atr >= 5.0:
        return VolatilityTier.VOL_EXTREME.value
    if s < 35 or atr >= 3.0:
        return VolatilityTier.VOL_HIGH.value
    if s < 55:
        return VolatilityTier.VOL_NORMAL.value
    if s < 70 or atr <= 0.5:
        return VolatilityTier.VOL_LOW.value
    return VolatilityTier.VOL_TOO_LOW.value


def btc_risk_tier_from_score(btc_market_risk_score: int) -> str:
    s = int(btc_market_risk_score or 50)
    if s < 20:
        return BtcRiskTier.BTC_RISK_BLOCKED.value
    if s < 40:
        return BtcRiskTier.BTC_RISK_HIGH.value
    if s < 55:
        return BtcRiskTier.BTC_RISK_MEDIUM.value
    if s < 75:
        return BtcRiskTier.BTC_RISK_LOW.value
    return BtcRiskTier.BTC_RISK_SUPPORTIVE.value


def order_reality_tier_from_context(
    equity_usdt: float,
    min_notional: float,
    headroom_usdt: float,
) -> str:
    eq = max(float(equity_usdt or 0.0), 0.0)
    mn = max(float(min_notional or DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    hr = max(float(headroom_usdt or 0.0), 0.0)
    if eq < mn:
        return OrderRealityTier.ORDER_IMPOSSIBLE.value
    if eq < mn * 3 or hr < mn:
        return OrderRealityTier.ORDER_TIGHT.value
    if eq < mn * 10:
        return OrderRealityTier.ORDER_OK.value
    return OrderRealityTier.ORDER_COMFORTABLE.value
