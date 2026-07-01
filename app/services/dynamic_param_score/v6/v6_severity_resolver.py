"""Resolve DEF / STD / ACT severity from live inputs."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.domain.types import SeverityMode, V6InputContract


def resolve_severity(inp: V6InputContract, *, data_quality_risk: int = 0) -> SeverityMode:
    """Initial severity before per-adjuster overrides."""
    if data_quality_risk >= 75:
        return "DEF"
    risk = 0
    if inp.btc_ema200_below:
        risk += 20
    bc = inp.btc_crash_velocity
    if bc is not None:
        if bc < -1.5:
            risk += 60
        elif bc < -0.7:
            risk += 35
        elif bc < -0.3:
            risk += 15
    frag = inp.asset_fragility_class
    if frag == "F3":
        risk += 40
    elif frag == "F2":
        risk += 25
    vp = inp.volatility_percentile or 0
    if vp >= 90:
        risk += 35
    elif vp >= 70:
        risk += 20
    if data_quality_risk >= 50:
        risk += 25
    if risk >= 60:
        return "DEF"
    if risk >= 30:
        return "STD"
    return "ACT"


def apply_severity_override(current: SeverityMode, override: SeverityMode | None) -> SeverityMode:
    if override is None:
        return current
    order = {"DEF": 0, "STD": 1, "ACT": 2}
    return current if order[current] <= order[override] else override
