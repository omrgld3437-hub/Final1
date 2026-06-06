"""
Metrics stubs for snapshot and future observability.
Replace with real histogram implementation (e.g. Prometheus) when available.
"""
from __future__ import annotations
import threading
from collections import deque
from typing import Deque

# Last N values for snapshot (placeholder histograms)
_SNAPSHOT_SERVER_MS: Deque[float] = deque(maxlen=500)
_SNAPSHOT_PAYLOAD_BYTES: Deque[int] = deque(maxlen=500)
_lock = threading.Lock()


def record_snapshot(server_ms: float, payload_bytes: int) -> None:
    """Record one snapshot response for stub histograms."""
    with _lock:
        _SNAPSHOT_SERVER_MS.append(server_ms)
        _SNAPSHOT_PAYLOAD_BYTES.append(payload_bytes)


def get_snapshot_metrics() -> dict:
    """Return stub histogram stats (count, p50, p95) for snapshot."""
    with _lock:
        ms_list = list(_SNAPSHOT_SERVER_MS)
        bytes_list = list(_SNAPSHOT_PAYLOAD_BYTES)
    n = len(ms_list)
    if n == 0:
        return {"snapshot_server_ms": {"count": 0, "p50": 0, "p95": 0}, "snapshot_payload_bytes": {"count": 0, "p50": 0, "p95": 0}}
    ms_sorted = sorted(ms_list)
    bytes_sorted = sorted(bytes_list)
    return {
        "snapshot_server_ms": {"count": n, "p50": ms_sorted[int(0.5 * n)] if n else 0, "p95": ms_sorted[int(0.95 * n)] if n else 0},
        "snapshot_payload_bytes": {"count": n, "p50": bytes_sorted[int(0.5 * n)] if n else 0, "p95": bytes_sorted[int(0.95 * n)] if n else 0},
    }
