"""
Kullanıcı işlem geçmişi API — frontend beacon ve admin görüntüleme.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.auth import get_client_ip, require_auth
from app.db.session import get_db
from app.services.user_readable_activity_logger import (
    UserReadableActivityLogger,
    read_user_log_lines,
    resolve_user_identity,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_PAGE_LABELS = {
    "dashboard": "Dashboard",
    "param-assistant": "Parametre Asistanı",
    "dynamic-mode": "Dinamik Mod",
    "bot-settings": "Bot Ayarları",
    "bot-history": "Bot Geçmişi",
    "settings": "Ayarlar",
    "support": "Destek",
    "reports": "Raporlar",
    "admin": "Admin",
}


class ActivityBeaconRequest(BaseModel):
    event_type: str = Field(..., max_length=64)
    page: Optional[str] = Field(None, max_length=64)
    screen: Optional[str] = Field(None, max_length=64)
    symbol: Optional[str] = Field(None, max_length=32)
    budget: Optional[float] = None
    action: Optional[str] = Field(None, max_length=500)
    result: Optional[str] = Field(None, max_length=500)
    context: Optional[Dict[str, Any]] = None
    abandonment: Optional[Dict[str, Any]] = None


def _require_admin(current: dict) -> dict:
    if not current.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli.")
    return current


@router.post("/user-activity/beacon")
async def activity_beacon(
    req: ActivityBeaconRequest,
    current: dict = Depends(require_auth),
):
    """Frontend sayfa/sekme/vazgeçme olayları."""
    user_id = current.get("user_id")
    if not user_id:
        return {"ok": True}
    ctx: Dict[str, Any] = dict(req.context or {})
    if req.page:
        ctx["page"] = _PAGE_LABELS.get(req.page, req.page)
    if req.symbol:
        ctx["symbol"] = req.symbol.upper()
    if req.budget is not None:
        ctx["budget"] = req.budget

    if req.abandonment:
        ab = req.abandonment
        ab_type = str(ab.get("type") or "").upper()
        if ab_type == "COIN_NO_ANALYSIS":
            UserReadableActivityLogger.write_event(
                user_id, "ABANDON_COIN_NO_ANALYSIS", context=ctx
            )
        elif ab_type == "BUDGET_NO_ANALYSIS":
            UserReadableActivityLogger.write_event(
                user_id, "ABANDON_BUDGET_NO_ANALYSIS", context=ctx
            )
        elif ab_type == "PARAM_NO_APPROVE":
            UserReadableActivityLogger.write_event(
                user_id, "ABANDON_PARAM_NO_APPROVE", context=ctx
            )
        elif ab_type == "BOT_NO_START":
            UserReadableActivityLogger.write_event(
                user_id, "ABANDON_BOT_NO_START", context=ctx
            )
        elif ab_type == "MESSAGE_UNSENT":
            UserReadableActivityLogger.write_event(
                user_id, "ABANDON_MESSAGE_UNSENT", context=ctx
            )
        return {"ok": True}

    event = req.event_type.upper()
    if event == "PAGE_VIEW" and req.page:
        ctx["page"] = _PAGE_LABELS.get(req.page, req.page)

    UserReadableActivityLogger.write_event(
        user_id,
        event,
        context=ctx,
        screen=req.screen,
        action=req.action,
        result=req.result,
    )
    return {"ok": True}


@router.get("/admin/user-activity-logs")
async def admin_list_user_activity_logs(
    user_id: int = Query(..., ge=1),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    screen: Optional[str] = Query(None),
    coin: Optional[str] = Query(None),
    result_filter: Optional[str] = Query(None, alias="result"),
    limit: int = Query(500, ge=1, le=2000),
    current: dict = Depends(require_auth),
    db=Depends(get_db),
):
    _require_admin(current)
    uid, name, surname = resolve_user_identity(db, user_id=user_id)
    if not uid:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

    lines = read_user_log_lines(
        uid,
        name=name,
        surname=surname,
        from_date=from_date,
        to_date=to_date,
        screen=screen,
        coin=coin,
        result_filter=result_filter,
        limit=limit,
    )

    admin_id = current.get("user_id")
    if admin_id:
        UserReadableActivityLogger.write_event(
            int(admin_id),
            "ADMIN_LOG_VIEWED",
            context={"target_user_id": uid},
        )

    return {
        "ok": True,
        "user_id": uid,
        "name": name,
        "surname": surname,
        "count": len(lines),
        "lines": lines,
    }


@router.get("/admin/user-activity-logs/download")
async def admin_download_user_activity_logs(
    user_id: int = Query(..., ge=1),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    screen: Optional[str] = Query(None),
    coin: Optional[str] = Query(None),
    result_filter: Optional[str] = Query(None, alias="result"),
    current: dict = Depends(require_auth),
    db=Depends(get_db),
):
    _require_admin(current)
    uid, name, surname = resolve_user_identity(db, user_id=user_id)
    if not uid:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

    lines = read_user_log_lines(
        uid,
        name=name,
        surname=surname,
        from_date=from_date,
        to_date=to_date,
        screen=screen,
        coin=coin,
        result_filter=result_filter,
        limit=10000,
    )
    display = f"{name or ''} {surname or ''}".strip() or f"user_{uid}"
    body = "\n".join(lines) + ("\n" if lines else "")
    filename = f"islem_gecmisi_{display}_{uid}.txt"
    return PlainTextResponse(
        content=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
