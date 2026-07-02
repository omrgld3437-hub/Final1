#!/usr/bin/env python3
"""Live 50-symbol V6 dry-run — Binance data read only, no trade execution."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.dynamic_param_v6.v6_simulation_common import (  # noqa: E402
    REPORT_DIR,
    aggregate_findings,
    calculate_live_symbol,
    decision_to_live_row,
    ensure_report_dir,
    fetch_tradable_usdt_symbols,
    merge_report_summary,
    pick_live_symbols,
    render_logic_errors_report,
    utc_now_iso,
    validate_live_decision,
    write_csv,
    write_json,
)


async def run_live(
    *,
    budget: float,
    symbol_count: int,
    seed: int,
) -> int:
    ensure_report_dir()
    pool = await fetch_tradable_usdt_symbols()
    symbols = pick_live_symbols(pool, count=symbol_count, seed=seed)
    print(f"Live dry-run: {len(symbols)} symbols @ {budget} USDT")

    rows = []
    fetch_failed = []
    for sym in symbols:
        try:
            decision = await calculate_live_symbol(sym, budget=budget)
            errors, warnings, extras = validate_live_decision(decision, symbol=sym)
            row = decision_to_live_row(decision, symbol=sym, errors=errors, warnings=warnings, extras=extras)
            rows.append(row)
            status = "OK" if not errors else "ERR"
            print(f"  [{status}] {sym} regime={row.get('regime')} profile={str(row.get('final_profile_id'))[:36]}")
        except Exception as exc:
            fetch_failed.append(sym)
            rows.append(
                {
                    "symbol": sym,
                    "data_fetch_status": "DATA_FETCH_FAILED",
                    "errors": f"DATA_FETCH_FAILED:{exc}",
                    "warnings": "",
                    "workability_score": 0,
                }
            )
            print(f"  [FAIL] {sym}: {exc}")

    payload = {
        "generated_at": utc_now_iso(),
        "budget_usdt": budget,
        "seed": seed,
        "symbols_requested": symbol_count,
        "symbols_tested": len(symbols),
        "data_fetch_failed": fetch_failed,
        "results": rows,
    }
    write_json(REPORT_DIR / "live_50_symbols_results.json", payload)

    csv_fields = [
        "symbol",
        "regime",
        "behavior_id",
        "severity",
        "profile_id",
        "final_profile_id",
        "apply_policy",
        "base_pct",
        "quote_pct",
        "buy_grid_distances",
        "sell_grid_distances",
        "rebuy_enabled",
        "profit_sell_enabled",
        "workability_score",
        "errors",
        "warnings",
        "data_fetch_status",
    ]
    write_csv(REPORT_DIR / "live_50_symbols_results.csv", rows, csv_fields)

    summary_lines = [
        "# Dynamic Param V6 — Live 50 Symbol Dry-Run Summary",
        "",
        f"Generated: {utc_now_iso()}",
        f"Budget: {budget} USDT · Seed: {seed}",
        "",
        f"Symbols tested: {len(symbols)}",
        f"Data fetch failures: {len(fetch_failed)}",
        "",
        "## Results",
        "",
        "| symbol | regime | behavior | severity | workability | errors | warnings |",
        "|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        summary_lines.append(
            f"| {row.get('symbol')} | {row.get('regime', '')} | {row.get('behavior_id', '')} | "
            f"{row.get('severity', '')} | {row.get('workability_score', '')} | "
            f"{str(row.get('errors', ''))[:50]} | {str(row.get('warnings', ''))[:50]} |"
        )
    if fetch_failed:
        summary_lines.extend(["", "## Data fetch failures", "", ", ".join(fetch_failed)])

    (REPORT_DIR / "live_50_symbols_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    agg = merge_report_summary(aggregate_findings([], [], live_rows=rows))
    write_json(REPORT_DIR / "critical_findings.json", agg)
    (REPORT_DIR / "logic_errors_report.md").write_text(
        render_logic_errors_report(agg, live_rows=rows),
        encoding="utf-8",
    )

    critical = [
        r
        for r in rows
        if any(e.startswith("ERROR_") for e in str(r.get("errors") or "").split(";") if e.strip())
    ]
    if critical:
        print(f"FAIL: {len(critical)} symbols with ERROR_* findings", file=sys.stderr)
        return 1
    print(f"Reports written to {REPORT_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="V6 live 50-symbol dry-run")
    parser.add_argument("--budget", type=float, default=500.0)
    parser.add_argument("--symbols", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    return asyncio.run(run_live(budget=args.budget, symbol_count=args.symbols, seed=args.seed))


if __name__ == "__main__":
    raise SystemExit(main())
