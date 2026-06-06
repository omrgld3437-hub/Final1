"""
In-memory rate limiter for login and sensitive endpoints. Sliding window; configurable limits.
"""

import logging
import os
import time
import random
from collections import defaultdict
from typing import Tuple

logger = logging.getLogger(__name__)

# key -> list of timestamps (sliding window)
_store: dict = defaultdict(list)
_WINDOW_5MIN = 5 * 60
_MAX_KEYS = 2000


def _config_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip())
    except ValueError:
        return default


def _enabled() -> bool:
    return os.environ.get("AUTH_RATE_LIMIT_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _cleanup():
    global _store
    if len(_store) > _MAX_KEYS:
        cutoff = time.time() - _WINDOW_5MIN
        for k in list(_store.keys()):
            _store[k] = [t for t in _store[k] if t > cutoff]
            if not _store[k]:
                del _store[k]
        if len(_store) > _MAX_KEYS:
            by_age = sorted(
                _store.keys(), key=lambda k: min(_store[k]) if _store[k] else 0
            )
            for k in by_age[: len(_store) - _MAX_KEYS]:
                del _store[k]


def check_login_rate_limit(ip: str, user_key: str) -> Tuple[bool, int]:
    """
    Return (allowed, retry_after_seconds).
    user_key: normalized username or phone (lowercase/hash for privacy).
    """
    if not _enabled():
        return True, 0

    now = time.time()
    window = _config_int("AUTH_RATE_LIMIT_LOGIN_WINDOW_SEC", _WINDOW_5MIN)
    per_ip = _config_int("AUTH_RATE_LIMIT_LOGIN_PER_IP_5MIN", 20)
    per_user = _config_int("AUTH_RATE_LIMIT_LOGIN_PER_USER_5MIN", 10)

    cutoff = now - window
    ip_key = f"login:ip:{ip}"
    user_key_stored = f"login:user:{user_key[:64]}"

    for key in (ip_key, user_key_stored):
        _store[key] = [t for t in _store[key] if t > cutoff]
    _cleanup()

    ip_count = len(_store[ip_key])
    user_count = len(_store[user_key_stored])
    limit_ip = per_ip
    limit_user = per_user

    if ip_count >= limit_ip:
        # Jitter to avoid thundering herd
        retry = min(window, 60 + random.randint(0, 30))
        logger.info(
            "rate_limit login ip=%s ip_count=%s limit=%s retry_after=%s",
            ip[:16] + "***",
            ip_count,
            limit_ip,
            retry,
        )
        return False, retry
    if user_count >= limit_user:
        retry = min(window, 60 + random.randint(0, 30))
        logger.info(
            "rate_limit login user_key_count=%s limit=%s retry_after=%s",
            user_count,
            limit_user,
            retry,
        )
        return False, retry

    _store[ip_key].append(now)
    _store[user_key_stored].append(now)
    return True, 0
