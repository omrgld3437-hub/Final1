"""
FILE: auth.py
VERSION: v1
DATE: 2026-01-24
CHANGE: Authentication system - login, register, password reset, admin approval, IP ban
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime, timedelta
import json
import os
import secrets
import bcrypt
import random
from app.db.session import get_db
from app.db.models import (
    User,
    Account,
    PendingRegistration,
    BannedIP,
    PasswordResetRequest,
    ContactMessage,
    ChatThread,
    ChatMessage,
    ChatRating,
    AuditEvent,
    AdminPopup,
    AdminPopupDismissal,
)
from app.services.encryption import encrypt_text
from app.services import audit as audit_svc
from app.core.auth.token_utils import hash_token, short_session_id
import logging
import time
import threading
import unicodedata

logger = logging.getLogger(__name__)

# Sliding TTL: only update last_seen_at/expires_at if last activity was > this many seconds ago (avoid DB write on every request)
SESSION_SLIDING_ENABLED = os.environ.get("AUTH_SLIDING_TTL", "1").strip() in (
    "1",
    "true",
    "yes",
)
SESSION_SLIDING_UPDATE_MIN_SEC = int(
    os.environ.get("SESSION_SLIDING_UPDATE_MIN_SEC", "60")
)
# Per-worker session validation cache (reduces auth_sessions SELECT on hot paths; < sliding window)
AUTH_SESSION_CACHE_SEC = max(0, int(os.environ.get("AUTH_SESSION_CACHE_SEC", "45")))
_session_cache_lock = threading.Lock()
_session_cache: dict[str, tuple[dict, float]] = {}


def _normalize_password(s: str) -> str:
    """Trim and NFC-normalize so local vs yayin (farkli tarayici/OS) ayni sonucu verir."""
    if not s:
        return ""
    return unicodedata.normalize("NFC", s.strip())


router = APIRouter()
security = HTTPBearer(auto_error=False)

# In-memory session store (fallback when auth_sessions not used)
_sessions: dict[str, dict] = {}

# Shared DB session store (auth_sessions table) for multi-worker locality
SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "7"))


# Alias: use central token hashing (never log raw token; use short_session_id for logs)
def _token_hash(token: str) -> str:
    return hash_token(token)


def _session_cache_get(token_hash: str) -> Optional[dict]:
    if AUTH_SESSION_CACHE_SEC <= 0:
        return None
    now = time.monotonic()
    with _session_cache_lock:
        entry = _session_cache.get(token_hash)
        if not entry:
            return None
        data, exp = entry
        if now >= exp:
            _session_cache.pop(token_hash, None)
            return None
        return dict(data)


def _session_cache_set(token_hash: str, session: dict) -> None:
    if AUTH_SESSION_CACHE_SEC <= 0:
        return
    exp = time.monotonic() + AUTH_SESSION_CACHE_SEC
    with _session_cache_lock:
        _session_cache[token_hash] = (dict(session), exp)


def _session_cache_invalidate(token_hash: str) -> None:
    with _session_cache_lock:
        _session_cache.pop(token_hash, None)


def _session_cache_clear() -> None:
    with _session_cache_lock:
        _session_cache.clear()


def _session_set(
    token: str,
    user_id: int,
    account_id: Optional[int],
    is_admin: bool,
    device_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> None:
    from app.boot_id import get_boot_id

    boot_id = get_boot_id()
    data = {
        "user_id": user_id,
        "account_id": account_id,
        "is_admin": is_admin,
        "boot_id": boot_id,
        "device_id": device_id,
    }
    if db is not None:
        try:
            from sqlalchemy import text

            now = datetime.utcnow()
            th = _token_hash(token)
            expires = now + timedelta(days=SESSION_TTL_DAYS)
            now_iso = now.isoformat()
            exp_iso = expires.isoformat()
            # last_seen_at optional (column may not exist on older DBs)
            db.execute(
                text("""
                    INSERT INTO auth_sessions (token_hash, user_id, account_id, is_admin, boot_id, device_id, created_at, expires_at, last_seen_at)
                    VALUES (:th, :uid, :aid, :admin, :bid, :did, :now, :exp, :now)
                """),
                {
                    "th": th,
                    "uid": user_id,
                    "aid": account_id,
                    "admin": 1 if is_admin else 0,
                    "bid": boot_id,
                    "did": device_id,
                    "now": now_iso,
                    "exp": exp_iso,
                },
            )
            db.commit()
            return
        except Exception as e:
            logger.warning(
                "auth_sessions insert failed, will try without last_seen_at or fallback to memory: %s",
                e,
            )
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.execute(
                    text("""
                        INSERT INTO auth_sessions (token_hash, user_id, account_id, is_admin, boot_id, device_id, created_at, expires_at)
                        VALUES (:th, :uid, :aid, :admin, :bid, :did, :now, :exp)
                    """),
                    {
                        "th": th,
                        "uid": user_id,
                        "aid": account_id,
                        "admin": 1 if is_admin else 0,
                        "bid": boot_id,
                        "did": device_id,
                        "now": now_iso,
                        "exp": exp_iso,
                    },
                )
                db.commit()
                return
            except Exception as e2:
                logger.warning(
                    "auth_sessions insert (no last_seen_at) failed, fallback to memory: %s",
                    e2,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
    _sessions[token] = data


def _session_get(token: str, db: Optional[Session] = None) -> Optional[dict]:
    """Validate token against shared store (DB). No boot_id in acceptance criteria (diagnostics only); multi-worker safe."""
    from app.boot_id import get_boot_id

    boot_id = get_boot_id()
    th = _token_hash(token)
    cached = _session_cache_get(th)
    if cached is not None:
        return cached
    if db is not None:
        try:
            from sqlalchemy import text

            now = datetime.utcnow()
            now_iso = now.isoformat()
            # Session valid if token_hash exists, not revoked, not expired. boot_id not used in WHERE.
            r = None
            try:
                r = db.execute(
                    text("""
                        SELECT user_id, account_id, is_admin, device_id, created_at, expires_at, last_seen_at
                        FROM auth_sessions
                        WHERE token_hash = :th AND expires_at > :now AND (COALESCE(revoked, 0) = 0)
                    """),
                    {"th": th, "now": now_iso},
                ).fetchone()
            except Exception as rev_err:
                # Fallback when revoked column not yet migrated
                if (
                    "revoked" in str(rev_err)
                    or "no such column" in str(rev_err).lower()
                ):
                    r = db.execute(
                        text("""
                            SELECT user_id, account_id, is_admin, device_id, created_at, expires_at, last_seen_at
                            FROM auth_sessions
                            WHERE token_hash = :th AND expires_at > :now
                        """),
                        {"th": th, "now": now_iso},
                    ).fetchone()
                else:
                    raise
            if r:
                # Sliding TTL: update last_seen_at/expires_at only if last activity was > SESSION_SLIDING_UPDATE_MIN_SEC ago
                do_slide = False
                if SESSION_SLIDING_ENABLED:
                    last_seen = r[6]  # last_seen_at
                    if last_seen is None:
                        do_slide = True
                    else:
                        try:
                            last_dt = (
                                datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                if isinstance(last_seen, str)
                                else last_seen
                            )
                            delta = (now - last_dt).total_seconds()
                            if delta > SESSION_SLIDING_UPDATE_MIN_SEC:
                                do_slide = True
                        except Exception:
                            do_slide = True
                else:
                    do_slide = False
                if do_slide:
                    new_expires = (now + timedelta(days=SESSION_TTL_DAYS)).isoformat()
                    try:
                        db.execute(
                            text(
                                "UPDATE auth_sessions SET last_seen_at = :now, expires_at = :exp WHERE token_hash = :th"
                            ),
                            {"now": now_iso, "exp": new_expires, "th": th},
                        )
                        db.commit()
                    except Exception as slide_err:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        logger.warning(
                            "auth_sessions sliding TTL update failed (session still valid): %s",
                            slide_err,
                        )
                session = {
                    "user_id": r[0],
                    "account_id": r[1],
                    "is_admin": bool(r[2]),
                    "boot_id": boot_id,
                    "device_id": r[3],
                }
                _session_cache_set(th, session)
                return session
        except Exception as e:
            logger.warning(
                "auth_sessions get failed (SESSION_NOT_FOUND sebebi olabilir), fallback to memory: %s",
                e,
                exc_info=False,
            )
    # In-memory fallback: do not reject on boot_id (multi-worker: acceptance is token_hash+expiry, not boot_id)
    data = _sessions.get(token)
    if not data:
        return None
    session = {
        "user_id": data["user_id"],
        "account_id": data.get("account_id"),
        "is_admin": data.get("is_admin", False),
        "boot_id": boot_id,
        "device_id": data.get("device_id"),
    }
    _session_cache_set(th, session)
    return session


def _session_drop_by_user_id(user_id: int, db: Optional[Session] = None) -> None:
    _session_cache_clear()
    if db is not None:
        try:
            from sqlalchemy import text

            db.execute(
                text("DELETE FROM auth_sessions WHERE user_id = :uid"), {"uid": user_id}
            )
            db.commit()
        except Exception:
            pass
    to_drop = [t for t, s in _sessions.items() if s.get("user_id") == user_id]
    for t in to_drop:
        _sessions.pop(t, None)


def _session_drop_by_device_id(
    user_id: int, device_id: str, db: Optional[Session] = None
) -> None:
    _session_cache_clear()
    if db is not None:
        try:
            from sqlalchemy import text

            db.execute(
                text(
                    "DELETE FROM auth_sessions WHERE user_id = :uid AND device_id = :did"
                ),
                {"uid": user_id, "did": device_id},
            )
            db.commit()
        except Exception:
            pass
    to_drop = [
        t
        for t, s in _sessions.items()
        if s.get("user_id") == user_id and s.get("device_id") == device_id
    ]
    for t in to_drop:
        _sessions.pop(t, None)


def _session_drop_by_token(token: str, db: Optional[Session] = None) -> None:
    """Invalidate session (logout): set revoked=1 when column exists, else delete row. Also clear in-memory."""
    th = _token_hash(token)
    _session_cache_invalidate(th)
    if db is not None:
        try:
            from sqlalchemy import text

            try:
                db.execute(
                    text("UPDATE auth_sessions SET revoked = 1 WHERE token_hash = :th"),
                    {"th": th},
                )
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.execute(
                    text("DELETE FROM auth_sessions WHERE token_hash = :th"), {"th": th}
                )
                db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    _sessions.pop(token, None)


def _detail_std(request: Optional[Request], error_code: str, message: str) -> dict:
    """Standard error detail with request_id when available."""
    detail = {"error_code": error_code, "message": message}
    if request and getattr(request.state, "request_id", None):
        detail["request_id"] = request.state.request_id
    return detail


def _login_401_detail(
    request: Request,
    ip: str,
    hint: str,
    message: Optional[str] = None,
    error_code: Optional[str] = None,
) -> dict:
    """401 detail for login; localhost + X-Debug-Login header ile debug_hint eklenir."""
    if message is None:
        message = "Telefon numarası veya şifre hatalı"
    if error_code is None:
        error_code = "INVALID_CREDENTIALS"
    detail = _detail_std(request, error_code, message)
    from app.services.test_account import is_localhost

    if is_localhost(ip) and (
        request.headers.get("X-Debug-Login") or request.headers.get("x-debug-login")
    ):
        detail["debug_hint"] = hint
    return detail


def _auth_validate_log(
    request: Request,
    outcome: str,
    reason: str,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """Structured AUTH_VALIDATE log line; never log raw token. MISSING_TOKEN at DEBUG to reduce log noise."""
    rid = getattr(request.state, "request_id", None)
    try:
        from app.boot_id import get_boot_id

        bid = get_boot_id()
    except Exception:
        bid = ""
    pid = os.getpid()
    log_args = (
        rid or "",
        pid,
        bid,
        session_id or "",
        outcome,
        reason,
        user_id if user_id is not None else "",
    )
    if (outcome == "FAIL" and reason == "MISSING_TOKEN") or (
        outcome == "OK" and reason == "OK"
    ):
        logger.debug(
            "AUTH_VALIDATE request_id=%s worker_pid=%s boot_id=%s session_id=%s outcome=%s reason=%s user_id=%s",
            *log_args,
        )
    else:
        logger.info(
            "AUTH_VALIDATE request_id=%s worker_pid=%s boot_id=%s session_id=%s outcome=%s reason=%s user_id=%s",
            *log_args,
        )


def _require_auth_fail(request: Request, reason: str, error_code: str, message: str):
    """Log and raise 401 with standard detail. missing_token at DEBUG to avoid log noise from unauthenticated requests."""
    rid = getattr(request.state, "request_id", None)
    if reason == "missing_token":
        logger.debug(
            "require_auth failure reason=%s error_code=%s request_id=%s",
            reason,
            error_code,
            rid,
        )
    else:
        logger.info(
            "require_auth failure reason=%s error_code=%s request_id=%s",
            reason,
            error_code,
            rid,
        )
    detail = _detail_std(request, error_code, message)
    raise HTTPException(status_code=401, detail=detail)


def _auth_allow_bearer() -> bool:
    return os.environ.get("AUTH_ALLOW_BEARER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def get_token_from_request(request: Request) -> tuple:
    """
    Return (token or None, source). Cookie-first when Bearer disabled; else Bearer first.
    source in ("bearer", "cookie") or None when missing.
    """
    auth_header = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    bearer = (
        auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
    ) or ""
    cookie = (request.cookies.get("auth_token") or "").strip()
    if _auth_allow_bearer() and bearer:
        return bearer, "bearer"
    if cookie:
        return cookie, "cookie"
    if bearer:
        return bearer, "bearer"
    return None, None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """Bearer or auth_token cookie (get_token_from_request); validate against shared session store (multi-worker safe)."""
    token, source = get_token_from_request(request)
    try:
        request.state.auth_source = source or "none"
    except Exception:
        pass
    if not token:
        _auth_validate_log(request, "FAIL", "MISSING_TOKEN")
        _require_auth_fail(
            request, "missing_token", "UNAUTHORIZED", "Giriş yapmanız gerekiyor"
        )
    th = _token_hash(token)
    session_id_log = short_session_id(th)
    session = _session_get(token, db)
    if not session:
        _auth_validate_log(
            request, "FAIL", "SESSION_NOT_FOUND", session_id=session_id_log
        )
        _require_auth_fail(
            request,
            "session_not_found",
            "SESSION_NOT_FOUND",
            "Oturum geçersiz veya sonlanmış. Lütfen tekrar giriş yapın.",
        )
    _auth_validate_log(
        request, "OK", "OK", session_id=session_id_log, user_id=session.get("user_id")
    )
    return session


async def require_admin_auth(
    request: Request, current: dict = Depends(require_auth)
) -> dict:
    """Auth zorunlu + is_admin; aksi halde 403 FORBIDDEN. Auth.router içindeki /api/admin/* route'larında kullanılır."""
    if not current.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail=_detail_std(request, "FORBIDDEN", "Bu işlem için yetkiniz yok"),
        )
    return current


def require_account_access(current: dict, account_id: int) -> None:
    """Verilen hesaba erişim yetkisi yoksa 403 fırlatır. Admin veya hesap sahibi olmalı."""
    if current.get("is_admin"):
        return
    if current.get("account_id") != account_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "message": "Bu hesaba erişim yetkiniz yok",
            },
        )


def get_account_or_403(current: dict, account_id: int, db: Session):
    """
    Hesabı DB'den yükle; yoksa 404, sahibi değilse 403.
    Yetki kaynağı her zaman session'daki user_id; URL/query asla yetki vermez.
    Return: Account or raises HTTPException.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ACCOUNT_NOT_FOUND", "message": "Hesap bulunamadı"},
        )
    if current.get("is_admin"):
        if getattr(account, "isolate_from_admin", False):
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "ACCOUNT_ISOLATED",
                    "message": "Bu hesap adminden izole; hesaba giriş yapılamaz.",
                },
            )
        return account
    if account.user_id is None or account.user_id != current.get("user_id"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "message": "Bu hesaba erişim yetkiniz yok",
            },
        )
    return account


async def require_admin_ip_allowed(
    current: dict = Depends(require_auth),
) -> dict:
    """IP onayı kaldırıldı; sadece require_auth. Binance API key zaten IP doğrulamalı."""
    return current


from app.utils.account_code import generate_account_code


def hash_password(password: str) -> str:
    """Hash password using bcrypt. Input is NFC-normalized for consistency."""
    pwd = _normalize_password(password)
    return bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: Optional[Union[str, bytes]]) -> bool:
    """Verify password against bcrypt hash. Tries NFC, NFD, then raw strip (max uyumluluk)."""
    if not password_hash:
        return False
    if (
        password_hash
        if isinstance(password_hash, str)
        else password_hash.decode("utf-8")
    ).strip() == INITIAL_ADMIN_UNSET_SENTINEL:
        return False  # İlk admin henüz şifre atanmamış; login'de ayrı işlenir
    hash_bytes = (
        password_hash
        if isinstance(password_hash, bytes)
        else password_hash.encode("utf-8")
    )

    def check(p: str) -> bool:
        try:
            return bcrypt.checkpw(p.encode("utf-8"), hash_bytes)
        except Exception:
            return False

    pwd_nfc = _normalize_password(password)
    if check(pwd_nfc):
        return True
    pwd_nfd = unicodedata.normalize("NFD", pwd_nfc)
    if pwd_nfd != pwd_nfc and check(pwd_nfd):
        return True
    pwd_raw = (password or "").strip()
    if pwd_raw != pwd_nfc and check(pwd_raw):
        return True
    return False


# İlk admin şifresi atanmamış sentinel (bcrypt değil; Invalid salt hatası önlenir)
INITIAL_ADMIN_UNSET_SENTINEL = "__INITIAL_ADMIN_UNSET__"


def get_initial_admin_unset_hash() -> str:
    """Admin bu değerle oluşturulur; ilk girişte yazılan şifre kalıcı kaydedilir."""
    return INITIAL_ADMIN_UNSET_SENTINEL


def generate_password(name: str = "", surname: str = "") -> str:
    """Generate a random password that passes validate_password_strength (validator-compliant)."""
    upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lower = "abcdefghijklmnopqrstuvwxyz"
    digits = "0123456789"
    punct = ".,!?;:"
    pool = upper + lower + digits + punct
    for _ in range(200):
        buf = [
            secrets.choice(upper),
            secrets.choice(lower),
            secrets.choice(digits),
            secrets.choice(punct),
        ]
        n = 6 + secrets.randbelow(5)
        buf.extend(secrets.choice(pool) for _ in range(n))
        random.shuffle(buf)
        pwd = "".join(buf)
        ok, _ = validate_password_strength(pwd, name or "", surname or "")
        if ok:
            return pwd
    return "Aa1." + "".join(secrets.choice(lower + digits) for _ in range(8))


def validate_password_strength(
    password: str, name: str = "", surname: str = ""
) -> tuple[bool, str]:
    """Validate password strength - returns (is_valid, error_message)"""
    if len(password) < 10:
        return False, "Şifre en az 10 karakter olmalıdır"

    # Check for uppercase and lowercase letters (including Turkish characters: Ş, Ğ, İ, Ö, Ü, Ç)
    # Use a more reliable method that works with Turkish characters
    # Compare character with its uppercase/lowercase versions to handle Turkish characters correctly
    has_upper = False
    has_lower = False
    for c in password:
        if c.isalpha():
            # For Turkish characters, check if character changes when converted to lowercase
            # This correctly identifies uppercase Turkish characters (Ş, Ğ, İ, Ö, Ü, Ç)
            if c != c.lower():
                has_upper = True
            # Check if character changes when converted to uppercase
            # This correctly identifies lowercase Turkish characters (ş, ğ, i, ö, ü, ç)
            if c != c.upper():
                has_lower = True

    has_digit = any(c.isdigit() for c in password)
    has_punct = any(c in ".,!?;:" for c in password)

    if not has_upper:
        return False, "Şifre en az 1 büyük harf içermelidir"
    if not has_lower:
        return False, "Şifre en az 1 küçük harf içermelidir"
    if not has_digit:
        return False, "Şifre en az 1 rakam içermelidir"
    if not has_punct:
        return False, "Şifre en az 1 noktalama işareti (.,!?;:) içermelidir"

    # Check if password contains name or surname (only if name/surname is at least 3 chars)
    # Use casefold() for better Turkish character handling
    password_lower = password.casefold()
    name_lower = name.casefold() if name else ""
    surname_lower = surname.casefold() if surname else ""
    if name_lower and len(name_lower) >= 3 and name_lower in password_lower:
        return False, "Şifre isminizi içeremez"
    if surname_lower and len(surname_lower) >= 3 and surname_lower in password_lower:
        return False, "Şifre soyadınızı içeremez"

    # Check for common weak passwords
    weak_passwords = [
        "password",
        "123456",
        "qwerty",
        "abc123",
        "password123",
        "admin",
        "welcome",
    ]
    if password_lower in weak_passwords:
        return False, "Bu şifre çok zayıf, lütfen daha güçlü bir şifre seçin"

    # Check for obvious sequential patterns (only flag very obvious ones)
    obvious_sequences = [
        "12345",
        "23456",
        "34567",
        "45678",
        "56789",
        "67890",
        "abcdef",
        "bcdefg",
        "cdefgh",
        "defghi",
        "efghij",
        "fghijk",
        "qwerty",
        "asdfgh",
        "zxcvbn",
    ]
    if any(seq in password_lower for seq in obvious_sequences):
        return (
            False,
            "Şifre çok belirgin sıralı karakterler içeremez (örn: 12345, qwerty)",
        )

    return True, ""


def get_client_ip(request: Request) -> str:
    """Get client IP address (supports X-Forwarded-For behind reverse proxy)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _normalize_phone(s: str) -> str:
    """Rakamlari al; 0 ile veya 0siz TR numaralarini ayni 10 haneli forma getir."""
    digits = "".join(c for c in (s or "").strip() if c.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]  # 05551234567 -> 5551234567
    if len(digits) == 12 and digits.startswith("90"):
        return digits[2:]  # 905551234567 -> 5551234567
    return digits


# Login rate limit: IP + phone, 5 attempts per minute -> 429
_login_rate: dict[str, list[datetime]] = {}
_LOGIN_RATE_WINDOW = timedelta(minutes=1)
_LOGIN_RATE_MAX = 5
_LOGIN_RATE_MAX_KEYS = 500

# Admin login: 3 yanlış şifre = 1 dakika IP bloke (admin askıya alınmaz)
import time as _time

_admin_login_block: dict[
    str, tuple[float, int]
] = {}  # ip -> (block_until_ts, wrong_count)
_ADMIN_BLOCK_DURATION_SEC = 60.0
_ADMIN_WRONG_BEFORE_BLOCK = 3


def _admin_login_blocked(ip: str) -> bool:
    """Admin girişi için bu IP bloke mi? Bloke süresi dolmuşsa temizle."""
    now = _time.time()
    if ip not in _admin_login_block:
        return False
    block_until, _ = _admin_login_block[ip]
    if now >= block_until:
        del _admin_login_block[ip]
        return False
    return True


def _admin_login_record_wrong(ip: str) -> bool:
    """Admin için yanlış şifre kaydet. 3. yanlışta True döner (bloke uygulandı)."""
    now = _time.time()
    if ip not in _admin_login_block:
        _admin_login_block[ip] = (0.0, 0)
    block_until, wrong = _admin_login_block[ip]
    wrong += 1
    if wrong % _ADMIN_WRONG_BEFORE_BLOCK == 0:
        _admin_login_block[ip] = (now + _ADMIN_BLOCK_DURATION_SEC, wrong)
        return True  # bloke uygulandı
    _admin_login_block[ip] = (block_until, wrong)
    return False


def _login_rate_limit_check(ip: str, phone_clean: str) -> bool:
    """Return True if login attempt is allowed, False if rate limited."""
    now = datetime.utcnow()
    key = f"{ip}:{phone_clean}"
    if key not in _login_rate:
        _login_rate[key] = []
    times = _login_rate[key]
    cutoff = now - _LOGIN_RATE_WINDOW
    _login_rate[key] = [t for t in times if t > cutoff]
    if len(_login_rate[key]) >= _LOGIN_RATE_MAX:
        return False
    _login_rate[key].append(now)
    if len(_login_rate) > _LOGIN_RATE_MAX_KEYS:
        empty_keys = [k for k, v in _login_rate.items() if not v]
        for k in empty_keys[: len(_login_rate) - _LOGIN_RATE_MAX_KEYS + 1]:
            _login_rate.pop(k, None)
        if len(_login_rate) > _LOGIN_RATE_MAX_KEYS:
            for k in sorted(_login_rate.keys())[
                : len(_login_rate) - _LOGIN_RATE_MAX_KEYS
            ]:
                _login_rate.pop(k, None)
    return True


class LoginRequest(BaseModel):
    phone: str  # Phone number instead of username
    password: str


class RegisterRequest(BaseModel):
    name: str
    surname: str
    phone: str
    password: str
    password_confirm: str


class PasswordResetRequestModel(BaseModel):
    phone: str  # Only phone number needed


class AdminPasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str
    new_password_confirm: str


class AdminUsernameChangeRequest(BaseModel):
    new_username: str


class AdminApproveRequest(BaseModel):
    registration_id: int
    approve: bool  # True = approve, False = reject


class AdminUnbanIPRequest(BaseModel):
    ip_address: str


class AdminSuspendUserRequest(BaseModel):
    user_id: int
    suspend: bool  # True = suspend, False = unsuspend


class AdminKickUserRequest(BaseModel):
    user_id: Optional[int] = None
    account_id: Optional[int] = None


class AdminSetUserPasswordRequest(BaseModel):
    account_id: int
    new_password: str
    new_password_confirm: str


class AdminSetUserPasswordByPhoneRequest(BaseModel):
    """Admin: telefon ile kullanici bulunup sifre atanir (yayin/local senkron icin)."""

    phone: str
    new_password: str
    new_password_confirm: str


class AdminGenerateSetPasswordRequest(BaseModel):
    account_id: int


class AdminUpdateUserPhoneRequest(BaseModel):
    account_id: int
    phone: str


class UpdatePhoneRequest(BaseModel):
    account_id: int
    phone: str


class LogoutRequest(BaseModel):
    account_id: int


class ResetAdminPasswordBySecretRequest(BaseModel):
    """Giris yapmadan admin sifresini sifirlamak icin: .env'de ADMIN_PASSWORD_RESET_SECRET tanimla, sonra bu endpoint'i cagir."""

    secret: str
    new_password: str
    new_password_confirm: str


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login endpoint - uses phone number and password. Erişim IP whitelist ile kısıtlı.
    İlk girişte kullanıcının izin verilen IP'si yoksa mevcut IP otomatik eklenir; sonraki yeni IP'ler onay bekler."""
    ip = get_client_ip(request)
    # 0 ile veya 0siz, bosluk/tire ile: hepsi ayni kanonik forma (10 hane)
    phone_raw = (
        req.phone.strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    phone_canonical = _normalize_phone(req.phone)

    # Allow shorter input for username-based login (admin, etc.)
    if not phone_raw:
        raise HTTPException(
            status_code=400, detail="Telefon numarası veya kullanıcı adı girin"
        )

    # Rate limit: configurable limiter (app/core/security/rate_limiter) or legacy in-memory
    try:
        from app.core.config import get_security_config

        sec = get_security_config()
        if sec.get("auth_rate_limit_enabled", True):
            from app.core.security.rate_limiter import check_login_rate_limit

            user_key = (phone_canonical or phone_raw or "").lower()[:64]
            allowed, retry_after = check_login_rate_limit(ip, user_key)
            if not allowed:
                detail = {
                    "error_code": "RATE_LIMITED",
                    "message": "Çok fazla giriş denemesi. Lütfen daha sonra tekrar deneyin.",
                    "retry_after": retry_after,
                }
                if getattr(request.state, "request_id", None):
                    detail["request_id"] = request.state.request_id
                raise HTTPException(status_code=429, detail=detail)
    except HTTPException:
        raise
    except Exception:
        if not _login_rate_limit_check(ip, phone_canonical or phone_raw):
            detail = {
                "error_code": "RATE_LIMITED",
                "message": "Çok fazla giriş denemesi. Lütfen bir dakika sonra tekrar deneyin.",
                "retry_after": 60,
            }
            if getattr(request.state, "request_id", None):
                detail["request_id"] = request.state.request_id
            raise HTTPException(status_code=429, detail=detail)

    # If it looks like a phone number (10+ digits), treat as phone for lookup
    is_phone_format = len(phone_canonical) >= 10

    logger.info(
        "Login attempt with phone/username: %s (is_phone_format: %s)",
        phone_raw,
        is_phone_format,
    )

    # Find user by phone: 0 ile/0siz hepsi ayni kanonik forma gider
    user = (
        db.query(User)
        .filter(
            User.phone == phone_canonical,
            or_(User.is_deleted == False, User.is_deleted.is_(None)),
        )
        .first()
    )

    # DB'de 0 ile kayitli olabilir; kanonik karsilastir
    if not user:
        all_users = (
            db.query(User)
            .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
            .all()
        )
        for u in all_users:
            if u.phone:
                stored_canonical = _normalize_phone(str(u.phone))
                if stored_canonical == phone_canonical:
                    user = u
                    logger.info(
                        "Found user by phone (canonical match): %s (ID: %s)",
                        u.username,
                        u.id,
                    )
                    break

    # Special case: If input doesn't look like a phone number, try username lookup
    if not user and not is_phone_format:
        username_match = (
            db.query(User)
            .filter(
                func.lower(User.username) == func.lower(phone_raw),
                or_(User.is_deleted == False, User.is_deleted.is_(None)),
            )
            .first()
        )

        if username_match:
            # If user found by username, allow login (even if they have a phone)
            user = username_match
            logger.info(
                f"Found user by username: {user.username} (ID: {user.id}, phone: {user.phone})"
            )

    # If not found, check pending registrations (kanonik telefon)
    if not user:
        pending_reg = (
            db.query(PendingRegistration)
            .filter(
                PendingRegistration.phone == phone_canonical,
                PendingRegistration.status == "pending",
            )
            .first()
        )
        if not pending_reg:
            for pr in (
                db.query(PendingRegistration)
                .filter(PendingRegistration.status == "pending")
                .all()
            ):
                if pr.phone and _normalize_phone(str(pr.phone)) == phone_canonical:
                    pending_reg = pr
                    break

        if pending_reg:
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "PENDING_APPROVAL",
                    "message": "Admin tarafından onay bekleniyor. Daha sonra tekrar deneyin.",
                },
            )
        # Prevent enumeration: same response as wrong password
        logger.warning("Login failed: No user found (phone/username attempted)")
        try:
            from app.middleware.request_metrics import RequestMetrics

            RequestMetrics.record_login_fail(
                ip,
                (phone_raw or phone_canonical or "")[:8] + "***",
                "invalid_credentials",
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=401,
            detail=_login_401_detail(
                request,
                ip,
                "invalid_credentials",
                message="Telefon numarası veya şifre hatalı",
                error_code="INVALID_CREDENTIALS",
            ),
        )

    # Reload user from DB to get latest status (expire and reload)
    user_id = user.id  # Save ID before expire
    db.expire(user)
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=401,
            detail=_login_401_detail(
                request,
                ip,
                "invalid_credentials",
                message="Telefon numarası veya şifre hatalı",
                error_code="INVALID_CREDENTIALS",
            ),
        )

    # Check if account is deleted
    if user.is_deleted:
        raise HTTPException(
            status_code=403,
            detail="Hesabınız admin tarafından silinmiştir. Tekrar kayıt olabilir veya admin ile iletişime geçebilirsiniz.",
        )

    # Test hesabı: sadece localhost'tan giriş
    from app.services.test_account import is_test_account_username, is_localhost

    if is_test_account_username(getattr(user, "username", None)):
        ip = get_client_ip(request)
        if not is_localhost(ip):
            raise HTTPException(
                status_code=403,
                detail="Bu hesap yalnızca yerel (localhost) ortamda kullanılabilir. Bu bilgisayarda http://127.0.0.1 üzerinden giriş yapın.",
            )

    # Admin girişi: 3 yanlışta 1 dk bloke (admin askıya alınmaz)
    if getattr(user, "is_admin", False) and _admin_login_blocked(ip):
        detail = {
            "error_code": "RATE_LIMITED",
            "message": "3 kez yanlış şifre girdiniz. 1 dakika bekleyip tekrar deneyin.",
            "retry_after": 60,
        }
        if getattr(request.state, "request_id", None):
            detail["request_id"] = request.state.request_id
        raise HTTPException(status_code=429, detail=detail)

    # İlk admin: şifre henüz atanmamışsa (sentinel hash) ilk girişte yazılan şifre kalıcı olur
    user_hash = (getattr(user, "password_hash", None) or "").strip()
    password_valid = False
    if user.is_admin and user_hash == get_initial_admin_unset_hash():
        pwd = _normalize_password(req.password or "")
        if not pwd or len(pwd) < 6:
            raise HTTPException(
                status_code=400,
                detail="İlk giriş için en az 6 karakterli bir şifre girin.",
            )
        is_valid, err = validate_password_strength(
            req.password or "", user.name or "", user.surname or ""
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=err)
        user.password_hash = hash_password(req.password or "")
        user.must_change_password = False
        db.commit()
        password_valid = True
    else:
        password_valid = verify_password(
            req.password or "", getattr(user, "password_hash", None)
        )

    if not password_valid:
        logger.warning(
            "Login failed: invalid password for user id=%s phone=%s username=%s",
            user.id,
            getattr(user, "phone", None),
            getattr(user, "username", None),
        )
        user.failed_login_attempts += 1
        db.commit()
        audit_svc.log_event(
            db,
            actor_type="user",
            event_type="LOGIN_FAILED",
            severity="WARN",
            actor_user_id=user.id,
            target_user_id=user.id,
            target_account_id=user.account_id,
            ip=ip,
            device_id=None,
            request_id=getattr(request.state, "request_id", None),
            meta={"reason": "invalid_password", "attempts": user.failed_login_attempts},
        )
        is_admin = getattr(user, "is_admin", False)
        if is_admin:
            # Admin: askıya alma yok; her 3 yanlışta 1 dk IP bloke
            blocked_now = _admin_login_record_wrong(ip)
            if blocked_now:
                detail = {
                    "error_code": "RATE_LIMITED",
                    "message": "3 kez yanlış şifre girdiniz. 1 dakika bekleyip tekrar deneyin.",
                    "retry_after": 60,
                }
                if getattr(request.state, "request_id", None):
                    detail["request_id"] = request.state.request_id
                raise HTTPException(status_code=429, detail=detail)
        else:
            # Normal kullanıcı: 3 yanlışta hesap askıya alınır
            max_failed = 3
            if user.failed_login_attempts >= max_failed:
                user.is_suspended = True
                db.commit()
                msg = f"{max_failed} kez yanlış şifre girdiniz. Hesabınız güvenlik için askıya alındı. Lütfen admin ile iletişime geçin."
                raise HTTPException(status_code=403, detail=msg)
        try:
            from app.middleware.request_metrics import RequestMetrics

            RequestMetrics.record_login_fail(
                ip, user.phone or user.username or phone_raw or "", "invalid_password"
            )
        except Exception:
            pass
        try:
            setattr(
                request.state,
                "error_log_identifier",
                (user.phone or user.username or phone_raw or "")[:128],
            )
        except Exception:
            pass
        msg = (
            "Admin girişi: şifre hatalı. Doğru şifreyi girin."
            if is_admin
            else "Telefon numarası veya şifre hatalı"
        )
        raise HTTPException(
            status_code=401,
            detail=_login_401_detail(
                request,
                ip,
                "invalid_password",
                message=msg,
                error_code="INVALID_CREDENTIALS",
            ),
        )

    # Check if suspended (log for debugging) - ONLY AFTER PASSWORD IS VERIFIED
    logger.info(
        f"Login attempt for user {user.username} (ID: {user.id}, Phone: {user.phone}): is_suspended={user.is_suspended}, is_approved={user.is_approved}, is_deleted={user.is_deleted}, password_valid={password_valid}"
    )
    if user.is_suspended:
        raise HTTPException(
            status_code=403,
            detail="Hesabınız admin tarafından askıya alınmıştır. Giriş yapamazsınız. Lütfen yönetici ile iletişime geçin.",
        )

    # Check if approved (for non-admin users)
    if not user.is_admin and not user.is_approved:
        # Check if there's a pending registration for this user
        pending_reg = (
            db.query(PendingRegistration)
            .filter(
                PendingRegistration.phone == user.phone,
                PendingRegistration.status == "pending",
            )
            .first()
        )

        if pending_reg:
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "PENDING_APPROVAL",
                    "message": "Hesabınız henüz onaylanmamış. Admin onayını bekliyorsunuz. Lütfen admin onayını bekleyin.",
                },
            )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PENDING_APPROVAL",
                "message": "Hesabınız henüz onaylanmamış. Lütfen admin onayını bekleyin.",
            },
        )

    # Check one-time password: if must_change_password=True and last_login_at is set, password was already used once
    if getattr(user, "must_change_password", False) and user.last_login_at is not None:
        raise HTTPException(
            status_code=403,
            detail="Bu şifre tek kullanımlıktır ve daha önce kullanılmıştır. Lütfen admin ile iletişime geçerek yeni şifre talep edin.",
        )

    from app.boot_id import get_boot_id

    token = secrets.token_urlsafe(32)
    account = None
    try:
        # Reset failed attempts on successful login, store IP, clear kick
        user.failed_login_attempts = 0
        user.last_login_at = datetime.utcnow()
        user.last_login_ip = get_client_ip(request)
        user.kicked_at = None
        db.commit()

        # If user has no account (e.g. legacy or manually created user), create one so dashboard can load
        if not user.account_id:
            account_code = generate_account_code(db)
            new_account = Account(
                account_code=account_code,
                name=f"{getattr(user, 'name', '') or ''} {getattr(user, 'surname', '') or ''}".strip()
                or user.username,
                exchange="BINANCE",
                api_key_enc=encrypt_text(""),
                api_secret_enc=encrypt_text(""),
                mode="live",
                is_first_login=True,
                user_id=user.id,
            )
            db.add(new_account)
            db.flush()
            db.refresh(new_account)
            user.account_id = new_account.id
            db.commit()
            db.refresh(user)
            account = new_account
            logger.info(
                "Login: created missing account for user id=%s account_id=%s account_code=%s",
                user.id,
                new_account.id,
                account_code,
            )

        # Get account if exists; ensure 6-digit account_code for identity
        if user.account_id and account is None:
            account = db.query(Account).filter(Account.id == user.account_id).first()
            if account and (
                not account.account_code or len(str(account.account_code or "")) != 6
            ):
                account.account_code = generate_account_code(db)
                db.commit()
                db.refresh(account)

        _session_set(
            token, user.id, user.account_id, bool(user.is_admin), device_id=None, db=db
        )
        audit_svc.log_event(
            db,
            actor_type="user",
            event_type="LOGIN_SUCCESS",
            severity="INFO",
            actor_user_id=user.id,
            target_user_id=user.id,
            target_account_id=user.account_id,
            ip=ip,
            device_id=None,
            request_id=getattr(request.state, "request_id", None),
            meta={"user_agent": (request.headers.get("user-agent") or "")[:200]},
        )
        if account:
            from app.services.test_account import clear_first_login_if_keys_configured

            clear_first_login_if_keys_configured(account, db)
    except Exception as e:
        logger.warning(
            "Login post-auth step failed (DB/audit), using in-memory session: %s", e
        )
        try:
            db.rollback()
        except Exception:
            pass
        try:
            account = (
                db.query(Account).filter(Account.id == user.account_id).first()
                if user.account_id
                else None
            )
        except Exception:
            account = None
        _session_set(
            token,
            user.id,
            user.account_id,
            bool(user.is_admin),
            device_id=None,
            db=None,
        )

    # Token her zaman JSON'da donsun ki admin/dashboard sessionStorage'a yazabilsin (yoksa yonlendirme login'e doner)
    include_token = True
    payload = {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "surname": user.surname,
            "is_admin": user.is_admin,
            "is_first_login": bool(getattr(account, "is_first_login", False))
            if account
            else False,
            "account_id": user.account_id,
            "account_code": account.account_code
            if account and getattr(account, "account_code", None)
            else None,
            "must_change_password": bool(getattr(user, "must_change_password", False)),
        },
        "token": token if include_token else None,
        "boot_id": get_boot_id(),
    }
    response = JSONResponse(content=payload)
    # Cookie attributes from security config
    try:
        from app.core.config import get_security_config

        sec = get_security_config()
        secure_cookie = sec.get("auth_cookie_secure_auto", True) and (
            (
                request.url.scheme
                if getattr(request, "url", None) and hasattr(request.url, "scheme")
                else ""
            )
            == "https"
        )
        if os.environ.get("AUTH_COOKIE_SECURE", "").strip() == "1":
            secure_cookie = True
        samesite = (sec.get("auth_cookie_samesite") or "Lax").strip() or "Lax"
        max_age = int(sec.get("auth_cookie_max_age_sec") or 604800)
    except Exception:
        secure_cookie = (
            (getattr(request.url, "scheme", None) == "https")
            if getattr(request, "url", None)
            else False
        )
        samesite = "lax"
        max_age = 86400 * SESSION_TTL_DAYS
        sec = {}
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite=samesite.lower(),
        secure=secure_cookie,
        max_age=max_age,
        path="/",
    )
    if sec.get("auth_csrf_double_submit"):
        csrf_token_val = secrets.token_urlsafe(32)
        response.set_cookie(
            key="csrf_token",
            value=csrf_token_val,
            httponly=False,
            samesite=samesite.lower(),
            secure=secure_cookie,
            max_age=max_age,
            path="/",
        )
    return response


@router.post("/auth/reset-admin-password-with-secret")
async def reset_admin_password_with_secret(
    req: ResetAdminPasswordBySecretRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Admin sifresini giris yapmadan sifirla. Sadece .env'de ADMIN_PASSWORD_RESET_SECRET tanimli ve gonderilen secret eslesirse calisir. Sonra bu env'i kaldirin."""
    expected = os.environ.get("ADMIN_PASSWORD_RESET_SECRET", "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="Ozellik acik degil")
    if req.secret != expected:
        raise HTTPException(status_code=401, detail="Gecersiz")
    if req.new_password != req.new_password_confirm:
        raise HTTPException(status_code=400, detail="Yeni sifreler eslesmiyor")
    admin = (
        db.query(User)
        .filter(
            User.is_admin == True,
            or_(User.is_deleted == False, User.is_deleted.is_(None)),
        )
        .first()
    )
    if not admin:
        raise HTTPException(status_code=404, detail="Admin kullanici bulunamadi")
    is_valid, err = validate_password_strength(
        req.new_password, admin.name or "", admin.surname or ""
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=err)
    admin.password_hash = hash_password(req.new_password)
    admin.failed_login_attempts = 0
    admin.must_change_password = False
    db.commit()
    ip = get_client_ip(request)
    if ip in _admin_login_block:
        del _admin_login_block[ip]
    logger.info("Admin password reset via secret for user id=%s", admin.id)
    return {
        "success": True,
        "message": "Admin sifresi guncellendi. Yeni sifre kalici olarak gecerli. ADMIN_PASSWORD_RESET_SECRET env'ini kaldirin.",
    }


@router.post("/auth/register")
async def register(
    req: RegisterRequest, request: Request, db: Session = Depends(get_db)
):
    """Register endpoint - creates pending registration"""
    # Validate passwords match
    if req.password != req.password_confirm:
        raise HTTPException(status_code=400, detail="Şifreler eşleşmiyor")

    # Validate password strength
    is_valid, error_msg = validate_password_strength(
        req.password, req.name.strip(), req.surname.strip()
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Validate phone number (0 ile veya 0siz kabul; kanonik forma getir)
    if not req.phone or not req.phone.strip():
        raise HTTPException(status_code=400, detail="Telefon numarası zorunludur")

    phone_canonical = _normalize_phone(req.phone)
    if len(phone_canonical) < 10:
        raise HTTPException(
            status_code=400,
            detail="Geçerli bir telefon numarası girin (en az 10 haneli)",
        )

    # Check if phone number already exists (kanonik karsilastir)
    for u in (
        db.query(User)
        .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
        .all()
    ):
        if u.phone and _normalize_phone(str(u.phone)) == phone_canonical:
            raise HTTPException(
                status_code=400,
                detail="Bu telefon numarası zaten kayıtlı. Şifremi unuttum seçeneğini kullanabilirsiniz.",
            )

    # Check if there's a pending registration with this phone
    for pr in (
        db.query(PendingRegistration)
        .filter(PendingRegistration.status == "pending")
        .all()
    ):
        if pr.phone and _normalize_phone(str(pr.phone)) == phone_canonical:
            raise HTTPException(
                status_code=400,
                detail="Bu telefon numarası ile zaten bekleyen bir başvuru var.",
            )

    ip_address = get_client_ip(request)

    # Check if IP is banned
    banned = (
        db.query(BannedIP)
        .filter(BannedIP.ip_address == ip_address, BannedIP.unbanned_at.is_(None))
        .first()
    )

    if banned:
        raise HTTPException(
            status_code=403,
            detail="Bu IP adresi engellenmiş. Lütfen admin ile iletişime geçin.",
        )

    # Check if there's already a pending registration from this IP
    existing = (
        db.query(PendingRegistration)
        .filter(
            PendingRegistration.ip_address == ip_address,
            PendingRegistration.status == "pending",
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400, detail="Zaten bekleyen bir başvurunuz var."
        )

    # Hash password for storage; onayda bu şifre kullanıcıya atanacak
    password_hash = hash_password(req.password)

    registration = PendingRegistration(
        name=req.name.strip(),
        surname=req.surname.strip(),
        ip_address=ip_address,
        status="pending",
        phone=phone_canonical,
        password_hash=password_hash,
    )
    db.add(registration)
    db.commit()
    db.refresh(registration)

    return {
        "success": True,
        "message": "Kayıt başvurunuz alındı. Admin onayından sonra hesabınız aktif olacaktır.",
        "registration_id": registration.id,
    }


@router.post("/auth/password-reset-request")
async def password_reset_request(
    req: PasswordResetRequestModel, request: Request, db: Session = Depends(get_db)
):
    """Request password reset - sends notification to admin (phone number only)"""
    phone_canonical = _normalize_phone(req.phone)
    if not phone_canonical or len(phone_canonical) < 10:
        raise HTTPException(
            status_code=400, detail="Geçerli bir telefon numarası girin"
        )

    # Find user by phone (0 ile/0siz ayni)
    user = None
    for u in (
        db.query(User)
        .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
        .all()
    ):
        if u.phone and _normalize_phone(str(u.phone)) == phone_canonical:
            user = u
            break

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Bu telefon numarası sistemde kayıtlı değil. Lütfen kayıt olun veya doğru telefon numarasını girin.",
        )

    # Check if there's already a pending request for this phone
    for pr in (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.status == "pending")
        .all()
    ):
        if pr.phone and _normalize_phone(str(pr.phone)) == phone_canonical:
            raise HTTPException(
                status_code=400,
                detail="Bu telefon numarası için zaten bekleyen bir şifre sıfırlama talebi var. Lütfen admin onayını bekleyin.",
            )

    # Create password reset request
    reset_req = PasswordResetRequest(
        username=user.username, phone=phone_canonical, status="pending"
    )
    db.add(reset_req)
    db.commit()

    return {
        "success": True,
        "message": "Şifre sıfırlama talebiniz admin paneline iletildi. Admin iletişime geçecektir.",
    }


@router.get("/auth/me")
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    """Get current user info (placeholder - will use JWT later)"""
    # For now, return None - will be implemented with proper JWT
    return {"user": None}


@router.get("/auth/whoami")
async def whoami(
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return current session identity for quick verification. Admin sayfasi token yoksa cookie ile whoami cagirip sessionStorage doldurabilir."""
    user = db.query(User).filter(User.id == current["user_id"]).first()
    account = (
        db.query(Account).filter(Account.id == current["account_id"]).first()
        if current.get("account_id")
        else None
    )
    return {
        "user_id": current["user_id"],
        "account_id": current.get("account_id"),
        "username": user.username if user else None,
        "name": getattr(user, "name", None) or "",
        "surname": getattr(user, "surname", None) or "",
        "is_admin": bool(current.get("is_admin")),
        "account_code": account.account_code
        if account and getattr(account, "account_code", None)
        else None,
    }


@router.get("/auth/popup/active")
async def get_active_popup(
    first_login: bool = Query(False, description="İlk giriş yapan kullanıcı mı"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Giriş yapan kullanıcı için geçerli pop-up döner. max_shows_per_user kadar kapatana kadar tekrar gösterilir."""
    from datetime import datetime as _dt

    now = _dt.utcnow()
    target = "first_login" if first_login else "normal_user"
    user_id = current.get("user_id")
    if not user_id:
        return {"popup": None}
    q = (
        db.query(AdminPopup)
        .filter(
            AdminPopup.target == target,
            AdminPopup.valid_until >= now,
        )
        .order_by(AdminPopup.created_at.desc())
    )
    for p in q.limit(10).all():
        max_show = getattr(p, "max_shows_per_user", None) or 1
        dismissal_count = (
            db.query(func.count(AdminPopupDismissal.id))
            .filter(
                AdminPopupDismissal.user_id == user_id,
                AdminPopupDismissal.popup_id == p.id,
            )
            .scalar()
            or 0
        )
        if dismissal_count < max_show:
            return {
                "popup": {
                    "id": p.id,
                    "title_key": p.title_key,
                    "message": p.message,
                    "valid_until": p.valid_until.isoformat()
                    if hasattr(p.valid_until, "isoformat")
                    else str(p.valid_until),
                }
            }
    return {"popup": None}


class DismissPopupRequest(BaseModel):
    popup_id: int


@router.post("/auth/popup/dismiss")
async def dismiss_popup(
    req: DismissPopupRequest,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Kullanıcı pop-up'i kapatti; max_shows_per_user kadar kapatma kaydi tutulur, o sayiya ulasana kadar tekrar gosterilir."""
    user_id = current.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Giriş gerekli")
    db.add(AdminPopupDismissal(user_id=user_id, popup_id=req.popup_id))
    db.commit()
    return {"success": True}


@router.get("/auth/ping")
async def auth_ping(
    account_id: int = Query(..., description="Account ID"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Update last_activity_at for user on this account; return kicked status. Dashboard calls periodically.
    kicked=true when user was kicked (kicked_at) or suspended (is_suspended) → redirect to login.
    Requires auth and ownership of the given account."""
    get_account_or_403(current, account_id, db)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account or not account.user_id:
        return {"kicked": False}
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        return {"kicked": False}
    user.last_activity_at = datetime.utcnow()
    db.commit()
    kicked = user.kicked_at is not None or bool(user.is_suspended)
    return {"kicked": kicked}


@router.post("/auth/logout")
async def logout(
    req: LogoutRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Secure logout: invalidate session in shared store, set last_logout_at, clear cookie."""
    token = None
    if request.cookies.get("auth_token"):
        token = request.cookies.get("auth_token")
    auth_header = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if token:
        _session_drop_by_token(token, db)
    user = db.query(User).filter(User.account_id == req.account_id).first()
    if user:
        user.last_logout_at = datetime.utcnow()
        db.commit()
        audit_svc.log_event(
            db,
            actor_type="user",
            event_type="LOGOUT",
            severity="INFO",
            actor_user_id=user.id,
            target_user_id=user.id,
            target_account_id=req.account_id,
            ip=get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )
    response = JSONResponse(
        content={"success": True, "message": "Güvenli çıkış yapıldı."}
    )
    secure_cookie = os.environ.get("AUTH_COOKIE_SECURE", "").strip() == "1"
    if not secure_cookie and request and getattr(request, "url", None):
        secure_cookie = (
            request.url.scheme if hasattr(request.url, "scheme") else ""
        ) == "https"
    response.delete_cookie(
        key="auth_token", path="/", secure=secure_cookie, samesite="lax", httponly=True
    )
    return response


@router.get("/admin/pending-registrations")
async def get_pending_registrations(
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Get pending registrations (admin only)"""
    pending = (
        db.query(PendingRegistration)
        .filter(PendingRegistration.status == "pending")
        .order_by(PendingRegistration.created_at.desc())
        .all()
    )

    return {
        "pending": [
            {
                "id": r.id,
                "name": r.name,
                "surname": r.surname,
                "phone": r.phone if hasattr(r, "phone") else "",
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in pending
        ],
        "count": len(pending),
    }


@router.post("/admin/approve-registration")
async def approve_registration(
    req: AdminApproveRequest,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Approve or reject registration (admin only)"""
    registration = (
        db.query(PendingRegistration)
        .filter(PendingRegistration.id == req.registration_id)
        .first()
    )

    if not registration:
        raise HTTPException(status_code=404, detail="Başvuru bulunamadı")

    # Check if already approved or rejected
    if registration.status == "approved":
        raise HTTPException(status_code=400, detail="Bu başvuru zaten onaylanmış")
    if registration.status == "rejected":
        raise HTTPException(status_code=400, detail="Bu başvuru zaten reddedilmiş")

    if req.approve:
        # Get phone number safely (kanonik form)
        phone_canonical = None
        if hasattr(registration, "phone") and registration.phone:
            phone_canonical = _normalize_phone(str(registration.phone))
            if len(phone_canonical) >= 10:
                for u in (
                    db.query(User)
                    .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
                    .all()
                ):
                    if u.phone and _normalize_phone(str(u.phone)) == phone_canonical:
                        raise HTTPException(
                            status_code=400,
                            detail="Bu telefon numarası ile zaten bir kullanıcı kayıtlı",
                        )

        # Create user and account
        username = f"{registration.name.lower()}.{registration.surname.lower()}"
        # Make username unique
        base_username = username
        counter = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{base_username}{counter}"
            counter += 1

        # Kayıt sırasında girilen şifreyi kullan (varsa); yoksa geçici şifre (eski kayıtlar)
        stored_hash = (
            getattr(registration, "password_hash", None) if registration else None
        )
        temp_password = None
        if stored_hash and isinstance(stored_hash, str) and len(stored_hash) > 10:
            user_password_hash = stored_hash
        else:
            temp_password = secrets.token_urlsafe(12)
            user_password_hash = hash_password(temp_password)
        user = User(
            username=username,
            password_hash=user_password_hash,
            name=registration.name,
            surname=registration.surname,
            phone=phone_canonical,
            is_admin=False,
            is_approved=True,
            is_suspended=False,
        )
        db.add(user)
        db.flush()
        db.refresh(user)  # Get user.id

        # Generate unique account code
        account_code = generate_account_code(db)

        # Create account with user_id
        account = Account(
            account_code=account_code,
            name=f"{registration.name} {registration.surname}",
            exchange="BINANCE",
            api_key_enc=encrypt_text(""),
            api_secret_enc=encrypt_text(""),
            mode="live",
            is_first_login=True,
            user_id=user.id,
        )
        db.add(account)
        db.flush()
        db.refresh(account)  # Get account.id

        # Now set user.account_id
        user.account_id = account.id
        registration.status = "approved"
        registration.approved_at = datetime.utcnow()

        try:
            db.commit()
        except Exception as e:
            error_msg = str(e)
            # Try to rollback, but ignore errors during rollback
            try:
                db.rollback()
            except Exception:
                # Ignore rollback errors - they're usually about non-persisted instances
                pass

            if "UNIQUE constraint failed: users.account_id" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail="Hesap ID çakışması. Lütfen sayfayı yenileyip tekrar deneyin.",
                )
            raise HTTPException(
                status_code=500, detail=f"Kullanıcı oluşturulamadı: {error_msg}"
            )

        return {
            "success": True,
            "message": "Kullanıcı onaylandı",
            "username": username,
            "temp_password": temp_password,  # Sadece eski kayıtlarda (şifre saklanmamışsa) dolu; admin paylaşabilir
        }
    else:
        # Reject - ban IP
        registration.status = "rejected"
        registration.rejected_at = datetime.utcnow()

        # Check if IP already banned
        existing_ban = (
            db.query(BannedIP)
            .filter(
                BannedIP.ip_address == registration.ip_address,
                BannedIP.unbanned_at.is_(None),
            )
            .first()
        )

        ip_banned = False
        if not existing_ban:
            try:
                banned_ip = BannedIP(
                    ip_address=registration.ip_address, reason="Registration rejected"
                )
                db.add(banned_ip)
                db.flush()
                ip_banned = True
            except Exception:
                # IP might already be banned (race condition or UNIQUE constraint)
                db.rollback()
                # Re-check if it exists now
                existing_ban = (
                    db.query(BannedIP)
                    .filter(
                        BannedIP.ip_address == registration.ip_address,
                        BannedIP.unbanned_at.is_(None),
                    )
                    .first()
                )
                if existing_ban:
                    ip_banned = True
                # Continue with registration rejection even if IP ban failed

        try:
            db.commit()
        except Exception:
            db.rollback()
            # If commit fails, try again with just the registration status update
            registration.status = "rejected"
            registration.rejected_at = datetime.utcnow()
            db.commit()

        message = "Başvuru reddedildi" + (" ve IP engellendi" if ip_banned else "")
        return {"success": True, "message": message}


@router.get("/admin/password-reset-requests")
async def get_password_reset_requests(
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Get password reset requests (admin only)"""
    requests = (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.status == "pending")
        .order_by(PasswordResetRequest.created_at.desc())
        .all()
    )

    result = []
    for r in requests:
        user = db.query(User).filter(User.username == r.username).first()
        result.append(
            {
                "id": r.id,
                "username": r.username,
                "phone": r.phone,
                "user_name": user.name if user else "",
                "user_surname": user.surname if user else "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )

    return {"requests": result, "count": len(requests)}


@router.post("/admin/password-reset-requests/{request_id}/dismiss")
async def dismiss_password_reset_request(
    request_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Mark password reset request as completed/dismissed (admin only). Removes from pending list. Idempotent."""
    r = (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.id == request_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Talep bulunamadı")
    if r.status == "completed":
        return {"success": True, "message": "Talep zaten kapatılmış"}
    r.status = "completed"
    r.completed_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Talep kapatıldı"}


@router.get("/admin/banned-ips")
async def get_banned_ips(
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Get banned IPs (admin only)"""
    banned = db.query(BannedIP).filter(BannedIP.unbanned_at.is_(None)).all()

    return {
        "banned_ips": [
            {
                "id": b.id,
                "ip_address": b.ip_address,
                "reason": b.reason,
                "banned_at": b.banned_at.isoformat() if b.banned_at else None,
            }
            for b in banned
        ]
    }


@router.post("/admin/unban-ip")
async def unban_ip(
    req: AdminUnbanIPRequest,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Unban IP (admin only)"""
    banned = (
        db.query(BannedIP)
        .filter(BannedIP.ip_address == req.ip_address, BannedIP.unbanned_at.is_(None))
        .first()
    )

    if not banned:
        raise HTTPException(
            status_code=404, detail="IP bulunamadı veya zaten engeli kaldırılmış"
        )

    banned.unbanned_at = datetime.utcnow()
    db.commit()

    return {"success": True, "message": "IP engeli kaldırıldı"}


@router.delete("/admin/contact-messages/{message_id}")
async def delete_contact_message(
    message_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Delete contact message (admin only)"""
    message = db.query(ContactMessage).filter(ContactMessage.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı")

    db.delete(message)
    db.commit()

    return {"success": True, "message": "Mesaj silindi"}


@router.post("/admin/suspend-user")
async def suspend_user(
    req: AdminSuspendUserRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Suspend or unsuspend user (admin only). On suspend, also set kicked_at so user is
    logged out immediately; they cannot log back in until unsuspended."""
    user = db.query(User).filter(User.id == req.user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    user.is_suspended = req.suspend
    if req.suspend:
        user.kicked_at = datetime.utcnow()
    else:
        user.failed_login_attempts = 0
        user.kicked_at = None

    db.commit()
    if req.suspend:
        _session_drop_by_user_id(user.id, db)

    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_USER_SUSPENDED" if req.suspend else "ADMIN_USER_UNSUSPENDED",
        severity="WARN" if req.suspend else "INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=user.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"user_id": user.id, "suspend": req.suspend},
    )
    return {
        "success": True,
        "message": "Kullanıcı askıya alındı"
        if req.suspend
        else "Kullanıcı askıdan çıkarıldı",
    }


@router.post("/admin/change-password")
async def admin_change_password(
    req: AdminPasswordChangeRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Change admin password (admin only)"""
    admin = db.query(User).filter(User.is_admin == True).first()

    if not admin:
        raise HTTPException(status_code=404, detail="Admin kullanıcı bulunamadı")
    if not verify_password(req.old_password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Eski şifre hatalı")
    if req.new_password != req.new_password_confirm:
        raise HTTPException(status_code=400, detail="Yeni şifreler eşleşmiyor")
    is_valid, error_msg = validate_password_strength(
        req.new_password, admin.name, admin.surname
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    admin.password_hash = hash_password(req.new_password)
    db.commit()

    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_PASSWORD_CHANGE",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=admin.id,
        target_account_id=admin.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"remark": "admin_own_password"},
    )
    return {"success": True, "message": "Şifre değiştirildi"}


@router.post("/admin/change-username")
async def admin_change_username(
    req: AdminUsernameChangeRequest,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Change admin username (admin only)"""
    # Get admin user (first admin)
    admin = db.query(User).filter(User.is_admin == True).first()

    if not admin:
        raise HTTPException(status_code=404, detail="Admin kullanıcı bulunamadı")

    # Validate new username
    new_username = req.new_username.strip()
    if not new_username or len(new_username) < 3:
        raise HTTPException(
            status_code=400, detail="Kullanıcı adı en az 3 karakter olmalıdır"
        )

    # Check if username already exists
    existing_user = (
        db.query(User)
        .filter(User.username == new_username, User.id != admin.id)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=400, detail="Bu kullanıcı adı zaten kullanılıyor"
        )

    # Update username
    admin.username = new_username
    db.commit()

    return {
        "success": True,
        "message": "Kullanıcı adı değiştirildi",
        "username": new_username,
    }


@router.post("/admin/kick-user")
async def kick_user(
    req: AdminKickUserRequest,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Kick user from account (admin only). User can log in again; session is dropped so they are logged out immediately."""
    user = None
    if req.user_id:
        user = db.query(User).filter(User.id == req.user_id).first()
    elif req.account_id:
        acc = db.query(Account).filter(Account.id == req.account_id).first()
        if acc and acc.user_id:
            user = db.query(User).filter(User.id == acc.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı veya hesap bulunamadı")
    user.kicked_at = datetime.utcnow()
    db.commit()
    _session_drop_by_user_id(user.id, db)
    return {"success": True, "message": "Kullanıcı hesaptan çıkarıldı"}


@router.post("/admin/generate-and-set-user-password")
async def admin_generate_and_set_user_password(
    req: AdminGenerateSetPasswordRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Generate validator-compliant password, set it for account's user, mark one-time. Admin copies and shares."""
    user = db.query(User).filter(User.account_id == req.account_id).first()
    if not user:
        raise HTTPException(
            status_code=404, detail="Bu hesaba bağlı kullanıcı bulunamadı"
        )
    pwd = generate_password(user.name or "", user.surname or "")
    user.password_hash = hash_password(pwd)
    user.must_change_password = True
    user.last_login_at = None
    db.commit()

    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_USER_PASSWORD_SET",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"account_id": req.account_id, "mode": "generated"},
    )
    return {
        "success": True,
        "message": "Şifre oluşturuldu ve ayarlandı. Tek kullanımlıktır.",
        "generated_password": pwd,
    }


@router.post("/admin/set-user-password")
async def admin_set_user_password(
    req: AdminSetUserPasswordRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Set password for account's user (admin only). One-time use."""
    user = db.query(User).filter(User.account_id == req.account_id).first()
    if not user:
        raise HTTPException(
            status_code=404, detail="Bu hesaba bağlı kullanıcı bulunamadı"
        )
    if req.new_password != req.new_password_confirm:
        raise HTTPException(status_code=400, detail="Yeni şifreler eşleşmiyor")
    is_valid, err = validate_password_strength(
        req.new_password, user.name, user.surname
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=err)
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = True
    user.last_login_at = None
    db.commit()

    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_USER_PASSWORD_SET",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"account_id": req.account_id, "mode": "set"},
    )
    return {"success": True, "message": "Şifre güncellendi"}


@router.post("/admin/set-user-password-by-phone")
async def admin_set_user_password_by_phone(
    req: AdminSetUserPasswordByPhoneRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Telefon numarasi ile kullanici bulunur, sifresi atanir (yayin/local ayni sifre icin). Admin only."""
    if req.new_password != req.new_password_confirm:
        raise HTTPException(status_code=400, detail="Yeni sifreler eslesmiyor")
    phone_canonical = _normalize_phone(req.phone)
    if len(phone_canonical) < 10:
        raise HTTPException(
            status_code=400, detail="Gecerli telefon numarasi girin (en az 10 rakam)"
        )
    user = (
        db.query(User)
        .filter(
            User.phone == phone_canonical,
            or_(User.is_deleted == False, User.is_deleted.is_(None)),
        )
        .first()
    )
    if not user:
        for u in (
            db.query(User)
            .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
            .all()
        ):
            if u.phone and _normalize_phone(str(u.phone)) == phone_canonical:
                user = u
                break
    if not user:
        raise HTTPException(
            status_code=404, detail="Bu telefon numarasina kayitli kullanici bulunamadi"
        )
    is_valid, err = validate_password_strength(
        req.new_password, user.name or "", user.surname or ""
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=err)
    user.password_hash = hash_password(req.new_password)
    user.failed_login_attempts = 0
    user.must_change_password = False
    db.commit()
    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_USER_PASSWORD_SET",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=user.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"by": "phone", "phone_masked": phone_canonical[:3] + "***"},
    )
    return {"success": True, "message": "Sifre guncellendi", "username": user.username}


@router.post("/admin/update-user-phone")
async def admin_update_user_phone(
    req: AdminUpdateUserPhoneRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Admin: update phone for account's user."""
    user = db.query(User).filter(User.account_id == req.account_id).first()
    if not user:
        raise HTTPException(
            status_code=404, detail="Bu hesaba bağlı kullanıcı bulunamadı"
        )
    phone_clean = _normalize_phone(req.phone)
    if len(phone_clean) < 10:
        raise HTTPException(
            status_code=400, detail="Geçerli telefon numarası girin (en az 10 rakam)"
        )
    other = (
        db.query(User)
        .filter(
            User.phone == phone_clean,
            User.id != user.id,
            or_(User.is_deleted == False, User.is_deleted.is_(None)),
        )
        .first()
    )
    if other:
        raise HTTPException(
            status_code=400, detail="Bu telefon numarası başka bir kullanıcıda kayıtlı"
        )
    user.phone = phone_clean
    db.commit()
    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="ADMIN_USER_PHONE_UPDATE",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"account_id": req.account_id, "field": "phone"},
    )
    return {"success": True, "message": "Telefon güncellendi"}


@router.post("/auth/update-phone")
async def user_update_phone(
    req: UpdatePhoneRequest,
    request: Request,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """User: update own phone (dashboard Ayarlar)."""
    if current.get("account_id") != req.account_id:
        raise HTTPException(status_code=403, detail="Bu hesaba erişim yetkiniz yok")
    user = db.query(User).filter(User.account_id == req.account_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if user.is_deleted:
        raise HTTPException(status_code=403, detail="Hesabınız silinmiştir")
    if user.is_suspended:
        raise HTTPException(
            status_code=403,
            detail="Hesabınız admin tarafından askıya alınmıştır. Lütfen yönetici ile iletişime geçin.",
        )
    phone_clean = _normalize_phone(req.phone)
    if len(phone_clean) < 10:
        raise HTTPException(
            status_code=400, detail="Geçerli telefon numarası girin (en az 10 rakam)"
        )
    other = (
        db.query(User)
        .filter(
            User.phone == phone_clean,
            User.id != user.id,
            or_(User.is_deleted == False, User.is_deleted.is_(None)),
        )
        .first()
    )
    if other:
        raise HTTPException(
            status_code=400, detail="Bu telefon numarası başka bir kullanıcıda kayıtlı"
        )
    user.phone = phone_clean
    db.commit()
    audit_svc.log_event(
        db,
        actor_type="user",
        event_type="PHONE_UPDATE",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"field": "phone"},
    )
    return {"success": True, "message": "Telefon güncellendi"}


class UserPasswordChangeRequest(BaseModel):
    account_id: int
    new_password: str
    new_password_confirm: str


@router.post("/auth/change-password")
async def user_change_password(
    req: UserPasswordChangeRequest,
    request: Request,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Change user password (for regular users)"""
    if current.get("account_id") != req.account_id:
        raise HTTPException(status_code=403, detail="Bu hesaba erişim yetkiniz yok")
    user = db.query(User).filter(User.account_id == req.account_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    if user.is_deleted:
        raise HTTPException(status_code=403, detail="Hesabınız silinmiştir")
    if user.is_suspended:
        raise HTTPException(
            status_code=403,
            detail="Hesabınız admin tarafından askıya alınmıştır. Lütfen yönetici ile iletişime geçin.",
        )
    if req.new_password != req.new_password_confirm:
        raise HTTPException(status_code=400, detail="Şifreler eşleşmiyor")
    is_valid, error_msg = validate_password_strength(
        req.new_password, user.name, user.surname
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    db.commit()

    audit_svc.log_event(
        db,
        actor_type="user",
        event_type="PASSWORD_CHANGE",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
    )
    return {"success": True, "message": "Şifre başarıyla değiştirildi"}


class ContactMessageRequest(BaseModel):
    name: str = ""  # Optional - will use user's info if not provided
    surname: str = ""  # Optional - will use user's info if not provided
    phone: str = ""  # Optional - will use user's info if not provided
    message: str


@router.post("/auth/contact")
async def send_contact_message(
    req: ContactMessageRequest, request: Request, db: Session = Depends(get_db)
):
    """Send contact message to admin (only approved users)"""
    # Validate message
    if not req.message or len(req.message.strip()) < 1:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")

    if len(req.message.strip()) > 50:
        raise HTTPException(
            status_code=400, detail="Mesaj en fazla 50 karakter olabilir"
        )

    ip_address = get_client_ip(request)

    # Get user info from request - name, surname, phone are optional
    name = req.name.strip() if req.name and req.name.strip() else ""
    surname = req.surname.strip() if req.surname and req.surname.strip() else ""
    phone_clean = None
    user_id = None

    # Try to find user by phone if provided
    if req.phone and req.phone.strip():
        phone_clean = (
            req.phone.strip()
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if len(phone_clean) >= 10:
            user = (
                db.query(User)
                .filter(
                    User.phone == phone_clean,
                    or_(User.is_deleted == False, User.is_deleted.is_(None)),
                )
                .first()
            )
            if user:
                if not user.is_approved:
                    raise HTTPException(
                        status_code=403,
                        detail="Hesabınız henüz onaylanmamış. Mesaj göndermek için hesabınızın onaylanması gerekiyor.",
                    )
                # Use user's info
                name = user.name
                surname = user.surname
                phone_clean = user.phone
                user_id = user.id

    # If name/surname not provided, use defaults (will be shown in admin panel)
    if not name:
        name = "Bilinmeyen"
    if not surname:
        surname = "Kullanıcı"

    # Check if there's a recent pending message (not replied yet)
    # Only block if message is still "pending" (not read by admin) and was created in the last 24 hours
    # Allow new messages if:
    # - Message is "read" (admin has seen it, even if not replied)
    # - Message is older than 24 hours
    # - Message has admin_reply (already replied)
    from datetime import timedelta

    cutoff_time = datetime.utcnow() - timedelta(hours=24)

    if user_id:
        # Check for recent pending messages (not read, not replied, within 24h)
        recent_pending = (
            db.query(ContactMessage)
            .filter(
                ContactMessage.user_id == user_id,
                ContactMessage.status
                == "pending",  # Only block if still pending (not read)
                ContactMessage.admin_reply.is_(None),
                ContactMessage.created_at >= cutoff_time,
            )
            .first()
        )

        if recent_pending:
            raise HTTPException(
                status_code=400,
                detail="Cevap bekleyen bir mesajınız var. Admin mesajı okuyana kadar yeni mesaj gönderemezsiniz.",
            )
    else:
        # If no user_id, check by IP (for cases where user is not found by phone)
        recent_pending = (
            db.query(ContactMessage)
            .filter(
                ContactMessage.ip_address == ip_address,
                ContactMessage.status
                == "pending",  # Only block if still pending (not read)
                ContactMessage.admin_reply.is_(None),
                ContactMessage.created_at >= cutoff_time,
            )
            .first()
        )

        if recent_pending:
            raise HTTPException(
                status_code=400,
                detail="Cevap bekleyen bir mesajınız var. Admin mesajı okuyana kadar yeni mesaj gönderemezsiniz.",
            )

    # Create contact message
    contact_msg = ContactMessage(
        user_id=user_id,
        name=name,
        surname=surname,
        phone=phone_clean or "",
        message=req.message.strip()[:50],
        ip_address=ip_address,
        status="pending",
    )
    db.add(contact_msg)
    db.commit()

    return {
        "success": True,
        "message": "Mesajınız admin paneline iletildi. En kısa sürede cevap verilecektir.",
    }


@router.get("/admin/contact-messages")
async def get_contact_messages(
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Get contact messages (admin only)"""
    messages = db.query(ContactMessage).order_by(ContactMessage.created_at.desc()).all()

    # Check actual IP ban status for each message and get user info
    result_messages = []
    for m in messages:
        # Get user info if user_id exists
        user_name = m.name
        user_surname = m.surname
        user_phone = m.phone

        if m.user_id:
            user = db.query(User).filter(User.id == m.user_id).first()
            if user:
                user_name = user.name
                user_surname = user.surname
                user_phone = user.phone or m.phone

        # Check if IP is actually banned (real-time check)
        is_ip_banned = False
        if m.ip_address:
            banned_ip = (
                db.query(BannedIP)
                .filter(
                    BannedIP.ip_address == m.ip_address, BannedIP.unbanned_at.is_(None)
                )
                .first()
            )
            is_ip_banned = banned_ip is not None

        result_messages.append(
            {
                "id": m.id,
                "user_id": m.user_id,
                "name": user_name,
                "surname": user_surname,
                "phone": user_phone,
                "message": m.message,
                "ip_address": m.ip_address,
                "status": m.status,
                "admin_reply": m.admin_reply,
                "ip_banned": is_ip_banned,  # Real-time check instead of stored flag
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "read_at": m.read_at.isoformat() if m.read_at else None,
                "replied_at": m.replied_at.isoformat() if m.replied_at else None,
            }
        )

    return {"messages": result_messages, "count": len(result_messages)}


class ContactReplyRequest(BaseModel):
    message_id: int
    reply: str = ""  # Optional, can be empty if only banning IP
    ban_ip: bool = False


@router.post("/admin/contact-reply")
async def reply_contact_message(
    req: ContactReplyRequest,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Reply to contact message and optionally ban IP (admin only)"""
    message = (
        db.query(ContactMessage).filter(ContactMessage.id == req.message_id).first()
    )

    if not message:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı")

    # Only update reply fields if reply is provided
    if req.reply.strip():
        message.status = "replied"
        message.admin_reply = req.reply.strip()
        message.replied_at = datetime.utcnow()
        message.read_at = datetime.utcnow()  # Mark as read when replying
    else:
        # If no reply, just mark as read
        if not message.read_at:
            message.read_at = datetime.utcnow()
            message.status = "read"

    # Ban IP if requested
    if req.ban_ip:
        message.ip_banned = True
        # Check if IP already banned
        existing_ban = (
            db.query(BannedIP)
            .filter(
                BannedIP.ip_address == message.ip_address,
                BannedIP.unbanned_at.is_(None),
            )
            .first()
        )

        if not existing_ban:
            banned_ip = BannedIP(
                ip_address=message.ip_address,
                reason=f"Contact message abuse: {message.message[:50]}",
            )
            db.add(banned_ip)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        error_msg = str(e)
        # If it's a UNIQUE constraint error for IP, IP is already banned
        if "UNIQUE constraint failed: banned_ips.ip_address" in error_msg:
            # IP is already banned, just mark message as banned and commit
            message.ip_banned = True
            # Re-check if ban exists
            existing_ban = (
                db.query(BannedIP)
                .filter(
                    BannedIP.ip_address == message.ip_address,
                    BannedIP.unbanned_at.is_(None),
                )
                .first()
            )
            if not existing_ban:
                # Try to get the existing ban (might have unbanned_at set)
                existing_ban_any = (
                    db.query(BannedIP)
                    .filter(BannedIP.ip_address == message.ip_address)
                    .order_by(BannedIP.banned_at.desc())
                    .first()
                )
                if existing_ban_any:
                    # Re-activate the ban
                    existing_ban_any.unbanned_at = None
            db.commit()
        else:
            # Other error, re-raise
            raise

    if req.ban_ip:
        return {"success": True, "message": "IP adresi engellendi"}
    elif req.reply.strip():
        return {"success": True, "message": "Cevap gönderildi"}
    else:
        return {"success": True, "message": "Mesaj okundu olarak işaretlendi"}


@router.get("/auth/contact-history")
async def get_contact_history(request: Request, db: Session = Depends(get_db)):
    """Get contact message history for current user"""
    # Get account_id from query parameter
    account_id = request.query_params.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id gerekli")

    try:
        account_id_int = int(account_id)
    except:
        raise HTTPException(status_code=400, detail="Geçersiz account_id")

    # Get account and user
    account = db.query(Account).filter(Account.id == account_id_int).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    # Get all contact messages for this user
    messages = (
        db.query(ContactMessage)
        .filter(ContactMessage.user_id == user.id)
        .order_by(ContactMessage.created_at.asc())
        .all()
    )

    result = []
    for m in messages:
        result.append(
            {
                "id": m.id,
                "user_message": m.message,
                "admin_reply": m.admin_reply,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "replied_at": m.replied_at.isoformat() if m.replied_at else None,
            }
        )

    return {"messages": result, "count": len(result)}


@router.post("/admin/contact-read")
async def mark_contact_read(
    message_id: int = Body(...),
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Mark contact message as read (admin only)"""
    message = db.query(ContactMessage).filter(ContactMessage.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı")

    if not message.read_at:
        message.read_at = datetime.utcnow()
        message.status = "read"
        db.commit()

    return {"success": True, "message": "Mesaj okundu olarak işaretlendi"}


# ----- Chat (WhatsApp-style admin-user) -----
MAX_CHAT_BODY = 2000


def _get_or_create_thread_for_user(
    db: Session, user_id: int, account_id: Optional[int]
) -> ChatThread:
    t = db.query(ChatThread).filter(ChatThread.user_id == user_id).first()
    if t:
        if t.account_id != account_id and account_id is not None:
            t.account_id = account_id
            db.commit()
        return t
    t = ChatThread(user_id=user_id, account_id=account_id)
    db.add(t)
    db.commit()
    return t


# Sohbeti başlatmak için açtığında giden otomatik mesaj (admin tarafından görünür)
WELCOME_CHAT_BODY = "Merhaba, size nasıl yardımcı olabiliriz?"

# Admin "yazıyor" göstergesi: thread_id -> son typing zamanı (unix timestamp)
_admin_typing_by_thread: dict = {}
ADMIN_TYPING_TTL_SEC = 5


@router.get("/auth/chat")
async def get_chat(
    account_id: int = Query(..., description="Account ID"),
    open: Optional[int] = Query(
        None, description="1 when user opens chat to send message"
    ),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Get chat thread + messages. Sohbet ilk kez açıldığında (mesaj yoksa) otomatik hoş geldin mesajı eklenir.
    Creates thread on first open; adds welcome message if empty. Requires auth and ownership."""
    get_account_or_403(current, account_id, db)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    if not account.user_id:
        return {
            "thread_id": None,
            "locked": False,
            "ended": False,
            "rating": None,
            "messages": [],
            "count": 0,
        }
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        return {
            "thread_id": None,
            "locked": False,
            "ended": False,
            "rating": None,
            "messages": [],
            "count": 0,
        }
    thread = db.query(ChatThread).filter(ChatThread.user_id == user.id).first()
    if not thread:
        thread = _get_or_create_thread_for_user(db, user.id, account_id)
    db.refresh(thread)  # güncel reopened_at için
    reopened_at = getattr(thread, "reopened_at", None)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.thread_id == thread.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    if reopened_at:
        # Yeni sohbet: sadece reopen sonrası mesajlar; kullanıcı ekranı sıfırdan sohbet görsün
        msgs = [m for m in msgs if m.created_at and m.created_at >= reopened_at]
    # İlk kez sohbet açıldığında (henüz reopen yok, mesaj yok) tek seferlik hoş geldin; reopen'da mesaj _reopen_chat_impl'de eklenir
    if reopened_at is None and len(msgs) == 0 and open:
        has_any_welcome = (
            db.query(ChatMessage.id)
            .filter(
                ChatMessage.thread_id == thread.id,
                ChatMessage.sender_type == "admin",
                ChatMessage.body == WELCOME_CHAT_BODY,
            )
            .limit(1)
            .first()
        )
        if not has_any_welcome:
            welcome = ChatMessage(
                thread_id=thread.id, sender_type="admin", body=WELCOME_CHAT_BODY
            )
            db.add(welcome)
            db.commit()
        msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
    locked = thread.locked_at is not None
    ended = thread.ended_at is not None
    messages = [
        {
            "id": m.id,
            "sender_type": m.sender_type,
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "read_at": m.read_at.isoformat() if m.read_at else None,
        }
        for m in msgs
    ]
    now_ts = _time.time()
    admin_typing = False
    if thread and not locked and not ended:
        t = _admin_typing_by_thread.get(thread.id)
        if t is not None and (now_ts - t) < ADMIN_TYPING_TTL_SEC:
            admin_typing = True
    return {
        "thread_id": thread.id,
        "locked": locked,
        "ended": ended,
        "rating": getattr(thread, "rating", None),
        "reopened_at": reopened_at.isoformat() if reopened_at else None,
        "messages": messages,
        "count": len(messages),
        "admin_typing": admin_typing,
    }


class ChatSendRequest(BaseModel):
    account_id: int
    message: str


@router.post("/auth/chat/send")
async def send_chat_message(
    req: ChatSendRequest,
    request: Request,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Send user message. Creates thread if needed. Rejects if locked or ended.
    Requires auth and ownership of the account."""
    if not req.message or len(req.message.strip()) < 1:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    if len(req.message.strip()) > MAX_CHAT_BODY:
        raise HTTPException(
            status_code=400, detail=f"Mesaj en fazla {MAX_CHAT_BODY} karakter olabilir"
        )
    get_account_or_403(current, req.account_id, db)
    account = db.query(Account).filter(Account.id == req.account_id).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    thread = _get_or_create_thread_for_user(db, user.id, req.account_id)
    if thread.ended_at:
        raise HTTPException(
            status_code=400,
            detail="Bu sohbet sonlandırıldı. Yeni mesaj gönderemezsiniz.",
        )
    if thread.locked_at:
        raise HTTPException(
            status_code=400, detail="Sohbet kilitlendi. Mesaj gönderemezsiniz."
        )
    m = ChatMessage(thread_id=thread.id, sender_type="user", body=req.message.strip())
    db.add(m)
    thread.updated_at = datetime.utcnow()
    db.commit()
    body_preview = (
        (req.message.strip()[:80] + "…")
        if len(req.message.strip()) > 80
        else req.message.strip()
    )
    audit_svc.log_event(
        db,
        actor_type="user",
        event_type="CHAT_USER_MESSAGE",
        severity="INFO",
        actor_user_id=user.id,
        target_user_id=user.id,
        target_account_id=req.account_id,
        ip=get_client_ip(request),
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"body_preview": body_preview},
    )
    return {
        "success": True,
        "message_id": m.id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


class ChatReadRequest(BaseModel):
    account_id: int
    message_ids: Optional[list[int]] = (
        None  # If None, mark all admin messages in thread as read
    )


@router.post("/auth/chat/read")
async def mark_chat_read(
    req: ChatReadRequest,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Mark admin messages as read. If message_ids omitted, mark all admin messages in thread.
    Requires auth and ownership of the account."""
    get_account_or_403(current, req.account_id, db)
    account = db.query(Account).filter(Account.id == req.account_id).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    thread = db.query(ChatThread).filter(ChatThread.user_id == user.id).first()
    if not thread:
        return {"success": True, "marked": 0}
    now = datetime.utcnow()
    if req.message_ids:
        q = db.query(ChatMessage).filter(
            ChatMessage.thread_id == thread.id,
            ChatMessage.sender_type == "admin",
            ChatMessage.id.in_(req.message_ids),
        )
    else:
        q = db.query(ChatMessage).filter(
            ChatMessage.thread_id == thread.id, ChatMessage.sender_type == "admin"
        )
    count = 0
    for m in q.all():
        if not m.read_at:
            m.read_at = now
            count += 1
    db.commit()
    return {"success": True, "marked": count}


class ChatEndRequest(BaseModel):
    account_id: int
    rating: Optional[int] = None  # 1-5 when user ends chat


@router.post("/auth/chat/end")
async def end_chat(
    req: ChatEndRequest,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """User ends the chat (and optionally submits 1-5 star rating). Sets thread.ended_at."""
    get_account_or_403(current, req.account_id, db)
    account = db.query(Account).filter(Account.id == req.account_id).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    thread = db.query(ChatThread).filter(ChatThread.user_id == user.id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    if thread.ended_at:
        return {"success": True, "message": "Sohbet zaten sonlandırılmış"}
    # Sadece sonlandır; mesajları veya thread'i silme. Admin sohbeti "Sohbeti komple temizle" diyene kadar kalıcıdır.
    thread.ended_at = datetime.utcnow()
    if req.rating is not None and 1 <= req.rating <= 5:
        thread.rating = req.rating
        try:
            db.add(ChatRating(thread_id=thread.id, rating=req.rating))
        except Exception:
            pass
    thread.updated_at = datetime.utcnow()
    db.commit()
    return {
        "success": True,
        "message": "Sohbet sonlandırıldı",
        "rating": getattr(thread, "rating", None),
    }


class ChatReopenRequest(BaseModel):
    account_id: int


def _reopen_chat_impl(req: ChatReopenRequest, current: dict, db: Session):
    """Shared impl for reopen endpoints. Caller must have verified auth and ownership."""
    get_account_or_403(current, req.account_id, db)
    account = db.query(Account).filter(Account.id == req.account_id).first()
    if not account or not account.user_id:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user = db.query(User).filter(User.id == account.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    thread = db.query(ChatThread).filter(ChatThread.user_id == user.id).first()
    if not thread:
        return {"success": True, "message": "Sohbet hazır"}
    now = datetime.utcnow()
    thread.ended_at = None
    thread.locked_at = None
    thread.reopened_at = now
    thread.updated_at = now
    if hasattr(thread, "rating"):
        thread.rating = None
    db.commit()
    # Her yeni sohbet başlatıldığında tek bir admin oto mesajı (çift tıklama / tekrarlı istekte tekrar ekleme)
    recent = datetime.utcnow() - timedelta(seconds=10)
    existing = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.thread_id == thread.id,
            ChatMessage.sender_type == "admin",
            ChatMessage.body == WELCOME_CHAT_BODY,
            ChatMessage.created_at >= recent,
        )
        .limit(1)
        .first()
    )
    if not existing:
        welcome = ChatMessage(
            thread_id=thread.id, sender_type="admin", body=WELCOME_CHAT_BODY
        )
        db.add(welcome)
        db.commit()
    return {"success": True, "message": "Sohbet yeniden açıldı"}


@router.post("/auth/chat/reopen")
async def reopen_chat(
    req: ChatReopenRequest,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Reopen thread after admin ended it. User can request 'Yeni sohbet başlat'."""
    return _reopen_chat_impl(req, current, db)


@router.post("/auth/chat-reopen")
async def reopen_chat_alt(
    req: ChatReopenRequest,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Alternative path for chat reopen (avoids 404 with nested /auth/chat/reopen in some setups)."""
    return _reopen_chat_impl(req, current, db)


# ----- Audit events (user-facing: kendi hesabının işlem geçmişi) -----
VALID_AUDIT_RANGES = {"day": 1, "month": 30, "3m": 90, "6m": 180, "year": 365}


def _audit_created_at_iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO string for audit created_at. Naive UTC datetimes get 'Z' so frontend parses as UTC and shows Turkey time."""
    if not dt:
        return None
    s = dt.isoformat()
    if dt.tzinfo is None:
        s = s + "Z"
    return s


@router.get("/audit/events")
async def list_audit_events(
    account_id: int = Query(..., description="Account ID"),
    range_key: str = Query("month", alias="range", description="day|month|3m|6m|year"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """User: kendi hesabının audit kayıtları. Admin işlemlerinde IP asla dönmez (sadece kullanıcı görmesin)."""
    get_account_or_403(current, account_id, db)
    days = VALID_AUDIT_RANGES.get(range_key.lower() if range_key else "")
    if not days:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_RANGE",
                "message": "Geçersiz range. day, month, 3m, 6m, year kullanın.",
                "ok": False,
            },
        )
    cutoff = datetime.utcnow() - timedelta(days=days)
    # Test hesabında sadece son 24 saat gösterilsin (eski migrasyon/admin kayıtları karışmasın)
    from app.services.test_account import is_test_account

    if is_test_account(account_id, db):
        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        if cutoff < cutoff_24h:
            cutoff = cutoff_24h
    q = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.target_account_id == account_id,
            AuditEvent.created_at >= cutoff,
        )
        .order_by(AuditEvent.created_at.desc())
    )
    total = q.count()
    events = q.offset(offset).limit(limit).all()
    out = []
    for e in events:
        # Kullanıcı kendi işlem geçmişinde admin IP asla görmesin (sadece kullanıcı göremesin)
        if e.actor_type == "admin":
            ip_out = None
        else:
            ip_out = None if e.ip_masked else (e.ip or None)
        out.append(
            {
                "id": e.id,
                "created_at": _audit_created_at_iso(e.created_at),
                "event_type": e.event_type,
                "severity": e.severity,
                "actor_type": e.actor_type,
                "actor_label": "Admin"
                if e.actor_type == "admin"
                else ("Sistem" if e.actor_type == "system" else "Siz"),
                "ip": ip_out,
                "device_id": (e.device_id[:12] + "…")
                if e.device_id and len(e.device_id) > 12
                else (e.device_id or None),
                "meta": _parse_meta(e.meta_json),
                "request_id": e.request_id,
                "detail": _audit_event_detail(e),
            }
        )
    return {"ok": True, "events": out, "total": total}


def _parse_meta(meta_json: Optional[str]):
    """Parse meta_json safely; return dict or None."""
    if not meta_json:
        return None
    try:
        return json.loads(meta_json)
    except Exception:
        return None


def _audit_event_detail(e: AuditEvent) -> str:
    """İnsan okunabilir kısa açıklama: event_type + meta."""
    meta = _parse_meta(e.meta_json)
    if e.event_type == "SPOT_ORDER_CREATE" and meta:
        parts = [meta.get("side", ""), meta.get("symbol", "")]
        if meta.get("quantity") is not None:
            parts.append(f"{meta['quantity']} adet")
        if meta.get("price") is not None:
            parts.append(f"fiyat {meta['price']}")
        if meta.get("executed_value_usdt") is not None:
            parts.append(f"~{float(meta['executed_value_usdt']):.2f} USDT")
        return " · ".join(str(p) for p in parts if p) or "—"
    if e.event_type == "BOT_TRADE" and meta:
        side_tr = (
            "Alım"
            if (meta.get("side") or "").upper() in ("BUY", "DOWN_BUY")
            else "Satım"
        )
        return f"{side_tr} {meta.get('symbol', '')} {meta.get('qty')} @ {meta.get('price')} (neden: {meta.get('reason', '')})"
    if e.event_type == "BOT_CREATE" and meta:
        cfg = meta.get("config_summary") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        budget = (
            cfg.get("budget_usdt")
            or cfg.get("budget_usd")
            or cfg.get("initial_capital_usdt")
            or cfg.get("bot_budget_usdt")
            or cfg.get("bot_budget_quote")
            or meta.get("budget_usdt")
            or meta.get("budget_usd")
        )
        try:
            budget_val = float(budget) if budget is not None else None
        except (TypeError, ValueError):
            budget_val = None
        mode_raw = (meta.get("mode") or "").strip().lower()
        # Botlar her zaman canlı modda; eski "paper" kayıtları da canlı gösterilir
        mode_label = "canlı" if mode_raw in ("live", "paper", "") else (mode_raw or "—")
        symbol = meta.get("symbol", "")
        bot_id = meta.get("bot_id", "")
        if budget_val is not None and budget_val >= 0:
            return (
                f"Bot #{bot_id} {symbol} · {mode_label} · bütçe {budget_val:.2f} USDT"
            )
        return f"Bot #{bot_id} {symbol} · {mode_label}"
    if e.event_type == "BOT_DELETE" and meta:
        return f"Bot #{meta.get('bot_id')} {meta.get('symbol', '')} silindi"
    if e.event_type == "BOT_START" and meta:
        sym = meta.get("symbol", "")
        return (
            f"Bot #{meta.get('bot_id')} {sym} başlatıldı"
            if sym
            else f"Bot #{meta.get('bot_id')} başlatıldı"
        )
    if e.event_type == "BOT_STOP" and meta:
        sym = meta.get("symbol", "")
        return (
            f"Bot #{meta.get('bot_id')} {sym} durduruldu"
            if sym
            else f"Bot #{meta.get('bot_id')} durduruldu"
        )
    if e.event_type in ("CHAT_USER_MESSAGE", "CHAT_ADMIN_MESSAGE") and meta:
        return (meta.get("body_preview") or "—")[:120]
    if e.event_type == "PASSWORD_CHANGE":
        return "Şifre değiştirildi"
    if e.event_type in ("PHONE_UPDATE", "ADMIN_USER_PHONE_UPDATE") and meta:
        return "Telefon güncellendi"
    if meta:
        if meta.get("order_id"):
            return f"Emir #{meta['order_id']}"
        if meta.get("field"):
            return f"Alan: {meta['field']}"
        if meta.get("account_name"):
            return f"Hesap: {meta['account_name']}"
    return "—"


def _admin_audit_events_query(
    db: Session,
    cutoff: datetime,
    admin_only: bool,
    own_only: bool,
    actor_user_id: Optional[int],
    target_user_id: Optional[int] = None,
    target_account_ids: Optional[List[int]] = None,
):
    """Ortak audit sorgusu: admin paneli ve kullanıcı işlem geçmişi için."""
    q = (
        db.query(AuditEvent)
        .filter(AuditEvent.created_at >= cutoff)
        .order_by(AuditEvent.created_at.desc())
    )
    if admin_only:
        q = q.filter(AuditEvent.actor_type == "admin")
    if own_only and actor_user_id is not None:
        q = q.filter(AuditEvent.actor_user_id == actor_user_id)
    if target_user_id is not None:
        q = q.filter(AuditEvent.target_user_id == target_user_id)
    if target_account_ids is not None:
        q = q.filter(AuditEvent.target_account_id.in_(target_account_ids))
    return q


@router.get("/admin/audit/events")
async def list_admin_audit_events(
    range_key: str = Query("month", alias="range", description="day|month|3m|6m|year"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin_only: bool = Query(False, description="Sadece admin işlemleri"),
    own_only: bool = Query(False, description="Sadece benim yaptığım işlemler"),
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Admin: tüm işlem geçmişi veya filtrelenmiş. IP tam gösterilir."""
    days = VALID_AUDIT_RANGES.get(range_key.lower() if range_key else "")
    if not days:
        raise HTTPException(
            status_code=400, detail="Geçersiz range. day, month, 3m, 6m, year kullanın."
        )
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = _admin_audit_events_query(
        db, cutoff, admin_only, own_only, current.get("user_id"), None, None
    )
    total = q.count()
    events = q.offset(offset).limit(limit).all()
    out = []
    for e in events:
        actor_label = (
            "Admin"
            if e.actor_type == "admin"
            else ("Sistem" if e.actor_type == "system" else "Kullanıcı")
        )
        if e.actor_user_id and e.actor_type == "user":
            u = db.query(User).filter(User.id == e.actor_user_id).first()
            actor_label = (
                f"{u.name or ''} {u.surname or ''}".strip()
                or f"Kullanıcı #{e.actor_user_id}"
                if u
                else actor_label
            )
        target_user_label = None
        if e.target_user_id:
            tu = db.query(User).filter(User.id == e.target_user_id).first()
            target_user_label = (
                f"{tu.name or ''} {tu.surname or ''}".strip() or None if tu else None
            )
        elif e.target_account_id:
            acc = db.query(Account).filter(Account.id == e.target_account_id).first()
            if acc and acc.user_id:
                tu = db.query(User).filter(User.id == acc.user_id).first()
                target_user_label = (
                    f"{tu.name or ''} {tu.surname or ''}".strip()
                    or (acc.name or acc.account_code)
                    if tu
                    else (acc.name or acc.account_code)
                )
            elif acc:
                target_user_label = acc.name or acc.account_code
        out.append(
            {
                "id": e.id,
                "created_at": _audit_created_at_iso(e.created_at),
                "event_type": e.event_type,
                "severity": e.severity,
                "actor_type": e.actor_type,
                "actor_user_id": e.actor_user_id,
                "actor_label": actor_label,
                "target_user_id": e.target_user_id,
                "target_account_id": e.target_account_id,
                "target_user_label": target_user_label,
                "ip": e.ip,
                "ip_masked": False,
                "device_id": e.device_id,
                "meta": _parse_meta(e.meta_json),
                "request_id": e.request_id,
                "admin_reason": e.admin_reason,
                "detail": _audit_event_detail(e),
            }
        )
    return {"ok": True, "events": out, "total": total}


@router.get("/admin/users/{user_id}/audit")
async def list_admin_user_audit(
    user_id: int,
    range_key: str = Query("month", alias="range", description="day|month|3m|6m|year"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Admin: belirli kullanıcının işlem geçmişi. IP tam gösterilir."""
    from sqlalchemy import or_

    days = VALID_AUDIT_RANGES.get(range_key.lower() if range_key else "")
    if not days:
        raise HTTPException(status_code=400, detail="Geçersiz range.")
    cutoff = datetime.utcnow() - timedelta(days=days)
    account_ids = [
        a.id for a in db.query(Account).filter(Account.user_id == user_id).all()
    ]
    if account_ids:
        q = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.created_at >= cutoff,
                or_(
                    AuditEvent.target_user_id == user_id,
                    AuditEvent.target_account_id.in_(account_ids),
                ),
            )
            .order_by(AuditEvent.created_at.desc())
        )
    else:
        q = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.created_at >= cutoff,
                AuditEvent.target_user_id == user_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
    total = q.count()
    events = q.offset(offset).limit(limit).all()
    out = []
    for e in events:
        actor_label = (
            "Admin"
            if e.actor_type == "admin"
            else ("Sistem" if e.actor_type == "system" else "Kullanıcı")
        )
        if e.actor_user_id and e.actor_type == "user":
            u = db.query(User).filter(User.id == e.actor_user_id).first()
            actor_label = (
                f"{u.name or ''} {u.surname or ''}".strip()
                or f"Kullanıcı #{e.actor_user_id}"
                if u
                else actor_label
            )
        target_user_label = None
        if e.target_user_id:
            tu = db.query(User).filter(User.id == e.target_user_id).first()
            target_user_label = (
                f"{tu.name or ''} {tu.surname or ''}".strip() or None if tu else None
            )
        elif e.target_account_id:
            acc = db.query(Account).filter(Account.id == e.target_account_id).first()
            if acc and acc.user_id:
                tu = db.query(User).filter(User.id == acc.user_id).first()
                target_user_label = (
                    f"{tu.name or ''} {tu.surname or ''}".strip()
                    or (acc.name or acc.account_code)
                    if tu
                    else (acc.name or acc.account_code)
                )
            elif acc:
                target_user_label = acc.name or acc.account_code
        out.append(
            {
                "id": e.id,
                "created_at": _audit_created_at_iso(e.created_at),
                "event_type": e.event_type,
                "severity": e.severity,
                "actor_type": e.actor_type,
                "actor_user_id": e.actor_user_id,
                "actor_label": actor_label,
                "target_user_id": e.target_user_id,
                "target_account_id": e.target_account_id,
                "target_user_label": target_user_label,
                "ip": e.ip,
                "ip_masked": False,
                "device_id": e.device_id,
                "meta": _parse_meta(e.meta_json),
                "request_id": e.request_id,
                "admin_reason": e.admin_reason,
                "detail": _audit_event_detail(e),
            }
        )
    return {"ok": True, "events": out, "total": total}


def _thread_avg_rating(
    db: Session, thread_id: int, fallback_last: Optional[int]
) -> Optional[float]:
    """O kullanıcının (thread) tüm sohbetlerinde verdiği yıldızların ortalaması."""
    try:
        rows = (
            db.query(ChatRating.rating).filter(ChatRating.thread_id == thread_id).all()
        )
        if rows:
            vals = [r[0] for r in rows if r[0] is not None]
            if vals:
                return round(sum(vals) / len(vals), 1)
        return float(fallback_last) if fallback_last is not None else None
    except Exception:
        return float(fallback_last) if fallback_last is not None else None


@router.get("/admin/chats")
async def list_admin_chats(
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """List all users with accounts; each has at most one thread. For İletişim tab.
    avg_rating = kullanıcının tüm sohbetlerinde verdiği yıldızların ortalaması.
    online = sadece kullanıcı (is_admin=0) oturumu ve son 2 dakikada last_seen_at güncellenmiş; admin girişleri sayılmaz."""
    from sqlalchemy import text

    now = datetime.utcnow()
    now_iso = now.isoformat()
    cutoff_iso = (now - timedelta(minutes=2)).isoformat()
    online_user_ids = set()
    try:
        rows = db.execute(
            text(
                "SELECT DISTINCT user_id FROM auth_sessions "
                "WHERE is_admin = 0 AND COALESCE(revoked, 0) = 0 AND expires_at > :now "
                "AND last_seen_at IS NOT NULL AND last_seen_at > :cutoff"
            ),
            {"now": now_iso, "cutoff": cutoff_iso},
        ).fetchall()
        online_user_ids = {r[0] for r in rows}
    except Exception:
        pass
    accounts = (
        db.query(Account)
        .join(User, Account.user_id == User.id)
        .filter(or_(User.is_deleted == False, User.is_deleted.is_(None)))
        .all()
    )
    out = []
    for acc in accounts:
        u = db.query(User).filter(User.id == acc.user_id).first()
        if not u:
            continue
        thread = db.query(ChatThread).filter(ChatThread.user_id == u.id).first()
        last_at = None
        unread = 0
        last_rating = getattr(thread, "rating", None) if thread else None
        avg_rating = _thread_avg_rating(db, thread.id, last_rating) if thread else None
        if thread:
            last = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread.id)
                .order_by(ChatMessage.created_at.desc())
                .first()
            )
            if last:
                last_at = last.created_at.isoformat() if last.created_at else None
            unread = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.thread_id == thread.id,
                    ChatMessage.sender_type == "user",
                    ChatMessage.read_at.is_(None),
                )
                .count()
            )
        out.append(
            {
                "user_id": u.id,
                "name": u.name or "",
                "surname": u.surname or "",
                "phone": u.phone or "",
                "account_id": acc.id,
                "account_code": acc.account_code or "",
                "thread_id": thread.id if thread else None,
                "locked": thread.locked_at is not None if thread else False,
                "ended": thread.ended_at is not None if thread else False,
                "rating": last_rating,
                "avg_rating": avg_rating,
                "last_message_at": last_at,
                "unread_count": unread,
                "online": u.id in online_user_ids,
            }
        )
    out.sort(
        key=lambda x: x.get("last_message_at") or "", reverse=True
    )  # newest first, no thread last
    return {"chats": out}


@router.get("/admin/chats/{user_id}/messages")
async def get_admin_chat_messages(
    user_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Get messages for user's thread. Thread created on first admin send if missing."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    db.query(Account).filter(Account.user_id == user_id).first()
    thread = db.query(ChatThread).filter(ChatThread.user_id == user_id).first()
    if not thread:
        return {
            "thread_id": None,
            "locked": False,
            "ended": False,
            "rating": None,
            "messages": [],
            "count": 0,
        }
    locked = thread.locked_at is not None
    ended = thread.ended_at is not None
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.thread_id == thread.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    messages = [
        {
            "id": m.id,
            "sender_type": m.sender_type,
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "read_at": m.read_at.isoformat() if m.read_at else None,
        }
        for m in msgs
    ]
    # Mark user messages as read when admin fetches
    now = datetime.utcnow()
    for m in msgs:
        if m.sender_type == "user" and not m.read_at:
            m.read_at = now
    db.commit()
    return {
        "thread_id": thread.id,
        "locked": locked,
        "ended": ended,
        "rating": getattr(thread, "rating", None),
        "messages": messages,
        "count": len(messages),
    }


class AdminChatSendRequest(BaseModel):
    user_id: int
    message: str


class AdminChatTypingRequest(BaseModel):
    user_id: int


@router.post("/admin/chats/typing")
async def admin_chat_typing(
    req: AdminChatTypingRequest,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Admin yazıyor göstergesi: bu thread için son typing zamanını günceller. Kullanıcı GET /auth/chat ile admin_typing alır."""
    thread = db.query(ChatThread).filter(ChatThread.user_id == req.user_id).first()
    if thread:
        _admin_typing_by_thread[thread.id] = _time.time()
    return {"ok": True}


@router.post("/admin/chats/send")
async def admin_send_chat(
    req: AdminChatSendRequest,
    request: Request,
    current: dict = Depends(require_admin_auth),
    db: Session = Depends(get_db),
):
    """Admin send message to user. Creates thread if not exists."""
    if not req.message or len(req.message.strip()) < 1:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    if len(req.message.strip()) > MAX_CHAT_BODY:
        raise HTTPException(
            status_code=400, detail=f"Mesaj en fazla {MAX_CHAT_BODY} karakter olabilir"
        )
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    acc = db.query(Account).filter(Account.user_id == req.user_id).first()
    thread = _get_or_create_thread_for_user(db, req.user_id, acc.id if acc else None)
    if thread.ended_at:
        raise HTTPException(
            status_code=400, detail="Sohbet sonlandırıldı. Yeni mesaj gönderemezsiniz."
        )
    m = ChatMessage(thread_id=thread.id, sender_type="admin", body=req.message.strip())
    db.add(m)
    thread.updated_at = datetime.utcnow()
    db.commit()
    _admin_typing_by_thread.pop(thread.id, None)
    body_preview = (
        (req.message.strip()[:80] + "…")
        if len(req.message.strip()) > 80
        else req.message.strip()
    )
    audit_svc.log_event(
        db,
        actor_type="admin",
        event_type="CHAT_ADMIN_MESSAGE",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=req.user_id,
        target_account_id=acc.id if acc else None,
        ip=get_client_ip(request),
        ip_masked=True,
        device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"body_preview": body_preview},
    )
    return {
        "success": True,
        "message_id": m.id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/admin/chats/{thread_id}/lock")
async def admin_chat_lock(
    thread_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    t.locked_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Sohbet kilitlendi"}


@router.post("/admin/chats/{thread_id}/unlock")
async def admin_chat_unlock(
    thread_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    t.locked_at = None
    db.commit()
    return {"success": True, "message": "Sohbet kilidi açıldı"}


@router.post("/admin/chats/{thread_id}/end")
async def admin_chat_end(
    thread_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    t.ended_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Sohbet sonlandırıldı"}


@router.post("/admin/chats/{thread_id}/reopen")
async def admin_chat_reopen(
    thread_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Admin sohbeti yeniden açar (kullanıcı tekrar mesaj atabilir). Her reopen'da admin oto mesaj atılır."""
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    now = datetime.utcnow()
    t.ended_at = None
    t.locked_at = None
    t.reopened_at = now
    t.updated_at = now
    if hasattr(t, "rating"):
        t.rating = None
    db.commit()
    recent = datetime.utcnow() - timedelta(seconds=10)
    existing = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.thread_id == t.id,
            ChatMessage.sender_type == "admin",
            ChatMessage.body == WELCOME_CHAT_BODY,
            ChatMessage.created_at >= recent,
        )
        .limit(1)
        .first()
    )
    if not existing:
        welcome = ChatMessage(
            thread_id=t.id, sender_type="admin", body=WELCOME_CHAT_BODY
        )
        db.add(welcome)
        db.commit()
    return {"success": True, "message": "Sohbet tekrar açıldı"}


@router.post("/admin/chats/{thread_id}/clear")
async def admin_chat_clear(
    thread_id: int,
    db: Session = Depends(get_db),
    current: dict = Depends(require_admin_auth),
):
    """Sohbeti komple temizler: tüm mesajlar silinir, thread yeniden kullanılabilir.
    Admin panelindeki sohbet YALNIZCA bu endpoint ile temizlenir; kullanıcı sohbeti sonlandırsa bile
    mesajlar kalıcıdır, admin 'Sohbeti komple temizle' demedikçe silinmez."""
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    db.query(ChatMessage).filter(ChatMessage.thread_id == thread_id).delete()
    try:
        db.query(ChatRating).filter(ChatRating.thread_id == thread_id).delete()
    except Exception:
        pass
    t.locked_at = None
    t.ended_at = None
    if hasattr(t, "rating"):
        t.rating = None
    if hasattr(t, "reopened_at"):
        t.reopened_at = None
    db.commit()
    return {"success": True, "message": "Sohbet temizlendi"}
