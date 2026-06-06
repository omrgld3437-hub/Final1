# app/services/cache.py
from __future__ import annotations
import time
from typing import Any, Dict, Tuple

class TTLCache:
    def __init__(self):
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = (time.time() + ttl_seconds, value)

    def clear_prefix(self, prefix: str) -> None:
        keys = [k for k in self._store.keys() if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)


