"""Template stability layer — reduce template flip-flop between cycles."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_param_score.models import FinalAction, RegimeTag

# Override stability for safety-critical regimes/actions
_STABILITY_OVERRIDE_REGIMES = frozenset({
    RegimeTag.DUMP_RISK.value,
    RegimeTag.NO_TRADE.value,
    RegimeTag.LOW_LIQUIDITY.value,
    RegimeTag.SPREAD_UNSAFE.value,
    RegimeTag.NO_DATA.value,
})

_STABILITY_OVERRIDE_ACTIONS = frozenset({
    FinalAction.NO_TRADE.value,
    FinalAction.WAIT.value,
    "DATA_STALE_SAFE_WAIT",
    "RECOVERY_SELL",
})

MIN_TEMPLATE_SCORE_IMPROVEMENT = 8.0


def apply_template_stability(
    *,
    previous_template_key: Optional[str],
    candidate_template_key: Optional[str],
    candidate_score: float,
    previous_score: float,
    regime: str,
    final_action: str,
    risk_state: str,
    exposure_tier: str = "",
) -> Dict[str, Any]:
    """Return stability decision; may keep previous template when delta too small."""
    telemetry: Dict[str, Any] = {
        "previous_template": previous_template_key,
        "candidate_template": candidate_template_key,
        "kept_previous": False,
        "reason": None,
    }

    if not previous_template_key or not candidate_template_key:
        telemetry["reason"] = "no_previous"
        return telemetry

    if previous_template_key == candidate_template_key:
        telemetry["reason"] = "same_template"
        return telemetry

    if regime in _STABILITY_OVERRIDE_REGIMES:
        telemetry["reason"] = "regime_override"
        return telemetry

    if final_action in _STABILITY_OVERRIDE_ACTIONS:
        telemetry["reason"] = "action_override"
        return telemetry

    if exposure_tier == "OVEREXPOSED":
        telemetry["reason"] = "exposure_override"
        return telemetry

    if risk_state == "BLOCKED":
        telemetry["reason"] = "risk_blocked_override"
        return telemetry

    delta = float(candidate_score or 0.0) - float(previous_score or 0.0)
    if delta < MIN_TEMPLATE_SCORE_IMPROVEMENT:
        telemetry["kept_previous"] = True
        telemetry["reason"] = "delta_too_small"
        telemetry["score_delta"] = round(delta, 2)
        return telemetry

    telemetry["reason"] = "candidate_better"
    telemetry["score_delta"] = round(delta, 2)
    return telemetry
