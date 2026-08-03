from __future__ import annotations

import base64
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.db.models import WebPushSubscription


logger = logging.getLogger(__name__)
_PUSH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ayserose-push")
_SUPPORTED_REASONS = {
    "trail_buy_grid": "Grid alış",
    "trail_sell_grid": "Grid satış",
    "trail_reentry_buy": "Kâr alımı",
    "trail_profit_sell": "Kâr satışı",
}


def _key_path() -> Path:
    configured = (os.environ.get("WEBPUSH_VAPID_PRIVATE_KEY_FILE") or "").strip()
    if configured:
        return Path(configured)
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("sqlite:///"):
        database_path = Path(database_url.removeprefix("sqlite:///"))
        return database_path.parent / "webpush-vapid-private.pem"
    return Path(".run/webpush-vapid-private.pem")


@lru_cache(maxsize=1)
def _vapid_material() -> tuple[str, str]:
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        if path.exists():
            private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        else:
            private_key = ec.generate_private_key(ec.SECP256R1())
            payload = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            temporary.write_bytes(payload)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    public_key = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")
    return private_pem, public_key


def get_vapid_public_key() -> str:
    return _vapid_material()[1]


def format_trade_notification(
    symbol: str,
    reason: str,
    cycle_id: int,
    *,
    new_cycle_id: Optional[int] = None,
    grid_index: Optional[int] = None,
) -> Optional[dict[str, str]]:
    operation = _SUPPORTED_REASONS.get((reason or "").strip())
    if not operation:
        return None
    clean_symbol = (symbol or "").strip().upper()
    cycle = max(1, int(cycle_id or 1))
    title = f"{clean_symbol} · {operation} gerçekleşti"
    if reason in ("trail_reentry_buy", "trail_profit_sell"):
        next_cycle = max(cycle + 1, int(new_cycle_id or cycle + 1))
        body = (
            f"{clean_symbol} için {operation.lower()} gerçekleşti. "
            f"{cycle}. tur kapandı, {next_cycle}. tur başladı."
        )
    else:
        grid_text = (
            f"{max(0, int(grid_index)) + 1}. grid "
            if grid_index is not None
            else "grid "
        )
        body = (
            f"{clean_symbol} için {grid_text}{operation.split()[-1].lower()} "
            f"gerçekleşti. {cycle}. tur devam ediyor."
        )
    return {"title": title, "body": body}


def _send(subscription: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        from pywebpush import webpush

        _vapid_material()
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=str(_key_path()),
            vapid_claims={
                "sub": os.environ.get("WEBPUSH_VAPID_SUBJECT", "https://ayserose.com")
            },
            ttl=300,
        )
    except Exception as error:
        logger.warning("WEB_PUSH_SEND_FAILED err_type=%s", type(error).__name__)


def enqueue_trade_notification(
    db: Any,
    *,
    account_id: int,
    bot_id: int,
    symbol: str,
    reason: str,
    cycle_id: int,
    new_cycle_id: Optional[int],
    grid_index: Optional[int],
    event_id: str,
) -> int:
    message = format_trade_notification(
        symbol,
        reason,
        cycle_id,
        new_cycle_id=new_cycle_id,
        grid_index=grid_index,
    )
    if not message:
        return 0
    rows = (
        db.query(WebPushSubscription)
        .filter(
            WebPushSubscription.account_id == int(account_id),
            WebPushSubscription.revoked_at.is_(None),
        )
        .all()
    )
    payload = {
        **message,
        "bot_id": int(bot_id),
        "tag": f"bot-{bot_id}-{event_id}",
        "url": f"/ui/assets/v2/dashboard/index.html?tab=bots&bot_id={int(bot_id)}",
        "icon": "/ui/assets/pwa/ayserose-plain-v4-192.png",
        "badge": "/ui/assets/pwa/favicon-32.png",
    }
    for row in rows:
        subscription = {
            "endpoint": row.endpoint,
            "keys": {"p256dh": row.p256dh, "auth": row.auth},
        }
        _PUSH_POOL.submit(_send, subscription, payload)
    return len(rows)
