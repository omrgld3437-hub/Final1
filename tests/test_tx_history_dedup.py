"""İşlem geçmişi fill dedup — sync_from_db tekrarı çift sayım yapmamalı."""
from datetime import datetime, timezone

import pytest

from app.services import transaction_history_file_store as store


@pytest.fixture
def tx_account(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_TX_ROOT", tmp_path / "tx_history")
    aid = 9001
    yield aid
    store._query_cache.clear()
    store._db_sync_last_ts.pop(aid, None)


def _upsert(aid, trade_id, order_id, qty, quote):
    store.upsert_trade_fill(
        aid,
        trade_id=trade_id,
        order_id=order_id,
        time=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        side="SELL",
        symbol="ETHUSDT",
        qty=qty,
        price=quote / qty if qty else 0,
        quote_qty=quote,
        commission=0.001,
        commission_asset="USDT",
        is_maker=False,
        bot_id=2,
        bot_name="Bot #2",
    )


def test_same_trade_id_not_merged_twice(tx_account):
    aid = tx_account
    _upsert(aid, "4053603790", "46955827007", 0.0025, 5.045975)
    _upsert(aid, "4053603790", "46955827007", 0.0025, 5.045975)

    with store._account_lock(aid):
        data = store._load_ledger_unlocked(aid)
        rec = data["orders"]["o_46955827007"]
    assert rec[store.C_QTY] == pytest.approx(0.0025)
    assert rec[store.C_QUOTE] == pytest.approx(5.045975)
    assert rec[store.C_FILLS] == 1


def test_partial_fills_merge_once_each(tx_account):
    aid = tx_account
    _upsert(aid, "4053603790", "46955827007", 0.0025, 5.045975)
    _upsert(aid, "4053603791", "46955827007", 0.0025, 5.045975)
    _upsert(aid, "4053603792", "46955827007", 0.0019, 3.834941)
    # Tekrar sync simülasyonu
    _upsert(aid, "4053603790", "46955827007", 0.0025, 5.045975)
    _upsert(aid, "4053603791", "46955827007", 0.0025, 5.045975)

    with store._account_lock(aid):
        rec = store._load_ledger_unlocked(aid)["orders"]["o_46955827007"]
    assert rec[store.C_QTY] == pytest.approx(0.0069)
    assert rec[store.C_QUOTE] == pytest.approx(13.926891)
    assert rec[store.C_FILLS] == 3
