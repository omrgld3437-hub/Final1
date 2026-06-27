"""V5 route dimension constants — 7 × 17 × 3 × 9 × 5 × 3 × 4 = 192,780."""

from __future__ import annotations

from typing import Literal, Tuple

ASSET_CLASSES: Tuple[str, ...] = (
    "A1_BTC_CORE",
    "A2_ETH_CORE",
    "A3_MAJOR_ALT",
    "A4_HIGH_BETA_ALT",
    "A5_MEME_SPECULATIVE",
    "A6_LOW_LIQUIDITY_ALT",
    "A7_STABLE_OR_SPECIAL",
)

REGIMES: Tuple[str, ...] = (
    "R1_STRONG_UPTREND",
    "R2_BALANCED_RANGE",
    "R3_LOW_VOL_SQUEEZE",
    "R4_VOLATILE_RANGE",
    "R5_PRE_BREAKOUT_COMPRESSION",
    "R6_BREAKOUT_CONTINUATION",
    "R7_RECOVERY",
    "R8_CRASH",
    "R9_STRONG_DOWNTREND",
    "R10_LOWER_LOWS_DOWNTREND",
    "R11_FAILED_BREAKOUT",
    "R12_CAPITULATION_REACTION",
    "R13_HIGH_VOL_DISORDER",
    "R14_LOW_LIQUIDITY_DRIFT",
    "R15_SPECIAL_STRESS_TRANSITION",
    "R16_OVEREXTENDED_MOMENTUM",
    "R17_DATA_UNCERTAIN_REGIME",
)

DIRECTIONS: Tuple[str, ...] = (
    "D1_UP_BIAS",
    "D2_NEUTRAL_BIAS",
    "D3_DOWN_BIAS",
)

STRUCTURES: Tuple[str, ...] = (
    "S1_RANGE_MID",
    "S2_RANGE_UPPER",
    "S3_RANGE_LOWER",
    "S4_HIGHER_HIGHS",
    "S5_LOWER_LOWS",
    "S6_BREAKOUT_SETUP",
    "S7_BREAKOUT_RETEST",
    "S8_BREAKDOWN",
    "S9_UNSTRUCTURED_CHOP",
)

VOLATILITIES: Tuple[str, ...] = (
    "V1_ULTRA_LOW",
    "V2_LOW",
    "V3_NORMAL",
    "V4_HIGH",
    "V5_SHOCK",
)

RISK_POSTURES: Tuple[str, ...] = (
    "K1_DEFENSIVE",
    "K2_NORMAL_CONTROLLED",
    "K3_AGGRESSIVE",
)

LIQUIDITY_COSTS: Tuple[str, ...] = (
    "L1_HIGH_LIQUIDITY_LOW_COST",
    "L2_NORMAL_LIQUIDITY_NORMAL_COST",
    "L3_LOW_LIQUIDITY_HIGH_COST",
    "L4_EXECUTION_RISKY",
)

AssetClass = Literal[
    "A1_BTC_CORE",
    "A2_ETH_CORE",
    "A3_MAJOR_ALT",
    "A4_HIGH_BETA_ALT",
    "A5_MEME_SPECULATIVE",
    "A6_LOW_LIQUIDITY_ALT",
    "A7_STABLE_OR_SPECIAL",
]
Regime = Literal[
    "R1_STRONG_UPTREND",
    "R2_BALANCED_RANGE",
    "R3_LOW_VOL_SQUEEZE",
    "R4_VOLATILE_RANGE",
    "R5_PRE_BREAKOUT_COMPRESSION",
    "R6_BREAKOUT_CONTINUATION",
    "R7_RECOVERY",
    "R8_CRASH",
    "R9_STRONG_DOWNTREND",
    "R10_LOWER_LOWS_DOWNTREND",
    "R11_FAILED_BREAKOUT",
    "R12_CAPITULATION_REACTION",
    "R13_HIGH_VOL_DISORDER",
    "R14_LOW_LIQUIDITY_DRIFT",
    "R15_SPECIAL_STRESS_TRANSITION",
    "R16_OVEREXTENDED_MOMENTUM",
    "R17_DATA_UNCERTAIN_REGIME",
]
Direction = Literal["D1_UP_BIAS", "D2_NEUTRAL_BIAS", "D3_DOWN_BIAS"]
Structure = Literal[
    "S1_RANGE_MID",
    "S2_RANGE_UPPER",
    "S3_RANGE_LOWER",
    "S4_HIGHER_HIGHS",
    "S5_LOWER_LOWS",
    "S6_BREAKOUT_SETUP",
    "S7_BREAKOUT_RETEST",
    "S8_BREAKDOWN",
    "S9_UNSTRUCTURED_CHOP",
]
Volatility = Literal["V1_ULTRA_LOW", "V2_LOW", "V3_NORMAL", "V4_HIGH", "V5_SHOCK"]
RiskPosture = Literal["K1_DEFENSIVE", "K2_NORMAL_CONTROLLED", "K3_AGGRESSIVE"]
LiquidityCost = Literal[
    "L1_HIGH_LIQUIDITY_LOW_COST",
    "L2_NORMAL_LIQUIDITY_NORMAL_COST",
    "L3_LOW_LIQUIDITY_HIGH_COST",
    "L4_EXECUTION_RISKY",
]

EXPECTED_V5_SHELF_COUNT = (
    len(ASSET_CLASSES)
    * len(REGIMES)
    * len(DIRECTIONS)
    * len(STRUCTURES)
    * len(VOLATILITIES)
    * len(RISK_POSTURES)
    * len(LIQUIDITY_COSTS)
)

assert EXPECTED_V5_SHELF_COUNT == 192_780, (
    f"Expected 192780 shelves, got {EXPECTED_V5_SHELF_COUNT}"
)

# Human-readable labels for UI trace
DIMENSION_LABELS = {
    **{a: a.split("_", 1)[1].replace("_", " ") for a in ASSET_CLASSES},
    **{r: r.split("_", 1)[1].replace("_", " ") for r in REGIMES},
    **{d: d.split("_", 1)[1].replace("_", " ") for d in DIRECTIONS},
    **{s: s.split("_", 1)[1].replace("_", " ") for s in STRUCTURES},
    **{v: v.split("_", 1)[1].replace("_", " ") for v in VOLATILITIES},
    **{k: k.split("_", 1)[1].replace("_", " ") for k in RISK_POSTURES},
    **{l: l.split("_", 1)[1].replace("_", " ") for l in LIQUIDITY_COSTS},
}
