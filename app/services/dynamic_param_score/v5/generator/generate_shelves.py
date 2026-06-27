"""Core V5 shelf generation — deterministic formula."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import List

from app.services.dynamic_param_score.v5.domain.dimensions import (
    ASSET_CLASSES,
    DIRECTIONS,
    EXPECTED_V5_SHELF_COUNT,
    LIQUIDITY_COSTS,
    REGIMES,
    RISK_POSTURES,
    STRUCTURES,
    VOLATILITIES,
)
from app.services.dynamic_param_score.v5.domain.math_utils import clamp, normalize_distribution, round2
from app.services.dynamic_param_score.v5.domain.route_key import (
    V5RouteParts,
    make_route_key,
    make_scenario_title,
    make_shelf_id,
)
from app.services.dynamic_param_score.v5.domain.types import (
    V5BaseTemplate,
    V5GenerationMeta,
    V5Shelf,
)
from app.services.dynamic_param_score.v5.generator.grid_factory import (
    apply_hard_exposure_invariants,
    is_two_grid_equal_allowed,
    make_distribution,
)
from app.services.dynamic_param_score.v5.generator.grid_formula import compute_grid_spacing
from app.services.dynamic_param_score.v5.generator.modifiers import (
    get_asset_modifier,
    get_direction_modifier,
    get_liquidity_modifier,
    get_risk_modifier,
    get_structure_modifier,
    get_volatility_modifier,
    merge_modifiers,
)
from app.services.dynamic_param_score.v5.generator.policies import (
    make_fallback_policy,
    make_resolver_policy,
    make_scenario_description,
    make_validation_policy,
)
from app.services.dynamic_param_score.v5.generator.regime_profiles import get_regime_base_profile
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf

FORMULA_VERSION = "DPLV5_FORMULA_2"


def make_source_logic_hash(parts: V5RouteParts, base: V5BaseTemplate) -> str:
    payload = {
        "formula": FORMULA_VERSION,
        "route": parts.to_dict(),
        "base": base.to_dict(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def generate_shelf(parts: V5RouteParts) -> V5Shelf:
    route_key = make_route_key(parts)
    shelf_id = make_shelf_id(parts)
    regime_base = get_regime_base_profile(parts.regime)

    modifiers = merge_modifiers(
        get_asset_modifier(parts.asset),
        get_direction_modifier(parts.direction),
        get_structure_modifier(parts.structure),
        get_volatility_modifier(parts.volatility),
        get_risk_modifier(parts.risk),
        get_liquidity_modifier(parts.liquidity),
    )

    grid = compute_grid_spacing(parts)
    sell_grid_levels_pct = grid.sell_grid_levels_pct
    buy_grid_levels_pct = grid.buy_grid_levels_pct
    preferred_grid_count = grid.grid_count
    assumed_cost_floor_pct = grid.assumed_cost_floor_pct

    ctx = {
        "regime": parts.regime,
        "structure": parts.structure,
        "risk": parts.risk,
        "volatility": parts.volatility,
        "liquidity": parts.liquidity,
    }

    sell_mode = modifiers.sell_distribution_mode or regime_base.distribution_intent[0]
    buy_mode = modifiers.buy_distribution_mode or regime_base.distribution_intent[1]

    sell_distribution_pct = normalize_distribution(
        make_distribution(preferred_grid_count, sell_mode, ctx)
    )
    buy_distribution_pct = normalize_distribution(
        make_distribution(preferred_grid_count, buy_mode, ctx)
    )

    target_base_pct = clamp(
        round2(regime_base.target_base_pct + modifiers.base_pct_shift),
        5,
        85,
    )
    target_quote_pct = round2(100 - target_base_pct)

    max_base_exposure_pct = clamp(
        round2(regime_base.max_exposure_pct * modifiers.exposure_multiplier),
        5,
        85,
    )
    active_buy_ladder_max_budget_pct = clamp(
        round2(regime_base.active_buy_ladder_max_pct * modifiers.active_buy_ladder_multiplier),
        2,
        45,
    )

    exposure_clamped = apply_hard_exposure_invariants(
        {
            "regime": parts.regime,
            "structure": parts.structure,
            "risk": parts.risk,
            "volatility": parts.volatility,
            "liquidity": parts.liquidity,
            "max_base_exposure_pct": max_base_exposure_pct,
            "active_buy_ladder_max_budget_pct": active_buy_ladder_max_budget_pct,
        }
    )
    max_base_exposure_pct = exposure_clamped["max_base_exposure_pct"]
    active_buy_ladder_max_budget_pct = exposure_clamped["active_buy_ladder_max_budget_pct"]

    sell_trailing_pct = round2(
        clamp(
            sell_grid_levels_pct[0] * regime_base.trailing_factor * modifiers.trailing_multiplier,
            0.05,
            sell_grid_levels_pct[0] * 0.30,
        )
    )
    buy_trailing_pct = round2(
        clamp(
            buy_grid_levels_pct[0] * regime_base.trailing_factor * modifiers.trailing_multiplier,
            0.05,
            buy_grid_levels_pct[0] * 0.30,
        )
    )

    tp_trigger = round2(
        max(
            regime_base.tp_trigger_pct * modifiers.tp_multiplier,
            assumed_cost_floor_pct + regime_base.min_profit_after_cost_floor_pct,
        )
    )

    def _is_equal_dist(dist: list) -> bool:
        return len(dist) == 2 and abs(dist[0] - 50) < 0.5 and abs(dist[1] - 50) < 0.5

    equal_justified = (
        preferred_grid_count == 2
        and is_two_grid_equal_allowed(ctx)
        and (_is_equal_dist(sell_distribution_pct) or _is_equal_dist(buy_distribution_pct))
    )

    base_template = V5BaseTemplate(
        preferred_grid_count=preferred_grid_count,
        allowed_grid_count_range=(2, 4),
        sell_grid_levels_pct=sell_grid_levels_pct,
        buy_grid_levels_pct=buy_grid_levels_pct,
        sell_distribution_pct=sell_distribution_pct,
        buy_distribution_pct=buy_distribution_pct,
        target_base_pct=target_base_pct,
        target_quote_pct=target_quote_pct,
        max_base_exposure_pct=max_base_exposure_pct,
        active_buy_ladder_max_budget_pct=active_buy_ladder_max_budget_pct,
        sell_trailing_pct=sell_trailing_pct,
        buy_trailing_pct=buy_trailing_pct,
        take_profit_buy_trigger_pct=tp_trigger,
        take_profit_buy_trailing_pct=round2(min(buy_trailing_pct, tp_trigger * 0.45)),
        take_profit_sell_trigger_pct=tp_trigger,
        take_profit_sell_trailing_pct=round2(min(sell_trailing_pct, tp_trigger * 0.45)),
        min_profit_after_cost_floor_pct=grid.min_profit_after_cost_floor_pct,
        execution_safety_buffer_pct=grid.execution_safety_buffer_pct,
        assumed_cost_floor_pct=assumed_cost_floor_pct,
        equal_2_grid_justified=equal_justified,
        grid_reasoning=grid.grid_reasoning.to_dict(),
    )

    shelf = V5Shelf(
        version="DPLV5",
        shelf_id=shelf_id,
        route_key=route_key,
        route_parts=parts,
        scenario_title=make_scenario_title(parts),
        scenario_description=make_scenario_description(parts, base_template.to_dict()),
        base_template=base_template,
        resolver_policy=make_resolver_policy(parts),
        fallback_policy=make_fallback_policy(parts),
        validation_policy=make_validation_policy(parts),
        generation_meta=V5GenerationMeta(
            deterministic_formula_version=FORMULA_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            generated_by="dynamic_param_v5_generator",
            random_used=False,
            source_logic_hash=make_source_logic_hash(parts, base_template),
        ),
    )

    validation = validate_shelf(shelf)
    blockers = [v for v in validation.violations if v.severity in ("BLOCKER", "CRITICAL")]
    if blockers:
        codes = [v.code for v in blockers]
        raise ValueError(f"Generated invalid shelf {shelf_id}: {codes}")

    return shelf


def generate_all_v5_shelves() -> List[V5Shelf]:
    shelves: List[V5Shelf] = []
    for asset in ASSET_CLASSES:
        for regime in REGIMES:
            for direction in DIRECTIONS:
                for structure in STRUCTURES:
                    for volatility in VOLATILITIES:
                        for risk in RISK_POSTURES:
                            for liquidity in LIQUIDITY_COSTS:
                                parts = V5RouteParts(
                                    asset=asset,
                                    regime=regime,
                                    direction=direction,
                                    structure=structure,
                                    volatility=volatility,
                                    risk=risk,
                                    liquidity=liquidity,
                                )
                                shelves.append(generate_shelf(parts))

    if len(shelves) != EXPECTED_V5_SHELF_COUNT:
        raise ValueError(
            f"V5 shelf count mismatch: expected {EXPECTED_V5_SHELF_COUNT}, got {len(shelves)}"
        )

    route_keys = {s.route_key for s in shelves}
    if len(route_keys) != len(shelves):
        raise ValueError(f"Duplicate route keys: {len(shelves) - len(route_keys)}")

    shelf_ids = {s.shelf_id for s in shelves}
    if len(shelf_ids) != len(shelves):
        raise ValueError(f"Duplicate shelf IDs: {len(shelves) - len(shelf_ids)}")

    return shelves
