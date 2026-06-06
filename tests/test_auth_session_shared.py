"""
Auth shared-session tests: login then protected endpoint returns 200 (fixes login redirect loop).
Session store is DB-backed so multi-worker and restarts work; no boot_id in acceptance criteria.
"""

import os
import pytest
import secrets
from datetime import datetime, timedelta
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_login_then_protected_endpoint_returns_200(client: TestClient):
    """
    Login -> then call protected endpoint with same token -> 200.
    Session is in shared store (DB), so any worker would find it.
    """
    username = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    password = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not username or not password:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD to run auth test")

    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
    )
    assert login_resp.status_code == 200, login_resp.text
    data = login_resp.json()
    assert data.get("success") is True
    token = data.get("token")
    assert token, "Login response must include token"

    whoami_resp = client.get(
        "/api/auth/whoami",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert whoami_resp.status_code == 200, whoami_resp.text
    whoami = whoami_resp.json()
    assert "user_id" in whoami
    assert whoami.get("username") == username


def test_login_then_protected_endpoint_with_cookie(client: TestClient):
    """Same as above but use cookie (auth_token) instead of Bearer for protected call."""
    username = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    password = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not username or not password:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD to run auth test")

    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
    )
    assert login_resp.status_code == 200, login_resp.text
    # Use cookies from login response for next request (simulates browser)
    cookies = login_resp.cookies
    whoami_resp = client.get("/api/auth/whoami", cookies=cookies)
    assert whoami_resp.status_code == 200, whoami_resp.text
    whoami = whoami_resp.json()
    assert whoami.get("username") == username


def test_require_auth_returns_401_with_session_not_found(client: TestClient):
    """Invalid or expired token yields 401 with SESSION_NOT_FOUND (or UNAUTHORIZED)."""
    resp = client.get(
        "/api/auth/whoami",
        headers={"Authorization": "Bearer invalid-token-no-session"},
    )
    assert resp.status_code == 401
    data = resp.json()
    detail = data.get("detail", {})
    if isinstance(detail, dict):
        code = detail.get("error_code")
    else:
        code = data.get("error_code")
    assert code in ("UNAUTHORIZED", "SESSION_NOT_FOUND")


def test_session_validation_does_not_depend_on_boot_id(client: TestClient):
    """
    Session validation must NOT depend on boot_id (multi-worker safe).
    Create session row with boot_id='A'; validate with token -> must succeed regardless of current process boot_id.
    """
    from app.db.base import SessionLocal
    from app.core.auth.token_utils import hash_token
    from sqlalchemy import text

    raw_token = secrets.token_urlsafe(32)
    th = hash_token(raw_token)
    now = datetime.utcnow()
    exp = now + timedelta(days=7)
    now_iso = now.isoformat()
    exp_iso = exp.isoformat()

    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO auth_sessions (token_hash, user_id, account_id, is_admin, boot_id, device_id, created_at, expires_at, last_seen_at)
                VALUES (:th, 1, 1, 1, 'boot-A', NULL, :now, :exp, :now)
            """),
            {"th": th, "now": now_iso, "exp": exp_iso},
        )
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        # revoked column may be required
        try:
            db.execute(
                text("""
                    INSERT INTO auth_sessions (token_hash, user_id, account_id, is_admin, boot_id, device_id, created_at, expires_at, last_seen_at, revoked)
                    VALUES (:th, 1, 1, 1, 'boot-A', NULL, :now, :exp, :now, 0)
                """),
                {"th": th, "now": now_iso, "exp": exp_iso},
            )
            db.commit()
        except Exception:
            db.rollback()
            pytest.skip("auth_sessions schema or user_id=1 not available")
    finally:
        db.close()

    # Validate with Bearer token: must succeed (no boot_id filter in WHERE)
    whoami_resp = client.get(
        "/api/auth/whoami",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert whoami_resp.status_code == 200, whoami_resp.text
    assert whoami_resp.json().get("user_id") == 1

    # Cleanup
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM auth_sessions WHERE token_hash = :th"), {"th": th})
        db.commit()
    finally:
        db.close()


def test_require_auth_returns_401_when_token_missing(client: TestClient):
    """No Authorization and no cookie -> 401 UNAUTHORIZED."""
    resp = client.get("/api/auth/whoami")
    assert resp.status_code == 401
    data = resp.json()
    detail = data.get("detail", {})
    code = (
        detail.get("error_code") if isinstance(detail, dict) else data.get("error_code")
    )
    assert code == "UNAUTHORIZED"


def test_logout_invalidates_session(client: TestClient):
    """Login -> whoami 200 -> logout -> whoami 401."""
    username = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    password = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not username or not password:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD to run auth test")

    login_resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
    )
    assert login_resp.status_code == 200, login_resp.text
    data = login_resp.json()
    token = data.get("token")
    account_id = data.get("user", {}).get("account_id") or 1

    whoami_resp = client.get(
        "/api/auth/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert whoami_resp.status_code == 200

    logout_resp = client.post(
        "/api/auth/logout",
        json={"account_id": account_id},
        headers={"Authorization": f"Bearer {token}"},
        cookies=login_resp.cookies,
    )
    assert logout_resp.status_code == 200

    whoami_after = client.get(
        "/api/auth/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert whoami_after.status_code == 401
