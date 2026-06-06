"""
Türkiye saati (Europe/Istanbul) – "Bugün" ve "şimdi" için ortak yardımcılar.
Uygulama genelinde giriş/çıkış, işlemler, PnL bugün vb. tek saat (Türkiye) kullanılır.
"""
import logging
from datetime import datetime, timezone, timedelta
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


def turkey_today_start_utc() -> datetime:
    """Türkiye'de bugünün gece yarısı (00:00), naive UTC olarak."""
    now_tr = datetime.now(TR_TZ)
    midnight_tr = now_tr.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_tr.astimezone(timezone.utc).replace(tzinfo=None)


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
