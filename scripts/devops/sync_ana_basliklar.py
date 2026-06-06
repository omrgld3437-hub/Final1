#!/usr/bin/env python3
"""
Generate docs/ANA_BASLIKLAR.md — all project files grouped under main headings.
Usage: python scripts/sync_ana_basliklar.py
"""

from __future__ import annotations
from collections import OrderedDict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "ANA_BASLIKLAR.md"

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "_meta"}
SKIP_FILES = {".DS_Store"}
SKIP_SUFFIX = {".pyc", ".db-shm", ".db-wal"}


def _match(path: str) -> str | None:
    p = path.replace("\\", "/")
    name = p.split("/")[-1]

    if (
        p.startswith("marketing/")
        or p.startswith("Omeraltinhtml/")
        or p.startswith("omeraltinhtml/")
    ):
        return "13 — Marketing sitesi (opsiyonel)"
    if p.startswith("ops/"):
        return "02 — Çalıştırma"
    if p.startswith("docs/"):
        return "11 — Dokümantasyon"
    if p.startswith("tests/"):
        return "10 — Testler"
    if p.startswith("deploy/"):
        return "09 — Deploy"
    if p.startswith("scripts/"):
        sub = p.split("/")[1] if len(p.split("/")) > 2 else ""
        labels = {
            "runtime": "08a — Scriptler (runtime)",
            "devops": "08b — Scriptler (devops)",
            "audit": "08c — Scriptler (audit)",
            "perf": "08d — Scriptler (perf)",
            "maintenance": "08e — Scriptler (maintenance)",
            "migrations": "08f — Scriptler (migrations)",
        }
        return labels.get(sub, "08 — Scriptler")
    if p.startswith("manager_server/"):
        return "07 — Manager paneli"
    if p.startswith("ui/"):
        return "06 — Web paneli"
    if p.startswith("command/"):
        return "02 — Çalıştırma"
    if p.startswith("app/botengine/"):
        return "04 — Bot Engine"
    if p.startswith("app/services/"):
        return "05 — Servisler"
    if p.startswith("app/bot/"):
        return "05b — Legacy bot"
    if p.startswith("app/api/"):
        return "03b — API"
    if p.startswith("app/"):
        if p.startswith(
            (
                "app/db/",
                "app/core/",
                "app/middleware/",
                "app/observability/",
                "app/constants/",
                "app/utils/",
            )
        ):
            return "03 — Backend (çekirdek)"
        return "03 — Backend (çekirdek)"
    if name in {
        "README.md",
        "TRADE_TRAILING_MASTER_SPEC.md",
        "requirements.txt",
        ".env.example",
        ".gitignore",
        ".gitattributes",
    } or p in {".env.example"}:
        return "01 — Spec ve yapılandırma"
    if name.endswith((".command", ".bat", ".sh")) or name in {
        "deploy.sh",
        "run.sh",
        "start",
        "Kurulum.bat",
        "guncelle.bat",
    }:
        return "02 — Çalıştırma"
    if name.endswith(".db"):
        return "12 — Yerel veri (gitignore önerilir)"
    if p.startswith("logs/") or p.startswith(".run/") or p.startswith("shared/"):
        return "12 — Çalışma zamanı (gitignore)"
    return None


def _collect() -> OrderedDict[str, list[str]]:
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIX:
            continue
        if "/_meta/" in rel:
            continue
        key = _match(rel)
        if key is None:
            key = "99 — Diğer"
        groups.setdefault(key, []).append(rel)
    return groups


def _render(groups: OrderedDict[str, list[str]]) -> str:
    lines = [
        "# Ana başlıklar — dosya dizini",
        "",
        f"**Güncelleme:** {date.today().isoformat()}",
        "",
        "Tüm proje dosyaları ana kategorilere ayrılmıştır. Kod yolları değişmez.",
        "",
        "Otomatik üretim: `python scripts/sync_ana_basliklar.py`",
        "",
        "İlgili: [CODE_TREE.md](CODE_TREE.md) · [INDEX.md](INDEX.md)",
        "",
        "---",
        "",
    ]
    order = [
        "01 — Spec ve yapılandırma",
        "02 — Çalıştırma",
        "03 — Backend (çekirdek)",
        "03b — API",
        "04 — Bot Engine",
        "05 — Servisler",
        "05b — Legacy bot",
        "06 — Web paneli",
        "07 — Manager paneli",
        "08 — Scriptler",
        "09 — Deploy",
        "10 — Testler",
        "11 — Dokümantasyon",
        "12 — Çalışma zamanı (gitignore)",
        "12 — Yerel veri (gitignore önerilir)",
        "13 — Marketing sitesi (opsiyonel)",
        "99 — Diğer",
    ]
    seen = set()
    for key in order:
        if key not in groups:
            continue
        seen.add(key)
        files = groups[key]
        lines.append(f"## {key}")
        lines.append("")
        lines.append(f"*{len(files)} dosya*")
        lines.append("")
        lines.append("```")
        lines.extend(files)
        lines.append("```")
        lines.append("")
    for key, files in groups.items():
        if key in seen:
            continue
        lines.append(f"## {key}")
        lines.append("")
        lines.append("```")
        lines.extend(files)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    groups = _collect()
    OUT.write_text(_render(groups), encoding="utf-8")
    total = sum(len(v) for v in groups.values())
    print(f"wrote {OUT.relative_to(ROOT)} ({total} dosya, {len(groups)} başlık)")


if __name__ == "__main__":
    main()
