"""Data quality adjuster — spec §11."""

from __future__ import annotations

from typing import Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def _freshness_penalty(sec: float | None) -> int:
    if sec is None:
        return 15
    if sec <= 60:
        return 0
    if sec <= 180:
        return 15
    if sec <= 300:
        return 30
    return 50


def _gap_penalty(sec: float | None) -> int:
    if sec is None or sec == 0:
        return 0
    if sec <= 60:
        return 20
    if sec <= 300:
        return 40
    return 70


def _candle_penalty(c5: int, c1h: int) -> int:
    if c5 >= 1000 and c1h >= 200:
        return 0
    if c5 >= 500 and c1h >= 100:
        return 20
    return 50


def data_quality_adjuster(inp: V6InputContract) -> Tuple[AdjusterDelta, Dict]:
    price_penalty = 0 if inp.price_valid else 100
    risk = max(
        _freshness_penalty(inp.data_freshness_sec),
        _gap_penalty(inp.data_gap_sec),
        _candle_penalty(inp.candles_5m, inp.candles_1h),
        price_penalty,
    )
    delta = AdjusterDelta(tags=[f"DQ_{risk}"])
    if risk >= 75:
        delta.severity_override = "DEF"
        delta.normal_buy_override = True
        delta.base_delta_steps -= 2
        delta.buy_grid_count_delta -= 1
        delta.buy_trailing_delta_steps += 1
        delta.buyback_trigger_delta += 0.5
    elif risk >= 50:
        delta.severity_override = "DEF"
        delta.base_delta_steps -= 1
        delta.buy_grid_distance_delta += 1
        delta.buyback_trigger_delta += 0.5
        delta.profit_sell_trigger_delta += 0.5
    elif risk >= 25:
        delta.severity_override = "STD"
        delta.buy_trailing_delta_steps += 1
        delta.sell_trailing_delta_steps += 1
        delta.buyback_trigger_delta += 0.5
        delta.profit_sell_trigger_delta += 0.5
    return delta, {"data_quality_risk": risk}
