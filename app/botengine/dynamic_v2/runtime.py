"""Runtime factory and lightweight safety check used by the orchestrator."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from app.utils.parse_utils import parse_bool

from .config import DynamicV2Config
from .service import DynamicModeV2


_ENGINES: Dict[tuple, DynamicModeV2] = {}


def get_engine(raw_config: Mapping[str, Any]) -> DynamicModeV2:
    shadow = (
        parse_bool(raw_config.get("dynamic_mode_v2_shadow"))
        if "dynamic_mode_v2_shadow" in raw_config
        else True
    )
    key = (shadow,)
    if key not in _ENGINES:
        _ENGINES[key] = DynamicModeV2(
            DynamicV2Config(enabled=True, shadow_mode=shadow)
        )
    return _ENGINES[key]


def micro_risk_check(state: Dict[str, Any]) -> Dict[str, Any]:
    """No parameter production: only freeze/kill-switch signals."""
    connected = not bool(state.get("last_error_code"))
    uncertain_order = bool(state.get("_reconciliation_unknown"))
    balance_mismatch = bool(state.get("_balance_drift_detected"))
    reasons = []
    if not connected:
        reasons.append("EXCHANGE_CONNECTION")
    if uncertain_order:
        reasons.append("ORDER_STATUS_UNCERTAIN")
    if balance_mismatch:
        reasons.append("BALANCE_MISMATCH")
    result = {"healthy": not reasons, "reasons": reasons}
    if reasons:
        state["_dynamic_v2_kill_switch"] = {
            "active": True,
            "reasons": reasons,
        }
    return result
