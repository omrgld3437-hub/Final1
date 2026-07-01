"""Asset fragility adjuster — spec §13."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def fragility_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    cls = inp.asset_fragility_class
    delta = AdjusterDelta(tags=[f"F_{cls}"])
    if cls == "F3":
        delta.base_delta_steps -= 2
        delta.buy_grid_count_delta -= 1
        delta.buy_grid_distance_delta += 3
        delta.sell_grid_distance_delta += 2
        delta.buyback_trigger_delta += 1.0
        delta.profit_sell_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.sell_trailing_delta_steps += 1
    elif cls == "F2":
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 2
        delta.sell_grid_distance_delta += 1
        delta.buyback_trigger_delta += 0.5
        delta.profit_sell_trigger_delta += 0.5
        delta.buy_trailing_delta_steps += 1
    elif cls == "F1" and (inp.volatility_percentile or 0) >= 70:
        delta.profit_sell_trigger_delta += 0.5
    return delta, {"fragility_class": cls}
