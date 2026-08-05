"""
Kullanıcı işlem geçmişi — sade Türkçe, dosya tabanlı log servisi.

Proje kökünde ``Kullanıcı Logları/`` klasörüne kullanıcı başına dosya yazar.
Teknik hata dökümü burada tutulmaz; yazma hataları ``Sistem Logları/`` altına gider.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, List, Optional, Tuple

from app.services.user_activity_translations import (
    AUDIT_EVENT_MAP,
    format_event,
    translate_technical_reason,
)
from app.utils.tz_utils import TR_TZ

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_LOG_DIR_NAME = "Kullanıcı Logları"
SYSTEM_LOG_DIR_NAME = "Sistem Logları"
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
MAX_NAME_PART_LEN = 40
_LOG_LINE_SEP = " — "

_FORBIDDEN_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FORBIDDEN_LOG_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"traceback",
        r"stack\s*trace",
        r"TypeError",
        r"ValueError",
        r"KeyError",
        r"AttributeError",
        r"undefined",
        r"null\s*pointer",
        r"Exception:",
        r"\.py:\d+",
        r"SELECT\s+.+\s+FROM",
        r"INSERT\s+INTO",
        r"\{[\s\S]*\"[\w]+\"[\s\S]*\}",  # raw JSON object
    )
]
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "api_secret",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "private_key",
        "session_secret",
        "secret",
        "authorization",
    }
)
_API_KEY_PATTERN = re.compile(r"\b([a-zA-Z0-9]{4})[a-zA-Z0-9]{8,}([a-zA-Z0-9]{4})\b")
_IP_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

_file_locks_guard = threading.Lock()
_file_locks: Dict[str, threading.Lock] = {}
_write_queue: Queue = Queue(maxsize=5000)
_worker_started = False
_worker_lock = threading.Lock()
_custom_root: Optional[Path] = None


@dataclass
class _WriteJob:
    user_id: int
    user_name: Optional[str]
    user_surname: Optional[str]
    screen: str
    action: str
    result: str


def _project_root() -> Path:
    return _custom_root or _PROJECT_ROOT


def set_log_root_for_tests(root: Path) -> None:
    """Testler için kök dizin override."""
    global _custom_root
    _custom_root = root


def reset_log_root_for_tests() -> None:
    global _custom_root
    _custom_root = None


def user_log_dir() -> Path:
    return _project_root() / USER_LOG_DIR_NAME


def system_log_dir() -> Path:
    return _project_root() / SYSTEM_LOG_DIR_NAME


def _ensure_dirs() -> None:
    for directory in (user_log_dir(), system_log_dir()):
        directory.mkdir(parents=True, exist_ok=True)
        # Production deploy historically left these as root:app 2750 (no group write).
        # When the process owns the directory, keep group-writable sticky bits.
        try:
            mode = directory.stat().st_mode & 0o7777
            if mode & 0o020 == 0:
                directory.chmod((mode | 0o2770) & 0o2777)
        except OSError:
            pass


def _get_file_lock(path: str) -> threading.Lock:
    with _file_locks_guard:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def sanitize_filename_part(value: str, max_len: int = MAX_NAME_PART_LEN) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    s = s.replace(" ", ".")
    s = _FORBIDDEN_FILENAME_CHARS.sub("", s)
    s = re.sub(r"\.{2,}", ".", s).strip(".")
    if len(s) > max_len:
        s = s[:max_len].rstrip(".")
    return s


def build_log_filename(
    user_id: int,
    name: Optional[str] = None,
    surname: Optional[str] = None,
) -> str:
    n = sanitize_filename_part(name or "")
    sn = sanitize_filename_part(surname or "")
    if n and sn:
        return f"{n}.{sn}__{user_id}.log"
    return f"user_{user_id}.log"


def _generic_log_path(user_id: int) -> Path:
    return user_log_dir() / f"user_{user_id}.log"


def _find_named_log_paths(user_id: int) -> List[Path]:
    base = user_log_dir()
    if not base.exists():
        return []
    return sorted(base.glob(f"*__{user_id}.log"))


_HEADER_PREFIXES = (
    "Kullanıcı İşlem Geçmişi",
    "Kullanıcı:",
    "Kullanıcı ID:",
    "Log Başlangıç",
    "Saat Dilimi:",
)


def _is_header_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return any(s.startswith(p) for p in _HEADER_PREFIXES)


def _read_body_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [
                ln.rstrip("\n")
                for ln in f
                if ln.strip() and not _is_header_line(ln.rstrip("\n"))
            ]
    except OSError:
        return []


def _merge_log_file_into(target: Path, source: Path) -> None:
    """Append *source* body lines into *target*, then remove *source*."""
    if not source.exists() or source.resolve() == target.resolve():
        return
    extra = _read_body_lines(source)
    if not extra:
        try:
            source.unlink()
        except OSError:
            pass
        return
    lock = _get_file_lock(str(target))
    with lock:
        existing = set(_read_body_lines(target))
        with open(target, "a", encoding="utf-8") as f:
            for line in extra:
                if line not in existing:
                    f.write(line + "\n")
                    existing.add(line)
    try:
        source.unlink()
    except OSError:
        pass


def _rename_log_file(src: Path, dst: Path) -> Path:
    if not src.exists() or src.resolve() == dst.resolve():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        _merge_log_file_into(dst, src)
        return dst
    try:
        src.rename(dst)
    except OSError:
        _merge_log_file_into(dst, src)
    return dst


def resolve_log_path(
    user_id: int,
    name: Optional[str] = None,
    surname: Optional[str] = None,
) -> Path:
    """Tek kullanıcı → tek dosya; generic ve adlı dosyalar birleştirilir."""
    _ensure_dirs()
    uid = int(user_id)
    generic = _generic_log_path(uid)
    preferred_name = build_log_filename(uid, name, surname)
    preferred = user_log_dir() / preferred_name
    named_existing = _find_named_log_paths(uid)

    # Ad/soyadlı hedef dosya varsa onu kullan; generic varsa içine birleştir.
    if preferred_name != f"user_{uid}.log":
        if preferred.exists():
            if generic.exists():
                _merge_log_file_into(preferred, generic)
            return preferred
        for p in named_existing:
            if p.name == preferred_name:
                if generic.exists():
                    _merge_log_file_into(p, generic)
                return p
        if named_existing:
            canonical = named_existing[0]
            if generic.exists():
                _merge_log_file_into(canonical, generic)
            return canonical
        if generic.exists():
            return _rename_log_file(generic, preferred)
        return preferred

    # Ad/soyad yok — mevcut adlı dosyaya yaz (generic açılmasın).
    if named_existing:
        canonical = named_existing[0]
        if generic.exists():
            _merge_log_file_into(canonical, generic)
        return canonical
    return generic


def _format_timestamp(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(TR_TZ)
    if d.tzinfo is None:
        d = d.replace(tzinfo=TR_TZ)
    else:
        d = d.astimezone(TR_TZ)
    return d.strftime("%d.%m.%Y %H:%M:%S")


def sanitize_text(text: str) -> str:
    """Teknik/hassas içeriği kullanıcı logundan temizler."""
    if not text:
        return ""
    s = str(text)
    for pat in _FORBIDDEN_LOG_PATTERNS:
        if pat.search(s):
            return "İşlem kaydı oluşturuldu"
    lower = s.lower()
    for key in _SENSITIVE_KEYS:
        if key in lower:
            return re.sub(
                rf"{re.escape(key)}[\s:=]+[\S]+",
                f"{key}=***",
                s,
                flags=re.IGNORECASE,
            )
    s = _API_KEY_PATTERN.sub(r"\1****\2", s)
    s = _IP_PATTERN.sub("[IP]", s)
    return s.strip()


def format_log_line(
    screen: str,
    action: str,
    result: str,
    *,
    ts: Optional[datetime] = None,
) -> str:
    action = sanitize_text(action)
    result = sanitize_text(result)
    screen = sanitize_text(screen) or "Sistem"
    return f"{_format_timestamp(ts)}{_LOG_LINE_SEP}{screen}{_LOG_LINE_SEP}{action}{_LOG_LINE_SEP}{result}"


def _maybe_rotate(path: Path) -> Path:
    if not path.exists():
        return path
    try:
        if path.stat().st_size < MAX_LOG_FILE_BYTES:
            return path
    except OSError:
        return path
    stem = path.stem
    suffix = path.suffix
    month = datetime.now(TR_TZ).strftime("%Y-%m")
    rotated = path.with_name(f"{stem}_{month}{suffix}")
    if rotated.exists():
        idx = 1
        while True:
            candidate = path.with_name(f"{stem}_{month}_{idx}{suffix}")
            if not candidate.exists():
                rotated = candidate
                break
            idx += 1
    try:
        path.rename(rotated)
    except OSError:
        pass
    return path


def _write_header_if_new(path: Path, user_id: int, name: str, surname: str) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    display = f"{name} {surname}".strip() or f"Kullanıcı {user_id}"
    start = datetime.now(TR_TZ).strftime("%d.%m.%Y")
    header = (
        "Kullanıcı İşlem Geçmişi\n"
        f"Kullanıcı: {display}\n"
        f"Kullanıcı ID: {user_id}\n"
        f"Log Başlangıç Tarihi: {start}\n"
        "Saat Dilimi: Türkiye Saati\n"
        "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(header)


def _append_line_to_file(job: _WriteJob) -> None:
    _ensure_dirs()
    path = resolve_log_path(job.user_id, job.user_name, job.user_surname)
    path = _maybe_rotate(path)
    line = format_log_line(job.screen, job.action, job.result) + "\n"
    lock = _get_file_lock(str(path))
    with lock:
        _write_header_if_new(
            path,
            job.user_id,
            job.user_name or "",
            job.user_surname or "",
        )
        # Append-only: avoids mkstemp in a directory that may lack write for the
        # service user (common after root-owned deploy of Kullanıcı Logları/).
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        try:
            if (path.stat().st_mode & 0o020) == 0:
                path.chmod(0o640)
        except OSError:
            pass


def _log_write_failure(message: str) -> None:
    try:
        _ensure_dirs()
        err_path = system_log_dir() / "developer_errors.log"
        ts = _format_timestamp()
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} — user_activity_logger — {message}\n")
    except Exception:
        logger.warning("user_activity_logger: could not write system error log: %s", message)


def _worker_loop() -> None:
    while True:
        try:
            job = _write_queue.get(timeout=1.0)
        except Empty:
            continue
        if job is None:
            break
        try:
            _append_line_to_file(job)
        except Exception as exc:
            _log_write_failure(f"kullanıcı logu yazılamadı user_id={job.user_id}: {exc}")
        finally:
            _write_queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, name="user-activity-logger", daemon=True)
        t.start()
        _worker_started = True


class UserReadableActivityLogger:
    """Merkezi sade kullanıcı işlem geçmişi servisi."""

    @classmethod
    def write(
        cls,
        user_id: int,
        *,
        user_name: Optional[str] = None,
        user_surname: Optional[str] = None,
        screen: str,
        action: str,
        result: str,
        details: Optional[str] = None,
    ) -> None:
        """Doğrudan sade satır yazar. Ana işlemi asla durdurmaz."""
        if not user_id:
            return
        try:
            action_text = action
            if details:
                action_text = f"{action} — {sanitize_text(details)}"
            job = _WriteJob(
                user_id=int(user_id),
                user_name=user_name,
                user_surname=user_surname,
                screen=screen,
                action=action_text,
                result=result,
            )
            _ensure_worker()
            try:
                _write_queue.put_nowait(job)
            except Exception:
                _append_line_to_file(job)
        except Exception as exc:
            _log_write_failure(f"write enqueue failed user_id={user_id}: {exc}")

    @classmethod
    def write_event(
        cls,
        user_id: int,
        event_type: str,
        *,
        user_name: Optional[str] = None,
        user_surname: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        screen: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
    ) -> None:
        ctx = dict(context or {})
        if ctx.get("technical_reason"):
            ctx["block_reason"] = ctx.get("technical_reason")
        scr, act, res = format_event(
            event_type,
            ctx,
            screen_override=screen,
            action_override=action,
            result_override=result,
        )
        if ctx.get("technical_reason") and not result:
            res = translate_technical_reason(str(ctx["technical_reason"]))
        cls.write(
            user_id,
            user_name=user_name,
            user_surname=user_surname,
            screen=scr,
            action=act,
            result=res,
        )

    @classmethod
    def write_from_audit(
        cls,
        event_type: str,
        *,
        actor_user_id: Optional[int] = None,
        target_user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        user_surname: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        mapped = AUDIT_EVENT_MAP.get(event_type)
        if not mapped:
            return
        uid = target_user_id or actor_user_id
        if not uid:
            return
        ctx = dict(meta or {})
        if ctx.get("symbol"):
            ctx.setdefault("symbol", ctx["symbol"])
        cls.write_event(
            int(uid),
            mapped,
            user_name=user_name,
            user_surname=user_surname,
            context=ctx,
        )

    @classmethod
    def write_sync(
        cls,
        user_id: int,
        *,
        user_name: Optional[str] = None,
        user_surname: Optional[str] = None,
        screen: str,
        action: str,
        result: str,
    ) -> None:
        """Testler için senkron yazım."""
        job = _WriteJob(
            user_id=int(user_id),
            user_name=user_name,
            user_surname=user_surname,
            screen=screen,
            action=action,
            result=result,
        )
        _append_line_to_file(job)


def read_user_log_lines(
    user_id: int,
    *,
    name: Optional[str] = None,
    surname: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    screen: Optional[str] = None,
    coin: Optional[str] = None,
    result_filter: Optional[str] = None,
    event_screen: Optional[str] = None,
    limit: int = 500,
) -> List[str]:
    """Admin panel için log satırlarını okur ve filtreler."""
    base = user_log_dir()
    if not base.exists():
        return []
    path = resolve_log_path(user_id, name, surname)
    paths = [path] if path.exists() else []
    if not paths:
        paths = _find_named_log_paths(user_id)
        generic = _generic_log_path(user_id)
        if generic.exists() and generic not in paths:
            paths.append(generic)
    lines: List[str] = []
    for path in sorted(paths):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.rstrip("\n")
                    if not line or line.startswith("Kullanıcı İşlem") or line.startswith("Kullanıcı:"):
                        continue
                    if line.startswith("Kullanıcı ID:") or line.startswith("Log Başlangıç") or line.startswith("Saat Dilimi:"):
                        continue
                    if " — " not in line:
                        continue
                    lines.append(line)
        except OSError:
            continue

    def _parse_ts(line: str) -> Optional[datetime]:
        try:
            part = line.split(_LOG_LINE_SEP, 1)[0]
            return datetime.strptime(part, "%d.%m.%Y %H:%M:%S").replace(tzinfo=TR_TZ)
        except (ValueError, IndexError):
            return None

    filtered: List[str] = []
    for line in lines:
        if screen and screen not in line:
            continue
        if event_screen and event_screen not in line:
            continue
        if coin and coin.upper() not in line.upper():
            continue
        if result_filter and result_filter not in line:
            continue
        if from_date or to_date:
            ts = _parse_ts(line)
            if ts:
                if from_date:
                    try:
                        fd = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=TR_TZ)
                        if ts.date() < fd.date():
                            continue
                    except ValueError:
                        pass
                if to_date:
                    try:
                        td = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=TR_TZ)
                        if ts.date() > td.date():
                            continue
                    except ValueError:
                        pass
        filtered.append(line)
    return filtered[-limit:]


def resolve_user_identity(
    db,
    user_id: Optional[int] = None,
    account_id: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """user_id veya account_id ile ad/soyad çöz."""
    try:
        from app.db.models import Account, User

        if user_id:
            u = db.query(User).filter(User.id == user_id).first()
            if u:
                return u.id, u.name, u.surname
        if account_id:
            acc = db.query(Account).filter(Account.id == account_id).first()
            if acc and acc.user_id:
                u = db.query(User).filter(User.id == acc.user_id).first()
                if u:
                    return u.id, u.name, u.surname
    except Exception:
        pass
    return user_id, None, None


def log_for_account(
    db,
    account_id: int,
    event_type: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    screen: Optional[str] = None,
    action: Optional[str] = None,
    result: Optional[str] = None,
) -> None:
    """Worker/bot tarafı: account_id → kullanıcı logu."""
    uid, name, surname = resolve_user_identity(db, account_id=account_id)
    if not uid:
        return
    UserReadableActivityLogger.write_event(
        uid,
        event_type,
        user_name=name,
        user_surname=surname,
        context=context,
        screen=screen,
        action=action,
        result=result,
    )
