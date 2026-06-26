"""Random 1000 profile / signature audits for DPS V4 clean route architecture."""

from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.services.dynamic_param_score.audit_v4.library_schema import (
    PROFILE_TYPE_LIBRARY,
    audit_library_profile_schema,
    profile_type_of,
)
from app.services.dynamic_param_score.models import ExchangeConstraints
from app.services.dynamic_param_score.param_generator.candidate_validator import hard_validate_profile
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    BUDGET_SHELVES,
    budget_code_from_class,
    budget_midpoint_v4,
    is_forbidden_fallback,
    normalize_route_key,
)
from app.services.dynamic_param_score.param_generator.library_repair_v4 import (
    classify_ladder_issue,
    is_intentional_empty_ladder,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    market_signature_v4_from_live,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import POOL_TARGET_V4
from app.services.dynamic_param_score.param_generator.v4_resolvers import resolve_capacity
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

BUDGETS = [25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]


def _profile_dict(template: ParamTemplate) -> Dict[str, Any]:
    dps = (template.params or {}).get("dps_profile") or {}
    p = dict(template.params or {})
    p.update(dps)
    for dist_key in ("buy_distribution", "sell_distribution"):
        if isinstance(p.get(dist_key), str):
            if isinstance(dps.get(dist_key), list):
                p[dist_key] = dps[dist_key]
            else:
                p.pop(dist_key, None)
    p.setdefault("profile_id", template.template_key)
    p.setdefault("route_key", dps.get("route_key"))
    p.setdefault("final_action", template.final_action)
    p.setdefault("profile_family", template.profile_family)
    return p


def _route_key_valid(rk: str) -> bool:
    normalized = normalize_route_key(str(rk or ""))
    parts = normalized.split("|")
    if len(parts) != 5:
        return False
    a, r, s, v, risk = parts
    if not (a.startswith("A") and r.startswith("R") and s.startswith("S") and v.startswith("V")):
        return False
    return bool(risk)


def _regime_from_route(route_key: str) -> str:
    parts = normalize_route_key(str(route_key or "")).split("|")
    return parts[1] if len(parts) >= 2 else ""


def _asset_from_route(route_key: str) -> str:
    parts = normalize_route_key(str(route_key or "")).split("|")
    return parts[0] if len(parts) >= 1 else ""


def audit_profile_schema(profile: Dict[str, Any]) -> List[str]:
    """Legacy string codes — prefer audit_library_profile_schema for detail."""
    rows = audit_library_profile_schema(profile)
    return list(dict.fromkeys(r.get("reason") or r.get("missing_field") or r.get("invalid_field") for r in rows))


def audit_profile_ladders(profile: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Return (fail_codes, intentional_empty)."""
    issues, intentional = classify_ladder_issue(profile)
    if intentional:
        return [], True
    if issues:
        return issues, False

    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)
    if buy_n == 0 and sell_n == 0:
        return [], True

    ok, hard_errs = hard_validate_profile(profile)
    if not ok:
        return hard_errs, False
    return [], False


def audit_profile_distribution(profile: Dict[str, Any]) -> List[str]:
    fails: List[str] = []
    if is_intentional_empty_ladder(profile):
        return fails
    for side in ("buy", "sell"):
        dist = profile.get(f"{side}_distribution") or []
        grids = profile.get(f"{side}_grid_ladder_pcts") or profile.get(f"{side}_grid_pcts") or []
        if not dist or not grids:
            continue
        if not isinstance(dist, list) or not all(isinstance(x, (int, float)) for x in dist):
            fails.append(f"{side}_distribution_invalid")
            continue
        total = sum(float(x) for x in dist)
        if abs(total - 100) > 1.0 and abs(total - 1.0) > 0.02:
            fails.append(f"{side}_distribution_fail")
        if len(dist) == 2 and abs(dist[0] - dist[1]) < 3:
            fails.append(f"{side}_fifty_fifty_fail")
        if len(dist) == 3 and max(dist) - min(dist) < 5:
            fails.append(f"{side}_equal_three_fail")
        if len(dist) != len(grids):
            fails.append(f"{side}_dist_grid_len_mismatch")
    return fails


def audit_directional_logic(profile: Dict[str, Any]) -> List[str]:
    from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
        SCENARIO_SPECS,
        validate_scenario_direction,
    )

    scenario = str(profile.get("scenario") or "")
    if scenario not in SCENARIO_SPECS:
        return []

    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)
    if buy_n < 1 or sell_n < 1:
        return []

    spec = SCENARIO_SPECS[scenario]
    base = float(profile.get("base_alloc_frac") or 0.5)
    quote = float(profile.get("quote_alloc_frac") or 0.5)
    buy_g = profile.get("buy_grid_ladder_pcts") or profile.get("buy_grid_pcts") or []
    sell_g = profile.get("sell_grid_ladder_pcts") or profile.get("sell_grid_pcts") or []
    ok, _errs = validate_scenario_direction(spec, base, quote, buy_g, sell_g)
    return [] if ok else ["directional_scenario_fail"]


def audit_trailing(profile: Dict[str, Any]) -> List[str]:
    if is_intentional_empty_ladder(profile):
        return []
    fails: List[str] = []
    for side in ("buy", "sell"):
        grids = profile.get(f"{side}_grid_ladder_pcts") or profile.get(f"{side}_grid_pcts") or []
        if not grids:
            continue
        first = float(grids[0])
        trail = float(profile.get(f"{side}_trailing_pct") or profile.get("trailing_pct") or 0)
        if trail < 0:
            fails.append(f"{side}_trailing_negative")
        if trail > first * 0.30 + 1e-6:
            fails.append(f"{side}_trailing_fail")
        if trail > 0 and (first - trail) < 0.54 - 1e-6:
            fails.append(f"{side}_net_room_fail")
    return fails


def audit_fee_contradiction(profile: Dict[str, Any]) -> List[str]:
    """Library fee checks — fee lives in CostResolver at runtime, not in route_key."""
    fails: List[str] = []
    if profile_type_of(profile) == "runtime_output":
        return fails

    fee_class = str(profile.get("fee_class") or "")
    fee_code = str(profile.get("fee_code") or "")
    fa = str(profile.get("final_action") or "").upper()

    if fee_class == "fee_bad" and fa in ("WAIT", "NO_TRADE", "SAFE_WAIT"):
        fails.append("fee_bad_wait")
    if fee_code == "F6" and fa in ("WAIT", "NO_TRADE", "SAFE_WAIT"):
        fails.append("fee_bad_wait")

    total_cost = profile.get("total_cost_pct")
    if total_cost is not None and float(total_cost) <= 0.001:
        if not profile.get("cost_floor_applied") and not profile.get("cost_floor_pct"):
            fails.append("fee_zero_without_floor")

    if fee_class == "fee_bad" or fee_code == "F6":
        widen = float(profile.get("grid_widening_multiplier") or 1.30)
        first_grid = float(
            (profile.get("sell_grid_ladder_pcts") or profile.get("buy_grid_ladder_pcts") or [0])[0]
            or 0
        )
        if first_grid > 0 and first_grid < 1.8 * widen * 0.95:
            fails.append("fee_bad_not_widened")
    return fails


def _budgets_for_profile(profile: Dict[str, Any]) -> List[float]:
    b_code = str(
        profile.get("budget_code")
        or budget_code_from_class(str(profile.get("budget_class") or "50_100"))
    )
    mid = budget_midpoint_v4(b_code)
    label, tier_lo, tier_hi = BUDGET_SHELVES.get(b_code, ("50_100", 50.0, 100.0))
    base_frac = float(profile.get("base_alloc_frac") or 0.5)
    quote_frac = float(profile.get("quote_alloc_frac") or 0.5)
    mn = DEFAULT_MIN_NOTIONAL_USDT
    budgets: List[float] = []
    for b in (mid, max(float(tier_lo), 10.0)):
        if b * max(base_frac, quote_frac) >= mn * 0.99:
            budgets.append(round(b, 2))
    return budgets or [mid]


def audit_capacity(
    profile: Dict[str, Any],
    *,
    min_notional: float = DEFAULT_MIN_NOTIONAL_USDT,
) -> List[str]:
    if is_intentional_empty_ladder(profile):
        return []
    fails: List[str] = []
    base_frac = float(profile.get("base_alloc_frac") or 0.5)
    quote_frac = float(profile.get("quote_alloc_frac") or 0.5)
    buy_n = int(profile.get("buy_grid_count") or 0)
    sell_n = int(profile.get("sell_grid_count") or 0)

    for budget in _budgets_for_profile(profile):
        cap = resolve_capacity(
            budget=budget,
            base_alloc_frac=base_frac,
            quote_alloc_frac=quote_frac,
            min_notional=min_notional,
            profile_buy_n=buy_n,
            profile_sell_n=sell_n,
        )
        if buy_n > 0 and cap.buy_grid_capacity <= 0:
            fails.append(f"min_notional_buy_fail_{int(budget)}")
        if sell_n > 0 and cap.sell_grid_capacity <= 0:
            fails.append(f"min_notional_sell_fail_{int(budget)}")
        if buy_n > 0:
            quote_per = budget * quote_frac / max(cap.buy_grid_capacity, 1)
            if quote_per < min_notional * 0.99:
                fails.append(f"min_notional_buy_grid_{int(budget)}")
        if sell_n > 0:
            base_per = budget * base_frac / max(cap.sell_grid_capacity, 1)
            if base_per < min_notional * 0.99:
                fails.append(f"min_notional_sell_grid_{int(budget)}")
    return fails


def audit_exposure(profile: Dict[str, Any]) -> List[str]:
    max_exp = profile.get("max_base_exposure_frac")
    worst_raw = profile.get("worst_case_base_exposure_frac")
    if max_exp is None or worst_raw is None:
        return []
    max_exp_f = float(max_exp)
    worst = float(worst_raw)
    if worst > max_exp_f + 1e-6:
        return ["exposure_violation"]
    return []


def _sample_row(profile: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {
        "profile_id": str(profile.get("profile_id") or profile.get("template_key") or ""),
        "route_key": str(profile.get("route_key") or ""),
        "scenario": str(profile.get("scenario") or ""),
        "profile_type": profile_type_of(profile),
        **extra,
    }


def write_fail_sample_csvs(
    samples: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    mapping = {
        "schema_fail": "schema_fail_samples.csv",
        "ladder_null_fail": "ladder_null_fail_samples.csv",
        "fee_contradiction": "fee_contradiction_samples.csv",
        "min_notional_critical_fail": "min_notional_fail_samples.csv",
        "invalid_fallback": "invalid_fallback_samples.csv",
    }
    for key, fname in mapping.items():
        rows = samples.get(key) or []
        if not rows:
            continue
        path = output_dir / fname
        fieldnames: List[str] = []
        for row in rows:
            for k in row:
                if k not in fieldnames:
                    fieldnames.append(k)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written


def run_random_profile_logic_audit(
    templates: List[ParamTemplate],
    *,
    sample_size: int = 1000,
    seed: int = 20260626,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    pool = list(templates)
    if not pool:
        return {"pass": False, "error": "empty_pool", "sample_size": 0}
    sample = [pool[rng.randrange(len(pool))] for _ in range(min(sample_size, len(pool)))]

    report: Dict[str, Any] = {
        "sample_size": len(sample),
        "seed": seed,
        "profiles_total": len(pool),
        "schema_fail": 0,
        "route_key_fail": 0,
        "budget_in_route_fail": 0,
        "fee_in_route_fail": 0,
        "ladder_null_fail": 0,
        "intentional_empty_ladder": 0,
        "unexpected_ladder_null": 0,
        "distribution_fail": 0,
        "directional_critical_fail": 0,
        "trailing_fail": 0,
        "fee_contradiction": 0,
        "min_notional_critical_fail": 0,
        "exposure_violation": 0,
        "invalid_fallback": 0,
        "selection_trace_missing": 0,
        "zero_candidate_but_selected": 0,
        "fail_samples": {
            "schema_fail": [],
            "ladder_null_fail": [],
            "fee_contradiction": [],
            "min_notional_critical_fail": [],
            "invalid_fallback": [],
        },
    }

    for tmpl in sample:
        p = _profile_dict(tmpl)
        schema_rows = audit_library_profile_schema(p)
        if schema_rows:
            report["schema_fail"] += 1
            for row in schema_rows[:3]:
                report["fail_samples"]["schema_fail"].append(row)
            for row in schema_rows:
                reason = row.get("reason") or ""
                if reason == "route_key_fail":
                    report["route_key_fail"] += 1
                elif reason == "budget_in_route_fail":
                    report["budget_in_route_fail"] += 1
                elif reason == "fee_in_route_fail":
                    report["fee_in_route_fail"] += 1

        ladder_fails, intentional = audit_profile_ladders(p)
        if intentional:
            report["intentional_empty_ladder"] += 1
        elif ladder_fails:
            report["ladder_null_fail"] += 1
            report["unexpected_ladder_null"] += 1
            report["fail_samples"]["ladder_null_fail"].append(
                _sample_row(
                    p,
                    missing_field=";".join(ladder_fails),
                    ladder_class="unexpected_ladder_null",
                )
            )

        dist_fails = audit_profile_distribution(p)
        if dist_fails:
            report["distribution_fail"] += 1

        dir_fails = audit_directional_logic(p)
        if dir_fails:
            report["directional_critical_fail"] += 1

        trail_fails = audit_trailing(p)
        if trail_fails:
            report["trailing_fail"] += 1

        fee_fails = audit_fee_contradiction(p)
        if fee_fails:
            report["fee_contradiction"] += 1
            report["fail_samples"]["fee_contradiction"].append(
                _sample_row(p, invalid_field=";".join(fee_fails))
            )

        cap_fails = audit_capacity(p)
        if cap_fails:
            report["min_notional_critical_fail"] += 1
            report["fail_samples"]["min_notional_critical_fail"].append(
                _sample_row(p, invalid_field=";".join(cap_fails))
            )

        exp_fails = audit_exposure(p)
        if exp_fails:
            report["exposure_violation"] += 1

    pass_keys = (
        "schema_fail",
        "route_key_fail",
        "budget_in_route_fail",
        "fee_in_route_fail",
        "ladder_null_fail",
        "distribution_fail",
        "directional_critical_fail",
        "trailing_fail",
        "fee_contradiction",
        "min_notional_critical_fail",
        "exposure_violation",
        "invalid_fallback",
        "selection_trace_missing",
        "zero_candidate_but_selected",
    )
    report["pass"] = all(report[k] == 0 for k in pass_keys)
    return report


def _signature_regime_asset(sig: Dict[str, Any]) -> Tuple[str, str]:
    from_regime = _regime_from_route(str(sig.get("route_key") or "")) or str(
        sig.get("regime_code") or sig.get("regime") or ""
    )
    from_asset = _asset_from_route(str(sig.get("route_key") or "")) or str(
        sig.get("asset_code") or ""
    )
    return from_regime, from_asset


def _template_regime_asset(dps: Dict[str, Any]) -> Tuple[str, str]:
    to_regime = _regime_from_route(str(dps.get("route_key") or "")) or str(
        dps.get("regime_code") or dps.get("regime") or ""
    )
    to_asset = _asset_from_route(str(dps.get("route_key") or "")) or str(
        dps.get("asset_code") or ""
    )
    return to_regime, to_asset


def run_random_signature_selection_audit(
    templates: List[ParamTemplate],
    *,
    sample_size: int = 1000,
    seed: int = 20260626,
) -> Dict[str, Any]:
    from app.services.dynamic_param_score.param_pool.selector import select_template
    from app.services.dynamic_param_score.models import (
        IndicatorSnapshot,
        PortfolioState,
        RegimeTag,
        RiskState,
        SubScores,
    )

    prepare_v4_lazy_pool_for_selection()

    rng = random.Random(seed)
    report: Dict[str, Any] = {
        "sample_size": sample_size,
        "seed": seed,
        "invalid_route": 0,
        "invalid_fallback": 0,
        "zero_candidate_but_selected": 0,
        "directional_logic_fail": 0,
        "selection_trace_missing": 0,
        "pass": True,
        "fail_samples": {"invalid_fallback": []},
    }

    regimes = list(RegimeTag)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

    for i in range(sample_size):
        sig = market_signature_v4_from_live(
            symbol=symbols[i % len(symbols)],
            budget=rng.choice(BUDGETS),
            regime=rng.choice([r.value for r in regimes if r != RegimeTag.NO_DATA]),
            risk_level=rng.choice(["NORMAL", "DEFENSIVE", "CAUTION"]),
            volatility_percentile=rng.uniform(10, 90),
            lower_lows=rng.random() < 0.35,
            higher_highs=rng.random() < 0.35,
            fee_efficiency_score=int(rng.uniform(15, 85)),
            atr_1h_pct=rng.uniform(0.5, 3.0),
            spread_pct=rng.uniform(0, 0.08),
        )
        rk = normalize_route_key(str(sig.get("route_key") or ""))
        if not _route_key_valid(rk):
            report["invalid_route"] += 1
            continue

        sub = SubScores(
            trend_score=int(rng.uniform(20, 80)),
            volatility_score=int(sig.get("volatility_percentile") or 50),
            range_score=50,
            liquidity_score=int(rng.uniform(30, 90)),
            spread_score=int(rng.uniform(20, 90)),
            fee_efficiency_score=int(sig.get("fee_efficiency_score") or 50),
            exposure_safety_score=60,
            data_quality_score=80,
            btc_market_risk_score=55,
            drawdown_risk_score=50,
            mean_reversion_score=50,
        )
        ind = IndicatorSnapshot(
            orderbook_spread_pct=float(sig.get("spread_pct") or 0),
            atr14_pct_1h=float(sig.get("atr_1h_pct") or 1.0),
            lower_lows=bool(sig.get("lower_lows")),
            higher_highs=bool(sig.get("higher_highs")),
        )
        portfolio = PortfolioState(
            total_equity_usdt=float(sig.get("budget") or 100),
            quote_balance=float(sig.get("budget") or 100) * 0.55,
            quote_value_usdt=float(sig.get("budget") or 100) * 0.55,
            base_balance=0.0,
            base_value_usdt=float(sig.get("budget") or 100) * 0.45,
            current_base_exposure_frac=0.45,
        )
        constraints = ExchangeConstraints(
            min_notional=DEFAULT_MIN_NOTIONAL_USDT,
            step_size=0.001,
            tick_size=0.01,
            min_qty=0.001,
            taker_fee_pct=0.1,
            maker_fee_pct=0.1,
            estimated_slippage_pct=0.05,
        )

        try:
            regime = RegimeTag(sig.get("regime") or RegimeTag.BALANCED_RANGE.value)
        except ValueError:
            regime = RegimeTag.BALANCED_RANGE

        sel = select_template(
            param_score=int(rng.uniform(10, 85)),
            regime=regime,
            risk_state=RiskState.DEFENSIVE.value,
            sub=sub,
            ind=ind,
            portfolio=portfolio,
            constraints=constraints,
            budget_usdt=float(sig.get("budget") or 100),
            min_notional=DEFAULT_MIN_NOTIONAL_USDT,
            symbol=str(sig.get("symbol") or "ETHUSDT"),
        )
        ctx = sel.selection_context or {}
        trace_fields = (
            "exact_route_candidate_count",
            "scored_candidate_count",
            "route_key",
            "market_signature",
        )
        if any(ctx.get(f) is None for f in trace_fields):
            report["selection_trace_missing"] += 1

        if sel.template and ctx.get("route_index_fallback_used"):
            dps = (sel.template.params or {}).get("dps_profile") or {}
            sig_used = ctx.get("market_signature") or sig
            from_regime, from_asset = _signature_regime_asset(sig_used)
            to_regime, to_asset = _template_regime_asset(dps)
            if to_regime and from_regime and to_regime != from_regime:
                sig_rk = normalize_route_key(str(sig_used.get("route_key") or rk))
                sig_parts = sig_rk.split("|")
                to_parts = normalize_route_key(str(dps.get("route_key") or "")).split("|")
                if is_forbidden_fallback(
                    from_regime,
                    to_regime,
                    from_asset=from_asset,
                    to_asset=to_asset,
                    from_structure=sig_parts[2] if len(sig_parts) >= 5 else str(sig_used.get("structure_code") or ""),
                    to_structure=to_parts[2] if len(to_parts) >= 5 else str(dps.get("structure_code") or ""),
                    from_vol=sig_parts[3] if len(sig_parts) >= 5 else str(sig_used.get("vol_code") or ""),
                    to_vol=to_parts[3] if len(to_parts) >= 5 else str(dps.get("vol_code") or ""),
                ):
                    report["invalid_fallback"] += 1
                    report["fail_samples"]["invalid_fallback"].append(
                        {
                            "profile_id": sel.selected_template_key or "",
                            "route_key": str(dps.get("route_key") or ""),
                            "scenario": str(dps.get("scenario") or ""),
                            "profile_type": PROFILE_TYPE_LIBRARY,
                            "from_regime": from_regime,
                            "to_regime": to_regime,
                            "from_asset": from_asset,
                            "to_asset": to_asset,
                            "fallback_route": str(ctx.get("fallback_route") or ""),
                        }
                    )

        scored = int(ctx.get("scored_candidate_count") or sel.candidate_count or 0)
        has_profile = bool(sel.selected_template_key)
        runtime_safe = bool(ctx.get("runtime_safe_profile_generated"))
        if scored <= 0 and has_profile and not runtime_safe and not sel.fallback_used:
            report["zero_candidate_but_selected"] += 1

        if sel.template:
            p = _profile_dict(sel.template)
            if audit_directional_logic(p):
                report["directional_logic_fail"] += 1

    report["pass"] = (
        report["invalid_route"] == 0
        and report["invalid_fallback"] == 0
        and report["zero_candidate_but_selected"] == 0
        and report["directional_logic_fail"] == 0
        and report["selection_trace_missing"] == 0
    )
    return report


def load_v4_templates(profiles_path: Optional[str] = None) -> Tuple[List[ParamTemplate], Dict[str, Any]]:
    """Load full pool — prefer load_v4_templates_sampled for audits."""
    templates, meta = load_v4_templates_sampled(
        profiles_path, sample_size=None, seed=0, stratified=False
    )
    return templates, meta


def sample_v4_template_keys(
    *,
    sqlite_path: Path,
    index_path: Path,
    sample_size: int,
    seed: int,
    stratified: bool = True,
) -> Tuple[List[str], Dict[str, Any]]:
    """Pick template_key ids from route index without loading the full SQLite pool."""
    import json
    import random

    rng = random.Random(seed)
    meta: Dict[str, Any] = {
        "keys_sampled": sample_size,
        "seed": seed,
        "stratified": stratified,
        "index_path": str(index_path),
        "sqlite_path": str(sqlite_path),
    }

    if index_path.exists():
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        src = raw.get("index_by_route_key") or raw.get("route_index") or raw
        if isinstance(src, dict) and src:
            route_items = [(str(rk), list(ids)) for rk, ids in src.items() if ids]
            meta["routes_in_index"] = len(route_items)
            meta["profiles_in_index"] = sum(len(ids) for _, ids in route_items)

            keys: List[str] = []
            if stratified:
                rng.shuffle(route_items)
                per_route = max(1, (sample_size + len(route_items) - 1) // len(route_items))
                for _rk, ids in route_items:
                    if len(keys) >= sample_size:
                        break
                    picks = rng.sample(ids, min(per_route, len(ids)))
                    keys.extend(str(p) for p in picks)
            else:
                flat = [str(i) for _, ids in route_items for i in ids]
                keys = rng.sample(flat, min(sample_size, len(flat)))

            rng.shuffle(keys)
            keys = list(dict.fromkeys(keys))[:sample_size]
            meta["sample_method"] = "route_index_stratified" if stratified else "route_index_flat"
            meta["routes_touched"] = min(len(route_items), sample_size)
            return keys, meta

    if not sqlite_path.exists():
        return [], {**meta, "error": "no_index_or_sqlite"}

    import sqlite3

    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute(
            "SELECT template_key FROM param_templates WHERE status = 'active' "
            "ORDER BY RANDOM() LIMIT ?",
            (sample_size,),
        ).fetchall()
    finally:
        conn.close()
    keys = [str(r[0]) for r in rows if r and r[0]]
    meta["sample_method"] = "sqlite_random"
    return keys, meta


def load_v4_templates_sampled(
    profiles_path: Optional[str] = None,
    *,
    sample_size: Optional[int] = 1000,
    seed: int = 20260626,
    stratified: bool = True,
) -> Tuple[List[ParamTemplate], Dict[str, Any]]:
    """Load only sampled templates from live v4 library (no full-pool RAM load)."""
    import os
    from pathlib import Path

    from app.services.dynamic_param_score.param_pool.sqlite_store import (
        DEFAULT_V4_MANIFEST_PATH,
        DEFAULT_V4_SELECTION_INDEX_PATH,
        DEFAULT_V4_SQLITE_PATH,
        load_templates_by_keys,
    )
    from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
        FAST_TEST_POOL_TARGET_V4,
        POOL_TARGET_V4,
        build_dps_v4_pool,
    )

    sqlite_path = DEFAULT_V4_SQLITE_PATH
    index_path = DEFAULT_V4_SELECTION_INDEX_PATH
    manifest_path = DEFAULT_V4_MANIFEST_PATH

    if profiles_path:
        path = Path(profiles_path)
        if path.exists():
            if path.suffix == ".sqlite":
                sqlite_path = path
                index_path = path.parent / f"{path.stem}.selection_index.json"
                manifest_path = path.parent / f"{path.stem}.manifest.json"
            elif path.suffix == ".json" and "selection_index" in path.name:
                index_path = path
                sqlite_path = path.parent / path.name.replace(".selection_index.json", ".sqlite")
            elif path.parent.joinpath("param_pool_v4.sqlite").exists():
                sqlite_path = path.parent / "param_pool_v4.sqlite"
                index_path = path.parent / "param_pool_v4.selection_index.json"

    if sqlite_path.exists() and (sample_size is None or sample_size <= 0):
        from app.services.dynamic_param_score.param_pool.sqlite_store import load_templates_from_sqlite

        templates = load_templates_from_sqlite(sqlite_path, manifest_path=manifest_path)
        meta = {
            "source": str(sqlite_path),
            "count": len(templates),
            "profiles_total": POOL_TARGET_V4,
            "load_mode": "full_sqlite",
        }
        if manifest_path.exists():
            try:
                from app.services.dynamic_param_score.param_pool.manifest import read_manifest

                meta["profiles_total"] = int(read_manifest(manifest_path).template_count or POOL_TARGET_V4)
            except Exception:
                pass
        return templates, meta

    if sqlite_path.exists() and sample_size:
        keys, sample_meta = sample_v4_template_keys(
            sqlite_path=sqlite_path,
            index_path=index_path,
            sample_size=sample_size,
            seed=seed,
            stratified=stratified,
        )
        if keys:
            templates = load_templates_by_keys(
                sqlite_path, keys, manifest_path=manifest_path
            )
            profiles_total = POOL_TARGET_V4
            if manifest_path.exists():
                try:
                    from app.services.dynamic_param_score.param_pool.manifest import read_manifest

                    profiles_total = int(read_manifest(manifest_path).template_count or POOL_TARGET_V4)
                except Exception:
                    pass
            meta = {
                **sample_meta,
                "source": str(sqlite_path),
                "count": len(templates),
                "keys_requested": len(keys),
                "profiles_total": profiles_total,
                "load_mode": "sampled_by_route_index",
            }
            return templates, meta

    os.environ.setdefault("PARAM_POOL_VERSION", "v4.0.0")
    target = int(os.environ.get("DPS_AUDIT_POOL_SIZE", str(FAST_TEST_POOL_TARGET_V4)))
    templates = build_dps_v4_pool(total_target=target, migrate_v3=False)
    return templates, {
        "source": "build_dps_v4_pool",
        "count": len(templates),
        "target": target,
        "profiles_total": POOL_TARGET_V4,
        "load_mode": "programmatic_fallback",
    }


def prepare_v4_lazy_pool_for_selection() -> Dict[str, Any]:
    """Ensure signature-selection audit uses lazy route shelves, not full RAM pool."""
    import os

    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
    from app.services.dynamic_param_score.param_pool.sqlite_store import DEFAULT_V4_SQLITE_PATH
    from app.services.dynamic_param_score.param_pool.versioning import (
        _CACHED_INDEXED_POOLS,
        _CACHED_POOLS,
        clear_pool_cache,
        lazy_shelf_enabled,
    )

    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    os.environ.setdefault("PARAM_POOL_LAZY_SHELF", "1")
    clear_pool_cache()
    _CACHED_POOLS.clear()
    _CACHED_INDEXED_POOLS.clear()
    return {
        "pool_version": POOL_VERSION_V4,
        "lazy_shelf": lazy_shelf_enabled(POOL_VERSION_V4),
        "sqlite_path": str(DEFAULT_V4_SQLITE_PATH),
    }
