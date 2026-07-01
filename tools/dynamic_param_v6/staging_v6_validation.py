#!/usr/bin/env python3
"""V6-only staging acceptance validation (post V5 removal)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.dynamic_param_v6.staging_v5_v6_comparison import (  # noqa: E402
    BUDGET,
    REPORT_DIR,
    SYMBOLS,
    ValidationResult,
    calculate_symbol,
    validate_v6_decision,
)

REPORT_FILE = REPORT_DIR / "v6_staging_validation_report.md"
JSON_FILE = REPORT_DIR / "v6_staging_validation_raw.json"


async def main() -> int:
    os.environ.setdefault("DPS_ENGINE_VERSION", "v6")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_usdt": BUDGET,
        "engine_version": os.getenv("DPS_ENGINE_VERSION", "v6"),
        "symbols": {},
        "staging_v6_all_ok": True,
    }
    lines = [
        "# V6 Staging Validation Report",
        "",
        f"Generated: {results['generated_at']}",
        f"Engine: DPS_ENGINE_VERSION={results['engine_version']}",
        "",
    ]
    for symbol in SYMBOLS:
        entry: dict = {}
        try:
            decision = await calculate_symbol(symbol, "v6")
            val = validate_v6_decision(decision, symbol=symbol)
            v6d = (decision.telemetry or {}).get("v6_display") or {}
            entry = {
                "ok": val.ok,
                "errors": val.errors,
                "profile_id": v6d.get("profile_id"),
                "behavior": v6d.get("behavior_id"),
                "severity": v6d.get("severity"),
                "rebuy_enabled": v6d.get("rebuy_enabled"),
                "buy_grid_count": v6d.get("buy_grid_count"),
                "deployable": decision.deployable,
            }
            lines.append(f"## {symbol}")
            lines.append(f"- OK: **{val.ok}** profile=`{entry['profile_id']}`")
            lines.append(f"- behavior={entry['behavior']} severity={entry['severity']}")
            lines.append(f"- rebuy={entry['rebuy_enabled']} buy_grids={entry['buy_grid_count']}")
            if val.errors:
                lines.append(f"- errors: {val.errors}")
            lines.append("")
            if not val.ok:
                results["staging_v6_all_ok"] = False
        except Exception as e:
            entry = {"ok": False, "error": str(e)}
            results["staging_v6_all_ok"] = False
            lines.append(f"## {symbol}")
            lines.append(f"- ERROR: `{e}`")
            lines.append("")
        results["symbols"][symbol] = entry
    lines.append(f"**staging V6 all OK:** {results['staging_v6_all_ok']}")
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    JSON_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {REPORT_FILE}")
    print(f"staging V6 all OK: {results['staging_v6_all_ok']}")
    return 0 if results["staging_v6_all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
