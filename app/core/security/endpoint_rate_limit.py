"""
Hassas / sık çağrılan API endpoint'leri için kayan pencere rate limit.
Login limiter'dan ayrı; RAM sınırı: en fazla _MAX_KEYS anahtar.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections import defaultdict
from typing import Tuple

logger = logging.getLogger(__name__)

_store: dict = defaultdict(list)
_MAX_KEYS = 4000
_WINDOW_CAP_SEC = 600.0


def _enabled() -> bool:
    return os.environ.get("ENDPOINT_RATE_LIMIT_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _cleanup(cutoff: float) -> None:
    global _store
    for k in list(_store.keys()):
        _store[k] = [t for t in _store[k] if t > cutoff]
        if not _store[k]:
            del _store[k]
    if len(_store) > _MAX_KEYS:
        by_age = sorted(
            _store.keys(), key=lambda k: min(_store[k]) if _store[k] else 0.0
        )
        for k in by_age[: len(_store) - _MAX_KEYS]:
            del _store[k]


def check_endpoint_rate_limit(
    key: str,
    *,
    limit: int,
    window_sec: float = 60.0,
) -> Tuple[bool, int]:
    """
    (allowed, retry_after_seconds). allowed=False → HTTP 429 önerilir.
    """
    if not _enabled() or limit <= 0:
        return True, 0
    now = time.time()
    window = min(max(float(window_sec), 1.0), _WINDOW_CAP_SEC)
    cutoff = now - window
    k = (key or "unknown")[:128]
    _store[k] = [t for t in _store[k] if t > cutoff]
    _cleanup(cutoff)
    if len(_store[k]) >= limit:
        retry = int(min(window, 30 + random.randint(0, 15)))
        logger.info(
            "endpoint_rate_limit key=%s count=%s limit=%s retry=%s",
            k[:48],
            len(_store[k]),
            limit,
            retry,
        )
        return False, retry
    _store[k].append(now)
    return True, 0
