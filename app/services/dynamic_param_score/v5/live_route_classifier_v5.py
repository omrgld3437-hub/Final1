"""V5 live route classifier — 7-part exact route from market data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.dynamic_param_score.models import IndicatorSnapshot, RegimeTag, SubScores
from app.services.dynamic_param_score.v5.domain.route_key import V5RouteParts


@dataclass(frozen=True)
class V5LiveClassification:
    route_parts: V5RouteParts
    route_key: str
    classification_reason: str


def _asset_class(symbol: str, liquidity_score: int, volatility_score: int) -> str:
    sym = (symbol or "").upper()
    if sym in ("BTCUSDT", "BTCBUSD", "BTC"):
        return "A1_BTC_CORE"
    if sym in ("ETHUSDT", "ETHBUSD", "ETH"):
        return "A2_ETH_CORE"
    if liquidity_score < 35:
        return "A6_LOW_LIQUIDITY_ALT"
    if sym.endswith("USDT") and any(x in sym for x in ("DOGE", "SHIB", "PEPE", "FLOKI", "WIF", "BONK")):
        return "A5_MEME_SPECULATIVE"
    if volatility_score >= 75:
        return "A4_HIGH_BETA_ALT"
    if sym in ("BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"):
        return "A3_MAJOR_ALT"
    if liquidity_score >= 70:
        return "A3_MAJOR_ALT"
    if liquidity_score < 50:
        return "A6_LOW_LIQUIDITY_ALT"
    return "A4_HIGH_BETA_ALT"


def _breakout_continuation(ind: IndicatorSnapshot, sub: SubScores, *, confidence: float = 50.0) -> bool:
    adx = float(getattr(ind, "adx_1h", 0) or 0)
    ema20 = float(getattr(ind, "ema20_slope_5m", 0) or getattr(ind, "ema20_slope_pct", 0) or 0)
    ema50 = float(getattr(ind, "ema50_slope_5m", 0) or getattr(ind, "ema50_slope_pct", 0) or 0)
    roc = float(getattr(ind, "roc_5m", 0) or getattr(ind, "roc_5m_pct", 0) or 0)
    vol_spike = float(getattr(ind, "volume_spike_abnormality", 1) or 1)
    return (
        bool(getattr(ind, "higher_highs", False))
        and not bool(getattr(ind, "lower_lows", False))
        and float(ind.return_24h_pct or 0) > 5
        and adx >= 18
        and ema20 > 0.03
        and ema50 >= 0
        and roc > 0.15
        and vol_spike >= 1.2
        and confidence >= 35
        and int(sub.data_quality_score or 70) >= 50
    )


def _regime_v5(
    regime_tag: str,
    *,
    lower_lows: bool,
    higher_highs: bool,
    return_24h_pct: float,
    crash_velocity: float,
    btc_crash_velocity: float,
    drawdown_7d_pct: float,
    volatility_percentile: float,
    data_quality_score: int,
    ind: Optional[IndicatorSnapshot] = None,
    sub: Optional[SubScores] = None,
    confidence: float = 50.0,
) -> str:
    if data_quality_score < 40:
        return "R17_DATA_UNCERTAIN_REGIME"
    if return_24h_pct < -8 or (crash_velocity < -1.5 and return_24h_pct < -5):
        return "R8_CRASH"
    if lower_lows and return_24h_pct < -3:
        return "R10_LOWER_LOWS_DOWNTREND"
    if return_24h_pct < -5 or regime_tag == RegimeTag.TRENDING_DOWN.value:
        return "R9_STRONG_DOWNTREND"
    if return_24h_pct > 8 and higher_highs:
        return "R1_STRONG_UPTREND"
    if ind is not None and sub is not None and _breakout_continuation(ind, sub, confidence=confidence):
        return "R6_BREAKOUT_CONTINUATION"
    if return_24h_pct > 5 and higher_highs and not lower_lows:
        if ind is not None and float(getattr(ind, "adx_1h", 0) or 0) >= 18:
            return "R6_BREAKOUT_CONTINUATION"
        return "R4_VOLATILE_RANGE"
    if lower_lows and return_24h_pct < 0:
        return "R10_LOWER_LOWS_DOWNTREND"
    if volatility_percentile < 25 and abs(return_24h_pct) < 2:
        return "R3_LOW_VOL_SQUEEZE"
    if volatility_percentile > 80:
        return "R13_HIGH_VOL_DISORDER"
    if btc_crash_velocity < -1.0 and return_24h_pct < -2:
        return "R14_LOW_LIQUIDITY_DRIFT"
    if return_24h_pct < -2 and drawdown_7d_pct > 10:
        return "R12_CAPITULATION_REACTION"
    if return_24h_pct > 3 and drawdown_7d_pct > 8:
        return "R7_RECOVERY"
    if abs(return_24h_pct) > 6 and volatility_percentile > 70:
        return "R16_OVEREXTENDED_MOMENTUM"
    if volatility_percentile > 55 and abs(return_24h_pct) < 4:
        return "R4_VOLATILE_RANGE"
    if volatility_percentile < 35:
        return "R5_PRE_BREAKOUT_COMPRESSION"
    if crash_velocity < -0.8 or btc_crash_velocity < -0.8:
        return "R15_SPECIAL_STRESS_TRANSITION"
    if regime_tag == RegimeTag.BREAKOUT_RISK.value:
        return "R11_FAILED_BREAKOUT"
    return "R2_BALANCED_RANGE"


def _direction(return_24h_pct: float, ema_slope: float, z_score: Optional[float]) -> str:
    z = float(z_score or 0)
    if return_24h_pct > 3 or ema_slope > 0.15 or z > 1.0:
        return "D1_UP_BIAS"
    if return_24h_pct < -3 or ema_slope < -0.15 or z < -1.0:
        return "D3_DOWN_BIAS"
    return "D2_NEUTRAL_BIAS"


def _structure(
    lower_lows: bool,
    higher_highs: bool,
    return_24h_pct: float,
    price_in_bb: Optional[float],
) -> str:
    bb = float(price_in_bb if price_in_bb is not None else 0.5)
    if lower_lows and not higher_highs:
        return "S5_LOWER_LOWS"
    if higher_highs and not lower_lows:
        return "S4_HIGHER_HIGHS"
    if return_24h_pct < -4:
        return "S8_BREAKDOWN"
    if bb > 0.78:
        return "S2_RANGE_UPPER"
    if bb < 0.22:
        return "S3_RANGE_LOWER"
    if return_24h_pct > 4 and bb > 0.6:
        return "S6_BREAKOUT_SETUP"
    if return_24h_pct > 2 and 0.45 <= bb <= 0.65:
        return "S7_BREAKOUT_RETEST"
    if lower_lows and higher_highs:
        return "S9_UNSTRUCTURED_CHOP"
    return "S1_RANGE_MID"


def _volatility(atr_1h_pct: float, volatility_score: int, return_24h_pct: float) -> str:
    atr = max(float(atr_1h_pct or 0), 0)
    vol = int(volatility_score or 50)
    ret = abs(float(return_24h_pct or 0))
    if atr >= 5.0 or ret >= 15.0:
        return "V5_SHOCK"
    if atr >= 3.0 or vol >= 75:
        return "V4_HIGH"
    if atr < 0.5:
        return "V1_ULTRA_LOW"
    if atr < 0.9:
        return "V2_LOW"
    if atr < 1.5:
        return "V3_NORMAL"
    return "V4_HIGH"


def _risk_posture(risk_state: str) -> str:
    rs = str(risk_state or "NORMAL").upper()
    if rs in ("DEFENSIVE", "BLOCKED", "CAUTION"):
        return "K1_DEFENSIVE"
    if rs in ("AGGRESSIVE", "SAFE", "HIGH_CONFIDENCE"):
        return "K3_AGGRESSIVE"
    return "K2_NORMAL_CONTROLLED"


def _liquidity_cost(liquidity_score: int, spread_score: int, spread_pct: float) -> str:
    liq = int(liquidity_score or 50)
    spread = int(spread_score or 50)
    sp = float(spread_pct or 0)
    if liq < 30 or spread < 25 or sp > 0.5:
        return "L4_EXECUTION_RISKY"
    if liq < 50 or spread < 45 or sp > 0.25:
        return "L3_LOW_LIQUIDITY_HIGH_COST"
    if liq >= 75 and spread >= 70:
        return "L1_HIGH_LIQUIDITY_LOW_COST"
    return "L2_NORMAL_LIQUIDITY_NORMAL_COST"


def classify_live_route_v5(
    *,
    symbol: str,
    regime_tag: str,
    risk_state: str,
    sub: SubScores,
    ind: IndicatorSnapshot,
) -> V5LiveClassification:
    from app.services.dynamic_param_score.v5.domain.route_key import make_route_key

    asset = _asset_class(symbol, sub.liquidity_score, sub.volatility_score)
    regime = _regime_v5(
        regime_tag,
        lower_lows=bool(getattr(ind, "lower_lows", False)),
        higher_highs=bool(getattr(ind, "higher_highs", False)),
        return_24h_pct=float(ind.return_24h_pct or 0),
        crash_velocity=float(getattr(ind, "crash_velocity", 0) or 0),
        btc_crash_velocity=float(ind.btc_crash_velocity or 0),
        drawdown_7d_pct=float(ind.drawdown_7d_pct or 0),
        volatility_percentile=float(
            ind.volatility_percentile if ind.volatility_percentile is not None else sub.volatility_score
        ),
        data_quality_score=int(sub.data_quality_score or 70),
        ind=ind,
        sub=sub,
        confidence=float(getattr(ind, "confidence", 50) or 50),
    )
    direction = _direction(
        float(ind.return_24h_pct or 0),
        float(getattr(ind, "ema20_slope_5m", 0) or getattr(ind, "ema20_slope_pct", 0) or 0),
        ind.z_score_5m,
    )
    structure = _structure(
        bool(getattr(ind, "lower_lows", False)),
        bool(getattr(ind, "higher_highs", False)),
        float(ind.return_24h_pct or 0),
        ind.price_in_bb,
    )
    volatility = _volatility(
        float(ind.atr14_pct_1h or ind.atr14_pct_5m or 1.0),
        sub.volatility_score,
        float(ind.return_24h_pct or 0),
    )
    risk = _risk_posture(risk_state)
    liquidity = _liquidity_cost(
        sub.liquidity_score,
        sub.spread_score,
        float(ind.orderbook_spread_pct or 0),
    )
    parts = V5RouteParts(
        asset=asset,
        regime=regime,
        direction=direction,
        structure=structure,
        volatility=volatility,
        risk=risk,
        liquidity=liquidity,
    )
    rk = make_route_key(parts)
    return V5LiveClassification(
        route_parts=parts,
        route_key=rk,
        classification_reason=f"live_v5:{regime}:{direction}:{structure}",
    )
