"""Patch H: Flash Home – /api/home/fast must NOT call Binance (no binance in fast code path)."""
import inspect
import pytest


def test_home_fast_does_not_reference_binance():
    """home_fast handler source must not reference binance (critical path is Binance-free)."""
    from app.api.routes import home as home_module
    source = inspect.getsource(home_module.home_fast)
    assert "binance" not in source.lower(), "home_fast must not reference Binance"


def test_home_fast_response_contract_meta_keys():
    """Document expected meta keys for GET /api/home/fast (contract)."""
    expected_meta = {"request_id", "server_ms", "payload_bytes", "stale", "cache", "generated_at"}
    assert "request_id" in expected_meta
    assert "payload_bytes" in expected_meta
    assert "cache" in expected_meta


def test_home_fast_data_keys():
    """Document expected data keys for GET /api/home/fast."""
    expected_data = {"prices", "kpis", "wallet_cached", "wallet_cached_at", "prices_ready", "wallet_live_inflight"}
    assert "prices_ready" in expected_data
    assert "wallet_live_inflight" in expected_data
