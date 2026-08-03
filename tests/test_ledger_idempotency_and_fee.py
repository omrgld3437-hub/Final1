"""
FILE: test_ledger_idempotency_and_fee.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Ledger idempotency'sinin DB seviyesinde kilitlenmesi + fee_usdt birim doğruluğu.

Aynı borsa emrinin iki kez kaydedilmesi PnL'i çift sayar; komisyonun BNB gibi bir
varlıkta olup USDT sayılması ise PnL'i sessizce bozar. İkisi de para hatası.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.bot.ledger import Ledger, _is_usd_equivalent
from app.db.models import Account, Base, Bot, Trade


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'ledger.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    account = Account(
        account_code="000001",
        name="test",
        exchange="BINANCE",
        api_key_enc="x",
        api_secret_enc="x",
        mode="paper",
    )
    session.add(account)
    session.commit()
    bot = Bot(account_id=account.id, symbol="BTCUSDT", mode="paper", status="stopped")
    session.add(bot)
    session.commit()
    session.bot_id = bot.id
    session.account_id = account.id
    try:
        yield session
    finally:
        session.close()


def test_unique_constraint_exists_on_bot_order():
    """trades(bot_id, order_id) unique kısıtı model üzerinde tanımlı."""
    names = {c.name for c in Trade.__table__.constraints}
    assert "uq_trades_bot_order" in names


def test_unique_constraint_enforced_by_database(tmp_path):
    """Kısıt gerçekten veritabanı seviyesinde uygulanıyor (uygulama koduna güvenmiyoruz)."""
    engine = create_engine(f"sqlite:///{tmp_path/'idx.db'}")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    unique_cols = [
        tuple(u["column_names"]) for u in insp.get_unique_constraints("trades")
    ] + [tuple(i["column_names"]) for i in insp.get_indexes("trades") if i.get("unique")]
    assert ("bot_id", "order_id") in unique_cols

    session = sessionmaker(bind=engine)()
    try:
        for _ in range(2):
            session.add(
                Trade(
                    bot_id=1,
                    account_id=1,
                    ts=__import__("datetime").datetime.utcnow(),
                    side="BUY",
                    qty=1.0,
                    price=1.0,
                    order_id="DUP",
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_duplicate_order_id_returns_existing_row(db):
    """Aynı order_id ikinci kez kaydedilmez; mevcut satır döner."""
    first, inserted_first = Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0, order_id="OID-1"
    )
    second, inserted_second = Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0, order_id="OID-1"
    )
    assert inserted_first is True
    assert inserted_second is False
    assert first.id == second.id
    assert db.query(Trade).count() == 1


def test_concurrent_insert_race_is_closed_by_db(db, monkeypatch):
    """Ön sorgu ile insert arasına başka bir yazar girse bile çift kayıt oluşmaz.

    Ön sorguyu 'kayıt yok' diyecek şekilde köreltip yarışı simüle ediyoruz;
    koruma artık unique index + IntegrityError yakalaması.
    """
    Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0, order_id="OID-RACE"
    )

    real_query = db.query
    calls = {"n": 0}

    class _Blind:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    def blind_query(model):
        # Yalnızca ilk (ön kontrol) sorgusunu körelt; IntegrityError sonrası
        # yapılan yeniden okuma gerçek sorguyu kullanmalı.
        if model is Trade and calls["n"] == 0:
            calls["n"] += 1
            return _Blind()
        return real_query(model)

    monkeypatch.setattr(db, "query", blind_query)
    row, inserted = Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0, order_id="OID-RACE"
    )
    monkeypatch.undo()

    assert inserted is False
    assert db.query(Trade).count() == 1


def test_null_order_id_rows_are_not_deduplicated(db):
    """order_id NULL olan paper/simülasyon kayıtları unique kısıta takılmaz."""
    Ledger.record_trade(db, db.bot_id, db.account_id, "BUY", 1.0, 100.0)
    Ledger.record_trade(db, db.bot_id, db.account_id, "BUY", 1.0, 100.0)
    assert db.query(Trade).count() == 2


@pytest.mark.parametrize("asset", ["USDT", "usdt", "BUSD", "USDC", "FDUSD"])
def test_usd_equivalent_assets(asset):
    assert _is_usd_equivalent(asset) is True


@pytest.mark.parametrize("asset", ["BNB", "BTC", "ETH", "TRY", "", None])
def test_non_usd_assets(asset):
    assert _is_usd_equivalent(asset) is False


def test_fee_usdt_defaults_from_fee_when_asset_is_usdt(db):
    trade, _ = Ledger.record_trade(
        db, db.bot_id, db.account_id, "SELL", 1.0, 100.0,
        fee=0.1, fee_asset="USDT", order_id="OID-FEE-USDT",
    )
    assert trade.fee_usdt == pytest.approx(0.1)


def test_fee_usdt_stays_unknown_for_bnb_fee(db):
    """BNB komisyonu USDT sayılamaz; dönüşüm yoksa alan None kalır."""
    trade, _ = Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0,
        fee=0.002, fee_asset="BNB", order_id="OID-FEE-BNB",
    )
    assert trade.fee_usdt is None
    assert trade.fee_amount == pytest.approx(0.002)


def test_explicit_fee_usdt_is_respected(db):
    """Çağıran dönüşümü yapmışsa (execution.py) verilen değer korunur."""
    trade, _ = Ledger.record_trade(
        db, db.bot_id, db.account_id, "BUY", 1.0, 100.0,
        fee=0.9, fee_asset="BNB", fee_amount=0.002, fee_usdt=0.9,
        order_id="OID-FEE-EXPLICIT",
    )
    assert trade.fee_usdt == pytest.approx(0.9)
