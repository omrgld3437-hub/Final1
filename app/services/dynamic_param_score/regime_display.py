"""Regime / route display helpers — V6-first (no V5 shelf dependency)."""

from __future__ import annotations

from typing import Optional

V6_REGIME_LABELS = {
    "R1": "Güçlü yükseliş trendi",
    "R2": "Dengeli aralık",
    "R3": "Zayıf / gürültülü aralık",
    "R4": "Volatil aralık",
    "R5": "Toparlanma",
    "R6": "Tepe / dağılım / zayıflama",
    "R7": "Düşüş trendi",
    "R8": "Crash / sert düşüş",
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
