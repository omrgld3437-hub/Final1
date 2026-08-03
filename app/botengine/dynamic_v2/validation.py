"""Ordered all-or-nothing candidate validation."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from .config import DynamicV2Config
from .math_engine import EPSILON, ceil_to_tick, floor_to_step, floor_to_tick
from .models import (
    BalanceSnapshot,
    DynamicParameterCandidate,
    GridRuntimeState,
    GridSnapshot,
    ONE,
    TurnReferenceParameters,
    ValidationResult,
    ZERO,
)


D = Decimal


class ParameterValidationEngine:
    def __init__(self, config: DynamicV2Config):
        self.config = config

    @staticmethod
    def _strictly_increasing(values: Sequence[Decimal]) -> bool:
        return all(left < right for left, right in zip(values, values[1:]))

    @staticmethod
    def minimum_profit_trigger(
        buy_fee_rate: Decimal,
        sell_fee_rate: Decimal,
        expected_buy_slippage_rate: Decimal,
        expected_sell_slippage_rate: Decimal,
        safety_margin: Decimal,
    ) -> Decimal:
        buy_cost = buy_fee_rate + expected_buy_slippage_rate
        sell_cost = sell_fee_rate + expected_sell_slippage_rate
        if sell_cost >= ONE:
            raise ValueError("sell cost must be below 1")
        required = ((ONE + buy_cost) / (ONE - sell_cost)) * (
            ONE + safety_margin
        )
        return required - ONE

    def validate(
        self,
        candidate: DynamicParameterCandidate,
        reference: TurnReferenceParameters,
        balances: BalanceSnapshot,
        buy_grids: Sequence[GridSnapshot],
        sell_grids: Sequence[GridSnapshot],
        *,
        data_quality: Decimal,
        exchange_connected: bool,
        symbol_trading: bool,
        min_notional: Decimal,
        min_qty: Decimal,
        max_qty: Optional[Decimal],
        tick_size: Decimal,
        step_size: Decimal,
        buy_fee_rate: Decimal,
        sell_fee_rate: Decimal,
        expected_buy_slippage_rate: Decimal,
        expected_sell_slippage_rate: Decimal,
        minimum_gap: Decimal,
    ) -> ValidationResult:
        result = ValidationResult()

        def check(ok: bool, code: str) -> None:
            result.checks.append(code)
            if not ok:
                result.reject(code)

        check(data_quality >= self.config.data_quality_limited, "DATA_QUALITY")
        check(
            candidate.confidence >= self.config.minimum_confidence,
            "ANALYSIS_CONFIDENCE",
        )
        check(
            len(candidate.buy_grid_trigger_percentages)
            == len(reference.buy_grid_trigger_percentages)
            and len(candidate.sell_grid_trigger_percentages)
            == len(reference.sell_grid_trigger_percentages),
            "GRID_COUNT_IMMUTABLE",
        )
        check(
            abs(
                candidate.target_base_ratio
                + candidate.target_quote_ratio
                - ONE
            )
            <= EPSILON,
            "BASE_QUOTE_SUM",
        )
        check(
            all(x > ZERO for x in candidate.buy_grid_trigger_percentages)
            and all(x > ZERO for x in candidate.sell_grid_trigger_percentages),
            "GRID_PERCENT_POSITIVE",
        )
        check(
            self._strictly_increasing(
                candidate.buy_grid_trigger_percentages
            )
            and self._strictly_increasing(
                candidate.sell_grid_trigger_percentages
            ),
            "GRID_ORDER",
        )
        gaps = [
            right - left
            for values in (
                candidate.buy_grid_trigger_percentages,
                candidate.sell_grid_trigger_percentages,
            )
            for left, right in zip(values, values[1:])
        ]
        check(all(gap >= minimum_gap for gap in gaps), "MINIMUM_GRID_GAP")
        buy_prices = [
            balances.mid_price * (ONE - pct / D("100"))
            for pct in candidate.buy_grid_trigger_percentages
        ]
        sell_prices = [
            balances.mid_price * (ONE + pct / D("100"))
            for pct in candidate.sell_grid_trigger_percentages
        ]
        check(
            all(price < balances.mid_price for price in buy_prices)
            and all(price > balances.mid_price for price in sell_prices),
            "CURRENT_PRICE_SIDE",
        )
        eligible_buy_amounts = [
            amount
            for amount, grid in zip(candidate.buy_grid_amounts, buy_grids)
            if grid.status == GridRuntimeState.WAITING_UNTRIGGERED
        ]
        eligible_sell_amounts = [
            amount
            for amount, grid in zip(candidate.sell_grid_amounts, sell_grids)
            if grid.status == GridRuntimeState.WAITING_UNTRIGGERED
        ]
        check(
            all(amount >= ZERO for amount in eligible_buy_amounts),
            "BUY_AMOUNT_POSITIVE",
        )
        check(
            all(amount >= ZERO for amount in eligible_sell_amounts),
            "SELL_AMOUNT_POSITIVE",
        )
        check(
            abs(sum(candidate.buy_grid_amount_weights, ZERO) - ONE) <= EPSILON,
            "BUY_WEIGHT_SUM",
        )
        check(
            abs(sum(candidate.sell_grid_amount_weights, ZERO) - ONE) <= EPSILON,
            "SELL_WEIGHT_SUM",
        )
        check(
            sum(eligible_buy_amounts, ZERO)
            + sum(
                (
                    grid.protected_amount
                    for grid in buy_grids
                    if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
                ),
                ZERO,
            )
            + self.config.quote_safety_reserve
            <= balances.free_quote
            + EPSILON,
            "QUOTE_BUDGET",
        )
        check(
            sum(eligible_sell_amounts, ZERO)
            + sum(
                (
                    grid.protected_amount
                    for grid in sell_grids
                    if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
                ),
                ZERO,
            )
            + self.config.base_safety_reserve
            <= balances.free_base
            + EPSILON,
            "BASE_BUDGET",
        )
        rounded_buy_prices = [
            floor_to_tick(price, tick_size) for price in buy_prices
        ]
        rounded_sell_prices = [
            ceil_to_tick(price, tick_size) for price in sell_prices
        ]
        rounded_sell_qty = [
            floor_to_step(amount, step_size) for amount in eligible_sell_amounts
        ]
        check(
            all(
                amount == ZERO or amount >= min_notional
                for amount in eligible_buy_amounts
            )
            and all(
                qty == ZERO
                or (
                    qty >= min_qty
                    and (max_qty is None or qty <= max_qty)
                    and qty * price >= min_notional
                )
                for qty, price in zip(
                    rounded_sell_qty,
                    [
                        price
                        for price, grid in zip(rounded_sell_prices, sell_grids)
                        if grid.status == GridRuntimeState.WAITING_UNTRIGGERED
                    ],
                )
            ),
            "EXCHANGE_FILTERS",
        )
        check(
            candidate.buy_grid_trailing_percentage
            < min(candidate.buy_grid_trigger_percentages)
            and candidate.sell_grid_trailing_percentage
            < min(candidate.sell_grid_trigger_percentages),
            "TRAILING_TRIGGER_LIMIT",
        )
        minimum_profit = self.minimum_profit_trigger(
            buy_fee_rate,
            sell_fee_rate,
            expected_buy_slippage_rate,
            expected_sell_slippage_rate,
            self.config.profit_safety_margin,
        ) * D("100")
        check(
            candidate.profit_buy_trigger_percentage >= minimum_profit
            and candidate.profit_sell_trigger_percentage >= minimum_profit,
            "PROFIT_COST_FLOOR",
        )
        protected_ok = all(
            (
                candidate.buy_grid_trigger_percentages[grid.index]
                == grid.trigger_percentage
                and candidate.buy_grid_amounts[grid.index] == grid.amount
            )
            for grid in buy_grids
            if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
        ) and all(
            (
                candidate.sell_grid_trigger_percentages[grid.index]
                == grid.trigger_percentage
                and candidate.sell_grid_amounts[grid.index] == grid.amount
            )
            for grid in sell_grids
            if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
        )
        check(protected_ok, "ACTIVE_GRID_PROTECTION")
        check(exchange_connected and symbol_trading, "EXCHANGE_CONNECTION")
        check(bool(candidate.idempotency_key), "IDEMPOTENCY")
        candidate.validation_result = result
        return result
