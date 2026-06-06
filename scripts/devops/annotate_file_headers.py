#!/usr/bin/env python3
"""
Kaynak dosyalarina tek satirlik aciklama ekler (docstring / yorum).
Mevcut docstring veya ust yorum varsa dokunmaz.

Usage: python3 scripts/annotate_file_headers.py [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {
    ".venv",
    ".git",
    "__pycache__",
    "_meta",
    ".pytest_cache",
    "node_modules",
    "vendor",
}
SKIP_SUFFIX = {
    ".pyc",
    ".db",
    ".db-shm",
    ".db-wal",
    ".png",
    ".jpg",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".json",
    ".xml",
    ".css",
    ".map",
}

HINTS: dict[str, str] = {
    "main.py": "FastAPI giris; UI mount, startup, route kaydi.",
    "worker_main.py": "Bot Engine worker girisi; komut kuyrugu ve tick dongusu.",
    "orchestrator.py": "Legacy bot dongusu; v5 disi modda bot tick.",
    "bot_run.py": "v5 tek bot tick; strateji + execution cagrisi.",
    "scheduler.py": "v5 heap zamanlayici; bot next_run_at.",
    "execution.py": "Emir gonderimi; intent ledger + Binance adapter.",
    "bots_engine.py": "Bot start/stop/detail API; worker komut kuyrugu.",
    "routes.py": "Dashboard REST API; bot listesi, wallet, fiyat.",
    "dashboard.js": "Ana panel JS; bot olusturma, liste, finance.",
    "app.py": "Manager FastAPI; process kontrol, log tail.",
    "state.py": "Manager durum; PID, port, servis baslat/durdur.",
}


def _guess(rel: str) -> str:
    name = Path(rel).name
    if name in HINTS:
        return HINTS[name]
    stem = Path(rel).stem.replace("_", " ")
    parent = Path(rel).parent.name
    if name == "__init__.py":
        return f"{parent} Python paketi."
    if rel.endswith(".py"):
        return f"{stem} modulu ({parent}/)."
    if rel.endswith((".js", ".html")):
        return f"{stem} ({parent}/)."
    if rel.endswith((".sh", ".command")):
        return f"Shell script: {stem}."
    if rel.endswith(".bat"):
        return f"Windows batch: {stem}."
    return f"Dosya: {rel}"


def _has_py_doc(text: str) -> bool:
    t = text.lstrip("\ufeff")
    if t.startswith('"""') or t.startswith("'''"):
        return True
    if t.startswith("#!"):
        rest = t.split("\n", 1)[-1].lstrip()
        return rest.startswith('"""') or rest.startswith("'''")
    return False


def _has_top_comment(text: str, prefix: str) -> bool:
    for line in text.splitlines()[:5]:
        s = line.strip()
        if not s:
            continue
        return s.startswith(prefix)
    return False


def annotate(path: Path, dry_run: bool) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    hint = _guess(rel)
    new_text: str | None = None

    if path.suffix == ".py" and not _has_py_doc(text):
        new_text = f'"""\n{hint}\n"""\n' + text
    elif path.suffix in (".sh", ".command"):
        if _has_top_comment(text, "#"):
            return False
        if text.startswith("#!"):
            first, _, rest = text.partition("\n")
            new_text = f"{first}\n# {hint}\n{rest}"
        else:
            new_text = f"#!/bin/bash\n# {hint}\n{text}"
    elif path.suffix == ".bat" and not _has_top_comment(text, "REM"):
        new_text = f"REM {hint}\n" + text
    elif path.suffix == ".html" and not _has_top_comment(text, "<!--"):
        new_text = f"<!-- {hint} -->\n" + text
    elif (
        path.suffix == ".js"
        and not _has_top_comment(text, "//")
        and not _has_top_comment(text, "/*")
    ):
        new_text = f"// {hint}\n" + text

    if new_text and new_text != text:
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    changed = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(p in SKIP for p in path.parts):
            continue
        if path.suffix in SKIP_SUFFIX or path.name.startswith("."):
            continue
        if path.suffix not in (".py", ".js", ".html", ".sh", ".command", ".bat"):
            continue
        if annotate(path, args.dry_run):
            changed += 1
            print(
                ("would " if args.dry_run else "")
                + f"annotate {path.relative_to(ROOT)}"
            )
    print(f"{'would change' if args.dry_run else 'changed'}: {changed} files")


if __name__ == "__main__":
    main()
