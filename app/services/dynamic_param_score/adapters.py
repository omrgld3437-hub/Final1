"""Convert BotParams to bot config / UI formats."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.models import (
    BotParams,
    DynamicParamDecision,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    RegimeTag,
)
from app.services.dynamic_param_score.safe_overlay import (
    apply_policy_from_decision,
    build_safe_overlay_for_decision,
    management_mode_from_action,
    ui_severity_from_decision,
)

PARAM_ASSISTANT_RESULT_SCHEMA = "3.4"  # 3.4: selection trace counts + fee display contract

_ROUTE_REGIME_TR = {
    "R2": "Dengeli aralık",
    "R3": "Düşük volatilite sıkışma",
    "R4": "Kırılım riski / yüksek volatil momentum",
    "R5": "Geniş chop",
    "R6": "Zayıf düşüş aralığı",
    "R7": "Güçlü düşüş baskısı",
    "R8": "Crash riski",
    "R9": "Zayıf yükseliş",
    "R12": "Oversold toparlanma",
    "R13": "Overbought chop",
    "R14": "BTC baskılı savunmacı alan",
    "R15": "Aşırı pump / blow-off riski",
}

_STRUCTURE_TR = {
    "S2": "alt dip yapısı",
    "S3": "yüksek tepe yapısı",
    "S4": "geniş chop (üst tepe + alt dip)",
    "S6": "mikro düşüş / makro aralık",
    "S8": "makro düşüş / mikro tepki",
}


def _parse_route_parts(route_key: str) -> Dict[str, str]:
    parts = [p.strip() for p in str(route_key or "").split("|") if p.strip()]
    if len(parts) < 5:
        return {}
    return {
        "asset": parts[0],
        "regime": parts[1],
        "structure": parts[2],
        "volatility": parts[3],
        "risk": parts[4],
    }


def build_display_regime_label(
    *,
    regime_tag: str,
    route_key: str = "",
    fallback_route: str = "",
    fallback_used: bool = False,
    risk_state: str = "",
    regime_tag_live: str = "",
    effective_risk_state: str = "",
    regime_code: str = "",
    structure_code: str = "",
    vol_code: str = "",
) -> str:
    """Human-readable regime for UI — prefers final selected route over soft tag."""
    effective = route_key or fallback_route
    parts = _parse_route_parts(effective)
    if not parts and regime_code:
        parts = {
            "regime": regime_code,
            "structure": structure_code,
            "volatility": vol_code,
            "risk": effective_risk_state or risk_state or "NORMAL",
        }
    risk_for_label = effective_risk_state or risk_state
    if not parts:
        from app.services.dynamic_param_score.explain import _REGIME_TR

        live_tag = regime_tag_live or regime_tag
        return _REGIME_TR.get(live_tag, live_tag.replace("_", " ").lower())

    regime_lbl = _ROUTE_REGIME_TR.get(parts.get("regime", ""), parts.get("regime", ""))
    struct_lbl = _STRUCTURE_TR.get(parts.get("structure", ""), "")
    chunks = [regime_lbl]
    if struct_lbl:
        chunks.append(struct_lbl)
    if parts.get("risk") == "DEFENSIVE" or risk_for_label == "DEFENSIVE":
        chunks.append("savunmacı")
    if fallback_used and route_key and fallback_route and route_key != fallback_route:
        chunks.append("fallback raf")
    return " · ".join(chunks)


def build_profile_display_line(
    template_key: str,
    *,
    route_key: str = "",
    fallback_route: str = "",
    fallback_used: bool = False,
) -> str:
    effective = fallback_route if fallback_used and fallback_route else route_key
    parts = _parse_route_parts(effective)
    if parts:
        core = (
            f"DPLV4_{parts['asset']}_{parts['regime']}_{parts['structure']}_"
            f"{parts['volatility']}_{parts['risk']}"
        )
        suffix = ""
        if template_key and template_key not in core:
            tail = template_key.split("_")[-2:]
            suffix = "_" + "_".join(tail) if tail else ""
        return core + suffix
    return template_key

_FEE_BAD_ACTIVE_DEFENSIVE_TEMPLATE = "BALANCED_RANGE_60_69_FEE_BAD_WAIT"
_FEE_BAD_LEGACY_WAIT_SUFFIX = "_FEE_BAD_WAIT"


def _weights_to_display_pct(weights: List[float], decimals: int = 1) -> List[float]:
    """Fractional ladder weights -> display % that sum to exactly 100."""
    if not weights:
        return []
    if len(weights) == 1:
        return [100.0]
    scale = 10**decimals
    total_w = sum(weights) or 1.0
    normed = [w / total_w for w in weights]
    units = [int(round(n * 100 * scale)) for n in normed]
    drift = int(100 * scale) - sum(units)
    if drift and units:
        idx = max(range(len(units)), key=lambda i: units[i])
        units[idx] += drift
    return [u / scale for u in units]


def _grid_rows_from_weights(
    spacing_pct: float,
    weights: List[float],
    *,
    pct_key: str,
    qty_key: str,
    ladder_pcts: Optional[List[float]] = None,
) -> List[Dict[str, float]]:
    qtys = _weights_to_display_pct(weights)
    pcts = ladder_pcts if ladder_pcts and len(ladder_pcts) == len(qtys) else None
    rows: List[Dict[str, float]] = []
    for i, qty in enumerate(qtys):
        if pcts:
            grid_pct = round(float(pcts[i]), 4)
        else:
            grid_pct = round(spacing_pct * (i + 1), 4)
        rows.append({pct_key: grid_pct, qty_key: qty})
    return rows


def _profit_ui_values(
    params: BotParams,
    *,
    sell_trail: float,
    buy_trail: float,
    ui_display: bool,
) -> Tuple[float, float, float, float]:
    """Kar alım / kar satış UI değerleri — grid trailing'den bağımsız."""
    buy_n = int(params.buy_grid_count or 0)
    sell_n = int(params.sell_grid_count or 0)
    rebuy_on = params.rebuy_enabled and buy_n > 0 and not params.buy_disabled
    resell_on = params.resell_enabled and sell_n > 0

    if ui_display:
        rebuy_trigger = (
            float(params.rebuy_trigger_pct)
            if params.rebuy_trigger_pct is not None
            else round(params.buy_grid_spacing_pct * 2, 4) if buy_n > 0 else 0.0
        )
        rebuy_trail = (
            float(params.rebuy_trail_pct)
            if params.rebuy_trail_pct is not None
            else round(buy_trail, 4) if buy_n > 0 else 0.0
        )
        resell_trigger = (
            float(params.resell_trigger_pct)
            if params.resell_trigger_pct is not None
            else round(params.take_profit_pct, 4) if sell_n > 0 else 0.0
        )
        resell_trail = (
            float(params.resell_trail_pct)
            if params.resell_trail_pct is not None
            else round(sell_trail, 4) if sell_n > 0 else 0.0
        )
        return rebuy_trigger, rebuy_trail, resell_trigger, resell_trail

    rebuy_trigger = (
        float(params.rebuy_trigger_pct)
        if params.rebuy_trigger_pct is not None
        else round(params.buy_grid_spacing_pct * 2, 4) if rebuy_on else 0.0
    )
    rebuy_trail = (
        float(params.rebuy_trail_pct)
        if params.rebuy_trail_pct is not None
        else round(buy_trail, 4) if rebuy_on else 0.0
    )
    resell_trigger = (
        float(params.resell_trigger_pct)
        if params.resell_trigger_pct is not None
        else round(params.take_profit_pct, 4) if resell_on else 0.0
    )
    resell_trail = (
        float(params.resell_trail_pct)
        if params.resell_trail_pct is not None
        else round(sell_trail, 4) if resell_on else 0.0
    )
    return rebuy_trigger, rebuy_trail, resell_trigger, resell_trail


def _params_from_dict(raw: Optional[Dict[str, Any]]) -> Optional[BotParams]:
    if not raw:
        return None
    allowed = {f.name for f in fields(BotParams)}
    try:
        return BotParams(**{k: v for k, v in raw.items() if k in allowed})
    except (TypeError, ValueError):
        return None


def _indicator_from_telemetry(tel: Dict[str, Any]) -> IndicatorSnapshot:
    raw = tel.get("indicators") or {}
    allowed = {f.name for f in fields(IndicatorSnapshot)}
    return IndicatorSnapshot(**{k: v for k, v in raw.items() if k in allowed})


def _constraints_from_telemetry(tel: Dict[str, Any]) -> ExchangeConstraints:
    ind = tel.get("indicators") or {}
    friction = float(ind.get("total_friction_pct") or 0.15)
    min_n = float(tel.get("min_notional") or DEFAULT_MIN_NOTIONAL_USDT)
    fee = max(friction / 3.0, 0.04)
    return ExchangeConstraints(
        min_notional=min_n,
        step_size=0.001,
        tick_size=0.01,
        min_qty=0.001,
        taker_fee_pct=fee,
        maker_fee_pct=max(fee * 0.85, 0.03),
        estimated_slippage_pct=max(friction - fee, 0.01),
    )


def _exposure_frac_from_telemetry(tel: Dict[str, Any]) -> float:
    pool = tel.get("param_pool") or {}
    ctx = pool.get("selection_context") or {}
    tier = str(ctx.get("exposure_tier") or "NO_BASE")
    return {
        "NO_BASE": 0.0,
        "LOW_BASE": 0.15,
        "TARGET_BASE": 0.40,
        "HIGH_BASE": 0.55,
        "OVEREXPOSED": 0.75,
    }.get(tier, 0.0)


def _fee_display_from_selection(pool_meta: dict) -> dict:
    """UI-facing fee breakdown — never show %0 when live fee data is missing."""
    ctx = pool_meta.get("selection_context") or {}
    cost = ctx.get("cost_resolution") or {}
    if cost:
        available = bool(cost.get("fee_data_available", True))
        floor = float(cost.get("cost_floor_pct") or cost.get("total_cost_pct") or 1.2)
        return {
            "fee_data_available": available,
            "maker_fee_pct": cost.get("maker_fee_pct"),
            "taker_fee_pct": cost.get("taker_fee_pct"),
            "roundtrip_fee_pct": cost.get("roundtrip_fee_pct"),
            "spread_pct": cost.get("spread_pct"),
            "estimated_slippage_pct": cost.get("estimated_slippage_pct"),
            "rounding_cost_pct": cost.get("rounding_cost_pct"),
            "total_cost_floor_pct": floor,
            "fee_tier": cost.get("fee_tier"),
            "display_note": (
                None
                if available
                else f"Fee verisi yok; güvenli cost floor %{floor:.2f} uygulandı."
            ),
        }
    friction = float(ctx.get("total_friction_pct") or 0)
    if friction > 0.001:
        return {
            "fee_data_available": True,
            "total_cost_floor_pct": friction,
            "display_note": None,
        }
    return {
        "fee_data_available": False,
        "total_cost_floor_pct": 1.2,
        "display_note": "Fee verisi yok; güvenli cost floor %1,20 uygulandı.",
    }


def _reference_display_template_key(decision: DynamicParamDecision) -> Optional[str]:
    """Legacy WAIT paths only — DPS V2 uses deployable ACTIVE_DEFENSIVE grids."""
    tel = decision.telemetry or {}
    pool = tel.get("param_pool") or {}
    ctx = pool.get("selection_context") or {}
    selected = str(pool.get("selected_template_key") or "")
    fa = str(decision.final_action or "")

    if fa in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.ACTIVE_GRID.value,
    ):
        fb = str(pool.get("fallback_reason") or ctx.get("fallback_reason") or "")
        if selected in (
            "FALLBACK_FEE_BAD_ACTIVE_DEFENSIVE",
            "FALLBACK_DEFENSIVE",
            "FALLBACK_DUMP_DEFENSIVE",
        ) or fb == "fee_bad_wide_grid_active":
            return _FEE_BAD_ACTIVE_DEFENSIVE_TEMPLATE
        return None

    if selected.endswith(_FEE_BAD_LEGACY_WAIT_SUFFIX) and fa in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ):
        return _FEE_BAD_ACTIVE_DEFENSIVE_TEMPLATE
    return None


def _resolve_reference_display_params(
    decision: DynamicParamDecision,
    budget: float,
) -> Tuple[Optional[BotParams], Optional[str]]:
    """Render informational grid params when the selected template has no grids."""
    ref_key = _reference_display_template_key(decision)
    if not ref_key:
        return None, None

    from app.services.dynamic_param_score.param_pool.defaults import _pinned_templates
    from app.services.dynamic_param_score.param_pool.renderer import render_template

    pinned = {t.template_key: t for t in _pinned_templates()}
    tmpl = pinned.get(ref_key)
    if tmpl is None:
        return None, None

    tel = decision.telemetry or {}
    ind = _indicator_from_telemetry(tel)
    constraints = _constraints_from_telemetry(tel)
    min_n = float(tel.get("min_notional") or constraints.min_notional or DEFAULT_MIN_NOTIONAL_USDT)
    exposure = _exposure_frac_from_telemetry(tel)
    try:
        regime = RegimeTag(str(decision.regime_tag or RegimeTag.BALANCED_RANGE.value))
    except ValueError:
        regime = RegimeTag.BALANCED_RANGE

    params = render_template(
        tmpl,
        param_score=int(decision.param_score or 50),
        regime=regime,
        ind=ind,
        constraints=constraints,
        current_exposure_frac=exposure,
        budget_usdt=float(budget or 0.0),
        min_notional=min_n,
    )
    if params is None:
        return None, None
    if int(params.buy_grid_count or 0) < 1 and int(params.sell_grid_count or 0) < 1:
        return None, None
    return params, ref_key


def _resolve_recommendation_params(decision: DynamicParamDecision) -> Optional[BotParams]:
    """Best-effort params for UI — post-safety, then pre-safety telemetry."""
    candidates: List[Optional[BotParams]] = [decision.params]
    tel = decision.telemetry or {}
    candidates.append(_params_from_dict(tel.get("post_safety_params")))
    candidates.append(_params_from_dict(tel.get("pre_safety_params")))
    for p in candidates:
        if p is None:
            continue
        if int(p.buy_grid_count or 0) > 0 or int(p.sell_grid_count or 0) > 0:
            return p
    return None


def _build_score_labels(
    decision: DynamicParamDecision,
    sel_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    runtime_safe = bool(sel_ctx.get("runtime_safe_profile_generated"))
    scored = int(sel_ctx.get("scored_candidate_count") or 0)
    profile_score = sel_ctx.get("selected_profile_score")
    labels: Dict[str, Any] = {
        "market_confidence": {
            "label": "Piyasa güven skoru",
            "value": decision.confidence_score,
        },
    }
    if runtime_safe or (scored <= 0 and profile_score in (0, 0.0, None)):
        labels["runtime_safety_score"] = {
            "label": "Runtime güvenlik skoru",
            "value": decision.param_score,
            "note": "Raf profili skorlanamadı; sentetik güvenli profil.",
        }
        labels["route_profile_score"] = {
            "label": "Raf profil skoru",
            "value": 0,
            "note": "Gerçek 300k profil seçilmedi.",
        }
    else:
        labels["param_work_score"] = {
            "label": "Parametre çalışma skoru",
            "value": decision.param_score,
        }
        labels["route_profile_score"] = {
            "label": "Seçilen profil uyum skoru",
            "value": profile_score,
        }
    return labels


def _params_to_param_assistant_ui(
    decision: DynamicParamDecision,
    budget: float,
    params: BotParams,
    *,
    final_action: Optional[str] = None,
    recommendation_only: bool = False,
    reference_display_template_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    fa = str(final_action or decision.final_action or "")
    buy_n = int(params.buy_grid_count or 0)
    sell_n = int(params.sell_grid_count or 0)
    sell_only = params.sell_only_mode or (buy_n == 0 and sell_n > 0)
    if sell_n < 1 and buy_n < 1:
        return None
    if fa == FinalAction.SELL_MANAGEMENT_ONLY.value and sell_n < 1:
        return None

    tel = decision.telemetry or {}
    pool = tel.get("param_pool") or {}
    sel_ctx = pool.get("selection_context") or {}
    target_alloc = tel.get("target_allocation") or {}
    order_plan = tel.get("order_intent_plan") or {}
    rebalance = tel.get("rebalance_plan") or {}
    current_base_frac = float(target_alloc.get("current_base_frac") or 0.0)
    current_base_pct = round(current_base_frac * 100, 2)
    ladder_budget_usdt = float(
        tel.get("buy_ladder_budget_usdt") or order_plan.get("total_buy_quote_usdt") or 0.0
    )
    active_buy_usdt = float(order_plan.get("total_buy_quote_usdt") or ladder_budget_usdt)
    budget_val = max(float(budget or 0.0), 1.0)
    sell_ladder_active = current_base_frac > 0.01 and sell_n > 0 and not sell_only
    sell_ladder_mode = "active" if sell_ladder_active else "planned_inactive"
    min_tr = float(tel.get("min_trailing_callback_pct") or 0.35)
    ui_display = bool(recommendation_only)
    cfg = params_to_grid_config(
        params,
        min_trailing_pct=min_tr,
        final_action=fa,
        pool_version=pool.get("pool_version"),
        ui_display=ui_display,
    )
    up_grids = [
        {"trigger_pct": g["sell_grid_pct"], "qty_pct": g["sell_qty_pct_of_base"]}
        for g in cfg["sell_grids"]
    ]
    down_grids = [
        {"trigger_pct": g["buy_grid_pct"], "qty_pct": g["buy_qty_pct_of_quote"]}
        for g in cfg["buy_grids"]
    ]
    rebuy_trigger, rebuy_trail, resell_trigger, resell_trail = _profit_ui_values(
        params,
        sell_trail=float(cfg["sell_trigger_trailing_pct"] or 0.0),
        buy_trail=float(cfg["buy_trigger_trailing_pct"] or 0.0),
        ui_display=ui_display,
    )
    target_quote_usdt = round(budget_val * float(cfg["quote_alloc_pct"]) / 100.0, 2)
    unused_quote_usdt = round(max(0.0, target_quote_usdt - active_buy_usdt), 2)
    active_buy_risk_pct = round(active_buy_usdt / budget_val * 100, 2)
    sel_tel = decision.selection_telemetry if hasattr(decision, "selection_telemetry") else {}
    if not sel_tel:
        sel_tel = pool
    route_key = str(sel_ctx.get("route_key") or pool.get("route_key") or "")
    fallback_route = str(pool.get("fallback_route") or sel_ctx.get("fallback_route") or "")
    fallback_used = bool(pool.get("fallback_used") or pool.get("route_index_fallback_used"))
    template_key = str(pool.get("selected_template_key") or decision.selected_profile_name or "")
    market_sig = tel.get("market_signature") or {}
    effective_risk = str(
        market_sig.get("risk_class")
        or sel_ctx.get("risk_class")
        or (
            "DEFENSIVE"
            if fa in (FinalAction.ACTIVE_DEFENSIVE_GRID.value, FinalAction.DEFENSIVE_GRID.value)
            else decision.risk_state
        )
        or decision.risk_state
        or "NORMAL"
    )
    display_regime_label = build_display_regime_label(
        regime_tag=str(market_sig.get("regime_tag_live") or decision.regime_tag or ""),
        route_key=route_key,
        fallback_route=fallback_route,
        fallback_used=fallback_used,
        risk_state=str(decision.risk_state or ""),
        regime_tag_live=str(market_sig.get("regime_tag_live") or ""),
        effective_risk_state=effective_risk,
        regime_code=str(market_sig.get("regime_code") or ""),
        structure_code=str(market_sig.get("structure_code") or ""),
        vol_code=str(market_sig.get("vol_code") or ""),
    )
    profile_display = build_profile_display_line(
        template_key,
        route_key=route_key,
        fallback_route=fallback_route,
        fallback_used=fallback_used,
    )
    ui_payload: Dict[str, Any] = {
        "symbol": decision.symbol,
        "budget_usd": round(budget, 2),
        "base_alloc_pct": cfg["base_alloc_pct"],
        "quote_alloc_pct": cfg["quote_alloc_pct"],
        "up": {
            "grids": up_grids,
            "trail_pct": cfg["sell_trigger_trailing_pct"],
            "enabled": cfg["sell_trailing_enabled"],
        },
        "down": {
            "grids": down_grids,
            "trail_pct": cfg["buy_trigger_trailing_pct"],
            "enabled": cfg["buy_trailing_enabled"],
        },
        "profit": {
            "rebuy_trigger_pct": rebuy_trigger,
            "rebuy_trail_pct": rebuy_trail,
            "resell_trigger_pct": resell_trigger,
            "resell_trail_pct": resell_trail,
            "rebuy_enabled": cfg["rebuy_enabled"],
            "resell_enabled": cfg.get("resell_enabled", True),
            "basis_mode": "grid_only",
        },
        "max_buy_levels": cfg.get("max_buy_levels"),
        "min_net_profit_rate": cfg.get("min_net_profit_rate"),
        "dps_decision_id": decision.decision_id,
        "param_score": decision.param_score,
        "regime_tag": decision.regime_tag,
        "display_regime_label": display_regime_label,
        "effective_route_key": fallback_route if fallback_used and fallback_route else route_key,
        "profile_display": profile_display,
        "risk_state": decision.risk_state,
        "effective_risk_state": effective_risk,
        "final_action": fa,
        "management_mode": cfg.get("management_mode"),
        "action_detail": decision.action_detail,
        "selected_profile": decision.selected_profile_name,
        "post_safety_action": decision.final_action,
        "recommendation_only": recommendation_only,
        "sell_management_only": sell_only,
        "buy_disabled": cfg.get("buy_disabled", buy_n == 0),
        "allocation_display": {
            "strategic_target": {
                "base_pct": cfg["base_alloc_pct"],
                "quote_pct": cfg["quote_alloc_pct"],
            },
            "target_quote_usdt": target_quote_usdt,
            "active_buy_ladder_usdt": round(active_buy_usdt, 2),
            "active_buy_risk_pct": active_buy_risk_pct,
            "unused_quote_usdt": unused_quote_usdt,
            "buy_ladder_budget_usdt": round(ladder_budget_usdt, 2),
            "current_base_pct": current_base_pct,
            "rebalance_allowed": not bool(rebalance.get("blocked", True)),
        },
        "ladder_display": {
            "active_buy_ladder": down_grids if buy_n > 0 and not cfg.get("buy_disabled") else [],
            "active_sell_ladder": up_grids if sell_ladder_active else [],
            "planned_sell_ladder": up_grids if not sell_ladder_active and sell_n > 0 else [],
            "sell_ladder_mode": sell_ladder_mode,
        },
        "score_labels": _build_score_labels(decision, sel_ctx),
        "volatility_display": {
            "raw_vol_percentile": market_sig.get("volatility_percentile"),
            "composite_vol_score": market_sig.get("volatility_score"),
            "selected_volatility_tier": market_sig.get("vol_code"),
            "tier_reason": market_sig.get("vol_tier_reason")
            or market_sig.get("volatility_tier_reason"),
        },
        "runtime_safe_profile": bool(sel_ctx.get("runtime_safe_profile_generated")),
        "coverage_gap": sel_ctx.get("coverage_gap"),
        "defensive_fallback_overlay": sel_ctx.get("defensive_fallback_overlay"),
    }
    if reference_display_template_key:
        ui_payload["reference_display_template_key"] = reference_display_template_key
        ui_payload["reference_display_only"] = True
        ui_payload["reference_display_reason"] = "legacy_fee_bad_wait_reference"
    return ui_payload


def decision_to_recommendation_config(
    decision: DynamicParamDecision, budget: float
) -> Optional[Dict[str, Any]]:
    """UI config for Param Assistant — shows best pool params even when not deployable."""
    reference_key: Optional[str] = None
    params = _resolve_recommendation_params(decision)
    if params is None:
        params, reference_key = _resolve_reference_display_params(decision, budget)
    if params is None:
        return None
    pool_meta = (decision.telemetry or {}).get("param_pool") or {}
    pool_action = pool_meta.get("final_action") or decision.final_action
    return _params_to_param_assistant_ui(
        decision,
        budget,
        params,
        final_action=pool_action,
        recommendation_only=not decision.deployable,
        reference_display_template_key=reference_key,
    )


def decision_to_ui_config(decision: DynamicParamDecision, budget: float) -> Optional[Dict[str, Any]]:
    """Param Assistant UI schema (compatible with create-modal)."""
    if not decision.deployable or not decision.params:
        return None
    fa = decision.final_action
    p = decision.params
    if fa == FinalAction.SELL_MANAGEMENT_ONLY.value:
        if p.sell_grid_count < 1:
            return None
    elif fa == FinalAction.ACTIVE_DEFENSIVE_GRID.value:
        if p.buy_grid_count < 1 and p.sell_grid_count < 1:
            return None
    elif p.buy_grid_count < 1 or p.sell_grid_count < 1:
        return None
    return _params_to_param_assistant_ui(decision, budget, p, final_action=fa, recommendation_only=False)


def params_to_grid_config(
    params: BotParams,
    *,
    min_trailing_pct: float = 0.35,
    final_action: Optional[str] = None,
    pool_version: Optional[str] = None,
    ui_display: bool = False,
) -> Dict[str, Any]:
    """Map BotParams to DcaGridTrailingConfig overlay dict (pct 0-100)."""
    buy_grids = _grid_rows_from_weights(
        params.buy_grid_spacing_pct,
        params.buy_qty_distribution,
        pct_key="buy_grid_pct",
        qty_key="buy_qty_pct_of_quote",
        ladder_pcts=params.buy_grid_ladder_pcts,
    )
    sell_grids = _grid_rows_from_weights(
        params.sell_grid_spacing_pct,
        params.sell_qty_distribution,
        pct_key="sell_grid_pct",
        qty_key="sell_qty_pct_of_base",
        ladder_pcts=params.sell_grid_ladder_pcts,
    )

    sell_only = params.sell_only_mode or (
        params.buy_grid_count == 0 and params.sell_grid_count > 0
    )
    buy_disabled = params.buy_disabled or params.buy_grid_count == 0 or params.emergency_no_buy
    min_tr = max(float(min_trailing_pct or 0.0), 0.0)

    from app.services.dynamic_param_score.param_generator.grid_distribution import cap_trailing_pct

    if params.trailing_enabled:
        sell_trail = max(float(params.trailing_callback_pct or 0.0), min_tr)
    elif params.sell_grid_count > 0:
        sell_trail = max(float(params.trailing_callback_pct or 0.0), min_tr)
    else:
        sell_trail = 0.0
    if sell_grids:
        sell_trail = max(cap_trailing_pct(sell_trail, float(sell_grids[0]["sell_grid_pct"])), min_tr)

    buy_trail_blocked = sell_only or (buy_disabled and not ui_display)
    if buy_trail_blocked:
        buy_trail = 0.0
    elif params.trailing_enabled or params.buy_grid_count > 0:
        buy_trail = max(float(params.trailing_callback_pct or 0.0) * 0.8, min_tr * 0.8)
    else:
        buy_trail = 0.0
    if buy_grids and not buy_trail_blocked:
        buy_trail = max(
            cap_trailing_pct(buy_trail, float(buy_grids[0]["buy_grid_pct"])),
            min_tr * 0.8,
        )

    rebuy_enabled = params.rebuy_enabled and params.buy_grid_count > 0 and not buy_disabled

    rebuy_trigger = (
        float(params.rebuy_trigger_pct)
        if params.rebuy_trigger_pct is not None
        else round(params.buy_grid_spacing_pct * 2, 4) if rebuy_enabled else 0.0
    )
    rebuy_trail_val = (
        float(params.rebuy_trail_pct)
        if params.rebuy_trail_pct is not None
        else round(buy_trail, 4) if rebuy_enabled else 0.0
    )
    resell_trigger = (
        float(params.resell_trigger_pct)
        if params.resell_trigger_pct is not None
        else round(params.take_profit_pct, 4) if params.sell_grid_count > 0 else 0.0
    )
    resell_trail_val = (
        float(params.resell_trail_pct)
        if params.resell_trail_pct is not None
        else round(sell_trail, 4) if params.sell_grid_count > 0 else 0.0
    )

    fa = final_action or params.management_mode or ""
    mm = params.management_mode or management_mode_from_action(str(fa))

    return {
        "base_alloc_pct": round(params.base_alloc_frac * 100.0, 2),
        "quote_alloc_pct": round(params.quote_alloc_frac * 100.0, 2),
        "sell_grids": sell_grids,
        "buy_grids": buy_grids,
        "sell_trigger_trailing_pct": round(sell_trail, 4),
        "buy_trigger_trailing_pct": round(buy_trail, 4),
        "profit_exit_rise_pct": round(params.take_profit_pct, 4),
        "profit_exit_drop_pct": round(sell_trail, 4),
        "profit_reentry_drop_pct": round(rebuy_trigger, 4) if rebuy_enabled else 0.0,
        "profit_reentry_rise_pct": round(rebuy_trail_val, 4) if rebuy_enabled else 0.0,
        "max_buy_levels": max(params.buy_grid_count, 0),
        "min_net_profit_rate": round(params.min_cycle_profit_after_fee_pct / 100.0, 6),
        "max_base_exposure_frac": round(params.max_base_exposure_frac, 4),
        "rebuy_enabled": rebuy_enabled,
        "resell_enabled": params.resell_enabled,
        "buy_disabled": buy_disabled,
        "sell_only_mode": sell_only,
        "cancel_existing_buy_orders": params.cancel_existing_buy_orders,
        "cancel_existing_sell_orders": params.cancel_existing_sell_orders,
        "selected_template_key": params.selected_template_key,
        "pool_version": pool_version or params.pool_version,
        "final_action": fa,
        "management_mode": mm,
        "buy_trailing_enabled": params.buy_grid_count > 0 and buy_trail > 0 and not buy_disabled,
        "sell_trailing_enabled": params.sell_grid_count > 0 and sell_trail > 0,
        "_dps_meta": {
            "emergency_no_buy": params.emergency_no_buy,
            "max_base_exposure_frac": params.max_base_exposure_frac,
            "cancel_existing_buy_orders": params.cancel_existing_buy_orders,
            "reason_code": params.reason_code,
            "sell_management_only": sell_only,
            "buy_disabled": buy_disabled,
            "management_mode": mm,
        },
    }


def _is_management_decision(decision: DynamicParamDecision) -> bool:
    """True only when there is no grid recommendation to show."""
    if _resolve_recommendation_params(decision) is not None:
        return False
    fa = str(decision.final_action or "")
    if fa in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.NO_TRADE.value,
        FinalAction.SAFE_WAIT.value,
        "DATA_STALE_SAFE_WAIT",
    ) and _reference_display_template_key(decision):
        return False
    return fa in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.NO_TRADE.value,
        FinalAction.SAFE_WAIT.value,
        "DATA_STALE_SAFE_WAIT",
    )


def decision_to_param_assistant_result(
    decision: DynamicParamDecision, budget: float, symbol: str
) -> Dict[str, Any]:
    """Adapter for legacy param-assistant response shape."""
    ui_config = decision_to_ui_config(decision, budget)
    recommendation_config = decision_to_recommendation_config(decision, budget)
    display_config = ui_config or recommendation_config
    has_ui = display_config is not None
    up_n = len((display_config or {}).get("up", {}).get("grids", []) or [])
    down_n = len((display_config or {}).get("down", {}).get("grids", []) or [])
    deploy = bool(decision.deployable and ui_config is not None)
    fa = decision.final_action
    management = _is_management_decision(decision)
    mm = management_mode_from_action(fa)
    apply_policy = apply_policy_from_decision(fa, deployable=deploy)
    safe_overlay = None
    can_apply_safe_overlay = False

    if management and not deploy:
        safe_overlay = build_safe_overlay_for_decision(decision)
        can_apply_safe_overlay = True
        apply_policy = apply_policy_from_decision(fa, deployable=False)
        decision_label = "management_decision"
    elif has_ui and not deploy:
        decision_label = "recommended_grid"
    elif not deploy or not has_ui:
        decision_label = "management_decision" if management else "abstain"
        if management:
            safe_overlay = build_safe_overlay_for_decision(decision)
            can_apply_safe_overlay = True
    elif fa == FinalAction.SELL_MANAGEMENT_ONLY.value:
        decision_label = "deploy"
    else:
        decision_label = "deploy"

    sub = decision.telemetry.get("sub_scores", {})
    pool_meta = decision.telemetry.get("param_pool") or {}
    diag = pool_meta.get("diagnostics") or {}
    data_window = decision.telemetry.get("data_window") or {}
    market_sig = decision.telemetry.get("market_signature") or {}
    effective_risk = str(
        market_sig.get("risk_class")
        or (
            "DEFENSIVE"
            if fa in (FinalAction.ACTIVE_DEFENSIVE_GRID.value, FinalAction.DEFENSIVE_GRID.value)
            else decision.risk_state
        )
        or decision.risk_state
        or "NORMAL"
    )
    display_regime = (display_config or {}).get("display_regime_label") or ""

    feas_meta = {
        k: decision.telemetry.get(k)
        for k in (
            "distribution_invalid",
            "deploy_blocked_reason",
            "exposure_hard_cap_breach",
            "first_start_buy_only",
            "single_probe_only",
            "worst_case_base_exposure_frac",
            "max_base_exposure_frac",
        )
        if decision.telemetry.get(k) is not None
    }
    sel_ctx = pool_meta.get("selection_context") or {}
    profile_source = str(sel_ctx.get("profile_source") or "")
    if sel_ctx.get("runtime_safe_profile_generated"):
        profile_source = "runtime_synthetic"

    from app.services.dynamic_param_score.models import BotContext
    from app.services.dynamic_param_score.result_type import resolve_result_type

    bot_ctx = BotContext(
        run_source=decision.run_source,
        budget_usdt=float(budget or 0.0),
        is_first_start=bool(decision.telemetry.get("is_first_start")),
        first_start_buy_only=bool(
            feas_meta.get("first_start_buy_only")
            or decision.telemetry.get("first_start_buy_only")
        ),
    )
    result_type = resolve_result_type(
        deployable=deploy,
        final_action=fa,
        params=decision.params,
        feasibility_meta=feas_meta,
        bot_context=bot_ctx,
        blocking_reasons=decision.blocking_reasons,
        has_recommendation_ui=has_ui,
        profile_source=profile_source,
    )
    if profile_source == "runtime_synthetic" and has_ui and not deploy:
        result_type = "recommended_grid"

    return {
        "ok": True,
        "result_schema_version": PARAM_ASSISTANT_RESULT_SCHEMA,
        "result_type": result_type,
        "engine": "dynamic_param_score",
        "decision_id": decision.decision_id,
        "created_at": decision.timestamp,
        "run_source": decision.run_source,
        "ui_config": display_config,
        "recommendation_config": recommendation_config,
        "safe_overlay": safe_overlay,
        "decision": decision_label,
        "final_recommendation": decision_label,
        "deployable": decision.deployable,
        "can_apply_safe_overlay": can_apply_safe_overlay,
        "management_mode": mm,
        "apply_policy": apply_policy,
        "ui_severity": ui_severity_from_decision(fa, ok=True),
        "trade_opens_new_position": deploy and fa not in (
            FinalAction.SELL_MANAGEMENT_ONLY.value,
            FinalAction.WAIT.value,
            FinalAction.WAIT_SAFETY.value,
            FinalAction.NO_TRADE.value,
        ),
        "param_score": decision.param_score,
        "confidence": decision.confidence_score,
        "regime_tag": decision.regime_tag,
        "display_regime_label": display_regime,
        "risk_state": decision.risk_state,
        "effective_risk_state": effective_risk,
        "final_action": fa,
        "final_action_label": _action_label_tr(fa),
        "selected_profile": decision.selected_profile_name,
        "post_safety_action": fa,
        "action_detail": decision.action_detail,
        "blocking_reasons": decision.blocking_reasons,
        "warnings": decision.warnings,
        "rationale": {
            "lines": [],
            "sub_scores": sub,
        },
        "explain": decision.explain,
        "telemetry": decision.telemetry,
        "params": decision.params.to_dict() if decision.params else None,
        "selection_telemetry": {
            "selected_template_key": pool_meta.get("selected_template_key"),
            "pool_version": pool_meta.get("pool_version"),
            "profile_subfamily": pool_meta.get("profile_subfamily"),
            "route_key": (pool_meta.get("selection_context") or {}).get("route_key"),
            "scenario": (pool_meta.get("selection_context") or {}).get("market_signature", {}).get("scenario"),
            "selection_path": (pool_meta.get("selection_context") or {}).get("selection_path"),
            "selection_reason": (
                (pool_meta.get("selection_context") or {}).get("selection_reason")
                or (pool_meta.get("selection_context") or {}).get("reason")
            ),
            "exact_route_candidate_count": (pool_meta.get("selection_context") or {}).get(
                "exact_route_candidate_count"
            ),
            "fallback_route": (pool_meta.get("selection_context") or {}).get("fallback_route"),
            "fallback_candidate_count": (pool_meta.get("selection_context") or {}).get(
                "fallback_candidate_count"
            ),
            "route_index_fallback_used": (pool_meta.get("selection_context") or {}).get(
                "route_index_fallback_used"
            ),
            "scored_candidate_count": (
                (pool_meta.get("selection_context") or {}).get("scored_candidate_count")
                if (pool_meta.get("selection_context") or {}).get("scored_candidate_count") is not None
                else pool_meta.get("candidate_count")
            ),
            "selected_profile_score": (pool_meta.get("selection_context") or {}).get(
                "selected_profile_score"
            ),
            "hard_reject_count": (pool_meta.get("selection_context") or {}).get("hard_reject_count"),
            "runtime_safe_profile_generated": (pool_meta.get("selection_context") or {}).get(
                "runtime_safe_profile_generated"
            ),
            "capacity_resolution": (pool_meta.get("selection_context") or {}).get("capacity_resolution"),
            "cost_resolution": (pool_meta.get("selection_context") or {}).get("cost_resolution"),
            "fee_display": _fee_display_from_selection(pool_meta),
            "structure_fit": (pool_meta.get("selection_context") or {}).get("structure_fit"),
            "grid_direction_fit": (pool_meta.get("selection_context") or {}).get("grid_direction_fit"),
            "base_quote_fit": (pool_meta.get("selection_context") or {}).get("base_quote_fit"),
            "fallback_used": pool_meta.get("fallback_used"),
            "fallback_reason": pool_meta.get("fallback_reason"),
            "coverage_gap": (pool_meta.get("selection_context") or {}).get("coverage_gap"),
            "defensive_fallback_overlay": (pool_meta.get("selection_context") or {}).get(
                "defensive_fallback_overlay"
            ),
            "score_labels": {
                "market_confidence": {
                    "label": "Piyasa güven skoru",
                    "value": decision.confidence_score,
                },
                "param_work_score": {
                    "label": "Parametre çalışma skoru",
                    "value": decision.param_score,
                },
                "profile_fit_score": {
                    "label": "Seçilen profil uyum skoru",
                    "value": (pool_meta.get("selection_context") or {}).get(
                        "selected_profile_score"
                    ),
                },
            },
            "candidate_count": (
                (pool_meta.get("selection_context") or {}).get("scored_candidate_count")
                if (pool_meta.get("selection_context") or {}).get("scored_candidate_count") is not None
                else pool_meta.get("candidate_count")
            ),
            "candidate_count_after_filters": (
                (pool_meta.get("selection_context") or {}).get("scored_candidate_count")
                if (pool_meta.get("selection_context") or {}).get("scored_candidate_count") is not None
                else pool_meta.get("candidate_count")
            ),
            "active_template_count": (
                (pool_meta.get("selection_context") or {}).get("active_template_count")
                or diag.get("active_template_count")
                or pool_meta.get("active_template_count")
            ),
            "templates_scanned": (
                (pool_meta.get("selection_context") or {}).get("templates_scanned")
                or diag.get("templates_scanned")
            ),
            "unique_rejected_templates": pool_meta.get("unique_rejected_templates")
            if pool_meta.get("unique_rejected_templates") is not None
            else len((pool_meta.get("reject_examples") or [])),
            "reject_events_total": pool_meta.get("reject_events_total"),
            "filter_summary": pool_meta.get("filter_summary"),
            "selection_context": pool_meta.get("selection_context"),
            "rebalance_plan": (decision.telemetry or {}).get("rebalance_plan"),
            "order_intent_plan": (decision.telemetry or {}).get("order_intent_plan"),
            "intent_execution_enabled": (decision.telemetry or {}).get(
                "intent_execution_enabled", False
            ),
            "data_window": data_window,
        },
        "symbol": symbol,
        "budget": budget,
        "sell_management_only": bool(
            has_ui
            and (
                fa == FinalAction.SELL_MANAGEMENT_ONLY.value
                or (display_config or {}).get("sell_management_only")
            )
        ),
        "grid_summary": (
            f"Alış {down_n} · Satış {up_n}"
            if has_ui
            else None
        ),
    }


def _action_label_tr(action: str) -> str:
    labels = {
        FinalAction.NO_TRADE.value: "İşlem yok",
        FinalAction.WAIT.value: "Bekle",
        FinalAction.WAIT_SAFETY.value: "Güvenlik bekle",
        FinalAction.SAFE_WAIT.value: "Güvenli bekle",
        FinalAction.SELL_MANAGEMENT_ONLY.value: "Sadece satış yönetimi",
        FinalAction.RECOVERY_SELL.value: "Toparlanma satışı",
        FinalAction.DEFENSIVE_GRID.value: "Savunmacı grid",
        FinalAction.BALANCED_GRID.value: "Dengeli grid",
        FinalAction.LOW_FEE_WIDE_GRID.value: "Düşük fee geniş grid",
        FinalAction.ACTIVE_DEFENSIVE_GRID.value: "Aktif savunmacı grid",
        FinalAction.ACTIVE_GRID.value: "Aktif grid",
        FinalAction.TREND_TRAILING.value: "Trend trailing",
        FinalAction.INITIAL_ENTRY.value: "İlk giriş",
    }
    return labels.get(action, action)
