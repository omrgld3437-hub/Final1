"""Decision persistence — DB + structured JSON logs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.log_retention import maybe_prune_after_write
from app.services.dynamic_param_score.models import DynamicParamDecision
from app.services.dynamic_param_score.utils import json_safe

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOG_DIR = _PROJECT_ROOT / C.LOG_DIR_NAME


def _file_log_enabled() -> bool:
    return os.getenv("DPS_FILE_LOG_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _hash_obj(obj: Any) -> str:
    raw = json.dumps(json_safe(obj), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _compact_decision_for_log(decision: DynamicParamDecision) -> Dict[str, Any]:
    """File log payload — omit redundant/heavy telemetry blobs."""
    tel = _compact_telemetry(decision.telemetry, keep_indicators=False)

    return {
        "decision_id": decision.decision_id,
        "symbol": decision.symbol,
        "timestamp": decision.timestamp,
        "run_source": decision.run_source,
        "final_action": decision.final_action,
        "deployable": decision.deployable,
        "param_score": decision.param_score,
        "confidence_score": decision.confidence_score,
        "risk_score": decision.risk_score,
        "regime_tag": decision.regime_tag,
        "risk_state": decision.risk_state,
        "selected_profile_name": decision.selected_profile_name,
        "blocking_reasons": decision.blocking_reasons,
        "warnings": decision.warnings,
        "explain": decision.explain,
        "telemetry": tel,
        "action_detail": decision.action_detail,
    }


def _compact_telemetry(
    telemetry: Optional[Dict[str, Any]], *, keep_indicators: bool = True
) -> Dict[str, Any]:
    """Remove diagnostic fan-out while preserving the persisted decision."""
    tel = dict(telemetry or {})
    if not keep_indicators:
        tel.pop("indicators", None)

    pool = tel.get("param_pool")
    if isinstance(pool, dict):
        pool = dict(pool)
        pool.pop("filtered_out", None)
        tel["param_pool"] = pool
    return tel


def save_decision_log(
    decision: DynamicParamDecision,
    input_summary: Dict[str, Any],
    raw_indicators: Dict[str, Any],
    pre_safety_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Write structured log file; returns path (empty when file logging disabled)."""
    path = _LOG_DIR / f"{decision.decision_id}.json"
    if not _file_log_enabled():
        return ""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "decision_id": decision.decision_id,
        "input_summary": input_summary,
        "raw_indicators": raw_indicators,
        "normalized_scores": decision.telemetry.get("sub_scores"),
        "regime_decision": {
            "regime_tag": decision.regime_tag,
            "risk_state": decision.risk_state,
        },
        "selected_profile": decision.selected_profile_name,
        "pre_safety_params": pre_safety_params,
        "post_safety_params": decision.params.to_dict() if decision.params else None,
        "gates": [g.to_dict() for g in decision.safety_gates],
        "final_decision": _compact_decision_for_log(decision),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(json_safe(payload), f, indent=2, ensure_ascii=False)
        maybe_prune_after_write(_LOG_DIR)
    except OSError as e:
        logger.warning("DPS log write failed %s: %s", path, e)
    return str(path)


def save_decision_db(
    decision: DynamicParamDecision,
    bot_id: Optional[int],
    market_hash: str,
    portfolio_hash: str,
    round_id: Optional[str] = None,
) -> None:
    """Persist decision snapshot to dynamic_param_decisions table."""
    try:
        from app.db.base import engine
        from sqlalchemy import text

        if engine is None:
            return

        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO dynamic_param_decisions (
                        id, bot_id, symbol, run_source, round_id, timestamp,
                        param_score, confidence_score, risk_score,
                        regime_tag, risk_state, final_action, deployable,
                        selected_profile_name, params_json, telemetry_json,
                        safety_gates_json, blocking_reasons_json, warnings_json,
                        explanation, market_data_hash, portfolio_state_hash
                    ) VALUES (
                        :id, :bot_id, :symbol, :run_source, :round_id, :timestamp,
                        :param_score, :confidence_score, :risk_score,
                        :regime_tag, :risk_state, :final_action, :deployable,
                        :selected_profile_name, :params_json, :telemetry_json,
                        :safety_gates_json, :blocking_reasons_json, :warnings_json,
                        :explanation, :market_data_hash, :portfolio_state_hash
                    )
                    """
                ),
                {
                    "id": decision.decision_id,
                    "bot_id": bot_id,
                    "symbol": decision.symbol,
                    "run_source": decision.run_source,
                    "round_id": round_id,
                    "timestamp": decision.timestamp,
                    "param_score": decision.param_score,
                    "confidence_score": decision.confidence_score,
                    "risk_score": decision.risk_score,
                    "regime_tag": decision.regime_tag,
                    "risk_state": decision.risk_state,
                    "final_action": decision.final_action,
                    "deployable": 1 if decision.deployable else 0,
                    "selected_profile_name": decision.selected_profile_name,
                    "params_json": json.dumps(
                        decision.params.to_dict() if decision.params else None
                    ),
                    "telemetry_json": json.dumps(
                        json_safe(_compact_telemetry(decision.telemetry))
                    ),
                    "safety_gates_json": json.dumps(
                        [g.to_dict() for g in decision.safety_gates]
                    ),
                    "blocking_reasons_json": json.dumps(decision.blocking_reasons),
                    "warnings_json": json.dumps(decision.warnings),
                    "explanation": decision.explain,
                    "market_data_hash": market_hash,
                    "portfolio_state_hash": portfolio_hash,
                },
            )
            conn.commit()
    except Exception as e:
        logger.warning("DPS DB save failed: %s", e)


def persist_decision(
    decision: DynamicParamDecision,
    market_data: Any,
    portfolio: Any,
    bot_id: Optional[int] = None,
    round_id: Optional[str] = None,
    raw_indicators: Optional[Dict[str, Any]] = None,
    pre_safety_params: Optional[Dict[str, Any]] = None,
) -> None:
    m_hash = _hash_obj(market_data.to_dict() if hasattr(market_data, "to_dict") else market_data)
    p_hash = _hash_obj(portfolio.to_dict() if hasattr(portfolio, "to_dict") else portfolio)
    save_decision_log(
        decision,
        {
            "symbol": decision.symbol,
            "run_source": decision.run_source,
            "bot_id": bot_id,
            "round_id": round_id,
        },
        raw_indicators or {},
        pre_safety_params,
    )
    save_decision_db(decision, bot_id, m_hash, p_hash, round_id)
