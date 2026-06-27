"""ADAUSDT and live-style regression cases for V5 UI trace audit."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.models import (
    BotContext,
    DynamicParamDecision,
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.explain import build_explanation
from app.services.dynamic_param_score.v5.audit.trace_consistency import (
    audit_rendered_result,
    build_rendered_trace_from_result,
)
from app.services.dynamic_param_score.v5.audit.violations import V5AuditViolation
from app.services.dynamic_param_score.v5.bridge import v5_select_and_render
from app.services.dynamic_param_score.v5.ui_trace import (
    render_risk_opportunity_sentence,
    risk_label_from_route,
)


def _ada_indicators() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        return_24h_pct=6.0,
        atr14_pct_5m=0.25,
        atr14_pct_1h=1.2,
        orderbook_spread_pct=0.08,
        rsi14_1h=58,
        price_in_bb=0.72,
        higher_highs=True,
        lower_lows=False,
        adx_1h=22,
        ema20_slope_5m=0.08,
        ema50_slope_5m=0.02,
        roc_5m=0.2,
        volume_spike_abnormality=1.3,
        btc_crash_velocity=0,
        crash_velocity=0,
        drawdown_7d_pct=4,
        volatility_percentile=45,
    )


def _ada_sub() -> SubScores:
    return SubScores(
        range_score=60,
        liquidity_score=72,
        spread_score=70,
        fee_efficiency_score=40,
        volatility_score=50,
        data_quality_score=75,
        btc_market_risk_score=70,
        exposure_safety_score=60,
        trend_score=55,
        drawdown_risk_score=45,
    )


def _run_v5_case(*, case_id: str, risk_state: str, confidence: float = 50.0) -> Dict[str, Any]:
    os.environ["PARAM_POOL_VERSION"] = "v5.0.0"
    sub = _ada_sub()
    ind = _ada_indicators()
    portfolio = PortfolioState(
        base_balance=1000,
        quote_balance=400,
        base_value_usdt=100,
        quote_value_usdt=400,
        total_equity_usdt=500,
        current_base_exposure_frac=0.2,
    )
    constraints = ExchangeConstraints(
        min_notional=10,
        step_size=0.1,
        tick_size=0.0001,
        min_qty=0.1,
        maker_fee_pct=0.1,
        taker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )
    ctx = BotContext(run_source="param_assistant", budget_usdt=500, bot_id=1)
    sel, params, _bucket = v5_select_and_render(
        65,
        RegimeTag.BALANCED_RANGE,
        risk_state,
        sub,
        ind,
        portfolio,
        constraints,
        ctx,
        500,
        10,
        symbol="ADAUSDT",
    )
    decision = DynamicParamDecision(
        decision_id=f"regression-{case_id}",
        timestamp=1_700_000_000,
        symbol="ADAUSDT",
        run_source="param_assistant",
        param_score=65,
        confidence_score=int(confidence),
        risk_score=50,
        regime_tag=RegimeTag.BALANCED_RANGE.value,
        risk_state=risk_state,
        final_action=FinalAction.BALANCED_GRID.value,
        deployable=False,
        selected_profile_name=sel.selected_template_key or "",
        selected_profile_bucket="V5_EXACT",
        params=params,
        safety_gates=[],
        explain="",
        blocking_reasons=[],
        warnings=[],
        telemetry={
            "sub_scores": sub.__dict__,
            "param_pool": {
                "pool_version": sel.pool_version,
                "selected_template_key": sel.selected_template_key,
                "selection_context": sel.selection_context,
                "fallback_used": sel.fallback_used,
            },
            "min_notional": 10,
            "volume_consistency": 0.29,
            "indicators": {**ind.to_dict(), "route_key": sel.selection_context.get("route_key")},
        },
    )
    decision.explain = build_explanation(
        65,
        RegimeTag.BALANCED_RANGE.value,
        risk_state,
        FinalAction.BALANCED_GRID.value,
        sub,
        params,
        [],
        selected_template_key=sel.selected_template_key,
        indicators={**ind.to_dict(), "route_key": sel.selection_context.get("route_key")},
        budget_usdt=500,
    )
    result = decision_to_param_assistant_result(decision, 500, "ADAUSDT")
    violations = audit_rendered_result(result, symbol="ADAUSDT")
    rendered = build_rendered_trace_from_result(result)
    ui_cfg = result.get("ui_config") or {}
    buy_grids = (ui_cfg.get("down") or {}).get("grids") or []
    sell_grids = (ui_cfg.get("up") or {}).get("grids") or []
    route_key = str(sel.selection_context.get("route_key") or "")
    risk_opp = render_risk_opportunity_sentence(sub.drawdown_risk_score, sub.trend_score)
    rendered_fields = {
        "ui_risk_label": risk_label_from_route(route_key) if route_key else rendered.get("ui_risk_label"),
        "explanation_risk_label": rendered.get("explanation_risk_label"),
        "route_risk": route_key.split("|")[5] if "|" in route_key else "",
        "market_regime_text": ui_cfg.get("display_regime_label") or result.get("display_regime_label"),
        "pattern_phrase": rendered.get("pattern_phrase"),
        "higher_highs": ind.higher_highs,
        "lower_lows": ind.lower_lows,
        "target_base_pct": ui_cfg.get("base_alloc_pct"),
        "max_exposure_pct": round((params.max_base_exposure_frac if params else 0) * 100, 2),
        "worst_exposure_pct": rendered.get("worst_exposure_pct"),
        "active_buy_ladder_budget_usdt": (ui_cfg.get("allocation_display") or {}).get("active_buy_ladder_usdt"),
        "min_notional_usdt": 10,
        "buy_orders_active": rendered.get("buy_orders_active"),
        "final_action_label": result.get("final_action_label"),
        "deployable": result.get("deployable"),
        "grid_summary_buy_pct": rendered.get("grid_summary_buy_pct"),
        "grid_summary_sell_pct": rendered.get("grid_summary_sell_pct"),
        "final_first_buy_grid": buy_grids[0]["trigger_pct"] if buy_grids else None,
        "final_first_sell_grid": sell_grids[0]["trigger_pct"] if sell_grids else None,
        "risk_opportunity_text": risk_opp,
        "explain_excerpt": (result.get("explain") or "")[:400],
    }
    return {
        "case_id": case_id,
        "shelf_id": sel.selected_template_key,
        "route_key": sel.selection_context.get("route_key"),
        "violations": violations,
        "rendered_fields": rendered_fields,
        "result_summary": {
            "confidence": result.get("confidence"),
            "final_action_label": result.get("final_action_label"),
            "effective_risk_state": result.get("effective_risk_state"),
            "deployable": result.get("deployable"),
        },
        "pass": len(violations) == 0,
    }


def run_all_regression_cases() -> List[Dict[str, Any]]:
    return [
        _run_v5_case(case_id="ADAUSDT-001", risk_state="DEFENSIVE", confidence=15),
        _run_v5_case(case_id="ADAUSDT-002", risk_state="NORMAL", confidence=29),
    ]


def assert_regression_case_rules(case: Dict[str, Any]) -> List[V5AuditViolation]:
    extra: List[V5AuditViolation] = []
    cid = case["case_id"]
    shelf = str(case.get("shelf_id") or "")
    rs = case.get("result_summary") or {}
    if cid == "ADAUSDT-001":
        if shelf and "K1" not in shelf:
            extra.append(
                V5AuditViolation(
                    severity="BLOCKER",
                    code="ADA001_WRONG_RISK_SHELF",
                    message="ADAUSDT-001 expects K1 defensive shelf",
                    shelf_id=shelf,
                    expected="K1",
                    actual=shelf,
                )
            )
        if rs.get("effective_risk_state") not in (None, "DEFENSIVE"):
            extra.append(
                V5AuditViolation(
                    severity="BLOCKER",
                    code="ADA001_RISK_STATE",
                    message="UI effective risk must be DEFENSIVE for K1",
                    expected="DEFENSIVE",
                    actual=rs.get("effective_risk_state"),
                )
            )
    if cid == "ADAUSDT-002":
        if shelf and "K2" not in shelf:
            extra.append(
                V5AuditViolation(
                    severity="BLOCKER",
                    code="ADA002_WRONG_RISK_SHELF",
                    message="ADAUSDT-002 expects K2 normal controlled shelf",
                    shelf_id=shelf,
                    expected="K2",
                    actual=shelf,
                )
            )
        if rs.get("effective_risk_state") == "DEFENSIVE":
            extra.append(
                V5AuditViolation(
                    severity="BLOCKER",
                    code="ADA002_UI_DEFENSIVE_ON_K2",
                    message="K2 route must not show DEFENSIVE as primary risk",
                    actual=rs.get("effective_risk_state"),
                )
            )
        if (rs.get("confidence") or 100) < 30 and rs.get("final_action_label") == "Dengeli grid":
            extra.append(
                V5AuditViolation(
                    severity="CRITICAL",
                    code="ADA002_LOW_CONF_ACTIVE_LABEL",
                    message="Low confidence must not show Dengeli grid",
                    actual=rs.get("final_action_label"),
                )
            )
    return extra
