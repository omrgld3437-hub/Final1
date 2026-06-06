"""
Bot Engine v5 – User Data Stream (optional).
ListenKey WS: executionReport for fills/balances. Reduces REST polling for 300 bots.
TODO: Full implementation when Binance user stream is enabled in deployment.
Impact: Without this, reconcile loop (REST openOrders/allOrders) is used; weight-governed and bounded.
Mitigation: Reconcile every 30–60s per account; weight budget allows it within limit.
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


async def start_user_stream_for_account(
    account_id: int,
    on_execution_report: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> bool:
    """
    Start listenKey stream for account. On executionReport, call on_execution_report(payload).
    Returns True if started, False if not supported or error.
    TODO: Implement GET /api/v3/userDataStream (keepalive), WS wss://stream.binance.com:9443/ws/<listenKey>
    """
    logger.info("USER_STREAM_TODO account_id=%s (not implemented; using REST reconcile)", account_id)
    return False


async def stop_user_stream_for_account(account_id: int) -> None:
    """Close listenKey stream for account."""
    pass
