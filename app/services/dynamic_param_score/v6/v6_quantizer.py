"""V6 lattice quantizer — no fractional base/grid/trailing/profit values."""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence

from app.services.dynamic_param_score.v6.constants import (
    BASE_ALLOC_PCT_STEPS,
    GRID_AMOUNT_STEP_PCT,
    GRID_DISTANCE_STEP_PCT,
    MIN_PROFIT_BUFFER_PCT,
    DEFAULT_COST_FLOOR_PCT,
    PROFIT_TRIGGER_CODES,
    PROFIT_PCT_TO_CODE,
    TRAILING_CODES,
    TRAILING_PCT_TO_CODE,
)
from app.services.dynamic_param_score.v6.domain.types import GridLevel, V6CatalogProfile


def round_to_nearest_5(pct: float) -> int:
    return int(max(0, min(95, round(pct / 5) * 5)))


def quantize_base_pct(pct: float) -> int:
    return round_to_nearest_5(pct)


def quantize_grid_distance(pct: float, *, is_buy: bool) -> int:
    """Risky direction rounding: buy more negative, sell more positive."""
    if pct == 0:
        return 0
    sign = -1 if pct < 0 else 1
    mag = abs(pct)
    step = GRID_DISTANCE_STEP_PCT
    if is_buy:
        # deeper buy: round away from zero (more negative)
        q = math.ceil(mag / step) * step if sign < 0 else math.floor(mag / step) * step
    else:
        q = math.ceil(mag / step) * step if sign > 0 else math.floor(mag / step) * step
    return int(sign * q)


def quantize_grid_amount(pct: float) -> int:
    step = GRID_AMOUNT_STEP_PCT
    return int(max(0, min(100, round(pct / step) * step)))


def trailing_code_from_pct(pct: float) -> str:
    best = min(TRAILING_CODES.items(), key=lambda kv: abs(kv[1] - pct))
    return best[0]


def trailing_pct_from_code(code: str) -> float:
    return TRAILING_CODES.get(code, TRAILING_CODES["T2"])


def profit_code_from_pct(pct: float) -> str:
    if pct in PROFIT_PCT_TO_CODE:
        return PROFIT_PCT_TO_CODE[pct]
    best = min(PROFIT_TRIGGER_CODES.items(), key=lambda kv: abs(kv[1] - pct))
    return best[0]


def profit_pct_from_code(code: str) -> float:
    return PROFIT_TRIGGER_CODES.get(code, PROFIT_TRIGGER_CODES["K10"])


def quantize_profit_trigger_pct(pct: float) -> float:
    step = 0.5
    return round(max(2.5, min(8.0, round(pct / step) * step)), 1)


def min_profit_pct_for_trailing(trailing_pct: float, *, regime_floor: Optional[float] = None) -> float:
    raw = DEFAULT_COST_FLOOR_PCT + trailing_pct + MIN_PROFIT_BUFFER_PCT
    if regime_floor is not None:
        raw = max(raw, regime_floor)
    return quantize_profit_trigger_pct(raw)


def apply_trailing_step_delta(code: str, delta_steps: int) -> str:
    keys = list(TRAILING_CODES.keys())
    idx = keys.index(code) if code in keys else 2
    idx = max(0, min(len(keys) - 1, idx + delta_steps))
    return keys[idx]


def normalize_grid_levels(levels: Sequence[GridLevel], *, is_buy: bool) -> List[GridLevel]:
    out: List[GridLevel] = []
    for g in levels:
        out.append(
            GridLevel(
                distance_pct=quantize_grid_distance(float(g.distance_pct), is_buy=is_buy),
                amount_pct=quantize_grid_amount(float(g.amount_pct)),
            )
        )
    total = sum(g.amount_pct for g in out)
    if out and total != 100:
        # largest remainder on 5% lattice
        scaled = [g.amount_pct * 100 // max(total, 1) for g in out]
        diff = 100 - sum(scaled)
        scaled[-1] += diff
        out = [GridLevel(out[i].distance_pct, int(scaled[i])) for i in range(len(out))]
    return out


def quantize_profile(profile: V6CatalogProfile) -> V6CatalogProfile:
    p = profile.copy()
    p.base_allocation_pct = quantize_base_pct(p.base_allocation_pct)
    p.quote_allocation_pct = 100 - p.base_allocation_pct
    p.buy_grids = normalize_grid_levels(p.buy_grids, is_buy=True)
    p.sell_grids = normalize_grid_levels(p.sell_grids, is_buy=False)
    if not p.normal_buy_enabled:
        p.buy_grids = []
    p.sell_trailing_code = trailing_code_from_pct(trailing_pct_from_code(p.sell_trailing_code))
    p.buy_trailing_code = trailing_code_from_pct(trailing_pct_from_code(p.buy_trailing_code))
    sell_trail = trailing_pct_from_code(p.sell_trailing_code)
    buy_trail = trailing_pct_from_code(p.buy_trailing_code)
    if p.buyback_after_sell_enabled:
        bp = profit_pct_from_code(p.buyback_trigger_code)
        bp = max(bp, min_profit_pct_for_trailing(buy_trail))
        p.buyback_trigger_code = profit_code_from_pct(quantize_profit_trigger_pct(bp))
    if p.profit_sell_after_buyback_enabled:
        sp = profit_pct_from_code(p.profit_sell_trigger_code)
        sp = max(sp, min_profit_pct_for_trailing(trailing_pct_from_code(p.profit_sell_trailing_code)))
        p.profit_sell_trigger_code = profit_code_from_pct(quantize_profit_trigger_pct(sp))
    return p


def has_fractional_violation(profile: V6CatalogProfile) -> bool:
    if profile.base_allocation_pct % 5 != 0:
        return True
    for g in profile.buy_grids + profile.sell_grids:
        if abs(g.distance_pct) % GRID_DISTANCE_STEP_PCT != 0:
            return True
        if g.amount_pct % GRID_AMOUNT_STEP_PCT != 0:
            return True
    return False
