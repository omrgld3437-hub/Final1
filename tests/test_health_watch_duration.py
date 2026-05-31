"""Bot restart mesajı süre formatı."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.botengine.health_watch import (
    _compute_unreachable_sec,
    _format_tr_duration,
    humanize_restart_reason,
)


def test_format_tr_duration_seconds():
    assert _format_tr_duration(1) == "1 saniye"
    assert _format_tr_duration(45) == "45 saniye"


def test_format_tr_duration_minutes():
    assert _format_tr_duration(60) == "1 dakika"
    assert _format_tr_duration(120) == "2 dakika"
    assert _format_tr_duration(150) == "2 dakika 30 saniye"


def test_format_tr_duration_hours():
    assert _format_tr_duration(3600) == "1 saat"
    assert _format_tr_duration(3660) == "1 saat 1 dakika"
    assert _format_tr_duration(7200) == "2 saat"


def test_format_tr_duration_never_vague():
    assert "Kısa" not in _format_tr_duration(None)
    assert _format_tr_duration(0) == "1 saniye"


def test_compute_unreachable_from_last_tick():
    now = 1_700_000_000
    state = {"last_tick_at": datetime.fromtimestamp(now - 125, tz=timezone.utc)}
    assert _compute_unreachable_sec(state, now=now) == 125


def test_compute_unreachable_worker_started_fallback():
    now = 1_700_000_000
    with patch("app.botengine.health_watch._worker_started_ts", return_value=now - 30):
        assert _compute_unreachable_sec({}, now=now) == 30


def test_compute_unreachable_defaults_to_one_second():
    with patch("app.botengine.health_watch._worker_started_ts", return_value=None):
        assert _compute_unreachable_sec({}, now=1_700_000_000) == 1


def test_humanize_restart_reason_includes_duration():
    msg = humanize_restart_reason("worker_poll", unavailable_sec=90)
    assert "1 dakika 30 saniye" in msg
    assert "Kısa bir süre" not in msg
    assert "Sunucu yeniden başlatıldığı" in msg


def test_emit_loop_auto_restart_allows_new_worker_boot(monkeypatch):
    from app.botengine.health_watch import emit_loop_auto_restart

    appended = []
    mark_calls = []

    def fake_append(db, bot_id, account_id, typ, msg, meta):
        appended.append((typ, msg))

    def fake_load(db, bot_id):
        return {"_resilience_last_emit": {"BOT_LOOP_AUTO_RESTART": 1_700_000_000.0}}

    def fake_save(db, bot_id, account_id, state):
        pass

    def fake_mark(db, bot, state, **kw):
        mark_calls.append(bot.id)

    class FakeBot:
        id = 42
        account_id = 1
        status = "running"

    class FakeQ:
        def filter(self, *a):
            return self

        def first(self):
            return FakeBot()

    class FakeDb:
        def query(self, *a):
            return FakeQ()

    monkeypatch.setattr("app.botengine.state_store.append_event", fake_append)
    monkeypatch.setattr("app.botengine.state_store.load_state", fake_load)
    monkeypatch.setattr("app.botengine.state_store.save_state", fake_save)
    monkeypatch.setattr("app.botengine.health_watch._worker_started_ts", lambda: 1_700_000_100.0)
    monkeypatch.setattr(
        "app.services.binance_connectivity.mark_pending_connectivity_stable",
        fake_mark,
    )

    emit_loop_auto_restart(FakeDb(), 42, 1, "worker_poll")

    assert len(appended) == 2
    assert "Sunucu yeniden başlatıldığı" in appended[1][1]
    assert mark_calls == [42]


def test_emit_loop_auto_restart_dedup_same_worker(monkeypatch):
    from app.botengine.health_watch import emit_loop_auto_restart

    appended = []

    def fake_append(db, bot_id, account_id, typ, msg, meta):
        appended.append(typ)

    def fake_load(db, bot_id):
        return {"_resilience_last_emit": {"BOT_LOOP_AUTO_RESTART": time.time() - 5}}

    monkeypatch.setattr("app.botengine.state_store.append_event", fake_append)
    monkeypatch.setattr("app.botengine.state_store.load_state", fake_load)
    monkeypatch.setattr("app.botengine.state_store.save_state", lambda *a, **k: None)
    monkeypatch.setattr("app.botengine.health_watch._worker_started_ts", lambda: time.time() - 3600)

    emit_loop_auto_restart(None, 42, 1, "worker_poll")

    assert appended == []
