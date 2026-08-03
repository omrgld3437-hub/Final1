"""Structured adjuster trace for V6 telemetry / staging reports."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.v6.adjusters.btc_adjuster import btc_adjuster
from app.services.dynamic_param_score.v6.adjusters.data_quality_adjuster import data_quality_adjuster
from app.services.dynamic_param_score.v6.adjusters.fake_move_adjuster import fake_move_adjuster
from app.services.dynamic_param_score.v6.adjusters.fragility_adjuster import fragility_adjuster
from app.services.dynamic_param_score.v6.adjusters.liquidity_adjuster import liquidity_adjuster
from app.services.dynamic_param_score.v6.adjusters.support_resistance_adjuster import support_resistance_adjuster
from app.services.dynamic_param_score.v6.adjusters.volatility_adjuster import volatility_adjuster
from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract

ADJUSTER_CHAIN = (
    (data_quality_adjuster, "data_quality"),
    (btc_adjuster, "btc_context"),
    (fragility_adjuster, "asset_fragility"),
    (volatility_adjuster, "volatility"),
    (liquidity_adjuster, "liquidity"),
    (support_resistance_adjuster, "support_resistance"),
    (fake_move_adjuster, "fake_move"),
)


def _delta_dict(delta: AdjusterDelta) -> Dict[str, Any]:
    return {
        "base_delta_steps": delta.base_delta_steps,
        "buy_grid_distance_delta": delta.buy_grid_distance_delta,
        "sell_grid_distance_delta": delta.sell_grid_distance_delta,
        "buyback_trigger_delta": delta.buyback_trigger_delta,
        "profit_sell_trigger_delta": delta.profit_sell_trigger_delta,
        "buy_trailing_delta_steps": delta.buy_trailing_delta_steps,
        "sell_trailing_delta_steps": delta.sell_trailing_delta_steps,
        "buy_grid_count_delta": delta.buy_grid_count_delta,
        "sell_grid_count_delta": delta.sell_grid_count_delta,
        "normal_buy_override": delta.normal_buy_override,
        "severity_override": delta.severity_override,
        "tags": list(delta.tags),
    }


def _class_for(name: str, extra: Dict[str, Any], delta: AdjusterDelta) -> str:
    if name == "data_quality":
        risk = int(extra.get("data_quality_risk") or 0)
        if risk >= 75:
            return "DQ3"
        if risk >= 50:
            return "DQ2"
        if risk >= 25:
            return "DQ1"
        return "DQ0"
    if name == "btc_context":
        risk = int(extra.get("btc_risk") or 0)
        return f"B{min(3, max(0, risk // 25))}"
    if name == "asset_fragility":
        return str(extra.get("fragility_class") or "F1")
    if name == "volatility":
        score = int(extra.get("volatility_score") or 0)
        return f"V{min(5, max(1, score // 20 + 1))}"
    if name == "liquidity":
        risk = int(extra.get("liquidity_risk") or 0)
        return f"L{min(3, max(0, risk // 25))}"
    if name == "support_resistance":
        tags = [t for t in delta.tags if t.startswith("SR_")]
        return tags[0] if tags else "SR_NEUTRAL"
    if name == "fake_move":
        tags = [t for t in delta.tags if t in ("PUMP_HIGH", "DUMP_HIGH", "FAKE_BOUNCE", "FAKE_BREAKOUT")]
        return tags[0] if tags else "FM_NEUTRAL"
    return "N/A"


def _score_for(name: str, extra: Dict[str, Any], inp: V6InputContract) -> int:
    if name == "data_quality":
        return int(extra.get("data_quality_risk") or 0)
    if name == "btc_context":
        return int(extra.get("btc_risk") or 0)
    if name == "asset_fragility":
        return {"F1": 25, "F2": 55, "F3": 85}.get(str(extra.get("fragility_class") or "F1"), 25)
    if name == "volatility":
        return int(extra.get("volatility_score") or 0)
    if name == "liquidity":
        return int(extra.get("liquidity_risk") or 0)
    if name == "support_resistance":
        return int(inp.support_strength_score or 0)
    if name == "fake_move":
        vals = [
            float(v)
            for v in (
                inp.pump_score,
                inp.dump_score,
                inp.fake_bounce_score,
                inp.fake_breakout_score,
            )
            if v is not None
        ]
        return int(max(vals)) if vals else 0
    return 0


_RISK_SCORE_FIELD = {
    "data_quality": "data_quality_risk_score",
    "btc_context": "btc_market_risk_score",
    "asset_fragility": "fragility_risk_score",
    "volatility": "volatility_risk_score",
    "liquidity": "liquidity_risk_score",
}


def _trace_entry(name: str, extra: Dict[str, Any], delta: AdjusterDelta, inp: V6InputContract) -> Dict[str, Any]:
    score = _score_for(name, extra, inp)
    entry: Dict[str, Any] = {
        "name": name,
        "class": _class_for(name, extra, delta),
        "score": score,
        "delta": _delta_dict(delta),
    }
    risk_field = _RISK_SCORE_FIELD.get(name)
    if risk_field:
        entry[risk_field] = score
    if name == "btc_context" and extra.get("btc_context_delta_multiplier") is not None:
        entry["delta_multiplier"] = extra.get("btc_context_delta_multiplier")
    return entry


def run_adjusters_with_trace(inp: V6InputContract) -> Tuple[AdjusterDelta, int, List[Dict[str, Any]]]:
    total = AdjusterDelta()
    trace: List[Dict[str, Any]] = []
    data_quality_risk = 0
    for fn, name in ADJUSTER_CHAIN:
        delta, extra = fn(inp)
        if extra.get("data_quality_risk") is not None:
            data_quality_risk = int(extra["data_quality_risk"])
        trace.append(_trace_entry(name, extra, delta, inp))
        total.merge(delta)
    return total, data_quality_risk, trace


def append_post_pipeline_trace(
    trace: List[Dict[str, Any]],
    *,
    delta_pre: AdjusterDelta,
    delta_capped: AdjusterDelta,
    budget_notes: List[str],
    exchange_notes: List[str],
) -> List[Dict[str, Any]]:
    out = list(trace)
    out.append(
        {
            "name": "delta_limiter",
            "class": "CAPPED",
            "score": abs(delta_pre.base_delta_steps - delta_capped.base_delta_steps),
            "delta": {
                "base_delta_steps": delta_capped.base_delta_steps - delta_pre.base_delta_steps,
                "buy_trailing_delta_steps": (
                    delta_capped.buy_trailing_delta_steps - delta_pre.buy_trailing_delta_steps
                ),
                "sell_trailing_delta_steps": (
                    delta_capped.sell_trailing_delta_steps - delta_pre.sell_trailing_delta_steps
                ),
                "buyback_trigger_delta": round(
                    delta_capped.buyback_trigger_delta - delta_pre.buyback_trigger_delta, 2
                ),
                "profit_sell_trigger_delta": round(
                    delta_capped.profit_sell_trigger_delta - delta_pre.profit_sell_trigger_delta, 2
                ),
            },
        }
    )
    out.append(
        {
            "name": "budget_scaler",
            "class": "APPLIED" if budget_notes else "PASS",
            "score": len(budget_notes),
            "delta": {"notes": budget_notes},
        }
    )
    out.append(
        {
            "name": "exchange_validator",
            "class": "TRIMMED" if exchange_notes else "PASS",
            "score": len(exchange_notes),
            "delta": {"notes": exchange_notes},
        }
    )
    return out
