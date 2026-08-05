"""V6 live engine — classify → catalog → adjust → quantize → validate.

V6 profile resolver must maximize controlled risk/reward, not minimize risk.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_DOWN
import time
from typing import Any, Dict

from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import (
    BotContext,
    DynamicParamDecision,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
# Import order initializes the adjusters package before its trace module; this
# avoids the package's trace/pipeline circular import during cold startup.
from app.services.dynamic_param_score.v6.adjusters.pipeline import run_adjusters  # noqa: F401
from app.services.dynamic_param_score.v6.v6_adjuster_trace import append_post_pipeline_trace, run_adjusters_with_trace
from app.services.dynamic_param_score.v6.constants import ENGINE_VERSION
from app.services.dynamic_param_score.v6.domain.types import GridLevel, V6FinalProfile, V6InputContract
from app.services.dynamic_param_score.v6.v6_apply_delta import apply_delta
from app.services.dynamic_param_score.v6.v6_behavior_resolver import resolve_behavior
from app.services.dynamic_param_score.v6.v6_budget_scaler import budget_scale
from app.services.dynamic_param_score.v6.v6_delta_limiter import cap_total_delta
from app.services.dynamic_param_score.v6.v6_exchange_validator import exchange_validate
from app.services.dynamic_param_score.v6.v6_indicator_adapter import build_v6_input_contract
from app.services.dynamic_param_score.v6.v6_input_contract import validate_input_contract
from app.services.dynamic_param_score.v6.v6_mandatory_buy_guard import enforce_mandatory_deep_buy
from app.services.dynamic_param_score.v6.net_profile_library import (
    resolve_net_profile,
    seal_net_profile_shape,
)
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile
from app.services.dynamic_param_score.v6.v6_quantizer import profit_code_from_pct, quantize_profile, trailing_code_from_pct
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (
    POOL_VERSION_V6,
    v6_final_to_bot_params,
    v6_final_to_telemetry_extras,
)
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display
from app.services.dynamic_param_score.v6.v6_ui_explainer import build_profile_ids
from app.services.dynamic_param_score.v6.v6_scenario_classifier import classify_scenario, to_scenario_identity
from app.services.dynamic_param_score.v6.v6_regime_stickiness import apply_regime_stickiness
from app.services.dynamic_param_score.v6.v6_scenario_tree import find_terminal_for_classifier
from app.services.dynamic_param_score.v6.v6_severity_resolver import apply_severity_override, resolve_severity
from app.services.dynamic_param_score.v6.v6_opportunity import (
    apply_v6_opportunity_postprocess,
    build_v6_opportunity_explain,
)

logger = logging.getLogger(__name__)


def _score_0_100(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (float(value) - lo) * 100.0 / (hi - lo)))


def _low_liq_reason_codes(inp: V6InputContract) -> set[str]:
    spread = float(inp.spread_pct or 0)
    volume = float(inp.volume_24h or 0)
    vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    frag = str(inp.asset_fragility_class or "F1").upper()
    zero = int(inp.zero_volume_flag or 0) > 0
    reasons: set[str] = set()
    if spread >= 0.50:
        reasons.add("EXTREME_SPREAD")
    if spread >= 0.10 and volume < 1_000_000:
        reasons.update({"HIGH_SPREAD", "LOW_VOLUME"})
    if vq < 0.25 and zero:
        reasons.update({"LOW_VOLUME_CONSISTENCY", "ZERO_VOLUME_GAPS"})
    if frag == "F3" and vq < 0.25:
        reasons.update({"F3_FRAGILITY", "LOW_VOLUME_CONSISTENCY"})
    if frag in ("F2", "F3") and vq <= 0.05 and volume < 5_000_000:
        reasons.update({f"{frag}_FRAGILITY", "LOW_VOLUME_CONSISTENCY"})
    if frag == "F3" and volume < 1_000_000:
        reasons.update({"F3_FRAGILITY", "LOW_VOLUME"})
    if not reasons:
        if spread >= 0.10:
            reasons.add("HIGH_SPREAD")
        if volume < 1_000_000:
            reasons.add("LOW_VOLUME")
        if vq < 0.35 and (volume < 2_000_000 or spread >= 0.05 or zero):
            reasons.add("LOW_VOLUME_CONSISTENCY")
    if reasons:
        reasons.update({"LOW_LIQUIDITY_RESTRICTED", "RESTRICTED_DEPLOY"})
    return reasons


def _compact_micro_base_sell_grids(profile, inp: V6InputContract, opportunity_notes: Dict[str, Any]):
    if not profile.sell_grids or len(profile.sell_grids) <= 2:
        return profile, opportunity_notes
    if profile.base_allocation_pct > 5 or profile.normal_buy_enabled:
        return profile, opportunity_notes
    role = _semantic_role(
        str(profile.scenario.regime_id or ""),
        str((opportunity_notes or {}).get("sub_profile_hint") or ""),
        set((opportunity_notes or {}).get("reason_codes") or []),
    )
    if role != "PARABOLIC_OVEREXTENDED":
        return profile, opportunity_notes
    base_pool = float(inp.bot_budget_usdt or 0) * float(profile.base_allocation_pct or 0) / 100.0
    min_notional = float(inp.min_notional or 10)
    if base_pool <= 0:
        return profile, opportunity_notes
    if all((base_pool * int(g.amount_pct or 0) / 100.0) >= min_notional for g in profile.sell_grids):
        return profile, opportunity_notes

    p = profile.copy()
    first = max(5, int(p.sell_grids[0].distance_pct or 5) + 1)
    second = max(first + 4, 14)
    p.sell_grids = [GridLevel(first, 60), GridLevel(second, 40)]
    modules = dict(p.modules or {})
    modules["micro_base_sell_grid_compacted"] = True
    p.modules = modules
    notes = dict(opportunity_notes or {})
    reason_codes = set(notes.get("reason_codes") or [])
    reason_codes.add("MICRO_BASE_SELL_GRID_COMPACTED")
    notes["reason_codes"] = sorted(reason_codes)
    notes["micro_base_sell_grid_compacted"] = True
    return quantize_profile(p), notes


def _r8_pb12_act_base_20_allowed(inp: V6InputContract) -> bool:
    bounce_confirmed = (
        (inp.fake_bounce_score is not None and inp.fake_bounce_score >= 60)
        or (inp.support_strength_score or 0) >= 60
        or ((inp.return_1h_pct or 0) > 0 and (inp.return_4h_pct or 0) >= -2.0)
    )
    data_quality_ok = (
        bool(inp.price_valid)
        and float(inp.data_gap_sec or 0) <= 0
        and float(inp.data_freshness_sec or 0) <= 300
        and int(inp.zero_volume_flag or 0) == 0
        and int(inp.candles_5m or 0) >= 200
    )
    return (
        bounce_confirmed
        and float(inp.spread_pct or 0) <= 0.25
        and float(inp.crash_velocity or 0) > -0.60
        and float(inp.return_4h_pct or 0) >= -2.0
        and data_quality_ok
    )


def _apply_v4_host_base_cap(profile, inp: V6InputContract, opportunity_notes: Dict[str, Any]):
    """V4 final overlay: cap host R7/R8 base after dynamic/profile repairs."""
    rid = str(profile.scenario.regime_id or "").upper()
    behavior = str(profile.scenario.behavior_id or "").upper()
    severity = str(profile.scenario.severity or "").upper()
    cap = None
    reason = ""

    if rid == "R7" and int(profile.base_allocation_pct or 0) > 25:
        cap = 25
        reason = "V4_HOST_R7_BASE_CAP"
    elif rid == "R8" and behavior in ("PB13", "PB14") and int(profile.base_allocation_pct or 0) > 15:
        cap = 15
        reason = f"V4_HOST_R8_{behavior}_BASE_CAP"
    elif (
        rid == "R8"
        and behavior == "PB12"
        and severity == "ACT"
        and int(profile.base_allocation_pct or 0) > 15
        and not _r8_pb12_act_base_20_allowed(inp)
    ):
        cap = 15
        reason = "V4_HOST_R8_PB12_ACT_CONDITIONAL_BASE_CAP"

    if cap is None:
        return profile, opportunity_notes

    p = profile.copy()
    p.base_allocation_pct = cap
    p.quote_allocation_pct = 100 - cap
    modules = dict(p.modules or {})
    modules["v4_host_base_cap"] = True
    modules["v4_host_base_cap_reason"] = reason
    p.modules = modules

    notes = dict(opportunity_notes or {})
    reason_codes = set(notes.get("reason_codes") or [])
    reason_codes.add(reason)
    notes["reason_codes"] = sorted(reason_codes)
    notes["v4_host_base_cap"] = {"base_pct": cap, "reason": reason}
    return quantize_profile(p), notes


def _decimal_floor(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    v = Decimal(str(max(value, 0.0)))
    s = Decimal(str(step))
    return float((v / s).to_integral_value(rounding=ROUND_DOWN) * s)


def _profile_order_feasibility_failures(profile, inp: V6InputContract) -> list[str]:
    price = float(inp.current_price or 0)
    if price <= 0:
        return ["price_invalid"]
    min_notional = float(inp.min_notional or 10)
    step = float(inp.step_size or 0.00001)
    tick = float(inp.tick_size or 0.01)
    min_qty = step
    budget = float(inp.bot_budget_usdt or 0)
    failures: list[str] = []

    def check(side: str, pool_usdt: float, grid: GridLevel) -> None:
        raw_notional = pool_usdt * int(grid.amount_pct or 0) / 100.0
        dist = abs(int(grid.distance_pct or 0))
        level_price = price * (1 - dist / 100.0) if side == "BUY" else price * (1 + dist / 100.0)
        rounded_price = _decimal_floor(level_price, tick)
        qty = raw_notional / rounded_price if rounded_price > 0 else 0.0
        rounded_qty = _decimal_floor(qty, step)
        rounded_notional = rounded_qty * rounded_price
        code = f"{side}_{dist}_{int(grid.amount_pct or 0)}"
        if rounded_price <= 0:
            failures.append(f"{code}:tick_price_invalid")
        if rounded_qty + 1e-12 < min_qty:
            failures.append(f"{code}:min_qty")
        if rounded_notional + 1e-9 < min_notional:
            failures.append(f"{code}:min_notional")

    quote_pool = budget * float(getattr(profile, "quote_allocation_pct", 0) or 0) / 100.0
    base_pool = budget * float(getattr(profile, "base_allocation_pct", 0) or 0) / 100.0
    if getattr(profile, "normal_buy_enabled", False):
        for grid in getattr(profile, "buy_grids", []) or []:
            check("BUY", quote_pool, grid)
    for grid in getattr(profile, "sell_grids", []) or []:
        check("SELL", base_pool, grid)
    return failures


def _controlled_risk_reward_score(
    inp: V6InputContract,
    profile,
    *,
    regime_id: str,
    deployable_hint: bool,
    reason_codes: set[str],
) -> Dict[str, Any]:
    spread = float(inp.spread_pct or 0)
    volume = float(inp.volume_24h or 0)
    vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    frag = str(inp.asset_fragility_class or "F1").upper()
    pve = float(inp.price_vs_ema200_pct or 0)
    ret24 = float(inp.return_24h_pct or 0)
    ret4 = float(inp.return_4h_pct or 0)
    atr = float(inp.atr_1h_pct or 0)
    rstab = float(inp.range_stability or 0)
    bb_pos = float(inp.bb_position if inp.bb_position is not None else 0.5)
    z = float(inp.z_score or 0)
    dd7 = float(inp.drawdown_7d_pct or 0)
    crash_velocity = float(inp.crash_velocity or 0)
    rid = str(regime_id or "").upper()

    trend_continuation = min(
        100.0,
        _score_0_100(pve, -2, 8) * 0.35
        + _score_0_100(ret24, -3, 8) * 0.25
        + _score_0_100(ret4, -1, 3) * 0.20
        + (15.0 if inp.higher_highs else 0.0)
        + (5.0 if (inp.ema20_slope or 0) > 0 else 0.0),
    )
    range_loop = min(100.0, rstab * 75.0 + max(0.0, 25.0 - abs(bb_pos - 0.5) * 50.0))
    volatility_profit = 100.0 - min(100.0, abs(atr - 2.0) * 25.0)
    liquidity_execution = min(
        100.0,
        (100.0 - min(100.0, spread * 500.0)) * 0.45
        + min(100.0, vq * 100.0) * 0.30
        + _score_0_100(volume, 250_000, 25_000_000) * 0.25,
    )
    mean_reversion = min(
        100.0,
        rstab * 40.0 + min(60.0, abs(bb_pos - 0.5) * 90.0 + abs(z) * 12.0),
    )

    reward_score = round(
        trend_continuation * (0.30 if rid in ("R1", "R5", "R6") else 0.18)
        + range_loop * (0.28 if rid in ("R2", "R3", "R4") else 0.18)
        + volatility_profit * 0.16
        + liquidity_execution * 0.22
        + mean_reversion * 0.16,
        2,
    )

    drawdown_risk = min(100.0, dd7 * 3.0)
    crash_risk = min(100.0, abs(min(0.0, crash_velocity)) * 30.0 + max(0.0, -ret24) * 2.0)
    spread_risk = min(100.0, spread * 500.0)
    liquidity_risk = max(0.0, 100.0 - liquidity_execution)
    overextension_risk = min(100.0, max(0.0, pve - 3.0) * 10.0 + max(0.0, bb_pos - 0.70) * 120.0 + max(0.0, z - 1.0) * 25.0)
    fragility_risk = {"F0": 0.0, "F1": 12.0, "F2": 30.0, "F3": 55.0}.get(frag, 20.0)
    risk_score = round(
        drawdown_risk * 0.22
        + crash_risk * 0.20
        + spread_risk * 0.18
        + liquidity_risk * 0.18
        + overextension_risk * 0.14
        + fragility_risk * 0.08,
        2,
    )
    penalty_multiplier = 1.10 if {"LOW_LIQUIDITY_RESTRICTED", "CONDITIONAL_PROBE_ONLY"} & reason_codes else 0.82
    risk_penalty_adjusted = round(risk_score * penalty_multiplier, 2)
    return {
        "objective": "maximize_controlled_risk_reward_not_minimize_risk",
        "reward_score": reward_score,
        "risk_score": risk_score,
        "risk_penalty_adjusted": risk_penalty_adjusted,
        "risk_reward_score": round(reward_score - risk_penalty_adjusted, 2),
        "base_allocation_pct": int(getattr(profile, "base_allocation_pct", 0) or 0),
        "deployable_hint": bool(deployable_hint),
        "components": {
            "trend_continuation_potential": round(trend_continuation, 2),
            "range_loop_potential": round(range_loop, 2),
            "volatility_profit_potential": round(volatility_profit, 2),
            "liquidity_execution_quality": round(liquidity_execution, 2),
            "mean_reversion_opportunity": round(mean_reversion, 2),
            "drawdown_risk": round(drawdown_risk, 2),
            "crash_risk": round(crash_risk, 2),
            "spread_risk": round(spread_risk, 2),
            "liquidity_risk": round(liquidity_risk, 2),
            "overextension_risk": round(overextension_risk, 2),
            "fragility_risk": round(fragility_risk, 2),
        },
    }


def _semantic_role(regime_id: str, sub_profile_hint: str, reason_codes: set[str]) -> str:
    hint = str(sub_profile_hint or "")
    if hint == "R8_HARD_BLOCK":
        return "R8_HARD_BLOCK"
    if hint == "R5_DEF_PARABOLIC_OVEREXTENDED":
        return "PARABOLIC_OVEREXTENDED"
    if "LOW_LIQUIDITY_RESTRICTED" in reason_codes:
        return "LOW_LIQUIDITY_RESTRICTED"
    if "CONDITIONAL_PROBE_ONLY" in reason_codes:
        return "R8_CAPITULATION_CONDITIONAL_PROBE"
    if hint == "R5_ACT_CLEAN_BREAKOUT":
        return "CLEAN_BREAKOUT"
    if hint == "R5_STD_POST_BREAKOUT_COOLDOWN":
        return "POST_BREAKOUT_COOLDOWN"
    if hint == "R5_DEF_PARABOLIC_OVEREXTENDED":
        return "PARABOLIC_OVEREXTENDED"
    if hint == "R5_DEF_OVEREXTENDED":
        return "OVEREXTENDED_MOMENTUM"
    if hint == "R6_RECOVERY_BREAKOUT" or str(regime_id or "").upper() == "R6":
        return "RECOVERY"
    return hint


def _apply_low_liq_restricted_profile(
    profile,
    inp: V6InputContract,
    opportunity_notes: Dict[str, Any],
    *,
    regime_id: str,
    sub_profile_hint: str,
) -> tuple[Any, Dict[str, Any]]:
    if sub_profile_hint in ("R8_HARD_BLOCK", "R5_DEF_PARABOLIC_OVEREXTENDED"):
        return profile, opportunity_notes
    reasons = _low_liq_reason_codes(inp)
    if not reasons:
        return profile, opportunity_notes

    p = profile.copy()
    rid = str(regime_id or p.scenario.regime_id or "").upper()
    hint = str(sub_profile_hint or "")
    overextended = rid == "R5" or "OVEREXTENDED" in hint
    p.base_allocation_pct = 5
    p.quote_allocation_pct = 95
    p.buyback_after_sell_enabled = True
    p.profit_sell_after_buyback_enabled = True
    p.sell_trailing_code = trailing_code_from_pct(1.4)
    p.buy_trailing_code = trailing_code_from_pct(1.4)
    p.buyback_trigger_code = profit_code_from_pct(8.0 if overextended else 4.5)
    p.buyback_trailing_code = trailing_code_from_pct(1.4)
    p.profit_sell_trigger_code = profit_code_from_pct(5.0 if overextended else 3.0)
    p.profit_sell_trailing_code = trailing_code_from_pct(1.4 if overextended else 1.1)

    if overextended:
        p.normal_buy_enabled = False
        p.buy_grids = []
        p.sell_grids = [GridLevel(5, 45), GridLevel(10, 35), GridLevel(18, 20)]
        semantic = "OVEREXTENDED_LOW_LIQUIDITY"
    elif rid == "R4":
        p.normal_buy_enabled = True
        p.buy_grids = [GridLevel(-6, 10), GridLevel(-12, 25), GridLevel(-20, 65)]
        p.sell_grids = [GridLevel(3, 45), GridLevel(6, 35), GridLevel(10, 20)]
        semantic = "LOW_LIQUIDITY_RESTRICTED"
    elif rid == "R8":
        p.base_allocation_pct = 10
        p.quote_allocation_pct = 90
        p.normal_buy_enabled = True
        p.buy_grids = [GridLevel(-6, 10), GridLevel(-12, 25), GridLevel(-20, 65)]
        p.sell_grids = [GridLevel(3, 45), GridLevel(6, 35), GridLevel(10, 20)]
        semantic = "R8_LOW_LIQUIDITY_RESTRICTED"
    else:
        p.base_allocation_pct = 10
        p.quote_allocation_pct = 90
        p.normal_buy_enabled = True
        p.buy_grids = [GridLevel(-3, 10), GridLevel(-6, 25), GridLevel(-10, 65)]
        p.sell_grids = [GridLevel(2, 45), GridLevel(5, 35), GridLevel(9, 20)]
        semantic = "R3_RESTRICTED_LOW_LIQUIDITY_COMPRESSION"

    modules = dict(p.modules or {})
    modules.update(
        {
            "normal_buy_grid": p.normal_buy_enabled,
            "sell_grid": True,
            "profit_buyback_after_sell": True,
            "profit_sell_after_buyback": True,
            "controlled_grid": True,
            "params_valid": True,
            "new_buys_status": "paused" if not p.normal_buy_enabled else "restricted",
            "max_total_exposure_pct": 15,
            "semantic_role": semantic,
            "low_liquidity_restricted": True,
        }
    )
    p.modules = modules
    p = quantize_profile(p)

    merged_reasons = set(opportunity_notes.get("reason_codes") or [])
    merged_reasons.update(reasons)
    if overextended:
        merged_reasons.add("OVEREXTENDED_LOW_LIQUIDITY")
    opportunity_notes = dict(opportunity_notes)
    opportunity_notes.update(
        {
            "deployable": False,
            "params_valid": True,
            "controlled_grid": True,
            "semantic_role": semantic,
            "reason_codes": sorted(merged_reasons),
        }
    )
    return p, opportunity_notes


def _add_semantic_contract_notes(
    profile,
    opportunity_notes: Dict[str, Any],
    *,
    regime_id: str,
    sub_profile_hint: str,
) -> Dict[str, Any]:
    notes = dict(opportunity_notes)
    reason_codes = set(notes.get("reason_codes") or [])
    if sub_profile_hint == "R8_CAPITULATION_CONDITIONAL_PROBE":
        reason_codes.update({"DEEP_CRASH", "CAPITULATION", "CONDITIONAL_PROBE_ONLY"})
        notes["deployable"] = False
        notes["conditional_probe"] = {
            "enabled": True,
            "buy_distances_pct": [12, 22, 35],
            "buy_amounts_pct": [10, 25, 65],
            "max_total_exposure_pct": 15,
        }
    notes["semantic_role"] = notes.get("semantic_role") or _semantic_role(
        regime_id,
        sub_profile_hint,
        reason_codes,
    )
    if profile is not None:
        modules = dict(profile.modules or {})
        modules["semantic_role"] = notes["semantic_role"]
        profile.modules = modules
    notes["reason_codes"] = sorted(reason_codes)
    notes["params_valid"] = notes.get("params_valid", True)
    notes["controlled_grid"] = notes.get("controlled_grid", True)
    notes["profile_resolver_objective"] = "maximize_controlled_risk_reward_not_minimize_risk"
    return notes


class V6Engine:
    """Scenario identity + catalog profile + adjuster pipeline."""

    def run(
        self,
        inp: V6InputContract,
        *,
        sticky_key: str | None = None,
        prev_regime_id: str | None = None,
        prev_sub_profile_hint: str | None = None,
        prev_regime_label: str | None = None,
    ) -> V6FinalProfile:
        errors = validate_input_contract(inp)
        classified = classify_scenario(inp)
        classified, sticky_meta = apply_regime_stickiness(
            classified,
            sticky_key=sticky_key or f"pa:{getattr(inp, 'symbol', '') or 'NA'}",
            prev_regime_id=prev_regime_id,
            prev_sub_profile_hint=prev_sub_profile_hint,
            prev_regime_label=prev_regime_label,
        )
        behavior_id = resolve_behavior(classified)
        logger.info(
            "V6 scenario resolved regime=%s behavior=%s label=%s sticky_held=%s raw=%s",
            classified.regime_id,
            behavior_id,
            classified.label,
            sticky_meta.get("held"),
            sticky_meta.get("raw_regime_id"),
        )
        delta_pre, dq_risk, adjuster_trace = run_adjusters_with_trace(inp)
        logger.info("V6 adjusters applied tags=%s", delta_pre.tags)
        severity = resolve_severity(inp, data_quality_risk=dq_risk)
        severity = apply_severity_override(severity, delta_pre.severity_override)
        label_lc = str(classified.label or "").lower()
        if severity == "ACT" and (
            classified.sub_profile_hint in (
                "R1_STD_TREND_COOLDOWN",
                "R1_STD_PULLBACK",
                "R3_STD_UPTREND_OVERHEAT_COOLDOWN",
                "R5_STD_POST_BREAKOUT_COOLDOWN",
            )
            or any(term in label_lc for term in ("tepe", "dağılım", "zayıflama", "geri çekilme riski", "aşırı"))
        ):
            severity = "STD"
        scenario = to_scenario_identity(classified, severity)
        scenario.behavior_id = behavior_id
        terminal = find_terminal_for_classifier(
            scenario.regime_id,
            scenario.sub_id,
            scenario.micro_id,
            behavior_id,
        )
        if terminal:
            scenario.sub_id = str(terminal["sub_id"])
            scenario.micro_id = str(terminal["micro_id"])
            scenario.terminal_id = str(terminal["terminal_id"])
        # The former generated shelf/catalog library remains on disk only for
        # rollback tooling. Live PA/DM resolution never reads or records it.
        profile = resolve_net_profile(classified, inp, severity)
        from app.services.dynamic_param_score.v6.net_profile_library import (
            build_classification_trace,
            canonical_headline_for_key,
        )

        classification_trace = build_classification_trace(
            classified,
            inp,
            selected_profile_key=profile.profile_id,
        )
        logger.info(
            "V6 profile selected id=%s severity=%s headline=%s",
            profile.profile_id,
            severity,
            classification_trace.get("canonical_headline"),
        )

        btc_risk = next((int(t.split("_")[1][1:]) * 25 for t in delta_pre.tags if t.startswith("BTC_B")), 0)
        vol_score = 0
        for t in delta_pre.tags:
            if t.startswith("V") and len(t) == 2 and t[1].isdigit():
                vol_score = int(t[1]) * 20

        delta = cap_total_delta(delta_pre, inp, btc_risk=btc_risk, volatility_score=vol_score)
        adjusted = apply_delta(profile, delta)
        val_errors = validate_profile(adjusted)
        if val_errors:
            logger.warning("V6 profile validation after adjust: %s", val_errors)

        adjusted, budget_notes = exchange_validate(adjusted, inp)
        exchange_notes = list(budget_notes or [])
        opportunity_notes: Dict[str, Any] = {}
        adjusted, opportunity_notes = apply_v6_opportunity_postprocess(
            adjusted, inp, adjuster_trace, scenario.regime_id,
            severity=severity,
            sub_profile_hint=getattr(classified, "sub_profile_hint", "") or "",
        )
        adjusted, opportunity_notes = _apply_low_liq_restricted_profile(
            adjusted,
            inp,
            opportunity_notes,
            regime_id=scenario.regime_id,
            sub_profile_hint=getattr(classified, "sub_profile_hint", "") or "",
        )
        adjusted, opportunity_notes = _compact_micro_base_sell_grids(
            adjusted,
            inp,
            opportunity_notes,
        )
        adjusted, opportunity_notes = _apply_v4_host_base_cap(
            adjusted,
            inp,
            opportunity_notes,
        )
        preserve_sell_management_shape = (
            adjusted.base_allocation_pct <= 5
            and not adjusted.normal_buy_enabled
            and scenario.regime_id in ("R5", "R8")
        )
        if not preserve_sell_management_shape:
            adjusted, final_budget_notes = exchange_validate(adjusted, inp)
            if final_budget_notes:
                exchange_notes.extend(f"final_{note}" for note in final_budget_notes)
                reason_codes = set(opportunity_notes.get("reason_codes") or [])
                reason_codes.update(final_budget_notes)
                opportunity_notes["reason_codes"] = sorted(reason_codes)
                opportunity_notes["budget_adjusted_final"] = True
        sealed_library = bool((profile.modules or {}).get("net_profile_library"))
        buy_guard_notes: Dict[str, Any] = {}
        if sealed_library:
            # Operator 4+4 contract is authoritative; skip mandatory-buy reshape.
            buy_guard_notes = {"mandatory_deep_buy_skipped": "net_profile_sealed_4x4"}
        else:
            adjusted, buy_guard_notes = enforce_mandatory_deep_buy(
                adjusted,
                inp,
                reason="FINAL_OUTPUT_BUY_SURFACE",
            )
            # Explicitly closed sides in the operator library are contractual.
            if not profile.normal_buy_enabled:
                adjusted.normal_buy_enabled = False
                adjusted.buy_grids = []
                buy_guard_notes = {"mandatory_deep_buy_skipped": "net_profile_buy_closed"}
            if not profile.sell_grids:
                adjusted.sell_grids = []
        if sealed_library:
            # Restore authored ladders after opportunity / host-cap / compact steps.
            adjusted = seal_net_profile_shape(adjusted, profile)
        if buy_guard_notes:
            opportunity_notes.update(buy_guard_notes)
            if buy_guard_notes.get("mandatory_deep_buy_applied"):
                reason_codes = set(opportunity_notes.get("reason_codes") or [])
                reason_codes.add("MANDATORY_DEEP_BUY")
                opportunity_notes["reason_codes"] = sorted(reason_codes)
        opportunity_notes = _add_semantic_contract_notes(
            adjusted,
            opportunity_notes,
            regime_id=scenario.regime_id,
            sub_profile_hint=getattr(classified, "sub_profile_hint", "") or "",
        )
        opportunity_notes["risk_reward"] = _controlled_risk_reward_score(
            inp,
            adjusted,
            regime_id=scenario.regime_id,
            deployable_hint=opportunity_notes.get("deployable", True) is not False,
            reason_codes=set(opportunity_notes.get("reason_codes") or []),
        )
        # Keep the operator-authored user copy after technical adjusters run.
        adjusted.scenario.name = str((adjusted.modules or {}).get("headline") or classified.label)
        adjusted.scenario.severity = scenario.severity
        val_errors = validate_profile(adjusted)
        if val_errors:
            logger.warning("V6 profile validation after opportunity: %s", val_errors)
        from app.services.dynamic_param_score.v6.v6_opportunity import assess_operational_validity

        validity = assess_operational_validity(adjusted)
        opportunity_notes["operational_validity"] = validity.to_dict()
        has_trade_surface = validity.valid
        reason_codes = set(opportunity_notes.get("reason_codes") or [])
        order_feasibility_failures = _profile_order_feasibility_failures(adjusted, inp)
        if order_feasibility_failures:
            reason_codes.add("ORDER_FEASIBILITY_RESTRICTED")
            opportunity_notes["reason_codes"] = sorted(reason_codes)
            opportunity_notes["order_feasibility_failures"] = order_feasibility_failures
        restricted_by_liquidity = (
            opportunity_notes.get("deployable") is False
            and bool(
                {
                    "LOW_LIQUIDITY_RESTRICTED",
                    "RESTRICTED_DEPLOY",
                    "R4_RESTRICTED_UNSTABLE",
                    "HIGH_SPREAD",
                    "LOW_VOLUME",
                    "UNSTABLE_RANGE",
                }
                & reason_codes
            )
        )
        conditional_probe_only = (
            opportunity_notes.get("deployable") is False
            and "CONDITIONAL_PROBE_ONLY" in reason_codes
        )
        operator_auto_apply = bool((adjusted.modules or {}).get("automatic_apply", True))
        deployable = (
            "price_valid_false" not in errors
            and has_trade_surface
            and not restricted_by_liquidity
            and not conditional_probe_only
            and not order_feasibility_failures
            and operator_auto_apply
        )
        block_reason = "price_valid_false" if not inp.price_valid else None
        if not has_trade_surface:
            deployable = False
            block_reason = block_reason or "technical_block"
        elif restricted_by_liquidity:
            deployable = False
            block_reason = block_reason or "restricted_by_liquidity"
        elif conditional_probe_only:
            deployable = False
            block_reason = block_reason or "conditional_probe_only"
        elif order_feasibility_failures:
            deployable = False
            block_reason = block_reason or "order_feasibility_restricted"
        elif not operator_auto_apply:
            deployable = False
            block_reason = block_reason or "operator_profile_auto_apply_disabled"
        elif val_errors and not has_trade_surface:
            deployable = False
            block_reason = block_reason or "profile_validation_failed"
        adjuster_trace = append_post_pipeline_trace(
            adjuster_trace,
            delta_pre=delta_pre,
            delta_capped=delta,
            budget_notes=[],
            exchange_notes=exchange_notes,
        )
        catalog_id, final_id, full_id = build_profile_ids(adjusted, delta.tags)

        return V6FinalProfile(
            catalog_profile_id=catalog_id,
            final_profile_id=final_id,
            full_param_id=full_id,
            profile=adjusted,
            deployable=deployable,
            deploy_block_reason=block_reason,
            adjuster_tags=list(delta.tags),
            telemetry={
                "engine_version": ENGINE_VERSION,
                "adjuster_trace": adjuster_trace,
                "regime_stickiness": sticky_meta,
                "scenario": {
                    "regime_id": scenario.regime_id,
                    "sub_id": scenario.sub_id,
                    "micro_id": scenario.micro_id,
                    "behavior_id": behavior_id,
                    "severity": severity,
                    "label": classified.label,
                    "sub_profile_hint": getattr(classified, "sub_profile_hint", "") or "",
                    "net_profile_key": adjusted.profile_id,
                    "selected_profile_key": adjusted.profile_id,
                    "canonical_headline": canonical_headline_for_key(adjusted.profile_id),
                    "headline": (adjusted.modules or {}).get("headline"),
                    "why": (adjusted.modules or {}).get("why"),
                    "automatic_apply_label": (adjusted.modules or {}).get("automatic_apply_label"),
                    "hard_block": bool(getattr(classified, "hard_block", False)),
                    "hard_block_reason": list(getattr(classified, "hard_block_reasons", ()) or ()),
                },
                "classification_trace": classification_trace,
                "budget": budget_scale(adjusted, inp),
                "validation_errors": val_errors,
                "input_errors": errors,
                "budget_notes": budget_notes,
                "delta": delta.__dict__,
                "opportunity_notes": opportunity_notes,
            },
        )


def calculate_decision_v6(
    symbol: str,
    market_data: MarketDataBundle,
    portfolio_state: PortfolioState,
    exchange_constraints: ExchangeConstraints,
    bot_context: BotContext,
) -> DynamicParamDecision:
    """Bridge: V6 engine → legacy DynamicParamDecision shell."""
    logger.info("DynamicParamScoreEngine version=v6 symbol=%s", symbol)
    ind = compute_indicators(market_data, portfolio_state)
    price = float(market_data.ticker_price or 0)
    budget = float(bot_context.budget_usdt or 0)
    inp = build_v6_input_contract(
        symbol=symbol,
        bot_budget_usdt=budget,
        current_price=price,
        ind=ind,
        market=market_data,
        exchange=exchange_constraints,
    )
    sticky_key = bot_context.regime_sticky_key
    if not sticky_key:
        if bot_context.bot_id:
            sticky_key = f"dm:{int(bot_context.bot_id)}:{symbol.upper()}"
        else:
            sticky_key = f"pa:{symbol.upper()}"
    result = V6Engine().run(
        inp,
        sticky_key=sticky_key,
        prev_regime_id=bot_context.prev_regime_id,
        prev_sub_profile_hint=bot_context.prev_sub_profile_hint,
        prev_regime_label=bot_context.prev_regime_label,
    )
    scenario = result.telemetry.get("scenario") or {}
    bot_params = v6_final_to_bot_params(result, bot_budget_usdt=budget)
    opp = result.telemetry.get("opportunity_notes") or {}
    display_base = v6_final_to_telemetry_extras(
        result,
        bot_budget_usdt=budget,
        adjuster_trace=result.telemetry.get("adjuster_trace") or [],
    )
    scen_id = dict(display_base.get("scenario_identity") or {})
    scen_id.update(
        {
            "canonical_headline": scenario.get("canonical_headline") or scen_id.get("canonical_headline"),
            "headline": scenario.get("headline") or scen_id.get("headline"),
            "selected_profile_key": scenario.get("selected_profile_key")
            or scenario.get("net_profile_key")
            or scen_id.get("selected_profile_key"),
            "net_profile_key": scenario.get("net_profile_key") or scen_id.get("net_profile_key"),
            "sub_profile_hint": scenario.get("sub_profile_hint") or scen_id.get("sub_profile_hint") or "",
            "hard_block": scenario.get("hard_block"),
            "hard_block_reason": scenario.get("hard_block_reason") or [],
        }
    )
    display_base["scenario_identity"] = scen_id
    display_base["classification_trace"] = result.telemetry.get("classification_trace") or {}
    v6_display = enrich_v6_display(
        display_base,
        adjuster_trace=result.telemetry.get("adjuster_trace") or [],
        deployable=result.deployable,
        deploy_block_reason=result.deploy_block_reason,
        opportunity_notes=opp,
    )
    explain = build_v6_opportunity_explain(
        symbol,
        str(scenario.get("regime_id", "R2")),
        str(scenario.get("label", "")),
        result.profile,
        result.telemetry.get("adjuster_trace") or [],
        opp,
    )
    from app.services.dynamic_param_score.v6.v6_opportunity import resolve_v6_apply_policy

    final_action = "CONTROLLED_GRID"
    pa_soft = bool(
        bot_params
        and (
            bot_params.sell_grid_count
            or bot_params.buy_grid_count
            or bot_params.rebuy_enabled
        )
    )
    policy = resolve_v6_apply_policy(
        deployable=result.deployable,
        params=bot_params,
        final_action=final_action,
    )
    logger.info("V6 BotParams mapped profile=%s rebuy=%s", result.catalog_profile_id, bot_params.rebuy_enabled)
    return DynamicParamDecision(
        decision_id=DynamicParamDecision.new_id(),
        symbol=symbol.upper(),
        timestamp=int(time.time() * 1000),
        run_source=bot_context.run_source,
        final_action=final_action,
        deployable=result.deployable,
        param_score=70,
        confidence_score=70,
        risk_score=40,
        regime_tag=str(scenario.get("regime_id", "R2")),
        risk_state="DEFENSIVE" if result.profile.scenario.severity == "DEF" else "NORMAL",
        selected_profile_name=result.catalog_profile_id,
        selected_profile_bucket="V6",
        params=bot_params,
        safety_gates=[],
        blocking_reasons=[result.deploy_block_reason] if result.deploy_block_reason else [],
        warnings=[],
        explain=explain,
        telemetry={
            "engine_version": ENGINE_VERSION,
            "pool_version": POOL_VERSION_V6,
            "net_profile": {
                "key": scenario.get("net_profile_key") or result.profile.profile_id,
                "headline": scenario.get("headline") or result.profile.scenario.name,
                "why": scenario.get("why") or (result.profile.modules or {}).get("why"),
                "automatic_apply_label": scenario.get("automatic_apply_label")
                or (result.profile.modules or {}).get("automatic_apply_label"),
                "library_version": "net_profiles_2026_08",
            },
            "apply_policy": policy,
            "pa_soft_deployable": pa_soft,
            "classification_trace": result.telemetry.get("classification_trace") or {},
            "v6_display": v6_display,
            "v6_final": {
                "catalog_profile_id": result.catalog_profile_id,
                "final_profile_id": result.final_profile_id,
                "full_param_id": result.full_param_id,
                "deployable": result.deployable,
                "deploy_block_reason": result.deploy_block_reason,
                "profile": _profile_to_dict(result.profile),
                **result.telemetry,
            },
        },
    )


def _profile_to_dict(profile) -> Dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "base_allocation_pct": profile.base_allocation_pct,
        "quote_allocation_pct": profile.quote_allocation_pct,
        "normal_buy_enabled": profile.normal_buy_enabled,
        "buy_grids": [{"distance_pct": g.distance_pct, "amount_pct": g.amount_pct} for g in profile.buy_grids],
        "sell_grids": [{"distance_pct": g.distance_pct, "amount_pct": g.amount_pct} for g in profile.sell_grids],
        "sell_trailing_code": profile.sell_trailing_code,
        "buy_trailing_code": profile.buy_trailing_code,
        "buyback_after_sell_enabled": profile.buyback_after_sell_enabled,
        "buyback_trigger_code": profile.buyback_trigger_code,
        "profit_sell_trigger_code": profile.profit_sell_trigger_code,
    }
