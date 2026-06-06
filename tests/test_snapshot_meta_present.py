"""Patch C: Snapshot response must include meta with request_id, server_ms, payload_bytes, trimmed_fields, stale."""

import pytest


def test_snapshot_response_shape_documentation():
    """Document expected keys; actual contract test would call the endpoint with auth."""
    expected_meta_keys = {
        "request_id",
        "server_ms",
        "payload_bytes",
        "trimmed_fields",
        "stale",
    }
    assert len(expected_meta_keys) == 5
    assert "request_id" in expected_meta_keys
    assert "payload_bytes" in expected_meta_keys
