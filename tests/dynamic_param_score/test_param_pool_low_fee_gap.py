"""Fee-efficiency gap templates, fallback safety and pool coverage (spec §19)."""

from __future__ import annotations

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.explain import build_explanation
from app.services.dynamic_param_score.feasibility import total_friction_pct
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import (
    FinalAction,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_pool.defaults import build_v1_pool
from app.services.dynamic_param_score.param_pool.models import (
    ExposureTier,
    FeeTier,
    ProfileFamily,
)
from app.services.dynamic_param_score.param_pool.renderer import render_template
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache
from tests.dynamic_param_score.conftest import constraints, ctx, market_bundle, portfolio


def _sub(**kwargs) -> SubScores:
    base = SubScores(
        trend_score=56,
        volatility_score=40,
        range_score=47,
        liquidity_score=79,
        spread_score=95,
        momentum_score=100,
        mean_reversion_score=41,
        drawdown_risk_score=49,
        btc_market_risk_score=55,
        exposure_safety_score=90,
        fee_efficiency_score=15,
        data_quality_score=100,
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def _select(score, regime, risk, budget, exposure, sub=None):
    clear_pool_cache()
    m = market_bundle(symbol="SOLUSDT", price=67.8)
    pf = portfolio(budget, exposure)
    ind = compute_indicators(m, pf)
    sub = sub or _sub()
    return select_template(
        score, regime, risk, sub, ind, pf, constraints(), budget, 5.0
    )


def test_balanced_range_60_69_fee_bad_active_defensive_template():
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value, 50, 0.0)
    assert r.final_action != FinalAction.WAIT.value
    assert r.final_action in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
    )
    assert r.template is not None
    explain = build_explanation(
        62,
        RegimeTag.BALANCED_RANGE.value,
        RiskState.NORMAL.value,
        r.final_action,
        _sub(),
        None,
        [],
        selected_template_key=r.selected_template_key,
    )
    assert "fee" in explain.lower()


def test_balanced_range_60_69_fee_bad_sell_management_template():
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value, 50, 0.44)
    assert r.selected_template_key in (
        "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT",
        "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT",
    )
    assert r.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
    assert r.template is not None
    assert int(r.template.params.get("buy_grid_count") or 0) == 0
    assert int(r.template.params.get("sell_grid_count") or 0) > 0
    assert r.template.params.get("rebuy_enabled") is False


def test_balanced_range_60_69_fee_weak_wide_grid_template():
    sub = _sub(fee_efficiency_score=42, drawdown_risk_score=55)
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value, 200, 0.20, sub)
    assert r.selected_template_key == "BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID"
    assert r.final_action == FinalAction.BALANCED_GRID.value
    buy_n = int(r.template.params.get("buy_grid_count") or 0)
    sell_n = int(r.template.params.get("sell_grid_count") or 0)
    assert 1 <= buy_n <= 2
    assert 1 <= sell_n <= 3
    assert r.template.profile_family.endswith("LOW_FEE_WIDE_GRID_PROFILE")

    c = constraints()
    m = market_bundle(symbol="SOLUSDT", price=100.0)
    pf = portfolio(200, 0.20)
    ind = compute_indicators(m, pf)
    params = render_template(
        r.template,
        param_score=62,
        regime=RegimeTag.BALANCED_RANGE,
        ind=ind,
        constraints=c,
        current_exposure_frac=0.20,
        budget_usdt=200,
        min_notional=5.0,
    )
    friction = total_friction_pct(c, float(ind.orderbook_spread_pct or 0.0))
    assert params.buy_grid_spacing_pct >= 4.0 * friction - 1e-6
    assert r.final_action != FinalAction.ACTIVE_GRID.value


def test_active_not_selected_when_fee_bad():
    sub = _sub(fee_efficiency_score=15, range_score=85, liquidity_score=85)
    r = _select(80, RegimeTag.RANGE_HIGH_VOL, RiskState.NORMAL.value, 500, 0.35, sub)
    assert r.final_action != FinalAction.ACTIVE_GRID.value


def test_dump_risk_no_trade_template():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.factories import make_market_bundle

    m = make_market_bundle(pattern="dump_risk")
    pf = portfolio(500, 0.3)
    ind = compute_indicators(m, pf)
    sub = _sub(drawdown_risk_score=5, btc_market_risk_score=5)
    r = select_template(
        50, RegimeTag.DUMP_RISK, RiskState.BLOCKED.value,
        sub, ind, pf, constraints(), 500, 5.0,
    )
    assert r.final_action in (
        FinalAction.NO_TRADE.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ) or "DUMP" in (r.selected_template_key or "")


def test_overexposed_recovery_sell_template():
    sub = _sub(fee_efficiency_score=55)
    r = _select(70, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, 500, 0.82, sub)
    assert r.selected_template_key == "OVEREXPOSED_ANY_RECOVERY_SELL"
    assert r.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
    assert int(r.template.params.get("buy_grid_count") or 0) == 0
    assert int(r.template.params.get("sell_grid_count") or 0) >= 2


def test_no_template_fallback_is_safe():
    sub = SubScores(
        range_score=5,
        liquidity_score=5,
        spread_score=5,
        fee_efficiency_score=5,
        exposure_safety_score=5,
        data_quality_score=5,
        btc_market_risk_score=5,
    )
    r = _select(12, RegimeTag.BREAKOUT_RISK, RiskState.BLOCKED.value, 30, 0.0, sub)
    assert r.fallback_used or r.selected_template_key
    assert r.fallback_reason or r.selected_template_key
    if r.template:
        assert int(r.template.params.get("buy_grid_count") or 0) == 0 or r.final_action in (
            FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            FinalAction.BALANCED_GRID.value,
        )
    else:
        assert r.final_action in (
            FinalAction.WAIT.value,
            FinalAction.WAIT_SAFETY.value,
            FinalAction.NO_TRADE.value,
            FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            FinalAction.BALANCED_GRID.value,
        )


def test_selector_logs_reject_reasons():
    r = _select(62, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, 50, 0.44)
    assert r.candidate_count >= 1
    if r.filtered_out:
        summary = r.filter_summary or r.to_dict()["diagnostics"]["reject_summary"]
        assert sum(summary.values()) > 0


def test_decision_snapshot_consistency():
    clear_pool_cache()
    m = market_bundle(symbol="SOLUSDT", price=67.8)
    pf = portfolio(50, 0.0)
    engine = DynamicParamScoreEngine()
    decision = engine.calculate_decision(
        symbol="SOLUSDT",
        market_data=m,
        portfolio_state=pf,
        exchange_constraints=constraints(),
        bot_context=ctx(budget=50),
    )
    result = decision_to_param_assistant_result(decision, 50, "SOLUSDT")
    assert result["param_score"] == decision.param_score
    assert result["risk_state"] == decision.risk_state
    assert result["regime_tag"] == decision.regime_tag
    assert result["explain"] == decision.explain
    assert result["rationale"]["sub_scores"] == decision.telemetry["sub_scores"]
    assert result["decision_id"] == decision.decision_id
    pool = decision.telemetry.get("param_pool") or {}
    assert pool.get("pool_version")
    assert pool.get("diagnostics", {}).get("param_score") == decision.param_score


def test_pool_has_minimum_template_coverage():
    pool = build_v1_pool()
    assert len(pool) >= 120
    families = {t.profile_family for t in pool if t.status == "active"}
    for fam in ProfileFamily:
        assert fam.value in families, f"missing profile family {fam.value}"

    fee_gap_keys = {
        t.template_key
        for t in pool
        if t.score_min <= 69
        and t.score_max >= 60
        and RegimeTag.BALANCED_RANGE.value in t.supported_regimes
        and (
            FeeTier.FEE_BAD.value in t.fee_tiers
            or FeeTier.FEE_WEAK.value in t.fee_tiers
        )
    }
    assert "BALANCED_RANGE_60_69_FEE_BAD_WAIT" in fee_gap_keys  # legacy key; action is ACTIVE_DEFENSIVE_GRID
    fee_bad_templates = [t for t in pool if t.template_key == "BALANCED_RANGE_60_69_FEE_BAD_WAIT"]
    if fee_bad_templates:
        assert fee_bad_templates[0].final_action in (
            FinalAction.ACTIVE_DEFENSIVE_GRID.value,
            FinalAction.WAIT.value,
        )
    assert "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT" in fee_gap_keys
    assert "BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID" in fee_gap_keys

    small_sell = [
        t
        for t in pool
        if t.profile_family == ProfileFamily.SELL_MANAGEMENT_ONLY.value
        and "SMALL" in t.budget_tiers
    ]
    assert small_sell

    trending_down = [
        t
        for t in pool
        if RegimeTag.TRENDING_DOWN.value in t.supported_regimes
        and t.final_action in (FinalAction.WAIT.value, FinalAction.SELL_MANAGEMENT_ONLY.value)
    ]
    assert trending_down

    dump = [t for t in pool if RegimeTag.DUMP_RISK.value in t.supported_regimes]
    assert any(t.template_key == "DUMP_RISK_ANY_NO_TRADE" for t in dump)

    overexposed = [
        t for t in pool if ExposureTier.OVEREXPOSED.value in t.exposure_tiers
    ]
    assert any(t.template_key == "OVEREXPOSED_ANY_RECOVERY_SELL" for t in overexposed)
