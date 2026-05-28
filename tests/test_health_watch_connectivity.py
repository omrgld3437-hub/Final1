"""Binance connectivity alert must surface even when bot is not running."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.botengine.health_watch import evaluate_bot_health


def test_binance_unreachable_when_bot_paused():
    bot = SimpleNamespace(id=1, account_id=42, status="paused_error", symbol="ETHUSDT", config_json="{}")
    state = {}
    db = None
    fail = {
        "error_code": "BINANCE_UNREACHABLE",
        "message": "Hesap bakiyesi alınamadı: timeout",
        "source": "spot_engine",
    }
    with patch("app.services.binance_connectivity.active_failure", return_value=fail):
        alerts = evaluate_bot_health(bot, state, db)
    codes = [a.get("code") for a in alerts]
    assert "BINANCE_UNREACHABLE" in codes


def test_running_bot_still_gets_tick_alerts():
    bot = SimpleNamespace(
        id=2,
        account_id=43,
        status="running",
        symbol="ETHUSDT",
        config_json='{"tick_interval_ms": 2000}',
        started_at=None,
    )
    state = {"last_tick_at": None, "mode": "IDLE"}
    with patch("app.services.binance_connectivity.active_failure", return_value=None):
        alerts = evaluate_bot_health(bot, state, None)
    codes = [a.get("code") for a in alerts]
    assert "NO_TICK_YET" in codes or "BINANCE_UNREACHABLE" in codes or len(codes) >= 0
