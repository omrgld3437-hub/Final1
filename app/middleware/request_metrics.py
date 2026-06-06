"""
Request metrics middleware: per-route count, latency (avg, p95), status summary.
In-memory only (debug); resets on app restart.
"""

from __future__ import annotations
import re
import time
from collections import defaultdict
from typing import Dict, List, Any
import threading

# Route template: /api/bots/123 -> /api/bots/{id}, /api/accounts/1/wallet -> /api/accounts/{id}/wallet
_PATH_NORMALIZE_RE = re.compile(
    r"/\d+|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _normalize_path(path: str) -> str:
    if not path or path == "/":
        return path
    # Strip query string
    base = path.split("?")[0]
    # Replace numeric segments and UUIDs with {id}
    out = _PATH_NORMALIZE_RE.sub("/{id}", base) or base
    # Collapse multiple slashes (e.g. /api/items//{id} -> /api/items/{id})
    while "//" in out:
        out = out.replace("//", "/")
    return out


class RingBuffer:
    """Fixed-size buffer for last N latencies (for p95)."""

    __slots__ = ("buf", "n", "i", "full")

    def __init__(self, size: int = 200):
        self.buf: List[float] = [0.0] * size
        self.n = size
        self.i = 0
        self.full = False

    def append(self, x: float) -> None:
        self.buf[self.i] = x
        self.i = (self.i + 1) % self.n
        if self.i == 0:
            self.full = True

    def p50(self) -> float:
        if not self.full and self.i == 0:
            return 0.0
        k = self.n if self.full else self.i
        arr = sorted(self.buf[:k])
        idx = max(0, int(0.5 * k) - 1)
        return round(arr[idx], 2)

    def p95(self) -> float:
        if not self.full and self.i == 0:
            return 0.0
        k = self.n if self.full else self.i
        arr = sorted(self.buf[:k])
        idx = max(0, int(0.95 * k) - 1)
        return round(arr[idx], 2)

    def __len__(self) -> int:
        return self.n if self.full else self.i


_RECENT_REQUESTS_MAX = 50
_MAX_ROUTES = 120
_MAX_USER_AGENT_ENTRIES = 80
_MAX_IPS = 400
_RING_SIZE = 100
_TOP_PATHS_MAX = 50
_TOP_IPS_MAX = 50
_LOGIN_FAILS_MAX = 50


class RequestMetrics:
    """In-memory request metrics: count, avg_ms, p95, status_counts, client_ips, user_agents, recent requests. Capped for RAM stability."""

    _lock = threading.Lock()
    _start_time: float = time.perf_counter()
    _by_route: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "total_ms": 0.0,
            "latencies": RingBuffer(_RING_SIZE),
            "status_counts": defaultdict(int),
            "methods": defaultdict(int),
        }
    )
    _status_global: Dict[int, int] = defaultdict(int)
    _ips: set = set()
    _ip_counts: Dict[str, int] = defaultdict(int)
    _user_agents: Dict[str, int] = defaultdict(int)
    _recent_requests: List[Dict[str, Any]] = []
    _login_fail_total: int = 0
    _last_login_fails: List[Dict[str, Any]] = []

    @classmethod
    def _trim_routes(cls) -> None:
        if len(cls._by_route) <= _MAX_ROUTES:
            return
        by_count = sorted(cls._by_route.items(), key=lambda x: -x[1]["count"])
        for route, _ in by_count[_MAX_ROUTES:]:
            cls._by_route.pop(route, None)

    @classmethod
    def _trim_user_agents(cls) -> None:
        if len(cls._user_agents) <= _MAX_USER_AGENT_ENTRIES:
            return
        by_count = sorted(cls._user_agents.items(), key=lambda x: -x[1])
        for ua, _ in by_count[_MAX_USER_AGENT_ENTRIES:]:
            cls._user_agents.pop(ua, None)

    @classmethod
    def _trim_ips(cls) -> None:
        if len(cls._ips) <= _MAX_IPS:
            return
        lst = list(cls._ips)
        cls._ips = set(lst[-_MAX_IPS:])

    @classmethod
    def _trim_ip_counts(cls) -> None:
        """Keep only top _TOP_IPS_MAX by count."""
        if len(cls._ip_counts) <= _TOP_IPS_MAX:
            return
        by_count = sorted(cls._ip_counts.items(), key=lambda x: -x[1])
        cls._ip_counts = dict(by_count[:_TOP_IPS_MAX])

    @classmethod
    def record_login_fail(cls, ip: str, user: str, reason: str = "") -> None:
        """Record a login failure for Manager SECURITY panel. Bounded to last _LOGIN_FAILS_MAX."""
        with cls._lock:
            cls._login_fail_total += 1
            entry = {
                "ts": round(time.time(), 2),
                "ip": (ip or "")[:64],
                "user": (user or "")[:128],
                "reason": (reason or "")[:64],
            }
            cls._last_login_fails.append(entry)
            if len(cls._last_login_fails) > _LOGIN_FAILS_MAX:
                cls._last_login_fails = cls._last_login_fails[-_LOGIN_FAILS_MAX:]

    @classmethod
    def record(
        cls,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client_ip: str = "",
        user_agent: str = "",
    ) -> None:
        route = _normalize_path(path)
        with cls._lock:
            cls._start_time = cls._start_time  # no-op, keep start
            r = cls._by_route[route]
            r["count"] += 1
            r["total_ms"] += duration_ms
            r["latencies"].append(duration_ms)
            r["status_counts"][status_code] += 1
            r["methods"][method.upper()] += 1
            cls._status_global[status_code] += 1
            if client_ip:
                cls._ips.add(client_ip)
                cls._ip_counts[client_ip] = cls._ip_counts.get(client_ip, 0) + 1
            if user_agent:
                ua_short = (
                    (user_agent[:80] + "..") if len(user_agent) > 80 else user_agent
                )
                cls._user_agents[ua_short] += 1
            cls._trim_routes()
            cls._trim_user_agents()
            cls._trim_ips()
            cls._trim_ip_counts()
            # Son istekler (log sayfası için)
            entry = {
                "method": (method or "GET").upper(),
                "path": (path or "")[:256],
                "status": status_code,
                "ms": round(duration_ms, 2),
                "ts": round(time.time(), 2),
            }
            cls._recent_requests.append(entry)
            if len(cls._recent_requests) > _RECENT_REQUESTS_MAX:
                cls._recent_requests = cls._recent_requests[-_RECENT_REQUESTS_MAX:]

    @classmethod
    def total_requests(cls) -> int:
        with cls._lock:
            return sum(r["count"] for r in cls._by_route.values())

    @classmethod
    def reset_counts(cls) -> None:
        """Sayaçları sıfırla (sistem yeniden başlatıldığında log sayfası için)."""
        with cls._lock:
            cls._start_time = time.perf_counter()
            cls._by_route.clear()
            cls._status_global.clear()
            cls._ips.clear()
            cls._ip_counts.clear()
            cls._user_agents.clear()
            cls._recent_requests.clear()
            # login_fail_total and _last_login_fails kept for security audit (or clear: cls._login_fail_total = 0; cls._last_login_fails.clear())

    @classmethod
    def snapshot_web_metrics(cls) -> Dict[str, Any]:
        """Snapshot for .run/web.metrics.json: request_total, requests_per_min, status_2xx/4xx/5xx, top_paths (max 50), top_ips (max 50), login_fail_total, last_50_login_fails."""
        with cls._lock:
            total = sum(r["count"] for r in cls._by_route.values())
            uptime = max(0.01, time.perf_counter() - cls._start_time)
            rps = total / uptime if uptime else 0
            requests_per_min = round(rps * 60, 1)
            s = cls._status_global
            status_2xx = sum(s.get(c, 0) for c in (200, 201, 204))
            status_4xx = sum(s.get(c, 0) for c in (400, 401, 403, 404, 429))
            status_5xx = sum(s.get(c, 0) for c in (500, 502, 503))
            total_req = sum(r["count"] for r in cls._by_route.values())
            latencies_p50 = [
                r["latencies"].p50() for r in cls._by_route.values() if r["count"]
            ]
            latencies_p95 = [
                r["latencies"].p95() for r in cls._by_route.values() if r["count"]
            ]
            latency_p50_ms = (
                round(sum(latencies_p50) / len(latencies_p50), 2)
                if latencies_p50
                else 0
            )
            latency_p95_ms = round(max(latencies_p95), 2) if latencies_p95 else 0
            routes = sorted(
                [
                    {"path": route, "count": r["count"]}
                    for route, r in cls._by_route.items()
                ],
                key=lambda x: -x["count"],
            )[:_TOP_PATHS_MAX]
            top_paths = [{"path": x["path"], "count": x["count"]} for x in routes]
            ip_list = sorted(cls._ip_counts.items(), key=lambda x: -x[1])[:_TOP_IPS_MAX]
            top_ips = [{"ip": ip, "count": c} for ip, c in ip_list]
            last_login_fails = list(cls._last_login_fails)[-_LOGIN_FAILS_MAX:]
            return {
                "request_total": total,
                "requests_per_min": requests_per_min,
                "status_2xx": status_2xx,
                "status_4xx": status_4xx,
                "status_5xx": status_5xx,
                "latency_p50_ms": latency_p50_ms,
                "latency_p95_ms": latency_p95_ms,
                "error_rate": (status_4xx + status_5xx) / total_req if total_req else 0,
                "top_paths": top_paths,
                "top_ips": top_ips,
                "login_fail_total": cls._login_fail_total,
                "last_login_fails": last_login_fails,
                "ts": round(time.time(), 2),
            }

    @classmethod
    def uptime_sec(cls) -> float:
        return round(time.perf_counter() - cls._start_time, 2)

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        with cls._lock:
            total = sum(r["count"] for r in cls._by_route.values())
            uptime = max(0.01, time.perf_counter() - cls._start_time)
            rps_avg = total / uptime if uptime else 0

            def route_summary(route: str, r: Dict) -> Dict[str, Any]:
                c = r["count"]
                avg = round(r["total_ms"] / c, 2) if c else 0
                return {
                    "route": route,
                    "count": c,
                    "avg_ms": avg,
                    "p95_ms": r["latencies"].p95(),
                    "status": dict(r["status_counts"]),
                }

            routes = [route_summary(route, r) for route, r in cls._by_route.items()]
            routes.sort(key=lambda x: -x["count"])

            by_count = routes[:20]
            by_avg = sorted(routes, key=lambda x: -x["avg_ms"])[:20]
            by_p95 = sorted(routes, key=lambda x: -x["p95_ms"])[:20]

            ua_list = sorted(
                [{"ua": ua, "count": c} for ua, c in cls._user_agents.items()],
                key=lambda x: -x["count"],
            )[:10]

        return {
            "uptime_sec": round(uptime, 2),
            "total_requests": total,
            "rps_avg": round(rps_avg, 2),
            "top_by_count": by_count,
            "top_by_avg_latency": by_avg,
            "top_by_p95_latency": by_p95,
            "status_summary": dict(cls._status_global),
            "unique_ips_count": len(cls._ips),
            "top_user_agents": ua_list,
        }


def get_metrics() -> Dict[str, Any]:
    return RequestMetrics.to_dict()


def get_recent_requests() -> List[Dict[str, Any]]:
    """Son N istek (log sayfası için). En yeni en sonda."""
    with RequestMetrics._lock:
        return list(RequestMetrics._recent_requests)
