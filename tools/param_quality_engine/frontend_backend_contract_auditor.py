"""Frontend/backend field mapping audit."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List


FIELD_MAPPINGS = [
    ("Parametre Skoru", "param_score", "scoring.compute_param_score", True, True, True, "OK"),
    ("Rejim", "regime_tag", "regime.classify_regime", True, True, True, "OK"),
    ("Risk durumu", "risk_state", "regime.determine_risk_state", True, True, True, "OK"),
    ("Final karar", "final_action", "engine.calculate_decision", True, True, True, "OK"),
    ("Açıklama", "explain", "explain.build_explanation", True, False, True, "OK"),
    ("ADX 1h", "adx_1h", "indicators.compute_indicators", True, True, True, "OK"),
    ("RSI 1h", "rsi_1h", "indicators.compute_indicators", True, True, True, "OK"),
    ("ATR 1h", "atr_1h_pct", "indicators.compute_indicators", True, True, True, "OK"),
    ("Volatilite skoru", "volatility_score", "scoring.compute_sub_scores", True, True, True, "OK"),
    ("Toplam fee", "fee_score", "scoring.compute_sub_scores", True, True, True, "OK"),
    ("Alış gridleri", "ui_config.down.grids", "adapters._params_to_param_assistant_ui", True, True, True, "OK"),
    ("Satış gridleri", "ui_config.up.grids", "adapters._params_to_param_assistant_ui", True, True, True, "OK"),
    ("Kar alımı", "ui_config.profit.rebuy_enabled", "adapters._profit_ui_values", True, True, True, "OK"),
    ("Selection telemetry", "selection_telemetry", "selector.build_selection_diagnostics", True, True, False, "OK"),
    ("wait_reason (legacy)", "wait_reason", "legacy", False, False, False, "LEGACY"),
    ("final_recommendation (legacy)", "final_recommendation", "legacy", False, False, False, "LEGACY"),
    ("Vol 24s display", "vol_24h", "ui display only", False, False, False, "DISPLAY_ONLY"),
]


def _scan_ui_reads(project_root: Path) -> List[str]:
    hits: List[str] = []
    ui = project_root / "ui/assets/modules/dashboard-create-modal.js"
    if not ui.exists():
        return hits
    text = ui.read_text(encoding="utf-8", errors="ignore")
    for field in ("final_action", "wait_reason", "final_recommendation", "selection_telemetry", "ui_config"):
        if field in text:
            hits.append(field)
    return hits


def audit_contract(project_root: Path) -> Dict[str, Any]:
    ui_reads = _scan_ui_reads(project_root)
    rows = []
    for row in FIELD_MAPPINGS:
        ui_field, backend, src, sel, grid, expl, status = row
        rows.append({
            "ui_field": ui_field,
            "backend_field": backend,
            "source_function": src,
            "used_in_decision": sel,
            "used_in_grid_math": grid,
            "used_in_explanation": expl,
            "status": status,
        })

    adapter = project_root / "app/services/dynamic_param_score/adapters.py"
    pa_route = project_root / "app/api/param_assistant_routes.py"
    cycle_mgr = project_root / "app/botengine/dynamic/cycle_manager.py"
    route_text = pa_route.read_text(encoding="utf-8") if pa_route.exists() else ""
    cycle_text = cycle_mgr.read_text(encoding="utf-8") if cycle_mgr.exists() else ""
    same_motor = (
        "calculate_decision" in route_text
        and ("get_dps_engine" in cycle_text or "get_engine" in cycle_text)
    )

    md = [
        "# Frontend / Backend Contract",
        "",
        f"- Param assistant route present: {pa_route.exists()}",
        f"- Dynamic cycle manager present: {cycle_mgr.exists()}",
        f"- Both use same DPS motor (calculate_decision): {same_motor}",
        f"- UI reads: {', '.join(ui_reads)}",
        "",
        "## Issues",
    ]
    issues = []
    for row in FIELD_MAPPINGS:
        ui_field, backend, src, sel, grid, expl, status = row
        if (
            status == "LEGACY"
            and backend == "final_recommendation"
            and backend in ui_reads
            and "final_action" not in ui_reads
        ):
            issues.append(f"Frontend still references legacy field: {backend}")
    md.extend([f"- {i}" for i in issues] or ["- None detected"])

    csv_buf = io.StringIO()
    w = csv.DictWriter(
        csv_buf,
        fieldnames=[
            "ui_field", "backend_field", "source_function",
            "used_in_decision", "used_in_grid_math", "used_in_explanation", "status",
        ],
    )
    w.writeheader()
    w.writerows(rows)

    legacy_refs = []
    if "final_recommendation" in ui_reads and "final_action" not in ui_reads:
        legacy_refs.append("final_recommendation")
    if "wait_reason" in ui_reads and "final_action" not in ui_reads:
        legacy_refs.append("wait_reason")

    return {
        "rows": rows,
        "csv": csv_buf.getvalue(),
        "md": "\n".join(md),
        "issues": issues,
        "same_motor": same_motor,
        "legacy_ui_refs": legacy_refs,
        "primary_decision_field": "final_action" if "final_action" in ui_reads else None,
    }
