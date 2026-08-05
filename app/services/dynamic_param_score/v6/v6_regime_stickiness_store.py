"""Pluggable persistence for V6 regime stickiness (multi-worker ready).

Default: process memory (existing behaviour).
Optional file store (``V6_REGIME_STICKY_STORE=file``) shares state across
workers on the same host via ``.run/v6_regime_stickiness.json``.

Redis design (not required for local single-host): set
``V6_REGIME_STICKY_STORE=redis`` and ``V6_REGIME_STICKY_REDIS_URL``; the Redis
backend is stubbed until a redis client is installed — falls back to memory
with a warning. Keys: ``v6:regime_sticky:{sticky_key}`` TTL 7200s.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_FILE = _PROJECT_ROOT / ".run" / "v6_regime_stickiness.json"
_TTL_SEC = int(os.getenv("V6_REGIME_STICKY_TTL_SEC", "7200"))


@dataclass
class StickyRecord:
    locked_regime_id: str
    locked_sub_hint: str
    locked_label: str
    locked_at: float
    candidate_regime_id: str
    candidate_sub_hint: str
    candidate_label: str
    candidate_since: float
    locked_hard_block: bool = False
    locked_hard_block_reasons: tuple = ()
    locked_matched_gates: tuple = ()
    locked_sub_id: str = "01"
    locked_micro_id: str = "001"
    locked_behavior_id: str = "STD"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["locked_hard_block_reasons"] = list(self.locked_hard_block_reasons or ())
        d["locked_matched_gates"] = list(self.locked_matched_gates or ())
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "StickyRecord":
        return cls(
            locked_regime_id=str(raw.get("locked_regime_id") or "R3"),
            locked_sub_hint=str(raw.get("locked_sub_hint") or ""),
            locked_label=str(raw.get("locked_label") or ""),
            locked_at=float(raw.get("locked_at") or 0),
            candidate_regime_id=str(raw.get("candidate_regime_id") or "R3"),
            candidate_sub_hint=str(raw.get("candidate_sub_hint") or ""),
            candidate_label=str(raw.get("candidate_label") or ""),
            candidate_since=float(raw.get("candidate_since") or 0),
            locked_hard_block=bool(raw.get("locked_hard_block")),
            locked_hard_block_reasons=tuple(raw.get("locked_hard_block_reasons") or ()),
            locked_matched_gates=tuple(raw.get("locked_matched_gates") or ()),
            locked_sub_id=str(raw.get("locked_sub_id") or "01"),
            locked_micro_id=str(raw.get("locked_micro_id") or "001"),
            locked_behavior_id=str(raw.get("locked_behavior_id") or "STD"),
        )


class StickyStore(Protocol):
    def get(self, key: str) -> Optional[StickyRecord]: ...
    def set(self, key: str, record: StickyRecord) -> None: ...
    def clear(self) -> None: ...
    def backend_name(self) -> str: ...


class MemoryStickyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, StickyRecord] = {}

    def get(self, key: str) -> Optional[StickyRecord]:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, record: StickyRecord) -> None:
        with self._lock:
            self._data[key] = record
            if len(self._data) > 256:
                oldest = sorted(self._data.items(), key=lambda kv: kv[1].locked_at)[:16]
                for k, _ in oldest:
                    self._data.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def backend_name(self) -> str:
        return "memory"


class FileStickyStore:
    """Cross-process JSON store for same-host multi-worker PA stickiness."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or os.getenv("V6_REGIME_STICKY_FILE", str(_DEFAULT_FILE)))
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: Dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".stickytmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, key: str) -> Optional[StickyRecord]:
        with self._lock:
            data = self._load()
            raw = data.get(key)
            if not isinstance(raw, dict):
                return None
            rec = StickyRecord.from_dict(raw)
            if time.time() - float(rec.locked_at or 0) > _TTL_SEC:
                data.pop(key, None)
                self._save(data)
                return None
            return rec

    def set(self, key: str, record: StickyRecord) -> None:
        with self._lock:
            data = self._load()
            data[key] = record.to_dict()
            # Drop expired
            now = time.time()
            for k in list(data.keys()):
                try:
                    if now - float(data[k].get("locked_at") or 0) > _TTL_SEC:
                        data.pop(k, None)
                except Exception:
                    data.pop(k, None)
            self._save(data)

    def clear(self) -> None:
        with self._lock:
            self._save({})

    def backend_name(self) -> str:
        return "file"


class RedisStickyStore:
    """Optional Redis backend; falls back to memory if redis unavailable."""

    def __init__(self) -> None:
        self._mem = MemoryStickyStore()
        self._client = None
        url = os.getenv("V6_REGIME_STICKY_REDIS_URL", "").strip()
        if not url:
            logger.warning("V6_REGIME_STICKY_STORE=redis but REDIS URL missing; using memory")
            return
        try:
            import redis  # type: ignore

            self._client = redis.Redis.from_url(url, decode_responses=True)
            self._client.ping()
        except Exception as ex:
            logger.warning("V6 Redis sticky unavailable (%s); using memory", ex)
            self._client = None

    def _rkey(self, key: str) -> str:
        return f"v6:regime_sticky:{key}"

    def get(self, key: str) -> Optional[StickyRecord]:
        if self._client is None:
            return self._mem.get(key)
        try:
            raw = self._client.get(self._rkey(key))
            if not raw:
                return None
            return StickyRecord.from_dict(json.loads(raw))
        except Exception as ex:
            logger.debug("redis sticky get failed: %s", ex)
            return self._mem.get(key)

    def set(self, key: str, record: StickyRecord) -> None:
        if self._client is None:
            self._mem.set(key, record)
            return
        try:
            self._client.setex(self._rkey(key), _TTL_SEC, json.dumps(record.to_dict()))
            self._mem.set(key, record)
        except Exception as ex:
            logger.debug("redis sticky set failed: %s", ex)
            self._mem.set(key, record)

    def clear(self) -> None:
        self._mem.clear()
        if self._client is None:
            return
        try:
            for k in self._client.scan_iter(match="v6:regime_sticky:*", count=100):
                self._client.delete(k)
        except Exception:
            pass

    def backend_name(self) -> str:
        return "redis" if self._client is not None else "memory_fallback"


_STORE: Optional[StickyStore] = None
_STORE_LOCK = threading.Lock()


def get_sticky_store() -> StickyStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        mode = (os.getenv("V6_REGIME_STICKY_STORE") or "memory").strip().lower()
        if mode == "file":
            _STORE = FileStickyStore()
        elif mode == "redis":
            _STORE = RedisStickyStore()
        else:
            _STORE = MemoryStickyStore()
        logger.info("V6 regime sticky store backend=%s", _STORE.backend_name())
        return _STORE


def reset_sticky_store_for_tests() -> None:
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            try:
                _STORE.clear()
            except Exception:
                pass
        _STORE = MemoryStickyStore()
