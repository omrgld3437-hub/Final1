"""
FILE: hata_log.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Kök klasördeki HATALAR.log — son 90 günün tüm hataları, tekrar bastırmalı.

Amaç: kullanıcının ve AI sorgularının tek dosyadan tüm hataları görebilmesi.

Tasarım kararları:

- **Tek dosya, kök klasör.** Rotasyonlu 90 ayrı dosya yerine tek `HATALAR.log`;
  kullanıcı çift tıklayıp okuyabilsin, AI tek dosyayı okuyabilsin.
- **90 gün saklama.** Dosya periyodik olarak budanır; 90 günden eski satırlar
  atılır. Ayrıca sert bir boyut tavanı vardır (beklenmeyen bir patlamada disk
  dolmasın).
- **Tekrar bastırma (dedupe).** Aynı hata parmak izi pencere içinde bir kez
  yazılır. Pencere kapanınca, o aralıkta kaç kez tekrarlandığı tek satırda
  bildirilir. Böylece saniyede yüzlerce tekrarlayan bir hata ne dosyayı şişirir
  ne de disk I/O ile sunucuyu yorar; yine de hiçbir hata görünmez kalmaz.
- **Asla patlamaz.** Log yazımı uygulamanın çalışmasını engellemez; her hata
  yutulur.

Çok process (api + worker) aynı dosyaya yazar. Her kayıt tek bir `O_APPEND`
write çağrısıyla ve satır uzunluğu sınırlı biçimde yazılır; POSIX'te bu boyutta
append'ler atomiktir, satırlar birbirine karışmaz.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HATA_LOG_PATH = PROJECT_ROOT / "HATALAR.log"

RETENTION_DAYS = int(os.getenv("HATA_LOG_RETENTION_DAYS", "90"))
# Aynı hata bu pencere içinde tekrar yazılmaz; pencere kapanınca tekrar sayısı bildirilir.
DEDUPE_WINDOW_SEC = float(os.getenv("HATA_LOG_DEDUPE_WINDOW_SEC", "300"))
# Parmak izi tablosu bu boyutu geçerse en eskiler atılır (RAM koruması).
MAX_FINGERPRINTS = 2000
# Beklenmeyen bir patlamada diski doldurmasın diye sert tavan.
MAX_FILE_BYTES = int(os.getenv("HATA_LOG_MAX_BYTES", str(32 * 1024 * 1024)))
MAX_LINE_CHARS = 2000
# Budama her yazımda değil, bu aralıkta bir yapılır.
PRUNE_INTERVAL_SEC = 3600.0

_HEADER = (
    "# HATALAR.log — bu dosyada sadece HATALAR var (son {days} gün).\n"
    "# Biçim: <zaman TR> | <seviye> | <kaynak> | <mesaj> | <ek bilgi>\n"
    "# Aynı hata kısa aralıkta tekrarlarsa bir kez yazılır; tekrar sayısı\n"
    "# 'tekrar=N' olarak ayrı bir satırda bildirilir.\n"
    "# Bu dosya otomatik üretilir; elle düzenlemek gerekmez, silinirse yeniden oluşur.\n"
    "#" + "-" * 100 + "\n"
)

_lock = threading.Lock()
# fingerprint -> (pencerenin ilk yazım zamanı, bastırılan tekrar sayısı)
_seen: Dict[str, Tuple[float, int]] = {}
_last_prune_at = 0.0

# Parmak izinde oynak kısımlar sabitlenir; aksi halde her istek yeni bir hata sayılır.
_VOLATILE_PATTERNS = (
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hex>"),
    (re.compile(r"\b\d{6,}\b"), "<num>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"), "<ts>"),
)


def _normalize_for_fingerprint(text: str) -> str:
    out = text or ""
    for pattern, repl in _VOLATILE_PATTERNS:
        out = pattern.sub(repl, out)
    return out.strip()[:400]


def _fingerprint(level: str, source: str, message: str, path: Optional[str]) -> str:
    raw = "|".join(
        (
            (level or "").upper(),
            (source or "").lower(),
            (path or ""),
            _normalize_for_fingerprint(message),
        )
    )
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _now_tr_str() -> str:
    """Türkiye saati (Europe/Istanbul). zoneinfo yoksa UTC+3 sabiti."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=3)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )


def _one_line(value: Any, limit: int) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\r", " ").replace("\n", " \\n ")
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _ensure_header() -> None:
    if HATA_LOG_PATH.exists() and HATA_LOG_PATH.stat().st_size > 0:
        return
    HATA_LOG_PATH.write_text(_HEADER.format(days=RETENTION_DAYS), encoding="utf-8")


def _append(line: str) -> None:
    """Tek atomik append. Hata durumunda sessizce vazgeçilir."""
    try:
        _ensure_header()
        with open(HATA_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


_LINE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) ")


def prune(force: bool = False) -> None:
    """90 günden eski satırları ve tavanı aşan fazlalığı at.

    Saatte bir çalışır (veya force=True). Dosya küçükse ve eski satır yoksa
    hiçbir şey yazılmaz, yani maliyeti bir stat + okuma ile sınırlıdır.
    """
    global _last_prune_at
    now = time.monotonic()
    if not force and (now - _last_prune_at) < PRUNE_INTERVAL_SEC:
        return
    _last_prune_at = now
    try:
        if not HATA_LOG_PATH.exists():
            return
        size = HATA_LOG_PATH.stat().st_size
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        raw = HATA_LOG_PATH.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines(keepends=True)
        kept = []
        dropped = 0
        for line in lines:
            if line.startswith("#"):
                continue
            m = _LINE_DATE_RE.match(line)
            if m and m.group(1) < cutoff:
                dropped += 1
                continue
            kept.append(line)

        # Tavan aşıldıysa en yeni satırlar tutulur, eskiler atılır.
        body_bytes = sum(len(line.encode("utf-8")) for line in kept)
        if body_bytes > MAX_FILE_BYTES:
            while kept and body_bytes > MAX_FILE_BYTES:
                body_bytes -= len(kept.pop(0).encode("utf-8"))
                dropped += 1

        if dropped == 0 and size <= MAX_FILE_BYTES:
            return
        tmp = HATA_LOG_PATH.with_suffix(".log.tmp")
        tmp.write_text(
            _HEADER.format(days=RETENTION_DAYS) + "".join(kept), encoding="utf-8"
        )
        os.replace(tmp, HATA_LOG_PATH)
    except Exception:
        pass


def kaydet(
    level: str,
    source: str,
    message: str,
    *,
    detail: Optional[str] = None,
    path: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Hatayı HATALAR.log'a yaz (tekrar bastırmalı). Asla exception fırlatmaz."""
    try:
        fp = _fingerprint(level, source, message, path)
        now = time.monotonic()
        write_line = True
        repeats = 0
        with _lock:
            entry = _seen.get(fp)
            if entry is not None:
                first_at, count = entry
                if (now - first_at) < DEDUPE_WINDOW_SEC:
                    # Pencere açık: yazma, sadece say.
                    _seen[fp] = (first_at, count + 1)
                    write_line = False
                else:
                    # Pencere kapandı: bastırılan tekrarları bildir ve yeni pencere aç.
                    repeats = count
                    _seen[fp] = (now, 0)
            else:
                _seen[fp] = (now, 0)
            if len(_seen) > MAX_FINGERPRINTS:
                for stale in sorted(_seen, key=lambda k: _seen[k][0])[:MAX_FINGERPRINTS // 4]:
                    _seen.pop(stale, None)
        if not write_line:
            return

        bits = []
        if path:
            bits.append(f"yol={_one_line(path, 200)}")
        if extra:
            for key, value in list(extra.items())[:8]:
                bits.append(f"{key}={_one_line(value, 120)}")
        if repeats:
            bits.append(f"tekrar={repeats + 1}")
        if detail:
            bits.append(f"ayrıntı={_one_line(detail, 600)}")

        line = (
            f"{_now_tr_str()} | {(level or 'ERROR').upper():8} | "
            f"{_one_line(source, 24):24} | {_one_line(message, MAX_LINE_CHARS)}"
        )
        if bits:
            line += " | " + " ".join(bits)
        _append(line[:MAX_LINE_CHARS] + "\n")
        prune()
    except Exception:
        pass


class HataLogHandler(logging.Handler):
    """Root logger'a takılan ERROR+ handler'ı — uygulamadaki tüm hatalar buraya düşer."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            detail = None
            if record.exc_info:
                detail = logging.Formatter().formatException(record.exc_info)
            kaydet(
                record.levelname,
                record.name,
                record.getMessage(),
                detail=detail,
                extra={"kod": f"{Path(record.pathname).name}:{record.lineno}"},
            )
        except Exception:
            pass


_installed = False


def install() -> None:
    """Handler'ı root'a ve propagate=False olan loggerlara tak (idempotent).

    ``app.botengine`` logger'ı propagate=False olduğu için root'a takmak yetmez;
    o ağacın hataları aksi halde dosyaya düşmez.
    """
    global _installed
    if _installed:
        return
    _installed = True
    try:
        handler = HataLogHandler()
        logging.getLogger().addHandler(handler)
        for name in ("app.botengine",):
            lg = logging.getLogger(name)
            if not lg.propagate:
                lg.addHandler(handler)
        prune(force=True)
    except Exception:
        pass
