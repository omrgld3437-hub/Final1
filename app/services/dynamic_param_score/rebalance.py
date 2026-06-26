"""Target allocation drift detection and safe one-shot rebalance planning."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BotParams,
    ExchangeConstraints,
    FinalAction,
    PortfolioState,
    RegimeTag,
    SubScores,
)

# Total percentage-point drift (base + quote legs) below which rebalance is skipped.
REBALANCE_THRESHOLD_TOTAL_PP = 15.0

DEFAULT_REBALANCE_POLICY: Dict[str, Any] = {
    "enabled": True,
    "mode": "oneshot",
    "rebalance_threshold_total_pp": REBALANCE_THRESHOLD_TOTAL_PP,
    "prefer_limit_orders": True,
    "allow_market_order": False,
    "buy_rebalance_allowed": True,
    "sell_rebalance_allowed": True,
    "rebalance_cooldown_turns": 2,
}

DISABLED_REBALANCE_POLICY: Dict[str, Any] = {
    "enabled": False,
    "mode": "none",
    "rebalance_threshold_total_pp": REBALANCE_THRESHOLD_TOTAL_PP,
    "prefer_limit_orders": True,
    "allow_market_order": False,
    "buy_rebalance_allowed": False,
    "sell_rebalance_allowed": False,
}


class RebalanceMode(str, Enum):
    NO_REBALANCE = "NO_REBALANCE"
    PASSIVE_REBALANCE = "PASSIVE_REBALANCE"
    ONESHOT_BUY_REBALANCE = "REBALANCE_ONESHOT_BUY"
    ONESHOT_SELL_REBALANCE = "REBALANCE_ONESHOT_SELL"
    REBALANCE_DEFERRED = "REBALANCE_DEFERRED"
    GRADUAL_BUY_REBALANCE = "GRADUAL_BUY_REBALANCE"  # legacy alias
    GRADUAL_SELL_REBALANCE = "GRADUAL_SELL_REBALANCE"
    SELL_MANAGEMENT_ONLY = "SELL_MANAGEMENT_ONLY"
    RECOVERY_SELL = "RECOVERY_SELL"
    EMERGENCY_RISK_REDUCTION = "EMERGENCY_RISK_REDUCTION"


@dataclass
class RebalanceOrder:
    side: str
    quote_usdt: float = 0.0
    base_usdt: float = 0.0
    order_type: str = "MARKETABLE_LIMIT"
    price_offset_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RebalancePlan:
    rebalance_action: str
    current_base_frac: float
    target_base_frac: float
    drift_frac: float
    drift_abs_frac: float
    required_quote_usdt: float
    required_base_usdt: float
    allowed_rebalance_quote_usdt: float
    allowed_rebalance_base_usdt: float
    mode: str
    deadband_frac: float
    orders: List[RebalanceOrder] = field(default_factory=list)
    enabled: bool = True
    blocked: bool = False
    block_reasons: List[str] = field(default_factory=list)
    notes: str = ""
    rebalance_decision: str = "SKIP"
    rebalance_skipped_reason: str = ""
    rebalance_delta_total_pp: float = 0.0
    rebalance_threshold_pp: float = REBALANCE_THRESHOLD_TOTAL_PP
    rebalance_execution_mode: str = ""
    rebalance_order_type: str = ""
    other_parameters_applied: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["orders"] = [o.to_dict() for o in self.orders]
        return d


@dataclass
class SafetyContext:
    risk_state: str
    regime: str
    final_action: str
    param_score: int
    sub_scores: SubScores
    headroom_usdt: float
    min_notional: float
    spread_pct: float = 0.0
    atr_pct: float = 1.0


def rebalance_delta_total_pp(current_base_frac: float, target_base_frac: float) -> float:
    cur_b = float(current_base_frac or 0.0) * 100.0
    cur_q = (1.0 - float(current_base_frac or 0.0)) * 100.0
    tgt_b = float(target_base_frac or 0.0) * 100.0
    tgt_q = (1.0 - float(target_base_frac or 0.0)) * 100.0
    return abs(cur_b - tgt_b) + abs(cur_q - tgt_q)


def rebalance_policy_for_action(final_action: str, template_policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    policy = copy.deepcopy(DEFAULT_REBALANCE_POLICY)
    if template_policy:
        policy.update(template_policy)

    if final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        policy.update(DISABLED_REBALANCE_POLICY)
    elif final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        policy.update(
            {
                "enabled": True,
                "buy_rebalance_allowed": False,
                "sell_rebalance_allowed": True,
                "mode": "oneshot",
            }
        )
    return policy


def calculate_allocation_drift(
    current_base_frac: float,
    target_base_frac: float,
    total_equity_usdt: float,
) -> Dict[str, float]:
    cur = max(float(current_base_frac or 0.0), 0.0)
    tgt = max(float(target_base_frac or 0.0), 0.0)
    eq = max(float(total_equity_usdt or 0.0), 0.0)
    drift = tgt - cur
    return {
        "current_base_frac": round(cur, 6),
        "target_base_frac": round(tgt, 6),
        "drift_frac": round(drift, 6),
        "drift_abs_frac": round(abs(drift), 6),
        "required_quote_usdt": round(max(drift * eq, 0.0), 4),
        "required_base_usdt": round(max(-drift * eq, 0.0), 4),
        "rebalance_delta_total_pp": round(rebalance_delta_total_pp(cur, tgt), 4),
    }


def _rebalance_safety_blocked(ctx: SafetyContext, policy: Dict[str, Any], side: str) -> List[str]:
    reasons: List[str] = []
    if side == "BUY" and not policy.get("buy_rebalance_allowed", True):
        reasons.append("buy_rebalance_disabled")
    if side == "SELL" and not policy.get("sell_rebalance_allowed", True):
        reasons.append("sell_rebalance_disabled")
    if ctx.regime in (
        RegimeTag.DUMP_RISK.value,
        RegimeTag.NO_DATA.value,
        RegimeTag.SPREAD_UNSAFE.value,
        RegimeTag.LOW_LIQUIDITY.value,
    ):
        reasons.append("regime_unsafe")
    if ctx.spread_pct > 0.35:
        reasons.append("spread_unsafe")
    if ctx.sub_scores.liquidity_score < 25:
        reasons.append("low_liquidity")
    if ctx.sub_scores.fee_efficiency_score < 30:
        reasons.append("fee_bad")
    if ctx.headroom_usdt < ctx.min_notional and side == "BUY":
        reasons.append("no_headroom")
    if ctx.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        reasons.append("final_action_blocks_rebalance")
    if ctx.risk_state in ("BLOCKED",) and side == "BUY":
        reasons.append("risk_blocked")
    return reasons


def _cooldown_active(policy: Dict[str, Any]) -> bool:
    last_turn = policy.get("last_rebalance_turn_id")
    cur_turn = policy.get("current_turn_id")
    cooldown = int(policy.get("rebalance_cooldown_turns") or 2)
    if last_turn is None or cur_turn is None:
        return False
    try:
        return int(cur_turn) - int(last_turn) < cooldown
    except (TypeError, ValueError):
        return False


def plan_rebalance(
    target_base_frac: float,
    current_base_frac: float,
    portfolio: PortfolioState,
    bot_params: Optional[BotParams],
    constraints: ExchangeConstraints,
    safety_context: SafetyContext,
    *,
    rebalance_policy: Optional[Dict[str, Any]] = None,
) -> RebalancePlan:
    policy = rebalance_policy_for_action(safety_context.final_action, rebalance_policy)
    drift = calculate_allocation_drift(
        current_base_frac,
        target_base_frac,
        portfolio.total_equity_usdt,
    )
    threshold_pp = float(policy.get("rebalance_threshold_total_pp") or REBALANCE_THRESHOLD_TOTAL_PP)
    delta_pp = float(drift.get("rebalance_delta_total_pp") or 0.0)

    base_plan = RebalancePlan(
        rebalance_action=RebalanceMode.NO_REBALANCE.value,
        current_base_frac=drift["current_base_frac"],
        target_base_frac=drift["target_base_frac"],
        drift_frac=drift["drift_frac"],
        drift_abs_frac=drift["drift_abs_frac"],
        required_quote_usdt=drift["required_quote_usdt"],
        required_base_usdt=drift["required_base_usdt"],
        allowed_rebalance_quote_usdt=0.0,
        allowed_rebalance_base_usdt=0.0,
        mode=RebalanceMode.NO_REBALANCE.value,
        deadband_frac=threshold_pp / 100.0,
        enabled=bool(policy.get("enabled", True)),
        rebalance_delta_total_pp=delta_pp,
        rebalance_threshold_pp=threshold_pp,
        rebalance_decision="SKIP",
        other_parameters_applied=True,
    )

    if not policy.get("enabled", True):
        base_plan.rebalance_skipped_reason = "REBALANCE_DISABLED"
        base_plan.notes = "Rebalance policy disabled for this template/action."
        return base_plan

    if _cooldown_active(policy):
        base_plan.rebalance_skipped_reason = "REBALANCE_COOLDOWN_ACTIVE"
        base_plan.notes = "Son rebalance üzerinden cooldown geçmedi; base/quote korunuyor."
        return base_plan

    if delta_pp <= threshold_pp:
        base_plan.rebalance_decision = "SKIP"
        base_plan.rebalance_skipped_reason = "SMALL_BASE_QUOTE_DELTA"
        base_plan.rebalance_action = RebalanceMode.NO_REBALANCE.value
        base_plan.mode = RebalanceMode.PASSIVE_REBALANCE.value
        base_plan.notes = (
            f"Yeni hedef dağılım mevcut portföye yakın (Δ={delta_pp:.1f}pp ≤ {threshold_pp:.0f}pp); "
            "base/quote rebalance yapılmadı. Diğer dinamik parametreler uygulanabilir."
        )
        return base_plan

    order_type = "MARKETABLE_LIMIT"
    if policy.get("allow_market_order") and safety_context.regime == RegimeTag.DUMP_RISK.value:
        order_type = "MARKET"

    # Need more base → one-shot buy
    if drift["drift_frac"] > 0:
        block = _rebalance_safety_blocked(safety_context, policy, "BUY")
        if block:
            base_plan.rebalance_decision = "DEFER"
            base_plan.rebalance_action = RebalanceMode.REBALANCE_DEFERRED.value
            base_plan.mode = RebalanceMode.REBALANCE_DEFERRED.value
            base_plan.blocked = True
            base_plan.block_reasons = block + ["REBALANCE_SAFETY_BLOCKED"]
            base_plan.rebalance_skipped_reason = "REBALANCE_SAFETY_BLOCKED"
            base_plan.notes = (
                "Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları "
                f"uygun olmadığı için rebalance ertelendi ({', '.join(block)})."
            )
            return base_plan

        allowed = min(
            drift["required_quote_usdt"],
            safety_context.headroom_usdt,
            float(portfolio.quote_value_usdt or portfolio.quote_balance or 0.0),
        )
        allowed = max(allowed, 0.0)
        if allowed < constraints.min_notional:
            base_plan.rebalance_decision = "DEFER"
            base_plan.rebalance_action = RebalanceMode.REBALANCE_DEFERRED.value
            base_plan.blocked = True
            base_plan.block_reasons = ["min_notional", "REBALANCE_SAFETY_BLOCKED"]
            base_plan.notes = "Rebalance alış tutarı min-notional altında; ertelendi."
            return base_plan

        base_plan.orders = [
            RebalanceOrder(
                side="BUY",
                quote_usdt=round(allowed, 4),
                order_type=order_type,
                price_offset_pct=0.0,
            )
        ]
        base_plan.allowed_rebalance_quote_usdt = round(allowed, 4)
        base_plan.rebalance_decision = "EXECUTE"
        base_plan.rebalance_execution_mode = "ONESHOT"
        base_plan.rebalance_order_type = order_type
        base_plan.rebalance_action = RebalanceMode.ONESHOT_BUY_REBALANCE.value
        base_plan.mode = RebalanceMode.ONESHOT_BUY_REBALANCE.value
        base_plan.notes = (
            "Base/quote hedefi anlamlı şekilde değiştiği için tek seferlik kontrollü rebalance "
            f"emri hazırlandı (alış ${allowed:.2f}). Bu emir grid değil, portföy dengeleme emridir."
        )
        return base_plan

    # Need less base → one-shot sell
    block = _rebalance_safety_blocked(safety_context, policy, "SELL")
    if block and safety_context.final_action != FinalAction.SELL_MANAGEMENT_ONLY.value:
        base_plan.rebalance_decision = "DEFER"
        base_plan.rebalance_action = RebalanceMode.REBALANCE_DEFERRED.value
        base_plan.blocked = True
        base_plan.block_reasons = block + ["REBALANCE_SAFETY_BLOCKED"]
        base_plan.notes = (
            "Base/quote hedefi anlamlı değişti ancak satış rebalance güvenlik nedeniyle ertelendi."
        )
        return base_plan

    allowed = min(drift["required_base_usdt"], max(portfolio.base_value_usdt, 0.0))
    if allowed < constraints.min_notional:
        base_plan.rebalance_decision = "DEFER"
        base_plan.rebalance_action = RebalanceMode.REBALANCE_DEFERRED.value
        base_plan.blocked = True
        base_plan.block_reasons = ["min_notional", "REBALANCE_SAFETY_BLOCKED"]
        base_plan.notes = "Rebalance satış tutarı min-notional altında; ertelendi."
        return base_plan

    if safety_context.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        mode = RebalanceMode.SELL_MANAGEMENT_ONLY.value
    elif portfolio.current_base_exposure_frac > 0.75:
        mode = RebalanceMode.RECOVERY_SELL.value
    elif safety_context.regime == RegimeTag.DUMP_RISK.value:
        mode = RebalanceMode.EMERGENCY_RISK_REDUCTION.value
    else:
        mode = RebalanceMode.ONESHOT_SELL_REBALANCE.value

    base_plan.orders = [
        RebalanceOrder(
            side="SELL",
            base_usdt=round(allowed, 4),
            order_type=order_type,
            price_offset_pct=0.0,
        )
    ]
    base_plan.allowed_rebalance_base_usdt = round(allowed, 4)
    base_plan.rebalance_decision = "EXECUTE"
    base_plan.rebalance_execution_mode = "ONESHOT"
    base_plan.rebalance_order_type = order_type
    base_plan.rebalance_action = mode
    base_plan.mode = mode
    base_plan.notes = (
        "Base/quote hedefi anlamlı şekilde değiştiği için tek seferlik kontrollü rebalance "
        f"emri hazırlandı (satış ${allowed:.2f}). Bu emir grid değil, portföy dengeleme emridir."
    )
    return base_plan


def apply_rebalance_safety(
    rebalance_plan: RebalancePlan,
    safety_context: SafetyContext,
    bot_params: Optional[BotParams],
    constraints: ExchangeConstraints,
    *,
    total_equity_usdt: float = 0.0,
) -> RebalancePlan:
    plan = copy.deepcopy(rebalance_plan)
    if not plan.enabled or not plan.orders:
        return plan

    min_n = max(float(constraints.min_notional or DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    reasons: List[str] = list(plan.block_reasons)
    max_exp = float(getattr(bot_params, "max_base_exposure_frac", 1.0) or 1.0) if bot_params else 1.0
    safe_orders: List[RebalanceOrder] = []

    for order in plan.orders:
        if order.side == "BUY":
            if safety_context.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
                reasons.append("buy_blocked_by_final_action")
                continue
            if order.quote_usdt < min_n:
                reasons.append("buy_below_min_notional")
                continue
            eq = max(float(total_equity_usdt or 0.0), min_n * 10)
            projected_exp = plan.current_base_frac + (order.quote_usdt / eq)
            if projected_exp > max_exp + 1e-6:
                reasons.append("max_exposure_cap")
                continue
        else:
            if order.base_usdt < min_n:
                reasons.append("sell_below_min_notional")
                continue
        safe_orders.append(order)

    if not safe_orders and plan.orders:
        plan.blocked = True
        plan.rebalance_decision = "DEFER"
        plan.rebalance_action = RebalanceMode.REBALANCE_DEFERRED.value
        plan.mode = RebalanceMode.REBALANCE_DEFERRED.value
        plan.orders = []
        plan.allowed_rebalance_quote_usdt = 0.0
        plan.allowed_rebalance_base_usdt = 0.0
        plan.block_reasons = list(dict.fromkeys(reasons + ["REBALANCE_SAFETY_BLOCKED"]))
        plan.rebalance_skipped_reason = "REBALANCE_SAFETY_BLOCKED"
        plan.notes = "Rebalance emirleri safety gate sonrası ertelendi."
        return plan

    plan.orders = safe_orders
    plan.block_reasons = list(dict.fromkeys(reasons))
    if plan.rebalance_action.endswith("BUY") or "ONESHOT_BUY" in plan.rebalance_action:
        plan.allowed_rebalance_quote_usdt = round(sum(o.quote_usdt for o in safe_orders), 4)
    elif "SELL" in plan.rebalance_action:
        plan.allowed_rebalance_base_usdt = round(sum(o.base_usdt for o in safe_orders), 4)
    return plan
