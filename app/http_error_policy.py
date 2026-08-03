"""Classification policy for errors shown in the admin operational error feed."""

from typing import Any


ACTIONABLE_HTTP_ERROR_CODES = {
    "CONVERT_FAILED",
    "BINANCE_AUTH",
    "BINANCE_RATE_LIMIT",
    "BINANCE_UPSTREAM_ERROR",
    "WORKER_ONLY_OPERATION",
}


def http_detail_error_code(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("error_code") or "").strip().upper()
    return ""


def should_persist_http_exception(status: int, detail: Any) -> bool:
    """Keep operational failures; discard normal validation/auth/not-found outcomes."""
    if status >= 500 or status == 429:
        return True
    return http_detail_error_code(detail) in ACTIONABLE_HTTP_ERROR_CODES
