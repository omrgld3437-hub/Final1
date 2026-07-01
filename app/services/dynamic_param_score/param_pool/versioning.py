"""Param pool version management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from app.services.dynamic_param_score.param_pool.defaults import (
    POOL_VERSION_ID,
    POOL_VERSION_V2,
    POOL_VERSION_V3,
    POOL_VERSION_V4,
    build_v1_pool,
    build_v2_pool,
    build_v3_pool,
    build_v4_pool,
)
from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.param_pool.manifest import build_manifest, pool_checksum
from app.services.dynamic_param_score.param_pool.models import ParamPoolVersion, ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_SQLITE_PATH,
    DEFAULT_V2_MANIFEST_PATH,
    DEFAULT_V2_SQLITE_PATH,
    DEFAULT_V3_MANIFEST_PATH,
    DEFAULT_V3_SQLITE_PATH,
    DEFAULT_V4_MANIFEST_PATH,
    DEFAULT_V4_SQLITE_PATH,
    load_route_index_map,
    load_templates_from_sqlite,
    selection_index_path_for_version,
)

_CACHED_POOLS: Dict[str, List[ParamTemplate]] = {}
_CACHED_INDEXED_POOLS: Dict[str, object] = {}
_USE_SQLITE = os.environ.get("PARAM_POOL_MODE", "auto") != "programmatic"


def resolve_pool_version(version_id: Optional[str] = None) -> str:
    if version_id:
        return version_id
    if os.environ.get("PARAM_POOL_VERSION"):
        return os.environ["PARAM_POOL_VERSION"]
    if os.environ.get("PARAM_POOL_MODE") == "v1":
        return POOL_VERSION_ID
    if os.environ.get("PARAM_POOL_MODE") == "v2":
        return POOL_VERSION_V2
    if os.environ.get("PARAM_POOL_MODE") == "v3":
        return POOL_VERSION_V3
    if os.environ.get("PARAM_POOL_MODE") == "v4":
        return POOL_VERSION_V4
    if DEFAULT_V4_SQLITE_PATH.exists():
        return POOL_VERSION_V4
    if DEFAULT_V3_SQLITE_PATH.exists():
        return POOL_VERSION_V3
    if DEFAULT_V2_SQLITE_PATH.exists():
        return POOL_VERSION_V2
    if os.environ.get("PARAM_POOL_MODE") == "programmatic":
        return POOL_VERSION_V4
    return POOL_VERSION_V4


def _sqlite_paths_for_version(version_id: str) -> tuple[Path, Path]:
    if version_id == POOL_VERSION_V4:
        return DEFAULT_V4_SQLITE_PATH, DEFAULT_V4_MANIFEST_PATH
    if version_id == POOL_VERSION_V3:
        return DEFAULT_V3_SQLITE_PATH, DEFAULT_V3_MANIFEST_PATH
    if version_id == POOL_VERSION_V2:
        return DEFAULT_V2_SQLITE_PATH, DEFAULT_V2_MANIFEST_PATH
    return DEFAULT_SQLITE_PATH, DEFAULT_MANIFEST_PATH


def lazy_shelf_enabled(version_id: Optional[str] = None) -> bool:
    """V4: load only route shelf on demand."""
    vid = resolve_pool_version(version_id)
    if vid != POOL_VERSION_V4:
        return False
    flag = os.environ.get("PARAM_POOL_LAZY_SHELF", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    return DEFAULT_V4_SQLITE_PATH.exists() and selection_index_path_for_version(vid).exists()


def get_pool_version(version_id: Optional[str] = None) -> ParamPoolVersion:
    vid = resolve_pool_version(version_id)
    if lazy_shelf_enabled(vid):
        _, manifest_path = _sqlite_paths_for_version(vid)
        from app.services.dynamic_param_score.param_pool.manifest import read_manifest

        manifest = read_manifest(manifest_path) if manifest_path.exists() else None
        count = int(manifest.template_count if manifest else 0)
        checksum = manifest.checksum[:16] if manifest and manifest.checksum else "lazy"
        return ParamPoolVersion(
            version_id=vid,
            label=f"Param Template Pool {vid}",
            template_count=count,
            status="active",
            notes=f"Havuz — {count} template (lazy shelf mode), checksum {checksum}",
        )

    templates = load_version_templates(vid)
    if not templates:
        templates = []
    active = [t for t in templates if t.status == "active"]
    checksum = pool_checksum(active)
    return ParamPoolVersion(
        version_id=vid,
        label=f"Param Template Pool {vid}",
        template_count=len(templates),
        status="active",
        notes=f"Havuz — {len(active)} active template, checksum {checksum[:16]}",
    )


def _load_from_sqlite(version_id: str) -> Optional[List[ParamTemplate]]:
    sqlite_path, manifest_path = _sqlite_paths_for_version(version_id)
    if not sqlite_path.exists():
        return None
    try:
        return load_templates_from_sqlite(sqlite_path, version_id, manifest_path=manifest_path)
    except Exception:
        return None


def _normalize_loaded_templates(templates: List[ParamTemplate]) -> List[ParamTemplate]:
    """Runtime fixes for pool artifacts (WAIT/NO_TRADE deployable, SELL_MANAGEMENT base gate)."""
    out: List[ParamTemplate] = []
    for t in templates:
        if t.final_action in (
            FinalAction.NO_TRADE.value,
            FinalAction.WAIT.value,
            FinalAction.WAIT_SAFETY.value,
            FinalAction.SAFE_WAIT.value,
        ):
            updates: dict = {"deployable": False}
            buy_n = int(t.params.get("buy_grid_count") or 0)
            sell_n = int(t.params.get("sell_grid_count") or 0)
            if buy_n > 0 or sell_n > 0:
                updates["params"] = {**t.params, "buy_grid_count": 0, "sell_grid_count": 0}
            t = t.model_copy(update=updates)
        elif t.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
            hl = dict(t.hard_limits or {})
            hl.setdefault("requires_sell_min_notional", True)
            hl["requires_has_base"] = True
            t = t.model_copy(
                update={
                    "requires_sellable_base": True,
                    "hard_limits": hl,
                }
            )
        out.append(t)
    return out


def load_version_templates(version_id: str) -> List[ParamTemplate]:
    if version_id in _CACHED_POOLS:
        return _CACHED_POOLS[version_id]

    templates: Optional[List[ParamTemplate]] = None
    if _USE_SQLITE:
        templates = _load_from_sqlite(version_id)

    if templates is None:
        if version_id == POOL_VERSION_V4:
            templates = build_v4_pool()
        elif version_id == POOL_VERSION_V3:
            templates = build_v3_pool()
        elif version_id == POOL_VERSION_V2:
            templates = build_v2_pool()
        else:
            templates = build_v1_pool()

    templates = _normalize_loaded_templates(templates)
    _CACHED_POOLS[version_id] = templates
    return templates


def load_indexed_pool(version_id: Optional[str] = None):
    """Load ParamPool with memory indexes (cached per version)."""
    vid = resolve_pool_version(version_id)
    if vid in _CACHED_INDEXED_POOLS:
        return _CACHED_INDEXED_POOLS[vid]

    if lazy_shelf_enabled(vid):
        from app.services.dynamic_param_score.param_pool.manifest import read_manifest
        from app.services.dynamic_param_score.param_pool.sqlite_store import ParamPool

        sqlite_path, manifest_path = _sqlite_paths_for_version(vid)
        manifest = read_manifest(manifest_path) if manifest_path.exists() else None
        route_ids = load_route_index_map(vid)
        pool = ParamPool(
            pool_version=vid,
            templates=[],
            manifest=manifest,
            lazy_mode=True,
        )
        pool._route_key_ids = route_ids
        pool._sqlite_path = sqlite_path
        _CACHED_INDEXED_POOLS[vid] = pool
        return pool

    templates = load_version_templates(vid)
    from app.services.dynamic_param_score.param_pool.manifest import read_manifest
    from app.services.dynamic_param_score.param_pool.sqlite_store import ParamPool

    _, manifest_path = _sqlite_paths_for_version(vid)
    manifest = read_manifest(manifest_path) if manifest_path.exists() else build_manifest(templates, vid)
    pool = ParamPool(pool_version=vid, templates=templates, manifest=manifest)
    pool.build_memory_indexes()
    _CACHED_INDEXED_POOLS[vid] = pool
    return pool


def clear_pool_cache() -> None:
    _CACHED_POOLS.clear()
    _CACHED_INDEXED_POOLS.clear()


def production_pool_status(version_id: Optional[str] = None) -> Dict[str, object]:
    """Report whether the on-disk V4 pool + route index are usable for live selection."""
    from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
        MANDATORY_CRITICAL_ROUTES,
        MIN_PROFILES_PER_SHELF,
    )

    vid = resolve_pool_version(version_id)
    sqlite_path, manifest_path = _sqlite_paths_for_version(vid)
    index_path = selection_index_path_for_version(vid)
    route_ids = load_route_index_map(vid) if index_path.exists() else {}
    profile_count = sum(len(v) for v in route_ids.values())
    route_count = len(route_ids)
    mandatory_missing = [
        rk
        for rk in MANDATORY_CRITICAL_ROUTES
        if len(route_ids.get(rk, [])) < MIN_PROFILES_PER_SHELF
    ]
    loaded = bool(
        sqlite_path.exists()
        and index_path.exists()
        and route_count > 0
        and profile_count > 0
    )
    return {
        "pool_version": vid,
        "production_pool_loaded": loaded,
        "sqlite_path": str(sqlite_path),
        "selection_index_path": str(index_path),
        "route_index_route_count": route_count,
        "route_index_profile_count": profile_count,
        "mandatory_shelves_ok": len(mandatory_missing) == 0,
        "mandatory_missing_routes": mandatory_missing,
        "lazy_shelf_enabled": lazy_shelf_enabled(vid),
    }
