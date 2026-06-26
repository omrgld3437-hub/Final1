"""Write audit artifacts and optional zip bundle."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from tools.param_quality_engine.config import SECRET_PATTERNS, ZIP_REQUIRED_FILES
from tools.param_quality_engine.coverage_gap_analyzer import coverage_matrix_csv
from tools.param_quality_engine.profile_normalizer import behavior_fingerprint


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, obj: Any) -> None:
    _write(path, _json_dump(obj))


def _sanitize_text(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = re.sub(
            rf"({pat}\s*[=:]\s*)[^\s\"']+",
            rf"\1***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _bad_profiles_csv(bad: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["profile_id", "errors", "warnings"])
    for row in bad[:5000]:
        w.writerow([
            row.get("profile_id", ""),
            ";".join(row.get("errors") or []),
            ";".join(row.get("warnings") or []),
        ])
    return buf.getvalue()


def _top_profiles_csv(profiles: List[Dict[str, Any]], n: int = 500) -> str:
    ranked = sorted(
        profiles,
        key=lambda p: float(p.get("score_prior") or 0),
        reverse=True,
    )[:n]
    buf = io.StringIO()
    if not ranked:
        return ""
    keys = [
        "profile_id", "asset_class", "budget_class", "regime", "fee_class",
        "buy_grid_count", "sell_grid_count", "score_prior", "final_action",
    ]
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    for p in ranked:
        w.writerow({k: p.get(k) for k in keys})
    return buf.getvalue()


def _quality_scores_csv(profiles: List[Dict[str, Any]], grid_result: Dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["profile_id", "score_prior", "asset_class", "fee_class", "first_buy_grid"])
    for p in profiles[:50000]:
        buy = (p.get("buy_grid_pcts") or [0])[0]
        w.writerow([p.get("profile_id"), p.get("score_prior"), p.get("asset_class"), p.get("fee_class"), buy])
    return buf.getvalue()


def _fingerprints_csv(profiles: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["profile_id", "fingerprint"])
    for p in profiles:
        w.writerow([p.get("profile_id"), behavior_fingerprint(p)])
    return buf.getvalue()


def build_executive_summary(bundle: Dict[str, Any]) -> str:
    meta = bundle.get("load_meta") or {}
    final = bundle.get("final_report") or {}
    lines = [
        "# Executive Summary — Parametre Kalite Denetimi",
        "",
        f"**Timestamp:** {bundle.get('timestamp')}",
        f"**Mode:** {bundle.get('mode', 'legacy')}",
        f"**Profile source:** {meta.get('source')}",
        f"**Profiles audited:** {meta.get('profiles_audited') or meta.get('active_count')}",
        f"**Truncated:** {meta.get('truncated')}",
        f"**Elapsed:** {bundle.get('elapsed_seconds', '—')}s",
        "",
        "## Overall",
        f"- **GENEL SONUÇ:** {final.get('overall', 'N/A')}",
        "",
        "## Section Results",
    ]
    for section, result in (final.get("sections") or {}).items():
        lines.append(f"- **{section}:** {result}")
    lines.extend(["", "## Red Flags"])
    for flag in final.get("red_flags") or []:
        lines.append(f"- {flag}")
    if not final.get("red_flags"):
        lines.append("- None")
    acc = final.get("acceptance") or {}
    if acc:
        lines.extend(["", "## Acceptance Metrics"])
        for k, v in acc.items():
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def build_final_pass_fail(bundle: Dict[str, Any]) -> str:
    final = bundle.get("final_report") or {}
    lines = [
        "# Final PASS / FAIL Report",
        "",
        f"**GENEL SONUÇ:** {final.get('overall', 'N/A')}",
        "",
        "| Alan | Sonuç |",
        "|------|-------|",
    ]
    for k, v in (final.get("sections") or {}).items():
        lines.append(f"| {k} | {v} |")
    lines.extend(["", "## Red Flags", ""])
    for flag in final.get("red_flags") or []:
        lines.append(f"- {flag}")
    lines.extend(["", "## FAIL Detayları", ""])
    for fail in final.get("fail_details") or []:
        lines.append(f"### {fail.get('area')}")
        lines.append(f"- **Hata:** {fail.get('error')}")
        lines.append(f"- **Düzeltme:** {fail.get('fix', '—')}")
        lines.append(f"- **Öncelik:** {fail.get('priority', '—')}")
        lines.append("")
    return "\n".join(lines)


def build_error_warnings(bundle: Dict[str, Any]) -> str:
    lines = ["# Errors & Warnings", ""]
    for w in bundle.get("warnings") or []:
        lines.append(f"- WARN: {w}")
    for e in bundle.get("errors") or []:
        lines.append(f"- ERROR: {e}")
    return "\n".join(lines)


def compute_final_report(bundle: Dict[str, Any]) -> Dict[str, Any]:
    schema = bundle.get("schema") or {}
    grid = bundle.get("grid_math") or {}
    amount = bundle.get("amount_dist") or {}
    min_n = bundle.get("min_notional") or {}
    fee = bundle.get("fee_spread") or {}
    wait = bundle.get("wait") or {}
    scenario = bundle.get("scenario") or {}
    trace = bundle.get("selection_trace") or {}
    coverage = bundle.get("coverage") or {}
    dup = bundle.get("duplicates") or {}
    contract = bundle.get("contract") or {}
    load_meta = bundle.get("load_meta") or {}
    deep = bundle.get("deep_risk") or {}

    def pf(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    def sub_status(obj: Dict[str, Any], key: str = "status") -> str:
        return str(obj.get(key) or "").lower()

    total = max(schema.get("total_profiles") or load_meta.get("profiles_audited") or 1, 1)
    schema_pass_rate = (schema.get("passed") or 0) / total
    grid_pass_rate = (grid.get("passed") or 0) / total
    amount_pass_rate = (amount.get("passed") or 0) / total
    profiles_ok = (
        (load_meta.get("profiles_audited") or 0) >= 190000
        and not load_meta.get("truncated")
    )

    dup_overall = dup.get("near_duplicate_rate_pct") or 0
    unique_fps = dup.get("unique_behavior_fingerprints") or dup.get("unique_fingerprints") or 0
    cov_req = coverage.get("coverage_required_pct") or 0
    min_n_rate = min_n.get("adaptive_pass_rate_pct") or min_n.get("pass_rate_pct") or 0

    dup_ok = dup_overall <= 25 or unique_fps >= 150000
    cov_ok = cov_req >= 95.0
    grid_ok = grid_pass_rate >= 0.99 and (grid.get("critical_failures") or 0) == 0
    amount_ok = amount_pass_rate >= 0.99
    min_n_ok = min_n_rate >= 80.0

    sections = {
        "200k profil tam yüklendi": pf(profiles_ok),
        "Parametre kalitesi (schema)": pf(schema_pass_rate >= 0.99),
        "Grid matematiği": pf(grid_ok),
        "Amount distribution": pf(amount_ok),
        "Fee-spread-slippage mantığı": pf(fee.get("wait_selected_count", 1) == 0),
        "Min-notional (adaptive)": pf(min_n_ok),
        "WAIT decision mantığı": pf(wait.get("pass", False)),
        "Selection trace": pf(trace.get("all_complete", False) and trace.get("diversity_ok", False)),
        "Scenario replay": pf(
            deep.get("all_pass", scenario.get("all_pass", False))
            if deep or scenario
            else False
        ),
        "Frontend/backend uyumu": pf(
            contract.get("same_motor") and contract.get("primary_decision_field") == "final_action"
        ),
        "Coverage (required)": pf(cov_ok),
        "Duplicate oranı": pf(dup_ok),
    }

    red_flags: List[str] = []
    if load_meta.get("truncated"):
        red_flags.append("Profil seti truncated")
    if sub_status(dup) in ("fail", "critical_fail") or dup_overall > 25:
        red_flags.append(
            f"Duplicate: {dup_overall}% (unique={unique_fps}, hedef <%25 veya 150k+)"
        )
    if sub_status(coverage) == "fail" or cov_req < 95:
        red_flags.append(f"Coverage required: {cov_req}% (hedef >=95%)")
    if grid_pass_rate < 0.99:
        red_flags.append(f"Grid math fail: {grid.get('failed', 0)} ({round(100-grid_pass_rate*100,2)}%)")
    if amount_pass_rate < 0.99:
        red_flags.append(f"Amount dist fail: {amount.get('failed', 0)}")
    if min_n_rate < 80:
        red_flags.append(f"Min-notional adaptive: {min_n_rate}%")
    if fee.get("wait_selected_count", 0) > 0:
        red_flags.append("Fee_bad deployable WAIT/NO_TRADE")
    if not trace.get("diversity_ok"):
        red_flags.append("Selection trace coin çeşitliliği yetersiz")
    if not trace.get("all_complete"):
        red_flags.append("Selection trace eksik")

    fails = [k for k, v in sections.items() if v == "FAIL"]
    overall = "PASS" if not fails and not red_flags else "FAIL"

    fail_details: List[Dict[str, Any]] = []
    if dup_overall > 25:
        fail_details.append({
            "area": "Duplicate oranı",
            "error": f"near_duplicate_rate_pct={dup_overall}, unique={unique_fps}",
            "fix": "python -m tools.param_pool.enhance_pool_quality",
            "priority": "P0",
        })
    if cov_req < 95:
        fail_details.append({
            "area": "Coverage gap",
            "error": f"coverage_required_pct={cov_req}",
            "fix": "Eksik required_cells doldur",
            "priority": "P0",
        })

    return {
        "overall": overall,
        "sections": sections,
        "red_flags": red_flags,
        "fail_details": fail_details,
        "acceptance": {
            "profiles_audited": load_meta.get("profiles_audited"),
            "truncated": load_meta.get("truncated"),
            "schema_pass_rate_pct": round(schema_pass_rate * 100, 4),
            "grid_pass_rate_pct": round(grid_pass_rate * 100, 4),
            "amount_pass_rate_pct": round(amount_pass_rate * 100, 4),
            "near_duplicate_rate_pct": dup_overall,
            "unique_behavior_fingerprints": unique_fps,
            "coverage_required_pct": cov_req,
            "min_notional_adaptive_pass_rate_pct": min_n_rate,
            "duplicate_status": dup.get("status"),
            "coverage_status": coverage.get("status"),
        },
    }


def write_all_reports(output_dir: Path, bundle: Dict[str, Any]) -> List[Path]:
    bundle["final_report"] = compute_final_report(bundle)
    written: List[Path] = []
    profiles = bundle.get("profiles") or []

    files = {
        "00_EXECUTIVE_SUMMARY.md": build_executive_summary(bundle),
        "01_PARAM_LIBRARY_OVERVIEW.json": _json_dump({
            "load_meta": bundle.get("load_meta"),
            "profile_count": len(profiles),
            "pool_version": bundle.get("load_meta", {}).get("pool_version"),
        }),
        "02_PROFILE_SCHEMA_VALIDATION.json": _json_dump(bundle.get("schema")),
        "03_GRID_MATH_VALIDATION.json": _json_dump(bundle.get("grid_math")),
        "04_AMOUNT_DISTRIBUTION_VALIDATION.json": _json_dump(bundle.get("amount_dist")),
        "05_MIN_NOTIONAL_VALIDATION.json": _json_dump(bundle.get("min_notional")),
        "06_FEE_SPREAD_SLIPPAGE_VALIDATION.json": _json_dump(bundle.get("fee_spread")),
        "07_WAIT_DECISION_AUDIT.json": _json_dump(bundle.get("wait")),
        "08_SCENARIO_REPLAY_RESULTS.json": _json_dump(bundle.get("scenario")),
        "09_SELECTION_TRACE_RESULTS.json": _json_dump(bundle.get("selection_trace")),
        "10_COVERAGE_GAP_ANALYSIS.json": _json_dump(bundle.get("coverage")),
        "11_DUPLICATE_PROFILE_REPORT.json": _json_dump(bundle.get("duplicates")),
        "12_BAD_PROFILE_SAMPLES.csv": _bad_profiles_csv(
            (bundle.get("grid_math") or {}).get("bad_samples") or []
        ),
        "13_TOP_500_PROFILE_SAMPLES.csv": _top_profiles_csv(profiles, 500),
        "14_SYMBOL_REPLAY_ETHUSDT.md": bundle.get("eth_replay_md") or "",
        "15_SYMBOL_REPLAY_BTCUSDT.md": bundle.get("btc_replay_md") or "",
        "16_CODE_TREE.md": (bundle.get("code_tree") or {}).get("code_tree_md") or "",
        "17_DEPENDENCY_GRAPH.md": (bundle.get("dependency") or {}).get("md") or "",
        "18_MARKET_DATA_FLOW_TRACE.md": _json_dump(bundle.get("market_trace")),
        "19_FRONTEND_BACKEND_CONTRACT.md": (bundle.get("contract") or {}).get("md") or "",
        "20_FIELD_MAPPING_TABLE.csv": (bundle.get("contract") or {}).get("csv") or "",
        "21_TEST_LOGS.txt": _sanitize_text(bundle.get("test_logs") or ""),
        "22_ERROR_WARNINGS.md": build_error_warnings(bundle),
        "23_FINAL_PASS_FAIL_REPORT.md": build_final_pass_fail(bundle),
        "FAST_FULL_AUDIT_SUMMARY.json": _json_dump(
            (bundle.get("fast_audit") or {}).get("FAST_FULL_AUDIT_SUMMARY")
            or (bundle.get("fast_audit") or {})
        ),
        "SMART_SAMPLE_AUDIT_SUMMARY.json": _json_dump(
            (bundle.get("smart_sample") or {}).get("SMART_SAMPLE_AUDIT_SUMMARY")
            or (bundle.get("smart_sample") or {})
        ),
        "DEEP_RISK_AUDIT_SUMMARY.json": _json_dump(
            (bundle.get("deep_risk") or {}).get("DEEP_RISK_AUDIT_SUMMARY")
            or (bundle.get("deep_risk") or {})
        ),
        "profile_quality_scores.csv": _quality_scores_csv(profiles, bundle.get("grid_math") or {}),
        "profile_fingerprints.csv": _fingerprints_csv(profiles),
        "coverage_matrix.csv": coverage_matrix_csv(profiles),
        "selection_trace_samples.jsonl": "\n".join(
            json.dumps(t, ensure_ascii=False, default=str)
            for t in (bundle.get("selection_trace") or {}).get("traces") or []
        ),
    }

    optional = {
        "code_call_graph.json": _json_dump((bundle.get("dependency") or {}).get("json_graph")),
    }

    for name, content in files.items():
        p = output_dir / name
        _write(p, content)
        written.append(p)

    for name, content in optional.items():
        if content:
            p = output_dir / name
            _write(p, content)
            written.append(p)

    return written


def create_zip(output_dir: Path, timestamp: str) -> Path:
    zip_name = output_dir / f"param_quality_full_audit_{timestamp}.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(output_dir.iterdir()):
            if path.suffix == ".zip":
                continue
            if path.is_file():
                zf.write(path, arcname=path.name)
    missing = [f for f in ZIP_REQUIRED_FILES if not (output_dir / f).exists()]
    if missing:
        raise RuntimeError(f"Zip missing required files: {missing}")
    return zip_name
