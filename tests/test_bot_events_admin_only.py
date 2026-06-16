"""Bot engine events API — admin-only access."""

import uuid

from fastapi.testclient import TestClient


def _seed_bot(db):
    from app.db.models import Account, Bot

    code = str(uuid.uuid4().int)[-6:]
    account = Account(
        account_code=code,
        name="Events Admin Test",
        api_key_enc="test-key",
        api_secret_enc="test-secret",
    )
    db.add(account)
    db.flush()
    bot = Bot(
        account_id=account.id,
        symbol="BTCUSDT",
        status="running",
        config_json='{"initial_capital_usdt": 100}',
    )
    db.add(bot)
    db.commit()
    return account, bot


def test_bots_events_forbidden_for_non_admin():
    from app.api import bots_engine
    from app.db.base import SessionLocal
    from app.main import app

    db = SessionLocal()
    account, bot = _seed_bot(db)
    app.dependency_overrides[bots_engine.require_auth] = lambda: {
        "is_admin": False,
        "user_id": 2,
        "account_id": account.id,
    }
    try:
        client = TestClient(app)
        resp = client.get(
            f"/api/bots-engine/{bot.id}/events?account_id={account.id}&limit=10"
        )
        assert resp.status_code == 403, resp.text
        detail = resp.json().get("detail") or {}
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        assert "admin" in str(msg).lower()
    finally:
        app.dependency_overrides.pop(bots_engine.require_auth, None)
        db.query(type(bot)).filter_by(id=bot.id).delete()
        db.query(type(account)).filter_by(id=account.id).delete()
        db.commit()
        db.close()


def test_bots_events_allowed_for_admin():
    from app.api import bots_engine
    from app.db.base import SessionLocal
    from app.main import app

    db = SessionLocal()
    account, bot = _seed_bot(db)
    app.dependency_overrides[bots_engine.require_auth] = lambda: {
        "is_admin": True,
        "user_id": 1,
        "account_id": account.id,
    }
    try:
        client = TestClient(app)
        resp = client.get(
            f"/api/bots-engine/{bot.id}/events?account_id={account.id}&limit=10"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "events" in data
    finally:
        app.dependency_overrides.pop(bots_engine.require_auth, None)
        db.query(type(bot)).filter_by(id=bot.id).delete()
        db.query(type(account)).filter_by(id=account.id).delete()
        db.commit()
        db.close()
