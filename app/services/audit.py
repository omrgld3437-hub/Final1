"""
FILE: audit.py
VERSION: v1
DATE: 2026-01-26
CHANGE: Audit log / işlem geçmişi - user + admin güvenlik logları.
        Sadece kritik aksiyonlar loglanır; market data poll vb. loglanmaz.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import AuditEvent

logger = logging.getLogger(__name__)

# meta_json içine ASLA yazılmayacak anahtarlar
_FORBIDDEN_META_KEYS = frozenset({"api_secret", "password", "password_hash", "token", "secret"})


def _sanitize_meta(meta: Optional[dict[str, Any]]) -> Optional[str]:
    """meta dict'i JSON string'e çevirir; hassas alanları dışarıda bırakır."""
    if not meta:
        return None
    if not isinstance(meta, dict):
        return str(meta)[:2000]
    out = {}
    for k, v in meta.items():
        k_lower = k.lower()
        if any(f in k_lower for f in _FORBIDDEN_META_KEYS):
            continue
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, (list, dict)):
            try:
                out[k] = v
            except Exception:
                out[k] = "[truncated]"
        else:
            out[k] = str(v)[:200]
    try:
        return json.dumps(out, ensure_ascii=False)[:8000]
    except Exception:
        return str(out)[:8000]


def log_event(
    db: Session,
    *,
    actor_type: str,  # "user" | "admin" | "system"
    event_type: str,
    severity: str = "INFO",  # INFO | WARN | CRITICAL
    actor_user_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    ip: Optional[str] = None,
    ip_masked: bool = False,
    device_id: Optional[str] = None,
    user_agent_hash: Optional[str] = None,
    request_id: Optional[str] = None,
    session_token_prefix: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    admin_reason: Optional[str] = None,
) -> Optional[int]:
    """
    Tek bir audit event kaydı yazar. Performans: basit INSERT; sadece güvenlik/kritik aksiyonlarda çağrılır.
    Returns: AuditEvent.id or None on error.
    """
    if actor_type not in ("user", "admin", "system"):
        actor_type = "system"
    if severity not in ("INFO", "WARN", "CRITICAL"):
        severity = "INFO"
    try:
        ev = AuditEvent(
            created_at=datetime.utcnow(),
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            target_account_id=target_account_id,
            event_type=event_type,
            severity=severity,
            ip=ip[:50] if ip else None,
            ip_masked=bool(ip_masked),
            device_id=device_id[:64] if device_id else None,
            user_agent_hash=user_agent_hash[:64] if user_agent_hash else None,
            request_id=request_id[:64] if request_id else None,
            session_token_prefix=session_token_prefix[:16] if session_token_prefix else None,
            meta_json=_sanitize_meta(meta),
            admin_reason=admin_reason[:255] if admin_reason else None,
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return ev.id
    except Exception as e:
        logger.warning("audit log_event failed: %s", e)
        db.rollback()
        return None
