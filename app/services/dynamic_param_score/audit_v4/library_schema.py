"""V4 library profile schema — separate from runtime BotParams / adapter output."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    ASSET_SHELVES,
    REGIME_SHELVES,
    STRUCTURE_SHELVES,
    VOL_SHELVES,
    normalize_route_key,
    structure_to_legacy,
)

PROFILE_TYPE_LIBRARY = "library_v4"
PROFILE_TYPE_RUNTIME = "runtime_output"

_LEGACY_VOL_LABEL = {
    "V1": "0_10",
    "V2": "10_25",
    "V3": "25_50",
    "V4": "50_75",
    "V5": "90_100",
}


def profile_type_of(profile: Dict[str, Any]) -> str:
    if profile.get("fallback_generated") or profile.get("runtime_safe_profile"):
        return PROFILE_TYPE_RUNTIME
    if str(profile.get("version") or "") == "DPS_ENGINE_V4":
        return PROFILE_TYPE_LIBRARY
    if profile.get("route_key") and str(profile.get("profile_id", "")).startswith("DPLV4_"):
        return PROFILE_TYPE_LIBRARY
    return PROFILE_TYPE_LIBRARY


def _route_parts(route_key: str) -> Optional[Dict[str, str]]:
    rk = normalize_route_key(str(route_key or ""))
    parts = rk.split("|")
    if len(parts) != 5:
        return None
    a, r, s, v, risk = parts
    if not (a.startswith("A") and r.startswith("R") and s.startswith("S") and v.startswith("V")):
        return None
    return {
        "asset_code": a,
        "regime_code": r,
        "structure_code": s,
        "vol_code": v,
        "risk_class": risk,
    }


def audit_library_profile_schema(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    """Structured schema failures for on-disk library profiles (not runtime overlay)."""
    if profile_type_of(profile) == PROFILE_TYPE_RUNTIME:
        return []

    rows: List[Dict[str, str]] = []
    pid = str(profile.get("profile_id") or profile.get("template_key") or "")
    rk_raw = str(profile.get("route_key") or "")
    rk = normalize_route_key(rk_raw)
    scenario = str(profile.get("scenario") or profile.get("reason_code") or "")
    ptype = profile_type_of(profile)

    def _row(*, missing: str = "", invalid: str = "", reason: str = "") -> None:
        rows.append(
            {
                "profile_id": pid,
                "route_key": rk or rk_raw,
                "scenario": scenario,
                "profile_type": ptype,
                "missing_field": missing,
                "invalid_field": invalid,
                "reason": reason or missing or invalid,
            }
        )

    if not pid:
        _row(missing="profile_id", reason="profile_id_empty")

    if not rk:
        _row(missing="route_key", reason="route_key_empty")
    else:
        parts = _route_parts(rk)
        if not parts:
            _row(invalid="route_key", reason="route_key_fail")
        legacy_parts = rk_raw.split("|")
        if len(legacy_parts) == 7:
            if any(p.startswith("B") for p in legacy_parts):
                _row(invalid="route_key", reason="budget_in_route_fail")
            if any(p.startswith("F") for p in legacy_parts):
                _row(invalid="route_key", reason="fee_in_route_fail")

    parts = _route_parts(rk) if rk else None
    if parts:
        for code_key, shelf, label_key in (
            ("asset_code", ASSET_SHELVES, "asset_class"),
            ("regime_code", REGIME_SHELVES, "regime"),
            ("structure_code", STRUCTURE_SHELVES, "structure"),
            ("vol_code", VOL_SHELVES, "volatility_bin"),
        ):
            code = parts[code_key]
            if code_key == "asset_code":
                valid = code in shelf
            else:
                valid = code in shelf
            if not valid:
                _row(invalid=code_key, reason=f"invalid_{code_key}")
            stored = profile.get(code_key) or profile.get(label_key)
            if not stored:
                _row(missing=code_key, reason=f"{code_key}_empty")

    if not scenario and not profile.get("regime_code") and not profile.get("regime"):
        _row(missing="scenario", reason="scenario_empty")

    structure = profile.get("structure") or profile.get("structure_code") or (parts or {}).get("structure_code")
    if not structure:
        _row(missing="structure", reason="structure_empty")

    vol = (
        profile.get("volatility_bin")
        or profile.get("vol_code")
        or (parts or {}).get("vol_code")
    )
    if not vol:
        _row(missing="volatility_bin", reason="volatility_empty")

    risk = profile.get("risk_class") or profile.get("risk_level") or (parts or {}).get("risk_class")
    if not risk:
        _row(missing="risk_class", reason="risk_empty")

    return rows


def backfill_library_schema_fields(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Derive missing library metadata from clean route_key — does not touch runtime fields."""
    out = dict(profile)
    parts = _route_parts(str(out.get("route_key") or ""))
    if not parts:
        return out

    a = parts["asset_code"]
    r = parts["regime_code"]
    s = parts["structure_code"]
    v = parts["vol_code"]
    risk = parts["risk_class"]

    out.setdefault("asset_code", a)
    out.setdefault("regime_code", r)
    out.setdefault("structure_code", s)
    out.setdefault("vol_code", v)
    out.setdefault("risk_class", risk)
    out.setdefault("asset_class", ASSET_SHELVES.get(a, ("MID_CAP_NORMAL", 0))[0])
    out.setdefault("regime", REGIME_SHELVES.get(r, "BALANCED_RANGE"))
    out.setdefault("structure", structure_to_legacy(s))
    out.setdefault("volatility_bin", _LEGACY_VOL_LABEL.get(v, "25_50"))
    out.setdefault("version", "DPS_ENGINE_V4")
    if not out.get("scenario"):
        out["scenario"] = out.get("regime") or REGIME_SHELVES.get(r, "BALANCED_RANGE")
    out["route_key"] = normalize_route_key(str(out.get("route_key") or ""))
    return out
