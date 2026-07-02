"""Param Assistant result_type / controlled_grid semantic contract."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.dynamic_param_score.atmosphere import regime_code_from_route
from app.services.dynamic_param_score.models import BotParams, FinalAction

_CAPITULATION_REGIMES = frozenset({"R8", "R12", "R13", "R15"})


def resolve_fee_data_status(fee_display: Optional[Dict[str, Any]]) -> str:
    fd = fee_display or {}
    raw = fd.get("status")
    if isinstance(raw, str) and raw:
        return raw
    if fd.get("fee_data_available") is True:
        return "live_fee"
    if fd.get("fee_data_available") is False:
        return "missing_fee"
    return "missing_fee"


def grid_spacing_from_params(params: Optional[BotParams]) -> Tuple[Optional[float], Optional[float]]:
    if not params:
        return None, None
    buy = float(params.buy_grid_spacing_pct) if params.buy_grid_spacing_pct else None
    sell = float(params.sell_grid_spacing_pct) if params.sell_grid_spacing_pct else None
    return buy, sell


def is_unsafe_controlled_start(
    *,
    result_type: str,
    param_score: int,
    risk_score: Optional[int],
    spread_pct: Optional[float],
    fee_missing: bool,
    effective_risk_state: str,
    route_key: str = "",
) -> bool:
    """Block deployable controlled_grid when spread/risk/fee/regime combo is unsafe."""
    rt = str(result_type or "")
    if rt not in ("controlled_grid", "restricted_deployable_grid"):
        return False
    if int(param_score or 0) < 50:
        return True
    if risk_score is not None and int(risk_score) < 20:
        return True
    if spread_pct is not None and float(spread_pct) >= 0.10:
        return True
    rs = str(effective_risk_state or "").upper()
    rc = regime_code_from_route(route_key)
    if fee_missing and (rs == "DEFENSIVE" or rc in _CAPITULATION_REGIMES):
        return True
    return False


def resolve_controlled_contract(
    *,
    result_type: str,
    final_action: str,
    deployable: bool,
    params: Optional[BotParams],
    feasibility_meta: Dict[str, Any],
    fee_missing: bool,
    param_score: int = 0,
    risk_score: Optional[int] = None,
    spread_pct: Optional[float] = None,
    effective_risk_state: str = "",
    route_key: str = "",
) -> Dict[str, Any]:
    """Normalize controlled_grid vs recommended_grid semantics."""
    meta = feasibility_meta or {}
    buy_n = int(params.buy_grid_count or 0) if params else 0
    fa = str(final_action or "").upper()
    rt = str(result_type or "")
    exposure_breach = bool(meta.get("exposure_hard_cap_breach"))
    worst = float(meta.get("worst_case_base_exposure_frac") or 0.0)
    max_exp = float(meta.get("max_base_exposure_frac") or 0.0)
    if max_exp > 0 and worst > max_exp:
        exposure_breach = True

    controlled_intent = bool(
        meta.get("controlled_grid")
        or rt in ("controlled_grid", "restricted_deployable_grid")
        or fa == FinalAction.CONTROLLED_GRID.value
    )
    can_start = bool(
        controlled_intent
        and deployable
        and buy_n >= 2
        and not exposure_breach
        and not meta.get("distribution_invalid")
    )
    full_deployable = bool(meta.get("full_deployable"))
    unsafe = is_unsafe_controlled_start(
        result_type=rt,
        param_score=param_score,
        risk_score=risk_score,
        spread_pct=spread_pct,
        fee_missing=fee_missing,
        effective_risk_state=effective_risk_state,
        route_key=route_key,
    )
    if unsafe:
        rt = "recommended_grid"
        controlled_intent = False
        can_start = False
        meta_note = "UNSAFE_CONTROLLED_GRID_CONDITIONS"
    else:
        meta_note = None

    if rt in ("controlled_grid", "restricted_deployable_grid") and not can_start:
        rt = "recommended_grid"
        controlled_intent = False

    if can_start:
        if fee_missing or not full_deployable:
            user_label = "Kontrollü grid / fee verisi eksik" if fee_missing else "Kontrollü grid önerildi"
        else:
            user_label = "Kontrollü grid önerildi"
        can_start_mode = "controlled"
    elif unsafe:
        user_label = (
            "Parametre referans olarak üretildi; spread/risk/fee koşulları nedeniyle "
            "kontrollü başlangıç kapalı tutuldu."
        )
        can_start_mode = "reference"
    elif controlled_intent and not can_start:
        user_label = "Referans / bekle"
        can_start_mode = "reference"
    else:
        user_label = None
        can_start_mode = None

    return {
        "result_type": rt,
        "can_start_controlled": can_start,
        "can_start_mode": can_start_mode,
        "full_deployable": full_deployable,
        "user_visible_decision": user_label,
        "controlled_grid": controlled_intent and can_start,
        "unsafe_controlled_blocked": unsafe,
        "unsafe_controlled_reason": meta_note,
    }
