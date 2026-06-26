"""V4 live route classification — regime/vol from indicators, not soft balanced default."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.dynamic_param_score.models import RegimeTag


@dataclass(frozen=True)
class LiveRouteClassification:
    regime_code: str
    vol_code: str
    regime_tag: str
    scenario: str
    regime_overlay: Optional[str] = None
    classification_reason: str = ""


def _crash_hard_filter(
    *,
    return_24h_pct: float,
    crash_velocity: float,
    btc_crash_velocity: float,
    drawdown_7d_pct: float,
) -> bool:
    if return_24h_pct < -6 and crash_velocity < -1.5:
        return True
    if drawdown_7d_pct > 15 and crash_velocity < -1.0:
        return True
    if return_24h_pct < -12 and btc_crash_velocity < -1.5:
        return True
    return False


def classify_vol_code_v4(
    *,
    atr_1h_pct: float,
    volatility_score: int,
    return_24h_pct: float,
) -> str:
    atr = max(float(atr_1h_pct or 0.0), 0.0)
    vol = int(volatility_score or 50)
    ret = abs(float(return_24h_pct or 0.0))
    if atr >= 5.0 or ret >= 15.0:
        return "V5"
    if atr >= 3.0 or vol >= 75 or ret >= 8.0:
        return "V4"
    if atr < 0.5:
        return "V1"
    if atr < 0.9:
        return "V2"
    if atr < 1.5:
        return "V3"
    if atr < 2.5:
        return "V4"
    return "V5"


def classify_regime_code_v4(
    *,
    regime_tag: str,
    lower_lows: bool,
    higher_highs: bool,
    return_24h_pct: float = 0.0,
    drawdown_7d_pct: float = 0.0,
    drawdown_30d_pct: float = 0.0,
    z_score_5m: Optional[float] = None,
    price_in_bb: Optional[float] = None,
    atr_1h_pct: float = 0.0,
    risk_level: str = "NORMAL",
    btc_crash_velocity: float = 0.0,
    crash_velocity: float = 0.0,
    volatility_percentile: float = 50.0,
) -> LiveRouteClassification:
    """Map live indicators to V4 regime code; never soften sharp downtrends to R2."""
    tag = str(regime_tag or RegimeTag.BALANCED_RANGE.value)
    ret24 = float(return_24h_pct or 0.0)
    dd7 = float(drawdown_7d_pct or 0.0)
    dd30 = float(drawdown_30d_pct or 0.0)
    z = float(z_score_5m) if z_score_5m is not None else 0.0
    bb = float(price_in_bb) if price_in_bb is not None else 0.5
    crash_hard = _crash_hard_filter(
        return_24h_pct=ret24,
        crash_velocity=float(crash_velocity or 0.0),
        btc_crash_velocity=float(btc_crash_velocity or 0.0),
        drawdown_7d_pct=dd7,
    )

    overlay: Optional[str] = None
    reason = ""

    if tag == RegimeTag.BREAKOUT_RISK.value:
        vol_code = classify_vol_code_v4(
            atr_1h_pct=atr_1h_pct,
            volatility_score=int(volatility_percentile or 75),
            return_24h_pct=ret24,
        )
        if (
            ret24 >= 15.0
            and float(volatility_percentile or 0) >= 95
            and bb >= 0.90
        ):
            return LiveRouteClassification(
                regime_code="R15",
                vol_code=vol_code,
                regime_tag=RegimeTag.BREAKOUT_RISK.value,
                scenario="PUMP_EXHAUSTION",
                classification_reason="breakout_risk_pump_exhaustion",
            )
        return LiveRouteClassification(
            regime_code="R4",
            vol_code=vol_code,
            regime_tag=RegimeTag.BREAKOUT_RISK.value,
            scenario="HIGH_VOL_CHOPPY_RANGE",
            classification_reason="breakout_risk_live",
        )

    if tag == RegimeTag.DUMP_RISK.value or crash_hard:
        return LiveRouteClassification(
            regime_code="R8",
            vol_code="V5",
            regime_tag=RegimeTag.DUMP_RISK.value,
            scenario="CRASH_RISK",
            classification_reason="crash_hard_filter",
        )

    strong_downtrend = (
        lower_lows
        and not higher_highs
        and ret24 <= -6.0
        and dd7 >= 20.0
    )
    defensive_downtrend = (
        lower_lows
        and not higher_highs
        and ret24 <= -4.0
        and risk_level in ("DEFENSIVE", "CAUTION", "BLOCKED")
    )
    if strong_downtrend or defensive_downtrend or tag == RegimeTag.TRENDING_DOWN.value:
        if dd7 >= 25 or ret24 <= -8 or dd30 >= 35:
            return LiveRouteClassification(
                regime_code="R7",
                vol_code=classify_vol_code_v4(
                    atr_1h_pct=atr_1h_pct,
                    volatility_score=85 if dd7 >= 20 else 70,
                    return_24h_pct=ret24,
                ),
                regime_tag=RegimeTag.TRENDING_DOWN.value,
                scenario="STRONG_DOWNTREND_RANGE",
                classification_reason="lower_lows_strong_downtrend",
            )
        return LiveRouteClassification(
            regime_code="R6",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct,
                volatility_score=70,
                return_24h_pct=ret24,
            ),
            regime_tag=RegimeTag.TRENDING_DOWN.value,
            scenario="LOWER_LOWS_WEAK_DOWN_RANGE",
            classification_reason="lower_lows_weak_down",
        )

    oversold = (
        z <= -1.8
        and bb <= 0.15
        and not crash_hard
        and lower_lows
        and not higher_highs
    )
    if oversold or (z <= -1.5 and ret24 <= -5 and dd7 >= 15):
        overlay = "OVERSOLD_DEFENSIVE"
        return LiveRouteClassification(
            regime_code="R12",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct,
                volatility_score=75,
                return_24h_pct=ret24,
            ),
            regime_tag=RegimeTag.RANGE_LOW_VOL.value,
            scenario="OVERSOLD_MEAN_REVERSION",
            regime_overlay=overlay,
            classification_reason="oversold_defensive",
        )

    if tag == RegimeTag.TRENDING_UP.value:
        return LiveRouteClassification(
            regime_code="R9" if higher_highs else "R10",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct, volatility_score=60, return_24h_pct=ret24
            ),
            regime_tag=tag,
            scenario="HIGHER_HIGHS_WEAK_UP_RANGE" if higher_highs else "STRONG_UPTREND",
            classification_reason="trending_up",
        )

    wide_chop = higher_highs and lower_lows
    high_vol = (
        float(volatility_percentile or 0) >= 70
        or atr_1h_pct >= 2.5
        or abs(ret24) >= 6.0
    )
    btc_pressure = float(btc_crash_velocity or 0.0) < -0.5
    overbought_chop = wide_chop and z >= 1.8 and bb >= 0.95

    if overbought_chop and (btc_pressure or high_vol):
        vol_code = classify_vol_code_v4(
            atr_1h_pct=atr_1h_pct,
            volatility_score=int(volatility_percentile or 80),
            return_24h_pct=ret24,
        )
        if btc_pressure:
            return LiveRouteClassification(
                regime_code="R14",
                vol_code=vol_code,
                regime_tag=RegimeTag.RANGE_HIGH_VOL.value,
                scenario="BTC_DRAG_PRESSURE",
                classification_reason="overbought_wide_chop_btc_pressure",
            )
        return LiveRouteClassification(
            regime_code="R13",
            vol_code=vol_code,
            regime_tag=RegimeTag.RANGE_HIGH_VOL.value,
            scenario="OVERBOUGHT_MEAN_REVERSION",
            classification_reason="overbought_wide_chop",
        )

    if tag == RegimeTag.RANGE_HIGH_VOL.value or tag == RegimeTag.HIGH_VOL_UNSTABLE.value:
        return LiveRouteClassification(
            regime_code="R4" if tag == RegimeTag.RANGE_HIGH_VOL.value else "R5",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct, volatility_score=80, return_24h_pct=ret24
            ),
            regime_tag=tag,
            scenario="HIGH_VOL_CHOPPY_RANGE" if tag == RegimeTag.RANGE_HIGH_VOL.value else "WIDE_CHOP",
            classification_reason="high_vol_range",
        )

    wide_chop = higher_highs and lower_lows
    high_vol = (
        float(volatility_percentile or 0) >= 70
        or atr_1h_pct >= 2.5
        or abs(ret24) >= 6.0
    )
    if wide_chop and high_vol:
        vol_code = classify_vol_code_v4(
            atr_1h_pct=atr_1h_pct,
            volatility_score=int(volatility_percentile or 75),
            return_24h_pct=ret24,
        )
        if risk_level in ("DEFENSIVE", "CAUTION", "BLOCKED") and btc_pressure:
            return LiveRouteClassification(
                regime_code="R14",
                vol_code=vol_code,
                regime_tag=RegimeTag.RANGE_HIGH_VOL.value,
                scenario="BTC_DRAG_PRESSURE",
                classification_reason="wide_chop_btc_pressure_defensive",
            )
        regime_code = "R5" if wide_chop else "R4"
        return LiveRouteClassification(
            regime_code=regime_code,
            vol_code=vol_code,
            regime_tag=RegimeTag.RANGE_HIGH_VOL.value,
            scenario="WIDE_CHOP" if regime_code == "R5" else "HIGH_VOL_CHOPPY_RANGE",
            classification_reason="wide_chop_high_vol",
        )

    if tag == RegimeTag.RANGE_LOW_VOL.value:
        if wide_chop or high_vol or float(volatility_percentile or 0) >= 70:
            vol_code = classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct,
                volatility_score=int(volatility_percentile or 70),
                return_24h_pct=ret24,
            )
            regime_code = "R5" if wide_chop else "R4"
            return LiveRouteClassification(
                regime_code=regime_code,
                vol_code=vol_code,
                regime_tag=RegimeTag.RANGE_HIGH_VOL.value,
                scenario="WIDE_CHOP" if regime_code == "R5" else "HIGH_VOL_CHOPPY_RANGE",
                classification_reason="low_vol_tag_overridden_by_live_vol",
            )
        return LiveRouteClassification(
            regime_code="R3",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct, volatility_score=35, return_24h_pct=ret24
            ),
            regime_tag=tag,
            scenario="LOW_VOL_COMPRESSION",
            classification_reason="low_vol_range",
        )

    if lower_lows and not higher_highs and ret24 < -3:
        reason = "lower_lows_blocks_balanced"
        return LiveRouteClassification(
            regime_code="R6",
            vol_code=classify_vol_code_v4(
                atr_1h_pct=atr_1h_pct, volatility_score=65, return_24h_pct=ret24
            ),
            regime_tag=RegimeTag.TRENDING_DOWN.value,
            scenario="LOWER_LOWS_WEAK_DOWN_RANGE",
            classification_reason=reason,
        )

    return LiveRouteClassification(
        regime_code="R2",
        vol_code=classify_vol_code_v4(
            atr_1h_pct=atr_1h_pct, volatility_score=50, return_24h_pct=ret24
        ),
        regime_tag=tag,
        scenario="BALANCED_RANGE",
        classification_reason="balanced_default",
    )
