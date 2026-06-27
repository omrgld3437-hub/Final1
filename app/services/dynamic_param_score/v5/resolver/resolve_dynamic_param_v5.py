"""V5 resolver chain — shelf template to final param."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List

from app.services.dynamic_param_score.v5.domain.math_utils import (
    clamp,
    is_approx_100,
    normalize_distribution,
    round2,
    round4,
)
from app.services.dynamic_param_score.v5.domain.route_key import make_route_key
from app.services.dynamic_param_score.v5.domain.types import (
    V5ResolveInput,
    V5ResolvedParam,
    V5ResolveTrace,
    V5Shelf,
)
from app.services.dynamic_param_score.v5.generator.grid_factory import make_distribution
from app.services.dynamic_param_score.v5.index.route_lookup import V5RouteIndex, lookup_exact_v5_shelf
from app.services.dynamic_param_score.v5.resolver.fallback_resolver_v5 import resolve_safe_fallback_v5


def materialize_base_template(
    shelf: V5Shelf,
    input_data: V5ResolveInput,
    selection_type: str,
) -> V5ResolvedParam:
    t = shelf.base_template
    return V5ResolvedParam(
        version="DPLV5",
        selection_type=selection_type,  # type: ignore[arg-type]
        shelf_id=shelf.shelf_id,
        route_key=shelf.route_key,
        final_grid_count=t.preferred_grid_count,
        sell_grid_levels_pct=list(t.sell_grid_levels_pct),
        buy_grid_levels_pct=list(t.buy_grid_levels_pct),
        sell_distribution_pct=list(t.sell_distribution_pct),
        buy_distribution_pct=list(t.buy_distribution_pct),
        target_base_pct=t.target_base_pct,
        target_quote_pct=t.target_quote_pct,
        max_base_exposure_pct=t.max_base_exposure_pct,
        active_buy_ladder_budget_usdt=round2(
            input_data.budget_usdt * t.active_buy_ladder_max_budget_pct / 100
        ),
        sell_trailing_pct=t.sell_trailing_pct,
        buy_trailing_pct=t.buy_trailing_pct,
        take_profit_buy_trigger_pct=t.take_profit_buy_trigger_pct,
        take_profit_buy_trailing_pct=t.take_profit_buy_trailing_pct,
        take_profit_sell_trigger_pct=t.take_profit_sell_trigger_pct,
        take_profit_sell_trailing_pct=t.take_profit_sell_trailing_pct,
        cost_floor_pct=t.assumed_cost_floor_pct,
        min_profit_after_cost_floor_pct=t.min_profit_after_cost_floor_pct,
        confidence=0.85,
        trace=V5ResolveTrace(
            exact_route_hit=selection_type == "EXACT_V5",
            fallback_used=selection_type != "EXACT_V5",
        ),
    )


def resize_grid_count_preserving_intent(
    param: V5ResolvedParam,
    desired_count: int,
    route_parts,
) -> V5ResolvedParam:
    if desired_count == param.final_grid_count:
        return param
    ctx = {
        "regime": route_parts.regime,
        "structure": route_parts.structure,
        "risk": route_parts.risk,
        "volatility": route_parts.volatility,
        "liquidity": route_parts.liquidity,
    }
    sell_dist = normalize_distribution(make_distribution(desired_count, "balanced", ctx))
    buy_dist = normalize_distribution(make_distribution(desired_count, "deep", ctx))
    ratio_s = param.sell_grid_levels_pct[-1] / param.sell_grid_levels_pct[0]
    ratio_b = param.buy_grid_levels_pct[-1] / param.buy_grid_levels_pct[0]
    sell_levels = [round2(param.sell_grid_levels_pct[0] * (ratio_s ** (i / max(desired_count - 1, 1)))) for i in range(desired_count)]
    buy_levels = [round2(param.buy_grid_levels_pct[0] * (ratio_b ** (i / max(desired_count - 1, 1)))) for i in range(desired_count)]
    return V5ResolvedParam(
        **{
            **param.__dict__,
            "final_grid_count": desired_count,
            "sell_grid_levels_pct": sell_levels,
            "buy_grid_levels_pct": buy_levels,
            "sell_distribution_pct": sell_dist,
            "buy_distribution_pct": buy_dist,
        }
    )


def apply_budget_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.budget_adjustments)
    desired = param.final_grid_count
    affordable = int(max(0, input_data.budget_usdt * 0.9) / max(input_data.min_notional_usdt, 0.01))
    if affordable < desired * 2:
        desired = max(2, affordable // 2)
        trace.append(f"Grid count reduced by min-notional to {desired}")
    if input_data.budget_usdt < 150:
        desired = min(desired, 2)
        trace.append("Grid count capped to 2 for small budget")
    if input_data.budget_usdt >= 3000 and input_data.route_parts.liquidity == "L1_HIGH_LIQUIDITY_LOW_COST":
        desired = min(4, max(desired, 3))
        trace.append("Grid count allowed up to 4 for strong budget/liquidity")
    if desired != param.final_grid_count:
        param = resize_grid_count_preserving_intent(param, desired, input_data.route_parts)
    active_buy = round2(input_data.budget_usdt * param.max_base_exposure_pct / 100 * 0.35)
    param.active_buy_ladder_budget_usdt = active_buy
    param.trace.budget_adjustments = trace
    return param


def apply_position_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.position_adjustments)
    base_diff = input_data.current_base_pct - param.target_base_pct
    if base_diff > 8:
        reduction = round2(min(base_diff * 0.3, param.active_buy_ladder_budget_usdt * 0.4))
        param.active_buy_ladder_budget_usdt = max(0, round2(param.active_buy_ladder_budget_usdt - reduction))
        trace.append(f"Reduced buy ladder: base overweight by {base_diff:.1f}%")
    elif base_diff < -8 and input_data.route_parts.regime not in ("R8_CRASH", "R9_STRONG_DOWNTREND"):
        trace.append("Quote overweight — controlled buy ladder maintained")
    param.trace.position_adjustments = trace
    return param


def apply_momentum_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.momentum_adjustments)
    ind = input_data.indicators
    rsi = ind.get("rsi1h", 50)
    bb_pos = ind.get("bb_position", 0.5)
    if rsi > 75 or bb_pos > 0.92:
        param.max_base_exposure_pct = round2(param.max_base_exposure_pct * 0.92)
        trace.append("Overbought momentum — exposure clamped")
    if rsi < 30 and input_data.route_parts.regime not in ("R8_CRASH", "R10_LOWER_LOWS_DOWNTREND"):
        trace.append("Oversold — buy ladder intent preserved with crash guard")
    if ind.get("crash_velocity", 0) > 0.5:
        param.active_buy_ladder_budget_usdt = round2(param.active_buy_ladder_budget_usdt * 0.5)
        trace.append("High crash velocity — buy ladder halved")
    param.trace.momentum_adjustments = trace
    return param


def apply_data_quality_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.data_quality_adjustments)
    dq = input_data.data_quality
    if dq.get("freshness_sec", 0) > 120:
        param.confidence = round2(param.confidence * 0.85)
        trace.append("Stale data — confidence reduced")
    if dq.get("candle_count5m", 100) < 20:
        param.max_base_exposure_pct = round2(param.max_base_exposure_pct * 0.88)
        trace.append("Insufficient candles — exposure reduced")
    if dq.get("data_gap_sec", 0) > 300:
        param.active_buy_ladder_budget_usdt = round2(param.active_buy_ladder_budget_usdt * 0.7)
        trace.append("Data gap — buy ladder reduced")
    param.trace.data_quality_adjustments = trace
    return param


def apply_execution_cost_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.execution_cost_adjustments)
    roundtrip = round4(input_data.maker_fee_pct + input_data.taker_fee_pct)
    raw_cost = round4(roundtrip + input_data.spread_pct + input_data.slippage_pct + input_data.rounding_pct)
    effective = round2(max(raw_cost, param.cost_floor_pct))
    min_grid = round2(effective + param.min_profit_after_cost_floor_pct)
    sell = list(param.sell_grid_levels_pct)
    buy = list(param.buy_grid_levels_pct)
    if sell[0] < min_grid:
        ratio = min_grid / sell[0]
        sell = [round2(v * ratio) for v in sell]
        trace.append(f"Sell grid widened below cost floor min={min_grid}")
    if buy[0] < min_grid:
        ratio = min_grid / buy[0]
        buy = [round2(v * ratio) for v in buy]
        trace.append(f"Buy grid widened below cost floor min={min_grid}")
    param.sell_grid_levels_pct = sell
    param.buy_grid_levels_pct = buy
    param.cost_floor_pct = effective
    param.trace.execution_cost_adjustments = trace
    return param


def apply_btc_context_resolver_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.btc_context_adjustments)
    btc_crash = input_data.indicators.get("btc_crash_velocity", 0)
    if btc_crash > 0.4 and input_data.route_parts.asset not in ("A1_BTC_CORE", "A2_ETH_CORE"):
        param.max_base_exposure_pct = round2(param.max_base_exposure_pct * 0.85)
        param.confidence = round2(param.confidence * 0.9)
        trace.append("BTC stress — altcoin exposure clamped")
    param.trace.btc_context_adjustments = trace
    return param


def apply_risk_clamp_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.risk_clamp_adjustments)
    rp = input_data.route_parts
    if rp.risk == "K3_AGGRESSIVE" and rp.regime in ("R8_CRASH", "R17_DATA_UNCERTAIN_REGIME"):
        param.max_base_exposure_pct = min(param.max_base_exposure_pct, 45)
        trace.append("Aggressive clamped in crash/uncertain regime")
    if rp.liquidity == "L4_EXECUTION_RISKY":
        param.max_base_exposure_pct = min(param.max_base_exposure_pct, 42)
        param.active_buy_ladder_budget_usdt = round2(param.active_buy_ladder_budget_usdt * 0.6)
        trace.append("Execution risky — minimal safe clamp")
    param.trace.risk_clamp_adjustments = trace
    return param


def make_global_safe_no_action_param(
    param: V5ResolvedParam,
    input_data: V5ResolveInput,
    trace: List[str],
) -> V5ResolvedParam:
    return V5ResolvedParam(
        version="DPLV5",
        selection_type="GLOBAL_SAFE_V5",
        shelf_id=param.shelf_id,
        route_key=param.route_key,
        final_grid_count=0,
        sell_grid_levels_pct=[],
        buy_grid_levels_pct=[],
        sell_distribution_pct=[],
        buy_distribution_pct=[],
        target_base_pct=param.target_base_pct,
        target_quote_pct=param.target_quote_pct,
        max_base_exposure_pct=0,
        active_buy_ladder_budget_usdt=0,
        sell_trailing_pct=0,
        buy_trailing_pct=0,
        take_profit_buy_trigger_pct=0,
        take_profit_buy_trailing_pct=0,
        take_profit_sell_trigger_pct=0,
        take_profit_sell_trailing_pct=0,
        cost_floor_pct=param.cost_floor_pct,
        min_profit_after_cost_floor_pct=param.min_profit_after_cost_floor_pct,
        confidence=0.1,
        trace=V5ResolveTrace(
            exact_route_hit=False,
            fallback_used=True,
            final_validation_adjustments=trace,
        ),
    )


def final_validate_and_clamp_v5(param: V5ResolvedParam, input_data: V5ResolveInput) -> V5ResolvedParam:
    trace = list(param.trace.final_validation_adjustments)
    if not input_data.data_quality.get("price_valid", True):
        return make_global_safe_no_action_param(param, input_data, ["Price invalid: global safe"])
    if param.final_grid_count == 0:
        return param
    if not is_approx_100(param.sell_distribution_pct):
        param.sell_distribution_pct = normalize_distribution(param.sell_distribution_pct)
        trace.append("Sell distribution normalized")
    if not is_approx_100(param.buy_distribution_pct):
        param.buy_distribution_pct = normalize_distribution(param.buy_distribution_pct)
        trace.append("Buy distribution normalized")
    max_sell_tr = round2(param.sell_grid_levels_pct[0] * 0.30)
    if param.sell_trailing_pct > max_sell_tr:
        param.sell_trailing_pct = max_sell_tr
        trace.append("Sell trailing clamped")
    max_buy_tr = round2(param.buy_grid_levels_pct[0] * 0.30)
    if param.buy_trailing_pct > max_buy_tr:
        param.buy_trailing_pct = max_buy_tr
        trace.append("Buy trailing clamped")
    if param.take_profit_sell_trigger_pct <= param.take_profit_sell_trailing_pct:
        param.take_profit_sell_trigger_pct = round2(
            param.take_profit_sell_trailing_pct + param.min_profit_after_cost_floor_pct
        )
        trace.append("Sell TP trigger lifted")
    if param.take_profit_buy_trigger_pct <= param.take_profit_buy_trailing_pct:
        param.take_profit_buy_trigger_pct = round2(
            param.take_profit_buy_trailing_pct + param.min_profit_after_cost_floor_pct
        )
        trace.append("Buy TP trigger lifted")
    if param.target_base_pct > param.max_base_exposure_pct + 0.01:
        param.target_base_pct = round2(param.max_base_exposure_pct)
        param.target_quote_pct = round2(100 - param.max_base_exposure_pct)
        trace.append(f"target_base clamped to max exposure: {param.max_base_exposure_pct}")
    min_n = float(input_data.min_notional_usdt or 10)
    budget = float(input_data.budget_usdt or 0)
    if 0 < param.active_buy_ladder_budget_usdt < min_n:
        old_ladder = param.active_buy_ladder_budget_usdt
        param.active_buy_ladder_budget_usdt = 0
        trace.append(f"Active buys disabled: ladder {old_ladder} < min-notional {min_n}")
    elif param.active_buy_ladder_budget_usdt > 0 and param.buy_distribution_pct:
        total = sum(param.buy_distribution_pct) or 100
        for share in param.buy_distribution_pct:
            if param.active_buy_ladder_budget_usdt * (share / total) < min_n:
                param.active_buy_ladder_budget_usdt = 0
                trace.append("Per-order buy below min-notional — active buys disabled")
                break
    if budget > 0 and param.active_buy_ladder_budget_usdt > 0:
        ladder_frac = (param.active_buy_ladder_budget_usdt / budget) * 100
        worst = round2(max(param.target_base_pct, input_data.current_base_pct) + ladder_frac * 0.85)
        if worst > param.max_base_exposure_pct + 0.01:
            reduce = param.max_base_exposure_pct - max(param.target_base_pct, input_data.current_base_pct)
            if reduce <= 0:
                param.active_buy_ladder_budget_usdt = 0
                trace.append("worst exposure exceeds max — active buys disabled")
            else:
                param.active_buy_ladder_budget_usdt = round2(max(0, (reduce / 0.85) * budget / 100))
                trace.append("active buy ladder reduced to respect max exposure")
    param.trace.final_validation_adjustments = trace
    return param


def resolve_dynamic_param_v5(
    input_data: V5ResolveInput,
    index: V5RouteIndex,
) -> V5ResolvedParam:
    route_key = make_route_key(input_data.route_parts)
    selection_type = "EXACT_V5"
    try:
        shelf = lookup_exact_v5_shelf(index, route_key)
    except KeyError:
        shelf = resolve_safe_fallback_v5(input_data, index)
        selection_type = "SAFE_FALLBACK_V5"

    param = materialize_base_template(shelf, input_data, selection_type)
    param = apply_budget_resolver_v5(param, input_data)
    param = apply_position_resolver_v5(param, input_data)
    param = apply_momentum_resolver_v5(param, input_data)
    param = apply_data_quality_resolver_v5(param, input_data)
    param = apply_execution_cost_resolver_v5(param, input_data)
    param = apply_btc_context_resolver_v5(param, input_data)
    param = apply_risk_clamp_v5(param, input_data)
    param = final_validate_and_clamp_v5(param, input_data)
    return param
