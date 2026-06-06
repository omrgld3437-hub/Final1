"""
At-rest şifreleme — API anahtarları ve hassas hesap verileri.

v2 (varsayılan): AES-256-GCM + HKDF-SHA256 (BINANCE_MASTER_KEY + ENCRYPTION_SALT + bağlam).
v1 (legacy): Fernet — eski kayıtlar okunur; kayıt/güncellemede v2'ye geçilir.

Bağlam (context) örnekleri: account:{id}:api_key, account:{id}:api_secret, file:tx_history:{id}
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from dotenv import load_dotenv

load_dotenv()

V2_TEXT_PREFIX = "v2:"
V2_BYTES_PREFIX = b"v2b:"
_DEFAULT_SALT = "tradetrailing-at-rest-v2"


def _master_material() -> bytes:
    master_key = os.getenv("BINANCE_MASTER_KEY")
    if not master_key:
        raise ValueError("BINANCE_MASTER_KEY environment variable not set")
    return master_key.encode("utf-8")


def _salt_bytes() -> bytes:
    return (os.getenv("ENCRYPTION_SALT") or _DEFAULT_SALT).encode("utf-8")


def _legacy_fernet_key() -> bytes:
    key_bytes = _master_material()[:32].ljust(32, b"0")
    return base64.urlsafe_b64encode(key_bytes)


def _derive_aes256_key(context: str) -> bytes:
    info = ("tt-aes256:" + (context or "app:default")).encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_salt_bytes(),
        info=info,
    )
    return hkdf.derive(_master_material())


def get_encryption_key():
    """Geriye uyumluluk — Fernet anahtarı (legacy)."""
    return _legacy_fernet_key()


def is_v2_encrypted(cipher: Optional[str]) -> bool:
    return bool(cipher and str(cipher).strip().startswith(V2_TEXT_PREFIX))


def is_v2_encrypted_bytes(data: Optional[bytes]) -> bool:
    return bool(data and data.startswith(V2_BYTES_PREFIX))


def encrypt_text(text: str, *, context: str = "app:default") -> str:
    """AES-256-GCM ile şifrele (v2 metin formatı)."""
    if not text:
        return ""
    key = _derive_aes256_key(context)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return V2_TEXT_PREFIX + blob


def decrypt_text(encrypted_text: str, *, context: str = "app:default") -> str:
    """v2 veya legacy Fernet (v1) çöz."""
    if not encrypted_text:
        return ""
    s = encrypted_text.strip()
    if s.startswith(V2_TEXT_PREFIX):
        try:
            raw = base64.urlsafe_b64decode(s[len(V2_TEXT_PREFIX) :].encode("ascii"))
            nonce, ct = raw[:12], raw[12:]
            plain = AESGCM(_derive_aes256_key(context)).decrypt(nonce, ct, None)
            return plain.decode("utf-8")
        except Exception:
            raise ValueError("Decryption failed")
    try:
        f = Fernet(_legacy_fernet_key())
        return f.decrypt(s.encode("utf-8")).decode("utf-8")
    except Exception:
        raise ValueError("Decryption failed")


def encrypt_bytes(data: bytes, *, context: str = "file:blob") -> bytes:
    if not data:
        return b""
    key = _derive_aes256_key(context)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return V2_BYTES_PREFIX + base64.urlsafe_b64encode(nonce + ct)


def decrypt_bytes(data: bytes, *, context: str = "file:blob") -> bytes:
    if not data:
        return b""
    if data.startswith(V2_BYTES_PREFIX):
        try:
            raw = base64.urlsafe_b64decode(data[len(V2_BYTES_PREFIX) :])
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(_derive_aes256_key(context)).decrypt(nonce, ct, None)
        except Exception:
            raise ValueError("Decryption failed")
    try:
        return Fernet(_legacy_fernet_key()).decrypt(data)
    except Exception:
        raise ValueError("Decryption failed")


def encrypt_account_api_key(account_id: int, plain: str) -> str:
    return encrypt_text(plain, context=f"account:{account_id}:api_key")


def decrypt_account_api_key(account_id: int, cipher: str) -> str:
    return decrypt_text(cipher, context=f"account:{account_id}:api_key")


def encrypt_account_api_secret(account_id: int, plain: str) -> str:
    return encrypt_text(plain, context=f"account:{account_id}:api_secret")


def decrypt_account_api_secret(account_id: int, cipher: str) -> str:
    return decrypt_text(cipher, context=f"account:{account_id}:api_secret")


def encrypt_account_ip_whitelist(account_id: int, plain: str) -> str:
    if not plain:
        return ""
    return encrypt_text(plain, context=f"account:{account_id}:ip_whitelist")


def decrypt_account_ip_whitelist(account_id: int, cipher: str) -> str:
    if not cipher:
        return ""
    return decrypt_text(cipher, context=f"account:{account_id}:ip_whitelist")


def tx_history_file_context(account_id: int) -> str:
    return f"file:tx_history:{account_id}"


def maybe_upgrade_account_secrets(
    db, account_id: int, api_key: str, api_secret: str
) -> None:
    """Legacy v1 ciphertext → v2 (hesap bağlamlı AES-GCM)."""
    from app.db.models import Account

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        return
    changed = False
    if api_key and not is_v2_encrypted(account.api_key_enc):
        account.api_key_enc = encrypt_account_api_key(account_id, api_key)
        changed = True
    if api_secret and not is_v2_encrypted(account.api_secret_enc):
        account.api_secret_enc = encrypt_account_api_secret(account_id, api_secret)
        changed = True
    wl = getattr(account, "api_ip_whitelist", None) or ""
    if wl and not is_v2_encrypted(wl):
        try:
            plain_wl = decrypt_account_ip_whitelist(account_id, wl)
        except ValueError:
            plain_wl = wl
        account.api_ip_whitelist = encrypt_account_ip_whitelist(account_id, plain_wl)
        changed = True
    if changed:
        db.commit()


def encrypt_key(plain: str, *, context: str = "app:default") -> str:
    return encrypt_text(plain, context=context)


def decrypt_key(cipher: str, *, context: str = "app:default") -> str:
    return decrypt_text(cipher, context=context)


encrypt = encrypt_text
decrypt = decrypt_text


if __name__ == "__main__":
    s = "test-secret-value"
    enc = encrypt_text(s, context="selftest")
    assert decrypt_text(enc, context="selftest") == s
    enc_acc = encrypt_account_api_key(1, s)
    assert decrypt_account_api_key(1, enc_acc) == s
    blob = encrypt_bytes(b"blob", context="selftest")
    assert decrypt_bytes(blob, context="selftest") == b"blob"
    print("Encryption self-test OK (AES-256-GCM v2)")
