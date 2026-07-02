"""Enrich V6 DynamicParamDecision telemetry for Param Assistant / DM full display."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_param_score.models import (
    DynamicParamDecision,
    ExchangeConstraints,
    IndicatorSnapshot,
    MarketDataBundle,
    PortfolioState,
    SubScores,
)
from app.services.dynamic_param_score.regime_display import (
    V6_REGIME_LABELS,
    build_regime_technical_label,
    market_status_plain,
)
from app.services.dynamic_param_score.v6.v6_pa_display import contextual_market_status_plain
from app.services.dynamic_param_score.scenario_alignment import _params_snapshot
from app.services.dynamic_param_score.scoring import compute_param_score, compute_sub_scores
from app.services.dynamic_param_score.v6.constants import DEFAULT_COST_FLOOR_PCT


def _indicator_dict_for_ui(ind: IndicatorSnapshot) -> Dict[str, Any]:
    raw = ind.to_dict()
    for src, dst in (
        ("btc_return_1h", "btc_return_1h_pct"),
        ("btc_return_4h", "btc_return_4h_pct"),
        ("btc_return_24h", "btc_return_24h_pct"),
    ):
        if raw.get(src) is not None and raw.get(dst) is None:
            raw[dst] = raw[src]
    return raw


def _data_window_from_indicators(ind: IndicatorSnapshot) -> Dict[str, Any]:
    c5 = int(ind.candle_count_5m or 0)
    c15 = int(ind.candle_count_15m or 0)
    c1h = int(ind.candle_count_1h or 0)
    return {
        "5m": {"actual": c5, "expected": max(c5, 288)},
        "15m": {"actual": c15, "expected": max(c15, 96)},
        "1h": {"actual": c1h, "expected": max(c1h, 168)},
        "window_days": round(c5 * 5 / 1440, 1) if c5 else 0,
    }


def build_v6_market_signature(
    decision: DynamicParamDecision,
    ind: IndicatorSnapshot,
    sub: SubScores,
) -> Dict[str, Any]:
    v6d = (decision.telemetry or {}).get("v6_display") or {}
    scen = v6d.get("scenario_identity") or {}
    regime_id = str(scen.get("regime_id") or decision.regime_tag or "")
    return {
        "regime_code": regime_id,
        "regime_tag_live": decision.regime_tag,
        "vol_code": next(
            (str(e.get("class")) for e in (v6d.get("adjuster_trace") or []) if e.get("name") == "volatility"),
            "",
        ),
        "volatility_percentile": ind.volatility_percentile,
        "volatility_risk_score": sub.volatility_score,
        "risk_class": v6d.get("risk_display_label") or decision.risk_state,
        "behavior_id": v6d.get("behavior_id"),
        "severity": v6d.get("severity"),
        "scenario": scen,
    }


def build_v6_scenario_alignment(
    decision: DynamicParamDecision,
    ind: IndicatorSnapshot,
    sub: SubScores,
    *,
    v6_display: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    v6d = v6_display or (decision.telemetry or {}).get("v6_display") or {}
    scen = v6d.get("scenario_identity") or {}
    regime_id = str(scen.get("regime_id") or decision.regime_tag or "")
    applied = _params_snapshot(decision.params)
    if v6d.get("grid_plan_plain"):
        applied = dict(applied or {})
        applied["grid_plan_plain"] = v6d.get("grid_plan_plain")
        applied["buy_grid_ladder"] = v6d.get("buy_grid_distances_pct")
        applied["sell_grid_ladder"] = v6d.get("sell_grid_distances_pct")
    trace = v6d.get("adjuster_trace") or []
    adjustments = [
        f"{e.get('name')}: {e.get('class')} (skor {e.get('score')})"
        for e in trace
        if str(e.get("name") or "") not in ("delta_limiter", "budget_scaler", "exchange_validator")
    ]
    regime_label = build_regime_technical_label(scen)
    regime_label_plain = str(
        v6d.get("market_status_plain")
        or contextual_market_status_plain(regime_id, trace)
    )
    combined = float(decision.confidence_score or decision.param_score or 70)
    indicator_fit = round(
        (sub.data_quality_score + sub.liquidity_score + sub.spread_score) / 3.0,
        1,
    )
    return {
        "combined_score": combined,
        "shelf_scenario_fit": combined,
        "applied_fit": combined,
        "indicator_fit": indicator_fit,
        "structure_fit": 1.0 if decision.params and decision.params.sell_grid_count else 0.0,
        "grid_direction_fit": 1.0 if decision.params else 0.0,
        "aligned": True,
        "fully_aligned": combined >= 85,
        "canonical_regime_tag": regime_id,
        "legacy_regime_tag": decision.regime_tag,
        "regime_code": regime_id,
        "regime_label": regime_label,
        "regime_label_plain": regime_label_plain,
        "regime_headline": v6d.get("regime_headline"),
        "regime_strategy_why": v6d.get("regime_strategy_why"),
        "grid_plan_plain": v6d.get("grid_plan_plain"),
        "grid_strategy_plain": v6d.get("grid_strategy_plain"),
        "profit_loop_plain": v6d.get("profit_loop_plain"),
        "operational_mode_plain": v6d.get("operational_mode_plain"),
        "behavior_id": v6d.get("behavior_id"),
        "severity": v6d.get("severity"),
        "final_profile_id": v6d.get("final_profile_id"),
        "catalog_profile_id": v6d.get("catalog_profile_id"),
        "data_quality_label": v6d.get("data_quality_label"),
        "risk_display_label": v6d.get("risk_display_label"),
        "shelf_ideal": applied,
        "applied": applied,
        "adjustments": adjustments,
        "alignment_gate_min": 70,
        "engine": "v6",
    }


def build_v6_param_pool_meta(decision: DynamicParamDecision) -> Dict[str, Any]:
    v6d = (decision.telemetry or {}).get("v6_display") or {}
    scen = v6d.get("scenario_identity") or {}
    v6_final = (decision.telemetry or {}).get("v6_final") or {}
    return {
        "pool_version": "v6",
        "selected_template_key": decision.selected_profile_name,
        "profile_subfamily": v6d.get("behavior_id"),
        "candidate_count": 1,
        "selection_context": {
            "engine_version": "DPS_ENGINE_V6",
            "selection_type": "v6_catalog",
            "selection_reason": f"V6 {scen.get('behavior_id', '')} · {v6d.get('severity', 'STD')}",
            "behavior_id": v6d.get("behavior_id"),
            "severity": v6d.get("severity"),
            "scenario_identity": scen,
            "selected_profile_score": decision.param_score,
            "market_signature": (decision.telemetry or {}).get("market_signature"),
            "final_profile_id": v6d.get("final_profile_id"),
            "adjuster_trace": v6d.get("adjuster_trace"),
        },
        "diagnostics": {
            "engine_version": v6_final.get("engine_version"),
            "validation_errors": v6_final.get("validation_errors"),
            "budget_notes": v6_final.get("budget_notes"),
        },
    }


def enrich_v6_decision_for_pa(
    decision: DynamicParamDecision,
    *,
    market_data: MarketDataBundle,
    portfolio: PortfolioState,
    constraints: ExchangeConstraints,
    indicators: IndicatorSnapshot,
) -> DynamicParamDecision:
    """Attach indicators, sub-scores, scenario alignment and pool meta for PA/DM UI."""
    _ = market_data
    sub = compute_sub_scores(indicators, portfolio, constraints)
    from app.services.dynamic_param_score.v6.v6_opportunity import (
        compute_workability_score_1w,
        assess_operational_validity,
        v6_sub_scores_for_display,
    )

    tel = dict(decision.telemetry or {})
    tel["sub_scores"] = v6_sub_scores_for_display(sub.to_dict())
    tel["indicators"] = _indicator_dict_for_ui(indicators)
    v6_final = tel.get("v6_final") or {}
    prof = (v6_final.get("profile") or {}) if isinstance(v6_final, dict) else {}
    trace = (tel.get("v6_display") or {}).get("adjuster_trace") or tel.get("adjuster_trace") or []
    regime_id = str(decision.regime_tag or (tel.get("v6_display") or {}).get("scenario_identity", {}).get("regime_id") or "R2")
    if prof:
        from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile

        try:
            scen_raw = prof.get("scenario") or (tel.get("v6_display") or {}).get("scenario_identity") or {}
            profile_stub = V6CatalogProfile(
                profile_id=str(prof.get("profile_id") or decision.selected_profile_name or ""),
                scenario=ScenarioIdentity(
                    regime_id=str(scen_raw.get("regime_id") or regime_id),
                    sub_id=str(scen_raw.get("sub_id") or "01"),
                    micro_id=str(scen_raw.get("micro_id") or "001"),
                    behavior_id=str(scen_raw.get("behavior_id") or "PB01"),
                    severity=str(scen_raw.get("severity") or "STD"),  # type: ignore[arg-type]
                ),
                base_allocation_pct=int(prof.get("base_allocation_pct") or 0),
                quote_allocation_pct=int(prof.get("quote_allocation_pct") or 100),
                normal_buy_enabled=bool(prof.get("normal_buy_enabled", True)),
                buy_grids=[GridLevel(int(g["distance_pct"]), int(g["amount_pct"])) for g in (prof.get("buy_grids") or [])],
                sell_grids=[GridLevel(int(g["distance_pct"]), int(g["amount_pct"])) for g in (prof.get("sell_grids") or [])],
            )
            from app.services.dynamic_param_score.v6.v6_input_contract import input_contract_from_dict

            inp_stub = input_contract_from_dict(tel.get("indicators") or {})
            ws, wwarn = compute_workability_score_1w(profile_stub, inp_stub, trace, regime_id)
            tel["workability_score_1w"] = ws
            tel["operational_validity"] = assess_operational_validity(profile_stub).to_dict()
            if wwarn:
                tel["workability_warnings"] = wwarn
        except Exception:
            pass
    from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display, build_v6_stream_lines

    v6d = dict(tel.get("v6_display") or {})
    opp_notes = (v6_final.get("opportunity_notes") if isinstance(v6_final, dict) else None) or {}
    v6d = enrich_v6_display(
        v6d,
        adjuster_trace=v6d.get("adjuster_trace") or trace,
        deployable=bool(decision.deployable),
        deploy_block_reason=(v6_final.get("deploy_block_reason") if isinstance(v6_final, dict) else None),
        opportunity_notes=opp_notes,
    )
    tel["v6_display"] = v6d
    tel["v6_stream_lines"] = build_v6_stream_lines(
        v6d,
        symbol=decision.symbol,
        param_score=decision.param_score,
    )
    tel["market_signature"] = build_v6_market_signature(decision, indicators, sub)
    tel["scenario_alignment"] = build_v6_scenario_alignment(
        decision, indicators, sub, v6_display=v6d,
    )
    tel["param_pool"] = build_v6_param_pool_meta(decision)
    tel["min_notional"] = float(constraints.min_notional or 0)
    tel["volume_24h"] = indicators.quote_volume_24h
    tel["volume_consistency"] = indicators.volume_consistency
    tel["fee_floor_pct"] = DEFAULT_COST_FLOOR_PCT
    tel["data_window"] = _data_window_from_indicators(indicators)
    tel["is_first_start"] = portfolio.current_base_exposure_frac < 0.01
    ind_ui = tel.get("indicators") or {}
    ind_ui.pop("total_friction_pct", None)
    tel["indicators"] = ind_ui

    param_score = int(compute_param_score(sub))
    confidence = int(
        round(
            param_score * 0.45
            + sub.data_quality_score * 0.25
            + sub.liquidity_score * 0.15
            + sub.exposure_safety_score * 0.15
        )
    )
    return DynamicParamDecision(
        decision_id=decision.decision_id,
        symbol=decision.symbol,
        timestamp=decision.timestamp,
        run_source=decision.run_source,
        final_action=decision.final_action,
        deployable=decision.deployable,
        param_score=param_score,
        confidence_score=max(confidence, decision.confidence_score or 0),
        risk_score=max(100 - sub.drawdown_risk_score, decision.risk_score or 0),
        regime_tag=decision.regime_tag,
        risk_state=decision.risk_state,
        selected_profile_name=decision.selected_profile_name,
        selected_profile_bucket=decision.selected_profile_bucket,
        params=decision.params,
        safety_gates=decision.safety_gates,
        blocking_reasons=decision.blocking_reasons,
        warnings=decision.warnings,
        explain=decision.explain,
        telemetry=tel,
        action_detail=decision.action_detail,
    )
