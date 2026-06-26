#!/usr/bin/env python3
"""
Bounded log maintenance for local/runtime logs.

The app writes web.log/worker.log through shell redirection, so classic rename
rotation can leave running processes writing to the old inode. For those live
logs this script uses copy-truncate: compress the current content, then truncate
the original path in place.

Retention: archives and rotated copies older than LOG_RETENTION_DAYS (default 90)
are deleted. Run periodically via LOG_MAINTAIN_INTERVAL_SEC (default 24h) from
supervisor/worker, or on stack start (ops/start.command).
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"
RUN = ROOT / ".run"
LAST_MAINTAIN_STAMP = RUN / "last_log_maintain_ts"

# Shell-redirected live logs (copy-truncate when large or daily)
ACTIVE_LOGS = (
    "web.log",
    "worker.log",
    "manager.log",
    "html.log",
    "manager_backend.log",
    "supervisor.log",
    "ram_snapshots.log",
)

# .run/ runtime logs (same copy-truncate treatment)
RUN_ACTIVE_LOGS = (
    "server.log",
    "restart_helper.log",
    "manager_audit.log",
)

COMPRESS_PATTERNS = (
    "app.log.*",
    "ram_capture_*.jsonl",
    "ram_scenario_*.jsonl",
)

# Rotated / archive blobs under .run/ (compress when large, delete when old)
RUN_COMPRESS_GLOBS = (
    "audit_archive.jsonl",
    "issues_archive.jsonl",
    "*_archive.jsonl",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def retention_days() -> int:
    """Days to keep archived/rotated log files (default 90)."""
    for key in ("LOG_RETENTION_DAYS", "LOG_ARCHIVE_DELETE_DAYS"):
        raw = os.getenv(key, "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
    return 90


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _gzip_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)


def _latest_archive_ts(archive_dir: Path, base_name: str) -> float:
    best = 0.0
    for path in archive_dir.glob(f"{base_name}.*.gz"):
        try:
            best = max(best, path.stat().st_mtime)
        except OSError:
            continue
    return best


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


def _delete_old(
    paths: Iterable[Path], older_than_days: int, dry_run: bool
) -> List[str]:
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
        key = (
            path.name.split(".log.", 1)[0]
            if ".log." in path.name
            else path.name.split(".", 1)[0]
        )
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


def _maybe_rotate_live(
    path: Path,
    archive_dir: Path,
    *,
    max_active_mb: int,
    rotate_interval_days: int,
    min_rotate_mb: float,
    dry_run: bool,
) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    size_mb = _size_mb(path)
    if size_mb >= max_active_mb:
        return _copy_truncate(path, archive_dir, dry_run)
    if rotate_interval_days > 0 and size_mb >= min_rotate_mb:
        last = _latest_archive_ts(archive_dir, path.name)
        if last <= 0 or (time.time() - last) >= rotate_interval_days * 86400:
            return _copy_truncate(path, archive_dir, dry_run)
    return None


def maintain_logs(
    *,
    max_active_mb: int,
    compress_after_mb: int,
    delete_after_days: int,
    keep_archives: int,
    rotate_interval_days: int = 1,
    min_rotate_mb: float = 0.5,
    dry_run: bool = False,
) -> List[str]:
    LOGS.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(parents=True, exist_ok=True)
    archive_dir = LOGS / "archive"
    run_archive_dir = archive_dir / "run"
    archive_dir.mkdir(parents=True, exist_ok=True)
    run_archive_dir.mkdir(parents=True, exist_ok=True)
    actions: List[str] = []

    for name in ACTIVE_LOGS:
        path = LOGS / name
        action = _maybe_rotate_live(
            path,
            archive_dir,
            max_active_mb=max_active_mb,
            rotate_interval_days=rotate_interval_days,
            min_rotate_mb=min_rotate_mb,
            dry_run=dry_run,
        )
        if action:
            actions.append(action)

    for name in RUN_ACTIVE_LOGS:
        path = RUN / name
        action = _maybe_rotate_live(
            path,
            run_archive_dir,
            max_active_mb=max_active_mb,
            rotate_interval_days=rotate_interval_days,
            min_rotate_mb=min_rotate_mb,
            dry_run=dry_run,
        )
        if action:
            actions.append(action)

    rest_log = ROOT / os.getenv("REST_LOG_PATH", "logs/rest.log")
    if rest_log.is_file():
        action = _maybe_rotate_live(
            rest_log,
            archive_dir,
            max_active_mb=max_active_mb,
            rotate_interval_days=rotate_interval_days,
            min_rotate_mb=min_rotate_mb,
            dry_run=dry_run,
        )
        if action:
            actions.append(action)

    for pattern in COMPRESS_PATTERNS:
        for path in LOGS.glob(pattern):
            if (
                path.is_file()
                and path.suffix != ".gz"
                and _size_mb(path) >= compress_after_mb
            ):
                action = _compress_and_remove(path, archive_dir, dry_run)
                if action:
                    actions.append(action)

    for pattern in RUN_COMPRESS_GLOBS:
        for path in RUN.glob(pattern):
            if path.is_file() and _size_mb(path) >= compress_after_mb:
                action = _compress_and_remove(path, run_archive_dir, dry_run)
                if action:
                    actions.append(action)

    # Retention: drop archives older than N days (primary policy)
    actions.extend(_delete_old(archive_dir.glob("*.gz"), delete_after_days, dry_run))
    actions.extend(_delete_old(run_archive_dir.glob("*.gz"), delete_after_days, dry_run))
    actions.extend(_delete_old(LOGS.glob("app.log.*"), delete_after_days, dry_run))
    actions.extend(_delete_old(LOGS.glob("*.log.*"), delete_after_days, dry_run))

    actions.extend(_cap_archives(archive_dir, keep_archives, dry_run))
    actions.extend(_cap_archives(run_archive_dir, keep_archives, dry_run))
    return actions


def run_if_due(*, force: bool = False, dry_run: bool = False) -> List[str]:
    """Run maintenance at most once per LOG_MAINTAIN_INTERVAL_SEC unless force=True."""
    interval = _env_int("LOG_MAINTAIN_INTERVAL_SEC", 86400)
    now = time.time()
    if not force:
        try:
            if LAST_MAINTAIN_STAMP.exists():
                last = float(LAST_MAINTAIN_STAMP.read_text(encoding="utf-8").strip())
                if now - last < interval:
                    return []
        except (OSError, ValueError):
            pass

    actions = maintain_logs(
        max_active_mb=max(1, _env_int("LOG_ACTIVE_MAX_MB", 25)),
        compress_after_mb=max(0, _env_int("LOG_COMPRESS_AFTER_MB", 5)),
        delete_after_days=retention_days(),
        keep_archives=_env_int("LOG_ARCHIVE_KEEP", 0),
        rotate_interval_days=_env_int("LOG_ROTATE_INTERVAL_DAYS", 1),
        min_rotate_mb=float(os.getenv("LOG_MIN_ROTATE_MB", "0.5")),
        dry_run=dry_run,
    )
    if not dry_run:
        try:
            RUN.mkdir(parents=True, exist_ok=True)
            LAST_MAINTAIN_STAMP.write_text(str(now), encoding="utf-8")
        except OSError:
            pass
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compress/truncate large runtime logs; retain last N days."
    )
    parser.add_argument(
        "--max-active-mb", type=int, default=_env_int("LOG_ACTIVE_MAX_MB", 25)
    )
    parser.add_argument(
        "--compress-after-mb", type=int, default=_env_int("LOG_COMPRESS_AFTER_MB", 5)
    )
    parser.add_argument(
        "--delete-after-days",
        type=int,
        default=retention_days(),
        help="Delete archives older than this (default 90)",
    )
    parser.add_argument(
        "--keep-archives",
        type=int,
        default=_env_int("LOG_ARCHIVE_KEEP", 0),
        help="Optional per-log archive cap (0=disabled, use delete-after-days only)",
    )
    parser.add_argument(
        "--rotate-interval-days",
        type=int,
        default=_env_int("LOG_ROTATE_INTERVAL_DAYS", 1),
    )
    parser.add_argument(
        "--force", action="store_true", help="Ignore LOG_MAINTAIN_INTERVAL_SEC throttle"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.force:
        actions = maintain_logs(
            max_active_mb=max(1, args.max_active_mb),
            compress_after_mb=max(0, args.compress_after_mb),
            delete_after_days=max(0, args.delete_after_days),
            keep_archives=max(0, args.keep_archives),
            rotate_interval_days=max(0, args.rotate_interval_days),
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            try:
                RUN.mkdir(parents=True, exist_ok=True)
                LAST_MAINTAIN_STAMP.write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
    else:
        actions = run_if_due(force=False, dry_run=args.dry_run)

    for action in actions:
        print(action)
    if not actions:
        print("logs-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
