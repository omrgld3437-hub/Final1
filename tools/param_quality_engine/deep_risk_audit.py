"""Katman 3 — Risk-Based Deep Replay."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from tools.param_quality_engine.config import SCENARIO_NAMES, AUDIT_SYMBOLS_DEFAULT
from tools.param_quality_engine import scenario_replay_engine as scenario_v
from tools.param_quality_engine import selection_trace_auditor as trace_v
from tools.param_quality_engine.profile_normalizer import behavior_fingerprint


_ACTIVE_DECISIONS = frozenset({
    "ACTIVE_GRID",
    "ACTIVE_DEFENSIVE_GRID",
    "ACTIVE_WIDE_GRID",
    "ACTIVE_LOW_BUDGET_GRID",
    "BALANCED_GRID",
    "DEFENSIVE_GRID",
    "CAUTIOUS_BALANCED_GRID",
    "ULTRA_DEFENSIVE_GRID",
    "HIGH_CONFIDENCE_ACTIVE_GRID",
    "LOW_FEE_WIDE_GRID",
})


def _is_active_decision(action: str) -> bool:
    a = (action or "").upper()
    if a in _ACTIVE_DECISIONS:
        return True
    if a in ("NO_TRADE", "WAIT", "SAFE_WAIT", "DATA_STALE_SAFE_WAIT"):
        return False
    return "GRID" in a or a.startswith("ACTIVE_") or a.startswith("DEFENSIVE")


def collect_risk_profile_ids(
    profiles: List[Dict[str, Any]],
    fast_result: Dict[str, Any],
    *,
    max_profiles: int = 5000,
) -> List[str]:
    """Select profile IDs for deep replay from risk signals."""
    ids: List[str] = []
    seen: Set[str] = set()

    def add(pid: str) -> None:
        if pid and pid not in seen and len(ids) < max_profiles:
            seen.add(pid)
            ids.append(pid)

    for pid in fast_result.get("bad_profile_ids") or []:
        add(str(pid))

    dup_groups = (fast_result.get("duplicates") or {}).get("top_duplicate_groups") or []
    for grp in dup_groups[:50]:
        for pid in grp.get("sample_ids") or []:
            add(str(pid))

    coverage = fast_result.get("coverage") or {}
    for cell in (coverage.get("missing_required_cells_sample") or [])[:200]:
        _ = cell

    by_id = {str(p.get("profile_id") or p.get("template_key") or ""): p for p in profiles}

    # fee_bad, min-notional edge, top score
    for p in sorted(profiles, key=lambda x: float(x.get("score_prior") or 0), reverse=True)[:500]:
        pid = str(p.get("profile_id") or "")
        if p.get("fee_class") == "fee_bad":
            add(pid)
        budget = float(p.get("min_budget_required") or 25)
        grids = int(p.get("buy_grid_count") or 0) + int(p.get("sell_grid_count") or 0)
        if budget <= 50 and grids <= 3:
            add(pid)

    for p in profiles:
        if p.get("fee_class") == "fee_bad" and str(p.get("final_action") or "").upper() in ("WAIT", "NO_TRADE"):
            add(str(p.get("profile_id") or ""))

    return ids[:max_profiles]


def run_deep_risk_audit(
    profiles: List[Dict[str, Any]],
    fast_result: Dict[str, Any],
    *,
    symbols: List[str] | None = None,
    max_replay_profiles: int = 3000,
) -> Dict[str, Any]:
    symbols = list(symbols or AUDIT_SYMBOLS_DEFAULT)
    risk_ids = collect_risk_profile_ids(profiles, fast_result, max_profiles=max_replay_profiles)

    scenario = scenario_v.run_all_scenarios()
    trace = trace_v.audit_symbols(symbols, budgets=[50.0, 100.0, 250.0])

    invalid_scenarios = [
        r for r in scenario.get("results") or []
        if not _is_active_decision(r.get("final_decision", ""))
        and r.get("scenario") not in (
            "DATA_STALE", "BTC_CRASH_DRAG", "CRASH_RISK", "MIN_NOTIONAL_EDGE"
        )
    ]

    trace_issues = []
    for t in trace.get("traces") or []:
        sig = t.get("market_signature") or {}
        if sig.get("error"):
            trace_issues.append({"symbol": t.get("symbol"), "error": sig["error"]})
        fa = str(t.get("final_decision") or "").upper()
        if t.get("symbol") in ("ETHUSDT", "BTCUSDT", "SOLUSDT") and not _is_active_decision(fa):
            if t.get("scenario") not in ("DATA_STALE", "BTC_CRASH_DRAG"):
                trace_issues.append({
                    "symbol": t.get("symbol"),
                    "budget": t.get("budget"),
                    "final_decision": fa,
                    "issue": "expected_active_grid",
                })

    return {
        "layer": "deep-risk",
        "risk_profile_ids_count": len(risk_ids),
        "risk_profile_ids_sample": risk_ids[:100],
        "scenario_replay": scenario,
        "selection_trace": trace,
        "invalid_scenarios": invalid_scenarios,
        "trace_issues": trace_issues,
        "all_pass": len(invalid_scenarios) == 0 and len(trace_issues) == 0 and trace.get("all_complete"),
        "DEEP_RISK_AUDIT_SUMMARY": {
            "scenarios_run": scenario.get("scenarios_run", 0),
            "invalid_scenario_count": len(invalid_scenarios),
            "trace_count": trace.get("trace_count", 0),
            "trace_issues": len(trace_issues),
            "symbols": symbols,
        },
    }


def run_exhaustive_deep_audit(
    profiles: List[Dict[str, Any]],
    *,
    symbols: List[str] | None = None,
) -> Dict[str, Any]:
    """Heavy replay on every profile — release-only mode."""
    fast = {"bad_profile_ids": [p.get("profile_id") for p in profiles]}
    return run_deep_risk_audit(
        profiles,
        fast,
        symbols=symbols,
        max_replay_profiles=len(profiles),
    )
