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
from app.services.dynamic_param_score.v6.domain.types import V6FinalProfile, V6InputContract
from app.services.dynamic_param_score.v6.v6_apply_delta import apply_delta
from app.services.dynamic_param_score.v6.v6_behavior_resolver import resolve_behavior
from app.services.dynamic_param_score.v6.v6_budget_scaler import budget_scale
from app.services.dynamic_param_score.v6.v6_delta_limiter import cap_total_delta
from app.services.dynamic_param_score.v6.v6_exchange_validator import exchange_validate
from app.services.dynamic_param_score.v6.v6_indicator_adapter import build_v6_input_contract
from app.services.dynamic_param_score.v6.v6_input_contract import validate_input_contract
from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (
    POOL_VERSION_V6,
    v6_final_to_bot_params,
    v6_final_to_telemetry_extras,
)
from app.services.dynamic_param_score.v6.v6_scenario_classifier import classify_scenario, to_scenario_identity
from app.services.dynamic_param_score.v6.v6_scenario_tree import find_terminal_for_classifier
from app.services.dynamic_param_score.v6.v6_severity_resolver import apply_severity_override, resolve_severity
from app.services.dynamic_param_score.v6.v6_ui_explainer import build_profile_ids

logger = logging.getLogger(__name__)


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
        adjuster_trace = append_post_pipeline_trace(
            adjuster_trace,
            delta_pre=delta_pre,
            delta_capped=delta,
            budget_notes=[],
            exchange_notes=exchange_notes,
        )
        catalog_id, final_id, full_id = build_profile_ids(adjusted, delta.tags)

        deployable = "price_valid_false" not in errors
        block_reason = "price_valid_false" if not inp.price_valid else None
        if val_errors:
            deployable = False
            block_reason = block_reason or "profile_validation_failed"

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
                },
                "budget": budget_scale(adjusted, inp),
                "validation_errors": val_errors,
                "input_errors": errors,
                "budget_notes": budget_notes,
                "delta": delta.__dict__,
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
    v6_display = v6_final_to_telemetry_extras(
        result,
        bot_budget_usdt=budget,
        adjuster_trace=result.telemetry.get("adjuster_trace") or [],
    )
    logger.info("V6 BotParams mapped profile=%s rebuy=%s", result.catalog_profile_id, bot_params.rebuy_enabled)
    return DynamicParamDecision(
        decision_id=DynamicParamDecision.new_id(),
        symbol=symbol.upper(),
        timestamp=int(time.time() * 1000),
        run_source=bot_context.run_source,
        final_action="CONTROLLED_GRID" if result.deployable else "WAIT",
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
        explain=f"V6 {scenario.get('label', '')} · {result.final_profile_id}",
        telemetry={
            "engine_version": ENGINE_VERSION,
            "pool_version": POOL_VERSION_V6,
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
