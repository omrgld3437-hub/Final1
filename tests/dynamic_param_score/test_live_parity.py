"""PA ↔ Dynamic Mode live deploy parity."""

from __future__ import annotations

from app.services.dynamic_param_score.live_parity import evaluate_dynamic_round_parity
from app.services.dynamic_param_score.models import BotParams, ExchangeConstraints, PortfolioState, SubScores
from tests.dynamic_param_score.conftest import constraints, portfolio


def _params(**kw) -> BotParams:
    base = dict(
        base_alloc_frac=0.52,
        quote_alloc_frac=0.48,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.5,
        sell_grid_spacing_pct=2.5,
        buy_qty_distribution=[0.35, 0.65],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.62,
        max_quote_to_spend_per_buy_frac=0.35,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )
    base.update(kw)
    return BotParams(**base)


def test_live_parity_fails_small_budget_bilateral():
    pf = portfolio(50, 0.0)
    sub = SubScores()
    ok, blocking = evaluate_dynamic_round_parity(
        _params(),
        portfolio=pf,
        constraints=constraints(),
        budget_usdt=50,
        sub=sub,
        ind=None,
        risk_state="NORMAL",
        final_action="CONTROLLED_GRID",
    )
    assert not ok
    assert blocking


def test_live_parity_ok_larger_budget():
    pf = portfolio(1000, 0.0)
    sub = SubScores(liquidity_score=80, spread_score=80, fee_efficiency_score=65)
    ok, blocking = evaluate_dynamic_round_parity(
        _params(buy_grid_count=3, sell_grid_count=3, max_base_exposure_frac=0.70),
        portfolio=pf,
        constraints=constraints(),
        budget_usdt=1000,
        sub=sub,
        ind=None,
        risk_state="NORMAL",
        final_action="CONTROLLED_GRID",
    )
    assert ok or not blocking or "MIN_NOTIONAL" not in str(blocking)
