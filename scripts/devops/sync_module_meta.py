#!/usr/bin/env python3
"""
Regenerate grouped file inventory in _meta/MODULE.md.
Usage: python scripts/sync_module_meta.py
"""

from __future__ import annotations
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIP_PARTS = {"__pycache__", "_meta", ".pytest_cache", ".git", ".venv"}

MODULES: list[tuple[str, list[str], list[str]]] = [
    ("ops", ["*"], []),
    (
        "app",
        ["*.py"],
        [
            "botengine",
            "api",
            "services",
            "bot",
            "db",
            "core",
            "middleware",
            "observability",
            "utils",
        ],
    ),
    ("app/botengine", ["*.py"], ["strategies", "adapters"]),
    ("app/api", ["*.py"], ["routes", "utils"]),
    ("app/services", ["*.py"], []),
    ("manager_server", ["*.py"], ["ui"]),
    ("ui", ["*.html"], ["assets", "vendor"]),
    (
        "scripts",
        ["*.py", "*.sh", "*.bat", "*.ps1"],
        ["runtime", "devops", "audit", "perf", "maintenance", "migrations"],
    ),
    ("tests", ["*.py"], []),
    ("deploy", ["*"], []),
]


def _collect_files(base: Path, patterns: list[str], subdirs: list[str]) -> list[Path]:
    found: list[Path] = []
    for pat in patterns:
        for p in base.glob(pat):
            if p.is_file():
                found.append(p)
    for sd in subdirs:
        d = base / sd
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file() and not any(s in SKIP_PARTS for s in p.parts):
                    if p.suffix in (".pyc",) or p.name.startswith("."):
                        continue
                    found.append(p)
    return sorted(set(found), key=lambda x: x.as_posix())


def _group_by_folder(base: Path, files: list[Path]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in files:
        rel = p.relative_to(base)
        if len(rel.parts) == 1:
            key = "(kök)"
        else:
            key = rel.parts[0] + "/"
        groups[key].append(rel.as_posix() if len(rel.parts) > 1 else rel.name)
    return dict(sorted(groups.items(), key=lambda kv: (kv[0] != "(kök)", kv[0])))


def _render_inventory(base: Path, files: list[Path]) -> str:
    if not files:
        return "_Dosya yok._\n"
    groups = _group_by_folder(base, files)
    lines = ["## Dosya envanteri\n"]
    for folder, names in groups.items():
        lines.append(f"### `{folder}`\n")
        lines.append("```")
        lines.extend(names)
        lines.append("```\n")
    lines.append(
        f"*Envanter: {date.today().isoformat()} — `python scripts/sync_module_meta.py`*\n"
    )
    return "\n".join(lines)


def _replace_inventory(meta_path: Path, block: str) -> None:
    text = meta_path.read_text(encoding="utf-8")
    if "## Dosya envanteri" in text:
        text = re.sub(
            r"## Dosya envanteri\n.*", block.rstrip() + "\n", text, flags=re.DOTALL
        )
    else:
        text = text.rstrip() + "\n\n" + block
    meta_path.write_text(text, encoding="utf-8")


def main() -> None:
    for rel, patterns, subdirs in MODULES:
        base = ROOT / rel
        meta = base / "_meta" / "MODULE.md"
        if not base.is_dir() or not meta.is_file():
            continue
        files = _collect_files(base, patterns, subdirs)
        block = _render_inventory(base, files)
        _replace_inventory(meta, block)
        print(f"ok  {rel}/_meta/MODULE.md  ({len(files)} dosya)")


if __name__ == "__main__":
    main()
