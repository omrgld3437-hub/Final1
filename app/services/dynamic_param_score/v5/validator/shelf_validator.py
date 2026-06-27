"""V5 shelf validator."""

from __future__ import annotations

from typing import Callable, List

from app.services.dynamic_param_score.v5.domain.math_utils import is_approx_100, is_strictly_increasing, round2, sum_values
from app.services.dynamic_param_score.v5.domain.route_key import make_route_key, make_shelf_id
from app.services.dynamic_param_score.v5.domain.types import (
    ValidationResult,
    ValidationViolation,
    V5Shelf,
)
from app.services.dynamic_param_score.v5.generator.grid_factory import is_two_grid_equal_allowed


def validate_special_risk_rules(
    shelf: V5Shelf,
    add: Callable[..., None],
) -> None:
    regime = shelf.route_parts.regime
    structure = shelf.route_parts.structure
    risk = shelf.route_parts.risk
    t = shelf.base_template

    is_defensive = risk == "K1_DEFENSIVE"
    is_lower_lows = regime == "R10_LOWER_LOWS_DOWNTREND" or structure == "S5_LOWER_LOWS"
    is_strong_downtrend = regime == "R9_STRONG_DOWNTREND" or structure == "S8_BREAKDOWN"
    is_crash = regime == "R8_CRASH"

    if is_defensive and is_lower_lows and t.max_base_exposure_pct > 50:
        add(
            "CRITICAL",
            "DEFENSIVE_LOWER_LOWS_EXPOSURE_TOO_HIGH",
            "defensive lower-lows max exposure must be <= 50",
            50,
            t.max_base_exposure_pct,
        )
    if is_defensive and is_lower_lows and t.active_buy_ladder_max_budget_pct > 30:
        add(
            "CRITICAL",
            "DEFENSIVE_LOWER_LOWS_BUY_LADDER_TOO_HIGH",
            "defensive lower-lows active buy ladder must be <= 30",
            30,
            t.active_buy_ladder_max_budget_pct,
        )
    if is_defensive and is_strong_downtrend and t.max_base_exposure_pct > 40:
        add(
            "CRITICAL",
            "DEFENSIVE_STRONG_DOWNTREND_EXPOSURE_TOO_HIGH",
            "defensive strong downtrend max exposure must be <= 40",
            40,
            t.max_base_exposure_pct,
        )
    if is_defensive and is_crash and t.max_base_exposure_pct > 32:
        add(
            "CRITICAL",
            "DEFENSIVE_CRASH_EXPOSURE_TOO_HIGH",
            "defensive crash exposure must be <= 32",
            32,
            t.max_base_exposure_pct,
        )


def validate_equal_grid_rules(shelf: V5Shelf, add: Callable[..., None]) -> None:
    t = shelf.base_template
    gc = t.preferred_grid_count
    ctx = {
        "regime": shelf.route_parts.regime,
        "structure": shelf.route_parts.structure,
        "risk": shelf.route_parts.risk,
        "volatility": shelf.route_parts.volatility,
        "liquidity": shelf.route_parts.liquidity,
    }

    if gc == 3:
        for dist, side in ((t.sell_distribution_pct, "sell"), (t.buy_distribution_pct, "buy")):
            if len(dist) == 3 and all(abs(v - 33.33) < 0.5 for v in dist):
                add(
                    "CRITICAL",
                    "THREE_GRID_EQUAL_DISTRIBUTION",
                    f"{side} 3-grid equal distribution forbidden",
                )

    if gc == 2:
        for dist, side in ((t.sell_distribution_pct, "sell"), (t.buy_distribution_pct, "buy")):
            if len(dist) == 2 and abs(dist[0] - 50) < 0.5 and abs(dist[1] - 50) < 0.5:
                if not is_two_grid_equal_allowed(ctx):
                    add(
                        "CRITICAL",
                        "TWO_GRID_EQUAL_UNJUSTIFIED",
                        f"{side} 2-grid 50/50 not allowed for this route",
                    )
                elif not t.equal_2_grid_justified:
                    add(
                        "MAJOR",
                        "TWO_GRID_EQUAL_NOT_FLAGGED",
                        f"{side} 2-grid equal should have equal_2_grid_justified=true",
                    )


def validate_fallback_policy(shelf: V5Shelf, add: Callable[..., None]) -> None:
    fp = shelf.fallback_policy
    regime = shelf.route_parts.regime

    if regime == "R8_CRASH" and "R2_BALANCED_RANGE" not in fp.forbidden_fallbacks:
        add("BLOCKER", "R8_MISSING_R2_FORBIDDEN", "R8 crash must forbid R2 balanced fallback")
    if regime == "R15_SPECIAL_STRESS_TRANSITION":
        if "R2_BALANCED_RANGE" not in fp.forbidden_fallbacks:
            add("BLOCKER", "R15_MISSING_R2_FORBIDDEN", "R15 must forbid R2 derivation")
        required = {"R12_CAPITULATION_REACTION", "R7_RECOVERY", "R6_BREAKOUT_CONTINUATION"}
        if not required.issubset(set(fp.nearest_safe_dimensions)):
            add("BLOCKER", "R15_NEAREST_SAFE_MISSING", "R15 nearest safe dimensions incomplete")
    if shelf.route_parts.risk == "K1_DEFENSIVE":
        if "K2_NORMAL_CONTROLLED_RAW" not in fp.forbidden_fallbacks:
            add("BLOCKER", "DEFENSIVE_RAW_FALLBACK", "defensive must forbid raw normal fallback")


def validate_shelf(shelf: V5Shelf) -> ValidationResult:
    violations: List[ValidationViolation] = []
    t = shelf.base_template

    def add(
        severity: ValidationViolation["severity"],
        code: str,
        message: str,
        expected=None,
        actual=None,
    ) -> None:
        violations.append(
            ValidationViolation(
                severity=severity,
                code=code,
                message=message,
                shelf_id=shelf.shelf_id,
                route_key=shelf.route_key,
                expected=expected,
                actual=actual,
            )
        )

    if shelf.version != "DPLV5":
        add("BLOCKER", "INVALID_VERSION", "Shelf version must be DPLV5", "DPLV5", shelf.version)

    if make_route_key(shelf.route_parts) != shelf.route_key:
        add("BLOCKER", "ROUTE_KEY_MISMATCH", "routeKey does not match routeParts")

    if make_shelf_id(shelf.route_parts) != shelf.shelf_id:
        add("BLOCKER", "SHELF_ID_MISMATCH", "shelfId does not match routeParts")

    if shelf.generation_meta.random_used is not False:
        add("BLOCKER", "RANDOM_USED", "random_used must be false")

    total_bq = round2(t.target_base_pct + t.target_quote_pct)
    if abs(total_bq - 100) > 0.02:
        add("CRITICAL", "BASE_QUOTE_SUM_NOT_100", "base + quote must equal 100", 100, total_bq)

    if not is_approx_100(t.sell_distribution_pct):
        add(
            "CRITICAL",
            "SELL_DISTRIBUTION_SUM_NOT_100",
            "sell distribution must sum to 100",
            100,
            sum_values(t.sell_distribution_pct),
        )
    if not is_approx_100(t.buy_distribution_pct):
        add(
            "CRITICAL",
            "BUY_DISTRIBUTION_SUM_NOT_100",
            "buy distribution must sum to 100",
            100,
            sum_values(t.buy_distribution_pct),
        )

    for name, grids, dists in (
        ("sell", t.sell_grid_levels_pct, t.sell_distribution_pct),
        ("buy", t.buy_grid_levels_pct, t.buy_distribution_pct),
    ):
        if len(grids) != t.preferred_grid_count:
            add("BLOCKER", f"{name.upper()}_GRID_COUNT_MISMATCH", f"{name} grid count mismatch")
        if len(dists) != t.preferred_grid_count:
            add("BLOCKER", f"{name.upper()}_DIST_COUNT_MISMATCH", f"{name} distribution count mismatch")
        if not is_strictly_increasing(grids):
            add("CRITICAL", f"{name.upper()}_GRID_NOT_INCREASING", f"{name} grid must be increasing")
        for i, level in enumerate(grids):
            if level <= 0:
                add("CRITICAL", f"{name.upper()}_GRID_NON_POSITIVE", f"{name} grid {i} must be positive")

    sell_trailing_max = round2(t.sell_grid_levels_pct[0] * 0.30)
    if t.sell_trailing_pct > sell_trailing_max + 0.001:
        add(
            "CRITICAL",
            "SELL_TRAILING_TOO_HIGH",
            "sell trailing must be <= first sell grid * 0.30",
            sell_trailing_max,
            t.sell_trailing_pct,
        )

    buy_trailing_max = round2(t.buy_grid_levels_pct[0] * 0.30)
    if t.buy_trailing_pct > buy_trailing_max + 0.001:
        add(
            "CRITICAL",
            "BUY_TRAILING_TOO_HIGH",
            "buy trailing must be <= first buy grid * 0.30",
            buy_trailing_max,
            t.buy_trailing_pct,
        )

    if t.take_profit_buy_trigger_pct <= t.take_profit_buy_trailing_pct:
        add("CRITICAL", "TP_BUY_TRIGGER_NOT_ABOVE_TRAILING", "TP buy trigger must be above trailing")
    if t.take_profit_sell_trigger_pct <= t.take_profit_sell_trailing_pct:
        add("CRITICAL", "TP_SELL_TRIGGER_NOT_ABOVE_TRAILING", "TP sell trigger must be above trailing")

    min_tp = round2(t.assumed_cost_floor_pct + t.min_profit_after_cost_floor_pct)
    if t.take_profit_buy_trigger_pct < min_tp - 0.001:
        add("CRITICAL", "TP_BUY_BELOW_COST_FLOOR", "TP buy trigger below cost floor", min_tp, t.take_profit_buy_trigger_pct)
    if t.take_profit_sell_trigger_pct < min_tp - 0.001:
        add("CRITICAL", "TP_SELL_BELOW_COST_FLOOR", "TP sell trigger below cost floor", min_tp, t.take_profit_sell_trigger_pct)

    min_grid = round2(t.assumed_cost_floor_pct + t.min_profit_after_cost_floor_pct)
    if t.sell_grid_levels_pct[0] < min_grid - 0.001:
        add("CRITICAL", "SELL_GRID_BELOW_COST_FLOOR", "first sell grid below cost floor", min_grid, t.sell_grid_levels_pct[0])
    if t.buy_grid_levels_pct[0] < min_grid - 0.001:
        add("CRITICAL", "BUY_GRID_BELOW_COST_FLOOR", "first buy grid below cost floor", min_grid, t.buy_grid_levels_pct[0])

    validate_special_risk_rules(shelf, add)
    validate_equal_grid_rules(shelf, add)
    validate_fallback_policy(shelf, add)
    validate_grid_scenario_rules(shelf, add)
    validate_grid_reasoning(shelf, add)

    return ValidationResult(ok=len(violations) == 0, violations=violations)


def validate_grid_reasoning(shelf: V5Shelf, add: Callable[..., None]) -> None:
    gr = shelf.base_template.grid_reasoning
    if not gr:
        add("BLOCKER", "GRID_REASONING_MISSING", "grid_reasoning is required on every V5 shelf")
        return
    required = (
        "cost_floor_pct",
        "min_grid_by_cost_pct",
        "vol_grid_pct",
        "scenario_grid_pct",
        "selected_base_first_grid_pct",
        "sell_first_grid_pct",
        "buy_first_grid_pct",
        "expansion_factor",
        "reason",
    )
    for key in required:
        if key not in gr:
            add("MAJOR", "GRID_REASONING_FIELD_MISSING", f"grid_reasoning missing {key}")


def validate_grid_scenario_rules(shelf: V5Shelf, add: Callable[..., None]) -> None:
    t = shelf.base_template
    rp = shelf.route_parts
    if not t.sell_grid_levels_pct or not t.buy_grid_levels_pct:
        return

    sell_first = t.sell_grid_levels_pct[0]
    buy_first = t.buy_grid_levels_pct[0]
    min_grid = round2(t.assumed_cost_floor_pct + t.min_profit_after_cost_floor_pct)

    # Structure/direction asymmetry
    if rp.structure == "S2_RANGE_UPPER":
        if sell_first >= buy_first:
            add(
                "CRITICAL",
                "RANGE_UPPER_SELL_NOT_CLOSER",
                "range upper: sell grid should be closer than buy",
                f"sell<{buy_first}",
                sell_first,
            )
    if rp.structure == "S3_RANGE_LOWER" and rp.regime not in (
        "R8_CRASH",
        "R9_STRONG_DOWNTREND",
        "R10_LOWER_LOWS_DOWNTREND",
    ):
        if buy_first >= sell_first - 0.001:
            add(
                "CRITICAL",
                "RANGE_LOWER_BUY_NOT_CLOSER",
                "range lower: buy grid should be closer than sell when not crash",
            )

    # Crash/downtrend: buy not surface-aggressive
    if rp.regime in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND") or rp.structure in (
        "S5_LOWER_LOWS",
        "S8_BREAKDOWN",
    ):
        if buy_first < sell_first * 0.98:
            pass  # buy deeper — OK
        elif buy_first <= min_grid * 1.15:
            add(
                "CRITICAL",
                "CRASH_BUY_GRID_TOO_SURFACE",
                "crash/downtrend buy grid too close to surface",
                f">{min_grid * 1.15}",
                buy_first,
            )

    # Low vol: not too wide (except crash/downtrend where deep grids are required)
    crash_like = rp.regime in (
        "R8_CRASH",
        "R9_STRONG_DOWNTREND",
        "R10_LOWER_LOWS_DOWNTREND",
        "R12_CAPITULATION_REACTION",
        "R13_HIGH_VOL_DISORDER",
        "R14_LOW_LIQUIDITY_DRIFT",
        "R15_SPECIAL_STRESS_TRANSITION",
    ) or rp.structure in ("S5_LOWER_LOWS", "S8_BREAKDOWN")
    if rp.volatility in ("V1_ULTRA_LOW", "V2_LOW") and not crash_like:
        if rp.liquidity not in ("L3_LOW_LIQUIDITY_HIGH_COST", "L4_EXECUTION_RISKY"):
            if sell_first > 5.5 or buy_first > 6.5:
                add("CRITICAL", "LOW_VOL_GRID_TOO_WIDE", "low volatility grid too wide")

    # High vol / shock: not too narrow
    if rp.volatility in ("V4_HIGH", "V5_SHOCK"):
        if sell_first < 1.6 or buy_first < 1.6:
            add("CRITICAL", "HIGH_VOL_GRID_TOO_NARROW", "high volatility grid too narrow")

    # Low liquidity: wider grids
    if rp.liquidity in ("L3_LOW_LIQUIDITY_HIGH_COST", "L4_EXECUTION_RISKY"):
        if sell_first < min_grid * 1.05:
            add("CRITICAL", "LOW_LIQUIDITY_GRID_TOO_TIGHT", "low liquidity grid too tight vs cost")

    # Defensive range upper: buy not overly aggressive
    if rp.risk == "K1_DEFENSIVE" and rp.structure == "S2_RANGE_UPPER":
        if buy_first < sell_first * 1.08:
            add(
                "MAJOR",
                "DEFENSIVE_RANGE_UPPER_BUY_NOT_DEEP_ENOUGH",
                "defensive range upper should keep buy ladder deeper",
            )

