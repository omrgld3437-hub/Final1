#!/usr/bin/env python3
"""Run reconciliation for an account (or all accounts with non-final intents). Usage: reconcile_now.py [account_id]"""
from __future__ import annotations
import asyncio
import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _root)
    os.chdir(_root)

from app.db.base import SessionLocal
from app.botengine.reconcile import reconcile_account, get_reconcile_metrics
from app.botengine.intent_ledger import get_non_final_intents_for_account
from app.services.binance_assets import get_account_keys
from app.botengine.adapters.binance_adapter import BinanceAdapter


async def main():
    account_id_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        if account_id_arg:
            account_ids = [account_id_arg]
        else:
            from sqlalchemy import text
            rows = db.execute(text("SELECT DISTINCT account_id FROM order_intents WHERE status NOT IN ('FILLED','CANCELED','REJECTED','FINAL')")).fetchall()
            account_ids = [r[0] for r in rows]
        if not account_ids:
            print("No accounts with non-final intents.")
            return
        for aid in account_ids:
            try:
                keys = await get_account_keys(aid, db)
                if not keys:
                    print(f"account_id={aid} no keys, skip")
                    continue
                adapter = BinanceAdapter(aid, keys, paper_mode=False)
                result = await reconcile_account(
                    aid,
                    lambda symbol=None: adapter.get_open_orders(symbol),
                    lambda symbol=None, limit=20: adapter.get_all_orders(symbol or "BTCUSDT", limit),
                    lambda symbol, coid: adapter.get_order_by_client_order_id(symbol, coid),
                    db,
                )
                print(f"account_id={aid} matched={result['matched']} updated={result['updated']} errors={result['errors']} open_checked={result['open_orders_checked']}")
            except Exception as e:
                print(f"account_id={aid} error: {e}")
        print("metrics:", get_reconcile_metrics())
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
