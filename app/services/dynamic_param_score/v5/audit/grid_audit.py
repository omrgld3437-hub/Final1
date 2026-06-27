"""Grid logic family audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from app.services.dynamic_param_score.v5.domain.math_utils import round2
from app.services.dynamic_param_score.v5.domain.types import V5Shelf


@dataclass
class GridFamilyStats:
    count: int = 0
    sell_first_min: float = 999.0
    sell_first_max: float = 0.0
    buy_first_min: float = 999.0
    buy_first_max: float = 0.0
    trailing_violations: int = 0
    issues: List[str] = field(default_factory=list)

    def observe(self, shelf: V5Shelf) -> None:
        t = shelf.base_template
        sell0 = t.sell_grid_levels_pct[0]
        buy0 = t.buy_grid_levels_pct[0]
        self.count += 1
        self.sell_first_min = min(self.sell_first_min, sell0)
        self.sell_first_max = max(self.sell_first_max, sell0)
        self.buy_first_min = min(self.buy_first_min, buy0)
        self.buy_first_max = max(self.buy_first_max, buy0)
        if t.sell_trailing_pct > round2(sell0 * 0.30) + 0.001:
            self.trailing_violations += 1
        if t.buy_trailing_pct > round2(buy0 * 0.30) + 0.001:
            self.trailing_violations += 1


def audit_grid_logic(shelves: List[V5Shelf]) -> dict:
    families: Dict[str, GridFamilyStats] = {
        "low_vol": GridFamilyStats(),
        "high_vol_shock": GridFamilyStats(),
        "crash_downtrend": GridFamilyStats(),
        "range_upper": GridFamilyStats(),
        "range_lower": GridFamilyStats(),
        "L4_execution_risky": GridFamilyStats(),
    }
    trailing_total_violations = 0
    range_upper_ok = 0
    range_upper_bad = 0
    range_lower_ok = 0
    range_lower_bad = 0
    crash_buy_deep_ok = 0
    crash_buy_deep_bad = 0
    low_vol_too_wide = 0
    high_vol_too_narrow = 0
    l4_grid_count_high = 0

    for shelf in shelves:
        rp = shelf.route_parts
        t = shelf.base_template
        sell0 = t.sell_grid_levels_pct[0]
        buy0 = t.buy_grid_levels_pct[0]
        min_grid = round2(t.assumed_cost_floor_pct + t.min_profit_after_cost_floor_pct)

        if t.sell_trailing_pct > round2(sell0 * 0.30) + 0.001:
            trailing_total_violations += 1
        if t.buy_trailing_pct > round2(buy0 * 0.30) + 0.001:
            trailing_total_violations += 1

        if rp.volatility in ("V1_ULTRA_LOW", "V2_LOW"):
            families["low_vol"].observe(shelf)
            if sell0 > 6.0 and rp.regime not in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R15_SPECIAL_STRESS_TRANSITION"):
                low_vol_too_wide += 1

        if rp.volatility in ("V4_HIGH", "V5_SHOCK"):
            families["high_vol_shock"].observe(shelf)
            if sell0 < 1.5:
                high_vol_too_narrow += 1

        if rp.regime in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND") or rp.structure in (
            "S5_LOWER_LOWS",
            "S8_BREAKDOWN",
        ):
            families["crash_downtrend"].observe(shelf)
            needs_deep_buy = rp.direction != "D1_UP_BIAS" and (
                rp.regime in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND")
                or rp.structure in ("S5_LOWER_LOWS", "S8_BREAKDOWN")
            )
            if not needs_deep_buy:
                crash_buy_deep_ok += 1
            elif buy0 >= sell0 * 1.02:
                crash_buy_deep_ok += 1
            else:
                crash_buy_deep_bad += 1

        if rp.structure == "S2_RANGE_UPPER":
            families["range_upper"].observe(shelf)
            if sell0 < buy0:
                range_upper_ok += 1
            else:
                range_upper_bad += 1

        if rp.structure == "S3_RANGE_LOWER":
            families["range_lower"].observe(shelf)
            if rp.regime in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND"):
                range_lower_ok += 1
            elif buy0 < sell0:
                range_lower_ok += 1
            else:
                range_lower_bad += 1

        if rp.liquidity == "L4_EXECUTION_RISKY":
            families["L4_execution_risky"].observe(shelf)
            if t.preferred_grid_count > 3:
                l4_grid_count_high += 1

    def fam_dict(name: str, st: GridFamilyStats) -> dict:
        if st.count == 0:
            return {"count": 0}
        return {
            "count": st.count,
            "sell_first_min": round2(st.sell_first_min),
            "sell_first_max": round2(st.sell_first_max),
            "buy_first_min": round2(st.buy_first_min),
            "buy_first_max": round2(st.buy_first_max),
            "trailing_violations": st.trailing_violations,
        }

    pass_audit = (
        trailing_total_violations == 0
        and range_upper_bad == 0
        and range_lower_bad == 0
        and crash_buy_deep_bad == 0
        and low_vol_too_wide == 0
        and high_vol_too_narrow == 0
        and l4_grid_count_high == 0
    )

    return {
        "families": {k: fam_dict(k, v) for k, v in families.items()},
        "trailing_total_violations": trailing_total_violations,
        "range_upper_ok": range_upper_ok,
        "range_upper_bad": range_upper_bad,
        "range_lower_ok": range_lower_ok,
        "range_lower_bad": range_lower_bad,
        "crash_buy_deep_ok": crash_buy_deep_ok,
        "crash_buy_deep_bad": crash_buy_deep_bad,
        "low_vol_too_wide": low_vol_too_wide,
        "high_vol_too_narrow": high_vol_too_narrow,
        "l4_grid_count_high": l4_grid_count_high,
        "pass_audit": pass_audit,
    }
