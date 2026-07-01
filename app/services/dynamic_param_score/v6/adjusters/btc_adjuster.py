"""BTC context adjuster — spec §12."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _btc_risk(inp: V6InputContract) -> int:
    ema_p = 20 if inp.btc_ema200_below else 0
    cv = inp.btc_crash_velocity
    crash_p = 0
    if cv is not None:
        if cv < -1.5:
            crash_p = 60
        elif cv < -0.7:
            crash_p = 35
        elif cv < -0.3:
            crash_p = 15
    r4 = inp.btc_return_4h_pct or 0
    r24 = inp.btc_return_24h_pct or 0
    ret_p = 0
    if r4 <= -3 or r24 <= -6:
        ret_p = 60
    elif r4 <= -1.5 or r24 <= -3:
        ret_p = 35
    elif r4 < 0 or r24 < 0:
        ret_p = 15
    return min(100, ema_p + crash_p + ret_p)


def btc_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    risk = _btc_risk(inp)
    delta = AdjusterDelta(tags=[f"BTC_B{risk // 25}"])
    if risk >= 60:  # B3
        delta.severity_override = "DEF"
        delta.base_delta_steps -= 2
        delta.normal_buy_override = True
        delta.buy_grid_distance_delta += 3
        delta.buyback_trigger_delta += 1.0
        delta.profit_sell_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
        delta.sell_trailing_delta_steps += 1
    elif risk >= 25:  # B2
        delta.severity_override = "STD"
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 1
        delta.buyback_trigger_delta += 0.5
        delta.profit_sell_trigger_delta += 0.5
    elif risk == 0 and (inp.btc_return_4h_pct or 0) > 1 and (inp.btc_return_24h_pct or 0) > 2 and not inp.btc_ema200_below:
        delta.base_delta_steps += 1
        delta.buy_grid_distance_delta -= 1
        delta.profit_sell_trigger_delta -= 0.5
        delta.tags.append("BTC_B1")
    return delta, {"btc_risk": risk}
