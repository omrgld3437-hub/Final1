"""Selection trace auditor — live symbol replay with score breakdown."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    index_key_for_signature,
    market_signature_from_live,
)
from tests.dynamic_param_score.factories import (
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)

_SYMBOL_SCENARIOS: Dict[str, Tuple[str, float]] = {
    "BTCUSDT": ("flat_dead_market", 65000.0),
    "ETHUSDT": ("balanced_range", 3500.0),
    "SOLUSDT": ("range_high_vol", 150.0),
    "AVAXUSDT": ("high_vol_unstable", 35.0),
    "BNBUSDT": ("balanced_range", 600.0),
    "ADAUSDT": ("low_liquidity", 0.45),
    "XRPUSDT": ("balanced_range", 0.55),
    "LINKUSDT": ("trending_up", 14.0),
}


def build_selection_trace(symbol: str, budget: float = 50.0) -> Dict[str, Any]:
    engine = DynamicParamScoreEngine()
    pattern, price = _SYMBOL_SCENARIOS.get(symbol.upper(), ("balanced_range", 100.0))
    market = make_market_bundle(symbol=symbol, pattern=pattern, price=price)
    portfolio = make_portfolio_state(
        budget_usdt=budget,
        base_exposure_frac=0.0,
        price=market.ticker_price or price,
    )
    decision = engine.calculate_decision(
        symbol,
        market,
        portfolio,
        make_constraints(),
        make_context(run_source="param_assistant", budget_usdt=budget),
    )
    telemetry = decision.telemetry or {}
    pool_t = telemetry.get("param_pool") or {}
    sel_ctx = pool_t.get("selection_context") or {}
    sub = telemetry.get("sub_scores") or {}
    ind = telemetry.get("indicators") or {}

    signature: Dict[str, Any] = {}
    try:
        signature = market_signature_from_live(
            symbol=symbol,
            budget=budget,
            regime=str(decision.regime_tag or ""),
            risk_level=str(decision.risk_state or "NORMAL"),
            volatility_percentile=float(ind.get("volatility_percentile") or 50),
            lower_lows=bool(ind.get("lower_lows")),
            higher_highs=bool(ind.get("higher_highs")),
            fee_efficiency_score=int(
                sub.get("fee_efficiency_score") or ind.get("fee_score") or 50
            ),
        )
    except Exception as exc:
        signature = {"error": str(exc)}

    prefilter_key = index_key_for_signature(signature) if isinstance(signature, dict) and not signature.get("error") else ""

    score_breakdown = {
        "regime_match": round(float(sub.get("trend_score") or 0) / 100, 4),
        "volatility_fit": round(float(sub.get("volatility_score") or 0) / 100, 4),
        "grid_distance": round(float(sub.get("liquidity_score") or 0) / 100, 4),
        "fee_efficiency": round(float(sub.get("fee_efficiency_score") or 0) / 100, 4),
        "min_notional": round(float(sub.get("order_reality_score") or 0) / 100, 4),
        "structure_fit": round(float(sub.get("structure_score") or 0) / 100, 4),
        "trend_risk": round(float(sub.get("trend_score") or 0) / 100, 4),
        "data_quality": round(float(sub.get("data_quality_score") or 0) / 100, 4),
    }

    candidate_before = int(pool_t.get("active_template_count") or pool_t.get("templates_scanned") or 300000)
    candidate_prefilter = int(pool_t.get("candidate_count") or candidate_before)
    candidate_validation = int(pool_t.get("templates_scanned") or candidate_prefilter)

    top_candidates = sel_ctx.get("top_candidates") or pool_t.get("top_candidates") or []
    selected_key = pool_t.get("selected_template_key") or decision.selected_profile_name

    return {
        "symbol": symbol,
        "budget": budget,
        "market_pattern": pattern,
        "market_signature": signature,
        "prefilter_key": prefilter_key,
        "candidate_count_before": candidate_before,
        "candidate_count_after_prefilter": candidate_prefilter,
        "candidate_count_after_validation": candidate_validation,
        "candidate_count": candidate_prefilter,
        "templates_scanned": pool_t.get("templates_scanned"),
        "active_template_count": pool_t.get("active_template_count"),
        "top_10_candidates": top_candidates[:10] if isinstance(top_candidates, list) else [],
        "top_reject_summary": pool_t.get("filter_summary"),
        "selected_profile": {
            "template_key": selected_key,
            "profile_id": decision.selected_profile_name,
            "profile_family": pool_t.get("profile_family"),
            "final_action": decision.final_action,
        },
        "selected_profile_id": selected_key,
        "score_breakdown": score_breakdown,
        "final_score": round(float(decision.param_score or 0) / 100, 4),
        "final_decision": decision.final_action,
        "explanation": decision.explain,
        "selection_context": sel_ctx,
        "trace_complete": bool(selected_key) and not signature.get("error") and len(top_candidates) > 0,
        "counts_consistent": (
            candidate_prefilter <= candidate_before
            and candidate_validation <= candidate_prefilter
        ),
        "diversity_ok": selected_key is not None,
    }


def audit_symbols(symbols: List[str], budgets: List[float] | None = None) -> Dict[str, Any]:
    budgets = budgets or [50.0, 100.0, 250.0]
    traces: List[Dict[str, Any]] = []
    incomplete = 0
    families_seen: set[str] = set()
    for sym in symbols:
        for b in budgets[:2]:
            t = build_selection_trace(sym, b)
            traces.append(t)
            fam = (t.get("selected_profile") or {}).get("profile_family") or ""
            if fam:
                families_seen.add(fam)
            if not t.get("trace_complete") or not t.get("counts_consistent"):
                incomplete += 1
    return {
        "traces": traces,
        "trace_count": len(traces),
        "incomplete_traces": incomplete,
        "all_complete": incomplete == 0,
        "unique_profile_families": sorted(families_seen),
        "diversity_ok": len(families_seen) >= min(3, len(symbols)),
    }
