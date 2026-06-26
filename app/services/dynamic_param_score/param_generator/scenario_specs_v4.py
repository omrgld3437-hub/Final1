"""V4 scenario parameter specs — directional grid and allocation rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    regime_codes: Tuple[str, ...]
    structure_codes: Tuple[str, ...]
    base_range: Tuple[float, float]
    quote_range: Tuple[float, float]
    buy_grids: Tuple[float, ...]
    sell_grids: Tuple[float, ...]
    buy_dist: Tuple[int, ...]
    sell_dist: Tuple[int, ...]
    buy_trail_range: Tuple[float, float]
    sell_trail_range: Tuple[float, float]
    rebuy_range: Tuple[float, float]
    resell_range: Tuple[float, float]
    final_action: str = "BALANCED_GRID"
    buy_wider_than_sell: Optional[bool] = None
    sell_wider_than_buy: Optional[bool] = None


def _dist(n: int, mode: str = "geo") -> Tuple[int, ...]:
    if n == 1:
        return (100,)
    if n == 2:
        return (35, 65)
    if n == 4:
        return (10, 20, 30, 40)
    return (15, 30, 55)


SCENARIO_SPECS: dict[str, ScenarioSpec] = {
    "BALANCED_RANGE": ScenarioSpec(
        name="BALANCED_RANGE",
        regime_codes=("R1", "R2"),
        structure_codes=("S1", "S5"),
        base_range=(0.45, 0.55),
        quote_range=(0.45, 0.55),
        buy_grids=(1.30, 3.10, 6.80),
        sell_grids=(1.30, 3.10, 6.80),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.22, 0.28),
        sell_trail_range=(0.22, 0.28),
        rebuy_range=(1.80, 2.40),
        resell_range=(1.80, 2.40),
    ),
    "LOWER_LOWS_WEAK_DOWN_RANGE": ScenarioSpec(
        name="LOWER_LOWS_WEAK_DOWN_RANGE",
        regime_codes=("R6",),
        structure_codes=("S2", "S6", "S8"),
        base_range=(0.25, 0.35),
        quote_range=(0.65, 0.75),
        buy_grids=(1.80, 4.00, 8.00),
        sell_grids=(1.25, 3.00),
        buy_dist=_dist(3),
        sell_dist=(35, 65),
        buy_trail_range=(0.35, 0.55),
        sell_trail_range=(0.30, 0.45),
        rebuy_range=(2.20, 3.00),
        resell_range=(1.60, 2.20),
        buy_wider_than_sell=True,
    ),
    "STRONG_DOWNTREND_RANGE": ScenarioSpec(
        name="STRONG_DOWNTREND_RANGE",
        regime_codes=("R7", "R18"),
        structure_codes=("S2", "S6"),
        base_range=(0.15, 0.25),
        quote_range=(0.75, 0.85),
        buy_grids=(3.00, 7.00, 14.00),
        sell_grids=(1.80, 4.20),
        buy_dist=(12, 28, 60),
        sell_dist=(35, 65),
        buy_trail_range=(0.55, 0.85),
        sell_trail_range=(0.40, 0.60),
        rebuy_range=(3.50, 5.00),
        resell_range=(2.20, 3.20),
        buy_wider_than_sell=True,
    ),
    "CRASH_RISK": ScenarioSpec(
        name="CRASH_RISK",
        regime_codes=("R8",),
        structure_codes=("S2", "S4", "S5"),
        base_range=(0.0, 0.15),
        quote_range=(0.85, 1.0),
        buy_grids=(6.00, 14.00, 28.00),
        sell_grids=(3.00, 7.00, 15.00),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.60, 1.00),
        sell_trail_range=(0.50, 0.80),
        rebuy_range=(4.00, 6.00),
        resell_range=(3.00, 5.00),
        final_action="SELL_MANAGEMENT_ONLY",
        buy_wider_than_sell=True,
    ),
    "HIGHER_HIGHS_WEAK_UP_RANGE": ScenarioSpec(
        name="HIGHER_HIGHS_WEAK_UP_RANGE",
        regime_codes=("R9",),
        structure_codes=("S3", "S7", "S9"),
        base_range=(0.55, 0.70),
        quote_range=(0.30, 0.45),
        buy_grids=(1.20, 2.80),
        sell_grids=(2.00, 4.60, 9.00),
        buy_dist=(35, 65),
        sell_dist=_dist(3),
        buy_trail_range=(0.30, 0.45),
        sell_trail_range=(0.45, 0.70),
        rebuy_range=(1.60, 2.30),
        resell_range=(2.50, 3.50),
        sell_wider_than_buy=True,
    ),
    "STRONG_UPTREND": ScenarioSpec(
        name="STRONG_UPTREND",
        regime_codes=("R10", "R11"),
        structure_codes=("S3", "S7", "S9"),
        base_range=(0.65, 0.80),
        quote_range=(0.20, 0.35),
        buy_grids=(1.60, 3.80),
        sell_grids=(3.00, 7.00, 14.00),
        buy_dist=(35, 65),
        sell_dist=_dist(3),
        buy_trail_range=(0.40, 0.65),
        sell_trail_range=(0.70, 1.20),
        rebuy_range=(2.20, 3.20),
        resell_range=(4.00, 6.00),
        sell_wider_than_buy=True,
    ),
    "WIDE_CHOP": ScenarioSpec(
        name="WIDE_CHOP",
        regime_codes=("R5",),
        structure_codes=("S4",),
        base_range=(0.40, 0.55),
        quote_range=(0.45, 0.60),
        buy_grids=(1.80, 4.00, 8.50),
        sell_grids=(1.70, 3.80, 8.00),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.45, 0.70),
        sell_trail_range=(0.45, 0.70),
        rebuy_range=(2.50, 3.50),
        resell_range=(2.50, 3.50),
    ),
    "OVERSOLD_MEAN_REVERSION": ScenarioSpec(
        name="OVERSOLD_MEAN_REVERSION",
        regime_codes=("R12",),
        structure_codes=("S1", "S2", "S5"),
        base_range=(0.30, 0.45),
        quote_range=(0.55, 0.70),
        buy_grids=(1.30, 3.20, 6.80),
        sell_grids=(1.60, 3.80, 7.50),
        buy_dist=(20, 30, 50),
        sell_dist=_dist(3),
        buy_trail_range=(0.30, 0.45),
        sell_trail_range=(0.35, 0.50),
        rebuy_range=(1.80, 2.60),
        resell_range=(2.20, 3.20),
    ),
    "OVERBOUGHT_MEAN_REVERSION": ScenarioSpec(
        name="OVERBOUGHT_MEAN_REVERSION",
        regime_codes=("R13",),
        structure_codes=("S1", "S3", "S5"),
        base_range=(0.35, 0.50),
        quote_range=(0.50, 0.65),
        buy_grids=(2.00, 4.60, 9.00),
        sell_grids=(1.20, 2.90),
        buy_dist=_dist(3),
        sell_dist=(35, 65),
        buy_trail_range=(0.40, 0.55),
        sell_trail_range=(0.30, 0.45),
        rebuy_range=(2.60, 3.80),
        resell_range=(1.60, 2.40),
    ),
    "LOW_VOL_COMPRESSION": ScenarioSpec(
        name="LOW_VOL_COMPRESSION",
        regime_codes=("R3",),
        structure_codes=("S1", "S5"),
        base_range=(0.45, 0.55),
        quote_range=(0.45, 0.55),
        buy_grids=(1.20, 2.80, 5.80),
        sell_grids=(1.20, 2.80, 5.80),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.25, 0.40),
        sell_trail_range=(0.25, 0.40),
        rebuy_range=(1.60, 2.20),
        resell_range=(1.60, 2.20),
    ),
    "HIGH_VOL_CHOPPY": ScenarioSpec(
        name="HIGH_VOL_CHOPPY",
        regime_codes=("R4",),
        structure_codes=("S4", "S5"),
        base_range=(0.40, 0.55),
        quote_range=(0.45, 0.60),
        buy_grids=(2.20, 5.20, 10.50),
        sell_grids=(2.20, 5.20, 10.50),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.60, 0.95),
        sell_trail_range=(0.60, 0.95),
        rebuy_range=(3.00, 4.50),
        resell_range=(3.00, 4.50),
    ),
    "FEE_BAD_ACTIVE_DEFENSIVE": ScenarioSpec(
        name="FEE_BAD_ACTIVE_DEFENSIVE",
        regime_codes=("R14",),
        structure_codes=("S1", "S2", "S3", "S4", "S5"),
        base_range=(0.40, 0.55),
        quote_range=(0.45, 0.60),
        buy_grids=(1.80, 4.20, 9.00),
        sell_grids=(1.80, 4.20, 9.00),
        buy_dist=_dist(3),
        sell_dist=_dist(3),
        buy_trail_range=(0.35, 0.50),
        sell_trail_range=(0.35, 0.50),
        rebuy_range=(2.50, 3.50),
        resell_range=(2.50, 3.50),
        final_action="ACTIVE_DEFENSIVE_GRID",
    ),
    "MIN_NOTIONAL_EDGE": ScenarioSpec(
        name="MIN_NOTIONAL_EDGE",
        regime_codes=("R2",),
        structure_codes=("S1", "S2", "S3", "S5"),
        base_range=(0.40, 0.55),
        quote_range=(0.45, 0.60),
        buy_grids=(1.50, 3.50, 7.00),
        sell_grids=(1.50, 3.50, 7.00),
        buy_dist=_dist(2),
        sell_dist=_dist(2),
        buy_trail_range=(0.30, 0.45),
        sell_trail_range=(0.30, 0.45),
        rebuy_range=(2.00, 2.80),
        resell_range=(2.00, 2.80),
    ),
    "RECOVERY_AFTER_DUMP": ScenarioSpec(
        name="RECOVERY_AFTER_DUMP",
        regime_codes=("R15",),
        structure_codes=("S1", "S2", "S5"),
        base_range=(0.35, 0.50),
        quote_range=(0.50, 0.65),
        buy_grids=(1.40, 3.40, 7.00),
        sell_grids=(1.80, 4.20, 8.50),
        buy_dist=(20, 30, 50),
        sell_dist=_dist(3),
        buy_trail_range=(0.30, 0.45),
        sell_trail_range=(0.35, 0.50),
        rebuy_range=(2.00, 2.80),
        resell_range=(2.40, 3.40),
    ),
    "POST_PUMP_COOLING": ScenarioSpec(
        name="POST_PUMP_COOLING",
        regime_codes=("R16",),
        structure_codes=("S1", "S3", "S5"),
        base_range=(0.30, 0.45),
        quote_range=(0.55, 0.70),
        buy_grids=(2.00, 5.00, 10.00),
        sell_grids=(1.30, 3.20),
        buy_dist=_dist(3),
        sell_dist=(35, 65),
        buy_trail_range=(0.40, 0.55),
        sell_trail_range=(0.30, 0.45),
        rebuy_range=(2.80, 4.00),
        resell_range=(1.80, 2.60),
    ),
}

PRIORITY_SCENARIO_MAP = {
    "LOWER_LOWS_DOWN_RANGE": "LOWER_LOWS_WEAK_DOWN_RANGE",
    "HIGHER_HIGHS_UP_RANGE": "HIGHER_HIGHS_WEAK_UP_RANGE",
    "STRONG_DOWNTREND_CRASH_DEFENSIVE": "STRONG_DOWNTREND_RANGE",
    "STRONG_UPTREND_BREAKOUT": "STRONG_UPTREND",
    "WIDE_CHOP": "WIDE_CHOP",
    "HIGH_VOL_CHOPPY": "HIGH_VOL_CHOPPY",
    "LOW_VOL_COMPRESSION": "LOW_VOL_COMPRESSION",
    "FEE_BAD_ACTIVE_DEFENSIVE": "FEE_BAD_ACTIVE_DEFENSIVE",
    "LOW_BUDGET_MIN_NOTIONAL_EDGE": "MIN_NOTIONAL_EDGE",
    "MEAN_REVERSION": "OVERSOLD_MEAN_REVERSION",
}


def resolve_scenario_spec(
    regime_code: str,
    structure_code: str,
    fee_code: str = "F3",
) -> ScenarioSpec:
    if fee_code == "F6":
        return SCENARIO_SPECS["FEE_BAD_ACTIVE_DEFENSIVE"]
    for spec in SCENARIO_SPECS.values():
        if regime_code in spec.regime_codes and structure_code in spec.structure_codes:
            return spec
    for spec in SCENARIO_SPECS.values():
        if regime_code in spec.regime_codes:
            return spec
    if structure_code == "S2":
        return SCENARIO_SPECS["LOWER_LOWS_WEAK_DOWN_RANGE"]
    if structure_code == "S3":
        return SCENARIO_SPECS["HIGHER_HIGHS_WEAK_UP_RANGE"]
    return SCENARIO_SPECS["BALANCED_RANGE"]


def interpolate_range(lo: float, hi: float, variant: int, span: int = 7) -> float:
    if span <= 1:
        return (lo + hi) / 2.0
    t = (variant % span) / max(span - 1, 1)
    return round(lo + (hi - lo) * t, 4)


def scale_grids(
    grids: Tuple[float, ...],
    variant: int,
    *,
    widen: float = 1.0,
) -> List[float]:
    factor = widen * (1.0 + 0.04 * (variant % 5))
    return [round(g * factor, 2) for g in grids]


def validate_scenario_direction(
    spec: ScenarioSpec,
    base: float,
    quote: float,
    buy_grids: List[float],
    sell_grids: List[float],
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if spec.buy_wider_than_sell and buy_grids and sell_grids:
        if buy_grids[0] < sell_grids[0] * 1.25 - 1e-6:
            errors.append("buy_not_wider_than_sell")
        if len(buy_grids) > 1 and len(sell_grids) > 1:
            if buy_grids[1] < sell_grids[1] * 1.25 - 1e-6:
                errors.append("buy_second_not_wider")
    if spec.sell_wider_than_buy and buy_grids and sell_grids:
        if sell_grids[0] < buy_grids[0] * 1.25 - 1e-6:
            errors.append("sell_not_wider_than_buy")
        if len(buy_grids) > 1 and len(sell_grids) > 1:
            if sell_grids[1] < buy_grids[1] * 1.25 - 1e-6:
                errors.append("sell_second_not_wider")
    if spec.name in ("LOWER_LOWS_WEAK_DOWN_RANGE", "STRONG_DOWNTREND_RANGE", "CRASH_RISK"):
        if base > 0.35 + 1e-6:
            errors.append("base_too_high_for_down")
        if quote < 0.65 - 1e-6:
            errors.append("quote_too_low_for_down")
    if spec.name in ("HIGHER_HIGHS_WEAK_UP_RANGE", "STRONG_UPTREND"):
        if base < 0.55 - 1e-6:
            errors.append("base_too_low_for_up")
        if quote > 0.45 + 1e-6:
            errors.append("quote_too_high_for_up")
    return len(errors) == 0, errors
