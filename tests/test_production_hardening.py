"""Production hardening: server IP cache, settings password guard, SSE config."""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_config_public_includes_dashboard_sse_flag(client: TestClient):
    r = client.get("/api/config/public")
    assert r.status_code == 200
    data = r.json()
    assert "dashboard_sse_enabled" in data
    assert isinstance(data["dashboard_sse_enabled"], bool)


def test_settings_patch_rejects_password_field(client: TestClient):
    """PATCH /settings password alanı reddedilir — bcrypt yalnızca /auth/change-password."""
    user = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    pwd = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not user or not pwd:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD")
    login = client.post("/api/auth/login", json={"phone": user, "password": pwd})
    assert login.status_code == 200
    body = login.json()
    account_id = body.get("account_id") or (body.get("user") or {}).get("account_id")
    if not account_id:
        pytest.skip("No account_id in login response")
    token = body.get("token") or login.cookies.get("auth_token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.patch(
        f"/api/accounts/{account_id}/settings",
        json={"password": "NewPass123!"},
        headers=headers,
    )
    assert r.status_code == 400
    detail = r.json().get("detail", {})
    if isinstance(detail, dict):
        assert detail.get("error_code") == "PASSWORD_USE_AUTH_ENDPOINT"


def test_change_password_rejects_weak_password(client: TestClient):
    user = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    pwd = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not user or not pwd:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD")
    login = client.post("/api/auth/login", json={"phone": user, "password": pwd})
    assert login.status_code == 200
    body = login.json()
    account_id = body.get("account_id") or (body.get("user") or {}).get("account_id")
    token = body.get("token") or login.cookies.get("auth_token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.post(
        "/api/auth/change-password",
        json={
            "account_id": account_id,
            "new_password": "short",
            "new_password_confirm": "short",
        },
        headers=headers,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_server_public_ip_cache():
    from app.services import server_public_ip as sip

    sip._cached_ip = "203.0.113.1"
    sip._cached_at = __import__("time").time()
    ip = await sip.get_server_public_ip()
    assert ip == "203.0.113.1"
