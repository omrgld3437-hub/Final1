"""V5 UI trace consistency audits."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.v5.audit.violations import V5AuditViolation
from app.services.dynamic_param_score.v5.domain.route_key import parse_route_key
from app.services.dynamic_param_score.v5.ui_trace import (
    RISK_LABELS,
    build_pattern_phrase,
    canonical_semantic_for_route,
    compact_route_codes,
    estimate_worst_exposure_pct,
    phrase_means_down_weak_range,
    risk_label_from_route,
    shelf_suffix_from_parts,
)


def audit_trace_consistency(rendered_output: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    route_key = str(rendered_output.get("route_key") or "")
    profile_id = str(rendered_output.get("profile_id") or rendered_output.get("shelf_id") or "")
    if not route_key:
        return violations
    try:
        route = parse_route_key(route_key)
    except (ValueError, KeyError):
        return violations

    ui_risk = rendered_output.get("ui_risk_label")
    explanation_risk = rendered_output.get("explanation_risk_label")
    codes = compact_route_codes(route)
    expected_risk = RISK_LABELS.get(codes["risk"], codes["risk"])

    if ui_risk and ui_risk != expected_risk:
        violations.append(
            V5AuditViolation(
                severity="BLOCKER",
                code="UI_RISK_ROUTE_MISMATCH",
                message="UI risk label does not match V5 route risk posture",
                route_key=route_key,
                shelf_id=profile_id,
                expected=expected_risk,
                actual=ui_risk,
                repairable=True,
                repair_action="derive_ui_risk_from_route_risk_posture",
            )
        )
    if explanation_risk and explanation_risk != expected_risk:
        violations.append(
            V5AuditViolation(
                severity="BLOCKER",
                code="EXPLANATION_RISK_ROUTE_MISMATCH",
                message="Explanation risk label does not match V5 route risk posture",
                route_key=route_key,
                shelf_id=profile_id,
                expected=expected_risk,
                actual=explanation_risk,
                repairable=True,
                repair_action="derive_explanation_risk_from_route_risk_posture",
            )
        )
    suffix = shelf_suffix_from_parts(route)
    if profile_id and not profile_id.endswith(suffix):
        violations.append(
            V5AuditViolation(
                severity="BLOCKER",
                code="PROFILE_ID_ROUTE_MISMATCH",
                message="Profile ID does not match selected route key",
                route_key=route_key,
                shelf_id=profile_id,
                expected=suffix,
                actual=profile_id,
                repairable=False,
            )
        )
    return violations


def audit_regime_route_semantics(classifier_output: dict, route_key: str) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    if not route_key:
        return violations
    try:
        route = parse_route_key(route_key)
    except (ValueError, KeyError):
        return violations
    ui_phrase = str(classifier_output.get("market_regime_text") or classifier_output.get("display_regime_label") or "")
    route_semantic = canonical_semantic_for_route(route_key)
    codes = compact_route_codes(route)
    if phrase_means_down_weak_range(ui_phrase):
        if codes["direction"] == "D1" and codes["structure"] == "S4":
            violations.append(
                V5AuditViolation(
                    severity="CRITICAL",
                    code="REGIME_TEXT_CONFLICTS_WITH_ROUTE_DIRECTION_STRUCTURE",
                    message="UI regime text says weak/down/range but route says up-bias/higher-highs",
                    route_key=route_key,
                    expected=route_semantic,
                    actual=ui_phrase,
                    repairable=True,
                    repair_action="rebuild_market_regime_text_from_route_plus_indicators",
                )
            )
    return violations


def audit_pattern_phrase(indicators: dict, rendered_output: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    higher_highs = indicators.get("higher_highs") is True
    lower_lows = indicators.get("lower_lows") is True
    phrase = str(rendered_output.get("pattern_phrase") or "")
    pl = phrase.lower()
    if "alt dip" in pl and not lower_lows:
        violations.append(
            V5AuditViolation(
                severity="MAJOR",
                code="PATTERN_PHRASE_FALSE_LOWER_LOWS",
                message="UI mentions lower lows although indicator says lower_lows=False",
                expected=False,
                actual=phrase,
                repairable=True,
                repair_action="generate_pattern_phrase_from_boolean_flags",
            )
        )
    if "üst tepe" in pl and not higher_highs:
        violations.append(
            V5AuditViolation(
                severity="MAJOR",
                code="PATTERN_PHRASE_FALSE_HIGHER_HIGHS",
                message="UI mentions higher highs although indicator says higher_highs=False",
                expected=False,
                actual=phrase,
                repairable=True,
                repair_action="generate_pattern_phrase_from_boolean_flags",
            )
        )
    return violations


def audit_exposure_final(param: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    target_base = float(param.get("target_base_pct") or 0)
    worst_exposure = float(param.get("worst_exposure_pct") or 0)
    max_exposure = float(param.get("max_base_exposure_pct") or 0)
    live_applicable = bool(param.get("live_applicable", True))
    if not live_applicable:
        return violations
    if worst_exposure > max_exposure + 0.01:
        violations.append(
            V5AuditViolation(
                severity="BLOCKER" if live_applicable else "CRITICAL",
                code="WORST_EXPOSURE_EXCEEDS_MAX",
                message="Worst exposure exceeds max base exposure",
                expected=f"<= {max_exposure}",
                actual=worst_exposure,
                repairable=True,
                repair_action="clamp_target_base_and_buy_ladder_to_max_exposure",
            )
        )
    if target_base > max_exposure + 0.01:
        violations.append(
            V5AuditViolation(
                severity="CRITICAL",
                code="TARGET_BASE_EXCEEDS_MAX_EXPOSURE",
                message="Target base exceeds max exposure",
                expected=f"<= {max_exposure}",
                actual=target_base,
                repairable=True,
                repair_action="clamp_target_base_pct_to_max_exposure",
            )
        )
    return violations


def audit_min_notional(param: dict, input_ctx: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    min_notional = float(input_ctx.get("min_notional_usdt") or 10)
    active_buy_budget = float(param.get("active_buy_ladder_budget_usdt") or 0)
    buy_levels = param.get("buy_grid_levels_pct") or []
    live_applicable = bool(param.get("live_applicable", True)) and bool(param.get("buy_orders_active", True))
    if not live_applicable:
        return violations
    if active_buy_budget > 0 and active_buy_budget < min_notional:
        violations.append(
            V5AuditViolation(
                severity="BLOCKER" if live_applicable else "CRITICAL",
                code="ACTIVE_BUY_LADDER_BELOW_MIN_NOTIONAL",
                message="Total active buy ladder budget is below exchange min-notional",
                expected=f">= {min_notional} or 0",
                actual=active_buy_budget,
                repairable=True,
                repair_action="disable_active_buys_or_raise_budget_to_min_notional_if_allowed",
            )
        )
    if active_buy_budget > 0 and buy_levels:
        dist = param.get("buy_distribution_pct") or [100 / len(buy_levels)] * len(buy_levels)
        total = sum(dist) or 100
        for i, share in enumerate(dist):
            order_size = active_buy_budget * (float(share) / total)
            if order_size < min_notional:
                violations.append(
                    V5AuditViolation(
                        severity="BLOCKER" if live_applicable else "CRITICAL",
                        code="BUY_ORDER_BELOW_MIN_NOTIONAL",
                        message=f"Buy grid order #{i + 1} below min-notional",
                        expected=f">= {min_notional}",
                        actual=round(order_size, 2),
                        repairable=True,
                        repair_action="reduce_grid_count_or_disable_buys",
                    )
                )
    return violations


def audit_safety_gate(rendered: dict, ctx: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    confidence = rendered.get("confidence")
    fee_missing = bool(ctx.get("fee_missing", False))
    btc_risk = float(ctx.get("btc_market_risk") or 0)
    volume_consistency = float(ctx.get("volume_consistency") or 1)
    safety_result = str(rendered.get("safety_result") or "")
    must_be_reference = (
        (confidence is not None and confidence < 30)
        or fee_missing
        or btc_risk >= 70
        or volume_consistency < 0.35
    )
    if must_be_reference and safety_result in (
        "Dengeli grid",
        "Aktif grid",
        "Aktif savunmacı grid",
        "Savunmacı grid",
    ):
        violations.append(
            V5AuditViolation(
                severity="CRITICAL",
                code="LOW_CONFIDENCE_ACTIVE_SAFETY_LABEL",
                message="Low confidence or missing fee data should not be labeled as active/balanced grid",
                expected="Referans/Bekle/Düşük güven",
                actual=safety_result,
                repairable=True,
                repair_action="derive_safety_result_from_gate_state",
            )
        )
    return violations


def audit_score_placeholders(rendered_text: str) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    if "risk skoru /100" in rendered_text or "fırsat skoru /100" in rendered_text:
        violations.append(
            V5AuditViolation(
                severity="MAJOR",
                code="EMPTY_RISK_OPPORTUNITY_SCORE_PLACEHOLDER",
                message="Risk/opportunity score placeholder rendered without numeric values",
                expected="risk skoru NN/100, fırsat skoru NN/100 or omit phrase",
                actual="risk skoru /100, fırsat skoru /100",
                repairable=True,
                repair_action="render_scores_only_when_numeric",
            )
        )
    return violations


def audit_grid_summary(param: dict, rendered: dict) -> List[V5AuditViolation]:
    violations: List[V5AuditViolation] = []
    buy_levels = param.get("buy_grid_levels_pct") or []
    sell_levels = param.get("sell_grid_levels_pct") or []
    if not buy_levels or not sell_levels:
        return violations
    summary_buy = rendered.get("grid_summary_buy_pct")
    summary_sell = rendered.get("grid_summary_sell_pct")
    final_buy_first = abs(float(buy_levels[0]))
    final_sell_first = abs(float(sell_levels[0]))
    if summary_buy is not None and abs(float(summary_buy) - final_buy_first) > 0.05:
        violations.append(
            V5AuditViolation(
                severity="MAJOR",
                code="GRID_SUMMARY_BUY_MISMATCH",
                message="Grid summary buy pct does not match final buy first grid",
                expected=final_buy_first,
                actual=summary_buy,
                repairable=True,
                repair_action="render_final_grid_first_or_label_as_base_grid",
            )
        )
    if summary_sell is not None and abs(float(summary_sell) - final_sell_first) > 0.05:
        violations.append(
            V5AuditViolation(
                severity="MAJOR",
                code="GRID_SUMMARY_SELL_MISMATCH",
                message="Grid summary sell pct does not match final sell first grid",
                expected=final_sell_first,
                actual=summary_sell,
                repairable=True,
                repair_action="render_final_grid_first_or_label_as_base_grid",
            )
        )
    return violations


def build_rendered_trace_from_result(result: dict) -> dict:
    """Normalize param-assistant API result into audit-friendly trace dict."""
    sel = result.get("selection_telemetry") or {}
    ctx = sel.get("selection_context") or {}
    route_key = str(ctx.get("route_key") or ctx.get("v5_route_key") or sel.get("route_key") or "")
    ui_cfg = result.get("ui_config") or {}
    tel = result.get("telemetry") or {}
    feas = {k: tel.get(k) for k in tel if k.startswith("worst") or k.endswith("_frac")}
    params = result.get("params") or {}
    budget = float(result.get("budget") or ui_cfg.get("budget_usd") or 500)
    alloc = ui_cfg.get("allocation_display") or {}
    active_buy = float(alloc.get("active_buy_ladder_usdt") or tel.get("buy_ladder_budget_usdt") or 0)
    target_base = float(ui_cfg.get("base_alloc_pct") or (params.get("base_alloc_frac", 0) * 100))
    max_exp = float((params.get("max_base_exposure_frac") or 0) * 100) or float(
        ui_cfg.get("max_exposure_pct") or 0
    )
    worst_frac = tel.get("worst_case_base_exposure_frac")
    worst_pct = round(float(worst_frac) * 100, 2) if worst_frac is not None else estimate_worst_exposure_pct(
        target_base_pct=target_base,
        active_buy_ladder_budget_usdt=active_buy,
        budget_usdt=budget,
    )
    explain = str(result.get("explain") or "")
    from app.services.dynamic_param_score.v5.ui_trace import risk_state_from_route

    route_risk_state = risk_state_from_route(route_key) if route_key else ""
    ui_risk_raw = ui_cfg.get("effective_risk_state") or result.get("effective_risk_state") or ""
    from app.services.dynamic_param_score.v5.ui_trace import RISK_CODE_TO_STATE

    risk_tr = {"DEFENSIVE": "Savunmacı", "NORMAL": "Normal kontrollü", "AGGRESSIVE": "Agresif"}
    ui_risk_label = risk_tr.get(route_risk_state) if route_key else risk_tr.get(str(ui_risk_raw).upper(), "")

    buy_grids = (ui_cfg.get("down") or {}).get("grids") or []
    sell_grids = (ui_cfg.get("up") or {}).get("grids") or []
    buy_first = abs(float(buy_grids[0]["trigger_pct"])) if buy_grids else None
    sell_first = abs(float(sell_grids[0]["trigger_pct"])) if sell_grids else None

    ind = tel.get("indicators") or (result.get("rationale") or {}).get("indicators") or {}

    return {
        "route_key": route_key,
        "profile_id": sel.get("selected_template_key") or ctx.get("v5_shelf_id"),
        "shelf_id": ctx.get("v5_shelf_id"),
        "ui_risk_label": ui_risk_label,
        "explanation_risk_label": _extract_explanation_risk(explain),
        "display_regime_label": ui_cfg.get("display_regime_label") or result.get("display_regime_label"),
        "market_regime_text": ui_cfg.get("display_regime_label") or result.get("display_regime_label"),
        "pattern_phrase": _extract_pattern_phrase(explain),
        "confidence": result.get("confidence"),
        "safety_result": result.get("final_action_label") or "",
        "target_base_pct": target_base,
        "worst_exposure_pct": worst_pct,
        "max_base_exposure_pct": max_exp,
        "active_buy_ladder_budget_usdt": active_buy,
        "live_applicable": bool(result.get("deployable")),
        "buy_orders_active": bool(buy_grids) and not ui_cfg.get("buy_disabled"),
        "buy_grid_levels_pct": [g["trigger_pct"] for g in buy_grids],
        "sell_grid_levels_pct": [g["trigger_pct"] for g in sell_grids],
        "buy_distribution_pct": [g.get("qty_pct", 0) for g in buy_grids],
        "grid_summary_buy_pct": _extract_grid_summary_buy(explain),
        "grid_summary_sell_pct": _extract_grid_summary_sell(explain),
        "explain": explain,
        "indicators": ind,
        "final_buy_first": buy_first,
        "final_sell_first": sell_first,
    }


def _extract_explanation_risk(explain: str) -> str:
    low = explain.lower()
    if "risk durumu savunmacı" in low or "risk durumu defensive" in low:
        return "Savunmacı"
    if "risk durumu normal" in low:
        return "Normal kontrollü"
    if "risk durumu agresif" in low or "risk durumu aggressive" in low:
        return "Agresif"
    return ""


def _extract_pattern_phrase(explain: str) -> str:
    if "geniş chop" in explain.lower():
        for part in explain.split("."):
            if "chop" in part.lower() or "üst tepe" in part.lower() or "alt dip" in part.lower():
                return part.strip()
    if "üst tepe" in explain.lower():
        return "üst tepe yapısı"
    if "alt dip" in explain.lower():
        return "alt dip yapısı"
    return ""


def _extract_grid_summary_buy(explain: str) -> Optional[float]:
    import re

    m = re.search(r"grid aralığı alış %([\d]+(?:\.[\d]+)?)", explain.lower())
    return float(m.group(1)) if m else None


def _extract_grid_summary_sell(explain: str) -> Optional[float]:
    import re

    m = re.search(r"satış %([\d]+(?:\.[\d]+)?)", explain.lower())
    return float(m.group(1)) if m else None


def audit_rendered_result(result: dict, *, symbol: str = "") -> List[V5AuditViolation]:
    rendered = build_rendered_trace_from_result(result)
    ind = rendered.get("indicators") or {}
    if not ind and result.get("telemetry"):
        tel = result["telemetry"]
        ind = {
            "higher_highs": tel.get("higher_highs"),
            "lower_lows": tel.get("lower_lows"),
        }
    violations: List[V5AuditViolation] = []
    violations.extend(audit_trace_consistency(rendered))
    violations.extend(audit_regime_route_semantics(rendered, rendered.get("route_key", "")))
    violations.extend(audit_pattern_phrase(ind, rendered))
    param = {
        "target_base_pct": rendered.get("target_base_pct"),
        "worst_exposure_pct": rendered.get("worst_exposure_pct"),
        "max_base_exposure_pct": rendered.get("max_base_exposure_pct"),
        "active_buy_ladder_budget_usdt": rendered.get("active_buy_ladder_budget_usdt"),
        "live_applicable": rendered.get("live_applicable"),
        "buy_orders_active": rendered.get("buy_orders_active"),
        "buy_grid_levels_pct": rendered.get("buy_grid_levels_pct"),
        "buy_distribution_pct": rendered.get("buy_distribution_pct"),
    }
    violations.extend(audit_exposure_final(param))
    ctx = {
        "min_notional_usdt": float((result.get("telemetry") or {}).get("min_notional") or 10),
        "fee_missing": bool(
            ((result.get("selection_telemetry") or {}).get("fee_display") or {}).get("fee_data_available") is False
        ),
    }
    violations.extend(audit_min_notional(param, ctx))
    sub = (result.get("rationale") or {}).get("sub_scores") or (result.get("telemetry") or {}).get("sub_scores") or {}
    violations.extend(
        audit_safety_gate(
            rendered,
            {
                "fee_missing": ctx["fee_missing"],
                "btc_market_risk": sub.get("btc_market_risk_score", 0),
                "volume_consistency": (result.get("telemetry") or {}).get("volume_consistency", 1),
            },
        )
    )
    violations.extend(audit_score_placeholders(rendered.get("explain", "")))
    rendered_summary = {
        "grid_summary_buy_pct": rendered.get("grid_summary_buy_pct") or rendered.get("final_buy_first"),
        "grid_summary_sell_pct": rendered.get("grid_summary_sell_pct") or rendered.get("final_sell_first"),
    }
    violations.extend(
        audit_grid_summary(
            {
                "buy_grid_levels_pct": rendered.get("buy_grid_levels_pct"),
                "sell_grid_levels_pct": rendered.get("sell_grid_levels_pct"),
            },
            rendered_summary,
        )
    )
    for v in violations:
        v.symbol = symbol
    return violations
