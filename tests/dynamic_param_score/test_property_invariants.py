"""Parametric invariants across budget/exposure/pattern grid."""

from __future__ import annotations

import itertools

import pytest

from app.services.dynamic_param_score.adapters import params_to_grid_config
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from tests.dynamic_param_score.factories import (
    make_constraints,
    make_context,
    make_market_bundle,
    make_portfolio_state,
)

ALLOWED = {a.value for a in FinalAction}
TOLERANCE = 0.02


@pytest.mark.parametrize(
    "budget,min_notional,exposure,pattern",
    list(
        itertools.islice(
            itertools.product(
                [10, 25, 50, 75, 100, 150, 500],
                [5, 10],
                [0.0, 0.25, 0.50, 0.75],
                ["balanced_range", "trending_down", "dump_risk", "low_liquidity"],
            ),
            48,
        )
    ),
)
def test_decision_invariants(budget, min_notional, exposure, pattern):
    engine = DynamicParamScoreEngine()
    market = make_market_bundle(pattern=pattern, quote_vol=max(50_000_000, budget * 1_000_000))
    pf = make_portfolio_state(budget_usdt=budget, base_exposure_frac=exposure)
    d = engine.calculate_decision(
        market.symbol,
        market,
        pf,
        make_constraints(min_notional=min_notional),
        make_context(budget_usdt=budget),
    )
    assert 0 <= d.param_score <= 100
    assert 0 <= d.confidence_score <= 100
    assert 0 <= d.risk_score <= 100
    assert d.final_action in ALLOWED

    p = d.params
    if p:
        assert 0 <= p.base_alloc_frac <= 1
        assert 0 <= p.quote_alloc_frac <= 1
        assert abs(p.base_alloc_frac + p.quote_alloc_frac - 1) < TOLERANCE
        assert 0 <= p.max_base_exposure_frac <= 0.80 + TOLERANCE

        if d.regime_tag == RegimeTag.TRENDING_DOWN.value:
            assert d.final_action != FinalAction.ACTIVE_GRID.value
            assert p.base_alloc_frac <= 0.30 + TOLERANCE
            assert p.max_base_exposure_frac <= p.base_alloc_frac + 0.06 + TOLERANCE

        if d.regime_tag == RegimeTag.DUMP_RISK.value:
            assert d.final_action in (
                FinalAction.NO_TRADE.value,
                FinalAction.WAIT.value,
                FinalAction.WAIT_SAFETY.value,
                FinalAction.SAFE_WAIT.value,
            )
            assert p.buy_grid_count == 0

        cur_exp = pf.current_base_exposure_frac
        if cur_exp >= p.max_base_exposure_frac - 0.001:
            assert p.buy_grid_count == 0

        wait_actions = {
            FinalAction.WAIT.value,
            FinalAction.WAIT_SAFETY.value,
            FinalAction.SAFE_WAIT.value,
        }
        if d.final_action in wait_actions:
            assert p.buy_grid_count == 0 and p.sell_grid_count == 0

        if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
            assert p.buy_grid_count == 0 and p.sell_grid_count > 0

        if d.deployable and d.final_action in (
            FinalAction.BALANCED_GRID.value,
            FinalAction.DEFENSIVE_GRID.value,
            FinalAction.ACTIVE_GRID.value,
        ):
            assert p.buy_grid_count >= 1 and p.sell_grid_count >= 1

        if d.deployable and d.final_action == FinalAction.ACTIVE_DEFENSIVE_GRID.value:
            assert p.buy_grid_count >= 1 or p.sell_grid_count >= 1

        if p.buy_grid_count == 0:
            cfg = params_to_grid_config(p)
            assert cfg.get("rebuy_enabled") is False

        ladder = float(d.telemetry.get("buy_ladder_budget_usdt") or 0)
        sell_budget = float(pf.base_value_usdt or budget * p.base_alloc_frac)
        for w in p.buy_qty_distribution:
            if p.buy_grid_count > 0 and ladder > 0:
                assert ladder * w >= min_notional - 0.1 or ladder < min_notional
        if p.sell_grid_count > 0 and sell_budget > 0:
            assert sell_budget >= min_notional - 0.1, (
                "sell side should drop grids when budget < min_notional"
            )
        for w in p.sell_qty_distribution:
            if p.sell_grid_count > 0 and sell_budget >= min_notional:
                assert sell_budget * w >= min_notional - 0.1

        if p.buy_grid_count > 0:
            worst = float(d.telemetry.get("worst_case_base_exposure_frac") or 0)
            cap = float(p.max_base_exposure_frac)
            assert worst <= cap + TOLERANCE
