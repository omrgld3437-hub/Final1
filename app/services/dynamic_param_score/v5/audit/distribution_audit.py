"""Distribution audit — 2-grid equal and 3-grid equal (full listing)."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v5.domain.types import V5Shelf
from app.services.dynamic_param_score.v5.generator.grid_factory import is_two_grid_equal_allowed


FORBIDDEN_EQUAL_CONTEXT = {
    "regimes": {
        "R8_CRASH",
        "R9_STRONG_DOWNTREND",
        "R10_LOWER_LOWS_DOWNTREND",
    },
    "structures": {"S5_LOWER_LOWS", "S8_BREAKDOWN"},
    "volatility": {"V5_SHOCK"},
    "liquidity": {"L4_EXECUTION_RISKY"},
    "risk": {"K3_AGGRESSIVE"},
}


def _is_equal_2(dist: List[float]) -> bool:
    return len(dist) == 2 and abs(dist[0] - 50) < 0.5 and abs(dist[1] - 50) < 0.5


def _is_equal_3(dist: List[float]) -> bool:
    return len(dist) == 3 and all(abs(v - 33.33) < 0.5 for v in dist)


def _justification_text(entry: dict, shelf: V5Shelf) -> str:
    if entry["justified"]:
        return "equal_2_grid_justified=true and balanced/safe route family allows 50/50"
    if not entry["equal_2_grid_justified_flag"]:
        return "equal_2_grid_justified flag false"
    return "route family does not allow equal 2-grid without extra justification"


def audit_distributions(shelves: List[V5Shelf]) -> dict:
    equal_2_routes: List[dict] = []
    equal_2_unjustified: List[str] = []
    equal_2_forbidden: List[str] = []
    equal_3_routes: List[dict] = []
    forbidden_context_scan = {
        "crash_downtrend": 0,
        "lower_lows_structure": 0,
        "high_vol_shock": 0,
        "L4_execution": 0,
        "aggressive_risk": 0,
    }

    for shelf in shelves:
        t = shelf.base_template
        rp = shelf.route_parts
        ctx = {
            "regime": rp.regime,
            "structure": rp.structure,
            "risk": rp.risk,
            "volatility": rp.volatility,
            "liquidity": rp.liquidity,
        }

        if rp.regime in FORBIDDEN_EQUAL_CONTEXT["regimes"]:
            forbidden_context_scan["crash_downtrend"] += 1
        if rp.structure in FORBIDDEN_EQUAL_CONTEXT["structures"]:
            forbidden_context_scan["lower_lows_structure"] += 1
        if rp.volatility in FORBIDDEN_EQUAL_CONTEXT["volatility"]:
            forbidden_context_scan["high_vol_shock"] += 1
        if rp.liquidity in FORBIDDEN_EQUAL_CONTEXT["liquidity"]:
            forbidden_context_scan["L4_execution"] += 1
        if rp.risk in FORBIDDEN_EQUAL_CONTEXT["risk"]:
            forbidden_context_scan["aggressive_risk"] += 1

        for side, dist in (("sell", t.sell_distribution_pct), ("buy", t.buy_distribution_pct)):
            if _is_equal_3(dist):
                equal_3_routes.append(
                    {"route_key": shelf.route_key, "shelf_id": shelf.shelf_id, "side": side, "distribution": dist}
                )

            if _is_equal_2(dist):
                justified = is_two_grid_equal_allowed(ctx) and t.equal_2_grid_justified
                entry = {
                    "route_key": shelf.route_key,
                    "shelf_id": shelf.shelf_id,
                    "side": side,
                    "justified": justified,
                    "equal_2_grid_justified_flag": t.equal_2_grid_justified,
                    "distribution": dist,
                }
                entry["justification"] = _justification_text(entry, shelf)
                equal_2_routes.append(entry)
                if not justified:
                    equal_2_unjustified.append(f"{shelf.shelf_id}:{side}")
                forbidden = (
                    rp.regime in FORBIDDEN_EQUAL_CONTEXT["regimes"]
                    or rp.structure in FORBIDDEN_EQUAL_CONTEXT["structures"]
                    or rp.volatility in FORBIDDEN_EQUAL_CONTEXT["volatility"]
                    or rp.liquidity in FORBIDDEN_EQUAL_CONTEXT["liquidity"]
                    or rp.risk in FORBIDDEN_EQUAL_CONTEXT["risk"]
                )
                if forbidden:
                    equal_2_forbidden.append(f"{shelf.shelf_id}:{side}")

    pass_audit = (
        len(equal_2_unjustified) == 0
        and len(equal_2_forbidden) == 0
        and len(equal_3_routes) == 0
    )

    return {
        "equal_2_grid_count": len(equal_2_routes),
        "equal_2_routes": equal_2_routes,
        "equal_2_unjustified_count": len(equal_2_unjustified),
        "equal_2_unjustified_samples": equal_2_unjustified,
        "equal_2_forbidden_count": len(equal_2_forbidden),
        "equal_2_forbidden_samples": equal_2_forbidden,
        "equal_2_forbidden_in_context_families": forbidden_context_scan,
        "equal_2_forbidden_in_context_note": (
            "Counts shelves in forbidden families; equal_2_forbidden_count must be 0 "
            "(no 50/50 inside crash/downtrend/lower-lows/shock/L4/aggressive)."
        ),
        "equal_3_grid_count": len(equal_3_routes),
        "equal_3_routes": equal_3_routes,
        "pass_audit": pass_audit,
    }
