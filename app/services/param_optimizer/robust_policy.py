"""
Regime-forecasted robust policy contract for the parameter optimizer.

This module is intentionally small and dependency-free. It does not pretend to
be a full HMM/GARCH implementation yet; instead it codifies the hard guarantees
from the design spec:

* the only trusted forecast is one that beats a baseline out of sample,
* failed skill falls back to climatology,
* bot params are generated from state/volatility policy rules,
* deployment has an explicit deploy / do-not-deploy gate.

The expensive pieces (Student-t HMM, GJR-GARCH, CSCV/PBO) can replace the light
estimators here without changing the output contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.param_optimizer.indicators import HistoryFeatures


REGIMES: List[str] = [
    "LOW_VOL_RANGING",
    "HIGH_VOL_RANGING",
    "TRENDING_UP",
    "TRENDING_DOWN",
    "SQUEEZE",
    "BREAKOUT",
    "DUMP_RISK",
    "UNKNOWN",
]

DEFENSIVE_REGIMES = {"TRENDING_DOWN", "DUMP_RISK", "HIGH_VOL_RANGING"}
TREND_REGIMES = {"TRENDING_UP", "BREAKOUT"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _normalize(probs: Mapping[str, float]) -> Dict[str, float]:
    out = {r: max(0.0, _safe_float(probs.get(r, 0.0))) for r in REGIMES}
    total = sum(out.values())
    if total <= 0:
        return {r: 1.0 / len(REGIMES) for r in REGIMES}
    return {r: v / total for r, v in out.items()}


def climatology_from_labels(labels: Sequence[str]) -> Dict[str, float]:
    """Empirical regime frequency distribution."""
    if not labels:
        return {r: 1.0 / len(REGIMES) for r in REGIMES}
    counts = {r: 1.0 for r in REGIMES}  # light Laplace smoothing
    for label in labels:
        counts[label if label in counts else "UNKNOWN"] += 1.0
    return _normalize(counts)


def default_transition_matrix(persistence: float = 0.78) -> Dict[str, Dict[str, float]]:
    """Simple Markov transition matrix with regime persistence."""
    persistence = _clamp(persistence, 0.05, 0.98)
    spill = (1.0 - persistence) / (len(REGIMES) - 1)
    matrix: Dict[str, Dict[str, float]] = {}
    for src in REGIMES:
        row = {dst: spill for dst in REGIMES}
        row[src] = persistence
        matrix[src] = _normalize(row)
    return matrix


def markov_forward(
    gamma_t: Mapping[str, float],
    transition: Mapping[str, Mapping[str, float]],
    horizon_steps: int,
) -> List[Dict[str, float]]:
    """Compute pi_{T+h} = gamma_T * P^h for h=1..horizon_steps."""
    current = _normalize(gamma_t)
    out: List[Dict[str, float]] = []
    for _ in range(max(0, int(horizon_steps))):
        nxt = {r: 0.0 for r in REGIMES}
        for src, p_src in current.items():
            row = _normalize(transition.get(src, {}))
            for dst, p_dst in row.items():
                nxt[dst] += p_src * p_dst
        current = _normalize(nxt)
        out.append(current)
    return out


def multiclass_log_loss(
    probs: Sequence[Mapping[str, float]],
    actuals: Sequence[str],
    *,
    eps: float = 1e-12,
) -> float:
    """Average multiclass log-loss."""
    n = min(len(probs), len(actuals))
    if n <= 0:
        return float("inf")
    total = 0.0
    for i in range(n):
        p = _normalize(probs[i])
        y = actuals[i] if actuals[i] in REGIMES else "UNKNOWN"
        total -= math.log(max(eps, p.get(y, 0.0)))
    return total / n


@dataclass
class ForecastSkill:
    model_log_loss: float
    baseline_log_loss: float
    skill_score: float
    passed: bool
    fallback_used: bool
    baseline_name: str = "climatology"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_log_loss": round(self.model_log_loss, 6)
            if math.isfinite(self.model_log_loss)
            else None,
            "baseline_log_loss": round(self.baseline_log_loss, 6)
            if math.isfinite(self.baseline_log_loss)
            else None,
            "skill_score": round(self.skill_score, 6)
            if math.isfinite(self.skill_score)
            else None,
            "passed": self.passed,
            "fallback_used": self.fallback_used,
            "baseline_name": self.baseline_name,
            "reason": self.reason,
        }


def forecast_skill_gate(
    model_probs: Sequence[Mapping[str, float]],
    actuals: Sequence[str],
    baseline_probs: Sequence[Mapping[str, float]],
    *,
    min_skill: float = 0.0,
    baseline_name: str = "climatology",
) -> ForecastSkill:
    """OOS skill gate: SS = 1 - L_model / L_baseline."""
    model_loss = multiclass_log_loss(model_probs, actuals)
    base_loss = multiclass_log_loss(baseline_probs, actuals)
    if not math.isfinite(model_loss) or not math.isfinite(base_loss) or base_loss <= 0:
        return ForecastSkill(
            model_loss,
            base_loss,
            float("-inf"),
            False,
            True,
            baseline_name,
            "invalid_oos_skill",
        )
    ss = 1.0 - model_loss / base_loss
    passed = ss > min_skill
    return ForecastSkill(
        model_loss,
        base_loss,
        ss,
        passed,
        not passed,
        baseline_name,
        "model_beats_baseline" if passed else "fallback_to_climatology",
    )


@dataclass
class RobustForecast:
    horizon_steps: int
    regime_probs: List[Dict[str, float]]
    vol_term_pct: List[float]
    skill: ForecastSkill
    climatology: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_steps": self.horizon_steps,
            "regime_probs": [
                {k: round(v, 6) for k, v in row.items()} for row in self.regime_probs
            ],
            "vol_term_pct": [round(v, 6) for v in self.vol_term_pct],
            "skill": self.skill.to_dict(),
            "climatology": {k: round(v, 6) for k, v in self.climatology.items()},
        }


def _current_gamma(features: HistoryFeatures, climatology: Mapping[str, float]) -> Dict[str, float]:
    regime = features.regime_code if features.regime_code in REGIMES else "UNKNOWN"
    base = {r: 0.20 * climatology.get(r, 0.0) for r in REGIMES}
    confidence = _clamp(_safe_float(getattr(features, "confidence", 50.0), 50.0) / 100.0, 0.25, 0.9)
    base[regime] += confidence
    return _normalize(base)


def build_robust_forecast(
    features: HistoryFeatures,
    *,
    skill: Optional[ForecastSkill] = None,
    regime_labels: Optional[Sequence[str]] = None,
    horizon_steps: int = 6,
    transition: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> RobustForecast:
    """Build the calibrated forecast contract with skill-gated fallback."""
    climatology = climatology_from_labels(regime_labels or [])
    if skill is None:
        # No OOS proof means no model authority. This is deliberately conservative.
        skill = ForecastSkill(
            model_log_loss=float("inf"),
            baseline_log_loss=float("inf"),
            skill_score=0.0,
            passed=False,
            fallback_used=True,
            reason="no_oos_skill_provided",
        )
    gamma = _current_gamma(features, climatology) if skill.passed else climatology
    matrix = transition or default_transition_matrix()
    regime_probs = markov_forward(gamma, matrix, horizon_steps)

    current_vol = max(
        0.1,
        _safe_float(getattr(features, "atr_pct", None), 0.0)
        or _safe_float(getattr(features, "realized_vol_pct", None), 0.0)
        or _safe_float(getattr(features, "daily_range_med_pct", None), 1.0),
    )
    long_vol = max(
        0.1,
        _safe_float(getattr(features, "daily_range_med_pct", None), current_vol),
        current_vol * 0.65,
    )
    persistence = 0.72
    vol_term = [
        max(0.1, long_vol + (current_vol - long_vol) * (persistence ** h))
        for h in range(1, horizon_steps + 1)
    ]
    return RobustForecast(horizon_steps, regime_probs, vol_term, skill, climatology)


@dataclass
class PolicyState:
    regime: str
    base_alloc_pct: float
    quote_alloc_pct: float
    grid_step_pct: float
    trailing_pct: float
    profit_exit_rise_pct: float
    profit_reentry_drop_pct: float
    max_inventory_pct: float
    position_scale: float
    structure: str
    kill_switch: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "base_alloc_pct": round(self.base_alloc_pct, 4),
            "quote_alloc_pct": round(self.quote_alloc_pct, 4),
            "grid_step_pct": round(self.grid_step_pct, 4),
            "trailing_pct": round(self.trailing_pct, 4),
            "profit_exit_rise_pct": round(self.profit_exit_rise_pct, 4),
            "profit_reentry_drop_pct": round(self.profit_reentry_drop_pct, 4),
            "max_inventory_pct": round(self.max_inventory_pct, 4),
            "position_scale": round(self.position_scale, 4),
            "structure": self.structure,
            "kill_switch": {k: round(v, 4) for k, v in self.kill_switch.items()},
        }


def fee_floor_step_pct(fee_rate: float, slippage_bps: float = 0.0, kappa: float = 2.0) -> float:
    """Approximate g_floor = kappa * 2(f+s)/(1-f) in percent."""
    f = max(0.0, _safe_float(fee_rate))
    s = max(0.0, _safe_float(slippage_bps)) / 10_000.0
    denom = max(1e-9, 1.0 - f)
    return kappa * 2.0 * (f + s) / denom * 100.0


def build_state_policy(
    forecast: RobustForecast,
    features: HistoryFeatures,
    *,
    fee_rate: float = 0.001,
    slippage_bps: float = 2.0,
) -> Dict[str, PolicyState]:
    """Generate state -> parameter policy from forecast volatility."""
    sigma = forecast.vol_term_pct[0] if forecast.vol_term_pct else max(0.6, features.atr_pct)
    floor = fee_floor_step_pct(fee_rate, slippage_bps)
    states: Dict[str, PolicyState] = {}
    for regime in REGIMES:
        vol_mult = 1.0
        alloc = 50.0 + _safe_float(features.trend_score, 0.0) * 10.0
        structure = "symmetric_moving_anchor_inventory_cap_dd_stop"
        scale = 1.0
        inventory_cap = 70.0
        if regime in DEFENSIVE_REGIMES:
            vol_mult = 1.35 if regime != "DUMP_RISK" else 1.75
            alloc = min(38.0, alloc)
            scale = 0.55 if regime == "DUMP_RISK" else 0.75
            inventory_cap = 45.0
        elif regime in TREND_REGIMES:
            vol_mult = 1.15
            alloc = max(55.0, alloc)
            inventory_cap = 78.0
            structure = "drift_tilted_moving_anchor_inventory_cap_dd_stop"
        elif regime == "SQUEEZE":
            vol_mult = 0.9
            scale = 0.85
        elif regime == "LOW_VOL_RANGING":
            vol_mult = 0.85
        step = max(floor, sigma * vol_mult)
        trail = _clamp(step * 0.42, 0.20, 4.0)
        alloc = _clamp(alloc, 20.0, 70.0)
        states[regime] = PolicyState(
            regime=regime,
            base_alloc_pct=alloc,
            quote_alloc_pct=100.0 - alloc,
            grid_step_pct=step,
            trailing_pct=trail,
            profit_exit_rise_pct=max(floor, step * 1.45),
            profit_reentry_drop_pct=max(floor, step * 1.25),
            max_inventory_pct=inventory_cap,
            position_scale=scale,
            structure=structure,
            kill_switch={
                "soft_dd_pct": 15.0,
                "hard_dd_pct": 25.0,
                "vol_band_multiplier": 1.8,
            },
        )
    return states


def cvar(values: Sequence[float], beta: float = 0.05) -> float:
    """Left-tail expected value at beta."""
    xs = sorted(_safe_float(v) for v in values if math.isfinite(_safe_float(v)))
    if not xs:
        return 0.0
    n_tail = max(1, int(math.ceil(len(xs) * _clamp(beta, 0.001, 1.0))))
    return sum(xs[:n_tail]) / n_tail


def robust_objective(returns: Sequence[float], lambda_cvar: float = 0.65) -> float:
    """J = E[R] - lambda * (-CVaR_5)."""
    xs = [_safe_float(v) for v in returns if math.isfinite(_safe_float(v))]
    if not xs:
        return float("-inf")
    mean_r = sum(xs) / len(xs)
    left_tail = cvar(xs, 0.05)
    return mean_r - max(0.0, lambda_cvar) * max(0.0, -left_tail)


@dataclass
class DeployGate:
    deploy: bool
    reasons: List[str]
    checks: Dict[str, bool]

    def to_dict(self) -> Dict[str, Any]:
        return {"deploy": self.deploy, "reasons": self.reasons, "checks": self.checks}


def deploy_gate(
    *,
    skill: ForecastSkill,
    oos: Optional[Mapping[str, Any]] = None,
    walk_forward: Optional[Mapping[str, Any]] = None,
    pbo: Optional[float] = None,
    deflated_sharpe_ok: Optional[bool] = None,
    stress_ok: Optional[bool] = None,
    plateau_ok: Optional[bool] = None,
) -> DeployGate:
    """Hard deploy / do-not-deploy decision."""
    checks: Dict[str, bool] = {
        "forecast_skill_positive": bool(skill.passed and skill.skill_score > 0.0),
    }
    oos_ret = None if not oos else oos.get("return_pct")
    checks["oos_positive"] = oos_ret is not None and _safe_float(oos_ret) > 0.0
    if walk_forward:
        checks["walk_forward_consistent"] = (
            _safe_float(walk_forward.get("frac_profitable")) >= 0.55
            and int(walk_forward.get("total_cycles") or 0) >= 10
        )
    else:
        checks["walk_forward_consistent"] = False
    checks["pbo_ok"] = pbo is not None and _safe_float(pbo, 1.0) < 0.5
    checks["deflated_sharpe_ok"] = bool(deflated_sharpe_ok)
    checks["stress_ok"] = bool(stress_ok)
    checks["plateau_ok"] = bool(plateau_ok)

    reasons = [name for name, ok in checks.items() if not ok]
    return DeployGate(not reasons, reasons, checks)


def build_robust_policy_report(
    features: HistoryFeatures,
    result: Mapping[str, Any],
    *,
    fee_rate: float = 0.001,
    slippage_bps: float = 2.0,
    horizon_steps: int = 6,
) -> Dict[str, Any]:
    """Attach the robust-policy contract to the existing optimizer result."""
    forecast_dict = result.get("forecast") or {}
    # Existing MC is not a calibrated regime classifier, so it cannot pass the
    # forecast skill gate by itself. If a future nested WF classifier supplies
    # robust_skill, this function will honor it.
    raw_skill = result.get("robust_skill") or {}
    skill = ForecastSkill(
        model_log_loss=_safe_float(raw_skill.get("model_log_loss"), float("inf")),
        baseline_log_loss=_safe_float(raw_skill.get("baseline_log_loss"), float("inf")),
        skill_score=_safe_float(raw_skill.get("skill_score"), 0.0),
        passed=bool(raw_skill.get("passed")),
        fallback_used=not bool(raw_skill.get("passed")),
        baseline_name=str(raw_skill.get("baseline_name") or "climatology"),
        reason=str(raw_skill.get("reason") or "no_nested_oos_regime_skill"),
    )
    if not skill.passed:
        skill.fallback_used = True

    labels: List[str] = []
    code = features.regime_code if features.regime_code in REGIMES else "UNKNOWN"
    labels.append(code)
    robust_forecast = build_robust_forecast(
        features,
        skill=skill,
        regime_labels=labels,
        horizon_steps=horizon_steps,
    )
    policy = build_state_policy(
        robust_forecast,
        features,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
    )
    gate = deploy_gate(
        skill=robust_forecast.skill,
        oos=result.get("oos_result"),
        walk_forward=result.get("walk_forward"),
        pbo=result.get("pbo"),
        deflated_sharpe_ok=result.get("deflated_sharpe_ok"),
        stress_ok=forecast_dict.get("p05_return_pct") is not None
        and _safe_float(forecast_dict.get("p05_return_pct")) > -20.0,
        plateau_ok=result.get("plateau_ok"),
    )
    return {
        "contract_version": 1,
        "forecast": robust_forecast.to_dict(),
        "policy": {k: v.to_dict() for k, v in policy.items()},
        "deploy_gate": gate.to_dict(),
        "notes": [
            "trusted_metric_is_outer_walk_forward_oos",
            "skill_gate_falls_back_to_climatology_when_ss_non_positive",
            "output_is_state_to_parameter_policy_not_single_param_set",
        ],
    }
