"""
FILE: test_reconcile_inconclusive_lookup.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Reconcile'da 'emir yok' ile 'sorgulayamadım' ayrımı (K4 regresyon kilidi).

Geçici bir ağ kesintisi veya 429 sırasında canlı bir emrin CANCELED işaretlenmesi,
botun gerçek pozisyonun takibini kaybetmesine yol açar. Bu testler o davranışı kilitler.
"""

import pytest

from app.botengine import reconcile as reconcile_mod


class _FakeDb:
    pass


@pytest.fixture
def patched(monkeypatch):
    """Reconcile'ın intent kaynağını ve güncelleme çağrısını izole eder."""
    calls = []

    def fake_get_non_final(db, account_id):
        return [
            {
                "intent_id": 42,
                "client_order_id": "BOT-7-abc",
                "symbol": "BTCUSDT",
            }
        ]

    def fake_update(db, intent_id, **kwargs):
        calls.append({"intent_id": intent_id, **kwargs})
        return True

    monkeypatch.setattr(
        reconcile_mod, "get_non_final_intents_for_account", fake_get_non_final
    )
    monkeypatch.setattr(reconcile_mod, "update_intent_from_binance", fake_update)
    return calls


async def _no_open_orders(symbol=None):
    return []


@pytest.mark.asyncio
async def test_network_error_does_not_cancel_intent(patched):
    """Her iki sorgu da ağ hatası verirse intent'e dokunulmaz ve hata sayılır."""

    async def raise_network(*args, **kwargs):
        raise ConnectionError("Connection reset by peer")

    result = await reconcile_mod.reconcile_account(
        account_id=1,
        get_open_orders=_no_open_orders,
        get_all_orders=raise_network,
        get_order_by_client_order_id=raise_network,
        db=_FakeDb(),
    )

    assert patched == [], "geçici hatada intent CANCELED işaretlendi"
    assert result["errors"] >= 1
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_rate_limit_error_does_not_cancel_intent(patched):
    """429 rate limit 'emir yok' anlamına gelmez."""

    async def raise_429(*args, **kwargs):
        raise RuntimeError("HTTP 429 Too Many Requests")

    result = await reconcile_mod.reconcile_account(
        account_id=1,
        get_open_orders=_no_open_orders,
        get_all_orders=raise_429,
        get_order_by_client_order_id=raise_429,
        db=_FakeDb(),
    )

    assert patched == []
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_binance_2013_marks_canceled(patched):
    """Binance -2013 kesin 'emir yok' cevabıdır; intent CANCELED işaretlenir."""

    async def raise_2013(*args, **kwargs):
        raise RuntimeError("APIError(code=-2013): Order does not exist.")

    result = await reconcile_mod.reconcile_account(
        account_id=1,
        get_open_orders=_no_open_orders,
        get_all_orders=raise_2013,
        get_order_by_client_order_id=raise_2013,
        db=_FakeDb(),
    )

    assert len(patched) == 1
    assert patched[0]["status"] == reconcile_mod.STATUS_CANCELED
    assert result["updated"] == 1


@pytest.mark.asyncio
async def test_clean_empty_history_marks_canceled(patched):
    """Geçmiş listesi temiz döndü ve emri içermiyorsa kesin yok cevabıdır."""

    async def none_lookup(symbol, coid):
        return None

    async def empty_all_orders(symbol=None, limit=20):
        return []

    result = await reconcile_mod.reconcile_account(
        account_id=1,
        get_open_orders=_no_open_orders,
        get_all_orders=empty_all_orders,
        get_order_by_client_order_id=none_lookup,
        db=_FakeDb(),
    )

    assert len(patched) == 1
    assert patched[0]["status"] == reconcile_mod.STATUS_CANCELED


@pytest.mark.asyncio
async def test_live_order_found_is_not_canceled(patched):
    """Emir açık emirler arasında bulunursa SUBMITTED olarak güncellenir."""

    async def open_orders(symbol=None):
        return [{"clientOrderId": "BOT-7-abc", "status": "NEW", "orderId": 99}]

    async def unused(*args, **kwargs):
        raise AssertionError("açık emir bulunduğunda ek sorgu yapılmamalı")

    await reconcile_mod.reconcile_account(
        account_id=1,
        get_open_orders=open_orders,
        get_all_orders=unused,
        get_order_by_client_order_id=unused,
        db=_FakeDb(),
    )

    assert len(patched) == 1
    assert patched[0]["status"] == reconcile_mod.STATUS_SUBMITTED
