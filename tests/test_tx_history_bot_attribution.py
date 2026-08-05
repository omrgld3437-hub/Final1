"""Spot olarak yazılmış bot fill'leri sonradan Bot etiketi almalı; platform Ayserose/Binance."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import transaction_history_file_store as store


def test_tag_ledger_order_upgrades_spot_to_bot(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_TX_ROOT", tmp_path / "tx_history")
    aid = 9102
    store.upsert_trade_fill(
        aid,
        trade_id="t1",
        order_id="ord-bot-close-1",
        time=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
        side="SELL",
        symbol="SOLUSDT",
        qty=1.0,
        price=150.0,
        quote_qty=150.0,
        commission=0.01,
        commission_asset="USDT",
        is_maker=False,
        bot_id=None,
        platform="Binance",
    )
    with store._account_lock(aid):
        rec = store._load_ledger_unlocked(aid)["orders"]["o_ord-bot-close-1"]
    assert rec[store.C_SRC] == "s"
    assert rec[store.C_BID] is None

    changed = store._tag_ledger_order_as_bot(
        aid,
        order_id="ord-bot-close-1",
        bot_id=7,
        bot_name="SOL Bot",
    )
    assert changed is True

    items = store.query_transactions(
        aid, period="all", type_filter="buysell", page=1, per_page=5
    )["items"]
    assert len(items) == 1
    assert items[0]["is_bot"] is True
    assert items[0]["source_label"].startswith("Bot")
    assert items[0]["bot_id"] == 7
    assert items[0]["platform"] == "Ayserose"
    store._query_cache.clear()


def test_binance_vs_ayserose_platform_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_TX_ROOT", tmp_path / "tx_history")
    aid = 9103
    store.upsert_trade_fill(
        aid,
        trade_id="bn-1",
        order_id="ord-bn-1",
        time=datetime(2026, 8, 5, 17, 0, tzinfo=timezone.utc),
        side="BUY",
        symbol="BTCUSDT",
        qty=0.01,
        price=60000.0,
        quote_qty=600.0,
        commission=0.0,
        commission_asset="USDT",
        is_maker=False,
        bot_id=None,
        platform="Binance",
    )
    store.record_spot_manual_trade_fill(
        aid,
        order_id="ord-ui-1",
        symbol="ETHUSDT",
        side="BUY",
        qty=0.5,
        price=3000.0,
        quote_qty=1500.0,
    )
    items = store.query_transactions(
        aid, period="all", type_filter="buysell", page=1, per_page=10
    )["items"]
    by_oid = {i["order_id"]: i for i in items}
    assert by_oid["ord-bn-1"]["platform"] == "Binance"
    assert by_oid["ord-bn-1"]["source_label"] == "Binance"
    assert by_oid["ord-bn-1"]["is_bot"] is False
    assert by_oid["ord-ui-1"]["platform"] == "Ayserose"
    assert by_oid["ord-ui-1"]["source_label"] == "Ayserose"
    store._query_cache.clear()


def test_record_bot_close_convert_fill_is_bot(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_TX_ROOT", tmp_path / "tx_history")
    aid = 9104
    db = SimpleNamespace(
        query=lambda *_a, **_k: SimpleNamespace(
            filter=lambda *_a2, **_k2: SimpleNamespace(
                first=lambda: SimpleNamespace(
                    id=42, name="Close Bot", config_json="{}", symbol="SOLUSDT"
                )
            )
        )
    )
    store.record_bot_close_convert_fill(
        db,
        aid,
        42,
        "SOLUSDT",
        {
            "orderId": 991122,
            "side": "SELL",
            "symbol": "SOLUSDT",
            "executedQty": "2.5",
            "cummulativeQuoteQty": "375.0",
            "price": "0",
            "fills": [
                {
                    "id": 555001,
                    "qty": "2.5",
                    "price": "150.0",
                    "commission": "0.0375",
                    "commissionAsset": "USDT",
                }
            ],
            "transactTime": int(
                datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc).timestamp() * 1000
            ),
        },
    )
    items = store.query_transactions(
        aid, period="all", type_filter="buysell", page=1, per_page=5
    )["items"]
    assert len(items) == 1
    assert items[0]["is_bot"] is True
    assert items[0]["bot_id"] == 42
    assert items[0]["source_label"].startswith("Bot")
    assert items[0]["platform"] == "Ayserose"
    assert items[0]["side"] == "SELL"
    store._query_cache.clear()


def test_later_binance_sync_does_not_downgrade_bot_close(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_TX_ROOT", tmp_path / "tx_history")
    aid = 9105
    store.upsert_trade_fill(
        aid,
        trade_id="555001",
        order_id="991122",
        time=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
        side="SELL",
        symbol="SOLUSDT",
        qty=2.5,
        price=150.0,
        quote_qty=375.0,
        commission=0.0375,
        commission_asset="USDT",
        is_maker=False,
        bot_id=42,
        bot_name="Close Bot",
        platform="Ayserose",
    )
    # Same fill re-synced from Binance without bot_id must stay Bot.
    store.upsert_trade_fill(
        aid,
        trade_id="555001",
        order_id="991122",
        time=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
        side="SELL",
        symbol="SOLUSDT",
        qty=2.5,
        price=150.0,
        quote_qty=375.0,
        commission=0.0375,
        commission_asset="USDT",
        is_maker=False,
        bot_id=None,
        platform="Binance",
    )
    items = store.query_transactions(
        aid, period="all", type_filter="buysell", page=1, per_page=5
    )["items"]
    assert len(items) == 1
    assert items[0]["is_bot"] is True
    assert items[0]["platform"] == "Ayserose"
    store._query_cache.clear()
