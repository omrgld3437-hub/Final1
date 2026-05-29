"""
RAM Capture — 5 dk (veya RAM_CAPTURE_DURATION) detaylı JSONL oturumu.

Ortam:
  RAM_CAPTURE=1          Oturumu aç (web/worker yeniden başlat)
  RAM_CAPTURE_DURATION=300   Saniye (varsayılan 300)
  RAM_CAPTURE_INTERVAL=10    Snapshot aralığı (varsayılan 10)
  RAM_CAPTURE_SESSION=...    Opsiyonel oturum kimliği (web+worker aynı dosya adı)

Çıktı:
  logs/ram_capture_{session}_{web|worker}.jsonl
  logs/ram_capture_session.json   manifest (bitince complete=1)

Analiz: python scripts/perf/ram_capture_5min.py --analyze
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_MANIFEST_PATH = _LOGS_DIR / "ram_capture_session.json"

_capture_thread: Optional[threading.Thread] = None
_capture_stop = threading.Event()
_session_id: Optional[str] = None
_component: Optional[str] = None
_log_path: Optional[Path] = None
_line_count = 0
_hooks: Dict[str, Callable[[], dict]] = {}


def is_capture_enabled() -> bool:
    v = os.getenv("RAM_CAPTURE", "").strip().lower()
    return v in ("1", "true", "yes")


def _ensure_logs_dir() -> None:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _session_id_value() -> str:
    global _session_id
    if _session_id:
        return _session_id
    _session_id = (
        os.getenv("RAM_CAPTURE_SESSION", "").strip()
        or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    return _session_id


def get_capture_log_path(component: Optional[str] = None) -> Path:
    comp = component or _component or "unknown"
    return _LOGS_DIR / f"ram_capture_{_session_id_value()}_{comp}.jsonl"


def _append_capture_line(payload: Dict[str, Any], component: Optional[str] = None) -> None:
    global _line_count
    if not is_capture_enabled():
        return
    comp = component or _component or payload.get("component") or "unknown"
    path = _log_path or get_capture_log_path(comp)
    payload.setdefault("session_id", _session_id_value())
    payload.setdefault("component", comp)
    payload.setdefault("pid", os.getpid())
    if "ts" not in payload:
        payload["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        _ensure_logs_dir()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        _line_count += 1
    except Exception as e:
        logger.warning("RAM_CAPTURE write failed: %s", e)


def _approx_mapping_bytes(obj: Any, max_sample: int = 8) -> int:
    if obj is None:
        return 0
    try:
        if isinstance(obj, dict):
            if not obj:
                return 0
            keys = list(obj.keys())[:max_sample]
            sample = {k: obj[k] for k in keys}
            per = len(json.dumps(sample, ensure_ascii=False, default=str)) / max(1, len(keys))
            return int(per * len(obj))
        if isinstance(obj, (list, tuple)):
            if not obj:
                return 0
            sample = obj[:max_sample]
            per = len(json.dumps(sample, ensure_ascii=False, default=str)) / max(1, len(sample))
            return int(per * len(obj))
        return len(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return 0


def _safe_len(obj: Any) -> int:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:
        return 0


def collect_ram_inventory() -> Dict[str, Any]:
    """Salt okunur: süreç içi cache/bellek yapılarının boyut özeti."""
    inv: Dict[str, Any] = {"subsystems": {}}

    try:
        from app.services.data_hub import data_hub

        dh = inv["subsystems"]["data_hub"] = {
            "prices_len": _safe_len(getattr(data_hub, "prices", None)),
            "mini_ws_len": _safe_len(getattr(data_hub, "_mini_ws", None)),
            "coin_list_len": _safe_len(getattr(data_hub, "coin_list", None) or []),
            "account_balances_len": _safe_len(getattr(data_hub, "account_balances", None)),
            "all_symbols_len": _safe_len(getattr(data_hub, "all_symbols", None) or []),
            "top_100_len": _safe_len(getattr(data_hub, "top_100_symbols", None) or []),
            "ws_status": getattr(data_hub, "ws_status", None),
            "hub_snapshot_cached": getattr(data_hub, "_hub_snapshot", None) is not None,
        }
        dh["prices_est_bytes"] = _approx_mapping_bytes(getattr(data_hub, "prices", None))
        dh["mini_ws_est_bytes"] = _approx_mapping_bytes(getattr(data_hub, "_mini_ws", None))
    except Exception as e:
        inv["subsystems"]["data_hub"] = {"error": str(e)}

    try:
        from app.services import binance_spot as bs

        inv["subsystems"]["exchange_compact"] = {
            "cache_keys": _safe_len(getattr(bs, "_exchange_compact_cache", None) or {}),
        }
    except Exception as e:
        inv["subsystems"]["exchange_compact"] = {"error": str(e)}

    try:
        from app.services.binance_rest_log import get_rest_events_buffer_info

        inv["subsystems"]["binance_rest_log"] = get_rest_events_buffer_info()
    except Exception:
        try:
            from app.services import binance_rest_log as brl

            dq = getattr(brl, "_events_deque", None)
            inv["subsystems"]["binance_rest_log"] = {
                "deque_len": _safe_len(dq) if dq is not None else 0,
                "maxlen": getattr(dq, "maxlen", None),
            }
        except Exception as e:
            inv["subsystems"]["binance_rest_log"] = {"error": str(e)}

    try:
        from app.api import bots_engine as be

        perf = getattr(be, "PerfLRUCache", None)
        live = getattr(be, "_live_snapshot_cache", None)
        inv["subsystems"]["bots_engine_cache"] = {
            "perf_lru_entries": _safe_len(getattr(perf, "_cache", None) or {}) if perf else 0,
            "live_snapshot_entries": _safe_len(live or {}),
        }
    except Exception as e:
        inv["subsystems"]["bots_engine_cache"] = {"error": str(e)}

    try:
        from app.services import pnl_service as ps

        inv["subsystems"]["pnl_service"] = {
            "max_fifo_rows": getattr(ps, "_MAX_FIFO_TRADES_ROWS", None),
        }
    except Exception as e:
        inv["subsystems"]["pnl_service"] = {"error": str(e)}

    try:
        from app.botengine import orchestrator as orch

        inv["subsystems"]["worker_tasks"] = {
            "active_bot_tasks": _safe_len(getattr(orch, "_tasks", None) or {}),
        }
    except Exception as e:
        inv["subsystems"]["worker_tasks"] = {"error": str(e)}

    inv["hooks"] = {}
    for name, fn in list(_hooks.items()):
        try:
            inv["hooks"][name] = fn()
        except Exception as e:
            inv["hooks"][name] = {"error": str(e)}

    return inv


def register_capture_hook(name: str, fn: Callable[[], dict]) -> None:
    _hooks[name] = fn


def _quick_rss_mb() -> Optional[float]:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 2)
    except Exception:
        return None


def log_ram_event(
    category: str,
    detail: Optional[Dict[str, Any]] = None,
    *,
    component: Optional[str] = None,
) -> None:
    """Anlık olay satırı (snapshot döngüsü dışında)."""
    if not is_capture_enabled():
        return
    _append_capture_line(
        {
            "kind": "event",
            "category": category,
            "detail": detail or {},
            "rss_mb": _quick_rss_mb(),
        },
        component=component,
    )


def take_detailed_snapshot(component: str, reason: str = "") -> Dict[str, Any]:
    from app.observability.ram_probe import snapshot_now

    snap = snapshot_now(component, reason=reason or "capture")
    snap["kind"] = "snapshot"
    snap["inventory"] = collect_ram_inventory()
    _append_capture_line(snap, component=component)
    return snap


def _update_manifest(patch: Dict[str, Any]) -> None:
    try:
        _ensure_logs_dir()
        data: Dict[str, Any] = {}
        if _MANIFEST_PATH.exists():
            try:
                data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data.update(patch)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _MANIFEST_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("RAM_CAPTURE manifest update failed: %s", e)


def start_ram_capture_session(
    component: str,
    duration_sec: Optional[int] = None,
    interval_sec: Optional[int] = None,
) -> Optional[Path]:
    """
    Arka planda detaylı snapshot + env ile otomatik durma.
    RAM_CAPTURE=1 değilse no-op.
    """
    global _capture_thread, _component, _log_path
    if not is_capture_enabled():
        return None
    if _capture_thread and _capture_thread.is_alive():
        return _log_path

    _component = component
    dur = duration_sec if duration_sec is not None else int(os.getenv("RAM_CAPTURE_DURATION", "300"))
    interval = interval_sec if interval_sec is not None else int(
        os.getenv("RAM_CAPTURE_INTERVAL", os.getenv("RAM_PROBE_INTERVAL", "10"))
    )
    if dur >= 3600:
        interval = max(30, min(300, interval))
    else:
        interval = max(5, min(60, interval))
    dur = max(60, min(86400, dur))

    _ensure_logs_dir()
    _log_path = get_capture_log_path(component)

    os.environ.setdefault("RAM_PROBE", "1")
    os.environ.setdefault("RAM_PROBE_ENABLED", "1")

    try:
        from app.observability.ram_probe import _ensure_tracemalloc, start_ram_probe

        _ensure_tracemalloc()
        if os.getenv("RAM_CAPTURE_ALSO_PROBE", "1").strip() in ("1", "true", "yes"):
            start_ram_probe(component=component, interval_sec=interval)
    except Exception as e:
        logger.debug("RAM_CAPTURE ram_probe sidecar: %s", e)

    _capture_stop.clear()
    sid = _session_id_value()

    _append_capture_line(
        {
            "kind": "session_start",
            "reason": "ram_capture",
            "duration_sec": dur,
            "interval_sec": interval,
            "log_path": str(_log_path),
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        component=component,
    )

    manifest = {
        "session_id": sid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_sec": dur,
        "interval_sec": interval,
        "complete": False,
        "files": {component: str(_log_path)},
    }
    if _MANIFEST_PATH.exists():
        try:
            old = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            if old.get("session_id") == sid and isinstance(old.get("files"), dict):
                manifest["files"] = {**old["files"], component: str(_log_path)}
        except Exception:
            pass
    _update_manifest(manifest)

    def _loop() -> None:
        end_at = time.monotonic() + dur
        n = 0
        started = time.monotonic()
        last_hourly = started
        last_half = started
        while time.monotonic() < end_at:
            if _capture_stop.is_set():
                break
            now_m = time.monotonic()
            try:
                if now_m - last_hourly >= 3600.0:
                    take_detailed_snapshot(component, reason=f"hourly_{n}")
                    last_hourly = now_m
                    last_half = now_m
                elif dur >= 3600 and now_m - last_half >= 1800.0:
                    take_detailed_snapshot(component, reason=f"half_hourly_{n}")
                    last_half = now_m
                else:
                    take_detailed_snapshot(component, reason=f"periodic_{n}")
            except Exception as e:
                logger.warning("RAM_CAPTURE snapshot: %s", e)
                _append_capture_line(
                    {
                        "kind": "error",
                        "category": "snapshot_failed",
                        "detail": {"message": str(e)},
                    },
                    component=component,
                )
            n += 1
            wait = min(interval, max(0.0, end_at - time.monotonic()))
            if wait <= 0:
                break
            if _capture_stop.wait(timeout=wait):
                break
        try:
            take_detailed_snapshot(component, reason="session_end")
        except Exception:
            pass
        _append_capture_line(
            {
                "kind": "session_end",
                "snapshots_taken": n + 1,
                "lines_written": _line_count,
            },
            component=component,
        )
        _update_manifest(
            {
                "session_id": sid,
                "complete": True,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                f"{component}_lines": _line_count,
            }
        )
        logger.info(
            "RAM_CAPTURE finished component=%s session=%s lines=%s log=%s",
            component,
            sid,
            _line_count,
            _log_path,
        )

    _capture_thread = threading.Thread(
        target=_loop, daemon=True, name=f"ram_capture_{component}"
    )
    _capture_thread.start()
    logger.info(
        "RAM_CAPTURE started component=%s duration=%ss interval=%ss log=%s",
        component,
        dur,
        interval,
        _log_path,
    )
    return _log_path


def register_default_capture_hooks(component: str) -> None:
    """Web/worker ortak envanter kancaları."""
    if component == "web":

        def hook_sessions():
            try:
                from app.api import auth as auth_mod

                store = getattr(auth_mod, "_sessions", None)
                return {"auth_sessions_len": _safe_len(store or {})}
            except Exception as e:
                return {"auth_sessions_error": str(e)}

        register_capture_hook("auth_sessions", hook_sessions)

    if component == "worker":

        def hook_active_bots():
            try:
                from app.botengine.orchestrator import _tasks

                return {"active_bots": _safe_len(_tasks)}
            except Exception as e:
                return {"error": str(e)}

        def hook_cache_sizes():
            try:
                from app.services.data_hub import data_hub

                return {
                    "prices_len": _safe_len(getattr(data_hub, "prices", None)),
                    "all_symbols_len": _safe_len(getattr(data_hub, "all_symbols", None) or []),
                }
            except Exception as e:
                return {"error": str(e)}

        register_capture_hook("active_bots", hook_active_bots)
        register_capture_hook("cache_sizes", hook_cache_sizes)


def mirror_probe_line(payload: Dict[str, Any]) -> None:
    """ram_probe JSONL satırını capture dosyasına da yazar (kind=probe_mirror)."""
    if not is_capture_enabled():
        return
    payload = dict(payload)
    payload["kind"] = payload.get("kind") or "probe_mirror"
    if "inventory" not in payload and payload.get("reason") in (
        "periodic",
        "startup",
        "ORDER_FILLED",
    ):
        try:
            payload["inventory"] = collect_ram_inventory()
        except Exception:
            pass
    _append_capture_line(payload)


def load_capture_lines(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def analyze_session(session_id: Optional[str] = None) -> Path:
    """logs/ram_capture_analysis_{session}.md üret."""
    _ensure_logs_dir()
    if session_id is None and _MANIFEST_PATH.exists():
        try:
            session_id = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")).get(
                "session_id"
            )
        except Exception:
            session_id = None
    sid = session_id or "*"
    paths = sorted(_LOGS_DIR.glob(f"ram_capture_{sid.replace('*', '')}*.jsonl"))
    if not paths and sid != "*":
        paths = sorted(_LOGS_DIR.glob("ram_capture_*.jsonl"))
    if not paths:
        raise FileNotFoundError(
            "ram_capture JSONL bulunamadı. RAM_CAPTURE=1 ile web/worker başlatıp 5 dk bekleyin."
        )

    sid_tag = session_id or paths[0].name.replace("ram_capture_", "").rsplit("_", 1)[0]
    report_path = _LOGS_DIR / f"ram_capture_analysis_{sid_tag}.md"

    lines_out: List[str] = [
        "# RAM Capture Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Session: {session_id or '(latest files)'}",
        "",
    ]

    for path in paths:
        rows = load_capture_lines(path)
        comp = path.stem.split("_")[-1] if "_" in path.stem else "unknown"
        snapshots = [r for r in rows if r.get("kind") == "snapshot"]
        events = [r for r in rows if r.get("kind") == "event"]
        rss_vals = [
            float(r["rss_mb"])
            for r in snapshots
            if r.get("rss_mb") is not None
        ]
        lines_out.append(f"## {comp} — `{path.name}`")
        lines_out.append("")
        lines_out.append(f"- Total lines: {len(rows)}")
        lines_out.append(f"- Snapshots: {len(snapshots)}")
        lines_out.append(f"- Events: {len(events)}")
        if rss_vals:
            lines_out.append(
                f"- RSS (MB): start={rss_vals[0]:.1f} end={rss_vals[-1]:.1f} max={max(rss_vals):.1f} delta={rss_vals[-1]-rss_vals[0]:+.1f}"
            )
        lines_out.append("")

        by_cat: Dict[str, int] = {}
        for ev in events:
            c = ev.get("category") or "unknown"
            by_cat[c] = by_cat.get(c, 0) + 1
        if by_cat:
            lines_out.append("### Events by category")
            lines_out.append("")
            for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
                lines_out.append(f"- `{cat}`: {cnt}")
            lines_out.append("")

        heavy_http = sorted(
            [
                ev
                for ev in events
                if ev.get("category") == "http_request"
                and (ev.get("detail") or {}).get("duration_ms", 0) >= 200
            ],
            key=lambda e: (e.get("detail") or {}).get("duration_ms", 0),
            reverse=True,
        )[:15]
        if heavy_http:
            lines_out.append("### Slow HTTP (top 15)")
            lines_out.append("")
            lines_out.append("| ms | RSS Δ | path | bytes |")
            lines_out.append("|----|-------|------|-------|")
            for ev in heavy_http:
                d = ev.get("detail") or {}
                lines_out.append(
                    f"| {d.get('duration_ms', '—')} | {d.get('rss_delta_mb', '—')} | `{d.get('path', '')[:48]}` | {d.get('response_bytes', '—')} |"
                )
            lines_out.append("")

        last_inv = None
        for r in reversed(snapshots):
            if r.get("inventory"):
                last_inv = r["inventory"]
                break
        if last_inv:
            lines_out.append("### Last inventory snapshot")
            lines_out.append("")
            lines_out.append("```json")
            lines_out.append(json.dumps(last_inv, indent=2, ensure_ascii=False)[:8000])
            lines_out.append("```")
            lines_out.append("")

    report_path.write_text("\n".join(lines_out), encoding="utf-8")
    logger.info("RAM capture analysis: %s", report_path)
    return report_path
