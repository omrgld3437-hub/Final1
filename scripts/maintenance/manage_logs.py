#!/usr/bin/env python3
"""
Bounded log maintenance for local/runtime logs.

The app writes web.log/worker.log through shell redirection, so classic rename
rotation can leave running processes writing to the old inode. For those live
logs this script uses copy-truncate: compress the current content, then truncate
the original path in place.
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"

ACTIVE_LOGS = (
    "web.log",
    "worker.log",
    "manager.log",
    "html.log",
    "manager_backend.log",
    "ram_snapshots.log",
)

COMPRESS_PATTERNS = (
    "app.log.*",
    "ram_capture_*.jsonl",
    "ram_scenario_*.jsonl",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _gzip_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)


def _copy_truncate(path: Path, archive_dir: Path, dry_run: bool) -> str | None:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = archive_dir / f"{path.name}.{stamp}.gz"
    if dry_run:
        return f"rotate-live {path} -> {dst} ({_size_mb(path):.1f} MB)"
    _gzip_file(path, dst)
    with path.open("r+b") as f:
        f.truncate(0)
    return f"rotated-live {path.name} -> {dst.name}"


def _compress_and_remove(path: Path, archive_dir: Path, dry_run: bool) -> str | None:
    if not path.exists() or not path.is_file() or path.suffix == ".gz":
        return None
    dst = archive_dir / f"{path.name}.gz"
    if dst.exists():
        dst = archive_dir / f"{path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.gz"
    if dry_run:
        return f"compress {path} -> {dst} ({_size_mb(path):.1f} MB)"
    _gzip_file(path, dst)
    path.unlink(missing_ok=True)
    return f"compressed {path.name} -> {dst.name}"


def _delete_old(paths: Iterable[Path], older_than_days: int, dry_run: bool) -> List[str]:
    out: List[str] = []
    if older_than_days <= 0:
        return out
    cutoff = time.time() - older_than_days * 86400
    for path in paths:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                if dry_run:
                    out.append(f"delete-old {path}")
                else:
                    path.unlink(missing_ok=True)
                    out.append(f"deleted-old {path.name}")
        except FileNotFoundError:
            continue
    return out


def _cap_archives(archive_dir: Path, keep: int, dry_run: bool) -> List[str]:
    out: List[str] = []
    if keep <= 0 or not archive_dir.exists():
        return out
    grouped = {}
    for path in archive_dir.glob("*.gz"):
        key = path.name.split(".log.", 1)[0] if ".log." in path.name else path.name.split(".", 1)[0]
        grouped.setdefault(key, []).append(path)
    for paths in grouped.values():
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in paths[keep:]:
            if dry_run:
                out.append(f"delete-cap {old}")
            else:
                old.unlink(missing_ok=True)
                out.append(f"deleted-cap {old.name}")
    return out


def maintain_logs(
    *,
    max_active_mb: int,
    compress_after_mb: int,
    delete_after_days: int,
    keep_archives: int,
    dry_run: bool = False,
) -> List[str]:
    LOGS.mkdir(parents=True, exist_ok=True)
    archive_dir = LOGS / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    actions: List[str] = []

    for name in ACTIVE_LOGS:
        path = LOGS / name
        if path.exists() and _size_mb(path) >= max_active_mb:
            action = _copy_truncate(path, archive_dir, dry_run)
            if action:
                actions.append(action)

    rest_log = ROOT / os.getenv("REST_LOG_PATH", "rest.log")
    if rest_log.exists() and rest_log.is_file() and _size_mb(rest_log) >= max_active_mb:
        action = _copy_truncate(rest_log, archive_dir, dry_run)
        if action:
            actions.append(action)

    for pattern in COMPRESS_PATTERNS:
        for path in LOGS.glob(pattern):
            if path.is_file() and path.suffix != ".gz" and _size_mb(path) >= compress_after_mb:
                action = _compress_and_remove(path, archive_dir, dry_run)
                if action:
                    actions.append(action)

    actions.extend(_delete_old(archive_dir.glob("*.gz"), delete_after_days, dry_run))
    actions.extend(_cap_archives(archive_dir, keep_archives, dry_run))
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Compress/truncate large runtime logs safely.")
    parser.add_argument("--max-active-mb", type=int, default=_env_int("LOG_ACTIVE_MAX_MB", 25))
    parser.add_argument("--compress-after-mb", type=int, default=_env_int("LOG_COMPRESS_AFTER_MB", 5))
    parser.add_argument("--delete-after-days", type=int, default=_env_int("LOG_ARCHIVE_DELETE_DAYS", 14))
    parser.add_argument("--keep-archives", type=int, default=_env_int("LOG_ARCHIVE_KEEP", 12))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    actions = maintain_logs(
        max_active_mb=max(1, args.max_active_mb),
        compress_after_mb=max(1, args.compress_after_mb),
        delete_after_days=max(0, args.delete_after_days),
        keep_archives=max(1, args.keep_archives),
        dry_run=args.dry_run,
    )
    for action in actions:
        print(action)
    if not actions:
        print("logs-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
