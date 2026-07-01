"""Cap merged adjuster deltas — spec §18."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.constants import (
    MAX_BASE_DOWN_STEPS_EXTREME,
    MAX_BASE_DOWN_STEPS_NORMAL,
    MAX_BASE_UP_STEPS_NORMAL,
    MAX_PROFIT_INCREASE_EXTREME,
    MAX_PROFIT_INCREASE_NORMAL,
    MAX_TRAILING_UP_STEPS_EXTREME,
    MAX_TRAILING_UP_STEPS_NORMAL,
)
from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _extreme_risk(inp: V6InputContract, btc_risk: int, vol_score: int) -> bool:
    return (
        btc_risk >= 60
        and inp.asset_fragility_class == "F3"
        and vol_score >= 80
    )


def cap_total_delta(
    delta: AdjusterDelta,
    inp: V6InputContract,
    *,
    btc_risk: int = 0,
    volatility_score: int = 0,
) -> AdjusterDelta:
    extreme = _extreme_risk(inp, btc_risk, volatility_score)
    max_down = MAX_BASE_DOWN_STEPS_EXTREME if extreme else MAX_BASE_DOWN_STEPS_NORMAL
    delta.base_delta_steps = max(-max_down, min(MAX_BASE_UP_STEPS_NORMAL, delta.base_delta_steps))
    max_trail = MAX_TRAILING_UP_STEPS_EXTREME if extreme else MAX_TRAILING_UP_STEPS_NORMAL
    delta.buy_trailing_delta_steps = max(-max_trail, min(max_trail, delta.buy_trailing_delta_steps))
    delta.sell_trailing_delta_steps = max(-max_trail, min(max_trail, delta.sell_trailing_delta_steps))
    max_profit = MAX_PROFIT_INCREASE_EXTREME if extreme else MAX_PROFIT_INCREASE_NORMAL
    delta.buyback_trigger_delta = max(0, min(max_profit, delta.buyback_trigger_delta))
    delta.profit_sell_trigger_delta = max(0, min(max_profit, delta.profit_sell_trigger_delta))
    delta.buy_grid_distance_delta = max(-8, min(12, delta.buy_grid_distance_delta))
    delta.sell_grid_distance_delta = max(-6, min(10, delta.sell_grid_distance_delta))
    delta.buy_grid_count_delta = max(-2, min(0, delta.buy_grid_count_delta))
    delta.sell_grid_count_delta = max(-2, min(0, delta.sell_grid_count_delta))
    return delta
