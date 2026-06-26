"""Section 20 regression — BALANCED_RANGE 61 DEFENSIVE FEE_BAD."""

from __future__ import annotations

from app.services.dynamic_param_score.models import FinalAction, RegimeTag, RiskState
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache
from tests.dynamic_param_score.conftest import constraints, market_bundle, portfolio
from tests.dynamic_param_score.test_fee_bad_templates import _sub


def _select(score, exposure):
    clear_pool_cache()
    m = market_bundle(symbol="SOLUSDT", price=67.8)
    pf = portfolio(50, exposure)
    from app.services.dynamic_param_score.indicators import compute_indicators

    ind = compute_indicators(m, pf)
    return select_template(
        score,
        RegimeTag.BALANCED_RANGE,
        RiskState.DEFENSIVE.value,
        _sub(),
        ind,
        pf,
        constraints(),
        50,
        5.0,
    )


def test_balanced_range_61_defensive_fee_bad_active_without_base():
    r = _select(61, 0.0)
    assert r.final_action != FinalAction.WAIT.value
    assert r.final_action in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
    )
    assert r.template is not None
    assert int(r.template.params.get("buy_grid_count") or 0) >= 1
    assert int(r.template.params.get("sell_grid_count") or 0) >= 1


def test_balanced_range_61_defensive_fee_bad_sell_management_with_base():
    r = _select(61, 0.44)
    assert r.selected_template_key in (
        "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT",
        "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT",
    )
    assert r.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
    assert r.fallback_used is False
    assert r.template is not None
    assert int(r.template.params.get("buy_grid_count") or 0) == 0
    assert int(r.template.params.get("sell_grid_count") or 0) >= 1
    assert r.template.params.get("rebuy_enabled") is False
