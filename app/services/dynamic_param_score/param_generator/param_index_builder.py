"""Fast index builder — clean route_key (5-part) + market signature."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.param_generator.feature_bins import (
    budget_class_from_usdt,
    fee_class_from_score,
    structure_from_flags,
    volatility_bin_from_percentile,
)
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    ASSET_SHELVES,
    BUDGET_SHELVES,
    FEE_SHELVES,
    REGIME_SHELVES,
    STRUCTURE_SHELVES,
    VOL_SHELVES,
    asset_class_from_symbol_v4,
    budget_class_from_usdt_v4,
    clean_fallback_keys,
    clean_route_key,
    direction_bias_for_structure,
    fallback_keys,
    fee_code_from_score,
    grid_bias_for_context,
    normalize_route_key,
    regime_code_from_live_tag,
    route_key,
    structure_from_flags_v4,
    vol_code_from_atr_1h,
)


def index_key_for_signature(sig: Dict[str, Any]) -> str:
    """Primary index key — clean 5-part route."""
    return route_key_for_signature(sig)


def route_key_for_signature(sig: Dict[str, Any]) -> str:
    rk = sig.get("route_key") or sig.get("clean_route_key")
    if rk:
        return normalize_route_key(str(rk))
    return clean_route_key(
        str(sig.get("asset_code") or sig.get("asset_class") or "A3"),
        str(sig.get("regime_code") or sig.get("regime") or "R2"),
        str(sig.get("structure_code") or sig.get("structure") or "S1"),
        str(sig.get("vol_code") or sig.get("volatility_bin") or "V3"),
        str(sig.get("risk_class") or sig.get("risk_level") or "NORMAL"),
    )


def build_selection_index(profiles: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = defaultdict(list)
    for p in profiles:
        raw = p.get("route_key") or p.get("clean_route_key") or ""
        key = normalize_route_key(str(raw)) if raw else route_key_for_signature(p)
        pid = p.get("profile_id") or p.get("template_key") or ""
        if pid and key:
            index[key].append(pid)
    return dict(index)


def build_v4_indexes(profiles: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    indexes: Dict[str, Dict[str, List[str]]] = {
        "index_by_route_key": defaultdict(list),
        "index_by_asset_regime": defaultdict(list),
        "index_by_structure": defaultdict(list),
        "index_by_risk_class": defaultdict(list),
        "index_by_behavior_fingerprint": defaultdict(list),
    }
    for p in profiles:
        pid = p.get("profile_id") or p.get("template_key") or ""
        if not pid:
            continue
        rk = normalize_route_key(str(p.get("route_key") or "")) or route_key_for_signature(p)
        indexes["index_by_route_key"][rk].append(pid)
        ar = "|".join([str(p.get("asset_code") or ""), str(p.get("regime_code") or "")])
        indexes["index_by_asset_regime"][ar].append(pid)
        indexes["index_by_structure"][str(p.get("structure_code") or "")].append(pid)
        indexes["index_by_risk_class"][str(p.get("risk_class") or "NORMAL")].append(pid)
        fp = str(p.get("behavior_fingerprint") or "")
        if fp:
            indexes["index_by_behavior_fingerprint"][fp].append(pid)
    return {k: dict(v) for k, v in indexes.items()}


def _live_volatility_percentile(
    volatility_percentile: float,
    volatility_score: int | None,
) -> float:
    if volatility_percentile and volatility_percentile > 0:
        return float(volatility_percentile)
    return float(volatility_score if volatility_score is not None else 50)


def _reconcile_regime_vol_codes(
    r_code: str,
    v_code: str,
    *,
    volatility_percentile: float,
    wide_chop: bool,
) -> tuple[str, str]:
    vol_pct = float(volatility_percentile or 0)
    if r_code == "R3" and (v_code in ("V4", "V5") or vol_pct >= 70 or wide_chop):
        r_code = "R5" if wide_chop else "R4"
    if r_code in ("R3", "R2") and v_code == "V5" and vol_pct >= 80:
        r_code = "R5" if wide_chop else "R4"
    return r_code, v_code


def _effective_v4_risk_level(
    risk_level: str,
    *,
    btc_pressure: bool,
    overbought: bool,
    vol_pct: float,
    fee_efficiency_score: int,
) -> str:
    if risk_level == "BLOCKED":
        return risk_level
    if fee_efficiency_score < 30 and risk_level in ("NORMAL", "SAFE"):
        return "DEFENSIVE"
    if btc_pressure and (overbought or vol_pct >= 75):
        return "DEFENSIVE"
    if overbought and vol_pct >= 85 and risk_level == "NORMAL":
        return "DEFENSIVE"
    return risk_level or "NORMAL"


def market_signature_from_live(
    *,
    symbol: str,
    budget: float,
    regime: str,
    risk_level: str,
    volatility_percentile: float,
    lower_lows: bool,
    higher_highs: bool,
    fee_efficiency_score: int,
    asset_class: str | None = None,
    atr_1h_pct: float | None = None,
    spread_pct: float = 0.0,
    data_quality_score: int = 80,
    return_24h_pct: float | None = None,
    drawdown_7d_pct: float | None = None,
    drawdown_30d_pct: float | None = None,
    z_score_5m: float | None = None,
    price_in_bb: float | None = None,
    volatility_score: int | None = None,
    btc_crash_velocity: float | None = None,
    crash_velocity: float | None = None,
) -> Dict[str, Any]:
    if _is_v4_active():
        return market_signature_v4_from_live(
            symbol=symbol,
            budget=budget,
            regime=regime,
            risk_level=risk_level,
            volatility_percentile=volatility_percentile,
            lower_lows=lower_lows,
            higher_highs=higher_highs,
            fee_efficiency_score=fee_efficiency_score,
            atr_1h_pct=atr_1h_pct,
            spread_pct=spread_pct,
            data_quality_score=data_quality_score,
            return_24h_pct=return_24h_pct,
            drawdown_7d_pct=drawdown_7d_pct,
            drawdown_30d_pct=drawdown_30d_pct,
            z_score_5m=z_score_5m,
            price_in_bb=price_in_bb,
            volatility_score=volatility_score,
            btc_crash_velocity=btc_crash_velocity,
            crash_velocity=crash_velocity,
        )
    from app.services.dynamic_param_score.param_generator.feature_bins import (
        asset_class_from_symbol,
        regime_class_from_tag,
    )

    return {
        "symbol": symbol,
        "asset_class": asset_class or asset_class_from_symbol(symbol),
        "budget": budget,
        "budget_class": budget_class_from_usdt(budget),
        "regime": regime_class_from_tag(regime),
        "risk_level": risk_level,
        "volatility_bin": volatility_bin_from_percentile(volatility_percentile),
        "structure": structure_from_flags(lower_lows, higher_highs),
        "fee_class": fee_class_from_score(fee_efficiency_score),
    }


def market_signature_v4_from_live(
    *,
    symbol: str,
    budget: float,
    regime: str,
    risk_level: str,
    volatility_percentile: float,
    lower_lows: bool,
    higher_highs: bool,
    fee_efficiency_score: int,
    atr_1h_pct: float | None = None,
    spread_pct: float = 0.0,
    data_quality_score: int = 80,
    return_24h_pct: float | None = None,
    drawdown_7d_pct: float | None = None,
    drawdown_30d_pct: float | None = None,
    z_score_5m: float | None = None,
    price_in_bb: float | None = None,
    volatility_score: int | None = None,
    btc_crash_velocity: float | None = None,
    crash_velocity: float | None = None,
) -> Dict[str, Any]:
    from app.services.dynamic_param_score.param_generator.live_route_classifier_v4 import (
        classify_regime_code_v4,
    )

    a_code = asset_class_from_symbol_v4(symbol)
    b_code = budget_class_from_usdt_v4(budget)
    s_code = structure_from_flags_v4(lower_lows, higher_highs)
    wide_chop = bool(lower_lows and higher_highs)
    vol_pct = _live_volatility_percentile(volatility_percentile, volatility_score)
    atr_val = float(atr_1h_pct if atr_1h_pct is not None else vol_pct / 40.0)
    vol_score = int(volatility_score if volatility_score is not None else vol_pct)
    z_val = float(z_score_5m) if z_score_5m is not None else 0.0
    bb_val = float(price_in_bb) if price_in_bb is not None else 0.5
    btc_pressure = float(btc_crash_velocity or 0.0) < -0.5
    overbought = z_val >= 1.8 and bb_val >= 0.95
    effective_risk = _effective_v4_risk_level(
        risk_level or "NORMAL",
        btc_pressure=btc_pressure,
        overbought=overbought,
        vol_pct=vol_pct,
        fee_efficiency_score=int(fee_efficiency_score or 50),
    )

    live_cls = classify_regime_code_v4(
        regime_tag=regime,
        lower_lows=lower_lows,
        higher_highs=higher_highs,
        return_24h_pct=float(return_24h_pct or 0.0),
        drawdown_7d_pct=float(drawdown_7d_pct or 0.0),
        drawdown_30d_pct=float(drawdown_30d_pct or 0.0),
        z_score_5m=z_score_5m,
        price_in_bb=price_in_bb,
        atr_1h_pct=atr_val,
        risk_level=effective_risk,
        btc_crash_velocity=float(btc_crash_velocity or 0.0),
        crash_velocity=float(crash_velocity or 0.0),
        volatility_percentile=vol_pct,
    )
    r_code = live_cls.regime_code
    v_code = vol_code_from_atr_1h(
        atr_val,
        volatility_score=vol_score,
        return_24h_pct=float(return_24h_pct or 0.0),
    )
    r_code, v_code = _reconcile_regime_vol_codes(
        r_code,
        v_code,
        volatility_percentile=vol_pct,
        wide_chop=wide_chop,
    )
    f_code = fee_code_from_score(fee_efficiency_score, spread_pct)

    dir_bias = direction_bias_for_structure(s_code, r_code)
    g_bias = grid_bias_for_context(s_code, r_code)
    base_quote = (
        "QUOTE_HEAVY" if dir_bias == "DOWN_BIAS"
        else "BASE_HEAVY" if dir_bias == "UP_BIAS"
        else "BALANCED"
    )

    rk = clean_route_key(a_code, r_code, s_code, v_code, effective_risk)
    scenario = live_cls.scenario or REGIME_SHELVES.get(r_code, "BALANCED_RANGE")

    return {
        "symbol": symbol,
        "asset_class": ASSET_SHELVES[a_code][0],
        "asset_code": a_code,
        "budget": budget,
        "budget_class": BUDGET_SHELVES[b_code][0],
        "budget_code": b_code,
        "regime_class": REGIME_SHELVES[r_code],
        "regime": REGIME_SHELVES[r_code],
        "regime_code": r_code,
        "structure_class": STRUCTURE_SHELVES[s_code],
        "structure": STRUCTURE_SHELVES[s_code],
        "structure_code": s_code,
        "volatility_class": VOL_SHELVES[v_code],
        "vol_code": v_code,
        "fee_spread_class": FEE_SHELVES[f_code],
        "fee_code": f_code,
        "risk_class": effective_risk,
        "requested_risk_class": risk_level or "NORMAL",
        "direction_bias": dir_bias,
        "base_quote_bias": base_quote,
        "grid_bias": g_bias,
        "scenario": scenario,
        "live_route_scenario": live_cls.scenario,
        "regime_overlay": live_cls.regime_overlay,
        "classification_reason": live_cls.classification_reason,
        "regime_tag_live": live_cls.regime_tag,
        "volatility_percentile_live": round(vol_pct, 2),
        "btc_pressure": btc_pressure,
        "overbought_chop": overbought and wide_chop,
        "min_notional_state": "OK",
        "data_quality": "GOOD" if data_quality_score >= 75 else "USABLE" if data_quality_score >= 55 else "WEAK",
        "data_quality_score": data_quality_score,
        "data_quality_fit": data_quality_score / 100.0,
        "route_key": rk,
        "clean_route_key": rk,
        "fallback_keys": clean_fallback_keys(rk),
    }


def lookup_candidate_ids(
    index: Dict[str, List[str]],
    sig: Dict[str, Any],
    *,
    max_candidates: int = 500,
) -> List[str]:
    key = route_key_for_signature(sig)
    ids = list(index.get(key, []))
    if ids:
        return ids[:max_candidates]
    for fb in sig.get("fallback_keys") or clean_fallback_keys(key):
        ids = list(index.get(fb, []))
        if ids:
            return ids[:max_candidates]
    return []


def _is_v4_active() -> bool:
    import os

    if os.environ.get("PARAM_POOL_VERSION") == "v4.0.0":
        return True
    from app.services.dynamic_param_score.param_pool.sqlite_store import DEFAULT_V4_SQLITE_PATH

    if DEFAULT_V4_SQLITE_PATH.exists() and os.environ.get("PARAM_POOL_MODE", "auto") != "v3":
        return True
    from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import POOL_VERSION_V4

    return os.environ.get("PARAM_POOL_VERSION") == POOL_VERSION_V4
