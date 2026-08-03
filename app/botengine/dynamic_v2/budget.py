"""Consumed/protected/remaining side-budget accounting."""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from .config import DynamicV2Config
from .math_engine import clip, normalize_weights
from .models import (
    BalanceSnapshot,
    BudgetLedger,
    ContinuousMarketState,
    DynamicParameterCandidate,
    GridRuntimeState,
    GridSnapshot,
    ONE,
    TurnReferenceParameters,
    ZERO,
)


D = Decimal


class SideBudgetAccountingEngine:
    @staticmethod
    def ledger(target: Decimal, grids: Iterable[GridSnapshot]) -> BudgetLedger:
        consumed = ZERO
        protected = ZERO
        for grid in grids:
            consumed += max(grid.filled_amount, ZERO)
            if grid.status not in (
                GridRuntimeState.WAITING_UNTRIGGERED,
                GridRuntimeState.FILLED,
                GridRuntimeState.COMPLETED,
            ):
                protected += max(grid.protected_amount, grid.amount - grid.filled_amount, ZERO)
        remaining = max(ZERO, target - consumed - protected)
        return BudgetLedger(
            target_budget=target,
            consumed_budget=consumed,
            protected_budget=protected,
            remaining_budget=remaining,
            over_target=max(ZERO, consumed + protected - target),
        )

    @staticmethod
    def distribute(
        ledger: BudgetLedger,
        all_grids: Sequence[GridSnapshot],
        desired_weights: Sequence[Decimal],
    ) -> Dict[str, Decimal]:
        if len(all_grids) != len(desired_weights):
            raise ValueError("grid/weight count mismatch")
        eligible = [
            (grid, desired_weights[index])
            for index, grid in enumerate(all_grids)
            if grid.status == GridRuntimeState.WAITING_UNTRIGGERED
        ]
        if not eligible:
            return {}
        normalized = normalize_weights([weight for _, weight in eligible])
        result = {
            grid.grid_id: ledger.remaining_budget * normalized[index]
            for index, (grid, _) in enumerate(eligible)
        }
        last_grid = eligible[-1][0]
        result[last_grid.grid_id] += ledger.remaining_budget - sum(
            result.values(), ZERO
        )
        return result


class PortfolioBudgetEngine:
    def __init__(self, config: DynamicV2Config):
        self.config = config
        self.accounting = SideBudgetAccountingEngine()

    def allocate(
        self,
        candidate: DynamicParameterCandidate,
        reference: TurnReferenceParameters,
        market_state: ContinuousMarketState,
        balances: BalanceSnapshot,
        buy_grids: Sequence[GridSnapshot],
        sell_grids: Sequence[GridSnapshot],
        reference_portfolio_value: Optional[Decimal] = None,
    ) -> tuple[BudgetLedger, BudgetLedger]:
        portfolio = (
            reference_portfolio_value
            if reference_portfolio_value is not None
            and reference_portfolio_value > ZERO
            else balances.portfolio_value
        )
        if portfolio <= ZERO or balances.mid_price <= ZERO:
            raise ValueError("portfolio value and mid price must be positive")
        base_error = candidate.target_base_ratio - balances.current_base_ratio
        normalized_error = clip(
            base_error / self.config.ratio_band, D("-1"), ONE
        )
        buy_utilization = clip(
            reference.reference_buy_utilization
            * (
                ONE
                + D("0.45") * normalized_error
                - D("0.20") * market_state.downward_trend_strength
                - D("0.15") * market_state.liquidity_risk
                - D("0.10") * market_state.coin_risk
            ),
            self.config.min_buy_utilization,
            self.config.max_buy_utilization,
        )
        sell_utilization = clip(
            reference.reference_sell_utilization
            * (
                ONE
                - D("0.45") * normalized_error
                + D("0.15") * market_state.downward_trend_strength
                - D("0.10") * market_state.liquidity_risk
            ),
            self.config.min_sell_utilization,
            self.config.max_sell_utilization,
        )
        target_buy_quote = (
            portfolio * candidate.target_quote_ratio * buy_utilization
        )
        target_sell_base = (
            portfolio
            * candidate.target_base_ratio
            / balances.mid_price
            * sell_utilization
        )
        buy_ledger = self.accounting.ledger(target_buy_quote, buy_grids)
        sell_ledger = self.accounting.ledger(target_sell_base, sell_grids)
        buy_available_for_new = max(
            ZERO,
            balances.free_quote
            - buy_ledger.protected_budget
            - self.config.quote_safety_reserve,
        )
        sell_available_for_new = max(
            ZERO,
            balances.free_base
            - sell_ledger.protected_budget
            - self.config.base_safety_reserve,
        )
        buy_ledger = BudgetLedger(
            target_budget=buy_ledger.target_budget,
            consumed_budget=buy_ledger.consumed_budget,
            protected_budget=buy_ledger.protected_budget,
            remaining_budget=min(
                buy_ledger.remaining_budget, buy_available_for_new
            ),
            over_target=buy_ledger.over_target,
        )
        sell_ledger = BudgetLedger(
            target_budget=sell_ledger.target_budget,
            consumed_budget=sell_ledger.consumed_budget,
            protected_budget=sell_ledger.protected_budget,
            remaining_budget=min(
                sell_ledger.remaining_budget, sell_available_for_new
            ),
            over_target=sell_ledger.over_target,
        )
        buy_allocations = self.accounting.distribute(
            buy_ledger, buy_grids, candidate.buy_grid_amount_weights
        )
        sell_allocations = self.accounting.distribute(
            sell_ledger, sell_grids, candidate.sell_grid_amount_weights
        )
        candidate.buy_grid_amounts = [
            buy_allocations.get(grid.grid_id, grid.amount) for grid in buy_grids
        ]
        candidate.sell_grid_amounts = [
            sell_allocations.get(grid.grid_id, grid.amount) for grid in sell_grids
        ]
        if buy_ledger.over_target > ZERO:
            candidate.risk_flags.append("BUY_BUDGET_ALREADY_OVER_TARGET")
        if sell_ledger.over_target > ZERO:
            candidate.risk_flags.append("SELL_BUDGET_ALREADY_OVER_TARGET")
        candidate.explanations.extend(
            [
                "buy_budget=target-consumed-protected",
                "sell_budget=target-consumed-protected",
            ]
        )
        return buy_ledger, sell_ledger
