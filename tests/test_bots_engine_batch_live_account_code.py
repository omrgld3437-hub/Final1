import uuid

from fastapi.testclient import TestClient


def test_batch_live_accepts_account_code_without_account_id():
    from app.api import bots_engine
    from app.db.base import SessionLocal
    from app.db.models import Account, Bot
    from app.main import app

    code = str(uuid.uuid4().int)[-6:]
    db = SessionLocal()
    account = Account(
        account_code=code,
        name="Batch Live Account Code Test",
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
    bot_id = bot.id

    app.dependency_overrides[bots_engine.require_auth] = lambda: {"is_admin": True, "user_id": 1}
    try:
        client = TestClient(app)
        resp = client.get(f"/api/bots-engine/batch/live?account_code={code}&bot_ids={bot_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert str(bot_id) in data["live"]
    finally:
        app.dependency_overrides.pop(bots_engine.require_auth, None)
        db.query(Bot).filter(Bot.id == bot_id).delete()
        db.query(Account).filter(Account.id == account.id).delete()
        db.commit()
        db.close()
