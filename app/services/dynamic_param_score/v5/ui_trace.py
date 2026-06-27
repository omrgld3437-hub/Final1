"""Canonical V5 UI trace labels — route-derived, not free classifier text."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_param_score.v5.domain.route_key import (
    V5RouteParts,
    compact_dimension_code,
    parse_route_key,
)

RISK_LABELS = {
    "K1": "Savunmacı",
    "K2": "Normal kontrollü",
    "K3": "Agresif",
}

REGIME_LABELS = {
    "R1": "Güçlü yükseliş trendi",
    "R2": "Dengeli aralık",
    "R3": "Düşük volatilite sıkışma",
    "R4": "Volatil aralık",
    "R5": "Kırılım öncesi sıkışma",
    "R6": "Kırılım devamı",
    "R7": "Toparlanma",
    "R8": "Crash",
    "R9": "Güçlü düşüş",
    "R10": "Alt dipli düşüş",
    "R11": "Başarısız kırılım",
    "R12": "Kapitülasyon tepkisi",
    "R13": "Yüksek volatilite düzensizliği",
    "R14": "Düşük likidite sürüklenmesi",
    "R15": "Özel stres/geçiş",
    "R16": "Aşırı uzamış momentum",
    "R17": "Veri belirsiz rejim",
}

DIRECTION_LABELS = {
    "D1": "Yukarı eğilim",
    "D2": "Nötr eğilim",
    "D3": "Aşağı eğilim",
}

STRUCTURE_LABELS = {
    "S1": "Aralık orta bölge",
    "S2": "Aralık üst bölge",
    "S3": "Aralık alt bölge",
    "S4": "Üst tepeler",
    "S5": "Alt dipler",
    "S6": "Kırılım hazırlığı",
    "S7": "Kırılım retesti",
    "S8": "Destek kırılımı",
    "S9": "Yapısız chop",
}

RISK_CODE_TO_STATE = {
    "K1": "DEFENSIVE",
    "K2": "NORMAL",
    "K3": "AGGRESSIVE",
}


def route_parts_from_key(route_key: str) -> Optional[V5RouteParts]:
    if not route_key or "|" not in route_key:
        return None
    try:
        return parse_route_key(route_key)
    except (ValueError, KeyError):
        return None


def compact_route_codes(parts: V5RouteParts) -> Dict[str, str]:
    return {
        "asset": compact_dimension_code(parts.asset),
        "regime": compact_dimension_code(parts.regime),
        "direction": compact_dimension_code(parts.direction),
        "structure": compact_dimension_code(parts.structure),
        "volatility": compact_dimension_code(parts.volatility),
        "risk": compact_dimension_code(parts.risk),
        "liquidity": compact_dimension_code(parts.liquidity),
    }


def shelf_suffix_from_parts(parts: V5RouteParts) -> str:
    c = compact_route_codes(parts)
    return "_".join(
        [c["asset"], c["regime"], c["direction"], c["structure"], c["volatility"], c["risk"], c["liquidity"]]
    )


def risk_label_from_route(route_key: str) -> str:
    parts = route_parts_from_key(route_key)
    if not parts:
        return ""
    code = compact_dimension_code(parts.risk)
    return RISK_LABELS.get(code, code)


def risk_state_from_route(route_key: str) -> str:
    parts = route_parts_from_key(route_key)
    if not parts:
        return "NORMAL"
    code = compact_dimension_code(parts.risk)
    return RISK_CODE_TO_STATE.get(code, "NORMAL")


def build_route_semantic_label(route_key: str) -> str:
    """Primary regime label from V5 route semantics."""
    parts = route_parts_from_key(route_key)
    if not parts:
        return ""
    c = compact_route_codes(parts)
    regime = REGIME_LABELS.get(c["regime"], c["regime"])
    direction = DIRECTION_LABELS.get(c["direction"], c["direction"])
    structure = STRUCTURE_LABELS.get(c["structure"], c["structure"])
    return f"{regime} · {direction} · {structure}"


def build_display_regime_label_v5(route_key: str, *, fallback_used: bool = False) -> str:
    parts = route_parts_from_key(route_key)
    if not parts:
        return ""
    c = compact_route_codes(parts)
    regime = REGIME_LABELS.get(c["regime"], c["regime"])
    structure = STRUCTURE_LABELS.get(c["structure"], "")
    chunks = [regime]
    if structure:
        chunks.append(structure)
    risk_lbl = RISK_LABELS.get(c["risk"])
    if risk_lbl:
        chunks.append(risk_lbl.lower())
    if fallback_used:
        chunks.append("fallback raf")
    return " · ".join(chunks)


def build_pattern_phrase(
    *,
    higher_highs: bool,
    lower_lows: bool,
    range_stability: float = 0.5,
) -> str:
    if higher_highs and lower_lows:
        return "geniş chop (üst tepe + alt dip)"
    if higher_highs and not lower_lows:
        return "üst tepe yapısı; alt dip teyidi yok"
    if lower_lows and not higher_highs:
        return "alt dip yapısı; üst tepe teyidi yok"
    if range_stability >= 0.60:
        return "stabil aralık"
    return "belirsiz/chop yapı"


def phrase_means_down_weak_range(phrase: str) -> bool:
    p = (phrase or "").lower()
    return any(x in p for x in ("zayıf düşüş", "düşüş aralığı", "aşağı baskı", "makro düşüş"))


def canonical_semantic_for_route(route_key: str) -> str:
    return build_route_semantic_label(route_key)


def estimate_worst_exposure_pct(
    *,
    target_base_pct: float,
    active_buy_ladder_budget_usdt: float,
    budget_usdt: float,
    current_base_pct: float = 0.0,
) -> float:
    if budget_usdt <= 0:
        return target_base_pct
    ladder_frac = (active_buy_ladder_budget_usdt / budget_usdt) * 100.0
    return round(max(target_base_pct, current_base_pct) + ladder_frac * 0.85, 2)


def derive_safety_result_label(
    *,
    confidence: Optional[float],
    fee_missing: bool,
    btc_risk: float,
    volume_consistency: float,
    live_applicable: bool,
    final_action_label: str = "",
) -> str:
    if not live_applicable:
        return "Referans / bekle"
    if confidence is not None and confidence < 30:
        return "Düşük güven / bekle"
    if fee_missing:
        return "Fee verisi eksik / referans"
    if btc_risk >= 70:
        return "BTC risk yüksek / bekle"
    if volume_consistency < 0.35:
        return "Hacim tutarlılığı zayıf / referans"
    return final_action_label or "Dengeli grid"


def render_risk_opportunity_sentence(risk_score: Any, opportunity_score: Any) -> str:
    if isinstance(risk_score, (int, float)) and isinstance(opportunity_score, (int, float)):
        return f"risk skoru {risk_score:.0f}/100, fırsat skoru {opportunity_score:.0f}/100"
    return "risk ve fırsat dengesi mevcut indikatörlere göre tartılıyor"


def build_grid_summary_text(*, buy_first: float, sell_first: float, buy_count: int, sell_count: int) -> str:
    return (
        f"Grid aralığı: alış %{buy_first:.2f} · satış %{sell_first:.2f} "
        f"({buy_count} alış · {sell_count} satış kademe)"
    )
