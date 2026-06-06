"""
Core module: constants, config, errors.
Single source of truth for lock TTL, snapshot caps, and standardized errors.
"""
from app.core.constants import (
    DEFAULT_LEASE_TTL_SEC,
    LOCK_HEARTBEAT_SEC,
    LOCK_BLOCKING_TIMEOUT_SEC,
)
from app.core.config import get_config

__all__ = [
    "DEFAULT_LEASE_TTL_SEC",
    "LOCK_HEARTBEAT_SEC",
    "LOCK_BLOCKING_TIMEOUT_SEC",
    "get_config",
]
