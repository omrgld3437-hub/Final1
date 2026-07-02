"""Param Assistant vs Dynamic Mode round-start deploy parity."""

from __future__ import annotations

import copy
from typing import List, Optional, Tuple

from app.services.dynamic_param_score.action_detail import (
    is_deployable,
    is_sell_management_only,
    resolve_post_safety_action,
)
from app.services.dynamic_param_score.consumer_policy import build_dynamic_round_context
from app.services.dynamic_param_score.feasibility import (
    apply_exposure_and_notional_feasibility,
    has_sellable_base_feasible,
)
from app.services.dynamic_param_score.models import (
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    SafetyGateResult,
    SubScores,
)


def evaluate_dynamic_round_parity(
    params: Optional[BotParams],
    *,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    budget_usdt: float,
    sub: SubScores,
    ind: Optional[IndicatorSnapshot],
    risk_state: str,
    final_action: str,
    profile_name: str = "",
    current_price: Optional[float] = None,
    route_key: str = "",
) -> Tuple[bool, List[str]]:
    """
    Would Dynamic Mode (tur 2+, first_start kapalı) aynı parametre setini deploy edebilir?
    PA yumuşatması olmadan exposure + min-notional yeniden değerlendirilir.
    """
    if params is None:
        return False, ["NO_PARAMS"]

    dm_ctx = build_dynamic_round_context(budget_usdt=float(budget_usdt or 0), cycle_id=2)
    p = copy.deepcopy(params)
    gates: List[SafetyGateResult] = []
    warnings: List[str] = []
    blocking: List[str] = []
    action = str(final_action or "")

    p, meta = apply_exposure_and_notional_feasibility(
        p,
        portfolio,
        constraints,
        dm_ctx,
        gates,
        warnings,
        profile_name=profile_name,
        current_price=current_price,
        final_action=action,
        risk_state=risk_state,
        sub=sub,
        ind=ind,
        route_key=route_key,
    )

    has_sellable, _ = has_sellable_base_feasible(
        portfolio, constraints, price=current_price
    )

    if meta.get("min_notional_feasible") is False:
        if int(p.buy_grid_count or 0) == 0 and int(p.sell_grid_count or 0) == 0:
            blocking.append("MIN_NOTIONAL_HARD_FAIL")
        elif int(p.buy_grid_count or 0) > 0 and int(p.sell_grid_count or 0) > 0:
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        elif int(p.buy_grid_count or 0) > 0:
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        else:
            blocking.append("MIN_NOTIONAL_HARD_FAIL")

    if meta.get("exposure_hard_cap_breach") or (
        meta.get("worst_case_base_exposure_frac") is not None
        and meta.get("max_base_exposure_frac") is not None
        and float(meta["worst_case_base_exposure_frac"])
        > float(meta["max_base_exposure_frac"]) + 0.005
    ):
        blocking.append("EXPOSURE_HARD_CAP_BREACH")

    if is_sell_management_only(p) and not has_sellable:
        blocking.append("NO_SELLABLE_BASE")

    action = resolve_post_safety_action(p, action, blocking=bool(blocking))
    deployable = is_deployable(action, p, meta)

    if action == FinalAction.CONTROLLED_GRID.value:
        deployable = is_deployable(FinalAction.ACTIVE_DEFENSIVE_GRID.value, p, meta)

    ok = bool(deployable and not blocking)
    return ok, blocking
