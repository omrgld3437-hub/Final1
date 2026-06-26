"""Dynamic Mode V4 final — rebalance, start retry, churn, shared engine invariants."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.botengine.dynamic import churn_policy as cp
from app.botengine.dynamic import cycle_manager as cm
from app.botengine.dynamic import start_retry_policy as srp
from app.services.dynamic_param_score.models import FinalAction, RiskState, SubScores
from app.services.dynamic_param_score.rebalance import (
    REBALANCE_THRESHOLD_TOTAL_PP,
    RebalanceMode,
    SafetyContext,
    plan_rebalance,
    rebalance_delta_total_pp,
)
from tests.dynamic_param_score.conftest import constraints, portfolio


def _ctx(**kwargs) -> SafetyContext:
    defaults = dict(
        risk_state=RiskState.NORMAL.value,
        regime="BALANCED_RANGE",
        final_action=FinalAction.BALANCED_GRID.value,
        param_score=65,
        sub_scores=SubScores(fee_efficiency_score=70, exposure_safety_score=80, liquidity_score=75),
        headroom_usdt=200.0,
        min_notional=5.0,
        spread_pct=0.05,
    )
    defaults.update(kwargs)
    return SafetyContext(**defaults)


def test_dynamic_mode_uses_same_engine_as_param_assistant():
    from app.services.dynamic_param_score.engine import DynamicParamScoreEngine, get_engine

    assert isinstance(get_engine(), DynamicParamScoreEngine)
    assert cm.get_dps_engine() is get_engine()


def test_small_base_quote_delta_no_rebalance():
    assert rebalance_delta_total_pp(0.50, 0.45) == pytest.approx(10.0)
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(0.45, 0.50, pf, None, constraints(), _ctx())
    assert plan.rebalance_decision == "SKIP"
    assert plan.rebalance_skipped_reason == "SMALL_BASE_QUOTE_DELTA"
    assert not plan.orders


def test_base_quote_50_50_to_45_55_no_rebalance():
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(0.45, 0.50, pf, None, constraints(), _ctx())
    assert plan.rebalance_delta_total_pp == 10.0
    assert plan.rebalance_decision == "SKIP"


def test_base_quote_50_50_to_40_60_oneshot_rebalance():
    assert rebalance_delta_total_pp(0.50, 0.40) == 20.0
    pf = portfolio(1000, 0.78)
    plan = plan_rebalance(0.50, 0.78, pf, None, constraints(), _ctx())
    assert plan.rebalance_decision == "EXECUTE"
    assert plan.rebalance_execution_mode == "ONESHOT"
    assert len(plan.orders) == 1
    assert plan.orders[0].order_type == "MARKETABLE_LIMIT"


def test_rebalance_never_ladder():
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(0.70, 0.50, pf, None, constraints(), _ctx(headroom_usdt=500.0))
    assert len(plan.orders) <= 1


def test_rebalance_uses_oneshot_order_type():
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(0.70, 0.50, pf, None, constraints(), _ctx(headroom_usdt=500.0))
    if plan.orders:
        assert plan.rebalance_action in (
            RebalanceMode.ONESHOT_BUY_REBALANCE.value,
            RebalanceMode.ONESHOT_SELL_REBALANCE.value,
        )


def test_rebalance_deferred_when_spread_unsafe():
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(
        0.70,
        0.50,
        pf,
        None,
        constraints(),
        _ctx(regime="SPREAD_UNSAFE", spread_pct=0.5, headroom_usdt=500.0),
    )
    assert plan.rebalance_decision == "DEFER"
    assert "REBALANCE_SAFETY_BLOCKED" in plan.block_reasons


def test_rebalance_cooldown_prevents_churn():
    pf = portfolio(1000, 0.50)
    plan = plan_rebalance(
        0.70,
        0.50,
        pf,
        None,
        constraints(),
        _ctx(headroom_usdt=500.0),
        rebalance_policy={"last_rebalance_turn_id": "5", "current_turn_id": "6", "rebalance_cooldown_turns": 2},
    )
    assert plan.rebalance_skipped_reason == "REBALANCE_COOLDOWN_ACTIVE"


def test_churn_protection_no_order_replace_on_small_change():
    prev = {"buy_grids": [{"buy_grid_pct": 2.0}], "buy_trigger_trailing_pct": 0.3}
    new = {"buy_grids": [{"buy_grid_pct": 2.05}], "buy_trigger_trailing_pct": 0.31}
    preserve, reasons = cp.should_preserve_orders(prev, new, rebalance_plan={"rebalance_delta_total_pp": 10})
    assert preserve is True
    assert "small_base_quote_delta" in reasons


def test_start_blocked_when_no_deployable_params():
    assert srp.is_turn_start_blocked(result_type="recommended_grid", deployable=False) is True
    assert srp.is_turn_start_blocked(result_type="deployable_grid", deployable=True) is False


def test_risky_start_goes_to_retry_pending():
    st = {"cycle_id": 2}
    srp.mark_start_blocked(
        st,
        cycle_id=2,
        result_type="management_decision",
        deployable=False,
        block_reasons=["SPREAD_HIGH"],
    )
    wl = srp.get_watchlist(st)
    assert wl["status"] == srp.START_BLOCKED_RETRY_PENDING


def test_retry_backoff_increases_after_consecutive_failures():
    m1 = srp.retry_after_minutes(["DUMP_RISK"], retry_count=1)
    m3 = srp.retry_after_minutes(["DUMP_RISK"], retry_count=3)
    assert m3 >= m1


def test_retry_recomputes_full_engine_flag():
    st = {"cycle_id": 2}
    srp.mark_start_blocked(st, cycle_id=2, result_type="no_trade", deployable=False, block_reasons=["SPREAD_HIGH"])
    wl = st["_dynamic_start_watchlist"]
    wl["next_retry_at_ms"] = int(time.time() * 1000) - 1
    assert srp.need_start_retry(st) is True
    assert st.get("_dynamic_recompute_needed") is True


def test_one_grid_not_deployable_dynamic():
    from app.services.dynamic_param_score.result_type import resolve_result_type
    from app.services.dynamic_param_score.models import BotContext, BotParams

    params = BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=1,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.0,
        sell_grid_spacing_pct=2.0,
        buy_qty_distribution=[1.0],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.5,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="t",
    )
    rt = resolve_result_type(
        deployable=True,
        final_action="BALANCED_GRID",
        params=params,
        feasibility_meta={},
        bot_context=BotContext(run_source="dynamic_round_start", budget_usdt=100.0),
        blocking_reasons=[],
        has_recommendation_ui=True,
    )
    assert rt == "single_probe_recommendation"


def test_two_grid_40_60_allowed_normal_dynamic():
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        DistributionContext,
        normalize_side_distribution,
    )

    dist, _ = normalize_side_distribution([40, 60], ctx=DistributionContext(risk_state="NORMAL"))
    assert dist == [40, 60]


def test_two_grid_50_50_forbidden_dynamic():
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        DistributionContext,
        normalize_side_distribution,
    )

    dist, changed = normalize_side_distribution([50, 50], ctx=DistributionContext(risk_state="NORMAL"))
    assert changed
    assert dist != [50, 50]


def test_three_grid_defensive_not_equalish_dynamic():
    from app.services.dynamic_param_score.param_generator.grid_distribution import (
        DistributionContext,
        normalize_side_distribution,
    )

    ctx = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    dist, changed = normalize_side_distribution([29.8, 34.3, 36.0], ctx=ctx)
    assert changed
    assert max(dist) - min(dist) >= 30


def test_v4_no_mid_turn_cycle_hold_by_default():
    from app.botengine.dynamic import cycle_gate as cg
    from app.botengine.dynamic import regime as reg

    assert cg.HOLD_ENABLED is False
    feats = {
        "atr_pct_5m": 2.6,
        "ret_5m_last": -4.2,
        "rsi_5m": 22.0,
        "spread_pct": 0.30,
        "volume_zscore_5m": 3.0,
        "wick_body_ratio_5m": 2.0,
        "ema_slope_1h_pct": -1.0,
        "realized_vol_5m": 2.0,
        "rsi_1h": 30.0,
        "adx_1h": 30.0,
    }
    st = {"cycle_id": 2, "quote_balance": 500.0, "buy_grid_fired": [False, False]}
    cfg = {"buy_grids": [{"buy_grid_pct": 2}], "max_buy_levels": 2}
    v = cg.evaluate(feats, reg.DUMP_RISK, 0.9, st, cfg)
    assert v.holding is False
    kept, blocked = cg.filter_actions(st, [{"reason": "trail_buy_grid"}])
    assert blocked == 0
    assert len(kept) == 1
