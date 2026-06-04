"""Small shared services for the bots_engine API module."""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def detail_err(code: str, message: str, request_id: str) -> dict:
    error_id = str(uuid.uuid4())[:16]
    logger.warning(
        "API_ERR error_code=%s error_id=%s request_id=%s msg=%s",
        code,
        error_id,
        request_id,
        message,
    )
    return {"error_code": code, "message": message, "request_id": request_id, "error_id": error_id}
