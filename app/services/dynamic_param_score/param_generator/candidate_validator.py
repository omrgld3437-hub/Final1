"""Hard and soft validation for DPS Engine V2 parameter profiles."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    MAX_TRAILING_FRAC,
    MIN_GRID_SPACING,
    MIN_NET_ROOM,
)


def _first_grid(side_grids: List[float]) -> float:
    return float(side_grids[0]) if side_grids else 0.0


def hard_validate_profile(profile: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    asset = str(profile.get("asset_class") or "MID_CAP")
    asset_min = ASSET_MIN_GRID.get(asset, 1.80)
    min_spacing = MIN_GRID_SPACING.get(asset, 1.50)
    min_net = MIN_NET_ROOM.get(asset, 1.20)
    is_v4 = bool(profile.get("version") == "DPS_ENGINE_V4" or profile.get("route_key"))
    max_trail_frac = 0.30 if is_v4 else MAX_TRAILING_FRAC.get(asset, 0.28)

    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)

    for side in ("buy", "sell"):
        grids = profile.get(f"{side}_grid_pcts") or profile.get(f"{side}_grid_ladder_pcts") or []
        side_n = buy_n if side == "buy" else sell_n
        if not grids:
            if side_n > 0 and (profile.get("version") == "DPS_ENGINE_V4" or profile.get("route_key")):
                errors.append(f"{side}_grid_ladder_pcts_null")
            continue
        first = _first_grid(grids)
        if first < asset_min - 1e-6:
            errors.append(f"{side}_first_grid_below_asset_min")
        if first < 1.0 - 1e-6:
            errors.append(f"{side}_first_grid_below_1pct")
        for i in range(1, len(grids)):
            if grids[i] < grids[i - 1] + min_spacing - 1e-6:
                errors.append(f"{side}_grid_spacing_too_tight")
            ratio = grids[i] / max(first, 0.01)
            min_ratio = {1: 2.2, 2: 4.5, 3: 7.0}.get(i, 2.2)
            if i == 1 and ratio < min_ratio - 1e-6:
                errors.append(f"{side}_second_grid_ratio_fail")
            if i == 2 and ratio < 4.5 - 1e-6:
                errors.append(f"{side}_third_grid_ratio_fail")
            if i == 3 and ratio < 7.0 - 1e-6:
                errors.append(f"{side}_fourth_grid_ratio_fail")

        trail = float(profile.get(f"{side}_trailing_pct") or profile.get("trailing_pct") or 0)
        if trail > first * max_trail_frac + 1e-6:
            errors.append(f"{side}_trailing_too_high")
            if is_v4:
                errors.append("trailing_too_large_fail")
        if grids and trail > 0 and (grids[0] - trail) < min_net - 1e-6:
            errors.append(f"{side}_net_room_too_small")

    for side in ("buy", "sell"):
        dist = profile.get(f"{side}_distribution") or []
        if dist and abs(sum(dist) - 100) > 0.5 and abs(sum(dist) - 1.0) > 0.01:
            errors.append(f"{side}_distribution_not_100")
        if len(dist) == 2 and abs(float(dist[0]) - float(dist[1])) < 3:
            errors.append("equal_two_grid_distribution_fail")
        if len(dist) == 3 and max(dist) - min(dist) < 5:
            errors.append("equal_three_grid_distribution_fail")
        if len(dist) >= 2 and dist[-1] < dist[0]:
            errors.append(f"{side}_far_grid_underweighted")

    if profile.get("fee_class") == "fee_bad" and profile.get("safety_level") == "WAIT":
        errors.append("fee_bad_must_not_wait")

    if profile.get("version") and profile.get("version") != "DPS_ENGINE_V2":
        pass

    return len(errors) == 0, errors


def soft_validate_profile(profile: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Return soft score 0-1 and warning codes."""
    warnings: List[str] = []
    score = 1.0
    structure = profile.get("structure") or "neither"
    buy_grids = profile.get("buy_grid_pcts") or []
    sell_grids = profile.get("sell_grid_pcts") or []

    if structure == "lower_lows_only" and buy_grids and sell_grids:
        if buy_grids[0] <= sell_grids[0] * 1.05:
            warnings.append("lower_lows_but_buy_grid_too_close")
            score -= 0.15

    if structure == "higher_highs_only" and buy_grids and sell_grids:
        if sell_grids[0] <= buy_grids[0] * 1.05:
            warnings.append("higher_highs_but_sell_grid_too_close")
            score -= 0.15

    if profile.get("fee_class") == "fee_bad":
        first = _first_grid(buy_grids or sell_grids)
        if first < ASSET_MIN_GRID.get(profile.get("asset_class", "MID_CAP"), 1.8) * 1.1:
            warnings.append("fee_bad_but_grid_not_widened")
            score -= 0.2

    vol_bin = profile.get("volatility_bin") or "25_50"
    if vol_bin in ("75_90", "90_100") and buy_grids:
        if buy_grids[0] < 1.5:
            warnings.append("high_vol_but_grid_too_close")
            score -= 0.1

    return max(0.0, score), warnings
