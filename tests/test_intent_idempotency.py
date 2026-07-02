"""
Unit tests for order intent idempotency.
"""

from app.botengine.intent_ledger import (
    build_intent_id,
    build_client_order_id,
    _intent_hash,
)


def test_intent_hash_deterministic():
    """Identical intent params produce same hash."""
    h1 = _intent_hash("BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0)
    h2 = _intent_hash("BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0)
    assert h1 == h2
    assert len(h1) == 16


def test_intent_hash_different_intents():
    """Different params produce different hash."""
    h1 = _intent_hash("BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0)
    h2 = _intent_hash("BTCUSDT", "SELL", 0.001, 50.0, "trail_sell_grid", 0)
    assert h1 != h2


def test_build_intent_id_deterministic():
    """Same params -> same intent_id (no epoch)."""
    i1 = build_intent_id(1, 1, "BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0)
    i2 = build_intent_id(1, 1, "BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0)
    assert i1 == i2
    assert "bot1_cy1_it" in i1


def test_build_client_order_id_format():
    """client_order_id format and max 36 chars."""
    coid = build_client_order_id(
        1, 1, "BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0
    )
    assert len(coid) <= 36
    assert "b1c1i" in coid


def test_build_client_order_id_same_intent_same_hash_part():
    """Same intent params -> same hash part in client_order_id (epoch differs)."""
    coid1 = build_client_order_id(
        1, 1, "BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0, epoch_ms=1000
    )
    coid2 = build_client_order_id(
        1, 1, "BTCUSDT", "BUY", 0.001, 50.0, "trail_buy_grid", 0, epoch_ms=1000
    )
    assert coid1 == coid2


def test_build_intent_id_includes_run_id():
    """Different run_id => different intent_id (no restart collision)."""
    i0 = build_intent_id(
        1, 0, "LTCUSDT", "BUY", 0.1, 1400.0, "initial_allocation", None, run_id="cmd101"
    )
    i1 = build_intent_id(
        1, 0, "LTCUSDT", "BUY", 0.1, 1400.0, "initial_allocation", None, run_id="cmd102"
    )
    assert i0 != i1
    assert "r" in i0 and "cmd101" in i0
    assert "r" in i1 and "cmd102" in i1


def test_build_client_order_id_includes_run_id_max_36():
    """run_id included; total length <= 36 (Binance limit)."""
    coid = build_client_order_id(
        1, 0, "LTCUSDT", "BUY", 0.1, 1400.0, "initial_allocation", None, run_id="cmd999"
    )
    assert len(coid) <= 36
    assert "b1" in coid and "c0" in coid
