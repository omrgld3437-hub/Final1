"""
CSRF protection for cookie-authenticated state-changing requests.
Origin/Referer check; optional double-submit token. Bearer-auth requests bypass.
"""
import logging
from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Routes that never require CSRF (no session yet or explicit exempt)
CSRF_EXEMPT_PATHS = frozenset([
    "/api/auth/login",
    "/api/auth/register",
    "/api/log-error",  # frontend hata raporu — CSRF yüzünden sessizce düşmesin
])
# Paths where we only do Origin check (e.g. logout); double-submit not required if not enabled
CSRF_ORIGIN_ONLY_PATHS = frozenset(["/api/auth/logout"])


def _get_security_config():
    try:
        from app.core.config import get_security_config
        return get_security_config()
    except Exception:
        return {}


def _allowed_hosts(request: Request, cfg: dict) -> set:
    """Allowed host names for Origin/Referer check."""
    hosts = set()
    host = request.headers.get("host") or ""
    if host:
        # strip port for comparison
        hosts.add(host.split(":")[0] if ":" in host else host)
    base = (cfg.get("public_base_url") or "").strip()
    if base:
        try:
            p = urlparse(base if "://" in base else "https://" + base)
            if p.hostname:
                hosts.add(p.hostname)
        except Exception:
            pass
    hosts.add("localhost")
    hosts.add("127.0.0.1")
    return hosts


def _origin_ok(origin: str, allowed: set) -> bool:
    if not origin or not origin.startswith("http"):
        return False
    try:
        p = urlparse(origin)
        host = (p.hostname or "").lower()
        return host in allowed or any(host == a.lower() for a in allowed)
    except Exception:
        return False


def _referer_ok(referer: str, allowed: set) -> bool:
    if not referer or not referer.startswith("http"):
        return False
    try:
        p = urlparse(referer)
        host = (p.hostname or "").lower()
        return host in allowed or any(host == a.lower() for a in allowed)
    except Exception:
        return False


async def csrf_middleware(request: Request, call_next):
    """Enforce CSRF for cookie-authenticated POST/PUT/PATCH/DELETE. Bearer bypass."""
    cfg = _get_security_config()
    if not cfg.get("auth_csrf_enabled", True):
        return await call_next(request)

    method = getattr(request, "method", "GET") or "GET"
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return await call_next(request)

    path = (request.url.path or "").rstrip("/")
    if path in CSRF_EXEMPT_PATHS:
        return await call_next(request)

    origin_only = path in CSRF_ORIGIN_ONLY_PATHS

    # Determine auth source: Bearer first, then cookie
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization") or ""
    bearer_token = (auth_header[7:].strip() if auth_header.startswith("Bearer ") else None) or ""
    cookie_token = (request.cookies.get("auth_token") or "").strip()

    if bearer_token and cfg.get("auth_allow_bearer", True):
        try:
            request.state.auth_source = "bearer"
        except Exception:
            pass
        return await call_next(request)

    if cookie_token:
        try:
            request.state.auth_source = "cookie"
        except Exception:
            pass
    else:
        # No cookie auth; no CSRF to enforce
        return await call_next(request)

    # Cookie-authenticated state-changing request: apply CSRF
    allowed = _allowed_hosts(request, cfg)
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()

    if cfg.get("auth_csrf_origin_check"):
        if origin:
            if not _origin_ok(origin, allowed):
                rid = getattr(request.state, "request_id", None)
                logger.warning("CSRF Origin mismatch request_id=%s path=%s origin=%s", rid, path, origin[:80])
                return JSONResponse(
                    status_code=403,
                    content={
                        "error_code": "CSRF_BLOCKED",
                        "message": "Origin not allowed",
                        "request_id": rid,
                    },
                )
        elif referer:
            if not _referer_ok(referer, allowed):
                rid = getattr(request.state, "request_id", None)
                logger.warning("CSRF Referer mismatch request_id=%s path=%s", rid, path)
                return JSONResponse(
                    status_code=403,
                    content={
                        "error_code": "CSRF_BLOCKED",
                        "message": "Referer not allowed",
                        "request_id": rid,
                    },
                )
        elif cfg.get("auth_csrf_origin_check_strict"):
            rid = getattr(request.state, "request_id", None)
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "CSRF_BLOCKED",
                    "message": "Origin or Referer required",
                    "request_id": rid,
                },
            )
        else:
            logger.debug("CSRF: Origin and Referer missing (allowed when not strict) request_id=%s", getattr(request.state, "request_id", None))

    if cfg.get("auth_csrf_double_submit") and not origin_only:
        csrf_cookie = (request.cookies.get("csrf_token") or "").strip()
        csrf_header = (request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            rid = getattr(request.state, "request_id", None)
            logger.warning("CSRF double-submit mismatch request_id=%s path=%s", rid, path)
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "CSRF_BLOCKED",
                    "message": "Invalid CSRF token",
                    "request_id": rid,
                },
            )

    return await call_next(request)
