"""Market atmosphere classification and deploy-score decomposition (V5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.distribution_policy import (
    DistributionContext,
    distribution_context_from_mapping,
    is_buy_distribution_valid,
    normalize_distribution_for_context,
)
from app.services.dynamic_param_score.models import BotParams, IndicatorSnapshot, SubScores
from app.services.dynamic_param_score.utils import clamp

REGIME_TEXT = {
    "R1": "Güçlü yükseliş trendi",
    "R2": "Dengeli aralık",
    "R3": "Düşük volatilite sıkışma",
    "R4": "Volatil aralık",
    "R5": "Kırılım öncesi sıkışma / kırılım hazırlığı",
    "R6": "Kırılım devamı",
    "R7": "Toparlanma",
    "R8": "Crash / sert düşüş",
    "R9": "Güçlü düşüş",
    "R10": "Alt dipli düşüş",
    "R11": "Başarısız kırılım",
    "R12": "Kapitülasyon tepkisi",
    "R13": "Şok volatilite",
    "R14": "Düşük likidite sürüklenmesi",
    "R15": "Stres geçiş rejimi",
    "R16": "Aşırı uzamış momentum",
    "R17": "Veri belirsizliği",
}


@dataclass
class DecisionScores:
    market_suitability_score: float = 50.0
    execution_safety_score: float = 50.0
    parameter_validity_score: float = 50.0
    exposure_safety_score: float = 50.0
    data_quality_score: float = 50.0
    final_deploy_confidence: float = 50.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "market_suitability_score": round(self.market_suitability_score, 1),
            "execution_safety_score": round(self.execution_safety_score, 1),
            "parameter_validity_score": round(self.parameter_validity_score, 1),
            "exposure_safety_score": round(self.exposure_safety_score, 1),
            "data_quality_score": round(self.data_quality_score, 1),
            "final_deploy_confidence": round(self.final_deploy_confidence, 1),
        }


@dataclass
class MarketAtmosphere:
    asset_class: str = "major_alt"
    regime_code: str = "R2"
    direction_structure: str = "neutral"
    volatility_state: str = "normal"
    liquidity_state: str = "normal"
    execution_state: str = "L1"
    risk_state: str = "NORMAL"
    btc_context: str = "calm"
    data_quality_state: str = "clean"
    fee_bad: bool = False
    issues: List[str] = field(default_factory=list)


def regime_code_from_route(route_key: str) -> str:
    if not route_key or "|" not in route_key:
        return ""
    part = route_key.split("|")[1]
    if part.startswith("R") and len(part) >= 2:
        digits = ""
        for ch in part[1:]:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            return f"R{digits}"
    return part[:3] if part.startswith("R") else ""


def regime_text_from_route(route_key: str) -> str:
    code = regime_code_from_route(route_key)
    return REGIME_TEXT.get(code, "")


def regime_text_for_explanation(route_key: str, regime_tag: str) -> str:
    """Single source for explanation prose — route wins over soft classifier."""
    routed = regime_text_from_route(route_key)
    if routed:
        return routed
    _fallback = {
        "BALANCED_RANGE": "dengeli aralık",
        "RANGE_LOW_VOL": "düşük volatilite aralık",
        "BREAKOUT_RISK": "kırılım riski",
        "TRENDING_UP": "yükseliş trendi",
        "TRENDING_DOWN": "aşağı baskılı trend",
        "HIGH_VOL_UNSTABLE": "yüksek volatilite / dengesiz",
        "DUMP_RISK": "sert düşüş riski",
    }
    return _fallback.get(str(regime_tag or "").upper(), str(regime_tag or "belirsiz"))


def build_distribution_context(
    *,
    sub: SubScores,
    ind: Optional[IndicatorSnapshot],
    risk_state: str,
    route_key: str = "",
    fee_bad: bool = False,
) -> DistributionContext:
    regime_code = regime_code_from_route(route_key)
    data = {
        "risk_state": risk_state or "NORMAL",
        "liquidity_score": int(sub.liquidity_score or 50),
        "spread_score": int(sub.spread_score or 50),
        "btc_market_risk_score": int(sub.btc_market_risk_score or 50),
        "fee_efficiency_score": int(sub.fee_efficiency_score or 50),
        "volatility_score": int(sub.volatility_score or 50),
        "drawdown_risk_score": int(sub.drawdown_risk_score or 50),
        "lower_lows": bool(getattr(ind, "lower_lows", False) if ind else False),
        "higher_highs": bool(getattr(ind, "higher_highs", False) if ind else False),
        "regime_tag": str(getattr(ind, "regime_tag", "") if ind else ""),
        "regime_code": regime_code,
        "rsi_5m": float(getattr(ind, "rsi14_5m", 0) or 0) if ind else None,
        "rsi_1h": float(getattr(ind, "rsi14_1h", 0) or 0) if ind else None,
        "fee_bad": bool(fee_bad),
    }
    return distribution_context_from_mapping(data)


def enforce_momentum_base_cap(
    params: BotParams,
    dist_ctx: DistributionContext,
) -> bool:
    """Cap aggressive base target in high-momentum + fee_bad contexts."""
    if not dist_ctx.high_momentum_buy_context:
        return False
    cap = 0.58
    if float(params.base_alloc_frac or 0) <= cap:
        return False
    params.base_alloc_frac = round(cap, 6)
    params.quote_alloc_frac = round(1.0 - cap, 6)
    params.max_base_exposure_frac = round(
        min(float(params.max_base_exposure_frac or 0.72), cap + 0.06),
        6,
    )
    return True


def enforce_buy_distribution_on_params(
    params: BotParams,
    dist_ctx: DistributionContext,
) -> bool:
    """Normalize buy ladder weights; return True if changed."""
    buy_n = int(params.buy_grid_count or 0)
    if buy_n <= 0 or not params.buy_qty_distribution:
        return False
    pct = [max(1, int(round(float(w) * 100))) for w in params.buy_qty_distribution[:buy_n]]
    fixed, changed = normalize_distribution_for_context(pct, buy_n, dist_ctx)
    params.buy_qty_distribution = [round(x / 100.0, 6) for x in fixed]
    valid, reason = is_buy_distribution_valid(fixed, grid_count=buy_n, ctx=dist_ctx)
    if not valid:
        fixed, _ = normalize_distribution_for_context([], buy_n, dist_ctx)
        params.buy_qty_distribution = [round(x / 100.0, 6) for x in fixed]
        changed = True
    return changed or pct != fixed


def compute_decision_scores(
    sub: SubScores,
    *,
    param_score: int,
    feasibility_meta: Optional[Dict[str, Any]] = None,
    blocking: Optional[List[str]] = None,
    fee_data_available: bool = True,
    worst_exposure_frac: float = 0.0,
    max_exposure_frac: float = 0.72,
) -> DecisionScores:
    from app.services.dynamic_param_score.controlled_deploy import compute_confidence_components

    fm = feasibility_meta or {}
    comps = compute_confidence_components(
        sub,
        param_score=param_score,
        feasibility_meta=fm,
        blocking=blocking or [],
        fee_data_available=fee_data_available,
    )
    exp_score = 88.0
    if worst_exposure_frac > max_exposure_frac + 0.001:
        exp_score = 0.0
    elif worst_exposure_frac > max_exposure_frac * 0.92:
        exp_score = 35.0
    dq = float(sub.data_quality_score or 50)
    if fm.get("data_field_null"):
        dq = max(0, dq - 10)
    final = (
        comps["market_suitability_score"] * 0.30
        + comps["execution_safety_score"] * 0.25
        + comps["parameter_validity_score"] * 0.25
        + exp_score * 0.12
        + dq * 0.08
    )
    return DecisionScores(
        market_suitability_score=float(comps["market_suitability_score"]),
        execution_safety_score=float(comps["execution_safety_score"]),
        parameter_validity_score=float(comps["parameter_validity_score"]),
        exposure_safety_score=exp_score,
        data_quality_score=dq,
        final_deploy_confidence=float(clamp(final, 0, 100)),
    )
