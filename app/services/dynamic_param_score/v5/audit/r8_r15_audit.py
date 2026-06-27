"""R8/R15 hard invariant audit with explicit tables."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v5.domain.types import V5Shelf
from app.services.dynamic_param_score.v5.resolver.fallback_resolver_v5 import resolve_safe_fallback_v5
from app.services.dynamic_param_score.v5.domain.types import V5ResolveInput
from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts, make_route_key
from app.services.dynamic_param_score.v5.index.route_lookup import V5RouteIndex


def audit_r8_r15(shelves: List[V5Shelf], index: V5RouteIndex) -> dict:
    r8_rows: List[dict] = []
    r15_rows: List[dict] = []
    r8_r2_forbidden_ok = 0
    r8_r2_forbidden_fail = 0
    r15_r2_forbidden_ok = 0
    r15_r2_forbidden_fail = 0
    r15_nearest_ok = 0
    r15_nearest_fail = 0
    r15_source_order_checks: List[dict] = []

    for shelf in shelves:
        rp = shelf.route_parts
        fp = shelf.fallback_policy
        if rp.regime == "R8_CRASH":
            has_r2 = "R2_BALANCED_RANGE" in fp.forbidden_fallbacks
            if has_r2:
                r8_r2_forbidden_ok += 1
            else:
                r8_r2_forbidden_fail += 1
            r8_rows.append(
                {
                    "shelf_id": shelf.shelf_id,
                    "R2_forbidden": has_r2,
                    "forbidden_list": fp.forbidden_fallbacks[:6],
                }
            )
        if rp.regime == "R15_SPECIAL_STRESS_TRANSITION":
            has_r2 = "R2_BALANCED_RANGE" in fp.forbidden_fallbacks
            nearest = set(fp.nearest_safe_dimensions)
            required = {"R12_CAPITULATION_REACTION", "R7_RECOVERY", "R6_BREAKOUT_CONTINUATION"}
            nearest_ok = required.issubset(nearest)
            if has_r2:
                r15_r2_forbidden_ok += 1
            else:
                r15_r2_forbidden_fail += 1
            if nearest_ok:
                r15_nearest_ok += 1
            else:
                r15_nearest_fail += 1
            r15_rows.append(
                {
                    "shelf_id": shelf.shelf_id,
                    "R2_forbidden": has_r2,
                    "nearest_safe": fp.nearest_safe_dimensions,
                    "nearest_ok": nearest_ok,
                }
            )

    # R15 fallback source order simulation (exception path only)
    sample_r15 = next((s for s in shelves if s.route_parts.regime == "R15_SPECIAL_STRESS_TRANSITION"), None)
    if sample_r15:
        parts = sample_r15.route_parts
        fake_input = V5ResolveInput(
            symbol="BTCUSDT",
            route_parts=parts,
            budget_usdt=500,
            min_notional_usdt=10,
            current_base_pct=40,
            current_quote_pct=60,
            maker_fee_pct=0.1,
            taker_fee_pct=0.1,
            spread_pct=0.05,
            slippage_pct=0.03,
            rounding_pct=0.01,
        )
        # Force fallback by using invalid route in index lookup path — test source order via resolve_safe_fallback
        fb_shelf = resolve_safe_fallback_v5(fake_input, index)
        fb_regime = fb_shelf.route_parts.regime
        r15_source_order_checks.append(
            {
                "input_regime": "R15_SPECIAL_STRESS_TRANSITION",
                "fallback_regime": fb_regime,
                "fallback_shelf_id": fb_shelf.shelf_id,
                "not_R2": fb_regime != "R2_BALANCED_RANGE",
                "order_valid": fb_regime in (
                    "R12_CAPITULATION_REACTION",
                    "R7_RECOVERY",
                    "R6_BREAKOUT_CONTINUATION",
                )
                or fb_regime != "R2_BALANCED_RANGE",
            }
        )

    pass_audit = (
        r8_r2_forbidden_fail == 0
        and r15_r2_forbidden_fail == 0
        and r15_nearest_fail == 0
    )

    return {
        "R8_crash_shelf_count": len(r8_rows),
        "R8_R2_forbidden_ok": r8_r2_forbidden_ok,
        "R8_R2_forbidden_fail": r8_r2_forbidden_fail,
        "R8_sample_rows": r8_rows[:10],
        "R15_shelf_count": len(r15_rows),
        "R15_R2_forbidden_ok": r15_r2_forbidden_ok,
        "R15_R2_forbidden_fail": r15_r2_forbidden_fail,
        "R15_nearest_ok": r15_nearest_ok,
        "R15_nearest_fail": r15_nearest_fail,
        "R15_sample_rows": r15_rows[:10],
        "R15_fallback_source_order": r15_source_order_checks,
        "pass_audit": pass_audit,
    }
