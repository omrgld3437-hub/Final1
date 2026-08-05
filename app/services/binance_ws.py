"""
FILE: binance_ws.py
Binance WebSocket combined stream (!miniTicker@arr) -> DataHub prices/mini.
Reconnect + exponential backoff + jitter; ping/heartbeat; clean shutdown.
"""

from __future__ import annotations
import asyncio
import inspect
import json
import logging
import os
import random
from pathlib import Path
import shutil
import ssl
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Node bridge emits one JSON line per WS frame. !miniTicker@arr payloads often
# exceed asyncio.StreamReader's default 64KiB readline limit.
NODE_BRIDGE_LINE_LIMIT = 16 * 1024 * 1024

# DNS/network unreachable: log once per interval to avoid flood when offline
_LAST_DNS_ERROR_LOG: float = 0.0
_DNS_ERROR_LOG_INTERVAL: float = 300.0  # seconds
# Handshake timeout: log WARNING at most once per interval (avoid flood when Binance/firewall slow)
_LAST_HANDSHAKE_TIMEOUT_LOG: float = 0.0
_HANDSHAKE_TIMEOUT_LOG_INTERVAL: float = 300.0  # seconds
# TLS/proxy protocol mismatch: log once per interval to avoid flood when a proxy
# or blocked 9443 endpoint returns non-TLS bytes to the TLS client.
_LAST_TLS_PROTOCOL_ERROR_LOG: float = 0.0
_TLS_PROTOCOL_ERROR_LOG_INTERVAL: float = 300.0  # seconds


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


def _is_ssl_wrong_version(exc: BaseException) -> bool:
    """True if TLS saw plain HTTP/proxy bytes or an incompatible protocol."""
    msg = str(exc).lower()
    return isinstance(exc, ssl.SSLError) and (
        "wrong_version_number" in msg or "wrong version number" in msg
    )


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _ws_proxy_arg() -> object:
    """Public price stream defaults to direct connection; opt in to proxy if needed."""
    explicit = (os.getenv("BINANCE_WS_PROXY") or "").strip()
    if explicit:
        return explicit
    return True if _env_flag("BINANCE_WS_USE_PROXY", False) else None


# Combined stream: all symbols mini ticker (array)
BINANCE_WS_LIVE = "wss://stream.binance.com/stream?streams=!miniTicker@arr"
BINANCE_WS_LIVE_9443 = "wss://stream.binance.com:9443/stream?streams=!miniTicker@arr"
BINANCE_WS_TESTNET = "wss://testnet.binance.vision/stream?streams=!miniTicker@arr"

RECONNECT_INITIAL = 1.0
RECONNECT_MAX = 60.0
RECONNECT_JITTER = 0.3
PING_INTERVAL = 30.0
# Binance bazen pong'u geciktirebiliyor; 10s yerine 20s ile ping timeout azalır
PING_TIMEOUT = 20.0
# Ağ yavaşken handshake 10s'de yetmeyebilir; 20s ile tekrar denemeden önce daha fazla süre ver
OPEN_HANDSHAKE_TIMEOUT = 20.0
MAX_CONSECUTIVE_FAILURES = int(
    os.getenv("BINANCE_WS_MAX_CONSECUTIVE_FAILURES", "8") or 8
)


def _ws_urls(testnet: bool) -> Tuple[str, ...]:
    if testnet:
        return (BINANCE_WS_TESTNET,)
    return (BINANCE_WS_LIVE, BINANCE_WS_LIVE_9443)


def _ws_url(testnet: bool) -> str:
    return _ws_urls(testnet)[0]


def _node_ws_enabled() -> bool:
    return _env_flag("BINANCE_WS_NODE_BRIDGE", True)


def node_ws_available() -> bool:
    return bool(shutil.which("node") and _node_ws_script_path().exists())


def _node_ws_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "binance_ws_stream_node.js"


async def _readline_limited(
    stream: asyncio.StreamReader,
    buf: bytearray,
    *,
    limit: int = NODE_BRIDGE_LINE_LIMIT,
    chunk_size: int = 65536,
) -> bytes:
    """Read one newline-delimited line without relying on StreamReader.readline() 64KiB cap."""
    while True:
        nl = buf.find(b"\n")
        if nl >= 0:
            line = bytes(buf[: nl + 1])
            del buf[: nl + 1]
            return line
        if len(buf) >= limit:
            raise RuntimeError(
                f"Node WebSocket bridge line exceeds limit ({limit} bytes)"
            )
        chunk = await stream.read(chunk_size)
        if not chunk:
            if not buf:
                return b""
            line = bytes(buf)
            buf.clear()
            return line
        buf.extend(chunk)


def _dispatch_raw_message(
    on_message: Callable[[Dict[str, Any]], None], raw: str, source: str
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.debug("[%s] Parse error: %s", source, e)
        return
    try:
        if isinstance(data, dict) and "data" in data:
            # Combined stream: { "stream": "!miniTicker@arr", "data": [ {...}, ... ] }
            arr = data.get("data")
            if isinstance(arr, list):
                on_message({"miniTicker": arr})
                return
        if isinstance(data, list):
            on_message({"miniTicker": data})
            return
    except Exception as e:
        logger.debug("[%s] on_message error: %s", source, e)


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
        self._url_index = 0
        self._consecutive_failures = 0

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
        global _LAST_DNS_ERROR_LOG
        global _LAST_HANDSHAKE_TIMEOUT_LOG
        global _LAST_TLS_PROTOCOL_ERROR_LOG
        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_failures += 1
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
                elif _is_ssl_wrong_version(e):
                    urls = _ws_urls(self.testnet)
                    if len(urls) > 1:
                        self._url_index = (self._url_index + 1) % len(urls)
                    now = time.monotonic()
                    if (
                        now - _LAST_TLS_PROTOCOL_ERROR_LOG
                        >= _TLS_PROTOCOL_ERROR_LOG_INTERVAL
                    ):
                        _LAST_TLS_PROTOCOL_ERROR_LOG = now
                        logger.warning(
                            "[BinanceWS] TLS/proxy protokol hatası: canlı fiyat "
                            "stream'i yanlış TLS yanıtı aldı. 443/9443 alternatif "
                            "endpoint ile tekrar denenecek; ortam proxy'si gerekiyorsa "
                            "BINANCE_WS_USE_PROXY=1 veya BINANCE_WS_PROXY ayarlayın. "
                            "Detail: %s",
                            e,
                        )
                    else:
                        logger.debug("[BinanceWS] Run error (TLS/proxy): %s", e)
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
            if (
                MAX_CONSECUTIVE_FAILURES > 0
                and self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES
            ):
                logger.warning(
                    "[BinanceWS] %s ardışık bağlantı denemesi başarısız oldu; REST fallback sağlıklı olduğu için WS yeniden deneme döngüsü durduruldu.",
                    self._consecutive_failures,
                )
                self._stop.set()
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

        urls = _ws_urls(self.testnet)
        url = urls[self._url_index % len(urls)]
        self._reconnect_delay = RECONNECT_INITIAL
        connect_kwargs = {
            "ping_interval": PING_INTERVAL,
            "ping_timeout": PING_TIMEOUT,
            "close_timeout": 5,
            "open_timeout": OPEN_HANDSHAKE_TIMEOUT,
        }
        if "proxy" in inspect.signature(websockets.connect).parameters:
            connect_kwargs["proxy"] = _ws_proxy_arg()
        async with websockets.connect(
            url,
            **connect_kwargs,
        ) as ws:
            self._consecutive_failures = 0
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
        _dispatch_raw_message(self.on_message, raw, "BinanceWS")


class NodeBinanceWSClient:
    """Node WebSocket bridge for environments where Python TLS/proxy WS is incompatible."""

    def __init__(
        self,
        on_message: Callable[[Dict[str, Any]], None],
        testnet: bool = False,
    ):
        self.on_message = on_message
        self.testnet = testnet
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reconnect_delay = RECONNECT_INITIAL

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
            logger.info("[BinanceWS:Node] Started (testnet=%s)", self.testnet)
        except RuntimeError:
            logger.warning("[BinanceWS:Node] No event loop; start from async context")

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("[BinanceWS:Node] Stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[BinanceWS:Node] Run error: %s", e)
            if self._stop.is_set():
                break
            delay = self._reconnect_delay + random.uniform(
                0, RECONNECT_JITTER * self._reconnect_delay
            )
            self._reconnect_delay = min(RECONNECT_MAX, self._reconnect_delay * 2)
            logger.info("[BinanceWS:Node] Reconnecting in %.1fs", delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _connect_and_listen(self) -> None:
        node = shutil.which("node")
        script = _node_ws_script_path()
        if not node or not script.exists():
            raise RuntimeError("Node WebSocket bridge unavailable")
        url = _ws_url(self.testnet)
        proc = await asyncio.create_subprocess_exec(
            node,
            str(script),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        # create_subprocess_exec hardcodes StreamReader limit=64KiB; raise it so
        # large miniTicker@arr frames do not trip LimitOverrunError reconnects.
        if proc.stdout is not None:
            try:
                proc.stdout._limit = NODE_BRIDGE_LINE_LIMIT  # noqa: SLF001
            except Exception:
                pass
        stderr_task = asyncio.create_task(self._drain_stderr(proc))
        line_buf = bytearray()
        try:
            if proc.stdout is None:
                raise RuntimeError("Node WebSocket bridge stdout unavailable")
            while not self._stop.is_set():
                line = await _readline_limited(
                    proc.stdout, line_buf, limit=NODE_BRIDGE_LINE_LIMIT
                )
                if not line:
                    break
                try:
                    event = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    logger.debug("[BinanceWS:Node] invalid bridge line")
                    continue
                typ = event.get("type")
                if typ == "connected":
                    self._reconnect_delay = RECONNECT_INITIAL
                    logger.info("[BinanceWS:Node] Connected to %s", event.get("url") or url)
                elif typ == "message":
                    raw = event.get("data")
                    if isinstance(raw, str):
                        _dispatch_raw_message(self.on_message, raw, "BinanceWS:Node")
                elif typ == "error":
                    logger.warning("[BinanceWS:Node] Bridge error: %s", event.get("error"))
                elif typ == "closed":
                    raise RuntimeError(
                        "Node WebSocket closed code=%s reason=%s"
                        % (event.get("code"), event.get("reason") or "")
                    )
            rc = await proc.wait()
            if not self._stop.is_set():
                raise RuntimeError(f"Node WebSocket bridge exited rc={rc}")
        finally:
            stderr_task.cancel()
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
            self._proc = None

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        try:
            if proc.stderr is None:
                return
            while not self._stop.is_set():
                line = await proc.stderr.readline()
                if not line:
                    break
                msg = line.decode("utf-8", "replace").strip()
                if msg:
                    logger.debug("[BinanceWS:Node] stderr: %s", msg[:500])
        except asyncio.CancelledError:
            pass
