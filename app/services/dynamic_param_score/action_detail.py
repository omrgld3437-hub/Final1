"""Final action resolution and action_detail payload for DPS decisions."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import BotParams, FinalAction

# Bilateral grid rule applies only to full two-sided grid runtime modes.
BILATERAL_GRID_ACTIONS = frozenset(
    {
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.ACTIVE_GRID.value,
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.CONTROLLED_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
        FinalAction.TREND_TRAILING.value,
    }
)


def grids_are_bilateral(params: Optional[BotParams]) -> bool:
    if params is None:
        return False
    min_each = int(C.MIN_GRID_COUNT_DEPLOYABLE)
    return (
        int(params.buy_grid_count or 0) >= min_each
        and int(params.sell_grid_count or 0) >= min_each
    )


def grids_are_buy_only_deployable(
    params: Optional[BotParams],
    feasibility_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    if params is None:
        return False
    meta = feasibility_meta or {}
    if not meta.get("first_start_buy_only"):
        return False
    return int(params.buy_grid_count or 0) >= int(C.MIN_GRID_COUNT_DEPLOYABLE)


def is_sell_management_only(params: Optional[BotParams]) -> bool:
    if params is None:
        return False
    return int(params.buy_grid_count or 0) == 0 and int(params.sell_grid_count or 0) > 0


def requires_bilateral_grids(final_action: str) -> bool:
    return final_action in BILATERAL_GRID_ACTIONS


def resolve_post_safety_action(
    params: BotParams,
    profile_action: str,
    *,
    blocking: bool = False,
) -> str:
    """Map safety-adjusted grid counts to explicit final_action semantics."""
    if blocking or profile_action == FinalAction.NO_TRADE.value:
        return FinalAction.NO_TRADE.value

    buy_n = int(params.buy_grid_count or 0)
    sell_n = int(params.sell_grid_count or 0)

    if buy_n > 0 and sell_n > 0:
        if profile_action in BILATERAL_GRID_ACTIONS:
            return profile_action
        return profile_action or FinalAction.BALANCED_GRID.value

    if is_sell_management_only(params):
        return FinalAction.SELL_MANAGEMENT_ONLY.value

    if buy_n > 0 or sell_n > 0:
        if profile_action == FinalAction.ACTIVE_DEFENSIVE_GRID.value:
            return profile_action
        return FinalAction.ACTIVE_DEFENSIVE_GRID.value

    return FinalAction.WAIT_SAFETY.value


def build_action_detail(
    params: Optional[BotParams],
    final_action: str,
    profile_name: str,
    feasibility_meta: Dict[str, Any],
    warnings: list,
) -> Dict[str, Any]:
    buy_n = int(getattr(params, "buy_grid_count", 0) or 0) if params else 0
    sell_n = int(getattr(params, "sell_grid_count", 0) or 0) if params else 0
    reason = "NONE"
    if final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        reason = "SELL_MANAGEMENT_ONLY"
    elif not feasibility_meta.get("bilateral_grid_ok", True) and buy_n > 0 and sell_n > 0:
        reason = "BILATERAL_GRID_REQUIRED"
    elif "EXPOSURE_HEADROOM_TOO_LOW" in warnings:
        reason = "EXPOSURE_HEADROOM_TOO_LOW_OR_MIN_NOTIONAL"
    elif feasibility_meta.get("adjusted_buy_grid_count_reason"):
        reason = str(feasibility_meta.get("adjusted_buy_grid_count_reason"))
    elif params and getattr(params, "emergency_no_buy", False):
        reason = "EMERGENCY_NO_BUY"

    return {
        "buy_side": "enabled" if buy_n > 0 else "disabled",
        "sell_side": "enabled" if sell_n > 0 else "disabled",
        "reason": reason,
        "management_mode": final_action,
        "selected_profile": profile_name,
        "post_safety_action": final_action,
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "bilateral_grid_ok": feasibility_meta.get(
            "bilateral_grid_ok", buy_n > 0 and sell_n > 0
        ),
        "sell_management_only": final_action == FinalAction.SELL_MANAGEMENT_ONLY.value,
    }


def is_deployable(
    final_action: str,
    params: Optional[BotParams],
    feasibility_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    meta = feasibility_meta or {}
    fa = str(final_action or "").upper()
    if meta.get("fee_bad_rebalance_deferred") and fa != FinalAction.CONTROLLED_GRID.value:
        return False
    if meta.get("full_deployable") is False and fa not in (
        FinalAction.CONTROLLED_GRID.value,
        FinalAction.SELL_MANAGEMENT_ONLY.value,
    ):
        return False
    if meta.get("exposure_hard_cap_breach") or meta.get("deploy_blocked_reason"):
        if final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
            return is_sell_management_only(params)
        return False
    if meta.get("distribution_invalid"):
        return False
    if meta.get("single_probe_only"):
        return False
    worst = float(meta.get("worst_case_base_exposure_frac") or 0.0)
    max_exp = float(meta.get("max_base_exposure_frac") or 0.0)
    if params is not None and max_exp > 0 and worst > max_exp:
        return False
    if params is not None and max_exp > 0 and worst > max_exp + float(C.WORST_CASE_EXPOSURE_TOLERANCE):
        return False
    if final_action in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ):
        return False
    if final_action == FinalAction.CONTROLLED_GRID.value and meta.get("controlled_grid"):
        buy_n = int(params.buy_grid_count or 0) if params else 0
        return buy_n >= int(C.MIN_GRID_COUNT_DEPLOYABLE)
    if final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        return is_sell_management_only(params)
    buy_n = int(params.buy_grid_count or 0) if params else 0
    if buy_n < int(C.MIN_GRID_COUNT_DEPLOYABLE):
        return False
    if meta.get("first_start_buy_only"):
        return grids_are_buy_only_deployable(params, meta)
    if requires_bilateral_grids(final_action):
        return grids_are_bilateral(params)
    return grids_are_bilateral(params)
