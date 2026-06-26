#!/usr/bin/env python3
"""Batch E2E audit for Param Assistant user flow (black-box HTTP)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.param_pool.param_assistant_e2e_lib import (  # noqa: E402
    DEFAULT_BUDGETS,
    DEFAULT_SYMBOLS,
    ParamAssistantHttpClient,
    acceptance_passes,
    iter_audit_matrix,
    run_batch_audit,
    write_audit_reports,
)


def _parse_csv_floats(raw: str) -> tuple:
    return tuple(float(x.strip()) for x in raw.split(",") if x.strip())


def _parse_csv_str(raw: str) -> tuple:
    return tuple(x.strip().upper() for x in raw.split(",") if x.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Param Assistant E2E batch audit (user flow)")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated USDT pairs",
    )
    parser.add_argument(
        "--budgets",
        default=",".join(str(int(b)) for b in DEFAULT_BUDGETS),
        help="Comma-separated USDT budgets",
    )
    parser.add_argument(
        "--scenarios",
        default="first_start,has_base",
        help="Balance scenarios: first_start,has_base,only_base,low_budget,normal_budget",
    )
    parser.add_argument(
        "--first-start-buy-only",
        action="store_true",
        help="Also run matrix with first_start_buy_only=true",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional running API base URL (default: in-process TestClient)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Always dry-run (default true; requests include dry_run=true)",
    )
    parser.add_argument(
        "--md-out",
        default=str(ROOT / "docs" / "PARAM_ASSISTANT_E2E_AUDIT.md"),
    )
    parser.add_argument(
        "--json-out",
        default=str(ROOT / "docs" / "PARAM_ASSISTANT_E2E_AUDIT.json"),
    )
    args = parser.parse_args()

    symbols = _parse_csv_str(args.symbols)
    budgets = _parse_csv_floats(args.budgets)
    scenarios = _parse_csv_str(args.scenarios)
    fs_variants = (False, True) if args.first_start_buy_only else (False,)

    client = ParamAssistantHttpClient(base_url=args.base_url or None)
    matrix = iter_audit_matrix(symbols, budgets, scenarios, first_start_variants=fs_variants)
    print(f"Running {len(matrix)} Param Assistant user-flow cases…")
    rows = run_batch_audit(client, matrix)
    flags = write_audit_reports(rows, md_path=Path(args.md_out), json_path=Path(args.json_out))
    print(f"Wrote {args.md_out}")
    print(f"Wrote {args.json_out}")
    print(
        f"total={flags['total']} failed_cases={flags['failed_cases']} "
        f"deployable_grid={flags['deployable_grid']} runtime={flags['runtime']}"
    )
    if not acceptance_passes(flags):
        print("ACCEPTANCE: FAIL — see report for invariant detail", file=sys.stderr)
        return 1
    print("ACCEPTANCE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
