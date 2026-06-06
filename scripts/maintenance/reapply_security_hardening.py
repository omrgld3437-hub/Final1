#!/usr/bin/env python3
"""
Guvenlik sertlestirmesini yeniden uygular:
- Tum oturumlari iptal eder (yeniden giris)
- Admin/test hesap bayraklarini duzeltir
Usage: python3 scripts/maintenance/reapply_security_hardening.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from sqlalchemy import text
from app.db.session import SessionLocal
from app.db.models import User


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(text("UPDATE auth_sessions SET revoked = 1"))
        db.execute(text("DELETE FROM auth_sessions"))
        admin = db.query(User).filter(User.is_admin == True).first()
        if admin:
            admin.failed_login_attempts = 0
            admin.is_suspended = False
            admin.is_deleted = False
            admin.is_approved = True
        for u in db.query(User).filter(User.username == "test").all():
            u.is_suspended = False  # localhost-only zaten kodda
        db.commit()
        print("Tum oturumlar silindi; admin bayraklari duzeltildi.")
        print("Web/worker yeniden baslatilmali (.env guvenlik bayraklari icin).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
