#!/usr/bin/env python3
"""CLI: V4 parameter library random logic and signature selection audits."""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.audit_v4.auditor import (  # noqa: E402
    load_v4_templates_sampled,
    prepare_v4_lazy_pool_for_selection,
    run_random_profile_logic_audit,
    run_random_signature_selection_audit,
    write_fail_sample_csvs,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import POOL_TARGET_V4  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DPS V4 audit — random profile logic & signature selection")
    p.add_argument(
        "--profiles-path",
        type=str,
        default=str(ROOT / "data" / "param_pool" / "v4" / "param_pool_v4.sqlite"),
    )
    p.add_argument(
        "--mode",
        type=str,
        default="both",
        choices=(
            "random-profile-logic",
            "random-signature-selection",
            "both",
        ),
    )
    p.add_argument("--sample-size", type=int, default=1000)
    p.add_argument("--seed", type=int, default=20260626)
    p.add_argument("--output-dir", type=str, default="audit_output/v4")
    p.add_argument("--zip", dest="zip_output", action="store_true", default=True)
    p.add_argument("--no-zip", dest="zip_output", action="store_false")
    return p.parse_args()


def _stamp_report(report: dict, *, mode: str, load_meta: dict, seed: int) -> dict:
    report["profiles_total"] = load_meta.get("profiles_total", POOL_TARGET_V4)
    report["load_meta"] = load_meta
    report["mode"] = mode
    report["seed"] = seed
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report


def _merge_fail_samples(*reports: dict) -> dict:
    merged: dict = {}
    for report in reports:
        samples = report.get("fail_samples") or {}
        for key, rows in samples.items():
            merged.setdefault(key, []).extend(rows)
    return merged


def _executive_summary(profile_report: dict, signature_report: dict) -> dict:
    return {
        "sample_size": profile_report.get("sample_size"),
        "seed": profile_report.get("seed"),
        "profiles_total": profile_report.get("profiles_total", POOL_TARGET_V4),
        "profile_logic": profile_report,
        "signature_selection": signature_report,
        "schema_fail": profile_report.get("schema_fail", 0),
        "route_key_fail": profile_report.get("route_key_fail", 0),
        "budget_in_route_fail": profile_report.get("budget_in_route_fail", 0),
        "fee_in_route_fail": profile_report.get("fee_in_route_fail", 0),
        "ladder_null_fail": profile_report.get("ladder_null_fail", 0),
        "intentional_empty_ladder": profile_report.get("intentional_empty_ladder", 0),
        "unexpected_ladder_null": profile_report.get("unexpected_ladder_null", 0),
        "distribution_fail": profile_report.get("distribution_fail", 0),
        "directional_critical_fail": profile_report.get("directional_critical_fail", 0),
        "trailing_fail": profile_report.get("trailing_fail", 0),
        "fee_contradiction": profile_report.get("fee_contradiction", 0),
        "min_notional_critical_fail": profile_report.get("min_notional_critical_fail", 0),
        "exposure_violation": profile_report.get("exposure_violation", 0),
        "invalid_fallback": signature_report.get("invalid_fallback", 0),
        "selection_trace_missing": (
            profile_report.get("selection_trace_missing", 0)
            + signature_report.get("selection_trace_missing", 0)
        ),
        "zero_candidate_but_selected": (
            profile_report.get("zero_candidate_but_selected", 0)
            + signature_report.get("zero_candidate_but_selected", 0)
        ),
        "invalid_route": signature_report.get("invalid_route", 0),
        "directional_logic_fail": signature_report.get("directional_logic_fail", 0),
        "pass": bool(profile_report.get("pass")) and bool(signature_report.get("pass")),
    }


def main() -> int:
    args = parse_args()
    os.environ.setdefault("PARAM_POOL_VERSION", "v4.0.0")
    os.environ.setdefault("PARAM_POOL_LAZY_SHELF", "1")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: dict[str, dict] = {}
    exit_code = 0

    if args.mode in ("random-profile-logic", "both"):
        templates, load_meta = load_v4_templates_sampled(
            args.profiles_path or None,
            sample_size=args.sample_size,
            seed=args.seed,
            stratified=True,
        )
        if not templates:
            report = {"pass": False, "error": "no_templates", "load_meta": load_meta}
            reports["random-profile-logic"] = report
            exit_code = 1
        else:
            report = run_random_profile_logic_audit(
                templates, sample_size=min(args.sample_size, len(templates)), seed=args.seed
            )
            reports["random-profile-logic"] = _stamp_report(
                report, mode="random-profile-logic", load_meta=load_meta, seed=args.seed
            )
            if not report.get("pass"):
                exit_code = 1

    if args.mode in ("random-signature-selection", "both"):
        pool_meta = prepare_v4_lazy_pool_for_selection()
        warmup_n = min(50, args.sample_size)
        templates, warmup_meta = load_v4_templates_sampled(
            args.profiles_path or None,
            sample_size=warmup_n,
            seed=args.seed,
            stratified=True,
        )
        load_meta = {
            **pool_meta,
            "signature_audit_sample_size": args.sample_size,
            "warmup_templates_requested": warmup_n,
            "warmup_templates_loaded": len(templates or []),
            "warmup_keys_sampled": warmup_meta.get("keys_sampled"),
            "warmup_load_mode": warmup_meta.get("load_mode"),
        }
        report = run_random_signature_selection_audit(
            templates or [],
            sample_size=args.sample_size,
            seed=args.seed,
        )
        reports["random-signature-selection"] = _stamp_report(
            report, mode="random-signature-selection", load_meta=load_meta, seed=args.seed
        )
        if not report.get("pass"):
            exit_code = 1

    written: list[Path] = []
    all_fail_samples: dict = {}
    for mode, report in reports.items():
        fname = f"v4_audit_{mode}_{args.seed}.json"
        out_path = out_dir / fname
        payload = dict(report)
        fail_samples = payload.pop("fail_samples", None)
        if fail_samples:
            for key, rows in fail_samples.items():
                all_fail_samples.setdefault(key, []).extend(rows)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(out_path)
        print(json.dumps(payload, indent=2))

    if all_fail_samples:
        written.extend(write_fail_sample_csvs(all_fail_samples, out_dir))

    if args.mode == "both" and len(reports) == 2:
        summary = _executive_summary(
            reports["random-profile-logic"],
            reports["random-signature-selection"],
        )
        summary_path = out_dir / f"v4_audit_executive_summary_{args.seed}.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        written.append(summary_path)
        print("\n--- executive summary ---")
        print(json.dumps(summary, indent=2))

    if args.zip_output and written:
        zip_path = out_dir / f"v4_audit_bundle_{args.seed}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in written:
                zf.write(p, arcname=p.name)
        print(f"\nWrote zip: {zip_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
