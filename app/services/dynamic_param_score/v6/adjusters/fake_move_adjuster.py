"""Pump / dump / fake move adjuster — spec §17."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def fake_move_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    delta = AdjusterDelta()
    if inp.pump_score >= 70:
        delta.base_delta_steps -= 2
        delta.buy_grid_count_delta -= 1
        delta.buy_grid_distance_delta += 4
        delta.sell_grid_distance_delta += 3
        delta.profit_sell_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.tags.append("PUMP_HIGH")
    elif inp.pump_score >= 40:
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 2
        delta.sell_grid_distance_delta += 1
        delta.profit_sell_trigger_delta += 0.5
    if inp.dump_score >= 70:
        delta.normal_buy_override = True
        delta.base_delta_steps -= 2
        delta.buyback_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.tags.append("DUMP_HIGH")
    elif inp.dump_score >= 40:
        delta.buy_grid_distance_delta += 2
        delta.base_delta_steps -= 1
        delta.buyback_trigger_delta += 0.5
    if inp.fake_bounce_score >= 70:
        delta.normal_buy_override = True
        delta.base_delta_steps -= 2
        delta.buy_grid_distance_delta += 3
        delta.profit_sell_trigger_delta += 1.0
        delta.tags.append("FAKE_BOUNCE")
    if inp.fake_breakout_score >= 70:
        delta.base_delta_steps -= 1
        delta.sell_grid_distance_delta -= 1
        delta.buy_grid_distance_delta += 2
        delta.profit_sell_trigger_delta += 0.5
        delta.tags.append("FAKE_BREAKOUT")
    return delta, {}
