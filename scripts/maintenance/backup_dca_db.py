#!/usr/bin/env python3
"""
dca.db yedekleme — ~/.trader/backups/ altına zaman damgalı kopya.

Usage:
  python3 scripts/maintenance/backup_dca_db.py
"""

from __future__ import annotations

import shutil
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


def main() -> None:
    src = _active_db()
    if not src.is_file():
        print(f"HATA: Veritabani bulunamadi: {src}")
        raise SystemExit(1)
    dest_dir = Path.home() / ".trader" / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"dca.db.{stamp}"
    shutil.copy2(src, dest)
    # WAL varsa yaninda kopyala
    for suffix in ("-wal", "-shm"):
        wal = Path(str(src) + suffix)
        if wal.is_file():
            shutil.copy2(wal, dest_dir / f"dca.db.{stamp}{suffix}")
    print(f"Yedek: {dest}")
    print(f"Boyut: {dest.stat().st_size} byte")


if __name__ == "__main__":
    main()
