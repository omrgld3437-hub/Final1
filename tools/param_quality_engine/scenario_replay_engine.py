"""Scenario replay through DPS engine."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import BotContext, ExchangeConstraints, FinalAction
from tests.dynamic_param_score.factories import (
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)

from tools.param_quality_engine.config import SCENARIO_NAMES


def _scenario_inputs(name: str) -> Dict[str, Any]:
    mapping = {
        "CALM_RANGE_MAJOR": ("BTCUSDT", "flat_dead_market", 100, 500),
        "BALANCED_RANGE_MAJOR": ("ETHUSDT", "balanced_range", 100, 500),
        "VOLATILE_RANGE_MAJOR": ("BTCUSDT", "range_high_vol", 100, 500),
        "CHOPPY_ALTCOIN": ("SOLUSDT", "high_vol_unstable", 80, 200),
        "LOW_VOL_BUT_FEE_BAD": ("ETHUSDT", "flat_dead_market", 50, 100),
        "LOW_BUDGET_50_USDT": ("ETHUSDT", "balanced_range", 50, 50),
        "LOWER_LOWS_RANGE": ("ETHUSDT", "balanced_range", 100, 400),
        "HIGHER_HIGHS_RANGE": ("ETHUSDT", "balanced_range", 100, 400),
        "BTC_CRASH_DRAG": ("SOLUSDT", "dump_risk", 100, 300),
        "CRASH_RISK": ("BTCUSDT", "dump_risk", 100, 65000),
        "SPREAD_WIDE_BUT_NOT_DANGEROUS": ("LINKUSDT", "balanced_range", 100, 500),
        "DATA_STALE": ("ETHUSDT", "bad_data_gaps", 100, 500),
        "MIN_NOTIONAL_EDGE": ("ADAUSDT", "balanced_range", 25, 30),
    }
    sym, pattern, budget, price = mapping.get(name, ("ETHUSDT", "balanced_range", 100, 500))
    return {"symbol": sym, "pattern": pattern, "budget": budget, "price": price}


def replay_scenario(name: str, engine: DynamicParamScoreEngine | None = None) -> Dict[str, Any]:
    engine = engine or DynamicParamScoreEngine()
    inp = _scenario_inputs(name)
    market = make_market_bundle(
        symbol=inp["symbol"],
        pattern=inp["pattern"],
        price=inp["price"],
    )
    if name == "LOW_VOL_BUT_FEE_BAD":
        pass  # fee stress handled via constraints / portfolio in engine
    if name == "SPREAD_WIDE_BUT_NOT_DANGEROUS":
        pass
    portfolio = make_portfolio_state(
        budget_usdt=inp["budget"],
        base_exposure_frac=0.0,
        price=inp["price"],
    )
    c = make_constraints(min_notional=5 if inp["budget"] >= 50 else 10)
    decision = engine.calculate_decision(
        inp["symbol"],
        market,
        portfolio,
        c,
        make_context(run_source="param_assistant", budget_usdt=inp["budget"]),
    )
    telemetry = decision.telemetry or {}
    pool_t = telemetry.get("param_pool") or {}
    return {
        "scenario": name,
        "input_features": {
            "symbol": inp["symbol"],
            "pattern": inp["pattern"],
            "budget_usdt": inp["budget"],
            "price": inp["price"],
            "regime_tag": decision.regime_tag,
            "risk_state": decision.risk_state,
        },
        "feature_bins": pool_t.get("selection_context") or {},
        "candidate_count_before": pool_t.get("active_template_count"),
        "candidate_count_after_prefilter": pool_t.get("candidate_count"),
        "candidate_count_after_validation": pool_t.get("templates_scanned"),
        "selected_profile_id": decision.selected_profile_name or pool_t.get("selected_template_key"),
        "selected_params": decision.params.to_dict() if decision.params else None,
        "rejected_top_reasons": (pool_t.get("filter_summary") or {}) if isinstance(pool_t.get("filter_summary"), dict) else [],
        "final_decision": decision.final_action,
        "deployable": decision.deployable,
        "explanation": decision.explain,
        "blocking_reasons": decision.blocking_reasons,
        "wait_is_hard_safety_only": decision.final_action not in (
            FinalAction.WAIT.value,
            FinalAction.NO_TRADE.value,
        )
        or bool(decision.blocking_reasons),
    }


def run_all_scenarios(names: List[str] | None = None) -> Dict[str, Any]:
    names = list(names or SCENARIO_NAMES)
    engine = DynamicParamScoreEngine()
    results = [replay_scenario(n, engine) for n in names]
    invalid_waits = [
        r for r in results
        if r["final_decision"] in ("WAIT", "NO_TRADE", "SAFE_WAIT")
        and r["scenario"] not in ("DATA_STALE", "MIN_NOTIONAL_EDGE", "BTC_CRASH_DRAG")
    ]
    return {
        "scenarios_run": len(results),
        "results": results,
        "invalid_wait_scenarios": invalid_waits,
        "all_pass": len(invalid_waits) == 0,
    }


def format_symbol_replay_md(symbol: str, results: List[Dict[str, Any]]) -> str:
    lines = [f"# Symbol Replay — {symbol}", ""]
    for r in results:
        if r["input_features"].get("symbol") != symbol:
            continue
        lines.append(f"## {r['scenario']}")
        lines.append(f"- **Final decision:** {r['final_decision']}")
        lines.append(f"- **Deployable:** {r['deployable']}")
        lines.append(f"- **Selected profile:** {r['selected_profile_id']}")
        lines.append(f"- **Candidates:** {r['candidate_count_after_prefilter']}")
        lines.append(f"- **Explanation:** {r['explanation'][:300] if r['explanation'] else '—'}")
        lines.append("")
    return "\n".join(lines)
