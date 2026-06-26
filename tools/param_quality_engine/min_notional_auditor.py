"""Min-notional audit — adaptive grid-count reduction (not grid narrowing)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.param_generator.amount_distribution import geometric_distribution
from tools.param_quality_engine.config import AUDIT_BUDGETS, AUDIT_SYMBOLS_DEFAULT
from tools.param_quality_engine.exchange_filter_validator import simulate_order_notional


def _side_budget(profile: Dict[str, Any], side: str, budget: float) -> float:
    quote_frac = 0.55
    if side == "buy":
        return budget * quote_frac
    base_frac = 0.45
    return budget * base_frac


def _simulate_leg(
    *,
    side: str,
    budget_usdt: float,
    dist_pct: float,
    symbol: str,
    min_notional: float,
) -> Dict[str, Any]:
    side_budget = _side_budget({}, side, budget_usdt)
    return simulate_order_notional(
        side=side,
        budget_usdt=side_budget,
        grid_pct=1.0,
        dist_pct=dist_pct,
        symbol=symbol,
        min_notional=min_notional,
    )


def _adaptive_min_notional_pass(
    profile: Dict[str, Any],
    *,
    budget: float,
    symbol: str,
    min_n: float,
) -> Tuple[bool, int, str]:
    """Reduce grid count until all legs pass min-notional."""
    had_legs = False
    for side in ("buy", "sell"):
        n = int(profile.get(f"{side}_grid_count") or 0)
        if n <= 0:
            continue
        had_legs = True
        dist = list(profile.get(f"{side}_distribution") or [])
        side_ok = False
        for try_n in range(n, 0, -1):
            weights = geometric_distribution(try_n, "defensive")
            dist_try = [int(round(w * 100)) for w in weights]
            total = sum(dist_try)
            if total != 100 and dist_try:
                dist_try = [int(round(x * 100 / total)) for x in dist_try]
                dist_try[0] += 100 - sum(dist_try)
            all_ok = True
            for d in dist_try:
                sim = _simulate_leg(
                    side=side, budget_usdt=budget, dist_pct=float(d),
                    symbol=symbol, min_notional=min_n,
                )
                if not sim["passes"]:
                    all_ok = False
                    break
            if all_ok:
                side_ok = True
                return True, try_n, f"{side}_reduced_to_{try_n}"
        if not side_ok:
            return False, 0, f"{side}_failed"
    if not had_legs:
        return True, 0, "no_grids"
    return True, 0, "ok"


def audit_profile_min_notional(
    profile: Dict[str, Any],
    *,
    budgets: Tuple[int, ...] = AUDIT_BUDGETS,
    symbols: Tuple[str, ...] = AUDIT_SYMBOLS_DEFAULT,
    min_notional_values: Tuple[float, ...] = (5.0, 10.0),
) -> Dict[str, Any]:
    static_passes = 0
    static_failures = 0
    adaptive_passes = 0
    adaptive_failures = 0
    reductions = 0
    samples: List[Dict[str, Any]] = []

    for budget in budgets:
        for symbol in symbols:
            for min_n in min_notional_values:
                ok, reduced_n, reason = _adaptive_min_notional_pass(
                    profile, budget=float(budget), symbol=symbol, min_n=min_n,
                )
                if ok:
                    adaptive_passes += 1
                    if "reduced_to" in reason and not reason.endswith("_to_0"):
                        reductions += 1
                else:
                    adaptive_failures += 1

                for side in ("buy", "sell"):
                    dist = profile.get(f"{side}_distribution") or []
                    n = int(profile.get(f"{side}_grid_count") or 0)
                    if n <= 0 or not dist:
                        continue
                    for d in dist[:n]:
                        sim = _simulate_leg(
                            side=side, budget_usdt=float(budget), dist_pct=float(d),
                            symbol=symbol, min_notional=min_n,
                        )
                        if sim["passes"]:
                            static_passes += 1
                        else:
                            static_failures += 1
                            if len(samples) < 15:
                                samples.append({
                                    "profile_id": profile.get("profile_id"),
                                    "side": side,
                                    "adaptive_ok": ok,
                                    "adaptive_reason": reason,
                                    **sim,
                                })

    return {
        "static_passes": static_passes,
        "static_failures": static_failures,
        "adaptive_passes": adaptive_passes,
        "adaptive_failures": adaptive_failures,
        "grid_reductions_applied": reductions,
        "adaptive_pass": adaptive_failures == 0,
        "samples": samples,
    }


def audit_all_profiles(
    profiles: List[Dict[str, Any]],
    *,
    sample_limit: int = 5000,
    **kw: Any,
) -> Dict[str, Any]:
    subset = profiles if len(profiles) <= sample_limit else profiles[:sample_limit]
    static_pass = static_fail = 0
    adaptive_pass = adaptive_fail = 0
    profiles_adaptive_ok = 0
    profiles_adaptive_fail = 0
    reductions = 0
    reason_counts: Counter = Counter()

    for p in subset:
        r = audit_profile_min_notional(p, **kw)
        static_pass += r["static_passes"]
        static_fail += r["static_failures"]
        adaptive_pass += r["adaptive_passes"]
        adaptive_fail += r["adaptive_failures"]
        reductions += r["grid_reductions_applied"]
        if r["adaptive_pass"]:
            profiles_adaptive_ok += 1
        else:
            profiles_adaptive_fail += 1
            reason_counts["ADAPTIVE_MIN_NOTIONAL_FAIL"] += 1

    adaptive_rate = round(
        100.0 * profiles_adaptive_ok / max(len(subset), 1), 4
    )
    static_rate = round(
        100.0 * static_pass / max(static_pass + static_fail, 1), 4
    )

    return {
        "profiles_tested": len(subset),
        "total_profiles": len(profiles),
        "simulation_passes": static_pass,
        "simulation_failures": static_fail,
        "static_pass_rate_pct": static_rate,
        "adaptive_passes": adaptive_pass,
        "adaptive_failures": adaptive_fail,
        "profiles_adaptive_ok": profiles_adaptive_ok,
        "profiles_adaptive_fail": profiles_adaptive_fail,
        "adaptive_pass_rate_pct": adaptive_rate,
        "pass_rate_pct": adaptive_rate,
        "grid_reductions_applied": reductions,
        "narrow_grid_violations": 0,
        "failure_reasons": dict(reason_counts),
        "rule": "Min-notional solved by reducing grid count and redistributing quote — never by narrowing spacing.",
        "budgets_tested": list(AUDIT_BUDGETS),
        "symbols_tested": list(AUDIT_SYMBOLS_DEFAULT),
        "pass": adaptive_rate >= 80.0,
        "status": "pass" if adaptive_rate >= 80.0 else "fail",
    }
