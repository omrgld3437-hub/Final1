"""Continuous formula engine; no regime shelves or profile selection."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

from .config import DynamicV2Config, FormulaCoefficients
from .math_engine import (
    EPSILON,
    clip,
    clip01,
    normalize_weights,
    quantize_base_step,
    quantize_multiplier,
)
from .models import (
    ContinuousMarketState,
    DynamicParameterCandidate,
    ONE,
    TurnReferenceParameters,
    ZERO,
)


D = Decimal


def _reference_weights(amounts: Sequence[Decimal]) -> List[Decimal]:
    return normalize_weights(list(amounts))


class FormulaCoefficientRepository:
    """Read-only champion coefficients used by a decision.

    A database-backed repository can implement the same two methods. Keeping the
    default immutable prevents live self-calibration from changing production.
    """

    def __init__(self, champion: Optional[FormulaCoefficients] = None):
        self._champion = champion or FormulaCoefficients()

    def get_champion(self) -> FormulaCoefficients:
        return self._champion

    def challenger(self) -> None:
        return None


class DynamicFormulaEngine:
    def __init__(
        self,
        config: DynamicV2Config,
        coefficients: FormulaCoefficients,
    ):
        self.config = config
        self.coefficients = coefficients

    @staticmethod
    def _level_norm(index: int, count: int) -> Decimal:
        return ZERO if count <= 1 else D(index) / D(count - 1)

    @staticmethod
    def _quiet_range(state: ContinuousMarketState) -> Decimal:
        return (
            state.range_strength
            * (ONE - state.volatility_score)
            * state.regime_stability
        )

    def _base_ratio(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> tuple[Decimal, Decimal, Decimal]:
        c = self.coefficients.base_market
        raw_points = (
            c["up"] * state.upward_trend_strength
            + c["down"] * state.downward_trend_strength
            + c["volatility"] * state.volatility_score
            + c["coin_risk"] * state.coin_risk
            + c["liquidity"] * state.liquidity_risk
            + c["quiet_range"]
            * state.range_strength
            * (ONE - state.volatility_score)
            + c["down_volatility"]
            * state.downward_trend_strength
            * state.volatility_score
            + c["up_stability"]
            * state.upward_trend_strength
            * state.regime_stability
        )
        step = quantize_base_step(raw_points)
        base = clip(
            reference.target_base_ratio + step / D("100"),
            self.config.min_base_ratio,
            self.config.max_base_ratio,
        )
        return base, ONE - base, step

    def _buy_triggers(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> tuple[List[Decimal], List[Decimal]]:
        c = self.coefficients.buy_distance
        quiet = self._quiet_range(state)
        effect = (
            c["down_vol"] * state.downside_volatility_score
            + c["down"] * state.downward_trend_strength
            + c["coin"] * state.coin_risk
            + c["liquidity"] * state.liquidity_risk
            + c["negative_jump"] * state.negative_jump_risk
            + c["down_x_vol"]
            * state.downward_trend_strength
            * state.downside_volatility_score
            + c["vol_x_liquidity"]
            * state.downside_volatility_score
            * state.liquidity_risk
            + c["quiet_range"] * quiet
            + c["up_quiet"]
            * state.upward_trend_strength
            * (ONE - state.volatility_score)
        )
        deepening = clip01(
            D("0.45") * state.downside_volatility_score
            + D("0.35") * state.downward_trend_strength
            + D("0.10") * state.coin_risk
            + D("0.10") * state.negative_jump_risk
        )
        distances: List[Decimal] = []
        multipliers: List[Decimal] = []
        count = len(reference.buy_grid_trigger_percentages)
        for index, distance in enumerate(reference.buy_grid_trigger_percentages):
            level_curve = self._level_norm(index, count) ** D("1.35")
            raw = (
                ONE
                + D("0.55") * effect
                + D("0.35") * deepening * level_curve
            )
            multiplier = quantize_multiplier(raw, D("0.70"), D("1.90"))
            multipliers.append(multiplier)
            distances.append(distance * multiplier)
        return distances, multipliers

    def _sell_triggers(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> tuple[List[Decimal], List[Decimal]]:
        c = self.coefficients.sell_distance
        quiet = self._quiet_range(state)
        effect = (
            c["up_vol"] * state.upside_volatility_score
            + c["up"] * state.upward_trend_strength
            + c["coin"] * state.coin_risk
            + c["liquidity"] * state.liquidity_risk
            + c["positive_jump"] * state.positive_jump_risk
            + c["up_x_vol"]
            * state.upward_trend_strength
            * state.upside_volatility_score
            + c["vol_x_liquidity"]
            * state.upside_volatility_score
            * state.liquidity_risk
            + c["quiet_range"] * quiet
            + c["down_quiet"]
            * state.downward_trend_strength
            * (ONE - state.volatility_score)
        )
        deepening = clip01(
            D("0.45") * state.upside_volatility_score
            + D("0.35") * state.upward_trend_strength
            + D("0.10") * state.coin_risk
            + D("0.10") * state.positive_jump_risk
        )
        distances: List[Decimal] = []
        multipliers: List[Decimal] = []
        count = len(reference.sell_grid_trigger_percentages)
        for index, distance in enumerate(reference.sell_grid_trigger_percentages):
            level_curve = self._level_norm(index, count) ** D("1.35")
            raw = (
                ONE
                + D("0.55") * effect
                + D("0.35") * deepening * level_curve
            )
            multiplier = quantize_multiplier(raw, D("0.70"), D("1.90"))
            multipliers.append(multiplier)
            distances.append(distance * multiplier)
        return distances, multipliers

    def _amount_weights(
        self,
        reference_amounts: Sequence[Decimal],
        shift: Decimal,
    ) -> List[Decimal]:
        reference_weights = _reference_weights(reference_amounts)
        count = len(reference_weights)
        raw: List[Decimal] = []
        for index, weight in enumerate(reference_weights):
            centered = D("2") * self._level_norm(index, count) - ONE
            effect = shift * centered * D("0.65")
            raw.append(weight * effect.exp())
        return normalize_weights(raw)

    def _buy_weights(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> List[Decimal]:
        shift = clip(
            D("0.75") * state.downward_trend_strength
            + D("0.45") * state.downside_volatility_score
            + D("0.20") * state.negative_jump_risk
            + D("0.15") * state.coin_risk
            + D("0.10") * state.liquidity_risk
            - D("0.35") * state.upward_trend_strength
            - D("0.20") * self._quiet_range(state),
            D("-0.50"),
            D("1.50"),
        )
        return self._amount_weights(reference.buy_grid_amounts, shift)

    def _sell_weights(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> List[Decimal]:
        shift = clip(
            D("0.75") * state.upward_trend_strength
            + D("0.45") * state.upside_volatility_score
            + D("0.20") * state.positive_jump_risk
            + D("0.15") * state.coin_risk
            - D("0.65") * state.downward_trend_strength
            - D("0.15") * self._quiet_range(state),
            D("-1.20"),
            D("1.50"),
        )
        return self._amount_weights(reference.sell_grid_amounts, shift)

    def _grid_trailing(
        self,
        reference_value: Decimal,
        state: ContinuousMarketState,
        *,
        downside: bool,
    ) -> tuple[Decimal, Decimal]:
        directional_vol = (
            state.downside_volatility_score
            if downside
            else state.upside_volatility_score
        )
        effect = (
            D("0.40") * state.micro_noise
            + D("0.25") * state.spread_risk
            + D("0.20") * directional_vol
            + D("0.15") * state.coin_risk
        )
        multiplier = quantize_multiplier(
            ONE + D("0.55") * effect, D("0.80"), D("1.60")
        )
        return reference_value * multiplier, multiplier

    def _profit_trigger(
        self,
        reference_value: Decimal,
        state: ContinuousMarketState,
        *,
        buy: bool,
    ) -> tuple[Decimal, Decimal]:
        quiet = self._quiet_range(state)
        if buy:
            effect = (
                D("0.38") * state.downside_volatility_score
                + D("0.28") * state.downward_trend_strength
                + D("0.14") * state.coin_risk
                + D("0.10") * state.liquidity_risk
                + D("0.10") * state.negative_jump_risk
                - D("0.18") * state.upward_trend_strength
                - D("0.10") * quiet
            )
        else:
            effect = (
                D("0.35") * state.upside_volatility_score
                + D("0.30") * state.upward_trend_strength
                + D("0.15") * state.coin_risk
                + D("0.10") * state.liquidity_risk
                + D("0.10") * state.positive_jump_risk
                - D("0.25") * state.downward_trend_strength
                - D("0.12") * quiet
            )
        multiplier = quantize_multiplier(
            ONE + D("0.60") * effect, D("0.70"), D("1.80")
        )
        return reference_value * multiplier, multiplier

    def _profit_trailing(
        self,
        reference_value: Decimal,
        state: ContinuousMarketState,
        *,
        buy: bool,
    ) -> tuple[Decimal, Decimal]:
        directional_vol = (
            state.downside_volatility_score
            if buy
            else state.upside_volatility_score
        )
        directional_trend = (
            state.downward_trend_strength
            if buy
            else state.upward_trend_strength
        )
        opposite = (
            state.upward_trend_strength
            if buy
            else state.downward_trend_strength
        )
        effect = (
            D("0.40") * state.micro_noise
            + D("0.25") * directional_vol
            + D("0.20") * directional_trend
            + D("0.10") * state.coin_risk
            + D("0.05") * state.spread_risk
            - D("0.15") * opposite
        )
        multiplier = quantize_multiplier(
            ONE + D("0.55") * effect, D("0.70"), D("1.70")
        )
        return reference_value * multiplier, multiplier

    @staticmethod
    def _decision_identity(
        *,
        analysis_run_id: str,
        state_version: int,
        formula_version: str,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
    ) -> tuple[str, str]:
        payload = {
            "analysis_run_id": analysis_run_id,
            "state_version": state_version,
            "formula_version": formula_version,
            "reference": reference.to_dict(),
            "market_state": state.to_dict(),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return digest[:24], digest

    def build_candidate(
        self,
        reference: TurnReferenceParameters,
        state: ContinuousMarketState,
        *,
        state_version: int,
        analysis_run_id: Optional[str] = None,
    ) -> DynamicParameterCandidate:
        analysis_id = analysis_run_id or uuid.uuid4().hex
        base, quote, base_step = self._base_ratio(reference, state)
        buy_triggers, buy_multipliers = self._buy_triggers(reference, state)
        sell_triggers, sell_multipliers = self._sell_triggers(reference, state)
        buy_weights = self._buy_weights(reference, state)
        sell_weights = self._sell_weights(reference, state)
        buy_trailing, buy_trailing_multiplier = self._grid_trailing(
            reference.buy_grid_trailing_percentage, state, downside=True
        )
        sell_trailing, sell_trailing_multiplier = self._grid_trailing(
            reference.sell_grid_trailing_percentage, state, downside=False
        )
        profit_buy_trigger, profit_buy_trigger_multiplier = self._profit_trigger(
            reference.profit_buy_trigger_percentage, state, buy=True
        )
        profit_sell_trigger, profit_sell_trigger_multiplier = self._profit_trigger(
            reference.profit_sell_trigger_percentage, state, buy=False
        )
        profit_buy_trailing, profit_buy_trailing_multiplier = self._profit_trailing(
            reference.profit_buy_trailing_percentage, state, buy=True
        )
        profit_sell_trailing, profit_sell_trailing_multiplier = self._profit_trailing(
            reference.profit_sell_trailing_percentage, state, buy=False
        )
        decision_id, idempotency_key = self._decision_identity(
            analysis_run_id=analysis_id,
            state_version=state_version,
            formula_version=self.coefficients.version,
            reference=reference,
            state=state,
        )
        confidence = clip01(state.data_quality * state.regime_stability)
        return DynamicParameterCandidate(
            target_base_ratio=base,
            target_quote_ratio=quote,
            buy_grid_trigger_percentages=buy_triggers,
            sell_grid_trigger_percentages=sell_triggers,
            buy_grid_amount_weights=buy_weights,
            sell_grid_amount_weights=sell_weights,
            buy_grid_amounts=[ZERO for _ in buy_weights],
            sell_grid_amounts=[ZERO for _ in sell_weights],
            buy_grid_trailing_percentage=buy_trailing,
            sell_grid_trailing_percentage=sell_trailing,
            profit_buy_trigger_percentage=profit_buy_trigger,
            profit_sell_trigger_percentage=profit_sell_trigger,
            profit_buy_trailing_percentage=profit_buy_trailing,
            profit_sell_trailing_percentage=profit_sell_trailing,
            confidence=confidence,
            explanations=[
                f"base_market_step_pp={format(base_step, 'f')}",
                "all_values_recomputed_from_immutable_reference",
            ],
            multipliers={
                "buy_trigger": buy_multipliers,
                "sell_trigger": sell_multipliers,
                "buy_trailing": buy_trailing_multiplier,
                "sell_trailing": sell_trailing_multiplier,
                "profit_buy_trigger": profit_buy_trigger_multiplier,
                "profit_sell_trigger": profit_sell_trigger_multiplier,
                "profit_buy_trailing": profit_buy_trailing_multiplier,
                "profit_sell_trailing": profit_sell_trailing_multiplier,
            },
            analysis_run_id=analysis_id,
            decision_id=decision_id,
            state_version=state_version,
            idempotency_key=idempotency_key,
            formula_version=self.coefficients.version,
        )
