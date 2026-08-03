"""Transactional persistence for V2 formula versions and analysis decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import DynamicV2Config, FormulaCoefficients


class DynamicV2AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def ensure_champion(
        self,
        coefficients: FormulaCoefficients,
        config: DynamicV2Config,
    ) -> str:
        version_id = coefficients.version
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.execute(
            text(
                """
                INSERT INTO dynamic_formula_versions
                    (id, version, status, coefficients_json, hard_limits_json,
                     soft_limits_json, created_at, activated_at)
                VALUES
                    (:id, :version, 'CHAMPION', :coefficients, :hard_limits,
                     :soft_limits, :created_at, :activated_at)
                ON CONFLICT(version) DO NOTHING
                """
            ),
            {
                "id": version_id,
                "version": coefficients.version,
                "coefficients": json.dumps(
                    coefficients.to_dict(), ensure_ascii=False, sort_keys=True
                ),
                "hard_limits": json.dumps(
                    {
                        "spot_only": True,
                        "grid_count_immutable": True,
                        "active_grid_immutable": True,
                        "min_base_ratio": str(config.min_base_ratio),
                        "max_base_ratio": str(config.max_base_ratio),
                    },
                    sort_keys=True,
                ),
                "soft_limits": json.dumps(
                    config.to_dict(), ensure_ascii=False, sort_keys=True
                ),
                "created_at": now,
                "activated_at": now,
            },
        )
        return version_id

    def record_analysis(
        self,
        *,
        analysis_run_id: str,
        decision_id: str,
        idempotency_key: str,
        state_version: int,
        symbol: str,
        turn_id: int,
        formula_version_id: str,
        data_quality_score: Any,
        market_state: Mapping[str, Any],
        reference_parameters: Mapping[str, Any],
        previous_parameters: Mapping[str, Any],
        candidate_parameters: Mapping[str, Any],
        applied_parameters: Mapping[str, Any],
        eligible_grid_ids: Sequence[str],
        protected_grid_ids: Sequence[str],
        decision: str,
        rejection_reasons: Sequence[str],
        next_analysis_at: Optional[str],
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        next_at = None
        if next_analysis_at:
            try:
                next_at = datetime.fromisoformat(
                    str(next_analysis_at).replace("Z", "+00:00")
                ).astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                next_at = None
        self.db.execute(
            text(
                """
                INSERT INTO dynamic_analysis_runs
                    (id, decision_id, idempotency_key, state_version, symbol,
                     turn_id, formula_version_id, started_at, completed_at,
                     data_quality_score, market_state_json,
                     reference_parameters_json, previous_parameters_json,
                     candidate_parameters_json, applied_parameters_json,
                     eligible_grid_ids_json, protected_grid_ids_json, decision,
                     rejection_reasons_json, next_analysis_at)
                VALUES
                    (:id, :decision_id, :idempotency_key, :state_version,
                     :symbol, :turn_id, :formula_version_id, :started_at,
                     :completed_at, :data_quality_score, :market_state_json,
                     :reference_parameters_json, :previous_parameters_json,
                     :candidate_parameters_json, :applied_parameters_json,
                     :eligible_grid_ids_json, :protected_grid_ids_json,
                     :decision, :rejection_reasons_json, :next_analysis_at)
                ON CONFLICT(idempotency_key) DO NOTHING
                """
            ),
            {
                "id": analysis_run_id,
                "decision_id": decision_id,
                "idempotency_key": idempotency_key,
                "state_version": state_version,
                "symbol": symbol,
                "turn_id": turn_id,
                "formula_version_id": formula_version_id,
                "started_at": now,
                "completed_at": now,
                "data_quality_score": str(data_quality_score),
                "market_state_json": json.dumps(
                    dict(market_state), ensure_ascii=False, sort_keys=True
                ),
                "reference_parameters_json": json.dumps(
                    dict(reference_parameters), ensure_ascii=False, sort_keys=True
                ),
                "previous_parameters_json": json.dumps(
                    dict(previous_parameters), ensure_ascii=False, sort_keys=True
                ),
                "candidate_parameters_json": json.dumps(
                    dict(candidate_parameters), ensure_ascii=False, sort_keys=True
                ),
                "applied_parameters_json": json.dumps(
                    dict(applied_parameters), ensure_ascii=False, sort_keys=True
                ),
                "eligible_grid_ids_json": json.dumps(list(eligible_grid_ids)),
                "protected_grid_ids_json": json.dumps(list(protected_grid_ids)),
                "decision": decision,
                "rejection_reasons_json": json.dumps(
                    list(rejection_reasons), ensure_ascii=False
                ),
                "next_analysis_at": next_at,
            },
        )
        # The caller persists bot_engine_state immediately afterwards. Keeping
        # this insert in the same transaction makes the parameter package and
        # its audit decision commit (or roll back) together.
