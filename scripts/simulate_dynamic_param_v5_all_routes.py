#!/usr/bin/env python3
"""Simulate V5 resolver across all routes."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.index.route_lookup import build_v5_route_index
from app.services.dynamic_param_score.v5.resolver.resolve_dynamic_param_v5 import resolve_dynamic_param_v5
from app.services.dynamic_param_score.v5.domain.types import V5ResolveInput

CRITICAL_REGIMES = {
    "R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND",
    "R12_CAPITULATION_REACTION", "R13_HIGH_VOL_DISORDER", "R14_LOW_LIQUIDITY_DRIFT",
    "R15_SPECIAL_STRESS_TRANSITION", "R17_DATA_UNCERTAIN_REGIME",
}
CRITICAL_STRUCTURES = {"S5_LOWER_LOWS", "S8_BREAKDOWN"}
CRITICAL_VOL = {"V5_SHOCK"}
CRITICAL_RISK = {"K1_DEFENSIVE"}
CRITICAL_LIQ = {"L4_EXECUTION_RISKY"}
CRITICAL_ASSET = {"A5_MEME_SPECULATIVE", "A6_LOW_LIQUIDITY_ALT"}


def make_default_input(route_parts) -> V5ResolveInput:
    return V5ResolveInput(
        symbol="BTCUSDT",
        route_parts=route_parts,
        budget_usdt=500.0,
        min_notional_usdt=10.0,
        current_base_pct=45.0,
        current_quote_pct=55.0,
        maker_fee_pct=0.1,
        taker_fee_pct=0.1,
        spread_pct=0.05,
        slippage_pct=0.03,
        rounding_pct=0.01,
        indicators={"rsi1h": 50, "bb_position": 0.5, "btc_crash_velocity": 0},
        data_quality={"freshness_sec": 30, "candle_count5m": 100, "data_gap_sec": 0, "price_valid": True},
    )


def is_critical(shelf) -> bool:
    rp = shelf.route_parts
    return (
        rp.regime in CRITICAL_REGIMES
        or rp.structure in CRITICAL_STRUCTURES
        or rp.volatility in CRITICAL_VOL
        or rp.risk in CRITICAL_RISK
        or rp.liquidity in CRITICAL_LIQ
        or rp.asset in CRITICAL_ASSET
    )


def main() -> None:
    shelves = generate_all_v5_shelves()
    index = build_v5_route_index(shelves)
    exact = fallback = invalid = 0
    critical_results = []
    all_results = []

    for shelf in shelves:
        inp = make_default_input(shelf.route_parts)
        result = resolve_dynamic_param_v5(inp, index)
        if result.selection_type == "EXACT_V5":
            exact += 1
        else:
            fallback += 1
        if result.final_grid_count == 0 and result.selection_type != "GLOBAL_SAFE_V5":
            if shelf.route_parts.regime not in ("R17_DATA_UNCERTAIN_REGIME",):
                invalid += 1
        entry = {
            "route_key": shelf.route_key,
            "selection_type": result.selection_type,
            "shelf_id": result.shelf_id,
        }
        all_results.append(entry)
        if is_critical(shelf):
            critical_results.append(entry)

    summary = {
        "totalRoutesSimulated": len(shelves),
        "exactHitCount": exact,
        "exactHitRatio": round(exact / len(shelves), 6),
        "fallbackCount": fallback,
        "fallbackRatio": round(fallback / len(shelves), 6),
        "invalidOutputCount": invalid,
        "expectedShelves": EXPECTED_V5_SHELF_COUNT,
    }
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dynamic_param_v5_all_route_simulation.json").write_text(
        json.dumps({"summary": summary, "sample": all_results[:100]}, indent=2), encoding="utf-8"
    )
    (reports / "dynamic_param_v5_critical_route_simulation.json").write_text(
        json.dumps({"count": len(critical_results), "results": critical_results[:200]}, indent=2),
        encoding="utf-8",
    )
    with open(reports / "dynamic_param_v5_simulation_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(summary.keys())
        w.writerow(summary.values())
    (reports / "dynamic_param_v5_resolver_simulation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if fallback > 0 or invalid > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
