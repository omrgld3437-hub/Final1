#!/usr/bin/env python3
"""Backfill account_code (6-digit random) for accounts where it is NULL or empty.
Run once: .venv/bin/python migrate_account_code_backfill.py"""

import sys
import random

sys.path.insert(0, ".")

from app.db.base import engine
from sqlalchemy import text


def generate_code(conn) -> str:
    for _ in range(100):
        code = "".join(str(random.randint(0, 9)) for _ in range(6))
        r = conn.execute(
            text("SELECT 1 FROM accounts WHERE account_code = :c"), {"c": code}
        )
        if r.fetchone() is None:
            return code
    return str(random.randint(100000, 999999))


def run():
    with engine.connect() as conn:
        r = conn.execute(text("SELECT id, account_code FROM accounts"))
        rows = r.fetchall()
        updated = 0
        for aid, ac in rows:
            if not ac or not str(ac).strip():
                code = generate_code(conn)
                conn.execute(
                    text("UPDATE accounts SET account_code = :c WHERE id = :id"),
                    {"c": code, "id": aid},
                )
                conn.commit()
                print(f"  account id={aid} -> account_code={code}")
                updated += 1
        if not updated:
            print("  No accounts needing backfill.")
        else:
            print(f"  Updated {updated} account(s).")
    print("Done.")


if __name__ == "__main__":
    run()
