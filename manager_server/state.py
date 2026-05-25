"""
Manager Server state: ring buffers, status, locks, process control, metrics.
Uses .run/web.pid, .run/worker.pid (engine=worker), logs/web.log, logs/worker.log.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

_TR_TZ = ZoneInfo("Europe/Istanbul")


def _now_tr_iso(epoch_sec: float | None = None) -> str:
    """Türkiye saati ISO format (YYYY-MM-DDTHH:MM:SS)."""
    if epoch_sec is None:
        epoch_sec = time.time()
    return datetime.fromtimestamp(epoch_sec, tz=_TR_TZ).strftime("%Y-%m-%dT%H:%M:%S")


def _now_tr_time(epoch_sec: float | None = None) -> str:
    """Türkiye saati sadece saat (HH:MM:SS)."""
    if epoch_sec is None:
        epoch_sec = time.time()
    return datetime.fromtimestamp(epoch_sec, tz=_TR_TZ).strftime("%H:%M:%S")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_DIR = _PROJECT_ROOT / ".run"
_LOGS_DIR = _PROJECT_ROOT / "logs"
_LOCKS_FILE = _RUN_DIR / "locks.json"
_DIAGNOSIS_FILE = _RUN_DIR / "diagnosis.json"
_HELPER = _PROJECT_ROOT / "scripts" / "runtime" / "local_web_worker_helper.py"
_WEB_METRICS_FILE = _RUN_DIR / "web.metrics.json"
_ENGINE_METRICS_FILE = _RUN_DIR / "engine.metrics.json"
_MANAGER_PID_FILE = _RUN_DIR / "manager.pid"

# Server keys: "web" | "engine" | "manager" | "html"
_WEB_PID = _RUN_DIR / "web.pid"
_ENGINE_PID = _RUN_DIR / "worker.pid"  # engine maps to worker
_WEB_LOG = _LOGS_DIR / "web.log"
_ENGINE_LOG = _LOGS_DIR / "worker.log"  # engine = worker process
_MANAGER_LOG = _LOGS_DIR / "manager.log"
_HTML_PID = _RUN_DIR / "html.pid"
_HTML_LOG = _LOGS_DIR / "html.log"
_WEB_PORT = int(os.environ.get("WEB_PORT", "8000"))
_HTML_PORT = int(os.environ.get("OMERALTINHTML_PORT", "8080"))
# marketing sitesi: env > marketing/ > eski klasor adlari > parent
if os.environ.get("OMERALTINHTML_PATH"):
    _OMERALTINHTML_PATH = Path(os.environ["OMERALTINHTML_PATH"])
elif (_PROJECT_ROOT / "marketing").is_dir():
    _OMERALTINHTML_PATH = _PROJECT_ROOT / "marketing"
elif (_PROJECT_ROOT / "omeraltinhtml").is_dir():
    _OMERALTINHTML_PATH = _PROJECT_ROOT / "omeraltinhtml"
elif (_PROJECT_ROOT / "Omeraltinhtml").is_dir():
    _OMERALTINHTML_PATH = _PROJECT_ROOT / "Omeraltinhtml"
else:
    _OMERALTINHTML_PATH = _PROJECT_ROOT.parent / "omeraltinhtml"

# --- RAM budget: sabit üst sınırlar, sınırsız büyüme yok ---
LOG_LINE_MAX = 400
RING_LINES = 300
RING_ERRORS = 30
RING_WARNS = 30
WS_BATCH_MAX = 40
TAIL_READ_BYTES = 256_000
ARCHIVE_QUERY_SCAN = 2500
JSONL_COUNT_CACHE_TTL = 60.0
ISSUE_PERSIST_DELAY_SEC = 20.0

# Metrics list caps (no unbounded growth)
_METRICS_TOP_PATHS = 30
_METRICS_TOP_IPS = 30
_METRICS_LOGIN_FAILS = 30

# Parsing
_ERROR_RE = re.compile(r"\b(ERROR|Traceback|Exception|CRITICAL)\b", re.I)
_WARN_RE = re.compile(r"\b(WARN(?:ING)?)\b", re.I)
# 401/Binance tekrarlarını ring'e ekleme: servis başına 10 dk'da en fazla 1
_WARN_401_THROTTLE_SEC = 600
_last_401_warn_ts: dict = {}  # key -> float (canlı tail için)
_last_401_placeholder_ts: dict = {}  # key -> float (throttle penceresinde placeholder eklendi mi)
_backfill_401_added: set = set()  # backfill sırasında 401 eklenen key'ler (servis başına 1)
_401_WARN_PATTERN = re.compile(
    r"(401\s+Unauthorized|BINANCE_SIGNED_ERROR.*401|BOT_EXECUTION_SKIP|BOT_EXECUTION_BALANCE_CHECK_FAIL)",
    re.I,
)
# Web access log: drop 200 OK lines from stream/export (SLOW_REQUEST WARN lines are kept)
_HTML_STATS_RE = re.compile(r"Günlük:\s*\d+\s*\|\s*Aylık:\s*\d+\s*\|\s*Toplam:\s*\d+")
_ACCESS_200_RE = re.compile(
    r'"\s*(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+[^"]*HTTP/1\.\d"\s+200\b',
    re.I,
)

_IS_WINDOWS = platform.system() == "Windows"
_jsonl_count_cache: dict[str, tuple[int, float]] = {}


def _truncate_line(line: str, max_len: int = LOG_LINE_MAX) -> str:
    line = (line or "").rstrip("\r\n")
    if len(line) <= max_len:
        return line
    return line[: max_len - 1] + "…"


def _read_file_tail_text(path: Path, max_bytes: int = TAIL_READ_BYTES) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        if size <= 0:
            return ""
        with open(path, "rb") as f:
            read_size = min(size, max_bytes)
            f.seek(-read_size, 2)
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _read_file_tail_lines(path: Path, n: int, max_bytes: int = TAIL_READ_BYTES) -> list[str]:
    text = _read_file_tail_text(path, max_bytes)
    if not text:
        return []
    lines = text.splitlines()
    return [_truncate_line(ln) for ln in lines[-n:] if ln.strip()]


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        n = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n
    except Exception:
        return 0


def _count_jsonl_lines_cached(path: Path) -> int:
    key = str(path)
    now = time.time()
    cached = _jsonl_count_cache.get(key)
    if cached and (now - cached[1]) < JSONL_COUNT_CACHE_TTL:
        return cached[0]
    n = _count_jsonl_lines(path)
    _jsonl_count_cache[key] = (n, now)
    return n


def _invalidate_jsonl_count_cache(path: Path) -> None:
    _jsonl_count_cache.pop(str(path), None)


def _trim_jsonl_file(path: Path, max_lines: int) -> None:
    if not path.exists():
        return
    try:
        total = _count_jsonl_lines(path)
        if total <= max_lines:
            return
        skip = total - max_lines
        tmp = path.with_suffix(path.suffix + ".tmp")
        kept = 0
        with open(path, "r", encoding="utf-8", errors="replace") as src, open(tmp, "w", encoding="utf-8") as dst:
            for line in src:
                if not line.strip():
                    continue
                if skip > 0:
                    skip -= 1
                    continue
                dst.write(line if line.endswith("\n") else line + "\n")
                kept += 1
        tmp.replace(path)
        _jsonl_count_cache[str(path)] = (kept, time.time())
    except Exception:
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _query_jsonl_archive(
    path: Path,
    limit: int,
    offset: int,
    match_fn,
    max_scan: int = ARCHIVE_QUERY_SCAN,
) -> tuple[list, int]:
    if not path.exists():
        return [], 0
    text = _read_file_tail_text(path, TAIL_READ_BYTES * 4)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > max_scan:
        lines = lines[-max_scan:]
    matched: list = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if match_fn(rec):
            matched.append(rec)
    total = len(matched)
    return matched[offset: offset + limit], total


try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

# In-memory state
status: dict = {}  # key -> { running, pid, started_at, locked, restart_count, last_exit_code, last_signal, last_start_attempt_ts, last_stop_ts }
logs_ring: dict = {}  # key -> deque of str (raw lines)
_diagnosis: dict = {}  # key -> last diagnosis dict (persisted)
_diagnosis_lock = threading.Lock()
errors_ring: dict = {}  # key -> deque of str
warns_ring: dict = {}  # key -> deque of str
locks: dict = {}  # key -> bool (persisted to _LOCKS_FILE)
_ws_batch: dict = {}  # key -> list of { ts, level, text }
_batch_lock = threading.Lock()
_tail_threads: dict = {}
_tail_stop: dict = {}  # key -> event to stop thread

# Metrics: single object, updated every 2s (no ring, bounded lists only)
metrics_cache: dict = {}
_metrics_lock = threading.Lock()
_metrics_thread: Optional[threading.Thread] = None
_metrics_stop = threading.Event()

# Issues (Sentry-style, bounded): fingerprint -> issue dict. LRU evict when > MAX_ISSUES
MAX_ISSUES = 300
MAX_ISSUE_SAMPLES = 3
ISSUE_COMMENT_MAX = 15
ISSUE_STATUS_HIST_MAX = 15
MAX_ISSUES_ARCHIVE = 10000
_ISSUES_ACTIVE_FILE = _RUN_DIR / "issues_active.json"
_ISSUES_ARCHIVE_FILE = _RUN_DIR / "issues_archive.jsonl"
ISSUE_ID_COUNTER = [0]  # list to allow mutability in nested fn
_issues: dict = {}  # fingerprint -> { id, fingerprint, severity, status, first_seen, last_seen, count, samples, tags }
_issues_lock = threading.Lock()
_issues_order: deque = deque()  # insertion order; evicted manually at MAX_ISSUES
_issues_persist_timer: Optional[threading.Timer] = None
_issues_persist_lock = threading.Lock()

# Audit events (bounded, persisted to .run/audit.json)
MAX_AUDIT = 300
MAX_AUDIT_ARCHIVE = 10000
_AUDIT_FILE = _RUN_DIR / "audit.json"
_AUDIT_ARCHIVE_FILE = _RUN_DIR / "audit_archive.jsonl"
_audit_events: deque = deque()
_audit_lock = threading.Lock()

# Alerts (bounded max 200, for toast/WS)
MAX_ALERTS = 50
_ALERT_ID_COUNTER = [0]
_alerts: deque = deque(maxlen=MAX_ALERTS)
_alerts_lock = threading.Lock()
_alert_cooldown: dict = {}  # kind -> last_ts for dedup
# Alert threshold state (for spike detection)
_last_5xx: int = 0
_last_login_count: int = 0
_TICK_AGE_THRESHOLD: float = 60.0
_5XX_RATE_THRESHOLD: float = 0.05
_LOGIN_SPIKE_THRESHOLD: int = 10
_RESTART_LOOP_COUNT: int = 5

# Metrics history for export (bounded ~900, downsampled)
MAX_METRICS_HISTORY = 180
_metrics_history: deque = deque(maxlen=MAX_METRICS_HISTORY)
_metrics_history_lock = threading.Lock()


def _read_pid(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def _read_json_capped(path: Path, max_paths: int = _METRICS_TOP_PATHS, max_ips: int = _METRICS_TOP_IPS, max_login_fails: int = _METRICS_LOGIN_FAILS) -> dict:
    """Read app metrics JSON and cap list lengths. Returns empty dict on missing/error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # Cap list-like fields
        for key in ("top_paths", "top_paths_requests", "paths"):
            if isinstance(data.get(key), list) and len(data[key]) > max_paths:
                data[key] = data[key][:max_paths]
        for key in ("top_ips", "top_ips_requests", "ips"):
            if isinstance(data.get(key), list) and len(data[key]) > max_ips:
                data[key] = data[key][:max_ips]
        if isinstance(data.get("last_login_fails"), list) and len(data["last_login_fails"]) > max_login_fails:
            data["last_login_fails"] = data["last_login_fails"][:max_login_fails]
        return data
    except Exception:
        return {}


def _process_metrics(pid: Optional[int], started_at: Optional[float]) -> dict:
    """Return { pid, cpu_pct, rss_mb, uptime_s, restart_count, thread_count } for a process. Bounded/safe."""
    out: dict = {"pid": pid, "cpu_pct": None, "rss_mb": None, "uptime_s": None, "restart_count": 0, "thread_count": None}
    if pid is None:
        return out
    if not psutil:
        return out
    try:
        p = psutil.Process(pid)
        out["cpu_pct"] = round(p.cpu_percent(interval=0.1) or 0, 1)
        out["rss_mb"] = round((p.memory_info().rss or 0) / (1024 * 1024), 1)
        out["uptime_s"] = int(time.time() - p.create_time()) if p.create_time() else None
        try:
            out["thread_count"] = p.num_threads()
        except (AttributeError, psutil.AccessDenied):
            pass
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        pass
    if started_at and isinstance(started_at, (int, float)):
        out["uptime_s"] = int(time.time() - started_at)
    return out


def _collect_metrics() -> None:
    """Update metrics_cache once: system + manager/web/engine + app JSON files. All lists capped."""
    global metrics_cache
    system = {"cpu_pct": None, "ram_used_mb": None, "ram_total_mb": None, "disk_used_mb": None, "disk_total_mb": None, "net_bytes_sent": None, "net_bytes_recv": None, "load_avg": None}
    if psutil:
        try:
            system["cpu_pct"] = round(psutil.cpu_percent(interval=0.1) or 0, 1)
            v = psutil.virtual_memory()
            system["ram_used_mb"] = int(v.used / (1024 * 1024))
            system["ram_total_mb"] = int(v.total / (1024 * 1024))
            disk_root = "C:" if _IS_WINDOWS else "/"
            d = psutil.disk_usage(disk_root)
            system["disk_used_mb"] = int(d.used / (1024 * 1024))
            system["disk_total_mb"] = int(d.total / (1024 * 1024))
            net = psutil.net_io_counters()
            if net:
                system["net_bytes_sent"] = getattr(net, "bytes_sent", None)
                system["net_bytes_recv"] = getattr(net, "bytes_recv", None)
            try:
                load = os.getloadavg()
                system["load_avg"] = round(load[0], 2) if load else None
            except (AttributeError, OSError):
                pass
        except Exception:
            pass
    manager_pid = _read_pid(_MANAGER_PID_FILE) if _MANAGER_PID_FILE.exists() else os.getpid()
    manager_started = None
    if (_RUN_DIR / "manager.started_at").exists():
        try:
            manager_started = float((_RUN_DIR / "manager.started_at").read_text().strip())
        except Exception:
            pass
    web_pid = _read_pid(_WEB_PID)
    web_started = None
    if (_RUN_DIR / "web.started_at").exists():
        try:
            web_started = float((_RUN_DIR / "web.started_at").read_text().strip())
        except Exception:
            pass
    engine_pid = _read_pid(_ENGINE_PID)
    engine_started = None
    if (_RUN_DIR / "worker.started_at").exists():
        try:
            engine_started = float((_RUN_DIR / "worker.started_at").read_text().strip())
        except Exception:
            pass
    manager_proc = _process_metrics(manager_pid, manager_started)
    web_proc = _process_metrics(web_pid, web_started)
    engine_proc = _process_metrics(engine_pid, engine_started)
    html_running = _is_port_in_use(_HTML_PORT)
    html_pid = _pid_on_port(_HTML_PORT) if html_running else _read_pid(_HTML_PID)
    html_started = None
    if (_RUN_DIR / "html.started_at").exists():
        try:
            html_started = float((_RUN_DIR / "html.started_at").read_text().strip())
        except Exception:
            pass
    html_proc = _process_metrics(html_pid, html_started)
    web_app = _read_json_capped(_WEB_METRICS_FILE)
    engine_app = _read_json_capped(_ENGINE_METRICS_FILE)
    with _metrics_lock:
        metrics_cache.clear()
        metrics_cache.update({
            "ts": time.time(),
            "system": system,
            "manager": manager_proc,
            "web": web_proc,
            "engine": engine_proc,
            "html": html_proc,
            "web_app": web_app,
            "engine_app": engine_app,
        })
    # Alert triggers (outside lock, no sound)
    try:
        global _last_5xx, _last_login_count
        total_req = web_app.get("request_total") or 0
        status_5xx = web_app.get("status_5xx") or 0
        err_rate = web_app.get("error_rate") or 0
        if total_req > 100 and (err_rate >= _5XX_RATE_THRESHOLD or status_5xx > max(5, _last_5xx + 3)):
            add_alert("CRIT", "5xx_spike", "Web 5xx/error rate spike: 5xx=%s rate=%.2f" % (status_5xx, err_rate), {"status_5xx": status_5xx, "error_rate": err_rate})
        _last_5xx = status_5xx
        tick_age = engine_app.get("last_tick_age_s")
        if tick_age is not None and tick_age >= _TICK_AGE_THRESHOLD:
            add_alert("CRIT", "tick_age", "Engine last_tick_age %.0fs >= %.0fs" % (tick_age, _TICK_AGE_THRESHOLD), {"last_tick_age_s": tick_age})
        login_fails = (web_app.get("last_login_fails") or [])
        n_login = len(login_fails)
        if n_login >= _LOGIN_SPIKE_THRESHOLD and n_login > _last_login_count + 2:
            add_alert("WARN", "login_spike", "Login fail spike: %d in last 50" % n_login, {"count": n_login})
        _last_login_count = n_login
        recent = get_audit_events(limit=20)
        restarts = [e for e in recent if e.get("action") in ("restart", "start")]
        if len(restarts) >= _RESTART_LOOP_COUNT:
            add_alert("WARN", "restart_loop", "Restart loop: %d restart/start in last 20 audit" % len(restarts), {"count": len(restarts)})
    except Exception:
        pass
    # Append to metrics history (lightweight snapshot for export)
    try:
        snap = {
            "ts": _now_tr_iso(),
            "ts_epoch": time.time(),
            "cpu_pct": system.get("cpu_pct"),
            "ram_used_mb": system.get("ram_used_mb"),
            "ram_total_mb": system.get("ram_total_mb"),
            "requests_per_min": web_app.get("requests_per_min"),
            "status_5xx": web_app.get("status_5xx"),
            "error_rate": web_app.get("error_rate"),
            "active_bots": engine_app.get("active_bots"),
            "last_tick_age_s": engine_app.get("last_tick_age_s"),
        }
        with _metrics_history_lock:
            _metrics_history.append(snap)
    except Exception:
        pass


def get_metrics_history(limit: int = 900) -> list:
    with _metrics_history_lock:
        return list(_metrics_history)[-limit:]


def _metrics_loop() -> None:
    while not _metrics_stop.is_set():
        try:
            _collect_metrics()
        except Exception:
            pass
        _metrics_stop.wait(timeout=2.0)


def get_metrics() -> dict:
    """Return a copy of current metrics_cache for API."""
    with _metrics_lock:
        out = json.loads(json.dumps(metrics_cache, default=str))
    # Cache boş kaldıysa dosyadan taze oku (web/engine app metrikleri)
    if not out.get("web_app"):
        wa = _read_json_capped(_WEB_METRICS_FILE)
        if wa:
            out["web_app"] = wa
    if not out.get("engine_app"):
        ea = _read_json_capped(_ENGINE_METRICS_FILE)
        if ea:
            out["engine_app"] = ea
    return out


def start_metrics_thread() -> None:
    """Start background thread that updates metrics_cache every 2s."""
    global _metrics_thread
    if _metrics_thread is not None and _metrics_thread.is_alive():
        return
    _metrics_stop.clear()
    _collect_metrics()
    _metrics_thread = threading.Thread(target=_metrics_loop, daemon=True)
    _metrics_thread.start()


def get_traffic() -> dict:
    """Normalized view of web metrics (from cache or file). Lists capped."""
    with _metrics_lock:
        if metrics_cache.get("web_app"):
            return json.loads(json.dumps(metrics_cache["web_app"], default=str))
    return _read_json_capped(_WEB_METRICS_FILE)


def get_engine_metrics() -> dict:
    """Normalized view of engine metrics (from cache or file). Lists capped."""
    with _metrics_lock:
        if metrics_cache.get("engine_app"):
            return json.loads(json.dumps(metrics_cache["engine_app"], default=str))
    return _read_json_capped(_ENGINE_METRICS_FILE)


def _process_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
            )
            return str(pid) in (r.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_path(key: str) -> Path:
    if key == "web":
        return _WEB_PID
    if key == "engine":
        return _ENGINE_PID
    if key == "html":
        return _HTML_PID
    return _MANAGER_PID_FILE  # manager


def _log_path(key: str) -> Path:
    if key == "web":
        return _WEB_LOG
    if key == "engine":
        return _ENGINE_LOG
    if key == "html":
        return _HTML_LOG
    return _MANAGER_LOG  # manager


def _python_exe() -> str:
    venv_py = _PROJECT_ROOT / ".venv" / ("Scripts" if _IS_WINDOWS else "bin") / ("python.exe" if _IS_WINDOWS else "python")
    if venv_py.exists():
        return str(venv_py)
    return os.environ.get("PYTHON", "python3" if not _IS_WINDOWS else "python")


def _helper_cmd(action: str) -> list:
    """e.g. web-start, worker-stop. engine -> worker for helper."""
    if action.startswith("engine"):
        action = "worker" + action[6:]
    return [_python_exe(), str(_HELPER), action]


def load_locks() -> dict:
    if not _LOCKS_FILE.exists():
        return {"web": False, "engine": False}
    try:
        d = json.loads(_LOCKS_FILE.read_text(encoding="utf-8"))
        return {"web": bool(d.get("web")), "engine": bool(d.get("engine"))}
    except Exception:
        return {"web": False, "engine": False}


def save_locks(l: dict) -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    d = {"web": l.get("web", False), "engine": l.get("engine", False), "updated_at": _now_tr_iso()}
    _LOCKS_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def init_state() -> None:
    global status, logs_ring, errors_ring, warns_ring, locks
    _load_audit()
    _load_active_issues()
    _load_diagnosis()
    locks = load_locks()
    for key in ("web", "engine"):
        pid_path = _pid_path(key)
        pid = _read_pid(pid_path)
        started_at = None
        if (_RUN_DIR / ("web.started_at" if key == "web" else "worker.started_at")).exists():
            try:
                started_at = float((_RUN_DIR / ("web.started_at" if key == "web" else "worker.started_at")).read_text().strip())
            except Exception:
                pass
        status[key] = {
            "running": _process_alive(pid),
            "pid": pid,
            "started_at": started_at,
            "locked": locks.get(key, False),
            "restart_count": 0,
            "last_exit_code": None,
            "last_signal": None,
            "last_start_attempt_ts": None,
            "last_stop_ts": None,
        }
        logs_ring[key] = deque(maxlen=RING_LINES)
        errors_ring[key] = deque(maxlen=RING_ERRORS)
        warns_ring[key] = deque(maxlen=RING_WARNS)
        _ws_batch[key] = []
    # Manager: this process; status from .run/manager.pid and manager.started_at
    manager_pid = _read_pid(_MANAGER_PID_FILE) if _MANAGER_PID_FILE.exists() else os.getpid()
    manager_started = None
    if (_RUN_DIR / "manager.started_at").exists():
        try:
            manager_started = float((_RUN_DIR / "manager.started_at").read_text().strip())
        except Exception:
            pass
    status["manager"] = {
        "running": True,  # we are the manager
        "pid": manager_pid,
        "started_at": manager_started,
        "locked": False,
        "restart_count": 0,
    }
    logs_ring["manager"] = deque(maxlen=RING_LINES)
    errors_ring["manager"] = deque(maxlen=RING_ERRORS)
    warns_ring["manager"] = deque(maxlen=RING_WARNS)
    _ws_batch["manager"] = []
    # HTML (omeraltinhtml): logs_ring for panel
    logs_ring["html"] = deque(maxlen=RING_LINES)
    errors_ring["html"] = deque(maxlen=RING_ERRORS)
    warns_ring["html"] = deque(maxlen=RING_WARNS)
    _ws_batch["html"] = []
    # HTML (omeraltinhtml): calistir.bat / stop.bat; running = port açık
    html_started = None
    if (_RUN_DIR / "html.started_at").exists():
        try:
            html_started = float((_RUN_DIR / "html.started_at").read_text().strip())
        except Exception:
            pass
    status["html"] = {
        "running": _is_port_in_use(_HTML_PORT),
        "pid": None,
        "started_at": html_started,
        "locked": False,
        "restart_count": 0,
    }


def classify_line(line: str) -> str:
    if _ERROR_RE.search(line):
        return "ERROR"
    if _WARN_RE.search(line):
        return "WARN"
    return "INFO"


def _is_web_access_200_line(line: str) -> bool:
    """True if line is a web access log with status 200 that should be hidden (not SLOW_REQUEST)."""
    if not line or "SLOW_REQUEST" in line:
        return False
    return bool(_ACCESS_200_RE.search(line))


def _is_noise_line(line: str, level: str) -> bool:
    """True if line should not be added to errors_ring/warns_ring (gürültü)."""
    s = line.strip()
    if not s:
        return True
    if level == "ERROR":
        # WebSocket normal kapanma (1000/1001) — istemci sayfadan ayrıldığında beklenen davranış
        if "ConnectionClosedOK" in s or "1001 (going away)" in s or "received 1001" in s:
            return True
        # Sadece "Traceback (most recent call last):" başlığı, stack yok
        if s == "Traceback (most recent call last):" or s.startswith("Traceback (most recent call last):") and len(s) < 80:
            return True
    if level == "WARN":
        # Kesik veya anlamsız: sadece "warnings.warn(" gibi
        if re.match(r"^\s*warnings\.warn\s*\(\s*$", s) or (s.startswith("warnings.warn(") and len(s) < 30):
            return True
        # SLOW_REQUEST: yavaş istek uyarıları panelde listelenmesin (log dosyasında kalsın)
        if "SLOW_REQUEST" in s:
            return True
        # Manager kendi /api/issues/summary 404 probe satırları — panel gürültüsü
        if "/api/issues/summary" in s and "404" in s:
            return True
    return False


def _should_throttle_401_warn(key: str, line: str) -> bool:
    """True if this 401/Binance/BOT WARN should be skipped (recent duplicate). Canlı tail için.
    Throttle penceresinde ilk atlamada ring'e tek özet satır eklenir (panelde görünsün)."""
    if not _401_WARN_PATTERN.search(line):
        return False
    now = time.time()
    last = _last_401_warn_ts.get(key, 0)
    if now - last < _WARN_401_THROTTLE_SEC:
        # Throttle penceresinde ilk kez atlıyorsak, tek özet satır ekle (10 dk'da 1)
        placeholder_last = _last_401_placeholder_ts.get(key, 0)
        if now - placeholder_last >= _WARN_401_THROTTLE_SEC:
            _last_401_placeholder_ts[key] = now
            placeholder = "[401/Binance uyarısı – tekrarlar 10 dk throttle, panelde tek satır gösterilir]"
            if key in warns_ring:
                warns_ring[key].append(placeholder)
        return True
    _last_401_warn_ts[key] = now
    return False


def _backfill_should_skip_401_warn(key: str, line: str) -> bool:
    """Backfill sırasında aynı servis için 401 WARN zaten eklendiyse atla (servis başına 1)."""
    if not _401_WARN_PATTERN.search(line):
        return False
    if key in _backfill_401_added:
        return True
    _backfill_401_added.add(key)
    return False


# --- Issue fingerprinting (Sentry-style, single-line) ---
_EXCEPTION_TYPE_RE = re.compile(r"^(\w+(?:\.\w+)*Error|Exception|[\w.]+):\s*", re.I)
_FILE_LINE_RE = re.compile(r'\s+File\s+"([^"]+)"\s*,\s*line\s+(\d+)', re.I)


def _normalize_for_fingerprint(line: str) -> str:
    """Normalize log line for fingerprint: strip numbers, UUIDs, paths to stable signature."""
    s = line.strip()[:300]
    s = re.sub(r"\d+", "0", s)
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "U", s, flags=re.I)
    s = re.sub(r"/[^\s]+/", "/path/", s)
    return s


def _fingerprint_line(line: str) -> str:
    """Produce stable fingerprint for issue grouping. Exception type + top frame or normalized message."""
    norm = _normalize_for_fingerprint(line)
    mt = _EXCEPTION_TYPE_RE.search(norm)
    if mt:
        exc_type = mt.group(1).split(".")[-1]
        return hashlib.sha256((exc_type + ":" + norm[:150]).encode()).hexdigest()[:20]
    return hashlib.sha256(norm.encode()).hexdigest()[:20]


def _issue_from_disk(raw: dict) -> dict:
    i = dict(raw)
    if not isinstance(i.get("comments"), deque):
        i["comments"] = deque(i.get("comments") or [], maxlen=ISSUE_COMMENT_MAX)
    if not isinstance(i.get("status_history"), deque):
        i["status_history"] = deque(i.get("status_history") or [], maxlen=ISSUE_STATUS_HIST_MAX)
    i.setdefault("assignee", None)
    i.setdefault("labels", [])
    i.setdefault("sla_note", None)
    return i


def _parse_issue_id_num(issue_id: Optional[str]) -> int:
    if not issue_id or not str(issue_id).startswith("ISS-"):
        return 0
    try:
        return int(str(issue_id)[4:])
    except ValueError:
        return 0


def _sync_issue_counter_from_records(records: list) -> None:
    max_id = ISSUE_ID_COUNTER[0]
    for rec in records:
        max_id = max(max_id, _parse_issue_id_num(rec.get("id")))
    ISSUE_ID_COUNTER[0] = max_id


def _append_issue_archive(issue: dict, reason: str = "capacity") -> None:
    """Evicted issues → local jsonl backup under .run/issues_archive.jsonl."""
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        record = _issue_to_dict(issue)
        record["_backup_reason"] = reason
        record["_backup_at"] = _now_tr_iso()
        with open(_ISSUES_ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        _invalidate_jsonl_count_cache(_ISSUES_ARCHIVE_FILE)
        _trim_jsonl_file(_ISSUES_ARCHIVE_FILE, MAX_ISSUES_ARCHIVE)
    except Exception:
        pass


def _trim_issues_archive_file() -> None:
    _trim_jsonl_file(_ISSUES_ARCHIVE_FILE, MAX_ISSUES_ARCHIVE)


def _pick_eviction_fingerprint() -> Optional[str]:
    """Evict archived/resolved before open; oldest last_seen within tier."""
    if not _issues:
        return None
    rank = {"ARCHIVED": 0, "RESOLVED": 1, "ACK": 2, "OPEN": 3}
    candidates: list[tuple] = []
    for fp in list(_issues_order):
        i = _issues.get(fp)
        if not i:
            continue
        st = (i.get("status") or "OPEN").upper()
        candidates.append((rank.get(st, 9), i.get("last_seen") or "", fp))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _evict_issue_for_capacity() -> None:
    fp = _pick_eviction_fingerprint()
    if not fp:
        return
    try:
        _issues_order.remove(fp)
    except ValueError:
        pass
    old = _issues.pop(fp, None)
    if old:
        _append_issue_archive(old, "capacity")


def _persist_active_issues() -> None:
    with _issues_lock:
        payload = {
            "counter": ISSUE_ID_COUNTER[0],
            "order": list(_issues_order),
            "issues": {fp: _issue_to_dict(i) for fp, i in _issues.items()},
            "saved_at": _now_tr_iso(),
        }
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _ISSUES_ACTIVE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(_ISSUES_ACTIVE_FILE)
    except Exception:
        pass


def _schedule_persist_active_issues(delay_sec: float = ISSUE_PERSIST_DELAY_SEC) -> None:
    global _issues_persist_timer
    with _issues_persist_lock:

        def _run() -> None:
            _persist_active_issues()

        if _issues_persist_timer is not None:
            _issues_persist_timer.cancel()
        _issues_persist_timer = threading.Timer(delay_sec, _run)
        _issues_persist_timer.daemon = True
        _issues_persist_timer.start()


def _load_active_issues() -> None:
    global _issues, _issues_order
    if _ISSUES_ACTIVE_FILE.exists():
        try:
            data = json.loads(_ISSUES_ACTIVE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ISSUE_ID_COUNTER[0] = int(data.get("counter") or 0)
                order = data.get("order") or []
                raw_issues = data.get("issues") or {}
                if isinstance(raw_issues, dict):
                    _issues.clear()
                    _issues_order.clear()
                    for fp in order:
                        if fp in raw_issues:
                            _issues[fp] = _issue_from_disk(raw_issues[fp])
                            _issues_order.append(fp)
                    for fp, raw in raw_issues.items():
                        if fp not in _issues:
                            _issues[fp] = _issue_from_disk(raw)
                            _issues_order.append(fp)
        except Exception:
            pass
    max_id = ISSUE_ID_COUNTER[0]
    for i in _issues.values():
        max_id = max(max_id, _parse_issue_id_num(i.get("id")))
    for line in _read_file_tail_lines(_ISSUES_ARCHIVE_FILE, 32):
        try:
            rec = json.loads(line)
            max_id = max(max_id, _parse_issue_id_num(rec.get("id")))
        except json.JSONDecodeError:
            continue
    ISSUE_ID_COUNTER[0] = max_id


def _count_issues_archive() -> int:
    return _count_jsonl_lines_cached(_ISSUES_ARCHIVE_FILE)


def get_issues_archive(limit: int = 100, q: Optional[str] = None, offset: int = 0, service: Optional[str] = None) -> dict:
    """Read backed-up issues from local jsonl tail (bounded RAM)."""
    limit = max(1, min(500, limit))
    offset = max(0, offset)
    needle = (q or "").strip().lower()

    def _match(rec: dict) -> bool:
        if service and (rec.get("tags") or {}).get("service") != service:
            return False
        if needle:
            hay = " ".join([
                str(rec.get("id") or ""),
                str(rec.get("status") or ""),
                str(rec.get("severity") or ""),
                str((rec.get("tags") or {}).get("service") or ""),
                " ".join(str(s) for s in (rec.get("samples") or [])[:2]),
            ]).lower()
            if needle not in hay:
                return False
        return True

    items, scanned_total = _query_jsonl_archive(_ISSUES_ARCHIVE_FILE, limit, offset, _match)
    return {
        "items": items,
        "total": _count_jsonl_lines_cached(_ISSUES_ARCHIVE_FILE) if not needle and not service else scanned_total,
        "limit": limit,
        "offset": offset,
        "path": str(_ISSUES_ARCHIVE_FILE),
    }


def _ingest_issue(key: str, line: str, level: str) -> None:
    """Register or update an issue from a log line. Bounded: max 300 active; overflow → local jsonl."""
    fp = _fingerprint_line(line)
    now_iso = _now_tr_iso()
    with _issues_lock:
        if fp in _issues:
            i = _issues[fp]
            i["last_seen"] = now_iso
            i["count"] = i.get("count", 0) + 1
            if i.get("status") == "ARCHIVED":
                i["status"] = "OPEN"
                i.pop("archived_at", None)
                _push_status_history(i, "REOPENED")
            samples = i.get("samples", [])
            if line not in samples[-MAX_ISSUE_SAMPLES:]:
                samples.append(_truncate_line(line, LOG_LINE_MAX))
                i["samples"] = samples[-MAX_ISSUE_SAMPLES:]
        else:
            while len(_issues) >= MAX_ISSUES:
                _evict_issue_for_capacity()
            ISSUE_ID_COUNTER[0] += 1
            iid = "ISS-%06d" % ISSUE_ID_COUNTER[0]
            _issues_order.append(fp)
            _issues[fp] = {
                "id": iid,
                "fingerprint": fp,
                "severity": level,
                "status": "OPEN",
                "first_seen": now_iso,
                "last_seen": now_iso,
                "count": 1,
                "samples": [_truncate_line(line, LOG_LINE_MAX)],
                "tags": {"service": key},
                "assignee": None,
                "labels": [],
                "sla_note": None,
                "comments": deque(maxlen=ISSUE_COMMENT_MAX),
                "status_history": deque(maxlen=ISSUE_STATUS_HIST_MAX),
            }
            _issues[fp]["status_history"].append({"ts": now_iso, "status": "OPEN"})
            if level == "ERROR":
                add_alert("CRIT", "error_issue", _truncate_line(line, 200), {"issue_id": iid, "service": key})
            _schedule_persist_active_issues()


def _issue_to_dict(i: dict) -> dict:
    """Copy issue for API; ensure assignee/labels/sla_note/comments/status_history present and deques as lists."""
    out = dict(i)
    out.setdefault("assignee", None)
    out.setdefault("labels", [])
    out.setdefault("sla_note", None)
    if isinstance(out.get("comments"), deque):
        out["comments"] = list(out["comments"])
    else:
        out.setdefault("comments", [])
    if isinstance(out.get("status_history"), deque):
        out["status_history"] = list(out["status_history"])
    else:
        out.setdefault("status_history", [])
    if isinstance(out.get("labels"), list) and len(out["labels"]) > 10:
        out["labels"] = out["labels"][:10]
    return out


def get_issue_stats() -> dict:
    """Counts by status for incidents dashboard."""
    counts = {"open": 0, "ack": 0, "resolved": 0, "archived": 0, "total": 0}
    with _issues_lock:
        for i in _issues.values():
            counts["total"] += 1
            st = (i.get("status") or "OPEN").upper()
            if st == "OPEN":
                counts["open"] += 1
            elif st == "ACK":
                counts["ack"] += 1
            elif st == "RESOLVED":
                counts["resolved"] += 1
            elif st == "ARCHIVED":
                counts["archived"] += 1
    counts["active"] = counts["open"] + counts["ack"] + counts["resolved"]
    counts["backup"] = _count_issues_archive()
    counts["max_active"] = MAX_ISSUES
    return counts


def get_issues(
    service: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    q: Optional[str] = None,
) -> list:
    """Return list of issues (open first, then by last_seen). Capped by limit (max 200)."""
    limit = max(1, min(200, limit))
    with _issues_lock:
        out = [_issue_to_dict(i) for i in _issues.values()]
    if service:
        out = [i for i in out if i.get("tags", {}).get("service") == service]
    sf = (status_filter or "").strip().upper()
    if sf == "ACTIVE":
        out = [i for i in out if (i.get("status") or "OPEN").upper() != "ARCHIVED"]
    elif sf:
        out = [i for i in out if (i.get("status") or "").upper() == sf]
    if q:
        needle = q.strip().lower()
        if needle:

            def _match(issue: dict) -> bool:
                parts = [
                    str(issue.get("id") or ""),
                    str(issue.get("status") or ""),
                    str(issue.get("severity") or ""),
                    str(issue.get("assignee") or ""),
                    " ".join(issue.get("labels") or []),
                    str((issue.get("tags") or {}).get("service") or ""),
                ]
                parts.extend(str(s) for s in (issue.get("samples") or [])[:3])
                return needle in " ".join(parts).lower()

            out = [i for i in out if _match(i)]
    status_rank = {"OPEN": 0, "ACK": 1, "RESOLVED": 2, "ARCHIVED": 3}
    out.sort(key=lambda x: x.get("last_seen") or "", reverse=True)
    out.sort(key=lambda x: status_rank.get((x.get("status") or "OPEN").upper(), 9))
    return out[:limit]


def get_issue_by_id(issue_id: str) -> Optional[dict]:
    """Return single issue by id or None."""
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                return _issue_to_dict(i)
    return None


def _push_status_history(issue: dict, new_status: str) -> None:
    hist = issue.get("status_history")
    if not isinstance(hist, deque):
        issue["status_history"] = deque(maxlen=ISSUE_STATUS_HIST_MAX)
        hist = issue["status_history"]
    hist.append({"ts": _now_tr_iso(), "status": new_status})


def issue_ack(issue_id: str) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["status"] = "ACK"
                _push_status_history(i, "ACK")
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_ack", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def issue_resolve(issue_id: str) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["status"] = "RESOLVED"
                _push_status_history(i, "RESOLVED")
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_resolve", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def issue_archive(issue_id: str) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["status"] = "ARCHIVED"
                i["archived_at"] = _now_tr_iso()
                _push_status_history(i, "ARCHIVED")
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_archive", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def issue_reopen(issue_id: str) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["status"] = "OPEN"
                i.pop("archived_at", None)
                _push_status_history(i, "REOPENED")
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_reopen", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def issue_assign(issue_id: str, assignee: Optional[str]) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["assignee"] = (assignee or "").strip() or None
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_assign", {"issue_id": issue_id, "assignee": assignee})
        _schedule_persist_active_issues()
    return out


def issue_labels(issue_id: str, labels: list) -> Optional[dict]:
    labels = [str(x).strip()[:64] for x in (labels or [])[:10]]
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["labels"] = labels
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_labels", {"issue_id": issue_id, "labels": labels})
        _schedule_persist_active_issues()
    return out


def issue_comment(issue_id: str, text: str, author: str = "local") -> Optional[dict]:
    text = (text or "").strip()[:500]
    if not text:
        return get_issue_by_id(issue_id)
    now_iso = _now_tr_iso()
    entry = {"ts": now_iso, "author": (author or "local")[:64], "text": text}
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                comm = i.get("comments")
                if not isinstance(comm, deque):
                    i["comments"] = deque(maxlen=ISSUE_COMMENT_MAX)
                    comm = i["comments"]
                comm.append(entry)
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_comment", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def issue_sla(issue_id: str, sla_note: Optional[str]) -> Optional[dict]:
    with _issues_lock:
        for i in _issues.values():
            if i.get("id") == issue_id:
                i["sla_note"] = (sla_note or "").strip() or None
                out = _issue_to_dict(i)
                break
        else:
            out = None
    if out:
        audit_event("issue_sla", {"issue_id": issue_id})
        _schedule_persist_active_issues()
    return out


def audit_event(action: str, detail: Optional[dict] = None) -> None:
    now_iso = _now_tr_iso()
    with _audit_lock:
        while len(_audit_events) >= MAX_AUDIT:
            _append_audit_archive(_audit_events.popleft())
        _audit_events.append({
            "ts": now_iso,
            "action": action,
            "detail": detail or {},
        })
    _persist_audit()


def get_audit_events(limit: int = 100) -> list:
    limit = max(1, min(MAX_AUDIT, limit))
    with _audit_lock:
        return list(_audit_events)[-limit:]


def _append_audit_archive(event: dict) -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        record = dict(event)
        record["_backup_at"] = _now_tr_iso()
        with open(_AUDIT_ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        _invalidate_jsonl_count_cache(_AUDIT_ARCHIVE_FILE)
        _trim_jsonl_file(_AUDIT_ARCHIVE_FILE, MAX_AUDIT_ARCHIVE)
    except Exception:
        pass


def _trim_audit_archive_file() -> None:
    _trim_jsonl_file(_AUDIT_ARCHIVE_FILE, MAX_AUDIT_ARCHIVE)


def _count_audit_archive() -> int:
    return _count_jsonl_lines_cached(_AUDIT_ARCHIVE_FILE)


def get_audit_stats() -> dict:
    with _audit_lock:
        active = len(_audit_events)
    return {
        "active": active,
        "backup": _count_audit_archive(),
        "max_active": MAX_AUDIT,
    }


def get_audit_archive(limit: int = 100, q: Optional[str] = None, offset: int = 0, service: Optional[str] = None) -> dict:
    limit = max(1, min(500, limit))
    offset = max(0, offset)
    needle = (q or "").strip().lower()

    def _match(rec: dict) -> bool:
        action = rec.get("action") or ""
        detail = rec.get("detail") or {}
        if service and audit_event_service(action, detail) != service:
            return False
        if needle:
            hay = " ".join([
                str(rec.get("ts") or ""),
                action,
                audit_action_label(action),
                audit_describe(action, detail),
                audit_service_label(audit_event_service(action, detail)),
            ]).lower()
            if needle not in hay:
                return False
        return True

    items, scanned_total = _query_jsonl_archive(_AUDIT_ARCHIVE_FILE, limit, offset, _match)
    return {
        "items": items,
        "total": _count_jsonl_lines_cached(_AUDIT_ARCHIVE_FILE) if not needle and not service else scanned_total,
        "limit": limit,
        "offset": offset,
        "path": str(_AUDIT_ARCHIVE_FILE),
    }


_AUDIT_ACTION_TR = {
    "start": "Servis başlatıldı",
    "stop": "Servis durduruldu",
    "restart": "Servis yeniden başlatıldı",
    "reset": "Metrikler sıfırlandı",
    "lock": "Servis kilidi değiştirildi",
    "alert_ack": "Uyarı onaylandı",
    "export_action": "Dışa aktarma yapıldı",
    "issue_ack": "Olay onaylandı",
    "issue_resolve": "Olay çözüldü",
    "issue_archive": "Olay arşivlendi",
    "issue_reopen": "Olay geri alındı",
    "issue_assign": "Olay atandı",
    "issue_labels": "Olay etiketleri güncellendi",
    "issue_comment": "Olaya yorum eklendi",
    "issue_sla": "Olay SLA notu güncellendi",
}

_AUDIT_CAT_TR = {
    "servis": "Servis",
    "olay": "Olay",
    "uyari": "Uyarı",
    "export": "Dışa aktarma",
    "diger": "Diğer",
}

_SERVICE_TR = {
    "web": "Web",
    "engine": "Motor",
    "manager": "Yönetici",
    "html": "HTML",
    "all": "Tümü",
}

_EXPORT_TYPE_TR = {
    "logs": "Log",
    "issues": "Olay listesi",
    "metrics": "Metrik",
    "audit": "Denetim günlüğü",
    "security": "Güvenlik",
    "alerts": "Uyarı listesi",
    "diagnosis": "Teşhis",
}


def audit_category(action: str) -> str:
    a = action or ""
    if a in ("start", "stop", "restart", "reset", "lock"):
        return "servis"
    if a.startswith("issue_"):
        return "olay"
    if a == "alert_ack":
        return "uyari"
    if a == "export_action":
        return "export"
    return "diger"


def audit_category_label(cat: str) -> str:
    return _AUDIT_CAT_TR.get(cat, cat)


def audit_action_label(action: str) -> str:
    return _AUDIT_ACTION_TR.get(action or "", action or "")


def audit_service_label(key: Optional[str]) -> str:
    if not key:
        return "—"
    return _SERVICE_TR.get(key, key)


def audit_event_service(action: str, detail: Optional[dict]) -> str:
    detail = detail or {}
    if detail.get("service"):
        return str(detail["service"])
    if detail.get("key") and detail.get("key") != "all":
        return str(detail["key"])
    if action == "export_action" and detail.get("service"):
        return str(detail["service"])
    if action == "lock":
        if detail.get("web") and not detail.get("engine"):
            return "web"
        if detail.get("engine") and not detail.get("web"):
            return "engine"
    return ""


def audit_describe(action: str, detail: Optional[dict]) -> str:
    detail = detail or {}
    if action in ("start", "stop", "restart"):
        svc = audit_service_label(detail.get("service"))
        verb = {"start": "başlatıldı", "stop": "durduruldu", "restart": "yeniden başlatıldı"}[action]
        return f"{svc} servisi {verb}"
    if action == "reset":
        if detail.get("key") == "all":
            return "Tüm servislerin sayaç ve metrikleri sıfırlandı"
        return f"{audit_service_label(detail.get('key'))} servis metrikleri sıfırlandı"
    if action == "lock":
        parts = []
        if "web" in detail:
            parts.append("Web: " + ("kilitli" if detail["web"] else "serbest"))
        if "engine" in detail:
            parts.append("Motor: " + ("kilitli" if detail["engine"] else "serbest"))
        return " · ".join(parts) if parts else "Kilit ayarı güncellendi"
    if action == "alert_ack":
        return f"Uyarı {detail.get('alert_id', '—')} onaylandı"
    if action == "export_action":
        label = _EXPORT_TYPE_TR.get(detail.get("type"), detail.get("type") or "Veri")
        fmt = (detail.get("format") or "csv").upper()
        extra = f" · {audit_service_label(detail.get('service'))}" if detail.get("service") else ""
        if detail.get("range"):
            extra += f" · {detail['range']}"
        return f"{label} {fmt} olarak indirildi{extra}"
    if action == "issue_ack":
        return f"Olay {detail.get('issue_id', '—')} onaylandı"
    if action == "issue_resolve":
        return f"Olay {detail.get('issue_id', '—')} çözüldü"
    if action == "issue_archive":
        return f"Olay {detail.get('issue_id', '—')} arşivlendi"
    if action == "issue_reopen":
        return f"Olay {detail.get('issue_id', '—')} geri alındı"
    if action == "issue_assign":
        return f"Olay {detail.get('issue_id', '—')} → {detail.get('assignee') or 'atanmadı'}"
    if action == "issue_labels":
        labels = detail.get("labels") or []
        return f"Olay {detail.get('issue_id', '—')} · etiketler: {', '.join(labels) or '—'}"
    if action == "issue_comment":
        return f"Olay {detail.get('issue_id', '—')} · yorum eklendi"
    if action == "issue_sla":
        return f"Olay {detail.get('issue_id', '—')} · SLA notu güncellendi"
    return json.dumps(detail, ensure_ascii=False)


def _persist_audit() -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        events = list(_audit_events)
        _AUDIT_FILE.write_text(json.dumps(events, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass


def _load_audit() -> None:
    if not _AUDIT_FILE.exists():
        return
    try:
        data = json.loads(_AUDIT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            if len(data) > MAX_AUDIT:
                for e in data[:-MAX_AUDIT]:
                    _append_audit_archive(e)
                data = data[-MAX_AUDIT:]
            with _audit_lock:
                _audit_events.clear()
                for e in data:
                    _audit_events.append(e)
    except Exception:
        pass


def _load_diagnosis() -> None:
    global _diagnosis
    if not _DIAGNOSIS_FILE.exists():
        return
    try:
        with _diagnosis_lock:
            data = json.loads(_DIAGNOSIS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _diagnosis = {k: v for k, v in data.items() if k in ("web", "engine", "manager") and isinstance(v, dict)}
    except Exception:
        pass


def _save_diagnosis() -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _DIAGNOSIS_FILE.with_suffix(".tmp")
        with _diagnosis_lock:
            payload = dict(_diagnosis)
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_DIAGNOSIS_FILE)
    except Exception:
        pass


def _diagnosis_context(key: str) -> tuple:
    """Returns (restart_count_5m, last_audit_was_stop) for service key."""
    now = time.time()
    five_min_ago_iso = _now_tr_iso(now - 300)
    with _audit_lock:
        events = [e for e in _audit_events if (e.get("detail") or {}).get("service") == key]
    restart_count_5m = 0
    last_audit_was_stop = False
    for e in events:
        ts = e.get("ts") or ""
        if ts >= five_min_ago_iso and e.get("action") in ("restart", "start"):
            restart_count_5m += 1
    if events:
        last_audit_was_stop = events[-1].get("action") == "stop"
    return restart_count_5m, last_audit_was_stop


def get_diagnosis(service: Optional[str] = None) -> dict:
    """Returns diagnosis dict(s). If service is None, returns { web: {...}, engine: {...}, manager: {...} }."""
    with _diagnosis_lock:
        if service:
            return _diagnosis.get(service) or {}
        return dict(_diagnosis)


# --- Alerts (toast, no sound) ---
def add_alert(level: str, kind: str, message: str, meta: Optional[dict] = None) -> Optional[str]:
    """level: CRIT | WARN. kind: error_issue | 5xx_spike | tick_age | login_spike | restart_loop. Returns alert id or None if cooldown."""
    cooldown = 30.0 if level == "CRIT" else 15.0
    if kind == "restart_loop":
        cooldown = 300.0
    now = time.time()
    with _alerts_lock:
        last = _alert_cooldown.get(kind, 0)
        if now - last < cooldown:
            return None
        _alert_cooldown[kind] = now
        _ALERT_ID_COUNTER[0] += 1
        aid = "ALT-%06d" % _ALERT_ID_COUNTER[0]
        _alerts.append({
            "id": aid,
            "ts": _now_tr_iso(),
            "level": level,
            "kind": kind,
            "message": (message or "")[:500],
            "meta": meta or {},
            "acked": False,
        })
        return aid
    return None


def get_alerts(acked: Optional[bool] = None) -> list:
    with _alerts_lock:
        out = list(_alerts)
    if acked is not None:
        out = [a for a in out if a.get("acked") == acked]
    return out[-MAX_ALERTS:]


def alert_ack(alert_id: str) -> Optional[dict]:
    with _alerts_lock:
        for a in _alerts:
            if a.get("id") == alert_id:
                a["acked"] = True
                return dict(a)
    return None


def pop_alert_events() -> list:
    """Return new unacked alerts since last call (for WS). Caller may pass last_seen id."""
    with _alerts_lock:
        return [dict(a) for a in _alerts if not a.get("acked")][-30:]


def _should_skip_html_stats_duplicate(key: str, line: str) -> bool:
    """HTML logunda ardışık aynı Günlük|Aylık|Toplam satırını atla."""
    if not _HTML_STATS_RE.search(line):
        return False
    ring = logs_ring.get(key)
    if not ring or len(ring) == 0:
        return False
    return ring[-1] == line


def _tail_loop(key: str) -> None:
    log_path = _log_path(key)
    stop = _tail_stop.get(key)
    while not log_path.exists() and stop and not stop.is_set():
        time.sleep(0.5)
    if not log_path.exists():
        return
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in _read_file_tail_lines(log_path, RING_LINES):
                line = _truncate_line(line)
                if key == "web" and _is_web_access_200_line(line):
                    continue
                if key == "html" and _should_skip_html_stats_duplicate(key, line):
                    continue
                logs_ring[key].append(line)
                level = classify_line(line)
                if level == "ERROR":
                    if not _is_noise_line(line, "ERROR"):
                        errors_ring[key].append(line)
                        _ingest_issue(key, line, "ERROR")
                elif level == "WARN":
                    if not _is_noise_line(line, "WARN") and not _backfill_should_skip_401_warn(key, line):
                        warns_ring[key].append(line)
                        _ingest_issue(key, line, "WARN")
            f.seek(0, 2)
            while stop and not stop.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                line = _truncate_line(line.rstrip("\n\r"))
                if key == "web" and _is_web_access_200_line(line):
                    continue
                if key == "html" and _should_skip_html_stats_duplicate(key, line):
                    continue
                logs_ring[key].append(line)
                level = classify_line(line)
                if level == "ERROR":
                    if not _is_noise_line(line, "ERROR"):
                        errors_ring[key].append(line)
                        _ingest_issue(key, line, "ERROR")
                elif level == "WARN":
                    if not _is_noise_line(line, "WARN") and not _should_throttle_401_warn(key, line):
                        warns_ring[key].append(line)
                        _ingest_issue(key, line, "WARN")
                ts = _now_tr_time()
                with _batch_lock:
                    batch = _ws_batch[key]
                    batch.append({"ts": ts, "level": level, "text": line})
                    if len(batch) > WS_BATCH_MAX * 3:
                        del batch[:-WS_BATCH_MAX]
    except Exception:
        pass


def start_tail_threads() -> None:
    for key in ("web", "engine", "manager", "html"):
        _tail_stop[key] = threading.Event()
        t = threading.Thread(target=_tail_loop, args=(key,), daemon=True)
        t.start()
        _tail_threads[key] = t


def get_status() -> dict:
    locks = load_locks()
    out = {}
    for key in ("web", "engine"):
        pid = _read_pid(_pid_path(key))
        alive = _process_alive(pid)
        # Web: PID guncel olmasa bile port aciksa calisiyor say (hata sonrasi yeniden baslatilinca durdu yazilmasin)
        if key == "web" and not alive and _is_port_in_use(_WEB_PORT):
            alive = True
        status[key]["running"] = alive
        status[key]["pid"] = pid
        status[key]["locked"] = locks.get(key, False)
        # Servis çalışıyorsa eski START_FAILED/CRASH_LOOP teşhisini temizle
        if alive:
            with _diagnosis_lock:
                cur = _diagnosis.get(key) or {}
            if cur.get("state") not in (None, "RUNNING"):
                _produce_and_store_diagnosis(key, "RUNNING")
        out[key] = {
            "running": alive,
            "pid": pid,
            "locked": locks.get(key, False),
            "started_at": status[key].get("started_at"),
            "restart_count": status[key].get("restart_count", 0),
        }
    # Manager: always running (we are it)
    manager_pid = _read_pid(_MANAGER_PID_FILE) if _MANAGER_PID_FILE.exists() else os.getpid()
    out["manager"] = {
        "running": True,
        "pid": manager_pid,
        "locked": False,
        "started_at": status["manager"].get("started_at"),
        "restart_count": status["manager"].get("restart_count", 0),
    }
    # HTML (omeraltinhtml): calistir.bat / stop.bat ile; çalışıyor = port açık
    html_running = _is_port_in_use(_HTML_PORT)
    html_pid = _pid_on_port(_HTML_PORT) if html_running else None
    status["html"]["running"] = html_running
    status["html"]["pid"] = html_pid
    if (_RUN_DIR / "html.started_at").exists():
        try:
            status["html"]["started_at"] = float((_RUN_DIR / "html.started_at").read_text().strip())
        except Exception:
            pass
    out["html"] = {
        "running": html_running,
        "pid": html_pid,
        "locked": False,
        "started_at": status["html"].get("started_at"),
        "restart_count": status["html"].get("restart_count", 0),
    }
    return out


def _produce_and_store_diagnosis(key: str, state: str, exit_code: Optional[int] = None, signal: Optional[str] = None) -> None:
    from manager_server.reason_engine import diagnose as reason_diagnose
    restart_count_5m, last_audit_was_stop = _diagnosis_context(key)
    port = 8000 if key == "web" else (7999 if key == "manager" else None)
    log_data = get_logs(key, 200)
    last_lines = log_data.get("lines") or []
    d = reason_diagnose(
        service=key,
        state=state,
        last_lines=last_lines,
        exit_code=exit_code,
        signal=signal,
        port=port,
        restart_count_5m=restart_count_5m,
        last_audit_was_stop=last_audit_was_stop,
        pid=status.get(key, {}).get("pid"),
    )
    with _diagnosis_lock:
        _diagnosis[key] = d
    status[key]["last_exit_code"] = exit_code
    status[key]["last_signal"] = signal
    status[key]["last_start_attempt_ts"] = _now_tr_iso()
    _save_diagnosis()
    if d.get("state") != "RUNNING":
        logging.getLogger().info(
            "DIAGNOSIS service=%s state=%s reason=%s title=%s summary=%s",
            key, d.get("state"), d.get("reason_code"), d.get("title_tr", ""), (d.get("summary_tr") or "")[:200],
        )


def _is_port_in_use(port: int) -> bool:
    """True if 127.0.0.1:port accepts a connection (server is up)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
        return True
    except (OSError, socket.error):
        return False


def _pid_on_port(port: int) -> Optional[int]:
    """Return PID listening on port, or None."""
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in (r.stdout or "").splitlines():
                if "LISTENING" not in line or ":%s" % port not in line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[-1])
                    if pid > 0:
                        return pid
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["lsof", "-ti", ":%s" % port],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in (r.stdout or "").strip().split():
                try:
                    pid = int(pid_str)
                    if pid > 0:
                        return pid
                except ValueError:
                    pass
        except Exception:
            pass
    return None


def _kill_port(port: int) -> None:
    """Portu dinleyen süreci durdur (omeraltinhtml stop için)."""
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in (r.stdout or "").splitlines():
                if "LISTENING" not in line or ":%s" % port not in line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[-1])
                    if pid > 0:
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/F"],
                            capture_output=True,
                            timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        time.sleep(0.5)
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["lsof", "-ti", ":%s" % port],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in (r.stdout or "").strip().split():
                try:
                    subprocess.run(["kill", "-9", pid_str], capture_output=True, timeout=3)
                    time.sleep(0.3)
                except (ValueError, OSError):
                    pass
        except Exception:
            pass


def _html_start_script() -> Optional[Path]:
    """calistir.bat (Win) veya calistir.command / calistir.sh (Unix)."""
    if _IS_WINDOWS:
        p = _OMERALTINHTML_PATH / "calistir.bat"
        return p if p.is_file() else None
    for name in ("calistir.command", "calistir.sh", "calistir"):
        p = _OMERALTINHTML_PATH / name
        if p.is_file():
            return p
    return None


def _html_stop_script() -> Optional[Path]:
    """stop.bat (Win) veya stop.command / stop.sh (Unix)."""
    if _IS_WINDOWS:
        p = _OMERALTINHTML_PATH / "stop.bat"
        return p if p.is_file() else None
    for name in ("stop.command", "stop.sh", "stop"):
        p = _OMERALTINHTML_PATH / name
        if p.is_file():
            return p
    return None


def _do_start_html() -> bool:
    """omeraltinhtml içindeki calistir.bat / start.py (Unix) / calistir.command ile başlat. Port 8080."""
    if not _OMERALTINHTML_PATH.is_dir():
        logging.getLogger().warning("HTML server: path not a directory: %s", _OMERALTINHTML_PATH)
        return False
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        if _IS_WINDOWS:
            start_script = _html_start_script()
            if not start_script:
                logging.getLogger().warning("HTML server: calistir.bat not found in %s", _OMERALTINHTML_PATH)
                return False
            subprocess.Popen(
                ["cmd", "/c", str(start_script)],
                cwd=str(_OMERALTINHTML_PATH),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            # Unix: start.py (port 8080) tercih; calistir.command 8000 kullanır, ana uygulama ile çakışır
            start_py = _OMERALTINHTML_PATH / "start.py"
            if start_py.is_file():
                logf = None
                if _HTML_LOG:
                    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
                    logf = open(_HTML_LOG, "a", encoding="utf-8", errors="replace")
                subprocess.Popen(
                    [sys.executable, "-u", str(start_py)],
                    cwd=str(_OMERALTINHTML_PATH),
                    stdout=logf or subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
            else:
                start_script = _html_start_script()
                if not start_script:
                    logging.getLogger().warning("HTML server: start.py / calistir.command not found in %s", _OMERALTINHTML_PATH)
                    return False
                subprocess.Popen(
                    ["/bin/sh", str(start_script)],
                    cwd=str(_OMERALTINHTML_PATH),
                )
        (_RUN_DIR / "html.started_at").write_text(str(time.time()), encoding="utf-8")
        status["html"]["started_at"] = time.time()
        audit_event("start", {"service": "html"})
        return True
    except Exception as e:
        logging.getLogger().warning("HTML server start failed: %s", e)
        return False


def _do_stop_html() -> bool:
    """omeraltinhtml içindeki stop.bat / stop.command ile durdur; port 8080'i de kapat. Returns True."""
    stop_script = _html_stop_script()
    if stop_script and stop_script.is_file():
        try:
            # Popen kullan - bekleme yok, timeout riski yok; _kill_port zaten portu kapatır
            if _IS_WINDOWS:
                subprocess.Popen(
                    ["cmd", "/c", str(stop_script)],
                    cwd=str(_OMERALTINHTML_PATH),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["/bin/sh", str(stop_script)],
                    cwd=str(_OMERALTINHTML_PATH),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            time.sleep(1)
        except Exception as e:
            logging.getLogger().warning("HTML server stop script failed: %s", e)
    _kill_port(_HTML_PORT)
    try:
        (_RUN_DIR / "html.started_at").unlink(missing_ok=True)
    except Exception:
        pass
    status["html"]["running"] = False
    status["html"]["pid"] = None
    audit_event("stop", {"service": "html"})
    return True


def do_start(key: str) -> bool:
    if key == "html":
        return _do_start_html()
    if key not in ("web", "engine"):
        return False
    helper_action = "web-start" if key == "web" else "worker-start"
    returncode = -1
    try:
        r = subprocess.run(
            _helper_cmd(helper_action),
            cwd=str(_PROJECT_ROOT),
            timeout=30,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if _IS_WINDOWS else 0,
        )
        returncode = r.returncode if r is not None else -1
    except Exception:
        pass
    time.sleep(1)
    get_status()
    audit_event("start", {"service": key})
    if not status[key]["running"]:
        _produce_and_store_diagnosis(key, "START_FAILED", exit_code=returncode)
    return status[key]["running"]


def do_stop(key: str) -> bool:
    if key == "html":
        return _do_stop_html()
    if key not in ("web", "engine"):
        return False
    helper_action = "web-stop" if key == "web" else "worker-stop"
    try:
        subprocess.run(
            _helper_cmd(helper_action),
            cwd=str(_PROJECT_ROOT),
            timeout=15,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if _IS_WINDOWS else 0,
        )
    except Exception:
        pass
    time.sleep(0.5)
    get_status()
    audit_event("stop", {"service": key})
    _produce_and_store_diagnosis(key, "STOPPED")
    return not status[key]["running"]


def do_restart(key: str) -> bool:
    if key == "html":
        _do_stop_html()
        time.sleep(1)
        return _do_start_html()
    if key not in ("web", "engine"):
        return False
    status[key]["restart_count"] = status[key].get("restart_count", 0) + 1
    helper_action = "web-restart" if key == "web" else "worker-restart"
    returncode = -1
    try:
        r = subprocess.run(
            _helper_cmd(helper_action),
            cwd=str(_PROJECT_ROOT),
            timeout=45,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if _IS_WINDOWS else 0,
        )
        returncode = r.returncode if r is not None else -1
    except Exception:
        pass
    time.sleep(1)
    get_status()
    audit_event("restart", {"service": key})
    if not status[key]["running"]:
        restart_count_5m, _ = _diagnosis_context(key)
        state = "CRASH_LOOP" if restart_count_5m >= 3 else "START_FAILED"
        _produce_and_store_diagnosis(key, state, exit_code=returncode)
    return status[key]["running"]


def global_start() -> tuple[list, list]:
    locks = load_locks()
    applied, skipped = [], []
    for key in ("web", "engine"):
        if locks.get(key):
            skipped.append(key)
            continue
        if not status[key]["running"]:
            do_start(key)
            applied.append(key)
    if not status.get("html", {}).get("running"):
        do_start("html")
        applied.append("html")
    return applied, skipped


def global_stop() -> tuple[list, list]:
    locks = load_locks()
    applied, skipped = [], []
    for key in ("web", "engine"):
        if locks.get(key):
            skipped.append(key)
            continue
        if status[key]["running"]:
            do_stop(key)
            applied.append(key)
    if status.get("html", {}).get("running"):
        do_stop("html")
        applied.append("html")
    return applied, skipped


def global_restart() -> tuple[list, list]:
    locks = load_locks()
    applied, skipped = [], []
    for key in ("web", "engine"):
        if locks.get(key):
            skipped.append(key)
            continue
        do_restart(key)
        applied.append(key)
    do_restart("html")
    applied.append("html")
    return applied, skipped


def reset_logs(key: str) -> None:
    audit_event("reset", {"key": key})
    if key == "all":
        for k in ("web", "engine", "manager", "html"):
            if k in logs_ring:
                logs_ring[k].clear()
                errors_ring[k].clear()
                warns_ring[k].clear()
                with _batch_lock:
                    _ws_batch[k].clear()
    elif key in ("web", "engine", "manager", "html") and key in logs_ring:
        logs_ring[key].clear()
        errors_ring[key].clear()
        warns_ring[key].clear()
        with _batch_lock:
            _ws_batch[key].clear()


def get_logs(key: str, tail: int = 300) -> dict:
    if key not in ("web", "engine", "manager", "html"):
        return {"lines": [], "errors": [], "warns": []}
    tail = max(1, min(RING_LINES, tail))
    ring = logs_ring[key]
    if key == "web":
        lines = [l for l in ring if not _is_web_access_200_line(l)]
    else:
        lines = list(ring)
    return {
        "lines": lines[-tail:] if len(lines) > tail else lines,
        "errors": list(errors_ring[key]),
        "warns": list(warns_ring[key]),
    }


def pop_ws_batch(key: str, max_lines: int = WS_BATCH_MAX) -> list:
    max_lines = max(1, min(WS_BATCH_MAX, max_lines))
    with _batch_lock:
        buf = _ws_batch.get(key, [])
        out = buf[-max_lines:] if len(buf) > max_lines else buf
        _ws_batch[key] = []
        return out


_html_watchdog_interval = 60  # seconds
_html_watchdog_thread: Optional[threading.Thread] = None
_html_watchdog_stop = threading.Event()


def _html_watchdog_loop() -> None:
    """Her N saniyede bir: html.started_at var ama port kapalıysa (süreç çöktüyse) yeniden başlat."""
    log = logging.getLogger()
    while not _html_watchdog_stop.wait(timeout=_html_watchdog_interval):
        try:
            started_at_file = _RUN_DIR / "html.started_at"
            if not started_at_file.exists():
                continue
            if not _OMERALTINHTML_PATH.is_dir():
                continue
            try:
                started_at = float(started_at_file.read_text().strip())
            except Exception:
                continue
            if time.time() - started_at < 15:
                continue
            if _is_port_in_use(_HTML_PORT):
                continue
            log.info("HTML (omeraltin.com) port %s kapali, yeniden baslatiliyor.", _HTML_PORT)
            do_start("html")
        except Exception as e:
            log.warning("HTML watchdog error: %s", e)


def start_html_watchdog() -> None:
    """omeraltin.com süreci çökerse otomatik yeniden başlatmak için arka plan thread."""
    global _html_watchdog_thread
    if _html_watchdog_thread is not None and _html_watchdog_thread.is_alive():
        return
    _html_watchdog_stop.clear()
    _html_watchdog_thread = threading.Thread(target=_html_watchdog_loop, daemon=True)
    _html_watchdog_thread.start()
    logging.getLogger().info("HTML watchdog started (interval=%ss).", _html_watchdog_interval)


def auto_start_if_needed() -> None:
    """On manager startup: start web, engine and html (omeraltin.com) if not locked and not running."""
    locks = load_locks()
    get_status()
    for key in ("web", "engine"):
        if locks.get(key):
            continue
        if not status[key]["running"]:
            do_start(key)
    if not status.get("html", {}).get("running"):
        do_start("html")
