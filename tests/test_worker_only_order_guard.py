"""
Patch B: Worker-only order placement. When DATABASE_ROLE is web/api, place_order must raise
standardized error (WORKER_ONLY_OPERATION) and never call Binance.
"""

import os
import pytest


def test_worker_role_detection(monkeypatch):
    """When DATABASE_ROLE=web or PROCESS_ROLE=api, is_worker_role() is False."""
    monkeypatch.setenv("DATABASE_ROLE", "web")
    monkeypatch.delenv("PROCESS_ROLE", raising=False)
    import importlib
    import app.core.config as config_mod

    importlib.reload(config_mod)
    assert config_mod.is_worker_role() is False

    monkeypatch.setenv("DATABASE_ROLE", "worker")
    importlib.reload(config_mod)
    assert config_mod.is_worker_role() is True


@pytest.mark.asyncio
async def test_place_order_raises_when_web_role(monkeypatch):
    """Simulate DATABASE_ROLE=web -> place_order raises AppError with WORKER_ONLY_OPERATION."""
    monkeypatch.setenv("DATABASE_ROLE", "web")
    monkeypatch.setenv("PROCESS_ROLE", "api")
    import importlib
    import app.core.config as config_mod

    importlib.reload(config_mod)
    from app.core.errors import AppError
    from app.services.binance_spot import place_order

    class FakeKeys:
        pass

    with pytest.raises(AppError) as exc_info:
        await place_order(
            FakeKeys(),
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": "10",
            },
        )

    assert exc_info.value.error_code == "WORKER_ONLY_OPERATION"
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_id is not None


def test_app_error_has_required_fields():
    """AppError must include error_code, error_id, request_id in to_dict()."""
    from app.core.errors import AppError

    e = AppError("WORKER_ONLY_OPERATION", "msg", request_id="req-1")
    d = e.to_dict()
    assert d.get("ok") is False
    err = d.get("error", {})
    assert err.get("error_code") == "WORKER_ONLY_OPERATION"
    assert err.get("error_id") is not None
    assert err.get("request_id") == "req-1"
    assert err.get("message") == "msg"
