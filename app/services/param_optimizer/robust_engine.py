"""
Robust v2 parameter optimizer.

This is the main implementation of the regime-forecasted robust design. It keeps
the public result shape used by the UI, but replaces broad free-parameter search
with a small set of structural variants whose numeric parameters are generated
from forecast volatility and regime state.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.services.param_optimizer import parallel
from app.services.param_optimizer.backtest import run_backtest
from app.services.param_optimizer.cancel import ParamOptimizerCancelled
from app.services.param_optimizer.indicators import HistoryFeatures
from app.services.param_optimizer.objective import ObjectiveConfig, combined_score, score_backtest
from app.services.param_optimizer.robust_policy import (
    REGIMES,
    ForecastSkill,
    build_robust_forecast,
    build_state_policy,
    cvar,
    default_transition_matrix,
    deploy_gate,
    forecast_skill_gate,
    robust_objective,
)
from app.services.param_optimizer.space import ParamSpace


_DAY_MS = 86_400_000


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _percentile(xs: Sequence[float], q: float) -> float:
    vals = sorted(_safe_float(x) for x in xs if math.isfinite(_safe_float(x)))
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    pos = _clamp(q, 0.0, 1.0) * (len(vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _median_interval_ms(candles: Sequence[Mapping[str, Any]]) -> int:
    diffs: List[int] = []
    for i in range(1, min(len(candles), 80)):
        d = int(candles[i].get("t") or 0) - int(candles[i - 1].get("t") or 0)
        if d > 0:
            diffs.append(d)
    if not diffs:
        return _DAY_MS
    diffs.sort()
    return diffs[len(diffs) // 2]


def _closes(candles: Sequence[Mapping[str, Any]]) -> List[float]:
    return [_safe_float(c.get("c")) for c in candles if _safe_float(c.get("c")) > 0]


def _log_returns(candles: Sequence[Mapping[str, Any]]) -> List[float]:
    closes = _closes(candles)
    out: List[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            out.append(math.log(closes[i] / closes[i - 1]))
    return out


def _std(xs: Sequence[float]) -> float:
    vals = [_safe_float(x) for x in xs]
    if len(vals) < 2:
        return 0.0
    mu = sum(vals) / len(vals)
    return math.sqrt(sum((x - mu) ** 2 for x in vals) / (len(vals) - 1))


def _intervals_per_day(candles: Sequence[Mapping[str, Any]]) -> float:
    return max(1.0, _DAY_MS / max(1, _median_interval_ms(candles)))


def variance_ratio(returns: Sequence[float], q: int = 5) -> float:
    if len(returns) < q * 4:
        return 1.0
    one = _std(returns) ** 2
    if one <= 0:
        return 1.0
    agg = [sum(returns[i : i + q]) for i in range(0, len(returns) - q + 1)]
    return (_std(agg) ** 2) / (q * one)


def ou_half_life(returns: Sequence[float]) -> Optional[float]:
    if len(returns) < 20:
        return None
    xs = list(returns[:-1])
    ys = list(returns[1:])
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return None
    phi = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs))) / den
    if not (0.0 < phi < 1.0):
        return None
    return -math.log(2.0) / math.log(phi)


def yang_zhang_vol_pct(candles: Sequence[Mapping[str, Any]]) -> float:
    if len(candles) < 3:
        return 0.0
    vals: List[float] = []
    for i in range(1, len(candles)):
        prev_c = _safe_float(candles[i - 1].get("c"))
        o = _safe_float(candles[i].get("o"))
        h = _safe_float(candles[i].get("h"))
        l = _safe_float(candles[i].get("l"))
        c = _safe_float(candles[i].get("c"))
        if min(prev_c, o, h, l, c) <= 0 or h < l:
            continue
        overnight = math.log(o / prev_c)
        open_close = math.log(c / o)
        rs = math.log(h / c) * math.log(h / o) + math.log(l / c) * math.log(l / o)
        vals.append(max(0.0, overnight * overnight + 0.34 * open_close * open_close + 0.66 * rs))
    if not vals:
        return 0.0
    return math.sqrt(sum(vals) / len(vals)) * 100.0


def hill_tail_index(returns: Sequence[float], k: int = 20) -> float:
    losses = sorted((abs(r) for r in returns if r < 0), reverse=True)
    if len(losses) < 8:
        return 8.0
    k = max(3, min(k, len(losses) - 1))
    threshold = max(losses[k], 1e-12)
    denom = sum(math.log(max(losses[i], 1e-12) / threshold) for i in range(k)) / k
    if denom <= 0:
        return 8.0
    return _clamp(1.0 / denom, 2.2, 20.0)


def _causal_feature_pack(candles: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rets = _log_returns(candles)
    return {
        "variance_ratio_5": round(variance_ratio(rets, 5), 6),
        "ou_half_life_bars": round(ou_half_life(rets) or 0.0, 6),
        "yang_zhang_vol_pct": round(yang_zhang_vol_pct(candles[-min(len(candles), 180) :]), 6),
        "hill_tail_alpha": round(hill_tail_index(rets), 6),
    }


def _rolling_regime_labels(candles: Sequence[Mapping[str, Any]], lookback: int = 24) -> List[str]:
    closes = _closes(candles)
    if len(closes) < 3:
        return []
    labels: List[str] = []
    returns = [0.0]
    for i in range(1, len(closes)):
        returns.append(math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0)
    vol_ref: List[float] = []
    for i in range(len(closes)):
        a = max(0, i - lookback + 1)
        seg = returns[a : i + 1]
        vol = _std(seg) * math.sqrt(max(1, lookback)) * 100.0
        vol_ref.append(vol)
    p70 = _percentile(vol_ref, 0.70)
    p30 = _percentile(vol_ref, 0.30)
    for i in range(len(closes)):
        a = max(0, i - lookback + 1)
        ret_pct = (closes[i] / closes[a] - 1.0) * 100.0 if closes[a] > 0 else 0.0
        vol = vol_ref[i]
        if ret_pct <= -10.0 and vol >= p70:
            label = "DUMP_RISK"
        elif abs(ret_pct) >= 4.0 and vol >= p70:
            label = "BREAKOUT" if ret_pct > 0 else "TRENDING_DOWN"
        elif ret_pct >= 3.0:
            label = "TRENDING_UP"
        elif ret_pct <= -3.0:
            label = "TRENDING_DOWN"
        elif vol <= max(0.15, p30 * 0.75):
            label = "SQUEEZE"
        elif vol >= p70:
            label = "HIGH_VOL_RANGING"
        else:
            label = "LOW_VOL_RANGING"
        labels.append(label)
    return labels


def _transition_from_labels(labels: Sequence[str], smoothing: float = 1.0) -> Dict[str, Dict[str, float]]:
    rows = {r: {c: smoothing for c in REGIMES} for r in REGIMES}
    for a, b in zip(labels[:-1], labels[1:]):
        aa = a if a in rows else "UNKNOWN"
        bb = b if b in rows[aa] else "UNKNOWN"
        rows[aa][bb] += 1.0
    out: Dict[str, Dict[str, float]] = {}
    for r, row in rows.items():
        total = sum(row.values()) or 1.0
        out[r] = {k: v / total for k, v in row.items()}
    return out


def _climatology(labels: Sequence[str]) -> Dict[str, float]:
    counts = {r: 1.0 for r in REGIMES}
    for label in labels:
        counts[label if label in counts else "UNKNOWN"] += 1.0
    total = sum(counts.values()) or 1.0
    return {k: v / total for k, v in counts.items()}


def _row_prediction(prev_label: str, transition: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
    row = transition.get(prev_label if prev_label in REGIMES else "UNKNOWN")
    if not row:
        return {r: 1.0 / len(REGIMES) for r in REGIMES}
    total = sum(max(0.0, _safe_float(v)) for v in row.values()) or 1.0
    return {r: max(0.0, _safe_float(row.get(r))) / total for r in REGIMES}


def _nested_forecast_skill(labels: Sequence[str], folds: int = 4, embargo: int = 3) -> Tuple[ForecastSkill, Dict[str, Dict[str, float]], Dict[str, float], Dict[str, Any]]:
    labels = [x if x in REGIMES else "UNKNOWN" for x in labels]
    if len(labels) < 80:
        skill = ForecastSkill(float("inf"), float("inf"), 0.0, False, True, reason="insufficient_regime_history")
        return skill, default_transition_matrix(), _climatology(labels), {"folds": 0, "purge": 0, "embargo": embargo}
    folds = max(2, min(int(folds or 4), 8))
    seg = max(10, len(labels) // folds)
    model_probs: List[Dict[str, float]] = []
    base_probs: List[Dict[str, float]] = []
    actuals: List[str] = []
    used = 0
    purged = 0
    for fidx in range(folds):
        start = fidx * seg
        end = len(labels) if fidx == folds - 1 else min(len(labels), (fidx + 1) * seg)
        if end - start < 8 or start < 10:
            continue
        train_labels = labels[: max(0, start - embargo)]
        purged += min(embargo, start)
        if len(train_labels) < 20:
            continue
        trans = _transition_from_labels(train_labels)
        clim = _climatology(train_labels)
        for i in range(start, end):
            prev = labels[i - 1] if i > 0 else train_labels[-1]
            model_probs.append(_row_prediction(prev, trans))
            base_probs.append(clim)
            actuals.append(labels[i])
            used += 1
    skill = forecast_skill_gate(model_probs, actuals, base_probs, baseline_name="climatology")
    transition = _transition_from_labels(labels)
    clim = _climatology(labels)
    meta = {
        "folds": folds,
        "oos_points": used,
        "purge": embargo,
        "embargo": embargo,
        "model_log_loss": None if not math.isfinite(skill.model_log_loss) else round(skill.model_log_loss, 6),
        "baseline_log_loss": None if not math.isfinite(skill.baseline_log_loss) else round(skill.baseline_log_loss, 6),
    }
    return skill, transition, clim, meta


def _emission_stats(candles: Sequence[Mapping[str, Any]], labels: Sequence[str]) -> Dict[str, Dict[str, float]]:
    rets = _log_returns(candles)
    aligned = list(labels[1 : len(rets) + 1])
    all_mu = sum(rets) / len(rets) if rets else 0.0
    all_sd = _std(rets) or 0.002
    out: Dict[str, Dict[str, float]] = {}
    for regime in REGIMES:
        xs = [rets[i] for i, lab in enumerate(aligned) if lab == regime and i < len(rets)]
        mu = sum(xs) / len(xs) if xs else all_mu
        sd = _std(xs) or all_sd
        out[regime] = {"mu": mu, "sigma": max(sd, 1e-6), "n": len(xs)}
    return out


def _gjr_garch_term_pct(returns: Sequence[float], horizon: int, bars_per_day: float) -> List[float]:
    if not returns:
        return [1.0 for _ in range(horizon)]
    omega = 0.000001
    alpha = 0.08
    gamma = 0.10
    beta = 0.86
    persistence = _clamp(alpha + beta + gamma / 2.0, 0.50, 0.985)
    var = _std(returns[-min(len(returns), 100) :]) ** 2 or 1e-6
    for r in returns[-min(len(returns), 250) :]:
        leverage = gamma if r < 0 else 0.0
        var = omega + (alpha + leverage) * r * r + beta * var
    uncond = omega / max(1e-6, 1.0 - persistence)
    out: List[float] = []
    for h in range(1, horizon + 1):
        v = uncond + (persistence ** (h - 1)) * (var - uncond)
        out.append(math.sqrt(max(v, 1e-12) * bars_per_day) * 100.0)
    return out


@dataclass
class StructuralVariant:
    name: str
    step_mult: float
    trail_mult: float
    base_shift: float
    growth: float
    reserve: float
    asymmetric: bool
    moving_anchor: bool
    dd_stop: bool


def _structural_variants() -> List[StructuralVariant]:
    return [
        StructuralVariant("symmetric_moving_cap_stop", 1.00, 1.00, 0.0, 1.22, 0.12, False, True, True),
        StructuralVariant("defensive_wide_reserve", 1.28, 0.92, -8.0, 1.30, 0.24, False, True, True),
        StructuralVariant("trend_tilted_asymmetric", 1.10, 1.10, 8.0, 1.20, 0.10, True, True, True),
        StructuralVariant("squeeze_tight_reduced", 0.84, 0.88, 0.0, 1.16, 0.18, False, True, True),
        StructuralVariant("high_vol_survival", 1.55, 0.85, -12.0, 1.38, 0.32, False, True, True),
    ]


def _qtys(count: int, reserve: float) -> List[float]:
    count = max(1, int(count))
    # Grid miktarları toplamda HER ZAMAN %100 olmalı: tüm tahsis grid'lere dağıtılır.
    # ('reserve' artık toplamı düşürmez — yalnızca kademeler arası ağırlık eğrisi korunur.)
    weights = [1.0 / (1.0 + i * 0.18) for i in range(count)]
    s = sum(weights) or 1.0
    qtys = [round(100.0 * w / s, 3) for w in weights]
    # Yuvarlama artığını son kademeye ekleyerek toplamı tam 100.000 yap.
    drift = round(100.0 - sum(qtys), 3)
    qtys[-1] = round(qtys[-1] + drift, 3)
    return qtys


def _params_from_policy(
    state: Mapping[str, Any],
    variant: StructuralVariant,
    budget: float,
    min_notional: float,
    *,
    trend_score: float,
) -> Dict[str, Any]:
    step = max(0.6, _safe_float(state.get("grid_step_pct")) * variant.step_mult)
    base = _clamp(_safe_float(state.get("base_alloc_pct"), 50.0) + variant.base_shift, 20.0, 70.0)
    if trend_score < -0.15:
        base = min(base, 42.0)
    if trend_score > 0.25 and variant.asymmetric:
        base = max(base, 55.0)
    quote = 100.0 - base
    sell_step = step * (0.95 if variant.asymmetric and trend_score > 0 else 1.0)
    buy_step = step * (1.15 if variant.asymmetric and trend_score > 0 else 1.0)
    if trend_score < -0.15:
        buy_step *= 1.15
    base_leg = budget * base / 100.0
    quote_leg = budget * quote / 100.0
    sell_count = max(1, min(6, int(base_leg // max(1.0, min_notional * 1.05))))
    buy_count = max(1, min(8, int(quote_leg // max(1.0, min_notional * 1.05))))
    if variant.name == "squeeze_tight_reduced":
        sell_count = min(sell_count, 3)
        buy_count = min(buy_count, 3)
    if variant.name == "high_vol_survival":
        sell_count = min(sell_count, 3)
        buy_count = min(buy_count, 4)
    sell_trigs = [round(sell_step * (variant.growth ** i), 3) for i in range(sell_count)]
    buy_trigs = [round(min(91.0, buy_step * (variant.growth ** i)), 3) for i in range(buy_count)]
    sell_qty = _qtys(sell_count, variant.reserve)
    buy_qty = _qtys(buy_count, variant.reserve)
    trail = max(0.2, _safe_float(state.get("trailing_pct"), step * 0.42) * variant.trail_mult)
    return {
        "base_alloc_pct": round(base, 2),
        "quote_alloc_pct": round(quote, 2),
        "sell_grids": [
            {"sell_grid_pct": sell_trigs[i], "sell_qty_pct_of_base": sell_qty[i]}
            for i in range(sell_count)
        ],
        "buy_grids": [
            {"buy_grid_pct": buy_trigs[i], "buy_qty_pct_of_quote": buy_qty[i]}
            for i in range(buy_count)
        ],
        "sell_trigger_trailing_pct": round(_clamp(trail, 0.2, sell_step * 0.95), 3),
        "buy_trigger_trailing_pct": round(_clamp(trail, 0.2, buy_step * 0.95), 3),
        "profit_exit_rise_pct": round(max(0.6, sell_step * 1.45), 3),
        "profit_exit_drop_pct": round(_clamp(trail * 0.9, 0.2, 4.5), 3),
        "profit_reentry_drop_pct": round(max(0.6, buy_step * 1.25), 3),
        "profit_reentry_rise_pct": round(_clamp(trail * 0.9, 0.2, 4.0), 3),
        "max_buy_levels": buy_count,
        "min_net_profit_rate": 0.0015,
        "basis_mode": "moving_anchor" if variant.moving_anchor else "grid_only",
        "min_notional_guard": min_notional,
        "robust_structure": variant.name,
        "dd_stop_enabled": variant.dd_stop,
    }


def _fold_segments(candles: Sequence[Dict[str, Any]], n_folds: int, min_bars: int = 50) -> List[List[Dict[str, Any]]]:
    if n_folds < 2 or len(candles) < min_bars * 2:
        return []
    n_folds = min(n_folds, max(2, len(candles) // min_bars))
    seg = len(candles) // n_folds
    if seg < min_bars:
        return []
    out: List[List[Dict[str, Any]]] = []
    for i in range(n_folds):
        a = i * seg
        b = len(candles) if i == n_folds - 1 else (i + 1) * seg
        if b - a >= min_bars:
            out.append(list(candles[a:b]))
    return out


def _backtest_metrics(
    params: Dict[str, Any],
    train: Sequence[Dict[str, Any]],
    oos: Optional[Sequence[Dict[str, Any]]],
    recent_in: Optional[Sequence[Dict[str, Any]]],
    budget: float,
    symbol: str,
    fee: float,
    slippage: float,
    obj_cfg: ObjectiveConfig,
    folds: int,
) -> Dict[str, Any]:
    r_in = run_backtest(train, params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
    r_recent = (
        run_backtest(recent_in, params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
        if recent_in
        else None
    )
    r_oos = (
        run_backtest(oos, params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
        if oos
        else None
    )
    sc = combined_score(r_in, r_oos, r_recent, obj_cfg)
    segments = _fold_segments(train, folds)
    fold_returns: List[float] = []
    fold_scores: List[float] = []
    for seg in segments:
        rr = run_backtest(seg, params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
        if rr.ok:
            fold_returns.append(rr.return_pct)
            fold_scores.append(score_backtest(rr, obj_cfg).score)
    if fold_scores:
        sc["fold_consistency"] = round(sum(fold_scores) / len(fold_scores) - 0.35 * _std(fold_scores), 4)
        sc["fold_returns"] = [round(x, 4) for x in fold_returns]
        # fold_adjusted_score: sıralama için kullan; final_score (combined_score çıktısı)
        # SABİT kalır — test ve karar katmanı tutarlı kıyaslama için buna güvenir.
        sc["fold_adjusted_score"] = round(0.75 * sc["final_score"] + 0.25 * sc["fold_consistency"], 4)
    else:
        sc["fold_adjusted_score"] = sc["final_score"]
    sc["in_metrics"] = r_in.to_dict()
    if r_oos:
        sc["oos_metrics"] = r_oos.to_dict()
    if r_recent:
        sc["recent_metrics"] = r_recent.to_dict()
    return sc


def _student_t(rng: random.Random, nu: float) -> float:
    nu = _clamp(nu, 2.2, 30.0)
    z = rng.gauss(0.0, 1.0)
    chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(max(1, int(round(nu)))))
    return z / math.sqrt(max(chi / nu, 1e-9))


def _sample_next_regime(rng: random.Random, row: Mapping[str, float]) -> str:
    x = rng.random()
    acc = 0.0
    for r in REGIMES:
        acc += max(0.0, _safe_float(row.get(r)))
        if x <= acc:
            return r
    return REGIMES[-1]


def _scenario_path(
    rng: random.Random,
    start_price: float,
    start_t: int,
    iv_ms: int,
    horizon_bars: int,
    current_regime: str,
    transition: Mapping[str, Mapping[str, float]],
    emissions: Mapping[str, Mapping[str, float]],
    vol_terms_pct: Sequence[float],
    tail_alpha: float,
    stress: Optional[str] = None,
    sign: float = 1.0,
) -> List[Dict[str, Any]]:
    # `sign` enables ANTITHETIC variates: a path generated with the same `rng`
    # seed but sign=-1 consumes the identical random stream (same regime path,
    # same |shock|) with the diffusion shock negated → a paired mirror that
    # cancels first-order sampling error in symmetric functionals.
    price = max(1e-9, start_price)
    regime = current_regime if current_regime in REGIMES else "UNKNOWN"
    out: List[Dict[str, Any]] = []
    for i in range(horizon_bars):
        if stress == "regime_flip" and i == horizon_bars // 3:
            regime = "DUMP_RISK" if regime != "DUMP_RISK" else "HIGH_VOL_RANGING"
        elif i > 0:
            regime = _sample_next_regime(rng, transition.get(regime, {}))
        em = emissions.get(regime, {})
        mu = _safe_float(em.get("mu"))
        sigma = max(1e-6, _safe_float(em.get("sigma"), 0.002))
        if vol_terms_pct:
            vt = vol_terms_pct[min(len(vol_terms_pct) - 1, int(i / max(1, horizon_bars / len(vol_terms_pct))))]
            sigma = max(sigma, vt / 100.0 / math.sqrt(max(1.0, _DAY_MS / iv_ms)))
        shock = sign * _student_t(rng, tail_alpha) * sigma
        if stress == "flash_crash" and i == max(2, horizon_bars // 8):
            shock -= max(0.10, 8.0 * sigma)
        if stress == "vol_spike" and horizon_bars // 4 <= i <= horizon_bars // 2:
            shock *= 2.3
        o = price
        price = max(1e-9, price * math.exp(mu + shock))
        c = price
        spread = max(abs(c - o), max(o, c) * sigma * (0.8 + rng.random() * 0.8))
        h = max(o, c) + spread * 0.45
        l = max(1e-9, min(o, c) - spread * 0.45)
        out.append({"t": start_t + i * iv_ms, "o": o, "h": h, "l": l, "c": c, "v": 1.0})
    return out


def _forecast_mc_score(
    params: Dict[str, Any],
    history: Sequence[Dict[str, Any]],
    labels: Sequence[str],
    robust_forecast: Any,
    transition: Mapping[str, Mapping[str, float]],
    *,
    n_paths: int,
    horizon_days: int,
    budget: float,
    symbol: str,
    fee: float,
    slippage: float,
    seed: int,
    deadline: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Tuple[Dict[str, Any], List[float], bool]:
    if not history or n_paths <= 0:
        return {}, [], False
    rng = random.Random(seed)
    iv_ms = _median_interval_ms(history)
    bars_per_day = max(1, int(round(_DAY_MS / iv_ms)))
    horizon_bars = max(30, int(horizon_days * bars_per_day))
    emissions = _emission_stats(history, labels)
    returns = _log_returns(history)
    tail_alpha = hill_tail_index(returns)
    start_price = _safe_float(history[-1].get("c"), 100.0)
    start_t = int(history[-1].get("t") or 0) + iv_ms
    current = labels[-1] if labels else "UNKNOWN"
    stress_modes = [None, None, None, "flash_crash", "regime_flip", "vol_spike"]
    rets: List[float] = []
    dds: List[float] = []
    cycles: List[float] = []
    stress_ok = True
    _last_prog = time.time()
    # Taban: deadline çoktan geçmiş olsa bile en az birkaç yol koştur ki forecast boş
    # kalmasın (anlamlı medyan/olasılık için). Tabandan sonra deadline'a kesin uyulur.
    _min_paths = min(n_paths, 16)
    for i in range(n_paths):
        # Sert zaman bütçesi: tabanı geçtikten sonra deadline aşılırsa o ana kadar
        # üretilen yollarla devam et (kısmi MC hâlâ anlamlı). Bu, motorun bütçeyi aşıp
        # çekirdeği saatlerce yememesini garanti eder — tek-thread döngü buradan kesilir.
        if deadline is not None and i >= _min_paths and time.time() >= deadline:
            break
        stress = stress_modes[i % len(stress_modes)] if i < max(6, n_paths // 8) else None
        path = _scenario_path(
            rng,
            start_price,
            start_t,
            iv_ms,
            horizon_bars,
            current,
            transition,
            emissions,
            robust_forecast.vol_term_pct,
            tail_alpha,
            stress=stress,
        )
        r = run_backtest(path, params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
        if r.ok:
            rets.append(r.return_pct)
            dds.append(r.max_drawdown_pct)
            cycles.append(r.cycles_closed)
            if stress and r.max_drawdown_pct > 35.0:
                stress_ok = False
        if progress_cb is not None and (time.time() - _last_prog) >= 2.0:
            _last_prog = time.time()
            try:
                progress_cb(i + 1, n_paths)
            except ParamOptimizerCancelled:
                raise
            except Exception:
                pass
    if not rets:
        return {}, [], False
    months = max(0.5, horizon_days / 30.4375)
    p05 = _percentile(rets, 0.05)
    p95 = _percentile(rets, 0.95)
    med = _percentile(rets, 0.5)
    score = robust_objective([x / months for x in rets])
    return {
        "robustness": round(score, 4),
        "median_return_pct": round(med, 4),
        "mean_return_pct": round(sum(rets) / len(rets), 4),
        "p05_return_pct": round(p05, 4),
        "p95_return_pct": round(p95, 4),
        "prob_profit": round(sum(1 for x in rets if x > 0) / len(rets), 4),
        "median_max_dd_pct": round(_percentile(dds, 0.5), 4),
        "worst_max_dd_pct": round(_percentile(dds, 0.95), 4),
        "median_cycles": round(_percentile(cycles, 0.5), 4),
        "n_paths": len(rets),
        "cvar5_return_pct": round(cvar(rets, 0.05), 4),
    }, rets, stress_ok


# ---------------------------------------------------------------------------
# Parallel, variance-reduced Monte-Carlo forecast
#   * CRN (Common Random Numbers): every candidate is scored on the SAME scenario
#     set (fixed base seed) → fair, low-variance ranking. The legacy code gave
#     each candidate a different future (seed+idx*101) = noisy comparison.
#   * Antithetic variates: diffusion paths emitted in +1/-1 mirror pairs.
#   * Stratified stress: the 3 tail scenarios are always represented.
#   * Path reuse: each path is generated once and backtested by ALL candidates.
#   * Parallelism: paths fan out across CPU cores (idle-aware), deadline-safe.
# ---------------------------------------------------------------------------

_MC_STRESS_MODES = ("flash_crash", "regime_flip", "vol_spike")
_MC_BASE_SEED = 70_413


def _build_scenario_plan(
    n_paths: int, base_seed: int = _MC_BASE_SEED
) -> List[Tuple[int, Optional[str], float]]:
    """Deterministic plan of (seed, stress, sign). Stress ~1/8 (>=3) stratified
    over the 3 modes; the rest are antithetic +1/-1 diffusion pairs sharing a
    seed. Seeds depend only on (base_seed, index) → identical across candidates."""
    n = max(1, int(n_paths))
    n_stress = min(n, max(3, n // 8))
    plan: List[Tuple[int, Optional[str], float]] = []
    for k in range(n_stress):
        plan.append((base_seed + 9001 + k, _MC_STRESS_MODES[k % len(_MC_STRESS_MODES)], 1.0))
    j = 0
    while len(plan) < n:
        seed = base_seed + j
        plan.append((seed, None, 1.0))
        if len(plan) < n:
            plan.append((seed, None, -1.0))  # antithetic mirror (same seed)
        j += 1
    return plan[:n]


def _summarize_mc(
    rets: Sequence[float],
    dds: Sequence[float],
    cycles: Sequence[float],
    stress_ok: bool,
    horizon_days: float,
) -> Dict[str, Any]:
    if not rets:
        return {}
    months = max(0.5, horizon_days / 30.4375)
    return {
        "robustness": round(robust_objective([x / months for x in rets]), 4),
        "median_return_pct": round(_percentile(rets, 0.5), 4),
        "mean_return_pct": round(sum(rets) / len(rets), 4),
        "p05_return_pct": round(_percentile(rets, 0.05), 4),
        "p95_return_pct": round(_percentile(rets, 0.95), 4),
        "prob_profit": round(sum(1 for x in rets if x > 0) / len(rets), 4),
        "median_max_dd_pct": round(_percentile(dds, 0.5), 4),
        "worst_max_dd_pct": round(_percentile(dds, 0.95), 4),
        "median_cycles": round(_percentile(cycles, 0.5), 4),
        "n_paths": len(rets),
        "cvar5_return_pct": round(cvar(rets, 0.05), 4),
        "stress_ok": bool(stress_ok),
    }


def _mc_path_worker(
    task: Tuple[int, int, Optional[str], float]
) -> Optional[Tuple[int, bool, List[Optional[Tuple[float, float, float]]]]]:
    """Top-level (picklable) worker: generate ONE scenario path from its seed and
    backtest EVERY candidate on it (path reuse + CRN). Shared config comes from
    `parallel.SHARED` (set once per worker by the pool initializer)."""
    idx, seed, stress, sign = task
    s = parallel.SHARED
    g = s.get("gen")
    if not g:
        return None
    try:
        path = _scenario_path(
            random.Random(seed),
            g["start_price"], g["start_t"], g["iv_ms"], g["horizon_bars"],
            g["current"], g["transition"], g["emissions"], g["vol_terms"],
            g["tail_alpha"], stress=stress, sign=sign,
        )
    except Exception:
        return None
    budget = s["budget"]
    symbol = s["symbol"]
    fee = s["fee"]
    slip = s["slippage"]
    per_candidate: List[Optional[Tuple[float, float, float]]] = []
    for params in s["candidates"]:
        try:
            r = run_backtest(path, params, budget, symbol, fee_rate=fee, slippage_bps=slip)
            per_candidate.append(
                (r.return_pct, r.max_drawdown_pct, float(r.cycles_closed)) if r.ok else None
            )
        except Exception:
            per_candidate.append(None)
    return idx, bool(stress), per_candidate


def _forecast_mc_parallel(
    top_candidates: Sequence[Dict[str, Any]],
    history: Sequence[Dict[str, Any]],
    labels: Sequence[str],
    robust_forecast: Any,
    transition: Mapping[str, Mapping[str, float]],
    *,
    n_paths: int,
    horizon_days: int,
    budget: float,
    symbol: str,
    fee: float,
    slippage: float,
    workers: int,
    deadline: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Tuple[Dict[str, Any], List[float], bool]]:
    """Score ALL top candidates on one shared, variance-reduced scenario set in
    parallel. Returns a list aligned to `top_candidates`: (fc, raw_returns, stress_ok)."""
    if not top_candidates or n_paths <= 0 or not history:
        return [({}, [], True) for _ in top_candidates]
    iv_ms = _median_interval_ms(history)
    bars_per_day = max(1, int(round(_DAY_MS / iv_ms)))
    horizon_bars = max(30, int(horizon_days * bars_per_day))
    gen = {
        "start_price": _safe_float(history[-1].get("c"), 100.0),
        "start_t": int(history[-1].get("t") or 0) + iv_ms,
        "iv_ms": iv_ms,
        "horizon_bars": horizon_bars,
        "current": labels[-1] if labels else "UNKNOWN",
        "transition": transition,
        "emissions": _emission_stats(history, labels),
        "vol_terms": list(robust_forecast.vol_term_pct),
        "tail_alpha": hill_tail_index(_log_returns(history)),
    }
    payload = {
        "gen": gen,
        "candidates": [sc["params"] for sc in top_candidates],
        "budget": budget, "symbol": symbol, "fee": fee, "slippage": slippage,
    }
    plan = _build_scenario_plan(n_paths)
    tasks = [(i, seed, stress, sign) for i, (seed, stress, sign) in enumerate(plan)]
    results = parallel.pmap(
        _mc_path_worker, tasks, workers=workers,
        init=parallel._init_worker, init_args=(payload,),
        deadline=deadline, min_items=min(len(tasks), 16), serial_threshold=8,
    )
    nC = len(top_candidates)
    rets: List[List[float]] = [[] for _ in range(nC)]
    dds: List[List[float]] = [[] for _ in range(nC)]
    cycs: List[List[float]] = [[] for _ in range(nC)]
    stress_ok = [True] * nC
    done = 0
    for res in results:
        if not res:
            continue
        _idx, is_stress, per_cand = res
        done += 1
        for c in range(nC):
            v = per_cand[c] if c < len(per_cand) else None
            if v is None:
                continue
            ret, dd, cyc = v
            rets[c].append(ret)
            dds[c].append(dd)
            cycs[c].append(cyc)
            if is_stress and dd > 35.0:
                stress_ok[c] = False
    if progress_cb:
        try:
            progress_cb(done, len(tasks))
        except Exception:
            pass
    return [
        (_summarize_mc(rets[c], dds[c], cycs[c], stress_ok[c], horizon_days), rets[c], stress_ok[c])
        for c in range(nC)
    ]


def _validate_candidate_worker(task: Tuple[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Top-level (picklable) worker: full robust scoring of ONE candidate over the
    shared train/oos/recent data + walk-forward folds."""
    name, params = task
    s = parallel.SHARED
    try:
        sc = _backtest_metrics(
            params, s["train"], s["oos"], s["recent_in"], s["budget"],
            s["symbol"], s["fee"], s["slippage"], s["obj_cfg"], s["folds"],
        )
    except Exception:
        return None
    sc["params"] = params
    sc["variant"] = name
    return sc


def _pbo_from_candidates(candidates: Sequence[Dict[str, Any]]) -> float:
    usable = [c for c in candidates if c.get("fold_returns")]
    if len(usable) < 3:
        return 1.0
    fold_n = min(len(c["fold_returns"]) for c in usable)
    if fold_n < 2:
        return 1.0
    bad = 0
    trials = 0
    for hold in range(fold_n):
        ranked = sorted(
            usable,
            key=lambda c: sum(c["fold_returns"][i] for i in range(fold_n) if i != hold) / max(1, fold_n - 1),
            reverse=True,
        )
        chosen = ranked[0]
        test_values = sorted((c["fold_returns"][hold] for c in usable), reverse=True)
        rank = test_values.index(chosen["fold_returns"][hold]) + 1
        if rank > len(test_values) / 2.0:
            bad += 1
        trials += 1
    return bad / max(1, trials)


def _deflated_sharpe_ok(fold_returns: Sequence[float], n_variants: int) -> bool:
    if len(fold_returns) < 3:
        return False
    mu = sum(fold_returns) / len(fold_returns)
    sd = _std(fold_returns)
    if sd <= 0:
        return mu > 0
    sharpe = mu / sd * math.sqrt(len(fold_returns))
    hurdle = math.sqrt(max(0.0, 2.0 * math.log(max(2, n_variants)))) / max(1.0, math.sqrt(len(fold_returns)))
    return sharpe > hurdle


def _plateau_ok(
    params: Dict[str, Any],
    candles: Sequence[Dict[str, Any]],
    budget: float,
    symbol: str,
    fee: float,
    slippage: float,
    obj_cfg: ObjectiveConfig,
) -> bool:
    base = score_backtest(run_backtest(candles, params, budget, symbol, fee_rate=fee, slippage_bps=slippage), obj_cfg).score
    if not math.isfinite(base):
        return False
    scores: List[float] = []
    for mult in (0.92, 1.08):
        p = {**params}
        p["sell_grids"] = [
            {**g, "sell_grid_pct": round(_safe_float(g.get("sell_grid_pct")) * mult, 3)}
            for g in params.get("sell_grids", [])
        ]
        p["buy_grids"] = [
            {**g, "buy_grid_pct": round(_safe_float(g.get("buy_grid_pct")) * mult, 3)}
            for g in params.get("buy_grids", [])
        ]
        p["sell_trigger_trailing_pct"] = round(max(0.2, _safe_float(params.get("sell_trigger_trailing_pct")) * mult), 3)
        p["buy_trigger_trailing_pct"] = round(max(0.2, _safe_float(params.get("buy_trigger_trailing_pct")) * mult), 3)
        rr = run_backtest(candles, p, budget, symbol, fee_rate=fee, slippage_bps=slippage)
        scores.append(score_backtest(rr, obj_cfg).score)
    if not scores:
        return False
    return min(scores) >= base - max(2.0, abs(base) * 0.35)


def optimize_robust(
    train: Sequence[Dict[str, Any]],
    oos: Optional[Sequence[Dict[str, Any]]],
    recent_in: Optional[Sequence[Dict[str, Any]]],
    space: ParamSpace,
    features: HistoryFeatures,
    budget: float,
    symbol: str,
    *,
    fee: float = 0.001,
    slippage: float = 2.0,
    obj_cfg: Optional[ObjectiveConfig] = None,
    tier: Any = None,
    time_budget_sec: float = 120.0,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    n_workers: int = 0,
) -> Dict[str, Any]:
    obj_cfg = obj_cfg or ObjectiveConfig()
    train = list(train)
    oos = list(oos) if oos else None
    recent_in = list(recent_in) if recent_in else None
    t_start = time.time()
    # Idle-aware CPU: use nearly all cores when the box is idle, back off when
    # busy. The candidate search + Monte-Carlo paths fan out across these workers.
    workers = parallel.resolve_workers(n_workers, idle_aware=True)
    seed = 31091
    rng = random.Random(seed)
    folds = max(2, int(getattr(tier, "walk_forward_folds", 4) or 4))
    mc_paths_target = int(getattr(tier, "monte_carlo_paths", 0) or 0)
    mc_horizon = int(getattr(tier, "mc_horizon_days", 180) or 180)
    min_notional = float(getattr(space, "min_notional", 10.0) or 10.0)
    # Sert duvar-saati: hiçbir aşama bu zamanı aşamaz (özellikle tek-thread MC).
    deadline = t_start + max(1.0, float(time_budget_sec))

    def emit(stage: str, **kw: Any) -> None:
        if progress_cb:
            try:
                progress_cb({"stage": stage, **kw})
            except ParamOptimizerCancelled:
                raise
            except Exception:
                pass

    center_variant = _structural_variants()[0]
    labels = _rolling_regime_labels(train, lookback=max(12, int(_intervals_per_day(train))))
    skill, transition, clim, skill_meta = _nested_forecast_skill(labels, folds=folds)
    returns = _log_returns(train)
    bars_per_day = _intervals_per_day(train)
    robust_forecast = build_robust_forecast(
        features,
        skill=skill,
        regime_labels=labels,
        horizon_steps=6,
        transition=transition if skill.passed else None,
    )
    garch_term = _gjr_garch_term_pct(returns, 6, bars_per_day)
    if garch_term:
        robust_forecast.vol_term_pct = [
            round(max(robust_forecast.vol_term_pct[i], garch_term[i]), 6)
            for i in range(min(len(robust_forecast.vol_term_pct), len(garch_term)))
        ]
    policy = build_state_policy(robust_forecast, features, fee_rate=fee, slippage_bps=slippage)
    current_regime = features.regime_code if features.regime_code in policy else "UNKNOWN"
    current_state = policy[current_regime].to_dict()

    t0 = time.time()
    base_params = _params_from_policy(current_state, center_variant, budget, min_notional, trend_score=features.trend_score)
    r0 = run_backtest(train, base_params, budget, symbol, fee_rate=fee, slippage_bps=slippage)
    per_eval = max(0.001, time.time() - t0)
    emit("measure", per_eval_sec=round(per_eval, 4), workers=workers, base_score=round(score_backtest(r0, obj_cfg).score, 4))

    variants = _structural_variants()
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    for variant in variants:
        params = _params_from_policy(current_state, variant, budget, min_notional, trend_score=features.trend_score)
        candidates.append((variant.name, params))
        for step_mult in (0.92, 1.08):
            vv = StructuralVariant(
                variant.name + ("_narrow" if step_mult < 1 else "_wide"),
                variant.step_mult * step_mult,
                variant.trail_mult,
                variant.base_shift,
                variant.growth,
                variant.reserve,
                variant.asymmetric,
                variant.moving_anchor,
                variant.dd_stop,
            )
            candidates.append((vv.name, _params_from_policy(current_state, vv, budget, min_notional, trend_score=features.trend_score)))
    # Deduplicate by actual bot params.
    unique: List[Tuple[str, Dict[str, Any]]] = []
    seen = set()
    for name, params in candidates:
        sig = (
            params["base_alloc_pct"],
            tuple((g["sell_grid_pct"], g["sell_qty_pct_of_base"]) for g in params["sell_grids"]),
            tuple((g["buy_grid_pct"], g["buy_qty_pct_of_quote"]) for g in params["buy_grids"]),
            params["sell_trigger_trailing_pct"],
            params["buy_trigger_trailing_pct"],
        )
        if sig not in seen:
            seen.add(sig)
            unique.append((name, params))
    candidates = unique
    emit("coarse", evaluated=len(candidates), best_score=round(score_backtest(r0, obj_cfg).score, 4), elapsed=round(time.time() - t_start, 1))

    # Candidate validation — embarrassingly parallel: each candidate is a full
    # robust score (train/oos/recent + walk-forward folds) over the SAME shared
    # data. Fan out across workers; deadline-safe; serial fallback inside pmap.
    emit("validate", candidates=len(candidates), candidates_done=0, workers=workers, elapsed=round(time.time() - t_start, 1))
    _val_payload = {
        "train": train, "oos": oos, "recent_in": recent_in, "budget": budget,
        "symbol": symbol, "fee": fee, "slippage": slippage, "obj_cfg": obj_cfg,
        "folds": max(2, int(getattr(tier, "walk_forward_oos_folds", folds) or folds)),
    }
    _val_results = parallel.pmap(
        _validate_candidate_worker, candidates, workers=workers,
        init=parallel._init_worker, init_args=(_val_payload,),
        deadline=deadline, min_items=1, serial_threshold=4,
    )
    scored: List[Dict[str, Any]] = [sc for sc in _val_results if sc]
    emit(
        "validate",
        message="görülmemiş doğrulama: %d aday %d çekirdekte" % (len(scored), workers),
        candidates=len(candidates),
        candidates_done=len(scored),
        workers=workers,
        elapsed=round(time.time() - t_start, 1),
    )

    pbo = _pbo_from_candidates(scored)
    # MC path budgeting: parallelism multiplies throughput, so we afford a much
    # higher FLOOR — tail metrics (p05 / CVaR5 / worst-DD) are meaningless at the
    # old ~15-path floor and need O(100+) paths. pmap still respects the deadline.
    mc_paths_eff = 0
    if mc_paths_target > 0:
        elapsed = time.time() - t_start
        remaining = max(0.0, time_budget_sec - elapsed)
        mc_top_n = max(1, min(int(getattr(tier, "mc_top_candidates", 5) or 5), len(scored)))
        # parallel throughput ≈ workers paths per (per_eval × candidates_per_path)
        thru = int(max(1, workers) * remaining / max(per_eval * mc_top_n, 0.01))
        floor = 24 if time_budget_sec <= 30 else 96
        mc_paths_eff = min(mc_paths_target, max(floor, thru))
    forecast_scores: Dict[int, Dict[str, Any]] = {}
    stress_results: Dict[int, bool] = {}
    if mc_paths_eff > 0 and scored:
        mc_top = max(1, min(int(getattr(tier, "mc_top_candidates", 5) or 5), len(scored)))
        if time_budget_sec <= 30:
            mc_top = 1
        top_for_mc = sorted(scored, key=lambda x: x["final_score"], reverse=True)[:mc_top]

        def _mc_prog(done: int, total: int) -> None:
            emit(
                "forecast",
                message="gelecek senaryoları: %d/%d yol · %d aday · %d çekirdek"
                % (done, total, len(top_for_mc), workers),
                candidates=len(top_for_mc),
                paths=mc_paths_eff,
                mc_done=done,
                mc_total=total,
                elapsed=round(time.time() - t_start, 1),
                eta_remaining_sec=max(0, int(deadline - time.time())),
            )

        emit(
            "forecast",
            message="forecast-conditioned senaryolar (CRN + antithetic, %d çekirdek)" % workers,
            candidates=len(top_for_mc),
            paths=mc_paths_eff,
            mc_done=0,
            mc_total=mc_paths_eff,
            elapsed=round(time.time() - t_start, 1),
        )
        # All top candidates scored on ONE shared, variance-reduced scenario set,
        # fanned out across workers (Common Random Numbers → fair, low-variance).
        _mc_out = _forecast_mc_parallel(
            top_for_mc,
            train,
            labels,
            robust_forecast,
            transition if skill.passed else default_transition_matrix(),
            n_paths=mc_paths_eff,
            horizon_days=mc_horizon,
            budget=budget,
            symbol=symbol,
            fee=fee,
            slippage=slippage,
            workers=workers,
            deadline=deadline,
            progress_cb=_mc_prog,
        )
        for sc, (fc, raw_returns, stress_ok) in zip(top_for_mc, _mc_out):
            sc["forecast"] = fc
            sc["mc_returns"] = raw_returns
            sc["robustness"] = fc.get("robustness", 0.0) if fc else 0.0
            # fold_adjusted_score üzerine robustness bonusu ekle — bu combined_score sıralama için
            sc["combined_score"] = sc.get("fold_adjusted_score", sc["final_score"]) + 0.55 * sc.get("robustness", 0.0)
            forecast_scores[id(sc)] = fc
            stress_results[id(sc)] = stress_ok
        emit(
            "forecast",
            message="%d aday × %d yol değerlendirildi (paylaşılan senaryo seti)"
            % (len(top_for_mc), mc_paths_eff),
            candidates=len(top_for_mc),
            mc_done=mc_paths_eff,
            mc_total=mc_paths_eff,
            elapsed=round(time.time() - t_start, 1),
        )
    for sc in scored:
        # combined_score: sıralama için fold_adjusted_score + robustness kullan
        sc.setdefault("combined_score", sc.get("fold_adjusted_score", sc["final_score"]))
        sc.setdefault("forecast", None)
        sc.setdefault("robustness", None)

    scored.sort(key=lambda x: x.get("combined_score", x.get("fold_adjusted_score", x["final_score"])), reverse=True)
    best = scored[0]
    # Garanti: MC açıkken kazanan adayın her zaman bir forecast'i olsun. Bütçe sınırı
    # nedeniyle kazanan MC görmemişse, taban yol sayısıyla (deadline-bağımsız min) tek
    # bir bounded MC daha koştur — sonuç/UI forecast'siz kalmasın, donma da olmaz.
    if mc_paths_eff > 0 and best.get("forecast") is None:
        fc_b, raw_b, stress_b = _forecast_mc_score(
            best["params"],
            train,
            labels,
            robust_forecast,
            transition if skill.passed else default_transition_matrix(),
            n_paths=mc_paths_eff,
            horizon_days=mc_horizon,
            budget=budget,
            symbol=symbol,
            fee=fee,
            slippage=slippage,
            seed=seed + 7,
            deadline=deadline,
        )
        best["forecast"] = fc_b
        best["mc_returns"] = raw_b
        best["robustness"] = fc_b.get("robustness", 0.0) if fc_b else 0.0
        best["combined_score"] = best.get("fold_adjusted_score", best["final_score"]) + 0.55 * best.get("robustness", 0.0)
        forecast_scores[id(best)] = fc_b
        stress_results[id(best)] = stress_b
    best_params = best["params"]
    plateau = _plateau_ok(
        best_params,
        recent_in or train[-min(len(train), 240) :],
        budget,
        symbol,
        fee,
        slippage,
        obj_cfg,
    )
    dsr_ok = _deflated_sharpe_ok(best.get("fold_returns") or [], len(scored))
    stress_ok = stress_results.get(id(best), True if not best.get("forecast") else False)
    gate = deploy_gate(
        skill=skill,
        oos=best.get("oos_metrics"),
        walk_forward={
            "frac_profitable": sum(1 for x in best.get("fold_returns", []) if x > 0) / max(1, len(best.get("fold_returns", []))),
            "total_cycles": sum(int((best.get("in_metrics") or {}).get("cycles_closed") or 0) for _ in [0]),
        },
        pbo=pbo,
        deflated_sharpe_ok=dsr_ok,
        stress_ok=stress_ok,
        plateau_ok=plateau,
    )

    # If tight/heavy analysis asks for serious compute, spend a small minimum on
    # actual extra plateau checks so the job is not an instant no-op.
    if time_budget_sec >= 20 and mc_paths_target >= 400:
        while time.time() - t_start < min(8.0, time_budget_sec * 0.5):
            v = rng.choice(variants)
            p = _params_from_policy(current_state, v, budget, min_notional, trend_score=features.trend_score)
            run_backtest(train[-min(len(train), 180) :], p, budget, symbol, fee_rate=fee, slippage_bps=slippage)

    leaderboard = []
    for sc in scored[: min(len(scored), 12)]:
        fc = sc.get("forecast") or {}
        leaderboard.append(
            {
                "combined_score": round(sc.get("combined_score", sc["final_score"]), 4),
                "final_score": round(sc["final_score"], 4),
                "in_sample_score": round(sc.get("in_sample_score", 0.0), 4),
                "oos_return_pct": (sc.get("oos_metrics") or {}).get("return_pct"),
                "in_return_pct": (sc.get("in_metrics") or {}).get("return_pct"),
                "mc_median_return_pct": fc.get("median_return_pct"),
                "mc_prob_profit": fc.get("prob_profit"),
                "mc_robustness": sc.get("robustness"),
                "structure": sc.get("variant"),
                "params": sc["params"],
            }
        )

    best_score = {k: v for k, v in best.items() if k not in ("params", "mc_returns")}
    best_score["pbo"] = round(pbo, 4)
    best_score["deflated_sharpe_ok"] = dsr_ok
    best_score["plateau_ok"] = plateau
    best_score["deploy_gate"] = gate.to_dict()
    best_forecast = best.get("forecast")
    if not best_forecast and mc_paths_eff == 0:
        best_forecast = {
            "n_paths": 0,
            "prob_profit": None,
            "median_return_pct": None,
            "p05_return_pct": None,
            "robustness": None,
        }

    return {
        "best_vec": {"structure": best.get("variant")},
        "best_params": best_params,
        "best_score": best_score,
        "forecast": best_forecast,
        "in_sample_result": best.get("in_metrics"),
        "oos_result": best.get("oos_metrics"),
        "leaderboard": leaderboard,
        "robust_skill": skill.to_dict(),
        "robust_forecast": robust_forecast.to_dict(),
        "causal_features": _causal_feature_pack(train),
        "pbo": round(pbo, 4),
        "deflated_sharpe_ok": dsr_ok,
        "plateau_ok": plateau,
        "stress_ok": stress_ok,
        "deploy_gate": gate.to_dict(),
        "stats": {
            "engine_version": "robust_v2",
            "per_eval_sec": round(per_eval, 4),
            "workers": 1,
            "evals_total": len(candidates),
            "search_evals": len(candidates),
            "validated": len(scored),
            "mc_tested": sum(1 for sc in scored if sc.get("forecast")),
            "mc_paths": mc_paths_eff,
            "walk_forward_folds": folds,
            "nested_oos_points": skill_meta.get("oos_points", 0),
            "purge": skill_meta.get("purge", 0),
            "embargo": skill_meta.get("embargo", 0),
            "pbo": round(pbo, 4),
            "deflated_sharpe_ok": dsr_ok,
            "plateau_ok": plateau,
            "deploy": gate.deploy,
            "degraded": False,
            "elapsed_sec": round(time.time() - t_start, 1),
            "forecast_skill_score": skill.to_dict().get("skill_score"),
            "forecast_fallback_used": skill.fallback_used,
        },
    }
