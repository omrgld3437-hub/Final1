#!/usr/bin/env python3
"""Tek seferlik: Admin hesabi yoksa olusturur, varsa (silinmis dahil) sifreyi Adminadmin01. yapar.
Login: kullanici adi 'Admin', sifre 'Adminadmin01.' (ilk giris sonrasi Ayarlar'dan degistirin).
Run once: .venv/bin/python scripts/migrations/set_admin_password_once.py"""

import sys
import os
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root))
os.chdir(_root)
# Sunucu ile ayni veritabanini kullan (DATABASE_URL .env'den)
try:
    from dotenv import load_dotenv

    load_dotenv(str(_root / ".env"))
except Exception:
    pass

from app.db.session import SessionLocal
from app.db.models import User, Account
from app.api.auth import hash_password, verify_password
from app.utils.account_code import generate_account_code
from app.services.encryption import encrypt_text

ADMIN_TEMP_PASSWORD = "Adminadmin01."
ADMIN_USERNAME = "Admin"


def run():
    db = SessionLocal()
    try:
        # is_deleted dahil tum admin kullanicilari bul (silinmis admini de geri getirebilmek icin)
        admin = db.query(User).filter(User.is_admin == True).first()
        if admin:
            admin.username = ADMIN_USERNAME
            admin.password_hash = hash_password(ADMIN_TEMP_PASSWORD)
            admin.must_change_password = False
            admin.failed_login_attempts = 0
            admin.is_deleted = False
            admin.is_suspended = False
            admin.deleted_at = None
            if not admin.account_id:
                account_code = generate_account_code(db)
                acc = Account(
                    account_code=account_code,
                    name="Admin",
                    exchange="BINANCE",
                    api_key_enc=encrypt_text(""),
                    api_secret_enc=encrypt_text(""),
                    mode="live",
                    is_first_login=False,
                )
                db.add(acc)
                db.flush()
                db.refresh(acc)
                admin.account_id = acc.id
                acc.user_id = admin.id
            db.commit()
            ok = verify_password(ADMIN_TEMP_PASSWORD, admin.password_hash)
            print(
                "  Admin hesabi guncellendi. Giris: Admin / Adminadmin01."
                + (
                    " Sifre dogrulandi: OK"
                    if ok
                    else " UYARI: Sifre dogrulamasi basarisiz!"
                )
            )
        else:
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
                password_hash=hash_password(ADMIN_TEMP_PASSWORD),
                name="Admin",
                surname="",
                phone=None,
                is_admin=True,
                is_approved=True,
                is_suspended=False,
                is_deleted=False,
                must_change_password=False,
                account_id=account.id,
            )
            db.add(user)
            db.flush()
            db.refresh(user)
            account.user_id = user.id
            db.commit()
            ok = verify_password(ADMIN_TEMP_PASSWORD, user.password_hash)
            print(
                "  Admin hesabi olusturuldu. Giris: Admin / Adminadmin01."
                + (
                    " Sifre dogrulandi: OK"
                    if ok
                    else " UYARI: Sifre dogrulamasi basarisiz!"
                )
            )
    finally:
        db.close()
    print("Done.")


if __name__ == "__main__":
    run()
