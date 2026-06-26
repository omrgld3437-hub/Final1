"""Disk cache for DPS Engine V4 (300k) parameter pool."""

from __future__ import annotations

import os
from typing import List, Optional

from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.precision_generator import load_templates_from_jsonl
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_JSONL_PATH,
    DEFAULT_V4_MANIFEST_PATH,
    DEFAULT_V4_SQLITE_PATH,
    load_templates_from_sqlite,
)

from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import POOL_TARGET_V4


def try_load_v4_pool_from_disk(
    *,
    min_count: int = POOL_TARGET_V4,
) -> Optional[List[ParamTemplate]]:
    if os.environ.get("DPS_FORCE_REBUILD") == "1":
        return None

    if DEFAULT_V4_SQLITE_PATH.exists():
        try:
            templates = load_templates_from_sqlite(
                DEFAULT_V4_SQLITE_PATH,
                "v4.0.0",
                manifest_path=DEFAULT_V4_MANIFEST_PATH if DEFAULT_V4_MANIFEST_PATH.exists() else None,
            )
            if templates and len(templates) >= min_count:
                return templates[:min_count] if min_count else templates
        except Exception:
            pass

    if DEFAULT_V4_JSONL_PATH.exists():
        try:
            templates = load_templates_from_jsonl(DEFAULT_V4_JSONL_PATH)
            if templates and len(templates) >= min_count:
                return templates[:min_count] if min_count else templates
        except Exception:
            pass

    return None
