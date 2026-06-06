"""
Bot Engine v5 – Typed errors and retry taxonomy.
Every error includes: error_code, error_id, request_id, context.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# Error codes (retry taxonomy)
VALIDATION_ERROR = "validation_error"
AUTH_ERROR = "auth_error"
DEPENDENCY_FAILURE = "dependency_failure"
RATE_LIMITED = "rate_limited"
TIMEOUT = "timeout"
LOCK_CONFLICT = "lock_conflict"
DATA_STALE = "data_stale"
STATE_CORRUPTION = "state_corruption"
INSUFFICIENT_BALANCE = "insufficient_balance"
ORDER_REJECTED = "order_rejected"
WEIGHT_DENIED = "weight_denied"
KILL_SWITCH = "kill_switch"
CIRCUIT_OPEN = "circuit_open"


# Retry policy: never | backoff | reconcile_only | circuit_breaker
RETRY_NEVER = "never"
RETRY_BACKOFF = "backoff"
RETRY_RECONCILE = "reconcile_only"
RETRY_CIRCUIT = "circuit_breaker"

RETRY_POLICY = {
    VALIDATION_ERROR: RETRY_NEVER,
    AUTH_ERROR: RETRY_NEVER,
    DEPENDENCY_FAILURE: RETRY_CIRCUIT,
    RATE_LIMITED: RETRY_BACKOFF,
    TIMEOUT: RETRY_RECONCILE,
    LOCK_CONFLICT: RETRY_BACKOFF,
    DATA_STALE: RETRY_NEVER,
    STATE_CORRUPTION: RETRY_NEVER,
    INSUFFICIENT_BALANCE: RETRY_NEVER,
    ORDER_REJECTED: RETRY_NEVER,
    WEIGHT_DENIED: RETRY_BACKOFF,
    KILL_SWITCH: RETRY_NEVER,
    CIRCUIT_OPEN: RETRY_CIRCUIT,
}


@dataclass
class BotEngineError(Exception):
    """Base typed error for bot engine."""

    error_code: str
    message: str
    error_id: Optional[str] = None
    request_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.error_id is None:
            self.error_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_id": self.error_id,
            "request_id": self.request_id,
            "message": self.message,
            "context": self.context,
        }

    @property
    def retry_policy(self) -> str:
        return RETRY_POLICY.get(self.error_code, RETRY_NEVER)


class ValidationError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(VALIDATION_ERROR, message, **kwargs)


class AuthError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(AUTH_ERROR, message, **kwargs)


class DependencyFailureError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(DEPENDENCY_FAILURE, message, **kwargs)


class RateLimitedError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(RATE_LIMITED, message, **kwargs)


class TimeoutError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(TIMEOUT, message, **kwargs)


class LockConflictError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(LOCK_CONFLICT, message, **kwargs)


class DataStaleError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(DATA_STALE, message, **kwargs)


class StateCorruptionError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(STATE_CORRUPTION, message, **kwargs)


class WeightDeniedError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(WEIGHT_DENIED, message, **kwargs)


class KillSwitchError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(KILL_SWITCH, message, **kwargs)


class CircuitOpenError(BotEngineError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(CIRCUIT_OPEN, message, **kwargs)
