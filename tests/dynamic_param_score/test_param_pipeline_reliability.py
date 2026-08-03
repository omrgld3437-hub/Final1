"""Param pipeline reliability — veri → tier → template → BotParams → execution gates."""

from __future__ import annotations

from app.services.dynamic_param_score.constants import (
    DATA_WINDOW_DAYS,
    KLINES_LIMIT_15M,
    KLINES_LIMIT_5M,
)
from app.services.dynamic_param_score.feasibility import has_sellable_base_feasible
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    FinalAction,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_pool.models import SelectionContext
from app.services.dynamic_param_score.param_pool.renderer import render_template
from app.services.dynamic_param_score.param_pool.selector import (
    _hard_filter,
    build_selection_context,
    select_template,
)
from app.services.dynamic_param_score.param_pool.defaults import _pinned_templates
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from tests.dynamic_param_score.conftest import constraints, ctx, portfolio
from tests.dynamic_param_score.sol_market_fixture import _sol_market


def _sub_fee_bad() -> SubScores:
    return SubScores(
        trend_score=45,
        volatility_score=40,
        range_score=44,
        liquidity_score=78,
        spread_score=95,
        momentum_score=99,
        mean_reversion_score=40,
        drawdown_risk_score=36,
        btc_market_risk_score=55,
        exposure_safety_score=90,
        fee_efficiency_score=15,
        data_quality_score=100,
    )


def test_klines_window_is_seven_days_not_one_day():
    assert KLINES_LIMIT_5M == 2016
    assert KLINES_LIMIT_15M == 672
    assert DATA_WINDOW_DAYS == 7


def test_selection_context_includes_all_tier_fields():
    from app.services.dynamic_param_score.indicators import compute_indicators

    m = _sol_market()
    ind = compute_indicators(m, portfolio(50))
    sc = build_selection_context(
        60,
        RegimeTag.BALANCED_RANGE,
        RiskState.CAUTION.value,
        _sub_fee_bad(),
        ind,
        portfolio(50),
        constraints(),
        50,
        5.0,
    )
    assert sc.liquidity_tier
    assert sc.volatility_tier
    assert sc.btc_risk_tier
    assert sc.order_reality_tier


def test_hard_filter_rejects_liquidity_tier_mismatch():
    pinned = {t.template_key: t for t in _pinned_templates()}
    tmpl = pinned["BALANCED_RANGE_60_69_FEE_BAD_WAIT"]
    if not tmpl.liquidity_tiers:
        return
    ctx_ok = SelectionContext(
        param_score=65,
        regime="BALANCED_RANGE",
        risk_state="NORMAL",
        budget_tier="SMALL",
        exposure_tier="NO_BASE",
        headroom_tier="GOOD_HEADROOM",
        fee_tier="FEE_BAD",
        equity_usdt=50,
        min_notional=5,
        headroom_usdt=40,
        has_base=False,
        has_sellable_base=False,
        sub_scores={},
        liquidity_tier=tmpl.liquidity_tiers[0],
    )
    ctx_bad = SelectionContext(**{**ctx_ok.__dict__, "liquidity_tier": "LIQ_EXCELLENT"})
    if "LIQ_EXCELLENT" in tmpl.liquidity_tiers:
        return
    ok, reasons = _hard_filter(tmpl, ctx_bad)
    assert not ok
    assert "liquidity_tier_mismatch" in reasons


def test_sellable_base_requires_min_notional_and_step_size():
    pf = PortfolioState(
        base_balance=0.001,
        quote_balance=50,
        base_value_usdt=6.0,
        quote_value_usdt=50,
        total_equity_usdt=56,
        current_base_exposure_frac=6.0 / 56,
    )
    c = ExchangeConstraints(
        min_notional=10.0,
        step_size=0.01,
        tick_size=0.01,
        min_qty=0.001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )
    ok, _ = has_sellable_base_feasible(pf, c, price=6000.0)
    assert not ok

    pf2 = PortfolioState(
        base_balance=0.01,
        quote_balance=50,
        base_value_usdt=60.0,
        quote_value_usdt=50,
        total_equity_usdt=110,
        current_base_exposure_frac=60.0 / 110,
    )
    ok2, _ = has_sellable_base_feasible(pf2, c, price=6000.0)
    assert ok2


def test_fresh_budget_never_selects_sell_management():
    from app.services.dynamic_param_score.indicators import compute_indicators

    m = _sol_market()
    ind = compute_indicators(m, portfolio(50))
    r = select_template(
        65,
        RegimeTag.BALANCED_RANGE,
        RiskState.NORMAL.value,
        _sub_fee_bad(),
        ind,
        portfolio(50, 0.0),
        constraints(),
        50,
        5.0,
        is_first_start=True,
    )
    assert r.final_action != FinalAction.SELL_MANAGEMENT_ONLY.value


def test_renderer_sets_explicit_sell_only_flags():
    pinned = {t.template_key: t for t in _pinned_templates()}
    tmpl = pinned["BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT"]
    from app.services.dynamic_param_score.indicators import compute_indicators

    m = _sol_market()
    pf = portfolio(200, 0.4)
    ind = compute_indicators(m, pf)
    params = render_template(
        tmpl,
        param_score=65,
        regime=RegimeTag.BALANCED_RANGE,
        ind=ind,
        constraints=constraints(),
        current_exposure_frac=pf.current_base_exposure_frac,
        budget_usdt=200,
        min_notional=5,
    )
    assert params is not None
    assert params.buy_disabled is True
    assert params.sell_only_mode is True
    assert params.rebuy_enabled is False
    assert params.selected_template_key == tmpl.template_key
    assert params.pool_version


def test_param_assistant_fee_bad_wait_not_error_result():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(50),
        constraints(),
        ctx("param_assistant", 50),
    )
    from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result

    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    if d.final_action in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    ):
        assert r["ok"] is True
        assert r["result_type"] in ("management_decision", "recommended_grid")
        assert r["ui_severity"] != "error"
