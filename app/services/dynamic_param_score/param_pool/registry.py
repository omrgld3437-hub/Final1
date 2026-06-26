"""Active param template pool registry."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_ID, POOL_VERSION_V2, POOL_VERSION_V3
from app.services.dynamic_param_score.param_pool.models import ParamPoolVersion, ParamTemplate
from app.services.dynamic_param_score.param_pool.validators import validate_pool
from app.services.dynamic_param_score.param_pool.versioning import (
    get_pool_version,
    lazy_shelf_enabled,
    load_version_templates,
    resolve_pool_version,
)

_ACTIVE_VERSION = resolve_pool_version()


def get_active_version_id() -> str:
    return resolve_pool_version(_ACTIVE_VERSION)


def set_active_version(version_id: str) -> None:
    global _ACTIVE_VERSION
    _ACTIVE_VERSION = version_id


def load_pool(version_id: Optional[str] = None) -> List[ParamTemplate]:
    vid = resolve_pool_version(version_id or _ACTIVE_VERSION)
    templates = load_version_templates(vid) or []
    return [t for t in templates if t.status == "active"]


def get_active_pool() -> Tuple[ParamPoolVersion, List[ParamTemplate]]:
    vid = get_active_version_id()
    version = get_pool_version(vid)
    if lazy_shelf_enabled(vid):
        return version, []
    templates = load_pool(vid)
    return version, templates


def assert_pool_valid(version_id: Optional[str] = None) -> None:
    vid = resolve_pool_version(version_id or _ACTIVE_VERSION)
    templates = load_version_templates(vid)
    ok, errors = validate_pool(templates)
    if not ok:
        raise ValueError("Param pool validation failed:\n" + "\n".join(errors[:20]))
