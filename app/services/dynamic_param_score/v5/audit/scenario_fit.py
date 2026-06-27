"""Scenario-fit scoring for V5 shelves — multi-axis with sub-score breakdown."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app.services.dynamic_param_score.v5.domain.math_utils import round2
from app.services.dynamic_param_score.v5.domain.route_key import compact_dimension_code
from app.services.dynamic_param_score.v5.domain.types import V5Shelf
from app.services.dynamic_param_score.v5.generator.grid_factory import is_two_grid_equal_allowed

CRITICAL_REGIMES = {
    "R8_CRASH",
    "R9_STRONG_DOWNTREND",
    "R10_LOWER_LOWS_DOWNTREND",
    "R12_CAPITULATION_REACTION",
    "R13_HIGH_VOL_DISORDER",
    "R14_LOW_LIQUIDITY_DRIFT",
    "R15_SPECIAL_STRESS_TRANSITION",
    "R17_DATA_UNCERTAIN_REGIME",
}
CRITICAL_STRUCTURES = {"S5_LOWER_LOWS", "S8_BREAKDOWN"}
CRITICAL_VOL = {"V5_SHOCK"}
CRITICAL_LIQ = {"L4_EXECUTION_RISKY"}

IDEAL_BASE_BY_RISK = {"K1_DEFENSIVE": 42.0, "K2_NORMAL_CONTROLLED": 52.0, "K3_AGGRESSIVE": 58.0}
IDEAL_GRID_LOW_VOL_MAX = 4.5
IDEAL_GRID_HIGH_VOL_MIN = 3.5


def is_critical_shelf(shelf: V5Shelf) -> bool:
    """High-attention shelves for scenario-fit reporting (excludes plain K1 alone)."""
    rp = shelf.route_parts
    return (
        rp.regime in CRITICAL_REGIMES
        or rp.structure in CRITICAL_STRUCTURES
        or rp.volatility in CRITICAL_VOL
        or rp.liquidity in CRITICAL_LIQ
        or rp.asset in ("A5_MEME_SPECULATIVE", "A6_LOW_LIQUIDITY_ALT")
    )


@dataclass
class ScenarioFitScore:
    total: float
    grid_fit: float
    distribution_fit: float
    base_quote_fit: float
    exposure_fit: float
    trailing_fit: float
    profit_cycle_fit: float
    execution_fit: float
    trace_fit: float
    deduction_notes: List[str] = field(default_factory=list)


def _weighted_total(parts: Dict[str, Tuple[float, float]]) -> float:
    return round2(sum(v * w for v, w in parts.values()))


def score_scenario_fit(shelf: V5Shelf) -> ScenarioFitScore:
    """Multi-axis scenario fit — valid shelves rarely score flat 100."""
    rp = shelf.route_parts
    t = shelf.base_template
    notes: List[str] = []
    min_grid = round2(t.assumed_cost_floor_pct + t.min_profit_after_cost_floor_pct)
    sell0 = t.sell_grid_levels_pct[0]
    buy0 = t.buy_grid_levels_pct[0]

    grid_fit = 100.0
    if sell0 < min_grid:
        grid_fit -= 35
        notes.append("sell_below_cost_floor")
    elif sell0 < min_grid * 1.08:
        grid_fit -= 8
        notes.append("sell_tight_vs_cost")
    if buy0 < min_grid:
        grid_fit -= 35
        notes.append("buy_below_cost_floor")
    elif buy0 < min_grid * 1.08:
        grid_fit -= 8
        notes.append("buy_tight_vs_cost")
    if rp.volatility in ("V1_ULTRA_LOW", "V2_LOW") and sell0 > IDEAL_GRID_LOW_VOL_MAX:
        grid_fit -= min(18, (sell0 - IDEAL_GRID_LOW_VOL_MAX) * 4)
        notes.append("low_vol_grid_wide")
    if rp.volatility in ("V4_HIGH", "V5_SHOCK") and sell0 < IDEAL_GRID_HIGH_VOL_MIN:
        grid_fit -= 22
        notes.append("high_vol_grid_narrow")
    if rp.regime in ("R8_CRASH", "R9_STRONG_DOWNTREND", "R10_LOWER_LOWS_DOWNTREND") and buy0 < sell0 * 1.02:
        grid_fit -= 20
        notes.append("downtrend_buy_not_deep")
    if rp.structure == "S2_RANGE_UPPER" and sell0 >= buy0:
        grid_fit -= 15
        notes.append("range_upper_sell_not_closer")

    distribution_fit = 100.0
    ctx = {
        "regime": rp.regime,
        "structure": rp.structure,
        "risk": rp.risk,
        "volatility": rp.volatility,
        "liquidity": rp.liquidity,
    }
    for side, dist in (("sell", t.sell_distribution_pct), ("buy", t.buy_distribution_pct)):
        if len(dist) == 3 and all(abs(v - 33.33) < 0.6 for v in dist):
            distribution_fit = 0
            notes.append(f"equal_3_grid_{side}")
        if len(dist) == 2 and abs(dist[0] - 50) < 0.6:
            if not (is_two_grid_equal_allowed(ctx) and t.equal_2_grid_justified):
                distribution_fit -= 25
                notes.append(f"unjustified_equal_2_{side}")
        if dist and dist[0] > 45 and rp.regime in CRITICAL_REGIMES:
            distribution_fit -= 12
            notes.append(f"front_heavy_{side}_stress_regime")

    ideal_base = IDEAL_BASE_BY_RISK.get(rp.risk, 50.0)
    base_quote_fit = 100.0 - min(30, abs(t.target_base_pct - ideal_base) * 1.2)
    if rp.risk == "K1_DEFENSIVE" and t.target_base_pct > 58:
        base_quote_fit -= 15
        notes.append("defensive_base_high")
    if abs(t.target_base_pct + t.target_quote_pct - 100) > 0.5:
        base_quote_fit -= 20
        notes.append("base_quote_not_100")

    exposure_fit = 100.0
    if t.max_base_exposure_pct < t.target_base_pct:
        gap = t.target_base_pct - t.max_base_exposure_pct
        if gap > 10:
            exposure_fit -= 25
            notes.append("max_below_target_large_gap")
        elif gap > 4:
            exposure_fit -= 12
            notes.append("max_below_target_moderate_gap")
        else:
            exposure_fit -= 5
            notes.append("max_below_target_conservative_cap")
    if rp.risk == "K1_DEFENSIVE" and t.max_base_exposure_pct > 52:
        exposure_fit -= min(25, (t.max_base_exposure_pct - 52) * 2)
        notes.append("defensive_max_exposure_high")
    if rp.regime == "R8_CRASH" and t.max_base_exposure_pct > 45:
        exposure_fit -= 20
        notes.append("crash_exposure_high")

    trailing_fit = 100.0
    if t.sell_trailing_pct > round2(sell0 * 0.30) + 0.01:
        trailing_fit -= 40
        notes.append("sell_trailing_over_cap")
    if t.buy_trailing_pct > round2(buy0 * 0.30) + 0.01:
        trailing_fit -= 40
        notes.append("buy_trailing_over_cap")

    profit_cycle_fit = 100.0
    if t.take_profit_sell_trigger_pct <= t.take_profit_sell_trailing_pct:
        profit_cycle_fit -= 30
        notes.append("sell_tp_order_bad")
    if t.take_profit_buy_trigger_pct <= t.take_profit_buy_trailing_pct:
        profit_cycle_fit -= 30
        notes.append("buy_tp_order_bad")
    if t.take_profit_sell_trigger_pct < min_grid + t.min_profit_after_cost_floor_pct:
        profit_cycle_fit -= 15
        notes.append("sell_tp_below_cost_floor")

    execution_fit = 100.0
    if rp.liquidity == "L4_EXECUTION_RISKY" and t.preferred_grid_count > 3:
        execution_fit -= 30
        notes.append("L4_too_many_grids")
    if rp.liquidity in ("L3_LOW_LIQUIDITY_HIGH_COST", "L4_EXECUTION_RISKY") and sell0 < min_grid * 1.05:
        execution_fit -= 18
        notes.append("low_liq_grid_tight")

    trace_fit = 100.0
    if not t.grid_reasoning:
        trace_fit -= 40
        notes.append("missing_grid_reasoning")
    if rp.regime == "R8_CRASH" and "R2_BALANCED_RANGE" not in shelf.fallback_policy.forbidden_fallbacks:
        trace_fit -= 35
        notes.append("R8_missing_R2_forbidden")

    total = _weighted_total(
        {
            "grid": (max(0, grid_fit), 0.18),
            "distribution": (max(0, distribution_fit), 0.16),
            "base_quote": (max(0, base_quote_fit), 0.16),
            "exposure": (max(0, exposure_fit), 0.18),
            "trailing": (max(0, trailing_fit), 0.10),
            "profit": (max(0, profit_cycle_fit), 0.08),
            "execution": (max(0, execution_fit), 0.10),
            "trace": (max(0, trace_fit), 0.04),
        }
    )

    return ScenarioFitScore(
        total=total,
        grid_fit=round2(max(0, grid_fit)),
        distribution_fit=round2(max(0, distribution_fit)),
        base_quote_fit=round2(max(0, base_quote_fit)),
        exposure_fit=round2(max(0, exposure_fit)),
        trailing_fit=round2(max(0, trailing_fit)),
        profit_cycle_fit=round2(max(0, profit_cycle_fit)),
        execution_fit=round2(max(0, execution_fit)),
        trace_fit=round2(max(0, trace_fit)),
        deduction_notes=notes,
    )


def compute_scenario_fit_score(shelf: V5Shelf) -> Tuple[float, List[str]]:
    sc = score_scenario_fit(shelf)
    return sc.total, sc.deduction_notes


@dataclass
class ScenarioFitAuditResult:
    total: int
    min_score: float
    avg_score: float
    p95_score: float
    p99_score: float
    below_85_count: int
    below_85_samples: List[str]
    critical_total: int
    critical_below_92_count: int
    critical_below_92_samples: List[str]
    sub_score_summary: Dict[str, Dict[str, float]]
    family_examples: List[dict]
    scoring_rules: List[str]
    pass_audit: bool

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "min_score": self.min_score,
            "avg_score": self.avg_score,
            "p95_score": self.p95_score,
            "p99_score": self.p99_score,
            "below_85_count": self.below_85_count,
            "below_85_samples": self.below_85_samples[:50],
            "critical_total": self.critical_total,
            "critical_below_92_count": self.critical_below_92_count,
            "critical_below_92_samples": self.critical_below_92_samples[:50],
            "sub_score_summary": self.sub_score_summary,
            "family_examples": self.family_examples,
            "scoring_rules": self.scoring_rules,
            "pass_audit": self.pass_audit,
        }


FAMILY_KEYS = [
    ("R3_low_vol", lambda s: compact_dimension_code(s.route_parts.regime) == "R3"),
    ("R8_crash", lambda s: compact_dimension_code(s.route_parts.regime) == "R8"),
    ("R15_stress", lambda s: compact_dimension_code(s.route_parts.regime) == "R15"),
    ("L4_execution", lambda s: compact_dimension_code(s.route_parts.liquidity) == "L4"),
    ("V5_shock", lambda s: compact_dimension_code(s.route_parts.volatility) == "V5"),
    ("K1_defensive", lambda s: compact_dimension_code(s.route_parts.risk) == "K1"),
]


SCORING_RULES = [
    "grid_fit: cost floor margin, vol/regime grid width, structure direction",
    "distribution_fit: no equal-3; equal-2 only when justified; front-heavy penalty in stress",
    "base_quote_fit: distance from risk-ideal base; sum=100",
    "exposure_fit: max vs target; defensive/crash caps",
    "trailing_fit: trailing <= first_grid * 0.30",
    "profit_cycle_fit: TP trigger > trailing; TP above cost floor",
    "execution_fit: L4 grid count; low-liq min grid margin",
    "trace_fit: grid_reasoning required; R8 forbids R2 fallback",
    "total: weighted average (grid 18%, distribution 16%, base_quote 16%, exposure 18%, trailing 10%, profit 8%, execution 10%, trace 4%)",
    "critical_below_92: informational metric on high-attention routes; hard gate is below_85 only",
]


def audit_scenario_fit(shelves: List[V5Shelf]) -> ScenarioFitAuditResult:
    scores: List[float] = []
    below_85: List[str] = []
    critical_below_92: List[str] = []
    sub_axes = [
        "grid_fit",
        "distribution_fit",
        "base_quote_fit",
        "exposure_fit",
        "trailing_fit",
        "profit_cycle_fit",
        "execution_fit",
        "trace_fit",
    ]
    sub_values: Dict[str, List[float]] = {k: [] for k in sub_axes}
    family_examples: List[dict] = []

    for shelf in shelves:
        sc = score_scenario_fit(shelf)
        scores.append(sc.total)
        for axis in sub_axes:
            sub_values[axis].append(getattr(sc, axis))
        if sc.total < 85:
            below_85.append(f"{shelf.shelf_id}:{sc.total}")
        if is_critical_shelf(shelf) and sc.total < 92:
            critical_below_92.append(f"{shelf.shelf_id}:{sc.total}")

    for label, pred in FAMILY_KEYS:
        sample = next((s for s in shelves if pred(s)), None)
        if sample:
            sc = score_scenario_fit(sample)
            family_examples.append(
                {
                    "family": label,
                    "route_key": sample.route_key,
                    "shelf_id": sample.shelf_id,
                    "total": sc.total,
                    "grid_fit": sc.grid_fit,
                    "distribution_fit": sc.distribution_fit,
                    "base_quote_fit": sc.base_quote_fit,
                    "exposure_fit": sc.exposure_fit,
                    "execution_fit": sc.execution_fit,
                    "trace_fit": sc.trace_fit,
                    "notes": sc.deduction_notes[:8],
                }
            )

    scores_sorted = sorted(scores)
    n = len(scores_sorted)

    def pct(p: float) -> float:
        idx = min(n - 1, int(n * p))
        return scores_sorted[idx]

    def sub_summary(axis: str) -> Dict[str, float]:
        vals = sorted(sub_values[axis])
        if not vals:
            return {}
        return {
            "min": round2(vals[0]),
            "avg": round2(sum(vals) / len(vals)),
            "p95": round2(vals[min(len(vals) - 1, int(len(vals) * 0.95))]),
        }

    critical_total = sum(1 for s in shelves if is_critical_shelf(s))

    return ScenarioFitAuditResult(
        total=n,
        min_score=round2(min(scores)),
        avg_score=round2(sum(scores) / n),
        p95_score=round2(pct(0.95)),
        p99_score=round2(pct(0.99)),
        below_85_count=len(below_85),
        below_85_samples=below_85,
        critical_total=critical_total,
        critical_below_92_count=len(critical_below_92),
        critical_below_92_samples=critical_below_92,
        sub_score_summary={axis: sub_summary(axis) for axis in sub_axes},
        family_examples=family_examples,
        scoring_rules=SCORING_RULES,
        pass_audit=len(below_85) == 0,
    )
