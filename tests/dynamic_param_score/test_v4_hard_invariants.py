"""Hard invariant regression tests for DPS V4 decision chain."""

from __future__ import annotations

from app.services.dynamic_param_score.action_detail import is_deployable
from app.services.dynamic_param_score.feasibility import _finalize_buy_distribution
from app.services.dynamic_param_score.models import BotParams, FinalAction
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    DEFENSIVE_TWO_GRID,
    DistributionContext,
    is_defensive_distribution_valid,
    normalize_side_distribution,
    trim_side_distribution,
)
from app.services.dynamic_param_score.param_generator.live_route_classifier_v4 import (
    classify_regime_code_v4,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    MANDATORY_CRITICAL_ROUTES,
)
from app.services.dynamic_param_score.param_pool.versioning import production_pool_status
from app.services.dynamic_param_score import constants as C


def _params(**kwargs) -> BotParams:
    base = dict(
        base_alloc_frac=0.40,
        quote_alloc_frac=0.60,
        buy_grid_count=2,
        sell_grid_count=2,
        buy_grid_spacing_pct=2.5,
        sell_grid_spacing_pct=2.5,
        buy_qty_distribution=[0.3, 0.7],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.35,
        take_profit_pct=1.2,
        stop_new_buys_below_score=0,
        max_base_exposure_frac=0.53,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.2,
        emergency_no_buy=False,
        cancel_existing_buy_orders=False,
        cancel_existing_sell_orders=False,
        reason_code="test",
    )
    base.update(kwargs)
    return BotParams(**base)


def test_defensive_two_grid_not_50_50():
    ctx = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    dist, changed = normalize_side_distribution([50, 50], ctx=ctx)
    assert changed
    assert dist == list(DEFENSIVE_TWO_GRID)
    assert not is_defensive_distribution_valid([50, 50], grid_count=2, ctx=ctx)


def test_defensive_two_grid_near_equal_rejected():
    ctx = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    dist, changed = normalize_side_distribution([48, 52], ctx=ctx)
    assert changed
    assert dist == list(DEFENSIVE_TWO_GRID)


def test_worst_case_exposure_blocks_deployable():
    params = _params()
    meta = {
        "exposure_hard_cap_breach": True,
        "worst_case_base_exposure_frac": 1.0,
        "max_base_exposure_frac": 0.53,
    }
    assert not is_deployable(
        FinalAction.ACTIVE_DEFENSIVE_GRID.value, params, meta
    )


def test_worst_case_within_cap_allows_deployable():
    params = _params()
    meta = {
        "worst_case_base_exposure_frac": 0.45,
        "max_base_exposure_frac": 0.53,
    }
    assert is_deployable(FinalAction.ACTIVE_DEFENSIVE_GRID.value, params, meta)


def test_breakout_risk_maps_to_r4_not_r2():
    cls = classify_regime_code_v4(
        regime_tag="BREAKOUT_RISK",
        lower_lows=False,
        higher_highs=True,
        return_24h_pct=8.0,
        volatility_percentile=75,
        atr_1h_pct=2.0,
        risk_level="DEFENSIVE",
    )
    assert cls.regime_code == "R4"
    assert cls.regime_code != "R2"


def test_production_pool_status_reports_paths():
    status = production_pool_status()
    assert "production_pool_loaded" in status
    assert "route_index_profile_count" in status
    assert isinstance(status["mandatory_missing_routes"], list)


def test_mandatory_routes_list_non_empty():
    assert len(MANDATORY_CRITICAL_ROUTES) >= 10


def test_finalize_buy_distribution_two_grid_defensive():
    ctx = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    fixed = _finalize_buy_distribution([0.5, 0.5], defensive=True, dist_ctx=ctx)
    assert [round(x * 100) for x in fixed] == list(DEFENSIVE_TWO_GRID)


def test_deployable_false_when_distribution_invalid():
    params = _params()
    meta = {"distribution_invalid": True}
    assert not is_deployable(FinalAction.ACTIVE_DEFENSIVE_GRID.value, params, meta)


def test_worst_case_tolerance_respected():
    params = _params(buy_grid_count=1, buy_qty_distribution=[1.0])
    tol = float(C.WORST_CASE_EXPOSURE_TOLERANCE)
    meta = {
        "worst_case_base_exposure_frac": 0.53 + tol + 0.001,
        "max_base_exposure_frac": 0.53,
    }
    assert not is_deployable(FinalAction.ACTIVE_DEFENSIVE_GRID.value, params, meta)


def test_fee_bad_fallback_uses_library_not_pinned():
    import os

    import pytest

    from app.services.dynamic_param_score.models import BotContext, RegimeTag, SubScores
    from app.services.dynamic_param_score.indicators import IndicatorSnapshot
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
    from app.services.dynamic_param_score.param_pool.registry import get_active_pool
    from app.services.dynamic_param_score.param_pool.selector import select_and_render
    from app.services.dynamic_param_score.param_pool.versioning import (
        clear_pool_cache,
        production_pool_status,
    )
    from tests.dynamic_param_score.conftest import constraints, portfolio

    if not production_pool_status(POOL_VERSION_V4).get("production_pool_loaded"):
        pytest.skip("v4 production pool sqlite/index not on disk")

    clear_pool_cache()
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    os.environ["PARAM_POOL_MODE"] = "auto"
    pool_version, _ = get_active_pool()
    assert pool_version.version_id == POOL_VERSION_V4

    sub = SubScores(
        trend_score=38,
        volatility_score=65,
        range_score=53,
        liquidity_score=32,
        spread_score=60,
        momentum_score=100,
        mean_reversion_score=51,
        drawdown_risk_score=50,
        btc_market_risk_score=70,
        exposure_safety_score=90,
        fee_efficiency_score=15,
        data_quality_score=100,
    )
    ind = IndicatorSnapshot(
        orderbook_spread_pct=0.08,
        atr14_pct_5m=1.2,
        atr14_pct_1h=1.5,
        total_friction_pct=0.15,
        data_freshness_sec=30,
    )
    sel, params, _ = select_and_render(
        57,
        RegimeTag.BALANCED_RANGE,
        "DEFENSIVE",
        sub,
        ind,
        portfolio(1000.0, exposure=0.0),
        constraints(),
        BotContext(run_source="param_assistant", budget_usdt=1000.0, is_first_start=True),
        1000.0,
        5.0,
        symbol="BTCUSDT",
    )
    key = sel.selected_template_key or ""
    assert not key.startswith("FALLBACK_"), "generic pinned fallback must not be used when v4 pool loaded"
    assert sel.selection_context.get("pinned_fallback_template_key") is None
    assert key.startswith("DPLV4_") or sel.selection_context.get("runtime_safe_profile_generated")
    assert params is not None
    assert params.base_alloc_frac is not None


def test_trim_side_distribution_defensive_three_to_two():
    ctx = DistributionContext(risk_state="DEFENSIVE", lower_lows=True, vol_code="V4")
    out = trim_side_distribution([12, 28, 60], 2, ctx=ctx)
    assert out == list(DEFENSIVE_TWO_GRID)


def test_exact_candidate_blocks_runtime_permitted():
    from app.services.dynamic_param_score.param_pool.models import TemplateSelectionResult
    from app.services.dynamic_param_score.param_pool.selector import _runtime_safe_permitted

    selection = TemplateSelectionResult(
        pool_version="param_pool_v4",
        selected_template_key="",
        profile_family="",
        final_action="ACTIVE_DEFENSIVE_GRID",
        selection_score=0.0,
        candidate_count=0,
        filtered_out={},
        fallback_used=True,
        fallback_reason="test",
        selection_context={
            "exact_route_candidate_count": 10,
            "exact_scored_count": 2,
            "scored_candidate_count": 0,
        },
    )
    assert not _runtime_safe_permitted(
        selection,
        pool_status={"production_pool_loaded": True},
    )


def test_exact_scored_blocks_runtime_permitted():
    from app.services.dynamic_param_score.param_pool.models import TemplateSelectionResult
    from app.services.dynamic_param_score.param_pool.selector import _runtime_safe_permitted

    selection = TemplateSelectionResult(
        pool_version="param_pool_v4",
        selected_template_key="",
        profile_family="",
        final_action="ACTIVE_DEFENSIVE_GRID",
        selection_score=0.0,
        candidate_count=0,
        filtered_out={},
        fallback_used=True,
        fallback_reason="test",
        selection_context={"exact_route_candidate_count": 0, "exact_scored_count": 3},
    )
    assert not _runtime_safe_permitted(
        selection,
        pool_status={"production_pool_loaded": True},
    )


def test_empty_deployable_grid_template_hard_rejected():
    import sqlite3
    import json

    from app.services.dynamic_param_score.param_generator.v4_scoring import hard_reject_v4

    conn = sqlite3.connect("data/param_pool/v4/param_pool_v4.sqlite")
    row = conn.execute(
        "SELECT final_action, params_json FROM param_templates "
        "WHERE template_key='DPLV4_A1_R2_S3_V3_DEFENSIVE_910007'"
    ).fetchone()
    assert row is not None

    class _Stub:
        deployable = True
        final_action = row[0]
        params = json.loads(row[1])

    sig = {
        "route_key": "A1|R2|S3|V3|DEFENSIVE",
        "structure_code": "S3",
        "regime_code": "R2",
        "fee_code": "F6",
        "data_quality_score": 100,
    }
    assert hard_reject_v4(_Stub(), sig) == "empty_deployable_grid"


def test_btcusdt_fee_bad_first_start_returns_grid_recommendation():
    import os

    import pytest

    from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
    from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
    from app.services.dynamic_param_score.models import FinalAction
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V4
    from app.services.dynamic_param_score.param_pool.registry import get_active_pool
    from app.services.dynamic_param_score.param_pool.versioning import (
        clear_pool_cache,
        production_pool_status,
    )
    from tests.dynamic_param_score.conftest import constraints
    from tests.dynamic_param_score.factories import make_context, make_market_bundle, make_portfolio_state

    if not production_pool_status(POOL_VERSION_V4).get("production_pool_loaded"):
        pytest.skip("v4 production pool sqlite/index not on disk")

    clear_pool_cache()
    os.environ["PARAM_POOL_VERSION"] = POOL_VERSION_V4
    os.environ["PARAM_POOL_MODE"] = "auto"
    pool_version, _ = get_active_pool()
    assert pool_version.version_id == POOL_VERSION_V4

    engine = DynamicParamScoreEngine()
    decision = engine.calculate_decision(
        "BTCUSDT",
        make_market_bundle(symbol="BTCUSDT", price=95000.0, pattern="balanced_range"),
        make_portfolio_state(budget_usdt=1000.0, base_exposure_frac=0.0),
        constraints(),
        make_context(
            run_source="param_assistant",
            budget_usdt=1000.0,
            is_first_start=True,
        ),
    )
    pool = decision.telemetry.get("param_pool") or {}
    key = pool.get("selected_template_key") or ""
    assert key != "DPLV4_A1_R2_S3_V3_DEFENSIVE_910007"
    pre = decision.telemetry.get("pre_safety_params") or {}
    assert int(pre.get("buy_grid_count") or 0) > 0 or int(pre.get("sell_grid_count") or 0) > 0

    pa = decision_to_param_assistant_result(decision, 1000.0, "BTCUSDT")
    rec = pa.get("recommendation_config") or pa.get("ui_config")
    assert rec is not None, "Param Assistant must show grid params when library template has grids"
    down = len(rec.get("down", {}).get("grids", []) or [])
    up = len(rec.get("up", {}).get("grids", []) or [])
    assert down >= 1 or up >= 1
    if decision.blocking_reasons and decision.final_action == FinalAction.NO_TRADE.value:
        assert pa.get("decision") == "recommended_grid"
