"""V6 live engine — classify → catalog → adjust → quantize → validate."""

from __future__ import annotations

import logging
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
from app.services.dynamic_param_score.v6.adjusters.pipeline import run_adjusters
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
from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile
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
from app.services.dynamic_param_score.v6.v6_scenario_tree import find_terminal_for_classifier
from app.services.dynamic_param_score.v6.v6_severity_resolver import apply_severity_override, resolve_severity
from app.services.dynamic_param_score.v6.v6_opportunity import (
    apply_v6_opportunity_postprocess,
    build_v6_opportunity_explain,
)

logger = logging.getLogger(__name__)


def _strong_low_liq_reason_codes(inp: V6InputContract) -> set[str]:
    spread = float(inp.spread_pct or 0)
    volume = float(inp.volume_24h or 0)
    vq = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    frag = str(inp.asset_fragility_class or "F1").upper()
    reasons: set[str] = set()
    if spread >= 0.50:
        reasons.add("EXTREME_SPREAD")
    if spread >= 0.10 and volume < 1_000_000:
        reasons.update({"HIGH_SPREAD", "LOW_VOLUME"})
    if vq < 0.25 and int(inp.zero_volume_flag or 0) > 0:
        reasons.update({"LOW_VOLUME_CONSISTENCY", "ZERO_VOLUME_GAPS"})
    if frag == "F3" and volume < 1_000_000:
        reasons.update({"F3_FRAGILITY", "LOW_VOLUME"})
    if reasons:
        reasons.update({"LOW_LIQUIDITY_RESTRICTED", "RESTRICTED_DEPLOY"})
    return reasons


def _semantic_role(regime_id: str, sub_profile_hint: str, reason_codes: set[str]) -> str:
    hint = str(sub_profile_hint or "")
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
    reasons = _strong_low_liq_reason_codes(inp)
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
    return notes


class V6Engine:
    """Scenario identity + catalog profile + adjuster pipeline."""

    def run(self, inp: V6InputContract) -> V6FinalProfile:
        errors = validate_input_contract(inp)
        classified = classify_scenario(inp)
        behavior_id = resolve_behavior(classified)
        logger.info(
            "V6 scenario resolved regime=%s behavior=%s label=%s",
            classified.regime_id,
            behavior_id,
            classified.label,
        )
        delta_pre, dq_risk, adjuster_trace = run_adjusters_with_trace(inp)
        logger.info("V6 adjusters applied tags=%s", delta_pre.tags)
        severity = resolve_severity(inp, data_quality_risk=dq_risk)
        severity = apply_severity_override(severity, delta_pre.severity_override)
        label_lc = str(classified.label or "").lower()
        if severity == "ACT" and (
            classified.sub_profile_hint in ("R1_STD_TREND_COOLDOWN", "R1_STD_PULLBACK")
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
        terminal_id = scenario.terminal_id

        profile = get_profile(
            scenario.regime_id,
            scenario.sub_id,
            scenario.micro_id,
            behavior_id,
            severity,
            terminal_id=terminal_id,
        )
        if profile is None:
            profile = get_profile(
                scenario.regime_id, scenario.sub_id, scenario.micro_id, behavior_id, "STD",
                terminal_id=terminal_id,
            )
        if profile is None:
            from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile_by_regime_behavior
            profile = get_profile_by_regime_behavior(scenario.regime_id, behavior_id, severity)
        if profile is None:
            from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile_by_regime_behavior
            profile = get_profile_by_regime_behavior(scenario.regime_id, behavior_id, "STD")
        if profile is None:
            raise LookupError(
                f"v6_catalog_miss:{scenario.regime_id}-{scenario.sub_id}-{scenario.micro_id}:{behavior_id}:{severity}"
            )
        logger.info(
            "V6 profile selected id=%s severity=%s",
            profile.profile_id,
            severity,
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
        opportunity_notes = _add_semantic_contract_notes(
            adjusted,
            opportunity_notes,
            regime_id=scenario.regime_id,
            sub_profile_hint=getattr(classified, "sub_profile_hint", "") or "",
        )
        adjusted.scenario.name = classified.label
        adjusted.scenario.severity = scenario.severity
        val_errors = validate_profile(adjusted)
        if val_errors:
            logger.warning("V6 profile validation after opportunity: %s", val_errors)
        from app.services.dynamic_param_score.v6.v6_opportunity import (
            assess_operational_validity,
            is_profile_operational,
        )

        validity = assess_operational_validity(adjusted)
        opportunity_notes["operational_validity"] = validity.to_dict()
        has_trade_surface = validity.valid
        reason_codes = set(opportunity_notes.get("reason_codes") or [])
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
        deployable = (
            "price_valid_false" not in errors
            and has_trade_surface
            and not restricted_by_liquidity
            and not conditional_probe_only
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
                "scenario": {
                    "regime_id": scenario.regime_id,
                    "sub_id": scenario.sub_id,
                    "micro_id": scenario.micro_id,
                    "behavior_id": behavior_id,
                    "severity": severity,
                    "label": classified.label,
                    "sub_profile_hint": getattr(classified, "sub_profile_hint", "") or "",
                },
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
    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    bot_params = v6_final_to_bot_params(result, bot_budget_usdt=budget)
    opp = result.telemetry.get("opportunity_notes") or {}
    v6_display = enrich_v6_display(
        v6_final_to_telemetry_extras(
            result,
            bot_budget_usdt=budget,
            adjuster_trace=result.telemetry.get("adjuster_trace") or [],
        ),
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
            "apply_policy": policy,
            "pa_soft_deployable": pa_soft,
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
