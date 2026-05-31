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
_BLOCKED_IPS_FILE = _RUN_DIR / "blocked_ips.json"
_HELPER = _PROJECT_ROOT / "scripts" / "runtime" / "local_web_worker_helper.py"
_MANAGER_REBOOT = _PROJECT_ROOT / "scripts" / "runtime" / "manager_reboot.py"
_WEB_METRICS_FILE = _RUN_DIR / "web.metrics.json"
_ENGINE_METRICS_FILE = _RUN_DIR / "engine.metrics.json"
_MANAGER_PID_FILE = _RUN_DIR / "manager.pid"
_MANAGER_STARTED_FILE = _RUN_DIR / "manager.started_at"
_SESSION_STARTED_FILE = _RUN_DIR / "session.started_at"

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

# Issues persist debounce (legacy; dosya deposu anında yazar)
ISSUE_PERSIST_DELAY_SEC = 20.0

# Metrics list caps (no unbounded growth)
_METRICS_TOP_PATHS = 30
_METRICS_TOP_IPS = 30
_METRICS_LOGIN_FAILS = 30

# Parsing — önce standart Python log seviyesi (" - INFO - "); error= alanı ERROR sayılmaz
_PY_LOG_LEVEL_RE = re.compile(r"\s-\s(WARNING|ERROR|CRITICAL|INFO|DEBUG)\s-", re.I)
_BRACKET_LEVEL_RE = re.compile(r"\]\s*(WARNING|ERROR|CRITICAL|INFO|DEBUG)\s+", re.I)
_ERROR_FALLBACK_RE = re.compile(r"Traceback \(most recent call last\)|\b(ERROR|CRITICAL)\s", re.I)
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
# Emilen tick/loop hataları — engine log + resilience; wrn-engine gürültüsü
_ABSORBED_ENGINE_WARN_RE = re.compile(
    r"BOT_LOOP_TRDCA_EXCEPTION|"
    r"BOT_LOOP_TOPLEVEL_EXCEPTION|"
    r"BOT_TICK_EXCEPTION|"
    r"RUN_ACTION_EXCEPTION error_code=RUN_ACTION_EXCEPTION|"
    r"BOT_TICK bot_id=\d+ lease_not_valid.*skip submit|"
    r"BOT_TICK_PRICE_MISSING.*skip_trade=True|"
    r"BOT_START_SKIPPED_ALREADY_RUNNING|"
    r"BOT_ACCOUNT_KEYS_FAIL|"
    r"WORKER_FIRST_TICK_FAILED|"
    r"bot_run get_account_keys|"
    r"bot_engine release_symbol_lock|"
    r"bot_engine sync_virtual_wallet_from_state failed",
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
    need = max(0, offset) + max(0, limit)
    matched: list = []
    extra = 0
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not match_fn(rec):
            continue
        if len(matched) < need:
            matched.append(rec)
        else:
            extra += 1
    total = len(matched) + extra
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
_rings_lock = threading.Lock()  # logs_ring / errors_ring / warns_ring (tail thread vs WS/API)
_tail_threads: dict = {}
_tail_stop: dict = {}  # key -> event to stop thread

# Metrics: single object, updated every 2s (no ring, bounded lists only)
metrics_cache: dict = {}
_metrics_lock = threading.Lock()
_metrics_thread: Optional[threading.Thread] = None
_metrics_stop = threading.Event()

# Issues — dosya tabanlı depo (manager_server/issue_file_store.py); RAM havuzu yok
MAX_ISSUES = 300
MAX_ISSUE_SAMPLES = 3
ISSUE_COMMENT_MAX = 15
ISSUE_STATUS_HIST_MAX = 15
MAX_ISSUES_ARCHIVE = 10000

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

# Saatlik tick: son 60 dakikadaki olay sayısı (servis bazlı, manager metrics döngüsünde güncellenir)
_TICK_WINDOW_SEC = 3600
_service_tick_ts: dict[str, deque] = {
    "manager": deque(),
    "web": deque(),
    "html": deque(),
}
_last_web_request_total: Optional[int] = None
_last_web_metrics_pid: Optional[int] = None


def _prune_tick_deque(dq: deque, now: float) -> None:
    cutoff = now - _TICK_WINDOW_SEC
    while dq and dq[0] < cutoff:
        dq.popleft()


def _record_service_ticks(service: str, count: int, now: Optional[float] = None) -> None:
    if count <= 0 or service not in _service_tick_ts:
        return
    ts = now if now is not None else time.time()
    dq = _service_tick_ts[service]
    for _ in range(min(count, 5000)):
        dq.append(ts)
    _prune_tick_deque(dq, ts)


def _ticks_last_60m(service: str, min_ts: Optional[float] = None) -> int:
    if service not in _service_tick_ts:
        return 0
    now = time.time()
    dq = _service_tick_ts[service]
    cutoff = now - _TICK_WINDOW_SEC
    if min_ts is not None and min_ts > cutoff:
        cutoff = min_ts
    while dq and dq[0] < cutoff:
        dq.popleft()
    return len(dq)


def _update_hourly_ticks(
    manager_proc: dict,
    web_proc: dict,
    engine_proc: dict,
    html_proc: dict,
    web_app: dict,
    engine_app: dict,
    html_running: bool,
    web_started_at: Optional[float] = None,
) -> None:
    """Son 60 dk tick sayacını servis proc dict'lerine yazar."""
    global _last_web_request_total, _last_web_metrics_pid
    now = time.time()
    if manager_proc.get("pid"):
        _record_service_ticks("manager", 1, now)
    manager_proc["ticks_last_60m"] = _ticks_last_60m("manager")

    web_pid = web_proc.get("pid")
    if web_pid != _last_web_metrics_pid:
        _last_web_metrics_pid = web_pid
        _last_web_request_total = None
        _service_tick_ts["web"].clear()
    total = int(web_app.get("request_total") or 0)
    if web_pid:
        if _last_web_request_total is None:
            _last_web_request_total = total
        elif total >= _last_web_request_total:
            _record_service_ticks("web", total - _last_web_request_total, now)
            _last_web_request_total = total
        else:
            _last_web_request_total = total
    web_min_ts = web_started_at if web_pid else None
    web_proc["ticks_last_60m"] = _ticks_last_60m("web", web_min_ts)
    if web_pid and web_app.get("requests_per_min") is not None:
        try:
            web_proc["requests_per_min"] = float(web_app["requests_per_min"])
        except (TypeError, ValueError):
            pass

    eng_ticks = engine_app.get("ticks_last_60m")
    if eng_ticks is not None and engine_proc.get("pid"):
        try:
            engine_proc["ticks_last_60m"] = int(eng_ticks)
        except (TypeError, ValueError):
            engine_proc["ticks_last_60m"] = 0
    else:
        engine_proc["ticks_last_60m"] = 0

    if html_running and html_proc.get("pid"):
        _record_service_ticks("html", 1, now)
    html_proc["ticks_last_60m"] = _ticks_last_60m("html")


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


def _reset_session_chrono() -> float:
    """Sistem çalışması kronometresi — yalnızca manager süreci yeniden başlayınca sıfırlanır."""
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        _SESSION_STARTED_FILE.write_text(str(now), encoding="utf-8")
    except Exception:
        pass
    return now


def _init_session_chrono_on_manager_start() -> None:
    """Manager boot: aynı PID ile tekrar init olmadıkça mevcut session.started_at korunur."""
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    current_pid = os.getpid()
    keep_existing = False
    if _MANAGER_PID_FILE.is_file() and _SESSION_STARTED_FILE.is_file():
        try:
            if int(_MANAGER_PID_FILE.read_text(encoding="utf-8").strip()) == current_pid:
                keep_existing = True
        except Exception:
            keep_existing = False
    if not keep_existing:
        _reset_session_chrono()


def _session_uptime_s() -> int:
    """session.started_at dosyasından geçen süre (saniye)."""
    if not _SESSION_STARTED_FILE.is_file():
        return 0
    try:
        started = float(_SESSION_STARTED_FILE.read_text(encoding="utf-8").strip())
        return max(0, int(time.time() - started))
    except Exception:
        return 0


def _session_started_ts() -> Optional[float]:
    if not _SESSION_STARTED_FILE.is_file():
        return None
    try:
        return float(_SESSION_STARTED_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _system_uptime_s() -> Optional[int]:
    """OS boot'tan bu yana saniye; psutil + platform yedekleri."""
    if psutil:
        try:
            boot = psutil.boot_time()
            if boot:
                return max(0, int(time.time() - boot))
        except Exception:
            pass
    if not _IS_WINDOWS:
        if sys.platform == "darwin":
            try:
                r = subprocess.run(
                    ["sysctl", "-n", "kern.boottime"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                m = re.search(r"sec\s*=\s*(\d+)", r.stdout or "")
                if m:
                    return max(0, int(time.time() - int(m.group(1))))
            except Exception:
                pass
        else:
            try:
                with open("/proc/uptime", encoding="utf-8") as f:
                    parts = (f.read() or "").split()
                    if parts:
                        return max(0, int(float(parts[0])))
            except Exception:
                pass
    return None


def _collect_metrics() -> None:
    """Update metrics_cache once: system + manager/web/engine + app JSON files. All lists capped."""
    global metrics_cache
    system = {"cpu_pct": None, "ram_used_mb": None, "ram_total_mb": None, "disk_used_mb": None, "disk_total_mb": None, "net_bytes_sent": None, "net_bytes_recv": None, "load_avg": None, "cpu_count": None, "uptime_s": None}
    try:
        system["cpu_count"] = os.cpu_count() or 1
    except Exception:
        system["cpu_count"] = 1
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
    system["uptime_s"] = _session_uptime_s()
    system["session_started_at"] = _session_started_ts()
    os_uptime = _system_uptime_s()
    if os_uptime is not None:
        system["os_uptime_s"] = os_uptime
    manager_pid = _read_pid(_MANAGER_PID_FILE) if _MANAGER_PID_FILE.exists() else os.getpid()
    manager_started = None
    if _MANAGER_STARTED_FILE.exists():
        try:
            manager_started = float(_MANAGER_STARTED_FILE.read_text(encoding="utf-8").strip())
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
    _update_hourly_ticks(
        manager_proc, web_proc, engine_proc, html_proc, web_app, engine_app, html_running, web_started
    )
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
    sys_obj = out.setdefault("system", {})
    sys_obj["uptime_s"] = _session_uptime_s()
    sys_obj["session_started_at"] = _session_started_ts()
    os_uptime = _system_uptime_s()
    if os_uptime is not None:
        sys_obj["os_uptime_s"] = os_uptime
    if sys_obj.get("cpu_count") is None:
        try:
            sys_obj["cpu_count"] = os.cpu_count() or 1
        except Exception:
            sys_obj["cpu_count"] = 1
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
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    _init_session_chrono_on_manager_start()
    try:
        _MANAGER_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        _MANAGER_STARTED_FILE.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass
    _load_audit()
    from manager_server import issue_file_store

    issue_file_store.init_store()
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
    if _MANAGER_STARTED_FILE.exists():
        try:
            manager_started = float(_MANAGER_STARTED_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    if manager_started is None:
        manager_started = _session_started_ts()
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
    try:
        _produce_and_store_diagnosis("manager", "RUNNING")
        if status["html"]["running"]:
            _produce_and_store_diagnosis("html", "RUNNING")
    except Exception:
        pass


def classify_line(line: str) -> str:
    """Log seviyesi: Python ' - LEVEL - ' alanı; error= parametresi ERROR değildir."""
    m = _PY_LOG_LEVEL_RE.search(line) or _BRACKET_LEVEL_RE.search(line)
    if m:
        lvl = m.group(1).upper()
        if lvl == "WARNING":
            return "WARN"
        if lvl in ("ERROR", "CRITICAL"):
            return "ERROR"
        return "INFO"
    if _ERROR_FALLBACK_RE.search(line):
        return "ERROR"
    if _WARN_RE.search(line):
        return "WARN"
    return "INFO"


def _is_web_access_200_line(line: str) -> bool:
    """True if line is a web access log with status 200 that should be hidden (not SLOW_REQUEST)."""
    if not line or "SLOW_REQUEST" in line:
        return False
    return bool(_ACCESS_200_RE.search(line))


def _is_auth_validate_ok_line(line: str) -> bool:
    """Başarılı oturum doğrulama INFO gürültüsü (dosyada DEBUG; eski/geçmiş satırlar için)."""
    return "AUTH_VALIDATE" in line and " outcome=OK " in line


def _is_noise_line(line: str, level: str) -> bool:
    """True if line should not be added to errors_ring/warns_ring (gürültü)."""
    s = line.strip()
    if not s:
        return True
    if level == "ERROR":
        # Eski manager sürümü: log ring okuma/yazma yarışı (güncel sürümde kilitli; panel gürültüsü)
        if "deque mutated during iteration" in s:
            return True
        # WebSocket normal kapanma (1000/1001) — istemci sayfadan ayrıldığında beklenen davranış
        if "ConnectionClosedOK" in s or "1001 (going away)" in s or "received 1001" in s:
            return True
        # Sadece "Traceback (most recent call last):" başlığı, stack yok
        if s == "Traceback (most recent call last):" or s.startswith("Traceback (most recent call last):") and len(s) < 80:
            return True
        # Tam yeniden başlat: eski Manager kapanmadan yeni süreç 7999'a bind dener (geçici)
        if ("EADDRINUSE" in s or "Address already in use" in s or "error while attempting to bind" in s) and (
            "7999" in s or "127.0.0.1', 7999" in s
        ):
            return True
    if level == "WARN":
        # Finans senkron: sembol önbelleği boşken yedek liste — beklenen, işlem devam eder
        if "[TradeSync] Symbol cache empty" in s:
            return True
        # Kesik veya anlamsız: sadece "warnings.warn(" gibi
        if re.match(r"^\s*warnings\.warn\s*\(\s*$", s) or (s.startswith("warnings.warn(") and len(s) < 30):
            return True
        # SLOW_REQUEST: yavaş istek uyarıları panelde listelenmesin (log dosyasında kalsın)
        if "SLOW_REQUEST" in s:
            return True
        # Manager kendi /api/issues/summary 404 probe satırları — panel gürültüsü
        if "/api/issues/summary" in s and "404" in s:
            return True
        # Eski Manager sürümü: güvenlik IP engel API'si yokken UI probe
        if "/api/security/" in s and "404" in s:
            return True
        # Eski rota: /api/server/manager/restart {key} çakışması → 400
        if "/api/server/manager/restart" in s and " 400" in s:
            return True
        if "/api/stack/restart" in s and (" 400" in s or " 404" in s):
            return True
        if "/api/server/manager/restart" in s and " 404" in s:
            return True
        # Toplu start/stop/restart: önceki işlem sürerken çift tıklama — beklenen, panel gürültüsü
        if "/api/global/" in s and " 409" in s:
            return True
        # Cüzdan yenileme import (düzeltildi / geçmiş spam)
        if "wallet_refresh_attempt error_code=ImportError" in s:
            return True
        if "wallet_refresh_attempt error_code=WALLET_MODULE_MISSING" in s:
            return True
        if "get_price_map_flat" in s and "wallet_refresh" in s:
            return True
        # Bot engine: emilen tick hataları (engine log + resilience; bot running kalır)
        if _ABSORBED_ENGINE_WARN_RE.search(s):
            return True
    if level == "ERROR":
        # INFO yanlış sınıflandırma düzeltmesi öncesi: home_wallet_refresh error=...
        if "home_wallet_refresh" in s and " error=" in s and " - INFO - " in s:
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
            with _rings_lock:
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


def _push_status_history(issue: dict, new_status: str) -> None:
    hist = issue.get("status_history")
    if not isinstance(hist, deque):
        issue["status_history"] = deque(maxlen=ISSUE_STATUS_HIST_MAX)
        hist = issue["status_history"]
    hist.append({"ts": _now_tr_iso(), "status": new_status})


def _ingest_issue(key: str, line: str, level: str) -> None:
    """Register or update an issue from a log line (dosya deposu)."""
    from manager_server import issue_file_store

    def _on_new(iid: str, svc: str, msg: str) -> None:
        add_alert("CRIT", "error_issue", _truncate_line(msg, 200), {"issue_id": iid, "service": svc})

    issue_file_store.ingest_issue(key, line, level, on_new_error=_on_new)


def get_issue_stats() -> dict:
    from manager_server import issue_file_store

    return issue_file_store.get_issue_stats()


def get_issues(
    service: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    q: Optional[str] = None,
) -> list:
    from manager_server import issue_file_store

    return issue_file_store.get_issues(service=service, status_filter=status_filter, limit=limit, q=q)


def get_issues_archive(limit: int = 100, q: Optional[str] = None, offset: int = 0, service: Optional[str] = None) -> dict:
    from manager_server import issue_file_store

    return issue_file_store.get_issues_archive(limit=limit, offset=offset, q=q, service=service)


def get_issue_by_id(issue_id: str) -> Optional[dict]:
    from manager_server import issue_file_store

    return issue_file_store.get_issue_by_id(issue_id)


def issue_ack(issue_id: str) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_ack(issue_id)
    if out:
        audit_event("issue_ack", {"issue_id": issue_id})
    return out


def issue_resolve(issue_id: str) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_resolve(issue_id)
    if out:
        audit_event("issue_resolve", {"issue_id": issue_id})
    return out


def issue_archive(issue_id: str) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_archive(issue_id)
    if out:
        audit_event("issue_archive", {"issue_id": issue_id})
    return out


def issue_reopen(issue_id: str) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_reopen(issue_id)
    if out:
        audit_event("issue_reopen", {"issue_id": issue_id})
    return out


def issue_assign(issue_id: str, assignee: Optional[str]) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_assign(issue_id, assignee)
    if out:
        audit_event("issue_assign", {"issue_id": issue_id, "assignee": assignee})
    return out


def issue_labels(issue_id: str, labels: list) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_labels(issue_id, labels)
    if out:
        audit_event("issue_labels", {"issue_id": issue_id, "labels": labels})
    return out


def issue_comment(issue_id: str, text: str, author: str = "local") -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_comment(issue_id, text, author=author)
    if out and (text or "").strip():
        audit_event("issue_comment", {"issue_id": issue_id})
    return out


def issue_sla(issue_id: str, sla_note: Optional[str]) -> Optional[dict]:
    from manager_server import issue_file_store

    out = issue_file_store.issue_sla(issue_id, sla_note)
    if out:
        audit_event("issue_sla", {"issue_id": issue_id})
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
                _diagnosis = {k: v for k, v in data.items() if k in ("web", "engine", "manager", "html") and isinstance(v, dict)}
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


def _ensure_diagnosis_current() -> None:
    """Store'da eksik veya güncel olmayan manager/html teşhislerini tamamla."""
    with _diagnosis_lock:
        mgr = _diagnosis.get("manager") or {}
    if mgr.get("reason_code") != "RUNNING":
        _produce_and_store_diagnosis("manager", "RUNNING")

    html_up = _is_port_in_use(_HTML_PORT)
    html_pid = _pid_on_port(_HTML_PORT) if html_up else None
    if "html" in status:
        status["html"]["running"] = html_up
        status["html"]["pid"] = html_pid
    with _diagnosis_lock:
        html_d = _diagnosis.get("html") or {}
    if html_up:
        if html_d.get("reason_code") != "RUNNING":
            _produce_and_store_diagnosis("html", "RUNNING")
    elif html_d.get("reason_code") == "RUNNING":
        _produce_and_store_diagnosis("html", "STOPPED")


def _patch_running_diagnosis_pids(live: Optional[dict] = None) -> None:
    """RUNNING teşhisinde evidence.pid/port değerlerini güncel status ile hizala."""
    ports = {"web": 8000, "manager": 7999, "html": 8080}
    changed_any = False
    with _diagnosis_lock:
        for key in ("web", "engine", "manager", "html"):
            d = _diagnosis.get(key)
            if not d or d.get("reason_code") != "RUNNING":
                continue
            st = (live or {}).get(key) or status.get(key) or {}
            if not st.get("running"):
                continue
            ev = dict(d.get("evidence") or {})
            patched = False
            live_pid = st.get("pid")
            if live_pid is not None and ev.get("pid") != live_pid:
                ev["pid"] = live_pid
                patched = True
            port = ports.get(key)
            if port is not None and ev.get("port") != port:
                ev["port"] = port
                patched = True
            if patched:
                nd = dict(d)
                nd["evidence"] = ev
                _diagnosis[key] = nd
                changed_any = True
    if changed_any:
        _save_diagnosis()


_blocked_ips_lock = threading.Lock()


def _load_blocked_ips() -> dict:
    if not _BLOCKED_IPS_FILE.exists():
        return {}
    try:
        raw = json.loads(_BLOCKED_IPS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out = {}
        for ip, meta in raw.items():
            if isinstance(ip, str) and ip.strip() and isinstance(meta, dict):
                out[ip.strip()] = meta
        return out
    except Exception:
        return {}


def _save_blocked_ips(data: dict) -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _BLOCKED_IPS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_BLOCKED_IPS_FILE)
    except Exception:
        pass


def get_blocked_ips() -> list:
    """Aktif engelli IP listesi (Manager güvenlik paneli)."""
    with _blocked_ips_lock:
        data = _load_blocked_ips()
    items = []
    for ip, meta in sorted(data.items()):
        items.append({
            "ip": ip,
            "reason": meta.get("reason") or "",
            "banned_at": meta.get("banned_at") or "",
        })
    return items


def ban_ip(ip: str, reason: str = "Manager güvenlik paneli") -> dict:
    ip = (ip or "").strip()
    if not ip:
        raise ValueError("IP gerekli")
    with _blocked_ips_lock:
        data = _load_blocked_ips()
        entry = {
            "reason": (reason or "Manager güvenlik paneli")[:200],
            "banned_at": _now_tr_iso(),
            "banned_by": "manager",
        }
        data[ip] = entry
        _save_blocked_ips(data)
    audit_event("ip_ban", {"ip": ip, "reason": reason})
    return {"ok": True, "ip": ip, **entry}


def unban_ip(ip: str) -> dict:
    ip = (ip or "").strip()
    if not ip:
        raise ValueError("IP gerekli")
    removed = False
    with _blocked_ips_lock:
        data = _load_blocked_ips()
        if ip in data:
            del data[ip]
            _save_blocked_ips(data)
            removed = True
    if removed:
        audit_event("ip_unban", {"ip": ip})
    return {"ok": removed, "ip": ip}


def get_diagnosis(service: Optional[str] = None) -> dict:
    """Returns diagnosis dict(s). If service is None, returns { web: {...}, engine: {...}, manager: {...}, html: {...} }."""
    _ensure_diagnosis_current()
    _patch_running_diagnosis_pids()
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
    with _rings_lock:
        ring = logs_ring.get(key)
        if not ring or len(ring) == 0:
            return False
        return ring[-1] == line


def _rings_append_line(key: str, line: str, level: str) -> None:
    """Thread-safe append to log rings; issue ingest outside lock."""
    ingest: Optional[tuple] = None
    with _rings_lock:
        if key not in logs_ring:
            return
        logs_ring[key].append(line)
        if level == "ERROR":
            if not _is_noise_line(line, "ERROR"):
                errors_ring[key].append(line)
                ingest = (key, line, "ERROR")
        elif level == "WARN":
            if not _is_noise_line(line, "WARN"):
                warns_ring[key].append(line)
                ingest = (key, line, "WARN")
    if ingest:
        _ingest_issue(ingest[0], ingest[1], ingest[2])


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
                if key == "web" and (_is_web_access_200_line(line) or _is_auth_validate_ok_line(line)):
                    continue
                if key == "html" and _should_skip_html_stats_duplicate(key, line):
                    continue
                level = classify_line(line)
                if level == "WARN" and _backfill_should_skip_401_warn(key, line):
                    continue
                _rings_append_line(key, line, level)
            f.seek(0, 2)
            while stop and not stop.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                line = _truncate_line(line.rstrip("\n\r"))
                if key == "web" and (_is_web_access_200_line(line) or _is_auth_validate_ok_line(line)):
                    continue
                if key == "html" and _should_skip_html_stats_duplicate(key, line):
                    continue
                level = classify_line(line)
                if level == "WARN" and _should_throttle_401_warn(key, line):
                    continue
                _rings_append_line(key, line, level)
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
            if cur.get("reason_code") != "RUNNING":
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
    with _diagnosis_lock:
        mgr_diag = _diagnosis.get("manager") or {}
    if mgr_diag.get("reason_code") != "RUNNING":
        _produce_and_store_diagnosis("manager", "RUNNING")
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
    if html_running:
        with _diagnosis_lock:
            html_diag = _diagnosis.get("html") or {}
        if html_diag.get("reason_code") != "RUNNING":
            _produce_and_store_diagnosis("html", "RUNNING")
    _patch_running_diagnosis_pids(out)
    return out


def _produce_and_store_diagnosis(key: str, state: str, exit_code: Optional[int] = None, signal: Optional[str] = None) -> None:
    from manager_server.reason_engine import diagnose as reason_diagnose
    restart_count_5m, last_audit_was_stop = _diagnosis_context(key)
    port = 8000 if key == "web" else (7999 if key == "manager" else (_HTML_PORT if key == "html" else None))
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
        _do_start_html()
        time.sleep(1.5)
        get_status()
        if status["html"]["running"]:
            _produce_and_store_diagnosis("html", "RUNNING")
        else:
            _produce_and_store_diagnosis("html", "START_FAILED")
        return status["html"]["running"]
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
        _do_stop_html()
        time.sleep(0.5)
        get_status()
        _produce_and_store_diagnosis("html", "STOPPED")
        return not status["html"]["running"]
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
        _do_start_html()
        time.sleep(1.5)
        get_status()
        if status["html"]["running"]:
            _produce_and_store_diagnosis("html", "RUNNING")
        else:
            _produce_and_store_diagnosis("html", "START_FAILED")
        audit_event("restart", {"service": "html"})
        return status["html"]["running"]
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


_REBOOT_LOCK_FILE = _RUN_DIR / "stack_reboot.lock"


def _spawn_manager_reboot() -> bool:
    """Detached reboot helper: eski PID kapanınca manager_server yeniden başlar."""
    if _REBOOT_LOCK_FILE.is_file():
        try:
            holder = int(_REBOOT_LOCK_FILE.read_text(encoding="utf-8").strip())
            if _process_alive(holder):
                return True
        except Exception:
            pass
    if not _MANAGER_REBOOT.is_file():
        logging.getLogger(__name__).error("manager_reboot.py missing: %s", _MANAGER_REBOOT)
        return False
    old_pid = os.getpid()
    allow_remote = (os.environ.get("MANAGER_ALLOW_REMOTE") or "").strip()
    cmd = [
        _python_exe(),
        str(_MANAGER_REBOOT),
        "--old-pid",
        str(old_pid),
        "--root",
        str(_PROJECT_ROOT),
        "--python",
        _python_exe(),
    ]
    if allow_remote:
        cmd.extend(["--allow-remote", allow_remote])
    cmd.append("--full-stack")
    try:
        kw: dict = {"cwd": str(_PROJECT_ROOT), "stdin": subprocess.DEVNULL}
        if _IS_WINDOWS:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            kw["creationflags"] = flags
        else:
            kw["start_new_session"] = True
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        return True
    except Exception as e:
        logging.getLogger(__name__).error("manager reboot spawn failed: %s", e)
        return False


def _exit_manager_after_delay(delay_s: float = 0.75) -> None:
    def _go() -> None:
        time.sleep(delay_s)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)

    threading.Thread(target=_go, daemon=True).start()


def schedule_manager_restart() -> bool:
    """Manager dahil tüm stack'i yeniden başlat (panel API)."""
    if not _spawn_manager_reboot():
        return False
    status["manager"]["restart_count"] = status["manager"].get("restart_count", 0) + 1
    audit_event("restart", {"service": "stack", "full_process": True, "includes": ["manager", "web", "engine", "html"]})
    _exit_manager_after_delay()
    return True


_global_action_lock = threading.Lock()
_global_action_running = False


def global_action_busy() -> bool:
    with _global_action_lock:
        return _global_action_running


def schedule_global_action(action: str) -> dict[str, Any]:
    """Toplu start/stop/restart — HTTP yanıtını bloklamadan arka planda çalıştır."""
    global _global_action_running
    action = (action or "").strip().lower()
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "error": "invalid_action"}
    with _global_action_lock:
        if _global_action_running:
            return {"ok": False, "busy": True}
        _global_action_running = True

    runners = {
        "start": global_start,
        "stop": global_stop,
        "restart": global_restart,
    }

    def _work() -> None:
        global _global_action_running
        try:
            applied, skipped = runners[action]()
            audit_event("global_" + action, {"applied": applied, "skipped": skipped})
        except Exception as e:
            logging.getLogger(__name__).exception("global %s failed", action)
        finally:
            try:
                get_status()
            except Exception:
                pass
            with _global_action_lock:
                _global_action_running = False

    threading.Thread(target=_work, daemon=True, name="global-" + action).start()
    return {"ok": True, "pending": True, "action": action}


def global_start() -> tuple[list, list]:
    get_status()
    locks = load_locks()
    applied, skipped = [], []
    for key in ("web", "engine"):
        if locks.get(key):
            skipped.append(key)
            continue
        if not status.get(key, {}).get("running"):
            do_start(key)
            applied.append(key)
    if not status.get("html", {}).get("running"):
        do_start("html")
        applied.append("html")
    return applied, skipped


def global_stop() -> tuple[list, list]:
    get_status()
    locks = load_locks()
    applied, skipped = [], []
    for key in ("web", "engine"):
        if locks.get(key):
            skipped.append(key)
            continue
        if status.get(key, {}).get("running"):
            do_stop(key)
            applied.append(key)
    if status.get("html", {}).get("running"):
        do_stop("html")
        applied.append("html")
    return applied, skipped


def global_restart() -> tuple[list, list]:
    get_status()
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
            with _rings_lock:
                if k in logs_ring:
                    logs_ring[k].clear()
                    errors_ring[k].clear()
                    warns_ring[k].clear()
            with _batch_lock:
                if k in _ws_batch:
                    _ws_batch[k].clear()
    elif key in ("web", "engine", "manager", "html") and key in logs_ring:
        with _rings_lock:
            logs_ring[key].clear()
            errors_ring[key].clear()
            warns_ring[key].clear()
        with _batch_lock:
            _ws_batch[key].clear()


def get_logs(key: str, tail: int = 300) -> dict:
    if key not in ("web", "engine", "manager", "html"):
        return {"lines": [], "errors": [], "warns": []}
    tail = max(1, min(RING_LINES, tail))
    with _rings_lock:
        ring = logs_ring.get(key)
        if not ring:
            return {"lines": [], "errors": [], "warns": []}
        if key == "web":
            lines = [l for l in ring if not _is_web_access_200_line(l)]
        else:
            lines = list(ring)
        errors = list(errors_ring.get(key, ()))
        warns = list(warns_ring.get(key, ()))
    return {
        "lines": lines[-tail:] if len(lines) > tail else lines,
        "errors": errors,
        "warns": warns,
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
