from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_account_or_403, require_auth
from app.db.models import WebPushSubscription
from app.db.session import get_db
from app.services.web_push_notifications import get_vapid_public_key


router = APIRouter(prefix="/push", tags=["push-notifications"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=16, max_length=512)
    auth: str = Field(min_length=8, max_length=256)


class PushSubscriptionBody(BaseModel):
    account_id: int
    endpoint: str = Field(min_length=20, max_length=4096)
    keys: PushKeys


class PushUnsubscribeBody(BaseModel):
    account_id: int
    endpoint: str = Field(min_length=20, max_length=4096)


@router.get("/vapid-public-key")
async def vapid_public_key(current: dict = Depends(require_auth)):
    return {"public_key": get_vapid_public_key()}


@router.post("/subscriptions")
async def subscribe(
    body: PushSubscriptionBody,
    request: Request,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    account = get_account_or_403(current, body.account_id, db)
    user_id = int(current.get("user_id") or 0)
    if user_id <= 0 or int(account.user_id or 0) != user_id:
        raise HTTPException(status_code=403, detail="Bildirim aboneliği yalnız hesap sahibi tarafından açılabilir.")
    row = db.query(WebPushSubscription).filter(WebPushSubscription.endpoint == body.endpoint).first()
    now = datetime.utcnow()
    if row is None:
        row = WebPushSubscription(endpoint=body.endpoint, created_at=now)
        db.add(row)
    row.user_id = user_id
    row.account_id = body.account_id
    row.p256dh = body.keys.p256dh
    row.auth = body.keys.auth
    row.user_agent = (request.headers.get("user-agent") or "")[:500]
    row.last_seen_at = now
    row.revoked_at = None
    db.commit()
    return {"ok": True, "enabled": True}


@router.delete("/subscriptions")
async def unsubscribe(
    body: PushUnsubscribeBody,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    get_account_or_403(current, body.account_id, db)
    row = (
        db.query(WebPushSubscription)
        .filter(
            WebPushSubscription.endpoint == body.endpoint,
            WebPushSubscription.user_id == int(current.get("user_id") or 0),
            WebPushSubscription.account_id == body.account_id,
        )
        .first()
    )
    if row:
        row.revoked_at = datetime.utcnow()
        db.commit()
    return {"ok": True, "enabled": False}
