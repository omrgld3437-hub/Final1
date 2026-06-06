#!/usr/bin/env python3
"""Add last_login_ip, last_activity_at, kicked_at to users table if missing.
Run once: .venv/bin/python migrate_user_activity.py"""

import sys

sys.path.insert(0, ".")

from app.db.base import engine
from sqlalchemy import text

COLUMNS = [
    ("last_login_ip", "VARCHAR(50)"),
    ("last_activity_at", "DATETIME"),
    ("kicked_at", "DATETIME"),
    ("must_change_password", "BOOLEAN"),
]


def run():
    with engine.connect() as conn:
        for name, typ in COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {typ}"))
                conn.commit()
                print(f"  + users.{name}")
            except Exception as e:
                err = str(e).lower()
                if "duplicate column name" in err or "already exists" in err:
                    print(f"  - users.{name} (already exists)")
                else:
                    raise
    print("Done.")


if __name__ == "__main__":
    run()
