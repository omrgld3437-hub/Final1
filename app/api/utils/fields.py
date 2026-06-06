"""
Snapshot fields query parameter: allowed set, validation. Unknown field -> 400 INVALID_FIELDS.
"""

from __future__ import annotations
from typing import List, Set, Tuple

ALLOWED_SNAPSHOT_FIELDS: Set[str] = {"prices", "wallet", "bots", "kpis"}
DEFAULT_SNAPSHOT_FIELDS: List[str] = ["prices", "kpis"]


def parse_snapshot_fields(
    fields_param: str | None,
) -> Tuple[List[str], List[str] | None]:
    """
    Parse comma-separated fields. Returns (list of allowed fields, invalid_list or None).
    If invalid_list is not None, return 400 with error_code INVALID_FIELDS.
    """
    if not fields_param or not fields_param.strip():
        return (DEFAULT_SNAPSHOT_FIELDS.copy(), None)
    parts = [p.strip().lower() for p in fields_param.split(",") if p.strip()]
    invalid = [p for p in parts if p not in ALLOWED_SNAPSHOT_FIELDS]
    if invalid:
        return ([], invalid)
    return (parts if parts else DEFAULT_SNAPSHOT_FIELDS.copy(), None)
