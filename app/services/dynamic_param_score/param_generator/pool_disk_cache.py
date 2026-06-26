"""Disk cache for DPS Engine V2 (200k) parameter pool."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.precision_generator import load_templates_from_jsonl
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V3_JSONL_PATH,
    DEFAULT_V3_MANIFEST_PATH,
    DEFAULT_V3_SQLITE_PATH,
    load_templates_from_sqlite,
)

from app.services.dynamic_param_score.param_generator.param_library_builder import POOL_TARGET_V3


def try_load_v3_pool_from_disk(
    *,
    min_count: int = POOL_TARGET_V3,
) -> Optional[List[ParamTemplate]]:
    """Load pre-built v3 pool from SQLite or JSONL (avoids runtime 200k generation)."""
    if os.environ.get("DPS_FORCE_REBUILD") == "1":
        return None

    if DEFAULT_V3_SQLITE_PATH.exists():
        try:
            templates = load_templates_from_sqlite(
                DEFAULT_V3_SQLITE_PATH,
                "v3.0.0",
                manifest_path=DEFAULT_V3_MANIFEST_PATH if DEFAULT_V3_MANIFEST_PATH.exists() else None,
            )
            if templates and len(templates) >= min_count:
                return templates[:min_count] if min_count else templates
        except Exception:
            pass

    if DEFAULT_V3_JSONL_PATH.exists():
        try:
            templates = load_templates_from_jsonl(DEFAULT_V3_JSONL_PATH)
            if templates and len(templates) >= min_count:
                return templates[:min_count] if min_count else templates
        except Exception:
            pass

    return None
