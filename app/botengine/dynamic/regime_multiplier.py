"""Regime-aware percentage multipliers for dynamic round starts.

The contract is intentionally strict:

* the bot's initial config is the immutable baseline;
* buy/sell grid row counts never change;
* every round is baseline x current multiplier (never previous x multiplier);
* upward and downward evidence are scored independently;
* allocation and per-side grid quantities are normalized back to 100%;
* safety can pause buying without deleting or rewriting the baseline ladder.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CONTRACT_VERSION = "regime_multiplier_v1"


@dataclass(frozen=True)
class RegimePolicy:
    label: str
    base_alloc: float = 1.0
    quote_alloc: float = 1.0
    buy_distance: float = 1.0
    sell_distance: float = 1.0
    buy_qty_tilt: float = 0.0
    sell_qty_tilt: float = 0.0
    buy_trailing: float = 1.0
    sell_trailing: float = 1.0
    profit_reentry_trigger: float = 1.0
    profit_reentry_trailing: float = 1.0
    profit_exit_trigger: float = 1.0
    profit_exit_trailing: float = 1.0
    max_exposure: float = 1.0


# Moderate production seed values. They intentionally preserve the user's ladder
# shape and let confidence blending damp uncertain classifications.
REGIME_POLICIES: Dict[str, RegimePolicy] = {
    "R1": RegimePolicy(
        "Güçlü yükseliş",
        base_alloc=1.18,
        quote_alloc=0.88,
        buy_distance=0.92,
        sell_distance=1.22,
        buy_qty_tilt=0.22,
        sell_qty_tilt=0.42,
        buy_trailing=0.94,
        sell_trailing=1.15,
        profit_reentry_trigger=0.94,
        profit_reentry_trailing=0.96,
        profit_exit_trigger=1.20,
        profit_exit_trailing=1.12,
        max_exposure=1.08,
    ),
    "R2": RegimePolicy(
        "Dengeli aralık",
        buy_qty_tilt=0.08,
        sell_qty_tilt=0.05,
    ),
    "R3": RegimePolicy(
        "Düşük volatilite / sıkışma",
        base_alloc=0.94,
        quote_alloc=1.05,
        buy_distance=0.84,
        sell_distance=0.82,
        buy_qty_tilt=0.38,
        sell_qty_tilt=-0.20,
        buy_trailing=0.84,
        sell_trailing=0.82,
        profit_reentry_trigger=0.88,
        profit_reentry_trailing=0.84,
        profit_exit_trigger=0.86,
        profit_exit_trailing=0.82,
        max_exposure=0.94,
    ),
    "R4": RegimePolicy(
        "Volatil aralık",
        base_alloc=0.90,
        quote_alloc=1.09,
        buy_distance=1.24,
        sell_distance=1.22,
        buy_qty_tilt=0.46,
        sell_qty_tilt=-0.05,
        buy_trailing=1.16,
        sell_trailing=1.14,
        profit_reentry_trigger=1.22,
        profit_reentry_trailing=1.16,
        profit_exit_trigger=1.18,
        profit_exit_trailing=1.14,
        max_exposure=0.90,
    ),
    "R5": RegimePolicy(
        "Yukarı kırılım / momentum",
        base_alloc=1.14,
        quote_alloc=0.91,
        buy_distance=0.98,
        sell_distance=1.34,
        buy_qty_tilt=0.28,
        sell_qty_tilt=0.52,
        buy_trailing=1.00,
        sell_trailing=1.24,
        profit_reentry_trigger=1.05,
        profit_reentry_trailing=1.00,
        profit_exit_trigger=1.32,
        profit_exit_trailing=1.20,
        max_exposure=1.04,
    ),
    "R6": RegimePolicy(
        "Toparlanma",
        base_alloc=1.08,
        quote_alloc=0.95,
        buy_distance=0.98,
        sell_distance=1.14,
        buy_qty_tilt=0.34,
        sell_qty_tilt=0.18,
        buy_trailing=0.98,
        sell_trailing=1.08,
        profit_reentry_trigger=1.02,
        profit_reentry_trailing=0.98,
        profit_exit_trigger=1.14,
        profit_exit_trailing=1.08,
        max_exposure=1.02,
    ),
    "R7": RegimePolicy(
        "Düşüş trendi",
        base_alloc=0.66,
        quote_alloc=1.24,
        buy_distance=1.46,
        sell_distance=0.82,
        buy_qty_tilt=0.68,
        sell_qty_tilt=-0.52,
        buy_trailing=1.20,
        sell_trailing=0.84,
        profit_reentry_trigger=1.44,
        profit_reentry_trailing=1.18,
        profit_exit_trigger=0.84,
        profit_exit_trailing=0.84,
        max_exposure=0.70,
    ),
    "R8": RegimePolicy(
        "Crash / sert düşüş",
        base_alloc=0.40,
        quote_alloc=1.38,
        buy_distance=1.82,
        sell_distance=0.70,
        buy_qty_tilt=0.92,
        sell_qty_tilt=-0.82,
        buy_trailing=1.34,
        sell_trailing=0.72,
        profit_reentry_trigger=1.76,
        profit_reentry_trailing=1.32,
        profit_exit_trigger=0.72,
        profit_exit_trailing=0.72,
        max_exposure=0.48,
    ),
}

NEUTRAL_POLICY = RegimePolicy("Belirsiz / nötr")

_LEGACY_REGIME_MAP = {
    "TRENDING_UP": "R1",
    "BALANCED_RANGE": "R2",
    "RANGE_LOW_VOL": "R3",
    "LOW_VOL_RANGE": "R3",
    "RANGE_HIGH_VOL": "R4",
    "BREAKOUT_RISK": "R5",
    "RECOVERY": "R6",
    "TRENDING_DOWN": "R7",
    "DUMP_RISK": "R8",
}


def _finite(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_pct(value: float) -> float:
    return round(float(value), 4)


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _canonical_regime(decision: Any) -> str:
    telemetry = getattr(decision, "telemetry", None) or {}
    v6_display = telemetry.get("v6_display") or {}
    scenario = v6_display.get("scenario_identity") or {}
    market_signature = telemetry.get("market_signature") or {}
    candidates = (
        scenario.get("regime_id"),
        market_signature.get("regime_code"),
        getattr(decision, "regime_tag", None),
    )
    for raw in candidates:
        key = str(raw or "").strip().upper()
        if key in REGIME_POLICIES:
            return key
        if key in _LEGACY_REGIME_MAP:
            return _LEGACY_REGIME_MAP[key]
    return "UNKNOWN"


def _sub_profile_hint(decision: Any) -> str:
    telemetry = getattr(decision, "telemetry", None) or {}
    v6_display = telemetry.get("v6_display") or {}
    v6_final = telemetry.get("v6_final") or {}
    scenario = v6_display.get("scenario_identity") or {}
    final_scenario = v6_final.get("scenario") or {}
    opportunity = v6_final.get("opportunity_notes") or {}
    values = (
        v6_display.get("sub_profile_hint"),
        scenario.get("sub_profile_hint"),
        v6_final.get("sub_profile_hint"),
        final_scenario.get("sub_profile_hint"),
        opportunity.get("sub_profile_hint"),
        opportunity.get("r6_mode"),
        getattr(decision, "selected_profile_name", None),
    )
    return " ".join(str(v or "").upper() for v in values)


def _policy_for_decision(decision: Any, regime: str) -> Tuple[RegimePolicy, List[str]]:
    policy = REGIME_POLICIES.get(regime, NEUTRAL_POLICY)
    guards: List[str] = []
    hint = _sub_profile_hint(decision)

    # A parabolic/overextended R5 is not treated like a clean breakout. The
    # regime remains R5, but capital and new-buy risk become defensive.
    if regime == "R5" and any(x in hint for x in ("OVEREXTENDED", "PARABOLIC")):
        policy = replace(
            policy,
            label="Aşırı uzamış yukarı momentum",
            base_alloc=0.58,
            quote_alloc=1.24,
            buy_distance=1.52,
            sell_distance=0.86,
            buy_qty_tilt=0.72,
            sell_qty_tilt=-0.58,
            buy_trailing=1.22,
            sell_trailing=0.88,
            profit_reentry_trigger=1.50,
            profit_reentry_trailing=1.20,
            profit_exit_trigger=0.90,
            profit_exit_trailing=0.88,
            max_exposure=0.64,
        )
        guards.append("R5_OVEREXTENDED_DEFENSIVE_OVERRIDE")
    elif regime == "R5" and "POST_BREAKOUT_COOLDOWN" in hint:
        policy = replace(
            policy,
            base_alloc=0.92,
            quote_alloc=1.06,
            buy_distance=1.18,
            sell_distance=0.92,
            buy_qty_tilt=0.48,
            sell_qty_tilt=-0.22,
            max_exposure=0.86,
        )
        guards.append("R5_COOLDOWN_DEFENSIVE_OVERRIDE")

    if regime == "R6" and "PROTECTIVE_SELL_ONLY" in hint:
        policy = replace(
            policy,
            base_alloc=0.78,
            quote_alloc=1.14,
            buy_distance=1.28,
            sell_distance=0.88,
            buy_qty_tilt=0.58,
            sell_qty_tilt=-0.36,
            max_exposure=0.78,
        )
        guards.append("R6_PROTECTIVE_OVERRIDE")
    return policy, guards


def _indicator_map(decision: Any) -> Dict[str, Any]:
    telemetry = getattr(decision, "telemetry", None) or {}
    indicators = telemetry.get("indicators") or {}
    return indicators if isinstance(indicators, dict) else {}


def _bipolar_component(
    components_up: List[Tuple[float, float]],
    components_down: List[Tuple[float, float]],
    value: Any,
    *,
    scale: float,
    weight: float,
) -> None:
    val = _finite(value)
    if val is None:
        return
    components_up.append((_clamp(max(val, 0.0) / scale, 0.0, 1.0), weight))
    components_down.append((_clamp(max(-val, 0.0) / scale, 0.0, 1.0), weight))


def _weighted_score(components: Sequence[Tuple[float, float]]) -> float:
    den = sum(weight for _, weight in components)
    if den <= 0:
        return 0.0
    return _clamp(sum(value * weight for value, weight in components) / den, 0.0, 1.0)


def direction_scores(decision: Any) -> Dict[str, float]:
    """Return independent 0..1 up/down evidence plus volatility intensity."""
    ind = _indicator_map(decision)
    up: List[Tuple[float, float]] = []
    down: List[Tuple[float, float]] = []

    for key, scale, weight in (
        ("return_1h_pct", 3.0, 0.16),
        ("return_4h_pct", 6.0, 0.20),
        ("return_24h_pct", 12.0, 0.18),
        ("ema20_slope_5m", 0.80, 0.09),
        ("ema50_slope_5m", 0.60, 0.09),
        ("price_vs_ema200_pct", 8.0, 0.10),
        ("roc_5m", 2.5, 0.06),
        ("btc_return_1h_pct", 3.0, 0.04),
        ("btc_return_4h_pct", 6.0, 0.04),
        ("btc_return_24h_pct", 12.0, 0.04),
    ):
        value = ind.get(key)
        if value is None and key.endswith("_pct"):
            value = ind.get(key[:-4])
        _bipolar_component(up, down, value, scale=scale, weight=weight)

    rsi_5m = _finite(ind.get("rsi14_5m"))
    if rsi_5m is not None:
        _bipolar_component(up, down, rsi_5m - 50.0, scale=25.0, weight=0.05)
    rsi_1h = _finite(ind.get("rsi14_1h"))
    if rsi_1h is not None:
        _bipolar_component(up, down, rsi_1h - 50.0, scale=25.0, weight=0.05)
    bb = _finite(ind.get("price_in_bb"))
    if bb is not None:
        _bipolar_component(up, down, bb - 0.5, scale=0.5, weight=0.04)

    if ind.get("higher_highs") is not None:
        up.append((1.0 if bool(ind.get("higher_highs")) else 0.0, 0.08))
    if ind.get("lower_lows") is not None:
        down.append((1.0 if bool(ind.get("lower_lows")) else 0.0, 0.08))
    if ind.get("btc_below_ema200") is not None:
        down.append((1.0 if bool(ind.get("btc_below_ema200")) else 0.0, 0.04))

    crash = _finite(ind.get("crash_velocity"))
    if crash is not None:
        down.append((_clamp(max(-crash, 0.0) / 3.0, 0.0, 1.0), 0.10))
    btc_crash = _finite(ind.get("btc_crash_velocity"))
    if btc_crash is not None:
        down.append((_clamp(max(-btc_crash, 0.0) / 3.0, 0.0, 1.0), 0.05))
    red_pressure = _finite(ind.get("consecutive_red_pressure"))
    if red_pressure is not None:
        down.append((_clamp(red_pressure, 0.0, 1.0), 0.06))

    volatility_percentile = _finite(ind.get("volatility_percentile"))
    if volatility_percentile is None:
        volatility = 0.5
    else:
        volatility = _clamp(volatility_percentile / 100.0, 0.0, 1.0)
    return {
        "up": round(_weighted_score(up), 4),
        "down": round(_weighted_score(down), 4),
        "volatility": round(volatility, 4),
    }


def _indicator_coverage(indicators: Mapping[str, Any]) -> float:
    keys = (
        "return_1h_pct",
        "return_4h_pct",
        "return_24h_pct",
        "ema20_slope_5m",
        "ema50_slope_5m",
        "price_vs_ema200_pct",
        "adx_1h",
        "volatility_percentile",
        "rsi14_5m",
        "rsi14_1h",
        "price_in_bb",
        "crash_velocity",
    )
    present = sum(1 for key in keys if _finite(indicators.get(key)) is not None)
    return present / float(len(keys))


def _effective_confidence(decision: Any, regime: str) -> Dict[str, float]:
    telemetry = getattr(decision, "telemetry", None) or {}
    sub_scores = telemetry.get("sub_scores") or {}
    decision_conf = _clamp((_finite(getattr(decision, "confidence_score", 0)) or 0.0) / 100.0, 0.0, 1.0)
    data_quality = _finite(sub_scores.get("data_quality_score"))
    if data_quality is None:
        data_quality = _finite(sub_scores.get("data_quality_risk_score"))
    if data_quality is None:
        data_quality = decision_conf * 100.0
    data_quality = _clamp(data_quality / 100.0, 0.0, 1.0)
    coverage = _indicator_coverage(_indicator_map(decision))
    raw = _clamp(decision_conf * 0.50 + data_quality * 0.30 + coverage * 0.20, 0.0, 1.0)
    risk_floor = {"R7": 0.68, "R8": 0.82}.get(regime, 0.0)
    effective = max(raw, risk_floor)
    return {
        "decision": round(decision_conf, 4),
        "data_quality": round(data_quality, 4),
        "indicator_coverage": round(coverage, 4),
        "raw": round(raw, 4),
        "effective": round(effective, 4),
        "risk_floor": risk_floor,
    }


def _blend(target: float, confidence: float) -> float:
    return 1.0 + confidence * (target - 1.0)


def _bounded_factor(target: float, confidence: float, low: float, high: float) -> float:
    return _clamp(_blend(target, confidence), low, high)


def _raw_factors(
    policy: RegimePolicy,
    scores: Mapping[str, float],
    confidence: float,
) -> Dict[str, float]:
    up = float(scores.get("up") or 0.0)
    down = float(scores.get("down") or 0.0)
    volatility = float(scores.get("volatility") or 0.5)
    directional_net = up - down
    volatility_scale = 0.84 + 0.48 * volatility

    targets = {
        "base_alloc": policy.base_alloc * (1.0 + 0.16 * directional_net),
        "quote_alloc": policy.quote_alloc * (1.0 - 0.12 * directional_net),
        "buy_distance": policy.buy_distance
        * volatility_scale
        * (1.0 + 0.14 * down - 0.07 * up),
        "sell_distance": policy.sell_distance
        * volatility_scale
        * (1.0 + 0.12 * up - 0.10 * down),
        "buy_trailing": policy.buy_trailing
        * math.sqrt(volatility_scale)
        * (1.0 + 0.08 * down - 0.03 * up),
        "sell_trailing": policy.sell_trailing
        * math.sqrt(volatility_scale)
        * (1.0 + 0.07 * up - 0.05 * down),
        "profit_reentry_trigger": policy.profit_reentry_trigger
        * volatility_scale
        * (1.0 + 0.10 * down - 0.04 * up),
        "profit_reentry_trailing": policy.profit_reentry_trailing
        * math.sqrt(volatility_scale),
        "profit_exit_trigger": policy.profit_exit_trigger
        * volatility_scale
        * (1.0 + 0.09 * up - 0.07 * down),
        "profit_exit_trailing": policy.profit_exit_trailing
        * math.sqrt(volatility_scale),
        "max_exposure": policy.max_exposure * (1.0 + 0.10 * directional_net),
    }
    bounds = {
        "base_alloc": (0.38, 1.55),
        "quote_alloc": (0.50, 1.55),
        "buy_distance": (0.65, 1.95),
        "sell_distance": (0.65, 1.80),
        "buy_trailing": (0.65, 1.55),
        "sell_trailing": (0.65, 1.55),
        "profit_reentry_trigger": (0.65, 1.90),
        "profit_reentry_trailing": (0.65, 1.55),
        "profit_exit_trigger": (0.65, 1.75),
        "profit_exit_trailing": (0.65, 1.55),
        "max_exposure": (0.42, 1.12),
    }
    factors = {
        key: round(_bounded_factor(target, confidence, *bounds[key]), 6)
        for key, target in targets.items()
    }
    factors["buy_qty_tilt"] = round(
        confidence * (policy.buy_qty_tilt + 0.34 * down - 0.12 * up), 6
    )
    factors["sell_qty_tilt"] = round(
        confidence * (policy.sell_qty_tilt + 0.30 * up - 0.32 * down), 6
    )
    factors["volatility_scale"] = round(volatility_scale, 6)
    return factors


def _normalize_pair(
    base_pct: float,
    quote_pct: float,
    base_factor: float,
    quote_factor: float,
) -> Tuple[float, float]:
    base_raw = max(0.0, base_pct) * base_factor
    quote_raw = max(0.0, quote_pct) * quote_factor
    total = base_raw + quote_raw
    if total <= 0:
        return 50.0, 50.0
    base = round(100.0 * base_raw / total, 4)
    return base, round(100.0 - base, 4)


def _normalise_weights(
    values: Sequence[float],
    *,
    floor_pct: float = 0.0,
) -> Tuple[List[float], bool]:
    count = len(values)
    if count == 0:
        return [], False
    positive = [max(0.0, float(value)) for value in values]
    if sum(positive) <= 0:
        positive = [1.0] * count
    total = sum(positive)
    normalized = [100.0 * value / total for value in positive]
    floor_applied = False

    if floor_pct > 0 and floor_pct * count <= 100.0:
        fixed: Dict[int, float] = {}
        free = set(range(count))
        while free:
            remaining = 100.0 - sum(fixed.values())
            free_weight = sum(positive[i] for i in free)
            proposal = {
                i: remaining * (positive[i] / free_weight if free_weight > 0 else 1.0 / len(free))
                for i in free
            }
            below = [i for i, value in proposal.items() if value < floor_pct]
            if not below:
                for i, value in proposal.items():
                    fixed[i] = value
                break
            floor_applied = True
            for i in below:
                fixed[i] = floor_pct
                free.remove(i)
        normalized = [fixed[i] for i in range(count)]

    rounded = [round(value, 4) for value in normalized]
    rounded[-1] = round(rounded[-1] + (100.0 - sum(rounded)), 4)
    return rounded, floor_applied


def _grid_value(grid: Mapping[str, Any], primary: str, fallback: str) -> float:
    value = _finite(grid.get(primary))
    if value is None:
        value = _finite(grid.get(fallback))
    return max(0.0, value or 0.0)


def _scale_grids(
    grids: Iterable[Mapping[str, Any]],
    *,
    distance_key: str,
    qty_key: str,
    distance_factor: float,
    qty_tilt: float,
    side_budget: float,
    min_notional: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    source = [copy.deepcopy(dict(grid)) for grid in grids]
    count = len(source)
    if not count:
        return [], {"count": 0, "qty_level_factors": [], "min_notional_floor_pct": 0.0}

    min_spacing = 0.10
    scaled_distances: List[float] = []
    monotonic_repair = False
    previous = 0.0
    for grid in source:
        initial = _grid_value(grid, distance_key, "trigger_pct")
        scaled = _clamp(initial * distance_factor, min_spacing, 300.0 if distance_key.startswith("sell") else 92.0)
        if scaled <= previous:
            scaled = min(300.0 if distance_key.startswith("sell") else 92.0, previous + min_spacing)
            monotonic_repair = True
        scaled_distances.append(round(scaled, 4))
        previous = scaled

    initial_qty = [_grid_value(grid, qty_key, "qty_pct") for grid in source]
    if sum(initial_qty) <= 0:
        initial_qty = [1.0] * count
    if count == 1:
        level_factors = [1.0]
    else:
        positions = [(-1.0 + (2.0 * i / (count - 1))) for i in range(count)]
        level_factors = [math.exp(qty_tilt * position) for position in positions]
    tilted = [qty * factor for qty, factor in zip(initial_qty, level_factors)]

    floor_pct = 0.0
    min_notional_feasible = False
    if side_budget > 0 and min_notional > 0:
        floor_pct = 100.0 * min_notional / side_budget
        min_notional_feasible = floor_pct * count <= 100.0
    quantities, floor_applied = _normalise_weights(
        tilted,
        floor_pct=floor_pct if min_notional_feasible else 0.0,
    )

    out: List[Dict[str, Any]] = []
    for grid, distance, qty in zip(source, scaled_distances, quantities):
        grid[distance_key] = distance
        grid[qty_key] = qty
        if "trigger_pct" in grid:
            grid["trigger_pct"] = distance
        if "qty_pct" in grid:
            grid["qty_pct"] = qty
        out.append(grid)

    return out, {
        "count": count,
        "qty_level_factors": [round(value, 6) for value in level_factors],
        "min_notional_floor_pct": round(floor_pct, 4) if floor_pct else 0.0,
        "min_notional_feasible": min_notional_feasible if floor_pct else True,
        "min_notional_floor_applied": floor_applied,
        "monotonic_repair": monotonic_repair,
    }


def _cost_floor_pct(reference: Mapping[str, Any], constraints: Any) -> float:
    maker = _finite(getattr(constraints, "maker_fee_pct", None)) or 0.0
    taker = _finite(getattr(constraints, "taker_fee_pct", None)) or maker
    slippage = _finite(getattr(constraints, "estimated_slippage_pct", None)) or 0.0
    min_net = max(0.0, _finite(reference.get("min_net_profit_rate")) or 0.0) * 100.0
    return max(0.10, maker + taker + 2.0 * slippage + min_net)


def _scaled_positive(reference: Mapping[str, Any], key: str, factor: float, default: float) -> float:
    initial = _finite(reference.get(key))
    if initial is None:
        initial = default
    return max(0.0, initial) * factor


def _safety_flags(reference: Mapping[str, Any], decision: Any) -> Dict[str, Any]:
    params = getattr(decision, "params", None)
    final_action = str(getattr(decision, "final_action", "") or "").upper()
    hard_no_buy = final_action in {"NO_TRADE", "WAIT", "SELL_MANAGEMENT_ONLY"}
    if params is not None:
        hard_no_buy = hard_no_buy or bool(
            _flag(getattr(params, "emergency_no_buy", False))
            or _flag(getattr(params, "buy_disabled", False))
            or _flag(getattr(params, "sell_only_mode", False))
        )
    buy_disabled = _flag(reference.get("buy_disabled")) or hard_no_buy
    return {
        "buy_disabled": buy_disabled,
        "sell_only_mode": _flag(reference.get("sell_only_mode"))
        or final_action == "SELL_MANAGEMENT_ONLY"
        or _flag(getattr(params, "sell_only_mode", False) if params is not None else False),
        "rebuy_enabled": (
            True if reference.get("rebuy_enabled") is None else _flag(reference.get("rebuy_enabled"))
        )
        and not buy_disabled,
        "resell_enabled": (
            True if reference.get("resell_enabled") is None else _flag(reference.get("resell_enabled"))
        ),
        "cancel_existing_buy_orders": _flag(reference.get("cancel_existing_buy_orders"))
        or _flag(getattr(params, "cancel_existing_buy_orders", False) if params is not None else False)
        or buy_disabled,
        "cancel_existing_sell_orders": _flag(reference.get("cancel_existing_sell_orders"))
        or _flag(getattr(params, "cancel_existing_sell_orders", False) if params is not None else False),
        "intent_execution_enabled": bool(
            getattr(decision, "deployable", False) and final_action not in {"NO_TRADE", "WAIT"}
        ),
        "final_action": final_action or None,
        "management_mode": getattr(params, "management_mode", None) if params is not None else None,
        "selected_template_key": (
            getattr(params, "selected_template_key", None)
            if params is not None
            else getattr(decision, "selected_profile_name", None)
        ),
        "pool_version": getattr(params, "pool_version", None) if params is not None else None,
    }


def build_regime_multiplier_overlay(
    reference: Mapping[str, Any],
    decision: Any,
    *,
    constraints: Any = None,
    portfolio: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build one round's overlay strictly from the immutable reference config."""
    baseline = copy.deepcopy(dict(reference or {}))
    regime = _canonical_regime(decision)
    policy, guards = _policy_for_decision(decision, regime)
    scores = direction_scores(decision)
    confidence = _effective_confidence(decision, regime)
    factors = _raw_factors(policy, scores, confidence["effective"])

    base_initial = _finite(baseline.get("base_alloc_pct"))
    quote_initial = _finite(baseline.get("quote_alloc_pct"))
    base_pct, quote_pct = _normalize_pair(
        50.0 if base_initial is None else base_initial,
        50.0 if quote_initial is None else quote_initial,
        factors["base_alloc"],
        factors["quote_alloc"],
    )

    equity = _finite(getattr(portfolio, "total_equity_usdt", None)) or 0.0
    if equity <= 0:
        equity = _finite(baseline.get("initial_capital_usdt")) or _finite(
            baseline.get("bot_budget_usdt")
        ) or 0.0
    min_notional = _finite(getattr(constraints, "min_notional", None)) or 0.0
    buy_grids, buy_meta = _scale_grids(
        baseline.get("buy_grids") or [],
        distance_key="buy_grid_pct",
        qty_key="buy_qty_pct_of_quote",
        distance_factor=factors["buy_distance"],
        qty_tilt=factors["buy_qty_tilt"],
        side_budget=equity * quote_pct / 100.0,
        min_notional=min_notional,
    )
    sell_grids, sell_meta = _scale_grids(
        baseline.get("sell_grids") or [],
        distance_key="sell_grid_pct",
        qty_key="sell_qty_pct_of_base",
        distance_factor=factors["sell_distance"],
        qty_tilt=factors["sell_qty_tilt"],
        side_budget=equity * base_pct / 100.0,
        min_notional=min_notional,
    )

    buy_first = _grid_value(buy_grids[0], "buy_grid_pct", "trigger_pct") if buy_grids else 100.0
    sell_first = _grid_value(sell_grids[0], "sell_grid_pct", "trigger_pct") if sell_grids else 100.0
    cost_floor = _cost_floor_pct(baseline, constraints)

    buy_trailing = _clamp(
        _scaled_positive(baseline, "buy_trigger_trailing_pct", factors["buy_trailing"], 0.3),
        0.10,
        max(0.10, buy_first * 0.45),
    )
    sell_trailing = _clamp(
        _scaled_positive(baseline, "sell_trigger_trailing_pct", factors["sell_trailing"], 0.3),
        0.10,
        max(0.10, sell_first * 0.45),
    )
    reentry_trigger = max(
        cost_floor,
        _scaled_positive(
            baseline,
            "profit_reentry_drop_pct",
            factors["profit_reentry_trigger"],
            1.0,
        ),
    )
    reentry_trailing = _clamp(
        _scaled_positive(
            baseline,
            "profit_reentry_rise_pct",
            factors["profit_reentry_trailing"],
            0.3,
        ),
        0.10,
        max(0.10, reentry_trigger * 0.45),
    )
    exit_trigger = max(
        cost_floor,
        _scaled_positive(
            baseline,
            "profit_exit_rise_pct",
            factors["profit_exit_trigger"],
            1.0,
        ),
    )
    exit_trailing = _clamp(
        _scaled_positive(
            baseline,
            "profit_exit_drop_pct",
            factors["profit_exit_trailing"],
            0.3,
        ),
        0.10,
        max(0.10, exit_trigger * 0.45),
    )

    initial_exposure = _finite(baseline.get("max_base_exposure_frac"))
    if initial_exposure is None or initial_exposure <= 0:
        initial_exposure = 1.0
    max_exposure = _clamp(initial_exposure * factors["max_exposure"], 0.05, 0.98)
    target_base_frac = base_pct / 100.0
    if max_exposure < target_base_frac:
        max_exposure = min(0.98, target_base_frac + 0.03)
        guards.append("MAX_EXPOSURE_RAISED_TO_TARGET_ALLOCATION")

    if buy_meta.get("min_notional_floor_pct") and not buy_meta.get("min_notional_feasible"):
        guards.append("BUY_MIN_NOTIONAL_INFEASIBLE_GRID_COUNT_PRESERVED")
    if sell_meta.get("min_notional_floor_pct") and not sell_meta.get("min_notional_feasible"):
        guards.append("SELL_MIN_NOTIONAL_INFEASIBLE_GRID_COUNT_PRESERVED")
    if buy_meta.get("monotonic_repair"):
        guards.append("BUY_GRID_MONOTONIC_REPAIR")
    if sell_meta.get("monotonic_repair"):
        guards.append("SELL_GRID_MONOTONIC_REPAIR")

    overlay: Dict[str, Any] = {
        "base_alloc_pct": _round_pct(base_pct),
        "quote_alloc_pct": _round_pct(quote_pct),
        "buy_grids": buy_grids,
        "sell_grids": sell_grids,
        "buy_trigger_trailing_pct": _round_pct(buy_trailing),
        "sell_trigger_trailing_pct": _round_pct(sell_trailing),
        "profit_reentry_drop_pct": _round_pct(reentry_trigger),
        "profit_reentry_rise_pct": _round_pct(reentry_trailing),
        "profit_exit_rise_pct": _round_pct(exit_trigger),
        "profit_exit_drop_pct": _round_pct(exit_trailing),
        "max_base_exposure_frac": round(max_exposure, 6),
        # This is part of the grid-count invariant, not a dynamic recommendation.
        "max_buy_levels": int(
            baseline.get("max_buy_levels")
            if baseline.get("max_buy_levels") is not None
            else len(buy_grids)
        ),
        "min_net_profit_rate": max(
            0.0, _finite(baseline.get("min_net_profit_rate")) or 0.0
        ),
        **_safety_flags(baseline, decision),
    }

    telemetry = {
        "contract_version": CONTRACT_VERSION,
        "source": "immutable_initial_reference_x_regime_multiplier",
        "regime": regime,
        "regime_label": policy.label,
        "confidence": confidence,
        "direction_scores": scores,
        "regime_policy": asdict(policy),
        "multipliers": factors,
        "grids": {"buy": buy_meta, "sell": sell_meta},
        "grid_count_invariant": {
            "buy_initial": len(baseline.get("buy_grids") or []),
            "buy_applied": len(buy_grids),
            "sell_initial": len(baseline.get("sell_grids") or []),
            "sell_applied": len(sell_grids),
            "preserved": (
                len(baseline.get("buy_grids") or []) == len(buy_grids)
                and len(baseline.get("sell_grids") or []) == len(sell_grids)
            ),
        },
        "normalization": {
            "base_quote_total": round(base_pct + quote_pct, 4),
            "buy_qty_total": round(
                sum(_grid_value(grid, "buy_qty_pct_of_quote", "qty_pct") for grid in buy_grids),
                4,
            ),
            "sell_qty_total": round(
                sum(_grid_value(grid, "sell_qty_pct_of_base", "qty_pct") for grid in sell_grids),
                4,
            ),
        },
        "cost_floor_pct": round(cost_floor, 4),
        "guards": guards,
    }
    return overlay, telemetry
