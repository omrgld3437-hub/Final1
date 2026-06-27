"""Result type resolution for Param Assistant / Dynamic Mode UI contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.models import BotContext, BotParams, FinalAction


def resolve_result_type(
    *,
    deployable: bool,
    final_action: str,
    params: Optional[BotParams],
    feasibility_meta: Optional[Dict[str, Any]],
    bot_context: BotContext,
    blocking_reasons: Optional[List[str]],
    has_recommendation_ui: bool,
    profile_source: str = "",
) -> str:
    """Map engine output to UI result_type contract."""
    meta = feasibility_meta or {}
    blocking = [str(b).upper() for b in (blocking_reasons or [])]
    fa = str(final_action or "").upper()

    if fa in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ) or any(
        b in blocking
        for b in (
            "SPREAD_HIGH",
            "LIQUIDITY_LOW",
            "DUMP_RISK",
            "DATA_QUALITY_LOW",
            "PARAM_SCORE_TOO_LOW",
        )
    ):
        if fa == FinalAction.NO_TRADE.value or "SPREAD_HIGH" in blocking or "LIQUIDITY_LOW" in blocking:
            return "no_trade"
        return "management_decision"

    buy_n = int(params.buy_grid_count or 0) if params else 0
    sell_n = int(params.sell_grid_count or 0) if params else 0
    first_start = bool(getattr(bot_context, "is_first_start", False))
    buy_only_mode = bool(getattr(bot_context, "first_start_buy_only", False))

    if deployable and params and buy_n >= 2:
        if first_start and buy_only_mode and sell_n < 2:
            return "first_start_buy_only"
        if sell_n >= 2 or (first_start and buy_only_mode):
            return "deployable_grid"

    if params and buy_n == 1:
        return "single_probe_recommendation"

    if params and buy_n >= 2 and has_recommendation_ui:
        if first_start and buy_only_mode and sell_n < 2:
            return "first_start_buy_only"
        return "recommended_grid"

    if params and (buy_n > 0 or sell_n > 0) and has_recommendation_ui:
        return "recommended_grid"

    if (
        (meta.get("deploy_blocked_reason") == "NO_SELLABLE_BASE" or "NO_SELLABLE_BASE" in blocking)
        and not (first_start and buy_only_mode)
    ):
        return "recommended_grid"

    if str(profile_source or "") == "runtime_synthetic" and has_recommendation_ui:
        return "recommended_grid"

    return "management_decision"


def result_type_from_decision(
    decision: Any,
    *,
    bot_context: Optional[BotContext] = None,
    deployable_ui: Optional[bool] = None,
) -> str:
    """Resolve result_type from DynamicParamDecision (Param Assistant + Dynamic Mode)."""
    from app.services.dynamic_param_score.models import DynamicParamDecision

    if not isinstance(decision, DynamicParamDecision):
        return "management_decision"

    tel = decision.telemetry or {}
    pool_meta = tel.get("param_pool") or {}
    sel_ctx = pool_meta.get("selection_context") or {}
    profile_source = str(sel_ctx.get("profile_source") or "")
    if sel_ctx.get("runtime_safe_profile_generated"):
        profile_source = "runtime_synthetic"

    feas_meta = {
        k: tel.get(k)
        for k in (
            "distribution_invalid",
            "deploy_blocked_reason",
            "exposure_hard_cap_breach",
            "first_start_buy_only",
            "single_probe_only",
        )
        if tel.get(k) is not None
    }
    ctx = bot_context or BotContext(
        run_source=decision.run_source,
        budget_usdt=float(tel.get("budget_usdt") or 0),
        is_first_start=bool(tel.get("is_first_start")),
        first_start_buy_only=bool(tel.get("first_start_buy_only")),
    )
    from app.services.dynamic_param_score.consumer_policy import policy_for_context

    policy = policy_for_context(ctx)
    deploy = (
        bool(deployable_ui)
        if deployable_ui is not None
        else bool(decision.deployable and decision.params)
    )
    has_ui = bool(policy.recommendation_ui and decision.params is not None)
    return resolve_result_type(
        deployable=deploy,
        final_action=str(decision.final_action or ""),
        params=decision.params,
        feasibility_meta=feas_meta,
        bot_context=ctx,
        blocking_reasons=decision.blocking_reasons,
        has_recommendation_ui=has_ui,
        profile_source=profile_source,
    )
