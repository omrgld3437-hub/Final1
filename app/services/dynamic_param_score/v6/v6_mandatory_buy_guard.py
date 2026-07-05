"""V6 guard: keep a minimum deep buy surface for non-hard-block profiles."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from app.services.dynamic_param_score.v6.domain.types import GridLevel, V6CatalogProfile, V6InputContract
from app.services.dynamic_param_score.v6.v6_quantizer import quantize_profile

_SEVERITY_ORDER = ("DEF", "STD", "ACT")

DEEP_BUY_DISTANCE_BY_BEHAVIOR: Dict[str, Dict[str, int]] = {
    "PB06": {"DEF": 18, "STD": 16, "ACT": 14},
    "PB09": {"DEF": 22, "STD": 20, "ACT": 18},
    "PB11": {"DEF": 35, "STD": 32, "ACT": 28},
    "PB13": {"DEF": 28, "STD": 24, "ACT": 20},
    "PB14": {"DEF": 30, "STD": 26, "ACT": 22},
    "PB15": {"DEF": 25, "STD": 22, "ACT": 18},
    "PB16": {"DEF": 30, "STD": 25, "ACT": 20},
}


def _severity(profile: V6CatalogProfile) -> str:
    sev = str(profile.scenario.severity or "STD").upper()
    return sev if sev in _SEVERITY_ORDER else "STD"


def mandatory_deep_buy_distance(profile: V6CatalogProfile, inp: V6InputContract | None = None) -> int:
    """Return the single deep-buy distance required when a profile has no buy grid."""
    behavior = str(profile.scenario.behavior_id or "").upper()
    sev = _severity(profile)
    by_behavior = DEEP_BUY_DISTANCE_BY_BEHAVIOR.get(behavior)
    if by_behavior:
        return by_behavior[sev]

    if inp is not None:
        if (inp.price_vs_ema200_pct or 0) > 80 or (inp.return_24h_pct or 0) > 50 or (inp.rsi_1h or 0) > 85:
            return {"DEF": 35, "STD": 28, "ACT": 20}[sev]
        if (inp.return_24h_pct or 0) <= -10 or (inp.crash_velocity or 0) < -1 or (inp.drawdown_7d_pct or 0) > 50:
            return {"DEF": 45, "STD": 40, "ACT": 35}[sev]
        if (inp.spread_pct or 0) > 0.40:
            return {"DEF": 35, "STD": 30, "ACT": 25}[sev]
        if (inp.spread_pct or 0) > 0.25:
            return {"DEF": 25, "STD": 22, "ACT": 18}[sev]

    return {"DEF": 20, "STD": 18, "ACT": 15}[sev]


def enforce_mandatory_deep_buy(
    profile: V6CatalogProfile,
    inp: V6InputContract | None = None,
    *,
    reason: str = "MANDATORY_DEEP_BUY",
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """Add one ultra-deep buy if a non-hard-block V6 output would otherwise close buying."""
    if (profile.modules or {}).get("hard_block_no_trade"):
        return profile, {"mandatory_deep_buy_skipped": "hard_block_no_trade"}
    if profile.normal_buy_enabled and profile.buy_grids:
        return profile, {}

    p = profile.copy()
    distance = mandatory_deep_buy_distance(p, inp)
    p.normal_buy_enabled = True
    p.buy_grids = [GridLevel(-abs(distance), 100)]
    modules = dict(p.modules or {})
    prior_status = str(modules.get("new_buys_status") or "")
    modules.update(
        {
            "normal_buy_grid": True,
            "mandatory_deep_buy_guard": True,
            "no_closed_buy_rule": True,
            "mandatory_deep_buy_distance_pct": -abs(distance),
            "new_buys_status": "deep_probe" if prior_status == "paused" else "restricted",
        }
    )
    p.modules = modules
    return quantize_profile(p), {
        "mandatory_deep_buy_applied": True,
        "mandatory_deep_buy_distance_pct": -abs(distance),
        "mandatory_deep_buy_reason": reason,
        "new_buys_status": modules["new_buys_status"],
    }
