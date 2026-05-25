#!/usr/bin/env python3
"""Proje kökünde GIT.md üretir: GitHub bilgileri + tam commit geçmişi (git log)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = "\x1fRECORD\x1f"
SYNC_COMMIT_PREFIX = "docs: sync GIT.md"


def run(cmd: str, *, cwd: Path = ROOT) -> str:
    return subprocess.check_output(cmd, shell=True, text=True, cwd=cwd).strip()


def build_content() -> tuple[str, int]:
    remote = run("git remote get-url origin")
    branch = run("git branch --show-current")
    head_short = run("git rev-parse --short HEAD")
    head_full = run("git rev-parse HEAD")
    counts = run("git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '0\t0'")
    behind_s, ahead_s = counts.split()
    behind, ahead = int(behind_s), int(ahead_s)
    total = run("git rev-list --count HEAD")

    repo_name = "omrgld3437-hub/Final1"
    https_url = f"https://github.com/{repo_name}.git"
    web_url = f"https://github.com/{repo_name}"

    try:
        mkt_hash = run("git ls-tree HEAD marketing | awk '{print $3}'")
        mkt_short = mkt_hash[:7]
    except subprocess.CalledProcessError:
        mkt_hash = mkt_short = "—"

    if ahead > 0:
        remote_status = f"`origin/main`'den **{ahead}** commit önde"
    elif behind > 0:
        remote_status = f"`origin/main`'den **{behind}** commit geride"
    else:
        remote_status = "`origin/main` ile eşit"

    lines: list[str] = [
        "# Git — Final1",
        "",
        f"> HEAD `{head_short}` · Toplam **{total}** commit · branch `{branch}`",
        "",
        "## GitHub",
        "",
        "| Alan | Değer |",
        "|------|-------|",
        f"| Repository | [{repo_name}]({web_url}) |",
        f"| Web | {web_url} |",
        f"| SSH (origin) | `{remote}` |",
        f"| HTTPS | `{https_url}` |",
        f"| Aktif branch | `{branch}` |",
        f"| HEAD (kısa) | `{head_short}` |",
        f"| HEAD (tam) | `{head_full}` |",
        f"| Remote durumu | {remote_status} |",
        "",
        "## Submodule: marketing",
        "",
        "| Alan | Değer |",
        "|------|-------|",
        f"| Gitlink (HEAD) | `{mkt_short}` (`{mkt_hash}`) |",
        "| Klasör | `marketing/` (ayrı git repo) |",
        "",
        "## Commit geçmişi (`git log`)",
        "",
        "En yeni commit üstte.",
        "",
    ]

    raw = subprocess.check_output(
        [
            "git",
            "log",
            f"--format={RECORD}%H%x1e%h%x1e%an%x1e%ae%x1e%ad%x1e%s%x1e%b",
            "--date=format:%Y-%m-%d %H:%M:%S %z",
        ],
        text=True,
        cwd=ROOT,
    )

    entries = [e for e in raw.split(RECORD) if e.strip()]
    for i, entry in enumerate(entries, 1):
        parts = entry.strip().split("\x1e", 6)
        if len(parts) < 6:
            continue
        full, short, author, email, date, subject = parts[:6]
        body = parts[6].strip() if len(parts) > 6 else ""
        body = body.replace("Co-authored-by: Cursor <cursoragent@cursor.com>", "").strip()

        lines.append(f"### {i}. `{short}` — {subject}")
        lines.append("")
        lines.append(f"- **Commit no (tam):** `{full}`")
        lines.append(f"- **Commit no (kısa):** `{short}`")
        lines.append(f"- **Tarih:** {date}")
        lines.append(f"- **Yazar:** {author} <{email}>")
        if body:
            lines.append("- **Detay:**")
            for bl in body.splitlines():
                bl = bl.strip()
                if bl:
                    lines.append(f"  - {bl}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend(
        [
            "",
            "## Yenileme",
            "",
            "Her commit sonrası `post-commit` hook otomatik çalışır.",
            "",
            "Elle güncellemek için:",
            "",
            "```bash",
            "python3 scripts/devops/sync_git_log.py",
            "make hooks   # hook kurulumu (ilk sefer)",
            "```",
            "",
        ]
    )

    return "\n".join(lines) + "\n", len(entries)


def main() -> int:
    content, count = build_content()
    out = ROOT / "GIT.md"
    if out.exists() and out.read_text(encoding="utf-8") == content:
        print(f"GIT.md güncel ({count} commit)")
        return 0
    out.write_text(content, encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} ({count} commits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
