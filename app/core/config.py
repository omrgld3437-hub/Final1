"""
Central env config parsing. All config constants overridable by env.
"""
import os
from typing import Optional


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
        "auth_cookie_max_age_sec": _int("AUTH_COOKIE_MAX_AGE_SEC", 604800),
        "auth_rate_limit_enabled": _bool("AUTH_RATE_LIMIT_ENABLED", "1"),
        "auth_rate_limit_login_per_ip_5min": _int("AUTH_RATE_LIMIT_LOGIN_PER_IP_5MIN", 20),
        "auth_rate_limit_login_per_user_5min": _int("AUTH_RATE_LIMIT_LOGIN_PER_USER_5MIN", 10),
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
        "database_role": (os.environ.get("DATABASE_ROLE") or os.environ.get("ROLE") or "web").strip().lower(),
        "process_role": (os.environ.get("PROCESS_ROLE") or "api").strip().lower(),
        "snapshot_fields_enabled": os.environ.get("SNAPSHOT_FIELDS_ENABLED", "1").strip().lower() in ("1", "true", "yes"),
        "snapshot_trim_enabled": os.environ.get("SNAPSHOT_TRIM_ENABLED", "1").strip().lower() in ("1", "true", "yes"),
        # Flash Home (mobile-first) – Patch H
        "flash_home_enabled": os.environ.get("FLASH_HOME_ENABLED", "true").strip().lower() in ("1", "true", "yes"),
        "home_fast_cache_ttl_sec": int(os.environ.get("HOME_FAST_CACHE_TTL_SEC", "2")),
        "wallet_live_ttl_sec": int(os.environ.get("WALLET_LIVE_TTL_SEC", "5")),
        "wallet_cooldown_sec": int(os.environ.get("WALLET_COOLDOWN_SEC", "30")),
        "home_fast_max_assets": int(os.environ.get("HOME_FAST_MAX_ASSETS", "20")),
        "home_fast_warn_bytes": int(os.environ.get("HOME_FAST_WARN_BYTES", "200000")),
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
