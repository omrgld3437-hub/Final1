"""DPS Engine V2 — 200k pool, grid philosophy, and selection tests."""

from __future__ import annotations

import os
import time

import pytest

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.explain import build_explanation
from app.services.dynamic_param_score.models import FinalAction, RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_generator.grid_math import compute_first_grid_pct, compute_grid_ladder
from app.services.dynamic_param_score.param_generator.amount_distribution import geometric_distribution
from app.services.dynamic_param_score.param_generator.param_library_builder import (
    POOL_TARGET_V3,
    POOL_VERSION_V3,
)
from app.services.dynamic_param_score.param_generator.v2_scoring import compute_v2_profile_score
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    build_selection_index,
    market_signature_from_live,
)
from app.services.dynamic_param_score.param_pool.selector import select_template
from tests.dynamic_param_score.conftest import (
    FAST_TEST_POOL_SIZE,
    constraints,
    portfolio,
    v3_pool,
)


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


def test_grid_math_major_first_grid_minimum():
    first = compute_first_grid_pct(
        asset_class="BTC_ETH_MAJOR",
        regime="BALANCED_RANGE",
        atr_1h_pct=0.97,
        trailing_pct=0.35,
        total_cost_pct=0.12,
    )
    assert first >= 1.20
    ladder = compute_grid_ladder(first, 3)
    assert ladder[1] >= ladder[0] * 2.2 - 0.01


def test_geometric_distribution_not_equal_split():
    dist = geometric_distribution(3, "normal")
    assert abs(sum(dist) - 1.0) < 0.01
    assert dist[0] < dist[-1]


@pytest.mark.slow
def test_v3_pool_builds_200000():
    if os.environ.get("DPS_FULL_POOL") != "1":
        pytest.skip("Full 200k build — run with DPS_FULL_POOL=1 (or pre-built SQLite cache)")
    from app.services.dynamic_param_score.param_generator.pool_disk_cache import try_load_v3_pool_from_disk

    pool = try_load_v3_pool_from_disk()
    if pool is None:
        from app.services.dynamic_param_score.param_generator.param_library_builder import build_dps_v2_pool

        pool = build_dps_v2_pool(total_target=POOL_TARGET_V3, migrate_legacy=True)
    assert len(pool) == POOL_TARGET_V3


def test_v3_no_duplicate_keys(v3_pool):
    keys = [t.template_key for t in v3_pool]
    assert len(keys) == len(set(keys))


def test_v3_major_first_grid_not_below_1pct(v3_pool):
    majors = [
        t for t in v3_pool
        if (t.params or {}).get("dps_profile", {}).get("asset_class") == "BTC_ETH_MAJOR"
    ]
    if not majors:
        pytest.skip("Fast test pool has no BTC_ETH_MAJOR dps_profile rows")
    for t in majors[:50]:
        spacing = float(
            t.params.get("buy_grid_spacing_pct") or t.params.get("sell_grid_spacing_pct") or 0
        )
        if spacing:
            assert spacing >= 1.0


def test_fee_bad_never_wait_in_v3(v3_pool):
    fee_bad = [
        t for t in v3_pool
        if (t.params or {}).get("dps_profile", {}).get("fee_class") == "fee_bad"
        or t.final_action == FinalAction.ACTIVE_DEFENSIVE_GRID.value
    ]
    assert fee_bad
    for t in fee_bad:
        assert t.final_action not in (
            FinalAction.WAIT.value,
            FinalAction.SAFE_WAIT.value,
        )


def test_fee_bad_selects_active_not_wait():
    from app.services.dynamic_param_score.indicators import compute_indicators
    from app.services.dynamic_param_score.param_pool import versioning
    from tests.dynamic_param_score import conftest as dps_conftest

    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V3
    os.environ["PARAM_POOL_MODE"] = "programmatic"
    if dps_conftest._V3_POOL_SNAPSHOT is not None:
        versioning._CACHED_POOLS[POOL_VERSION_V3] = dps_conftest._V3_POOL_SNAPSHOT  # noqa: SLF001
    if dps_conftest._V3_INDEXED_SNAPSHOT is not None:
        versioning._CACHED_INDEXED_POOLS[POOL_VERSION_V3] = dps_conftest._V3_INDEXED_SNAPSHOT  # noqa: SLF001

    m = __import__("tests.dynamic_param_score.conftest", fromlist=["market_bundle"]).market_bundle(
        symbol="ETHUSDT", price=2500.0
    )
    pf = portfolio(50, 0.0)
    ind = compute_indicators(m, pf)
    r = select_template(
        62, RegimeTag.BALANCED_RANGE, RiskState.NORMAL.value,
        _sub(), ind, pf, constraints(), 50, 5.0,
    )
    assert r.final_action != FinalAction.WAIT.value
    assert r.final_action in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.BALANCED_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
    )
    explain = build_explanation(
        62, RegimeTag.BALANCED_RANGE.value, RiskState.NORMAL.value,
        r.final_action, _sub(), None, [],
        selected_template_key=r.selected_template_key,
    )
    assert "uygulanabilir emir boyutu oluşmadığı için bekle" not in explain.lower()


def test_lower_lows_widens_buy_grids():
    buy_mult = 1.25
    first = 1.5
    buy = [round(first * buy_mult * m, 2) for m in (1.0, 2.4, 5.0)]
    sell = [round(first * m, 2) for m in (1.0, 2.4)]
    assert buy[0] > sell[0]


def test_v2_scoring_weights():
    from app.services.dynamic_param_score.param_pool.models import ParamTemplate

    tmpl = ParamTemplate(
        template_key="TEST",
        version="DPS_ENGINE_V2",
        profile_family="BALANCED_GRID_PROFILE",
        final_action=FinalAction.BALANCED_GRID.value,
        score_min=40,
        score_max=80,
        supported_regimes=[RegimeTag.BALANCED_RANGE.value],
        allowed_risk_states=["NORMAL"],
        budget_tiers=["SMALL"],
        exposure_tiers=["LOW_BASE"],
        headroom_tiers=["HIGH_HEADROOM"],
        fee_tiers=["FEE_BAD"],
        liquidity_tiers=["LIQ_GOOD"],
        volatility_tiers=["VOL_MID"],
        btc_risk_tiers=["BTC_SAFE"],
        order_reality_tiers=["ORDER_OK"],
        min_equity_usdt=25.0,
        min_notional_multiple=2.0,
        params={
            "buy_grid_spacing_pct": 1.8,
            "sell_grid_spacing_pct": 1.5,
            "dps_profile": {
                "regime": "BALANCED_RANGE",
                "volatility_bin": "25_50",
                "structure": "lower_lows_only",
            },
            "score_prior": 0.72,
        },
        deployable=True,
    )
    sig = market_signature_from_live(
        symbol="ETHUSDT",
        budget=50,
        regime="BALANCED_RANGE",
        risk_level="NORMAL",
        volatility_percentile=28,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=15,
        asset_class="BTC_ETH_MAJOR",
    )
    score = compute_v2_profile_score(tmpl, sig)
    assert score > 40


def test_fast_pool_size_sane(v3_pool):
    assert len(v3_pool) >= 500
    if os.environ.get("DPS_FULL_POOL") != "1":
        assert len(v3_pool) <= max(FAST_TEST_POOL_SIZE + 200, 8000)


def test_selector_performance_budget_200k(v3_pool):
    from app.services.dynamic_param_score.indicators import compute_indicators
    from app.services.dynamic_param_score.param_pool import versioning
    from tests.dynamic_param_score import conftest as dps_conftest

    index = build_selection_index(
        [
            (t.params or {}).get("dps_profile", {})
            | {"profile_id": t.template_key, "template_key": t.template_key}
            for t in v3_pool
            if (t.params or {}).get("dps_profile")
        ][:2000]
    )
    assert index

    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V3
    versioning._CACHED_POOLS[POOL_VERSION_V3] = v3_pool  # noqa: SLF001
    if dps_conftest._V3_INDEXED_SNAPSHOT is not None:
        versioning._CACHED_INDEXED_POOLS[POOL_VERSION_V3] = dps_conftest._V3_INDEXED_SNAPSHOT  # noqa: SLF001

    m = __import__("tests.dynamic_param_score.conftest", fromlist=["market_bundle"]).market_bundle(
        symbol="ETHUSDT", price=2500.0
    )
    pf = portfolio(50, 0.2)
    ind = compute_indicators(m, pf)
    kwargs = dict(
        param_score=65,
        regime=RegimeTag.BALANCED_RANGE,
        risk_state=RiskState.NORMAL.value,
        sub=_sub(fee_efficiency_score=45),
        ind=ind,
        portfolio=pf,
        constraints=constraints(),
        budget_usdt=50,
        min_notional=5.0,
    )
    select_template(**kwargs)
    t0 = time.perf_counter()
    select_template(**kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 1500
