"""Validate V6 catalog profiles against lattice and module rules."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v6.constants import MAX_GRID_COUNT, MIN_GRID_COUNT, QTY_TEMPLATES
from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile
from app.services.dynamic_param_score.v6.v6_quantizer import (
    has_fractional_violation,
    profit_pct_from_code,
    trailing_pct_from_code,
    min_profit_pct_for_trailing,
)


def validate_profile(profile: V6CatalogProfile) -> List[str]:
    errors: List[str] = []
    if profile.base_allocation_pct % 5 != 0:
        errors.append("base_not_5_step")
    if profile.quote_allocation_pct != 100 - profile.base_allocation_pct:
        errors.append("quote_mismatch")
    if has_fractional_violation(profile):
        errors.append("fractional_lattice_violation")
    if not profile.normal_buy_enabled and profile.buy_grids:
        errors.append("buy_grids_when_normal_buy_disabled")
    for side, grids in (("buy", profile.buy_grids), ("sell", profile.sell_grids)):
        if not grids:
            continue
        if len(grids) < MIN_GRID_COUNT or len(grids) > MAX_GRID_COUNT:
            errors.append(f"{side}_grid_count_out_of_range")
        total = sum(g.amount_pct for g in grids)
        if total != 100:
            errors.append(f"{side}_qty_sum_not_100")
        tpls = QTY_TEMPLATES.get(len(grids), [])
        amounts = tuple(g.amount_pct for g in grids)
        if tpls and amounts not in tpls:
            errors.append(f"{side}_qty_template_invalid")
    if profile.buyback_after_sell_enabled:
        bt = trailing_pct_from_code(profile.buyback_trailing_code)
        bp = profit_pct_from_code(profile.buyback_trigger_code)
        if bp < min_profit_pct_for_trailing(bt):
            errors.append("buyback_below_cost_floor")
    if profile.buyback_after_sell_enabled and not profile.profit_sell_after_buyback_enabled:
        errors.append("profit_sell_missing_after_buyback")
    if profile.profit_sell_after_buyback_enabled and not profile.buyback_after_sell_enabled:
        errors.append("buyback_missing_before_profit_sell")
    return errors
