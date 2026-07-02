#!/usr/bin/env python3
"""50 coin × 3 budget Param Assistant user-flow E2E audit (black-box HTTP, dry-run)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.param_pool.param_assistant_e2e_lib import ParamAssistantHttpClient  # noqa: E402
from tools.param_pool.param_assistant_user_flow_50coin_lib import (  # noqa: E402
    DEFAULT_BUDGETS,
    auto50_symbols,
    final_acceptance_passes,
    render_markdown_50coin,
    run_50coin_matrix,
    summarize_runs,
    write_anomalies_md,
    write_consolidated_report,
    write_json_report,
    write_jsonl_raw,
)


def _parse_budgets(raw: str) -> tuple:
    return tuple(float(x.strip()) for x in raw.split(",") if x.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Param Assistant 50-coin user-flow E2E audit (dry-run, black-box HTTP)"
    )
    parser.add_argument("--mode", default="test-local", help="test-local | live (always dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument(
        "--symbols",
        default="auto50",
        help="auto50 or comma-separated USDT pairs",
    )
    parser.add_argument("--budgets", default="50,100,1000")
    parser.add_argument("--base-url", default="", help="Optional remote API base URL")
    parser.add_argument(
        "--output-md",
        default=str(ROOT / "reports" / "PARAM_ASSISTANT_USER_FLOW_50COIN_AUDIT.md"),
    )
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "PARAM_ASSISTANT_USER_FLOW_50COIN_AUDIT.json"),
    )
    parser.add_argument(
        "--raw-jsonl",
        default=str(ROOT / "reports" / "PARAM_ASSISTANT_USER_FLOW_50COIN_RAW_RESPONSES.jsonl"),
    )
    parser.add_argument(
        "--anomalies-md",
        default=str(ROOT / "reports" / "PARAM_ASSISTANT_USER_FLOW_50COIN_ANOMALIES.md"),
    )
    parser.add_argument(
        "--consolidated-md",
        default=str(ROOT / "reports" / "PARAM_ASSISTANT_USER_FLOW_50COIN_FULL_AUDIT.md"),
    )
    parser.add_argument("--limit-symbols", type=int, default=0, help="Debug: cap symbol count")
    args = parser.parse_args()

    if args.symbols.strip().lower() == "auto50":
        symbols = auto50_symbols()
    else:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if args.limit_symbols > 0:
        symbols = symbols[: args.limit_symbols]

    budgets = _parse_budgets(args.budgets)
    mode = args.mode

    client = ParamAssistantHttpClient(base_url=args.base_url or None)

    def _progress(msg: str) -> None:
        print(msg, flush=True)

    print(
        f"Param Assistant 50-coin user-flow audit — mode={mode} dry_run={args.dry_run} "
        f"symbols={len(symbols)} budgets={budgets} total={len(symbols) * len(budgets)}"
    )
    runs = run_50coin_matrix(client, symbols, budgets, mode=mode, progress=_progress)
    summary = summarize_runs(runs)

    md_path = Path(args.output_md)
    json_path = Path(args.output_json)
    jsonl_path = Path(args.raw_jsonl)
    anom_path = Path(args.anomalies_md)
    full_path = Path(args.consolidated_md)

    md_body = render_markdown_50coin(runs, summary, mode=mode)
    md_path.write_text(md_body, encoding="utf-8")
    write_json_report(runs, summary, json_path, mode=mode)
    write_jsonl_raw(runs, jsonl_path)
    write_anomalies_md(runs, anom_path)
    write_consolidated_report(
        runs,
        summary,
        full_path,
        mode=mode,
        anomalies_md=anom_path.read_text(encoding="utf-8") if anom_path.exists() else "",
    )

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {jsonl_path}")
    print(f"Wrote {anom_path}")
    print(f"Wrote {full_path}")
    print(
        f"Summary: ok={summary.get('successful')} fail={summary.get('failed')} "
        f"blockers={summary.get('blocker_count')} warnings={summary.get('warning_count')}"
    )

    if not final_acceptance_passes(summary):
        print("FINAL ACCEPTANCE: FAIL — see consolidated report", file=sys.stderr)
        return 1
    print("FINAL ACCEPTANCE: PASS (blocker + critical thresholds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
