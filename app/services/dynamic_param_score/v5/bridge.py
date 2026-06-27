"""V5 bridge — exact shelf lookup + resolver → BotParams / selection result."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

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
    SelectionContext,
    TemplateSelectionResult,
)
from app.services.dynamic_param_score.v5.domain.route_key import make_route_key
from app.services.dynamic_param_score.v5.domain.types import V5ResolveInput, V5ResolvedParam
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.index.route_lookup import (
    build_v5_route_index,
    get_cached_index,
    set_cached_index,
)
from app.services.dynamic_param_score.v5.live_route_classifier_v5 import classify_live_route_v5
from app.services.dynamic_param_score.v5.resolver.resolve_dynamic_param_v5 import resolve_dynamic_param_v5
from app.services.dynamic_param_score.v5.ui_trace import (
    build_route_semantic_label,
    risk_label_from_route,
)
from app.services.dynamic_param_score.v5.store.sqlite_store import DEFAULT_V5_SQLITE_PATH
from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V5


def v5_pool_enabled() -> bool:
    if os.environ.get("PARAM_POOL_VERSION") == POOL_VERSION_V5:
        return True
    if os.environ.get("PARAM_POOL_MODE") == "v5":
        return True
    if os.environ.get("DISABLE_V5_POOL", "").strip().lower() in ("1", "true", "yes"):
        return False
    return DEFAULT_V5_SQLITE_PATH.exists()


@lru_cache(maxsize=1)
def get_v5_route_index():
    cached = get_cached_index()
    if cached is not None:
        return cached
    shelves = generate_all_v5_shelves()
    index = build_v5_route_index(shelves)
    set_cached_index(index)
    return index


def v5_resolved_to_bot_params(resolved: V5ResolvedParam) -> BotParams:
    n = resolved.final_grid_count or len(resolved.buy_grid_levels_pct)
    buy_dist = [x / 100.0 for x in resolved.buy_distribution_pct[:n]]
    sell_dist = [x / 100.0 for x in resolved.sell_distribution_pct[:n]]
    base_frac = resolved.target_base_pct / 100.0
    return BotParams(
        base_alloc_frac=base_frac,
        quote_alloc_frac=resolved.target_quote_pct / 100.0,
        buy_grid_count=n,
        sell_grid_count=n,
        buy_grid_spacing_pct=float(resolved.buy_grid_levels_pct[0]) if n else 0,
        sell_grid_spacing_pct=float(resolved.sell_grid_levels_pct[0]) if n else 0,
        buy_qty_distribution=buy_dist or [0.5, 0.5],
        sell_qty_distribution=sell_dist or [0.5, 0.5],
        trailing_enabled=n > 0,
        trailing_callback_pct=max(resolved.buy_trailing_pct, resolved.sell_trailing_pct),
        take_profit_pct=resolved.take_profit_sell_trigger_pct,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=resolved.max_base_exposure_pct / 100.0,
        max_quote_to_spend_per_buy_frac=min(max(buy_dist) if buy_dist else 0.35, 0.45),
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=resolved.min_profit_after_cost_floor_pct,
        emergency_no_buy=resolved.selection_type == "GLOBAL_SAFE_V5",
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code=f"v5_{resolved.shelf_id}",
        buy_grid_ladder_pcts=list(resolved.buy_grid_levels_pct),
        sell_grid_ladder_pcts=list(resolved.sell_grid_levels_pct),
        rebuy_trigger_pct=resolved.take_profit_buy_trigger_pct,
        rebuy_trail_pct=resolved.take_profit_buy_trailing_pct,
        resell_trigger_pct=resolved.take_profit_sell_trigger_pct,
        resell_trail_pct=resolved.take_profit_sell_trailing_pct,
        selected_template_key=resolved.shelf_id,
    )


def _synthetic_v5_template(resolved: V5ResolvedParam, route_key: str) -> ParamTemplate:
    """Minimal ParamTemplate wrapper for telemetry compatibility."""
    action = FinalAction.BALANCED_GRID.value
    if resolved.final_grid_count == 0:
        action = FinalAction.WAIT.value
    return ParamTemplate(
        template_key=resolved.shelf_id,
        version=POOL_VERSION_V5,
        profile_family="V5_EXACT_SHELF",
        final_action=action,
        supported_regimes=[RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL", "DEFENSIVE", "CAUTION"],
        score_min=0,
        score_max=100,
        budget_tiers=["STANDARD"],
        exposure_tiers=["TARGET_BASE"],
        headroom_tiers=["GOOD_HEADROOM"],
        fee_tiers=["FEE_OK"],
        min_equity_usdt=0,
        min_notional_multiple=10,
        params={
            "dps_engine_version": "DPS_ENGINE_V5",
            "profile_id": resolved.shelf_id,
            "route_key": route_key,
            "selection_type": resolved.selection_type,
            "v5_version": "DPLV5",
        },
        hard_limits={},
        priority=100,
        deployable=resolved.final_grid_count > 0,
        status="active",
        notes=f"V5 exact shelf {resolved.shelf_id}",
    )


def v5_select_and_render(
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
    selection_context: Optional[SelectionContext] = None,
) -> Tuple[TemplateSelectionResult, Optional[BotParams], str]:
    sym = symbol or getattr(bot_context, "symbol", "") or ""
    classification = classify_live_route_v5(
        symbol=sym,
        regime_tag=regime.value,
        risk_state=risk_state,
        sub=sub,
        ind=ind,
    )
    index = get_v5_route_index()
    base_pct = float(portfolio.current_base_exposure_frac or 0) * 100
    quote_pct = max(0.0, 100.0 - base_pct)
    resolve_input = V5ResolveInput(
        symbol=sym,
        route_parts=classification.route_parts,
        budget_usdt=float(budget_usdt),
        min_notional_usdt=float(min_notional),
        current_base_pct=base_pct,
        current_quote_pct=quote_pct,
        maker_fee_pct=float(constraints.maker_fee_pct or 0),
        taker_fee_pct=float(constraints.taker_fee_pct or 0),
        spread_pct=float(ind.orderbook_spread_pct or 0) / 2.0,
        slippage_pct=float(constraints.estimated_slippage_pct or 0),
        rounding_pct=0.01,
        indicators={
            "rsi1h": float(ind.rsi14_1h or 50),
            "bb_position": float(ind.price_in_bb or 0.5),
            "btc_crash_velocity": float(ind.btc_crash_velocity or 0),
            "crash_velocity": float(getattr(ind, "crash_velocity", 0) or 0),
        },
        data_quality={
            "freshness_sec": 30,
            "candle_count5m": 100,
            "data_gap_sec": 0,
            "price_valid": True,
        },
    )
    resolved = resolve_dynamic_param_v5(resolve_input, index)
    params = v5_resolved_to_bot_params(resolved)
    template = _synthetic_v5_template(resolved, classification.route_key)

    selection = TemplateSelectionResult(
        pool_version=POOL_VERSION_V5,
        selected_template_key=resolved.shelf_id,
        profile_family="V5_EXACT_SHELF",
        final_action=template.final_action,
        selection_score=100.0 if resolved.selection_type == "EXACT_V5" else 50.0,
        candidate_count=1,
        filtered_out={},
        fallback_used=resolved.selection_type != "EXACT_V5",
        fallback_reason=None if resolved.selection_type == "EXACT_V5" else resolved.selection_type,
        template=template,
        selection_context={
            "route_key": classification.route_key,
            "matched_route_key": classification.route_key,
            "selection_type": resolved.selection_type,
            "v5_shelf_id": resolved.shelf_id,
            "v5_route_key": classification.route_key,
            "exact_route_hit": resolved.trace.exact_route_hit,
            "engine_version": "DPS_ENGINE_V5",
            "route_risk_code": classification.route_parts.risk,
            "route_risk_label": risk_label_from_route(classification.route_key),
            "route_semantic_label": build_route_semantic_label(classification.route_key),
            "resolver_trace": {
                "budget": resolved.trace.budget_adjustments,
                "position": resolved.trace.position_adjustments,
                "momentum": resolved.trace.momentum_adjustments,
                "data_quality": resolved.trace.data_quality_adjustments,
                "execution_cost": resolved.trace.execution_cost_adjustments,
                "btc_context": resolved.trace.btc_context_adjustments,
                "risk_clamp": resolved.trace.risk_clamp_adjustments,
                "final_validation": resolved.trace.final_validation_adjustments,
            },
        },
    )
    bucket = "V5_EXACT" if resolved.selection_type == "EXACT_V5" else resolved.selection_type
    return selection, params, bucket


def build_v5_selection_trace_for_ui(resolved: V5ResolvedParam, route_key: str) -> Dict[str, Any]:
    return {
        "engine_version": "DPS_ENGINE_V5",
        "profile_id": resolved.shelf_id,
        "profile_display": resolved.shelf_id,
        "route_key": route_key,
        "selection_type": resolved.selection_type,
        "exact_route_hit": resolved.trace.exact_route_hit,
        "fallback_used": resolved.trace.fallback_used,
    }
