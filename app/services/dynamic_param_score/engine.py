"""Dynamic Param Score Engine — central decision motor."""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.dynamic_param_score.adapters import params_to_grid_config
from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.action_detail import build_action_detail
from app.services.dynamic_param_score.explain import build_explanation
from app.services.dynamic_param_score.feasibility import exposure_headroom_quote_usdt
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import (
    BotContext,
    DynamicParamDecision,
    ExchangeConstraints,
    FinalAction,
    MarketDataBundle,
    PortfolioState,
    RegimeTag,
)
from app.services.dynamic_param_score.param_pool.selector import select_and_render
from app.services.dynamic_param_score.allocation import calculate_target_allocation
from app.services.dynamic_param_score.order_intent import plan_order_intents
from app.services.dynamic_param_score.rebalance import (
    SafetyContext,
    apply_rebalance_safety,
    plan_rebalance,
)
from app.services.dynamic_param_score.regime import classify_regime, determine_risk_state
from app.services.dynamic_param_score.safety import apply_safety_gates
from app.services.dynamic_param_score.scoring import (
    compute_confidence_score,
    compute_param_score,
    compute_risk_score,
    compute_sub_scores,
)
from app.services.dynamic_param_score.persistence import persist_decision
from app.services.dynamic_param_score.utils import json_safe

logger = logging.getLogger(__name__)


class DynamicParamScoreEngine:
    """Single central motor for Param Assistant and Dynamic Mode."""

    def calculate_decision(
        self,
        symbol: str,
        market_data: MarketDataBundle,
        portfolio_state: PortfolioState,
        exchange_constraints: ExchangeConstraints,
        bot_context: BotContext,
    ) -> DynamicParamDecision:
        ind = compute_indicators(market_data, portfolio_state)
        sub = compute_sub_scores(ind, portfolio_state, exchange_constraints)

        regime_down = False
        pre_regime = classify_regime(
            ind, sub, portfolio_state, exchange_constraints, 50
        )
        if pre_regime == RegimeTag.TRENDING_DOWN:
            regime_down = True

        param_score = compute_param_score(sub, regime_down=regime_down)
        regime = classify_regime(
            ind, sub, portfolio_state, exchange_constraints, param_score
        )
        risk_state = determine_risk_state(
            regime, param_score, sub, portfolio_state, exchange_constraints, ind=ind
        )
        budget = float(
            bot_context.budget_usdt or portfolio_state.total_equity_usdt or 0.0
        )
        min_n = float(exchange_constraints.min_notional or C.DEFAULT_MIN_NOTIONAL_USDT)

        pool_selection, pre_params, bucket = select_and_render(
            param_score=param_score,
            regime=regime,
            risk_state=risk_state,
            sub=sub,
            ind=ind,
            portfolio=portfolio_state,
            constraints=exchange_constraints,
            bot_context=bot_context,
            budget_usdt=budget,
            min_notional=min_n,
            symbol=symbol,
        )
        profile_name = pool_selection.profile_family
        final_action = pool_selection.final_action
        pre_params_dict = pre_params.to_dict() if pre_params else None

        params, final_action, deployable, gates, blocking, warnings, feas_meta = (
            apply_safety_gates(
                pre_params,
                sub,
                regime,
                portfolio_state,
                exchange_constraints,
                bot_context,
                param_score,
                final_action,
                ind,
                profile_name=profile_name,
                current_price=market_data.ticker_price,
                risk_state=risk_state,
            )
        )

        if params is not None:
            from app.services.dynamic_param_score.runtime_adjust import (
                apply_runtime_micro_adjust,
                compute_runtime_adjustment_factor,
            )

            tmpl_params = (
                (pool_selection.template.params or {})
                if pool_selection.template is not None
                else {}
            )
            profile_atr = float(
                tmpl_params.get("dps_profile", {}).get("atr_1h_pct")
                or ind.atr14_pct_1h
                or ind.atr14_pct_5m
                or 1.0
            )
            adj_factor, adj_reasons = compute_runtime_adjustment_factor(
                atr_1h_live=float(ind.atr14_pct_1h or ind.atr14_pct_5m or 1.0),
                atr_1h_profile=profile_atr,
                spread_live=float(ind.orderbook_spread_pct or 0.0),
                spread_profile=0.02,
                fee_live=float(ind.total_friction_pct or 0.0),
                fee_profile=0.10,
                data_freshness_sec=float(getattr(ind, "data_freshness_sec", 0) or 0),
                fee_bad=sub.fee_efficiency_score < C.FEE_EFF_CAUTIOUS,
            )
            params, runtime_meta = apply_runtime_micro_adjust(
                params, adj_factor, reasons=adj_reasons
            )
            feas_meta.update(runtime_meta)

        if blocking and bot_context.allow_no_trade:
            deployable = False
            if final_action not in (
                FinalAction.WAIT.value,
                FinalAction.WAIT_SAFETY.value,
                FinalAction.SELL_MANAGEMENT_ONLY.value,
            ):
                final_action = FinalAction.NO_TRADE.value

        target_base = float(params.base_alloc_frac) if params else portfolio_state.current_base_exposure_frac
        headroom = exposure_headroom_quote_usdt(
            portfolio_state,
            float(params.max_base_exposure_frac if params else 0.72),
        )
        template_policy = None
        if pool_selection.template and pool_selection.template.params:
            template_policy = dict(pool_selection.template.params.get("rebalance_policy") or {})
        template_policy = template_policy or {}
        template_policy.setdefault("current_turn_id", bot_context.current_round_id)
        template_policy.setdefault("last_rebalance_turn_id", bot_context.last_rebalance_round_id)
        template_policy.setdefault("rebalance_cooldown_turns", 2)

        rebalance_plan = plan_rebalance(
            target_base_frac=target_base,
            current_base_frac=portfolio_state.current_base_exposure_frac,
            portfolio=portfolio_state,
            bot_params=params,
            constraints=exchange_constraints,
            safety_context=SafetyContext(
                risk_state=risk_state,
                regime=regime.value,
                final_action=final_action,
                param_score=param_score,
                sub_scores=sub,
                headroom_usdt=headroom,
                min_notional=min_n,
                spread_pct=float(ind.orderbook_spread_pct or 0.0),
                atr_pct=float(ind.atr14_pct_5m or 1.0),
            ),
            rebalance_policy=template_policy,
        )
        rebalance_plan = apply_rebalance_safety(
            rebalance_plan,
            SafetyContext(
                risk_state=risk_state,
                regime=regime.value,
                final_action=final_action,
                param_score=param_score,
                sub_scores=sub,
                headroom_usdt=headroom,
                min_notional=min_n,
                spread_pct=float(ind.orderbook_spread_pct or 0.0),
                atr_pct=float(ind.atr14_pct_5m or 1.0),
            ),
            params,
            exchange_constraints,
            total_equity_usdt=portfolio_state.total_equity_usdt,
        )

        target_allocation = (
            calculate_target_allocation(params, portfolio_state) if params else None
        )
        order_intent_plan = plan_order_intents(
            params,
            portfolio_state,
            exchange_constraints,
            bot_context,
            final_action=final_action,
            profile_name=profile_name,
            rebalance_plan=rebalance_plan,
            buy_ladder_budget_override=feas_meta.get("buy_ladder_budget_usdt"),
        )

        confidence = compute_confidence_score(
            sub,
            param_score,
            warnings=warnings,
            gates=gates,
            feasibility_meta=feas_meta,
            profile_name=profile_name,
            final_action=final_action,
            min_notional=min_n,
        )
        risk_sc = compute_risk_score(sub)
        explain = build_explanation(
            param_score,
            regime.value,
            risk_state,
            final_action,
            sub,
            params,
            blocking,
            selected_template_key=pool_selection.selected_template_key,
            fallback_reason=pool_selection.fallback_reason,
            rebalance_plan=rebalance_plan.to_dict(),
            indicators=ind.to_dict(),
            budget_usdt=budget,
        )

        from app.services.dynamic_param_score.param_generator.param_index_builder import (
            market_signature_from_live,
        )

        market_signature = market_signature_from_live(
            symbol=symbol,
            budget=budget,
            regime=regime.value,
            risk_level=risk_state,
            volatility_percentile=float(ind.volatility_percentile or sub.volatility_score or 50),
            lower_lows=bool(ind.lower_lows),
            higher_highs=bool(ind.higher_highs),
            fee_efficiency_score=int(sub.fee_efficiency_score or 50),
            atr_1h_pct=float(ind.atr14_pct_1h or ind.atr14_pct_5m or 1.0),
            spread_pct=float(ind.orderbook_spread_pct or 0.0),
            data_quality_score=int(sub.data_quality_score or 80),
            return_24h_pct=float(ind.return_24h_pct or 0.0),
            drawdown_7d_pct=float(ind.drawdown_7d_pct or 0.0),
            drawdown_30d_pct=float(ind.drawdown_30d_pct or 0.0),
            z_score_5m=ind.z_score_5m,
            price_in_bb=ind.price_in_bb,
            volatility_score=int(sub.volatility_score or 50),
            btc_crash_velocity=float(ind.btc_crash_velocity or 0.0),
            crash_velocity=float(ind.crash_velocity or 0.0),
        )

        action_detail = build_action_detail(
            params,
            final_action,
            profile_name,
            feas_meta,
            warnings,
        )

        from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4

        engine_ver = C.DPS_ENGINE_V4 if pool_selection.pool_version == POOL_VERSION_V4 else C.DPS_ENGINE_V2

        telemetry = {
            "sub_scores": sub.to_dict(),
            "indicators": ind.to_dict(),
            "market_signature": market_signature,
            "dps_engine_version": engine_ver,
            "param_score_raw": param_score,
            "profile_bucket": bucket,
            "param_pool": pool_selection.to_dict(),
            "selection_trace": DynamicParamScoreEngine.build_selection_trace(
                symbol=symbol,
                market_signature=market_signature,
                pool_selection=pool_selection.to_dict(),
                params=params,
                final_action=final_action,
            ),
            "pre_safety_params": pre_params_dict,
            "post_safety_params": params.to_dict() if params else None,
            "action_detail": action_detail,
            "rebalance_plan": rebalance_plan.to_dict(),
            "target_allocation": target_allocation.to_dict() if target_allocation else None,
            "order_intent_plan": order_intent_plan.to_dict(),
            "intent_execution_enabled": False,
            "data_window": getattr(market_data, "data_window", None),
            "is_first_start": bool(bot_context.is_first_start),
            "first_start_buy_only": bool(bot_context.first_start_buy_only),
            **feas_meta,
        }

        decision = DynamicParamDecision(
            decision_id=DynamicParamDecision.new_id(),
            symbol=symbol.upper(),
            timestamp=int(time.time() * 1000),
            run_source=bot_context.run_source,
            final_action=final_action,
            deployable=deployable,
            param_score=param_score,
            confidence_score=confidence,
            risk_score=risk_sc,
            regime_tag=regime.value,
            risk_state=risk_state,
            selected_profile_name=profile_name,
            selected_profile_bucket=bucket,
            params=params,
            safety_gates=gates,
            blocking_reasons=blocking,
            warnings=warnings,
            explain=explain,
            telemetry=json_safe(telemetry),
            action_detail=action_detail,
        )

        try:
            persist_decision(
                decision,
                market_data,
                portfolio_state,
                bot_id=bot_context.bot_id,
                round_id=bot_context.current_round_id,
                raw_indicators=ind.to_dict(),
                pre_safety_params=pre_params_dict,
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
        """Unified V4 profile selection — Dynamic Mode and Param Assistant use this path."""
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
            pool_selection=(decision.telemetry or {}).get("param_pool") or {},
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
        sel_ctx = pool_selection.get("selection_context") or {}
        dps = ((params.to_dict() if params else {}) or {})
        pool_sel = pool_selection or {}
        buy_ladder = dps.get("buy_grid_ladder_pcts") or []
        sell_ladder = dps.get("sell_grid_ladder_pcts") or []
        return {
            "symbol": symbol,
            "profile_id": pool_sel.get("selected_template_key"),
            "route_key": sel_ctx.get("route_key") or market_signature.get("route_key"),
            "scenario": market_signature.get("scenario") or sel_ctx.get("scenario"),
            "final_action": final_action,
            "base_alloc_frac": dps.get("base_alloc_frac"),
            "quote_alloc_frac": dps.get("quote_alloc_frac"),
            "buy_grid_count": dps.get("buy_grid_count"),
            "sell_grid_count": dps.get("sell_grid_count"),
            "buy_grid_ladder_pcts": buy_ladder,
            "sell_grid_ladder_pcts": sell_ladder,
            "buy_distribution": sel_ctx.get("buy_distribution"),
            "sell_distribution": sel_ctx.get("sell_distribution"),
            "structure_fit": sel_ctx.get("structure_fit"),
            "grid_direction_fit": sel_ctx.get("grid_direction_fit"),
            "base_quote_fit": sel_ctx.get("base_quote_fit"),
            "capacity_resolution": sel_ctx.get("capacity_resolution"),
            "cost_resolution": sel_ctx.get("cost_resolution"),
            "fallback_used": pool_sel.get("fallback_used", False),
            "selection_path": sel_ctx.get("selection_path") or [],
            "reason": sel_ctx.get("reason"),
            "exact_route_candidate_count": sel_ctx.get("exact_route_candidate_count"),
            "fallback_route": sel_ctx.get("fallback_route"),
            "fallback_candidate_count": sel_ctx.get("fallback_candidate_count"),
            "route_index_fallback_used": sel_ctx.get("route_index_fallback_used"),
            "scored_candidate_count": sel_ctx.get("scored_candidate_count"),
            "selected_profile_score": sel_ctx.get("selected_profile_score"),
            "hard_reject_count": sel_ctx.get("hard_reject_count"),
            "runtime_safe_profile_generated": sel_ctx.get("runtime_safe_profile_generated"),
            "selection_reason": sel_ctx.get("selection_reason") or sel_ctx.get("reason"),
            "coverage_gap": sel_ctx.get("coverage_gap"),
            "defensive_fallback_overlay": sel_ctx.get("defensive_fallback_overlay"),
            "requested_risk_class": sel_ctx.get("requested_risk_class"),
            "market_signature": market_signature,
            "param_score": decision.param_score if decision else None,
        }

    @classmethod
    def decision_to_overlay(cls, decision: DynamicParamDecision) -> Optional[dict]:
        """Convert decision to cycle_manager overlay format."""
        if decision.deployable and decision.params:
            tel = decision.telemetry or {}
            pool = tel.get("param_pool") or {}
            overlay = params_to_grid_config(
                decision.params,
                final_action=decision.final_action,
                pool_version=pool.get("pool_version"),
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


# Module-level singleton
_engine: Optional[DynamicParamScoreEngine] = None


def get_engine() -> DynamicParamScoreEngine:
    global _engine
    if _engine is None:
        _engine = DynamicParamScoreEngine()
    return _engine
