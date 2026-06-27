"""V5 exception-path fallback resolver."""

from __future__ import annotations

from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts, make_route_key
from app.services.dynamic_param_score.v5.domain.types import V5ResolveInput, V5Shelf
from app.services.dynamic_param_score.v5.index.route_lookup import V5RouteIndex, lookup_exact_v5_shelf


def _shift_dimension(parts: V5RouteParts, shifts: dict) -> V5RouteParts:
    d = parts.to_dict()
    d.update(shifts)
    return V5RouteParts.from_dict(d)


def resolve_safe_fallback_v5(input_data: V5ResolveInput, index: V5RouteIndex) -> V5Shelf:
    """Exception-only fallback: preserve asset + risk, never escalate aggression."""
    parts = input_data.route_parts
    candidates: list[V5RouteParts] = []

    # Same asset, same risk — try liquidity safer
    for liq in ("L1_HIGH_LIQUIDITY_LOW_COST", "L2_NORMAL_LIQUIDITY_NORMAL_COST"):
        if liq != parts.liquidity:
            candidates.append(_shift_dimension(parts, {"liquidity": liq}))

    # R15 source order: R12 → R7 → R6
    if parts.regime == "R15_SPECIAL_STRESS_TRANSITION":
        for reg in (
            "R12_CAPITULATION_REACTION",
            "R7_RECOVERY",
            "R6_BREAKOUT_CONTINUATION",
        ):
            candidates.append(_shift_dimension(parts, {"regime": reg}))

    # Never R8 → R2
    if parts.regime == "R8_CRASH":
        for reg in ("R12_CAPITULATION_REACTION", "R14_LOW_LIQUIDITY_DRIFT"):
            candidates.append(_shift_dimension(parts, {"regime": reg}))

    # Structure/volatility soften
    for struct in ("S1_RANGE_MID", "S9_UNSTRUCTURED_CHOP"):
        if struct != parts.structure:
            candidates.append(_shift_dimension(parts, {"structure": struct}))
    for vol in ("V2_LOW", "V3_NORMAL"):
        if vol != parts.volatility:
            candidates.append(_shift_dimension(parts, {"volatility": vol}))

    for cand in candidates:
        if cand.risk != parts.risk:
            continue
        if cand.regime == "R2_BALANCED_RANGE" and parts.regime == "R8_CRASH":
            continue
        if cand.regime == "R2_BALANCED_RANGE" and parts.regime == "R15_SPECIAL_STRESS_TRANSITION":
            continue
        rk = make_route_key(cand)
        try:
            return lookup_exact_v5_shelf(index, rk)
        except KeyError:
            continue

    # Global safe: same asset defensive neutral
    safe = V5RouteParts(
        asset=parts.asset,
        regime="R17_DATA_UNCERTAIN_REGIME",
        direction="D2_NEUTRAL_BIAS",
        structure="S1_RANGE_MID",
        volatility="V2_LOW",
        risk="K1_DEFENSIVE" if parts.risk == "K1_DEFENSIVE" else parts.risk,
        liquidity="L2_NORMAL_LIQUIDITY_NORMAL_COST",
    )
    if parts.risk == "K3_AGGRESSIVE":
        safe = V5RouteParts(
            asset=parts.asset,
            regime="R17_DATA_UNCERTAIN_REGIME",
            direction="D2_NEUTRAL_BIAS",
            structure="S1_RANGE_MID",
            volatility="V2_LOW",
            risk="K2_NORMAL_CONTROLLED",
            liquidity="L2_NORMAL_LIQUIDITY_NORMAL_COST",
        )
    return lookup_exact_v5_shelf(index, make_route_key(safe))
