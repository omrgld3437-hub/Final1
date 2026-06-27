"""V4 shelf taxonomy — asset/regime/structure/vol classification + clean route_key."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Asset class shelves (A1–A7)
ASSET_SHELVES: Dict[str, Tuple[str, int]] = {
    "A1": ("BTC_ETH_MAJOR", 35_000),
    "A2": ("LARGE_CAP_LIQUID", 55_000),
    "A3": ("MID_CAP_NORMAL", 55_000),
    "A4": ("HIGH_VOL_ALT", 55_000),
    "A5": ("MEME_HIGH_RISK", 40_000),
    "A6": ("LOW_LIQUIDITY", 35_000),
    "A7": ("NEW_LISTING_OR_ABNORMAL", 25_000),
}

BUDGET_SHELVES: Dict[str, Tuple[str, float, float]] = {
    "B1": ("10_25", 10.0, 25.0),
    "B2": ("25_50", 25.0, 50.0),
    "B3": ("50_100", 50.0, 100.0),
    "B4": ("100_250", 100.0, 250.0),
    "B5": ("250_500", 250.0, 500.0),
    "B6": ("500_1000", 500.0, 1000.0),
    "B7": ("1000_2500", 1000.0, 2500.0),
    "B8": ("2500_PLUS", 2500.0, 10000.0),
}

REGIME_SHELVES: Dict[str, str] = {
    "R1": "CALM_RANGE",
    "R2": "BALANCED_RANGE",
    "R3": "LOW_VOL_COMPRESSION",
    "R4": "HIGH_VOL_CHOPPY_RANGE",
    "R5": "WIDE_CHOP",
    "R6": "LOWER_LOWS_WEAK_DOWN_RANGE",
    "R7": "STRONG_DOWNTREND_RANGE",
    "R8": "CRASH_RISK",
    "R9": "HIGHER_HIGHS_WEAK_UP_RANGE",
    "R10": "STRONG_UPTREND",
    "R11": "BREAKOUT_RISK",
    "R12": "OVERSOLD_MEAN_REVERSION",
    "R13": "OVERBOUGHT_MEAN_REVERSION",
    "R14": "BTC_DRAG_PRESSURE",
    "R15": "RECOVERY_AFTER_DUMP",
    "R16": "POST_PUMP_COOLING",
    "R17": "DATA_WEAK_BUT_USABLE",
    "R18": "STRONG_DOWNTREND_RANGE",
    "R19": "STRONG_UPTREND",
}

STRUCTURE_SHELVES: Dict[str, str] = {
    "S1": "NEUTRAL_STRUCTURE",
    "S2": "LOWER_LOWS_ONLY",
    "S3": "HIGHER_HIGHS_ONLY",
    "S4": "BOTH_HH_LL_WIDE_CHOP",
    "S5": "NO_CLEAR_STRUCTURE",
    "S6": "MICRO_DOWN_MACRO_RANGE",
    "S7": "MICRO_UP_MACRO_RANGE",
    "S8": "MACRO_DOWN_MICRO_BOUNCE",
    "S9": "MACRO_UP_MICRO_PULLBACK",
}

VOL_SHELVES: Dict[str, str] = {
    "V1": "ULTRA_LOW",
    "V2": "LOW",
    "V3": "NORMAL",
    "V4": "HIGH",
    "V5": "EXTREME",
}

FEE_SHELVES: Dict[str, str] = {
    "F1": "LOW_FEE_TIGHT_SPREAD",
    "F2": "NORMAL_FEE_TIGHT_SPREAD",
    "F3": "NORMAL_FEE_NORMAL_SPREAD",
    "F4": "FEE_WEAK",
    "F5": "SPREAD_WEAK_BUT_TRADABLE",
    "F6": "FEE_BAD_ACTIVE_DEFENSIVE",
    "F7": "SPREAD_DANGEROUS_HARD_SAFETY",
}

# Priority scenario targets for the +100k new profiles
PRIORITY_SCENARIO_TARGETS: Dict[str, int] = {
    "LOWER_LOWS_DOWN_RANGE": 15_000,
    "HIGHER_HIGHS_UP_RANGE": 15_000,
    "STRONG_DOWNTREND_CRASH_DEFENSIVE": 10_000,
    "STRONG_UPTREND_BREAKOUT": 10_000,
    "WIDE_CHOP": 10_000,
    "HIGH_VOL_CHOPPY": 10_000,
    "LOW_VOL_COMPRESSION": 7_500,
    "FEE_BAD_ACTIVE_DEFENSIVE": 7_500,
    "LOW_BUDGET_MIN_NOTIONAL_EDGE": 7_500,
    "MEAN_REVERSION": 7_500,
}

# Forbidden fallback pairs: (from_regime_group, to_regime_group)
FORBIDDEN_FALLBACK_PAIRS = frozenset(
    {
        ("LOWER_LOWS", "HIGHER_HIGHS"),
        ("HIGHER_HIGHS", "LOWER_LOWS"),
        ("CRASH_RISK", "BALANCED_RANGE"),
        ("LOW_LIQUIDITY", "MAJOR_SCALP"),
        ("HIGH_VOL_ALT", "LOW_VOL_COMPRESSION"),
        ("LOWER_LOWS", "BALANCED_RANGE"),
        ("CRASH_RISK", "LOW_VOL_COMPRESSION"),
    }
)

# Direct code-pair bans (route regime/structure/vol codes).
FORBIDDEN_FALLBACK_CODE_PAIRS = frozenset(
    {
        ("R7", "R2"),
        ("R8", "R2"),
        ("R8", "R1"),
        ("R8", "R3"),
        ("S2", "S3"),
        ("S3", "S2"),
        ("V5", "V1"),
        ("V5", "V2"),
    }
)

LOWER_LOWS_REGIMES = frozenset(
    {"R6", "R7", "LOWER_LOWS_WEAK_DOWN_RANGE", "STRONG_DOWNTREND_RANGE", "WEAK_DOWNTREND_RANGE"}
)
HIGHER_HIGHS_REGIMES = frozenset(
    {"R9", "R10", "HIGHER_HIGHS_WEAK_UP_RANGE", "STRONG_UPTREND", "WEAK_UPTREND_RANGE"}
)
CRASH_REGIMES = frozenset({"R8", "CRASH_RISK", "DUMP_RISK"})
BALANCED_REGIMES = frozenset({"R2", "BALANCED_RANGE", "CALM_RANGE"})

_LEGACY_ASSET_MAP = {
    "BTC_ETH_MAJOR": "A1",
    "LARGE_CAP_LIQUID": "A2",
    "MID_CAP": "A3",
    "MID_CAP_NORMAL": "A3",
    "HIGH_VOL_ALT": "A4",
    "MEME_HIGH_RISK": "A5",
    "LOW_LIQUIDITY": "A6",
    "NEW_LISTING_OR_ABNORMAL": "A7",
}

_LEGACY_BUDGET_MAP = {
    "10_25": "B1",
    "25_50": "B2",
    "50_100": "B3",
    "100_250": "B4",
    "250_500": "B5",
    "500_1000": "B6",
    "1000_PLUS": "B8",
    "1000_2500": "B7",
    "2500_PLUS": "B8",
}

_LEGACY_REGIME_MAP = {
    "CALM_RANGE": "R1",
    "BALANCED_RANGE": "R2",
    "LOW_VOL_COMPRESSION": "R3",
    "VOLATILE_RANGE": "R4",
    "CHOPPY_RANGE": "R4",
    "HIGH_VOL_CHOPPY_RANGE": "R4",
    "WIDE_CHOP": "R5",
    "WEAK_DOWNTREND_RANGE": "R6",
    "LOWER_LOWS_WEAK_DOWN_RANGE": "R6",
    "STRONG_DOWNTREND_RISK": "R7",
    "STRONG_DOWNTREND_RANGE": "R7",
    "CRASH_RISK": "R8",
    "WEAK_UPTREND_RANGE": "R9",
    "HIGHER_HIGHS_WEAK_UP_RANGE": "R9",
    "STRONG_UPTREND_RISK": "R10",
    "STRONG_UPTREND": "R10",
    "BREAKOUT_RISK": "R11",
    "OVERSOLD_MEAN_REVERSION": "R12",
    "OVERBOUGHT_MEAN_REVERSION": "R13",
    "FEE_BAD_ACTIVE_DEFENSIVE": "R14",
    "SPREAD_WEAK_BUT_TRADABLE": "R15",
    "MIN_NOTIONAL_EDGE": "R16",
    "DATA_WEAK_BUT_USABLE": "R17",
    "LIQUIDITY_THIN_RANGE": "R17",
    "RECOVERY_RANGE": "R15",
    "RECOVERY_AFTER_DUMP": "R15",
    "POST_PUMP_COOLING": "R16",
    "BTC_DRAG_PRESSURE": "R14",
    "FEE_BAD_ACTIVE_DEFENSIVE": "R2",
    "SPREAD_WEAK_BUT_TRADABLE": "R2",
    "MIN_NOTIONAL_EDGE": "R2",
}

_LEGACY_STRUCTURE_MAP = {
    "neither": "S1",
    "NEUTRAL_STRUCTURE": "S1",
    "lower_lows_only": "S2",
    "LOWER_LOWS_ONLY": "S2",
    "higher_highs_only": "S3",
    "HIGHER_HIGHS_ONLY": "S3",
    "both": "S4",
    "BOTH_HH_LL_WIDE_CHOP": "S4",
    "NO_CLEAR_STRUCTURE": "S5",
}

_LEGACY_VOL_MAP = {
    "0_10": "V1",
    "10_25": "V2",
    "25_50": "V3",
    "50_75": "V4",
    "75_90": "V4",
    "90_100": "V5",
    "ultra_low": "V1",
    "low": "V2",
    "normal": "V3",
    "high": "V4",
    "extreme": "V5",
    "ULTRA_LOW": "V1",
    "LOW": "V2",
    "NORMAL": "V3",
    "HIGH": "V4",
    "EXTREME": "V5",
}

_LEGACY_FEE_MAP = {
    "low_fee": "F1",
    "normal_fee": "F3",
    "high_fee": "F4",
    "fee_bad": "F6",
    "LOW_FEE_TIGHT_SPREAD": "F1",
    "NORMAL_FEE_NORMAL_SPREAD": "F3",
    "FEE_WEAK": "F4",
    "FEE_BAD_ACTIVE_DEFENSIVE": "F6",
}


def asset_code_from_name(name: str) -> str:
    for code, (label, _) in ASSET_SHELVES.items():
        if label == name or code == name:
            return code
    return _LEGACY_ASSET_MAP.get(name, "A3")


def budget_code_from_class(budget_class: str) -> str:
    for code, (label, _, _) in BUDGET_SHELVES.items():
        if label == budget_class or code == budget_class:
            return code
    return _LEGACY_BUDGET_MAP.get(budget_class, "B3")


def regime_code_from_name(name: str) -> str:
    for code, label in REGIME_SHELVES.items():
        if label == name or code == name:
            return code
    return _LEGACY_REGIME_MAP.get(name, "R2")


def structure_code_from_name(name: str) -> str:
    for code, label in STRUCTURE_SHELVES.items():
        if label == name or code == name:
            return code
    return _LEGACY_STRUCTURE_MAP.get(name, "S1")


def vol_code_from_bin(vol_bin: str) -> str:
    for code, label in VOL_SHELVES.items():
        if label == vol_bin or code == vol_bin:
            return code
    return _LEGACY_VOL_MAP.get(vol_bin, "V3")


def fee_code_from_class(fee_class: str) -> str:
    for code, label in FEE_SHELVES.items():
        if label == fee_class or code == fee_class:
            return code
    return _LEGACY_FEE_MAP.get(fee_class, "F3")


def budget_class_from_usdt_v4(budget: float) -> str:
    b = max(float(budget or 0.0), 0.0)
    for code, (_, lo, hi) in BUDGET_SHELVES.items():
        if lo <= b < hi:
            return code
    return "B8"


def budget_midpoint_v4(code: str) -> float:
    _, lo, hi = BUDGET_SHELVES.get(code, ("50_100", 50.0, 100.0))
    return (lo + hi) / 2.0


def asset_class_from_symbol_v4(symbol: str) -> str:
    sym = (symbol or "").upper()
    if sym in ("BTCUSDT", "ETHUSDT", "BTCBUSD", "ETHBUSD"):
        return "A1"
    majors = (
        "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
        "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT",
    )
    if sym in majors:
        return "A2"
    meme = ("PEPEUSDT", "SHIBUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT", "MEMEUSDT")
    if sym in meme:
        return "A5"
    if sym.endswith("USDT") and len(sym) > 10:
        return "A4"
    return "A3"


def structure_from_flags_v4(lower_lows: bool, higher_highs: bool) -> str:
    if lower_lows and higher_highs:
        return "S4"
    if lower_lows:
        return "S2"
    if higher_highs:
        return "S3"
    return "S1"


def vol_code_from_atr_1h(
    atr_pct: float,
    *,
    volatility_score: int | None = None,
    return_24h_pct: float | None = None,
) -> str:
    from app.services.dynamic_param_score.param_generator.live_route_classifier_v4 import (
        classify_vol_code_v4,
    )

    return classify_vol_code_v4(
        atr_1h_pct=float(atr_pct or 0.0),
        volatility_score=int(volatility_score if volatility_score is not None else 50),
        return_24h_pct=float(return_24h_pct or 0.0),
    )


def fee_code_from_score(score: int, spread_pct: float = 0.0) -> str:
    s = int(score or 0)
    sp = max(float(spread_pct or 0.0), 0.0)
    if sp > 0.12:
        return "F7"
    if sp > 0.05:
        return "F5"
    if s >= 65:
        return "F1"
    if s >= 50:
        return "F3"
    if s >= 30:
        return "F4"
    return "F6"


def regime_code_from_live_tag(regime_tag: str, *, lower_lows: bool = False, higher_highs: bool = False) -> str:
    tag = regime_tag or ""
    if tag == "DUMP_RISK":
        return "R8"
    if tag == "TRENDING_DOWN":
        return "R6" if lower_lows else "R7"
    if tag == "TRENDING_UP":
        return "R9" if higher_highs else "R10"
    if tag == "RANGE_LOW_VOL":
        return "R3"
    if tag == "RANGE_HIGH_VOL":
        return "R4"
    if tag == "HIGH_VOL_UNSTABLE":
        return "R5"
    if tag == "BREAKOUT_RISK":
        return "R11"
    if tag == "LOW_LIQUIDITY":
        return "R17"
    if tag == "SPREAD_UNSAFE":
        return "R15"
    return _LEGACY_REGIME_MAP.get(tag, "R2")


def clean_route_key(
    asset: str,
    regime: str,
    structure: str,
    vol: str,
    risk: str = "NORMAL",
) -> str:
    """Clean route: ASSET|REGIME|STRUCTURE|VOLATILITY|RISK — no budget/fee."""
    return "|".join(
        [
            asset_code_from_name(asset) if not str(asset).startswith("A") else asset,
            regime_code_from_name(regime) if not str(regime).startswith("R") else regime,
            structure_code_from_name(structure) if not str(structure).startswith("S") else structure,
            vol_code_from_bin(vol) if not str(vol).startswith("V") else vol,
            risk or "NORMAL",
        ]
    )


def normalize_route_key(route: str) -> str:
    """Convert legacy 7-part route to clean 5-part."""
    parts = (route or "").split("|")
    if len(parts) == 7 and parts[0].startswith("A"):
        return clean_route_key(parts[0], parts[2], parts[3], parts[4], parts[6])
    if len(parts) == 5 and parts[0].startswith("A"):
        return "|".join(parts[:5])
    return route or ""


def route_key(
    asset: str,
    budget: str,
    regime: str,
    structure: str,
    vol: str,
    fee: str,
    risk: str = "NORMAL",
) -> str:
    """Legacy alias — returns clean 5-part route (budget/fee ignored for indexing)."""
    return clean_route_key(asset, regime, structure, vol, risk)


def clean_fallback_keys(route: str) -> List[str]:
    """Fallback without budget/fee dimensions — defensive risk never drops to NORMAL first."""
    parts = normalize_route_key(route).split("|")
    if len(parts) < 5:
        return []
    a, r, s, v, risk = parts[:5]
    keys: List[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key not in seen:
            seen.add(key)
            keys.append(key)

    vol_cycle = [v, "V4", "V3", "V5", "V2", "V1"]
    for alt_v in vol_cycle:
        if alt_v != v:
            _add("|".join([a, r, s, alt_v, risk]))

    if r in ("R7", "R12", "R6", "R15"):
        for alt_r in ("R7", "R12", "R6", "R15"):
            if alt_r != r:
                _add("|".join([a, alt_r, s, v, risk]))
    elif r == "R8":
        for alt_r in ("R14", "R7", "R15"):
            _add("|".join([a, alt_r, s, v, risk]))
    elif r == "R3":
        # LOW_VOL_COMPRESSION live shelf often maps to BALANCED_RANGE (R2) in the library.
        for alt_r in ("R2", "R4", "R1", "R5"):
            if alt_r == r:
                continue
            _add("|".join([a, alt_r, s, v, risk]))
            for alt_v in ("V4", "V3", "V5", "V2", "V1"):
                if alt_v != v:
                    _add("|".join([a, alt_r, s, alt_v, risk]))
    elif r == "R2" and risk in ("DEFENSIVE", "CAUTION"):
        for alt_r in ("R7", "R12", "R6"):
            _add("|".join([a, alt_r, s, v, risk]))

    if a == "A1":
        _add("|".join(["A2", r, s, v, risk]))
    elif a == "A2":
        _add("|".join(["A1", r, s, v, risk]))
    elif a == "A3":
        _add("|".join(["A2", r, s, v, risk]))
        _add("|".join(["A4", r, s, v, risk]))
    elif a == "A4":
        _add("|".join(["A3", r, s, v, risk]))

    if risk == "DEFENSIVE":
        _add("|".join([a, r, s, v, "CAUTION"]))
    elif risk == "CAUTION":
        _add("|".join([a, r, s, v, "DEFENSIVE"]))
    elif risk not in ("NORMAL", "SAFE"):
        _add("|".join([a, r, s, v, "NORMAL"]))

    def _fb_ok(candidate: str) -> bool:
        cp = candidate.split("|")
        if len(cp) < 5:
            return False
        return not is_forbidden_fallback(
            r,
            cp[1],
            from_asset=a,
            to_asset=cp[0],
            from_structure=s,
            to_structure=cp[2],
            from_vol=v,
            to_vol=cp[3],
        )

    return [k for k in keys if _fb_ok(k)]


def fallback_keys(route: str) -> List[str]:
    return clean_fallback_keys(route)


def regime_group(regime: str) -> str:
    code = regime_code_from_name(regime)
    if code in ("R6", "R7") or regime in LOWER_LOWS_REGIMES:
        return "LOWER_LOWS"
    if code in ("R9", "R10") or regime in HIGHER_HIGHS_REGIMES:
        return "HIGHER_HIGHS"
    if code == "R8" or regime in CRASH_REGIMES:
        return "CRASH_RISK"
    if code in ("R1", "R2") or regime in BALANCED_REGIMES:
        return "BALANCED_RANGE"
    if code == "R3" or regime in ("LOW_VOL_COMPRESSION",):
        return "LOW_VOL_COMPRESSION"
    if code == "R4" or regime in ("HIGH_VOL_CHOPPY_RANGE", "VOLATILE_RANGE"):
        return "HIGH_VOL_ALT"
    return "OTHER"


def asset_group(asset: str) -> str:
    code = asset_code_from_name(asset)
    if code in ("A1", "A2"):
        return "MAJOR_SCALP"
    if code == "A6":
        return "LOW_LIQUIDITY"
    if code == "A4":
        return "HIGH_VOL_ALT"
    return "OTHER"


def is_forbidden_fallback(
    from_regime: str,
    to_regime: str,
    *,
    from_asset: str = "",
    to_asset: str = "",
    from_structure: str = "",
    to_structure: str = "",
    from_vol: str = "",
    to_vol: str = "",
) -> bool:
    fr = regime_code_from_name(from_regime)
    tr = regime_code_from_name(to_regime)
    if (fr, tr) in FORBIDDEN_FALLBACK_CODE_PAIRS:
        return True
    fs = structure_code_from_name(from_structure) if from_structure else ""
    ts = structure_code_from_name(to_structure) if to_structure else ""
    if fs and ts and (fs, ts) in FORBIDDEN_FALLBACK_CODE_PAIRS:
        return True
    fv = vol_code_from_bin(from_vol) if from_vol else ""
    tv = vol_code_from_bin(to_vol) if to_vol else ""
    if fv and tv and (fv, tv) in FORBIDDEN_FALLBACK_CODE_PAIRS:
        return True
    fg = regime_group(from_regime)
    tg = regime_group(to_regime)
    if (fg, tg) in FORBIDDEN_FALLBACK_PAIRS:
        return True
    if from_asset and to_asset:
        ag = asset_group(from_asset)
        tg_a = asset_group(to_asset)
        if (ag, tg_a) in FORBIDDEN_FALLBACK_PAIRS:
            return True
    return False


def structure_to_legacy(structure_code: str) -> str:
    mapping = {
        "S1": "neither",
        "S2": "lower_lows_only",
        "S3": "higher_highs_only",
        "S4": "both",
        "S5": "neither",
        "S6": "lower_lows_only",
        "S7": "higher_highs_only",
        "S8": "lower_lows_only",
        "S9": "higher_highs_only",
    }
    return mapping.get(structure_code, "neither")


def direction_bias_for_structure(structure_code: str, regime_code: str) -> str:
    if structure_code in ("S2", "S6", "S8") or regime_code in ("R6", "R7", "R8"):
        return "DOWN_BIAS"
    if structure_code in ("S3", "S7", "S9") or regime_code in ("R9", "R10", "R11"):
        return "UP_BIAS"
    return "NEUTRAL"


def grid_bias_for_context(structure_code: str, regime_code: str) -> str:
    if structure_code == "S2" or regime_code in ("R6", "R7"):
        return "BUY_WIDER_SELL_CLOSER"
    if structure_code == "S3" or regime_code in ("R9", "R10"):
        return "SELL_WIDER_BUY_CLOSER"
    return "SYMMETRIC"


def dplv4_profile_id_clean(cell: Dict[str, Any], *, seq: int) -> str:
    a = cell.get("asset_code") or asset_code_from_name(str(cell.get("asset_class", "A3")))
    r = cell.get("regime_code") or regime_code_from_name(str(cell.get("regime", "R2")))
    s = cell.get("structure_code") or structure_code_from_name(str(cell.get("structure", "S1")))
    v = cell.get("vol_code") or vol_code_from_bin(str(cell.get("volatility_bin", "V3")))
    risk = str(cell.get("risk_class") or "NORMAL")
    return f"DPLV4_{a}_{r}_{s}_{v}_{risk}_{seq:06d}"


def dplv4_profile_id(
    cell: Dict[str, Any],
    *,
    seq: int,
    grid_model: str = "GEO3",
    side_bias: str = "NEUTRAL",
) -> str:
    return dplv4_profile_id_clean(cell, seq=seq)
