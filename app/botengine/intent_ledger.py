"""
Intent Ledger v5 - Exactly-once order intent execution (idempotency).
intent_id = f(bot_id, account_id, cycle_id, symbol, action_type, qty_norm, price_norm, strategy_action_hash).
client_order_id: stored on first persist; reused on every retry. Same intent_id => same clientOrderId always.
State: NEW -> PERSISTED -> SUBMITTING -> SUBMITTED/ACKED -> (PARTIAL|FILLED|CANCELED|REJECTED) -> FINAL. UNKNOWN transient until reconciled.
"""
from __future__ import annotations
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# v5 status state machine
STATUS_NEW = "NEW"
STATUS_PERSISTED = "PERSISTED"
STATUS_SUBMITTING = "SUBMITTING"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_ACKED = "ACKED"
STATUS_PARTIAL = "PARTIAL"
STATUS_FILLED = "FILLED"
STATUS_CANCELED = "CANCELED"
STATUS_REJECTED = "REJECTED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_FINAL = "FINAL"
# Legacy aliases
STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"

FINAL_STATUSES = (STATUS_FILLED, STATUS_CANCELED, STATUS_REJECTED, STATUS_FINAL)
INFLIGHT_STATUSES = (STATUS_PENDING, STATUS_SENT, STATUS_PERSISTED, STATUS_SUBMITTING, STATUS_SUBMITTED, STATUS_ACKED, STATUS_PARTIAL, STATUS_UNKNOWN)


def _intent_hash(symbol: str, side: str, qty: float, quote_qty: float, reason: str, grid_index: Optional[int] = None) -> str:
    """Deterministic hash for identical intent retries. Max 16 chars for Binance clientOrderId (36 total)."""
    payload = f"{symbol}|{side}|{qty:.10f}|{quote_qty:.10f}|{reason}|{grid_index or 0}"
    h = hashlib.sha256(payload.encode()).hexdigest()
    return h[:16]


def _run_id_segment(run_id: Optional[str]) -> str:
    """Compact run_id for client_order_id (<=36 chars total). Use last 6 alnum or base36 of cmd id."""
    if not run_id or not str(run_id).strip():
        return "0"
    s = str(run_id).strip()
    if s.startswith("cmd") and s[3:].isdigit():
        try:
            n = int(s[3:])
            if n <= 0:
                return "0"
            base36 = "0123456789abcdefghijklmnopqrstuvwxyz"
            out = []
            while n:
                out.append(base36[n % 36])
                n //= 36
            return "".join(reversed(out))[:8] if out else "0"
        except ValueError:
            pass
    return "".join(c for c in s if c.isalnum())[-8:] or "0"


def build_client_order_id(
    bot_id: int,
    cycle_id: int,
    symbol: str,
    side: str,
    qty: float,
    quote_qty: float,
    reason: str,
    grid_index: Optional[int] = None,
    epoch_ms: Optional[int] = None,
    run_id: Optional[str] = None,
) -> str:
    """Deterministic client_order_id including run_id to avoid restart collision. Max 36 chars (Binance limit)."""
    ih = _intent_hash(symbol, side, qty, quote_qty, reason, grid_index)
    ts = epoch_ms or int(time.time() * 1000)
    rid = _run_id_segment(run_id)
    return f"b{bot_id}r{rid}c{cycle_id}i{ih}{ts}"[:36]


def build_intent_id(
    bot_id: int,
    cycle_id: int,
    symbol: str,
    side: str,
    qty: float,
    quote_qty: float,
    reason: str,
    grid_index: Optional[int] = None,
    strategy_action_hash: Optional[str] = None,
    run_id: Optional[str] = None,
) -> str:
    """Deterministic intent_id including run_id so restarts cannot collide with previous run's intents."""
    ih = _intent_hash(symbol, side, qty, quote_qty, reason, grid_index)
    if strategy_action_hash:
        ih = hashlib.sha256((ih + strategy_action_hash).encode()).hexdigest()[:16]
    rid = (str(run_id or "").strip() or "0")[:32]
    return f"bot{bot_id}_r{rid}_cy{cycle_id}_it{ih}"


def upsert_intent(
    db: Session,
    intent_id: str,
    bot_id: int,
    account_id: int,
    symbol: str,
    side: str,
    qty: float,
    price_type: str,
    client_order_id: str,
    price: Optional[float] = None,
    order_type: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Upsert order_intent (unique on intent_id). Returns (row_dict, is_new).
    Same intent_id => same client_order_id always (stored on first persist, reused on retry).
    If exists with status in FINAL_STATUSES -> (existing, False). Do NOT place again.
    If exists with status in INFLIGHT -> (existing, False). Use existing client_order_id for reconcile/submit.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = db.execute(
        text("SELECT id, intent_id, client_order_id, binance_order_id, status FROM order_intents WHERE intent_id = :iid"),
        {"iid": intent_id},
    ).fetchone()
    if existing:
        return {"id": existing[0], "intent_id": existing[1], "client_order_id": existing[2], "binance_order_id": existing[3], "status": existing[4]}, False
    ot = order_type or price_type
    try:
        # v5 schema has order_type; legacy has price_type
        try:
            db.execute(
                text("""
                    INSERT INTO order_intents (intent_id, bot_id, account_id, symbol, side, order_type, qty, price, client_order_id, status, created_at, updated_at)
                    VALUES (:iid, :bid, :aid, :sym, :side, :otype, :qty, :price, :coid, :status, :now, :now)
                """),
                {"iid": intent_id, "bid": bot_id, "aid": account_id, "sym": symbol, "side": side, "otype": ot, "qty": qty, "price": price, "coid": client_order_id, "status": STATUS_PERSISTED, "now": now},
            )
        except Exception:
            db.rollback()
            db.execute(
                text("""
                    INSERT INTO order_intents (intent_id, bot_id, account_id, symbol, side, qty, price_type, client_order_id, status, created_at, updated_at)
                    VALUES (:iid, :bid, :aid, :sym, :side, :qty, :ptype, :coid, 'PERSISTED', :now, :now)
                """),
                {"iid": intent_id, "bid": bot_id, "aid": account_id, "sym": symbol, "side": side, "qty": qty, "ptype": price_type, "coid": client_order_id, "now": now},
            )
        db.commit()
        return {"intent_id": intent_id, "client_order_id": client_order_id, "binance_order_id": None, "status": STATUS_PERSISTED}, True
    except Exception as e:
        db.rollback()
        logger.warning("upsert_intent conflict: %s", e)
        existing = db.execute(
            text("SELECT id, intent_id, client_order_id, binance_order_id, status FROM order_intents WHERE intent_id = :iid"),
            {"iid": intent_id},
        ).fetchone()
        if existing:
            return {"id": existing[0], "intent_id": existing[1], "client_order_id": existing[2], "binance_order_id": existing[3], "status": existing[4]}, False
    return None, False


def get_intent_by_client_order_id(db: Session, client_order_id: str) -> Optional[Dict[str, Any]]:
    """Get intent by client_order_id for reconciliation."""
    r = db.execute(
        text("SELECT id, intent_id, bot_id, account_id, symbol, side, qty, client_order_id, binance_order_id, status FROM order_intents WHERE client_order_id = :coid"),
        {"coid": client_order_id},
    ).fetchone()
    if not r:
        return None
    return {"id": r[0], "intent_id": r[1], "bot_id": r[2], "account_id": r[3], "symbol": r[4], "side": r[5], "qty": r[6], "client_order_id": r[7], "binance_order_id": r[8], "status": r[9]}


def update_intent_filled(
    db: Session,
    intent_id: str,
    binance_order_id: str,
    filled_qty: Optional[float] = None,
    avg_price: Optional[float] = None,
) -> bool:
    """Update intent: binance_order_id, status=FILLED, filled_qty, avg_price, final_ts."""
    now = datetime.now(timezone.utc).isoformat()
    final_ts = time.time()
    r = db.execute(
        text("""
            UPDATE order_intents
            SET binance_order_id = :oid, status = :status, updated_at = :now,
                filled_qty = COALESCE(:filled_qty, filled_qty),
                avg_price = COALESCE(:avg_price, avg_price),
                final_ts = :final_ts
            WHERE intent_id = :iid
        """),
        {"oid": str(binance_order_id), "status": STATUS_FILLED, "now": now, "filled_qty": filled_qty, "avg_price": avg_price, "final_ts": final_ts, "iid": intent_id},
    )
    db.commit()
    return r.rowcount > 0


def update_intent_sent(db: Session, intent_id: str) -> bool:
    """Mark intent as SUBMITTED (order placed, ack received). Backward compat: also set SENT."""
    now = datetime.now(timezone.utc).isoformat()
    r = db.execute(
        text("UPDATE order_intents SET status = 'SUBMITTED', updated_at = :now WHERE intent_id = :iid"),
        {"now": now, "iid": intent_id},
    )
    if r.rowcount == 0:
        r = db.execute(
            text("UPDATE order_intents SET status = 'SENT', updated_at = :now WHERE intent_id = :iid"),
            {"now": now, "iid": intent_id},
        )
    db.commit()
    return r.rowcount > 0


def update_intent_submitting(db: Session, intent_id: str, submit_ts: Optional[float] = None) -> bool:
    """Mark intent as SUBMITTING (about to call Binance)."""
    now = datetime.now(timezone.utc).isoformat()
    ts = submit_ts or time.time()
    r = db.execute(
        text("""
            UPDATE order_intents SET status = 'SUBMITTING', updated_at = :now,
                submit_attempts = COALESCE(submit_attempts, 0) + 1, last_submit_ts = :ts
            WHERE intent_id = :iid
        """),
        {"now": now, "ts": ts, "iid": intent_id},
    )
    db.commit()
    return r.rowcount > 0


def update_intent_unknown(db: Session, intent_id: str, error_code: Optional[str] = None, error_id: Optional[str] = None) -> bool:
    """On timeout: mark UNKNOWN; reconcile will resolve from Binance."""
    now = datetime.now(timezone.utc).isoformat()
    r = db.execute(
        text("""
            UPDATE order_intents SET status = 'UNKNOWN', updated_at = :now,
                last_error_code = :err_code, last_error_id = :err_id
            WHERE intent_id = :iid
        """),
        {"now": now, "err_code": error_code, "err_id": error_id, "iid": intent_id},
    )
    db.commit()
    return r.rowcount > 0


def update_intent_rejected(db: Session, intent_id: str, error_code: Optional[str] = None, error_id: Optional[str] = None) -> bool:
    """Order rejected by Binance -> REJECTED, final_ts."""
    now = datetime.now(timezone.utc).isoformat()
    final_ts = time.time()
    r = db.execute(
        text("""
            UPDATE order_intents SET status = 'REJECTED', updated_at = :now,
                last_error_code = :err_code, last_error_id = :err_id, final_ts = :final_ts
            WHERE intent_id = :iid
        """),
        {"now": now, "err_code": error_code, "err_id": error_id, "final_ts": final_ts, "iid": intent_id},
    )
    db.commit()
    return r.rowcount > 0


def update_intent_from_binance(
    db: Session,
    intent_id: str,
    binance_order_id: Optional[str] = None,
    status: str = STATUS_SUBMITTED,
    executed_qty: Optional[float] = None,
    avg_price: Optional[float] = None,
) -> bool:
    """Reconciliation: set status and fill from Binance order."""
    now = datetime.now(timezone.utc).isoformat()
    final_ts = time.time() if status in (STATUS_FILLED, STATUS_CANCELED, STATUS_REJECTED) else None
    r = db.execute(
        text("""
            UPDATE order_intents SET binance_order_id = COALESCE(:oid, binance_order_id),
                status = :status, updated_at = :now,
                filled_qty = COALESCE(:filled_qty, filled_qty),
                avg_price = COALESCE(:avg_price, avg_price),
                final_ts = COALESCE(:final_ts, final_ts)
            WHERE intent_id = :iid
        """),
        {"oid": binance_order_id, "status": status, "now": now, "filled_qty": executed_qty, "avg_price": avg_price, "final_ts": final_ts, "iid": intent_id},
    )
    db.commit()
    return r.rowcount > 0


def get_intent_status(db: Session, intent_id: str) -> Optional[str]:
    """Get current status of intent."""
    r = db.execute(text("SELECT status FROM order_intents WHERE intent_id = :iid"), {"iid": intent_id}).fetchone()
    return r[0] if r else None


def get_sent_intents_for_bot(db: Session, bot_id: int) -> List[Dict[str, Any]]:
    """Get inflight intents for this bot (reconciliation): PENDING, SENT, PERSISTED, SUBMITTING, SUBMITTED, UNKNOWN."""
    r = db.execute(
        text("""
            SELECT intent_id, client_order_id, symbol, side, qty, status
            FROM order_intents WHERE bot_id = :bid
            AND status IN ('PENDING','SENT','PERSISTED','SUBMITTING','SUBMITTED','ACKED','PARTIAL','UNKNOWN')
        """),
        {"bid": bot_id},
    ).fetchall()
    return [{"intent_id": row[0], "client_order_id": row[1], "symbol": row[2], "side": row[3], "qty": row[4], "status": row[5]} for row in r]


def get_non_final_intents_for_account(db: Session, account_id: int) -> List[Dict[str, Any]]:
    """Get all non-final intents for account (startup reconciliation)."""
    r = db.execute(
        text("""
            SELECT id, intent_id, bot_id, client_order_id, symbol, side, qty, status
            FROM order_intents WHERE account_id = :aid AND status NOT IN ('FILLED','CANCELED','REJECTED','FINAL')
        """),
        {"aid": account_id},
    ).fetchall()
    return [{"id": row[0], "intent_id": row[1], "bot_id": row[2], "client_order_id": row[3], "symbol": row[4], "side": row[5], "qty": row[6], "status": row[7]} for row in r]


async def reconcile_open_orders_for_bot(adapter: Any, bot_id: int, account_id: int, db: Session, symbol: str) -> int:
    """
    Startup/periodic reconciliation: fetch open orders, match by clientOrderId, update order_intents.
    Returns count of intents updated to SENT.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        open_orders = await adapter.get_open_orders(symbol=symbol)
        updated = 0
        for o in (open_orders or []):
            coid = (o.get("clientOrderId") or o.get("origClientOrderId") or "") or ""
            if not coid:
                continue
            row = db.execute(
                text("SELECT id, intent_id, status FROM order_intents WHERE bot_id = :bid AND client_order_id = :coid"),
                {"bid": bot_id, "coid": coid},
            ).fetchone()
            if row and row[2] == "PENDING":
                now = datetime.now(timezone.utc).isoformat()
                db.execute(
                    text("UPDATE order_intents SET status = 'SENT', updated_at = :now WHERE intent_id = :iid"),
                    {"now": now, "iid": row[1]},
                )
                db.commit()
                updated += 1
                log.info("RECONCILE_OPEN_ORDER bot_id=%s client_order_id=%s intent=%s", bot_id, coid, row[1])
        return updated
    except Exception as e:
        from app.services.binance_spot import BinanceIPBannedError
        if isinstance(e, BinanceIPBannedError):
            log.debug("reconcile_open_orders_for_bot bot_id=%s skipped (IP ban until %.0f)", bot_id, e.banned_until_ts)
        else:
            log.warning("reconcile_open_orders_for_bot bot_id=%s err=%s", bot_id, e)
        db.rollback()
        return 0
