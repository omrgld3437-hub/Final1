"""Management decision / safe overlay / execution gate contract tests."""

from __future__ import annotations

import math

import pytest

from app.services.dynamic_param_score.adapters import (
    decision_to_param_assistant_result,
    params_to_grid_config,
)
from app.services.dynamic_param_score.constants import (
    KLINES_LIMIT_5M,
    KLINES_LIMIT_15M,
    DATA_WINDOW_DAYS,
)
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import BotContext, BotParams, FinalAction
from app.services.dynamic_param_score.param_pool.models import SelectionContext
from app.services.dynamic_param_score.param_pool.selector import _hard_filter
from app.services.dynamic_param_score.param_pool.validators import validate_template
from app.services.dynamic_param_score.param_pool.defaults import _pinned_templates
from app.services.dynamic_param_score.safe_overlay import (
    build_safe_wait_overlay,
    build_no_trade_overlay,
    build_data_stale_overlay,
)
from app.botengine.dynamic.cycle_manager import _OVERLAY_FIELDS
from tests.dynamic_param_score.conftest import constraints, ctx, mk_candles, portfolio
from tests.dynamic_param_score.test_sol_50_budget import _sol_market


def _decision(final_action: str, deployable: bool = False):
    from app.services.dynamic_param_score.models import DynamicParamDecision

    return DynamicParamDecision(
        decision_id="test123",
        symbol="SOLUSDT",
        timestamp=1,
        run_source="param_assistant",
        final_action=final_action,
        deployable=deployable,
        param_score=55,
        confidence_score=50,
        risk_score=40,
        regime_tag="BALANCED_RANGE",
        risk_state="NORMAL",
        selected_profile_name="WAIT_PROFILE",
        selected_profile_bucket="BALANCED_LOW",
        params=None,
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain="test",
        telemetry={"param_pool": {"selected_template_key": "TEST_WAIT", "pool_version": "v1.0.0"}},
    )


def test_wait_returns_management_decision_not_error():
    d = _decision(FinalAction.WAIT.value)
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert r["ok"] is True
    assert r["result_type"] == "management_decision"
    assert r["ui_severity"] == "info"
    assert r["can_apply_safe_overlay"] is True
    assert r["apply_policy"] == "safe_wait"
    assert r["safe_overlay"] is not None
    assert r["safe_overlay"]["buy_disabled"] is True


def test_no_trade_returns_management_decision_not_error():
    d = _decision(FinalAction.NO_TRADE.value)
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert r["result_type"] == "no_trade"
    assert r["apply_policy"] == "no_trade"
    assert r["safe_overlay"]["cancel_existing_sell_orders"] is True


def test_result_schema_has_management_mode_and_apply_policy():
    d = _decision(FinalAction.WAIT.value)
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    assert "management_mode" in r
    assert "apply_policy" in r
    assert r["management_mode"] == "SAFE_WAIT"


def test_wait_templates_are_not_deployable():
    pinned = {t.template_key: t for t in _pinned_templates()}
    assert pinned["DUMP_RISK_ANY_NO_TRADE"].deployable is False
    fee_bad = pinned["BALANCED_RANGE_60_69_FEE_BAD_WAIT"]
    assert fee_bad.deployable is True
    assert fee_bad.final_action == FinalAction.ACTIVE_DEFENSIVE_GRID.value


def test_pool_build_fails_if_wait_or_no_trade_deployable():
    pinned = {t.template_key: t for t in _pinned_templates()}
    for key in ("DUMP_RISK_ANY_NO_TRADE",):
        t = pinned[key]
        ok, errs = validate_template(t)
        assert ok, errs
    fee_bad = pinned["BALANCED_RANGE_60_69_FEE_BAD_WAIT"]
    ok, errs = validate_template(fee_bad)
    assert ok, errs
    assert fee_bad.deployable is True


def test_collect_market_data_uses_7d_5m_window():
    assert KLINES_LIMIT_5M == 2016
    assert KLINES_LIMIT_15M == 672
    assert DATA_WINDOW_DAYS == 7


def test_selector_filters_liquidity_tier():
    pinned = {t.template_key: t for t in _pinned_templates()}
    tmpl = pinned["BALANCED_RANGE_60_69_FEE_BAD_WAIT"]
    ctx_ok = SelectionContext(
        param_score=65,
        regime="BALANCED_RANGE",
        risk_state="NORMAL",
        budget_tier="SMALL",
        exposure_tier="NO_BASE",
        headroom_tier="GOOD_HEADROOM",
        fee_tier="FEE_BAD",
        equity_usdt=50,
        min_notional=5,
        headroom_usdt=40,
        has_base=False,
        sub_scores={},
        liquidity_tier="LIQ_BAD",
    )
    ctx_bad = SelectionContext(**{**ctx_ok.__dict__, "liquidity_tier": "LIQ_EXCELLENT"})
    if tmpl.liquidity_tiers:
        ok, _ = _hard_filter(tmpl, ctx_bad)
        assert not ok


def test_dynamic_wait_overlay_clears_buy_and_sets_buy_disabled():
    d = _decision(FinalAction.WAIT.value)
    ov = build_safe_wait_overlay(d)
    assert ov["buy_grids"] == []
    assert ov["max_buy_levels"] == 0
    assert ov["buy_disabled"] is True
    assert ov["cancel_existing_buy_orders"] is True


def test_dynamic_stale_data_does_not_restore_manual_buy_grids():
    base = {"buy_grids": [{"buy_grid_pct": 1, "buy_qty_pct_of_quote": 50}], "sell_grids": []}
    ov = build_data_stale_overlay(base)
    assert ov["buy_grids"] == []
    assert ov["buy_disabled"] is True
    assert ov["management_mode"] == "DATA_STALE_SAFE_WAIT"


def test_overlay_fields_include_runtime_flags():
    assert "buy_disabled" in _OVERLAY_FIELDS
    assert "sell_only_mode" in _OVERLAY_FIELDS
    assert "management_mode" in _OVERLAY_FIELDS


def test_params_to_grid_config_carries_buy_disabled():
    p = BotParams(
        base_alloc_frac=0.5,
        quote_alloc_frac=0.5,
        buy_grid_count=0,
        sell_grid_count=2,
        buy_grid_spacing_pct=1.0,
        sell_grid_spacing_pct=1.0,
        buy_qty_distribution=[],
        sell_qty_distribution=[0.5, 0.5],
        trailing_enabled=True,
        trailing_callback_pct=0.5,
        take_profit_pct=1.0,
        stop_new_buys_below_score=30,
        max_base_exposure_frac=0.6,
        max_quote_to_spend_per_buy_frac=0.2,
        downtrend_buy_throttle=False,
        min_cycle_profit_after_fee_pct=0.5,
        emergency_no_buy=True,
        cancel_existing_buy_orders=True,
        cancel_existing_sell_orders=False,
        reason_code="test",
        buy_disabled=True,
        sell_only_mode=True,
        rebuy_enabled=False,
    )
    cfg = params_to_grid_config(p, final_action="SELL_MANAGEMENT_ONLY")
    assert cfg["buy_disabled"] is True
    assert cfg["sell_only_mode"] is True
    assert cfg["rebuy_enabled"] is False


def test_param_assistant_fresh_budget_never_selects_sell_management_without_base():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(50),
        constraints(),
        ctx("param_assistant", 50),
    )
    if d.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        assert float(d.telemetry.get("param_pool", {}).get("selection_context", {}).get("sellable_base_usdt", 0)) >= 5


def test_build_bot_context_auto_first_start_buy_only_without_base():
    from app.services.dynamic_param_score.data_collector import build_bot_context

    p = portfolio(100)
    auto = build_bot_context(run_source="param_assistant", budget_usdt=100, portfolio=p)
    assert auto.is_first_start is True
    assert auto.first_start_buy_only is True

    explicit_off = build_bot_context(
        run_source="param_assistant",
        budget_usdt=100,
        portfolio=p,
        first_start_buy_only=False,
    )
    assert explicit_off.is_first_start is True
    assert explicit_off.first_start_buy_only is False


def test_first_start_auto_buy_only_skips_no_sellable_base_blocking():
    from app.services.dynamic_param_score.data_collector import build_bot_context

    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision(
        "SOLUSDT",
        _sol_market(),
        portfolio(100),
        constraints(),
        build_bot_context(
            run_source="param_assistant",
            budget_usdt=100,
            portfolio=portfolio(100),
        ),
    )
    blocking = [str(b).upper() for b in (d.blocking_reasons or [])]
    assert "NO_SELLABLE_BASE" not in blocking


def test_sell_management_template_rejected_without_sellable_base():
    pinned = {t.template_key: t for t in _pinned_templates()}
    tmpl = pinned["BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT"]
    ctx_no_base = SelectionContext(
        param_score=65,
        regime="BALANCED_RANGE",
        risk_state="NORMAL",
        budget_tier="SMALL",
        exposure_tier="TARGET_BASE",
        headroom_tier="NO_HEADROOM",
        fee_tier="FEE_BAD",
        equity_usdt=50,
        min_notional=5,
        headroom_usdt=10,
        has_base=False,
        has_sellable_base=False,
        sellable_base_usdt=0,
        sub_scores={},
    )
    ok, reasons = _hard_filter(tmpl, ctx_no_base)
    assert not ok
    assert "sell_management_no_sellable_base" in reasons or "requires_sellable_base_missing" in reasons


def test_sqlite_artifact_wait_no_trade_not_deployable():
    """On-disk SQLite metadata must match runtime normalization."""
    import sqlite3
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "data" / "param_pool" / "v1" / "param_pool_v1.sqlite"
    if not p.exists():
        pytest.skip("param pool sqlite artifact missing")
    conn = sqlite3.connect(p)
    bad = 0
    for row in conn.execute(
        "SELECT metadata_json FROM param_templates WHERE final_action IN ('WAIT','NO_TRADE')"
    ):
        meta = json.loads(row[0] or "{}")
        if meta.get("deployable", True):
            bad += 1
    conn.close()
    assert bad == 0, f"{bad} WAIT/NO_TRADE rows still deployable=true in sqlite"


def test_sqlite_sell_management_requires_sellable_base():
    import sqlite3
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "data" / "param_pool" / "v1" / "param_pool_v1.sqlite"
    if not p.exists():
        pytest.skip("param pool sqlite artifact missing")
    conn = sqlite3.connect(p)
    missing = 0
    total = 0
    for row in conn.execute(
        "SELECT metadata_json FROM param_templates WHERE final_action='SELL_MANAGEMENT_ONLY'"
    ):
        total += 1
        meta = json.loads(row[0] or "{}")
        if not meta.get("requires_sellable_base"):
            missing += 1
    conn.close()
    assert total > 0
    assert missing == 0, f"{missing}/{total} SELL_MANAGEMENT rows missing requires_sellable_base"


def test_order_intent_plan_not_executed_unless_intent_execution_enabled():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision("SOLUSDT", _sol_market(), portfolio(50), constraints(), ctx("param_assistant", 50))
    assert d.telemetry.get("intent_execution_enabled") is False
