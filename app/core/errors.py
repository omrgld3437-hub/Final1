"""
Standardized API errors: error_code, error_id, request_id, message_safe (no raw stacktraces to client).
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional


class AppError(Exception):
    """Structured error for API responses. Always includes error_code, error_id, request_id."""

    def __init__(
        self,
        error_code: str,
        message: str,
        request_id: Optional[str] = None,
        error_id: Optional[str] = None,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message_safe = message
        self.request_id = request_id
        self.error_id = error_id or str(uuid.uuid4())
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Response body for JSON error."""
        return {
            "ok": False,
            "error": {
                "error_code": self.error_code,
                "error_id": self.error_id,
                "request_id": self.request_id,
                "message": self.message_safe,
                **({} if not self.details else {"details": self.details}),
            },
        }
