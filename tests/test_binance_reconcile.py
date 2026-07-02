"""
Unit tests for Binance reconcile semantics: code!=0 => error; -2013 / order does not exist => NOT_FOUND; valid order => FOUND.
"""

from app.services.binance_spot import (
    _is_order_not_found,
    _is_valid_order_response,
    BinanceSignedError,
)

import pytest


def test_is_order_not_found_minus_2013():
    """code -2013 => NOT_FOUND (proceed to place)."""
    assert _is_order_not_found(-2013, "Unknown order sent.") is True
    assert _is_order_not_found(-2013, "") is True


@pytest.mark.asyncio
async def test_get_wallet_timeout_consumes_late_inflight_exception(monkeypatch):
    """A timed-out shared account task must not leak asyncio 'never retrieved'."""
    import asyncio
    from app.services import binance_spot as spot

    class FakeKeys:
        testnet = False
        api_key = "k-test"
        _client = None

    contexts = []
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: contexts.append(ctx))

    async def slow_then_fail(_keys, _tag="wallet"):
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise RuntimeError("late connect failure")

    monkeypatch.setattr(spot, "BINANCE_REQUEST_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(spot, "_fetch_account_upstream", slow_then_fail)
    spot._account_cache.clear()
    spot._account_inflight.clear()

    try:
        with pytest.raises(spot.DependencyFailure):
            await spot.get_wallet(FakeKeys())
        await asyncio.sleep(0.08)
        assert spot._account_inflight == {}
        assert contexts == []
    finally:
        loop.set_exception_handler(old_handler)
        spot._account_cache.clear()
        spot._account_inflight.clear()


@pytest.mark.asyncio
async def test_signed_request_outer_cancel_consumes_late_exception(monkeypatch):
    """An outer cancel racing a late connect failure inside _signed_request must
    not leak asyncio 'Task exception was never retrieved'.

    Reproduces worker.log: Task-* coro=_signed_request_impl finishing with
    ConnectError/401 right as an outer awaiter (e.g. a timed-out get_wallet)
    cancels the request. wait_for's CancelledError branch would otherwise drop
    the inner task's exception unretrieved.
    """
    import asyncio
    from app.services import binance_spot as spot

    contexts = []
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: contexts.append(ctx))

    async def slow_then_fail(*_a, **_kw):
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise RuntimeError("late connect failure")

    monkeypatch.setattr(spot, "_signed_request_impl", slow_then_fail)
    # Generous inner timeout so the OUTER cancel below — not the inner wait_for —
    # is what races the late failure.
    monkeypatch.setattr(spot, "BINANCE_REQUEST_TIMEOUT_SEC", 5.0)

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                spot._signed_request(None, "GET", "/api/v3/account", object(), {}),
                timeout=0.01,
            )
        await asyncio.sleep(0.08)
        assert contexts == []
    finally:
        loop.set_exception_handler(old_handler)


def test_is_order_not_found_minus_1021():
    """code -1021 (timestamp) => NOT_FOUND so we don't treat as FOUND."""
    assert _is_order_not_found(-1021, "Timestamp outside recvWindow") is True


def test_is_order_not_found_msg_order_does_not_exist():
    """msg contains 'order does not exist' => NOT_FOUND."""
    assert _is_order_not_found(123, "Order does not exist.") is True
    assert _is_order_not_found(-999, "Error: order does not exist") is True


def test_is_order_not_found_other_codes():
    """Other codes => not NOT_FOUND (caller may raise)."""
    assert _is_order_not_found(0, "OK") is False
    assert _is_order_not_found(-2010, "Insufficient balance") is False
    assert _is_order_not_found(-1022, "Invalid signature") is False


def test_is_valid_order_response_valid():
    """Proper order JSON with orderId, status, symbol, clientOrderId => FOUND."""
    data = {
        "orderId": 12345678,
        "status": "FILLED",
        "symbol": "LTCUSDT",
        "clientOrderId": "b1r0c0iabc123",
        "executedQty": "0.5",
        "cummulativeQuoteQty": "50.0",
    }
    assert _is_valid_order_response(data, "LTCUSDT", "b1r0c0iabc123") is True
    assert _is_valid_order_response(data, "LTCUSDT", "b1r0c0iabc123") is True


def test_is_valid_order_response_uses_orig_client_order_id():
    """Match on origClientOrderId if clientOrderId not set."""
    data = {
        "orderId": 99,
        "status": "NEW",
        "symbol": "BTCUSDT",
        "origClientOrderId": "mycoid36chars",
    }
    assert _is_valid_order_response(data, "BTCUSDT", "mycoid36chars") is True


def test_is_valid_order_response_invalid_code_like_body():
    """Body with code!=0 is not passed to _is_valid_order_response (caller gets BinanceSignedError). We only validate successful JSON shape."""
    data = {"code": -2013, "msg": "Unknown order sent."}
    assert (
        _is_valid_order_response(data, "LTCUSDT", "any") is False
    )  # no orderId/status


def test_is_valid_order_response_no_order_id():
    """Missing or zero orderId => invalid (NOT_FOUND)."""
    assert _is_valid_order_response({}, "LTCUSDT", "coid") is False
    assert (
        _is_valid_order_response(
            {
                "orderId": 0,
                "status": "FILLED",
                "symbol": "LTCUSDT",
                "clientOrderId": "x",
            },
            "LTCUSDT",
            "x",
        )
        is False
    )
    assert (
        _is_valid_order_response(
            {
                "orderId": None,
                "status": "FILLED",
                "symbol": "LTCUSDT",
                "clientOrderId": "x",
            },
            "LTCUSDT",
            "x",
        )
        is False
    )


def test_is_valid_order_response_wrong_symbol():
    """Symbol mismatch => invalid."""
    data = {"orderId": 1, "status": "FILLED", "symbol": "BTCUSDT", "clientOrderId": "c"}
    assert _is_valid_order_response(data, "LTCUSDT", "c") is False


def test_is_valid_order_response_wrong_client_order_id():
    """clientOrderId mismatch => invalid."""
    data = {
        "orderId": 1,
        "status": "FILLED",
        "symbol": "LTCUSDT",
        "clientOrderId": "other",
    }
    assert _is_valid_order_response(data, "LTCUSDT", "expected_coid") is False


def test_is_valid_order_response_invalid_status():
    """Status not in allowed set => invalid."""
    data = {
        "orderId": 1,
        "status": "PENDING",
        "symbol": "LTCUSDT",
        "clientOrderId": "c",
    }
    assert _is_valid_order_response(data, "LTCUSDT", "c") is False


def test_binance_signed_error_attributes():
    """BinanceSignedError has code, msg, data for caller to handle -2013."""
    e = BinanceSignedError(
        -2013, "Unknown order sent.", {"code": -2013, "msg": "Unknown order sent."}
    )
    assert e.code == -2013
    assert "Unknown" in e.msg
    assert e.data.get("code") == -2013
