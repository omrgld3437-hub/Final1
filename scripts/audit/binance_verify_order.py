#!/usr/bin/env python3
"""
Debug CLI: verify an order on Binance by origClientOrderId.
Inputs: account_id, symbol, origClientOrderId
Outputs: GET /api/v3/order JSON, myTrades count for that orderId, decision (NOT_FOUND / FOUND / ERROR).

Usage:
  python scripts/binance_verify_order.py <account_id> <symbol> <origClientOrderId>

Example:
  python scripts/binance_verify_order.py 1 LTCUSDT b1r0c0iabc1234567890
"""

from __future__ import annotations
import asyncio
import json
import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _root)
    os.chdir(_root)

from app.db.base import SessionLocal
from app.services.binance_assets import get_account_keys
from app.services.binance_spot import get_order_by_client_order_id, get_my_trades


async def main():
    if len(sys.argv) < 4:
        print(
            "Usage: binance_verify_order.py <account_id> <symbol> <origClientOrderId>",
            file=sys.stderr,
        )
        sys.exit(1)
    account_id = int(sys.argv[1])
    symbol = (sys.argv[2] or "").upper() or "BTCUSDT"
    orig_client_order_id = (sys.argv[3] or "").strip()
    if not orig_client_order_id:
        print("origClientOrderId required", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        keys = await get_account_keys(account_id, db)
        if not keys:
            print(
                json.dumps(
                    {"decision": "ERROR", "error": "No API keys for account_id"},
                    indent=2,
                )
            )
            sys.exit(1)
        order = await get_order_by_client_order_id(keys, symbol, orig_client_order_id)
        if order is None:
            print(
                json.dumps(
                    {
                        "decision": "NOT_FOUND",
                        "order": None,
                        "myTrades_count": 0,
                        "message": "GET /order returned NOT_FOUND (-2013 or invalid); safe to place.",
                    },
                    indent=2,
                )
            )
            return
        order_id = order.get("orderId")
        try:
            order_id_int = int(order_id) if order_id is not None else 0
        except (TypeError, ValueError):
            order_id_int = 0
        trades = (
            await get_my_trades(keys, symbol, limit=50, order_id=order_id_int)
            if order_id_int
            else []
        )
        trades_count = len(trades)
        decision = "FOUND" if trades_count > 0 else "NOT_FOUND"
        if decision == "NOT_FOUND" and (order.get("status") or "").upper() == "FILLED":
            decision = "FOUND_ORDER_BUT_NO_MYTRADES"
        out = {
            "decision": decision,
            "order": {k: v for k, v in order.items() if k not in ("",)},
            "orderId": order_id,
            "myTrades_count": trades_count,
            "message": "FOUND and verified in myTrades"
            if trades_count > 0
            else "Order exists but no myTrades for this orderId (do not repair).",
        }
        print(json.dumps(out, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
