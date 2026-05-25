"""bots_trades timestamp parsing — naive DB + aware ledger must not crash duration."""
from datetime import datetime, timezone

from app.api.bots_engine import _parse_ts_utc


def test_parse_ts_utc_naive_assumed_utc():
    dt = _parse_ts_utc("2026-05-24T00:26:46.415471")
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_parse_ts_utc_aware_normalized():
    dt = _parse_ts_utc("2026-05-24T14:17:39.591374+00:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_mixed_ts_list_max_min():
    a = _parse_ts_utc("2026-05-24T00:26:46.415471")
    b = _parse_ts_utc("2026-05-24T14:17:39.591374+00:00")
    assert a is not None and b is not None
    assert (max(a, b) - min(a, b)).total_seconds() > 0
