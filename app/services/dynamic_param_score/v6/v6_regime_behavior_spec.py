"""V6 regime behavior spec — Ömer 8-rejim DEF/STD/ACT şartnamesi (tek kaynak davranış)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.v6.constants import (
    DEFAULT_COST_FLOOR_PCT,
    TRAILING_CODES,
    TRAILING_PCT_TO_CODE,
)
from app.services.dynamic_param_score.v6.domain.types import (
    GridLevel,
    SeverityMode,
    V6CatalogProfile,
    V6InputContract,
)
from app.services.dynamic_param_score.v6.v6_quantizer import (
    profit_code_from_pct,
    quantize_profile,
    quantize_profit_trigger_pct,
    trailing_code_from_pct,
)

SeverityKey = Tuple[str, SeverityMode]
_LAYER_ORDER = ("L1_REGIME_COHERENCE", "L2_RISK_SEVERITY", "L3_CAPITAL_ALLOCATION", "L4_GRID_EXECUTION", "L5_PROFIT_TRAILING_SAFETY")
_SEVERITY_RANK = {"DEF": 0, "STD": 1, "ACT": 2}
_VALID_TRAILING = tuple(sorted(TRAILING_CODES.values()))

# Named sell amount distributions (intentional, not random)
SELL_AMOUNTS_NAMED: Dict[str, Tuple[int, ...]] = {
    "BALANCED_VOL_SELL_5": (10, 15, 20, 25, 30),
    "RISK_REDUCE_SELL_4": (35, 30, 20, 15),
    "TREND_FOLLOW_SELL_5": (5, 10, 20, 30, 35),
    "VOL_RANGE_EARLY_BALANCED_SELL_4": (25, 30, 25, 20),
    "LOW_LIQUIDITY_SELL_3": (45, 35, 20),
    "LOW_LIQUIDITY_SELL_4": (35, 30, 20, 15),
}
BUY_AMOUNTS_DEF_5 = (5, 10, 15, 25, 45)
BUY_AMOUNTS_STD_5 = (5, 10, 20, 30, 35)
BUY_AMOUNTS_FRAGILE_LIQUID_5 = (5, 10, 15, 25, 45)


@dataclass(frozen=True)
class RegimeBehaviorTemplate:
    initial_base_pct: int
    initial_quote_pct: int
    max_total_exposure_pct: int
    active_buy_ladder_pct: int
    reserved_quote_pct: int
    buy_grid_enabled: bool
    buy_grid_count: int
    buy_distances_pct: Tuple[int, ...]
    buy_amounts_pct: Tuple[int, ...]
    sell_grid_enabled: bool
    sell_grid_count: int
    sell_distances_pct: Tuple[int, ...]
    sell_amounts_pct: Tuple[int, ...]
    profit_sell_enabled: bool
    profit_sell_trigger_pct: float
    profit_sell_mode: str
    trailing_sell_pct: float
    profit_buyback_enabled: bool
    profit_buyback_trigger_pct: float
    profit_buyback_mode: str
    trailing_buyback_pct: float
    new_buys_status: str = "active"
    new_buys_paused: bool = False
    buyback_restricted: bool = False
    max_buyback_of_sold_pct: Optional[int] = None
    max_single_profit_sell_pct: Optional[int] = None
    trend_tail_base_reserve_pct: Optional[int] = None


def _tpl(
    base: int,
    quote: int,
    max_exp: int,
    buy_ladder: int,
    reserved: int,
    buy_n: int,
    buy_d: List[int],
    buy_a: List[int],
    sell_n: int,
    sell_d: List[int],
    sell_a: List[int],
    ps_trig: float,
    ps_trail: float,
    pb_trig: float,
    pb_trail: float,
    *,
    ps_mode: str = "trailing_after_trigger",
    pb_mode: str = "trailing_rebuy",
    buy_enabled: bool = True,
    new_buys: str = "active",
    paused: bool = False,
    buyback_restricted: bool = False,
    max_buyback_pct: Optional[int] = None,
    max_single_ps: Optional[int] = None,
    tail_reserve: Optional[int] = None,
) -> RegimeBehaviorTemplate:
    return RegimeBehaviorTemplate(
        initial_base_pct=base,
        initial_quote_pct=quote,
        max_total_exposure_pct=max_exp,
        active_buy_ladder_pct=buy_ladder,
        reserved_quote_pct=reserved,
        buy_grid_enabled=buy_enabled,
        buy_grid_count=buy_n,
        buy_distances_pct=tuple(buy_d),
        buy_amounts_pct=tuple(buy_a),
        sell_grid_enabled=True,
        sell_grid_count=sell_n,
        sell_distances_pct=tuple(sell_d),
        sell_amounts_pct=tuple(sell_a),
        profit_sell_enabled=True,
        profit_sell_trigger_pct=ps_trig,
        profit_sell_mode=ps_mode,
        trailing_sell_pct=ps_trail,
        profit_buyback_enabled=True,
        profit_buyback_trigger_pct=pb_trig,
        profit_buyback_mode=pb_mode,
        trailing_buyback_pct=pb_trail,
        new_buys_status=new_buys,
        new_buys_paused=paused,
        buyback_restricted=buyback_restricted,
        max_buyback_of_sold_pct=max_buyback_pct,
        max_single_profit_sell_pct=max_single_ps,
        trend_tail_base_reserve_pct=tail_reserve,
    )


# --- R1 Güçlü yükseliş ---
_R1: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(50, 50, 65, 15, 35, 3, [3, 6, 10], [15, 30, 55], 4, [2, 5, 9, 14], [10, 20, 30, 40], 2.0, 0.8, 3.0, 0.8, max_single_ps=30, tail_reserve=25),
    "STD": _tpl(65, 35, 80, 20, 20, 3, [2, 5, 8], [15, 30, 55], 5, [3, 6, 10, 15, 21], [5, 10, 20, 30, 35], 2.5, 1.1, 3.5, 1.1),
    "ACT": _tpl(75, 25, 90, 20, 10, 2, [2, 4], [35, 65], 5, [4, 8, 13, 19, 26], [5, 10, 20, 30, 35], 3.0, 1.4, 4.0, 1.1),
}
_R1_STD_PULLBACK = _tpl(
    60, 40, 80, 30, 25, 3, [2, 5, 9], [15, 30, 55],
    5, [3, 6, 10, 15, 21], list(SELL_AMOUNTS_NAMED["BALANCED_VOL_SELL_5"]),
    3.0, 1.1, 3.5, 1.1,
)
_R1_STD_TREND_COOLDOWN = _tpl(
    60, 40, 80, 30, 25, 3, [2, 4, 7], [15, 30, 55],
    5, [2, 4, 7, 11, 16], [10, 15, 20, 25, 30],
    2.5, 0.8, 2.5, 1.1,
)

# --- R2 Dengeli range ---
_R2: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(40, 60, 60, 30, 40, 4, [2, 4, 7, 11], [10, 20, 30, 40], 4, [2, 4, 7, 10], [25, 30, 25, 20], 1.5, 0.5, 2.0, 0.5, ps_mode="staged_plus_trailing"),
    "STD": _tpl(50, 50, 70, 40, 30, 5, [1, 3, 5, 8, 12], [5, 10, 20, 30, 35], 5, [1, 3, 5, 8, 12], [10, 15, 20, 25, 30], 1.5, 0.5, 1.5, 0.5, ps_mode="staged_plus_trailing"),
    "ACT": _tpl(60, 40, 75, 35, 25, 4, [1, 2, 4, 7], [10, 20, 30, 40], 5, [2, 4, 7, 10, 14], [10, 15, 20, 25, 30], 2.0, 0.8, 2.0, 0.8, ps_mode="staged_plus_trailing"),
}

# --- R3 Düşük volatilite / sıkışma ---
_R3: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(35, 65, 50, 20, 50, 3, [1, 3, 6], [10, 25, 65], 3, [1, 2, 4], [45, 35, 20], 1.0, 0.5, 1.5, 0.5, ps_mode="staged_plus_tight_trailing"),
    "STD": _tpl(45, 55, 60, 25, 40, 4, [1, 2, 4, 6], [10, 20, 30, 40], 4, [1, 2, 4, 6], [25, 30, 25, 20], 1.0, 0.5, 1.5, 0.5, ps_mode="staged_plus_tight_trailing"),
    "ACT": _tpl(55, 45, 65, 25, 35, 3, [1, 2, 4], [15, 30, 55], 4, [2, 4, 7, 10], [15, 25, 30, 30], 1.5, 0.5, 2.0, 0.5, ps_mode="staged_plus_trailing"),
}

# --- R4 Yüksek volatilite range ---
_R4: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(30, 70, 55, 25, 45, 5, [3, 6, 10, 15, 21], list(BUY_AMOUNTS_DEF_5), 4, [3, 6, 10, 15], list(SELL_AMOUNTS_NAMED["VOL_RANGE_EARLY_BALANCED_SELL_4"]), 2.5, 1.1, 3.5, 1.1, ps_mode="staged_plus_trailing"),
    "STD": _tpl(45, 55, 65, 35, 35, 5, [2, 5, 9, 14, 20], list(BUY_AMOUNTS_STD_5), 5, [3, 6, 10, 15, 21], list(SELL_AMOUNTS_NAMED["BALANCED_VOL_SELL_5"]), 2.5, 1.1, 3.0, 1.1, ps_mode="staged_plus_trailing"),
    "ACT": _tpl(55, 45, 75, 35, 25, 4, [2, 4, 8, 13], [10, 20, 30, 40], 5, [3, 7, 12, 18, 25], list(SELL_AMOUNTS_NAMED["TREND_FOLLOW_SELL_5"]), 3.0, 1.4, 3.5, 1.1, ps_mode="staged_plus_trailing"),
}

_R4_STD_LIQUID = _R4["STD"]
_R4_DEF_OVERHEATED = _tpl(
    35, 65, 55, 25, 45, 5, [3, 6, 10, 15, 21], list(BUY_AMOUNTS_DEF_5), 4, [3, 6, 10, 15],
    list(SELL_AMOUNTS_NAMED["RISK_REDUCE_SELL_4"]), 2.5, 1.1, 3.5, 1.1, ps_mode="staged_plus_trailing",
)
_R4_DEF_LOW_LIQUIDITY = _tpl(
    12, 88, 28, 15, 72, 5, [5, 8, 12, 17, 23], list(BUY_AMOUNTS_DEF_5), 4, [3, 6, 10, 15],
    list(SELL_AMOUNTS_NAMED["LOW_LIQUIDITY_SELL_4"]), 3.0, 1.1, 4.0, 1.1,
    new_buys="restricted", ps_mode="staged_plus_trailing",
)
_R4_ACT_LOWER_BAND_BOUNCE = _tpl(
    55, 45, 75, 35, 25, 4, [2, 4, 8, 13], [10, 20, 30, 40], 5, [3, 7, 12, 18, 25],
    list(SELL_AMOUNTS_NAMED["TREND_FOLLOW_SELL_5"]), 3.0, 1.4, 3.5, 1.1, ps_mode="staged_plus_trailing",
)
_R4_RESTRICTED_UNSTABLE = _tpl(
    10, 90, 25, 10, 80, 3, [6, 12, 20], [10, 25, 65], 3, [3, 6, 10],
    list(SELL_AMOUNTS_NAMED["LOW_LIQUIDITY_SELL_3"]), 3.0, 1.1, 4.5, 1.4,
    new_buys="restricted", buyback_restricted=True, ps_mode="staged_plus_trailing",
)
_R4_FRAGILE_BUT_LIQUID = _tpl(
    35, 65, 60, 30, 40, 5, [3, 6, 10, 15, 21], list(BUY_AMOUNTS_FRAGILE_LIQUID_5), 4, [2, 5, 9, 14],
    list(SELL_AMOUNTS_NAMED["RISK_REDUCE_SELL_4"]), 3.0, 1.1, 3.5, 1.1, ps_mode="staged_plus_trailing",
)

# --- R5 Yukarı breakout ---
_R5: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(50, 50, 65, 15, 35, 3, [2, 5, 9], [15, 30, 55], 4, [3, 6, 10, 16], [10, 20, 30, 40], 2.5, 1.1, 3.0, 0.8),
    "STD": _tpl(65, 35, 80, 20, 20, 3, [2, 4, 7], [15, 30, 55], 5, [4, 8, 13, 19, 26], [5, 10, 20, 30, 35], 3.0, 1.4, 3.5, 1.1),
    "ACT": _tpl(75, 25, 90, 20, 10, 2, [2, 4], [35, 65], 5, [5, 10, 16, 23, 31], [5, 10, 20, 30, 35], 3.5, 1.7, 4.0, 1.4),
}
_R5_DEF_PARABOLIC_OVEREXTENDED = _tpl(
    5, 95, 15, 0, 85, 1, [20], [100], 3, [5, 10, 18],
    list(SELL_AMOUNTS_NAMED["LOW_LIQUIDITY_SELL_3"]),
    5.0, 1.4, 8.0, 1.4,
    buy_enabled=False, new_buys="paused", paused=True,
    pb_mode="restricted_trailing_rebuy", buyback_restricted=True, max_buyback_pct=35,
    ps_mode="risk_reduce_trailing",
)
_R5_DEF_OVEREXTENDED = _tpl(
    45, 55, 65, 20, 45, 3, [3, 6, 10], [15, 30, 55],
    4, [2, 5, 9, 14], list(SELL_AMOUNTS_NAMED["RISK_REDUCE_SELL_4"]),
    3.0, 1.1, 4.0, 1.1,
    new_buys="restricted", pb_mode="restricted_trailing_rebuy",
    buyback_restricted=True, max_buyback_pct=50, ps_mode="risk_reduce_trailing",
)

# --- R6 Recovery ---
_R6: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(35, 65, 55, 20, 45, 4, [2, 5, 9, 14], [5, 15, 30, 50], 4, [2, 4, 7, 11], [35, 30, 20, 15], 2.0, 0.8, 3.0, 0.8, ps_mode="staged_plus_trailing"),
    "STD": _tpl(50, 50, 70, 30, 30, 4, [2, 4, 7, 11], [10, 20, 30, 40], 4, [3, 6, 10, 15], [15, 25, 30, 30], 2.5, 1.1, 3.0, 1.1, ps_mode="staged_plus_trailing"),
    "ACT": _tpl(65, 35, 80, 25, 20, 3, [2, 4, 7], [15, 30, 55], 5, [3, 6, 10, 15, 21], [10, 15, 20, 25, 30], 2.5, 1.1, 3.5, 1.1),
}

# --- R7 Düşüş trendi ---
_R7: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _tpl(15, 85, 35, 10, 65, 3, [5, 10, 17], [10, 25, 65], 3, [2, 4, 7], [45, 35, 20], 1.5, 0.5, 4.0, 1.1, ps_mode="staged_plus_tight_trailing"),
    "STD": _tpl(30, 70, 50, 20, 50, 4, [4, 8, 13, 19], [5, 15, 30, 50], 4, [2, 5, 8, 12], [35, 30, 20, 15], 2.0, 0.8, 4.0, 1.1, ps_mode="staged_plus_trailing"),
    "ACT": _tpl(40, 60, 60, 25, 40, 3, [3, 7, 12], [15, 30, 55], 4, [3, 6, 10, 15], [25, 30, 25, 20], 2.5, 1.1, 3.5, 1.1, ps_mode="staged_plus_trailing"),
}

# --- R8 Crash ---
_R8_DEF_PANIC = _tpl(
    5, 95, 15, 0, 85, 1, [20], [100], 3, [2, 5, 9], list(SELL_AMOUNTS_NAMED["LOW_LIQUIDITY_SELL_3"]),
    2.5, 0.5, 6.0, 1.4,
    buy_enabled=False, new_buys="paused", paused=True,
    pb_mode="restricted_trailing_rebuy", buyback_restricted=True, max_buyback_pct=35,
    ps_mode="risk_reduce_trailing",
)
_R8_RECOVERY_RESTRICTED = _tpl(
    20, 80, 25, 10, 70, 2, [6, 12], [35, 65], 4, [3, 6, 10, 15],
    list(SELL_AMOUNTS_NAMED["RISK_REDUCE_SELL_4"]), 2.0, 0.8, 5.0, 1.1,
    new_buys="restricted", pb_mode="restricted_trailing_rebuy", buyback_restricted=True, max_buyback_pct=50,
    ps_mode="risk_reduce_trailing",
)

_R8: Dict[SeverityMode, RegimeBehaviorTemplate] = {
    "DEF": _R8_DEF_PANIC,
    "STD": _tpl(
        15, 85, 25, 5, 75, 2, [10, 18], [25, 75], 3, [2, 5, 10],
        list(SELL_AMOUNTS_NAMED["LOW_LIQUIDITY_SELL_3"]),
        2.0, 0.8, 5.0, 1.4,
        new_buys="restricted", pb_mode="restricted_trailing_rebuy", buyback_restricted=True, max_buyback_pct=50,
        ps_mode="risk_reduce_trailing",
    ),
    "ACT": _tpl(
        25, 75, 35, 10, 65, 2, [6, 12], [35, 65], 4, [3, 6, 10, 15],
        list(SELL_AMOUNTS_NAMED["RISK_REDUCE_SELL_4"]),
        2.5, 1.1, 4.0, 1.1,
        new_buys="restricted", pb_mode="restricted_trailing_rebuy", buyback_restricted=True, max_buyback_pct=60,
        ps_mode="risk_reduce_trailing",
    ),
}

REGIME_BEHAVIOR_TEMPLATES: Dict[str, Dict[SeverityMode, RegimeBehaviorTemplate]] = {
    "R1": _R1,
    "R2": _R2,
    "R3": _R3,
    "R4": _R4,
    "R5": _R5,
    "R6": _R6,
    "R7": _R7,
    "R8": _R8,
}


def _liquid_coin(inp: V6InputContract) -> bool:
    spread = float(inp.spread_pct if inp.spread_pct is not None else 1.0)
    vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    vol = float(inp.volume_24h or 0)
    return spread <= 0.03 and vq >= 0.45 and vol >= 1_000_000


def _infer_r4_sub_profile(inp: V6InputContract, trace: List[Dict[str, Any]]) -> str:
    spread = float(inp.spread_pct or 0)
    vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    rs = float(inp.range_stability or 0)
    frag = _trace_class(trace, "asset_fragility") or str(inp.asset_fragility_class or "F1")
    if rs < 0.20 or spread >= 0.20:
        return "R4_RESTRICTED_UNSTABLE"
    if spread >= 0.10 or vq < 0.40:
        return "R4_DEF_LOW_LIQUIDITY"
    if frag == "F2" and _liquid_coin(inp):
        return "R4_FRAGILE_BUT_LIQUID"
    if (inp.rsi_1h or 0) >= 70 or (inp.bb_position or 0) >= 0.75:
        return "R4_DEF_OVERHEATED"
    if (inp.bb_position or 0.5) <= 0.25 and (inp.rsi_1h or 50) < 62:
        return "R4_ACT_LOWER_BAND_BOUNCE"
    return "R4_STD_LIQUID"


def _infer_r8_sub_profile(inp: V6InputContract) -> str:
    ret24 = inp.return_24h_pct or 0
    ret1 = inp.return_1h_pct or 0
    ret4 = inp.return_4h_pct or 0
    if ret24 < -3 and (ret1 > 0 or ret4 > 0) and inp.higher_highs and not inp.lower_lows:
        return "R8_RECOVERY_RESTRICTED"
    return "R8_DEF_PANIC"


def _is_r1_pullback_setup(inp: V6InputContract) -> bool:
    if (inp.price_vs_ema200_pct or 0) < 3:
        return False
    if (inp.adx_1h or 0) < 25:
        return False
    if (inp.return_24h_pct or 0) <= 2:
        return False
    votes = 0
    if (inp.ema20_slope or 0) < 0:
        votes += 1
    if (inp.ema50_slope or 0) < 0:
        votes += 1
    if (inp.roc_5m or 0) < 0:
        votes += 1
    if inp.lower_lows:
        votes += 1
    if inp.higher_highs is False:
        votes += 1
    if (inp.bb_position or 0.5) <= 0.25:
        votes += 1
    if (inp.z_score or 0) <= -1.0:
        votes += 1
    if (inp.rsi_5m or 50) < 45:
        votes += 1
    return votes >= 4


def _is_r1_trend_cooldown_setup(inp: V6InputContract) -> bool:
    return (
        inp.higher_highs is True
        and inp.lower_lows is False
        and (inp.price_vs_ema200_pct or 0) >= 1.5
        and (inp.return_24h_pct or 0) >= 1.5
        and (inp.rsi_1h or 0) < 70
        and (inp.bb_position or 0) < 0.75
        and (inp.z_score or 0) < 1.0
        and (inp.roc_5m or 0) < 0.5
        and (inp.return_1h_pct or 0) < 0.7
        and (inp.return_4h_pct or 0) < 1.5
        and (inp.ema20_slope or 0) < 0.15
        and (inp.ema50_slope or 0) < 0.10
    )


def _is_overextended_top_setup(inp: V6InputContract) -> bool:
    top_votes = 0
    if (inp.rsi_1h or 0) >= 70:
        top_votes += 1
    if (inp.bb_position or 0) >= 0.75:
        top_votes += 1
    if (inp.z_score or 0) >= 1.0:
        top_votes += 1
    if (inp.price_vs_ema200_pct or 0) >= 6:
        top_votes += 1
    if (inp.return_24h_pct or 0) >= 5:
        top_votes += 1
    return top_votes >= 2


_R4_SUB_TEMPLATES: Dict[str, RegimeBehaviorTemplate] = {
    "R4_STD_LIQUID": _R4_STD_LIQUID,
    "R4_DEF_OVERHEATED": _R4_DEF_OVERHEATED,
    "R4_DEF_LOW_LIQUIDITY": _R4_DEF_LOW_LIQUIDITY,
    "R4_ACT_LOWER_BAND_BOUNCE": _R4_ACT_LOWER_BAND_BOUNCE,
    "R4_RESTRICTED_UNSTABLE": _R4_RESTRICTED_UNSTABLE,
    "R4_FRAGILE_BUT_LIQUID": _R4_FRAGILE_BUT_LIQUID,
}

_R8_SUB_TEMPLATES: Dict[str, RegimeBehaviorTemplate] = {
    "R8_DEF_PANIC": _R8_DEF_PANIC,
    "R8_RECOVERY_RESTRICTED": _R8_RECOVERY_RESTRICTED,
}


def resolve_regime_template(
    regime_id: str,
    severity: SeverityMode,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    *,
    sub_profile_hint: str = "",
) -> Tuple[RegimeBehaviorTemplate, List[str], bool]:
    """Pick regime template + reason codes. Returns (template, reasons, deployable_hint)."""
    rid = str(regime_id or "R2").upper()
    templates = REGIME_BEHAVIOR_TEMPLATES.get(rid) or REGIME_BEHAVIOR_TEMPLATES["R2"]
    tpl = templates.get(severity) or templates["STD"]
    reasons: List[str] = ["REGIME_BEHAVIOR_SPEC_V2"]
    deployable = True

    if rid == "R4":
        hint = sub_profile_hint or _infer_r4_sub_profile(inp, trace)
        tpl = _R4_SUB_TEMPLATES.get(hint, _R4_STD_LIQUID)
        reasons.append(hint)
        spread = float(inp.spread_pct or 0)
        vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
        if spread >= 0.10:
            reasons.append("HIGH_SPREAD")
        if vq < 0.40:
            reasons.append("LOW_VOLUME")
        if float(inp.range_stability or 0) < 0.25:
            reasons.append("UNSTABLE_RANGE")
        if hint in ("R4_RESTRICTED_UNSTABLE", "R4_DEF_LOW_LIQUIDITY"):
            reasons.append("RESTRICTED_BUYS")
            deployable = False
    elif rid == "R8":
        hint = sub_profile_hint or _infer_r8_sub_profile(inp)
        tpl = _R8_SUB_TEMPLATES.get(hint, _R8_DEF_PANIC)
        reasons.append(hint)
        if hint == "R8_RECOVERY_RESTRICTED":
            reasons.append("CRASH_RECOVERY")
            deployable = False
    elif rid == "R1" and (
        sub_profile_hint == "R1_STD_TREND_COOLDOWN" or _is_r1_trend_cooldown_setup(inp)
    ):
        tpl = _R1_STD_TREND_COOLDOWN
        reasons.append("R1_STD_TREND_COOLDOWN")
    elif rid == "R1" and (sub_profile_hint == "R1_STD_PULLBACK" or _is_r1_pullback_setup(inp)):
        tpl = _R1_STD_PULLBACK
        reasons.append("R1_STD_PULLBACK")
    elif rid == "R5" and sub_profile_hint in ("R5_DEF_PARABOLIC_OVEREXTENDED", "R5_DEF_OVEREXTENDED"):
        if sub_profile_hint == "R5_DEF_PARABOLIC_OVEREXTENDED":
            tpl = _R5_DEF_PARABOLIC_OVEREXTENDED
            deployable = False
            reasons.extend(
                [
                    "R5_DEF_PARABOLIC_OVEREXTENDED",
                    "PARABOLIC_PUMP",
                    "HIGH_REVERSAL_RISK",
                    "MICRO_BASE_ONLY",
                    "NEW_BUYS_PAUSED",
                ]
            )
        else:
            tpl = _R5_DEF_OVEREXTENDED
            reasons.extend(["R5_DEF_OVEREXTENDED", "HIGH_REVERSAL_RISK", "NEW_BUYS_RESTRICTED"])
        if (inp.rsi_1h or 0) >= 68:
            reasons.append("RSI_OVERBOUGHT")
        if (inp.atr_1h_pct or 0) >= 3:
            reasons.append("EXTREME_ATR")
        if (inp.price_vs_ema200_pct or 0) >= 3:
            reasons.append("EMA200_DISTANCE_HIGH")

    return tpl, reasons, deployable


def _trace_class(trace: List[Dict[str, Any]], name: str) -> str:
    for entry in trace or []:
        if str(entry.get("name") or "") == name:
            return str(entry.get("class") or "")
    return ""


def _downgrade_severity(sev: SeverityMode) -> SeverityMode:
    if sev == "ACT":
        return "STD"
    if sev == "STD":
        return "DEF"
    return "DEF"


def resolve_effective_severity(
    severity: SeverityMode,
    regime_id: str,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
) -> SeverityMode:
    """Şartname: BTC/fragility/spread/likidite ACT ve STD düşürme kuralları."""
    sev = severity
    btc = _trace_class(trace, "btc_context")
    frag = _trace_class(trace, "asset_fragility") or str(inp.asset_fragility_class or "F1")
    vol = _trace_class(trace, "volatility")
    liq = _trace_class(trace, "liquidity")
    spread = float(inp.spread_pct or 0)

    if sev == "ACT":
        if regime_id == "R1" and (_is_r1_pullback_setup(inp) or _is_r1_trend_cooldown_setup(inp)):
            sev = "STD"
        if regime_id == "R5" and _is_overextended_top_setup(inp):
            sev = "STD"
        if btc in ("B2", "B3"):
            sev = "STD"
        if frag == "F3" and regime_id not in ("R1", "R5"):
            sev = "DEF"
        elif frag == "F3" and regime_id in ("R1", "R5"):
            sev = "STD"
        if spread > 0.15:
            sev = _downgrade_severity(sev)
        if liq in ("L2", "L3"):
            sev = "DEF"
        if vol in ("V4", "V5"):
            sev = _downgrade_severity(sev)

    if sev == "STD":
        if btc == "B3":
            sev = "DEF"
        if frag == "F3":
            sev = "DEF"
        if vol in ("V4", "V5"):
            sev = "DEF"

    return sev


def _apply_fragility_to_template(
    tpl: RegimeBehaviorTemplate,
    frag: str,
    *,
    inp: Optional[V6InputContract] = None,
    regime_id: str = "",
) -> RegimeBehaviorTemplate:
    rid = str(regime_id or "").upper()
    liquid = _liquid_coin(inp) if inp is not None else False
    if tpl.initial_base_pct <= 5 and tpl.new_buys_paused and not tpl.buy_grid_enabled:
        return tpl
    if frag == "F0":
        base = min(95, tpl.initial_base_pct + 5)
        quote = 100 - base
        return RegimeBehaviorTemplate(**{**tpl.__dict__, "initial_base_pct": base, "initial_quote_pct": quote})
    if frag == "F1":
        return tpl
    if frag == "F2":
        penalty = 5 if liquid else 10
        base = max(5, tpl.initial_base_pct - penalty)
        if rid in ("R1", "R5"):
            base = max(45, base)
        quote = 100 - base
        buy_d = tuple(min(25, d + (1 if liquid else 2)) for d in tpl.buy_distances_pct)
        sell_d = tuple(max(1, d - 1) for d in tpl.sell_distances_pct)
        return RegimeBehaviorTemplate(
            **{
                **tpl.__dict__,
                "initial_base_pct": base,
                "initial_quote_pct": quote,
                "buy_distances_pct": buy_d,
                "sell_distances_pct": sell_d,
            }
        )
    if frag == "F3":
        penalty = 10 if liquid else 15
        base = max(5, tpl.initial_base_pct - penalty)
        if rid in ("R1", "R5"):
            base = max(40, base)
        elif rid == "R4" and liquid:
            base = max(30, base)
        quote = 100 - base
        paused = tpl.new_buys_paused or tpl.new_buys_status == "paused"
        return RegimeBehaviorTemplate(
            **{
                **tpl.__dict__,
                "initial_base_pct": base,
                "initial_quote_pct": quote,
                "max_total_exposure_pct": min(tpl.max_total_exposure_pct, base + 15),
                "new_buys_status": "restricted" if not paused else tpl.new_buys_status,
                "new_buys_paused": paused,
                "buyback_restricted": True,
            }
        )
    return tpl


def _cap_trailing_to_lattice(pct: float) -> float:
    best = min(_VALID_TRAILING, key=lambda v: abs(v - pct))
    return best


def _cap_trailing_safety(trailing: float, first_distance: float, *, is_buyback: bool = False) -> float:
    cap = first_distance * 0.45
    t = _cap_trailing_to_lattice(trailing)
    if t > cap:
        candidates = [v for v in _VALID_TRAILING if v <= cap]
        t = max(candidates) if candidates else _VALID_TRAILING[0]
    return t


def _effective_profit_floor(inp: V6InputContract) -> float:
    spread = float(inp.spread_pct or 0)
    slippage = 0.1
    return max(DEFAULT_COST_FLOOR_PCT, spread, slippage)


def _apply_profit_floor(trigger: float, floor: float) -> float:
    t = quantize_profit_trigger_pct(trigger, floor_pct=1.0)
    if t < floor:
        step = 0.5
        t = round((int(floor / step) + (1 if floor % step else 0)) * step, 1)
    return max(t, floor)


def _build_grids(tpl: RegimeBehaviorTemplate) -> Tuple[List[GridLevel], List[GridLevel]]:
    buy: List[GridLevel] = []
    if tpl.buy_grid_enabled and not tpl.new_buys_paused and tpl.buy_grid_count > 0:
        for d, a in zip(tpl.buy_distances_pct, tpl.buy_amounts_pct):
            buy.append(GridLevel(-abs(int(d)), int(a)))
    sell: List[GridLevel] = []
    if tpl.sell_grid_enabled and tpl.sell_grid_count > 0:
        for d, a in zip(tpl.sell_distances_pct, tpl.sell_amounts_pct):
            sell.append(GridLevel(abs(int(d)), int(a)))
    return buy, sell


def _validate_layers(
    regime_id: str,
    tpl: RegimeBehaviorTemplate,
    buy: List[GridLevel],
    sell: List[GridLevel],
    inp: V6InputContract,
) -> Tuple[str, List[str]]:
    """5 katman iç onay — fail olursa REBUILD_DEFENSIVE."""
    errors: List[str] = []
    rid = regime_id.upper()
    base = tpl.initial_base_pct
    quote = tpl.initial_quote_pct

    if base + quote != 100:
        errors.append("L3:base_quote_sum")
    if tpl.max_total_exposure_pct < base:
        errors.append("L3:exposure_below_base")

    if rid == "R1" and base < 45:
        errors.append("L1:R1_base_min")
    if rid == "R1" and tpl.sell_grid_count < 3:
        errors.append("L1:R1_sell_count")
    if rid == "R2" and (tpl.buy_grid_count < 3 or tpl.sell_grid_count < 3):
        errors.append("L1:R2_grid_count")
    if rid == "R3" and buy and abs(buy[0].distance_pct) > 2:
        errors.append("L1:R3_buy_too_far")
    if rid == "R8" and base > 30:
        errors.append("L1:R8_base_cap")
    if rid == "R8" and not sell:
        errors.append("L1:R8_sell_required")

    if tpl.trailing_sell_pct > (sell[0].distance_pct if sell else 99) * 0.45:
        errors.append("L5:trailing_sell_cap")
    if tpl.trailing_buyback_pct > tpl.profit_buyback_trigger_pct * 0.45:
        errors.append("L5:trailing_buyback_cap")

    floor = _effective_profit_floor(inp)
    if tpl.profit_sell_trigger_pct < floor and rid not in ("R2", "R3"):
        errors.append("L5:profit_sell_floor")

    if errors:
        return "REBUILD_DEFENSIVE", errors
    return "PASS", []


def _template_to_profile(
    profile: V6CatalogProfile,
    tpl: RegimeBehaviorTemplate,
    inp: V6InputContract,
) -> V6CatalogProfile:
    p = profile.copy()
    floor = _effective_profit_floor(inp)
    ps_trig = _apply_profit_floor(tpl.profit_sell_trigger_pct, floor)
    pb_trig = _apply_profit_floor(tpl.profit_buyback_trigger_pct, floor)

    first_sell = tpl.sell_distances_pct[0] if tpl.sell_distances_pct else 10
    trail_sell = _cap_trailing_safety(tpl.trailing_sell_pct, float(first_sell))
    trail_buy = _cap_trailing_safety(tpl.trailing_buyback_pct, pb_trig, is_buyback=True)

    buy, sell = _build_grids(tpl)
    p.base_allocation_pct = int(tpl.initial_base_pct)
    p.quote_allocation_pct = int(tpl.initial_quote_pct)
    p.normal_buy_enabled = bool(buy) and tpl.buy_grid_enabled and not tpl.new_buys_paused
    p.buy_grids = buy
    p.sell_grids = sell

    p.buyback_after_sell_enabled = tpl.profit_buyback_enabled and bool(sell)
    p.profit_sell_after_buyback_enabled = tpl.profit_sell_enabled and p.buyback_after_sell_enabled
    p.buyback_trigger_code = profit_code_from_pct(pb_trig)
    p.buyback_trailing_code = trailing_code_from_pct(trail_buy)
    p.profit_sell_trigger_code = profit_code_from_pct(ps_trig)
    p.profit_sell_trailing_code = trailing_code_from_pct(trail_sell)
    p.sell_trailing_code = trailing_code_from_pct(trail_sell)
    p.buy_trailing_code = trailing_code_from_pct(trail_buy)

    modules = dict(p.modules or {})
    modules.update(
        {
            "normal_buy_grid": p.normal_buy_enabled,
            "sell_grid": bool(sell),
            "profit_buyback_after_sell": p.buyback_after_sell_enabled,
            "profit_sell_after_buyback": p.profit_sell_after_buyback_enabled,
            "regime_behavior_spec": True,
            "max_total_exposure_pct": tpl.max_total_exposure_pct,
            "active_buy_ladder_pct": tpl.active_buy_ladder_pct,
            "reserved_quote_pct": tpl.reserved_quote_pct,
            "new_buys_status": tpl.new_buys_status,
            "controlled_grid": True,
            "params_valid": True,
        }
    )
    if tpl.buyback_restricted:
        modules["profit_buyback_restricted"] = True
    if tpl.max_buyback_of_sold_pct is not None:
        modules["max_buyback_of_sold_pct"] = tpl.max_buyback_of_sold_pct
    if tpl.max_single_profit_sell_pct is not None:
        modules["max_single_profit_sell_pct"] = tpl.max_single_profit_sell_pct
    if tpl.trend_tail_base_reserve_pct is not None:
        modules["trend_tail_base_reserve_pct"] = tpl.trend_tail_base_reserve_pct
    p.modules = modules
    return quantize_profile(p)


def _output_meta(
    regime_id: str,
    severity: SeverityMode,
    tpl: RegimeBehaviorTemplate,
    *,
    layer_results: Dict[str, str],
    deployable_hint: bool,
    reason_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "regime_id": regime_id,
        "severity": severity,
        "initial_base_pct": tpl.initial_base_pct,
        "initial_quote_pct": tpl.initial_quote_pct,
        "max_total_exposure_pct": tpl.max_total_exposure_pct,
        "active_buy_ladder_pct": tpl.active_buy_ladder_pct,
        "reserved_quote_pct": tpl.reserved_quote_pct,
        "buy_grid_enabled": tpl.buy_grid_enabled and not tpl.new_buys_paused,
        "buy_grid_count": tpl.buy_grid_count if tpl.buy_grid_enabled else 0,
        "buy_distances_pct": list(tpl.buy_distances_pct),
        "buy_amounts_pct": list(tpl.buy_amounts_pct),
        "sell_grid_enabled": tpl.sell_grid_enabled,
        "sell_grid_count": tpl.sell_grid_count,
        "sell_distances_pct": list(tpl.sell_distances_pct),
        "sell_amounts_pct": list(tpl.sell_amounts_pct),
        "profit_sell_enabled": tpl.profit_sell_enabled,
        "profit_sell_trigger_pct": tpl.profit_sell_trigger_pct,
        "profit_sell_mode": tpl.profit_sell_mode,
        "trailing_sell_pct": tpl.trailing_sell_pct,
        "profit_buyback_enabled": tpl.profit_buyback_enabled,
        "profit_buyback_trigger_pct": tpl.profit_buyback_trigger_pct,
        "profit_buyback_mode": tpl.profit_buyback_mode,
        "trailing_buyback_pct": tpl.trailing_buyback_pct,
        "new_buys_status": tpl.new_buys_status,
        "controlled_grid": True,
        "deployable": deployable_hint,
        "params_valid": True,
        "layer_results": layer_results,
        "reason_codes": list(reason_codes or ["REGIME_BEHAVIOR_SPEC_V2"]),
    }


def apply_regime_behavior_spec(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    *,
    regime_id: str,
    severity: SeverityMode,
    sub_profile_hint: str = "",
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """Şartname profilini uygula — params=None yasak; fail → savunmacı yeniden inşa."""
    rid = str(regime_id or profile.scenario.regime_id or "R2").upper()
    eff_sev = resolve_effective_severity(severity, rid, inp, trace)
    frag = _trace_class(trace, "asset_fragility") or str(inp.asset_fragility_class or "F1")

    layer_results: Dict[str, str] = {}
    notes: Dict[str, Any] = {"regime_behavior_spec": True, "effective_severity": eff_sev}
    attempt_sev: SeverityMode = eff_sev
    p = profile
    reason_codes: List[str] = []
    deploy_hint = True

    for _ in range(3):
        tpl_raw, reason_codes, deploy_hint = resolve_regime_template(
            rid, attempt_sev, inp, trace, sub_profile_hint=sub_profile_hint
        )
        tpl = _apply_fragility_to_template(tpl_raw, frag, inp=inp, regime_id=rid)
        buy, sell = _build_grids(tpl)
        layer_status, layer_errors = _validate_layers(rid, tpl, buy, sell, inp)
        layer_results = {name: layer_status for name in _LAYER_ORDER}
        if layer_errors:
            layer_results["errors"] = layer_errors  # type: ignore[assignment]
        if layer_status == "PASS":
            p = _template_to_profile(profile, tpl, inp)
            p.scenario.severity = attempt_sev
            notes.update(
                _output_meta(
                    rid, attempt_sev, tpl,
                    layer_results=layer_results,
                    deployable_hint=deploy_hint,
                    reason_codes=reason_codes,
                )
            )
            notes["regime_opportunity"] = f"{rid}_SPEC_{attempt_sev}"
            notes["sub_profile_hint"] = sub_profile_hint or (reason_codes[1] if len(reason_codes) > 1 else "")
            return p, notes
        attempt_sev = _downgrade_severity(attempt_sev)

    tpl_raw, reason_codes, deploy_hint = resolve_regime_template(
        rid, "DEF", inp, trace, sub_profile_hint=sub_profile_hint
    )
    tpl = _apply_fragility_to_template(tpl_raw, frag, inp=inp, regime_id=rid)
    p = _template_to_profile(profile, tpl, inp)
    p.scenario.severity = "DEF"
    layer_results = {name: "REBUILD_DEFENSIVE" for name in _LAYER_ORDER}
    notes.update(
        _output_meta(
            rid, "DEF", tpl,
            layer_results=layer_results,
            deployable_hint=False,
            reason_codes=reason_codes,
        )
    )
    notes["regime_opportunity"] = f"{rid}_SPEC_DEF_FALLBACK"
    notes["controlled_grid"] = True
    return p, notes
