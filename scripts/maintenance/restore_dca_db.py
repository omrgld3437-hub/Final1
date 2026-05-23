#!/usr/bin/env python3
"""
dca.db geri yukleme — yedek dosyadan aktif DATABASE_URL konumuna kopyalar.

Usage:
  ./ops/stop.command   # once durdur
  python3 scripts/maintenance/restore_dca_db.py /path/to/dca.db.backup
  ./ops/start.command

Arama (bulursa listeler):
  python3 scripts/maintenance/restore_dca_db.py --search
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _active_db() -> Path:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    import os
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        p = url.replace("sqlite:///", "", 1).split("?")[0]
        if p.startswith("/"):
            return Path(p)
        return (ROOT / p).resolve()
    return Path.home() / ".trader" / "dca.db"


def _integrity(path: Path) -> str:
    try:
        con = sqlite3.connect(str(path))
        row = con.execute("PRAGMA integrity_check").fetchone()
        con.close()
        return row[0] if row else "unknown"
    except Exception as e:
        return f"FAIL: {e}"


def _search_candidates() -> list[Path]:
    patterns = [
        Path.home() / ".trader" / "backups",
        ROOT / "data" / "backups",
        ROOT,
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    ]
    found: list[Path] = []
    for base in patterns:
        if not base.is_dir():
            continue
        for p in base.rglob("dca.db*"):
            if p.is_file() and p.suffix in ("", ".db") or "dca.db" in p.name:
                if p.stat().st_size > 50_000:
                    found.append(p)
    return sorted(set(found), key=lambda x: x.stat().st_mtime, reverse=True)


def restore(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Kaynak yok: {source}")
    check = _integrity(source)
    if check != "ok":
        raise SystemExit(f"Kaynak integrity_check basarisiz: {check}")

    target.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = Path.home() / ".trader" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        prev = backup_dir / f"dca.db.before-restore-{stamp}"
        shutil.copy2(target, prev)
        print(f"Mevcut DB yedeklendi: {prev}")
        for suffix in ("-wal", "-shm"):
            w = Path(str(target) + suffix)
            if w.is_file():
                shutil.copy2(w, Path(str(prev) + suffix))

    # WAL/shm temiz baslangic
    for suffix in ("-wal", "-shm"):
        p = Path(str(target) + suffix)
        if p.is_file():
            p.unlink()

    shutil.copy2(source, target)
    subprocess.run(["sqlite3", str(target), "PRAGMA wal_checkpoint(TRUNCATE);"], check=False)
    print(f"Geri yuklendi: {source} -> {target}")
    print(f"integrity_check: {_integrity(target)}")
    con = sqlite3.connect(str(target))
    users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    bots = con.execute("SELECT COUNT(*) FROM bots").fetchone()[0]
    con.close()
    print(f"users={users} bots={bots}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", help="Yedek dca.db dosya yolu")
    ap.add_argument("--search", action="store_true", help="Olası yedekleri listele")
    args = ap.parse_args()
    target = _active_db()
    print(f"Hedef (DATABASE_URL): {target}")

    if args.search or not args.source:
        print("\nBulunan aday dosyalar (>50KB):")
        cands = _search_candidates()
        if not cands:
            print("  (bulunamadi)")
            print("\nSilinen ./dca.db icin Time Machine veya Disk Drill gerekebilir.")
            print("Sunucuda kopya varsa: scp user@host:/path/dca.db ~/Desktop/dca.db.recovered")
            print("Sonra: python3 scripts/maintenance/restore_dca_db.py ~/Desktop/dca.db.recovered")
        else:
            for p in cands[:20]:
                print(f"  {p.stat().st_size:>9}  {p}")
        if not args.source:
            return
    restore(Path(args.source).expanduser().resolve(), target)


if __name__ == "__main__":
    main()
