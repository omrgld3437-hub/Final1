"""Feature binning for DPS Engine V2 scenario coverage."""

from __future__ import annotations

from typing import Literal, Optional

AssetClass = Literal[
    "BTC_ETH_MAJOR",
    "LARGE_CAP_LIQUID",
    "MID_CAP",
    "HIGH_VOL_ALT",
    "MEME_HIGH_RISK",
    "LOW_LIQUIDITY",
]

BudgetClass = Literal[
    "10_25",
    "25_50",
    "50_100",
    "100_250",
    "250_500",
    "500_1000",
    "1000_PLUS",
]

RegimeClass = Literal[
    "CALM_RANGE",
    "BALANCED_RANGE",
    "VOLATILE_RANGE",
    "CHOPPY_RANGE",
    "WEAK_DOWNTREND_RANGE",
    "STRONG_DOWNTREND_RISK",
    "WEAK_UPTREND_RANGE",
    "STRONG_UPTREND_RISK",
    "BREAKOUT_RISK",
    "CRASH_RISK",
    "RECOVERY_RANGE",
    "LIQUIDITY_THIN_RANGE",
]

ASSET_CLASSES: tuple[str, ...] = (
    "BTC_ETH_MAJOR",
    "LARGE_CAP_LIQUID",
    "MID_CAP",
    "HIGH_VOL_ALT",
    "MEME_HIGH_RISK",
    "LOW_LIQUIDITY",
)

BUDGET_CLASSES: tuple[str, ...] = (
    "10_25",
    "25_50",
    "50_100",
    "100_250",
    "250_500",
    "500_1000",
    "1000_PLUS",
)

REGIME_CLASSES: tuple[str, ...] = (
    "CALM_RANGE",
    "BALANCED_RANGE",
    "VOLATILE_RANGE",
    "CHOPPY_RANGE",
    "WEAK_DOWNTREND_RANGE",
    "STRONG_DOWNTREND_RISK",
    "WEAK_UPTREND_RANGE",
    "STRONG_UPTREND_RISK",
    "BREAKOUT_RISK",
    "CRASH_RISK",
    "RECOVERY_RANGE",
    "LIQUIDITY_THIN_RANGE",
)

VOLATILITY_BINS: tuple[str, ...] = (
    "0_10",
    "10_25",
    "25_50",
    "50_75",
    "75_90",
    "90_100",
)

ATR_1H_BINS: tuple[str, ...] = ("ultra_low", "low", "normal", "high", "extreme")
ADX_BINS: tuple[str, ...] = ("no_trend", "weak_trend", "moderate_trend", "strong_trend")
RSI_STATES: tuple[str, ...] = ("oversold", "low_neutral", "neutral", "high_neutral", "overbought")
BB_POSITIONS: tuple[str, ...] = ("lower_band", "lower_mid", "mid", "upper_mid", "upper_band")
STRUCTURES: tuple[str, ...] = ("higher_highs_only", "lower_lows_only", "both", "neither")
FEE_CLASSES: tuple[str, ...] = ("low_fee", "normal_fee", "high_fee", "fee_bad")
SPREAD_CLASSES: tuple[str, ...] = ("tight", "normal", "wide", "dangerous")
DATA_QUALITIES: tuple[str, ...] = ("excellent", "good", "usable", "weak")


def budget_class_from_usdt(budget: float) -> str:
    b = max(float(budget or 0.0), 0.0)
    if b < 25:
        return "10_25"
    if b < 50:
        return "25_50"
    if b < 100:
        return "50_100"
    if b < 250:
        return "100_250"
    if b < 500:
        return "250_500"
    if b < 1000:
        return "500_1000"
    return "1000_PLUS"


def volatility_bin_from_percentile(pct: float) -> str:
    v = max(0.0, min(100.0, float(pct or 0.0)))
    if v < 10:
        return "0_10"
    if v < 25:
        return "10_25"
    if v < 50:
        return "25_50"
    if v < 75:
        return "50_75"
    if v < 90:
        return "75_90"
    return "90_100"


def atr_1h_bin_from_pct(atr_pct: float) -> str:
    a = max(float(atr_pct or 0.0), 0.0)
    if a < 0.5:
        return "ultra_low"
    if a < 0.9:
        return "low"
    if a < 1.5:
        return "normal"
    if a < 2.5:
        return "high"
    return "extreme"


def adx_bin_from_value(adx: float) -> str:
    a = max(float(adx or 0.0), 0.0)
    if a < 15:
        return "no_trend"
    if a < 22:
        return "weak_trend"
    if a < 30:
        return "moderate_trend"
    return "strong_trend"


def rsi_state_from_value(rsi: float) -> str:
    r = max(0.0, min(100.0, float(rsi or 50.0)))
    if r < 30:
        return "oversold"
    if r < 45:
        return "low_neutral"
    if r < 55:
        return "neutral"
    if r < 70:
        return "high_neutral"
    return "overbought"


def bb_position_from_value(pos: float) -> str:
    p = max(0.0, min(1.0, float(pos or 0.5)))
    if p < 0.2:
        return "lower_band"
    if p < 0.4:
        return "lower_mid"
    if p < 0.6:
        return "mid"
    if p < 0.8:
        return "upper_mid"
    return "upper_band"


def structure_from_flags(
    lower_lows: bool,
    higher_highs: bool,
) -> str:
    if lower_lows and higher_highs:
        return "both"
    if lower_lows:
        return "lower_lows_only"
    if higher_highs:
        return "higher_highs_only"
    return "neither"


def fee_class_from_score(score: int) -> str:
    s = int(score or 0)
    if s >= 65:
        return "low_fee"
    if s >= 50:
        return "normal_fee"
    if s >= 30:
        return "high_fee"
    return "fee_bad"


def spread_class_from_pct(spread_pct: float) -> str:
    s = max(float(spread_pct or 0.0), 0.0)
    if s <= 0.02:
        return "tight"
    if s <= 0.05:
        return "normal"
    if s <= 0.12:
        return "wide"
    return "dangerous"


def data_quality_class_from_score(score: int) -> str:
    s = int(score or 0)
    if s >= 90:
        return "excellent"
    if s >= 75:
        return "good"
    if s >= 55:
        return "usable"
    return "weak"


def asset_class_from_symbol(symbol: str) -> str:
    sym = (symbol or "").upper()
    if sym in ("BTCUSDT", "ETHUSDT", "BTCBUSD", "ETHBUSD"):
        return "BTC_ETH_MAJOR"
    majors = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT")
    if sym in majors:
        return "LARGE_CAP_LIQUID"
    meme = ("PEPEUSDT", "SHIBUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT")
    if sym in meme:
        return "MEME_HIGH_RISK"
    return "MID_CAP"


def regime_class_from_tag(regime_tag: str) -> str:
    mapping = {
        "RANGE_LOW_VOL": "CALM_RANGE",
        "BALANCED_RANGE": "BALANCED_RANGE",
        "RANGE_HIGH_VOL": "VOLATILE_RANGE",
        "HIGH_VOL_UNSTABLE": "CHOPPY_RANGE",
        "TRENDING_DOWN": "WEAK_DOWNTREND_RANGE",
        "DUMP_RISK": "CRASH_RISK",
        "TRENDING_UP": "WEAK_UPTREND_RANGE",
        "BREAKOUT_RISK": "BREAKOUT_RISK",
        "LOW_LIQUIDITY": "LIQUIDITY_THIN_RANGE",
        "NO_DATA": "LIQUIDITY_THIN_RANGE",
        "SPREAD_UNSAFE": "LIQUIDITY_THIN_RANGE",
    }
    return mapping.get(regime_tag or "", "BALANCED_RANGE")
