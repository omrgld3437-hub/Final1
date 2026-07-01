"""V6 catalog / final profile → BotParams for PA / DM UI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.services.dynamic_param_score.models import BotParams
from app.services.dynamic_param_score.v6.constants import DEFAULT_COST_FLOOR_PCT
from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile, V6FinalProfile
from app.services.dynamic_param_score.v6.v6_quantizer import profit_pct_from_code, trailing_pct_from_code

POOL_VERSION_V6 = "v6"


def v6_profile_to_display_dict(
    profile: V6CatalogProfile,
    *,
    bot_budget_usdt: float = 0.0,
    adjuster_trace: Optional[List[Any]] = None,
    catalog_profile_id: str = "",
    final_profile_id: str = "",
) -> Dict[str, Any]:
    """Flat dict for telemetry / PA sections (spec field list)."""
    base_pct = profile.base_allocation_pct
    quote_pct = profile.quote_allocation_pct
    budget = float(bot_budget_usdt or 0.0)
    buy_dist = [abs(g.distance_pct) for g in profile.buy_grids]
    buy_amt = [g.amount_pct for g in profile.buy_grids]
    sell_dist = [g.distance_pct for g in profile.sell_grids]
    sell_amt = [g.amount_pct for g in profile.sell_grids]
    sell_trail = trailing_pct_from_code(profile.sell_trailing_code)
    buy_trail = trailing_pct_from_code(profile.buy_trailing_code)
    post_sell_bb = profile.buyback_after_sell_enabled
    post_bb_profit = profile.profit_sell_after_buyback_enabled
    return {
        "base_allocation_pct": base_pct,
        "quote_allocation_pct": quote_pct,
        "initial_base_budget_usdt": round(budget * base_pct / 100.0, 2),
        "quote_budget_usdt": round(budget * quote_pct / 100.0, 2),
        "normal_buy_enabled": profile.normal_buy_enabled,
        "buy_grid_count": len(profile.buy_grids) if profile.normal_buy_enabled else 0,
        "buy_grid_distances_pct": buy_dist,
        "buy_grid_amounts_pct": buy_amt,
        "buy_trailing_pct": buy_trail,
        "sell_grid_enabled": bool(profile.sell_grids),
        "sell_grid_count": len(profile.sell_grids),
        "sell_grid_distances_pct": sell_dist,
        "sell_grid_amounts_pct": sell_amt,
        "sell_trailing_pct": sell_trail,
        "post_sell_buyback_enabled": post_sell_bb,
        "post_sell_buyback_trigger_pct": (
            profit_pct_from_code(profile.buyback_trigger_code) if post_sell_bb else None
        ),
        "post_sell_buyback_trailing_pct": (
            trailing_pct_from_code(profile.buyback_trailing_code) if post_sell_bb else None
        ),
        "post_buyback_profit_sell_enabled": post_bb_profit,
        "post_buyback_profit_sell_trigger_pct": (
            profit_pct_from_code(profile.profit_sell_trigger_code) if post_bb_profit else None
        ),
        "post_buyback_profit_sell_trailing_pct": (
            trailing_pct_from_code(profile.profit_sell_trailing_code) if post_bb_profit else None
        ),
        "scenario_identity": {
            "regime_id": profile.scenario.regime_id,
            "sub_id": profile.scenario.sub_id,
            "micro_id": profile.scenario.micro_id,
            "terminal_id": profile.scenario.terminal_id,
            "behavior_id": profile.scenario.behavior_id,
            "severity": profile.scenario.severity,
            "name": profile.scenario.name,
        },
        "behavior_id": profile.scenario.behavior_id,
        "severity": profile.scenario.severity,
        "adjuster_trace": list(adjuster_trace or []),
        "profile_id": profile.profile_id,
        "final_profile_id": final_profile_id or profile.profile_id,
        "catalog_profile_id": catalog_profile_id or profile.profile_id,
        # PA/DM alias fields (staging contract)
        "rebuy_enabled": post_sell_bb,
        "rebuy_trigger_pct": (
            profit_pct_from_code(profile.buyback_trigger_code) if post_sell_bb else None
        ),
        "rebuy_trailing_pct": (
            trailing_pct_from_code(profile.buyback_trailing_code) if post_sell_bb else None
        ),
        "profit_sell_enabled": post_bb_profit,
        "profit_sell_trigger_pct": (
            profit_pct_from_code(profile.profit_sell_trigger_code) if post_bb_profit else None
        ),
        "profit_sell_trailing_pct": (
            trailing_pct_from_code(profile.profit_sell_trailing_code) if post_bb_profit else None
        ),
    }


def v6_profile_to_bot_params(
    profile: V6CatalogProfile,
    *,
    catalog_profile_id: str = "",
) -> BotParams:
    """Map V6 lattice profile to legacy BotParams (profit loop: sell → buyback → profit sell)."""
    buy_n = len(profile.buy_grids) if profile.normal_buy_enabled else 0
    sell_n = len(profile.sell_grids)
    buy_dist = [abs(g.distance_pct) for g in profile.buy_grids]
    sell_dist = [g.distance_pct for g in profile.sell_grids]
    buy_weights = [g.amount_pct / 100.0 for g in profile.buy_grids]
    sell_weights = [g.amount_pct / 100.0 for g in profile.sell_grids]

    sell_trail = trailing_pct_from_code(profile.sell_trailing_code)
    buy_trail = trailing_pct_from_code(profile.buy_trailing_code)
    post_sell_bb = profile.buyback_after_sell_enabled
    post_bb_profit = profile.profit_sell_after_buyback_enabled

    rebuy_trigger = profit_pct_from_code(profile.buyback_trigger_code) if post_sell_bb else None
    rebuy_trail = trailing_pct_from_code(profile.buyback_trailing_code) if post_sell_bb else None
    resell_trigger = profit_pct_from_code(profile.profit_sell_trigger_code) if post_bb_profit else None
    resell_trail = trailing_pct_from_code(profile.profit_sell_trailing_code) if post_bb_profit else None

    base_frac = profile.base_allocation_pct / 100.0
    pid = catalog_profile_id or profile.profile_id
    sell_only = not profile.normal_buy_enabled and sell_n > 0

    return BotParams(
        base_alloc_frac=base_frac,
        quote_alloc_frac=profile.quote_allocation_pct / 100.0,
        buy_grid_count=buy_n,
        sell_grid_count=sell_n,
        buy_grid_spacing_pct=float(buy_dist[0]) if buy_dist else 0.0,
        sell_grid_spacing_pct=float(sell_dist[0]) if sell_dist else 0.0,
        buy_qty_distribution=buy_weights,
        sell_qty_distribution=sell_weights,
        trailing_enabled=buy_n > 0 or sell_n > 0,
        trailing_callback_pct=max(sell_trail, buy_trail),
        take_profit_pct=resell_trigger or (rebuy_trigger or DEFAULT_COST_FLOOR_PCT),
        stop_new_buys_below_score=0,
        max_base_exposure_frac=min(base_frac + 0.15, 0.95),
        max_quote_to_spend_per_buy_frac=min(max(buy_weights) if buy_weights else 0.35, 0.45),
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=DEFAULT_COST_FLOOR_PCT,
        emergency_no_buy=profile.scenario.behavior_id == "PB16",
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code=f"v6_{pid}",
        buy_disabled=not profile.normal_buy_enabled,
        sell_only_mode=sell_only,
        rebuy_enabled=post_sell_bb,
        resell_enabled=post_bb_profit,
        selected_template_key=pid,
        pool_version=POOL_VERSION_V6,
        management_mode="CONTROLLED_GRID",
        buy_grid_ladder_pcts=buy_dist,
        sell_grid_ladder_pcts=sell_dist,
        rebuy_trigger_pct=rebuy_trigger,
        rebuy_trail_pct=rebuy_trail,
        resell_trigger_pct=resell_trigger,
        resell_trail_pct=resell_trail,
    )


def v6_final_to_bot_params(result: V6FinalProfile, *, bot_budget_usdt: float = 0.0) -> BotParams:
    return v6_profile_to_bot_params(
        result.profile,
        catalog_profile_id=result.catalog_profile_id,
    )


def v6_final_to_telemetry_extras(
    result: V6FinalProfile,
    *,
    bot_budget_usdt: float = 0.0,
    adjuster_trace: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    trace = adjuster_trace
    if trace is None:
        trace = result.telemetry.get("adjuster_trace") or result.adjuster_tags
    return v6_profile_to_display_dict(
        result.profile,
        bot_budget_usdt=bot_budget_usdt,
        adjuster_trace=trace,
        catalog_profile_id=result.catalog_profile_id,
        final_profile_id=result.final_profile_id,
    )
