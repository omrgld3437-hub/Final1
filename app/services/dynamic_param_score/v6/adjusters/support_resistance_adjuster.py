"""Support / resistance adjuster — spec §16."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def support_resistance_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    delta = AdjusterDelta()
    sd = inp.support_distance_pct
    ss = inp.support_strength_score or 0
    if sd is not None:
        if sd <= 1:
            near = 100
        elif sd <= 3:
            near = 75
        elif sd <= 5:
            near = 50
        elif sd <= 8:
            near = 25
        else:
            near = 0
        effect = near * ss / 100.0
        if effect >= 70:
            delta.buy_grid_distance_delta -= 2
            delta.base_delta_steps += 1
            delta.buyback_trigger_delta -= 0.5
            delta.tags.append("SR_STRONG_SUPPORT")
        elif near >= 75 and ss < 40:
            delta.base_delta_steps -= 1
            delta.buy_grid_distance_delta += 2
            delta.buyback_trigger_delta += 0.5
            delta.tags.append("SR_WEAK_SUPPORT")
    rd = inp.resistance_distance_pct
    rs = inp.resistance_strength_score or 0
    if rd is not None:
        if rd <= 1:
            rnear = 100
        elif rd <= 3:
            rnear = 75
        elif rd <= 5:
            rnear = 50
        elif rd <= 8:
            rnear = 25
        else:
            rnear = 0
        reffect = rnear * rs / 100.0
        if reffect >= 70:
            delta.sell_grid_distance_delta -= 2
            delta.base_delta_steps -= 1
            delta.tags.append("SR_STRONG_RESIST")
        elif rnear >= 75 and rs < 40:
            delta.sell_grid_distance_delta += 2
            delta.profit_sell_trigger_delta += 0.5
            delta.tags.append("SR_WEAK_RESIST")
    return delta, {}
