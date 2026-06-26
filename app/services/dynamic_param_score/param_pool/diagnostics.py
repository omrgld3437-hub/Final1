"""Selection diagnostics — reject summaries, fallback metadata, UI telemetry."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.param_pool.models import (
    SelectionContext,
    TemplateRejectReason,
    TemplateSelectionResult,
)

_REASON_BUCKET: Dict[str, str] = {
    "score_out_of_range": TemplateRejectReason.SCORE.value,
    "regime_mismatch": TemplateRejectReason.REGIME.value,
    "risk_state_mismatch": TemplateRejectReason.RISK.value,
    "fee_tier_mismatch": TemplateRejectReason.FEE.value,
    "fee_too_weak_for_active": TemplateRejectReason.FEE.value,
    "fee_efficiency_score_below_min": TemplateRejectReason.FEE.value,
    "liquidity_tier_mismatch": TemplateRejectReason.LIQUIDITY.value,
    "volatility_tier_mismatch": TemplateRejectReason.VOLATILITY.value,
    "btc_risk_tier_mismatch": TemplateRejectReason.BTC_RISK.value,
    "order_reality_tier_mismatch": TemplateRejectReason.ORDER_REALITY.value,
    "friction_too_high": TemplateRejectReason.FRICTION.value,
    "requires_sellable_base_missing": TemplateRejectReason.EXPOSURE.value,
    "fresh_start_no_sellable_base": TemplateRejectReason.EXPOSURE.value,
    "budget_tier_mismatch": TemplateRejectReason.BUDGET.value,
    "equity_below_min": TemplateRejectReason.BUDGET.value,
    "equity_above_max": TemplateRejectReason.BUDGET.value,
    "min_notional_multiple_fail": TemplateRejectReason.MIN_NOTIONAL.value,
    "headroom_tier_mismatch": TemplateRejectReason.HEADROOM.value,
    "headroom_insufficient_for_buy": TemplateRejectReason.HEADROOM.value,
    "min_headroom_multiple_fail": TemplateRejectReason.HEADROOM.value,
    "exposure_tier_mismatch": TemplateRejectReason.EXPOSURE.value,
    "overexposed_no_buy": TemplateRejectReason.EXPOSURE.value,
    "requires_base_missing": TemplateRejectReason.EXPOSURE.value,
    "requires_no_base": TemplateRejectReason.EXPOSURE.value,
    "drawdown_risk_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "mean_reversion_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "volatility_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "range_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "liquidity_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "spread_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "exposure_safety_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "data_quality_score_below_min": TemplateRejectReason.SUBSCORE.value,
    "btc_market_risk_score_below_min": TemplateRejectReason.SUBSCORE.value,
}


def reject_bucket(reason: str) -> str:
    return _REASON_BUCKET.get(reason, TemplateRejectReason.OTHER.value)


def build_reject_summary(filtered_out: Dict[str, List[str]]) -> Dict[str, int]:
    summary: Dict[str, int] = {b.value: 0 for b in TemplateRejectReason}
    for reasons in filtered_out.values():
        for r in reasons:
            bucket = reject_bucket(r)
            summary[bucket] = summary.get(bucket, 0) + 1
    return summary


def build_reject_examples(
    filtered_out: Dict[str, List[str]],
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """Small sample for logs/DB — never dump full 50k reject map."""
    examples: List[Dict[str, Any]] = []
    for template_key, reasons in filtered_out.items():
        examples.append({"template_key": template_key, "reasons": reasons[:5]})
        if len(examples) >= limit:
            break
    return examples


def build_selection_diagnostics(
    result: TemplateSelectionResult,
    ctx: Optional[SelectionContext] = None,
) -> Dict[str, Any]:
    """Structured diagnostics for logs, DB persistence and UI technical panel."""
    ctx_dict = result.selection_context or {}
    if ctx is not None:
        ctx_dict = {
            "param_score": ctx.param_score,
            "regime": ctx.regime,
            "risk_state": ctx.risk_state,
            "budget_tier": ctx.budget_tier,
            "exposure_tier": ctx.exposure_tier,
            "headroom_tier": ctx.headroom_tier,
            "fee_tier": ctx.fee_tier,
            "equity_usdt": round(ctx.equity_usdt, 2),
            "headroom_usdt": round(ctx.headroom_usdt, 2),
            "has_sellable_base": ctx.has_sellable_base,
            "min_notional": ctx.min_notional,
        }

    reject_summary = result.filter_summary or build_reject_summary(result.filtered_out)

    return {
        "pool_version": result.pool_version,
        "selected_template_key": result.selected_template_key,
        "selected_profile_family": result.profile_family,
        "candidate_count": result.candidate_count,
        "selection_score": result.selection_score,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "fallback_action": result.final_action if result.fallback_used else None,
        "reject_summary": reject_summary,
        "filtered_out_by_score": reject_summary.get(TemplateRejectReason.SCORE.value, 0),
        "filtered_out_by_regime": reject_summary.get(TemplateRejectReason.REGIME.value, 0),
        "filtered_out_by_risk": reject_summary.get(TemplateRejectReason.RISK.value, 0),
        "filtered_out_by_budget": reject_summary.get(TemplateRejectReason.BUDGET.value, 0),
        "filtered_out_by_exposure": reject_summary.get(TemplateRejectReason.EXPOSURE.value, 0),
        "filtered_out_by_headroom": reject_summary.get(TemplateRejectReason.HEADROOM.value, 0),
        "filtered_out_by_fee": reject_summary.get(TemplateRejectReason.FEE.value, 0),
        "filtered_out_by_subscore": reject_summary.get(TemplateRejectReason.SUBSCORE.value, 0),
        "filtered_out_by_min_notional": reject_summary.get(
            TemplateRejectReason.MIN_NOTIONAL.value, 0
        ),
        "filtered_out_by_liquidity": reject_summary.get(
            TemplateRejectReason.LIQUIDITY.value, 0
        ),
        "filtered_out_by_volatility": reject_summary.get(
            TemplateRejectReason.VOLATILITY.value, 0
        ),
        "filtered_out_by_btc_risk": reject_summary.get(
            TemplateRejectReason.BTC_RISK.value, 0
        ),
        "filtered_out_by_order_reality": reject_summary.get(
            TemplateRejectReason.ORDER_REALITY.value, 0
        ),
        "filtered_out_by_friction": reject_summary.get(
            TemplateRejectReason.FRICTION.value, 0
        ),
        "param_score": ctx_dict.get("param_score"),
        "regime": ctx_dict.get("regime"),
        "risk_state": ctx_dict.get("risk_state"),
        "fee_tier": ctx_dict.get("fee_tier"),
        "headroom_tier": ctx_dict.get("headroom_tier"),
        "budget_tier": ctx_dict.get("budget_tier"),
        "exposure_tier": ctx_dict.get("exposure_tier"),
        "has_sellable_base": ctx_dict.get("has_sellable_base"),
        "headroom_usdt": ctx_dict.get("headroom_usdt"),
        "min_notional": ctx_dict.get("min_notional"),
        "liquidity_tier": ctx_dict.get("liquidity_tier"),
        "volatility_tier": ctx_dict.get("volatility_tier"),
        "btc_risk_tier": ctx_dict.get("btc_risk_tier"),
        "order_reality_tier": ctx_dict.get("order_reality_tier"),
        "active_template_count": ctx_dict.get("active_template_count"),
        "templates_scanned": ctx_dict.get("templates_scanned"),
    }
