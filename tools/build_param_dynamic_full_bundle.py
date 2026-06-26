#!/usr/bin/env python3
"""Build full Param Assistant + Dynamic Mode bundle zip."""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / ".param_dynamic_full_bundle_staging"
OUT_ZIP = ROOT / f"param_dynamic_mode_full_bundle_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.zip"

LOG_SRC = ROOT / "logs" / "dynamic_param_score"
RECENT_LOG_COUNT = 80
MAX_FAULTY_LOGS = 120
FAULTY_MARKERS = (
    '"fallback_used": true',
    '"fallback_used":true',
    "FALLBACK_",
    "no_eligible_template",
    "NO_ELIGIBLE",
)


def _is_likely_faulty(chunk: str) -> bool:
    if '"fallback_used": true' in chunk or '"fallback_used":true' in chunk:
        return True
    if "FALLBACK_" in chunk or "no_eligible_template" in chunk:
        return True
    # blocking_reasons non-empty array
    for marker in ('"blocking_reasons": [', '"blocking_reasons":['):
        pos = chunk.find(marker)
        if pos == -1:
            continue
        rest = chunk[pos + len(marker) : pos + len(marker) + 80]
        if rest.lstrip().startswith("]"):
            continue
        inner = rest.split("]", 1)[0]
        if inner.strip():
            return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _extract_log_summary(path: Path) -> dict:
    summary = {
        "file": path.name,
        "decision_id": path.stem,
        "size_bytes": path.stat().st_size,
        "mtime_iso": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
    try:
        with path.open("r", encoding="utf-8") as fh:
            chunk = fh.read(65536)
        for key in (
            "final_action",
            "fallback_used",
            "selected_template_key",
            "deployable",
            "param_score",
            "regime_tag",
            "risk_state",
            "run_source",
            "symbol",
        ):
            marker = f'"{key}":'
            if marker in chunk:
                start = chunk.find(marker) + len(marker)
                end = chunk.find(",", start)
                if end == -1:
                    end = chunk.find("}", start)
                val = chunk[start:end].strip().strip('"')
                summary[key] = val
        summary["likely_faulty"] = _is_likely_faulty(chunk)
    except OSError:
        summary["error"] = "read_failed"
    return summary


def _write_readme(staging: Path, log_stats: dict) -> None:
    text = f"""# Parametre Asistanı + Dinamik Mod — Tam Paket

Oluşturulma: {datetime.now(timezone.utc).isoformat()}

## İçerik

### Kod
- `app/services/dynamic_param_score/` — merkez karar motoru (50k pool, rebalance, order intent)
- `app/api/param_assistant_routes.py`, `dynamic_param_score_routes.py`
- `app/botengine/dynamic/` — cycle_manager, overlay
- `tests/dynamic_param_score/` — testler
- `tools/param_pool/` — havuz build/validate CLI

### Veri
- `data/param_pool/v1/` — manifest, sha256, sqlite (50k template runtime)

### Dokümantasyon
- `docs/` — DYNAMIC_MODE*, audit, analysis
- `TRADE_TRAILING_MASTER_SPEC.md` — spec (param pool + katmanlar)
- `app/services/_meta/MODULE.md` — modül özeti

### Loglar
- `logs/dynamic_param_score/INDEX.jsonl` — {log_stats.get('total', 0)} karar özeti
- `logs/dynamic_param_score/faulty/` — en güncel {log_stats.get('faulty', 0)} hatalı log (tespit: {log_stats.get('faulty_total_detected', 0)}, cap={log_stats.get('faulty_capped', False)})
- `logs/dynamic_param_score/recent/` — son {log_stats.get('recent', 0)} karar logu (tam dosya)

Kaynak sunucuda toplam log: {log_stats.get('total', 0)} dosya (~{log_stats.get('total_gb', '?')} GB).
Tam arşiv diskte: `{LOG_SRC}`

## Akış (23 katman özeti)

1. Data Collector → 2. Market Feature → 3. Regime/Risk → 4. Tier Detection
5. 50k Template Selector → 6. Renderer → 7. Target Allocation → 8. Rebalance Planner
9. Order Intent Planner → 10. Feasibility → 11. Safety → 12. Overlay → 13. Execution

## Hatalı log kriterleri

- fallback_used=true
- blocking_reasons dolu
- FALLBACK_* template key
- no_eligible_template

## Paketi açma

```bash
unzip param_dynamic_mode_full_bundle_*.zip -d ./param_dynamic_review
```
"""
    (staging / "BUNDLE_README.md").write_text(text, encoding="utf-8")


def main() -> int:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    copies = [
        (ROOT / "app" / "services" / "dynamic_param_score", STAGING / "app" / "services" / "dynamic_param_score"),
        (ROOT / "app" / "api" / "param_assistant_routes.py", STAGING / "app" / "api" / "param_assistant_routes.py"),
        (ROOT / "app" / "api" / "dynamic_param_score_routes.py", STAGING / "app" / "api" / "dynamic_param_score_routes.py"),
        (ROOT / "app" / "botengine" / "dynamic", STAGING / "app" / "botengine" / "dynamic"),
        (ROOT / "tests" / "dynamic_param_score", STAGING / "tests" / "dynamic_param_score"),
        (ROOT / "tools" / "param_pool", STAGING / "tools" / "param_pool"),
        (ROOT / "tools" / "build_param_dynamic_full_bundle.py", STAGING / "tools" / "build_param_dynamic_full_bundle.py"),
        (ROOT / "data" / "param_pool" / "v1", STAGING / "data" / "param_pool" / "v1"),
        (ROOT / "docs" / "DYNAMIC_MODE_AND_PARAM_ASSISTANT_AI_AUDIT.md", STAGING / "docs" / "DYNAMIC_MODE_AND_PARAM_ASSISTANT_AI_AUDIT.md"),
        (ROOT / "docs" / "DYNAMIC_MODE_TECHNICAL.md", STAGING / "docs" / "DYNAMIC_MODE_TECHNICAL.md"),
        (ROOT / "docs" / "DYNAMIC_MODE_FLEET_DIAGNOSIS.md", STAGING / "docs" / "DYNAMIC_MODE_FLEET_DIAGNOSIS.md"),
        (ROOT / "docs" / "dynamic_mode_analysis", STAGING / "docs" / "dynamic_mode_analysis"),
        (ROOT / "TRADE_TRAILING_MASTER_SPEC.md", STAGING / "TRADE_TRAILING_MASTER_SPEC.md"),
        (ROOT / "app" / "services" / "_meta" / "MODULE.md", STAGING / "app" / "services" / "_meta" / "MODULE.md"),
        (ROOT / "ui" / "assets" / "modules" / "dashboard-create-modal.js", STAGING / "ui" / "assets" / "modules" / "dashboard-create-modal.js"),
        (ROOT / "ui" / "assets" / "modules" / "ai-assistant-spec.js", STAGING / "ui" / "assets" / "modules" / "ai-assistant-spec.js"),
    ]

    # execution parity snippets
    exec_snip = ROOT / "app" / "botengine" / "execution.py"
    if exec_snip.exists():
        copies.append((exec_snip, STAGING / "app" / "botengine" / "execution.py"))

    orch = ROOT / "app" / "botengine" / "orchestrator.py"
    if orch.exists():
        copies.append((orch, STAGING / "app" / "botengine" / "orchestrator.py"))

    for src, dst in copies:
        print(f"copy {src.relative_to(ROOT)}")
        _copy_tree(src, dst)

    log_stats = {"total": 0, "faulty": 0, "recent": 0, "total_gb": "0"}
    if LOG_SRC.exists():
        files = sorted(LOG_SRC.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        log_stats["total"] = len(files)
        total_bytes = sum(p.stat().st_size for p in files)
        log_stats["total_gb"] = f"{total_bytes / (1024**3):.2f}"

        index_path = STAGING / "logs" / "dynamic_param_score" / "INDEX.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faulty_dir = index_path.parent / "faulty"
        recent_dir = index_path.parent / "recent"
        faulty_dir.mkdir(parents=True, exist_ok=True)
        recent_dir.mkdir(parents=True, exist_ok=True)

        faulty_ids: set[str] = set()
        with index_path.open("w", encoding="utf-8") as idx:
            for i, path in enumerate(files):
                summary = _extract_log_summary(path)
                idx.write(json.dumps(summary, ensure_ascii=False) + "\n")
                if summary.get("likely_faulty"):
                    faulty_ids.add(path.name)
                if i < RECENT_LOG_COUNT:
                    shutil.copy2(path, recent_dir / path.name)
                    log_stats["recent"] += 1

        faulty_sorted = [p for p in files if p.name in faulty_ids]
        for path in faulty_sorted[:MAX_FAULTY_LOGS]:
            shutil.copy2(path, faulty_dir / path.name)
            log_stats["faulty"] += 1
        log_stats["faulty_total_detected"] = len(faulty_ids)
        log_stats["faulty_capped"] = len(faulty_ids) > MAX_FAULTY_LOGS

        print(f"logs indexed={log_stats['total']} faulty={log_stats['faulty']} recent={log_stats['recent']}")

    _write_readme(STAGING, log_stats)

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()

    print(f"zip -> {OUT_ZIP}")
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(STAGING))

    size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"OK: {OUT_ZIP.name} ({size_mb:.1f} MB)")
    print(json.dumps(log_stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
