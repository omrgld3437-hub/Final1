"""
Security headers and CSP middleware. Feature-flagged; report-only CSP by default.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def _get_security_config():
    try:
        from app.core.config import get_security_config
        return get_security_config()
    except Exception:
        return {}


def _build_csp_directives(cfg: dict) -> str:
    """Build CSP header value. default-src 'self'; style allows unsafe-inline when enabled."""
    parts = [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self' https: wss:",
    ]
    style_src = "style-src 'self'"
    if cfg.get("csp_allow_inline_scripts"):
        style_src += " 'unsafe-inline'"
    parts.append(style_src)

    script_parts = ["'self'"]
    if cfg.get("csp_allow_inline_scripts"):
        script_parts.append("'unsafe-inline'")
    if cfg.get("csp_allow_unsafe_eval"):
        script_parts.append("'unsafe-eval'")
    parts.append("script-src " + " ".join(script_parts))
    return "; ".join(parts)


async def security_headers_middleware(request: Request, call_next) -> Response:
    """Add security headers and optional CSP (report-only first)."""
    cfg = _get_security_config()
    if not cfg.get("security_headers_enabled", True):
        return await call_next(request)

    response = await call_next(request)

    # Standard security headers (SAMEORIGIN: bot detay sayfasında chart.html iframe ile açılabilsin)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    # HSTS only when HTTPS (middleware sees request.url.scheme)
    if cfg.get("hsts_enabled") and getattr(request.url, "scheme", "") == "https":
        max_age = cfg.get("hsts_max_age", 31536000)
        response.headers["Strict-Transport-Security"] = f"max-age={max_age}; includeSubDomains"

    # CSP
    if cfg.get("csp_enabled"):
        csp_value = _build_csp_directives(cfg)
        if cfg.get("csp_report_only", True):
            response.headers["Content-Security-Policy-Report-Only"] = csp_value
        else:
            response.headers["Content-Security-Policy"] = csp_value

    return response
