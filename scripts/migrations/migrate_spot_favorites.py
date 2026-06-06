#!/usr/bin/env python3
"""Add spot_favorites_json to accounts table if missing. Run once: .venv/bin/python migrate_spot_favorites.py"""
import sys
sys.path.insert(0, ".")

from app.db.base import engine
from sqlalchemy import text

def run():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN spot_favorites_json TEXT"))
            conn.commit()
            print("  + accounts.spot_favorites_json")
        except Exception as e:
            err = str(e).lower()
            if "duplicate column name" in err or "already exists" in err:
                print("  - accounts.spot_favorites_json (already exists)")
            else:
                raise
    print("Done.")

if __name__ == "__main__":
    run()
