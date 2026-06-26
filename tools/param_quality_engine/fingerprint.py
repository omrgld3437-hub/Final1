"""Delta audit — fingerprint-based incremental quality checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

from tools.param_quality_engine.profile_normalizer import behavior_fingerprint
from tools.param_quality_engine.fast_audit import run_fast_full_audit
from tools.param_quality_engine.deep_risk_audit import run_deep_risk_audit


def load_baseline_fingerprints(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "fingerprints" in data:
        items = data["fingerprints"]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    out: Dict[str, str] = {}
    for row in items:
        if isinstance(row, dict):
            pid = str(row.get("profile_id") or "")
            fp = str(row.get("fingerprint") or "")
            if pid and fp:
                out[pid] = fp
    return out


def compute_delta_targets(
    profiles: List[Dict[str, Any]],
    baseline: Dict[str, str],
    *,
    include_prior_failures: Set[str] | None = None,
) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    prior = prior_failures or set()
    for p in profiles:
        pid = str(p.get("profile_id") or p.get("template_key") or "")
        fp = behavior_fingerprint(p)
        reason = None
        if pid not in baseline:
            reason = "new_profile"
        elif baseline[pid] != fp:
            reason = "fingerprint_changed"
        elif pid in prior:
            reason = "prior_failure"
        elif p.get("fee_class") == "fee_bad":
            reason = "fee_bad_risk"
        elif float(p.get("score_prior") or 0) >= 85:
            reason = "top_candidate"
        if reason:
            targets.append({**p, "_delta_reason": reason, "_fingerprint": fp})
    return targets


def run_delta_audit(
    profiles: List[Dict[str, Any]],
    baseline_path: Path,
    *,
    output_dir: Path | None = None,
) -> Dict[str, Any]:
    baseline = load_baseline_fingerprints(baseline_path)
    fast = run_fast_full_audit(profiles)
    prior_fail = set(fast.get("bad_profile_ids") or [])
    targets = compute_delta_targets(profiles, baseline, include_prior_failures=prior_fail)

    fast_subset = {**fast, "bad_profile_ids": [t.get("profile_id") for t in targets]}
    deep = run_deep_risk_audit(profiles, fast_subset, max_replay_profiles=min(len(targets), 5000))

    fingerprints = [
        {"profile_id": p.get("profile_id"), "fingerprint": behavior_fingerprint(p)}
        for p in profiles
    ]

    if output_dir:
        out_fp = output_dir / "profile_fingerprints.json"
        out_fp.write_text(json.dumps({"fingerprints": fingerprints}, indent=2), encoding="utf-8")

    return {
        "layer": "delta",
        "baseline_profiles": len(baseline),
        "delta_targets": len(targets),
        "new_profiles": sum(1 for t in targets if t.get("_delta_reason") == "new_profile"),
        "changed_fingerprints": sum(1 for t in targets if t.get("_delta_reason") == "fingerprint_changed"),
        "fast_audit": fast,
        "deep_audit": deep,
        "fingerprints": fingerprints,
    }
