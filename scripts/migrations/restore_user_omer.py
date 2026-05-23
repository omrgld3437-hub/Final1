#!/usr/bin/env python3
"""
Silinen ./dca.db sonrasi: web.log'dan bilinen kullaniciyi yeniden olusturur.
Tam DB geri gelmez; yalnizca hesap + kullanici (bot/API key verisi yok).

Usage:
  python3 scripts/migrations/restore_user_omer.py
  python3 scripts/migrations/restore_user_omer.py --phone 5524516137 --username "omer.altin6"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from app.db.session import SessionLocal
from app.db.models import User, Account
from app.api.auth import hash_password, verify_password
from app.utils.account_code import generate_account_code
from app.services.encryption import encrypt_text

DEFAULT_PHONE = "5524516137"
DEFAULT_USERNAME = "ömer.altın6"
DEFAULT_NAME = "Omer"
DEFAULT_SURNAME = "Altin"
TEMP_PASSWORD = "OmerRestore2026!"


def run(phone: str, username: str, password: str) -> None:
    db = SessionLocal()
    try:
        phone_clean = phone.lstrip("0") if phone.startswith("0") and len(phone) > 10 else phone
        if phone.startswith("0") and len(phone) >= 11:
            phone_clean = phone[1:] if phone.startswith("0") else phone

        existing = db.query(User).filter(
            (User.phone == phone_clean) | (User.phone == phone) | (User.username == username)
        ).first()
        if existing:
            existing.username = username
            existing.phone = phone_clean
            existing.password_hash = hash_password(password)
            existing.is_deleted = False
            existing.is_suspended = False
            existing.is_approved = True
            existing.failed_login_attempts = 0
            existing.must_change_password = True
            db.commit()
            print(f"Kullanici guncellendi: {username} tel={phone_clean}")
        else:
            account_code = generate_account_code(db)
            acc = Account(
                account_code=account_code,
                name=username,
                exchange="BINANCE",
                api_key_enc=encrypt_text(""),
                api_secret_enc=encrypt_text(""),
                mode="live",
                is_first_login=False,
            )
            db.add(acc)
            db.flush()
            user = User(
                username=username,
                password_hash=hash_password(password),
                name=DEFAULT_NAME,
                surname=DEFAULT_SURNAME,
                phone=phone_clean,
                is_admin=False,
                is_approved=True,
                is_suspended=False,
                is_deleted=False,
                must_change_password=True,
                account_id=acc.id,
            )
            db.add(user)
            db.flush()
            acc.user_id = user.id
            db.commit()
            print(f"Kullanici olusturuldu: {username} tel={phone_clean} account_id={acc.id}")

        ok = verify_password(password, hash_password(password))
        print(f"Giris: telefon {phone} veya {phone_clean} / sifre: {password}")
        print(f"Ilk giriste sifre degistirmeniz istenebilir.")
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--username", default=DEFAULT_USERNAME)
    ap.add_argument("--password", default=TEMP_PASSWORD)
    args = ap.parse_args()
    run(args.phone, args.username, args.password)


if __name__ == "__main__":
    main()
