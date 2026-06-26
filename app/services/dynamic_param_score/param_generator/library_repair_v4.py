"""Repair V4 library profiles for schema, ladders, fee, and min-notional compliance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.audit_v4.library_schema import backfill_library_schema_fields
from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    BUDGET_SHELVES,
    REGIME_SHELVES,
    budget_code_from_class,
    budget_midpoint_v4,
    clean_route_key,
    fallback_keys,
    fee_code_from_class,
    normalize_route_key,
)
from app.services.dynamic_param_score.param_generator.candidate_validator import hard_validate_profile
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    cap_trailing_pct,
    normalize_side_distribution,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    MIN_GRID_SPACING,
    MIN_NET_ROOM,
    apply_side_structure_multiplier,
    compute_grid_ladder,
    enforce_grid_spacing_minimums,
)
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    SCENARIO_SPECS,
    resolve_scenario_spec,
    scale_grids,
    validate_scenario_direction,
)
from app.services.dynamic_param_score.param_generator.v4_resolvers import (
    _trim_distribution,
    _trim_ladder,
    resolve_capacity,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

WAIT_ACTIONS = frozenset(
    {"WAIT", "NO_TRADE", "SAFE_WAIT", "DATA_STALE_SAFE_WAIT", "ABSTAIN"}
)
NORMAL_GRID_SCENARIOS = frozenset(
    {
        "BALANCED_RANGE",
        "LOWER_LOWS_WEAK_DOWN_RANGE",
        "HIGHER_HIGHS_WEAK_UP_RANGE",
        "WIDE_CHOP",
        "HIGH_VOL_CHOPPY_RANGE",
        "HIGH_VOL_CHOPPY",
        "STRONG_UPTREND",
        "STRONG_DOWNTREND_RANGE",
        "LOW_VOL_COMPRESSION",
        "CALM_RANGE",
    }
)
_FEE_WIDEN = {"F4": 1.12, "F5": 1.12, "F6": 1.30}
_STRUCTURE_MAP = {"S2": "lower_lows_only", "S3": "higher_highs_only", "S6": "lower_lows_only", "S7": "higher_highs_only"}


def _resolve_spec_for_profile(profile: Dict[str, Any]):
    scenario = str(profile.get("scenario") or "")
    if scenario in SCENARIO_SPECS:
        return SCENARIO_SPECS[scenario]
    try:
        return resolve_scenario_spec(
            str(profile.get("regime_code") or "R2"),
            str(profile.get("structure_code") or "S1"),
            str(profile.get("fee_code") or "F3"),
        )
    except Exception:
        return None


def _capacity_fails(
    profile: Dict[str, Any],
    *,
    min_notional: float = DEFAULT_MIN_NOTIONAL_USDT,
) -> List[str]:
    if is_intentional_empty_ladder(profile):
        return []
    fails: List[str] = []
    b_code = str(
        profile.get("budget_code") or budget_code_from_class(str(profile.get("budget_class", "50_100")))
    )
    mid = budget_midpoint_v4(b_code)
    label, tier_lo, _tier_hi = BUDGET_SHELVES.get(b_code, ("50_100", 50.0, 100.0))
    base_frac = float(profile.get("base_alloc_frac") or 0.5)
    quote_frac = float(profile.get("quote_alloc_frac") or 0.5)
    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)
    budgets = []
    for b in (mid, max(float(tier_lo), 10.0)):
        if b * max(base_frac, quote_frac) >= min_notional * 0.99:
            budgets.append(round(b, 2))
    if not budgets:
        budgets = [mid]

    for budget in budgets:
        cap = resolve_capacity(
            budget=budget,
            base_alloc_frac=base_frac,
            quote_alloc_frac=quote_frac,
            min_notional=min_notional,
            profile_buy_n=buy_n,
            profile_sell_n=sell_n,
        )
        if buy_n > 0 and cap.buy_grid_capacity <= 0:
            fails.append(f"min_notional_buy_fail_{int(budget)}")
        if sell_n > 0 and cap.sell_grid_capacity <= 0:
            fails.append(f"min_notional_sell_fail_{int(budget)}")
        if buy_n > 0:
            quote_per = budget * quote_frac / max(cap.buy_grid_capacity, 1)
            if quote_per < min_notional * 0.99:
                fails.append(f"min_notional_buy_grid_{int(budget)}")
        if sell_n > 0:
            base_per = budget * base_frac / max(cap.sell_grid_capacity, 1)
            if base_per < min_notional * 0.99:
                fails.append(f"min_notional_sell_grid_{int(budget)}")
    return fails


def _bump_grid_ratios(grids: List[float], asset: str) -> List[float]:
    if not grids:
        return grids
    min_spacing = MIN_GRID_SPACING.get(asset, 1.50)
    min_ratios = (2.2, 4.5, 7.0)
    out = [round(max(grids[0], ASSET_MIN_GRID.get(asset, 1.8)), 4)]
    for i, g in enumerate(grids[1:], start=1):
        need_ratio = min_ratios[i - 1] if i - 1 < len(min_ratios) else 7.0
        out.append(round(max(float(g), out[-1] + min_spacing, out[0] * need_ratio + 0.05), 4))
    return out


def _sync_grid_metadata(profile: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(profile)
    buy = list(out.get("buy_grid_ladder_pcts") or out.get("buy_grid_pcts") or [])
    sell = list(out.get("sell_grid_ladder_pcts") or out.get("sell_grid_pcts") or [])
    out["buy_grid_ladder_pcts"] = buy
    out["sell_grid_ladder_pcts"] = sell
    out["buy_grid_pcts"] = buy
    out["sell_grid_pcts"] = sell
    out["buy_grid_count"] = len(buy)
    out["sell_grid_count"] = len(sell)
    fa = str(out.get("final_action") or "").upper()
    if len(buy) == 0 and len(sell) > 0 and fa not in WAIT_ACTIONS:
        out["final_action"] = FinalAction.SELL_MANAGEMENT_ONLY.value
    if len(buy) == 0 and len(sell) == 0 and fa not in WAIT_ACTIONS:
        out["final_action"] = FinalAction.WAIT.value
    if not out.get("final_action"):
        spec = _resolve_spec_for_profile(out)
        out["final_action"] = (
            spec.final_action if spec else FinalAction.BALANCED_GRID.value
        )
    return repair_distribution_profile(out)


def _fee_min_first_grid(profile: Dict[str, Any]) -> float:
    widen = _fee_widen_multiplier(profile)
    fee_class = str(profile.get("fee_class") or "")
    fee_code = str(profile.get("fee_code") or "")
    if fee_class == "fee_bad" or fee_code == "F6":
        return 1.8 * widen * 0.98
    return 0.0


def repair_grid_ladder_quality(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild ladder rungs from first grid so ratio/spacing rules pass."""
    out = dict(profile)
    if is_intentional_empty_ladder(out):
        return out
    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
    s_code = str(out.get("structure_code") or "S1")
    structure = _STRUCTURE_MAP.get(s_code, "neither")
    fee_class = str(out.get("fee_class") or "normal_fee")
    variant = int(out.get("variant_idx") or 0)
    fee_floor = _fee_min_first_grid(out)

    for side in ("buy", "sell"):
        key = f"{side}_grid_ladder_pcts"
        grids = list(out.get(key) or out.get(f"{side}_grid_pcts") or [])
        if not grids:
            continue
        first = max(float(grids[0]), ASSET_MIN_GRID.get(asset, 1.8), fee_floor)
        rebuilt = compute_grid_ladder(first, len(grids), variant_idx=variant)
        rebuilt = enforce_grid_spacing_minimums(rebuilt, asset)
        rebuilt = apply_side_structure_multiplier(
            rebuilt,
            side=side,
            structure=structure,
            fee_class=fee_class,
        )
        rebuilt = _bump_grid_ratios(rebuilt, asset)
        out[key] = rebuilt
        out[f"{side}_grid_pcts"] = rebuilt
    buy_n = len(out.get("buy_grid_ladder_pcts") or [])
    sell_n = len(out.get("sell_grid_ladder_pcts") or [])
    out["buy_grid_count"] = buy_n
    out["sell_grid_count"] = sell_n
    return out


def repair_directional_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(profile)
    if is_intentional_empty_ladder(out):
        return out
    spec = _resolve_spec_for_profile(out)
    if spec is None:
        return out

    base = float(out.get("base_alloc_frac") or 0.5)
    quote = float(out.get("quote_alloc_frac") or 0.5)
    buy = list(out.get("buy_grid_ladder_pcts") or out.get("buy_grid_pcts") or [])
    sell = list(out.get("sell_grid_ladder_pcts") or out.get("sell_grid_pcts") or [])

    if spec.buy_wider_than_sell and buy and sell and len(sell) > len(buy):
        sell = sell[: len(buy)]
    if spec.sell_wider_than_buy and buy and sell and len(buy) > len(sell):
        buy = buy[: len(sell)]

    ok, errs = validate_scenario_direction(spec, base, quote, buy, sell)
    if any("base_too" in e or "quote_too" in e for e in errs):
        target_base = (spec.base_range[0] + spec.base_range[1]) / 2
        target_quote = (spec.quote_range[0] + spec.quote_range[1]) / 2
        total = target_base + target_quote
        if total > 0:
            base = round(target_base / total, 4)
            quote = round(target_quote / total, 4)
            out["base_alloc_frac"] = base
            out["quote_alloc_frac"] = quote

    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
    variant = int(out.get("variant_idx") or 0)

    for _ in range(4):
        ok, errs = validate_scenario_direction(spec, base, quote, buy, sell)
        if ok:
            break
        if spec.buy_wider_than_sell and buy and sell:
            if buy[0] < sell[0] * 1.25:
                first = round(max(sell[0] * 1.35, _fee_min_first_grid(out), ASSET_MIN_GRID.get(asset, 1.8)), 4)
                buy = _bump_grid_ratios(
                    compute_grid_ladder(first, len(buy), variant_idx=variant), asset
                )
            if len(buy) > 1 and len(sell) > 1 and buy[1] < sell[1] * 1.25:
                buy[1] = round(max(buy[1], sell[1] * 1.35), 4)
                if len(buy) > 2:
                    buy[2] = round(max(buy[2], buy[1] * 2.0, buy[0] * 4.55), 4)
                buy = _bump_grid_ratios(buy, asset)
        if spec.sell_wider_than_buy and buy and sell:
            if sell[0] < buy[0] * 1.25:
                first = round(max(buy[0] * 1.35, _fee_min_first_grid(out), ASSET_MIN_GRID.get(asset, 1.8)), 4)
                sell = _bump_grid_ratios(
                    compute_grid_ladder(first, len(sell), variant_idx=variant), asset
                )
            if len(buy) > 1 and len(sell) > 1 and sell[1] < buy[1] * 1.25:
                sell[1] = round(max(sell[1], buy[1] * 1.35), 4)
                if len(sell) > 2:
                    sell[2] = round(max(sell[2], sell[1] * 2.0, sell[0] * 4.55), 4)
                sell = _bump_grid_ratios(sell, asset)

    out["buy_grid_ladder_pcts"] = buy
    out["sell_grid_ladder_pcts"] = sell
    out["buy_grid_pcts"] = buy
    out["sell_grid_pcts"] = sell
    out["buy_grid_count"] = len(buy)
    out["sell_grid_count"] = len(sell)
    out["buy_distribution"] = _trim_distribution(list(out.get("buy_distribution") or list(spec.buy_dist)), len(buy))
    out["sell_distribution"] = _trim_distribution(list(out.get("sell_distribution") or list(spec.sell_dist)), len(sell))
    return out


def repair_trailing_and_net_room(profile: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(profile)
    if is_intentional_empty_ladder(out):
        return out
    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
    min_net = MIN_NET_ROOM.get(asset, 1.2)
    for side in ("buy", "sell"):
        grids = out.get(f"{side}_grid_ladder_pcts") or []
        if not grids:
            continue
        first = float(grids[0])
        trail_key = f"{side}_trailing_pct"
        trail = cap_trailing_pct(float(out.get(trail_key) or 0), first)
        trail = min(trail, max(0.0, first - min_net - 0.02))
        out[trail_key] = round(trail, 4)
    return out


def repair_distribution_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(profile)
    defensive = str(out.get("risk_class") or "").upper() in ("DEFENSIVE", "CAUTION")
    spec = _resolve_spec_for_profile(out)

    def _coerce_dist(raw: Any, n: int, spec_dist: Any) -> List[int]:
        if n <= 0:
            return []
        if isinstance(raw, list) and raw and all(isinstance(x, (int, float)) for x in raw):
            coerced = [int(round(float(x))) for x in raw]
            if len(coerced) != n:
                if spec_dist:
                    return _trim_distribution(list(spec_dist), n)
                fixed, _ = normalize_side_distribution(
                    [35, 65] if n == 2 else [15, 30, 55] if n == 3 else [100],
                    defensive=defensive,
                )
                return _trim_distribution(fixed, n)
            return coerced
        if spec_dist:
            return _trim_distribution(list(spec_dist), n) or []
        fixed, _ = normalize_side_distribution(
            [35, 65] if n == 2 else [15, 30, 55] if n == 3 else [100],
            defensive=defensive,
        )
        return _trim_distribution(fixed, n) or [100]

    for side in ("buy", "sell"):
        n = int(out.get(f"{side}_grid_count") or len(out.get(f"{side}_grid_ladder_pcts") or []))
        spec_dist = getattr(spec, f"{side}_dist", ()) if spec is not None else ()
        dist = _coerce_dist(out.get(f"{side}_distribution"), n, spec_dist)
        if n > 0 and dist:
            fixed, _ = normalize_side_distribution(dist[:n], defensive=defensive)
            trimmed = _trim_distribution(fixed, n)
            if trimmed and len(trimmed) == n:
                out[f"{side}_distribution"] = trimmed
            else:
                out.pop(f"{side}_distribution", None)
        else:
            out.pop(f"{side}_distribution", None)
    return out


def _profile_compliance_ok(profile: Dict[str, Any]) -> bool:
    if is_intentional_empty_ladder(profile):
        return True
    if classify_ladder_issue(profile)[0]:
        return False
    ok, _ = hard_validate_profile(profile)
    if not ok:
        return False
    spec = _resolve_spec_for_profile(profile)
    if spec:
        dir_ok, _ = validate_scenario_direction(
            spec,
            float(profile.get("base_alloc_frac") or 0.5),
            float(profile.get("quote_alloc_frac") or 0.5),
            profile.get("buy_grid_ladder_pcts") or [],
            profile.get("sell_grid_ladder_pcts") or [],
        )
        if not dir_ok:
            return False
    if _capacity_fails(profile):
        return False
    widen = _fee_widen_multiplier(profile)
    fee_class = str(profile.get("fee_class") or "")
    fee_code = str(profile.get("fee_code") or "")
    if fee_class == "fee_bad" or fee_code == "F6":
        first = float(
            (profile.get("sell_grid_ladder_pcts") or profile.get("buy_grid_ladder_pcts") or [0])[0]
            or 0
        )
        if first > 0 and first < 1.8 * widen * 0.95:
            return False
    fa = str(profile.get("final_action") or "").upper()
    if (fee_class == "fee_bad" or fee_code == "F6") and fa in WAIT_ACTIONS:
        return False
    return True


def is_intentional_empty_ladder(profile: Dict[str, Any]) -> bool:
    fa = str(profile.get("final_action") or "").upper()
    if fa in WAIT_ACTIONS:
        return True
    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)
    scenario = str(profile.get("scenario") or "")
    regime = str(profile.get("regime_code") or profile.get("regime") or "")
    if fa == FinalAction.SELL_MANAGEMENT_ONLY.value and buy_n == 0:
        return True
    if scenario == "CRASH_RISK" or regime in ("R8", "CRASH_RISK"):
        if buy_n == 0:
            return True
    if buy_n == 0 and sell_n == 0:
        return True
    return False


def classify_ladder_issue(profile: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Return (issue_codes, is_intentional)."""
    if is_intentional_empty_ladder(profile):
        return [], True

    issues: List[str] = []
    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)
    buy = profile.get("buy_grid_ladder_pcts") or profile.get("buy_grid_pcts")
    sell = profile.get("sell_grid_ladder_pcts") or profile.get("sell_grid_pcts")

    if buy_n > 0 and not buy:
        issues.append("unexpected_buy_ladder_null")
    if sell_n > 0 and not sell:
        issues.append("unexpected_sell_ladder_null")
    if buy is None and buy_n == 0 and sell_n > 0:
        pass
    elif buy is None and buy_n > 0:
        issues.append("buy_ladder_null")
    if sell is None and sell_n > 0:
        issues.append("sell_ladder_null")

    scenario = str(profile.get("scenario") or "")
    if scenario in NORMAL_GRID_SCENARIOS and (not buy or not sell) and buy_n > 0 and sell_n > 0:
        issues.append("normal_scenario_ladder_null")

    for side, grids in (("buy", buy), ("sell", sell)):
        if not grids:
            continue
        if any(float(g) <= 0 for g in grids):
            issues.append(f"{side}_grid_non_positive")
        for i in range(1, len(grids)):
            if float(grids[i]) <= float(grids[i - 1]):
                issues.append(f"{side}_grid_not_ascending")

    return issues, False


def _fee_widen_multiplier(profile: Dict[str, Any]) -> float:
    f_code = str(profile.get("fee_code") or fee_code_from_class(str(profile.get("fee_class") or "")))
    return _FEE_WIDEN.get(f_code, 1.0 if profile.get("fee_class") != "fee_bad" else 1.30)


def _force_spec_compliant_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild from scenario spec until audit compliance passes."""
    out = dict(profile)
    if is_intentional_empty_ladder(out):
        return out
    spec = _resolve_spec_for_profile(out)
    if spec is None:
        return out

    widen = _fee_widen_multiplier(out)
    variant = int(out.get("variant_idx") or 0)
    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
    buy = _bump_grid_ratios(
        enforce_grid_spacing_minimums(scale_grids(spec.buy_grids, variant, widen=widen), asset),
        asset,
    )
    sell = _bump_grid_ratios(
        enforce_grid_spacing_minimums(scale_grids(spec.sell_grids, variant, widen=widen), asset),
        asset,
    )
    base = (spec.base_range[0] + spec.base_range[1]) / 2
    quote = (spec.quote_range[0] + spec.quote_range[1]) / 2
    total = base + quote
    if total > 0:
        base, quote = base / total, quote / total

    out.update(
        {
            "scenario": spec.name,
            "final_action": spec.final_action,
            "base_alloc_frac": round(base, 4),
            "quote_alloc_frac": round(quote, 4),
            "buy_grid_ladder_pcts": buy,
            "sell_grid_ladder_pcts": sell,
            "buy_grid_pcts": buy,
            "sell_grid_pcts": sell,
            "buy_grid_count": len(buy),
            "sell_grid_count": len(sell),
            "buy_distribution": _trim_distribution(list(spec.buy_dist), len(buy)),
            "sell_distribution": _trim_distribution(list(spec.sell_dist), len(sell)),
            "buy_trailing_pct": round(min((spec.buy_trail_range[0] + spec.buy_trail_range[1]) / 2, buy[0] * 0.28), 4) if buy else 0,
            "sell_trailing_pct": round(min((spec.sell_trail_range[0] + spec.sell_trail_range[1]) / 2, sell[0] * 0.28), 4) if sell else 0,
        }
    )
    out = repair_fee_profile(out)
    out = repair_min_notional_ladders(out)
    out = repair_grid_ladder_quality(out)
    out = repair_directional_profile(out)
    out = repair_trailing_and_net_room(out)
    out = repair_distribution_profile(out)
    return _sync_grid_metadata(out)


def repair_fee_profile(profile: Dict[str, Any], *, widen_grids: bool = True) -> Dict[str, Any]:
    out = dict(profile)
    fee_class = str(out.get("fee_class") or "")
    fee_code = str(out.get("fee_code") or fee_code_from_class(fee_class))
    fa = str(out.get("final_action") or "").upper()

    if fee_class == "fee_bad" or fee_code == "F6":
        if fa in WAIT_ACTIONS:
            out["final_action"] = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        out["safety_level"] = "ACTIVE_DEFENSIVE"
        widen = _fee_widen_multiplier(out)
        out["grid_widening_multiplier"] = widen
        out["cost_floor_applied"] = True
        out["cost_floor_pct"] = out.get("cost_floor_pct") or 1.2
        out["total_cost_pct"] = out.get("total_cost_pct") or out["cost_floor_pct"]
        if widen_grids:
            min_first = 1.8 * widen * 0.98
            for side in ("buy", "sell"):
                grids = list(out.get(f"{side}_grid_ladder_pcts") or out.get(f"{side}_grid_pcts") or [])
                if not grids:
                    continue
                if float(grids[0]) < min_first:
                    variant = int(out.get("variant_idx") or 0)
                    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
                    rebuilt = compute_grid_ladder(min_first, len(grids), variant_idx=variant)
                    rebuilt = enforce_grid_spacing_minimums(rebuilt, asset)
                    out[f"{side}_grid_ladder_pcts"] = rebuilt
                    out[f"{side}_grid_pcts"] = rebuilt
            out = repair_directional_profile(out)
            out = repair_trailing_and_net_room(out)

    out.pop("fee_in_route", None)
    rk = normalize_route_key(str(out.get("route_key") or ""))
    if rk:
        out["route_key"] = rk
    return out


def repair_min_notional_ladders(
    profile: Dict[str, Any],
    *,
    min_notional: float = DEFAULT_MIN_NOTIONAL_USDT,
) -> Dict[str, Any]:
    """Reduce grid count + re-trim distribution — never narrow ladder spacing."""
    out = dict(profile)
    if is_intentional_empty_ladder(out):
        return out

    b_code = str(out.get("budget_code") or budget_code_from_class(str(out.get("budget_class", "50_100"))))
    _, tier_lo, _tier_hi = BUDGET_SHELVES.get(b_code, ("50_100", 50.0, 100.0))
    test_budgets = [budget_midpoint_v4(b_code), max(float(tier_lo), 10.0)]

    buy_ladder = list(out.get("buy_grid_ladder_pcts") or out.get("buy_grid_pcts") or [])
    sell_ladder = list(out.get("sell_grid_ladder_pcts") or out.get("sell_grid_pcts") or [])
    buy_dist = list(out.get("buy_distribution") or [])
    sell_dist = list(out.get("sell_distribution") or [])
    base_frac = float(out.get("base_alloc_frac") or 0.5)
    quote_frac = float(out.get("quote_alloc_frac") or 0.5)

    def _passes(budget: float, buy_n: int, sell_n: int) -> bool:
        cap = resolve_capacity(
            budget=budget,
            base_alloc_frac=base_frac,
            quote_alloc_frac=quote_frac,
            min_notional=min_notional,
            profile_buy_n=buy_n,
            profile_sell_n=sell_n,
        )
        if buy_n > 0 and cap.buy_grid_capacity <= 0:
            return False
        if sell_n > 0 and cap.sell_grid_capacity <= 0:
            return False
        if buy_n > 0:
            quote_per = budget * quote_frac / max(cap.buy_grid_capacity, 1)
            if quote_per < min_notional * 0.99:
                return False
        if sell_n > 0:
            base_per = budget * base_frac / max(cap.sell_grid_capacity, 1)
            if base_per < min_notional * 0.99:
                return False
        return True

    buy_n = len(buy_ladder)
    sell_n = len(sell_ladder)
    while buy_n > 0 or sell_n > 0:
        ok_all = all(_passes(b, buy_n, sell_n) for b in test_budgets)
        if ok_all:
            break
        if buy_n >= sell_n and buy_n > 0:
            buy_n -= 1
        elif sell_n > 0:
            sell_n -= 1
        else:
            break

    buy_ladder = _trim_ladder(buy_ladder, buy_n)
    sell_ladder = _trim_ladder(sell_ladder, sell_n)
    buy_dist = _trim_distribution(buy_dist, buy_n) or ([100] if buy_n == 1 else buy_dist[:buy_n])
    sell_dist = _trim_distribution(sell_dist, sell_n) or ([100] if sell_n == 1 else sell_dist[:sell_n])

    out["buy_grid_count"] = buy_n
    out["sell_grid_count"] = sell_n
    out["buy_grid_ladder_pcts"] = buy_ladder
    out["sell_grid_ladder_pcts"] = sell_ladder
    out["buy_grid_pcts"] = buy_ladder
    out["sell_grid_pcts"] = sell_ladder
    if buy_dist:
        out["buy_distribution"] = buy_dist
    if sell_dist:
        out["sell_distribution"] = sell_dist
    if buy_n == 0 and sell_n == 0:
        out["final_action"] = FinalAction.WAIT.value
        out["buy_grid_ladder_pcts"] = []
        out["sell_grid_ladder_pcts"] = []
        out["buy_grid_pcts"] = []
        out["sell_grid_pcts"] = []
    elif buy_n == 0 and sell_n > 0:
        out["final_action"] = FinalAction.SELL_MANAGEMENT_ONLY.value
    return _sync_grid_metadata(out)


def _rebuild_ladders_from_scenario(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Last resort: rebuild ladders from scenario spec when null in normal scenario."""
    out = dict(profile)
    r_code = str(out.get("regime_code") or "R2")
    s_code = str(out.get("structure_code") or "S1")
    f_code = str(out.get("fee_code") or "F3")
    scenario = str(out.get("scenario") or "")
    if scenario not in SCENARIO_SPECS:
        scenario_map = {
            "STRONG_UPTREND_RISK": "STRONG_UPTREND",
            "STRONG_DOWNTREND_RISK": "STRONG_DOWNTREND_RANGE",
            "WEAK_DOWNTREND_RANGE": "LOWER_LOWS_WEAK_DOWN_RANGE",
            "WEAK_UPTREND_RANGE": "HIGHER_HIGHS_WEAK_UP_RANGE",
            "VOLATILE_RANGE": "HIGH_VOL_CHOPPY_RANGE",
            "CHOPPY_RANGE": "HIGH_VOL_CHOPPY_RANGE",
        }
        scenario = scenario_map.get(scenario, scenario)
    if scenario not in SCENARIO_SPECS:
        try:
            spec = resolve_scenario_spec(r_code, s_code, f_code)
        except Exception:
            return out
    else:
        spec = SCENARIO_SPECS[scenario]
    widen = _fee_widen_multiplier(out)
    variant = int(out.get("variant_idx") or 0)
    buy_grids = scale_grids(spec.buy_grids, variant, widen=widen)
    sell_grids = scale_grids(spec.sell_grids, variant, widen=widen)
    asset = str(out.get("asset_class") or "MID_CAP_NORMAL")
    buy_grids = enforce_grid_spacing_minimums(buy_grids, asset)
    sell_grids = enforce_grid_spacing_minimums(sell_grids, asset)

    b_code = str(out.get("budget_code") or budget_code_from_class(str(out.get("budget_class", "50_100"))))
    budget = budget_midpoint_v4(b_code)
    base_frac = float(out.get("base_alloc_frac") or (spec.base_range[0] + spec.base_range[1]) / 2)
    quote_frac = float(out.get("quote_alloc_frac") or (spec.quote_range[0] + spec.quote_range[1]) / 2)
    _, tier_lo, _tier_hi = BUDGET_SHELVES.get(b_code, ("50_100", 50.0, 100.0))
    for budget in (budget, max(float(tier_lo), 10.0)):
        cap = resolve_capacity(
            budget=budget,
            base_alloc_frac=base_frac,
            quote_alloc_frac=quote_frac,
            min_notional=DEFAULT_MIN_NOTIONAL_USDT,
            profile_buy_n=len(buy_grids),
            profile_sell_n=len(sell_grids),
        )
        buy_grids = buy_grids[: cap.buy_grid_capacity]
        sell_grids = sell_grids[: cap.sell_grid_capacity]
    if not buy_grids and not sell_grids:
        out["final_action"] = FinalAction.WAIT.value
        out["buy_grid_count"] = 0
        out["sell_grid_count"] = 0
        out["buy_grid_ladder_pcts"] = []
        out["sell_grid_ladder_pcts"] = []
        return out
    out["buy_grid_ladder_pcts"] = buy_grids
    out["sell_grid_ladder_pcts"] = sell_grids
    out["buy_grid_pcts"] = buy_grids
    out["sell_grid_pcts"] = sell_grids
    out["buy_grid_count"] = len(buy_grids)
    out["sell_grid_count"] = len(sell_grids)
    out["buy_distribution"] = _trim_distribution(list(spec.buy_dist), len(buy_grids))
    out["sell_distribution"] = _trim_distribution(list(spec.sell_dist), len(sell_grids))
    out["scenario"] = spec.name
    base = (spec.base_range[0] + spec.base_range[1]) / 2
    quote = (spec.quote_range[0] + spec.quote_range[1]) / 2
    total = base + quote
    if total > 0:
        base, quote = base / total, quote / total
    out["base_alloc_frac"] = round(base, 4)
    out["quote_alloc_frac"] = round(quote, 4)
    buy_trail = (spec.buy_trail_range[0] + spec.buy_trail_range[1]) / 2
    sell_trail = (spec.sell_trail_range[0] + spec.sell_trail_range[1]) / 2
    if buy_grids:
        out["buy_trailing_pct"] = min(buy_trail, buy_grids[0] * 0.28)
    if sell_grids:
        out["sell_trailing_pct"] = min(sell_trail, sell_grids[0] * 0.28)
    return out


def repair_library_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    raw_route = str(profile.get("route_key") or "")
    out = backfill_library_schema_fields(dict(profile))
    parts = normalize_route_key(str(out.get("route_key") or "")).split("|")
    if len(parts) == 5:
        a, r, s, v, risk = parts
        if r not in REGIME_SHELVES:
            r = {"R18": "R7", "R19": "R10"}.get(r, "R2")
        out["route_key"] = clean_route_key(a, r, s, v, risk)
        out.setdefault("fallback_keys", fallback_keys(out["route_key"]))

    if is_intentional_empty_ladder(out):
        out = repair_distribution_profile(out)
        return repair_fee_profile(out, widen_grids=False)

    legacy_route = "|B" in raw_route or "|F" in raw_route or len(raw_route.split("|")) == 7
    if legacy_route or classify_ladder_issue(out)[0]:
        out = _rebuild_ladders_from_scenario(out)

    for _attempt in range(4):
        if _profile_compliance_ok(out):
            break
        if _attempt == 0 and not legacy_route:
            pass
        elif classify_ladder_issue(out)[0] or not hard_validate_profile(out)[0]:
            out = _rebuild_ladders_from_scenario(out)
        out = repair_fee_profile(out)
        out = repair_min_notional_ladders(out)
        out = repair_grid_ladder_quality(out)
        out = repair_directional_profile(out)
        out = repair_trailing_and_net_room(out)
        out = repair_distribution_profile(out)
        out = _sync_grid_metadata(out)
        if is_intentional_empty_ladder(out):
            break

    if not _profile_compliance_ok(out) and not is_intentional_empty_ladder(out):
        out = _force_spec_compliant_profile(out)

    out = _sync_grid_metadata(out)
    if not _profile_compliance_ok(out) and not is_intentional_empty_ladder(out):
        out = _force_spec_compliant_profile(out)
        out = _sync_grid_metadata(out)

    return repair_fee_profile(out, widen_grids=False)


def repair_v4_template(template: ParamTemplate) -> ParamTemplate:
    params = dict(template.params or {})
    dps = dict(params.get("dps_profile") or {})
    dps = repair_library_profile(dps)

    fa = str(dps.get("final_action") or template.final_action or "")
    if dps.get("fee_class") == "fee_bad" and fa in WAIT_ACTIONS:
        fa = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        dps["final_action"] = fa

    params.update(
        {
            "dps_profile": dps,
            "route_key": dps.get("route_key"),
            "buy_grid_count": dps.get("buy_grid_count"),
            "sell_grid_count": dps.get("sell_grid_count"),
            "buy_grid_ladder_pcts": dps.get("buy_grid_ladder_pcts"),
            "sell_grid_ladder_pcts": dps.get("sell_grid_ladder_pcts"),
            "buy_qty_distribution": [
                x / 100.0 for x in (dps.get("buy_distribution") or [])
            ],
            "sell_qty_distribution": [
                x / 100.0 for x in (dps.get("sell_distribution") or [])
            ],
        }
    )
    for legacy_key in ("buy_distribution", "sell_distribution"):
        if isinstance(params.get(legacy_key), str):
            params.pop(legacy_key, None)
        if dps.get(legacy_key):
            params[legacy_key] = dps[legacy_key]
        else:
            params.pop(legacy_key, None)
    return template.model_copy(
        update={
            "params": params,
            "final_action": fa or template.final_action,
        }
    )
