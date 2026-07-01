"""Scenario alignment — canonical regime, runtime fit, shelf vs applied trace."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.models import (
    BotParams,
    FinalAction,
    IndicatorSnapshot,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.regime_display import (
    V6_REGIME_LABELS,
    build_display_regime_label_v5,
    regime_code_from_route_key,
)

REGIME_LABELS = V6_REGIME_LABELS

# V5 R-code → canonical RegimeTag (single user-facing regime source when route present)
R_CODE_TO_REGIME: Dict[str, RegimeTag] = {
    "R1": RegimeTag.TRENDING_UP,
    "R2": RegimeTag.BALANCED_RANGE,
    "R3": RegimeTag.RANGE_LOW_VOL,
    "R4": RegimeTag.RANGE_HIGH_VOL,
    "R5": RegimeTag.BREAKOUT_RISK,
    "R6": RegimeTag.TRENDING_UP,
    "R7": RegimeTag.TRENDING_UP,
    "R8": RegimeTag.DUMP_RISK,
    "R9": RegimeTag.TRENDING_DOWN,
    "R10": RegimeTag.TRENDING_DOWN,
    "R11": RegimeTag.BREAKOUT_RISK,
    "R12": RegimeTag.TRENDING_DOWN,
    "R13": RegimeTag.HIGH_VOL_UNSTABLE,
    "R14": RegimeTag.LOW_LIQUIDITY,
    "R15": RegimeTag.HIGH_VOL_UNSTABLE,
    "R16": RegimeTag.RANGE_HIGH_VOL,
    "R17": RegimeTag.NO_DATA,
}

BEAR_R_CODES = frozenset({"R8", "R9", "R10", "R12"})
LOW_VOL_R_CODES = frozenset({"R3", "R5"})

ALIGN_DEPLOY_MIN = 70
ALIGN_FULL_MIN = 85


def _compact_code(part: str) -> str:
    p = (part or "").upper().strip()
    if not p:
        return ""
    if p[0] in "RSDVAKL" and len(p) >= 2:
        return p[:2] if len(p) == 2 or (len(p) > 2 and p[2].isdigit()) else p[:3]
    return p[:3]


def structure_code_from_route_key(route_key: str) -> str:
    if not route_key or "|" not in route_key:
        return ""
    parts = route_key.split("|")
    if len(parts) < 4:
        return ""
    return _compact_code(parts[3])


def direction_code_from_route_key(route_key: str) -> str:
    if not route_key or "|" not in route_key:
        return ""
    parts = route_key.split("|")
    if len(parts) < 3:
        return ""
    return _compact_code(parts[2])


def regime_tag_from_v5_route(
    route_key: str,
    legacy: RegimeTag,
    sub: SubScores,
    ind: Optional[IndicatorSnapshot] = None,
) -> RegimeTag:
    """Canonical regime for decisions/UI — V5 route wins over legacy classifier."""
    code = regime_code_from_route_key(route_key)
    if not code:
        return legacy
    mapped = R_CODE_TO_REGIME.get(code)
    if mapped is None:
        return legacy
    # Hard safety overrides still apply
    if legacy in (RegimeTag.SPREAD_UNSAFE, RegimeTag.LOW_LIQUIDITY, RegimeTag.NO_TRADE, RegimeTag.NO_DATA):
        return legacy
    if legacy == RegimeTag.DUMP_RISK and code not in BEAR_R_CODES:
        return RegimeTag.DUMP_RISK
    if sub.data_quality_score < 40 or code == "R17":
        return RegimeTag.NO_DATA
    return mapped


def display_regime_for_route(route_key: str, *, fallback_used: bool = False) -> str:
    return build_display_regime_label_v5(route_key, fallback_used=fallback_used)


def score_shelf_scenario_fit(shelf) -> Tuple[float, Dict[str, float], List[str]]:
    """Legacy shelf fit — V5 removed; neutral default for V4 tooling."""
    _ = shelf
    return 90.0, {}, []


def compute_structure_fit(
    route_key: str,
    params: Optional[BotParams],
) -> float:
    """0–1 fit between route structure (S*) and grid shape."""
    if params is None or not route_key:
        return 0.0
    sc = structure_code_from_route_key(route_key)
    buy_n = int(params.buy_grid_count or 0)
    sell_n = int(params.sell_grid_count or 0)
    buy_sp = float(params.buy_grid_spacing_pct or 0)
    sell_sp = float(params.sell_grid_spacing_pct or 0)
    if buy_n == 0 and sell_n == 0:
        return 0.5
    score = 1.0
    if sc == "S5" and buy_n > 0 and sell_n > 0 and buy_sp < sell_sp * 0.95:
        score -= 0.25  # lower lows: buys should be wider/deeper
    if sc == "S4" and buy_n > 0 and sell_n > 0 and sell_sp > buy_sp * 1.15:
        score -= 0.2  # higher highs: sells closer
    if sc == "S8" and buy_n > 2:
        score -= 0.15
    if sc == "S9" and buy_n >= 3 and sell_n >= 3:
        score -= 0.1  # chop: prefer fewer levels
    return max(0.0, min(1.0, score))


def compute_grid_direction_fit(
    route_key: str,
    params: Optional[BotParams],
) -> float:
    """0–1 fit between route direction (D*) and alloc/grid bias."""
    if params is None or not route_key:
        return 0.0
    dc = direction_code_from_route_key(route_key)
    base = float(params.base_alloc_frac or 0)
    quote = float(params.quote_alloc_frac or 0)
    score = 1.0
    if dc == "D1" and base < 0.42:
        score -= 0.2
    if dc == "D3" and quote < 0.45 and int(params.buy_grid_count or 0) > 0:
        score -= 0.2
    if dc == "D3" and not params.downtrend_buy_throttle and int(params.buy_grid_count or 0) >= 3:
        score -= 0.15
    return max(0.0, min(1.0, score))


def score_applied_vs_shelf(
    shelf_params: Optional[BotParams],
    applied: Optional[BotParams],
    *,
    feasibility_meta: Optional[dict] = None,
) -> Tuple[float, List[str]]:
    """How much safety/feasibility changed the shelf-resolved params (100 = identical)."""
    if shelf_params is None or applied is None:
        return 100.0, []
    notes: List[str] = []
    penalty = 0.0

    def _delta(a: float, b: float, weight: float, note: str, rel: float = 0.0) -> None:
        nonlocal penalty
        if rel > 0 and a > 0 and abs(b - a) / a > rel:
            penalty += weight
            notes.append(note)
        elif rel <= 0 and abs(b - a) > 1e-6:
            if weight >= 10:
                penalty += weight
                notes.append(note)

    _delta(
        float(shelf_params.buy_grid_count or 0),
        float(applied.buy_grid_count or 0),
        12,
        "buy_grid_count_adjusted",
    )
    _delta(
        float(shelf_params.sell_grid_count or 0),
        float(applied.sell_grid_count or 0),
        12,
        "sell_grid_count_adjusted",
    )
    _delta(
        float(shelf_params.buy_grid_spacing_pct or 0),
        float(applied.buy_grid_spacing_pct or 0),
        8,
        "buy_spacing_fee_floor",
        rel=0.18,
    )
    _delta(
        float(shelf_params.base_alloc_frac or 0),
        float(applied.base_alloc_frac or 0),
        10,
        "base_alloc_clamped",
        rel=0.12,
    )
    fm = feasibility_meta or {}
    if fm.get("exposure_gate_adjusted"):
        penalty += 8
        notes.append("exposure_ladder_capped")
    if fm.get("distribution_repaired"):
        penalty += 5
        notes.append("distribution_repaired")
    if fm.get("runtime_spacing_adjusted"):
        penalty += 4
        notes.append("runtime_micro_adjust")

    return max(0.0, 100.0 - penalty), notes


def score_indicator_param_alignment(
    ind: Optional[IndicatorSnapshot],
    sub: SubScores,
    params: Optional[BotParams],
    route_key: str,
    final_action: str,
) -> Tuple[float, List[str]]:
    """Logical consistency: current indicators + route + final params."""
    if params is None:
        return 0.0, ["no_params"]
    notes: List[str] = []
    score = 100.0
    rc = regime_code_from_route_key(route_key)
    fa = str(final_action or "").upper()

    if rc in BEAR_R_CODES and fa in (
        FinalAction.ACTIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
    ):
        score -= 35
        notes.append("bear_route_aggressive_action")
    if rc == "R8" and int(params.buy_grid_count or 0) > 0 and not params.emergency_no_buy:
        score -= 20
        notes.append("crash_route_buy_open")
    if rc in LOW_VOL_R_CODES and ind and ind.atr14_pct_5m and params.buy_grid_spacing_pct:
        ratio = float(ind.atr14_pct_5m) / max(float(params.buy_grid_spacing_pct), 0.01)
        if ratio < 0.12:
            score -= 4
            notes.append("fee_floor_wider_than_atr_expected")
    if ind and ind.rsi14_5m is not None:
        dc = direction_code_from_route_key(route_key)
        rsi = float(ind.rsi14_5m)
        if dc == "D1" and rsi < 32:
            score -= 8
            notes.append("up_bias_low_rsi")
        if dc == "D3" and rsi > 68:
            score -= 8
            notes.append("down_bias_high_rsi")
    if sub.spread_score < 30 and fa not in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
    ):
        score -= 25
        notes.append("spread_unsafe_action")
    if sub.liquidity_score < 30:
        score -= 20
        notes.append("liquidity_blocked")

    return max(0.0, min(100.0, score)), notes


def _params_snapshot(p: Optional[BotParams]) -> Optional[Dict[str, Any]]:
    if p is None:
        return None
    return {
        "buy_grid_count": int(p.buy_grid_count or 0),
        "sell_grid_count": int(p.sell_grid_count or 0),
        "buy_grid_spacing_pct": round(float(p.buy_grid_spacing_pct or 0), 4),
        "sell_grid_spacing_pct": round(float(p.sell_grid_spacing_pct or 0), 4),
        "base_alloc_pct": round(float(p.base_alloc_frac or 0) * 100, 2),
        "quote_alloc_pct": round(float(p.quote_alloc_frac or 0) * 100, 2),
        "max_base_exposure_pct": round(float(p.max_base_exposure_frac or 0) * 100, 2),
    }


def build_scenario_alignment(
    *,
    route_key: str,
    regime_tag: str,
    legacy_regime_tag: str,
    final_action: str,
    params: Optional[BotParams],
    pre_safety_params: Optional[BotParams],
    ind: Optional[IndicatorSnapshot],
    sub: SubScores,
    feasibility_meta: Optional[dict],
    shelf_scenario_fit: Optional[float] = None,
    shelf_fit_axes: Optional[dict] = None,
    shelf_id: str = "",
    fallback_used: bool = False,
) -> Dict[str, Any]:
    structure_fit = compute_structure_fit(route_key, params)
    grid_direction_fit = compute_grid_direction_fit(route_key, params)
    applied_fit, applied_notes = score_applied_vs_shelf(
        pre_safety_params, params, feasibility_meta=feasibility_meta
    )
    indicator_fit, indicator_notes = score_indicator_param_alignment(
        ind, sub, params, route_key, final_action
    )

    shelf_fit = float(shelf_scenario_fit if shelf_scenario_fit is not None else 90.0)
    combined = (
        shelf_fit * 0.30
        + applied_fit * 0.25
        + indicator_fit * 0.30
        + structure_fit * 100 * 0.075
        + grid_direction_fit * 100 * 0.075
    )
    combined = round(max(0.0, min(100.0, combined)), 1)

    rc = regime_code_from_route_key(route_key)
    adjustments = list(dict.fromkeys(applied_notes + indicator_notes))

    return {
        "combined_score": combined,
        "shelf_scenario_fit": round(shelf_fit, 1),
        "shelf_fit_axes": shelf_fit_axes or {},
        "applied_fit": round(applied_fit, 1),
        "indicator_fit": round(indicator_fit, 1),
        "structure_fit": round(structure_fit, 4),
        "grid_direction_fit": round(grid_direction_fit, 4),
        "aligned": combined >= ALIGN_DEPLOY_MIN,
        "fully_aligned": combined >= ALIGN_FULL_MIN,
        "canonical_regime_tag": regime_tag,
        "legacy_regime_tag": legacy_regime_tag,
        "regime_code": rc,
        "regime_label": display_regime_for_route(route_key, fallback_used=fallback_used),
        "route_key": route_key,
        "shelf_id": shelf_id,
        "shelf_ideal": _params_snapshot(pre_safety_params),
        "applied": _params_snapshot(params),
        "adjustments": adjustments,
        "alignment_gate_min": ALIGN_DEPLOY_MIN,
    }


def lookup_v5_shelf(route_key: str):
    """V5 removed — no shelf lookup."""
    _ = route_key
    return None
