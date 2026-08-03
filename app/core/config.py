"""
Central env config parsing. All config constants overridable by env.
"""

import os
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse


def get_security_config() -> dict:
    """Security/auth hardening flags and limits. Safe defaults; no breaking changes."""

    def _bool(key: str, default: str = "1") -> bool:
        return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")

    def _int(key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)).strip())
        except ValueError:
            return default

    def _str(key: str, default: str) -> str:
        return (os.environ.get(key, default) or default).strip()

    return {
        "auth_cookie_primary": _bool("AUTH_COOKIE_PRIMARY", "0"),
        "auth_allow_bearer": _bool("AUTH_ALLOW_BEARER", "1"),
        "auth_legacy_token_response": _bool("AUTH_LEGACY_TOKEN_RESPONSE", "0"),
        "auth_csrf_enabled": _bool("AUTH_CSRF_ENABLED", "1"),
        "auth_csrf_origin_check": _bool("AUTH_CSRF_ORIGIN_CHECK", "1"),
        "auth_csrf_origin_check_strict": _bool("AUTH_CSRF_ORIGIN_CHECK_STRICT", "0"),
        "auth_csrf_double_submit": _bool("AUTH_CSRF_DOUBLE_SUBMIT", "0"),
        "auth_cookie_secure_auto": _bool("AUTH_COOKIE_SECURE_AUTO", "1"),
        "auth_cookie_samesite": _str("AUTH_COOKIE_SAMESITE", "Lax"),
        "auth_cookie_max_age_sec": _int(
            "AUTH_COOKIE_MAX_AGE_SEC", 3650 * 24 * 60 * 60
        ),
        "auth_rate_limit_enabled": _bool("AUTH_RATE_LIMIT_ENABLED", "1"),
        "auth_rate_limit_login_per_ip_5min": _int(
            "AUTH_RATE_LIMIT_LOGIN_PER_IP_5MIN", 20
        ),
        "auth_rate_limit_login_per_user_5min": _int(
            "AUTH_RATE_LIMIT_LOGIN_PER_USER_5MIN", 10
        ),
        "auth_rate_limit_global_burst": _int("AUTH_RATE_LIMIT_GLOBAL_BURST", 60),
        "security_headers_enabled": _bool("SECURITY_HEADERS_ENABLED", "1"),
        "csp_enabled": _bool("CSP_ENABLED", "1"),
        "csp_report_only": _bool("CSP_REPORT_ONLY", "1"),
        "csp_allow_inline_scripts": _bool("CSP_ALLOW_INLINE_SCRIPTS", "1"),
        "csp_allow_unsafe_eval": _bool("CSP_ALLOW_UNSAFE_EVAL", "0"),
        "hsts_enabled": _bool("HSTS_ENABLED", "1"),
        "hsts_max_age": _int("HSTS_MAX_AGE", 31536000),
        "public_base_url": _str("PUBLIC_BASE_URL", ""),
    }


def get_config() -> dict:
    """Return config dict from env (single place to parse env)."""
    return {
        "default_lease_ttl_sec": int(os.environ.get("DEFAULT_LEASE_TTL_SEC", "10")),
        "lock_heartbeat_sec": int(os.environ.get("LOCK_HEARTBEAT_SEC", "3")),
        "max_snapshot_bytes": int(os.environ.get("MAX_SNAPSHOT_BYTES", "500000")),
        "database_role": (
            os.environ.get("DATABASE_ROLE") or os.environ.get("ROLE") or "web"
        )
        .strip()
        .lower(),
        "process_role": (os.environ.get("PROCESS_ROLE") or "api").strip().lower(),
        "snapshot_fields_enabled": os.environ.get("SNAPSHOT_FIELDS_ENABLED", "1")
        .strip()
        .lower()
        in ("1", "true", "yes"),
        "snapshot_trim_enabled": os.environ.get("SNAPSHOT_TRIM_ENABLED", "1")
        .strip()
        .lower()
        in ("1", "true", "yes"),
        # Flash Home (mobile-first) – Patch H
        "flash_home_enabled": os.environ.get("FLASH_HOME_ENABLED", "true")
        .strip()
        .lower()
        in ("1", "true", "yes"),
        "home_fast_cache_ttl_sec": int(os.environ.get("HOME_FAST_CACHE_TTL_SEC", "2")),
        "wallet_live_ttl_sec": int(os.environ.get("WALLET_LIVE_TTL_SEC", "5")),
        "wallet_cooldown_sec": int(os.environ.get("WALLET_COOLDOWN_SEC", "30")),
        "wallet_snapshot_warn_age_sec": float(
            os.environ.get("WALLET_SNAPSHOT_WARN_AGE_SEC", "900")
        ),
        "home_fast_max_assets": int(os.environ.get("HOME_FAST_MAX_ASSETS", "20")),
        "home_fast_warn_bytes": int(os.environ.get("HOME_FAST_WARN_BYTES", "200000")),
    }


_LOCAL_DEV_ORIGINS = (
    "http://localhost",
    "http://localhost:8000",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
)


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _normalize_origin(origin: str) -> Optional[str]:
    raw = (origin or "").strip().rstrip(";,)")
    raw = raw.rstrip("/")
    if not raw or raw == "*":
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def discover_frontend_origins(project_root: Optional[Path] = None) -> List[str]:
    """Best-effort production origin discovery from env/docs/deploy files."""
    root = project_root or Path(__file__).resolve().parents[2]
    candidates: List[str] = []
    for key in ("PUBLIC_BASE_URL", "FRONTEND_URL", "SITE_URL", "WEB_ORIGIN"):
        candidates.extend(_split_csv(os.environ.get(key, "")))
    for rel in (
        "deploy/nginx-final1-server.conf",
        "ui/robots.txt",
        "marketing/robots.txt",
        "marketing/vercel.json",
        ".env",
        ".env.example",
    ):
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        candidates.extend(
            re.findall(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,=%-]+", text)
        )
        for server_name_line in re.findall(r"server_name\s+([^;]+);", text):
            for host in server_name_line.split():
                host = host.strip()
                if host and not host.startswith("_") and "." in host:
                    candidates.append(f"https://{host}")
    seen = set()
    out: List[str] = []
    for item in candidates:
        normalized = _normalize_origin(item)
        if not normalized:
            continue
        host = urlparse(normalized).hostname or ""
        if "." not in host:
            continue
        if host.endswith(
            (
                "googleapis.com",
                "gstatic.com",
                "binance.com",
                "registry.npmjs.org",
                "github.com",
            )
        ):
            continue
        if host in ("localhost", "127.0.0.1", "0.0.0.0"):
            continue
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def get_cors_config() -> dict:
    """Production CORS: explicit origins only; development falls back to localhost."""
    app_env = (
        (os.environ.get("APP_ENV") or os.environ.get("ENV") or "development")
        .strip()
        .lower()
    )
    is_prod = app_env in ("prod", "production", "staging")
    raw_origins = _split_csv(os.environ.get("ALLOWED_ORIGINS", ""))
    origins: List[str] = []
    invalid: List[str] = []
    for raw in raw_origins:
        normalized = _normalize_origin(raw)
        if normalized:
            origins.append(normalized)
        else:
            invalid.append(raw)
    if not origins and not is_prod:
        origins = list(_LOCAL_DEV_ORIGINS)
    seen = set()
    origins = [o for o in origins if not (o in seen or seen.add(o))]
    return {
        "environment": app_env,
        "is_production": is_prod,
        "allow_origins": origins,
        "allow_credentials": True,
        "invalid_origins": invalid,
        "suggested_origins": discover_frontend_origins(),
    }


def is_worker_role() -> bool:
    """True if this process is allowed to place orders (worker only)."""
    cfg = get_config()
    role = cfg.get("database_role", "web")
    proc = cfg.get("process_role", "api")
    if role == "worker":
        return True
    if proc in ("web", "api"):
        return False
    return role == "worker"
