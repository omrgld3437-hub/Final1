"""Dynamic Param Score Engine — V6-only central decision motor."""

from __future__ import annotations

import logging
import os
from typing import Optional

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.action_detail import build_action_detail
from app.services.dynamic_param_score.adapters import params_to_grid_config
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import (
    BotContext,
    DynamicParamDecision,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
from app.services.dynamic_param_score.persistence import persist_decision
from app.services.dynamic_param_score.utils import json_safe
from app.services.dynamic_param_score.v6.engine import calculate_decision_v6

logger = logging.getLogger(__name__)


class DynamicParamScoreEngine:
    """Single central motor for Param Assistant and Dynamic Mode (V6)."""

    def calculate_decision(
        self,
        symbol: str,
        market_data: MarketDataBundle,
        portfolio_state: PortfolioState,
        exchange_constraints: ExchangeConstraints,
        bot_context: BotContext,
        *,
        persist: bool = True,
    ) -> DynamicParamDecision:
        version = os.getenv("DPS_ENGINE_VERSION", "v6").lower()
        if version == "v5":
            raise RuntimeError(
                "Dynamic Param V5 has been removed. Use DPS_ENGINE_VERSION=v6 (default)."
            )
        logger.info("DynamicParamScoreEngine version=v6 route=calculate_decision symbol=%s", symbol)
        decision = calculate_decision_v6(
            symbol,
            market_data,
            portfolio_state,
            exchange_constraints,
            bot_context,
        )
        ind = compute_indicators(market_data, portfolio_state)
        from app.services.dynamic_param_score.v6.v6_pa_telemetry import enrich_v6_decision_for_pa

        decision = enrich_v6_decision_for_pa(
            decision,
            market_data=market_data,
            portfolio=portfolio_state,
            constraints=exchange_constraints,
            indicators=ind,
        )
        action_detail = build_action_detail(
            decision.params,
            decision.final_action,
            decision.selected_profile_name,
            {},
            list(decision.warnings or []),
        )
        tel = dict(decision.telemetry or {})
        tel["pool_version"] = "v6"
        v6d = tel.get("v6_display") or {}
        if isinstance(v6d, dict):
            v6d["pool_version"] = "v6"
            tel["v6_display"] = v6d
        decision = DynamicParamDecision(
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            timestamp=decision.timestamp,
            run_source=decision.run_source,
            final_action=decision.final_action,
            deployable=decision.deployable,
            param_score=decision.param_score,
            confidence_score=decision.confidence_score,
            risk_score=decision.risk_score,
            regime_tag=decision.regime_tag,
            risk_state=decision.risk_state,
            selected_profile_name=decision.selected_profile_name,
            selected_profile_bucket=decision.selected_profile_bucket,
            params=decision.params,
            safety_gates=decision.safety_gates,
            blocking_reasons=decision.blocking_reasons,
            warnings=decision.warnings,
            explain=decision.explain,
            telemetry=json_safe(tel),
            action_detail=action_detail,
        )
        if persist:
            try:
                persist_decision(
                    decision,
                    market_data,
                    portfolio_state,
                    bot_id=bot_context.bot_id,
                    round_id=bot_context.current_round_id,
                    raw_indicators=ind.to_dict(),
                    pre_safety_params=decision.params.to_dict() if decision.params else None,
                )
            except Exception as e:
                logger.warning("DPS persist failed: %s", e)
        return decision

    @classmethod
    def select_profile(
        cls,
        symbol: str,
        budget: float,
        market_data: MarketDataBundle,
        *,
        portfolio_state: Optional[PortfolioState] = None,
        exchange_constraints: Optional[ExchangeConstraints] = None,
        bot_context: Optional[BotContext] = None,
    ) -> dict:
        engine = cls()
        ctx = bot_context or BotContext(run_source="param_assistant", budget_usdt=budget)
        portfolio = portfolio_state or PortfolioState(
            base_balance=0.0,
            quote_balance=budget,
            base_value_usdt=0.0,
            quote_value_usdt=budget,
            total_equity_usdt=budget,
            current_base_exposure_frac=0.0,
        )
        constraints = exchange_constraints or ExchangeConstraints(
            min_notional=C.DEFAULT_MIN_NOTIONAL_USDT,
            step_size=0.0001,
            tick_size=0.01,
            min_qty=0.0001,
            taker_fee_pct=0.1,
            maker_fee_pct=0.1,
            estimated_slippage_pct=0.05,
        )
        decision = engine.calculate_decision(
            symbol, market_data, portfolio, constraints, ctx,
        )
        return cls.build_selection_trace(
            symbol=symbol,
            market_signature=(decision.telemetry or {}).get("market_signature") or {},
            pool_selection={},
            params=decision.params,
            final_action=decision.final_action,
            decision=decision,
        )

    @staticmethod
    def build_selection_trace(
        *,
        symbol: str,
        market_signature: dict,
        pool_selection: dict,
        params,
        final_action: str,
        decision: Optional[DynamicParamDecision] = None,
    ) -> dict:
        tel = (decision.telemetry or {}) if decision else {}
        v6d = tel.get("v6_display") or {}
        dps = (params.to_dict() if params else {}) or {}
        buy_ladder = dps.get("buy_grid_ladder_pcts") or v6d.get("buy_grid_distances_pct") or []
        sell_ladder = dps.get("sell_grid_ladder_pcts") or v6d.get("sell_grid_distances_pct") or []
        scen = v6d.get("scenario_identity") or {}
        return {
            "symbol": symbol,
            "profile_id": v6d.get("profile_id") or decision.selected_profile_name if decision else None,
            "final_profile_id": v6d.get("final_profile_id"),
            "scenario": scen or market_signature.get("scenario"),
            "behavior_id": v6d.get("behavior_id"),
            "severity": v6d.get("severity"),
            "final_action": final_action,
            "base_alloc_frac": dps.get("base_alloc_frac"),
            "quote_alloc_frac": dps.get("quote_alloc_frac"),
            "buy_grid_count": dps.get("buy_grid_count"),
            "sell_grid_count": dps.get("sell_grid_count"),
            "buy_grid_ladder_pcts": buy_ladder,
            "sell_grid_ladder_pcts": sell_ladder,
            "pool_version": "v6",
            "engine_version": tel.get("engine_version"),
            "adjuster_trace": v6d.get("adjuster_trace"),
            "market_signature": market_signature,
            "param_score": decision.param_score if decision else None,
        }

    @classmethod
    def decision_to_overlay(cls, decision: DynamicParamDecision) -> Optional[dict]:
        if decision.deployable and decision.params:
            tel = decision.telemetry or {}
            overlay = params_to_grid_config(
                decision.params,
                final_action=decision.final_action,
                pool_version=tel.get("pool_version") or "v6",
            )
            if tel.get("rebalance_plan"):
                overlay["rebalance_plan"] = tel["rebalance_plan"]
            if tel.get("order_intent_plan"):
                overlay["order_intent_plan"] = tel["order_intent_plan"]
            if tel.get("target_allocation"):
                overlay["target_allocation"] = tel["target_allocation"]
            overlay["intent_execution_enabled"] = tel.get("intent_execution_enabled", False)
            return overlay
        from app.services.dynamic_param_score.safe_overlay import build_safe_overlay_for_decision

        return build_safe_overlay_for_decision(decision)


_engine: Optional[DynamicParamScoreEngine] = None


def get_engine() -> DynamicParamScoreEngine:
    global _engine
    if _engine is None:
        _engine = DynamicParamScoreEngine()
    return _engine
