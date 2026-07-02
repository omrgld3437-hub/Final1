"""SOLUSDT 50 USDT deep regression."""

from __future__ import annotations

import math

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles
from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state


def _sol_market_deep():
    c5 = mk_candles(
        [100.0 * (1 + 0.001 * math.sin(i / 3.0)) for i in range(288)],
        interval_ms=300_000,
    )
    return make_market_bundle(
        symbol="SOLUSDT",
        price=100.0,
        pattern="balanced_range",
        quote_vol=228_000_000,
        spread_pct=0.04,
    )


def test_sol_50_regression_deep():
    engine = DynamicParamScoreEngine()
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.47, price=100)
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market_deep(),
        pf,
        constraints(min_notional=5),
        ctx("param_assistant", 50),
    )
    assert 55 <= d.param_score <= 69, f"param_score={d.param_score}"
    assert d.final_action != FinalAction.ACTIVE_GRID.value
    assert d.confidence_score <= 60

    min_n = 5.0
    headroom = float(d.telemetry.get("exposure_headroom_quote_usdt") or 0)
    if headroom < min_n and d.params and d.params.sell_grid_count > 0:
        assert d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value
        assert d.deployable is True
        assert d.params.buy_grid_count == 0
        assert d.params.sell_grid_count in (2, 3)
        assert "satış yönetimi" in d.explain.lower()
    elif headroom < min_n:
        assert d.final_action in (FinalAction.WAIT.value, FinalAction.NO_TRADE.value)
        assert not d.deployable

    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value and d.params:
        sell_budget = 50.0 * d.params.base_alloc_frac
        for w in d.params.sell_qty_distribution:
            assert sell_budget * w >= min_n - 0.05

    tele_keys = {
        "exposure_headroom_quote_usdt",
        "buy_ladder_budget_usdt",
        "worst_case_base_exposure_frac",
        "min_notional",
    }
    for k in tele_keys:
        assert k in d.telemetry, f"missing telemetry {k}"

    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert r["ok"] is True
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert r["sell_management_only"] is True
        assert r["apply_policy"] == "allow"
