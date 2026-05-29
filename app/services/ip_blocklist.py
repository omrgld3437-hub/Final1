"""Web uygulaması IP engel listesi — .run/blocked_ips.json (Manager panel yazar)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BLOCK_FILE = _PROJECT_ROOT / ".run" / "blocked_ips.json"
_cache_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "data": {}}
_CACHE_TTL_SEC = 2.0
_file_mtime: float = 0.0


def _file_mtime_ns() -> float:
    try:
        return _BLOCK_FILE.stat().st_mtime if _BLOCK_FILE.exists() else 0.0
    except Exception:
        return 0.0


def _load() -> Dict[str, dict]:
    global _file_mtime
    now = time.time()
    mtime = _file_mtime_ns()
    with _cache_lock:
        if now - _cache["ts"] < _CACHE_TTL_SEC and mtime == _file_mtime:
            return dict(_cache["data"])
    data: Dict[str, dict] = {}
    try:
        if _BLOCK_FILE.exists():
            raw = json.loads(_BLOCK_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for ip, meta in raw.items():
                    if isinstance(ip, str) and ip.strip() and isinstance(meta, dict):
                        data[ip.strip()] = meta
    except Exception:
        pass
    with _cache_lock:
        _cache["ts"] = now
        _cache["data"] = data
        _file_mtime = mtime
    return data


def is_ip_blocked(ip: str) -> bool:
    if not ip:
        return False
    return ip in _load()


def invalidate_cache() -> None:
    with _cache_lock:
        _cache["ts"] = 0.0
        _cache["data"] = {}
