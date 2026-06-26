"""Load and normalize parameter profiles for quality audit."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V3_JSONL_PATH,
    DEFAULT_V3_SQLITE_PATH,
    load_templates_from_sqlite,
)
from tools.param_quality_engine.profile_normalizer import template_to_audit_profile


def _load_jsonl(path: Path) -> List[ParamTemplate]:
    out: List[ParamTemplate] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(ParamTemplate.model_validate(json.loads(line)))
    return out


def resolve_profiles_path(profiles_path: Optional[Path], project_root: Path) -> Optional[Path]:
    if profiles_path and profiles_path.exists():
        return profiles_path
    for candidate in (
        DEFAULT_V3_SQLITE_PATH,
        DEFAULT_V3_JSONL_PATH,
        project_root / "data/param_pool/v3/param_pool_v3.sqlite",
        project_root / "data/param_pool/v3/param_pool_v3.jsonl",
        project_root / "data/param_pool/v2/param_pool_v2.sqlite",
    ):
        if candidate.exists():
            return candidate
    return None


def load_profiles(
    *,
    profiles_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
    max_profiles: Optional[int] = None,
    full: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (audit_profiles, load_meta). Always loads full active pool unless max_profiles set."""
    project_root = project_root or ROOT
    path = resolve_profiles_path(profiles_path, project_root)
    templates: List[ParamTemplate] = []
    source = "programmatic_build"

    if path:
        source = str(path)
        if path.suffix == ".sqlite":
            templates = load_templates_from_sqlite(path)
        elif path.suffix == ".jsonl":
            templates = _load_jsonl(path)
        else:
            raise ValueError(f"Unsupported profiles path: {path}")
    else:
        os.environ.setdefault("DPS_USE_SQLITE", "0")
        os.environ["DPS_FULL_POOL"] = "1"
        os.environ["DPS_POOL_TARGET"] = "200000"
        from app.services.dynamic_param_score.param_generator.param_library_builder import (
            build_dps_v2_pool,
        )

        templates = build_dps_v2_pool()

    active = [t for t in templates if t.status == "active"]
    total_active = len(active)
    truncated = False

    if max_profiles is not None and len(active) > max_profiles:
        active = active[:max_profiles]
        truncated = True

    profiles = [template_to_audit_profile(t) for t in active]
    meta = {
        "source": source,
        "total_templates": len(templates),
        "active_count": len(active),
        "profiles_audited": len(profiles),
        "pool_version": active[0].version if active else None,
        "truncated": truncated,
        "full_pool": not truncated and len(profiles) >= 190000,
    }
    return profiles, meta


def iter_profiles_chunked(
    profiles: List[Dict[str, Any]], chunk: int = 5000
) -> Iterator[List[Dict[str, Any]]]:
    for i in range(0, len(profiles), chunk):
        yield profiles[i : i + chunk]
