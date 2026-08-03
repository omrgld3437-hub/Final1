"""
FILE: test_endpoint_auth_contract.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Kimliksiz erişilebilen para/hesap uçlarının auth sözleşmesi + proxy IP güveni.

Bu testler regresyon kilidi görevi görür: para hareketi yaratan veya hesaba özel
veri döndüren bir uç yeniden kimliksiz hale gelirse burada kırılır.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute


@pytest.fixture(scope="module")
def app_obj():
    from app.main import app

    return app


@pytest.fixture(scope="module")
def client(app_obj):
    return TestClient(app_obj)


# Kimlik doğrulaması olmadan asla erişilememesi gereken uçlar.
# (method, path, çağrı için gereken query/body)
PROTECTED = [
    ("GET", "/api/accounts", None),
    ("POST", "/api/accounts?name=x", None),
    ("GET", "/api/binance/open-orders?account_id=1", None),
    ("DELETE", "/api/binance/order?account_id=1&symbol=BTCUSDT&order_id=1", None),
    ("POST", "/api/binance/order", {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"}),
    ("GET", "/api/bots/1", None),
    ("GET", "/api/bots/1/grids", None),
    ("POST", "/api/chat/reopen", {"account_id": 1}),
    ("GET", "/api/auth/contact-history?account_id=1", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_endpoint_rejects_anonymous(client: TestClient, method, path, body):
    """Kimliksiz çağrı 401/403 dönmeli; 200 veya 404 (=iş mantığına girdi) kabul edilemez."""
    r = client.request(method, path, json=body)
    assert r.status_code in (401, 403), (
        f"{method} {path} kimliksiz erişime açık: {r.status_code} {r.text[:200]}"
    )


def test_bare_post_bots_endpoint_removed(app_obj):
    """Kimliksiz bot yaratan legacy POST /api/bots kaldırıldı."""
    paths = {
        (m, r.path)
        for r in app_obj.routes
        if isinstance(r, APIRoute)
        for m in r.methods
    }
    assert ("POST", "/api/bots") not in paths


def test_debug_endpoints_reject_proxied_requests(client: TestClient):
    """Teşhis uçları proxy üzerinden (forwarding başlığı ile) erişilemez.

    TestClient doğrudan loopback'ten gelir; forwarding başlığı eklenince istek
    proxy'lenmiş sayılır ve 404 döner.
    """
    for path in (
        "/api/debug/db-mode",
        "/api/debug/resource-usage",
        "/debug/metrics",
    ):
        r = client.get(path, headers={"X-Forwarded-For": "8.8.8.8"})
        assert r.status_code == 404, f"{path} proxy üzerinden erişilebilir: {r.status_code}"


def test_build_info_does_not_leak_absolute_paths(client: TestClient):
    """Login gerektirmeyen build-info sunucu dosya yollarını sızdırmaz."""
    r = client.get("/api/debug/build-info")
    assert r.status_code == 200
    data = r.json()
    assert "base_dir" not in data
    assert "ui_dir" not in data
    assert "dashboard_html_version" in data


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, peer, headers):
        self.client = _FakeClient(peer) if peer else None
        self.headers = headers


def test_client_ip_ignores_forwarded_headers_from_untrusted_peer():
    """Doğrudan bağlanan istemcinin uydurduğu X-Forwarded-For yok sayılır."""
    from app.core.client_ip import client_ip_from_request

    req = _FakeRequest("203.0.113.9", {"x-forwarded-for": "1.2.3.4", "x-real-ip": "1.2.3.4"})
    assert client_ip_from_request(req) == "203.0.113.9"


def test_client_ip_uses_real_ip_from_trusted_proxy():
    """Güvenilen proxy'den gelen X-Real-IP okunur (nginx her istekte ezer)."""
    from app.core.client_ip import client_ip_from_request

    req = _FakeRequest("127.0.0.1", {"x-real-ip": "198.51.100.7"})
    assert client_ip_from_request(req) == "198.51.100.7"


def test_client_ip_uses_last_forwarded_entry_not_first():
    """X-Forwarded-For eklemeli: gerçek IP son eleman, istemcinin uydurduğu ilk eleman değil."""
    from app.core.client_ip import client_ip_from_request

    req = _FakeRequest("127.0.0.1", {"x-forwarded-for": "1.2.3.4, 5.6.7.8, 198.51.100.7"})
    assert client_ip_from_request(req) == "198.51.100.7"


def test_client_ip_falls_back_to_peer_without_headers():
    from app.core.client_ip import client_ip_from_request

    req = _FakeRequest("127.0.0.1", {})
    assert client_ip_from_request(req) == "127.0.0.1"
