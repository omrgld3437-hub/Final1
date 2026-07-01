"""V6 scenario classifier — coin-native R1..R8 (BTC does not alone set regime)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.dynamic_param_score.v6.domain.types import ScenarioIdentity, V6InputContract


@dataclass
class ClassifiedScenario:
    regime_id: str
    sub_id: str
    micro_id: str
    behavior_id: str
    label: str


def _crash_like(inp: V6InputContract) -> bool:
    cv = inp.crash_velocity
    dd = inp.drawdown_7d_pct or 0
    ret24 = inp.return_24h_pct or 0
    return (cv is not None and cv < -1.5) or dd >= 15 or ret24 <= -8


def _downtrend(inp: V6InputContract) -> bool:
    if inp.lower_lows and (inp.return_24h_pct or 0) < -3:
        return True
    pve = inp.price_vs_ema200_pct
    return pve is not None and pve < -5 and (inp.adx_1h or 0) >= 18


def _volatile_range(inp: V6InputContract) -> bool:
    vp = inp.volatility_percentile or 0
    atr = inp.atr_1h_pct or 0
    return vp >= 60 or atr >= 1.2


def _strong_uptrend(inp: V6InputContract) -> bool:
    if inp.higher_highs and (inp.return_24h_pct or 0) > 3:
        return True
    pve = inp.price_vs_ema200_pct
    return pve is not None and pve > 3 and (inp.adx_1h or 0) >= 22


def classify_scenario(inp: V6InputContract) -> ClassifiedScenario:
    """Heuristic classifier — full tree loaded from scenario_tree_v6.json in later passes."""
    if _crash_like(inp):
        regime, sub, micro, behavior = "R8", "01", "001", "PB11"
        label = "Crash / sert düşüş"
    elif _downtrend(inp):
        regime, sub, micro, behavior = "R7", "01", "001", "PB10"
        label = "Düşüş trendi"
    elif _volatile_range(inp):
        regime, sub, micro, behavior = "R4", "01", "001", "PB02"
        label = "Volatil aralık"
    elif _strong_uptrend(inp):
        regime, sub, micro, behavior = "R1", "01", "001", "PB05"
        label = "Güçlü yükseliş trendi"
    elif (inp.range_stability or 0) >= 0.55 and (inp.volatility_percentile or 50) < 45:
        regime, sub, micro, behavior = "R2", "01", "001", "PB01"
        label = "Dengeli aralık"
    elif (inp.volatility_percentile or 0) < 35:
        regime, sub, micro, behavior = "R3", "01", "001", "PB01"
        label = "Zayıf / gürültülü aralık"
    elif (inp.return_24h_pct or 0) > 0 and (inp.drawdown_7d_pct or 0) > 5:
        regime, sub, micro, behavior = "R5", "01", "001", "PB07"
        label = "Toparlanma"
    else:
        regime, sub, micro, behavior = "R6", "01", "001", "PB06"
        label = "Tepe / dağılım / zayıflama"

    # Fake breakout / pump micro overrides
    if inp.fake_breakout_score >= 70:
        micro, behavior = "003", "PB06"
    elif inp.pump_score >= 70 and regime not in ("R8", "R7"):
        micro, behavior = "002", "PB09"

    return ClassifiedScenario(
        regime_id=regime,
        sub_id=sub,
        micro_id=micro,
        behavior_id=behavior,
        label=label,
    )


def to_scenario_identity(
    classified: ClassifiedScenario,
    severity: str,
) -> ScenarioIdentity:
    return ScenarioIdentity(
        regime_id=classified.regime_id,
        sub_id=classified.sub_id,
        micro_id=classified.micro_id,
        behavior_id=classified.behavior_id,
        severity=severity,  # type: ignore[arg-type]
        name=classified.label,
    )
