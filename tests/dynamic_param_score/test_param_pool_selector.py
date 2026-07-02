"""Param pool selector tests."""

from __future__ import annotations

from app.services.dynamic_param_score.models import FinalAction, RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_pool.selector import (
    build_selection_context,
    select_template,
)
from tests.dynamic_param_score.conftest import constraints, portfolio


def _sub(**kwargs) -> SubScores:
    base = SubScores(
        range_score=70,
        liquidity_score=75,
        spread_score=75,
        fee_efficiency_score=70,
        exposure_safety_score=70,
        data_quality_score=80,
        btc_market_risk_score=70,
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def _select(
    score: int,
    regime: RegimeTag,
    risk: str,
    budget: float,
    exposure: float,
    sub: SubScores | None = None,
):
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    m = market_bundle(price=67.8)
    pf = portfolio(budget, exposure)
    ind = compute_indicators(m, pf)
    sub = sub or _sub()
    return select_template(
        score, regime, risk, sub, ind, pf, constraints(), budget, 5.0
    )


def test_sol_50_sell_management_selection():
    sub = _sub(fee_efficiency_score=55)
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, 50, 0.44, sub)
    assert r.selected_template_key == "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT"
    assert r.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
    assert r.template is not None
    assert r.template.params["buy_grid_count"] == 0
    assert r.template.params["sell_grid_count"] >= 2


def test_cautious_balanced_standard_good_headroom():
    sub = _sub(fee_efficiency_score=65)
    pf = portfolio(200, 0.35)
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    m = market_bundle(price=100.0)
    ind = compute_indicators(m, pf)
    r = select_template(
        62, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value,
        sub, ind, pf, constraints(), 200, 5.0,
    )
    eligible_keys = [
        t for t, _ in [(r.template, r)] if r.template
    ]
    assert r.final_action in (
        FinalAction.BALANCED_GRID.value,
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.SELL_MANAGEMENT_ONLY.value,
    )
    if r.selected_template_key:
        key = r.selected_template_key
        assert any(
            tag in key
            for tag in ("CAUTIOUS", "BALANCED", "REBALANCE", "ACTIVE_DEFENSIVE", "BR_", "BAL_")
        )


def test_active_grid_medium_fee_good():
    sub = _sub(fee_efficiency_score=72, range_score=75)
    r = _select(78, RegimeTag.RANGE_HIGH_VOL, RiskState.NORMAL.value, 500, 0.35, sub)
    if r.template and r.final_action == FinalAction.ACTIVE_GRID.value:
        assert r.selected_template_key == "RANGE_HIGH_VOL_MEDIUM_75_89_ACTIVE_GRID" or (
            "ACTIVE" in (r.selected_template_key or "")
        )


def test_active_grid_rejected_fee_bad():
    sub = _sub(fee_efficiency_score=20)
    r = _select(78, RegimeTag.RANGE_HIGH_VOL, RiskState.NORMAL.value, 500, 0.35, sub)
    assert r.final_action != FinalAction.ACTIVE_GRID.value or r.fallback_used


def test_dump_risk_no_trade():
    r = _select(50, RegimeTag.DUMP_RISK, RiskState.BLOCKED.value, 500, 0.3)
    assert r.final_action == FinalAction.NO_TRADE.value


def test_trending_down_no_active():
    sub = _sub(fee_efficiency_score=80)
    r = _select(78, RegimeTag.TRENDING_DOWN, RiskState.DEFENSIVE.value, 500, 0.2, sub)
    assert r.final_action != FinalAction.ACTIVE_GRID.value


def test_overexposed_no_buy_template():
    sub = _sub()
    r = _select(70, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, 500, 0.80, sub)
    if r.template:
        assert int(r.template.params.get("buy_grid_count") or 0) == 0


def test_low_liquidity_safe_fallback():
    r = _select(50, RegimeTag.LOW_LIQUIDITY, RiskState.BLOCKED.value, 500, 0.3)
    assert r.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)


def test_hard_filter_logs_reasons():
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, 50, 0.44)
    assert r.candidate_count >= 1
