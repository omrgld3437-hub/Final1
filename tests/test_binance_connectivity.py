"""Tests for Binance connectivity tracker."""
from __future__ import annotations

import time

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


def test_queue_and_flush_skips_recent_stable(monkeypatch):
    monkeypatch.setattr(bc, "_recent_connectivity_recovered", lambda db, bot_id, within_sec=45.0: True)
    called = {"mark": 0}

    def fake_mark(*a, **k):
        called["mark"] += 1

    monkeypatch.setattr(bc, "mark_pending_connectivity_stable", fake_mark)
    assert bc.queue_and_flush_connectivity_stable(None, 1) is False
    assert called["mark"] == 0
