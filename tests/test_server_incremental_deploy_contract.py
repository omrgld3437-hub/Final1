from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "sunucuya-yayinla.command"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_deploy_uses_content_incremental_rsync() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    assert "RSYNC_COMMON_ARGS=(" in source
    assert "\n  -rltz\n" in source
    assert "rsync -az" not in source
    assert "--no-perms --no-owner --no-group" in source
    assert "--omit-dir-times" in source
    assert "--delete-after" in source
    assert "--delay-updates" in source
    assert "--dry-run --itemize-changes" in source
    assert "--delete-excluded" not in source
    assert "systemctl stop '${APP_NAME}-worker'" not in source
    assert 'CODE_CHANGED=0' in source
    assert 'RUNTIME_CHANGED=0' in source
    assert 'if [ "\\${RUNTIME_CHANGED}" = "1" ]; then' in source
    assert 'CONFIG_CHANGED=0' in source
    assert 'DOMAIN_CONFIG_CHANGED=' in source
    assert 'elif [ "\\${CONFIG_CHANGED}" = "1" ]; then' in source
    assert "--exclude '.ruff_cache/'" in source


def test_dependencies_are_installed_only_when_requirements_change() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    assert 'REQUIREMENTS_STAMP="\\${APP_ROOT}/.requirements.sha256"' in source
    assert 'sha256sum "\\${REMOTE_DIR}/requirements.txt"' in source
    assert "Python bagimliliklari degismedi; kurulum atlandi." in source


def test_live_database_is_backed_up_before_migrations() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    backup_index = source.index('source.backup(target)')
    migration_index = source.index("alembic upgrade head")
    assert backup_index < migration_index
    assert 'PRAGMA quick_check' in source
    assert 'final1-data-\\${BACKUP_STAMP}.sqlite.gz' in source


def test_retired_domain_is_absent_from_production_configuration() -> None:
    production_files = (
        ".env",
        "app/main.py",
        "deploy/sunucuya-yayinla.command",
        "deploy/sunucu-kurulum-final1.sh",
        "deploy/nginx-final1-server.conf",
        "sunucu/ayarlar.env.example",
        "sunucu/ssl-sertifikalarini-guncelle.command",
        "ui/robots.txt",
        "ui/sitemap.xml",
    )

    for path in production_files:
        assert "tradertrailing.com" not in _read(path), path


def test_default_live_domains_are_ayserose_and_omeraltin() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    assert 'EXPECTED_PROJECT_DIR="${EXPECTED_PROJECT_DIR:-ayserose1}"' in source
    assert 'FRONTEND_ONLY="${FRONTEND_ONLY:-0}"' in source
    assert '(cd "${DASHBOARD_DIR}" && npm run verify)' in source
    assert '"${PROJECT_ROOT}/ui/assets/v2/dashboard/index.html"' in source
    assert '"${PROJECT_ROOT}/ui/"' in source
    assert '"${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/ui/"' in source
    assert 'SERVER_NAMES="${SERVER_NAMES:-ayserose.com www.ayserose.com}"' in source
    assert (
        'MARKETING_SERVER_NAMES="${MARKETING_SERVER_NAMES:-omeraltin.com www.omeraltin.com}"'
        in source
    )
