"""
FILE: client_ip.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Gerçek istemci IP'sinin tek doğru kaynağı; proxy başlığı sahtekârlığına kapalı.

Neden ayrı modül: hem `app.main` middleware'leri, hem `app.api.auth`, hem
`app.api.routes` aynı mantığa ihtiyaç duyuyor. Ortak bir alt katman olmadan
import döngüsü oluşuyor.
"""

from typing import Any, Optional

from app.core.config import get_trusted_proxy_ips


def _peer_host(request: Any) -> str:
    client = getattr(request, "client", None)
    return (getattr(client, "host", "") if client else "") or ""


def _header(request: Any, name: str) -> str:
    headers = getattr(request, "headers", None)
    if not headers:
        return ""
    try:
        return (headers.get(name) or "").strip()
    except Exception:
        return ""


def client_ip_from_request(request: Any, default: Optional[str] = "unknown") -> str:
    """İstemcinin gerçek IP'si.

    Forwarding başlıkları YALNIZCA istek güvenilen bir reverse proxy'den geldiğinde
    okunur (TRUSTED_PROXY_IPS, varsayılan loopback). Aksi halde istemci kendi
    ``X-Forwarded-For`` başlığını uydurarak IP blocklist, rate limit ve IP
    whitelist kontrollerini atlatabilir.

    Nginx ``X-Real-IP``'yi her istekte ``$remote_addr`` ile ezer, bu yüzden ona
    güvenilir. ``X-Forwarded-For`` ise ``$proxy_add_x_forwarded_for`` ile eklemeli
    çalışır: istemcinin gönderdiği değerler solda kalır, proxy'nin gördüğü gerçek
    IP **en sağa** eklenir. Bu yüzden ilk eleman değil son eleman okunur.
    """
    peer = _peer_host(request)
    if peer not in get_trusted_proxy_ips():
        return peer or (default or "")

    real_ip = _header(request, "x-real-ip")
    if real_ip:
        return real_ip

    chain = [p.strip() for p in _header(request, "x-forwarded-for").split(",") if p.strip()]
    if chain:
        return chain[-1]
    return peer or (default or "")
