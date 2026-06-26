"""Code tree auditor — project structure and legacy detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set

FOCUS_DIRS = (
    "app/services/dynamic_param_score",
    "app/botengine/dynamic",
    "app/api",
    "ui/assets",
    "tools",
)

LEGACY_PATTERNS = (
    r"FEE_BAD_WAIT",
    r"final_recommendation",
    r"wait_reason",
    r"NO_TRADE_WAIT",
    r"SAFE_WAIT",
)

KEY_FILES = [
    "app/services/dynamic_param_score/engine.py",
    "app/services/dynamic_param_score/param_pool/selector.py",
    "app/services/dynamic_param_score/safety.py",
    "app/services/dynamic_param_score/feasibility.py",
    "app/services/dynamic_param_score/adapters.py",
    "app/api/param_assistant_routes.py",
    "app/botengine/dynamic/cycle_manager.py",
    "ui/assets/modules/dashboard-create-modal.js",
]


def _walk_tree(root: Path, max_depth: int = 4) -> List[str]:
    lines: List[str] = []
    for d in FOCUS_DIRS:
        base = root / d
        if not base.exists():
            continue
        lines.append(f"## {d}/")
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(root)
            depth = len(rel.parts)
            if depth > max_depth + len(d.split("/")):
                continue
            if any(x in rel.parts for x in (".git", "__pycache__", "node_modules", ".param_dynamic")):
                continue
            lines.append(f"- `{rel}`")
    return lines


def _scan_legacy(root: Path) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    for d in ("app", "ui"):
        base = root / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in (".py", ".js", ".ts", ".tsx"):
                continue
            if any(x in path.parts for x in ("__pycache__", ".param_dynamic", "node_modules")):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in LEGACY_PATTERNS:
                if re.search(pat, text):
                    hits.append({"file": str(path.relative_to(root)), "pattern": pat})
    return hits[:200]


def audit_code_tree(project_root: Path) -> Dict[str, Any]:
    tree_md = "\n".join(_walk_tree(project_root))
    legacy = _scan_legacy(project_root)
    missing = [f for f in KEY_FILES if not (project_root / f).exists()]
    return {
        "code_tree_md": tree_md,
        "legacy_pattern_hits": legacy,
        "missing_key_files": missing,
        "key_files_present": len(KEY_FILES) - len(missing),
    }
