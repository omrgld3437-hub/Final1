"""
Benzersiz, karmaşık 6 haneli hesap kodu üretimi.
Tüm hesapların ID'leri karmaşık 6 haneli rakamlardan oluşur (100000–999999, en az 3 farklı rakam).
"""

import random
from sqlalchemy.orm import Session

from app.db.models import Account


def _is_complex_6_digits(code: int) -> bool:
    """En az 3 farklı rakam içermeli (111111, 123456 gibi basit kalıplar hariç)."""
    s = str(code)
    return len(s) == 6 and len(set(s)) >= 3


def generate_account_code(db: Session) -> str:
    """Benzersiz, karmaşık 6 haneli hesap kodu üretir (100000–999999, en az 3 farklı rakam)."""
    max_attempts = 200
    for _ in range(max_attempts):
        code = random.randint(100000, 999999)
        if not _is_complex_6_digits(code):
            continue
        code_str = str(code)
        existing = db.query(Account).filter(Account.account_code == code_str).first()
        if not existing:
            return code_str
    for _ in range(50):
        code = random.randint(100000, 999999)
        code_str = str(code)
        if db.query(Account).filter(Account.account_code == code_str).first() is None:
            return code_str
    return str(random.randint(100000, 999999))
