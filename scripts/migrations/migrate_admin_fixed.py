#!/usr/bin/env python3
"""Set admin username to 'Admin' and reset password to 'unset'; ilk girisinde yazacagi sifre kalici olur.
Run once: .venv/bin/python scripts/migrations/migrate_admin_fixed.py"""

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.db.models import User
from app.api.auth import get_initial_admin_unset_hash


def run():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.is_admin == True).first()
        if not admin:
            print(
                "  No admin user found. Create one first (e.g. create_first_admin.py)."
            )
            return
        admin.username = "Admin"
        admin.password_hash = get_initial_admin_unset_hash()
        admin.must_change_password = False
        admin.failed_login_attempts = 0
        db.commit()
        print(
            "  Admin username -> 'Admin'. Ilk girisinde yazacagi sifre kalici olacak."
        )
    finally:
        db.close()
    print("Done.")


if __name__ == "__main__":
    run()
