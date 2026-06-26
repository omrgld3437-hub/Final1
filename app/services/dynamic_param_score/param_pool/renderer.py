"""Render ParamTemplate into live BotParams."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.feasibility import (
    min_grid_spacing_pct,
    min_trailing_pct,
    total_friction_pct,
)
from app.services.dynamic_param_score.models import (
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    RegimeTag,
)
from app.services.dynamic_param_score.param_generator.grid_math import compute_grid_ladder
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.utils import clamp, distribute_weights, scale


def _resolve_alloc(
    params: Dict[str, Any],
    param_score: int,
    current_exposure: float,
) -> tuple[float, float]:
    mode = str(params.get("base_alloc_mode") or "fixed")
    if mode == "current_aware":
        base = max(float(params.get("base_alloc_frac") or 0.4), current_exposure)
        base = min(base, float(params.get("max_base_exposure_cap") or C.MAX_BASE_ALLOC_FRAC))
    elif mode == "scale":
        lo = float(params.get("base_alloc_min") or 0.3)
        hi = float(params.get("base_alloc_max") or 0.5)
        smin = int(params.get("score_min") or 45)
        smax = int(params.get("score_max") or 75)
        base = scale(param_score, smin, smax, lo, hi)
    else:
        base = float(params.get("base_alloc_frac") or 0.4)
    base = min(base, C.MAX_BASE_ALLOC_FRAC)
    return round(base, 4), round(1.0 - base, 4)


def _resolve_spacing(
    mode_key: str,
    mult_key: str,
    min_key: str,
    max_key: str,
    params: Dict[str, Any],
    atr_pct: float,
    constraints: ExchangeConstraints,
    spread_pct: float,
) -> float:
    atr = max(float(atr_pct or 1.0), 0.1)
    mode = str(params.get(mode_key) or "atr_mult")
    mn = float(params.get(min_key) or C.MIN_SPACING_FLOOR_PCT)
    mx = float(params.get(max_key) or 4.0)
    friction_floor = min_grid_spacing_pct(constraints, spread_pct)
    friction_mult = float(params.get("spacing_friction_mult") or 0.0)
    if friction_mult > 0:
        friction_floor = max(
            friction_floor,
            friction_mult * total_friction_pct(constraints, spread_pct),
        )
    min_spacing = max(mn, friction_floor)

    if mode == "fixed":
        return round(clamp(float(params.get(mult_key) or min_spacing), min_spacing, mx), 4)

    mult = float(params.get(mult_key) or 0.9)
    return round(clamp(atr * mult, min_spacing, mx), 4)


def _resolve_trailing(
    params: Dict[str, Any],
    atr_pct: float,
    constraints: ExchangeConstraints,
    spread_pct: float,
) -> float:
    if not params.get("trailing_enabled"):
        return 0.0
    atr = max(float(atr_pct or 1.0), 0.1)
    mult = float(params.get("trailing_atr_mult") or 0.45)
    tmpl_min = float(params.get("min_trailing_pct") or C.MIN_TRAILING_FLOOR_PCT)
    floor = min_trailing_pct(constraints, spread_pct)
    return round(max(atr * mult, max(tmpl_min, floor)), 4)


def _resolve_exposure_cap(
    base_alloc: float,
    params: Dict[str, Any],
) -> float:
    extra = float(params.get("max_base_exposure_extra") or 0.08)
    cap = float(params.get("max_base_exposure_cap") or C.MAX_BASE_EXPOSURE_FRAC)
    return round(min(base_alloc + extra, cap, C.MAX_BASE_EXPOSURE_FRAC), 4)


def _distribution(
    count: int,
    mode: str,
    max_level: float = 0.30,
) -> List[float]:
    if count <= 0:
        return []
    if mode == "front_light":
        return distribute_weights(count, max_level * 0.85)
    if mode == "back_heavy":
        w = distribute_weights(count, max_level)
        return list(reversed(w))
    if mode == "equal":
        return [round(1.0 / count, 4)] * count
    return distribute_weights(count, max_level)


def _distribution_from_params(
    count: int,
    mode: str,
    params: Dict[str, Any],
    *,
    side: str,
    max_level: float = 0.30,
) -> List[float]:
    """Prefer explicit fractional weights from template params (DPS V2)."""
    if count <= 0:
        return []
    key = f"{side}_qty_distribution"
    explicit = params.get(key)
    if isinstance(explicit, list) and len(explicit) == count:
        total = sum(float(x) for x in explicit) or 1.0
        return [round(float(x) / total, 4) for x in explicit]
    dps = params.get("dps_profile") or {}
    pct_key = f"{side}_distribution"
    pct_list = dps.get(pct_key) or params.get(pct_key)
    if isinstance(pct_list, list) and len(pct_list) == count:
        total = sum(float(x) for x in pct_list) or 100.0
        return [round(float(x) / total, 4) for x in pct_list]
    return _distribution(count, mode, max_level)


def _spacing_from_dps_profile(
    params: Dict[str, Any],
    side: str,
    fallback: float,
) -> float:
    dps = params.get("dps_profile") or {}
    grids = dps.get(f"{side}_grid_pcts") or []
    if grids:
        return round(max(float(grids[0]), C.ABSOLUTE_MIN_FIRST_GRID_PCT), 4)
    key = f"{side}_grid_spacing_pct"
    if params.get(key):
        return round(max(float(params[key]), C.ABSOLUTE_MIN_FIRST_GRID_PCT), 4)
    return fallback


def render_template(
    template: ParamTemplate,
    *,
    param_score: int,
    regime: RegimeTag,
    ind: IndicatorSnapshot,
    constraints: ExchangeConstraints,
    current_exposure_frac: float = 0.0,
    budget_usdt: float = 1000.0,
    min_notional: float = C.DEFAULT_MIN_NOTIONAL_USDT,
) -> Optional[BotParams]:
    if template.final_action in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ):
        return None

    p = dict(template.params)
    p.setdefault("score_min", template.score_min)
    p.setdefault("score_max", template.score_max)

    spread_pct = float(ind.orderbook_spread_pct or 0.0)
    atr_pct = float(ind.atr14_pct_1h or ind.atr14_pct_5m or 1.0)

    base, quote = _resolve_alloc(p, param_score, current_exposure_frac)
    buy_n = int(p.get("buy_grid_count") or 0)
    sell_n = int(p.get("sell_grid_count") or 0)

    if template.hard_limits.get("buy_grid_allowed") is False:
        buy_n = 0
    max_buy = template.hard_limits.get("max_buy_levels")
    if max_buy is not None:
        buy_n = min(buy_n, int(max_buy))

    # Budget caps on grid counts
    budget = max(float(budget_usdt or 0.0), 0.0)
    min_n = max(float(min_notional or C.DEFAULT_MIN_NOTIONAL_USDT), 1.0)
    if budget <= C.SMALL_BUDGET_75_USDT:
        buy_n = min(buy_n, C.SMALL_BUDGET_MAX_GRID_COUNT)
        sell_n = min(sell_n, C.SMALL_BUDGET_MAX_GRID_COUNT)
    if budget <= C.SMALL_BUDGET_50_USDT:
        buy_n = min(buy_n, 3)
        sell_n = min(sell_n, 3)
    if budget < min_n * 10:
        buy_n = min(buy_n, 2)
        sell_n = min(sell_n, 2)

    buy_sp = _spacing_from_dps_profile(
        p,
        "buy",
        _resolve_spacing(
            "buy_spacing_mode",
            "buy_spacing_atr_mult",
            "buy_spacing_min_pct",
            "buy_spacing_max_pct",
            p,
            atr_pct,
            constraints,
            spread_pct,
        ),
    )
    sell_sp = _spacing_from_dps_profile(
        p,
        "sell",
        _resolve_spacing(
            "sell_spacing_mode",
            "sell_spacing_atr_mult",
            "sell_spacing_min_pct",
            "sell_spacing_max_pct",
            p,
            atr_pct,
            constraints,
            spread_pct,
        ),
    )
    trail = _resolve_trailing(p, atr_pct, constraints, spread_pct)
    max_exp = _resolve_exposure_cap(base, p)
    max_q = float(p.get("max_quote_to_spend_per_buy_frac") or C.MAX_QUOTE_PER_BUY_FRAC)

    if regime == RegimeTag.TRENDING_DOWN:
        max_q = min(max_q, C.TRENDING_DOWN_MAX_QUOTE_PER_BUY)
        base = min(base, C.TRENDING_DOWN_MAX_BASE_ALLOC)
        max_exp = min(max_exp, base + C.TRENDING_DOWN_MAX_EXPOSURE_EXTRA)

    buy_dist = _distribution_from_params(
        buy_n, str(p.get("buy_distribution") or "balanced"), p, side="buy"
    )
    sell_dist = _distribution_from_params(
        sell_n, str(p.get("sell_distribution") or "balanced"), p, side="sell"
    )

    tp = float(p.get("take_profit_pct") or clamp(sell_sp * 1.5, 0.5, 5.0))
    friction = total_friction_pct(constraints, spread_pct)
    min_profit = max(
        float(p.get("min_cycle_profit_after_fee_pct") or 0.0),
        buy_sp * 0.3 if buy_n else sell_sp * 0.3,
        friction * 2,
    )

    trailing_on = bool(p.get("trailing_enabled")) and trail > 0
    sell_only = template.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
    buy_disabled = sell_only or buy_n == 0 or template.hard_limits.get("buy_grid_allowed") is False
    emergency_no_buy = buy_disabled
    rebuy_on = buy_n > 0 and not buy_disabled and bool(p.get("rebuy_enabled", True))
    if sell_only:
        rebuy_on = False
        buy_n = 0
        buy_dist = []

    rebalance_policy = p.get("rebalance_policy")
    dps = p.get("dps_profile") or {}
    buy_ladder = dps.get("buy_grid_pcts") or p.get("buy_grid_ladder_pcts")
    sell_ladder = dps.get("sell_grid_pcts") or p.get("sell_grid_ladder_pcts")
    variant = hash(template.template_key) % 7
    if buy_n > 0 and not buy_ladder:
        buy_ladder = compute_grid_ladder(buy_sp, buy_n, variant_idx=variant)
    if sell_n > 0 and not sell_ladder:
        sell_ladder = compute_grid_ladder(sell_sp, sell_n, variant_idx=variant + 1)

    return BotParams(
        base_alloc_frac=base,
        quote_alloc_frac=quote,
        buy_grid_count=buy_n,
        sell_grid_count=sell_n,
        buy_grid_spacing_pct=buy_sp,
        sell_grid_spacing_pct=sell_sp,
        buy_qty_distribution=[round(x, 4) for x in buy_dist],
        sell_qty_distribution=[round(x, 4) for x in sell_dist],
        trailing_enabled=trailing_on,
        trailing_callback_pct=trail,
        take_profit_pct=round(tp, 4),
        stop_new_buys_below_score=30,
        max_base_exposure_frac=max_exp,
        max_quote_to_spend_per_buy_frac=round(max_q, 4),
        downtrend_buy_throttle=regime == RegimeTag.TRENDING_DOWN,
        min_cycle_profit_after_fee_pct=round(min_profit, 4),
        emergency_no_buy=emergency_no_buy,
        cancel_existing_buy_orders=bool(p.get("cancel_existing_buy_orders", regime == RegimeTag.DUMP_RISK)),
        cancel_existing_sell_orders=bool(p.get("cancel_existing_sell_orders", False)),
        reason_code=f"pool:{template.template_key}:{regime.value}",
        buy_disabled=buy_disabled,
        sell_only_mode=sell_only,
        rebuy_enabled=rebuy_on,
        resell_enabled=sell_n > 0 and bool(p.get("resell_enabled", True)),
        selected_template_key=template.template_key,
        pool_version=template.version,
        management_mode=template.final_action,
        rebalance_policy=rebalance_policy if isinstance(rebalance_policy, dict) else None,
        buy_grid_ladder_pcts=[float(x) for x in buy_ladder] if isinstance(buy_ladder, list) else None,
        sell_grid_ladder_pcts=[float(x) for x in sell_ladder] if isinstance(sell_ladder, list) else None,
        rebuy_trigger_pct=float(p["rebuy_trigger_pct"]) if p.get("rebuy_trigger_pct") is not None else None,
        rebuy_trail_pct=float(p["rebuy_trail_pct"]) if p.get("rebuy_trail_pct") is not None else None,
        resell_trigger_pct=float(p["resell_trigger_pct"]) if p.get("resell_trigger_pct") is not None else None,
        resell_trail_pct=float(p["resell_trail_pct"]) if p.get("resell_trail_pct") is not None else None,
    )
