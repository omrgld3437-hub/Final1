import asyncio
import ssl

from app.services import binance_ws


def test_live_public_stream_prefers_443_with_9443_fallback():
    urls = binance_ws._ws_urls(testnet=False)

    assert urls[0] == "wss://stream.binance.com/stream?streams=!miniTicker@arr"
    assert "wss://stream.binance.com:9443/stream?streams=!miniTicker@arr" in urls


def test_testnet_public_stream_has_single_url():
    assert binance_ws._ws_urls(testnet=True) == (
        "wss://testnet.binance.vision/stream?streams=!miniTicker@arr",
    )


def test_ssl_wrong_version_is_detected():
    err = ssl.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number")

    assert binance_ws._is_ssl_wrong_version(err)


def test_public_ws_proxy_is_direct_by_default(monkeypatch):
    monkeypatch.delenv("BINANCE_WS_PROXY", raising=False)
    monkeypatch.delenv("BINANCE_WS_USE_PROXY", raising=False)

    assert binance_ws._ws_proxy_arg() is None


def test_public_ws_proxy_can_be_enabled(monkeypatch):
    monkeypatch.delenv("BINANCE_WS_PROXY", raising=False)
    monkeypatch.setenv("BINANCE_WS_USE_PROXY", "1")

    assert binance_ws._ws_proxy_arg() is True


def test_public_ws_explicit_proxy_wins(monkeypatch):
    monkeypatch.setenv("BINANCE_WS_PROXY", "http://127.0.0.1:8080")
    monkeypatch.setenv("BINANCE_WS_USE_PROXY", "0")

    assert binance_ws._ws_proxy_arg() == "http://127.0.0.1:8080"


def test_node_bridge_readline_accepts_large_lines():
    """miniTicker@arr wrapped JSON exceeds asyncio's default 64KiB readline limit."""

    async def _run() -> bytes:
        reader = asyncio.StreamReader(limit=64 * 1024)
        payload = b'{"type":"message","data":"' + (b"x" * (100 * 1024)) + b'"}\n'
        reader.feed_data(payload)
        reader.feed_eof()
        buf = bytearray()
        return await binance_ws._readline_limited(
            reader, buf, limit=binance_ws.NODE_BRIDGE_LINE_LIMIT
        )

    line = asyncio.run(_run())
    assert line.endswith(b"}\n")
    assert len(line) > 64 * 1024
