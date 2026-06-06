"""Stale bot perf cycles file is reconciled from state (account_id + cycle set)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.bot_perf_file_store import (
    _bot_cycles_path,
    load_bot_cycles_file,
    reconcile_bot_cycles_file_with_state,
)


def test_reconcile_clears_stale_file_when_state_empty(tmp_path, monkeypatch):
    import app.services.bot_perf_file_store as store

    monkeypatch.setattr(store, "_PERF_ROOT", tmp_path / "bot_perf")
    store._ensure_dirs()

    bot_id = 2
    stale_path = _bot_cycles_path(bot_id)
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    stale_path.write_text(
        json.dumps(
            {
                "v": 1,
                "bid": bot_id,
                "aid": 3,
                "sym": "ETHUSDT",
                "c": [
                    {
                        "i": 1,
                        "t": "2026-05-29T03:07:41+00:00",
                        "d": "2026-05-29",
                        "r": "trail_reentry_buy",
                        "ct": "INVENTORY",
                        "cp": 0.0,
                        "cf": 0.0,
                        "iq": 0.00011068,
                        "if": 0.055777,
                        "sy": "ETHUSDT",
                    }
                ],
                "u": "2026-05-29T19:39:47+00:00",
            }
        ),
        encoding="utf-8",
    )

    changed = reconcile_bot_cycles_file_with_state(bot_id, 2, "ETHUSDT", [])
    assert changed is True
    data = load_bot_cycles_file(bot_id)
    assert data.get("aid") == 2
    assert data.get("c") == []


def test_reconcile_idempotent_when_file_matches_state(tmp_path, monkeypatch):
    import app.services.bot_perf_file_store as store

    monkeypatch.setattr(store, "_PERF_ROOT", tmp_path / "bot_perf")
    store._ensure_dirs()

    bot_id = 5
    completed = [
        {
            "cycle_id": 1,
            "completed_at": "2026-05-29T10:00:00+00:00",
            "completed_reason": "trail_profit_sell",
            "cycle_type": "CASH",
            "cash_pnl_usdt": 0.5,
            "cash_fees_usdt": 0.01,
            "inventory_coin_adv_qty": 0.0,
            "inventory_fees_usdt": 0.0,
            "close_price_quote_per_base": 2000.0,
        }
    ]
    reconcile_bot_cycles_file_with_state(bot_id, 9, "ETHUSDT", completed)
    before = load_bot_cycles_file(bot_id)
    changed = reconcile_bot_cycles_file_with_state(bot_id, 9, "ETHUSDT", completed)
    after = load_bot_cycles_file(bot_id)
    assert changed is False
    assert len(before.get("c") or []) == 1
    assert before.get("c") == after.get("c")
