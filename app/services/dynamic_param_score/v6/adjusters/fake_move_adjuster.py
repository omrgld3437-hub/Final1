"""Pump / dump / fake move adjuster — spec §17."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.move_scores import SCORE_HIGH, SCORE_MEDIUM
from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _score(v) -> float:
    """Missing scores do not participate (treated as unavailable, not zero)."""
    return float(v) if v is not None else -1.0


def fake_move_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    delta = AdjusterDelta()
    pump = _score(inp.pump_score)
    dump = _score(inp.dump_score)
    fake_bounce = _score(inp.fake_bounce_score)
    fake_breakout = _score(inp.fake_breakout_score)

    if pump >= SCORE_HIGH:
        delta.base_delta_steps -= 2
        delta.buy_grid_count_delta -= 1
        delta.buy_grid_distance_delta += 4
        delta.sell_grid_distance_delta += 3
        delta.profit_sell_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.tags.append("PUMP_HIGH")
    elif pump >= SCORE_MEDIUM:
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 2
        delta.sell_grid_distance_delta += 1
        delta.profit_sell_trigger_delta += 0.5
    if dump >= SCORE_HIGH:
        delta.normal_buy_override = True
        delta.base_delta_steps -= 2
        delta.buyback_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.tags.append("DUMP_HIGH")
    elif dump >= SCORE_MEDIUM:
        delta.buy_grid_distance_delta += 2
        delta.base_delta_steps -= 1
        delta.buyback_trigger_delta += 0.5
    if fake_bounce >= SCORE_HIGH:
        delta.normal_buy_override = True
        delta.base_delta_steps -= 2
        delta.buy_grid_distance_delta += 3
        delta.profit_sell_trigger_delta += 1.0
        delta.tags.append("FAKE_BOUNCE")
    if fake_breakout >= SCORE_HIGH:
        delta.base_delta_steps -= 1
        delta.sell_grid_distance_delta -= 1
        delta.buy_grid_distance_delta += 2
        delta.profit_sell_trigger_delta += 0.5
        delta.tags.append("FAKE_BREAKOUT")
    return delta, {}
