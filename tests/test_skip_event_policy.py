"""Skip event dedupe policy and dashboard health flags."""

from __future__ import annotations

from app.botengine.skip_event_policy import (
    evaluate_skip_log,
    grid_min_notional_blocked,
    health_alerts_from_active_skips,
    mark_grid_min_notional_blocked,
    skip_dedupe_key,
)


def _alert_from_tmpl(code, level, tmpl, meta, message=None):
    return {
        "code": code,
        "level": level,
        "title": tmpl.get("title"),
        "message": message or tmpl.get("title"),
        "meta": meta,
    }


def test_skip_dedupe_key_includes_grid_and_cycle():
    key = skip_dedupe_key(
        "MIN_NOTIONAL",
        {
            "reason": "trail_sell_grid",
            "side": "SELL",
            "grid_index": 2,
            "cycle_id": 3,
        },
    )
    assert "grid_index=2" in key
    assert "cycle_id=3" in key


def test_min_notional_logged_once_per_grid_then_suppressed():
    state = {"cycle_id": 3}
    meta = {
        "reason": "trail_sell_grid",
        "side": "SELL",
        "grid_index": 1,
        "cycle_id": 3,
        "notional": 0.01,
        "min_notional": 5.0,
        "symbol": "AAVEUSDT",
    }
    assert evaluate_skip_log(state, "MIN_NOTIONAL", meta).persist is True
    for _ in range(20):
        assert evaluate_skip_log(state, "MIN_NOTIONAL", meta).persist is False
    assert state["active_health_skips"]["MIN_NOTIONAL"]["active"] is True
    assert 1 in state["active_health_skips"]["MIN_NOTIONAL"]["grid_indices"]


def test_grid_min_notional_blocked_stops_requeue():
    state = {"cycle_id": 1}
    mark_grid_min_notional_blocked(
        state, "SELL", 0, notional=0.01, min_notional=5.0
    )
    assert grid_min_notional_blocked(state, "SELL", 0) is True


def test_health_alerts_from_active_skips_critical_min_notional():
    state = {
        "cycle_id": 3,
        "active_health_skips": {
            "MIN_NOTIONAL": {
                "active": True,
                "ts": 9999999999,
                "cycle_id": 3,
                "grid_indices": [0, 1, 2],
                "symbol": "AAVEUSDT",
            }
        },
    }
    alerts = health_alerts_from_active_skips(
        state,
        ack_at=0,
        health_messages={
            "MIN_NOTIONAL": {
                "title": "Minimum tutar (MIN_NOTIONAL)",
                "severity": "warn",
                "cause": "test",
                "actions": [],
            }
        },
        alert_from_tmpl=_alert_from_tmpl,
    )
    assert len(alerts) == 1
    assert alerts[0]["level"] == "critical"
    assert "grid:" in alerts[0]["message"]
