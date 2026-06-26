"""Mathematical validation scoring for parameter profiles."""

from __future__ import annotations

from typing import Any, Dict

from app.services.dynamic_param_score.param_generator.candidate_validator import (
    hard_validate_profile,
    soft_validate_profile,
)


def compute_score_prior(profile: Dict[str, Any]) -> float:
    """Lightweight mathematical validation score (no full backtest)."""
    ok, hard_errors = hard_validate_profile(profile)
    if not ok:
        return max(0.0, 0.3 - 0.05 * len(hard_errors))

    soft_score, _ = soft_validate_profile(profile)
    base = 0.55 + 0.25 * soft_score

    fee = profile.get("fee_class")
    if fee == "low_fee":
        base += 0.05
    elif fee == "fee_bad" and profile.get("safety_level") == "ACTIVE_DEFENSIVE":
        base += 0.03

    regime = profile.get("regime")
    if regime in ("BALANCED_RANGE", "CALM_RANGE"):
        base += 0.04

    grids = profile.get("buy_grid_pcts") or profile.get("sell_grid_pcts") or []
    if grids and grids[0] >= 1.2:
        base += 0.03

    return round(min(0.95, max(0.35, base)), 4)


def sample_walk_forward_stub(profile: Dict[str, Any]) -> Dict[str, float]:
    """Placeholder walk-forward metrics derived from profile geometry."""
    prior = compute_score_prior(profile)
    first = 0.0
    if profile.get("buy_grid_pcts"):
        first = float(profile["buy_grid_pcts"][0])
    elif profile.get("sell_grid_pcts"):
        first = float(profile["sell_grid_pcts"][0])
    spacing_quality = min(1.0, first / 1.5) if first else 0.5
    return {
        "score_prior": prior,
        "spacing_quality": round(spacing_quality, 4),
        "math_validation_pass": 1.0 if prior >= 0.5 else 0.0,
    }
