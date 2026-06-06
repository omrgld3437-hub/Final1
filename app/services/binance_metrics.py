"""
Binance REST call metrics: total count, by path, duration (avg, p95).
Single gateway (binance_spot) should call record() on every request.
"""
from __future__ import annotations
import threading
import time
from collections import defaultdict
from typing import Dict, Any, List


class BinanceMetrics:
    _lock = threading.Lock()
    _total = 0
    _retry_count = 0
    _last_latency_ms: float = 0.0
    _by_path: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "total_ms": 0.0,
        "latencies": [],  # keep last 100 for p95
    })
    _max_latencies = 100

    @classmethod
    def record(cls, path: str, duration_ms: float, retry_count: int = 0) -> None:
        with cls._lock:
            cls._total += 1
            cls._retry_count += retry_count
            cls._last_latency_ms = duration_ms
            r = cls._by_path[path]
            r["count"] += 1
            r["total_ms"] += duration_ms
            lat = r["latencies"]
            lat.append(duration_ms)
            if len(lat) > cls._max_latencies:
                r["latencies"] = lat[-cls._max_latencies:]

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        with cls._lock:
            rows = []
            for path, r in cls._by_path.items():
                c = r["count"]
                avg_ms = round(r["total_ms"] / c, 2) if c else 0
                lat = r["latencies"]
                p95_ms = 0.0
                if lat:
                    s = sorted(lat)
                    idx = max(0, int(0.95 * len(s)) - 1)
                    p95_ms = round(s[idx], 2)
                rows.append({"path": path, "count": c, "avg_ms": avg_ms, "p95_ms": p95_ms})
            rows.sort(key=lambda x: -x["count"])
        total_ms_all = sum(r["total_ms"] for r in cls._by_path.values())
        try:
            from app.services.binance_spot import CircuitBreaker
            circuit_state = CircuitBreaker.get_state()
        except Exception:
            circuit_state = "unknown"
        return {
            "binance_calls_total": cls._total,
            "binance_retry_count": cls._retry_count,
            "binance_latency_ms": round(cls._last_latency_ms, 2),
            "binance_latency_avg_ms": round(total_ms_all / cls._total, 2) if cls._total else 0,
            "binance_calls_by_path": rows[:30],
            "binance_circuit_state": circuit_state,
        }
