import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"


def test_manifest_uses_ayserose_name_and_standalone_dashboard():
    manifest = json.loads((UI / "assets" / "manifest.webmanifest").read_text())

    assert manifest["name"] == "Ayserose"
    assert manifest["short_name"] == "Ayserose"
    assert manifest["start_url"] == "/ui/dashboard.html"
    assert manifest["display"] == "standalone"


def test_pwa_icons_exist_with_exact_square_dimensions():
    expected = {
        "apple-touch-icon-180.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-512.png": (512, 512),
        "favicon-32.png": (32, 32),
    }
    for filename, size in expected.items():
        path = UI / "assets" / "pwa" / filename
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size == size
            assert image.mode in ("RGB", "RGBA")


def test_primary_pages_publish_safari_home_screen_metadata():
    for filename in ("login.html", "dashboard.html", "bot.html", "bot_multi.html", "admin.html"):
        html = (UI / filename).read_text(encoding="utf-8")
        assert "viewport-fit=cover" in html
        assert 'name="apple-mobile-web-app-title" content="Ayserose"' in html
        assert 'name="apple-mobile-web-app-capable" content="yes"' in html
        assert 'href="/ui/assets/pwa-safe-area.css?v=1"' in html
        assert "ayserose-mobile-standalone" in html
        assert 'href="/ui/assets/manifest.webmanifest"' in html
        assert 'href="/ui/assets/pwa/apple-touch-icon-180.png"' in html
        assert "/ui/assets/core/persistentAuth.js?v=1" in html


def test_mobile_standalone_safe_area_keeps_content_below_status_bar():
    css = (UI / "assets" / "pwa-safe-area.css").read_text(encoding="utf-8")

    assert "env(safe-area-inset-top, 0px)" in css
    assert "max(env(safe-area-inset-top, 0px), 12px)" in css
    assert "padding-top: var(--ayserose-pwa-safe-top) !important" in css
    assert ".page-dashboard .dashboard-appbar" in css
    assert ".page-admin .admin-appbar" in css
    assert ".page-bot .page-bot-appbar" in css


def test_dashboard_does_not_force_logout_on_safari_bfcache_restore():
    html = (UI / "dashboard.html").read_text(encoding="utf-8")
    assert "if (e.persisted)" not in html
    assert "window.__ayseroseAuthReady" in html


def test_persistent_session_defaults_are_long_lived_and_sliding(monkeypatch):
    monkeypatch.delenv("AUTH_COOKIE_MAX_AGE_SEC", raising=False)
    from app.core.config import get_security_config

    config = get_security_config()
    assert config["auth_cookie_max_age_sec"] == 3650 * 24 * 60 * 60

    auth_source = (ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")
    assert 'os.environ.get("SESSION_TTL_DAYS", "3650")' in auth_source
    assert 'os.environ.get("AUTH_SLIDING_TTL", "1")' in auth_source


def test_production_deploy_enforces_persistent_secure_cookie():
    deploy = (ROOT / "deploy" / "sunucuya-yayinla.command").read_text(
        encoding="utf-8"
    )
    setup = (ROOT / "deploy" / "sunucu-kurulum-final1.sh").read_text(
        encoding="utf-8"
    )
    for text in (deploy, setup):
        assert "SESSION_TTL_DAYS" in text
        assert "AUTH_COOKIE_MAX_AGE_SEC" in text
        assert "AUTH_SLIDING_TTL" in text
        assert "AUTH_COOKIE_SECURE" in text
