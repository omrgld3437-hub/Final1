"""Volatility adjuster — spec §14."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _volatility_score(inp: V6InputContract) -> int:
    atr = inp.atr_1h_pct or 0
    if atr >= 5:
        atr_s = 90
    elif atr >= 2.5:
        atr_s = 65
    elif atr >= 1.2:
        atr_s = 40
    elif atr >= 0.6:
        atr_s = 20
    else:
        atr_s = 0
    vp = inp.volatility_percentile or 0
    if vp >= 90:
        pct_s = 90
    elif vp >= 75:
        pct_s = 65
    elif vp >= 60:
        pct_s = 40
    elif vp >= 40:
        pct_s = 20
    else:
        pct_s = 0
    bb = inp.bb_width or 0
    if bb >= 10:
        bb_s = 90
    elif bb >= 5:
        bb_s = 70
    elif bb >= 2:
        bb_s = 45
    elif bb >= 0.8:
        bb_s = 20
    else:
        bb_s = 0
    return int(0.45 * atr_s + 0.35 * pct_s + 0.20 * bb_s)


def volatility_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    score = _volatility_score(inp)
    v_tag = f"V{min(5, max(1, score // 20 + 1))}"
    delta = AdjusterDelta(tags=[v_tag])
    if score >= 80:  # V5
        delta.base_delta_steps -= 2
        delta.buy_grid_count_delta -= 1
        delta.buy_grid_distance_delta += 5
        delta.sell_grid_distance_delta += 4
        delta.buy_trailing_delta_steps += 2
        delta.sell_trailing_delta_steps += 2
        delta.buyback_trigger_delta += 1.5
        delta.profit_sell_trigger_delta += 1.5
    elif score >= 60:  # V4
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 3
        delta.sell_grid_distance_delta += 2
        delta.buy_trailing_delta_steps += 1
        delta.sell_trailing_delta_steps += 1
        delta.buyback_trigger_delta += 1.0
        delta.profit_sell_trigger_delta += 1.0
    elif score >= 40:  # V3
        delta.buy_grid_distance_delta += 2
        delta.sell_grid_distance_delta += 1
        delta.buy_trailing_delta_steps += 1
        delta.buyback_trigger_delta += 0.5
        delta.profit_sell_trigger_delta += 0.5
    elif score < 20:  # V1
        delta.buy_grid_distance_delta -= 2
        delta.sell_grid_distance_delta -= 1
        delta.buy_trailing_delta_steps -= 1
        delta.profit_sell_trigger_delta -= 0.5
    return delta, {"volatility_score": score}
