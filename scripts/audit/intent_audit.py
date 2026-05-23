#!/usr/bin/env python3
"""Audit order_intents: list non-final, by account/bot/status. Usage: intent_audit.py [--account N] [--bot N]"""
from __future__ import annotations
import argparse
import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _root)
    os.chdir(_root)

from sqlalchemy import text
from app.db.base import SessionLocal


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account", type=int, help="Filter by account_id")
    p.add_argument("--bot", type=int, help="Filter by bot_id")
    p.add_argument("--status", type=str, help="Filter by status")
    args = p.parse_args()
    db = SessionLocal()
    try:
        q = """
            SELECT id, intent_id, bot_id, account_id, symbol, side, qty, client_order_id, binance_order_id, status,
                   submit_attempts, filled_qty, last_error_code, created_at
            FROM order_intents
            WHERE 1=1
        """
        params = {}
        if args.account is not None:
            q += " AND account_id = :aid"
            params["aid"] = args.account
        if args.bot is not None:
            q += " AND bot_id = :bid"
            params["bid"] = args.bot
        if args.status:
            q += " AND status = :status"
            params["status"] = args.status
        q += " ORDER BY id DESC LIMIT 200"
        rows = db.execute(text(q), params).fetchall()
        print(f"count={len(rows)}")
        for r in rows:
            print(r)
    finally:
        db.close()


if __name__ == "__main__":
    main()
