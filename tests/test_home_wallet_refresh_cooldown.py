import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def test_wallet_refresh_force_still_respects_cooldown():
    from app.api.routes import home as home_routes
    from app.db.base import SessionLocal
    from app.db.models import Account
    from app.main import app

    code = str(uuid.uuid4().int)[-6:]
    db = SessionLocal()
    account = Account(
        account_code=code,
        name="Wallet Cooldown Test",
        api_key_enc="test-key",
        api_secret_enc="test-secret",
    )
    db.add(account)
    db.commit()
    account_id = account.id

    app.dependency_overrides[home_routes.require_auth] = lambda: {"is_admin": True, "user_id": 1}
    home_routes._wallet_cooldown_until[account_id] = time.monotonic() + 60
    try:
        resp = TestClient(app).post(f"/api/home/wallet/refresh?account_id={account_id}&force=1")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["skipped"] is True
        assert data["inflight"] is False
    finally:
        app.dependency_overrides.pop(home_routes.require_auth, None)
        home_routes._wallet_cooldown_until.pop(account_id, None)
        db.query(Account).filter(Account.id == account_id).delete()
        db.commit()
        db.close()


def test_wallet_status_reports_stale_snapshot_age():
    from app.api.routes import home as home_routes
    from app.db.base import SessionLocal
    from app.db.models import Account, AssetSnapshot
    from app.main import app

    code = str(uuid.uuid4().int)[-6:]
    db = SessionLocal()
    account = Account(
        account_code=code,
        name="Wallet Status Stale Test",
        api_key_enc="test-key",
        api_secret_enc="test-secret",
    )
    db.add(account)
    db.commit()
    account_id = account.id
    snap = AssetSnapshot(
        account_id=account_id,
        timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        total_usd_value=12.34,
        breakdown_json='{"USDT":{"free":12.34,"locked":0,"total":12.34}}',
        source="binance",
    )
    db.add(snap)
    db.commit()

    app.dependency_overrides[home_routes.require_auth] = lambda: {"is_admin": True, "user_id": 1}
    try:
        resp = TestClient(app).get(f"/api/home/wallet/status?account_id={account_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["keys_configured"] is True
        assert data["snapshot_stale"] is True
        assert data["last_snapshot_at"]
        assert data["last_snapshot_age_sec"] >= 3600
        assert data["stale_threshold_sec"] == 900
        assert data["last_snapshot_total_usd"] == 12.34
    finally:
        app.dependency_overrides.pop(home_routes.require_auth, None)
        db.query(AssetSnapshot).filter(AssetSnapshot.account_id == account_id).delete()
        db.query(Account).filter(Account.id == account_id).delete()
        db.commit()
        db.close()
