"""
Risk & guardrails: trade lock, max notional, min notional, duplicate prevention.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Per-bot lock: same bot cannot send two orders concurrently.
_bot_locks: Dict[int, asyncio.Lock] = {}
_lock_mu = asyncio.Lock()


async def acquire_bot_lock(bot_id: int) -> asyncio.Lock:
    async with _lock_mu:
        if bot_id not in _bot_locks:
            _bot_locks[bot_id] = asyncio.Lock()
        return _bot_locks[bot_id]


# Idempotency: (bot_id, action_key) -> last use ts. Skip if same key used recently.
_action_keys: Dict[Tuple[int, str], float] = {}
_ACTION_KEY_TTL = 5.0  # seconds
_ACTION_KEY_TTL_INITIAL_ALLOC = 2.0  # seconds; allow retry every 2s until success (avoid double-place within 2s)


def check_idempotency(bot_id: int, action_key: str, ttl_override: Optional[float] = None) -> bool:
    """True if we should skip (duplicate)."""
    is_initial = action_key == "initial_allocation_0" or (isinstance(action_key, str) and action_key.startswith("initial_allocation_"))
    ttl = _ACTION_KEY_TTL_INITIAL_ALLOC if is_initial else (ttl_override or _ACTION_KEY_TTL)
    k = (bot_id, action_key)
    now = time.time()
    if k in _action_keys and (now - _action_keys[k]) < ttl:
        return True
    _action_keys[k] = now
    # Prune old keys
    prune_ttl = max(ttl * 2, _ACTION_KEY_TTL * 2)
    to_del = [k2 for k2, t in _action_keys.items() if now - t > prune_ttl]
    for k2 in to_del:
        _action_keys.pop(k2, None)
    return False


def guard_min_notional(notional_usd: float, min_notional: float) -> bool:
    """True if order is allowed."""
    return notional_usd >= min_notional


def guard_max_orders_per_minute(count: int, limit: int) -> bool:
    return count <= limit
