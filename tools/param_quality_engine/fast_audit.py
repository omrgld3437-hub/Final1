"""Katman 1 — Full Fast Audit (vectorized, no heavy replay)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from tools.param_quality_engine.profile_normalizer import behavior_fingerprint
from tools.param_quality_engine import profile_schema_validator as schema_v
from tools.param_quality_engine import grid_math_validator as grid_v
from tools.param_quality_engine import amount_distribution_validator as amount_v
from tools.param_quality_engine.duplicate_profile_detector import detect_duplicates
from tools.param_quality_engine.coverage_gap_analyzer import analyze_coverage


def _try_pandas_schema_batch(profiles: List[Dict[str, Any]]) -> Tuple[int, int, Counter]:
    try:
        import pandas as pd

        df = pd.DataFrame(profiles)
        required = [
            "profile_id", "asset_class", "budget_class", "regime", "risk_level",
            "volatility_bin", "fee_class", "spread_class", "version",
        ]
        missing_mask = df[required].isna().any(axis=1) if all(c in df.columns for c in required) else None
        passed = 0
        failed = 0
        reasons: Counter = Counter()
        for p in profiles:
            ok, errs = schema_v.validate_profile_schema(p)
            if ok:
                passed += 1
            else:
                failed += 1
                for e in errs:
                    reasons[e.split(":")[0]] += 1
        _ = missing_mask  # reserved for future vectorized missing-field pass
        return passed, failed, reasons
    except ImportError:
        passed = failed = 0
        reasons: Counter = Counter()
        for p in profiles:
            ok, errs = schema_v.validate_profile_schema(p)
            if ok:
                passed += 1
            else:
                failed += 1
                for e in errs:
                    reasons[e.split(":")[0]] += 1
        return passed, failed, reasons


def run_fast_full_audit(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run all structural/math checks on every profile — no engine replay."""
    schema_pass, schema_fail, schema_reasons = _try_pandas_schema_batch(profiles)
    schema = {
        "total_profiles": len(profiles),
        "passed": schema_pass,
        "failed": schema_fail,
        "failure_reasons": dict(schema_reasons),
        "pass_rate_pct": round(100.0 * schema_pass / max(len(profiles), 1), 4),
    }

    grid = grid_v.audit_all_profiles(profiles)
    amount = amount_v.audit_all_profiles(profiles)
    duplicates = detect_duplicates(profiles)
    coverage = analyze_coverage(profiles)

    bad_ids: List[str] = []
    for p in profiles:
        ok, errs = schema_v.validate_profile_schema(p)
        if not ok:
            bad_ids.append(str(p.get("profile_id") or p.get("template_key") or ""))
        elif not grid_v.validate_profile_grid_math(p)[0]:
            bad_ids.append(str(p.get("profile_id") or ""))

    fingerprints = [
        {
            "profile_id": p.get("profile_id"),
            "fingerprint": behavior_fingerprint(p),
        }
        for p in profiles
    ]

    return {
        "layer": "fast-full",
        "profiles_audited": len(profiles),
        "truncated": False,
        "schema": schema,
        "grid_math": grid,
        "amount_distribution": amount,
        "duplicates": duplicates,
        "coverage": coverage,
        "bad_profile_ids": bad_ids[:5000],
        "fingerprints": fingerprints,
        "FAST_FULL_AUDIT_SUMMARY": {
            "profiles_audited": len(profiles),
            "schema_pass_rate_pct": schema["pass_rate_pct"],
            "grid_critical_failures": grid.get("critical_failures", 0),
            "near_duplicate_rate_pct": duplicates.get("near_duplicate_rate_pct", 0),
            "coverage_required_pct": coverage.get("coverage_required_pct", 0),
            "elapsed_note": "structural only — no DPS replay",
        },
        "PROFILE_SCHEMA_FAST_RESULT": schema,
        "GRID_MATH_FAST_RESULT": grid,
        "DUPLICATE_FINGERPRINT_FAST_RESULT": duplicates,
        "COVERAGE_FAST_RESULT": coverage,
    }
