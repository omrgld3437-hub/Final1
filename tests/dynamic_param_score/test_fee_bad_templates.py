"""Fee-efficiency gap templates and decision snapshot consistency."""

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
from app.services.dynamic_param_score.param_pool.selector import select_template
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
    from app.services.dynamic_param_score.param_pool import versioning
    from tests.dynamic_param_score.conftest import _V3_INDEXED_SNAPSHOT, _V3_POOL_SNAPSHOT

    if _V3_POOL_SNAPSHOT is not None:
        versioning._CACHED_POOLS[versioning.resolve_pool_version()] = _V3_POOL_SNAPSHOT  # noqa: SLF001
    if _V3_INDEXED_SNAPSHOT is not None:
        vid = versioning.resolve_pool_version()
        versioning._CACHED_INDEXED_POOLS[vid] = _V3_INDEXED_SNAPSHOT  # noqa: SLF001
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
        FinalAction.LOW_FEE_WIDE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
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
    assert "uygulanabilir emir boyutu oluşmadığı için bekle" not in explain.lower()


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
    assert r.template is not None
    buy_n = int(r.template.params.get("buy_grid_count") or 0)
    sell_n = int(r.template.params.get("sell_grid_count") or 0)
    assert 1 <= buy_n <= 2
    assert 1 <= sell_n <= 3
    assert r.template.profile_family.endswith("LOW_FEE_WIDE_GRID_PROFILE")

    from app.services.dynamic_param_score.param_pool.renderer import render_template

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
    assert params is not None
    friction = total_friction_pct(c, float(ind.orderbook_spread_pct or 0.0))
    min_spacing = 4.0 * friction
    assert params.buy_grid_spacing_pct >= min_spacing - 1e-6
    assert r.final_action != FinalAction.ACTIVE_GRID.value


def test_decision_snapshot_consistency():
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
    if decision.risk_state == RiskState.NORMAL.value:
        assert "savunmacı risk" not in decision.explain.lower()
        assert "drawdown riski yüksek" not in decision.explain.lower()


def test_fee_bad_shows_active_defensive_grid_in_param_assistant():
    m = market_bundle(symbol="ETHUSDT", price=2500.0)
    pf = portfolio(50, 0.0)
    engine = DynamicParamScoreEngine()
    decision = engine.calculate_decision(
        symbol="ETHUSDT",
        market_data=m,
        portfolio_state=pf,
        exchange_constraints=constraints(),
        bot_context=ctx(budget=50),
    )
    assert decision.final_action != FinalAction.WAIT.value
    result = decision_to_param_assistant_result(decision, 50, "ETHUSDT")
    rec = result.get("recommendation_config") or result.get("ui_config")
    assert rec is not None, "Fee bad should expose deployable or recommended grid params"
    up = rec.get("up", {}).get("grids") or []
    down = rec.get("down", {}).get("grids") or []
    assert up or down
    if up:
        assert abs(sum(float(g["qty_pct"]) for g in up) - 100.0) < 0.15
    if down:
        assert abs(sum(float(g["qty_pct"]) for g in down) - 100.0) < 0.15
    assert result["result_type"] in ("recommended_grid", "deployable_grid")
    assert "uygulanabilir emir boyutu oluşmadığı için bekle" not in (decision.explain or "").lower()
    if decision.deployable:
        assert result["apply_policy"] == "allow"
