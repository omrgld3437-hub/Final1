"""Mandatory V4 acceptance audits — route manifest, coverage, fingerprints, scenarios."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.audit_v4.auditor import (
    _profile_dict,
    audit_capacity,
    audit_directional_logic,
    audit_exposure,
    audit_fee_contradiction,
    audit_profile_distribution,
    audit_profile_ladders,
    audit_trailing,
    load_v4_templates_sampled,
    run_random_profile_logic_audit,
    run_random_signature_selection_audit,
)
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    clean_fallback_keys,
    is_forbidden_fallback,
    normalize_route_key,
)
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    normalize_side_distribution,
    trailing_too_large,
)
from app.services.dynamic_param_score.param_generator.live_route_classifier_v4 import (
    classify_regime_code_v4,
    classify_vol_code_v4,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    market_signature_v4_from_live,
)
from app.services.dynamic_param_score.param_generator.extended_coverage_v4 import (
    audit_extended_coverage_from_index,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    EXTENDED_COVERAGE_MIN_COUNT,
    MANDATORY_CRITICAL_ROUTES,
    MIN_PROFILES_PER_SHELF,
    ROUTE_MANIFEST_TOTAL,
    audit_route_manifest,
    enumerate_shelf_routes,
    extended_coverage_manifest,
    shelf_tier,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)


def audit_critical_route_coverage(
    index_path: Path,
    *,
    min_critical: int = EXTENDED_COVERAGE_MIN_COUNT,
    min_profiles_per_mandatory: int = MIN_PROFILES_PER_SHELF,
) -> Dict[str, Any]:
    report = audit_extended_coverage_from_index(
        index_path,
        min_count=min_critical,
        min_profiles=min_profiles_per_mandatory,
    )
    report["mandatory_routes"] = len(MANDATORY_CRITICAL_ROUTES)
    return report


def audit_r15_recovery_profiles(
    templates: List[ParamTemplate],
) -> Dict[str, Any]:
    """Verify R15 shelves are recovery behavior, not R2/R12 clones."""
    from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
        SCENARIO_SPECS,
        validate_scenario_direction,
    )

    spec = SCENARIO_SPECS["RECOVERY_AFTER_DUMP"]
    checked = 0
    clone_like = 0
    wrong_scenario = 0
    derived_from_r2 = 0
    rebuy_open_without_confirm = 0

    for tmpl in templates:
        p = _profile_dict(tmpl)
        rk = normalize_route_key(str(p.get("route_key") or ""))
        if "|R15|" not in rk:
            continue
        checked += 1
        if str(p.get("scenario") or "") != "RECOVERY_AFTER_DUMP":
            wrong_scenario += 1
        method = str(p.get("derivation_regime") or p.get("seed_derivation") or "")
        if "|R2|" in method:
            derived_from_r2 += 1
        if p.get("rebuy_enabled") is True and p.get("recovery_confirmation_required"):
            rebuy_open_without_confirm += 1
        buy = p.get("buy_grid_ladder_pcts") or []
        sell = p.get("sell_grid_ladder_pcts") or []
        ok, _ = validate_scenario_direction(
            spec,
            float(p.get("base_alloc_frac") or 0.5),
            float(p.get("quote_alloc_frac") or 0.5),
            buy,
            sell,
        )
        if not ok:
            clone_like += 1
        base = float(p.get("base_alloc_frac") or 0)
        if base < 0.34 or base > 0.51:
            clone_like += 1

    return {
        "r15_profiles_checked": checked,
        "r15_wrong_scenario": wrong_scenario,
        "r15_clone_like_fail": clone_like,
        "r15_derived_from_r2": derived_from_r2,
        "r15_rebuy_without_confirmation": rebuy_open_without_confirm,
        "pass": (
            checked > 0
            and wrong_scenario == 0
            and clone_like == 0
            and derived_from_r2 == 0
            and rebuy_open_without_confirm == 0
        ),
    }


def behavior_fingerprint(profile: Dict[str, Any]) -> str:
    parts = [
        str(profile.get("route_key") or ""),
        str(profile.get("grid_model") or profile.get("grid_bias") or ""),
        str(profile.get("buy_grid_count") or 0),
        str(profile.get("sell_grid_count") or 0),
        ",".join(str(x) for x in (profile.get("buy_grid_ladder_pcts") or [])),
        ",".join(str(x) for x in (profile.get("sell_grid_ladder_pcts") or [])),
        ",".join(str(x) for x in (profile.get("buy_distribution") or [])),
        ",".join(str(x) for x in (profile.get("sell_distribution") or [])),
        str(profile.get("trailing_model") or profile.get("buy_trailing_pct") or ""),
        str(profile.get("exposure_model") or profile.get("max_base_exposure_frac") or ""),
        str(profile.get("profit_cycle_model") or profile.get("rebuy_enabled") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def audit_profile_fingerprints(
    templates: List[ParamTemplate],
    *,
    pool_total: int = 300_000,
) -> Dict[str, Any]:
    fps: List[str] = []
    route_counts: Counter[str] = Counter()
    tier_empty_critical = 0
    for tmpl in templates:
        p = _profile_dict(tmpl)
        fps.append(behavior_fingerprint(p))
        rk = normalize_route_key(str(p.get("route_key") or ""))
        route_counts[rk] += 1

    fp_counts = Counter(fps)
    dup_rows = sum(1 for c in fp_counts.values() if c > 1)
    near_duplicate_rate = dup_rows / max(len(fps), 1)

    critical_routes = extended_coverage_manifest(min_count=EXTENDED_COVERAGE_MIN_COUNT)
    for rk in critical_routes:
        if route_counts.get(rk, 0) == 0:
            tier_empty_critical += 1

    critical_fps = [fp for fp, c in fp_counts.items() if c > 5 and c / max(len(fps), 1) > 0.001]
    critical_duplicate_rate = len(critical_fps) / max(len(fp_counts), 1)

    return {
        "profiles_total": len(templates),
        "unique_fingerprints": len(fp_counts),
        "near_duplicate_rate": round(near_duplicate_rate, 4),
        "critical_duplicate_rate": round(critical_duplicate_rate, 4),
        "empty_critical_routes": tier_empty_critical,
        "pass": (
            near_duplicate_rate <= 0.25
            and critical_duplicate_rate <= 0.10
            and tier_empty_critical == 0
        ),
    }


def run_re_like_downtrend_audit(*, sample_size: int = 100, seed: int = 20260626) -> Dict[str, Any]:
    rng = random.Random(seed)
    report: Dict[str, Any] = {
        "sample_size": sample_size,
        "wrong_balanced_regime": 0,
        "wrong_low_volatility": 0,
        "base_alloc_above_35": 0,
        "buy_grid_not_wider_than_sell": 0,
        "equal_two_grid_distribution": 0,
        "trailing_too_large": 0,
        "pass": True,
    }
    for _ in range(sample_size):
        ret24 = rng.uniform(-18, -6)
        dd7 = rng.uniform(20, 55)
        atr = rng.uniform(3.0, 6.0)
        z = rng.uniform(-3.0, -1.5)
        sig = market_signature_v4_from_live(
            symbol=rng.choice(["REUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT"]),
            budget=rng.choice([50, 100, 250, 500]),
            regime=RegimeTag.BALANCED_RANGE.value,
            risk_level="DEFENSIVE",
            volatility_percentile=rng.uniform(70, 95),
            lower_lows=True,
            higher_highs=False,
            fee_efficiency_score=int(rng.uniform(40, 70)),
            atr_1h_pct=atr,
            return_24h_pct=ret24,
            drawdown_7d_pct=dd7,
            z_score_5m=z,
            volatility_score=int(rng.uniform(70, 95)),
        )
        r_code = str(sig.get("regime_code") or "")
        v_code = str(sig.get("vol_code") or "")
        if r_code == "R2":
            report["wrong_balanced_regime"] += 1
        if v_code in ("V1", "V2"):
            report["wrong_low_volatility"] += 1

        from app.services.dynamic_param_score.param_generator.v4_resolvers import (
            apply_live_route_constraints,
        )

        params = apply_live_route_constraints(
            {
                "base_alloc_frac": 0.5,
                "quote_alloc_frac": 0.5,
                "buy_grid_ladder_pcts": [1.8, 4.0, 8.0],
                "sell_grid_ladder_pcts": [1.25, 3.0],
                "buy_distribution": [15, 30, 55],
                "sell_distribution": [35, 65],
                "buy_trailing_pct": 0.5,
                "sell_trailing_pct": 0.35,
            },
            sig,
        )
        if float(params.get("base_alloc_frac") or 0) > 0.35 + 1e-6:
            report["base_alloc_above_35"] += 1
        buy_g = params.get("buy_grid_ladder_pcts") or []
        sell_g = params.get("sell_grid_ladder_pcts") or []
        if buy_g and sell_g and float(buy_g[0]) < float(sell_g[0]) * 1.25 - 1e-6:
            report["buy_grid_not_wider_than_sell"] += 1
        for side in ("buy", "sell"):
            dist = params.get(f"{side}_distribution") or []
            if len(dist) == 2 and abs(dist[0] - dist[1]) < 3:
                report["equal_two_grid_distribution"] += 1
        if trailing_too_large(float(params.get("buy_trailing_pct") or 0), float(buy_g[0] if buy_g else 0)):
            report["trailing_too_large"] += 1

    report["pass"] = all(report[k] == 0 for k in report if k not in ("pass", "sample_size"))
    return report


def run_eth_lower_lows_defensive_audit(
    templates: List[ParamTemplate],
    *,
    sqlite_lazy: bool = True,
) -> Dict[str, Any]:
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=50.0,
        regime=RegimeTag.TRENDING_DOWN.value,
        risk_level="DEFENSIVE",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=0.97,
    )
    expected = "A1|R6|S2|V3|DEFENSIVE"
    report: Dict[str, Any] = {
        "expected_route": expected,
        "signature_route": sig.get("route_key"),
        "exact_candidate_count": 0,
        "runtime_safe_profile_generated": False,
        "max_exposure_above_50": 0,
        "active_buy_ladder_above_30pct": 0,
        "distribution_equal_fail": 0,
        "pass": False,
    }

    sub = SubScores(
        trend_score=35,
        volatility_score=45,
        range_score=50,
        liquidity_score=80,
        spread_score=70,
        fee_efficiency_score=55,
        exposure_safety_score=60,
        data_quality_score=85,
        btc_market_risk_score=50,
        drawdown_risk_score=55,
        mean_reversion_score=45,
    )
    ind = IndicatorSnapshot(lower_lows=True, higher_highs=False, atr14_pct_1h=0.97)
    portfolio = PortfolioState(
        total_equity_usdt=50.0,
        quote_balance=35.0,
        quote_value_usdt=35.0,
        base_balance=0.3,
        base_value_usdt=15.0,
        current_base_exposure_frac=0.30,
    )
    constraints = ExchangeConstraints(
        min_notional=5.0,
        step_size=0.001,
        tick_size=0.01,
        min_qty=0.001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )

    sel = select_template(
        param_score=55,
        regime=RegimeTag.TRENDING_DOWN,
        risk_state=RiskState.DEFENSIVE.value,
        sub=sub,
        ind=ind,
        portfolio=portfolio,
        constraints=constraints,
        budget_usdt=50.0,
        min_notional=5.0,
        symbol="ETHUSDT",
    )
    ctx = sel.selection_context or {}
    report["exact_candidate_count"] = int(ctx.get("exact_route_candidate_count") or 0)
    report["runtime_safe_profile_generated"] = bool(ctx.get("runtime_safe_profile_generated"))
    if sel.template:
        p = _profile_dict(sel.template)
        if float(p.get("max_base_exposure_frac") or 0) > 0.50 + 1e-6:
            report["max_exposure_above_50"] += 1
        for dist in (p.get("buy_distribution") or [], p.get("sell_distribution") or []):
            if len(dist) == 2 and abs(dist[0] - dist[1]) < 3:
                report["distribution_equal_fail"] += 1
            if len(dist) == 3 and max(dist) - min(dist) < 5:
                report["distribution_equal_fail"] += 1

    report["pass"] = (
        report["exact_candidate_count"] > 0
        and not report["runtime_safe_profile_generated"]
        and report["max_exposure_above_50"] == 0
        and report["distribution_equal_fail"] == 0
        and str(sig.get("route_key") or "").startswith("A1|R6|S2")
    )
    return report


def audit_crash_fallback_chain() -> Dict[str, Any]:
    report = {
        "r8_to_r2_fallback": 0,
        "r8_to_r1_fallback": 0,
        "r8_to_r3_fallback": 0,
        "crash_to_balanced": 0,
        "invalid_fallback": 0,
        "pass": True,
    }
    r8_route = "A1|R8|S2|V5|DEFENSIVE"
    for fb in clean_fallback_keys(r8_route):
        parts = fb.split("|")
        if len(parts) < 2:
            continue
        tr = parts[1]
        if tr == "R2":
            report["r8_to_r2_fallback"] += 1
        if tr == "R1":
            report["r8_to_r1_fallback"] += 1
        if tr == "R3":
            report["r8_to_r3_fallback"] += 1
        if is_forbidden_fallback("R8", tr, from_structure="S2", to_structure=parts[2]):
            report["invalid_fallback"] += 1
    if is_forbidden_fallback("R8", "R2"):
        report["crash_to_balanced"] += 1
    report["pass"] = (
        report["r8_to_r2_fallback"] == 0
        and report["r8_to_r1_fallback"] == 0
        and report["r8_to_r3_fallback"] == 0
        and report["invalid_fallback"] == 0
    )
    return report


def run_mandatory_acceptance_suite(
    *,
    profiles_path: Optional[str] = None,
    index_path: Optional[Path] = None,
    sample_size: int = 1000,
    seed: int = 20260626,
) -> Dict[str, Any]:
    from app.services.dynamic_param_score.param_pool.sqlite_store import (
        DEFAULT_V4_SELECTION_INDEX_PATH,
    )

    idx_path = index_path or DEFAULT_V4_SELECTION_INDEX_PATH
    manifest = audit_route_manifest()
    coverage = audit_critical_route_coverage(idx_path, min_critical=100)

    templates, load_meta = load_v4_templates_sampled(
        profiles_path,
        sample_size=sample_size,
        seed=seed,
        stratified=True,
    )
    profile_logic = run_random_profile_logic_audit(templates, sample_size=sample_size, seed=seed)
    signature = run_random_signature_selection_audit(templates, sample_size=sample_size, seed=seed)
    re_like = run_re_like_downtrend_audit(sample_size=100, seed=seed)
    eth_ll = run_eth_lower_lows_defensive_audit(templates)
    crash_fb = audit_crash_fallback_chain()
    r15_audit = audit_r15_recovery_profiles(templates)
    fingerprints = audit_profile_fingerprints(templates, pool_total=load_meta.get("profiles_total", 300_000))

    trailing_too_large_count = profile_logic.get("trailing_fail", 0)

    suite: Dict[str, Any] = {
        "profiles_total": load_meta.get("profiles_total", 300_000),
        "route_manifest_total": manifest.get("route_manifest_total"),
        "budget_in_route": manifest.get("budget_in_route"),
        "fee_in_route": manifest.get("fee_in_route"),
        "critical_route_empty": coverage.get("critical_route_empty"),
        "optional_route_empty_total": coverage.get("optional_route_empty_total"),
        "extended_pass": coverage.get("extended_pass"),
        "r15_derived_from_r2": 0,
        "schema_fail": profile_logic.get("schema_fail", 0),
        "distribution_fail": profile_logic.get("distribution_fail", 0),
        "trailing_too_large": trailing_too_large_count,
        "directional_critical_fail": profile_logic.get("directional_critical_fail", 0),
        "wrong_regime": re_like.get("wrong_balanced_regime", 0),
        "wrong_volatility_class": re_like.get("wrong_low_volatility", 0),
        "invalid_fallback": signature.get("invalid_fallback", 0) + crash_fb.get("invalid_fallback", 0),
        "r8_to_r2_fallback": crash_fb.get("r8_to_r2_fallback", 0),
        "zero_candidate_but_selected": signature.get("zero_candidate_but_selected", 0),
        "exposure_violation": profile_logic.get("exposure_violation", 0),
        "fee_contradiction": profile_logic.get("fee_contradiction", 0),
        "near_duplicate_rate": fingerprints.get("near_duplicate_rate"),
        "runtime_safe_profile_rate": None,
        "pass": False,
        "sections": {
            "route_manifest": manifest,
            "critical_coverage": coverage,
            "profile_logic": profile_logic,
            "signature_selection": signature,
            "re_like_downtrend": re_like,
            "eth_lower_lows_defensive": eth_ll,
            "crash_fallback": crash_fb,
            "r15_recovery": r15_audit,
            "fingerprints": fingerprints,
        },
    }

    hard_zeros = (
        "invalid_fallback",
        "directional_critical_fail",
        "distribution_fail",
        "trailing_too_large",
        "exposure_violation",
        "r8_to_r2_fallback",
        "critical_route_empty",
        "r15_derived_from_r2",
    )
    suite["pass"] = (
        manifest.get("pass") is True
        and coverage.get("pass") is True
        and profile_logic.get("pass") is True
        and signature.get("pass") is True
        and re_like.get("pass") is True
        and eth_ll.get("pass") is True
        and crash_fb.get("pass") is True
        and r15_audit.get("pass") is True
        and all(suite.get(k) == 0 for k in hard_zeros)
    )
    suite["r15_derived_from_r2"] = r15_audit.get("r15_derived_from_r2", 0)
    return suite
