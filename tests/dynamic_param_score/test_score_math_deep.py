"""Deep score math and friction invariants."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.scoring import compute_sub_scores
from tests.dynamic_param_score.factories import (
    make_candles,
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)


def _assert_scores_bounded(decision) -> None:
    assert 0 <= decision.param_score <= 100
    assert 0 <= decision.confidence_score <= 100
    assert 0 <= decision.risk_score <= 100
    sub = decision.telemetry.get("sub_scores") or {}
    for k, v in sub.items():
        if isinstance(v, (int, float)):
            assert 0 <= v <= 100, f"{k}={v} out of range"


@pytest.mark.parametrize(
    "pattern,data_quality",
    [
        ("balanced_range", "good"),
        ("dump_risk", "good"),
        ("low_liquidity", "good"),
        ("high_vol_unstable", "good"),
        ("bad_data_gaps", "bad"),
        ("zero_volume", "zero_vol"),
        ("flat_dead_market", "good"),
    ],
)
def test_all_scores_bounded_across_scenarios(pattern, data_quality):
    engine = DynamicParamScoreEngine()
    market = make_market_bundle(pattern=pattern, data_quality=data_quality)
    d = engine.calculate_decision(
        market.symbol,
        market,
        make_portfolio_state(budget_usdt=50),
        make_constraints(),
        make_context(budget_usdt=50),
    )
    _assert_scores_bounded(d)
    assert d.final_action in {a.value for a in FinalAction}


def test_high_spread_blocks_active_grid():
    engine = DynamicParamScoreEngine()
    low = make_market_bundle(spread_pct=0.02)
    high = make_market_bundle(spread_pct=0.80)
    pf = make_portfolio_state(budget_usdt=500, base_exposure_frac=0.2)
    ctx = make_context(budget_usdt=500)
    d_low = engine.calculate_decision("SOLUSDT", low, pf, make_constraints(), ctx)
    d_high = engine.calculate_decision("SOLUSDT", high, pf, make_constraints(), ctx)
    sub_low = d_low.telemetry.get("sub_scores") or {}
    sub_high = d_high.telemetry.get("sub_scores") or {}
    assert sub_high.get("spread_score", 0) <= sub_low.get("spread_score", 100)
    assert d_high.final_action != FinalAction.ACTIVE_GRID.value
    gate_codes = {g.reason_code for g in d_high.safety_gates}
    friction_codes = {
        c
        for c in gate_codes
        if any(x in c for x in ("SPREAD", "FRICTION", "FEE", "ACTIVE_FORBIDDEN"))
    }
    assert friction_codes or sub_high.get("spread_score", 0) < 70


def test_btc_dump_depresses_scores():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=500, base_exposure_frac=0.2)
    ctx = make_context(budget_usdt=500)
    normal = make_market_bundle(btc_pattern="normal")
    dump = make_market_bundle(btc_pattern="dump")
    d_n = engine.calculate_decision("SOLUSDT", normal, pf, make_constraints(), ctx)
    d_d = engine.calculate_decision("SOLUSDT", dump, pf, make_constraints(), ctx)
    sub_n = d_n.telemetry.get("sub_scores") or {}
    sub_d = d_d.telemetry.get("sub_scores") or {}
    assert sub_d.get("btc_market_risk_score", 50) <= sub_n.get("btc_market_risk_score", 50)
    assert d_d.param_score <= d_n.param_score + 5
    assert d_d.risk_score >= d_n.risk_score - 5
    assert d_d.final_action != FinalAction.ACTIVE_GRID.value


def test_bad_data_not_deployable():
    engine = DynamicParamScoreEngine()
    market = make_market_bundle(pattern="bad_data_gaps", data_quality="bad")
    d = engine.calculate_decision(
        "SOLUSDT",
        market,
        make_portfolio_state(),
        make_constraints(),
        make_context(),
    )
    sub = d.telemetry.get("sub_scores") or {}
    if sub.get("data_quality_score", 100) < 70:
        assert not d.deployable
        assert d.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)
