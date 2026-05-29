"""
Binance REST load monitor — 1 dakikalık pencere, rest.log dosyasına detaylı özet.
Tüm gateway çağrıları buradan geçer; budget aşımında istek engellenir (418 ban önleme).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Kaynak etiketi (with rest_source("data_hub.ticker_24h"): ...)
_current_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "binance_rest_source", default="unknown"
)

REST_LOG_ENABLED = os.getenv("REST_LOG_ENABLED", "1").strip().lower() in ("1", "true", "yes")
REST_LOG_INTERVAL_SEC = float(os.getenv("REST_LOG_INTERVAL_SEC", "60"))
REST_LOG_PATH = Path(os.getenv("REST_LOG_PATH", "rest.log"))
REST_WEIGHT_LIMIT = int(os.getenv("BINANCE_WEIGHT_LIMIT_PER_MIN", "1200"))
REST_SOFT_LIMIT = int(os.getenv("REST_SOFT_WEIGHT_LIMIT", str(int(REST_WEIGHT_LIMIT * 0.85))))

# Endpoint başına minimum aralık (saniye) — bulk 24hr en ağır suçlu
_PATH_MIN_INTERVAL: Dict[str, float] = {
    "/api/v3/ticker/24hr": 45.0,   # bulk (symbol yok) — max ~1.3/dk, weight ~53/dk
    "/api/v3/ticker/price": 8.0,    # bulk price — max ~7.5/dk, weight ~15/dk
    "/api/v3/exchangeInfo": 300.0,
    "/api/v3/time": 25.0,
    "/api/v3/klines": 2.0,
    "/api/v3/openOrders": 12.0,
    "/api/v3/account": 8.0,
    "/api/v3/allOrders": 15.0,
}
_PATH_MIN_INTERVAL_SINGLE: Dict[str, float] = {
    "/api/v3/ticker/24hr": 3.0,
    "/api/v3/ticker/price": 3.0,
}

_lock = threading.Lock()
_window_start = time.time()
_REST_EVENTS_MAX = int(os.getenv("REST_EVENTS_MAX", "1200"))
_events: Deque[Dict[str, Any]] = deque(maxlen=max(200, _REST_EVENTS_MAX))


def get_rest_events_buffer_info() -> Dict[str, Any]:
    """RAM capture: deque boyutu (okuma güvenli)."""
    return {"deque_len": len(_events), "maxlen": _events.maxlen}
_last_path_ts: Dict[str, float] = {}
_flush_task: Optional[asyncio.Task] = None
_denied_by_reason: Dict[str, int] = defaultdict(int)


def rest_source(name: str):
    """Context manager: çağrı kaynağını etiketle."""
    class _CM:
        def __enter__(self):
            self._token = _current_source.set(name)
            return self

        def __exit__(self, *_):
            _current_source.reset(self._token)

    return _CM()


def get_rest_source() -> str:
    return _current_source.get()


def compute_weight(path: str, method: str = "GET", params: Optional[Dict[str, Any]] = None) -> int:
    """Binance dokümantasyonuna göre endpoint weight."""
    p = params or {}
    m = method.upper()
    if "/api/v3/account" in path:
        return 10
    if "/api/v3/order" in path and m in ("POST", "DELETE"):
        return 1
    if "/api/v3/openOrders" in path or "/api/v3/allOrders" in path:
        return 10
    if "/api/v3/myTrades" in path:
        return 10
    if "/api/v3/time" in path:
        return 1
    if "/api/v3/exchangeInfo" in path:
        return 10
    if "/api/v3/ticker/price" in path:
        return 1 if p.get("symbol") else 2
    if "/api/v3/ticker/24hr" in path:
        return 1 if p.get("symbol") else 40
    if "/api/v3/klines" in path:
        try:
            limit = int(p.get("limit") or 500)
        except (TypeError, ValueError):
            limit = 500
        if limit <= 100:
            return 1
        if limit <= 500:
            return 2
        return 5
    return 5


def _path_throttle_key(path: str, params: Optional[Dict[str, Any]]) -> str:
    p = params or {}
    sym = p.get("symbol")
    if sym:
        return f"{path}?symbol={sym}"
    return path


def should_allow_rest(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
) -> Tuple[bool, str, int]:
    """
    İstek gönderilmeden önce kontrol.
    Returns: (allowed, reason, weight)
    """
    weight = compute_weight(path, method, params)
    src = source or get_rest_source()
    now = time.time()

    # Signed-request timestamps depend on this (weight 1); never throttle or budget-block.
    if "/api/v3/time" in path:
        return True, "ok", weight

    try:
        from app.services.binance_spot import is_ip_banned
        if is_ip_banned():
            return False, "ip_banned", weight
    except Exception:
        pass

    # Global weight budget (sync-safe kayıt)
    try:
        from app.services.binance_weight import get_weight_used_last_60s
        used = get_weight_used_last_60s(None, None)
        if used + weight > REST_WEIGHT_LIMIT:
            return False, f"weight_budget({used}+{weight}>{REST_WEIGHT_LIMIT})", weight
        if used + weight > REST_SOFT_LIMIT and weight >= 10:
            return False, f"soft_limit({used}+{weight}>{REST_SOFT_LIMIT})", weight
    except Exception:
        pass

    # Per-path minimum interval
    p = params or {}
    is_single = bool(p.get("symbol"))
    min_iv = (
        _PATH_MIN_INTERVAL_SINGLE.get(path, 0)
        if is_single
        else _PATH_MIN_INTERVAL.get(path, 0)
    )
    if min_iv > 0:
        key = _path_throttle_key(path, params)
        last = _last_path_ts.get(key, 0.0)
        if now - last < min_iv:
            return False, f"throttle({key},{min_iv}s)", weight

    return True, "ok", weight


def record_rest(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
    weight: Optional[int] = None,
    status: Optional[int] = None,
    latency_ms: float = 0.0,
    outcome: str = "ok",
    detail: str = "",
) -> None:
    """Her REST denemesini kaydet (ok / denied / skipped / error)."""
    if not REST_LOG_ENABLED:
        return
    w = weight if weight is not None else compute_weight(path, method, params)
    src = source or get_rest_source()
    evt = {
        "ts": time.time(),
        "method": method.upper(),
        "path": path,
        "source": src,
        "weight": w,
        "status": status,
        "latency_ms": round(latency_ms, 1),
        "outcome": outcome,
        "detail": detail[:200] if detail else "",
        "params_keys": sorted((params or {}).keys()),
        "has_symbol": bool((params or {}).get("symbol")),
    }
    with _lock:
        _events.append(evt)
        if outcome == "ok":
            key = _path_throttle_key(path, params)
            _last_path_ts[key] = evt["ts"]
        elif outcome in ("denied", "skipped"):
            _denied_by_reason[evt.get("detail") or outcome] += 1


def _aggregate_window(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_path: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "weight": 0, "ok": 0, "denied": 0, "skipped": 0, "error": 0, "sources": defaultdict(int)}
    )
    by_source: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "weight": 0, "ok": 0, "denied": 0}
    )
    total_weight_ok = 0
    denied = skipped = errors = 0
    for e in events:
        path = e["path"]
        src = e["source"]
        w = e["weight"]
        oc = e["outcome"]
        by_path[path]["count"] += 1
        by_path[path]["weight"] += w if oc == "ok" else 0
        by_path[path][oc if oc in ("ok", "denied", "skipped", "error") else "error"] += 1
        by_path[path]["sources"][src] += 1
        by_source[src]["count"] += 1
        if oc == "ok":
            by_source[src]["weight"] += w
            by_source[src]["ok"] += 1
            total_weight_ok += w
        elif oc == "denied":
            by_source[src]["denied"] += 1
            denied += 1
        elif oc == "skipped":
            skipped += 1
        else:
            errors += 1
    return {
        "total_events": len(events),
        "total_weight_ok": total_weight_ok,
        "denied": denied,
        "skipped": skipped,
        "errors": errors,
        "by_path": dict(by_path),
        "by_source": dict(by_source),
    }


def _format_window_report(start_ts: float, end_ts: float, agg: Dict[str, Any]) -> str:
    start_s = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    end_s = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pid = os.getpid()
    lines = [
        "",
        "=" * 72,
        f"REST window {start_s} → {end_s}  pid={pid}",
        f"events={agg['total_events']}  weight_ok={agg['total_weight_ok']}/{REST_WEIGHT_LIMIT}  "
        f"denied={agg['denied']}  skipped={agg['skipped']}  errors={agg['errors']}",
        "-" * 72,
        "by_path (weight = sadece başarılı istekler):",
    ]
    paths = sorted(agg["by_path"].items(), key=lambda x: -x[1]["weight"])
    for path, d in paths[:25]:
        src_bits = ", ".join(f"{s}({c})" for s, c in sorted(d["sources"].items(), key=lambda x: -x[1])[:4])
        lines.append(
            f"  {path:32} cnt={d['count']:4}  w={d['weight']:4}  "
            f"ok={d['ok']} skip={d['skipped']} deny={d['denied']} err={d['error']}  [{src_bits}]"
        )
    lines.append("-" * 72)
    lines.append("by_source:")
    for src, d in sorted(agg["by_source"].items(), key=lambda x: -x[1]["weight"])[:20]:
        lines.append(f"  {src:40} cnt={d['count']:4}  w={d['weight']:4}  ok={d['ok']} deny={d['denied']}")
    if _denied_by_reason:
        lines.append("-" * 72)
        lines.append("deny/skip reasons (kümülatif):")
        for reason, cnt in sorted(_denied_by_reason.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"  {reason}: {cnt}")
    # Otomatik uyarılar
    hints: List[str] = []
    for path, d in agg["by_path"].items():
        if path == "/api/v3/ticker/24hr" and d["count"] >= 6:
            hints.append(f"ticker/24hr bulk {d['count']}x/dk (~{d['weight']} weight) — interval artır veya DataHub cache kullan")
        if path == "/api/v3/ticker/price" and d["count"] >= 15:
            hints.append(f"ticker/price bulk {d['count']}x/dk — WS aktifken REST price kapat")
        if path == "/api/v3/openOrders" and d["count"] >= 8:
            hints.append(f"openOrders {d['count']}x/dk — cache TTL artır veya ban sırasında atla")
    if agg["total_weight_ok"] > REST_SOFT_LIMIT:
        hints.append(f"weight_ok={agg['total_weight_ok']} soft limit ({REST_SOFT_LIMIT}) üstünde — ban riski yüksek")
    if hints:
        lines.append("-" * 72)
        lines.append("warnings:")
        for h in hints:
            lines.append(f"  ! {h}")
    lines.append("=" * 72)
    return "\n".join(lines)


def flush_rest_log(force: bool = False) -> None:
    """Mevcut pencereyi rest.log dosyasına yaz."""
    if not REST_LOG_ENABLED and not force:
        return
    with _lock:
        global _window_start
        now = time.time()
        events = list(_events)
        start = _window_start
        _events.clear()
        _window_start = now
    if not events and not force:
        return
    agg = _aggregate_window(events)
    report = _format_window_report(start, now, agg)
    try:
        log_path = REST_LOG_PATH
        if not log_path.is_absolute():
            root = Path(__file__).resolve().parents[2]
            log_path = root / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    except Exception as e:
        logger.warning("rest.log write failed: %s", e)


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(REST_LOG_INTERVAL_SEC)
        try:
            flush_rest_log()
        except Exception as e:
            logger.debug("rest_log flush: %s", e)


def start_rest_log_flush_task() -> None:
    """Web/worker startup: 60s periyodik rest.log yazıcı."""
    global _flush_task
    if not REST_LOG_ENABLED:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _flush_task and not _flush_task.done():
        return
    _flush_task = loop.create_task(_flush_loop())
    logger.info("REST log flush started path=%s interval=%ss", REST_LOG_PATH, REST_LOG_INTERVAL_SEC)


def get_live_snapshot() -> Dict[str, Any]:
    """Debug: anlık pencere özeti (endpoint veya log okuma)."""
    with _lock:
        events = list(_events)
        start = _window_start
    agg = _aggregate_window(events)
    return {
        "window_start_ts": start,
        "window_age_sec": round(time.time() - start, 1),
        "log_path": str(REST_LOG_PATH),
        **agg,
    }
