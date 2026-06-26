"""Build 200k DPS Engine V2 parameter library."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from app.services.dynamic_param_score.param_generator.amount_distribution import (
    geometric_distribution,
    select_distribution_mode,
)
from app.services.dynamic_param_score.param_generator.backtest_sampler import compute_score_prior
from app.services.dynamic_param_score.param_generator.candidate_validator import (
    hard_validate_profile,
)
from app.services.dynamic_param_score.param_generator.feature_bins import (
    BUDGET_CLASSES,
    budget_class_from_usdt,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    apply_side_structure_multiplier,
    compute_first_grid_pct,
    compute_grid_ladder,
    compute_trailing_pct,
    enforce_grid_spacing_minimums,
)
from app.services.dynamic_param_score.param_generator.migration import migrate_pool
from app.services.dynamic_param_score.param_generator.risk_modifiers import (
    budget_grid_count_cap,
    fee_bad_adjustments,
    safety_level_from_context,
    structure_side_multipliers,
    volatility_adjustment,
)
from app.services.dynamic_param_score.param_generator.scenario_matrix import (
    expand_cells_with_variants,
    scenario_cells,
    scenario_key,
    total_primary_combinations,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.precision_generator import generate_pool_v2

DPS_ENGINE_V2 = "DPS_ENGINE_V2"
POOL_VERSION_V3 = "v3.0.0"
POOL_TARGET_V3 = 200_000
NEW_PROFILE_TARGET = 100_000
FAST_TEST_POOL_TARGET = 6_000


def resolve_pool_build_target() -> int:
    raw = os.environ.get("DPS_POOL_TARGET")
    if raw:
        return max(500, int(raw))
    if os.environ.get("DPS_FULL_POOL") == "1":
        return POOL_TARGET_V3
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return int(os.environ.get("DPS_TEST_POOL_SIZE", str(FAST_TEST_POOL_TARGET)))
    return POOL_TARGET_V3

_BUDGET_TIER_MAP = {
    "10_25": "MICRO",
    "25_50": "SMALL",
    "50_100": "SMALL",
    "100_250": "STANDARD",
    "250_500": "MEDIUM",
    "500_1000": "LARGE",
    "1000_PLUS": "WHALE",
}

_BUDGET_MIDPOINT = {
    "10_25": 17.5,
    "25_50": 37.5,
    "50_100": 75.0,
    "100_250": 175.0,
    "250_500": 375.0,
    "500_1000": 750.0,
    "1000_PLUS": 1500.0,
}

_ATR_BY_VOL = {
    "0_10": 0.75,
    "10_25": 0.90,
    "25_50": 1.10,
    "50_75": 1.40,
    "75_90": 1.80,
    "90_100": 2.30,
}


def _profile_id(cell: Dict[str, Any], seq: int) -> str:
    parts = [
        cell.get("regime", "BR")[:3],
        cell.get("asset_class", "AST")[:6],
        cell.get("budget_class", "B50"),
        cell.get("volatility_bin", "V25"),
        cell.get("structure", "NN")[:2],
        cell.get("fee_class", "FEE")[:4],
        f"V2_{seq:06d}",
    ]
    return "_".join(parts).upper()


def _cell_to_template(cell: Dict[str, Any], seq: int) -> Optional[ParamTemplate]:
    asset = cell["asset_class"]
    regime = cell["regime"]
    fee_class = cell["fee_class"]
    structure = cell["structure"]
    vol_bin = cell["volatility_bin"]
    budget_class = cell["budget_class"]
    variant = int(cell.get("variant_idx") or 0)

    budget = _BUDGET_MIDPOINT.get(budget_class, 75.0)
    atr_1h = _ATR_BY_VOL.get(vol_bin, 1.0) * volatility_adjustment(vol_bin)
    fee_pct = {"low_fee": 0.06, "normal_fee": 0.10, "high_fee": 0.14, "fee_bad": 0.20}.get(
        fee_class, 0.10
    )
    spread_pct = 0.02

    widen, grid_delta = fee_bad_adjustments(fee_class)
    buy_mult, sell_mult = structure_side_multipliers(structure)

    trailing = compute_trailing_pct(1.2, asset, fee_class=fee_class)
    first = compute_first_grid_pct(
        asset_class=asset,
        regime=regime,
        atr_1h_pct=atr_1h,
        trailing_pct=trailing,
        total_cost_pct=fee_pct + spread_pct,
    )
    first = round(first * widen, 4)

    base_buy_n = 3 + (variant % 2)
    base_sell_n = 2 + (variant % 2)
    min_n = 5.0
    buy_cap = budget_grid_count_cap(budget_class, budget * 0.5, min_n)
    sell_cap = budget_grid_count_cap(budget_class, budget * 0.5, min_n)
    buy_n = max(1, min(base_buy_n + grid_delta, buy_cap))
    sell_n = max(1, min(base_sell_n + grid_delta, sell_cap))

    buy_grids = compute_grid_ladder(first * buy_mult, buy_n, variant_idx=variant)
    sell_grids = compute_grid_ladder(first * sell_mult, sell_n, variant_idx=variant + 1)
    buy_grids = enforce_grid_spacing_minimums(
        apply_side_structure_multiplier(buy_grids, side="buy", structure=structure, fee_class=fee_class),
        asset,
    )
    sell_grids = enforce_grid_spacing_minimums(
        apply_side_structure_multiplier(sell_grids, side="sell", structure=structure, fee_class=fee_class),
        asset,
    )

    dist_mode = select_distribution_mode(
        risk_level="NORMAL",
        volatility_percentile=50,
        fee_class=fee_class,
        structure=structure,
    )
    buy_dist = geometric_distribution(len(buy_grids), dist_mode)
    sell_dist = geometric_distribution(len(sell_grids), dist_mode)

    safety = safety_level_from_context(fee_class=fee_class, regime=regime, risk_level="NORMAL")
    if fee_class == "fee_bad":
        final_action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        profile_family = "ACTIVE_DEFENSIVE_GRID_PROFILE"
    elif safety == "ACTIVE_DEFENSIVE":
        final_action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        profile_family = "ACTIVE_DEFENSIVE_GRID_PROFILE"
    else:
        final_action = FinalAction.BALANCED_GRID.value
        profile_family = "BALANCED_GRID_PROFILE"

    profile_dict = {
        "profile_id": _profile_id(cell, seq),
        "asset_class": asset,
        "budget_class": budget_class,
        "regime": regime,
        "volatility_bin": vol_bin,
        "structure": structure,
        "fee_class": fee_class,
        "buy_grid_count": len(buy_grids),
        "sell_grid_count": len(sell_grids),
        "buy_grid_pcts": buy_grids,
        "sell_grid_pcts": sell_grids,
        "buy_distribution": [int(x * 100) for x in buy_dist],
        "sell_distribution": [int(x * 100) for x in sell_dist],
        "safety_level": safety,
        "version": DPS_ENGINE_V2,
    }
    ok, _ = hard_validate_profile(profile_dict)
    if not ok:
        return None

    score_prior = compute_score_prior(profile_dict)
    pid = profile_dict["profile_id"]
    buy_spacing = buy_grids[0] if buy_grids else 1.5
    sell_spacing = sell_grids[0] if sell_grids else 1.5

    params: Dict[str, Any] = {
        "buy_grid_count": len(buy_grids),
        "sell_grid_count": len(sell_grids),
        "buy_grid_spacing_pct": buy_spacing,
        "sell_grid_spacing_pct": sell_spacing,
        "buy_spacing_pct": buy_spacing,
        "sell_spacing_pct": sell_spacing,
        "buy_qty_distribution": buy_dist,
        "sell_qty_distribution": sell_dist,
        "trailing_enabled": True,
        "trailing_atr_mult": 0.35,
        "min_trailing_pct": trailing,
        "base_alloc_frac": 0.45,
        "max_base_exposure_extra": 0.08,
        "dps_profile": profile_dict,
        "dps_engine_version": DPS_ENGINE_V2,
        "score_prior": score_prior,
        "rebuy_enabled": True,
        "rebuy_trigger_pct": round(buy_spacing * 1.4, 2),
        "rebuy_trail_pct": trailing,
        "resell_trigger_pct": round(sell_spacing * 1.3, 2),
        "resell_trail_pct": trailing,
    }

    regime_tag = RegimeTag.BALANCED_RANGE.value
    if "DOWNTREND" in regime or regime == "CRASH_RISK":
        regime_tag = RegimeTag.TRENDING_DOWN.value
    elif "UPTREND" in regime:
        regime_tag = RegimeTag.TRENDING_UP.value
    elif vol_bin in ("75_90", "90_100"):
        regime_tag = RegimeTag.RANGE_HIGH_VOL.value
    elif vol_bin == "0_10":
        regime_tag = RegimeTag.RANGE_LOW_VOL.value

    return ParamTemplate(
        template_key=pid,
        version=DPS_ENGINE_V2,
        profile_family=profile_family,
        final_action=final_action,
        score_min=40,
        score_max=85,
        supported_regimes=[regime_tag, RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL", "CAUTION", "DEFENSIVE", "SAFE"],
        budget_tiers=[_BUDGET_TIER_MAP.get(budget_class, "SMALL")],
        exposure_tiers=["LOW_BASE", "TARGET_BASE", "HIGH_BASE", "OVEREXPOSED"],
        headroom_tiers=["NO_HEADROOM", "LOW_HEADROOM", "MID_HEADROOM", "HIGH_HEADROOM"],
        fee_tiers=["FEE_GOOD", "FEE_OK", "FEE_WEAK", "FEE_BAD"],
        liquidity_tiers=["LIQ_GOOD", "LIQ_OK", "LIQ_WEAK"],
        volatility_tiers=["VOL_LOW", "VOL_MID", "VOL_HIGH", "VOL_EXTREME"],
        btc_risk_tiers=["BTC_SAFE", "BTC_NEUTRAL", "BTC_RISK"],
        order_reality_tiers=["ORDER_OK", "ORDER_TIGHT", "ORDER_STRETCHED"],
        min_equity_usdt=max(10.0, _BUDGET_MIDPOINT.get(budget_class, 25) * 0.5),
        min_notional_multiple=2.0,
        params=params,
        deployable=True,
        status="active",
        priority=int(score_prior * 100),
        selection_priority=int(score_prior * 100),
        notes=f"scenario:{scenario_key(cell)};prior:{score_prior}",
    )


def generate_new_profiles(target: int = NEW_PROFILE_TARGET) -> List[ParamTemplate]:
    cells = list(scenario_cells())
    variants = expand_cells_with_variants(cells, variants_per_cell=max(1, target // max(len(cells), 1)))
    out: List[ParamTemplate] = []
    seen: set[str] = set()

    for seq, cell in enumerate(variants):
        if len(out) >= target:
            break
        tmpl = _cell_to_template(cell, seq)
        if tmpl is None:
            continue
        fp = hashlib.sha256(tmpl.template_key.encode()).hexdigest()[:16]
        if fp in seen:
            continue
        seen.add(fp)
        out.append(tmpl)

    # Fill shortfall with perturbed clones
    i = 0
    while len(out) < target and out:
        base = out[i % len(out)]
        clone = base.model_copy(
            update={
                "template_key": f"{base.template_key}_F{i:05d}",
                "params": {**base.params, "perturb_idx": i},
            }
        )
        out.append(clone)
        i += 1

    return out[:target]


def build_dps_v2_pool(
    *,
    migrate_legacy: bool | None = None,
    new_target: int | None = None,
    total_target: int | None = None,
) -> List[ParamTemplate]:
    """Build DPS V2 pool — full 200k production or smaller fast-test subset."""
    target = total_target if total_target is not None else resolve_pool_build_target()

    if target >= POOL_TARGET_V3:
        from app.services.dynamic_param_score.param_generator.pool_disk_cache import (
            try_load_v3_pool_from_disk,
        )

        cached = try_load_v3_pool_from_disk(min_count=POOL_TARGET_V3)
        if cached:
            return cached

    if migrate_legacy is None:
        migrate_legacy = target >= POOL_TARGET_V3

    if new_target is None:
        new_target = NEW_PROFILE_TARGET if migrate_legacy else max(500, target - 80)

    pool: List[ParamTemplate] = []
    seen_keys: set[str] = set()

    if not migrate_legacy:
        from app.services.dynamic_param_score.param_pool.defaults import _pinned_templates

        for t in _pinned_templates():
            if t.template_key not in seen_keys:
                seen_keys.add(t.template_key)
                pool.append(t)
    elif migrate_legacy:
        legacy = generate_pool_v2(100_000)
        migrated, _ = migrate_pool(legacy)
        for t in migrated:
            if t.template_key not in seen_keys:
                seen_keys.add(t.template_key)
                pool.append(t)

    new_profiles = generate_new_profiles(new_target)
    for t in new_profiles:
        if t.template_key not in seen_keys:
            seen_keys.add(t.template_key)
            pool.append(t)

    if len(pool) > target:
        pool = pool[:target]
    elif len(pool) < target:
        i = 0
        while len(pool) < target and pool:
            base = pool[i % len(pool)]
            key = f"{base.template_key}_PAD{i:06d}"
            if key not in seen_keys:
                seen_keys.add(key)
                pool.append(base.model_copy(update={"template_key": key}))
            i += 1

    return pool
