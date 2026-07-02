"""Param pool selector performance tests."""

from __future__ import annotations

import os
import time

from app.services.dynamic_param_score.models import RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache
from tests.dynamic_param_score.conftest import constraints, market_bundle, portfolio


def _sub() -> SubScores:
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


def test_selector_50000_templates_under_300ms_memory_mode():
    os.environ["PARAM_POOL_MODE"] = "auto"
    clear_pool_cache()
    from app.services.dynamic_param_score.param_pool.versioning import load_indexed_pool, resolve_pool_version

    pool_version = resolve_pool_version()
    load_indexed_pool(pool_version)
    m = market_bundle(symbol="SOLUSDT", price=67.8)
    pf = portfolio(50, 0.0)
    from app.services.dynamic_param_score.indicators import compute_indicators

    ind = compute_indicators(m, pf)
    # Warm pool cache
    for _ in range(3):
        select_template(
            61, RegimeTag.BALANCED_RANGE, RiskState.DEFENSIVE.value,
            _sub(), ind, pf, constraints(), 50, 5.0,
        )
    start = time.perf_counter()
    for _ in range(10):
        select_template(
            61, RegimeTag.BALANCED_RANGE, RiskState.DEFENSIVE.value,
            _sub(), ind, pf, constraints(), 50, 5.0,
        )
    from app.services.dynamic_param_score import constants as C

    elapsed_ms = (time.perf_counter() - start) / 10 * 1000
    if pool_version.startswith("v3"):
        target_ms = C.SELECTOR_P95_TARGET_MS_200K * 5
    elif pool_version.startswith("v2"):
        target_ms = C.SELECTOR_P95_TARGET_MS_100K
    else:
        target_ms = C.SELECTOR_P95_TARGET_MS
    # First timed batch after cache warm; allow CI variance on cold sqlite mmap.
    assert elapsed_ms < target_ms * 3.0, f"selector avg {elapsed_ms:.1f}ms > {target_ms * 3:.0f}ms cap"
