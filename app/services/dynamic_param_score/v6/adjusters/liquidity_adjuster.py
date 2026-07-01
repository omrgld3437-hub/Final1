"""Liquidity / spread adjuster — spec §15 (no fee)."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _liquidity_risk(inp: V6InputContract) -> int:
    if inp.zero_volume_flag:
        return 100
    sp = inp.spread_pct or 0
    if sp > 0.25:
        spread_s = 80
    elif sp > 0.10:
        spread_s = 45
    elif sp > 0.03:
        spread_s = 20
    else:
        spread_s = 0
    vc = inp.volume_consistency
    if vc is None:
        vol_s = 20
    elif vc < 0.35:
        vol_s = 80
    elif vc < 0.55:
        vol_s = 45
    elif vc < 0.75:
        vol_s = 20
    else:
        vol_s = 0
    return int(max(0.45 * spread_s + 0.45 * vol_s, 0))


def liquidity_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    risk = _liquidity_risk(inp)
    delta = AdjusterDelta(tags=[f"L{risk // 25}"])
    if risk >= 70:  # L3
        delta.base_delta_steps -= 2
        delta.normal_buy_override = True
        delta.buy_grid_count_delta -= 1
        delta.sell_grid_count_delta -= 1
        delta.profit_sell_trigger_delta += 1.0
        delta.buy_trailing_delta_steps += 1
    elif risk >= 40:  # L2
        delta.profit_sell_trigger_delta += 0.5
        delta.buy_grid_count_delta -= 1
    return delta, {"liquidity_risk": risk}
