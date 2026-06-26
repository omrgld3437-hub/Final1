#!/usr/bin/env python3
"""Parametre Kalite Motoru — 3-layer smart audit CLI."""

from __future__ import annotations

import argparse
import io
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.param_quality_engine.config import AuditConfig, AUDIT_MODES, AUDIT_SYMBOLS_DEFAULT
from tools.param_quality_engine.load_profiles import load_profiles
from tools.param_quality_engine.fast_audit import run_fast_full_audit
from tools.param_quality_engine.smart_sampler import run_smart_sample_audit
from tools.param_quality_engine.deep_risk_audit import run_deep_risk_audit, run_exhaustive_deep_audit
from tools.param_quality_engine.fingerprint import run_delta_audit
from tools.param_quality_engine import min_notional_auditor as min_n_v
from tools.param_quality_engine import fee_spread_slippage_auditor as fee_v
from tools.param_quality_engine import wait_decision_auditor as wait_v
from tools.param_quality_engine import market_feature_trace as market_v
from tools.param_quality_engine import code_tree_auditor as code_v
from tools.param_quality_engine import dependency_graph_builder as dep_v
from tools.param_quality_engine import frontend_backend_contract_auditor as contract_v
from tools.param_quality_engine import scenario_replay_engine as scenario_v
from tools.param_quality_engine.report_writer import create_zip, write_all_reports


def parse_args() -> AuditConfig:
    p = argparse.ArgumentParser(description="Parametre Kalite Motoru — smart audit")
    p.add_argument("--profiles-path", type=str, default="")
    p.add_argument("--project-root", type=str, default=str(ROOT))
    p.add_argument("--output-dir", type=str, default="audit_output")
    p.add_argument(
        "--mode",
        type=str,
        default="smart-full",
        choices=list(AUDIT_MODES),
        help="Audit mode: fast-full | smart-sample | deep-risk | smart-full | exhaustive-deep | delta | legacy",
    )
    p.add_argument(
        "--sample-live-symbols",
        type=str,
        default=",".join(AUDIT_SYMBOLS_DEFAULT),
    )
    p.add_argument("--symbols", type=str, default="")
    p.add_argument("--full", action="store_true", default=True)
    p.add_argument("--no-full", dest="full", action="store_false")
    p.add_argument("--zip", dest="zip_output", action="store_true", default=False)
    p.add_argument("--max-profiles", type=int, default=None)
    p.add_argument("--sample-per-cell", type=int, default=7)
    p.add_argument("--enhance-pool", action="store_true", help="Run pool quality enhancer before audit")
    p.add_argument("--baseline", type=str, default="")
    args = p.parse_args()
    profiles_path = Path(args.profiles_path).resolve() if args.profiles_path else None
    symbols = tuple(s.strip() for s in (args.symbols or args.sample_live_symbols).split(",") if s.strip())
    baseline = Path(args.baseline).resolve() if args.baseline else None
    return AuditConfig(
        project_root=Path(args.project_root).resolve(),
        profiles_path=profiles_path,
        output_dir=Path(args.output_dir),
        sample_live_symbols=symbols,
        full=args.full,
        zip_output=args.zip_output,
        max_profiles=args.max_profiles,
        mode=args.mode,
        sample_per_cell=args.sample_per_cell,
        baseline_path=baseline,
        enhance_pool=args.enhance_pool,
    )


def _legacy_audit(profiles, cfg, bundle, log_buf):
    from tools.param_quality_engine import profile_schema_validator as schema_v
    from tools.param_quality_engine import grid_math_validator as grid_v
    from tools.param_quality_engine import amount_distribution_validator as amount_v
    from tools.param_quality_engine import selection_trace_auditor as trace_v
    from tools.param_quality_engine import coverage_gap_analyzer as coverage_v
    from tools.param_quality_engine import duplicate_profile_detector as dup_v

    bundle["schema"] = schema_v.audit_all_profiles(profiles)
    bundle["grid_math"] = grid_v.audit_all_profiles(profiles)
    bundle["amount_dist"] = amount_v.audit_all_profiles(profiles)
    bundle["min_notional"] = min_n_v.audit_all_profiles(profiles, sample_limit=len(profiles))
    bundle["fee_spread"] = fee_v.audit_all_profiles(profiles)
    bundle["wait"] = wait_v.audit_all_profiles(profiles)
    bundle["scenario"] = scenario_v.run_all_scenarios()
    bundle["selection_trace"] = trace_v.audit_symbols(list(cfg.sample_live_symbols))
    bundle["coverage"] = coverage_v.analyze_coverage(profiles)
    bundle["duplicates"] = dup_v.detect_duplicates(profiles)
    return bundle


def run_audit(cfg: AuditConfig) -> dict:
    log_buf = io.StringIO()
    errors: list[str] = []
    warnings: list[str] = []
    t0 = time.monotonic()

    with redirect_stdout(log_buf), redirect_stderr(log_buf):
        print(f"=== Param Quality Engine Audit (mode={cfg.mode}) ===")

        if cfg.enhance_pool and cfg.profiles_path:
            from tools.param_pool.enhance_pool_quality import enhance_pool
            from app.services.dynamic_param_score.param_pool.sqlite_store import load_templates_from_sqlite, write_pool_sqlite
            from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache

            print("Enhancing pool quality...")
            templates = load_templates_from_sqlite(cfg.profiles_path)
            enhanced, emeta = enhance_pool(templates)
            write_pool_sqlite(enhanced, cfg.profiles_path, enhanced[0].version if enhanced else "v3.0.0")
            clear_pool_cache()
            print(f"Pool enhanced: {emeta}")

        profiles, load_meta = load_profiles(
            profiles_path=cfg.profiles_path,
            project_root=cfg.project_root,
            max_profiles=cfg.max_profiles,
            full=cfg.full,
        )
        print(f"Loaded {len(profiles)} profiles from {load_meta.get('source')}")

        if load_meta.get("truncated"):
            warnings.append("Profile set truncated — remove --max-profiles for full 200k audit")
        elif len(profiles) < 190000 and cfg.full:
            warnings.append(f"Expected ~200k profiles, got {len(profiles)}")

        bundle: dict = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": cfg.mode,
            "profiles": profiles,
            "load_meta": load_meta,
            "errors": errors,
            "warnings": warnings,
        }

        if cfg.mode == "delta":
            if not cfg.baseline_path:
                raise ValueError("--baseline required for delta mode")
            delta = run_delta_audit(profiles, cfg.baseline_path, output_dir=cfg.resolve_output_dir())
            bundle.update(delta)
            fast = delta.get("fast_audit") or {}
            bundle["schema"] = fast.get("schema")
            bundle["grid_math"] = fast.get("grid_math")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")
            deep = delta.get("deep_audit") or {}
            bundle["scenario"] = deep.get("scenario_replay")
            bundle["selection_trace"] = deep.get("selection_trace")

        elif cfg.mode == "fast-full":
            fast = run_fast_full_audit(profiles)
            bundle["fast_audit"] = fast
            bundle["schema"] = fast.get("schema")
            bundle["grid_math"] = fast.get("grid_math")
            bundle["amount_dist"] = fast.get("amount_distribution")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")

        elif cfg.mode == "smart-sample":
            sample = run_smart_sample_audit(profiles, sample_per_cell=cfg.sample_per_cell)
            bundle["smart_sample"] = sample
            fast = run_fast_full_audit(profiles)
            bundle["fast_audit"] = fast
            bundle["schema"] = fast.get("schema")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")

        elif cfg.mode == "deep-risk":
            fast = run_fast_full_audit(profiles)
            bundle["fast_audit"] = fast
            deep = run_deep_risk_audit(profiles, fast, symbols=list(cfg.sample_live_symbols))
            bundle["deep_risk"] = deep
            bundle["scenario"] = deep.get("scenario_replay")
            bundle["selection_trace"] = deep.get("selection_trace")
            bundle["schema"] = fast.get("schema")
            bundle["grid_math"] = fast.get("grid_math")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")

        elif cfg.mode == "exhaustive-deep":
            fast = run_fast_full_audit(profiles)
            bundle["fast_audit"] = fast
            deep = run_exhaustive_deep_audit(profiles, symbols=list(cfg.sample_live_symbols))
            bundle["deep_risk"] = deep
            bundle["scenario"] = deep.get("scenario_replay")
            bundle["selection_trace"] = deep.get("selection_trace")
            bundle["schema"] = fast.get("schema")
            bundle["grid_math"] = fast.get("grid_math")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")

        elif cfg.mode == "smart-full":
            print("Layer 1: Fast full audit...")
            fast = run_fast_full_audit(profiles)
            bundle["fast_audit"] = fast
            bundle["schema"] = fast.get("schema")
            bundle["grid_math"] = fast.get("grid_math")
            bundle["amount_dist"] = fast.get("amount_distribution")
            bundle["coverage"] = fast.get("coverage")
            bundle["duplicates"] = fast.get("duplicates")

            print("Layer 2: Smart coverage sampling...")
            sample = run_smart_sample_audit(profiles, sample_per_cell=cfg.sample_per_cell)
            bundle["smart_sample"] = sample

            print("Layer 3: Risk-based deep replay...")
            deep = run_deep_risk_audit(profiles, fast, symbols=list(cfg.sample_live_symbols))
            bundle["deep_risk"] = deep
            bundle["scenario"] = deep.get("scenario_replay")
            bundle["selection_trace"] = deep.get("selection_trace")

        else:
            bundle = _legacy_audit(profiles, cfg, bundle, log_buf)

        if cfg.mode != "legacy":
            print("Supplementary audits...")
            rep_n = (bundle.get("smart_sample") or {}).get("representatives_selected") or len(profiles)
            min_sample = min(rep_n, 15000) if cfg.mode in ("smart-full", "smart-sample") else len(profiles)
            bundle["min_notional"] = min_n_v.audit_all_profiles(
                profiles, sample_limit=min(min_sample, len(profiles))
            )
            bundle["fee_spread"] = fee_v.audit_all_profiles(profiles)
            bundle["wait"] = wait_v.audit_all_profiles(profiles)

        print("Infrastructure audits...")
        try:
            samples = market_v.sample_live_features(list(cfg.sample_live_symbols))
            bundle["market_trace"] = market_v.build_market_feature_trace(sample_values=samples)
        except Exception as exc:
            warnings.append(f"market_trace: {exc}")
            bundle["market_trace"] = market_v.build_market_feature_trace()

        bundle["code_tree"] = code_v.audit_code_tree(cfg.project_root)
        bundle["dependency"] = dep_v.build_dependency_graph(cfg.project_root)
        bundle["contract"] = contract_v.audit_contract(cfg.project_root)

        if bundle.get("scenario"):
            try:
                bundle["eth_replay_md"] = scenario_v.format_symbol_replay_md(
                    "ETHUSDT", bundle["scenario"].get("results") or []
                )
                bundle["btc_replay_md"] = scenario_v.format_symbol_replay_md(
                    "BTCUSDT", bundle["scenario"].get("results") or []
                )
            except Exception as exc:
                warnings.append(f"symbol_replay_md: {exc}")

        elapsed = round(time.monotonic() - t0, 2)
        bundle["elapsed_seconds"] = elapsed
        bundle["test_logs"] = log_buf.getvalue() + f"\nElapsed: {elapsed}s\n"
        bundle["errors"] = errors
        bundle["warnings"] = warnings
        print(f"Audit completed in {elapsed}s")

    return bundle


def main() -> int:
    cfg = parse_args()
    out = cfg.resolve_output_dir()
    out.mkdir(parents=True, exist_ok=True)

    try:
        bundle = run_audit(cfg)
        write_all_reports(out, bundle)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if cfg.zip_output:
            zip_path = create_zip(out, ts)
            print(f"Audit complete. Zip: {zip_path}")
        else:
            print(f"Audit complete. Output: {out}")
        overall = bundle.get("final_report", {}).get("overall", "UNKNOWN")
        print(f"Overall: {overall}")
        print(f"Profiles audited: {bundle.get('load_meta', {}).get('profiles_audited')}")
        print(f"Truncated: {bundle.get('load_meta', {}).get('truncated')}")
        return 0 if overall in ("PASS", "PARTIAL PASS") else 1
    except Exception as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
