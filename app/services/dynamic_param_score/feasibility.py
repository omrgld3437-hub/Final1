"""Budget, min-notional and exposure feasibility for Dynamic Param Score Engine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    SafetyGateResult,
    SubScores,
)
from app.services.dynamic_param_score.utils import distribute_weights


def _finalize_buy_distribution(
    weights: List[float],
    *,
    defensive: bool = False,
    dist_ctx: Optional["DistributionContext"] = None,
) -> List[float]:
    if not weights:
        return weights
    from app.services.dynamic_param_score.distribution_policy import (
        DistributionContext,
        normalize_distribution_for_context,
    )
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        normalize_side_distribution,
    )

    pct = [max(1, int(round(float(w) * 100))) for w in weights]
    ctx = dist_ctx or DistributionContext(
        risk_state="DEFENSIVE" if defensive else "NORMAL"
    )
    fixed, _ = normalize_distribution_for_context(pct, len(pct), ctx)
    return [round(x / 100.0, 6) for x in fixed]


def total_friction_pct(
    constraints: ExchangeConstraints,
    spread_pct: Optional[float] = None,
) -> float:
    spread = max(0.0, float(spread_pct or 0.0))
    return (
        float(constraints.maker_fee_pct)
        + float(constraints.estimated_slippage_pct)
        + spread / 2.0
    )


def min_grid_spacing_pct(
    constraints: ExchangeConstraints,
    spread_pct: Optional[float] = None,
) -> float:
    friction = total_friction_pct(constraints, spread_pct)
    return max(C.MIN_GRID_SPACING_ABS_PCT, C.MIN_GRID_SPACING_FRICTION_MULT * friction)


def min_trailing_pct(
    constraints: ExchangeConstraints,
    spread_pct: Optional[float] = None,
) -> float:
    friction = total_friction_pct(constraints, spread_pct)
    return max(C.MIN_TRAILING_FLOOR_PCT, C.TRAILING_FEE_MULTIPLIER * friction)


def floor_to_step_qty(qty: float, step_size: float) -> float:
    """Round quantity down to exchange step size."""
    step = max(float(step_size or 0), 0.0)
    if step <= 0:
        return max(float(qty or 0), 0.0)
    import math

    return math.floor(max(float(qty or 0), 0.0) / step) * step


def has_sellable_base_feasible(
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    *,
    price: Optional[float] = None,
) -> Tuple[bool, float]:
    """True when base can fund at least one min-notional sell after step-size floor."""
    mn = max(float(constraints.min_notional or 0), 1.0)
    base_val = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    if base_val < mn:
        return False, base_val

    base_bal = max(float(portfolio.base_balance or 0.0), 0.0)
    px = float(price or 0.0)
    if px <= 0 and base_bal > 0 and base_val > 0:
        px = base_val / base_bal
    elif px <= 0 and portfolio.average_entry_price:
        px = float(portfolio.average_entry_price or 0.0)

    step = max(float(constraints.step_size or 0.0), 0.0)
    min_qty = max(float(constraints.min_qty or 0.0), 0.0)

    if base_bal > 0 and step > 0:
        sell_qty = floor_to_step_qty(base_bal, step)
        if sell_qty < min_qty:
            return False, base_val
        if px > 0 and sell_qty * px < mn:
            return False, base_val
    elif base_bal > 0 and px > 0 and base_bal * px < mn:
        return False, base_val

    return True, base_val


def exposure_headroom_quote_usdt(
    portfolio: PortfolioState,
    max_base_exposure_frac: float,
) -> float:
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)
    if equity <= 0:
        return 0.0
    max_base_value = float(max_base_exposure_frac) * equity
    current_base_value = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    return max(0.0, max_base_value - current_base_value)


def allowed_buy_quote_usdt(
    portfolio: PortfolioState,
    max_base_exposure_frac: float,
    current_price: Optional[float] = None,
) -> float:
    """Live execution parity: max quote spendable without breaching base exposure cap."""
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)
    if equity <= 0:
        return 0.0
    price = float(current_price or 0.0)
    if price > 0 and portfolio.base_balance:
        base_value = float(portfolio.base_balance) * price
    else:
        base_value = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    max_base_value = float(max_base_exposure_frac) * equity
    return max(0.0, max_base_value - base_value)


def _buy_budget_cap_frac(profile_name: str) -> float:
    if profile_name:
        return float(C.BUY_BUDGET_CAP_FRAC.get(profile_name, 1.0))
    return 1.0


def buy_ladder_budget_usdt(
    portfolio: PortfolioState,
    params: BotParams,
    context: BotContext,
    profile_name: str = "",
) -> float:
    """Quote budget for DCA buy ladder after initial allocation — exposure-capped."""
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)
    if equity <= 0:
        return 0.0
    quote_pool = max(float(portfolio.quote_value_usdt or 0.0), 0.0)
    cap_frac = _buy_budget_cap_frac(profile_name)
    quote_cap = quote_pool * cap_frac
    headroom = exposure_headroom_quote_usdt(portfolio, params.max_base_exposure_frac)
    if context.is_first_start and float(portfolio.current_base_exposure_frac or 0.0) <= 0:
        initial_quote = equity * float(params.base_alloc_frac)
        quote_after_initial = max(0.0, quote_pool - initial_quote)
        # V2: kalan quote alış gridlerine — headroom ile kısma (grid mesafesi koruma sağlar)
        return min(quote_after_initial, quote_cap)
    return min(quote_pool, headroom, quote_cap)


def simulate_worst_case_exposure(
    portfolio: PortfolioState,
    params: BotParams,
    buy_ladder_budget: float,
    context: BotContext,
    current_price: Optional[float] = None,
) -> float:
    """Conservative worst-case base exposure if all buy grid levels fill."""
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)
    if equity <= 0:
        return 0.0
    price = max(float(current_price or 0.0), 1e-9)
    base_qty = float(portfolio.base_balance or 0.0)
    if base_qty <= 0 and float(portfolio.base_value_usdt or 0.0) > 0:
        base_qty = float(portfolio.base_value_usdt) / price

    if context.is_first_start and base_qty * price <= 0:
        initial_quote = equity * float(params.base_alloc_frac)
        base_qty += initial_quote / price

    quote_remaining = max(0.0, float(buy_ladder_budget))
    weights = params.buy_qty_distribution or []
    if weights and quote_remaining > 0:
        for w in weights:
            level_quote = quote_remaining * float(w)
            base_qty += level_quote / price
    else:
        base_qty += quote_remaining / price

    return min(1.0, (base_qty * price) / equity)


def worst_case_base_exposure_frac(
    portfolio: PortfolioState,
    params: BotParams,
    buy_ladder_budget: float,
    context: BotContext,
    current_price: Optional[float] = None,
) -> float:
    return simulate_worst_case_exposure(
        portfolio, params, buy_ladder_budget, context, current_price
    )


def _level_notionals(side_budget: float, weights: List[float]) -> List[float]:
    return [max(0.0, float(side_budget) * float(w)) for w in weights]


def _reduce_grid_until_feasible(
    grid_count: int,
    weights: List[float],
    side_budget: float,
    min_notional: float,
    max_level_weight: float,
    defensive: bool = False,
) -> Tuple[int, List[float], bool]:
    n = int(grid_count)
    while n > 0:
        w = _finalize_buy_distribution(
            distribute_weights(n, max_level_weight),
            defensive=defensive,
        )
        notionals = _level_notionals(side_budget, w)
        if all(x >= min_notional - 1e-9 for x in notionals):
            return n, w, True
        n -= 1
    return 0, [], False


def apply_exposure_and_notional_feasibility(
    params: BotParams,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    context: BotContext,
    gates: List[SafetyGateResult],
    warnings: List[str],
    profile_name: str = "",
    current_price: Optional[float] = None,
    final_action: str = "",
    risk_state: str = "",
    sub: Optional[SubScores] = None,
    ind: Optional[IndicatorSnapshot] = None,
) -> Tuple[BotParams, Dict[str, Any]]:
    """Cap buy ladder to exposure headroom; shrink grids for min-notional."""
    meta: Dict[str, Any] = {
        "exposure_gate_adjusted": False,
        "min_notional_adjusted": False,
        "execution_exposure_cap_enabled": True,
        "live_parity_ok": True,
    }
    p = params
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)
    min_n = float(constraints.min_notional)
    tol = float(C.WORST_CASE_EXPOSURE_TOLERANCE)
    defensive = (
        final_action
        in (
            FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            FinalAction.DEFENSIVE_GRID.value,
        )
        or str(risk_state or "").upper() in ("DEFENSIVE", "CAUTION")
        or float(params.max_base_exposure_frac or 1.0) <= 0.55
    )
    from app.services.dynamic_param_score.distribution_policy import (
        distribution_context_from_mapping,
        is_buy_distribution_valid,
        normalize_distribution_for_context,
        resolve_two_grid_weights,
    )

    dist_ctx = distribution_context_from_mapping(
        {
            "risk_state": risk_state or ("DEFENSIVE" if defensive else "NORMAL"),
            "liquidity_score": int(sub.liquidity_score if sub else 50),
            "spread_score": int(sub.spread_score if sub else 50),
            "btc_market_risk_score": int(sub.btc_market_risk_score if sub else 50),
            "fee_efficiency_score": int(sub.fee_efficiency_score if sub else 50),
            "volatility_score": int(sub.volatility_score if sub else 50),
            "drawdown_risk_score": int(sub.drawdown_risk_score if sub else 50),
            "lower_lows": bool(getattr(ind, "lower_lows", False) if ind else False),
            "higher_highs": bool(getattr(ind, "higher_highs", False) if ind else False),
            "regime_tag": str(getattr(ind, "regime_tag", "") if ind else ""),
        }
    )
    meta["distribution_context"] = {
        "risk_state": dist_ctx.risk_state,
        "two_grid_target": list(resolve_two_grid_weights(dist_ctx)),
    }
    if context.first_start_buy_only:
        meta["first_start_buy_only"] = True

    ladder_budget = buy_ladder_budget_usdt(portfolio, p, context, profile_name)
    headroom = exposure_headroom_quote_usdt(portfolio, p.max_base_exposure_frac)
    meta["buy_ladder_budget_usdt"] = round(ladder_budget, 4)
    meta["exposure_headroom_quote_usdt"] = round(headroom, 4)
    meta["max_base_exposure_frac"] = round(float(p.max_base_exposure_frac), 6)

    if ladder_budget < min_n and p.buy_grid_count > 0:
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        meta["min_notional_feasible"] = False
        meta["adjusted_buy_grid_count_reason"] = "exposure_headroom_below_min_notional"
        warnings.append("EXPOSURE_HEADROOM_TOO_LOW")
        gates.append(
            SafetyGateResult(
                gate_id="exposure_headroom",
                passed=False,
                action="WAIT",
                reason_code="EXPOSURE_HEADROOM_TOO_LOW",
                message="Exposure headroom min emir tutarının altında; yeni alış kapalı.",
            )
        )

    # Worst-case exposure loop: shrink budget then grid count
    worst = simulate_worst_case_exposure(
        portfolio, p, ladder_budget, context, current_price
    )
    meta["worst_case_base_exposure_frac"] = round(worst, 6)
    max_exp = float(p.max_base_exposure_frac)

    while worst > max_exp + tol and p.buy_grid_count > 0:
        meta["exposure_gate_adjusted"] = True
        meta["exposure_adjustment_reason"] = "worst_case_exposure_exceeded"
        if ladder_budget > min_n:
            ladder_budget *= 0.85
            meta["buy_ladder_budget_usdt"] = round(ladder_budget, 4)
        elif p.buy_grid_count > 1:
            p.buy_grid_count -= 1
            p.buy_qty_distribution = _finalize_buy_distribution(
                distribute_weights(p.buy_grid_count, C.MAX_SINGLE_LEVEL_WEIGHT),
                defensive=defensive,
            )
            meta["min_notional_adjusted"] = True
            meta["adjusted_buy_grid_count_reason"] = (
                f"worst_case_exposure_grid_reduced_to_{p.buy_grid_count}"
            )
        else:
            p.emergency_no_buy = True
            p.buy_grid_count = 0
            p.buy_qty_distribution = []
            ladder_budget = 0.0
            meta["buy_ladder_budget_usdt"] = 0.0
            break
        worst = simulate_worst_case_exposure(
            portfolio, p, ladder_budget, context, current_price
        )
        meta["worst_case_base_exposure_frac"] = round(worst, 6)

    if meta.get("exposure_gate_adjusted"):
        warnings.append("EXPOSURE_LADDER_CAPPED")
        gates.append(
            SafetyGateResult(
                gate_id="worst_case_exposure",
                passed=False,
                action="ADJUST",
                reason_code="BUY_LADDER_CAPPED",
                message="Alış grid bütçesi worst-case exposure headroom ile sınırlandı.",
                adjustments={"buy_ladder_budget_usdt": meta["buy_ladder_budget_usdt"]},
            )
        )

    buy_budget = ladder_budget if p.buy_grid_count > 0 else 0.0
    if p.buy_grid_count > 0 and buy_budget >= min_n:
        new_n, new_w, ok = _reduce_grid_until_feasible(
            p.buy_grid_count,
            p.buy_qty_distribution,
            buy_budget,
            min_n,
            C.MAX_SINGLE_LEVEL_WEIGHT,
            defensive=defensive,
        )
        if not ok or new_n <= 0:
            p.emergency_no_buy = True
            p.buy_grid_count = 0
            p.buy_qty_distribution = []
            meta["min_notional_feasible"] = False
            meta["adjusted_buy_grid_count_reason"] = "buy_min_notional_infeasible"
            warnings.append("BUY_GRID_MIN_NOTIONAL_FAIL")
            gates.append(
                SafetyGateResult(
                    gate_id="min_notional_buy",
                    passed=False,
                    action="WAIT",
                    reason_code="MIN_NOTIONAL_BUY_FAIL",
                    message="Alış grid min notional altında; yeni alış kapalı.",
                )
            )
        elif new_n != p.buy_grid_count:
            p.buy_grid_count = new_n
            p.buy_qty_distribution = new_w
            meta["min_notional_adjusted"] = True
            meta["adjusted_buy_grid_count_reason"] = f"buy_grid_reduced_to_{new_n}"
            gates.append(
                SafetyGateResult(
                    gate_id="min_notional_buy",
                    passed=False,
                    action="ADJUST",
                    reason_code="BUY_GRID_REDUCED",
                    message=f"Alış grid {new_n} kademeye düşürüldü (min notional).",
                    adjustments={"buy_grid_count": new_n},
                )
            )
        elif p.buy_qty_distribution:
            p.buy_qty_distribution = _finalize_buy_distribution(
                p.buy_qty_distribution,
                defensive=defensive,
            )

    # Sell grid: use real base for sell-only; theoretical allocation only for initial entry
    sell_only = (
        final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        or getattr(p, "sell_only_mode", False)
    )
    sell_budget = float(portfolio.base_value_usdt or 0.0)
    if sell_only:
        if sell_budget < min_n:
            if p.sell_grid_count > 0:
                p.sell_grid_count = 0
                p.sell_qty_distribution = []
                meta["adjusted_sell_grid_count_reason"] = "sell_only_no_sellable_base"
                meta["min_notional_feasible"] = False
                warnings.append("SELL_ONLY_NO_BASE_DOWNGRADE")
        sell_budget = max(sell_budget, 0.0)
    elif context.is_first_start and sell_budget <= 0:
        sell_budget = equity * float(p.base_alloc_frac)
    else:
        sell_budget = max(float(portfolio.base_value_usdt or 0.0), 0.0)
    sell_budget = min(sell_budget, equity * float(p.max_base_exposure_frac))

    if p.sell_grid_count > 0 and sell_budget > 0:
        new_n, new_w, ok = _reduce_grid_until_feasible(
            p.sell_grid_count,
            p.sell_qty_distribution,
            sell_budget,
            min_n,
            C.MAX_SINGLE_LEVEL_WEIGHT,
        )
        if not ok or new_n <= 0:
            p.sell_grid_count = 0
            p.sell_qty_distribution = []
            warnings.append("SELL_GRID_MIN_NOTIONAL_FAIL")
            meta["adjusted_sell_grid_count_reason"] = "sell_min_notional_infeasible"
            meta["min_notional_feasible"] = False
        elif new_n != p.sell_grid_count:
            p.sell_grid_count = new_n
            p.sell_qty_distribution = new_w
            meta["min_notional_adjusted"] = True
            meta["adjusted_sell_grid_count_reason"] = f"sell_grid_reduced_to_{new_n}"
            gates.append(
                SafetyGateResult(
                    gate_id="min_notional_sell",
                    passed=False,
                    action="ADJUST",
                    reason_code="SELL_GRID_REDUCED",
                    message=f"Satış grid {new_n} kademeye düşürüldü (min notional).",
                    adjustments={"sell_grid_count": new_n},
                )
            )
    elif p.sell_grid_count > 0 and sell_budget < min_n:
        p.sell_grid_count = 0
        p.sell_qty_distribution = []
        meta["adjusted_sell_grid_count_reason"] = "sell_base_below_min_notional"
        warnings.append("SELL_GRID_DISABLED")

    meta.setdefault("min_notional_feasible", True)
    meta["fee_floor_pct"] = round(min_grid_spacing_pct(constraints), 4)
    meta["total_friction_pct"] = round(total_friction_pct(constraints), 4)
    meta["min_grid_spacing_pct"] = meta["fee_floor_pct"]
    meta["min_trailing_callback_pct"] = round(min_trailing_pct(constraints), 4)
    meta["min_notional"] = min_n
    p, meta = _enforce_bilateral_grid_minimum(
        p,
        portfolio,
        constraints,
        context,
        profile_name,
        ladder_budget,
        min_n,
        gates,
        warnings,
        meta,
    )
    ladder_budget = float(meta.get("buy_ladder_budget_usdt") or ladder_budget)
    p, ladder_budget, meta = _enforce_worst_case_hard_cap(
        p,
        portfolio,
        context,
        ladder_budget,
        min_n,
        current_price,
        meta,
        gates,
        warnings,
        tol,
        defensive=defensive,
    )
    p, meta = _finalize_post_grid_safety(
        p,
        portfolio,
        context,
        ladder_budget,
        min_n,
        current_price,
        meta,
        gates,
        warnings,
        tol,
        defensive=defensive,
        dist_ctx=dist_ctx,
    )
    return p, meta


def _finalize_post_grid_safety(
    params: BotParams,
    portfolio: PortfolioState,
    context: BotContext,
    ladder_budget: float,
    min_n: float,
    current_price: Optional[float],
    meta: Dict[str, Any],
    gates: List[SafetyGateResult],
    warnings: List[str],
    tol: float,
    *,
    defensive: bool,
    dist_ctx: Optional["DistributionContext"] = None,
) -> Tuple[BotParams, Dict[str, Any]]:
    """After final grid counts: normalize distributions, verify worst-case, block deploy if unsafe."""
    from app.services.dynamic_param_score.distribution_policy import (
        DistributionContext,
        is_buy_distribution_valid,
        normalize_distribution_for_context,
    )

    ctx = dist_ctx or DistributionContext(
        risk_state="DEFENSIVE" if defensive else "NORMAL"
    )

    p = params
    buy_n = int(p.buy_grid_count or 0)
    if buy_n > 0 and p.buy_qty_distribution:
        pct = [max(1, int(round(float(w) * 100))) for w in p.buy_qty_distribution[:buy_n]]
        fixed, _ = normalize_distribution_for_context(pct, buy_n, ctx)
        p.buy_qty_distribution = [round(x / 100.0, 6) for x in fixed]
        valid, reason = is_buy_distribution_valid(fixed, grid_count=buy_n, ctx=ctx)
        if not valid:
            meta["distribution_invalid"] = True
            meta["deploy_blocked_reason"] = reason or "INVALID_DISTRIBUTION"
            warnings.append("DEFENSIVE_DISTRIBUTION_INVALID")

    sell_n = int(p.sell_grid_count or 0)
    if sell_n > 0 and p.sell_qty_distribution:
        pct = [max(1, int(round(float(w) * 100))) for w in p.sell_qty_distribution[:sell_n]]
        fixed, _ = normalize_distribution_for_context(pct, sell_n, ctx)
        p.sell_qty_distribution = [round(x / 100.0, 6) for x in fixed]

    budget = float(ladder_budget or 0.0)
    max_exp = float(p.max_base_exposure_frac or 0.72)
    worst = simulate_worst_case_exposure(
        portfolio, p, budget, context, current_price
    )
    meta["worst_case_base_exposure_frac"] = round(worst, 6)

    if worst > max_exp + tol and buy_n > 0:
        meta["exposure_hard_cap_breach"] = True
        meta["deploy_blocked_reason"] = "EXPOSURE_HARD_CAP_BREACH"
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        budget = 0.0
        meta["buy_ladder_budget_usdt"] = 0.0
        warnings.append("EXPOSURE_HARD_CAP_BREACH")
        gates.append(
            SafetyGateResult(
                gate_id="worst_case_exposure_hard",
                passed=False,
                action="WAIT",
                reason_code="EXPOSURE_HARD_CAP_BREACH",
                message="Worst-case maruziyet max exposure üstünde; yeni alış engellendi.",
            )
        )
        worst = simulate_worst_case_exposure(
            portfolio, p, budget, context, current_price
        )
        meta["worst_case_base_exposure_frac"] = round(worst, 6)

    if (
        buy_n == 1
        and "SINGLE_LEVEL_TOO_LARGE" in warnings
        and worst > max_exp + tol
    ):
        meta["deploy_blocked_reason"] = "SINGLE_LEVEL_TOO_LARGE_EXPOSURE"
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []

    meta["distribution_valid"] = not meta.get("distribution_invalid", False)
    return p, meta


def _enforce_worst_case_hard_cap(
    params: BotParams,
    portfolio: PortfolioState,
    context: BotContext,
    ladder_budget: float,
    min_n: float,
    current_price: Optional[float],
    meta: Dict[str, Any],
    gates: List[SafetyGateResult],
    warnings: List[str],
    tol: float,
    *,
    defensive: bool,
) -> Tuple[BotParams, float, Dict[str, Any]]:
    """Hard invariant: worst_case_base_exposure_frac must not exceed max_base_exposure_frac."""
    p = params
    max_exp = float(p.max_base_exposure_frac or 0.72)
    budget = float(ladder_budget or 0.0)
    worst = simulate_worst_case_exposure(
        portfolio, p, budget, context, current_price
    )
    meta["worst_case_base_exposure_frac"] = round(worst, 6)
    attempts = 0
    while worst > max_exp + tol and int(p.buy_grid_count or 0) > 0 and attempts < 14:
        attempts += 1
        meta["exposure_hard_cap_enforced"] = True
        meta["exposure_adjustment_reason"] = "worst_case_hard_cap"
        mq = float(p.max_quote_to_spend_per_buy_frac or 0.30)
        if mq > 0.10:
            p.max_quote_to_spend_per_buy_frac = round(mq * 0.82, 4)
        elif budget > min_n:
            budget *= 0.82
            meta["buy_ladder_budget_usdt"] = round(budget, 4)
        elif int(p.buy_grid_count or 0) > 1:
            p.buy_grid_count = int(p.buy_grid_count) - 1
            p.buy_qty_distribution = _finalize_buy_distribution(
                distribute_weights(p.buy_grid_count, C.MAX_SINGLE_LEVEL_WEIGHT),
                defensive=defensive,
            )
            meta["adjusted_buy_grid_count_reason"] = (
                f"exposure_hard_cap_grid_{p.buy_grid_count}"
            )
        else:
            p.emergency_no_buy = True
            p.buy_grid_count = 0
            p.buy_qty_distribution = []
            budget = 0.0
            meta["buy_ladder_budget_usdt"] = 0.0
            break
        worst = simulate_worst_case_exposure(
            portfolio, p, budget, context, current_price
        )
        meta["worst_case_base_exposure_frac"] = round(worst, 6)
    if worst > max_exp + tol and int(p.buy_grid_count or 0) > 0:
        meta["exposure_hard_cap_breach"] = True
        meta["deploy_blocked_reason"] = "EXPOSURE_HARD_CAP_BREACH"
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        budget = 0.0
        meta["buy_ladder_budget_usdt"] = 0.0
        warnings.append("EXPOSURE_HARD_CAP_BREACH")
        gates.append(
            SafetyGateResult(
                gate_id="worst_case_exposure_hard",
                passed=False,
                action="WAIT",
                reason_code="EXPOSURE_HARD_CAP_BREACH",
                message="Worst-case maruziyet limiti aşıldı; yeni alış kapatıldı.",
            )
        )
    return p, budget, meta


def _enforce_bilateral_grid_minimum(
    params: BotParams,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    context: BotContext,
    profile_name: str,
    ladder_budget: float,
    min_n: float,
    gates: List[SafetyGateResult],
    warnings: List[str],
    meta: Dict[str, Any],
) -> Tuple[BotParams, Dict[str, Any]]:
    """Grid modes require both sides; SELL_MANAGEMENT_ONLY allows sell-only deploy."""
    p = params
    min_dep = int(C.MIN_GRID_COUNT_DEPLOYABLE)
    min_each = int(C.MIN_GRID_COUNT_EACH_SIDE)
    equity = max(float(portfolio.total_equity_usdt or 0.0), 0.0)

    buy_ok = int(p.buy_grid_count or 0) >= min_dep
    sell_ok = int(p.sell_grid_count or 0) >= min_dep

    if meta.get("exposure_hard_cap_breach") or meta.get("deploy_blocked_reason"):
        meta["bilateral_grid_ok"] = False
        meta["sell_management_only"] = sell_ok and not buy_ok
        if sell_ok and not buy_ok:
            return p, meta

    if not buy_ok:
        lb = max(float(ladder_budget or 0.0), 0.0)
        if lb < min_n:
            lb = buy_ladder_budget_usdt(portfolio, p, context, profile_name)
        min_dep = int(C.MIN_GRID_COUNT_DEPLOYABLE)
        if lb >= min_n * min_dep:
            p.buy_grid_count = min_dep
            p.buy_qty_distribution = distribute_weights(min_dep, C.MAX_SINGLE_LEVEL_WEIGHT)
            p.emergency_no_buy = False
            meta["buy_ladder_budget_usdt"] = round(lb, 4)
            buy_ok = int(p.buy_grid_count or 0) >= min_dep
        elif lb >= min_n:
            p.buy_grid_count = 1
            p.buy_qty_distribution = distribute_weights(1, C.MAX_SINGLE_LEVEL_WEIGHT)
            p.emergency_no_buy = False
            meta["buy_ladder_budget_usdt"] = round(lb, 4)
            meta["single_probe_only"] = True
            meta["deploy_blocked_reason"] = "SINGLE_PROBE_ONLY"
            buy_ok = False

    if not sell_ok:
        sell_budget = float(portfolio.base_value_usdt or 0.0)
        if context.is_first_start and sell_budget <= 0:
            if context.first_start_buy_only and int(p.buy_grid_count or 0) >= 1:
                meta["first_start_buy_only"] = True
                meta["bilateral_grid_ok"] = False
                meta["sell_management_only"] = False
                meta["min_notional_feasible"] = True
                meta.pop("deploy_blocked_reason", None)
                meta.pop("single_probe_only", None)
                warnings.append("FIRST_START_BUY_ONLY")
                return p, meta
            meta["deploy_blocked_reason"] = "NO_SELLABLE_BASE"
            warnings.append("NO_SELLABLE_BASE")
            sell_ok = False
        else:
            if sell_budget <= 0:
                sell_budget = max(sell_budget, equity * float(p.base_alloc_frac) * 0.5)
            sell_budget = min(sell_budget, equity * float(p.max_base_exposure_frac))
            min_dep = int(C.MIN_GRID_COUNT_DEPLOYABLE)
            new_n, new_w, ok = _reduce_grid_until_feasible(
                min_dep,
                p.sell_qty_distribution or [1.0],
                sell_budget,
                min_n,
                C.MAX_SINGLE_LEVEL_WEIGHT,
            )
            if ok and new_n >= min_dep:
                p.sell_grid_count = new_n
                p.sell_qty_distribution = new_w
                sell_ok = True

    if buy_ok and sell_ok:
        meta["bilateral_grid_ok"] = True
        meta["sell_management_only"] = False
        return p, meta

    # Sell-management-only: buy side closed/infeasible but sell grids remain valid.
    if not buy_ok and sell_ok:
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        p.emergency_no_buy = True
        meta["bilateral_grid_ok"] = False
        meta["sell_management_only"] = True
        meta["min_notional_feasible"] = True
        warnings.append("SELL_MANAGEMENT_ONLY")
        gates.append(
            SafetyGateResult(
                gate_id="sell_management_only",
                passed=True,
                action="ALLOW",
                reason_code="SELL_MANAGEMENT_ONLY",
                message="Yeni alış grid'i güvenlik nedeniyle kapatıldı; mevcut base için satış yönetimi bırakıldı.",
            )
        )
        return p, meta

    meta["bilateral_grid_ok"] = False
    meta["sell_management_only"] = False
    meta["min_notional_feasible"] = False
    meta["adjusted_grid_count_reason"] = "bilateral_grid_required"
    p.emergency_no_buy = True
    p.buy_grid_count = 0
    p.sell_grid_count = 0
    p.buy_qty_distribution = []
    p.sell_qty_distribution = []
    warnings.append("GRID_BOTH_SIDES_REQUIRED")
    gates.append(
        SafetyGateResult(
            gate_id="bilateral_grid",
            passed=False,
            action="WAIT",
            reason_code="BILATERAL_GRID_REQUIRED",
            message="Alış ve satış gridlerinin her ikisinde de en az bir kademe gerekli; "
            "tek taraf sıfır bırakılamaz.",
        )
    )
    return p, meta


def apply_spacing_and_trailing_floors(
    params: BotParams,
    constraints: ExchangeConstraints,
    spread_pct: Optional[float],
    gates: List[SafetyGateResult],
) -> BotParams:
    p = params
    min_sp = min_grid_spacing_pct(constraints, spread_pct)
    min_tr = min_trailing_pct(constraints, spread_pct)
    changed = False
    if p.buy_grid_spacing_pct < min_sp - 1e-6:
        p.buy_grid_spacing_pct = min_sp
        changed = True
    if p.sell_grid_spacing_pct < min_sp - 1e-6:
        p.sell_grid_spacing_pct = min_sp
        changed = True
    trail = max(p.trailing_callback_pct or 0.0, min_tr)
    if not p.trailing_enabled:
        trail = max(trail, min_tr)
    if trail > (p.trailing_callback_pct or 0.0) + 1e-6:
        p.trailing_callback_pct = round(trail, 4)
        changed = True
    if (p.trailing_callback_pct or 0.0) < min_tr - 1e-6:
        p.trailing_callback_pct = round(min_tr, 4)
        changed = True
    if changed:
        gates.append(
            SafetyGateResult(
                gate_id="friction_floor",
                passed=True,
                action="ADJUST",
                reason_code="FRICTION_FLOOR_APPLIED",
                message="Grid aralığı ve trailing fee/spread tabanına yükseltildi.",
                adjustments={
                    "buy_grid_spacing_pct": p.buy_grid_spacing_pct,
                    "sell_grid_spacing_pct": p.sell_grid_spacing_pct,
                    "trailing_callback_pct": p.trailing_callback_pct,
                    "spacing_adjusted": True,
                },
            )
        )
    return p
