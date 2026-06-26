"""Dynamic Param Score decision log retention — cap disk usage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from app.services.dynamic_param_score import constants as C

logger = logging.getLogger(__name__)

_prune_counter = 0
_PRUNE_EVERY_N_WRITES = 5


def log_dir_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[3]
    return root / C.LOG_DIR_NAME


def directory_size_bytes(log_dir: Path) -> int:
    if not log_dir.is_dir():
        return 0
    total = 0
    for path in log_dir.glob("*.json"):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def list_log_files_oldest_first(log_dir: Path) -> List[Path]:
    files: List[Tuple[float, Path]] = []
    for path in log_dir.glob("*.json"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(key=lambda x: x[0])
    return [p for _, p in files]


def prune_log_directory(
    log_dir: Path | None = None,
    *,
    max_bytes: int | None = None,
    target_bytes: int | None = None,
) -> dict:
    """Delete oldest decision logs until directory size <= target_bytes."""
    directory = log_dir or log_dir_path()
    cap = max_bytes if max_bytes is not None else C.LOG_DIR_MAX_BYTES
    target = target_bytes if target_bytes is not None else C.LOG_DIR_TARGET_BYTES

    if not directory.is_dir():
        return {"pruned": 0, "before_bytes": 0, "after_bytes": 0, "skipped": True}

    before = directory_size_bytes(directory)
    if before <= cap:
        return {"pruned": 0, "before_bytes": before, "after_bytes": before, "skipped": True}

    removed = 0
    for path in list_log_files_oldest_first(directory):
        if directory_size_bytes(directory) <= target:
            break
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("DPS log prune failed %s: %s", path, exc)

    after = directory_size_bytes(directory)
    if removed:
        logger.info(
            "DPS log prune removed=%s before_mb=%.1f after_mb=%.1f target_mb=%.1f",
            removed,
            before / (1024 * 1024),
            after / (1024 * 1024),
            target / (1024 * 1024),
        )
    return {
        "pruned": removed,
        "before_bytes": before,
        "after_bytes": after,
        "target_bytes": target,
        "max_bytes": cap,
        "skipped": False,
    }


def maybe_prune_after_write(log_dir: Path | None = None) -> None:
    """Throttle retention checks — run full prune every N writes."""
    global _prune_counter
    _prune_counter += 1
    if _prune_counter % _PRUNE_EVERY_N_WRITES != 0:
        return
    directory = log_dir or log_dir_path()
    if directory_size_bytes(directory) <= C.LOG_DIR_MAX_BYTES:
        return
    prune_log_directory(directory)
