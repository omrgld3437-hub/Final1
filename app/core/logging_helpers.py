"""
Wallet trace logging for debugging UI/backend wallet data flow.
Logs JSON-friendly events at every wallet boundary.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("wallet_trace")


def log_wallet_trace(
    event: str,
    request_id: str = "",
    account_id: Optional[int] = None,
    source: str = "",
    keys_configured: Optional[bool] = None,
    asset_count: Optional[int] = None,
    total_usd: Optional[float] = None,
    free_usd: Optional[float] = None,
    locked_usd: Optional[float] = None,
    error_code: Optional[str] = None,
    error_detail: Optional[str] = None,
    cache_hit: Optional[bool] = None,
    upstream_call: Optional[bool] = None,
    age_sec: Optional[float] = None,
    duration_ms: Optional[float] = None,
    **extra: Any,
) -> None:
    """Structured wallet trace log for diagnosing UI/backend wallet flow."""
    payload: dict[str, Any] = {
        "event": event,
        "request_id": request_id,
        "account_id": account_id,
        "source": source,
    }
    if keys_configured is not None:
        payload["keys_configured"] = keys_configured
    if asset_count is not None:
        payload["asset_count"] = asset_count
    if total_usd is not None:
        payload["total_usd"] = total_usd
        payload["total_usd_type"] = type(total_usd).__name__
    if free_usd is not None:
        payload["free_usd"] = free_usd
    if locked_usd is not None:
        payload["locked_usd"] = locked_usd
    if error_code:
        payload["error_code"] = error_code
    if error_detail:
        payload["error_detail"] = error_detail
    if cache_hit is not None:
        payload["cache_hit"] = cache_hit
    if upstream_call is not None:
        payload["upstream_call"] = upstream_call
    if age_sec is not None:
        payload["age_sec"] = round(age_sec, 2)
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    payload.update(extra)
    # Wallet payload traces are high-volume during dashboard polling. Keep
    # successful boundary traces at DEBUG; promote only error traces to INFO.
    if event == "wallet_payload_out" and not payload.get("error_code"):
        logger.debug("wallet_trace %s", payload)
    else:
        logger.info("wallet_trace %s", payload)
