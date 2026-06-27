"""Param template pool selector — score/regime/risk/budget/exposure aware selection."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.feasibility import (
    exposure_headroom_quote_usdt,
    has_sellable_base_feasible,
)
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.param_pool.models import (
    ParamTemplate,
    ProfileFamily,
    SelectionContext,
    SelectionFeatures,
    TemplateSelectionResult,
    budget_tier_from_equity,
    btc_risk_tier_from_score,
    exposure_tier_from_frac,
    fee_tier_from_score,
    headroom_tier_from_usdt,
    liquidity_tier_from_score,
    order_reality_tier_from_context,
    volatility_tier_from_score,
)
from app.services.dynamic_param_score.param_pool.diagnostics import build_reject_summary
from app.services.dynamic_param_score.param_pool.registry import get_active_pool
from app.services.dynamic_param_score.param_pool.renderer import render_template
from app.services.dynamic_param_score.param_pool.sqlite_store import query_candidates
from app.services.dynamic_param_score.param_pool.versioning import load_indexed_pool
from app.services.dynamic_param_score.scoring import score_bucket

# Synthetic fallback keys from _fallback_selection → pinned regression templates.
_PINNED_FALLBACK_ALIASES: Dict[str, str] = {
    "FALLBACK_FEE_BAD_ACTIVE_DEFENSIVE": "BALANCED_RANGE_60_69_FEE_BAD_WAIT",
    "FALLBACK_DEFENSIVE": "BALANCED_RANGE_60_69_FEE_BAD_WAIT",
    "FALLBACK_DUMP_DEFENSIVE": "BALANCED_RANGE_60_69_FEE_BAD_WAIT",
}

_GENERIC_PINNED_FALLBACK_KEYS = frozenset(_PINNED_FALLBACK_ALIASES.keys()) | frozenset(
    {
        "FALLBACK_NO_TRADE",
        "FALLBACK_SELL_MANAGEMENT",
        "FALLBACK_DUMP_DEFENSIVE",
    }
)


def _is_generic_pinned_fallback(template_key: Optional[str]) -> bool:
    key = str(template_key or "").strip()
    return key in _GENERIC_PINNED_FALLBACK_KEYS or key.startswith("FALLBACK_")


def build_selection_context(
    param_score: int,
    regime: RegimeTag,
    risk_state: str,
    sub: SubScores,
    ind: IndicatorSnapshot,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    budget_usdt: float,
    min_notional: float,
    *,
    is_first_start: bool = False,
) -> SelectionContext:
    equity = max(
        float(budget_usdt or 0.0),
        float(portfolio.total_equity_usdt or 0.0),
    )
    exp = max(float(portfolio.current_base_exposure_frac or 0.0), 0.0)
    ref_cap = min(
        C.MAX_BASE_EXPOSURE_FRAC,
        max(exp + 0.08, 0.52) if exp > 0.05 else 0.55,
    )
    headroom = exposure_headroom_quote_usdt(portfolio, ref_cap)
    mn = max(float(min_notional or C.DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    has_sellable_base, sellable_base = has_sellable_base_feasible(portfolio, constraints)
    if not has_sellable_base:
        sellable_base = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    has_base = has_sellable_base
    friction = float(ind.total_friction_pct or 0.0)
    if friction <= 0:
        friction = (
            float(constraints.maker_fee_pct)
            + float(constraints.estimated_slippage_pct)
            + float(ind.orderbook_spread_pct or 0.0) / 2.0
        )

    return SelectionContext(
        param_score=param_score,
        regime=regime.value,
        risk_state=risk_state,
        budget_tier=budget_tier_from_equity(equity),
        exposure_tier=exposure_tier_from_frac(portfolio.current_base_exposure_frac),
        headroom_tier=headroom_tier_from_usdt(headroom, min_notional),
        fee_tier=fee_tier_from_score(sub.fee_efficiency_score),
        liquidity_tier=liquidity_tier_from_score(sub.liquidity_score),
        volatility_tier=volatility_tier_from_score(
            sub.volatility_score, float(ind.atr14_pct_5m or 1.0)
        ),
        btc_risk_tier=btc_risk_tier_from_score(sub.btc_market_risk_score),
        order_reality_tier=order_reality_tier_from_context(equity, mn, headroom),
        total_friction_pct=friction,
        equity_usdt=equity,
        min_notional=mn,
        headroom_usdt=headroom,
        has_base=has_base,
        has_sellable_base=has_sellable_base,
        sellable_base_usdt=sellable_base,
        sell_min_notional_feasible=has_sellable_base,
        is_first_start=is_first_start,
        sub_scores={
            **sub.to_dict(),
            "lower_lows": bool(getattr(ind, "lower_lows", False)),
            "higher_highs": bool(getattr(ind, "higher_highs", False)),
            "return_24h_pct": float(ind.return_24h_pct or 0.0),
            "drawdown_7d_pct": float(ind.drawdown_7d_pct or 0.0),
            "drawdown_30d_pct": float(ind.drawdown_30d_pct or 0.0),
            "z_score_5m": ind.z_score_5m,
            "price_in_bb": ind.price_in_bb,
            "volatility_score": int(sub.volatility_score or 50),
            "volatility_percentile": float(
                ind.volatility_percentile
                if ind.volatility_percentile is not None
                else sub.volatility_score
            ),
            "btc_crash_velocity": float(ind.btc_crash_velocity or 0.0),
            "crash_velocity": float(ind.crash_velocity or 0.0),
        },
        spread_pct=float(ind.orderbook_spread_pct or 0.0),
        atr_pct=float(ind.atr14_pct_1h or ind.atr14_pct_5m or 1.0),
    )


def _selection_features_from_context(ctx: SelectionContext) -> SelectionFeatures:
    return SelectionFeatures(
        param_score=ctx.param_score,
        regime=ctx.regime,
        risk_state=ctx.risk_state,
        budget_tier=ctx.budget_tier,
        exposure_tier=ctx.exposure_tier,
        headroom_tier=ctx.headroom_tier,
        fee_tier=ctx.fee_tier,
        liquidity_tier=ctx.liquidity_tier,
        volatility_tier=ctx.volatility_tier,
        btc_risk_tier=ctx.btc_risk_tier,
        order_reality_tier=ctx.order_reality_tier,
        sub_scores=ctx.sub_scores,
        budget_usdt=ctx.equity_usdt,
        current_exposure_frac=0.0,
        headroom_usdt=ctx.headroom_usdt,
        min_notional=ctx.min_notional,
        has_sellable_base=ctx.has_sellable_base,
        total_friction_pct=ctx.total_friction_pct,
        atr_pct=ctx.atr_pct,
        spread_pct=ctx.spread_pct,
    )


def _candidate_templates(
    pool_version_id: str,
    all_templates: List[ParamTemplate],
    ctx: SelectionContext,
    *,
    symbol: str = "",
) -> List[ParamTemplate]:
    """Narrow pool via DPS route_key / signature index (v4/v3)."""
    try:
        pool = load_indexed_pool(pool_version_id)
        from app.services.dynamic_param_score.param_generator.param_index_builder import (
            market_signature_from_live,
        )

        sub = ctx.sub_scores
        sig = market_signature_from_live(
            symbol=symbol,
            budget=ctx.equity_usdt,
            regime=ctx.regime,
            risk_level=ctx.risk_state,
            volatility_percentile=float(
                sub.get("volatility_percentile", sub.get("volatility_score", 50)) or 50
            ),
            lower_lows=bool(sub.get("lower_lows")),
            higher_highs=bool(sub.get("higher_highs")),
            fee_efficiency_score=int(sub.get("fee_efficiency_score", 50) or 50),
            atr_1h_pct=float(ctx.atr_pct or 1.0),
            spread_pct=float(ctx.spread_pct or 0.0),
            data_quality_score=int(sub.get("data_quality_score", 80) or 80),
            return_24h_pct=float(sub.get("return_24h_pct") or 0.0),
            drawdown_7d_pct=float(sub.get("drawdown_7d_pct") or 0.0),
            drawdown_30d_pct=float(sub.get("drawdown_30d_pct") or 0.0),
            z_score_5m=sub.get("z_score_5m"),
            price_in_bb=sub.get("price_in_bb"),
            volatility_score=int(sub.get("volatility_score", 50) or 50),
            btc_crash_velocity=float(sub.get("btc_crash_velocity") or 0.0),
            crash_velocity=float(sub.get("crash_velocity") or 0.0),
        )
        ctx.sub_scores["_market_signature"] = sig  # noqa: SLF001 — selection scoring reuse
        dps_narrowed: List[ParamTemplate] = []
        if getattr(pool, "lazy_mode", False) or pool.dps_signature_index or getattr(
            pool, "route_key_index", None
        ):
            dps_narrowed, route_trace = pool.query_route_shelf_with_trace(sig)
            ctx.sub_scores["_route_lookup_trace"] = route_trace  # noqa: SLF001
        if dps_narrowed:
            return dps_narrowed[:500]
        # Route shelf miss — broaden via legacy indexes instead of scanning zero templates.
        narrowed = query_candidates(pool, _selection_features_from_context(ctx))
        if narrowed:
            return narrowed
        bucket = ctx.param_score // 10
        score_only: List[ParamTemplate] = []
        for b in (bucket - 1, bucket, bucket + 1):
            score_only.extend(pool.score_index.get(b, []))
        if score_only:
            return score_only
    except Exception:
        pass
    return all_templates


def _v4_hard_reject(template: ParamTemplate, ctx: SelectionContext) -> Optional[str]:
    from app.services.dynamic_param_score.param_generator.v4_scoring import hard_reject_v4

    sig = ctx.sub_scores.get("_market_signature") or {}
    if not sig:
        return None
    return hard_reject_v4(template, sig)


_V4_HARD_REJECT_REASONS = frozenset(
    {
        "forbidden_fallback_regime",
        "structure_fit_zero",
        "grid_direction_fit_zero",
        "base_quote_fit_zero",
        "null_grid_ladder",
        "empty_deployable_grid",
    }
)


def _template_has_usable_grids(template: ParamTemplate) -> bool:
    """Deployable grid templates must expose at least one buy or sell ladder."""
    if template.final_action in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT.value,
        FinalAction.SAFE_WAIT.value,
    ):
        return False
    p = template.params or {}
    dps = p.get("dps_profile") or {}
    buy_n = int(p.get("buy_grid_count") or dps.get("buy_grid_count") or 0)
    sell_n = int(p.get("sell_grid_count") or dps.get("sell_grid_count") or 0)
    buy_l = p.get("buy_grid_ladder_pcts") or dps.get("buy_grid_ladder_pcts") or dps.get("buy_grid_pcts")
    sell_l = (
        p.get("sell_grid_ladder_pcts")
        or dps.get("sell_grid_ladder_pcts")
        or dps.get("sell_grid_pcts")
    )
    if template.final_action in (
        FinalAction.SELL_MANAGEMENT_ONLY.value,
        FinalAction.RECOVERY_SELL.value,
    ):
        return sell_n > 0 or bool(sell_l)
    return buy_n > 0 or sell_n > 0 or bool(buy_l) or bool(sell_l)


def _hard_filter(
    template: ParamTemplate,
    ctx: SelectionContext,
    *,
    pool_version_id: str = "",
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

    if pool_version_id == POOL_VERSION_V4:
        v4_reject = _v4_hard_reject(template, ctx)
        if v4_reject:
            reasons.append(v4_reject)

    if template.status != "active":
        reasons.append("status_not_active")

    if ctx.fee_tier == "FEE_BAD" and template.final_action in (
        FinalAction.WAIT.value,
        FinalAction.SAFE_WAIT.value,
    ):
        reasons.append("fee_bad_wait_forbidden")

    if not (template.score_min <= ctx.param_score <= template.score_max):
        reasons.append("score_out_of_range")

    if ctx.regime not in template.supported_regimes:
        reasons.append("regime_mismatch")

    if ctx.risk_state not in template.allowed_risk_states:
        reasons.append("risk_state_mismatch")

    if ctx.budget_tier not in template.budget_tiers:
        reasons.append("budget_tier_mismatch")

    if ctx.exposure_tier not in template.exposure_tiers:
        reasons.append("exposure_tier_mismatch")

    if template.headroom_tiers and ctx.headroom_tier not in template.headroom_tiers:
        reasons.append("headroom_tier_mismatch")

    if template.fee_tiers and ctx.fee_tier not in template.fee_tiers:
        reasons.append("fee_tier_mismatch")

    if template.liquidity_tiers and ctx.liquidity_tier not in template.liquidity_tiers:
        reasons.append("liquidity_tier_mismatch")

    if template.volatility_tiers and ctx.volatility_tier not in template.volatility_tiers:
        reasons.append("volatility_tier_mismatch")

    if template.btc_risk_tiers and ctx.btc_risk_tier not in template.btc_risk_tiers:
        reasons.append("btc_risk_tier_mismatch")

    if template.order_reality_tiers and ctx.order_reality_tier not in template.order_reality_tiers:
        reasons.append("order_reality_tier_mismatch")

    if (
        template.max_total_friction_pct is not None
        and ctx.total_friction_pct > template.max_total_friction_pct
    ):
        reasons.append("friction_too_high")

    if ctx.equity_usdt < template.min_equity_usdt:
        reasons.append("equity_below_min")
    if template.max_equity_usdt is not None and ctx.equity_usdt > template.max_equity_usdt:
        reasons.append("equity_above_max")

    if template.min_notional_multiple > 0:
        if ctx.equity_usdt < ctx.min_notional * template.min_notional_multiple:
            reasons.append("min_notional_multiple_fail")

    if template.min_headroom_multiple > 0:
        if ctx.headroom_usdt < ctx.min_notional * template.min_headroom_multiple:
            reasons.append("min_headroom_multiple_fail")

    sub = ctx.sub_scores
    checks = [
        ("min_range_score", template.min_range_score),
        ("min_liquidity_score", template.min_liquidity_score),
        ("min_spread_score", template.min_spread_score),
        ("min_fee_efficiency_score", template.min_fee_efficiency_score),
        ("min_exposure_safety_score", template.min_exposure_safety_score),
        ("min_data_quality_score", template.min_data_quality_score),
        ("min_btc_market_risk_score", template.min_btc_market_risk_score),
        ("min_drawdown_risk_score", template.min_drawdown_risk_score),
        ("min_mean_reversion_score", template.min_mean_reversion_score),
        ("min_volatility_score", template.min_volatility_score),
    ]
    for key, minimum in checks:
        if minimum <= 0:
            continue
        sk = key.replace("min_", "")
        if int(sub.get(sk, 0) or 0) < minimum:
            reasons.append(f"{sk}_below_min")

    if template.max_spread_pct is not None and ctx.spread_pct > template.max_spread_pct:
        reasons.append("spread_too_high")

    buy_n = int(template.params.get("buy_grid_count") or 0)
    if buy_n > 0 and ctx.headroom_tier in ("NO_HEADROOM", "LOW_HEADROOM"):
        if template.hard_limits.get("buy_grid_allowed") is not False:
            reasons.append("headroom_insufficient_for_buy")

    if ctx.exposure_tier == "OVEREXPOSED" and buy_n > 0:
        reasons.append("overexposed_no_buy")

    active_profiles = {
        ProfileFamily.ACTIVE_RANGE_GRID.value,
        ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value,
    }
    if template.profile_family in active_profiles and ctx.fee_tier in ("FEE_BAD", "FEE_WEAK"):
        reasons.append("fee_too_weak_for_active")

    if template.profile_family in active_profiles and ctx.btc_risk_tier in (
        "BTC_RISK_HIGH", "BTC_RISK_BLOCKED",
    ):
        reasons.append("btc_risk_too_high_for_active")

    if template.profile_family in active_profiles and ctx.order_reality_tier in (
        "ORDER_IMPOSSIBLE", "ORDER_TIGHT",
    ):
        reasons.append("order_reality_blocks_active")

    if template.hard_limits.get("requires_has_base") and not ctx.has_base:
        reasons.append("requires_base_missing")

    if template.hard_limits.get("requires_no_base") and ctx.has_base:
        reasons.append("requires_no_base")

    if template.requires_sellable_base or template.hard_limits.get("requires_sell_min_notional"):
        if not ctx.has_sellable_base:
            reasons.append("requires_sellable_base_missing")

    if (
        template.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        and not ctx.has_sellable_base
    ):
        reasons.append("sell_management_no_sellable_base")

    return len(reasons) == 0, reasons


def _summarize_filtered_out(filtered_out: Dict[str, List[str]]) -> Dict[str, int]:
    return build_reject_summary(filtered_out)


def _selection_route_trace(selection: TemplateSelectionResult) -> Dict[str, object]:
    """Merge route telemetry from selection_context (flat + nested selection_trace)."""
    ctx = selection.selection_context or {}
    nested = ctx.get("selection_trace") or {}
    if not isinstance(nested, dict):
        nested = {}
    keys = (
        "exact_route_candidate_count",
        "exact_scored_count",
        "fallback_candidate_count",
        "fallback_route",
        "route_index_fallback_used",
        "exact_reject_summary",
        "route_gap_reason",
    )
    merged: Dict[str, object] = dict(nested)
    for key in keys:
        if key in ctx and ctx[key] is not None:
            merged[key] = ctx[key]
    return merged


def _exact_reject_summary_for_scan(
    filtered_out: Dict[str, List[str]],
    scan_templates: List[ParamTemplate],
) -> Dict[str, int]:
    scan_keys = {t.template_key for t in scan_templates}
    subset = {k: v for k, v in filtered_out.items() if k in scan_keys}
    return build_reject_summary(subset)


def _apply_selection_trace(
    ctx: SelectionContext,
    result: TemplateSelectionResult,
    *,
    scan_templates: List[ParamTemplate],
) -> None:
    route_trace = ctx.sub_scores.get("_route_lookup_trace") or {}
    exact_count = int(
        route_trace.get("exact_route_candidate_count", len(scan_templates))
    )
    fb_route = route_trace.get("fallback_route")
    fb_count = int(route_trace.get("fallback_candidate_count") or 0)
    index_fb = bool(route_trace.get("route_index_fallback_used"))
    scored = int(result.candidate_count or 0)
    sig = ctx.sub_scores.get("_market_signature") or {}
    requested_risk = str(sig.get("risk_class") or ctx.risk_state or "NORMAL")
    fb_risk = ""
    if fb_route:
        fb_parts = str(fb_route).split("|")
        fb_risk = fb_parts[4] if len(fb_parts) >= 5 else ""
    exact_scored = int(
        route_trace.get("exact_scored_count")
        or ctx.sub_scores.get("_exact_scored_count")
        or 0
    )
    if exact_count > 0 and scored == 0 and exact_scored > 0:
        scored = exact_scored
    exact_reject = route_trace.get("exact_reject_summary") or ctx.sub_scores.get(
        "_exact_reject_summary"
    )
    if exact_count > 0 and scored == 0 and not exact_reject:
        exact_reject = _exact_reject_summary_for_scan(
            result.filtered_out, scan_templates
        )
    coverage_gap = exact_count == 0 or (
        index_fb and requested_risk in ("DEFENSIVE", "CAUTION")
    )
    defensive_overlay = (
        requested_risk in ("DEFENSIVE", "CAUTION")
        and fb_risk == "NORMAL"
        and index_fb
    )
    selection_type = "EXACT"
    fallback_warning_level = "none"
    if index_fb:
        selection_type = "CLAMPED_FALLBACK" if defensive_overlay else "SAFE_FALLBACK"
        fallback_warning_level = "warning" if defensive_overlay else "info"
    elif exact_count == 0:
        selection_type = "GLOBAL_SAFE" if scored > 0 else "UNRESOLVED"
        fallback_warning_level = "critical" if exact_count == 0 and scored == 0 else "warning"

    route_suitability = None
    if result.template:
        from app.services.dynamic_param_score.param_generator.v4_scoring import (
            route_suitability_score,
        )

        route_suitability = route_suitability_score(
            result.template,
            sig,
            route_key_matched=exact_count > 0 and not index_fb,
            fallback_used=index_fb,
            defensive_overlay=defensive_overlay,
        )
    result.selection_context.update(
        {
            "exact_route_candidate_count": exact_count,
            "exact_scored_count": exact_scored,
            "exact_reject_summary": exact_reject or {},
            "fallback_route": fb_route,
            "fallback_candidate_count": fb_count,
            "route_index_fallback_used": index_fb,
            "coverage_gap": coverage_gap,
            "defensive_fallback_overlay": defensive_overlay,
            "requested_risk_class": requested_risk,
            "scored_candidate_count": scored,
            "selected_profile_score": round(float(result.selection_score or 0), 2),
            "route_suitability_score": route_suitability,
            "selection_type": selection_type,
            "fallback_warning_level": fallback_warning_level,
            "selection_reason": result.selection_context.get("reason"),
            "hard_reject_count": len(result.filtered_out),
            "market_signature": result.selection_context.get("market_signature")
            or ctx.sub_scores.get("_market_signature")
            or {},
        }
    )


def _finalize_selection_context(
    ctx: SelectionContext,
    result: TemplateSelectionResult,
    *,
    templates: List[ParamTemplate],
    scan_templates: List[ParamTemplate],
) -> None:
    sig = ctx.sub_scores.get("_market_signature") or {}
    result.selection_context.setdefault("market_signature", sig)
    if templates:
        result.selection_context["active_template_count"] = len(templates)
    else:
        from app.services.dynamic_param_score.param_pool.versioning import production_pool_status

        pool_stat = production_pool_status()
        result.selection_context["active_template_count"] = int(
            pool_stat.get("route_index_profile_count")
            or pool_stat.get("template_count")
            or 0
        )
    result.selection_context["templates_scanned"] = len(scan_templates)
    if sig.get("route_key"):
        result.selection_context.setdefault("route_key", sig["route_key"])
    if not result.selection_context.get("selection_path"):
        result.selection_context["selection_path"] = [
            "market_signature",
            "clean_route_key",
            "index_lookup",
            "candidate_scoring",
            "capacity_resolver",
            "cost_resolver",
            "exchange_validation",
            "final_action",
        ]
    _apply_selection_trace(ctx, result, scan_templates=scan_templates)


def _runtime_safe_permitted(
    selection: TemplateSelectionResult,
    *,
    pool_status: Optional[Dict[str, object]] = None,
) -> bool:
    """Runtime synthetic profile when v4 pool is loaded and library paths are exhausted."""
    from app.services.dynamic_param_score.param_pool.versioning import production_pool_status

    status = pool_status or production_pool_status()
    if not status.get("production_pool_loaded"):
        return False
    if selection.template is not None:
        return False
    if selection.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        return False
    trace = _selection_route_trace(selection)
    exact_scored = int(trace.get("exact_scored_count") or 0)
    scored = int(
        trace.get("scored_candidate_count")
        or selection.candidate_count
        or 0
    )
    if exact_scored > 0:
        return False
    if scored > 0 and not _is_generic_pinned_fallback(selection.selected_template_key):
        return False
    # Generic pinned fallback keys → symbol-specific runtime safe instead.
    if _is_generic_pinned_fallback(selection.selected_template_key):
        return True
    exact = int(trace.get("exact_route_candidate_count") or 0)
    fb = int(trace.get("fallback_candidate_count") or 0)
    if exact > 0 or fb > 0:
        return True
    return True


def _v4_runtime_fallback_params(
    selection: TemplateSelectionResult,
    *,
    sub: SubScores,
    ind: IndicatorSnapshot,
    constraints: ExchangeConstraints,
    budget_usdt: float,
    min_notional: float,
) -> Tuple[Optional[BotParams], Dict[str, Any]]:
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
    from app.services.dynamic_param_score.param_generator.v4_resolvers import (
        apply_v4_resolvers,
        bot_params_from_v4_profile,
        generate_runtime_safe_profile,
    )

    if selection.pool_version != POOL_VERSION_V4:
        return None, {}
    sig = (selection.selection_context or {}).get("market_signature") or {}
    if not sig:
        return None, {}
    fee_score = int(getattr(sub, "fee_efficiency_score", 50) or 50)
    profile = generate_runtime_safe_profile(
        sig,
        budget=budget_usdt,
        min_notional=min_notional,
        constraints=constraints,
        spread_pct=float(ind.orderbook_spread_pct or 0),
        fee_efficiency_score=fee_score,
    )
    params = bot_params_from_v4_profile(profile)
    params, rctx, fits = apply_v4_resolvers(
        params,
        template=None,
        signature=sig,
        budget=budget_usdt,
        min_notional=min_notional,
        constraints=constraints,
        ind=ind,
        fee_efficiency_score=fee_score,
        dps_profile=profile,
    )
    sel = selection.selection_context
    sel["route_key"] = profile.get("route_key")
    sel["reason"] = f"Runtime safe profile for {profile.get('scenario')} (route shelf empty)."
    sel["fallback_generated"] = True
    sel["runtime_safe_profile_generated"] = True
    sel["profile_source"] = "runtime_synthetic"
    sel["selected_profile_id"] = "RUNTIME_SAFE_SYNTHETIC"
    sel["route_profile_score"] = None
    sel["scored_candidate_count"] = 0
    fb_count = int(sel.get("fallback_candidate_count") or 0)
    if fb_count > 0:
        sel["fallback_scoring_failed"] = True
        sel["fallback_reject_summary"] = selection.filter_summary or {}
    sel["selection_reason"] = (
        "Route rafı boş; runtime güvenli profil üreticisi devreye girdi."
        if fb_count <= 0
        else "Fallback raf adayları skorlanamadı; runtime güvenli profil devreye girdi."
    )
    sel["buy_distribution"] = profile.get("buy_distribution")
    sel["sell_distribution"] = profile.get("sell_distribution")
    sel.update(
        {
            "capacity_resolution": rctx.capacity.to_dict(),
            "cost_resolution": rctx.cost.to_dict(),
            "structure_fit": fits.get("structure_fit", 1.0),
            "grid_direction_fit": fits.get("grid_direction_fit", 1.0),
            "base_quote_fit": fits.get("base_quote_fit", 1.0),
        }
    )
    selection.selected_template_key = profile.get("profile_id") or selection.selected_template_key
    selection.final_action = profile.get("final_action") or selection.final_action
    return params, sel


def _selection_context_dict(ctx: SelectionContext) -> Dict[str, Any]:
    return {
        "param_score": ctx.param_score,
        "regime": ctx.regime,
        "risk_state": ctx.risk_state,
        "budget_tier": ctx.budget_tier,
        "exposure_tier": ctx.exposure_tier,
        "headroom_tier": ctx.headroom_tier,
        "fee_tier": ctx.fee_tier,
        "liquidity_tier": ctx.liquidity_tier,
        "volatility_tier": ctx.volatility_tier,
        "btc_risk_tier": ctx.btc_risk_tier,
        "order_reality_tier": ctx.order_reality_tier,
        "total_friction_pct": round(ctx.total_friction_pct, 4),
        "equity_usdt": round(ctx.equity_usdt, 2),
        "headroom_usdt": round(ctx.headroom_usdt, 2),
        "has_base": ctx.has_base,
        "has_sellable_base": ctx.has_sellable_base,
        "sellable_base_usdt": round(ctx.sellable_base_usdt, 2),
        "sell_min_notional_feasible": ctx.sell_min_notional_feasible,
        "is_first_start": ctx.is_first_start,
        "min_notional": ctx.min_notional,
    }


def _score_bucket_center_fit(template: ParamTemplate, param_score: int) -> float:
    mid = (template.score_min + template.score_max) / 2.0
    half = max((template.score_max - template.score_min) / 2.0, 1.0)
    dist = abs(param_score - mid) / half
    return max(0.0, 10.0 - dist * 5.0)


def _combined_selection_score(
    template: ParamTemplate,
    ctx: SelectionContext,
    pool_version_id: str,
) -> float:
    base = _selection_score(template, ctx)
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V3, POOL_VERSION_V4

    sub = ctx.sub_scores
    sig = sub.get("_market_signature")
    if not sig:
        from app.services.dynamic_param_score.param_generator.param_index_builder import (
            market_signature_from_live,
        )

        sig = market_signature_from_live(
            symbol=str(sub.get("symbol") or ""),
            budget=ctx.equity_usdt,
            regime=ctx.regime,
            risk_level=ctx.risk_state,
            volatility_percentile=float(sub.get("volatility_score", 50) or 50),
            lower_lows=bool(sub.get("lower_lows")),
            higher_highs=bool(sub.get("higher_highs")),
            fee_efficiency_score=int(sub.get("fee_efficiency_score", 50) or 50),
            atr_1h_pct=float(ctx.atr_pct or 1.0),
            spread_pct=float(ctx.spread_pct or 0.0),
            data_quality_score=int(sub.get("data_quality_score", 80) or 80),
            return_24h_pct=float(sub.get("return_24h_pct") or 0.0),
            drawdown_7d_pct=float(sub.get("drawdown_7d_pct") or 0.0),
            drawdown_30d_pct=float(sub.get("drawdown_30d_pct") or 0.0),
            z_score_5m=sub.get("z_score_5m"),
            price_in_bb=sub.get("price_in_bb"),
            volatility_score=int(sub.get("volatility_score", 50) or 50),
            btc_crash_velocity=float(sub.get("btc_crash_velocity") or 0.0),
            crash_velocity=float(sub.get("crash_velocity") or 0.0),
        )

    if pool_version_id == POOL_VERSION_V4:
        from app.services.dynamic_param_score.param_generator.v4_scoring import compute_v4_profile_score
        from app.services.dynamic_param_score.param_generator.feature_bins_v4 import normalize_route_key

        dps = (template.params or {}).get("dps_profile") or {}
        rk_match = normalize_route_key(str(dps.get("route_key") or "")) == normalize_route_key(
            str(sig.get("route_key") or "")
        )
        v4 = compute_v4_profile_score(template, sig, route_key_matched=rk_match)
        return base * 0.35 + v4 * 100 * 0.65

    if pool_version_id != POOL_VERSION_V3:
        return base
    from app.services.dynamic_param_score.param_generator.v2_scoring import compute_v2_profile_score

    sig["data_quality_score"] = float(sub.get("data_quality_score", 80) or 80)
    v2 = compute_v2_profile_score(template, sig)
    return base * 0.45 + v2 * 0.55


def _selection_score(template: ParamTemplate, ctx: SelectionContext) -> float:
    score = float(template.selection_priority or template.priority)
    score += _score_bucket_center_fit(template, ctx.param_score)

    if ctx.regime in template.supported_regimes:
        score += 8.0

    # Budget fit — prefer templates tuned for current tier
    if len(template.budget_tiers) == 1 and template.budget_tiers[0] == ctx.budget_tier:
        score += 6.0

    # Headroom fit
    if ctx.headroom_tier in template.headroom_tiers:
        score += 5.0

    for tiers, ctx_tier, pts in (
        (template.liquidity_tiers, ctx.liquidity_tier, 4.0),
        (template.volatility_tiers, ctx.volatility_tier, 4.0),
        (template.btc_risk_tiers, ctx.btc_risk_tier, 3.0),
        (template.order_reality_tiers, ctx.order_reality_tier, 3.0),
        (template.fee_tiers, ctx.fee_tier, 3.0),
    ):
        if tiers and ctx_tier in tiers:
            score += pts
            if len(tiers) == 1:
                score += pts * 0.5

    buy_n = int(template.params.get("buy_grid_count") or 0)
    sell_n = int(template.params.get("sell_grid_count") or 0)
    complexity = buy_n + sell_n

    # Penalties
    if ctx.fee_tier == "FEE_BAD":
        score -= 15.0
        if template.final_action in (
            FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            FinalAction.LOW_FEE_WIDE_GRID.value,
            FinalAction.BALANCED_GRID.value,
        ):
            score += 18.0
        if "WIDE_GRID" in (template.template_key or "") or "FEE_WEAK" in (template.template_key or ""):
            score += 12.0
        if (template.params or {}).get("dps_engine_version") == "DPS_ENGINE_V2":
            score += 8.0
    elif ctx.fee_tier == "FEE_WEAK":
        score -= 8.0

    if ctx.spread_pct > 0.15:
        score -= 10.0
    elif ctx.spread_pct > 0.08:
        score -= 5.0

    if ctx.exposure_tier in ("HIGH_BASE", "OVEREXPOSED") and buy_n > 0:
        score -= 20.0

    if ctx.headroom_tier in ("NO_HEADROOM", "LOW_HEADROOM") and buy_n > 0:
        score -= 25.0

    if ctx.budget_tier in ("NANO", "MICRO", "SMALL") and complexity > 4:
        score -= 10.0

    # Simplicity bonus for small budgets
    if ctx.budget_tier in ("NANO", "MICRO", "SMALL") and complexity <= 3:
        score += 5.0

    if template.profile_family in (
        ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        ProfileFamily.RECOVERY_SELL.value,
    ) and ctx.has_sellable_base and ctx.headroom_tier in ("NO_HEADROOM", "LOW_HEADROOM"):
        score += 12.0

    _PINNED_SELECTION_BOOST = {
        "BALANCED_RANGE_60_69_FEE_BAD_WAIT": -50.0,
        "BALANCED_RANGE_60_69_FEE_BAD_ACTIVE_DEFENSIVE": 40.0,
        "FALLBACK_FEE_BAD_ACTIVE_DEFENSIVE": 38.0,
        "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT": 35.0,
        "BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID": 30.0,
        "BALANCED_RANGE_60_69_CAUTION_FEE_BAD_WAIT": -40.0,
        "BALANCED_RANGE_60_69_DEFENSIVE_FEE_BAD_WAIT": -40.0,
        "BALANCED_RANGE_50_59_CAUTION_FEE_BAD_WAIT": -40.0,
        "BALANCED_RANGE_50_59_DEFENSIVE_FEE_BAD_WAIT": -40.0,
        "RANGE_LOW_VOL_50_69_FEE_BAD_WAIT": -40.0,
        "RANGE_HIGH_VOL_50_69_FEE_BAD_WAIT": -40.0,
        "NO_HEADROOM_NO_BASE_ANY_WAIT": 40.0,
        "NO_HEADROOM_SELLABLE_BASE_ANY_SELL_MANAGEMENT": 38.0,
        "FEE_BAD_SELLABLE_BASE_ANY_SELL_MANAGEMENT": 36.0,
        "FEE_BAD_NO_BASE_ANY_WAIT": -30.0,
        "LOW_LIQUIDITY_ANY_WAIT": 45.0,
        "SPREAD_UNSAFE_ANY_NO_TRADE": 50.0,
        "NO_DATA_ANY_SAFE_WAIT": 48.0,
        "OVEREXPOSED_ANY_RECOVERY_SELL": 40.0,
        "DUMP_RISK_ANY_NO_TRADE": 50.0,
        "TRENDING_DOWN_50_69_DEFENSIVE_WAIT_OR_SELL": 25.0,
        "RANGE_HIGH_VOL_70_89_ACTIVE_GOOD_FEE": 20.0,
    }
    score += _PINNED_SELECTION_BOOST.get(template.template_key, 0.0)

    return score


_SOFT_FILTER_REASONS = frozenset(
    {
        "regime_mismatch",
        "risk_state_mismatch",
        "budget_tier_mismatch",
        "exposure_tier_mismatch",
        "headroom_tier_mismatch",
        "fee_tier_mismatch",
        "liquidity_tier_mismatch",
        "volatility_tier_mismatch",
        "btc_risk_tier_mismatch",
        "order_reality_tier_mismatch",
        "friction_too_high",
    }
)

_NEARBY_SOFT_REASONS = frozenset(
    {
        "score_out_of_range",
        "regime_mismatch",
        "risk_state_mismatch",
        "budget_tier_mismatch",
        "exposure_tier_mismatch",
        "headroom_tier_mismatch",
        "fee_tier_mismatch",
        "liquidity_tier_mismatch",
        "volatility_tier_mismatch",
    }
)

_NO_AUTO_PICK_REGIMES = frozenset(
    {
        RegimeTag.NO_DATA.value,
        RegimeTag.SPREAD_UNSAFE.value,
        RegimeTag.LOW_LIQUIDITY.value,
    }
)

_DEPLOYABLE_FALLBACK_PROFILES = frozenset(
    {
        ProfileFamily.DEFENSIVE_GRID.value,
        ProfileFamily.ULTRA_DEFENSIVE_GRID.value,
        ProfileFamily.CAUTIOUS_BALANCED_GRID.value,
        ProfileFamily.BALANCED_GRID.value,
        ProfileFamily.LOW_FEE_WIDE_GRID.value,
        ProfileFamily.ACTIVE_DEFENSIVE_GRID.value,
        ProfileFamily.INITIAL_ENTRY.value,
        ProfileFamily.SMALL_BUDGET_SAFE.value,
        ProfileFamily.SELL_MANAGEMENT_ONLY.value,
        ProfileFamily.RECOVERY_SELL.value,
    }
)


def _hard_filter_nearby(
    template: ParamTemplate,
    ctx: SelectionContext,
) -> Tuple[bool, List[str]]:
    """Widen score/regime slightly — only when mismatch count is small."""
    ok, reasons = _hard_filter(template, ctx)
    if ok:
        return True, []

    margin = int(C.SELECTOR_NEARBY_SCORE_MARGIN)
    score_nearby = (
        template.score_min - margin <= ctx.param_score <= template.score_max + margin
    )
    adjusted = [r for r in reasons if not (r == "score_out_of_range" and score_nearby)]
    soft = [r for r in adjusted if r in _NEARBY_SOFT_REASONS]
    hard = [r for r in adjusted if r not in _NEARBY_SOFT_REASONS]
    if hard:
        return False, reasons
    if len(soft) > int(C.SELECTOR_NEARBY_MAX_SOFT_MISMATCHES):
        return False, reasons
    if template.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        return False, reasons
    if not template.deployable:
        return False, reasons
    return True, soft


def _nearby_deployable_search(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
) -> List[Tuple[ParamTemplate, float]]:
    candidates: List[Tuple[ParamTemplate, float]] = []
    for t in templates:
        ok, soft_reasons = _hard_filter_nearby(t, ctx)
        if not ok:
            continue
        if not _template_has_usable_grids(t):
            continue
        score = _combined_selection_score(t, ctx, pool_version_id)
        score -= 6.0 * len(soft_reasons)
        candidates.append((t, score))
    candidates.sort(key=lambda x: (-x[1], -x[0].selection_priority, -x[0].priority, x[0].template_key))
    return candidates


def _hard_filter_relaxed(
    template: ParamTemplate,
    ctx: SelectionContext,
    *,
    score_margin: Optional[int] = None,
    pool_version_id: str = "",
) -> Tuple[bool, List[str]]:
    """Last-resort filter: relax tier/regime mismatches when nearby pass found nothing."""
    if score_margin is None:
        score_margin = int(C.SELECTOR_RELAXED_SCORE_MARGIN)
    reasons: List[str] = []

    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

    if pool_version_id == POOL_VERSION_V4:
        v4_reject = _v4_hard_reject(template, ctx)
        if v4_reject in _V4_HARD_REJECT_REASONS:
            return False, [v4_reject]

    if template.status != "active":
        reasons.append("status_not_active")
    if template.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        reasons.append("non_deployable_action")
    if not template.deployable:
        reasons.append("not_deployable")

    if not (template.score_min - score_margin <= ctx.param_score <= template.score_max + score_margin):
        reasons.append("score_out_of_range")

    if ctx.equity_usdt < template.min_equity_usdt:
        reasons.append("equity_below_min")
    if template.max_equity_usdt is not None and ctx.equity_usdt > template.max_equity_usdt:
        reasons.append("equity_above_max")

    if template.min_notional_multiple > 0:
        if ctx.equity_usdt < ctx.min_notional * template.min_notional_multiple:
            reasons.append("min_notional_multiple_fail")

    if template.min_headroom_multiple > 0:
        if ctx.headroom_usdt < ctx.min_notional * template.min_headroom_multiple:
            reasons.append("min_headroom_multiple_fail")

    sub = ctx.sub_scores
    checks = [
        ("min_range_score", template.min_range_score),
        ("min_liquidity_score", template.min_liquidity_score),
        ("min_spread_score", template.min_spread_score),
        ("min_fee_efficiency_score", template.min_fee_efficiency_score),
        ("min_exposure_safety_score", template.min_exposure_safety_score),
        ("min_data_quality_score", template.min_data_quality_score),
        ("min_btc_market_risk_score", template.min_btc_market_risk_score),
        ("min_drawdown_risk_score", template.min_drawdown_risk_score),
        ("min_mean_reversion_score", template.min_mean_reversion_score),
        ("min_volatility_score", template.min_volatility_score),
    ]
    for key, minimum in checks:
        if minimum <= 0:
            continue
        sk = key.replace("min_", "")
        if int(sub.get(sk, 0) or 0) < minimum:
            reasons.append(f"{sk}_below_min")

    if template.max_spread_pct is not None and ctx.spread_pct > template.max_spread_pct:
        reasons.append("spread_too_high")

    buy_n = int(template.params.get("buy_grid_count") or 0)
    if ctx.exposure_tier == "OVEREXPOSED" and buy_n > 0:
        reasons.append("overexposed_no_buy")

    if template.hard_limits.get("requires_has_base") and not ctx.has_base:
        reasons.append("requires_base_missing")
    if template.hard_limits.get("requires_no_base") and ctx.has_base:
        reasons.append("requires_no_base")

    if template.requires_sellable_base or template.hard_limits.get("requires_sell_min_notional"):
        if not ctx.has_sellable_base:
            reasons.append("requires_sellable_base_missing")

    if (
        template.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        and not ctx.has_sellable_base
        and not ctx.is_first_start
    ):
        reasons.append("sell_management_no_sellable_base")

    soft = [r for r in reasons if r in _SOFT_FILTER_REASONS]
    hard = [r for r in reasons if r not in _SOFT_FILTER_REASONS]
    if hard:
        return False, reasons
    if len(soft) > int(C.SELECTOR_RELAXED_MAX_SOFT_MISMATCHES):
        return False, reasons
    return True, soft


def _hard_filter_fallback_shelf(
    template: ParamTemplate,
    ctx: SelectionContext,
    *,
    pool_version_id: str = "",
) -> Tuple[bool, List[str]]:
    """Relaxed filter for fallback-shelf templates when strict scoring yields zero."""
    reasons: List[str] = []
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

    if pool_version_id == POOL_VERSION_V4:
        v4_reject = _v4_hard_reject(template, ctx)
        if v4_reject in _V4_HARD_REJECT_REASONS | frozenset(
            {"legacy_wait_profile", "distribution_not_100"}
        ):
            return False, [v4_reject]
        if v4_reject:
            reasons.append(v4_reject)

    if template.status != "active":
        reasons.append("status_not_active")
    if template.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        return False, ["non_deployable_action"]
    if not template.deployable:
        return False, ["not_deployable"]
    if ctx.equity_usdt < template.min_equity_usdt:
        return False, ["equity_below_min"]
    if ctx.exposure_tier == "OVEREXPOSED":
        buy_n = int(template.params.get("buy_grid_count") or 0)
        if buy_n > 0:
            return False, ["overexposed_no_buy"]
    return True, reasons


def _shelf_relaxed_deployable_search(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
    *,
    require_exact_shelf: bool = False,
    require_fallback_shelf: bool = False,
) -> List[Tuple[ParamTemplate, float]]:
    """Score exact or fallback-route shelf when strict filters rejected all candidates."""
    route_trace = ctx.sub_scores.get("_route_lookup_trace") or {}
    exact_count = int(route_trace.get("exact_route_candidate_count") or 0)
    fb_count = int(route_trace.get("fallback_candidate_count") or 0)
    if not templates:
        return []
    if require_exact_shelf and exact_count <= 0:
        return []
    if require_fallback_shelf and fb_count <= 0:
        return []
    if not require_exact_shelf and not require_fallback_shelf:
        if exact_count <= 0 and fb_count <= 0:
            return []
    min_score = float(C.SELECTOR_RELAXED_MIN_SELECTION_SCORE) - 8.0
    candidates: List[Tuple[ParamTemplate, float]] = []
    for t in templates:
        ok, soft_reasons = _hard_filter_fallback_shelf(
            t, ctx, pool_version_id=pool_version_id
        )
        if not ok:
            continue
        if not _template_has_usable_grids(t):
            continue
        score = _combined_selection_score(t, ctx, pool_version_id)
        score -= 4.0 * len(soft_reasons)
        if t.profile_family in _DEPLOYABLE_FALLBACK_PROFILES:
            score += 8.0
        if score < min_score:
            continue
        candidates.append((t, score))
    candidates.sort(key=lambda x: (-x[1], -x[0].selection_priority, -x[0].priority, x[0].template_key))
    return candidates


def _fallback_shelf_deployable_search(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
) -> List[Tuple[ParamTemplate, float]]:
    """Score fallback-route shelf when strict filters rejected all candidates."""
    return _shelf_relaxed_deployable_search(
        templates, ctx, pool_version_id, require_fallback_shelf=True
    )


def _exact_shelf_deployable_search(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
) -> List[Tuple[ParamTemplate, float]]:
    """Score exact-route shelf templates with relaxed filters."""
    return _shelf_relaxed_deployable_search(
        templates, ctx, pool_version_id, require_exact_shelf=True
    )


def _relaxed_deployable_search(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
) -> List[Tuple[ParamTemplate, float]]:
    """Find deployable template only when nearby strict pass also failed."""
    min_score = float(C.SELECTOR_RELAXED_MIN_SELECTION_SCORE)
    candidates: List[Tuple[ParamTemplate, float]] = []
    for t in templates:
        ok, soft_reasons = _hard_filter_relaxed(t, ctx, pool_version_id=pool_version_id)
        if not ok:
            continue
        if not _template_has_usable_grids(t):
            continue
        score = _combined_selection_score(t, ctx, pool_version_id)
        score -= 5.0 * len(soft_reasons)
        if t.profile_family in _DEPLOYABLE_FALLBACK_PROFILES:
            score += 6.0
        if ctx.is_first_start and t.profile_family == ProfileFamily.INITIAL_ENTRY.value:
            score += 10.0
        if ctx.fee_tier in ("FEE_BAD", "FEE_WEAK") and t.profile_family in (
            ProfileFamily.LOW_FEE_WIDE_GRID.value,
            ProfileFamily.DEFENSIVE_GRID.value,
            ProfileFamily.ULTRA_DEFENSIVE_GRID.value,
            ProfileFamily.ACTIVE_DEFENSIVE_GRID.value,
        ):
            score += 8.0
        if score < min_score:
            continue
        candidates.append((t, score))
    candidates.sort(key=lambda x: (-x[1], -x[0].selection_priority, -x[0].priority, x[0].template_key))
    return candidates


def _library_deployable_last_resort(
    templates: List[ParamTemplate],
    ctx: SelectionContext,
    pool_version_id: str = "",
) -> List[Tuple[ParamTemplate, float]]:
    """Exhaustive library pass with shelf-minimal filters — avoids generic pinned fallback."""
    if not templates:
        return []
    min_score = float(C.SELECTOR_RELAXED_MIN_SELECTION_SCORE) - 15.0
    candidates: List[Tuple[ParamTemplate, float]] = []
    for t in templates:
        ok, soft_reasons = _hard_filter_fallback_shelf(
            t, ctx, pool_version_id=pool_version_id
        )
        if not ok:
            continue
        if not _template_has_usable_grids(t):
            continue
        score = _combined_selection_score(t, ctx, pool_version_id)
        score -= 3.0 * len(soft_reasons)
        if t.profile_family in _DEPLOYABLE_FALLBACK_PROFILES:
            score += 6.0
        if score < min_score:
            continue
        candidates.append((t, score))
    candidates.sort(
        key=lambda x: (-x[1], -x[0].selection_priority, -x[0].priority, x[0].template_key)
    )
    return candidates


def _fallback_selection(
    ctx: SelectionContext,
    *,
    relaxed_candidates: Optional[List[Tuple[ParamTemplate, float]]] = None,
) -> TemplateSelectionResult:
    if relaxed_candidates:
        best, best_score = relaxed_candidates[0]
        return TemplateSelectionResult(
            pool_version="",
            selected_template_key=best.template_key,
            profile_family=best.profile_family,
            final_action=best.final_action,
            selection_score=best_score,
            candidate_count=len(relaxed_candidates),
            filtered_out={},
            fallback_used=True,
            fallback_reason="relaxed_pool_search",
            template=best,
        )

    reason = "no_eligible_template"
    profile = ProfileFamily.DEFENSIVE_GRID.value
    action = FinalAction.DEFENSIVE_GRID.value
    key = "FALLBACK_DEFENSIVE"

    if ctx.regime == RegimeTag.SPREAD_UNSAFE.value:
        profile = ProfileFamily.NO_TRADE.value
        action = FinalAction.NO_TRADE.value
        key = "FALLBACK_NO_TRADE"
        reason = "spread_high+liquidity_weak+no_eligible_template"
    elif ctx.regime == RegimeTag.LOW_LIQUIDITY.value:
        profile = ProfileFamily.NO_TRADE.value
        action = FinalAction.NO_TRADE.value
        key = "FALLBACK_NO_TRADE"
        reason = "liquidity_weak+no_eligible_template"
    elif ctx.regime == RegimeTag.NO_DATA.value or ctx.param_score < 10:
        profile = ProfileFamily.NO_TRADE.value
        action = FinalAction.NO_TRADE.value
        key = "FALLBACK_NO_TRADE"
        reason = "no_data_or_low_score"
    elif ctx.regime == RegimeTag.DUMP_RISK.value:
        profile = ProfileFamily.ULTRA_DEFENSIVE_GRID.value
        action = FinalAction.DEFENSIVE_GRID.value
        key = "FALLBACK_DUMP_DEFENSIVE"
        reason = "dump_risk_defensive"
    elif ctx.headroom_tier == "NO_HEADROOM" and ctx.has_sellable_base:
        profile = ProfileFamily.SELL_MANAGEMENT_ONLY.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        key = "FALLBACK_SELL_MANAGEMENT"
        reason = "no_headroom_with_base"
    elif ctx.fee_tier == "FEE_BAD" and ctx.has_sellable_base:
        profile = ProfileFamily.SELL_MANAGEMENT_ONLY.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        key = "FALLBACK_SELL_MANAGEMENT"
        reason = "fee_bad_with_base"
    elif ctx.fee_tier == "FEE_BAD":
        profile = "ACTIVE_DEFENSIVE_GRID_PROFILE"
        action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        key = "FALLBACK_FEE_BAD_ACTIVE_DEFENSIVE"
        reason = "fee_bad_wide_grid_active"
    elif ctx.headroom_tier == "LOW_HEADROOM" and ctx.has_sellable_base:
        profile = ProfileFamily.SELL_MANAGEMENT_ONLY.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        key = "FALLBACK_SELL_MANAGEMENT"
        reason = "low_headroom_with_base"

    return TemplateSelectionResult(
        pool_version="",
        selected_template_key=key,
        profile_family=profile,
        final_action=action,
        selection_score=0.0,
        candidate_count=0,
        filtered_out={},
        fallback_used=True,
        fallback_reason=reason,
        template=None,
    )


def select_template(
    param_score: int,
    regime: RegimeTag,
    risk_state: str,
    sub: SubScores,
    ind: IndicatorSnapshot,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    budget_usdt: float,
    min_notional: float,
    *,
    is_first_start: bool = False,
    symbol: str = "",
) -> TemplateSelectionResult:
    pool_version, templates = get_active_pool()
    ctx = build_selection_context(
        param_score, regime, risk_state, sub, ind, portfolio, constraints,
        budget_usdt, min_notional,
        is_first_start=is_first_start,
    )
    ctx.sub_scores["symbol"] = symbol
    scan_templates = _candidate_templates(pool_version.version_id, templates, ctx, symbol=symbol)

    filtered_out: Dict[str, List[str]] = {}
    candidates: List[Tuple[ParamTemplate, float]] = []

    for t in scan_templates:
        ok, reasons = _hard_filter(t, ctx, pool_version_id=pool_version.version_id)
        if not ok:
            filtered_out[t.template_key] = reasons
            continue
        if ctx.is_first_start and not _template_has_usable_grids(t):
            filtered_out[t.template_key] = ["empty_grid_profile"]
            continue
        candidates.append((t, _combined_selection_score(t, ctx, pool_version.version_id)))

    if not candidates:
        if ctx.regime in _NO_AUTO_PICK_REGIMES or ctx.param_score < 10:
            result = _fallback_selection(ctx)
            result.pool_version = pool_version.version_id
            result.candidate_count = 0
            result.filtered_out = filtered_out
            result.filter_summary = _summarize_filtered_out(filtered_out)
            result.selection_context = _selection_context_dict(ctx)
            _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
            return result

        nearby = _nearby_deployable_search(scan_templates, ctx, pool_version.version_id)
        if not nearby:
            nearby = _nearby_deployable_search(templates, ctx, pool_version.version_id)
        if nearby:
            best, best_score = nearby[0]
            result = TemplateSelectionResult(
                pool_version=pool_version.version_id,
                selected_template_key=best.template_key,
                profile_family=best.profile_family,
                final_action=best.final_action,
                selection_score=best_score,
                candidate_count=len(nearby),
                filtered_out=filtered_out,
                filter_summary=_summarize_filtered_out(filtered_out),
                selection_context=_selection_context_dict(ctx),
                fallback_used=True,
                fallback_reason="nearby_pool_search",
                template=best,
            )
            _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
            return result

        exact_shelf = _exact_shelf_deployable_search(
            scan_templates, ctx, pool_version.version_id
        )
        if exact_shelf:
            best, best_score = exact_shelf[0]
            ctx.sub_scores["_exact_scored_count"] = len(exact_shelf)  # noqa: SLF001
            result = TemplateSelectionResult(
                pool_version=pool_version.version_id,
                selected_template_key=best.template_key,
                profile_family=best.profile_family,
                final_action=best.final_action,
                selection_score=best_score,
                candidate_count=len(exact_shelf),
                filtered_out=filtered_out,
                filter_summary=_summarize_filtered_out(filtered_out),
                selection_context=_selection_context_dict(ctx),
                fallback_used=True,
                fallback_reason="exact_shelf_scored",
                template=best,
            )
            _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
            return result

        fb_shelf = _fallback_shelf_deployable_search(
            scan_templates, ctx, pool_version.version_id
        )
        if fb_shelf:
            best, best_score = fb_shelf[0]
            result = TemplateSelectionResult(
                pool_version=pool_version.version_id,
                selected_template_key=best.template_key,
                profile_family=best.profile_family,
                final_action=best.final_action,
                selection_score=best_score,
                candidate_count=len(fb_shelf),
                filtered_out=filtered_out,
                filter_summary=_summarize_filtered_out(filtered_out),
                selection_context=_selection_context_dict(ctx),
                fallback_used=True,
                fallback_reason="fallback_shelf_scored",
                template=best,
            )
            _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
            return result

        relaxed = _relaxed_deployable_search(scan_templates, ctx, pool_version.version_id)
        if not relaxed:
            relaxed = _relaxed_deployable_search(templates, ctx, pool_version.version_id)
        if not relaxed:
            library_last = _library_deployable_last_resort(
                scan_templates, ctx, pool_version.version_id
            )
            if not library_last:
                library_last = _library_deployable_last_resort(
                    templates, ctx, pool_version.version_id
                )
            relaxed = library_last
        route_trace = ctx.sub_scores.get("_route_lookup_trace") or {}
        exact_count = int(route_trace.get("exact_route_candidate_count") or 0)
        if exact_count > 0:
            ctx.sub_scores["_exact_reject_summary"] = _exact_reject_summary_for_scan(  # noqa: SLF001
                filtered_out, scan_templates
            )
            ctx.sub_scores["route_gap_reason"] = "exact_candidates_unscored"  # noqa: SLF001
        result = _fallback_selection(ctx, relaxed_candidates=relaxed or None)
        result.pool_version = pool_version.version_id
        result.candidate_count = len(relaxed) if relaxed else 0
        result.filtered_out = filtered_out
        result.filter_summary = _summarize_filtered_out(filtered_out)
        result.selection_context = _selection_context_dict(ctx)
        _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
        return result

    candidates.sort(key=lambda x: (-x[1], -x[0].selection_priority, -x[0].priority, x[0].template_key))
    best, best_score = candidates[0]
    top_candidates = [
        {
            "template_key": t.template_key,
            "profile_family": t.profile_family,
            "final_action": t.final_action,
            "selection_score": round(score, 4),
            "score_min": t.score_min,
            "score_max": t.score_max,
        }
        for t, score in candidates[:10]
    ]

    result = TemplateSelectionResult(
        pool_version=pool_version.version_id,
        selected_template_key=best.template_key,
        profile_family=best.profile_family,
        final_action=best.final_action,
        selection_score=best_score,
        candidate_count=len(candidates),
        filtered_out=filtered_out,
        filter_summary=_summarize_filtered_out(filtered_out),
        selection_context=_selection_context_dict(ctx),
        fallback_used=False,
        fallback_reason=None,
        template=best,
    )
    result.selection_context["active_template_count"] = len(templates)
    result.selection_context["templates_scanned"] = len(scan_templates)
    result.selection_context["top_candidates"] = top_candidates
    sig = ctx.sub_scores.get("_market_signature") or {}
    dps = (best.params or {}).get("dps_profile") or {}
    result.selection_context["reason"] = _selection_reason(sig, dps, best)
    _finalize_selection_context(ctx, result, templates=templates, scan_templates=scan_templates)
    result.selection_context["structure_fit"] = 1.0 if not result.fallback_used else 0.8
    result.selection_context["grid_direction_fit"] = 1.0
    return result


def _selection_reason(sig: Dict[str, Any], dps: Dict[str, Any], template: ParamTemplate) -> str:
    scenario = dps.get("scenario") or sig.get("scenario") or "balanced"
    bias = sig.get("grid_bias") or dps.get("grid_bias") or "SYMMETRIC"
    buy_l = dps.get("buy_grid_ladder_pcts") or dps.get("buy_grid_pcts") or []
    sell_l = dps.get("sell_grid_ladder_pcts") or dps.get("sell_grid_pcts") or []
    symmetric_ladders = (
        len(buy_l) == len(sell_l)
        and buy_l
        and all(abs(float(b) - float(s)) < 0.05 for b, s in zip(buy_l, sell_l))
    )
    if bias == "BUY_WIDER_SELL_CLOSER":
        return (
            f"{scenario}: lower lows detected; quote allocation increased, "
            "buy grids widened, sell grids kept closer."
        )
    if bias == "SELL_WIDER_BUY_CLOSER" and not symmetric_ladders:
        return (
            f"{scenario}: higher highs detected; base allocation increased, "
            "sell grids widened, buy grids kept closer."
        )
    return f"{scenario}: shelf-matched profile via route_key index lookup."


def select_and_render(
    param_score: int,
    regime: RegimeTag,
    risk_state: str,
    sub: SubScores,
    ind: IndicatorSnapshot,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    bot_context: BotContext,
    budget_usdt: float,
    min_notional: float,
    *,
    symbol: str = "",
) -> Tuple[TemplateSelectionResult, Optional[BotParams], str]:
    """Select template and render BotParams. Returns (selection, params, profile_bucket)."""
    from app.services.dynamic_param_score.v5.bridge import v5_pool_enabled, v5_select_and_render

    if v5_pool_enabled():
        return v5_select_and_render(
            param_score,
            regime,
            risk_state,
            sub,
            ind,
            portfolio,
            constraints,
            bot_context,
            budget_usdt,
            min_notional,
            symbol=symbol or getattr(bot_context, "symbol", "") or "",
        )

    selection = select_template(
        param_score, regime, risk_state, sub, ind, portfolio, constraints,
        budget_usdt, min_notional,
        is_first_start=bool(getattr(bot_context, "is_first_start", False)),
        symbol=symbol or getattr(bot_context, "symbol", "") or "",
    )
    bucket = score_bucket(param_score)

    if selection.fallback_used or selection.template is None:
        if selection.template is not None:
            params = render_template(
                selection.template,
                param_score=param_score,
                regime=regime,
                ind=ind,
                constraints=constraints,
                current_exposure_frac=portfolio.current_base_exposure_frac,
                budget_usdt=budget_usdt,
                min_notional=min_notional,
            )
            params, resolver_meta = _apply_v4_resolvers_if_needed(
                selection,
                params,
                sub=sub,
                ind=ind,
                constraints=constraints,
                budget_usdt=budget_usdt,
                min_notional=min_notional,
            )
            if resolver_meta:
                selection.selection_context.update(resolver_meta)
            if selection.fallback_used:
                selection.selection_context["fallback_profile_re_resolved"] = True
            return selection, params, bucket
        if selection.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
            return selection, None, bucket
        from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
        from app.services.dynamic_param_score.param_pool.versioning import production_pool_status

        pool_stat = production_pool_status()
        v4_loaded = (
            selection.pool_version == POOL_VERSION_V4
            and bool(pool_stat.get("production_pool_loaded"))
        )
        fallback_key = selection.selected_template_key or ""
        pinned_generic = _is_generic_pinned_fallback(fallback_key)

        if v4_loaded and pinned_generic:
            if _runtime_safe_permitted(selection, pool_status=pool_stat):
                v4_params, _ = _v4_runtime_fallback_params(
                    selection,
                    sub=sub,
                    ind=ind,
                    constraints=constraints,
                    budget_usdt=budget_usdt,
                    min_notional=min_notional,
                )
                if v4_params is not None:
                    selection.selection_context["pinned_fallback_skipped"] = True
                    selection.selection_context["library_exhausted"] = True
                    return selection, v4_params, bucket
            selection.selection_context["pinned_fallback_blocked"] = True
            selection.selection_context["library_exhausted"] = True
            return selection, None, bucket

        # Legacy pinned defaults — only when v4 pool is not loaded.
        from app.services.dynamic_param_score.param_pool.defaults import _pinned_templates

        pinned_key = _PINNED_FALLBACK_ALIASES.get(fallback_key or "", fallback_key or "")
        pinned = {t.template_key: t for t in _pinned_templates()}
        tmpl = pinned.get(pinned_key or "")
        if tmpl is None and selection.profile_family == ProfileFamily.SELL_MANAGEMENT_ONLY.value:
            tmpl = (
                pinned.get("BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT")
                or pinned.get("BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT")
            )
        if tmpl:
            params = render_template(
                tmpl,
                param_score=param_score,
                regime=regime,
                ind=ind,
                constraints=constraints,
                current_exposure_frac=portfolio.current_base_exposure_frac,
                budget_usdt=budget_usdt,
                min_notional=min_notional,
            )
            params, resolver_meta = _apply_v4_resolvers_if_needed(
                selection,
                params,
                sub=sub,
                ind=ind,
                constraints=constraints,
                budget_usdt=budget_usdt,
                min_notional=min_notional,
            )
            if resolver_meta:
                selection.selection_context.update(resolver_meta)
            selection.selection_context["fallback_profile_re_resolved"] = True
            selection.selection_context["pinned_fallback_template_key"] = tmpl.template_key
            if selection.selection_context.get("active_template_count", 0) <= 0:
                from app.services.dynamic_param_score.param_pool.versioning import production_pool_status

                pool_stat = production_pool_status()
                selection.selection_context["active_template_count"] = int(
                    pool_stat.get("route_index_profile_count") or 0
                )
            return selection, params, bucket
        if _runtime_safe_permitted(selection):
            v4_params, _ = _v4_runtime_fallback_params(
                selection,
                sub=sub,
                ind=ind,
                constraints=constraints,
                budget_usdt=budget_usdt,
                min_notional=min_notional,
            )
            if v4_params is not None:
                return selection, v4_params, bucket
        else:
            selection.selection_context["runtime_safe_blocked"] = True
            selection.selection_context["runtime_safe_block_reason"] = (
                "pool_not_loaded_or_shelf_not_exhausted"
            )
        return selection, None, bucket

    params = render_template(
        selection.template,
        param_score=param_score,
        regime=regime,
        ind=ind,
        constraints=constraints,
        current_exposure_frac=portfolio.current_base_exposure_frac,
        budget_usdt=budget_usdt,
        min_notional=min_notional,
    )
    params, resolver_meta = _apply_v4_resolvers_if_needed(
        selection,
        params,
        sub=sub,
        ind=ind,
        constraints=constraints,
        budget_usdt=budget_usdt,
        min_notional=min_notional,
    )
    if resolver_meta:
        selection.selection_context.update(resolver_meta)
    return selection, params, bucket


def _apply_v4_resolvers_if_needed(
    selection: TemplateSelectionResult,
    params: Optional[BotParams],
    *,
    sub: SubScores,
    ind: IndicatorSnapshot,
    constraints: ExchangeConstraints,
    budget_usdt: float,
    min_notional: float,
) -> Tuple[Optional[BotParams], Dict[str, Any]]:
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

    if params is None or selection.pool_version != POOL_VERSION_V4:
        return params, {}
    from app.services.dynamic_param_score.param_generator.v4_resolvers import apply_v4_resolvers

    sig = (selection.selection_context or {}).get("market_signature") or sub.to_dict()
    if hasattr(sub, "to_dict"):
        fee_score = int(sub.fee_efficiency_score or 50)
    else:
        fee_score = 50
    params, rctx, fits = apply_v4_resolvers(
        params,
        template=selection.template,
        signature=sig if isinstance(sig, dict) else {},
        budget=budget_usdt,
        min_notional=min_notional,
        constraints=constraints,
        ind=ind,
        fee_efficiency_score=fee_score,
    )
    meta = {
        "capacity_resolution": rctx.capacity.to_dict(),
        "cost_resolution": rctx.cost.to_dict(),
        "structure_fit": fits.get("structure_fit", 1.0),
        "grid_direction_fit": fits.get("grid_direction_fit", 1.0),
        "base_quote_fit": fits.get("base_quote_fit", 1.0),
    }
    if rctx.safety_hard:
        meta["safety_hard"] = True
        meta["safety_reason"] = rctx.safety_reason
    return params, meta
