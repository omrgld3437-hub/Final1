"""Tests for Binance connectivity tracker."""

from __future__ import annotations

import time
from types import SimpleNamespace

import app.services.binance_connectivity as bc


def test_active_failure_ttl(monkeypatch, tmp_path):
    bc._by_account.clear()
    monkeypatch.setattr(bc, "_RUN_DIR", tmp_path)
    bc.note_binance_failure(1, "BINANCE_UNREACHABLE", "timeout", "test")
    assert bc.active_failure(1) is not None
    rec = bc.active_failure(1)
    assert rec["error_code"] == "BINANCE_UNREACHABLE"
    assert (tmp_path / "binance_fail_1.json").exists()

    monkeypatch.setattr(bc, "_FAILURE_TTL_SEC", 0.01)
    time.sleep(0.02)
    assert bc.active_failure(1) is None


def test_success_clears_failure(monkeypatch, tmp_path):
    bc._by_account.clear()
    monkeypatch.setattr(bc, "_RUN_DIR", tmp_path)
    bc.note_binance_failure(2, "BINANCE_UNREACHABLE", "err", "test", emit_async=False)
    assert bc.active_failure(2) is not None
    bc.note_binance_success(2)
    assert bc.active_failure(2) is None
    assert not (tmp_path / "binance_fail_2.json").exists()


def test_classify_unauthorized():
    class Resp:
        status_code = 401

    class Err(Exception):
        response = Resp()

    code, msg = bc._classify_binance_error(Err())
    assert code == "API_UNAUTHORIZED"


def test_api_unauthorized_emits_without_transient_delay(monkeypatch, tmp_path):
    bc._by_account.clear()
    bc._first_fail_ts_by_account.clear()
    monkeypatch.setattr(bc, "_RUN_DIR", tmp_path)
    emitted = []
    monkeypatch.setattr(
        bc, "_emit_bot_events_async", lambda *args: emitted.append(args)
    )

    bc.note_binance_failure(
        7,
        "API_UNAUTHORIZED",
        "Binance API anahtarı geçersiz veya IP beyaz listesinde değil.",
        "wallet",
    )

    assert emitted
    assert emitted[0][0] == 7
    assert emitted[0][1] == "API_UNAUTHORIZED"


def test_api_unauthorized_connectivity_event_pauses_running_bot(monkeypatch):
    bot = SimpleNamespace(id=17, account_id=3, status="running")
    saved = {}
    events = []

    monkeypatch.setattr(bc, "_recent_connectivity_event", lambda *a, **k: False)
    monkeypatch.setattr(bc, "emit_tur_connectivity_paused_info", lambda *a, **k: True)
    monkeypatch.setattr("app.botengine.state_store.load_state", lambda *a, **k: {})
    monkeypatch.setattr(
        "app.botengine.state_store.save_state",
        lambda db, bot_id, account_id, state: saved.update(state),
    )
    monkeypatch.setattr(
        "app.botengine.state_store.append_event",
        lambda db, bot_id, account_id, event_type, message="", meta=None, ts=None: (
            events.append((event_type, message, meta or {}))
        ),
    )

    ok = bc.emit_connectivity_events_for_bot(
        object(),
        bot,
        "API_UNAUTHORIZED",
        "Binance API anahtarı geçersiz veya IP beyaz listesinde değil.",
        "health_poll",
        force=True,
    )

    assert ok is True
    assert bot.status == "paused_error"
    assert saved["last_error_code"] == "API_UNAUTHORIZED"
    assert saved["backoff_until"] > time.time()
    assert any(
        event_type == "ERROR" and "401/-2015" in msg
        for event_type, msg, _ in events
    )


def test_api_unauthorized_pauses_even_when_event_is_throttled(monkeypatch):
    bot = SimpleNamespace(id=18, account_id=3, status="running")
    saved = {}
    monkeypatch.setitem(bc._last_emit_by_bot, 18, time.time())

    monkeypatch.setattr(bc, "_recent_connectivity_event", lambda *a, **k: False)
    monkeypatch.setattr("app.botengine.state_store.load_state", lambda *a, **k: {})
    monkeypatch.setattr(
        "app.botengine.state_store.save_state",
        lambda db, bot_id, account_id, state: saved.update(state),
    )

    ok = bc.emit_connectivity_events_for_bot(
        object(),
        bot,
        "API_UNAUTHORIZED",
        "Binance API anahtarı geçersiz veya IP beyaz listesinde değil.",
        "health_poll",
        force=False,
    )

    assert ok is False
    assert bot.status == "paused_error"
    assert saved["last_error_code"] == "API_UNAUTHORIZED"
    assert saved["backoff_until"] > time.time()


def test_queue_and_flush_skips_recent_stable(monkeypatch):
    monkeypatch.setattr(
        bc, "_recent_connectivity_recovered", lambda db, bot_id, within_sec=45.0: True
    )
    called = {"mark": 0}

    def fake_mark(*a, **k):
        called["mark"] += 1

    monkeypatch.setattr(bc, "mark_pending_connectivity_stable", fake_mark)
    assert bc.queue_and_flush_connectivity_stable(None, 1) is False
    assert called["mark"] == 0
