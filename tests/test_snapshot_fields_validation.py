"""Patch C: Snapshot fields parameter validation."""
import pytest
from app.api.utils.fields import parse_snapshot_fields, ALLOWED_SNAPSHOT_FIELDS, DEFAULT_SNAPSHOT_FIELDS


def test_parse_empty_returns_default():
    fields, invalid = parse_snapshot_fields(None)
    assert invalid is None
    assert fields == DEFAULT_SNAPSHOT_FIELDS

    fields, invalid = parse_snapshot_fields("")
    assert invalid is None
    assert fields == DEFAULT_SNAPSHOT_FIELDS


def test_parse_valid_fields():
    fields, invalid = parse_snapshot_fields("prices,wallet,bots,kpis")
    assert invalid is None
    assert set(fields) == {"prices", "wallet", "bots", "kpis"}


def test_parse_invalid_field_returns_invalid_list():
    fields, invalid = parse_snapshot_fields("prices,foo,kpis")
    assert invalid == ["foo"]
    assert fields == []


def test_parse_case_insensitive():
    fields, invalid = parse_snapshot_fields("PRICES,KPIS")
    assert invalid is None
    assert fields == ["prices", "kpis"]


def test_allowed_fields_constant():
    assert "prices" in ALLOWED_SNAPSHOT_FIELDS
    assert "wallet" in ALLOWED_SNAPSHOT_FIELDS
    assert "bots" in ALLOWED_SNAPSHOT_FIELDS
    assert "kpis" in ALLOWED_SNAPSHOT_FIELDS
    assert "logs" not in ALLOWED_SNAPSHOT_FIELDS
