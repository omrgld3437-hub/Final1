from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.bot_performance_service import (
    normalize_perf_period,
    performance_period_start_ts,
    period_calendar_range,
)

TR_TZ = ZoneInfo("Europe/Istanbul")


def test_performance_period_start_ts_aligns_with_calendar_range():
    date_from, _, _ = period_calendar_range("day")
    assert date_from is not None
    start_ts = performance_period_start_ts("day")
    assert start_ts is not None
    expected = (
        datetime.strptime(date_from, "%Y-%m-%d")
        .replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=TR_TZ)
        .astimezone(timezone.utc)
    )
    assert start_ts == expected


def test_normalize_perf_period_aliases():
    assert normalize_perf_period("daily") == "day"
    assert normalize_perf_period("week") == "week"
    assert normalize_perf_period("month") == "month"
    assert normalize_perf_period("all") == "all"
