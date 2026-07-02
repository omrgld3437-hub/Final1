"""Controlled / restricted grid deploy — market OK but soft safety failures."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.atmosphere import enforce_momentum_base_cap
from app.services.dynamic_param_score.distribution_policy import (
    DistributionContext,
    distribution_context_from_mapping,
    normalize_distribution_for_context,
    resolve_two_grid_weights,
)
from app.services.dynamic_param_score.feasibility import (
    simulate_worst_case_exposure,
    total_friction_pct,
)
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    SubScores,
)

HARD_NO_TRADE_BLOCKING = frozenset(
    {
        "SPREAD_HIGH",
        "LIQUIDITY_LOW",
        "DUMP_RISK",
        "DATA_QUALITY_LOW",
        "PARAM_SCORE_TOO_LOW",
        "BUDGET_TOO_SMALL",
    }
)


def compute_confidence_components(
    sub: SubScores,
    *,
    param_score: int,
    feasibility_meta: Optional[Dict[str, Any]] = None,
    blocking: Optional[List[str]] = None,
    fee_data_available: bool = True,
) -> Dict[str, int]:
    """Split deploy confidence into market / execution / parameter layers."""
    fm = feasibility_meta or {}
    blocking_u = {str(b).upper() for b in (blocking or [])}

    fee_score = int(sub.fee_efficiency_score or 50)
    if not fee_data_available:
        fee_score = 55

    market_parts = [
        int(sub.liquidity_score or 50),
        int(sub.spread_score or 50),
        int(sub.data_quality_score or 50),
        int(sub.range_score or 50),
        int(sub.volatility_score or 50),
    ]
    market_suitability = int(sum(market_parts) / len(market_parts))

    exec_parts = [
        fee_score,
        int(sub.exposure_safety_score or 50),
        int(sub.btc_market_risk_score or 50),
    ]
    execution_safety = int(sum(exec_parts) / len(exec_parts))
    if fm.get("exposure_hard_cap_breach"):
        execution_safety = max(0, execution_safety - 18)
    if fm.get("fee_bad_rebalance_deferred"):
        execution_safety = max(0, execution_safety - 8)

    parameter_validity = 88
    if fm.get("distribution_invalid"):
        parameter_validity -= 35
    if fm.get("exposure_hard_cap_breach"):
        parameter_validity -= 25
    if fm.get("deploy_blocked_reason"):
        parameter_validity -= 15
    if blocking_u & HARD_NO_TRADE_BLOCKING:
        parameter_validity = min(parameter_validity, 20)

    final_deploy = int(
        market_suitability * 0.35
        + execution_safety * 0.30
        + parameter_validity * 0.35
    )
    if 55 <= param_score < 65:
        final_deploy = max(0, final_deploy - 5)

    return {
        "market_suitability_score": max(0, min(100, market_suitability)),
        "execution_safety_score": max(0, min(100, execution_safety)),
        "parameter_validity_score": max(0, min(100, parameter_validity)),
        "final_deploy_confidence": max(0, min(100, final_deploy)),
    }


def market_allows_controlled_grid(
    sub: SubScores,
    ind: Optional[IndicatorSnapshot],
    blocking: List[str],
) -> bool:
    if {str(b).upper() for b in blocking} & HARD_NO_TRADE_BLOCKING:
        return False
    if int(sub.data_quality_score or 0) < C.DATA_QUALITY_BLOCKED:
        return False
    if int(sub.liquidity_score or 0) < C.LIQUIDITY_BLOCKED:
        return False
    if int(sub.spread_score or 0) < C.SPREAD_BLOCKED:
        return False
    crash = float(getattr(ind, "crash_velocity", 0) or 0) if ind else 0.0
    if crash < -2.0:
        return False
    return True


def _dist_ctx_from_sub(
    sub: SubScores,
    ind: Optional[IndicatorSnapshot],
    risk_state: str,
    *,
    fee_data_available: bool = True,
) -> DistributionContext:
    return distribution_context_from_mapping(
        {
            "risk_state": risk_state or "NORMAL",
            "liquidity_score": int(sub.liquidity_score or 50),
            "spread_score": int(sub.spread_score or 50),
            "btc_market_risk_score": int(sub.btc_market_risk_score or 50),
            "fee_efficiency_score": int(sub.fee_efficiency_score or 50),
            "volatility_score": int(sub.volatility_score or 50),
            "drawdown_risk_score": int(sub.drawdown_risk_score or 50),
            "lower_lows": bool(getattr(ind, "lower_lows", False) if ind else False),
            "higher_highs": bool(getattr(ind, "higher_highs", False) if ind else False),
            "regime_tag": str(getattr(ind, "regime_tag", "") if ind else ""),
            "rsi_5m": float(getattr(ind, "rsi14_5m", 0) or 0) if ind else None,
            "rsi_1h": float(getattr(ind, "rsi14_1h", 0) or 0) if ind else None,
            "fee_bad": not fee_data_available,
        }
    )


def fix_buy_distribution(
    params: BotParams,
    *,
    dist_ctx: DistributionContext,
) -> bool:
    buy_n = int(params.buy_grid_count or 0)
    if buy_n <= 0 or not params.buy_qty_distribution:
        return False
    pct = [max(1, int(round(float(w) * 100))) for w in params.buy_qty_distribution[:buy_n]]
    fixed, changed = normalize_distribution_for_context(pct, buy_n, dist_ctx)
    params.buy_qty_distribution = [round(x / 100.0, 6) for x in fixed]
    return changed or pct != fixed


def trim_exposure_for_controlled_grid(
    params: BotParams,
    portfolio: PortfolioState,
    context: BotContext,
    ladder_budget: float,
    min_notional: float,
    current_price: Optional[float],
    *,
    max_attempts: int = 24,
) -> Tuple[float, bool]:
    """Shrink ladder / target until worst-case exposure fits max cap."""
    tol = 0.0
    max_exp = float(params.max_base_exposure_frac or 0.72)
    budget = float(ladder_budget or 0.0)
    worst = simulate_worst_case_exposure(portfolio, params, budget, context, current_price)
    attempts = 0
    while worst > max_exp + tol and int(params.buy_grid_count or 0) > 0 and attempts < max_attempts:
        attempts += 1
        if budget > float(min_notional) * 1.25:
            budget *= 0.85
        elif float(params.base_alloc_frac or 0) > 0.35:
            params.base_alloc_frac = round(max(0.35, float(params.base_alloc_frac) - 0.025), 6)
            params.quote_alloc_frac = round(1.0 - params.base_alloc_frac, 6)
            params.max_base_exposure_frac = round(
                min(float(params.max_base_exposure_frac or 0.72), float(params.base_alloc_frac) + 0.06),
                6,
            )
            max_exp = float(params.max_base_exposure_frac or 0.72)
        elif float(params.max_base_exposure_frac or 0) > float(params.base_alloc_frac) + 0.01:
            params.max_base_exposure_frac = round(
                max(float(params.base_alloc_frac) + 0.01, float(params.max_base_exposure_frac) - 0.015),
                6,
            )
            max_exp = float(params.max_base_exposure_frac or 0.72)
        else:
            break
        worst = simulate_worst_case_exposure(portfolio, params, budget, context, current_price)
    ok = worst <= max_exp + tol and int(params.buy_grid_count or 0) > 0
    return budget, ok


def try_controlled_grid_resolution(
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
    current_price: Optional[float] = None,
    fee_data_available: bool = True,
) -> Tuple[BotParams, str, bool, Dict[str, Any]]:
    """Attempt controlled grid when market is suitable but full deploy failed."""
    meta = dict(feasibility_meta or {})
    if deployable or not market_allows_controlled_grid(sub, ind, blocking):
        return params, final_action, deployable, meta

    p = copy.deepcopy(params)
    dist_ctx = _dist_ctx_from_sub(sub, ind, risk_state, fee_data_available=fee_data_available)
    if enforce_momentum_base_cap(p, dist_ctx):
        meta["base_target_capped"] = True
    dist_fixed = fix_buy_distribution(p, dist_ctx=dist_ctx)
    if dist_fixed:
        meta["distribution_invalid"] = False
        meta.pop("deploy_blocked_reason", None)
        meta["controlled_distribution_fix"] = list(resolve_two_grid_weights(dist_ctx))

    ladder = float(meta.get("buy_ladder_budget_usdt") or 0.0)
    min_n = float(constraints.min_notional or C.DEFAULT_MIN_NOTIONAL_USDT)
    ladder, exposure_ok = trim_exposure_for_controlled_grid(
        p, portfolio, context, ladder, min_n, current_price
    )
    if exposure_ok:
        meta["exposure_hard_cap_breach"] = False
        meta.pop("deploy_blocked_reason", None)
        meta["buy_ladder_budget_usdt"] = round(ladder, 4)
        worst = simulate_worst_case_exposure(portfolio, p, ladder, context, current_price)
        meta["worst_case_base_exposure_frac"] = round(worst, 6)

    comps = compute_confidence_components(
        sub,
        param_score=int(meta.get("param_score") or 50),
        feasibility_meta=meta,
        blocking=blocking,
        fee_data_available=fee_data_available,
    )
    meta["confidence_components"] = comps

    if not exposure_ok and meta.get("distribution_invalid"):
        return params, final_action, False, meta

    if not dist_fixed and not exposure_ok and not (not fee_data_available and market_allows_controlled_grid(sub, ind, blocking)):
        return params, final_action, False, meta

    if not dist_fixed and not exposure_ok and not fee_data_available:
        if int(p.buy_grid_count or 0) >= 2 and exposure_ok:
            meta["controlled_grid"] = True
            meta["controlled_grid_mode"] = "controlled_grid"
            meta["fee_bad_rebalance_deferred"] = True
            action = FinalAction.CONTROLLED_GRID.value
            return p, action, True, meta
        return params, final_action, False, meta

    if not exposure_ok:
        return params, final_action, False, meta

    meta["controlled_grid"] = True
    meta["controlled_grid_mode"] = (
        "restricted_deployable_grid" if exposure_ok and dist_fixed else "controlled_grid"
    )
    if not fee_data_available:
        meta["fee_bad_rebalance_deferred"] = True

    action = FinalAction.CONTROLLED_GRID.value
    if int(p.buy_grid_count or 0) >= 2 and int(p.sell_grid_count or 0) >= 2:
        action = FinalAction.CONTROLLED_GRID.value
    elif int(p.buy_grid_count or 0) > 0:
        action = FinalAction.ACTIVE_DEFENSIVE_GRID.value

    meta["auto_rebalance"] = False
    meta["rebalance_deferred"] = bool(meta.get("fee_bad_rebalance_deferred"))
    dep = bool(exposure_ok and int(p.buy_grid_count or 0) > 0)
    worst = float(meta.get("worst_case_base_exposure_frac") or 0)
    max_exp = float(meta.get("max_base_exposure_frac") or p.max_base_exposure_frac or 0.72)
    if worst > max_exp:
        meta.pop("controlled_grid", None)
        meta.pop("controlled_grid_mode", None)
        meta["exposure_hard_cap_breach"] = True
        meta["full_deployable"] = False
        return params, final_action, False, meta
    return p, action, dep, meta
