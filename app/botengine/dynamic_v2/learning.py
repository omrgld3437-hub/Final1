"""Outcome, shadow and calibration components.

Calibration only creates a challenger proposal; it never replaces the champion
used by the live formula repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Mapping, Sequence

from .models import DynamicParameterCandidate, ZERO, json_value


D = Decimal


class OutcomeCollector:
    def reward(
        self,
        *,
        net_return: Decimal,
        max_drawdown: Decimal,
        cvar_95: Decimal,
        capital_lock_duration: Decimal,
        fees_and_slippage: Decimal,
        base_quote_deviation: Decimal,
        parameter_instability: Decimal,
        lambdas: Sequence[Decimal] = (
            D("1"),
            D("1"),
            D("0.01"),
            D("1"),
            D("0.5"),
            D("0.5"),
        ),
    ) -> Decimal:
        penalties = (
            max_drawdown,
            cvar_95,
            capital_lock_duration,
            fees_and_slippage,
            base_quote_deviation,
            parameter_instability,
        )
        return net_return - sum(
            (weight * penalty for weight, penalty in zip(lambdas, penalties)),
            ZERO,
        )


@dataclass(frozen=True)
class ChallengerProposal:
    base_formula_version: str
    proposed_coefficients: Mapping[str, Any]
    sample_count: int
    status: str = "DRAFT"


class CoefficientCalibrationEngine:
    def propose(
        self,
        *,
        base_formula_version: str,
        proposed_coefficients: Mapping[str, Any],
        sample_count: int,
    ) -> ChallengerProposal:
        if sample_count <= 0:
            raise ValueError("calibration requires outcomes")
        return ChallengerProposal(
            base_formula_version=base_formula_version,
            proposed_coefficients=dict(proposed_coefficients),
            sample_count=sample_count,
        )

    def activate(self, _proposal: ChallengerProposal) -> None:
        raise RuntimeError(
            "calibration cannot activate live coefficients; "
            "champion promotion requires external approval"
        )


class ShadowEvaluationEngine:
    def compare(
        self,
        candidate: DynamicParameterCandidate,
        current_utility: Decimal,
        candidate_utility: Decimal,
        minimum_improvement: Decimal,
    ) -> Dict[str, Any]:
        improvement = candidate_utility - current_utility
        return {
            "decision_id": candidate.decision_id,
            "current_utility": format(current_utility, "f"),
            "candidate_utility": format(candidate_utility, "f"),
            "improvement": format(improvement, "f"),
            "passes": improvement > minimum_improvement,
        }


class AuditLogEngine:
    @staticmethod
    def decision_payload(
        candidate: DynamicParameterCandidate,
        *,
        decision: str,
        reasons: Sequence[str],
    ) -> Dict[str, Any]:
        return json_value(
            {
                "analysis_run_id": candidate.analysis_run_id,
                "decision_id": candidate.decision_id,
                "formula_version": candidate.formula_version,
                "decision": decision,
                "reasons": list(reasons),
                "candidate": candidate.to_dict(),
            }
        )


class DynamicModeUIAdapter:
    @staticmethod
    def build(
        *,
        enabled: bool,
        shadow_mode: bool,
        market_state: Mapping[str, Any],
        candidate: Mapping[str, Any],
        updated_grid_count: int,
        protected_grid_count: int,
        rejection_reasons: Sequence[str],
        next_analysis_at: str,
    ) -> Dict[str, Any]:
        return {
            "enabled": enabled,
            "shadow_mode": shadow_mode,
            "formula_version": candidate.get("formula_version"),
            "market_state": dict(market_state),
            "candidate": dict(candidate),
            "updated_grid_count": int(updated_grid_count),
            "protected_grid_count": int(protected_grid_count),
            "rejection_reasons": list(rejection_reasons),
            "next_analysis_at": next_analysis_at,
        }
