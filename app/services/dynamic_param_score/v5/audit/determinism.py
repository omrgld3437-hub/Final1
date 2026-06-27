"""Determinism audit — double generation + random usage scan."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import List

from app.services.dynamic_param_score.v5.generator.generate_shelves import FORMULA_VERSION, generate_all_v5_shelves

V5_ROOT = Path("app/services/dynamic_param_score/v5")
FORBIDDEN_PATTERNS = (
    "random.random",
    "Math.random",
    "uuid.uuid4",
    "uuid4(",
    "secrets.",
    "os.urandom",
)


V5_SCAN_DIRS = (
    Path("app/services/dynamic_param_score/v5/generator"),
    Path("app/services/dynamic_param_score/v5/resolver"),
    Path("app/services/dynamic_param_score/v5/index"),
)


def _scan_no_random_in_v5() -> List[str]:
    hits: List[str] = []
    root = Path(__file__).resolve().parents[5]
    for sub in V5_SCAN_DIRS:
        for py in (root / sub).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for pat in FORBIDDEN_PATTERNS:
                if pat in text and "FORBIDDEN_PATTERNS" not in text:
                    hits.append(f"{py.relative_to(root)}:{pat}")
    return hits


def audit_determinism(sample_size: int = 500) -> dict:
    shelves_a = generate_all_v5_shelves()
    shelves_b = generate_all_v5_shelves()

    if len(shelves_a) != len(shelves_b):
        return {"pass_audit": False, "error": "count mismatch on regen"}

    hash_a = hashlib.sha256(
        json.dumps([s.shelf_id + s.generation_meta.source_logic_hash for s in shelves_a], sort_keys=True).encode()
    ).hexdigest()
    hash_b = hashlib.sha256(
        json.dumps([s.shelf_id + s.generation_meta.source_logic_hash for s in shelves_b], sort_keys=True).encode()
    ).hexdigest()

    mismatches: List[str] = []
    step = max(1, len(shelves_a) // sample_size)
    for i in range(0, len(shelves_a), step):
        sa, sb = shelves_a[i], shelves_b[i]
        if sa.route_key != sb.route_key or sa.generation_meta.source_logic_hash != sb.generation_meta.source_logic_hash:
            mismatches.append(sa.route_key)
        if sa.base_template.sell_grid_levels_pct != sb.base_template.sell_grid_levels_pct:
            mismatches.append(f"grid:{sa.route_key}")

    random_hits = _scan_no_random_in_v5()
    all_random_false = all(s.generation_meta.random_used is False for s in shelves_a)

    pass_audit = hash_a == hash_b and not mismatches and not random_hits and all_random_false

    return {
        "formula_version": FORMULA_VERSION,
        "run_a_aggregate_hash": hash_a[:32],
        "run_b_aggregate_hash": hash_b[:32],
        "hashes_match": hash_a == hash_b,
        "sampled_mismatch_count": len(mismatches),
        "mismatch_samples": mismatches[:20],
        "random_used_all_false": all_random_false,
        "forbidden_random_scan_hits": random_hits,
        "pass_audit": pass_audit,
    }
