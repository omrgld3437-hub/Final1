"""V6 opportunity-oriented post-processing — risk-adaptive workable params."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.models import BotParams, DynamicParamDecision
from app.services.dynamic_param_score.v6.domain.types import GridLevel, V6CatalogProfile, V6InputContract
from app.services.dynamic_param_score.v6.v6_quantizer import quantize_profile

MAJOR_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"})

R6_CONTROLLED_ACTIVE = "R6_CONTROLLED_ACTIVE"
R6_PROTECTIVE_SELL_ONLY = "R6_PROTECTIVE_SELL_ONLY"

# 1-week bot reachability bands (first grid distance, abs for buy)
_ONE_WEEK_GRID_BANDS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "R1": {"buy": (4, 9), "sell": (5, 11)},
    "R2": {"buy": (4, 9), "sell": (3, 8)},
    "R3": {"buy": (6, 12), "sell": (4, 9)},
    "R4": {"buy": (8, 15), "sell": (5, 13)},
    "R5": {"buy": (4, 10), "sell": (4, 9)},
    "R6": {"buy": (4, 9), "sell": (3, 8)},
    "R7": {"buy": (9, 24), "sell": (5, 11)},
    "R8": {"buy": (10, 20), "sell": (6, 14)},
}


@dataclass
class OperationalValidity:
    """Final profile must be workable — not merely non-null params."""

    valid: bool
    mode: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "mode": self.mode, "errors": list(self.errors)}


def btc_context_delta_multiplier(symbol: str, btc_class: str = "") -> float:
    sym = str(symbol or "").upper()
    if sym == "BTCUSDT":
        return 0.5
    if sym in MAJOR_SYMBOLS and btc_class in ("B2", "B3"):
        return 0.75
    return 1.0


def scale_adjuster_delta(delta, multiplier: float):
    """Scale numeric delta fields in-place (AdjusterDelta)."""
    if multiplier >= 1.0:
        return delta
    m = float(multiplier)
    delta.base_delta_steps = int(round(delta.base_delta_steps * m))
    delta.buy_grid_distance_delta = int(round(delta.buy_grid_distance_delta * m))
    delta.sell_grid_distance_delta = int(round(delta.sell_grid_distance_delta * m))
    delta.buyback_trigger_delta = round(delta.buyback_trigger_delta * m, 2)
    delta.profit_sell_trigger_delta = round(delta.profit_sell_trigger_delta * m, 2)
    delta.buy_trailing_delta_steps = int(round(delta.buy_trailing_delta_steps * m))
    delta.sell_trailing_delta_steps = int(round(delta.sell_trailing_delta_steps * m))
    delta.buy_grid_count_delta = int(round(delta.buy_grid_count_delta * m))
    delta.sell_grid_count_delta = int(round(delta.sell_grid_count_delta * m))
    return delta


def _trace_class(trace: List[Dict[str, Any]], name: str) -> str:
    for entry in trace or []:
        if str(entry.get("name") or "") == name:
            return str(entry.get("class") or "")
    return ""


def _trace_score(trace: List[Dict[str, Any]], name: str) -> int:
    for entry in trace or []:
        if str(entry.get("name") or "") == name:
            return int(entry.get("score") or 0)
    return 0


def _is_clean_market(trace: List[Dict[str, Any]], inp: V6InputContract) -> bool:
    frag = _trace_class(trace, "asset_fragility")
    vol = _trace_class(trace, "volatility")
    liq = _trace_class(trace, "liquidity")
    btc = _trace_class(trace, "btc_context")
    dq = _trace_score(trace, "data_quality")
    return (
        frag in ("F0", "F1")
        and vol in ("V1", "V2")
        and liq in ("L0", "L1")
        and btc in ("B0", "B1", "B2")
        and dq < 50
        and (inp.spread_pct or 0) <= 0.25
        and inp.zero_volume_flag is not True
    )


def resolve_r6_mode(
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
) -> str:
    if str(regime_id) != "R6":
        return ""
    frag = _trace_class(trace, "asset_fragility")
    vol = _trace_class(trace, "volatility")
    liq = _trace_class(trace, "liquidity")
    btc = _trace_class(trace, "btc_context")
    dq = _trace_score(trace, "data_quality")

    high_risk = (
        frag == "F3"
        or vol in ("V4", "V5")
        or liq in ("L2", "L3")
        or btc == "B3"
        or (inp.fake_breakout_score is not None and inp.fake_breakout_score >= 70)
        or dq >= 50
        or (inp.spread_pct or 0) > 0.25
        or (inp.zero_volume_flag is True)
    )
    if high_risk:
        return R6_PROTECTIVE_SELL_ONLY

    clean = _is_clean_market(trace, inp)
    if clean or (
        str(inp.symbol or "").upper() in MAJOR_SYMBOLS
        and frag in ("F0", "F1", "F2")
        and vol in ("V1", "V2", "V3")
        and btc != "B3"
    ):
        return R6_CONTROLLED_ACTIVE
    return R6_PROTECTIVE_SELL_ONLY


def _profit_loop_modules(enabled: bool = True) -> Dict[str, bool]:
    return {
        "profit_buyback_after_sell": enabled,
        "profit_sell_after_buyback": enabled,
    }


def _apply_r6_protective_sell_only(profile: V6CatalogProfile) -> V6CatalogProfile:
    p = profile.copy()
    p.base_allocation_pct = max(10, min(int(p.base_allocation_pct or 15), 15))
    p.quote_allocation_pct = 100 - p.base_allocation_pct
    p.normal_buy_enabled = False
    p.buy_grids = []
    if not p.sell_grids:
        p.sell_grids = [GridLevel(8, 100)]
    elif len(p.sell_grids) == 1:
        d1 = int(p.sell_grids[0].distance_pct)
        p.sell_grids = [GridLevel(max(7, d1), 60), GridLevel(min(11, d1 + 4), 40)]
    p.buyback_after_sell_enabled = True
    p.profit_sell_after_buyback_enabled = True
    p.buyback_trigger_code = p.buyback_trigger_code or "K12"
    p.profit_sell_trigger_code = p.profit_sell_trigger_code or "K12"
    p.modules = {
        **(p.modules or {}),
        "initial_base_allocation": True,
        "normal_buy_grid": False,
        "sell_grid": True,
        **_profit_loop_modules(True),
    }
    return quantize_profile(p)


def _apply_r6_controlled_active(profile: V6CatalogProfile) -> V6CatalogProfile:
    p = profile.copy()
    p.base_allocation_pct = 20
    p.quote_allocation_pct = 80
    p.normal_buy_enabled = True
    p.buy_grids = [GridLevel(-5, 40), GridLevel(-9, 60)]
    p.sell_grids = [GridLevel(4, 60), GridLevel(8, 40)]
    p.buy_trailing_code = "T2"
    p.sell_trailing_code = "T2"
    p.buyback_after_sell_enabled = True
    p.buyback_trigger_code = "K11"
    p.buyback_trailing_code = "T2"
    p.profit_sell_after_buyback_enabled = True
    p.profit_sell_trigger_code = "K11"
    p.profit_sell_trailing_code = "T2"
    p.modules = {
        **(p.modules or {}),
        "initial_base_allocation": True,
        "normal_buy_grid": True,
        "sell_grid": True,
        "profit_buyback_after_sell": True,
        "profit_sell_after_buyback": True,
    }
    return quantize_profile(p)


def _cap_grid_distances(
    grids: List[GridLevel],
    *,
    is_buy: bool,
    first_max: int,
    second_max: Optional[int] = None,
) -> List[GridLevel]:
    if not grids:
        return grids
    out: List[GridLevel] = []
    for i, g in enumerate(grids):
        cap = first_max if i == 0 else (second_max if second_max is not None else first_max + 4)
        if is_buy:
            dist = g.distance_pct
            if abs(dist) > cap:
                dist = -cap
            out.append(GridLevel(dist, g.amount_pct))
        else:
            dist = min(g.distance_pct, cap)
            out.append(GridLevel(max(1, dist), g.amount_pct))
    return out


def _r1_target_base_pct(trace: List[Dict[str, Any]], inp: V6InputContract) -> int:
    """R1 uptrend: higher coin base for sell-grid + profit-loop turnover (not cash parking)."""
    frag = _trace_class(trace, "asset_fragility")
    btc = _trace_class(trace, "btc_context")
    vol = _trace_class(trace, "volatility")
    if frag == "F3":
        return 0
    if frag == "F2":
        return 45
    if btc == "B3":
        return 40
    target = 50
    if btc == "B2":
        target = 50
    if vol in ("V1", "V2"):
        target = 55
    if str(inp.symbol or "").upper() in MAJOR_SYMBOLS and frag in ("F0", "F1") and btc in ("B0", "B1", "B2"):
        target = max(target, 55)
    return min(target, 60)


def _apply_r1_opportunity(
    profile: V6CatalogProfile,
    trace: List[Dict[str, Any]],
    inp: V6InputContract,
) -> V6CatalogProfile:
    target = _r1_target_base_pct(trace, inp)
    if target <= 0:
        return profile
    p = profile.copy()
    if p.base_allocation_pct < target:
        p.base_allocation_pct = target
        p.quote_allocation_pct = 100 - target
    if p.normal_buy_enabled and p.buy_grids:
        p.buy_grids = _cap_grid_distances(p.buy_grids, is_buy=True, first_max=9, second_max=9)
    if p.sell_grids:
        p.sell_grids = _cap_grid_distances(p.sell_grids, is_buy=False, first_max=10, second_max=10)
    return quantize_profile(p)


def _apply_r3_opportunity(
    profile: V6CatalogProfile,
    trace: List[Dict[str, Any]],
) -> V6CatalogProfile:
    frag = _trace_class(trace, "asset_fragility")
    if frag == "F3":
        return profile
    buy_n, sell_n = _profile_grid_counts(profile)
    if buy_n > 0:
        return profile
    p = profile.copy()
    p.normal_buy_enabled = True
    p.buy_grids = [GridLevel(-7, 40), GridLevel(-12, 60)]
    if p.base_allocation_pct < 15:
        p.base_allocation_pct = 15
        p.quote_allocation_pct = 85
    if not p.sell_grids:
        p.sell_grids = [GridLevel(5, 60), GridLevel(9, 40)]
    p.modules = {**(p.modules or {}), "normal_buy_grid": True, "sell_grid": True}
    return quantize_profile(p)


def _apply_r4_opportunity(
    profile: V6CatalogProfile,
    trace: List[Dict[str, Any]],
) -> V6CatalogProfile:
    vol = _trace_class(trace, "volatility")
    if vol in ("V4", "V5"):
        return profile
    p = profile.copy()
    if p.buy_grids:
        p.buy_grids = _cap_grid_distances(p.buy_grids, is_buy=True, first_max=11, second_max=15)
    if p.sell_grids:
        p.sell_grids = _cap_grid_distances(p.sell_grids, is_buy=False, first_max=10, second_max=13)
    return quantize_profile(p)


def _apply_r5_opportunity(
    profile: V6CatalogProfile,
    trace: List[Dict[str, Any]],
    inp: V6InputContract,
) -> V6CatalogProfile:
    if not _is_clean_market(trace, inp):
        return profile
    p = profile.copy()
    if p.base_allocation_pct < 25:
        p.base_allocation_pct = 25
        p.quote_allocation_pct = 75
    if p.normal_buy_enabled and not p.buy_grids:
        p.buy_grids = [GridLevel(-5, 40), GridLevel(-10, 60)]
    if p.buy_grids:
        p.buy_grids = _cap_grid_distances(p.buy_grids, is_buy=True, first_max=10, second_max=10)
    if p.sell_grids:
        p.sell_grids = _cap_grid_distances(p.sell_grids, is_buy=False, first_max=9, second_max=9)
    return quantize_profile(p)


def _apply_r7_deep_buy(
    profile: V6CatalogProfile,
) -> V6CatalogProfile:
    buy_n, _ = _profile_grid_counts(profile)
    if buy_n > 0:
        return profile
    p = profile.copy()
    p.normal_buy_enabled = True
    p.buy_grids = [GridLevel(-10, 35), GridLevel(-16, 40), GridLevel(-24, 25)]
    if p.base_allocation_pct > 15:
        p.base_allocation_pct = 10
        p.quote_allocation_pct = 90
    elif p.base_allocation_pct < 5:
        p.base_allocation_pct = 5
        p.quote_allocation_pct = 95
    if not p.sell_grids:
        p.sell_grids = [GridLevel(6, 60), GridLevel(11, 40)]
    p.modules = {**(p.modules or {}), "normal_buy_grid": True, "sell_grid": bool(p.sell_grids)}
    return quantize_profile(p)


def apply_regime_opportunity_behavior(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """Risk-adaptive regime templates — opportunity over idle protection."""
    notes: Dict[str, Any] = {}
    regime = str(regime_id or "")
    p = profile
    r6_mode = resolve_r6_mode(inp, trace, regime) if regime == "R6" else ""
    notes["r6_mode"] = r6_mode or None

    if regime == "R6":
        if r6_mode == R6_CONTROLLED_ACTIVE:
            p = _apply_r6_controlled_active(p)
            notes["regime_opportunity"] = R6_CONTROLLED_ACTIVE
        else:
            p = _apply_r6_protective_sell_only(p)
            notes["regime_opportunity"] = R6_PROTECTIVE_SELL_ONLY
    elif regime == "R1":
        p = _apply_r1_opportunity(p, trace, inp)
        notes["regime_opportunity"] = "R1_EXPAND"
        notes["r1_target_base_pct"] = int(p.base_allocation_pct or 0)
    elif regime == "R3":
        p = _apply_r3_opportunity(p, trace)
        notes["regime_opportunity"] = "R3_DEEP_BUY"
    elif regime == "R4":
        p = _apply_r4_opportunity(p, trace)
        notes["regime_opportunity"] = "R4_VOL_AWARE"
    elif regime == "R5":
        p = _apply_r5_opportunity(p, trace, inp)
        notes["regime_opportunity"] = "R5_RECOVERY"
    elif regime == "R7":
        p = _apply_r7_deep_buy(p)
        notes["regime_opportunity"] = "R7_DEEP_BUY_ONLY"

    p = apply_r2_grid_contraction(p, inp, trace, regime)
    if regime in ("R2", "R3") and _trace_class(trace, "volatility") in ("V1", "V2"):
        notes["r2_contraction_applied"] = True

    behavior = str(p.scenario.behavior_id or "")
    if behavior == "PB11" or regime == "R8":
        if not p.sell_grids:
            p = p.copy()
            p.sell_grids = [GridLevel(8, 100)]
            p.modules = {**(p.modules or {}), "sell_grid": True}
        p = p.copy()
        p.buyback_after_sell_enabled = True
        p.profit_sell_after_buyback_enabled = True
        p.modules = {**(p.modules or {}), **_profit_loop_modules(True)}
        notes["pb11_loop_preserved"] = True
        p = quantize_profile(p)

    return p, notes


def apply_r2_grid_contraction(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
) -> V6CatalogProfile:
    if str(regime_id) not in ("R2", "R3"):
        return profile
    vol = _trace_class(trace, "volatility")
    frag = _trace_class(trace, "asset_fragility")
    liq = _trace_class(trace, "liquidity")
    btc = _trace_class(trace, "btc_context")
    if vol not in ("V1", "V2") or frag not in ("F0", "F1") or liq not in ("L0", "L1"):
        return profile
    if btc == "B3" or frag == "F3":
        return profile

    p = profile.copy()
    if p.buy_grids:
        p.buy_grids = _cap_grid_distances(p.buy_grids, is_buy=True, first_max=5, second_max=9)
    if p.sell_grids:
        p.sell_grids = _cap_grid_distances(p.sell_grids, is_buy=False, first_max=4, second_max=8)
    if p.base_allocation_pct < 25:
        p.base_allocation_pct = 25
        p.quote_allocation_pct = 75
    return quantize_profile(p)


def apply_v6_opportunity_postprocess(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
    *,
    severity: str = "STD",
    sub_profile_hint: str = "",
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """Post-pipeline: regime behavior spec → operational repair → validity gate."""
    from app.services.dynamic_param_score.v6.v6_regime_behavior_spec import apply_regime_behavior_spec

    sev = str(severity or profile.scenario.severity or "STD").upper()
    if sev not in ("DEF", "STD", "ACT"):
        sev = "STD"
    p, notes = apply_regime_behavior_spec(
        profile, inp, trace, regime_id=regime_id, severity=sev, sub_profile_hint=sub_profile_hint  # type: ignore[arg-type]
    )
    p, op_notes = ensure_profile_operational(p, inp, trace, regime_id)
    notes.update(op_notes)
    validity = assess_operational_validity(p)
    notes["operational_validity"] = validity.to_dict()
    if not validity.valid:
        notes["operational_repair_required"] = True
    notes["params_valid"] = True
    notes["controlled_grid"] = True
    return p, notes


def _profile_grid_counts(profile: V6CatalogProfile) -> Tuple[int, int]:
    buy_n = len(profile.buy_grids) if profile.normal_buy_enabled else 0
    sell_n = len(profile.sell_grids)
    return buy_n, sell_n


def assess_operational_validity(profile: V6CatalogProfile) -> OperationalValidity:
    """Mandatory final gate — params must represent a real trading plan."""
    buy_n, sell_n = _profile_grid_counts(profile)
    base = int(profile.base_allocation_pct or 0)
    behavior = str(profile.scenario.behavior_id or "")
    errors: List[str] = []

    if (profile.modules or {}).get("hard_block_no_trade"):
        return OperationalValidity(valid=False, mode="no_trade_monitor", errors=["NO_TRADE_MONITOR_ONLY"])

    if base == 0 and buy_n == 0 and sell_n == 0:
        errors.append("ERROR_NON_OPERATIONAL_PARAMS")
        return OperationalValidity(valid=False, mode="empty", errors=errors)

    if behavior == "PB11" or str(profile.scenario.regime_id or "") == "R8":
        if base > 0 and sell_n >= 1:
            mode = "micro_base_sell_rebuy"
        elif profile.normal_buy_enabled and buy_n >= 1:
            mode = "deep_crash_entry"
        else:
            errors.append("ERROR_PB11_NON_OPERATIONAL")
            mode = "invalid"
        return OperationalValidity(valid=not errors, mode=mode, errors=errors)

    if buy_n >= 1 and sell_n >= 1:
        mode = "bilateral_grid"
    elif sell_n >= 1 and base > 0:
        mode = "sell_management"
    elif buy_n >= 1:
        mode = "deep_buy_only"
    else:
        errors.append("ERROR_NON_OPERATIONAL_PARAMS")
        mode = "invalid"

    if (
        profile.buyback_after_sell_enabled
        or profile.profit_sell_after_buyback_enabled
    ) and sell_n == 0 and buy_n == 0:
        errors.append("ERROR_NON_OPERATIONAL_PARAMS")

    return OperationalValidity(valid=not errors, mode=mode, errors=errors)


def is_profile_operational(profile: V6CatalogProfile) -> bool:
    return assess_operational_validity(profile).valid


def _apply_pb11_mod_a(profile: V6CatalogProfile) -> V6CatalogProfile:
    p = profile.copy()
    if not p.sell_grids:
        p.sell_grids = [GridLevel(8, 100)]
    p.base_allocation_pct = max(int(p.base_allocation_pct or 0), 5)
    p.quote_allocation_pct = 100 - p.base_allocation_pct
    p.normal_buy_enabled = False
    p.buy_grids = []
    p.buyback_after_sell_enabled = True
    p.profit_sell_after_buyback_enabled = True
    p.modules = {
        **(p.modules or {}),
        "initial_base_allocation": True,
        "normal_buy_grid": False,
        "sell_grid": True,
        "profit_buyback_after_sell": True,
        "profit_sell_after_buyback": True,
    }
    return quantize_profile(p)


def _apply_pb11_mod_b(profile: V6CatalogProfile) -> V6CatalogProfile:
    p = profile.copy()
    p.base_allocation_pct = 0
    p.quote_allocation_pct = 100
    p.normal_buy_enabled = True
    p.buy_grids = [GridLevel(-12, 40), GridLevel(-20, 60)]
    if not p.sell_grids:
        p.sell_grids = [GridLevel(8, 60), GridLevel(14, 40)]
    p.buyback_after_sell_enabled = True
    p.profit_sell_after_buyback_enabled = True
    p.modules = {
        **(p.modules or {}),
        "initial_base_allocation": False,
        "normal_buy_grid": True,
        "sell_grid": bool(p.sell_grids),
        "profit_buyback_after_sell": True,
        "profit_sell_after_buyback": True,
    }
    return quantize_profile(p)


def ensure_profile_operational(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """Final repair after adjusters + exchange validator — PB11/R8 must not be empty."""
    from app.services.dynamic_param_score.v6.v6_exchange_validator import exchange_validate

    notes: Dict[str, Any] = {}
    p = profile
    behavior = str(p.scenario.behavior_id or "")
    regime = str(regime_id or "")

    if (p.modules or {}).get("hard_block_no_trade"):
        notes["pb11_operational_mode"] = "no_trade_monitor"
        return p, notes

    if is_profile_operational(p):
        return p, notes

    if behavior == "PB11" or regime == "R8":
        p = _apply_pb11_mod_a(p)
        p, ex_notes = exchange_validate(p, inp)
        if ex_notes:
            notes["exchange_notes_after_mod_a"] = ex_notes
        if is_profile_operational(p):
            notes["pb11_operational_mode"] = "mod_a_micro_base_sell"
            return p, notes

        p = _apply_pb11_mod_b(p)
        p, ex_notes = exchange_validate(p, inp)
        if ex_notes:
            notes["exchange_notes_after_mod_b"] = ex_notes
        if is_profile_operational(p):
            notes["pb11_operational_mode"] = "mod_b_deep_reentry"
            return p, notes

        notes["pb11_operational_mode"] = "technical_block_candidate"
        return p, notes

    buy_n, sell_n = _profile_grid_counts(p)
    if int(p.base_allocation_pct or 0) == 0 and buy_n == 0 and sell_n == 0:
        p = p.copy()
        p.normal_buy_enabled = True
        p.buy_grids = [GridLevel(-8, 50), GridLevel(-12, 50)]
        p, _ = exchange_validate(p, inp)
        notes["non_operational_repair"] = "generic_deep_buy"
    return p, notes


def resolve_v6_apply_policy(
    *,
    deployable: bool,
    params: Optional[BotParams],
    final_action: str,
) -> str:
    has_params = bool(
        params
        and (
            int(params.buy_grid_count or 0) > 0
            or int(params.sell_grid_count or 0) > 0
            or (params.rebuy_enabled and int(params.sell_grid_count or 0) > 0)
        )
    )
    if not has_params:
        return "technical_block"
    if deployable:
        return "deployable"
    fa = str(final_action or "").upper()
    if fa == "SELL_MANAGEMENT_ONLY":
        return "controlled_deploy"
    if fa in ("CONTROLLED_GRID", "ACTIVE_DEFENSIVE_GRID", "DEFENSIVE_GRID"):
        return "controlled_deploy"
    return "high_risk_controlled"


def apply_policy_v6(decision: DynamicParamDecision) -> str:
    """V6 apply policy names (no legacy safe_wait when params exist)."""
    return resolve_v6_apply_policy(
        deployable=bool(decision.deployable),
        params=decision.params,
        final_action=str(decision.final_action or ""),
    )


def apply_policy_label_v6(policy: str) -> str:
    mapping = {
        "deployable": "Uygulanabilir profil",
        "controlled_deploy": "Kontrollü uygulanabilir profil",
        "high_risk_controlled": "Yüksek risk · savunmacı V6 profili üretildi",
        "technical_block": "Parametre üretildi · emir teknik nedenle uygulanamaz",
        "allow": "Uygulanabilir profil",
        "safe_wait": "Yüksek risk · savunmacı V6 profili üretildi",
        "reference_grid": "Kontrollü uygulanabilir profil",
        "no_trade": "İşlem yok · profil referans",
        "sell_management": "Kontrollü uygulanabilir profil",
    }
    return mapping.get(str(policy or ""), "Savunmacı V6 profili üretildi")


def _one_week_grid_penalty(
    regime_id: str,
    vol: str,
    buy1: int,
    sell1: int,
    has_buy: bool,
    has_sell: bool,
) -> Tuple[int, List[str]]:
    """Penalize grids too wide for 1-week reach on low-vol regimes."""
    warnings: List[str] = []
    penalty = 0
    regime = str(regime_id or "R2")
    bands = _ONE_WEEK_GRID_BANDS.get(regime, _ONE_WEEK_GRID_BANDS["R2"])

    if vol in ("V1", "V2") and regime in ("R1", "R2", "R3", "R5", "R6"):
        buy_max = bands["buy"][1]
        sell_max = bands["sell"][1]
        if has_buy and buy1 > buy_max:
            warnings.append("WARN_LOW_ACTIVITY_FOR_1WEEK_BOT")
            penalty += 18
        if has_sell and sell1 > sell_max:
            warnings.append("WARN_LOW_ACTIVITY_FOR_1WEEK_BOT")
            penalty += 12
    elif vol in ("V4", "V5") and regime in ("R2", "R3"):
        if has_buy and buy1 < 8:
            warnings.append("WARN_GRID_TOO_NARROW_FOR_HIGH_VOL")
            penalty += 10

    return penalty, warnings


def compute_workability_score_1w(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    trace: List[Dict[str, Any]],
    regime_id: str,
) -> Tuple[int, List[str]]:
    score = 100
    warnings: List[str] = []
    vol = _trace_class(trace, "volatility")
    frag = _trace_class(trace, "asset_fragility")
    liq = _trace_class(trace, "liquidity")

    buy_n, sell_n = _profile_grid_counts(profile)
    base = int(profile.base_allocation_pct or 0)

    if base == 0 and buy_n == 0 and sell_n == 0:
        return 0, ["ERROR_NON_OPERATIONAL_PARAMS"]
    validity = assess_operational_validity(profile)
    if not validity.valid:
        return 0, list(validity.errors)

    buy1 = abs(profile.buy_grids[0].distance_pct) if profile.buy_grids else 0
    sell1 = profile.sell_grids[0].distance_pct if profile.sell_grids else 0

    if not profile.normal_buy_enabled and sell_n == 0:
        score = min(score, 15)
    if buy_n == 0 and sell_n == 0:
        score = min(score, 15)

    grid_pen, grid_warn = _one_week_grid_penalty(
        regime_id, vol, buy1, sell1, buy_n > 0, sell_n > 0
    )
    score -= grid_pen
    warnings.extend(grid_warn)

    if (
        str(regime_id) in ("R2", "R3")
        and vol in ("V1", "V2")
        and frag in ("F0", "F1")
        and liq in ("L0", "L1")
        and buy_n > 0
        and buy1 >= 8
        and sell_n > 0
        and sell1 >= 6
    ):
        if "WARN_LOW_ACTIVITY_FOR_1WEEK_BOT" not in warnings:
            warnings.append("WARN_LOW_ACTIVITY_FOR_1WEEK_BOT")
        score -= 10

    r6_mode = resolve_r6_mode(inp, trace, regime_id)
    if (
        r6_mode == R6_PROTECTIVE_SELL_ONLY
        and str(inp.symbol or "").upper() in MAJOR_SYMBOLS
        and frag in ("F0", "F1")
        and vol in ("V1", "V2")
        and liq in ("L0", "L1")
    ):
        warnings.append("WARN_OVER_PROTECTED_R6_MAJOR")
        score -= 22

    if str(regime_id) == "R8" and profile.base_allocation_pct > 20:
        score -= 15
    if not profile.sell_grids and profile.scenario.behavior_id != "PB11":
        score -= 30
    if profile.buyback_after_sell_enabled and not profile.profit_sell_after_buyback_enabled:
        score -= 25

    return max(0, min(100, score)), warnings


def build_v6_opportunity_explain(
    symbol: str,
    regime_id: str,
    scenario_label: str,
    profile: V6CatalogProfile,
    trace: List[Dict[str, Any]],
    opportunity_notes: Dict[str, Any],
) -> str:
    sym = str(symbol or "").upper()
    btc = _trace_class(trace, "btc_context")
    r6_mode = str(opportunity_notes.get("r6_mode") or "")
    parts = [
        f"{sym} için {regime_id} {scenario_label or 'senaryo'} tespit edildi.",
    ]
    if btc:
        parts.append(f"BTC bağlamı {btc}.")
    ro = str(opportunity_notes.get("regime_opportunity") or "")
    if ro == R6_CONTROLLED_ACTIVE:
        parts.append(
            "Düşüş sonrası toparlanmada kontrollü aktif mod: derin alış açık, satış ve kâr döngüsü birlikte çalışır."
        )
    elif ro == R6_PROTECTIVE_SELL_ONLY:
        parts.append(
            "Zayıf recovery nedeniyle satış ağırlıklı mod; normal alış kapalı, satış sonrası geri alım aktif."
        )
    elif r6_mode == R6_CONTROLLED_ACTIVE:
        parts.append(
            "Bu profil alış tarafını tamamen kapatmak yerine derin kontrollü alış kullanır; "
            "amaç düşüş sonrası kademeli toparlanmada kontrollü pozisyon kurmaktır."
        )
    elif r6_mode == R6_PROTECTIVE_SELL_ONLY:
        parts.append(
            "Zayıf recovery nedeniyle normal alış kapalı; kontrollü satış ve satış sonrası geri alım döngüsü aktif."
        )
    elif (profile.modules or {}).get("hard_block_no_trade"):
        parts.append(
            "Hard block: yeni alış, satış sonrası geri alım ve kâr döngüsü kapalı; profil izleme modundadır."
        )
    elif profile.scenario.behavior_id == "PB11":
        parts.append(
            "Crash profili: normal alış kapalı, satış ve satış sonrası kar alım / kar satış döngüsü korunur."
        )
    if opportunity_notes.get("r2_contraction_applied"):
        parts.append(
            "Düşük volatilite aralığında gridler 1 haftalık bot için yakınlaştırıldı."
        )
    return " ".join(parts)


def v6_sub_scores_for_display(sub_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Strip V5 fee artifacts; expose risk-oriented score names."""
    out = dict(sub_dict or {})
    out.pop("fee_efficiency_score", None)
    renames = {
        "data_quality_score": "data_quality_risk_score",
        "volatility_score": "volatility_risk_score",
        "liquidity_score": "liquidity_risk_score",
        "btc_market_risk_score": "btc_market_risk_score",
        "asset_fragility_score": "fragility_risk_score",
    }
    for old, new in renames.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
    return out


def grid_summary_label(profile: V6CatalogProfile) -> str:
    buy = "/".join(f"-{abs(g.distance_pct)}" for g in profile.buy_grids) if profile.buy_grids else "kapalı"
    sell = "/".join(f"+{g.distance_pct}" for g in profile.sell_grids) if profile.sell_grids else "kapalı"
    return f"Alış {buy} · Satış {sell}"
