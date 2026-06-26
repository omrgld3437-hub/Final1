"""V4 post-selection resolvers — budget/fee/capacity outside route_key."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BotParams,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
)
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    asset_code_from_name,
    direction_bias_for_structure,
    grid_bias_for_context,
    structure_code_from_name,
)
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    cap_trailing_pct,
    normalize_side_distribution,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    MIN_NET_ROOM,
)
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    resolve_scenario_spec,
    scale_grids,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate


@dataclass
class CapacityResolution:
    budget: float
    base_value: float
    quote_value: float
    buy_grid_capacity: int
    sell_grid_capacity: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CostResolution:
    total_cost_pct: float
    grid_widening_multiplier: float
    fee_tier: str
    maker_fee_pct: float = 0.0
    taker_fee_pct: float = 0.0
    roundtrip_fee_pct: float = 0.0
    spread_pct: float = 0.0
    estimated_slippage_pct: float = 0.0
    rounding_cost_pct: float = 0.02
    cost_floor_pct: float = 0.0
    fee_data_available: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolverContext:
    capacity: CapacityResolution
    cost: CostResolution
    data_quality: str
    safety_hard: bool
    safety_reason: Optional[str] = None
    fallback_generated: bool = False


def _side_budget(budget: float, base_frac: float, quote_frac: float) -> Tuple[float, float]:
    return budget * max(base_frac, 0.0), budget * max(quote_frac, 0.0)


def resolve_capacity(
    *,
    budget: float,
    base_alloc_frac: float,
    quote_alloc_frac: float,
    min_notional: float,
    profile_buy_n: int,
    profile_sell_n: int,
) -> CapacityResolution:
    """Budget is NOT in route_key — grid count capped per side independently."""
    base_val, quote_val = _side_budget(budget, base_alloc_frac, quote_alloc_frac)
    mn = max(float(min_notional or DEFAULT_MIN_NOTIONAL_USDT), 1.0)

    def _cap(side_budget: float, desired: int) -> int:
        if side_budget < mn * 1.5:
            return 0 if desired == 0 else 1
        if side_budget < mn * 3:
            return min(desired, 1)
        if side_budget < mn * 5:
            return min(desired, 2)
        if side_budget < mn * 8:
            return min(desired, 3)
        return min(desired, 4)

    buy_cap = _cap(quote_val, profile_buy_n)
    sell_cap = _cap(base_val, profile_sell_n)
    return CapacityResolution(
        budget=round(budget, 2),
        base_value=round(base_val, 2),
        quote_value=round(quote_val, 2),
        buy_grid_capacity=max(0, buy_cap),
        sell_grid_capacity=max(0, sell_cap),
    )


def resolve_cost(
    *,
    constraints: ExchangeConstraints,
    spread_pct: float,
    fee_efficiency_score: int,
    ind: Optional[IndicatorSnapshot] = None,
) -> CostResolution:
    maker = float(constraints.maker_fee_pct or 0)
    taker = float(constraints.taker_fee_pct or 0)
    slip = float(constraints.estimated_slippage_pct or 0)
    spread = max(float(spread_pct or 0), float(getattr(ind, "orderbook_spread_pct", 0) or 0))
    rounding = 0.02
    buffer = 0.05
    roundtrip = maker + taker
    fee_data_available = roundtrip > 0.001 or spread > 0.001
    if not fee_data_available:
        cost_floor = 1.2
        total = cost_floor
    else:
        cost_floor = max(roundtrip + spread + slip + rounding + buffer, 0.54)
        total = roundtrip / 2.0 + spread + slip + rounding + buffer

    score = int(fee_efficiency_score or 50)
    if score < 30 or spread > 0.12:
        tier = "FEE_BAD"
        widen = 1.30
    elif score < 50 or spread > 0.05:
        tier = "FEE_WEAK"
        widen = 1.12
    else:
        tier = "FEE_OK"
        widen = 1.0

    return CostResolution(
        total_cost_pct=round(total, 4),
        grid_widening_multiplier=widen,
        fee_tier=tier,
        maker_fee_pct=round(maker, 4),
        taker_fee_pct=round(taker, 4),
        roundtrip_fee_pct=round(roundtrip, 4),
        spread_pct=round(spread, 4),
        estimated_slippage_pct=round(slip, 4),
        rounding_cost_pct=rounding,
        cost_floor_pct=round(cost_floor, 4),
        fee_data_available=fee_data_available,
    )


def resolve_data_quality(
    *,
    data_quality_score: int,
    data_freshness_sec: float = 0.0,
    data_gap_sec: float = 0.0,
    price_valid: bool = True,
) -> Tuple[str, float, bool]:
    """Returns (quality_label, widen_multiplier, hard_fail)."""
    if not price_valid or data_gap_sec > 900 or data_freshness_sec > 600:
        return "HARD_FAIL", 1.0, True
    score = int(data_quality_score or 80)
    if score >= 75:
        return "GOOD", 1.0, False
    if score >= 55:
        return "USABLE", 1.08, False
    return "WEAK", 1.12, False


def resolve_safety_hard(
    *,
    ind: IndicatorSnapshot,
    constraints: ExchangeConstraints,
    spread_pct: float,
    data_hard_fail: bool,
    price_valid: bool = True,
) -> Tuple[bool, Optional[str]]:
    if data_hard_fail:
        return True, "data_hard_fail"
    if not price_valid:
        return True, "price_invalid"
    if float(spread_pct or 0) > 0.15:
        return True, "spread_dangerous"
    if float(ind.orderbook_spread_pct or 0) > 0.15:
        return True, "spread_dangerous"
    return False, None


def _trim_ladder(ladder: List[float], n: int) -> List[float]:
    if n <= 0:
        return []
    return list(ladder[:n]) if ladder else []


def _trim_distribution(dist: List[int], n: int) -> List[int]:
    if n <= 0:
        return []
    if not dist:
        return []
    if len(dist) < n:
        from app.services.dynamic_param_score.param_generator.grid_distribution import (
            STANDARD_THREE_GRID,
            STANDARD_TWO_GRID,
        )

        if n == 1:
            dist = [100]
        elif n == 2:
            dist = list(STANDARD_TWO_GRID)
        elif n == 3:
            dist = list(STANDARD_THREE_GRID)
        else:
            base = 100 // n
            dist = [base] * n
            dist[-1] += 100 - sum(dist)
    d = list(dist[:n])
    if not d:
        return []
    total = sum(d)
    if total != 100 and total > 0:
        d = [int(round(x * 100 / total)) for x in d]
        drift = 100 - sum(d)
        if drift and d:
            d[-1] += drift
    return d


def apply_capacity_to_ladders(
    params: Dict[str, Any],
    capacity: CapacityResolution,
) -> Dict[str, Any]:
    out = dict(params)
    buy_ladder = list(
        out.get("buy_grid_ladder_pcts")
        or out.get("buy_grid_pcts")
        or []
    )
    sell_ladder = list(
        out.get("sell_grid_ladder_pcts")
        or out.get("sell_grid_pcts")
        or []
    )
    buy_dist = list(out.get("buy_distribution") or out.get("buy_qty_distribution") or [])
    sell_dist = list(out.get("sell_distribution") or out.get("sell_qty_distribution") or [])

    buy_n = min(len(buy_ladder) if buy_ladder else capacity.buy_grid_capacity, capacity.buy_grid_capacity)
    sell_n = min(len(sell_ladder) if sell_ladder else capacity.sell_grid_capacity, capacity.sell_grid_capacity)

    buy_ladder = _trim_ladder(buy_ladder, buy_n)
    sell_ladder = _trim_ladder(sell_ladder, sell_n)
    if buy_dist and isinstance(buy_dist[0], float):
        buy_dist = [int(x * 100) for x in buy_dist]
    if sell_dist and isinstance(sell_dist[0], float):
        sell_dist = [int(x * 100) for x in sell_dist]
    risk_class = str(
        out.get("risk_class")
        or out.get("requested_risk_class")
        or out.get("effective_risk_class")
        or "NORMAL"
    )
    from app.services.dynamic_param_score.distribution_policy import (
        DistributionContext,
        distribution_context_from_mapping,
    )
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        trim_side_distribution,
    )

    dist_ctx = distribution_context_from_mapping(
        {
            "risk_state": risk_class,
            "vol_code": out.get("vol_code"),
            "structure_code": out.get("structure_code"),
            "liquidity_score": out.get("liquidity_score"),
            "spread_score": out.get("spread_score"),
            "btc_market_risk_score": out.get("btc_market_risk_score"),
            "fee_efficiency_score": out.get("fee_efficiency_score"),
            "volatility_score": out.get("volatility_score"),
            "drawdown_risk_score": out.get("drawdown_risk_score"),
            "lower_lows": out.get("lower_lows"),
            "higher_highs": out.get("higher_highs"),
            "regime_tag": out.get("regime"),
        }
    )
    if not out.get("liquidity_score"):
        dist_ctx = DistributionContext(
            risk_state=risk_class,
            vol_code=str(out.get("vol_code") or "V3"),
            structure_code=str(out.get("structure_code") or "S2"),
            lower_lows=bool(out.get("lower_lows")),
            higher_highs=bool(out.get("higher_highs")),
        )

    buy_dist = trim_side_distribution(buy_dist, buy_n, ctx=dist_ctx) if buy_n else []
    sell_dist = trim_side_distribution(sell_dist, sell_n, ctx=dist_ctx) if sell_n else []

    out["buy_grid_count"] = buy_n
    out["sell_grid_count"] = sell_n
    out["buy_grid_ladder_pcts"] = buy_ladder
    out["sell_grid_ladder_pcts"] = sell_ladder
    out["buy_grid_pcts"] = buy_ladder
    out["sell_grid_pcts"] = sell_ladder
    if buy_dist:
        out["buy_distribution"] = buy_dist
        out["buy_qty_distribution"] = [x / 100.0 for x in buy_dist]
    if sell_dist:
        out["sell_distribution"] = sell_dist
        out["sell_qty_distribution"] = [x / 100.0 for x in sell_dist]
    return out


def apply_cost_to_ladders(
    params: Dict[str, Any],
    cost: CostResolution,
    *,
    asset_class: str,
) -> Dict[str, Any]:
    out = dict(params)
    if cost.grid_widening_multiplier <= 1.001:
        return out
    asset_min = ASSET_MIN_GRID.get(asset_class, 1.8)
    for key in ("buy_grid_ladder_pcts", "sell_grid_ladder_pcts", "buy_grid_pcts", "sell_grid_pcts"):
        ladders = out.get(key)
        if not ladders:
            continue
        widened = [round(max(asset_min, float(g) * cost.grid_widening_multiplier), 2) for g in ladders]
        out[key] = widened
        if key.startswith("buy"):
            out["buy_grid_ladder_pcts"] = widened
        else:
            out["sell_grid_ladder_pcts"] = widened

    buy_first = float((out.get("buy_grid_ladder_pcts") or [0])[0] or 0)
    for tkey in ("buy_trailing_pct", "min_trailing_pct"):
        if tkey in out and buy_first:
            out[tkey] = min(float(out[tkey] or 0), buy_first * 0.28)
    sell_first = float((out.get("sell_grid_ladder_pcts") or [0])[0] or 0)
    if "sell_trailing_pct" in out and sell_first:
        out["sell_trailing_pct"] = min(float(out["sell_trailing_pct"] or 0), sell_first * 0.28)

    if cost.fee_tier == "FEE_BAD":
        out["final_action"] = FinalAction.ACTIVE_DEFENSIVE_GRID.value
    return out


def bot_params_from_v4_profile(profile: Dict[str, Any]) -> BotParams:
    """Build BotParams from runtime-safe or shelf dps profile dict."""
    buy_l = list(profile.get("buy_grid_ladder_pcts") or [1.5, 3.0])
    sell_l = list(profile.get("sell_grid_ladder_pcts") or [1.5, 3.0])
    buy_dist_raw = profile.get("buy_distribution") or [35, 65]
    sell_dist_raw = profile.get("sell_distribution") or [35, 65]
    buy_dist = [float(x) / 100.0 for x in buy_dist_raw[: len(buy_l)]]
    sell_dist = [float(x) / 100.0 for x in sell_dist_raw[: len(sell_l)]]
    trail = float(profile.get("buy_trailing_pct") or profile.get("sell_trailing_pct") or 0.4)
    max_exp = float(profile.get("max_base_exposure_frac") or 0.55)
    return BotParams(
        base_alloc_frac=float(profile.get("base_alloc_frac") or 0.5),
        quote_alloc_frac=float(profile.get("quote_alloc_frac") or 0.5),
        buy_grid_count=int(profile.get("buy_grid_count") or len(buy_l)),
        sell_grid_count=int(profile.get("sell_grid_count") or len(sell_l)),
        buy_grid_spacing_pct=float(buy_l[0]),
        sell_grid_spacing_pct=float(sell_l[0]),
        buy_qty_distribution=buy_dist,
        sell_qty_distribution=sell_dist,
        trailing_enabled=True,
        trailing_callback_pct=trail,
        take_profit_pct=float(profile.get("resell_trigger_pct") or 2.0),
        stop_new_buys_below_score=0,
        max_base_exposure_frac=max_exp,
        max_quote_to_spend_per_buy_frac=max(buy_dist) if buy_dist else 0.55,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=1.0,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code=str(profile.get("scenario") or "v4_runtime_profile"),
        buy_grid_ladder_pcts=buy_l,
        sell_grid_ladder_pcts=sell_l,
        rebuy_trigger_pct=profile.get("rebuy_trigger_pct"),
        rebuy_trail_pct=profile.get("rebuy_trail_pct"),
        resell_trigger_pct=profile.get("resell_trigger_pct"),
        resell_trail_pct=profile.get("resell_trail_pct"),
        selected_template_key=profile.get("profile_id"),
    )


def generate_runtime_safe_profile(
    signature: Dict[str, Any],
    *,
    budget: float,
    min_notional: float,
    constraints: ExchangeConstraints,
    spread_pct: float,
    fee_efficiency_score: int,
) -> Dict[str, Any]:
    """Runtime safe profile when route shelf is empty."""
    r_code = str(signature.get("regime_code") or "R2")
    s_code = str(signature.get("structure_code") or "S1")
    a_code = str(signature.get("asset_code") or "A3")
    v_code = str(signature.get("vol_code") or "V3")
    risk_class = str(signature.get("risk_class") or "NORMAL")
    asset_name = str(signature.get("asset_class") or "MID_CAP_NORMAL")
    defensive = risk_class in ("DEFENSIVE", "CAUTION")

    spec = resolve_scenario_spec(r_code, s_code, "F3")
    widen = 1.25 if fee_efficiency_score < 30 else 1.0
    buy_grids = scale_grids(spec.buy_grids, 0, widen=widen)
    sell_grids = scale_grids(spec.sell_grids, 0, widen=widen)
    base = (spec.base_range[0] + spec.base_range[1]) / 2
    quote = (spec.quote_range[0] + spec.quote_range[1]) / 2
    if defensive:
        base = min(base, 0.40)
        quote = max(quote, 1.0 - base)

    cap = resolve_capacity(
        budget=budget,
        base_alloc_frac=base,
        quote_alloc_frac=quote,
        min_notional=min_notional,
        profile_buy_n=len(buy_grids),
        profile_sell_n=len(sell_grids),
    )
    buy_grids = _trim_ladder(buy_grids, cap.buy_grid_capacity)
    sell_grids = _trim_ladder(sell_grids, cap.sell_grid_capacity)
    from app.services.dynamic_param_score.distribution_policy import (
        DistributionContext,
        distribution_context_from_mapping,
    )
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        trim_side_distribution,
    )

    dist_ctx = distribution_context_from_mapping(
        {
            "risk_state": risk_class,
            "vol_code": v_code,
            "structure_code": s_code,
            "fee_efficiency_score": fee_efficiency_score,
            "spread_score": 50 if spread_pct < 0.1 else 35,
            "liquidity_score": 50,
        }
    )
    buy_dist = trim_side_distribution(
        list(spec.buy_dist), len(buy_grids), ctx=dist_ctx
    )
    sell_dist = trim_side_distribution(
        list(spec.sell_dist), len(sell_grids), ctx=dist_ctx
    )

    from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
        clean_route_key,
        dplv4_profile_id_clean,
    )

    rk = str(signature.get("route_key") or clean_route_key(a_code, r_code, s_code, v_code, risk_class))
    pid = dplv4_profile_id_clean(
        {
            "asset_code": a_code,
            "regime_code": r_code,
            "structure_code": s_code,
            "vol_code": v_code,
            "risk_class": risk_class,
        },
        seq=999999,
    )

    final_action = spec.final_action
    if fee_efficiency_score < 30 or defensive:
        final_action = FinalAction.ACTIVE_DEFENSIVE_GRID.value

    profile = {
        "profile_id": pid,
        "route_key": rk,
        "scenario": spec.name,
        "final_action": final_action,
        "base_alloc_frac": round(base, 4),
        "quote_alloc_frac": round(quote, 4),
        "buy_grid_count": len(buy_grids),
        "sell_grid_count": len(sell_grids),
        "buy_grid_ladder_pcts": buy_grids,
        "sell_grid_ladder_pcts": sell_grids,
        "buy_distribution": buy_dist,
        "sell_distribution": sell_dist,
        "buy_trailing_pct": (spec.buy_trail_range[0] + spec.buy_trail_range[1]) / 2,
        "sell_trailing_pct": (spec.sell_trail_range[0] + spec.sell_trail_range[1]) / 2,
        "asset_class": asset_name,
        "asset_code": a_code,
        "regime_code": r_code,
        "structure_code": s_code,
        "vol_code": v_code,
        "risk_class": risk_class,
        "grid_bias": grid_bias_for_context(s_code, r_code),
        "fallback_generated": True,
        "max_base_exposure_frac": 0.50 if defensive else 0.72,
    }
    return apply_live_route_constraints(profile, signature)


def resolve_adaptive_max_exposure(
    signature: Dict[str, Any],
    *,
    current_max: float,
    defensive: bool,
) -> Tuple[float, str]:
    """Cap max_base_exposure_frac from live stress (pump, liq, BTC, downtrend)."""
    max_exp = float(current_max or 0.72)
    reason = ""
    r_code = str(signature.get("regime_code") or "")
    v_code = str(signature.get("vol_code") or "")
    overbought = bool(signature.get("overbought_chop"))
    btc_pressure = bool(signature.get("btc_pressure"))
    vol_pct = float(
        signature.get("volatility_percentile")
        or signature.get("volatility_score")
        or 50
    )
    liq_score = int(signature.get("liquidity_score") or 80)
    spread_score = int(signature.get("spread_score") or 80)
    ret_24h = abs(float(signature.get("return_24h_pct") or 0))
    bb_pos = float(signature.get("price_in_bb") or signature.get("bb_position") or 0.5)
    z_score = abs(float(signature.get("z_score_5m") or 0))

    pump_risk = (
        v_code == "V5"
        or r_code in ("R13", "R14", "R15")
        or (overbought and vol_pct >= 95)
        or (ret_24h >= 20.0 and vol_pct >= 90)
        or bb_pos >= 0.90
        or z_score >= 1.5
    )
    liq_weak = liq_score < 40 or spread_score < 35
    btc_vol_stress = btc_pressure and vol_pct >= 70

    if pump_risk:
        max_exp = min(max_exp, 0.35)
        reason = "pump_v5_overextension"
    elif liq_weak:
        max_exp = min(max_exp, 0.40)
        reason = "liquidity_spread_weak"
    elif btc_vol_stress:
        max_exp = min(max_exp, 0.42)
        reason = "btc_pressure_high_vol"
    elif r_code in ("R7", "R12"):
        max_exp = min(max_exp, 0.40)
        reason = "strong_downtrend_defensive"
    elif defensive:
        if r_code == "R4" and vol_pct >= 85:
            max_exp = min(max_exp, 0.45)
            reason = "breakout_risk_high_vol"
        elif overbought or btc_pressure:
            max_exp = min(max_exp, 0.48)
            reason = "defensive_overbought_btc"
        else:
            max_exp = min(max_exp, 0.50)
            reason = "defensive_range"
    return round(max_exp, 4), reason


def apply_live_route_constraints(
    merged: Dict[str, Any],
    signature: Dict[str, Any],
) -> Dict[str, Any]:
    """Cap base exposure, normalize grid weights, cap trailing for live route context."""
    out = dict(merged)
    r_code = str(signature.get("regime_code") or "")
    s_code = str(signature.get("structure_code") or "")
    requested_risk = str(signature.get("risk_class") or "NORMAL")
    profile_risk = str(out.get("risk_class") or "NORMAL")
    defensive = requested_risk in ("DEFENSIVE", "CAUTION") or profile_risk in (
        "DEFENSIVE",
        "CAUTION",
    )
    overbought = bool(signature.get("overbought_chop"))
    btc_pressure = bool(signature.get("btc_pressure"))

    base_frac = float(out.get("base_alloc_frac") or 0.5)
    if r_code in ("R7", "R12", "R13", "R14") and s_code == "S2":
        base_frac = min(base_frac, 0.30)
    elif r_code in ("R13", "R14") and s_code == "S4":
        base_frac = min(base_frac, 0.40)
    elif defensive and s_code == "S2":
        base_frac = min(base_frac, 0.35)
    elif defensive and overbought:
        base_frac = min(base_frac, 0.38)

    profile_risk = str(out.get("risk_class") or "NORMAL")
    if defensive and profile_risk == "NORMAL":
        out["defensive_fallback_overlay"] = True
        base_frac = min(base_frac, 0.35 if not overbought else 0.32)

    out["base_alloc_frac"] = round(base_frac, 4)
    out["quote_alloc_frac"] = round(1.0 - base_frac, 4)

    max_exp = float(out.get("max_base_exposure_frac") or 0.72)
    max_exp, exp_reason = resolve_adaptive_max_exposure(
        signature, current_max=max_exp, defensive=defensive
    )
    if exp_reason:
        out["adaptive_exposure_reason"] = exp_reason
    out["max_base_exposure_frac"] = max_exp

    buy_dist_raw = list(
        out.get("buy_distribution") or out.get("buy_qty_distribution") or []
    )
    buy_dist, buy_changed = normalize_side_distribution(
        buy_dist_raw,
        defensive=defensive,
    )
    if buy_dist:
        out["buy_distribution"] = buy_dist
        out["buy_qty_distribution"] = [x / 100.0 for x in buy_dist]
    sell_dist, sell_changed = normalize_side_distribution(
        list(out.get("sell_distribution") or out.get("sell_qty_distribution") or []),
        defensive=defensive,
    )
    if sell_dist:
        out["sell_distribution"] = sell_dist
        out["sell_qty_distribution"] = [x / 100.0 for x in sell_dist]

    buy_grids = out.get("buy_grid_ladder_pcts") or []
    sell_grids = out.get("sell_grid_ladder_pcts") or []
    if buy_grids:
        trail = float(
            out.get("buy_trailing_pct")
            or out.get("trailing_callback_pct")
            or 0.0
        )
        out["buy_trailing_pct"] = cap_trailing_pct(trail, float(buy_grids[0]))
        out["trailing_callback_pct"] = out["buy_trailing_pct"]
    if sell_grids:
        sell_trail = float(out.get("sell_trailing_pct") or out.get("trailing_callback_pct") or 0.0)
        out["sell_trailing_pct"] = cap_trailing_pct(sell_trail, float(sell_grids[0]))

    if buy_changed or sell_changed:
        out["distribution_normalized"] = True
    return out


def apply_v4_resolvers(
    params: BotParams,
    *,
    template: Optional[ParamTemplate],
    signature: Dict[str, Any],
    budget: float,
    min_notional: float,
    constraints: ExchangeConstraints,
    ind: IndicatorSnapshot,
    fee_efficiency_score: int,
    dps_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[BotParams, ResolverContext, Dict[str, float]]:
    """Apply capacity + cost + data quality after profile selection."""
    raw = params.to_dict() if params else {}
    dps = dps_profile or ((template.params or {}).get("dps_profile") if template else {}) or {}

    base_frac = float(raw.get("base_alloc_frac") or dps.get("base_alloc_frac") or 0.5)
    quote_frac = float(raw.get("quote_alloc_frac") or dps.get("quote_alloc_frac") or 0.5)
    buy_n = int(raw.get("buy_grid_count") or dps.get("buy_grid_count") or 0)
    sell_n = int(raw.get("sell_grid_count") or dps.get("sell_grid_count") or 0)

    capacity = resolve_capacity(
        budget=budget,
        base_alloc_frac=base_frac,
        quote_alloc_frac=quote_frac,
        min_notional=min_notional,
        profile_buy_n=buy_n,
        profile_sell_n=sell_n,
    )
    cost = resolve_cost(
        constraints=constraints,
        spread_pct=float(ind.orderbook_spread_pct or 0),
        fee_efficiency_score=fee_efficiency_score,
        ind=ind,
    )
    dq_label, dq_widen, dq_hard = resolve_data_quality(
        data_quality_score=int(signature.get("data_quality_score") or 80),
        data_freshness_sec=float(getattr(ind, "data_freshness_sec", 0) or 0),
        data_gap_sec=float(getattr(ind, "data_gap_sec", 0) or 0),
        price_valid=bool(getattr(ind, "price_valid", True)),
    )
    safety_hard, safety_reason = resolve_safety_hard(
        ind=ind,
        constraints=constraints,
        spread_pct=float(ind.orderbook_spread_pct or 0),
        data_hard_fail=dq_hard,
    )

    merged = {**dps, **raw}
    merged = apply_capacity_to_ladders(merged, capacity)
    if cost.grid_widening_multiplier > 1.0:
        cost = CostResolution(
            total_cost_pct=cost.total_cost_pct,
            grid_widening_multiplier=cost.grid_widening_multiplier * dq_widen,
            fee_tier=cost.fee_tier,
        )
    merged = apply_cost_to_ladders(
        merged,
        cost,
        asset_class=str(dps.get("asset_class") or signature.get("asset_class") or "MID_CAP_NORMAL"),
    )
    merged = apply_live_route_constraints(merged, signature)

    fit_scores = compute_fit_scores(dps, signature, capacity, cost)
    ctx = ResolverContext(
        capacity=capacity,
        cost=cost,
        data_quality=dq_label,
        safety_hard=safety_hard,
        safety_reason=safety_reason,
        fallback_generated=bool(dps.get("fallback_generated")),
    )

    field_names = {f.name for f in fields(BotParams)}
    updates: Dict[str, Any] = {}
    for k, v in merged.items():
        if k in field_names:
            updates[k] = v
    if "buy_grid_ladder_pcts" in merged:
        buy_l = merged["buy_grid_ladder_pcts"]
        if buy_l:
            updates["buy_grid_ladder_pcts"] = buy_l
            updates["buy_grid_spacing_pct"] = float(buy_l[0])
    if "sell_grid_ladder_pcts" in merged:
        sell_l = merged["sell_grid_ladder_pcts"]
        if sell_l:
            updates["sell_grid_ladder_pcts"] = sell_l
            updates["sell_grid_spacing_pct"] = float(sell_l[0])
    return replace(params, **updates), ctx, fit_scores


def compute_fit_scores(
    dps: Dict[str, Any],
    signature: Dict[str, Any],
    capacity: CapacityResolution,
    cost: CostResolution,
) -> Dict[str, float]:
    from app.services.dynamic_param_score.param_generator.v4_scoring import (
        base_quote_fit_score,
        grid_direction_fit_score,
        structure_fit_score,
    )

    sf = structure_fit_score(
        str(dps.get("structure_code") or ""),
        str(signature.get("structure_code") or ""),
    )
    gf = grid_direction_fit_score(dps, signature)
    bq = base_quote_fit_score(dps, signature)
    cap_fit = 1.0 if capacity.buy_grid_capacity > 0 or capacity.sell_grid_capacity > 0 else 0.0
    cost_fit = 1.0 if cost.fee_tier != "FEE_BAD" or cost.grid_widening_multiplier >= 1.15 else 0.5
    return {
        "structure_fit": sf,
        "grid_direction_fit": gf,
        "base_quote_fit": bq,
        "capacity_fit": cap_fit,
        "cost_fit": cost_fit,
    }
