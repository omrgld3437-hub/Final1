"""Dependency graph builder — import/call graph for DPS modules."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Set


def _imports_in_file(path: Path) -> Set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def build_dependency_graph(project_root: Path) -> Dict[str, Any]:
    dps_root = project_root / "app/services/dynamic_param_score"
    nodes: List[str] = []
    edges: List[Dict[str, str]] = []
    if not dps_root.exists():
        return {"nodes": [], "edges": [], "md": "DPS path not found"}

    for path in sorted(dps_root.rglob("*.py")):
        rel = str(path.relative_to(project_root))
        nodes.append(rel)
        for imp in _imports_in_file(path):
            if imp == "app":
                mod = str(path.relative_to(dps_root)).replace("/", ".").replace(".py", "")
                target_prefix = f"app/services/dynamic_param_score"
                edges.append({"from": rel, "to": f"{target_prefix}/...", "type": "internal"})

    md_lines = ["# DPS Dependency Graph", "", "## Core pipeline", ""]
    md_lines.extend([
        "```",
        "engine.py",
        "  → indicators, scoring, regime",
        "  → param_pool/selector.select_and_render",
        "  → safety.apply_safety_gates",
        "  → feasibility, allocation, rebalance",
        "  → explain.build_explanation",
        "  → adapters.params_to_grid_config",
        "```",
        "",
        "## Module count",
        f"- Python modules under DPS: {len(nodes)}",
    ])
    return {
        "nodes": nodes,
        "edges": edges[:500],
        "md": "\n".join(md_lines),
        "json_graph": {"nodes": nodes, "edges": edges[:500]},
    }
