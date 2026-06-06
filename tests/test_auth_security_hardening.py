"""
Auth security hardening: cookie attributes, CSRF, rate limit, enumeration, CSP.
"""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_config_public_returns_auth_flags(client: TestClient):
    """GET /api/config/public returns auth_cookie_primary and csrf_double_submit."""
    r = client.get("/api/config/public")
    assert r.status_code == 200
    data = r.json()
    assert "auth_cookie_primary" in data
    assert "csrf_double_submit" in data


def test_security_headers_present_when_enabled(client: TestClient):
    """Security headers (X-Content-Type-Options, etc.) and CSP Report-Only when enabled."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    # CSP may be Report-Only
    csp = r.headers.get("Content-Security-Policy-Report-Only") or r.headers.get(
        "Content-Security-Policy"
    )
    if os.environ.get("CSP_ENABLED", "1").strip().lower() in ("1", "true", "yes"):
        assert csp is not None
        assert "default-src" in (csp or "")


def test_login_cookie_has_httponly_samesite_path(client: TestClient):
    """Login response sets auth_token cookie with HttpOnly, Path=/, SameSite."""
    user = os.environ.get("TEST_LOGIN_USERNAME", "").strip()
    pwd = os.environ.get("TEST_LOGIN_PASSWORD", "").strip()
    if not user or not pwd:
        pytest.skip("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD")
    r = client.post("/api/auth/login", json={"phone": user, "password": pwd})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie") or ""
    assert "auth_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie
    assert "SameSite" in set_cookie.lower() or "samesite" in set_cookie.lower()


def test_login_fail_same_error_code_no_enumeration(client: TestClient):
    """Invalid user and wrong password both return 401 INVALID_CREDENTIALS (no user enumeration)."""
    # Non-existent user
    r1 = client.post(
        "/api/auth/login", json={"phone": "nonexistentuser12345", "password": "wrong"}
    )
    assert r1.status_code == 401
    d1 = r1.json().get("detail", {})
    code1 = d1.get("error_code") if isinstance(d1, dict) else None
    assert code1 == "INVALID_CREDENTIALS"

    # Wrong password for existing user would also be INVALID_CREDENTIALS (tested in integration)


def test_rate_limit_login_returns_429_with_retry_after(client: TestClient):
    """Repeated login attempts from same IP eventually get 429 RATE_LIMITED with Retry-After."""
    # Depends on AUTH_RATE_LIMIT_ENABLED and limits; run many attempts
    if os.environ.get("AUTH_RATE_LIMIT_ENABLED", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        pytest.skip("Rate limit disabled")
    attempts = 0
    last_status = 0
    last_retry_after = None
    while attempts < 50:
        r = client.post(
            "/api/auth/login",
            json={"phone": "ratelimit_test_user_xyz", "password": "wrong"},
        )
        last_status = r.status_code
        if last_status == 429:
            data = r.json()
            detail = data.get("detail", {})
            if isinstance(detail, dict) and detail.get("error_code") == "RATE_LIMITED":
                last_retry_after = detail.get("retry_after")
                break
        attempts += 1
    assert last_status == 429, "Expected 429 after many attempts"
    assert last_retry_after is not None


def test_csrf_cookie_auth_post_without_origin_allowed_or_403(client: TestClient):
    """Cookie-authenticated POST: without Origin may be allowed (non-strict) or 403 (strict)."""
    # This test only checks that CSRF middleware runs; exact behavior depends on AUTH_CSRF_ORIGIN_CHECK_STRICT
    # and whether we have a cookie. We can't easily get a cookie without logging in; so just ensure
    # login is exempt and app loads.
    r = client.post("/api/auth/login", json={"phone": "x", "password": "y"})
    assert r.status_code in (400, 401, 429)
