"""Param pool renderer tests."""

from __future__ import annotations

from app.services.dynamic_param_score.models import RegimeTag
from app.services.dynamic_param_score.param_pool.defaults import build_v1_pool
from app.services.dynamic_param_score.param_pool.renderer import render_template
from tests.dynamic_param_score.conftest import constraints, portfolio


def _template(key: str):
    for t in build_v1_pool():
        if t.template_key == key:
            return t
    raise KeyError(key)


def test_render_sell_management_no_buy():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    tmpl = _template("BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT")
    m = market_bundle(price=67.8)
    pf = portfolio(50, 0.44)
    ind = compute_indicators(m, pf)
    params = render_template(
        tmpl,
        param_score=62,
        regime=RegimeTag.BALANCED_RANGE,
        ind=ind,
        constraints=constraints(),
        current_exposure_frac=0.44,
        budget_usdt=50,
        min_notional=5.0,
    )
    assert params is not None
    assert params.buy_grid_count == 0
    assert params.sell_grid_count >= 2
    assert params.emergency_no_buy is True
    assert params.max_base_exposure_frac <= 0.60


def test_render_spacing_respects_friction_floor():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    tmpl = _template("BALANCED_RANGE_STANDARD_60_69_CAUTION_GRID")
    m = market_bundle(price=100.0)
    pf = portfolio(200, 0.35)
    ind = compute_indicators(m, pf)
    params = render_template(
        tmpl,
        param_score=65,
        regime=RegimeTag.BALANCED_RANGE,
        ind=ind,
        constraints=constraints(),
        budget_usdt=200,
        min_notional=5.0,
    )
    assert params is not None
    assert params.buy_grid_spacing_pct >= 0.45
    assert params.sell_grid_spacing_pct >= 0.45
    assert len(params.buy_qty_distribution) == params.buy_grid_count


def test_render_active_grid_counts():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    tmpl = _template("RANGE_HIGH_VOL_MEDIUM_75_89_ACTIVE_GRID")
    m = market_bundle(price=100.0)
    pf = portfolio(500, 0.35)
    ind = compute_indicators(m, pf)
    params = render_template(
        tmpl,
        param_score=80,
        regime=RegimeTag.RANGE_HIGH_VOL,
        ind=ind,
        constraints=constraints(),
        budget_usdt=500,
        min_notional=5.0,
    )
    assert params is not None
    assert params.buy_grid_count >= 4
    assert params.sell_grid_count >= 4
