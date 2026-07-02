"""DPS Engine V4 — 300k shelf-routed pool tests."""

from __future__ import annotations

import os
import time

import pytest

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    FinalAction,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    clean_route_key,
    is_forbidden_fallback,
    route_key,
    structure_from_flags_v4,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    build_v4_indexes,
    market_signature_v4_from_live,
    route_key_for_signature,
)
from app.services.dynamic_param_score.param_generator.param_library_builder_v4 import (
    FAST_TEST_POOL_TARGET_V4,
    POOL_TARGET_V4,
    POOL_VERSION_V4,
    build_dps_v4_pool,
    generate_v4_profiles,
)
from app.services.dynamic_param_score.param_generator.scenario_specs_v4 import (
    SCENARIO_SPECS,
    validate_scenario_direction,
)
from app.services.dynamic_param_score.param_generator.v4_scoring import (
    hard_reject_v4,
    structure_fit_score,
)
from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4 as PV4
from app.services.dynamic_param_score.param_pool.selector import select_template


@pytest.fixture
def portfolio():
    return PortfolioState(
        base_balance=0.5,
        quote_balance=40.0,
        base_value_usdt=35.0,
        quote_value_usdt=40.0,
        total_equity_usdt=75.0,
        current_base_exposure_frac=0.47,
    )


@pytest.fixture
def constraints():
    return ExchangeConstraints(
        min_notional=5.0,
        step_size=0.0001,
        tick_size=0.01,
        min_qty=0.0001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
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
        fee_efficiency_score=55,
        data_quality_score=100,
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


@pytest.fixture(scope="module")
def v4_pool():
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    return build_dps_v4_pool(total_target=FAST_TEST_POOL_TARGET_V4, migrate_v3=False)


def test_route_key_format():
    rk = clean_route_key("A1", "R6", "S2", "V3", "NORMAL")
    assert rk == "A1|R6|S2|V3|NORMAL"


def test_lower_lows_higher_highs_structure_separation():
    assert structure_fit_score("S2", "S3") == 0.0
    assert structure_fit_score("S3", "S2") == 0.0
    assert structure_fit_score("S2", "S2") == 1.0


def test_forbidden_fallback_lower_to_higher():
    assert is_forbidden_fallback("R6", "R9")
    assert is_forbidden_fallback("R8", "R2")
    assert not is_forbidden_fallback("R6", "R7")


def test_scenario_direction_lower_lows():
    spec = SCENARIO_SPECS["LOWER_LOWS_WEAK_DOWN_RANGE"]
    ok, errs = validate_scenario_direction(
        spec, 0.30, 0.70, [1.80, 4.00, 8.00], [1.25, 3.00]
    )
    assert ok, errs
    bad, errs = validate_scenario_direction(
        spec, 0.55, 0.45, [1.25, 3.00], [1.80, 4.00, 8.00]
    )
    assert not bad


def test_market_signature_v4_has_route_key():
    sig = market_signature_v4_from_live(
        symbol="ETHUSDT",
        budget=75.0,
        regime="TRENDING_DOWN",
        risk_level="NORMAL",
        volatility_percentile=45.0,
        lower_lows=True,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=1.2,
    )
    assert sig["route_key"]
    assert sig["structure_code"] == "S2"
    assert sig["direction_bias"] == "DOWN_BIAS"
    assert sig["grid_bias"] == "BUY_WIDER_SELL_CLOSER"


def test_v4_fast_pool_builds(v4_pool):
    assert len(v4_pool) >= 100
    assert all(t.template_key.startswith("DPLV4_") for t in v4_pool[:20])


def test_v4_profiles_have_ladders(v4_pool):
    for t in v4_pool[:50]:
        dps = (t.params or {}).get("dps_profile") or {}
        assert dps.get("buy_grid_ladder_pcts"), t.template_key
        assert dps.get("sell_grid_ladder_pcts"), t.template_key
        assert dps.get("route_key"), t.template_key


def test_v4_lower_lows_vs_higher_highs_allocations(v4_pool):
    lower = [
        t for t in v4_pool
        if ((t.params or {}).get("dps_profile") or {}).get("scenario")
        == "LOWER_LOWS_WEAK_DOWN_RANGE"
    ]
    higher = [
        t for t in v4_pool
        if ((t.params or {}).get("dps_profile") or {}).get("scenario")
        == "HIGHER_HIGHS_WEAK_UP_RANGE"
    ]
    assert lower or higher, "expected directional scenario profiles in pool"
    if lower:
        dps = lower[0].params["dps_profile"]
        assert dps["base_alloc_frac"] <= 0.40
        assert dps["quote_alloc_frac"] >= 0.60
    if higher:
        dps = higher[0].params["dps_profile"]
        assert dps["base_alloc_frac"] >= 0.50
        assert dps["quote_alloc_frac"] <= 0.50


def test_v4_index_lookup_narrowing(v4_pool):
    from app.services.dynamic_param_score.param_pool.sqlite_store import ParamPool

    pool = ParamPool(pool_version=PV4, templates=v4_pool)
    pool.build_memory_indexes()
    sig = market_signature_v4_from_live(
        symbol="BTCUSDT",
        budget=75.0,
        regime="BALANCED_RANGE",
        risk_level="NORMAL",
        volatility_percentile=50.0,
        lower_lows=False,
        higher_highs=False,
        fee_efficiency_score=60,
    )
    candidates = pool.query_dps_signature_candidates(sig)
    assert 1 <= len(candidates) <= 500


def test_v4_selector_uses_index_not_full_scan(v4_pool, portfolio, constraints, monkeypatch):
    from app.services.dynamic_param_score.param_pool import versioning
    from app.services.dynamic_param_score.param_pool.models import ParamPoolVersion
    from app.services.dynamic_param_score.param_pool.versioning import load_indexed_pool

    versioning._CACHED_POOLS[PV4] = v4_pool  # noqa: SLF001
    versioning._CACHED_INDEXED_POOLS[PV4] = load_indexed_pool(PV4)  # noqa: SLF001
    pv = ParamPoolVersion(
        version_id=PV4,
        label="v4 test",
        template_count=len(v4_pool),
        status="active",
    )
    monkeypatch.setattr(
        "app.services.dynamic_param_score.param_pool.selector.get_active_pool",
        lambda: (pv, v4_pool),
    )
    from app.services.dynamic_param_score.param_pool.manifest import build_manifest
    from app.services.dynamic_param_score.param_pool.sqlite_store import ParamPool

    def _indexed_test_pool(_vid: str):
        p = ParamPool(
            pool_version=PV4,
            templates=v4_pool,
            manifest=build_manifest(v4_pool, PV4),
        )
        p.build_memory_indexes()
        return p

    monkeypatch.setattr(
        "app.services.dynamic_param_score.param_pool.selector.load_indexed_pool",
        _indexed_test_pool,
    )
    ind = IndicatorSnapshot(
        lower_lows=True,
        higher_highs=False,
        atr14_pct_5m=1.1,
        orderbook_spread_pct=0.03,
    )
    result = select_template(
        62,
        RegimeTag.BALANCED_RANGE,
        RiskState.NORMAL.value,
        _sub(fee_efficiency_score=55),
        ind,
        portfolio,
        constraints,
        75.0,
        5.0,
        symbol="ETHUSDT",
    )
    assert result.pool_version == PV4
    assert result.selection_context.get("templates_scanned", 999) <= 500
    if not result.fallback_used:
        assert result.selection_context.get("selection_path")
    assert result.template is not None


def test_fee_bad_never_wait_v4(v4_pool):
    fee_bad = [
        t for t in v4_pool
        if ((t.params or {}).get("dps_profile") or {}).get("fee_code") == "F6"
    ]
    for t in fee_bad[:10]:
        assert t.final_action not in (FinalAction.WAIT.value, FinalAction.SAFE_WAIT.value)


@pytest.mark.slow
def test_v4_full_pool_300k():
    if os.environ.get("DPS_FULL_POOL") != "1":
        pytest.skip("Full 300k build — run with DPS_FULL_POOL=1")
    from app.services.dynamic_param_score.param_generator.pool_disk_cache_v4 import (
        try_load_v4_pool_from_disk,
    )

    pool = try_load_v4_pool_from_disk() or build_dps_v4_pool(total_target=POOL_TARGET_V4)
    assert len(pool) == POOL_TARGET_V4
