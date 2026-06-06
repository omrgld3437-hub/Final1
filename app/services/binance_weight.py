"""
Binance weight budget - sliding 60s window. Deny call if insufficient.
weight_used_last_60s, weight_denied_count, weight_wait_ms
"""

from __future__ import annotations
import asyncio
import logging
import time
from collections import deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Per account_id (or api_key) sliding window: (ts, weight) entries older than 60s are dropped
_weight_window: Dict[str, deque] = {}
_weight_lock = asyncio.Lock()
_weight_denied_count: Dict[str, int] = {}
_weight_wait_ms: Dict[str, float] = {}
BINANCE_WEIGHT_LIMIT_PER_MIN = 1200  # Typical IP limit
WINDOW_SEC = 60.0

# Endpoint weights (Binance docs)
WEIGHT_ACCOUNT = 10
WEIGHT_ORDER = 1
WEIGHT_OPEN_ORDERS = 10
WEIGHT_ALL_ORDERS = 10
WEIGHT_TICKER_PRICE = 2
WEIGHT_TICKER_24HR = 1
WEIGHT_EXCHANGE_INFO = 10
WEIGHT_TIME = 1


def _key(account_id: Optional[int], api_key: Optional[str]) -> str:
    """Tek IP limiti: public + signed çağrılar aynı pencerede toplanır."""
    if api_key:
        return f"acc_{account_id or 0}_key_{api_key[:8]}"
    return "ip_global"


async def request_weight_tokens(
    account_id: Optional[int], api_key: Optional[str], weight: int
) -> bool:
    """
    Weight budget kontrolü (rezervasyon yapmaz — kayıt başarılı HTTP sonrası record_weight_used ile).
    False ise çağrı yapma; stale/cache dön.
    """
    key = _key(account_id, api_key)
    async with _weight_lock:
        now = time.time()
        if key not in _weight_window:
            _weight_window[key] = deque()
        q = _weight_window[key]
        while q and now - q[0][0] > WINDOW_SEC:
            q.popleft()
        used = sum(w for _, w in q)
        if used + weight > BINANCE_WEIGHT_LIMIT_PER_MIN:
            _weight_denied_count[key] = _weight_denied_count.get(key, 0) + 1
            logger.warning(
                "BINANCE_WEIGHT_DENIED key=%s used=%s requested=%s limit=%s",
                key,
                used,
                weight,
                BINANCE_WEIGHT_LIMIT_PER_MIN,
            )
            return False
        return True


def record_weight_used(
    account_id: Optional[int],
    api_key: Optional[str],
    weight: int,
    latency_ms: float = 0,
) -> None:
    """Record weight after successful call (sync-safe)."""
    key = _key(account_id, api_key)
    _record_weight_sync(key, weight, latency_ms)


def _record_weight_sync(key: str, weight: int, latency_ms: float = 0) -> None:
    if key not in _weight_window:
        _weight_window[key] = deque()
    _weight_window[key].append((time.time(), weight))
    _weight_wait_ms[key] = latency_ms
    q = _weight_window[key]
    now = time.time()
    while q and now - q[0][0] > WINDOW_SEC:
        q.popleft()


def get_weight_used_last_60s(
    account_id: Optional[int] = None, api_key: Optional[str] = None
) -> int:
    """Sum of weights in last 60s for key."""
    key = _key(account_id, api_key)
    if key not in _weight_window:
        return 0
    q = _weight_window[key]
    now = time.time()
    return sum(w for ts, w in q if now - ts <= WINDOW_SEC)


def get_weight_denied_count(
    account_id: Optional[int] = None, api_key: Optional[str] = None
) -> int:
    return _weight_denied_count.get(_key(account_id, api_key), 0)


def get_weight_wait_ms(
    account_id: Optional[int] = None, api_key: Optional[str] = None
) -> float:
    return _weight_wait_ms.get(_key(account_id, api_key), 0.0)


def get_metrics() -> Dict:
    """Export for debug/metrics endpoint."""
    now = time.time()
    total_used = sum(
        sum(w for ts, w in q if now - ts <= WINDOW_SEC) for q in _weight_window.values()
    )
    global_used = get_weight_used_last_60s(None, None)
    return {
        "weight_used_last_60s": global_used,
        "weight_used_all_keys": total_used,
        "weight_denied_count": sum(_weight_denied_count.values()),
        "weight_wait_ms": sum(_weight_wait_ms.values()) / max(1, len(_weight_wait_ms)),
        "limit_per_min": BINANCE_WEIGHT_LIMIT_PER_MIN,
    }
