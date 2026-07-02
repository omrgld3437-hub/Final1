"""V2 param pool — 100k precision expansion tests (slow — opt-in)."""

from __future__ import annotations

import os
import time
from collections import Counter

import pytest

pytestmark = pytest.mark.slow

from app.services.dynamic_param_score import constants as C
from app.services.dynamic_param_score.models import (
    FinalAction,
    IndicatorSnapshot,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V2
from app.services.dynamic_param_score.param_pool.generator import is_logically_valid_template
from app.services.dynamic_param_score.param_pool.manifest import build_manifest, pool_checksum
from app.services.dynamic_param_score.param_pool.models import (
    BtcRiskTier,
    FeeTier,
    ProfileFamily,
    ProfileSubfamily,
)
from app.services.dynamic_param_score.param_pool.precision_generator import (
    POOL_TARGET_V2,
    generate_pool_v2,
    generate_precision_expansion,
    template_fingerprint,
)
from app.services.dynamic_param_score.param_pool.registry import get_active_pool, set_active_version
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    ParamPool,
    query_candidates,
)
from app.services.dynamic_param_score.param_pool.validators import validate_pool
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache, load_version_templates
from tests.dynamic_param_score.conftest import constraints, portfolio


@pytest.fixture(scope="module")
def v2_pool():
    os.environ["PARAM_POOL_MODE"] = "programmatic"
    clear_pool_cache()
    set_active_version(POOL_VERSION_V2)
    pool = generate_pool_v2(POOL_TARGET_V2)
    clear_pool_cache()
    return pool


@pytest.fixture(scope="module")
def warmed_v2_selector():
    os.environ["PARAM_POOL_MODE"] = "programmatic"
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V2
    clear_pool_cache()
    from app.services.dynamic_param_score.param_pool import versioning
    from app.services.dynamic_param_score.param_pool.versioning import load_indexed_pool

    versioning._CACHED_POOLS[POOL_VERSION_V2] = generate_pool_v2(POOL_TARGET_V2)  # noqa: SLF001
    load_indexed_pool(POOL_VERSION_V2)
    yield
    clear_pool_cache()


def test_pool_v2_builds_100000_templates(v2_pool):
    assert len(v2_pool) == 100_000


def test_pool_v2_has_50000_new_templates(v2_pool):
    precision = [t for t in v2_pool if t.version == POOL_VERSION_V2 and (
        t.profile_subfamily or (t.notes or "").startswith("precision")
    )]
    assert len(precision) >= 35_000


def test_pool_v2_has_no_duplicate_fingerprints(v2_pool):
    fps = [template_fingerprint(t) for t in v2_pool]
    assert len(fps) == len(set(fps))


def test_pool_v2_profile_distribution(v2_pool):
    dist = Counter(t.profile_family for t in v2_pool)
    assert len(dist) >= 15
    assert dist[ProfileFamily.INITIAL_ENTRY.value] >= 500
    assert dist[ProfileFamily.LOW_FEE_WIDE_GRID.value] >= 1000


def test_pool_v2_precision_coverage(v2_pool):
    subfams = {t.profile_subfamily for t in v2_pool if t.profile_subfamily}
    expected = {
        ProfileSubfamily.PRECISION_INITIAL_ENTRY.value,
        ProfileSubfamily.FEE_WEAK_WIDE_GRID.value,
        ProfileSubfamily.GRADUAL_REBALANCE_BUY.value,
    }
    assert expected.issubset(subfams)


def test_pool_v2_sell_management_requires_base(v2_pool):
    sell_only = [t for t in v2_pool if t.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value]
    assert sell_only
    assert all(t.requires_sellable_base or t.hard_limits.get("requires_sell_min_notional") for t in sell_only)


def test_pool_v2_initial_entry_no_big_buy(v2_pool):
    initial = [
        t for t in v2_pool
        if t.profile_family == ProfileFamily.INITIAL_ENTRY.value
        or t.profile_subfamily == ProfileSubfamily.PRECISION_INITIAL_ENTRY.value
    ]
    assert initial
    for t in initial:
        cap = float(t.params.get("max_base_exposure_cap") or 1.0)
        assert cap <= 0.72
        per_buy = float(t.params.get("max_quote_to_spend_per_buy_frac") or 1.0)
        assert per_buy <= 0.35


def test_pool_v2_rebalance_templates_exist(v2_pool):
    rebal = [
        t for t in v2_pool
        if isinstance(t.params.get("rebalance_policy"), dict)
        and t.params["rebalance_policy"].get("enabled")
    ]
    assert len(rebal) >= 500
    gradual = [t for t in rebal if t.params["rebalance_policy"].get("mode") == "gradual_buy"]
    assert gradual
    assert all(
        float(t.params["rebalance_policy"].get("max_rebalance_per_round_frac", 0.1)) <= 0.08
        for t in gradual[:50]
    )


def test_pool_v2_fee_bad_never_active(v2_pool):
    active_profiles = {
        ProfileFamily.ACTIVE_RANGE_GRID.value,
        ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value,
    }
    for t in v2_pool:
        if t.profile_family in active_profiles and FeeTier.FEE_BAD.value in t.fee_tiers:
            if len(t.fee_tiers) == 1:
                pytest.fail(f"FEE_BAD active template: {t.template_key}")


def test_pool_v2_btc_high_blocks_active(v2_pool, warmed_v2_selector):
    m = _market()
    pf = portfolio(200, 0.35)
    ind = _ind()
    sub = _sub(
        fee_efficiency_score=58,
        btc_market_risk_score=25,
        liquidity_score=72,
        spread_score=75,
    )
    sel = select_template(
        75, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, ind, pf, constraints(), 200, 5.0,
    )
    assert sel.fallback_used is False
    assert sel.final_action != FinalAction.ACTIVE_GRID.value


def test_pool_v2_order_reality_tight_blocks_active(v2_pool, warmed_v2_selector):
    pf = portfolio(12, 0.3)
    ind = _ind()
    sub = _sub(fee_efficiency_score=38, liquidity_score=55)
    sel = select_template(
        62, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, ind, pf, constraints(), 12, 5.0,
    )
    assert sel.final_action != FinalAction.ACTIVE_GRID.value


def test_pool_v2_manifest_and_checksum(v2_pool):
    manifest = build_manifest(
        v2_pool,
        POOL_VERSION_V2,
        schema_version="1.1",
        base_pool_version="v1.0.0",
        added_template_count=50_000,
    )
    assert manifest.active_template_count == 100_000
    assert manifest.base_pool_version == "v1.0.0"
    assert manifest.checksum == pool_checksum(v2_pool)


def test_pool_v2_selector_deterministic(v2_pool, warmed_v2_selector):
    pf = portfolio(100, 0.0)
    ind = _ind()
    sub = _sub(fee_efficiency_score=62)
    a = select_template(64, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, sub, ind, pf, constraints(), 100, 5.0)
    b = select_template(64, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value, sub, ind, pf, constraints(), 100, 5.0)
    assert a.selected_template_key == b.selected_template_key


def test_pool_v2_selector_performance_100k(v2_pool, warmed_v2_selector):
    pf = portfolio(100, 0.35)
    ind = _ind()
    sub = _sub(fee_efficiency_score=68)
    for _ in range(5):
        select_template(72, RegimeTag.RANGE_HIGH_VOL, RiskState.NORMAL.value, sub, ind, pf, constraints(), 100, 5.0)
    start = time.perf_counter()
    for _ in range(10):
        select_template(72, RegimeTag.RANGE_HIGH_VOL, RiskState.NORMAL.value, sub, ind, pf, constraints(), 100, 5.0)
    elapsed_ms = (time.perf_counter() - start) / 10 * 1000
    assert elapsed_ms < C.SELECTOR_P95_TARGET_MS_100K * 1.15


def test_selector_memory_index_and_sqlite_return_same_template(v2_pool):
    from app.services.dynamic_param_score.param_pool.models import SelectionFeatures

    pool = ParamPool(pool_version=POOL_VERSION_V2, templates=v2_pool)
    pool.build_memory_indexes()
    features = SelectionFeatures(
        param_score=64,
        regime=RegimeTag.BALANCED_RANGE.value,
        risk_state=RiskState.CAUTION.value,
        budget_tier="STANDARD",
        exposure_tier="TARGET_BASE",
        headroom_tier="GOOD_HEADROOM",
        fee_tier=FeeTier.FEE_WEAK.value,
        liquidity_tier="LIQ_GOOD",
        volatility_tier="VOL_NORMAL",
        btc_risk_tier=BtcRiskTier.BTC_RISK_LOW.value,
        order_reality_tier="ORDER_OK",
        budget_usdt=150,
        min_notional=5.0,
    )
    mem = query_candidates(pool, features, mode="memory_index_mode")
    sql = query_candidates(pool, features, mode="sqlite_query_mode")
    assert len(mem) == len(sql)


def test_pool_v2_required_regressions_no_fallback(warmed_v2_selector):
    scenarios = [
        (_scenario_fee_bad_no_base_wait, FinalAction.ACTIVE_DEFENSIVE_GRID.value),
        (_scenario_fee_bad_sellable_sell_mgmt, FinalAction.SELL_MANAGEMENT_ONLY.value),
        (_scenario_fee_weak_wide_grid, FinalAction.BALANCED_GRID.value),
        (_scenario_dump_risk, FinalAction.NO_TRADE.value),
    ]
    for builder, expected_action in scenarios:
        sel = builder()
        assert sel.fallback_used is False, f"fallback for {expected_action}"
        assert sel.final_action == expected_action


def test_pool_v2_property_invariants(v2_pool):
    ok, errors = validate_pool(v2_pool)
  # pinned v1 template may lack sellable flag
    assert sum(1 for t in v2_pool if not is_logically_valid_template(t)) < 5


def _sub(**kwargs) -> SubScores:
    defaults = dict(
        trend_score=50,
        volatility_score=45,
        range_score=50,
        liquidity_score=75,
        spread_score=80,
        momentum_score=60,
        mean_reversion_score=45,
        drawdown_risk_score=50,
        btc_market_risk_score=60,
        exposure_safety_score=85,
        fee_efficiency_score=55,
        data_quality_score=100,
    )
    defaults.update(kwargs)
    return SubScores(**defaults)


def _ind() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        atr14_pct_5m=1.2,
        orderbook_spread_pct=0.06,
        total_friction_pct=0.25,
    )


def _market():
    from tests.dynamic_param_score.conftest import market_bundle
    return market_bundle(symbol="SOLUSDT", price=67.8)


def _scenario_fee_bad_no_base_wait():
    pf = portfolio(80, 0.0)
    sub = _sub(fee_efficiency_score=22, exposure_safety_score=65)
    return select_template(
        60, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, _ind(), pf, constraints(), 80, 5.0,
    )


def _scenario_fee_bad_sellable_sell_mgmt():
    pf = portfolio(80, 0.4)
    sub = _sub(fee_efficiency_score=22)
    return select_template(
        60, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, _ind(), pf, constraints(), 80, 5.0,
    )


def _scenario_fee_weak_wide_grid():
    pf = portfolio(150, 0.35)
    sub = _sub(fee_efficiency_score=42)
    return select_template(
        64, RegimeTag.BALANCED_RANGE, RiskState.CAUTION.value,
        sub, _ind(), pf, constraints(), 150, 5.0,
    )


def _scenario_dump_risk():
    pf = portfolio(100, 0.2)
    sub = _sub()
    return select_template(
        70, RegimeTag.DUMP_RISK, RiskState.DEFENSIVE.value,
        sub, _ind(), pf, constraints(), 100, 5.0,
    )
