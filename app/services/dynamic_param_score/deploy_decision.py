"""Deploy decision layer — atmosphere OK but soft failures → controlled grid."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.action_detail import is_deployable
from app.services.dynamic_param_score.atmosphere import (
    build_distribution_context,
    compute_decision_scores,
    enforce_buy_distribution_on_params,
    enforce_momentum_base_cap,
)
from app.services.dynamic_param_score.controlled_deploy import (
    market_allows_controlled_grid,
    try_controlled_grid_resolution,
)
from app.services.dynamic_param_score.distribution_policy import is_buy_distribution_valid
from app.services.dynamic_param_score.feasibility import simulate_worst_case_exposure
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    SubScores,
)


def _worst_exposure_breach(
    params: BotParams,
    portfolio: PortfolioState,
    context: BotContext,
    ladder_budget: float,
    current_price: Optional[float],
    meta: Dict[str, Any],
    *,
    strict: bool = False,
) -> bool:
    worst = float(
        meta.get("worst_case_base_exposure_frac")
        or simulate_worst_case_exposure(
            portfolio, params, ladder_budget, context, current_price
        )
    )
    max_exp = float(
        meta.get("max_base_exposure_frac") or params.max_base_exposure_frac or 0.72
    )
    tol = 0.0 if strict else float(C.WORST_CASE_EXPOSURE_TOLERANCE)
    meta["worst_case_base_exposure_frac"] = round(worst, 6)
    meta["max_base_exposure_frac"] = round(max_exp, 6)
    return worst > max_exp + tol


def apply_deploy_decision_layer(
    params: BotParams,
    final_action: str,
    deployable: bool,
    *,
    sub: SubScores,
    ind: Optional[IndicatorSnapshot],
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    context: BotContext,
    risk_state: str,
    blocking: List[str],
    feasibility_meta: Dict[str, Any],
    param_score: int,
    route_key: str = "",
    current_price: Optional[float] = None,
    fee_data_available: bool = True,
    soften_for_ui: bool = False,
) -> Tuple[BotParams, str, bool, Dict[str, Any]]:
    """Final deploy gate: distribution, exposure, fee_bad, controlled grid."""
    p = copy.deepcopy(params)
    meta = dict(feasibility_meta or {})
    action = str(final_action or "")
    dep = bool(deployable)
    fee_bad = bool(meta.get("fee_bad_rebalance_deferred")) or not fee_data_available

    dist_ctx = build_distribution_context(
        sub=sub, ind=ind, risk_state=risk_state, route_key=route_key, fee_bad=fee_bad
    )
    if enforce_momentum_base_cap(p, dist_ctx):
        meta["base_target_capped"] = True
    if enforce_buy_distribution_on_params(p, dist_ctx):
        meta["distribution_invalid"] = False
        meta.pop("deploy_blocked_reason", None)
        meta["distribution_repaired"] = True

    buy_n = int(p.buy_grid_count or 0)
    if buy_n > 0 and p.buy_qty_distribution:
        pct = [max(1, int(round(float(w) * 100))) for w in p.buy_qty_distribution[:buy_n]]
        valid, reason = is_buy_distribution_valid(pct, grid_count=buy_n, ctx=dist_ctx)
        if not valid:
            meta["distribution_invalid"] = True
            meta["deploy_blocked_reason"] = reason or "INVALID_DISTRIBUTION"
            dep = False

    ladder = float(meta.get("buy_ladder_budget_usdt") or 0.0)
    if _worst_exposure_breach(p, portfolio, context, ladder, current_price, meta):
        meta["exposure_hard_cap_breach"] = True
        meta["deploy_blocked_reason"] = "EXPOSURE_HARD_CAP_BREACH"
        dep = False
        meta["full_deployable"] = False

    scores = compute_decision_scores(
        sub,
        param_score=param_score,
        feasibility_meta=meta,
        blocking=blocking,
        fee_data_available=fee_data_available,
        worst_exposure_frac=float(meta.get("worst_case_base_exposure_frac") or 0),
        max_exposure_frac=float(meta.get("max_base_exposure_frac") or p.max_base_exposure_frac or 0.72),
    )
    meta["confidence_components"] = scores.to_dict()
    meta["decision_scores"] = scores.to_dict()

    full_deploy_ok = (
        dep
        and not fee_bad
        and not meta.get("distribution_invalid")
        and not meta.get("exposure_hard_cap_breach")
        and scores.final_deploy_confidence >= 55
        and buy_n >= int(C.MIN_GRID_COUNT_DEPLOYABLE)
    )
    meta["full_deployable"] = full_deploy_ok

    if full_deploy_ok and fee_bad:
        full_deploy_ok = False
        dep = False

    needs_controlled = (
        soften_for_ui
        and market_allows_controlled_grid(sub, ind, blocking)
        and buy_n >= int(C.MIN_GRID_COUNT_DEPLOYABLE)
        and (
            fee_bad
            or not full_deploy_ok
            or action
            in (
                FinalAction.WAIT_SAFETY.value,
                FinalAction.WAIT.value,
                FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            )
            or meta.get("distribution_invalid")
            or meta.get("exposure_hard_cap_breach")
            or scores.final_deploy_confidence < 55
        )
    )

    if needs_controlled and (not dep or fee_bad or meta.get("exposure_hard_cap_breach") or meta.get("distribution_invalid")):
        meta["param_score"] = param_score
        p2, action2, dep2, meta2 = try_controlled_grid_resolution(
            p,
            action,
            False,
            sub=sub,
            ind=ind,
            portfolio=portfolio,
            constraints=constraints,
            context=context,
            risk_state=risk_state,
            blocking=blocking,
            feasibility_meta=meta,
            current_price=current_price,
            fee_data_available=fee_data_available,
        )
        if meta2.get("controlled_grid"):
            ladder2 = float(meta2.get("buy_ladder_budget_usdt") or 0)
            if _worst_exposure_breach(
                p2, portfolio, context, ladder2, current_price, meta2, strict=True
            ):
                from app.services.dynamic_param_score.controlled_deploy import (
                    trim_exposure_for_controlled_grid,
                )

                min_n = float(constraints.min_notional or C.DEFAULT_MIN_NOTIONAL_USDT)
                ladder3, ok = trim_exposure_for_controlled_grid(
                    p2,
                    portfolio,
                    context,
                    ladder2,
                    min_n,
                    current_price,
                    max_attempts=28,
                )
                meta2["buy_ladder_budget_usdt"] = round(ladder3, 4)
                worst3 = simulate_worst_case_exposure(
                    portfolio, p2, ladder3, context, current_price
                )
                meta2["worst_case_base_exposure_frac"] = round(worst3, 6)
                max_exp3 = float(meta2.get("max_base_exposure_frac") or p2.max_base_exposure_frac or 0.72)
                if worst3 > max_exp3:
                    meta2.pop("controlled_grid", None)
                    meta2.pop("controlled_grid_mode", None)
                    meta2["can_start_controlled"] = False
                    meta2["exposure_hard_cap_breach"] = True
                    meta2["full_deployable"] = False
                    return p2, FinalAction.WAIT_SAFETY.value, False, meta2
                meta2["exposure_hard_cap_breach"] = False
                meta2.pop("deploy_blocked_reason", None)
                meta2["exposure_trimmed"] = True
                dep2 = True
            else:
                meta2["exposure_hard_cap_breach"] = False
            meta2["can_start_controlled"] = bool(dep2 and meta2.get("controlled_grid"))
            return p2, action2, dep2, meta2

    if fee_bad and dep and action in (
        FinalAction.BALANCED_GRID.value,
        FinalAction.ACTIVE_GRID.value,
    ):
        meta["controlled_grid"] = True
        meta["controlled_grid_mode"] = "controlled_grid"
        meta["full_deployable"] = False
        action = FinalAction.CONTROLLED_GRID.value
        dep = is_deployable(action, p, meta)

    if meta.get("exposure_hard_cap_breach") and dep:
        dep = False
        meta["full_deployable"] = False

    if dep and _worst_exposure_breach(p, portfolio, context, ladder, current_price, meta, strict=True):
        dep = False
        meta["exposure_hard_cap_breach"] = True
        meta["full_deployable"] = False
        meta["deploy_blocked_reason"] = "EXPOSURE_HARD_CAP_BREACH"

    if meta.get("distribution_invalid") and dep:
        dep = False
        meta["full_deployable"] = False

    if not _worst_exposure_breach(p, portfolio, context, ladder, current_price, meta, strict=True):
        meta.pop("exposure_hard_cap_breach", None)

    return p, action, dep, meta
