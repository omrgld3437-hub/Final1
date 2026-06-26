"""V4 multi-factor profile scoring with structure/grid direction hard gates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    is_forbidden_fallback,
    normalize_route_key,
    structure_code_from_name,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

WEIGHTS = {
    "route_match": 0.30,
    "scenario_fit": 0.20,
    "structure_fit": 0.15,
    "grid_direction_fit": 0.15,
    "base_quote_fit": 0.10,
    "capacity_fit": 0.04,
    "cost_fit": 0.03,
    "data_quality_fit": 0.02,
    "prior_score": 0.01,
}


def _prefix(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a and b and a[:2] == b[:2]:
        return 0.5
    return 0.0


def structure_fit_score(profile_structure: str, sig_structure: str) -> float:
    ps = structure_code_from_name(profile_structure)
    ss = structure_code_from_name(sig_structure)
    if ps == ss:
        return 1.0
    lower = frozenset({"S2", "S6", "S8"})
    higher = frozenset({"S3", "S7", "S9"})
    if (ps in lower and ss in higher) or (ps in higher and ss in lower):
        return 0.0
    if ps in ("S1", "S5") or ss in ("S1", "S5"):
        return 0.4
    return 0.2


def grid_direction_fit_score(dps: Dict[str, Any], signature: Dict[str, Any]) -> float:
    bias = str(signature.get("grid_bias") or "")
    profile_bias = str(dps.get("grid_bias") or "")
    if not bias or not profile_bias:
        return 0.7
    if bias == profile_bias:
        return 1.0
    if bias == "SYMMETRIC" or profile_bias == "SYMMETRIC":
        return 0.6
    return 0.0


def base_quote_fit_score(dps: Dict[str, Any], signature: Dict[str, Any]) -> float:
    base = float(dps.get("base_alloc_frac") or 0.5)
    quote = float(dps.get("quote_alloc_frac") or 0.5)
    bias = str(signature.get("direction_bias") or "")
    if bias == "DOWN_BIAS":
        if base <= 0.35 and quote >= 0.65:
            return 1.0
        if base <= 0.40 and quote >= 0.60:
            return 0.6
        return 0.0
    if bias == "UP_BIAS":
        if base >= 0.55 and quote <= 0.45:
            return 1.0
        if base >= 0.50 and quote <= 0.50:
            return 0.6
        return 0.0
    if 0.40 <= base <= 0.60:
        return 1.0
    return 0.7


def hard_reject_v4(
    template: ParamTemplate,
    signature: Dict[str, Any],
) -> Optional[str]:
    dps = (template.params or {}).get("dps_profile") or {}
    params = template.params or {}

    buy_ladder = (
        params.get("buy_grid_ladder_pcts")
        or dps.get("buy_grid_ladder_pcts")
        or dps.get("buy_grid_pcts")
    )
    sell_ladder = (
        params.get("sell_grid_ladder_pcts")
        or dps.get("sell_grid_ladder_pcts")
        or dps.get("sell_grid_pcts")
    )
    buy_n = int(params.get("buy_grid_count") or dps.get("buy_grid_count") or 0)
    sell_n = int(params.get("sell_grid_count") or dps.get("sell_grid_count") or 0)
    if (buy_n > 0 and not buy_ladder) or (sell_n > 0 and not sell_ladder):
        return "null_grid_ladder"

    sf = structure_fit_score(
        str(dps.get("structure_code") or dps.get("structure") or ""),
        str(signature.get("structure_code") or signature.get("structure") or ""),
    )
    if sf == 0.0:
        return "structure_fit_zero"

    gf = grid_direction_fit_score(dps, signature)
    if gf == 0.0:
        return "grid_direction_fit_zero"

    bq = base_quote_fit_score(dps, signature)
    if bq == 0.0:
        return "base_quote_fit_zero"

    sig_rk = normalize_route_key(
        str(signature.get("route_key") or signature.get("clean_route_key") or "")
    )
    sig_parts = sig_rk.split("|") if sig_rk else []
    from_regime_code = sig_parts[1] if len(sig_parts) >= 5 else str(
        signature.get("regime_code") or signature.get("regime") or ""
    )
    from_asset = sig_parts[0] if len(sig_parts) >= 5 else str(signature.get("asset_code") or "")
    to_rk = normalize_route_key(str(dps.get("route_key") or ""))
    to_parts = to_rk.split("|") if to_rk else []
    to_regime_code = to_parts[1] if len(to_parts) >= 5 else str(
        dps.get("regime_code") or dps.get("regime") or ""
    )
    to_asset = to_parts[0] if len(to_parts) >= 5 else str(dps.get("asset_code") or "")
    if is_forbidden_fallback(
        from_regime_code,
        to_regime_code,
        from_asset=from_asset,
        to_asset=to_asset,
        from_structure=str(signature.get("structure_code") or ""),
        to_structure=to_parts[2] if len(to_parts) >= 5 else str(dps.get("structure_code") or ""),
        from_vol=str(signature.get("vol_code") or ""),
        to_vol=to_parts[3] if len(to_parts) >= 5 else str(dps.get("vol_code") or ""),
    ):
        return "forbidden_fallback_regime"

    if template.final_action in ("WAIT", "SAFE_WAIT", "NO_TRADE"):
        if str(signature.get("fee_code")) in ("F6",) or int(signature.get("data_quality_score") or 80) >= 40:
            return "legacy_wait_profile"

    for side, dist_key in (("buy", "buy_distribution"), ("sell", "sell_distribution")):
        dist = dps.get(dist_key) or params.get(dist_key.replace("distribution", "qty_distribution"))
        if dist and abs(sum(dist) - 100) > 1 and abs(sum(dist) - 1.0) > 0.02:
            return "distribution_not_100"

    return None


def compute_v4_profile_score(
    template: ParamTemplate,
    signature: Dict[str, Any],
    *,
    route_key_matched: bool = False,
    fit_overrides: Optional[Dict[str, float]] = None,
) -> float:
    dps = (template.params or {}).get("dps_profile") or {}
    scores: Dict[str, float] = {}
    overrides = fit_overrides or {}

    sig_route = normalize_route_key(str(signature.get("route_key") or ""))
    prof_route = normalize_route_key(
        str(dps.get("route_key") or (template.params or {}).get("route_key") or "")
    )
    scores["route_match"] = 1.0 if route_key_matched or (sig_route and sig_route == prof_route) else 0.3

    scores["scenario_fit"] = _prefix(
        str(dps.get("scenario") or ""),
        str(signature.get("scenario") or ""),
    )
    if scores["scenario_fit"] < 1.0:
        scores["scenario_fit"] = _prefix(
            str(dps.get("regime_code") or ""),
            str(signature.get("regime_code") or ""),
        )

    scores["structure_fit"] = structure_fit_score(
        str(dps.get("structure_code") or dps.get("structure") or ""),
        str(signature.get("structure_code") or signature.get("structure") or ""),
    )
    scores["grid_direction_fit"] = grid_direction_fit_score(dps, signature)
    scores["base_quote_fit"] = base_quote_fit_score(dps, signature)
    scores["capacity_fit"] = float(overrides.get("capacity_fit") or 0.85)
    scores["cost_fit"] = float(overrides.get("cost_fit") or 0.85)
    scores["data_quality_fit"] = float(signature.get("data_quality_fit") or 0.85)
    scores["prior_score"] = float((template.params or {}).get("score_prior") or 0.5)

    return round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 4)
