"""
FILE: token_utils.py
Token hashing and short session id for auth diagnostics. Never log raw token.
"""

import hashlib


def hash_token(token: str) -> str:
    """SHA256 hex digest of token. Use for DB key; never store raw token."""
    return hashlib.sha256(token.encode()).hexdigest()


def short_session_id(token_hash: str) -> str:
    """First 8 chars of token_hash for logs only. Never log full hash or raw token."""
    return (token_hash or "")[:8]
