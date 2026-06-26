"""DPS Engine V2 multi-factor profile scoring."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.dynamic_param_score.param_pool.models import ParamTemplate

# Weighted scoring per spec §12
WEIGHTS = {
    "regime_match_score": 0.20,
    "volatility_fit_score": 0.18,
    "grid_distance_score": 0.18,
    "fee_efficiency_score": 0.12,
    "min_notional_score": 0.10,
    "structure_fit_score": 0.10,
    "trend_risk_score": 0.07,
    "data_quality_score": 0.05,
}

PENALTY_VALUES = {
    "grid_too_close": 12.0,
    "trailing_too_high": 8.0,
    "too_many_grids_for_budget": 10.0,
    "fee_bad_but_grid_not_widened": 15.0,
    "lower_lows_but_buy_grid_too_close": 12.0,
    "higher_highs_but_sell_grid_too_close": 12.0,
    "min_notional_near_fail": 8.0,
    "data_staleness": 6.0,
}


def _norm_distance(a: str, b: str) -> float:
    return 100.0 if a == b else 40.0 if a[:3] == b[:3] else 0.0


def compute_v2_profile_score(
    template: ParamTemplate,
    signature: Dict[str, Any],
    *,
    penalties: List[str] | None = None,
) -> float:
    """Compute final weighted score for a candidate profile."""
    dps = (template.params or {}).get("dps_profile") or {}
    scores: Dict[str, float] = {}

    scores["regime_match_score"] = _norm_distance(
        str(dps.get("regime") or ""),
        str(signature.get("regime") or ""),
    )
    scores["volatility_fit_score"] = _norm_distance(
        str(dps.get("volatility_bin") or ""),
        str(signature.get("volatility_bin") or ""),
    )

    buy_spacing = float(template.params.get("buy_grid_spacing_pct") or 0)
    sell_spacing = float(template.params.get("sell_grid_spacing_pct") or 0)
    min_expected = 1.2 if signature.get("asset_class") == "BTC_ETH_MAJOR" else 1.5
    avg_spacing = (buy_spacing + sell_spacing) / 2 if buy_spacing and sell_spacing else max(buy_spacing, sell_spacing)
    if avg_spacing >= min_expected:
        scores["grid_distance_score"] = min(100.0, 60 + (avg_spacing - min_expected) * 20)
    else:
        scores["grid_distance_score"] = max(0.0, avg_spacing / min_expected * 50)

    fee_class = str(signature.get("fee_class") or "")
    if fee_class == "fee_bad":
        scores["fee_efficiency_score"] = 90.0 if template.final_action == "ACTIVE_DEFENSIVE_GRID" else 30.0
    else:
        scores["fee_efficiency_score"] = 75.0

    scores["min_notional_score"] = 80.0
    scores["structure_fit_score"] = _norm_distance(
        str(dps.get("structure") or ""),
        str(signature.get("structure") or ""),
    )
    scores["trend_risk_score"] = 70.0
    scores["data_quality_score"] = float(signature.get("data_quality_score") or 80)

    final = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    for p in penalties or []:
        final -= PENALTY_VALUES.get(p, 5.0)

    prior = float((template.params or {}).get("score_prior") or 0)
    if prior:
        final = final * 0.85 + prior * 100 * 0.15

    return round(max(0.0, min(100.0, final)), 4)
