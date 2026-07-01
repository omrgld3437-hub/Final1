#!/usr/bin/env python3
"""Staging validation + V5/V6 comparison report for Dynamic Param."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SYMBOLS = ("BTCUSDT", "ETHUSDT", "MANTAUSDT", "SYNUSDT", "ADAUSDT", "REUSDT")
BUDGET = 500.0
REPORT_DIR = ROOT / "reports" / "dynamic_param_v6"
REPORT_FILE = REPORT_DIR / "v5_v6_comparison_report.md"
JSON_FILE = REPORT_DIR / "v5_v6_comparison_raw.json"

ALLOWED_TRAILING = {0.5, 0.8, 1.1, 1.4, 1.7, 2.0, 2.3, 2.6, 2.9}
V5_FORBIDDEN = ("DPLV5", "shelf", "fee_efficiency", "scenario_alignment", "fallback shelf")


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _pct5(v: float) -> bool:
    return abs(v * 100 - round(v * 100 / 5) * 5) < 0.01 or abs(v - round(v / 5) * 5) < 0.01


def _profit_step(v: Optional[float]) -> bool:
    if v is None:
        return True
    return abs(v * 2 - round(v * 2)) < 0.01


def validate_v6_decision(decision, *, symbol: str) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    tel = decision.telemetry or {}
    raw = json.dumps(tel).lower()
    for token in V5_FORBIDDEN:
        if token.lower() in raw and token.lower() != "shelf":
            if "dplv5" in raw or "v5_shelf" in raw or "fee_efficiency" in raw:
                errors.append(f"v5_artifact:{token}")
    if "dplv5" in raw:
        errors.append("dplv5_in_telemetry")
    if decision.params is None:
        errors.append("params_empty")
    v6d = tel.get("v6_display") or {}
    for key in (
        "profile_id",
        "final_profile_id",
        "scenario_identity",
        "behavior_id",
        "severity",
        "adjuster_trace",
    ):
        if key not in v6d:
            errors.append(f"missing_v6_display.{key}")
    pid = str(v6d.get("profile_id") or decision.selected_profile_name or "")
    if not pid.startswith("DPLV6_"):
        errors.append(f"profile_id_not_dplv6:{pid}")
    base = int(v6d.get("base_allocation_pct") or 0)
    quote = int(v6d.get("quote_allocation_pct") or 0)
    if base + quote != 100:
        errors.append(f"alloc_sum:{base}+{quote}")
    if base % 5 != 0:
        errors.append(f"base_not_5_step:{base}")
    for dist in (v6d.get("buy_grid_distances_pct") or []) + (v6d.get("sell_grid_distances_pct") or []):
        if int(dist) != float(dist):
            errors.append(f"grid_distance_not_int:{dist}")
    for amt in (v6d.get("buy_grid_amounts_pct") or []) + (v6d.get("sell_grid_amounts_pct") or []):
        if int(amt) % 5 != 0:
            errors.append(f"grid_amount_not_5_step:{amt}")
    for trail_key in ("buy_trailing_pct", "sell_trailing_pct", "rebuy_trailing_pct", "profit_sell_trailing_pct"):
        tv = v6d.get(trail_key)
        if tv is not None and float(tv) not in ALLOWED_TRAILING:
            errors.append(f"trailing_not_allowed:{trail_key}={tv}")
    for pk in ("rebuy_trigger_pct", "profit_sell_trigger_pct"):
        if not _profit_step(v6d.get(pk)):
            errors.append(f"profit_not_half_step:{pk}")
    trace = v6d.get("adjuster_trace") or []
    if not trace:
        errors.append("adjuster_trace_empty")
    elif isinstance(trace, list) and trace and isinstance(trace[0], dict):
        names = {t.get("name") for t in trace}
        for required in (
            "data_quality",
            "btc_context",
            "asset_fragility",
            "volatility",
            "liquidity",
            "support_resistance",
            "fake_move",
            "delta_limiter",
            "budget_scaler",
            "exchange_validator",
        ):
            if required not in names:
                errors.append(f"adjuster_trace_missing:{required}")
    else:
        errors.append("adjuster_trace_not_structured")
    if decision.params:
        p = decision.params
        if p.pool_version != "v6":
            errors.append(f"pool_version:{p.pool_version}")
        if p.rebuy_enabled and p.buy_grid_count == 0 and p.sell_grid_count > 0:
            if p.rebuy_trigger_pct is None:
                errors.append("post_sell_rebuy_missing_trigger")
    if tel.get("engine_version", "").endswith("V6") is False and "v6" not in str(tel.get("pool_version", "")):
        warnings.append("engine_version_not_v6_marker")
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def _grid_summary(params) -> str:
    if params is None:
        return "—"
    buy = params.buy_grid_ladder_pcts or []
    sell = params.sell_grid_ladder_pcts or []
    buy_w = [round(x * 100) for x in (params.buy_qty_distribution or [])]
    sell_w = [round(x * 100) for x in (params.sell_qty_distribution or [])]
    parts = []
    if buy:
        parts.append("buy:" + ",".join(f"{d}%/{w}%" for d, w in zip(buy, buy_w)))
    if sell:
        parts.append("sell:" + ",".join(f"+{d}%/{w}%" for d, w in zip(sell, sell_w)))
    return " · ".join(parts) or "—"


def _profit_summary(params) -> str:
    if params is None:
        return "—"
    return (
        f"rebuy={params.rebuy_enabled}@{params.rebuy_trigger_pct}/{params.rebuy_trail_pct} "
        f"resell={params.resell_enabled}@{params.resell_trigger_pct}/{params.resell_trail_pct} "
        f"trail={params.trailing_callback_pct}"
    )


def extract_v5(decision) -> Dict[str, Any]:
    tel = decision.telemetry or {}
    pool = tel.get("param_pool") or {}
    ctx = pool.get("selection_context") or {}
    p = decision.params
    fee = ctx.get("cost_resolution") or {}
    return {
        "route": ctx.get("v5_route_key") or ctx.get("route_key") or "—",
        "shelf": ctx.get("v5_shelf_id") or pool.get("selected_template_key") or decision.selected_profile_name,
        "base_quote": (
            f"{round((p.base_alloc_frac if p else 0) * 100, 1)}/"
            f"{round((p.quote_alloc_frac if p else 0) * 100, 1)}"
            if p
            else "—"
        ),
        "grids": _grid_summary(p),
        "profit_trailing": _profit_summary(p),
        "fee": (
            f"tier={fee.get('fee_tier')} floor={fee.get('cost_floor_pct')} "
            f"available={fee.get('fee_data_available', True)}"
            if fee
            else f"friction={ctx.get('total_friction_pct')}"
        ),
        "action": decision.final_action,
        "deployable": decision.deployable,
        "blocking": decision.blocking_reasons,
    }


def extract_v6(decision) -> Dict[str, Any]:
    tel = decision.telemetry or {}
    v6d = tel.get("v6_display") or {}
    scen = v6d.get("scenario_identity") or {}
    trace = v6d.get("adjuster_trace") or []
    trace_sum = ", ".join(
        f"{t.get('name')}:{t.get('class')}" for t in trace if isinstance(t, dict)
    )[:200]
    return {
        "scenario": f"{scen.get('regime_id')}-{scen.get('sub_id')}-{scen.get('micro_id')}",
        "behavior": v6d.get("behavior_id"),
        "severity": v6d.get("severity"),
        "profile_id": v6d.get("profile_id"),
        "final_profile_id": v6d.get("final_profile_id"),
        "base_quote": f"{v6d.get('base_allocation_pct')}/{v6d.get('quote_allocation_pct')}",
        "buy_grids": v6d.get("buy_grid_distances_pct"),
        "sell_grids": v6d.get("sell_grid_distances_pct"),
        "post_sell_buyback": (
            f"enabled={v6d.get('post_sell_buyback_enabled')} "
            f"trigger={v6d.get('post_sell_buyback_trigger_pct')} "
            f"trail={v6d.get('post_sell_buyback_trailing_pct')}"
        ),
        "profit_sell": (
            f"enabled={v6d.get('profit_sell_enabled')} "
            f"trigger={v6d.get('profit_sell_trigger_pct')} "
            f"trail={v6d.get('profit_sell_trailing_pct')}"
        ),
        "adjuster_trace_summary": trace_sum,
        "action": decision.final_action,
        "deployable": decision.deployable,
        "normal_buy_enabled": v6d.get("normal_buy_enabled"),
        "rebuy_enabled": v6d.get("rebuy_enabled"),
        "buy_grid_count": v6d.get("buy_grid_count"),
    }


def compare_decision(v5: Dict[str, Any], v6: Dict[str, Any], v6_val: ValidationResult) -> Dict[str, str]:
    if not v6_val.ok:
        return {"decision": "V6 riskli", "reason": "; ".join(v6_val.errors[:5])}
    v5_wait = str(v5.get("action", "")).upper() in ("WAIT", "WAIT_SAFETY", "NO_TRADE")
    v6_params = v6.get("deployable") or v6.get("action") == "CONTROLLED_GRID"
    if v5_wait and v6_params:
        fee_note = "fee" in str(v5.get("fee", "")).lower()
        return {
            "decision": "V6 daha doğru",
            "reason": (
                "V5 bekle/engel iken V6 katalog profili üretti"
                + ("; V5 fee katmanı etkili olabilir" if fee_note else "")
            ),
        }
    if v6.get("behavior") == "PB11" and v6.get("rebuy_enabled") and v6.get("buy_grid_count") == 0:
        return {
            "decision": "V6 daha doğru",
            "reason": "PB11 crash: normal alış kapalı, post-sell rebuy açık (V5 bu deseni garanti etmez)",
        }
    if v5.get("shelf", "").startswith("DPLV5") and str(v6.get("profile_id", "")).startswith("DPLV6"):
        return {
            "decision": "eşdeğer / V6 tercih",
            "reason": "Her iki motor parametre üretti; V6 kafes + adjuster trace ile daha deterministik",
        }
    return {"decision": "eşdeğer", "reason": "Her iki motor geçerli çıktı verdi; majör mantık hatası görülmedi"}


async def calculate_symbol(symbol: str, version: str):
    os.environ["DPS_ENGINE_VERSION"] = version
    from app.services.dynamic_param_score import get_engine
    from app.services.dynamic_param_score.consumer_policy import build_param_assistant_context
    from app.services.dynamic_param_score.data_collector import (
        collect_market_data,
        default_exchange_constraints,
        portfolio_from_budget,
    )

    market = await collect_market_data(symbol)
    price = float(market.ticker_price or 0.0)
    if price <= 0:
        raise RuntimeError(f"{symbol}: invalid price")
    portfolio = portfolio_from_budget(BUDGET, price)
    constraints = default_exchange_constraints(symbol)
    ctx = build_param_assistant_context(
        budget_usdt=BUDGET,
        portfolio=portfolio,
        allow_no_trade=True,
    )
    return get_engine().calculate_decision(
        symbol=symbol,
        market_data=market,
        portfolio_state=portfolio,
        exchange_constraints=constraints,
        bot_context=ctx,
    )


async def run_staging() -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_usdt": BUDGET,
        "dps_engine_version_env": os.getenv("DPS_ENGINE_VERSION"),
        "symbols": {},
        "acceptance": {},
    }
    all_v6_ok = True
    for symbol in SYMBOLS:
        sym_result: Dict[str, Any] = {}
        try:
            v5_dec = await calculate_symbol(symbol, "v5")
            sym_result["v5"] = extract_v5(v5_dec)
        except Exception as e:
            sym_result["v5_error"] = str(e)
            v5_dec = None
        try:
            v6_dec = await calculate_symbol(symbol, "v6")
            v6_val = validate_v6_decision(v6_dec, symbol=symbol)
            sym_result["v6"] = extract_v6(v6_dec)
            sym_result["v6_validation"] = {"ok": v6_val.ok, "errors": v6_val.errors, "warnings": v6_val.warnings}
            if v5_dec:
                sym_result["comparison"] = compare_decision(
                    sym_result.get("v5") or {},
                    sym_result["v6"],
                    v6_val,
                )
            if not v6_val.ok:
                all_v6_ok = False
        except Exception as e:
            sym_result["v6_error"] = str(e)
            all_v6_ok = False
        results["symbols"][symbol] = sym_result
    results["acceptance"]["staging_v6_all_ok"] = all_v6_ok
    results["acceptance"]["v5_removal_ready"] = all_v6_ok
    return results


def render_report(data: Dict[str, Any]) -> str:
    lines = [
        "# Dynamic Param V5/V6 Staging Comparison Report",
        "",
        f"Generated: {data.get('generated_at')}",
        f"Budget: {data.get('budget_usdt')} USDT",
        "",
        "## Acceptance summary",
        "",
    ]
    acc = data.get("acceptance") or {}
    lines.append(f"- Staging V6 all OK: **{acc.get('staging_v6_all_ok')}**")
    lines.append(f"- V5 removal ready: **{acc.get('v5_removal_ready')}** (manual sign-off still required)")
    lines.append("")
    lines.append("## Per-symbol comparison")
    lines.append("")
    for symbol, sym in (data.get("symbols") or {}).items():
        lines.append(f"### {symbol}")
        lines.append("")
        if sym.get("v5_error"):
            lines.append(f"- V5 error: `{sym['v5_error']}`")
        if sym.get("v6_error"):
            lines.append(f"- V6 error: `{sym['v6_error']}`")
        v5 = sym.get("v5") or {}
        v6 = sym.get("v6") or {}
        val = sym.get("v6_validation") or {}
        lines.append(f"| Field | V5 | V6 |")
        lines.append(f"|-------|----|----|")
        lines.append(f"| Route / shelf | `{v5.get('route', '—')}` / `{v5.get('shelf', '—')}` | scenario `{v6.get('scenario')}` |")
        lines.append(f"| Base / quote | {v5.get('base_quote', '—')} | {v6.get('base_quote', '—')} |")
        lines.append(f"| Buy grids | {v5.get('grids', '—')} | {v6.get('buy_grids')} |")
        lines.append(f"| Sell grids | — | {v6.get('sell_grids')} |")
        lines.append(f"| Profit / trailing | {v5.get('profit_trailing', '—')} | {v6.get('post_sell_buyback')} · {v6.get('profit_sell')} |")
        lines.append(f"| Fee behavior | {v5.get('fee', '—')} | none (cost floor only) |")
        lines.append(f"| Behavior / severity | — | {v6.get('behavior')} / {v6.get('severity')} |")
        lines.append(f"| profile_id | — | `{v6.get('profile_id')}` |")
        lines.append(f"| final_profile_id | — | `{v6.get('final_profile_id')}` |")
        lines.append(f"| Adjuster trace | — | {v6.get('adjuster_trace_summary', '—')} |")
        lines.append(f"| V6 validation | — | OK={val.get('ok')} errors={val.get('errors')} |")
        cmp_ = sym.get("comparison") or {}
        lines.append("")
        lines.append(f"**Decision:** {cmp_.get('decision', '—')}")
        lines.append(f"**Reason:** {cmp_.get('reason', '—')}")
        lines.append("")
    lines.append("## PB11 / post-sell buyback check")
    lines.append("")
    for symbol, sym in (data.get("symbols") or {}).items():
        v6 = sym.get("v6") or {}
        if v6.get("behavior") == "PB11" or "PB11" in str(v6.get("profile_id", "")):
            lines.append(
                f"- {symbol}: normal_buy={v6.get('normal_buy_enabled')} buy_count={v6.get('buy_grid_count')} "
                f"rebuy={v6.get('rebuy_enabled')} · {v6.get('post_sell_buyback')}"
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- V5 **not removed** in this pass; removal PR: `remove-dynamic-param-v5-after-v6-staging-validation`")
    lines.append("- Set staging: `export DPS_ENGINE_VERSION=v6`")
    return "\n".join(lines)


async def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = await run_staging()
    REPORT_FILE.write_text(render_report(data), encoding="utf-8")
    JSON_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {REPORT_FILE}")
    print(f"Raw JSON: {JSON_FILE}")
    print(f"Staging V6 all OK: {data['acceptance']['staging_v6_all_ok']}")
    return 0 if data["acceptance"]["staging_v6_all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
