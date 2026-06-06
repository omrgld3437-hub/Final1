"""Binance connectivity alert must surface even when bot is not running."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.botengine.health_watch import (
    emit_health_alerts,
    evaluate_bot_health,
    evaluate_bot_health_lite,
)


def test_binance_unreachable_when_bot_paused():
    bot = SimpleNamespace(
        id=1, account_id=42, status="paused_error", symbol="ETHUSDT", config_json="{}"
    )
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


def test_wallet_snapshot_stale_surfaces_as_running_bot_warning():
    bot = SimpleNamespace(
        id=22,
        account_id=691363,
        status="running",
        symbol="ETHUSDT",
        config_json='{"tick_interval_ms": 2000}',
        started_at=None,
    )
    state = {"last_tick_at": datetime.now(timezone.utc)}
    wallet_alert = {
        "code": "WALLET_SNAPSHOT_STALE",
        "level": "warn",
        "title": "Cüzdan verisi güncel değil",
        "message": "Cüzdan verisi güncel değil: son snapshot 1400 dk önce",
        "meta": {"last_snapshot_at": "2026-06-02T00:47:00Z", "snapshot_age_s": 84000},
    }

    alerts = evaluate_bot_health_lite(
        bot,
        state,
        account_failure=None,
        account_wallet_alert=wallet_alert,
    )

    assert any(
        a.get("code") == "WALLET_SNAPSHOT_STALE" and a.get("level") == "warn"
        for a in alerts
    )


def test_connectivity_state_error_not_duplicated_when_error_log_exists():
    bot = SimpleNamespace(id=3, account_id=44)
    state = {}
    recent_error = {
        "type": "ERROR",
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": {"error_code": "BINANCE_UNREACHABLE"},
    }
    alerts = [
        {
            "code": "STATE_ERROR",
            "level": "critical",
            "title": "Bot hata durumunda",
            "message": "Kritik hata: BINANCE_UNREACHABLE",
            "meta": {"error_code": "BINANCE_UNREACHABLE"},
        }
    ]
    with (
        patch("app.botengine.state_store.list_events", return_value=[recent_error]),
        patch("app.botengine.state_store.append_event") as append_event,
        patch("app.botengine.state_store.save_state") as save_state,
    ):
        emitted = emit_health_alerts(None, bot, state, alerts)
    assert emitted == 0
    append_event.assert_not_called()
    save_state.assert_not_called()


def test_connectivity_state_error_emits_without_recent_error_log():
    bot = SimpleNamespace(id=4, account_id=45)
    state = {}
    alerts = [
        {
            "code": "STATE_ERROR",
            "level": "critical",
            "title": "Bot hata durumunda",
            "message": "Kritik hata: BINANCE_UNREACHABLE",
            "meta": {"error_code": "BINANCE_UNREACHABLE"},
        }
    ]
    with (
        patch("app.botengine.state_store.list_events", return_value=[]),
        patch("app.botengine.state_store.append_event") as append_event,
        patch("app.botengine.state_store.save_state") as save_state,
    ):
        emitted = emit_health_alerts(None, bot, state, alerts)
    assert emitted == 1
    append_event.assert_called_once()
    save_state.assert_called_once()
