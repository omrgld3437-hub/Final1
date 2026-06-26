"""Order Intent Planner — parametre + rebalance planından emir niyet listesi (henüz gönderim yok)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.feasibility import buy_ladder_budget_usdt
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    PortfolioState,
)
from app.services.dynamic_param_score.rebalance import RebalancePlan, RebalanceOrder


class IntentKind(str, Enum):
    GRID_BUY = "GRID_BUY"
    GRID_SELL = "GRID_SELL"
    REBALANCE_BUY = "REBALANCE_BUY"
    REBALANCE_SELL = "REBALANCE_SELL"
    REBALANCE_ONESHOT_BUY = "REBALANCE_ONESHOT_BUY"
    REBALANCE_ONESHOT_SELL = "REBALANCE_ONESHOT_SELL"


@dataclass
class OrderIntent:
    intent_id_suffix: str
    side: str
    kind: str
    quote_usdt: float = 0.0
    base_usdt: float = 0.0
    price_offset_pct: float = 0.0
    order_type: str = "LIMIT"
    level_index: int = 0
    source: str = "grid"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderIntentPlan:
    intents: List[OrderIntent] = field(default_factory=list)
    buy_intent_count: int = 0
    sell_intent_count: int = 0
    total_buy_quote_usdt: float = 0.0
    total_sell_base_usdt: float = 0.0
    blocked: bool = False
    block_reasons: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intents": [i.to_dict() for i in self.intents],
            "buy_intent_count": self.buy_intent_count,
            "sell_intent_count": self.sell_intent_count,
            "total_buy_quote_usdt": round(self.total_buy_quote_usdt, 4),
            "total_sell_base_usdt": round(self.total_sell_base_usdt, 4),
            "blocked": self.blocked,
            "block_reasons": self.block_reasons,
            "notes": self.notes,
        }


def _grid_buy_intents(
    params: BotParams,
    buy_budget: float,
    *,
    final_action: str,
) -> List[OrderIntent]:
    if params.buy_grid_count <= 0 or params.emergency_no_buy:
        return []
    if final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        return []

    intents: List[OrderIntent] = []
    weights = params.buy_qty_distribution or []
    if not weights:
        n = max(params.buy_grid_count, 1)
        weights = [1.0 / n] * n

    for i, w in enumerate(weights[: params.buy_grid_count]):
        quote = buy_budget * float(w)
        if quote <= 0:
            continue
        intents.append(
            OrderIntent(
                intent_id_suffix=f"buy_grid_{i + 1}",
                side="BUY",
                kind=IntentKind.GRID_BUY.value,
                quote_usdt=round(quote, 4),
                price_offset_pct=round(params.buy_grid_spacing_pct * (i + 1), 4),
                level_index=i + 1,
                source="grid",
            )
        )
    return intents


def _grid_sell_intents(
    params: BotParams,
    portfolio: PortfolioState,
    *,
    final_action: str,
) -> List[OrderIntent]:
    if params.sell_grid_count <= 0:
        return []
    if final_action == FinalAction.NO_TRADE.value:
        return []

    base_pool = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    if base_pool <= 0:
        return []

    intents: List[OrderIntent] = []
    weights = params.sell_qty_distribution or []
    if not weights:
        n = max(params.sell_grid_count, 1)
        weights = [1.0 / n] * n

    for i, w in enumerate(weights[: params.sell_grid_count]):
        base_usdt = base_pool * float(w)
        if base_usdt <= 0:
            continue
        intents.append(
            OrderIntent(
                intent_id_suffix=f"sell_grid_{i + 1}",
                side="SELL",
                kind=IntentKind.GRID_SELL.value,
                base_usdt=round(base_usdt, 4),
                price_offset_pct=round(params.sell_grid_spacing_pct * (i + 1), 4),
                level_index=i + 1,
                source="grid",
            )
        )
    return intents


def _rebalance_intents(rebalance_plan: Optional[RebalancePlan]) -> List[OrderIntent]:
    if not rebalance_plan or not rebalance_plan.orders:
        return []
    if rebalance_plan.rebalance_decision != "EXECUTE":
        return []
    intents: List[OrderIntent] = []
    oneshot = rebalance_plan.rebalance_execution_mode == "ONESHOT" or rebalance_plan.rebalance_action in (
        "REBALANCE_ONESHOT_BUY",
        "REBALANCE_ONESHOT_SELL",
    )
    for i, order in enumerate(rebalance_plan.orders):
        if oneshot:
            kind = (
                IntentKind.REBALANCE_ONESHOT_BUY.value
                if order.side == "BUY"
                else IntentKind.REBALANCE_ONESHOT_SELL.value
            )
            suffix = f"rebalance_oneshot_{order.side.lower()}"
        else:
            kind = (
                IntentKind.REBALANCE_BUY.value
                if order.side == "BUY"
                else IntentKind.REBALANCE_SELL.value
            )
            suffix = f"rebalance_{order.side.lower()}_{i + 1}"
        intents.append(
            OrderIntent(
                intent_id_suffix=suffix,
                side=order.side,
                kind=kind,
                quote_usdt=round(order.quote_usdt, 4),
                base_usdt=round(order.base_usdt, 4),
                price_offset_pct=round(order.price_offset_pct, 4),
                order_type=order.order_type,
                level_index=0 if oneshot else i + 1,
                source="rebalance_oneshot" if oneshot else "rebalance",
            )
        )
    return intents


def plan_order_intents(
    params: Optional[BotParams],
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    bot_context: BotContext,
    *,
    final_action: str,
    profile_name: str = "",
    rebalance_plan: Optional[RebalancePlan] = None,
    buy_ladder_budget_override: Optional[float] = None,
) -> OrderIntentPlan:
    """Parametre + rebalance → niyet listesi. Execution'dan önce test edilebilir."""
    plan = OrderIntentPlan()
    if params is None:
        plan.blocked = True
        plan.block_reasons = ["no_params"]
        plan.notes = "Parametre yok; emir niyeti üretilmedi."
        return plan

    if final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        plan.notes = f"{final_action}: grid/rebalance niyeti yok."
        return plan

    if buy_ladder_budget_override is not None:
        buy_budget = max(float(buy_ladder_budget_override), 0.0)
    else:
        buy_budget = buy_ladder_budget_usdt(portfolio, params, bot_context, profile_name)
    grid_buys = _grid_buy_intents(params, buy_budget, final_action=final_action)
    grid_sells = _grid_sell_intents(params, portfolio, final_action=final_action)
    rb_intents = _rebalance_intents(rebalance_plan)

    all_intents = grid_buys + rb_intents + grid_sells
    min_n = max(float(constraints.min_notional or DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    safe: List[OrderIntent] = []
    reasons: List[str] = []

    for intent in all_intents:
        if intent.side == "BUY":
            if intent.quote_usdt < min_n:
                reasons.append(f"{intent.intent_id_suffix}_below_min_notional")
                continue
            if intent.quote_usdt > portfolio.quote_value_usdt + 1e-6:
                reasons.append(f"{intent.intent_id_suffix}_insufficient_quote")
                continue
        else:
            if intent.base_usdt < min_n:
                reasons.append(f"{intent.intent_id_suffix}_below_min_notional")
                continue
            if intent.base_usdt > portfolio.base_value_usdt + 1e-6:
                reasons.append(f"{intent.intent_id_suffix}_insufficient_base")
                continue
        safe.append(intent)

    plan.intents = safe
    plan.buy_intent_count = sum(1 for i in safe if i.side == "BUY")
    plan.sell_intent_count = sum(1 for i in safe if i.side == "SELL")
    plan.total_buy_quote_usdt = round(sum(i.quote_usdt for i in safe if i.side == "BUY"), 4)
    plan.total_sell_base_usdt = round(sum(i.base_usdt for i in safe if i.side == "SELL"), 4)
    plan.block_reasons = list(dict.fromkeys(reasons))
    if not safe and (grid_buys or grid_sells or rb_intents):
        plan.blocked = True
        plan.notes = "Tüm niyetler feasibility ön filtresinde elendi."
    elif safe:
        plan.notes = (
            f"{plan.buy_intent_count} alış · {plan.sell_intent_count} satış niyeti "
            f"(grid + rebalance, henüz gönderilmedi)."
        )
    return plan
