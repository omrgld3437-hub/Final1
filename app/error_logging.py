"""
Merkezi hata kaydı – backend, frontend, Binance, arayüz hatalarını error_logs tablosuna yazar.
Admin panelde listelenir ve yeni hata popup ile bildirilir.
"""
import json
import logging
from typing import Optional, Any, Dict

from app.db.models import ErrorLog

logger = logging.getLogger(__name__)


def log_error_fire_and_forget(
    source: str,
    message: str,
    *,
    detail: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    İstek dışından (örn. Binance servisi) hata yazmak için. Kendi session'ını açar, persist_error çağırır.
    """
    try:
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            persist_error(
                db, source, message,
                detail=detail, context=context, level="error",
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning("log_error_fire_and_forget failed: %s", e)


def persist_error(
    db,
    source: str,
    message: str,
    *,
    detail: Optional[str] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
    request_id: Optional[str] = None,
    user_id: Optional[int] = None,
    account_id: Optional[int] = None,
    user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    is_admin: bool = False,
    level: str = "error",
) -> Optional[int]:
    """
    Hata kaydını error_logs tablosuna yazar. Returns error_log id or None.
    """
    try:
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        if detail and len(detail) > 16000:
            detail = detail[:16000] + "..."
        if message and len(message) > 8000:
            message = message[:8000] + "..."
        row = ErrorLog(
            source=source[:32] if source else "unknown",
            level=level[:16] if level else "error",
            message=message or "(no message)",
            detail=detail,
            path=path[:512] if path else None,
            method=method[:16] if method else None,
            request_id=request_id[:64] if request_id else None,
            user_id=user_id,
            account_id=account_id,
            user_agent=user_agent[:512] if user_agent else None,
            client_ip=client_ip[:50] if client_ip else None,
            context_json=context_json,
            is_admin=is_admin,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as e:
        logger.warning("error_logging persist_error failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
