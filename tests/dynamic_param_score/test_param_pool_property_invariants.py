"""Param pool property invariants."""

from __future__ import annotations

import random

from app.services.dynamic_param_score.models import RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_pool.defaults import build_v1_pool
from app.services.dynamic_param_score.param_pool.selector import (
    build_selection_context,
    select_template,
)
from app.services.dynamic_param_score.param_pool.validators import validate_template
from tests.dynamic_param_score.conftest import constraints, portfolio


def test_every_template_structurally_valid():
    for t in build_v1_pool():
        ok, errs = validate_template(t)
        assert ok, f"{t.template_key}: {errs}"


def test_fallback_never_selects_buy_when_no_headroom():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    m = market_bundle(price=100.0)
    pf = portfolio(50, 0.55)
    ind = compute_indicators(m, pf)
    sub = SubScores(
        range_score=65,
        liquidity_score=70,
        spread_score=70,
        fee_efficiency_score=40,
        exposure_safety_score=50,
        data_quality_score=80,
    )
    ctx_sel = build_selection_context(
        55, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, ind, pf, constraints(), 50, 5.0,
    )
    assert ctx_sel.headroom_tier in ("NO_HEADROOM", "LOW_HEADROOM", "MEDIUM_HEADROOM")

    r = select_template(
        55, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, ind, pf, constraints(), 50, 5.0,
    )
    if r.template and int(r.template.params.get("buy_grid_count") or 0) > 0:
        assert ctx_sel.headroom_tier not in ("NO_HEADROOM", "LOW_HEADROOM")


def test_random_contexts_produce_deterministic_selection():
    random.seed(42)
    from app.services.dynamic_param_score.indicators import compute_indicators
    from tests.dynamic_param_score.conftest import market_bundle

    m = market_bundle()
    for _ in range(20):
        score = random.randint(20, 85)
        exp = random.uniform(0, 0.7)
        budget = random.choice([50, 150, 500, 2000])
        pf = portfolio(budget, exp)
        ind = compute_indicators(m, pf)
        sub = SubScores()
        r1 = select_template(
            score, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value,
            sub, ind, pf, constraints(), budget, 5.0,
        )
        r2 = select_template(
            score, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value,
            sub, ind, pf, constraints(), budget, 5.0,
        )
        assert r1.selected_template_key == r2.selected_template_key
        assert r1.final_action == r2.final_action
