#!/usr/bin/env python3
"""Ilk admin kullanici ve hesabi yoksa olusturur. Varsayilan sifre yok; ilk girisinde yazacagi sifre kalici olur.
Calistir: .venv/bin/python scripts/migrations/create_first_admin.py
"""
import sys
sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.db.models import User, Account
from app.api.auth import get_initial_admin_unset_hash
from app.utils.account_code import generate_account_code
from app.services.encryption import encrypt_text

ADMIN_USERNAME = "Admin"


def run():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.is_admin == True).first()
        if admin:
            admin.username = ADMIN_USERNAME
            admin.failed_login_attempts = 0
            db.commit()
            print("  Admin zaten var; kullanici adi '%s' olarak guncellendi." % ADMIN_USERNAME)
            return

        account_code = generate_account_code(db)
        account = Account(
            account_code=account_code,
            name="Admin",
            exchange="BINANCE",
            api_key_enc=encrypt_text(""),
            api_secret_enc=encrypt_text(""),
            mode="live",
            is_first_login=False,
        )
        db.add(account)
        db.flush()
        db.refresh(account)

        user = User(
            username=ADMIN_USERNAME,
            password_hash=get_initial_admin_unset_hash(),
            name="Admin",
            surname="",
            phone=None,
            is_admin=True,
            is_approved=True,
            is_suspended=False,
            must_change_password=False,
            account_id=account.id,
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        account.user_id = user.id
        db.commit()
        print("  Ilk admin olusturuldu: kullanici adi '%s'. Ilk girisinde yazacagi sifre kalici olacak." % ADMIN_USERNAME)
    finally:
        db.close()
    print("Done.")


if __name__ == "__main__":
    run()
