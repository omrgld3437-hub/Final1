"""
FILE: binance_ws.py
Binance WebSocket combined stream (!miniTicker@arr) -> DataHub prices/mini.
Reconnect + exponential backoff + jitter; ping/heartbeat; clean shutdown.
"""

from __future__ import annotations
import asyncio
import json
import logging
import random
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# DNS/network unreachable: log once per interval to avoid flood when offline
_LAST_DNS_ERROR_LOG: float = 0.0
_DNS_ERROR_LOG_INTERVAL: float = 300.0  # seconds
# Handshake timeout: log WARNING at most once per interval (avoid flood when Binance/firewall slow)
_LAST_HANDSHAKE_TIMEOUT_LOG: float = 0.0
_HANDSHAKE_TIMEOUT_LOG_INTERVAL: float = 300.0  # seconds


def _is_dns_or_network_error(exc: BaseException) -> bool:
    """True if error is DNS resolution or network unreachable (e.g. offline)."""
    msg = str(exc).lower()
    if (
        "nodename nor servname" in msg
        or "errno 8" in msg
        or "name or service not known" in msg
    ):
        return True
    errno = getattr(exc, "errno", None)
    if errno is not None and errno in (8, -2):  # EAI_NONAME, EAI_NODATA
        return True
    return False


def _is_handshake_timeout(exc: BaseException) -> bool:
    """True if error is WebSocket opening handshake timeout (transient; throttle WARNING)."""
    return "timed out during opening handshake" in str(exc).lower()


# Combined stream: all symbols mini ticker (array)
BINANCE_WS_LIVE = "wss://stream.binance.com:9443/stream?streams=!miniTicker@arr"
BINANCE_WS_TESTNET = "wss://testnet.binance.vision/stream?streams=!miniTicker@arr"

RECONNECT_INITIAL = 1.0
RECONNECT_MAX = 60.0
RECONNECT_JITTER = 0.3
PING_INTERVAL = 30.0
# Binance bazen pong'u geciktirebiliyor; 10s yerine 20s ile ping timeout azalır
PING_TIMEOUT = 20.0
# Ağ yavaşken handshake 10s'de yetmeyebilir; 20s ile tekrar denemeden önce daha fazla süre ver
OPEN_HANDSHAKE_TIMEOUT = 20.0


def _ws_url(testnet: bool) -> str:
    return BINANCE_WS_TESTNET if testnet else BINANCE_WS_LIVE


class BinanceWSClient:
    """WebSocket client for Binance combined stream. Pushes to DataHub via on_message callback."""

    def __init__(
        self,
        on_message: Callable[[Dict[str, Any]], None],
        testnet: bool = False,
    ):
        self.on_message = on_message
        self.testnet = testnet
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._reconnect_delay = RECONNECT_INITIAL

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
            logger.info("[BinanceWS] Started (testnet=%s)", self.testnet)
        except RuntimeError:
            logger.warning("[BinanceWS] No event loop; start from async context")

    def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("[BinanceWS] Stopped")

    async def _run(self) -> None:
        global _LAST_DNS_ERROR_LOG, _LAST_HANDSHAKE_TIMEOUT_LOG
        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if (
                    "keepalive ping timeout" in str(e).lower()
                    or "no close frame" in str(e).lower()
                ):
                    logger.debug("[BinanceWS] Run error (reconnecting): %s", e)
                elif _is_handshake_timeout(e):
                    now = time.monotonic()
                    if (
                        now - _LAST_HANDSHAKE_TIMEOUT_LOG
                        >= _HANDSHAKE_TIMEOUT_LOG_INTERVAL
                    ):
                        _LAST_HANDSHAKE_TIMEOUT_LOG = now
                        logger.warning(
                            "[BinanceWS] Açılış el sıkışması zaman aşımı (ağ/firewall yavaş olabilir). %.0f sn sonra tekrar denenecek.",
                            _HANDSHAKE_TIMEOUT_LOG_INTERVAL,
                        )
                    else:
                        logger.debug("[BinanceWS] Run error (handshake timeout): %s", e)
                elif _is_dns_or_network_error(e):
                    now = time.monotonic()
                    if now - _LAST_DNS_ERROR_LOG >= _DNS_ERROR_LOG_INTERVAL:
                        _LAST_DNS_ERROR_LOG = now
                        logger.warning(
                            "[BinanceWS] Ağ/DNS erişilemiyor (Binance çözülemiyor). İnternet bağlantısını kontrol edin; %.0f sn sonra tekrar denenecek.",
                            _DNS_ERROR_LOG_INTERVAL,
                        )
                else:
                    logger.warning("[BinanceWS] Run error: %s", e)
            if self._stop.is_set():
                break
            delay = self._reconnect_delay + random.uniform(
                0, RECONNECT_JITTER * self._reconnect_delay
            )
            self._reconnect_delay = min(RECONNECT_MAX, self._reconnect_delay * 2)
            logger.info("[BinanceWS] Reconnecting in %.1fs", delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _connect_and_listen(self) -> None:
        import websockets

        url = _ws_url(self.testnet)
        self._reconnect_delay = RECONNECT_INITIAL
        async with websockets.connect(
            url,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
            close_timeout=5,
            open_timeout=OPEN_HANDSHAKE_TIMEOUT,
        ) as ws:
            logger.info("[BinanceWS] Connected to %s", url)
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=PING_INTERVAL + 5)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed as e:
                    reason = str(e)
                    is_ping_timeout = "keepalive ping timeout" in reason.lower()
                    if is_ping_timeout:
                        logger.debug(
                            "[BinanceWS] Connection closed (ping timeout): %s", e
                        )
                    else:
                        logger.info("[BinanceWS] Connection closed: %s", e)
                    if not is_ping_timeout:
                        try:
                            from app.error_logging import log_error_fire_and_forget

                            msg = "Binance WebSocket bağlantı koptu"
                            if "no close frame" in reason.lower():
                                msg = "Binance WebSocket beklenmedik kapanma (close frame yok); yeniden bağlanılıyor."
                            log_error_fire_and_forget(
                                "binance_ws",
                                msg,
                                detail=reason,
                                context={
                                    "reason": reason,
                                    "url": url,
                                    "stream": "!miniTicker@arr",
                                },
                            )
                        except Exception:
                            pass
                    raise
                self._on_raw(raw)

    def _on_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.debug("[BinanceWS] Parse error: %s", e)
            return
        try:
            if isinstance(data, dict) and "data" in data:
                # Combined stream: { "stream": "!miniTicker@arr", "data": [ {...}, ... ] }
                arr = data.get("data")
                if isinstance(arr, list):
                    self.on_message({"miniTicker": arr})
                    return
            if isinstance(data, list):
                self.on_message({"miniTicker": data})
                return
        except Exception as e:
            logger.debug("[BinanceWS] on_message error: %s", e)
