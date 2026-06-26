"""Param pool manifest — checksum, profile distribution, build metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from app.services.dynamic_param_score.param_pool.models import ParamPoolManifest, ParamTemplate


def pool_checksum(templates: List[ParamTemplate]) -> str:
    """Stable SHA256 checksum over active template keys."""
    payload = sorted(
        f"{t.template_key}:{t.version}:{t.status}:{t.profile_family}"
        for t in templates
        if t.status == "active"
    )
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def profile_distribution(templates: List[ParamTemplate]) -> Dict[str, int]:
    dist: Dict[str, int] = {}
    for t in templates:
        if t.status != "active":
            continue
        dist[t.profile_family] = dist.get(t.profile_family, 0) + 1
    return dict(sorted(dist.items()))


def build_manifest(
    templates: List[ParamTemplate],
    pool_version: str,
    *,
    schema_version: str = "1.0",
    notes: str | None = None,
    base_pool_version: str | None = None,
    added_template_count: int | None = None,
) -> ParamPoolManifest:
    active = [t for t in templates if t.status == "active"]
    return ParamPoolManifest(
        pool_version=pool_version,
        template_count=len(templates),
        active_template_count=len(active),
        checksum=pool_checksum(active),
        created_at=datetime.now(timezone.utc).isoformat(),
        schema_version=schema_version,
        profile_distribution=profile_distribution(active),
        base_pool_version=base_pool_version,
        added_template_count=added_template_count,
        notes=notes,
    )


def write_manifest(path: Path, manifest: ParamPoolManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> ParamPoolManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ParamPoolManifest.model_validate(data)


def write_sha256_sidecar(manifest_path: Path, checksum: str) -> Path:
    sidecar = manifest_path.with_suffix(".sha256")
    sidecar.write_text(checksum + "\n", encoding="utf-8")
    return sidecar
