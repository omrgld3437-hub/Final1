"""Consumer policies — Param Assistant vs Dynamic Mode on the shared DPS motor.

Both consumers call ``DynamicParamScoreEngine.calculate_decision()`` with isolated
``BotContext`` + ``ConsumerPolicy``. Policies control UI vs live-deploy semantics;
the scoring/selector pipeline stays shared and stateless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from app.services.dynamic_param_score.models import BotContext, PortfolioState, RunSource

ConsumerId = Literal["param_assistant", "dynamic_round_start"]

_VALID_SOURCES: frozenset[str] = frozenset({"param_assistant", "dynamic_round_start"})


@dataclass(frozen=True)
class ConsumerPolicy:
    """Per-consumer rules — never mutate shared engine state."""

    consumer_id: ConsumerId
    run_source: RunSource
    recommendation_ui: bool
    first_start_eligible: bool
    soften_extreme_safety_for_ui: bool
    live_deploy_required: bool

    @property
    def intent_execution_enabled(self) -> bool:
        return False


_PARAM_ASSISTANT = ConsumerPolicy(
    consumer_id="param_assistant",
    run_source="param_assistant",
    recommendation_ui=True,
    first_start_eligible=True,
    soften_extreme_safety_for_ui=True,
    live_deploy_required=False,
)

_DYNAMIC_ROUND = ConsumerPolicy(
    consumer_id="dynamic_round_start",
    run_source="dynamic_round_start",
    recommendation_ui=False,
    first_start_eligible=False,
    soften_extreme_safety_for_ui=False,
    live_deploy_required=True,
)

_POLICIES: dict[str, ConsumerPolicy] = {
    "param_assistant": _PARAM_ASSISTANT,
    "dynamic_round_start": _DYNAMIC_ROUND,
}


def normalize_run_source(run_source: str) -> RunSource:
    rs = str(run_source or "").strip().lower()
    if rs not in _VALID_SOURCES:
        raise ValueError(f"invalid run_source: {run_source!r}")
    return rs  # type: ignore[return-value]


def policy_for(run_source: str) -> ConsumerPolicy:
    return _POLICIES[normalize_run_source(run_source)]


def policy_for_context(context: BotContext) -> ConsumerPolicy:
    return policy_for(context.run_source)


def resolve_first_start_flags(
    policy: ConsumerPolicy,
    portfolio: PortfolioState,
    first_start_buy_only: Optional[bool] = None,
) -> tuple[bool, bool]:
    base_val = float(portfolio.base_value_usdt or 0)
    is_first_start = policy.first_start_eligible and base_val <= 0
    if first_start_buy_only is None:
        fs_buy_only = is_first_start
    else:
        fs_buy_only = bool(first_start_buy_only) and policy.first_start_eligible
    return is_first_start, fs_buy_only


def build_param_assistant_context(
    *,
    budget_usdt: float,
    portfolio: PortfolioState,
    first_start_buy_only: Optional[bool] = None,
    allow_live: bool = True,
    allow_no_trade: bool = True,
) -> BotContext:
    policy = _PARAM_ASSISTANT
    is_first_start, fs_buy_only = resolve_first_start_flags(
        policy, portfolio, first_start_buy_only=first_start_buy_only
    )
    return BotContext(
        run_source=policy.run_source,
        budget_usdt=float(budget_usdt),
        is_first_start=is_first_start,
        first_start_buy_only=fs_buy_only,
        allow_live=allow_live,
        allow_no_trade=allow_no_trade,
        bot_id=None,
    )


def build_dynamic_round_context(
    *,
    budget_usdt: float,
    cycle_id: int,
    bot_id: Optional[int] = None,
    last_rebalance_round_id: Optional[str] = None,
    allow_live: bool = True,
    allow_no_trade: bool = True,
) -> BotContext:
    policy = _DYNAMIC_ROUND
    return BotContext(
        run_source=policy.run_source,
        budget_usdt=float(budget_usdt),
        is_first_start=False,
        first_start_buy_only=False,
        current_round_id=str(cycle_id),
        previous_round_id=str(cycle_id - 1) if cycle_id > 1 else None,
        last_rebalance_round_id=last_rebalance_round_id,
        allow_live=allow_live,
        allow_no_trade=allow_no_trade,
        bot_id=bot_id,
    )


def sanitize_context_for_consumer(context: BotContext) -> BotContext:
    """Strip cross-consumer flags if a mismatched BotContext is passed."""
    policy = policy_for_context(context)
    if policy.first_start_eligible:
        return context
    if context.is_first_start or context.first_start_buy_only:
        return BotContext(
            run_source=context.run_source,
            budget_usdt=context.budget_usdt,
            is_first_start=False,
            first_start_buy_only=False,
            previous_round_id=context.previous_round_id,
            current_round_id=context.current_round_id,
            last_rebalance_round_id=context.last_rebalance_round_id,
            user_risk_level=context.user_risk_level,
            allow_live=context.allow_live,
            allow_no_trade=context.allow_no_trade,
            bot_id=context.bot_id,
        )
    return context
