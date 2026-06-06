"""
RAM Probe — measurement only. JSONL to logs/ram_snapshots.log.
Controlled via env RAM_PROBE=1 (or RAM_PROBE_ENABLED=1).
"""

from __future__ import annotations

import gc
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_RUN_DIR = _PROJECT_ROOT / ".run"
_RAM_SNAPSHOT_LOG = _LOGS_DIR / "ram_snapshots.log"
_tracemalloc_started = False
_probe_thread: Optional[threading.Thread] = None
_probe_stop = threading.Event()
_last_snapshot: Optional[Dict[str, Any]] = None
_hooks: Dict[str, Callable[[], dict]] = {}
_component: Optional[str] = None


def _is_enabled() -> bool:
    return (
        os.getenv("RAM_PROBE", "").strip() == "1"
        or os.getenv("RAM_PROBE_ENABLED", "").strip() == "1"
    )


def _ensure_tracemalloc() -> None:
    global _tracemalloc_started
    if _tracemalloc_started:
        return
    try:
        import tracemalloc

        tracemalloc.start(25)
        _tracemalloc_started = True
        logger.info("RAM_PROBE tracemalloc started (depth=25)")
    except Exception as e:
        logger.warning("RAM_PROBE tracemalloc not available: %s", e)


def _ensure_logs_dir() -> None:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _RUN_DIR.mkdir(parents=True, exist_ok=True)


def _get_process_memory() -> Dict[str, float]:
    out = {"rss_mb": 0.0, "vms_mb": 0.0}
    try:
        import psutil

        p = psutil.Process(os.getpid())
        mem = p.memory_info()
        out["rss_mb"] = round(mem.rss / (1024 * 1024), 2)
        out["vms_mb"] = round(mem.vms / (1024 * 1024), 2)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("RAM_PROBE psutil: %s", e)
    return out


def _get_tracemalloc_mb() -> tuple:
    """Returns (current_mb, peak_mb)."""
    try:
        import tracemalloc

        cur, peak = tracemalloc.get_traced_memory()
        return (round(cur / (1024 * 1024), 2), round(peak / (1024 * 1024), 2))
    except Exception:
        return (0.0, 0.0)


def _get_top_allocations(limit: int = 10) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    try:
        import tracemalloc

        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")
        for stat in top[:limit]:
            size_mb = stat.size / (1024 * 1024)
            file_path = ""
            line_no = None
            if stat.traceback:
                frame = stat.traceback[-1]
                file_path = getattr(frame, "filename", "") or ""
                line_no = getattr(frame, "lineno", None)
            result.append(
                {
                    "file": file_path,
                    "line": line_no,
                    "size_mb": round(size_mb, 2),
                }
            )
    except Exception as e:
        logger.debug("RAM_PROBE tracemalloc top: %s", e)
    return result


def _get_gc_counts() -> Dict[str, Any]:
    out: Dict[str, Any] = {"get_count": list(gc.get_count())}
    deep = os.getenv("RAM_PROBE_GC_DEEP", "").strip() in ("1", "true", "yes")
    if not deep:
        return out
    out["total_objects"] = 0
    type_counts: Dict[str, int] = defaultdict(int)
    try:
        objs = gc.get_objects()
        out["total_objects"] = len(objs)
        for obj in objs:
            t = type(obj).__name__
            type_counts[t] += 1
        out["dict"] = type_counts.get("dict", 0)
        out["list"] = type_counts.get("list", 0)
        out["tuple"] = type_counts.get("tuple", 0)
        out["str"] = type_counts.get("str", 0)
        out["bytes"] = type_counts.get("bytes", 0)
        try:
            import asyncio

            out["asyncio.Task"] = sum(1 for o in objs if isinstance(o, asyncio.Task))
        except Exception:
            out["asyncio.Task"] = 0
    except Exception as e:
        logger.debug("RAM_PROBE gc counts: %s", e)
    return out


def _run_hooks() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, fn in list(_hooks.items()):
        try:
            out[name] = fn()
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


def snapshot_now(component: str, reason: str = "") -> Dict[str, Any]:
    """Take one snapshot and return dict. Optionally write to JSONL."""
    ts = datetime.now(timezone.utc).isoformat()
    pid = os.getpid()
    payload: Dict[str, Any] = {
        "ts": ts,
        "component": component,
        "pid": pid,
        "reason": reason or None,
    }
    # Process memory (psutil)
    try:
        import psutil  # noqa: F401

        proc = _get_process_memory()
        payload["rss_mb"] = proc["rss_mb"]
        payload["vms_mb"] = proc["vms_mb"]
    except ImportError:
        payload["rss_mb"] = None
        payload["vms_mb"] = None
        payload["_note"] = "psutil not installed"
    # Python heap (tracemalloc current/peak)
    _ensure_tracemalloc()
    cur_mb, peak_mb = _get_tracemalloc_mb()
    payload["tracemalloc_current_mb"] = cur_mb
    payload["tracemalloc_peak_mb"] = peak_mb
    payload["python_heap_estimate_mb"] = cur_mb  # backward compat
    # GC counts
    payload["gc"] = _get_gc_counts()
    # tracemalloc top 10
    payload["tracemalloc_top"] = _get_top_allocations(10)
    # Hooks
    payload["hooks"] = _run_hooks()
    return payload


def _write_snapshot_line(payload: Dict[str, Any]) -> None:
    """Append one JSON line to logs/ram_snapshots.log. On failure write error line to same file."""
    try:
        if os.getenv("RAM_CAPTURE", "").strip().lower() in ("1", "true", "yes"):
            from app.observability.ram_capture import mirror_probe_line

            mirror_probe_line(payload)
    except Exception:
        pass
    try:
        _ensure_logs_dir()
        with open(_RAM_SNAPSHOT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("RAM_PROBE write snapshot: %s", e)
        try:
            err_line = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "component": _component or "unknown",
                "pid": os.getpid(),
                "error": "probe_write_failed",
                "message": str(e),
            }
            _ensure_logs_dir()
            with open(_RAM_SNAPSHOT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(err_line, ensure_ascii=False) + "\n")
        except Exception:
            pass


def write_snapshot_now(component: str, reason: str = "") -> None:
    """Take one snapshot and append it to logs/ram_snapshots.log. Safe; never raises."""
    try:
        snap = snapshot_now(component, reason=reason)
        _write_snapshot_line(snap)
    except Exception as e:
        logger.debug("RAM_PROBE write_snapshot_now: %s", e)


def register_probe_hook(name: str, fn: Callable[[], dict]) -> None:
    """Register a callable that returns a dict (e.g. active_bots, cache_sizes)."""
    _hooks[name] = fn


def start_ram_probe(component: str, interval_sec: int = 30) -> None:
    """
    Start background RAM probe. Writes JSONL to logs/ram_snapshots.log.
    component: "web" | "worker"
    Safe: runs even without psutil (writes rss_mb=null). Never crashes app; probe failures written to same file.
    """
    global _probe_thread, _component
    if not _is_enabled():
        return
    _component = component
    _ensure_logs_dir()
    _ensure_tracemalloc()
    _probe_stop.clear()

    def _loop() -> None:
        while True:
            try:
                snap = snapshot_now(_component, reason="periodic")
                _write_snapshot_line(snap)
                global _last_snapshot
                _last_snapshot = snap
            except Exception as e:
                logger.warning("RAM_PROBE snapshot_loop: %s", e)
                try:
                    _write_snapshot_line(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "component": _component or "unknown",
                            "pid": os.getpid(),
                            "error": "probe_snapshot_failed",
                            "message": str(e),
                        }
                    )
                except Exception:
                    pass
            if _probe_stop.wait(timeout=interval_sec):
                break

    _probe_thread = threading.Thread(target=_loop, daemon=True, name="ram_probe")
    _probe_thread.start()
    # First snapshot soon so file exists and has one line
    try:
        snap0 = snapshot_now(component, reason="startup")
        _write_snapshot_line(snap0)
        global _last_snapshot
        _last_snapshot = snap0
    except Exception as e:
        logger.warning("RAM_PROBE initial snapshot: %s", e)
        try:
            _write_snapshot_line(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "component": component,
                    "pid": os.getpid(),
                    "error": "probe_startup_snapshot_failed",
                    "message": str(e),
                }
            )
        except Exception:
            pass
    logger.info(
        "RAM_PROBE started component=%s interval_sec=%s log=%s",
        component,
        interval_sec,
        _RAM_SNAPSHOT_LOG,
    )


def get_last_snapshot() -> Optional[Dict[str, Any]]:
    """Return last snapshot for GET /api/health/ram."""
    return _last_snapshot


def get_ram_snapshot_log_path() -> Path:
    return _RAM_SNAPSHOT_LOG


# --- Backward compatibility / optional helpers ---


def take_snapshot(
    label: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Legacy: take snapshot with optional label/extra. Does not write to file by default."""
    comp = _component or "unknown"
    snap = snapshot_now(comp, reason=label or "")
    if label:
        snap["label"] = label
    if extra:
        snap["extra"] = extra
    return snap


def _write_snapshot_line_public(payload: Dict[str, Any]) -> None:
    _write_snapshot_line(payload)


def start_global_monitor() -> bool:
    """Legacy: start probe with component=web, interval from env."""
    if not _is_enabled():
        return False
    interval = int(
        os.getenv("RAM_PROBE_INTERVAL", os.getenv("RAM_PROBE_INTERVAL", "30"))
    )
    start_ram_probe(component="web", interval_sec=interval)
    return True


def probe_bot_event(
    event: str,
    bot_id: Optional[int] = None,
    task_count: Optional[int] = None,
    state_count_hint: Optional[int] = None,
    write_to_log: bool = True,
) -> Dict[str, Any]:
    """Legacy: bot event snapshot."""
    extra: Dict[str, Any] = {"event": event}
    if bot_id is not None:
        extra["bot_id"] = bot_id
    if task_count is not None:
        extra["task_count"] = task_count
    if state_count_hint is not None:
        extra["state_count_hint"] = state_count_hint
    payload = take_snapshot(label=f"bot_{event}", extra=extra)
    if write_to_log:
        _write_snapshot_line(payload)
    return payload


def probe_market_data(
    open_ws_count: Optional[int] = None,
    cache_symbol_count: Optional[int] = None,
    write_to_log: bool = True,
) -> Dict[str, Any]:
    """Legacy: market data snapshot."""
    extra = {}
    if open_ws_count is not None:
        extra["open_ws_count"] = open_ws_count
    if cache_symbol_count is not None:
        extra["cache_symbol_count"] = cache_symbol_count
    payload = take_snapshot(label="market_data", extra=extra or None)
    if write_to_log:
        _write_snapshot_line(payload)
    return payload


def probe_event_store(
    before_write: bool,
    event_count: Optional[int] = None,
    write_to_log: bool = True,
) -> Dict[str, Any]:
    """Legacy: event store snapshot."""
    label = "event_store_before" if before_write else "event_store_after"
    extra = {}
    if event_count is not None:
        extra["event_count"] = event_count
    payload = take_snapshot(label=label, extra=extra or None)
    if write_to_log:
        _write_snapshot_line(payload)
    return payload


def _get_asyncio_task_count() -> int:
    try:
        import asyncio

        return sum(
            1 for o in gc.get_objects() if isinstance(o, asyncio.Task) and not o.done()
        )
    except Exception:
        return 0


def gc_collect_and_count() -> Dict[str, Any]:
    gc.collect()
    counts = _get_gc_counts()
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "label": "gc_collect",
        "gc": counts,
        "asyncio_task_count": _get_asyncio_task_count(),
    }
