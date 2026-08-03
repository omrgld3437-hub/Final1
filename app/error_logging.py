"""
Merkezi hata kaydı – backend, frontend, Binance, arayüz hatalarını error_logs tablosuna yazar.
Admin panelde listelenir ve yeni hata popup ile bildirilir.
"""

import json
import logging
from typing import Optional, Any, Dict

from app.db.models import ErrorLog

logger = logging.getLogger(__name__)


def _mirror_to_hata_log(
    *,
    level: str,
    source: str,
    message: str,
    detail: Optional[str],
    path: Optional[str],
    method: Optional[str],
    request_id: Optional[str],
    account_id: Optional[int],
) -> None:
    """error_logs'a yazılan hatayı kök klasördeki HATALAR.log'a da yansıt.

    Frontend raporları ve Binance hataları logging üzerinden geçmediği için
    root handler onları görmez; tek dosyada tüm hataların bulunması bu yansıtmaya
    bağlı.
    """
    try:
        from app.observability.hata_log import kaydet

        extra = {}
        if method:
            extra["method"] = method
        if request_id:
            extra["request_id"] = request_id
        if account_id is not None:
            extra["account_id"] = account_id
        kaydet(
            level or "error",
            source or "unknown",
            message,
            detail=detail,
            path=path,
            extra=extra or None,
        )
    except Exception:
        pass


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
                db,
                source,
                message,
                detail=detail,
                context=context,
                level="error",
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
        clean_message = str(message or "").strip()
        if not clean_message and (source or "").strip().lower() == "binance":
            ctx = context or {}
            request_path = str(ctx.get("path") or "").strip()
            request_method = str(ctx.get("method") or "REQUEST").strip().upper()
            clean_message = (
                f"Binance {request_method} {request_path} isteği başarısız"
                if request_path
                else "Binance isteği başarısız"
            )
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        if detail and len(detail) > 16000:
            detail = detail[:16000] + "..."
        if len(clean_message) > 8000:
            clean_message = clean_message[:8000] + "..."
        row = ErrorLog(
            source=source[:32] if source else "unknown",
            level=level[:16] if level else "error",
            message=clean_message or "(no message)",
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
        _mirror_to_hata_log(
            level=level,
            source=source,
            message=clean_message,
            detail=detail,
            path=path,
            method=method,
            request_id=request_id,
            account_id=account_id,
        )
        return row.id
    except Exception as e:
        logger.warning("error_logging persist_error failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
