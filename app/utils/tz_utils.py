"""
Türkiye saati (Europe/Istanbul) – "Bugün" ve "şimdi" için ortak yardımcılar.
Uygulama genelinde giriş/çıkış, işlemler, PnL bugün vb. tek saat (Türkiye) kullanılır.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

TR_TZ = ZoneInfo("Europe/Istanbul")


class TurkeyTimeFormatter(logging.Formatter):
    """Logging formatter: %(asctime)s Türkiye saatinde."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=TR_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def turkey_now_utc() -> datetime:
    """Şu an Türkiye saatinde; naive UTC olarak döner (DB ile uyumlu)."""
    return datetime.now(TR_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def turkey_today_date_str() -> str:
    """Türkiye takvim günü (YYYY-MM-DD); canlı saat Europe/Istanbul."""
    return datetime.now(TR_TZ).strftime("%Y-%m-%d")


def turkey_today_start_utc() -> datetime:
    """Türkiye'de bugünün gece yarısı (00:00, 23:59'dan sonraki an), naive UTC olarak."""
    now_tr = datetime.now(TR_TZ)
    midnight_tr = now_tr.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_tr.astimezone(timezone.utc).replace(tzinfo=None)


def parse_binance_ms_to_utc_naive(raw: Any) -> Optional[datetime]:
    """Binance zaman alanı (ms epoch int/float/str veya ISO) → naive UTC datetime."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return datetime.fromtimestamp(float(s) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError, OverflowError):
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")[:26].rstrip("Z"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            return None
    return None


def turkey_day_start_utc_for_date(date_tr: str) -> datetime:
    """
    Given date_tr (YYYY-MM-DD), return that day's 00:00 in Turkey (Europe/Istanbul) as naive UTC.
    Used for daily realized PnL: cycle completed on date_tr iff max(trade.ts) in [day_start, day_end).
    """
    from datetime import date as date_type
    try:
        d = date_type.fromisoformat(date_tr)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date_tr: {date_tr!r}")
    midnight_tr = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=TR_TZ)
    return midnight_tr.astimezone(timezone.utc).replace(tzinfo=None)


def turkey_day_end_utc_for_date(date_tr: str) -> datetime:
    """Next day start (exclusive end for [day_start, day_end)). Naive UTC."""
    start = turkey_day_start_utc_for_date(date_tr)
    return start + timedelta(days=1)


def bot_started_on_tr_date(started_at, date_tr: str) -> bool:
    """Bot started_at falls on Turkey calendar date YYYY-MM-DD."""
    if started_at is None or not date_tr:
        return False
    try:
        if isinstance(started_at, str):
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        elif isinstance(started_at, datetime):
            dt = started_at
        else:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TR_TZ).strftime("%Y-%m-%d") == date_tr
    except Exception:
        return False
