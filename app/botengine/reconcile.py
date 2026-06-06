"""
Bot Engine v5 – Reconciliation from Binance truth.
On worker startup and before new submits: reconcile non-final intents.
Match by clientOrderId (prefix + exact). Update intents and ledger.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, TYPE_CHECKING


from app.botengine.intent_ledger import (
    get_non_final_intents_for_account,
    update_intent_from_binance,
    STATUS_FILLED,
    STATUS_CANCELED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    STATUS_PARTIAL,
)

# Binance -2013 "Order does not exist" => NOT_FOUND; we mark intent CANCELED so we stop re-querying.
NOT_FOUND_MARK_CANCELED = True

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Metrics
_reconcile_matches_total = 0
_reconcile_errors_total = 0


def get_reconcile_metrics() -> Dict[str, Any]:
    return {
        "reconcile_matches_total": _reconcile_matches_total,
        "reconcile_errors_total": _reconcile_errors_total,
    }


async def reconcile_account(
    account_id: int,
    get_open_orders: Any,
    get_all_orders: Any,
    get_order_by_client_order_id: Any,
    db: "Session",
) -> Dict[str, Any]:
    """
    Reconcile all non-final intents for account from Binance.
    get_open_orders(symbol?), get_all_orders(symbol?, limit?), get_order_by_client_order_id(symbol, client_order_id).
    Returns {matched: int, updated: int, errors: int, open_orders_checked: int}.
    """
    global _reconcile_matches_total, _reconcile_errors_total
    result = {"matched": 0, "updated": 0, "errors": 0, "open_orders_checked": 0}
    intents = get_non_final_intents_for_account(db, account_id)
    if not intents:
        return result
    client_order_ids = [i["client_order_id"] for i in intents]
    by_coid = {i["client_order_id"]: i for i in intents}
    open_orders: List[Dict[str, Any]] = []
    try:
        open_orders = await get_open_orders(symbol=None) or []
    except Exception as e:
        logger.warning(
            "reconcile_account get_open_orders account_id=%s err=%s", account_id, e
        )
        _reconcile_errors_total += 1
        result["errors"] += 1
    result["open_orders_checked"] = len(open_orders)
    open_by_coid = {}
    for o in open_orders:
        coid = (o.get("clientOrderId") or o.get("origClientOrderId") or "").strip()
        if coid:
            open_by_coid[coid] = o
    for coid in client_order_ids:
        intent = by_coid.get(coid)
        if not intent:
            continue
        symbol = (intent.get("symbol") or "").upper()
        if not symbol:
            continue
        binance_order = None
        if coid in open_by_coid:
            binance_order = open_by_coid[coid]
        else:
            try:
                binance_order = await get_order_by_client_order_id(symbol, coid)
            except Exception as e:
                logger.debug(
                    "reconcile get_order_by_client_order_id symbol=%s coid=%s err=%s",
                    symbol,
                    coid,
                    e,
                )
        if not binance_order:
            try:
                all_orders = await get_all_orders(symbol=symbol, limit=20) or []
                for o in all_orders:
                    if (
                        o.get("clientOrderId") or o.get("origClientOrderId") or ""
                    ).strip() == coid:
                        binance_order = o
                        break
            except Exception as e:
                logger.debug("reconcile get_all_orders symbol=%s err=%s", symbol, e)
        if binance_order:
            status_b = (binance_order.get("status") or "").upper()
            order_id_b = binance_order.get("orderId")
            executed_qty = float(binance_order.get("executedQty") or 0)
            cum_quote = float(binance_order.get("cummulativeQuoteQty") or 0)
            avg_price = (cum_quote / executed_qty) if executed_qty else None
            if status_b == "FILLED":
                ok = update_intent_from_binance(
                    db,
                    intent["intent_id"],
                    binance_order_id=str(order_id_b) if order_id_b else None,
                    status=STATUS_FILLED,
                    executed_qty=executed_qty,
                    avg_price=avg_price,
                )
            elif status_b in ("CANCELED", "EXPIRED", "REJECTED"):
                ok = update_intent_from_binance(
                    db,
                    intent["intent_id"],
                    binance_order_id=str(order_id_b) if order_id_b else None,
                    status=STATUS_CANCELED
                    if status_b != "REJECTED"
                    else STATUS_REJECTED,
                )
            elif status_b in ("NEW", "PARTIALLY_FILLED"):
                ok = update_intent_from_binance(
                    db,
                    intent["intent_id"],
                    binance_order_id=str(order_id_b) if order_id_b else None,
                    status=STATUS_SUBMITTED if status_b == "NEW" else STATUS_PARTIAL,
                    executed_qty=executed_qty,
                    avg_price=avg_price,
                )
            else:
                ok = update_intent_from_binance(
                    db,
                    intent["intent_id"],
                    binance_order_id=str(order_id_b) if order_id_b else None,
                    status=STATUS_SUBMITTED,
                )
            if ok:
                result["matched"] += 1
                result["updated"] += 1
                _reconcile_matches_total += 1
                logger.info(
                    "RECONCILE_MATCH account_id=%s intent_id=%s client_order_id=%s binance_status=%s",
                    account_id,
                    intent["intent_id"],
                    coid,
                    status_b,
                )
        elif NOT_FOUND_MARK_CANCELED:
            # Order not on Binance (-2013 / not in open or all) => mark CANCELED to stop re-querying every 45s
            ok = update_intent_from_binance(
                db,
                intent["intent_id"],
                binance_order_id=None,
                status=STATUS_CANCELED,
            )
            if ok:
                result["updated"] += 1
                logger.info(
                    "RECONCILE_NOT_FOUND account_id=%s intent_id=%s client_order_id=%s => CANCELED (stop re-query)",
                    account_id,
                    intent["intent_id"],
                    coid,
                )
    return result
