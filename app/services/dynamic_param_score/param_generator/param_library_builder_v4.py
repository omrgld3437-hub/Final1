"""Build DPS Engine V4 parameter library — 300k shelf-routed profiles."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from app.services.dynamic_param_score.param_generator.backtest_sampler import compute_score_prior
from app.services.dynamic_param_score.param_generator.candidate_validator import hard_validate_profile
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    ASSET_SHELVES,
    BUDGET_SHELVES,
    FEE_SHELVES,
    PRIORITY_SCENARIO_TARGETS,
    REGIME_SHELVES,
    STRUCTURE_SHELVES,
    VOL_SHELVES,
    asset_code_from_name,
    budget_code_from_class,
    budget_midpoint_v4,
    clean_route_key,
    dplv4_profile_id,
    dplv4_profile_id_clean,
    fallback_keys,
    fee_code_from_class,
    grid_bias_for_context,
    regime_code_from_name,
    route_key,
    structure_code_from_name,
    structure_to_legacy,
    vol_code_from_bin,
)
from app.services.dynamic_param_score.param_generator.grid_math import enforce_grid_spacing_minimums
from app.services.dynamic_param_score.param_generator.library_repair_v4 import repair_library_profile
from app.services.dynamic_param_score.param_generator.param_library_builder import build_dps_v2_pool
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    PRIORITY_SCENARIO_MAP,
    interpolate_range,
    resolve_scenario_spec,
    scale_grids,
    validate_scenario_direction,
)
from app.services.dynamic_param_score.param_generator.risk_modifiers import budget_grid_count_cap
from app.services.dynamic_param_score.param_generator.v4_resolvers import _trim_distribution, resolve_capacity
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

DPS_ENGINE_V4 = "DPS_ENGINE_V4"
POOL_VERSION_V4 = "v4.0.0"
POOL_TARGET_V4 = 300_000
MIGRATED_V3_TARGET = 200_000
NEW_PROFILE_TARGET_V4 = 100_000
FAST_TEST_POOL_TARGET_V4 = 8_000

_BUDGET_TIER_MAP = {
    "B1": "MICRO",
    "B2": "SMALL",
    "B3": "SMALL",
    "B4": "STANDARD",
    "B5": "MEDIUM",
    "B6": "LARGE",
    "B7": "LARGE",
    "B8": "WHALE",
}

_ASSET_NAME = {code: label for code, (label, _) in ASSET_SHELVES.items()}
_REGIME_NAME = dict(REGIME_SHELVES.items())
_STRUCTURE_NAME = dict(STRUCTURE_SHELVES.items())
_FEE_LEGACY = {
    "F1": "low_fee",
    "F2": "normal_fee",
    "F3": "normal_fee",
    "F4": "high_fee",
    "F5": "high_fee",
    "F6": "fee_bad",
    "F7": "fee_bad",
}
_VOL_LEGACY = {
    "V1": "0_10",
    "V2": "10_25",
    "V3": "25_50",
    "V4": "50_75",
    "V5": "90_100",
}


def resolve_pool_build_target_v4() -> int:
    raw = os.environ.get("DPS_POOL_TARGET")
    if raw:
        return max(500, int(raw))
    if os.environ.get("DPS_FULL_POOL") == "1":
        return POOL_TARGET_V4
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return int(os.environ.get("DPS_TEST_POOL_SIZE", str(FAST_TEST_POOL_TARGET_V4)))
    return POOL_TARGET_V4


def _behavior_fingerprint(profile: Dict[str, Any]) -> str:
    parts = [
        str(profile.get("route_key", "")),
        str(profile.get("base_alloc_frac", "")),
        str(profile.get("buy_grid_pcts", "")),
        str(profile.get("sell_grid_pcts", "")),
        str(profile.get("buy_grid_count", "")),
        str(profile.get("sell_grid_count", "")),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def _regime_tag_for_code(regime_code: str) -> str:
    name = _REGIME_NAME.get(regime_code, "BALANCED_RANGE")
    if "DOWNTREND" in name or regime_code in ("R6", "R7", "R8"):
        return RegimeTag.TRENDING_DOWN.value
    if "UPTREND" in name or regime_code in ("R9", "R10", "R11"):
        return RegimeTag.TRENDING_UP.value
    if regime_code in ("R3", "R1"):
        return RegimeTag.RANGE_LOW_VOL.value
    if regime_code in ("R4", "R5"):
        return RegimeTag.RANGE_HIGH_VOL.value
    if regime_code == "R8":
        return RegimeTag.DUMP_RISK.value
    return RegimeTag.BALANCED_RANGE.value


def _fee_widen(fee_code: str) -> float:
    if fee_code == "F6":
        return 1.25
    if fee_code in ("F4", "F5"):
        return 1.12
    return 1.0


def _cell_to_template_v4(cell: Dict[str, Any], seq: int) -> Optional[ParamTemplate]:
    a_code = cell.get("asset_code") or asset_code_from_name(str(cell.get("asset_class", "A3")))
    b_code = cell.get("budget_code") or budget_code_from_class(str(cell.get("budget_class", "B3")))
    r_code = cell.get("regime_code") or regime_code_from_name(str(cell.get("regime", "R2")))
    s_code = cell.get("structure_code") or structure_code_from_name(str(cell.get("structure", "S1")))
    v_code = cell.get("vol_code") or vol_code_from_bin(str(cell.get("volatility_bin", "V3")))
    f_code = cell.get("fee_code") or fee_code_from_class(str(cell.get("fee_class", "F3")))
    variant = int(cell.get("variant_idx") or 0)
    risk = str(cell.get("risk_class") or "NORMAL")

    asset_name = _ASSET_NAME.get(a_code, "MID_CAP_NORMAL")
    regime_name = _REGIME_NAME.get(r_code, "BALANCED_RANGE")
    structure_legacy = structure_to_legacy(s_code)
    fee_legacy = _FEE_LEGACY.get(f_code, "normal_fee")
    vol_legacy = _VOL_LEGACY.get(v_code, "25_50")
    budget_label = BUDGET_SHELVES.get(b_code, ("50_100", 50, 100))[0]

    spec = resolve_scenario_spec(r_code, s_code, f_code)
    widen = _fee_widen(f_code)

    base = interpolate_range(spec.base_range[0], spec.base_range[1], variant)
    quote = interpolate_range(spec.quote_range[0], spec.quote_range[1], variant)
    total = base + quote
    if total > 0:
        base, quote = base / total, quote / total

    buy_grids = scale_grids(spec.buy_grids, variant, widen=widen)
    sell_grids = scale_grids(spec.sell_grids, variant, widen=widen)

    budget = budget_midpoint_v4(b_code)
    min_n = float(DEFAULT_MIN_NOTIONAL_USDT)
    _, tier_lo, _tier_hi = BUDGET_SHELVES.get(b_code, ("50_100", 50.0, 100.0))
    buy_cap = budget_grid_count_cap(budget_label, budget * quote, min_n)
    sell_cap = budget_grid_count_cap(budget_label, budget * base, min_n)

    if b_code in ("B1", "B2") or r_code == "R16":
        buy_grids = buy_grids[: min(len(buy_grids), buy_cap)]
        sell_grids = sell_grids[: min(len(sell_grids), sell_cap)]

    for test_budget in (budget, max(float(tier_lo), 10.0)):
        cap = resolve_capacity(
            budget=test_budget,
            base_alloc_frac=base,
            quote_alloc_frac=quote,
            min_notional=min_n,
            profile_buy_n=len(buy_grids),
            profile_sell_n=len(sell_grids),
        )
        buy_grids = buy_grids[: cap.buy_grid_capacity]
        sell_grids = sell_grids[: cap.sell_grid_capacity]

    if buy_grids and tier_lo * quote < min_n * 0.99:
        buy_grids = []
    if sell_grids and tier_lo * base < min_n * 0.99:
        sell_grids = []
    if not buy_grids and not sell_grids:
        return None

    buy_grids = enforce_grid_spacing_minimums(buy_grids, asset_name)
    sell_grids = enforce_grid_spacing_minimums(sell_grids, asset_name)

    if not buy_grids or not sell_grids:
        return None

    buy_n = len(buy_grids)
    sell_n = len(sell_grids)

    buy_dist = _trim_distribution(list(spec.buy_dist), len(buy_grids))
    sell_dist = _trim_distribution(list(spec.sell_dist), len(sell_grids))

    ok_dir, _ = validate_scenario_direction(spec, base, quote, buy_grids, sell_grids)
    if not ok_dir:
        return None

    buy_trail = interpolate_range(spec.buy_trail_range[0], spec.buy_trail_range[1], variant)
    sell_trail = interpolate_range(spec.sell_trail_range[0], spec.sell_trail_range[1], variant)
    if f_code == "F6":
        cap = buy_grids[0] * 0.28
        buy_trail = min(buy_trail, cap)
        sell_trail = min(sell_trail, sell_grids[0] * 0.28)

    rk = clean_route_key(a_code, r_code, s_code, v_code, risk)
    fb = fallback_keys(rk)
    pid = dplv4_profile_id_clean(cell, seq=seq)

    profile_dict: Dict[str, Any] = {
        "profile_id": pid,
        "route_key": rk,
        "fallback_keys": fb,
        "asset_class": asset_name,
        "asset_code": a_code,
        "budget_class": budget_label,
        "budget_code": b_code,
        "regime": regime_name,
        "regime_code": r_code,
        "structure": structure_legacy,
        "structure_code": s_code,
        "volatility_bin": vol_legacy,
        "vol_code": v_code,
        "fee_class": fee_legacy,
        "fee_code": f_code,
        "risk_class": risk,
        "scenario": spec.name,
        "base_alloc_frac": round(base, 4),
        "quote_alloc_frac": round(quote, 4),
        "buy_grid_count": len(buy_grids),
        "sell_grid_count": len(sell_grids),
        "buy_grid_pcts": buy_grids,
        "sell_grid_pcts": sell_grids,
        "buy_grid_ladder_pcts": buy_grids,
        "sell_grid_ladder_pcts": sell_grids,
        "buy_distribution": buy_dist,
        "sell_distribution": sell_dist,
        "buy_trailing_pct": buy_trail,
        "sell_trailing_pct": sell_trail,
        "grid_bias": grid_bias_for_context(s_code, r_code),
        "behavior_fingerprint": "",
        "safety_level": "ACTIVE_DEFENSIVE" if f_code == "F6" else "ACTIVE_NORMAL",
        "version": DPS_ENGINE_V4,
    }
    profile_dict["behavior_fingerprint"] = _behavior_fingerprint(profile_dict)
    profile_dict = repair_library_profile(profile_dict)

    ok, _ = hard_validate_profile(profile_dict)
    if not ok:
        return None

    score_prior = compute_score_prior(profile_dict)
    final_action = spec.final_action
    if f_code == "F6":
        final_action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
    elif spec.name == "CRASH_RISK":
        final_action = FinalAction.SELL_MANAGEMENT_ONLY.value

    profile_family = {
        FinalAction.ACTIVE_DEFENSIVE_GRID.value: "ACTIVE_DEFENSIVE_GRID_PROFILE",
        FinalAction.SELL_MANAGEMENT_ONLY.value: "SELL_MANAGEMENT_ONLY",
    }.get(final_action, "BALANCED_GRID_PROFILE")

    regime_tag = _regime_tag_for_code(r_code)
    buy_spacing = buy_grids[0]
    sell_spacing = sell_grids[0]

    params: Dict[str, Any] = {
        "buy_grid_count": len(buy_grids),
        "sell_grid_count": len(sell_grids),
        "buy_grid_ladder_pcts": buy_grids,
        "sell_grid_ladder_pcts": sell_grids,
        "buy_qty_distribution": [x / 100.0 for x in buy_dist],
        "sell_qty_distribution": [x / 100.0 for x in sell_dist],
        "base_alloc_frac": base,
        "quote_alloc_frac": quote,
        "trailing_enabled": True,
        "buy_trailing_pct": buy_trail,
        "sell_trailing_pct": sell_trail,
        "min_trailing_pct": min(buy_trail, sell_trail),
        "rebuy_enabled": True,
        "rebuy_trigger_pct": interpolate_range(spec.rebuy_range[0], spec.rebuy_range[1], variant),
        "rebuy_trail_pct": buy_trail,
        "resell_trigger_pct": interpolate_range(spec.resell_range[0], spec.resell_range[1], variant),
        "resell_trail_pct": sell_trail,
        "dps_profile": profile_dict,
        "dps_engine_version": DPS_ENGINE_V4,
        "score_prior": score_prior,
        "route_key": rk,
        "scenario": spec.name,
    }

    return ParamTemplate(
        template_key=pid,
        version=DPS_ENGINE_V4,
        profile_family=profile_family,
        final_action=final_action,
        score_min=35,
        score_max=90,
        supported_regimes=[regime_tag, RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE", "SAFE"],
        budget_tiers=[_BUDGET_TIER_MAP.get(b_code, "SMALL")],
        exposure_tiers=["LOW_BASE", "TARGET_BASE", "HIGH_BASE", "OVEREXPOSED"],
        headroom_tiers=["NO_HEADROOM", "LOW_HEADROOM", "MID_HEADROOM", "HIGH_HEADROOM"],
        fee_tiers=["FEE_GOOD", "FEE_OK", "FEE_WEAK", "FEE_BAD"],
        liquidity_tiers=["LIQ_GOOD", "LIQ_OK", "LIQ_WEAK"],
        volatility_tiers=["VOL_LOW", "VOL_MID", "VOL_HIGH", "VOL_EXTREME"],
        btc_risk_tiers=["BTC_SAFE", "BTC_NEUTRAL", "BTC_RISK"],
        order_reality_tiers=["ORDER_OK", "ORDER_TIGHT", "ORDER_STRETCHED"],
        min_equity_usdt=max(10.0, budget * 0.5),
        min_notional_multiple=2.0,
        params=params,
        deployable=True,
        status="active",
        priority=int(score_prior * 100),
        selection_priority=int(score_prior * 100),
        notes=f"route:{rk};scenario:{spec.name};prior:{score_prior}",
    )


def _priority_cells() -> Iterator[Dict[str, Any]]:
    """Generate cells for the +100k priority scenario profiles."""
    asset_codes = list(ASSET_SHELVES.keys())
    budget_codes = list(BUDGET_SHELVES.keys())
    vol_codes = list(VOL_SHELVES.keys())
    fee_codes = ["F3", "F4", "F6"]

    for priority_name, target in PRIORITY_SCENARIO_TARGETS.items():
        spec_name = PRIORITY_SCENARIO_MAP[priority_name]
        from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import SCENARIO_SPECS

        spec = SCENARIO_SPECS[spec_name]
        count = 0
        variant = 0
        for a in asset_codes:
            for b in budget_codes:
                for r in spec.regime_codes:
                    for s in spec.structure_codes:
                        for v in vol_codes:
                            for f in fee_codes:
                                if count >= target:
                                    break
                                yield {
                                    "asset_code": a,
                                    "budget_code": b,
                                    "regime_code": r,
                                    "structure_code": s,
                                    "vol_code": v,
                                    "fee_code": f,
                                    "variant_idx": variant,
                                    "priority_bucket": priority_name,
                                    "risk_class": "DEFENSIVE" if variant % 3 == 0 else "NORMAL",
                                }
                                count += 1
                                variant += 1
                            if count >= target:
                                break
                        if count >= target:
                            break
                    if count >= target:
                        break
                if count >= target:
                    break
            if count >= target:
                break


def _shelf_cells() -> Iterator[Dict[str, Any]]:
    """Full shelf coverage for fast-test and gap fill."""
    for a_code in ASSET_SHELVES:
        for b_code in BUDGET_SHELVES:
            for r_code in REGIME_SHELVES:
                for s_code in STRUCTURE_SHELVES:
                    for v_code in VOL_SHELVES:
                        for f_code in FEE_SHELVES:
                            if f_code == "F7":
                                continue
                            yield {
                                "asset_code": a_code,
                                "budget_code": b_code,
                                "regime_code": r_code,
                                "structure_code": s_code,
                                "vol_code": v_code,
                                "fee_code": f_code,
                                "variant_idx": 0,
                                "risk_class": (
                                    "DEFENSIVE"
                                    if r_code in ("R6", "R7", "R8", "R12") and v_code in ("V3", "V4", "V5")
                                    else "NORMAL"
                                ),
                            }


def generate_v4_profiles(target: int) -> List[ParamTemplate]:
    cells = list(_priority_cells()) if target >= NEW_PROFILE_TARGET_V4 else list(_shelf_cells())
    if len(cells) < target:
        expanded: List[Dict[str, Any]] = []
        for i, cell in enumerate(cells):
            for v in range(max(1, target // max(len(cells), 1))):
                expanded.append({**cell, "variant_idx": v})
                if len(expanded) >= target:
                    break
            if len(expanded) >= target:
                break
        cells = expanded[:target]

    out: List[ParamTemplate] = []
    seen_fp: set[str] = set()
    seen_keys: set[str] = set()

    for seq, cell in enumerate(cells):
        if len(out) >= target:
            break
        tmpl = _cell_to_template_v4(cell, seq)
        if tmpl is None:
            continue
        fp = (tmpl.params or {}).get("dps_profile", {}).get("behavior_fingerprint", "")
        if fp in seen_fp or tmpl.template_key in seen_keys:
            continue
        seen_fp.add(fp)
        seen_keys.add(tmpl.template_key)
        out.append(tmpl)

    i = 0
    while len(out) < target and out:
        base = out[i % len(out)]
        cell = (base.params or {}).get("dps_profile", {})
        new_cell = {**cell, "variant_idx": int(cell.get("variant_idx", 0)) + i + 100}
        tmpl = _cell_to_template_v4(new_cell, len(out) + i)
        if tmpl and tmpl.template_key not in seen_keys:
            seen_keys.add(tmpl.template_key)
            out.append(tmpl)
        i += 1
        if i > target * 3:
            break

    return out[:target]


def _enrich_v3_template(t: ParamTemplate, seq: int) -> ParamTemplate:
    """Upgrade a v3 template with V4 route_key and ladder fields."""
    dps = dict((t.params or {}).get("dps_profile") or {})
    if dps.get("route_key") and dps.get("buy_grid_ladder_pcts"):
        return t

    a_code = asset_code_from_name(str(dps.get("asset_class", "MID_CAP")))
    b_code = budget_code_from_class(str(dps.get("budget_class", "50_100")))
    r_code = regime_code_from_name(str(dps.get("regime", "BALANCED_RANGE")))
    s_code = structure_code_from_name(str(dps.get("structure", "neither")))
    v_code = vol_code_from_bin(str(dps.get("volatility_bin", "25_50")))
    f_code = fee_code_from_class(str(dps.get("fee_class", "normal_fee")))

    buy_grids = list(dps.get("buy_grid_pcts") or [])
    sell_grids = list(dps.get("sell_grid_pcts") or [])
    if not buy_grids:
        spacing = float((t.params or {}).get("buy_grid_spacing_pct") or 1.5)
        n = int((t.params or {}).get("buy_grid_count") or 2)
        buy_grids = [round(spacing * (i + 1) * 1.8, 2) for i in range(max(n, 1))]
    if not sell_grids:
        spacing = float((t.params or {}).get("sell_grid_spacing_pct") or 1.5)
        n = int((t.params or {}).get("sell_grid_count") or 2)
        sell_grids = [round(spacing * (i + 1) * 1.8, 2) for i in range(max(n, 1))]

    rk = clean_route_key(a_code, r_code, s_code, v_code)
    pid = dps.get("profile_id") or t.template_key
    if not str(pid).startswith("DPLV4_"):
        pid = dplv4_profile_id_clean(
            {
                "asset_code": a_code,
                "regime_code": r_code,
                "structure_code": s_code,
                "vol_code": v_code,
            },
            seq=seq,
        )

    dps.update(
        {
            "profile_id": pid,
            "route_key": rk,
            "fallback_keys": fallback_keys(rk),
            "buy_grid_ladder_pcts": buy_grids,
            "sell_grid_ladder_pcts": sell_grids,
            "buy_grid_pcts": buy_grids,
            "sell_grid_pcts": sell_grids,
            "buy_grid_count": len(buy_grids),
            "sell_grid_count": len(sell_grids),
            "asset_code": a_code,
            "budget_code": b_code,
            "regime_code": r_code,
            "structure_code": s_code,
            "vol_code": v_code,
            "fee_code": f_code,
            "asset_class": _ASSET_NAME.get(a_code, "MID_CAP_NORMAL"),
            "regime": _REGIME_NAME.get(r_code, "BALANCED_RANGE"),
            "structure": structure_to_legacy(s_code),
            "volatility_bin": _VOL_LEGACY.get(v_code, "25_50"),
            "fee_class": _FEE_LEGACY.get(f_code, "normal_fee"),
            "scenario": _REGIME_NAME.get(r_code, "BALANCED_RANGE"),
            "risk_class": "NORMAL",
            "version": DPS_ENGINE_V4,
        }
    )
    dps = repair_library_profile(dps)
    dps["behavior_fingerprint"] = _behavior_fingerprint(dps)

    params = dict(t.params or {})
    params.update(
        {
            "buy_grid_ladder_pcts": dps.get("buy_grid_ladder_pcts") or buy_grids,
            "sell_grid_ladder_pcts": dps.get("sell_grid_ladder_pcts") or sell_grids,
            "buy_grid_count": dps.get("buy_grid_count"),
            "sell_grid_count": dps.get("sell_grid_count"),
            "dps_profile": dps,
            "dps_engine_version": DPS_ENGINE_V4,
            "route_key": dps.get("route_key") or rk,
        }
    )
    return t.model_copy(update={"template_key": pid, "version": DPS_ENGINE_V4, "params": params})


def build_dps_v4_pool(
    *,
    total_target: int | None = None,
    migrate_v3: bool | None = None,
) -> List[ParamTemplate]:
    """Build V4 pool — 200k migrated v3 + 100k priority shelf profiles."""
    target = total_target if total_target is not None else resolve_pool_build_target_v4()

    if target >= POOL_TARGET_V4:
        from app.services.dynamic_param_score.param_generator.pool_disk_cache_v4 import (
            try_load_v4_pool_from_disk,
        )

        cached = try_load_v4_pool_from_disk(min_count=POOL_TARGET_V4)
        if cached:
            return cached

    if migrate_v3 is None:
        migrate_v3 = target >= MIGRATED_V3_TARGET + 10_000

    pool: List[ParamTemplate] = []
    seen: set[str] = set()

    if migrate_v3 and target > NEW_PROFILE_TARGET_V4:
        v3_count = min(MIGRATED_V3_TARGET, target - min(NEW_PROFILE_TARGET_V4, target // 3))
        v3_pool = build_dps_v2_pool(total_target=v3_count, migrate_legacy=True)
        for i, t in enumerate(v3_pool):
            enriched = _enrich_v3_template(t, i)
            if enriched.template_key not in seen:
                seen.add(enriched.template_key)
                pool.append(enriched)

    new_target = target - len(pool)
    if new_target > 0:
        new_profiles = generate_v4_profiles(new_target)
        for t in new_profiles:
            if t.template_key not in seen:
                seen.add(t.template_key)
                pool.append(t)

    if len(pool) > target:
        pool = pool[:target]
    elif len(pool) < target and pool:
        i = 0
        while len(pool) < target:
            base = pool[i % len(pool)]
            key = f"{base.template_key}_V4PAD{i:06d}"
            if key not in seen:
                seen.add(key)
                pool.append(base.model_copy(update={"template_key": key}))
            i += 1
            if i > target * 2:
                break

    return pool
