"""
FILE: encryption.py
VERSION: v2
DATE: 2026-01-21
CHANGE: Add encrypt_key/decrypt_key wrapper functions for backward compatibility
Encryption Service for API Keys/Secrets
"""
from cryptography.fernet import Fernet
import os
import base64
from dotenv import load_dotenv

# Load .env file
load_dotenv()


def get_encryption_key():
    """Get or generate encryption key from env"""
    master_key = os.getenv("BINANCE_MASTER_KEY")
    if not master_key:
        raise ValueError("BINANCE_MASTER_KEY environment variable not set")
    
    # Convert to 32-byte key for Fernet (explicit UTF-8 for Turkish/env safety)
    key_bytes = master_key.encode("utf-8")[:32].ljust(32, b"0")
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_text(text: str) -> str:
    """Encrypt text"""
    if not text:
        return ""
    f = Fernet(get_encryption_key())
    return f.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_text(encrypted_text: str) -> str:
    """Decrypt text. On failure raises ValueError with ASCII-safe message (no raw exception text)."""
    if not encrypted_text:
        return ""
    try:
        f = Fernet(get_encryption_key())
        return f.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception:
        # Do not include str(e) to avoid non-ASCII chars in error messages (e.g. Turkish)
        raise ValueError("Decryption failed")


# Wrapper functions for backward compatibility (encrypt_key/decrypt_key)
def encrypt_key(plain: str) -> str:
    """Encrypt key (alias for encrypt_text)"""
    return encrypt_text(plain)


def decrypt_key(cipher: str) -> str:
    """Decrypt key (alias for decrypt_text)"""
    return decrypt_text(cipher)


# Backward compatibility: also export as encrypt/decrypt if needed
encrypt = encrypt_text
decrypt = decrypt_text


# Self-test
if __name__ == "__main__":
    s = "test"
    encrypted = encrypt_key(s)
    decrypted = decrypt_key(encrypted)
    assert decrypted == s, f"Self-test failed: {decrypted} != {s}"
    print("✅ Encryption self-test OK")

