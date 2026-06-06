"""
Yerel (localhost) test hesabı: paper modda bot testi için.
- Sadece 127.0.0.1 / ::1 üzerinden giriş yapılabilir.
- Bu hesapta oluşturulan botlar paper modda çalışır (10.000 USDT sanal bakiye).

Giriş (sadece bu bilgisayarda http://127.0.0.1 veya http://localhost):
  Kullanıcı adı: test
  Şifre: 123
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TEST_USERNAME = "test"
TEST_PASSWORD = "123"
TEST_ACCOUNT_CODE = "TEST01"
TEST_PAPER_BALANCE_USDT = 10_000.0


def is_test_account_username(username: Optional[str]) -> bool:
    return (username or "").strip().lower() == TEST_USERNAME.lower()


def is_test_account(account_id: Optional[int], db: "Session") -> bool:
    """True if account_id belongs to the local test user (paper mode)."""
    if not account_id:
        return False
    from app.db.models import Account, User
    acc = db.query(Account).filter(Account.id == int(account_id)).first()
    if not acc or not acc.user_id:
        return False
    user = db.query(User).filter(User.id == acc.user_id).first()
    return bool(user and is_test_account_username(getattr(user, "username", None)))


def is_localhost(client_host: Optional[str]) -> bool:
    if not client_host:
        return False
    h = (client_host or "").strip()
    return h in ("127.0.0.1", "::1", "localhost")


# Eski test kullanıcı adı (migrasyon: test_local -> test)
_LEGACY_TEST_USERNAME = "test_local"

def ensure_test_account(db: "Session") -> bool:
    """Test kullanıcı ve hesabı yoksa oluştur. Sadece local kurulumda kullanılır."""
    from app.db.models import User, Account
    from app.api.auth import hash_password
    from app.services.encryption import encrypt_text
    from app.utils.account_code import generate_account_code

    user = db.query(User).filter(User.username == TEST_USERNAME).first()
    if user:
        if not user.account_id:
            account = db.query(Account).filter(Account.account_code == TEST_ACCOUNT_CODE).first()
            if not account:
                account = Account(
                    account_code=TEST_ACCOUNT_CODE,
                    name="Test (Paper)",
                    exchange="BINANCE",
                    api_key_enc=encrypt_text(""),
                    api_secret_enc=encrypt_text(""),
                    mode="paper",
                    is_first_login=False,
                    user_id=user.id,
                )
                db.add(account)
                db.flush()
                db.refresh(account)
            user.account_id = account.id
            db.commit()
            logger.info("test_account: linked existing user to account")
        return False

    # Eski test_local kullanıcısını test/123'e güncelle
    legacy = db.query(User).filter(User.username == _LEGACY_TEST_USERNAME).first()
    if legacy:
        legacy.username = TEST_USERNAME
        legacy.password_hash = hash_password(TEST_PASSWORD)
        db.commit()
        logger.info("test_account: migrated test_local -> test (password: 123)")
        return False

    account = Account(
        account_code=TEST_ACCOUNT_CODE,
        name="Test (Paper)",
        exchange="BINANCE",
        api_key_enc=encrypt_text(""),
        api_secret_enc=encrypt_text(""),
        mode="paper",
        is_first_login=False,
        user_id=None,
    )
    db.add(account)
    db.flush()
    db.refresh(account)

    user = User(
        username=TEST_USERNAME,
        password_hash=hash_password(TEST_PASSWORD),
        name="Test",
        surname="Local",
        phone="0000000000",
        is_admin=False,
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
    logger.info("test_account: created test user and TEST01 account (paper, local only)")
    return True
