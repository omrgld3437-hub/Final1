"""Runtime micro-adjustment for selected DPS Engine V2 profiles."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.dynamic_param_score.models import BotParams

MAX_RUNTIME_ADJUSTMENT = 0.15


def _clamp_adjust(factor: float) -> float:
    return max(1.0 - MAX_RUNTIME_ADJUSTMENT, min(1.0 + MAX_RUNTIME_ADJUSTMENT, factor))


def compute_runtime_adjustment_factor(
    *,
    atr_1h_live: float,
    atr_1h_profile: float,
    spread_live: float,
    spread_profile: float,
    fee_live: float,
    fee_profile: float,
    data_freshness_sec: float,
    fee_bad: bool = False,
) -> Tuple[float, list[str]]:
    """Return multiplier for grid spacing and adjustment reasons."""
    reasons: list[str] = []
    factor = 1.0

    if atr_1h_profile > 0 and atr_1h_live > atr_1h_profile * 1.05:
        bump = min(0.15, (atr_1h_live / atr_1h_profile - 1.0) * 0.5)
        factor += bump
        reasons.append("atr_1h_increased")

    if spread_profile > 0 and spread_live > spread_profile * 1.1:
        factor += min(0.10, (spread_live / max(spread_profile, 0.001) - 1.0) * 0.3)
        reasons.append("spread_increased")

    if fee_bad or (fee_profile > 0 and fee_live > fee_profile * 1.15):
        factor += 0.10
        reasons.append("fee_worsened")

    if data_freshness_sec > 180:
        factor += 0.05
        reasons.append("data_staleness")

    return _clamp_adjust(factor), reasons


def apply_runtime_micro_adjust(
    params: BotParams,
    factor: float,
    *,
    reasons: Optional[list[str]] = None,
) -> Tuple[BotParams, Dict[str, Any]]:
    """Apply bounded runtime grid widening to live params."""
    meta: Dict[str, Any] = {
        "runtime_adjust_factor": round(factor, 4),
        "runtime_adjust_reasons": reasons or [],
        "max_runtime_adjustment": MAX_RUNTIME_ADJUSTMENT,
    }
    if abs(factor - 1.0) < 1e-6:
        return params, meta

    p = params
    p.buy_grid_spacing_pct = round(p.buy_grid_spacing_pct * factor, 4)
    p.sell_grid_spacing_pct = round(p.sell_grid_spacing_pct * factor, 4)
    if p.trailing_enabled and p.trailing_callback_pct:
        p.trailing_callback_pct = round(p.trailing_callback_pct * min(factor, 1.08), 4)
    meta["buy_grid_spacing_pct"] = p.buy_grid_spacing_pct
    meta["sell_grid_spacing_pct"] = p.sell_grid_spacing_pct
    return p, meta
