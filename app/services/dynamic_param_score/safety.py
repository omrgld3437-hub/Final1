"""Hard safety gates for Dynamic Param Score Engine."""

from __future__ import annotations

import copy
from typing import List, Optional, Tuple

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.feasibility import (
    apply_exposure_and_notional_feasibility,
    apply_spacing_and_trailing_floors,
    has_sellable_base_feasible,
    min_grid_spacing_pct,
    total_friction_pct,
)
from app.services.dynamic_param_score.models import (
    BotContext,
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    SafetyGateResult,
    SubScores,
)
from app.services.dynamic_param_score.action_detail import (
    build_action_detail,
    is_deployable,
    is_sell_management_only,
    resolve_post_safety_action,
)


def _gate(
    gate_id: str,
    passed: bool,
    action: str,
    reason_code: str,
    message: str,
    adjustments: Optional[dict] = None,
) -> SafetyGateResult:
    return SafetyGateResult(
        gate_id=gate_id,
        passed=passed,
        action=action,
        reason_code=reason_code,
        message=message,
        adjustments=adjustments or {},
    )


def apply_safety_gates(
    params: Optional[BotParams],
    sub: SubScores,
    regime: RegimeTag,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    context: BotContext,
    param_score: int,
    final_action: str,
    ind: Optional[IndicatorSnapshot] = None,
    profile_name: str = "",
    current_price: Optional[float] = None,
    risk_state: str = "",
) -> Tuple[
    Optional[BotParams],
    str,
    bool,
    List[SafetyGateResult],
    List[str],
    List[str],
    dict,
]:
    """Return (params, final_action, deployable, gates, blocking, warnings, feasibility_meta)."""
    gates: List[SafetyGateResult] = []
    blocking: List[str] = []
    warnings: List[str] = []
    feasibility_meta: dict = {}
    action = final_action
    spread_pct = float(getattr(ind, "orderbook_spread_pct", 0.0) or 0.0) if ind else 0.0

    if sub.data_quality_score < C.DATA_QUALITY_BLOCKED:
        gates.append(
            _gate("data", False, "BLOCK", "DATA_QUALITY_LOW", "Veri kalitesi yetersiz.")
        )
        blocking.append("DATA_QUALITY_LOW")
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if sub.liquidity_score < C.LIQUIDITY_BLOCKED:
        gates.append(
            _gate("liquidity", False, "NO_TRADE", "LIQUIDITY_LOW", "Likidite çok düşük.")
        )
        blocking.append("LIQUIDITY_LOW")
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if sub.spread_score < C.SPREAD_BLOCKED:
        gates.append(
            _gate("spread", False, "NO_TRADE", "SPREAD_HIGH", "Spread çok yüksek.")
        )
        blocking.append("SPREAD_HIGH")
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if params is None:
        if context.allow_no_trade:
            return None, action, False, gates, blocking, warnings, feasibility_meta
        blocking.append("NO_PARAMS")
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    p = copy.deepcopy(params)

    # Fee / friction spacing floor
    friction = total_friction_pct(constraints, spread_pct)
    required_min = min_grid_spacing_pct(constraints, spread_pct)
    spacing_eps = 1e-6
    if p.buy_grid_spacing_pct < required_min - spacing_eps:
        p.buy_grid_spacing_pct = required_min
        p.sell_grid_spacing_pct = max(p.sell_grid_spacing_pct, required_min * 0.85)
        gates.append(
            _gate(
                "fee_efficiency",
                True,
                "ADJUST",
                "SPACING_INCREASED",
                "Grid aralığı fee+slippage için artırıldı.",
                {
                    "buy_grid_spacing_pct": p.buy_grid_spacing_pct,
                    "sell_grid_spacing_pct": p.sell_grid_spacing_pct,
                },
            )
        )

    p = apply_spacing_and_trailing_floors(p, constraints, spread_pct, gates)

    if (
        sub.fee_efficiency_score < C.FEE_EFF_CAUTIOUS
        and action == FinalAction.ACTIVE_GRID.value
    ):
        action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        p.buy_grid_spacing_pct = max(p.buy_grid_spacing_pct, required_min * 1.15)
        p.sell_grid_spacing_pct = max(p.sell_grid_spacing_pct, required_min * 1.15)
        if p.buy_grid_count > 2:
            p.buy_grid_count = max(2, p.buy_grid_count - 1)
        if p.sell_grid_count > 2:
            p.sell_grid_count = max(2, p.sell_grid_count - 1)
        gates.append(
            _gate(
                "fee_efficiency",
                True,
                "ADJUST",
                "FEE_BAD_WIDEN_GRID",
                "Fee verimi düşük; grid genişletildi, ACTIVE_DEFENSIVE_GRID seçildi.",
                {
                    "buy_grid_spacing_pct": p.buy_grid_spacing_pct,
                    "sell_grid_spacing_pct": p.sell_grid_spacing_pct,
                },
            )
        )
        warnings.append("FEE_BAD_ACTIVE_DEFENSIVE")

    # Exposure headroom + min-notional feasibility (buy ladder ≠ full quote)
    p, feasibility_meta = apply_exposure_and_notional_feasibility(
        p,
        portfolio,
        constraints,
        context,
        gates,
        warnings,
        profile_name=profile_name,
        current_price=current_price,
        final_action=action,
        risk_state=risk_state,
        sub=sub,
        ind=ind,
    )

    has_sellable, _sellable_val = has_sellable_base_feasible(
        portfolio, constraints, price=current_price
    )

    if is_sell_management_only(p) and not has_sellable:
        p.sell_grid_count = 0
        p.sell_qty_distribution = []
        if int(p.buy_grid_count or 0) > 0:
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
            warnings.append("NO_BASE_BUY_ONLY_ACTIVE")
        else:
            action = FinalAction.WAIT_SAFETY.value
            blocking.append("NO_SELLABLE_BASE")
    elif not feasibility_meta.get("bilateral_grid_ok", True):
        if is_sell_management_only(p) and has_sellable:
            action = FinalAction.SELL_MANAGEMENT_ONLY.value
        elif int(p.buy_grid_count or 0) > 0 and int(p.sell_grid_count or 0) > 0:
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
            warnings.append("ASYMMETRIC_GRID_ACTIVE")
        elif int(p.sell_grid_count or 0) > 0 and has_sellable:
            action = FinalAction.SELL_MANAGEMENT_ONLY.value
        elif int(p.buy_grid_count or 0) > 0 or int(p.sell_grid_count or 0) > 0:
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
            warnings.append("PARTIAL_GRID_ACTIVE")
        else:
            action = FinalAction.WAIT_SAFETY.value
            blocking.append("MIN_NOTIONAL_HARD_FAIL")
    elif feasibility_meta.get("min_notional_feasible") is False:
        if int(p.buy_grid_count or 0) == 0 and int(p.sell_grid_count or 0) == 0:
            action = FinalAction.WAIT_SAFETY.value
            blocking.append("MIN_NOTIONAL_HARD_FAIL")
        elif not is_sell_management_only(p):
            action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
            warnings.append("MIN_NOTIONAL_GRID_COUNT_REDUCED")

    # Exposure at cap — block new buys; keep sell-side if base supports it.
    if portfolio.current_base_exposure_frac >= p.max_base_exposure_frac:
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        gates.append(
            _gate(
                "exposure",
                False,
                "WAIT",
                "EXPOSURE_AT_CAP",
                "Base exposure üst sınırda; yeni alış kapalı.",
            )
        )
        warnings.append("EXPOSURE_AT_CAP")

    if regime == RegimeTag.TRENDING_DOWN:
        p.base_alloc_frac = min(p.base_alloc_frac, C.TRENDING_DOWN_MAX_BASE_ALLOC)
        p.quote_alloc_frac = 1.0 - p.base_alloc_frac
        p.max_base_exposure_frac = min(
            p.max_base_exposure_frac,
            p.base_alloc_frac + C.TRENDING_DOWN_MAX_EXPOSURE_EXTRA,
        )
        p.max_quote_to_spend_per_buy_frac = min(
            p.max_quote_to_spend_per_buy_frac, C.TRENDING_DOWN_MAX_QUOTE_PER_BUY
        )
        p.downtrend_buy_throttle = True
        if action in (FinalAction.ACTIVE_GRID.value, FinalAction.TREND_TRAILING.value):
            action = FinalAction.DEFENSIVE_GRID.value
            gates.append(
                _gate(
                    "downtrend",
                    False,
                    "DEFENSIVE",
                    "DOWNTREND_PROFILE_ONLY",
                    "Düşüş rejiminde agresif profil yasak.",
                )
            )

    if regime == RegimeTag.DUMP_RISK:
        p.cancel_existing_buy_orders = True
        p.emergency_no_buy = True
        p.buy_grid_count = 0
        p.buy_qty_distribution = []
        blocking.append("DUMP_RISK")
        if context.run_source == "param_assistant":
            action = resolve_post_safety_action(p, FinalAction.DEFENSIVE_GRID.value)
            deployable = is_deployable(action, p, feasibility_meta)
            feasibility_meta["fee_floor_pct"] = round(required_min, 4)
            feasibility_meta["total_friction_pct"] = round(friction, 4)
            return p, action, deployable, gates, blocking, warnings, feasibility_meta
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if p.buy_grid_count == 1:
        if p.max_quote_to_spend_per_buy_frac > C.MAX_QUOTE_PER_BUY_FRAC:
            p.max_quote_to_spend_per_buy_frac = C.MAX_QUOTE_PER_BUY_FRAC
            gates.append(
                _gate(
                    "single_buy",
                    False,
                    "ADJUST",
                    "SINGLE_BUY_CAPPED",
                    "Tek seviye alış kotası sınırlandı.",
                )
            )
        if regime == RegimeTag.TRENDING_DOWN:
            p.buy_grid_count = 2
            from app.services.dynamic_param_score.utils import distribute_weights

            p.buy_qty_distribution = distribute_weights(2, 0.20)
            gates.append(
                _gate(
                    "single_buy",
                    False,
                    "ADJUST",
                    "DOWNTREND_MULTI_BUY",
                    "Düşüşte tek alış yasak; 2 kademeye bölündü.",
                )
            )

    for i, w in enumerate(p.buy_qty_distribution):
        if w > C.MAX_QUOTE_PER_BUY_FRAC:
            from app.services.dynamic_param_score.utils import distribute_weights

            p.buy_qty_distribution = distribute_weights(
                p.buy_grid_count, C.MAX_SINGLE_LEVEL_WEIGHT
            )
            gates.append(
                _gate(
                    "single_buy",
                    False,
                    "ADJUST",
                    "SINGLE_LEVEL_CAPPED",
                    "Tek seviye kotası sınırlandı; grid yeniden dağıtıldı.",
                )
            )
            warnings.append("SINGLE_LEVEL_TOO_LARGE")
            break

    if portfolio.total_equity_usdt < constraints.min_notional * 2:
        blocking.append("BUDGET_TOO_SMALL")
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if portfolio.open_buy_orders_count >= 5 and p.buy_grid_count > 2:
        p.buy_grid_count = max(2, p.buy_grid_count - 2)
        from app.services.dynamic_param_score.utils import distribute_weights

        p.buy_qty_distribution = distribute_weights(
            p.buy_grid_count, C.MAX_SINGLE_LEVEL_WEIGHT
        )
        warnings.append("OPEN_BUY_ORDERS_STACK_LIMIT")
        gates.append(
            _gate(
                "open_orders",
                True,
                "ADJUST",
                "BUY_GRID_TRIMMED",
                "Mevcut açık alış emirleri nedeniyle yeni grid azaltıldı.",
            )
        )

    if param_score < 15:
        blocking.append("PARAM_SCORE_TOO_LOW")
        if context.run_source == "param_assistant" and p is not None:
            action = resolve_post_safety_action(p, FinalAction.DEFENSIVE_GRID.value)
            deployable = is_deployable(action, p, feasibility_meta)
            feasibility_meta["fee_floor_pct"] = round(required_min, 4)
            feasibility_meta["total_friction_pct"] = round(friction, 4)
            return p, action, deployable, gates, blocking, warnings, feasibility_meta
        return None, FinalAction.NO_TRADE.value, False, gates, blocking, warnings, feasibility_meta

    if feasibility_meta.get("exposure_hard_cap_breach") or feasibility_meta.get(
        "deploy_blocked_reason"
    ):
        if is_sell_management_only(p) and has_sellable_base_feasible(
            portfolio, constraints, price=current_price
        )[0]:
            action = FinalAction.SELL_MANAGEMENT_ONLY.value
        else:
            action = FinalAction.WAIT_SAFETY.value
            blocking.append(
                str(
                    feasibility_meta.get("deploy_blocked_reason")
                    or "EXPOSURE_HARD_CAP_BREACH"
                )
            )

    action = resolve_post_safety_action(p, action, blocking=bool(blocking))
    deployable = is_deployable(action, p, feasibility_meta)

    feasibility_meta["fee_floor_pct"] = round(required_min, 4)
    feasibility_meta["total_friction_pct"] = round(friction, 4)
    feasibility_meta["execution_exposure_cap_enabled"] = True
    feasibility_meta["live_parity_ok"] = True
    gates.append(_gate("live_parity", True, "PASS", "LIVE_PARITY_OK", "Güvenlik kapıları tamamlandı."))
    return p, action, deployable, gates, blocking, warnings, feasibility_meta
