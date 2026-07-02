"""Regime / route display helpers — V6-first (no V5 shelf dependency)."""

from __future__ import annotations

from typing import Optional

V6_REGIME_LABELS = {
    "R1": "Güçlü yükseliş trendi",
    "R2": "Dengeli aralık",
    "R3": "Zayıf / gürültülü aralık",
    "R4": "Volatil aralık",
    "R5": "Toparlanma",
    "R6": "Toparlanma / zayıf yükseliş",
    "R7": "Düşüş trendi",
    "R8": "Crash / sert düşüş",
}

# Ana PA/DM ekranı — teknik kod yok, işlem anlamı
V6_MARKET_STATUS_PLAIN: dict[str, str] = {
    "R1": "Fiyat yükseliş trendinde, aktif fırsat var",
    "R2": "Fiyat yatay bölgede, iki yönlü fırsat var",
    "R3": "Fiyat gürültülü aralıkta, temkinli grid kullanılıyor",
    "R4": "Fiyat sert dalgalanıyor, gridler geniş tutuldu",
    "R5": "Toparlanma başlıyor, kontrollü alım fırsatı var",
    "R6": "Düşüş sonrası kademeli toparlanma var",
    "R7": "Düşüş trendi var, savunmacı mod aktif",
    "R8": "Sert düşüş var, yüksek riskli savunmacı mod",
}

LEGACY_REGIME_PLAIN: dict[str, str] = {
    "BALANCED_RANGE": "Fiyat yatay bölgede, iki yönlü fırsat var",
    "RANGE_LOW_VOL": "Fiyat yatay bölgede, iki yönlü fırsat var",
    "RANGE_HIGH_VOL": "Fiyat sert dalgalanıyor, gridler geniş tutuldu",
    "HIGH_VOL_UNSTABLE": "Fiyat sert dalgalanıyor, gridler geniş tutuldu",
    "TRENDING_UP": "Fiyat yükseliş trendinde, aktif fırsat var",
    "TRENDING_DOWN": "Düşüş trendi var, savunmacı mod aktif",
    "DUMP_RISK": "Sert düşüş var, yüksek riskli savunmacı mod",
    "BREAKOUT_RISK": "Kırılım riski var, temkinli grid kullanılıyor",
    "LOW_LIQUIDITY": "Likidite düşük, temkinli mod",
    "SPREAD_UNSAFE": "Spread geniş, işlem için uygun değil",
    "NO_TRADE": "Mevcut koşullarda işlem önerilmiyor",
    "NO_DATA": "Veri yetersiz",
}

RISK_TONE_PLAIN: dict[str, str] = {
    "Kontrollü savunmacı": "Temkinli strateji",
    "Savunmacı": "Temkinli strateji",
    "Normal": "Dengeli strateji",
    "Aktif": "Aktif strateji",
    "DEFENSIVE": "Temkinli strateji",
    "NORMAL": "Dengeli strateji",
    "CAUTION": "Temkinli strateji",
    "AGGRESSIVE": "Aktif strateji",
    "SAFE": "Güvenli strateji",
    "BLOCKED": "İşlem kapalı",
}

REGIME_LABELS = V6_REGIME_LABELS

RISK_LABELS = {
    "K1": "Savunmacı",
    "K2": "Normal kontrollü",
    "K3": "Agresif",
}

RISK_CODE_TO_STATE = {
    "K1": "DEFENSIVE",
    "K2": "NORMAL",
    "K3": "AGGRESSIVE",
}


def _route_parts(route_key: str) -> list[str]:
    return [p.strip() for p in str(route_key or "").split("|") if p.strip()]


def regime_code_from_route_key(route_key: str) -> str:
    parts = _route_parts(route_key)
    if len(parts) < 2:
        return ""
    part = parts[1].upper()
    if part.startswith("R"):
        return part[:3]
    return part[:3]


def risk_code_from_route_key(route_key: str) -> str:
    parts = _route_parts(route_key)
    if len(parts) < 6:
        return "K2"
    part = parts[5].upper()
    return part[:2] if part.startswith("K") else part


def risk_label_from_route(route_key: str) -> str:
    code = risk_code_from_route_key(route_key)
    return RISK_LABELS.get(code, code)


def risk_state_from_route(route_key: str) -> str:
    code = risk_code_from_route_key(route_key)
    return RISK_CODE_TO_STATE.get(code, "NORMAL")


def build_display_regime_label_v6(regime_id: str, *, name: str = "") -> str:
    base = V6_REGIME_LABELS.get(regime_id, regime_id)
    return f"{base} · {name}" if name else base


def market_status_plain(regime_id: str = "", *, legacy_tag: str = "") -> str:
    """User-facing market summary for PA/DM main screen (no technical IDs)."""
    rid = str(regime_id or "").upper()
    if rid in V6_MARKET_STATUS_PLAIN:
        return V6_MARKET_STATUS_PLAIN[rid]
    tag = str(legacy_tag or "").upper()
    if tag in LEGACY_REGIME_PLAIN:
        return LEGACY_REGIME_PLAIN[tag]
    if tag:
        return tag.replace("_", " ").lower().capitalize()
    return "Piyasa koşulları analiz edildi"


def risk_tone_plain(risk_label: str = "") -> str:
    """Plain risk tone for main PA/DM screen."""
    raw = str(risk_label or "").strip()
    if not raw:
        return "Temkinli strateji"
    if raw in RISK_TONE_PLAIN:
        return RISK_TONE_PLAIN[raw]
    upper = raw.upper()
    if upper in RISK_TONE_PLAIN:
        return RISK_TONE_PLAIN[upper]
    return raw


def format_confidence_pct(score: Optional[float]) -> str:
    if score is None:
        return "—"
    try:
        return f"%{int(round(float(score)))}"
    except (TypeError, ValueError):
        return "—"


def build_regime_technical_label(scen: Optional[dict]) -> str:
    """Technical regime line for detail / selection trace panels only."""
    scen = scen or {}
    regime_id = str(scen.get("regime_id") or "")
    name = str(scen.get("name") or "").strip()
    base = V6_REGIME_LABELS.get(regime_id, regime_id)
    if name:
        return name if name.startswith(base) or base in name else f"{base} · {name}"
    parts = [base]
    sub = scen.get("sub_id")
    micro = scen.get("micro_id")
    term = scen.get("terminal_id")
    beh = scen.get("behavior_id")
    if sub:
        parts.append(f"alt-{sub}")
    if micro:
        parts.append(f"mikro-{micro}")
    if term:
        parts.append(str(term))
    if beh:
        parts.append(str(beh))
    return " · ".join(parts)


def build_display_regime_label_v5(route_key: str, *, fallback_used: bool = False) -> str:
    """Legacy route label — kept for V4 route strings in adapters."""
    code = regime_code_from_route_key(route_key)
    label = V6_REGIME_LABELS.get(code, code)
    if fallback_used:
        label = f"{label} · fallback"
    return label


def build_route_semantic_label(route_key: str) -> str:
    code = regime_code_from_route_key(route_key)
    return V6_REGIME_LABELS.get(code, code)


def build_pattern_phrase(*_args, **_kwargs) -> str:
    return ""


def render_risk_opportunity_sentence(*_args, **_kwargs) -> str:
    return ""


def derive_safety_result_label(*_args, **_kwargs) -> str:
    return ""


def build_route_semantic_label_v5(route_key: str) -> str:
    return build_route_semantic_label(route_key)
