"""Duplicate / near-duplicate profile detection (behavior-based)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from tools.param_quality_engine.profile_normalizer import behavior_fingerprint


def detect_duplicates(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_fp: Dict[str, List[str]] = defaultdict(list)
    by_id: Dict[str, int] = defaultdict(int)
    v2_fps: Dict[str, List[str]] = defaultdict(list)
    precision_fps: Dict[str, List[str]] = defaultdict(list)

    for p in profiles:
        pid = str(p.get("profile_id") or p.get("template_key") or "")
        by_id[pid] += 1
        fp = behavior_fingerprint(p)
        by_fp[fp].append(pid)
        bucket = v2_fps if p.get("has_dps_profile") else precision_fps
        bucket[fp].append(pid)

    dup_ids = [pid for pid, n in by_id.items() if n > 1]
    dup_fps = {fp: ids for fp, ids in by_fp.items() if len(ids) > 1}
    near_dup_excess = sum(len(v) - 1 for v in dup_fps.values())
    unique_fps = len(by_fp)
    near_dup_rate = round(100.0 * near_dup_excess / max(len(profiles), 1), 4)

    def _rate(fps_map: Dict[str, List[str]], total: int) -> float:
        if total <= 0:
            return 0.0
        excess = sum(len(v) - 1 for v in fps_map.values() if len(v) > 1)
        return round(100.0 * excess / total, 4)

    v2_total = sum(1 for p in profiles if p.get("has_dps_profile"))
    prec_total = len(profiles) - v2_total
    v2_rate = _rate(v2_fps, v2_total)
    prec_rate = _rate(precision_fps, prec_total)

    status = "pass"
    if near_dup_rate > 25 or unique_fps < 150000:
        status = "fail"
    elif near_dup_rate > 10:
        status = "warning"
    if near_dup_rate > 50:
        status = "critical_fail"

    return {
        "total_profiles": len(profiles),
        "unique_behavior_fingerprints": unique_fps,
        "unique_fingerprints": unique_fps,
        "duplicate_profile_ids": len(dup_ids),
        "duplicate_id_samples": dup_ids[:30],
        "near_duplicate_groups": len(dup_fps),
        "near_duplicate_excess": near_dup_excess,
        "near_duplicate_rate_pct": near_dup_rate,
        "duplicate_rate_pct": near_dup_rate,
        "v2_library_near_duplicate_rate_pct": v2_rate,
        "precision_pool_near_duplicate_rate_pct": prec_rate,
        "v2_unique_fingerprints": len(v2_fps),
        "precision_unique_fingerprints": len(precision_fps),
        "status": status,
        "top_duplicate_groups": [
            {"fingerprint": fp, "count": len(ids), "sample_ids": ids[:5]}
            for fp, ids in sorted(dup_fps.items(), key=lambda x: -len(x[1]))[:20]
        ],
    }
