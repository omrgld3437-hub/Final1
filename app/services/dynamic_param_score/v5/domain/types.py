"""V5 shelf and resolver type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts


@dataclass
class V5BaseTemplate:
    preferred_grid_count: int
    allowed_grid_count_range: Tuple[int, int]
    sell_grid_levels_pct: List[float]
    buy_grid_levels_pct: List[float]
    sell_distribution_pct: List[float]
    buy_distribution_pct: List[float]
    target_base_pct: float
    target_quote_pct: float
    max_base_exposure_pct: float
    active_buy_ladder_max_budget_pct: float
    sell_trailing_pct: float
    buy_trailing_pct: float
    take_profit_buy_trigger_pct: float
    take_profit_buy_trailing_pct: float
    take_profit_sell_trigger_pct: float
    take_profit_sell_trailing_pct: float
    min_profit_after_cost_floor_pct: float
    execution_safety_buffer_pct: float
    assumed_cost_floor_pct: float
    equal_2_grid_justified: bool = False
    grid_reasoning: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "preferred_grid_count": self.preferred_grid_count,
            "allowed_grid_count_range": list(self.allowed_grid_count_range),
            "sell_grid_levels_pct": self.sell_grid_levels_pct,
            "buy_grid_levels_pct": self.buy_grid_levels_pct,
            "sell_distribution_pct": self.sell_distribution_pct,
            "buy_distribution_pct": self.buy_distribution_pct,
            "target_base_pct": self.target_base_pct,
            "target_quote_pct": self.target_quote_pct,
            "max_base_exposure_pct": self.max_base_exposure_pct,
            "active_buy_ladder_max_budget_pct": self.active_buy_ladder_max_budget_pct,
            "sell_trailing_pct": self.sell_trailing_pct,
            "buy_trailing_pct": self.buy_trailing_pct,
            "take_profit_buy_trigger_pct": self.take_profit_buy_trigger_pct,
            "take_profit_buy_trailing_pct": self.take_profit_buy_trailing_pct,
            "take_profit_sell_trigger_pct": self.take_profit_sell_trigger_pct,
            "take_profit_sell_trailing_pct": self.take_profit_sell_trailing_pct,
            "min_profit_after_cost_floor_pct": self.min_profit_after_cost_floor_pct,
            "execution_safety_buffer_pct": self.execution_safety_buffer_pct,
            "assumed_cost_floor_pct": self.assumed_cost_floor_pct,
            "equal_2_grid_justified": self.equal_2_grid_justified,
        }
        if self.grid_reasoning:
            out["grid_reasoning"] = self.grid_reasoning
        return out


@dataclass
class V5ResolverPolicy:
    budget_policy: str
    position_policy: str
    momentum_policy: str
    data_quality_policy: str
    execution_cost_policy: str
    btc_context_policy: str
    risk_clamp_policy: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "budget_policy": self.budget_policy,
            "position_policy": self.position_policy,
            "momentum_policy": self.momentum_policy,
            "data_quality_policy": self.data_quality_policy,
            "execution_cost_policy": self.execution_cost_policy,
            "btc_context_policy": self.btc_context_policy,
            "risk_clamp_policy": self.risk_clamp_policy,
        }


@dataclass
class V5FallbackPolicy:
    fallback_allowed: bool
    fallback_family: str
    forbidden_fallbacks: List[str]
    nearest_safe_dimensions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fallback_allowed": self.fallback_allowed,
            "fallback_family": self.fallback_family,
            "forbidden_fallbacks": self.forbidden_fallbacks,
            "nearest_safe_dimensions": self.nearest_safe_dimensions,
        }


@dataclass
class V5GenerationMeta:
    deterministic_formula_version: str
    generated_at: str
    generated_by: Literal["dynamic_param_v5_generator"]
    random_used: Literal[False]
    source_logic_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deterministic_formula_version": self.deterministic_formula_version,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "random_used": self.random_used,
            "source_logic_hash": self.source_logic_hash,
        }


@dataclass
class V5Shelf:
    version: Literal["DPLV5"]
    shelf_id: str
    route_key: str
    route_parts: V5RouteParts
    scenario_title: str
    scenario_description: str
    base_template: V5BaseTemplate
    resolver_policy: V5ResolverPolicy
    fallback_policy: V5FallbackPolicy
    validation_policy: Dict[str, List[str]]
    generation_meta: V5GenerationMeta

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "shelf_id": self.shelf_id,
            "route_key": self.route_key,
            "route_parts": self.route_parts.to_dict(),
            "scenario_title": self.scenario_title,
            "scenario_description": self.scenario_description,
            "base_template": self.base_template.to_dict(),
            "resolver_policy": self.resolver_policy.to_dict(),
            "fallback_policy": self.fallback_policy.to_dict(),
            "validation_policy": self.validation_policy,
            "generation_meta": self.generation_meta.to_dict(),
        }


SelectionType = Literal[
    "EXACT_V5",
    "SAFE_FALLBACK_V5",
    "CLAMPED_FALLBACK_V5",
    "GLOBAL_SAFE_V5",
]


@dataclass
class V5ResolveTrace:
    exact_route_hit: bool
    fallback_used: bool
    budget_adjustments: List[str] = field(default_factory=list)
    position_adjustments: List[str] = field(default_factory=list)
    momentum_adjustments: List[str] = field(default_factory=list)
    data_quality_adjustments: List[str] = field(default_factory=list)
    execution_cost_adjustments: List[str] = field(default_factory=list)
    btc_context_adjustments: List[str] = field(default_factory=list)
    risk_clamp_adjustments: List[str] = field(default_factory=list)
    final_validation_adjustments: List[str] = field(default_factory=list)


@dataclass
class V5ResolveInput:
    symbol: str
    route_parts: V5RouteParts
    budget_usdt: float
    min_notional_usdt: float
    current_base_pct: float
    current_quote_pct: float
    maker_fee_pct: float
    taker_fee_pct: float
    spread_pct: float
    slippage_pct: float
    rounding_pct: float
    indicators: Dict[str, float] = field(default_factory=dict)
    data_quality: Dict[str, Any] = field(default_factory=dict)


@dataclass
class V5ResolvedParam:
    version: Literal["DPLV5"]
    selection_type: SelectionType
    shelf_id: str
    route_key: str
    final_grid_count: int
    sell_grid_levels_pct: List[float]
    buy_grid_levels_pct: List[float]
    sell_distribution_pct: List[float]
    buy_distribution_pct: List[float]
    target_base_pct: float
    target_quote_pct: float
    max_base_exposure_pct: float
    active_buy_ladder_budget_usdt: float
    sell_trailing_pct: float
    buy_trailing_pct: float
    take_profit_buy_trigger_pct: float
    take_profit_buy_trailing_pct: float
    take_profit_sell_trigger_pct: float
    take_profit_sell_trailing_pct: float
    cost_floor_pct: float
    min_profit_after_cost_floor_pct: float
    confidence: float
    trace: V5ResolveTrace

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "selection_type": self.selection_type,
            "shelf_id": self.shelf_id,
            "route_key": self.route_key,
            "final_grid_count": self.final_grid_count,
            "sell_grid_levels_pct": self.sell_grid_levels_pct,
            "buy_grid_levels_pct": self.buy_grid_levels_pct,
            "sell_distribution_pct": self.sell_distribution_pct,
            "buy_distribution_pct": self.buy_distribution_pct,
            "target_base_pct": self.target_base_pct,
            "target_quote_pct": self.target_quote_pct,
            "max_base_exposure_pct": self.max_base_exposure_pct,
            "active_buy_ladder_budget_usdt": self.active_buy_ladder_budget_usdt,
            "sell_trailing_pct": self.sell_trailing_pct,
            "buy_trailing_pct": self.buy_trailing_pct,
            "take_profit_buy_trigger_pct": self.take_profit_buy_trigger_pct,
            "take_profit_buy_trailing_pct": self.take_profit_buy_trailing_pct,
            "take_profit_sell_trigger_pct": self.take_profit_sell_trigger_pct,
            "take_profit_sell_trailing_pct": self.take_profit_sell_trailing_pct,
            "cost_floor_pct": self.cost_floor_pct,
            "min_profit_after_cost_floor_pct": self.min_profit_after_cost_floor_pct,
            "confidence": self.confidence,
            "trace": {
                "exact_route_hit": self.trace.exact_route_hit,
                "fallback_used": self.trace.fallback_used,
                "budget_adjustments": self.trace.budget_adjustments,
                "position_adjustments": self.trace.position_adjustments,
                "momentum_adjustments": self.trace.momentum_adjustments,
                "data_quality_adjustments": self.trace.data_quality_adjustments,
                "execution_cost_adjustments": self.trace.execution_cost_adjustments,
                "btc_context_adjustments": self.trace.btc_context_adjustments,
                "risk_clamp_adjustments": self.trace.risk_clamp_adjustments,
                "final_validation_adjustments": self.trace.final_validation_adjustments,
            },
        }


@dataclass
class ValidationViolation:
    severity: Literal["BLOCKER", "CRITICAL", "MAJOR", "MINOR"]
    code: str
    message: str
    shelf_id: Optional[str] = None
    route_key: Optional[str] = None
    expected: Any = None
    actual: Any = None


@dataclass
class ValidationResult:
    ok: bool
    violations: List[ValidationViolation]
