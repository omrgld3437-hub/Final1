"""Dynamic round-start policy: absolute PA apply + 30m non-deployable rescan."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.botengine.dynamic import cycle_gate as cg
from app.botengine.dynamic import cycle_manager as cm
from app.botengine.dynamic import round_start_policy as rsp
from app.botengine.dynamic import regime as reg
from app.services.dynamic_param_score.models import DynamicParamDecision, FinalAction


def _state(cycle_id=2, **kw):
    s = {
        "bot_id": 42,
        "cycle_id": cycle_id,
        "quote_balance": 500.0,
        "base_balance": 0.0,
        "buy_grid_fired": [False, False],
        "initial_allocation_done": True,
    }
    s.update(kw)
    return s


def _cfg():
    return {
        "symbol": "BTCUSDT",
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "max_buy_levels": 2,
        "buy_grids": [
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 50.0},
            {"buy_grid_pct": 4.0, "buy_qty_pct_of_quote": 50.0},
        ],
        "sell_grids": [{"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 100.0}],
    }


def _decision(
    *,
    deployable=False,
    final_action=FinalAction.WAIT.value,
    regime="BALANCED_RANGE",
    blocking=None,
):
    d = MagicMock(spec=DynamicParamDecision)
    d.deployable = deployable
    d.final_action = final_action
    d.regime_tag = regime
    d.risk_state = "NORMAL"
    d.explain = "test"
    d.blocking_reasons = list(blocking or [])
    d.safety_gates = []
    d.params = MagicMock() if deployable else None
    d.telemetry = {}
    return d


# ---- round_start_policy -----------------------------------------------------


def test_hard_block_marks_pending_and_schedules_30m():
    st = _state()
    rsp.mark_pending(st, cycle_id=2, reason="DUMP", codes=["DUMP_RISK"])
    p = rsp.get_pending(st)
    assert p is not None
    assert p["active"] is True
    assert p["cycle_id"] == 2
    gap = int(p["next_retry_ms"]) - int(p["since_ms"])
    assert gap == int(rsp.ROUND_START_RETRY_SEC * 1000)
    assert rsp.ROUND_START_RETRY_SEC == pytest.approx(1800.0)


def test_retry_due_triggers_recompute():
    st = _state()
    rsp.mark_pending(st, cycle_id=2, reason="stale", codes=["DATA_STALE"])
    p = st["_dynamic_round_pending"]
    p["next_retry_ms"] = int(time.time() * 1000) - 1
    assert rsp.need_round_start_retry(st) is True
    assert st.get("_dynamic_recompute_needed") is True


def test_deployable_clears_pending():
    st = _state()
    rsp.mark_pending(st, cycle_id=2, reason="x", codes=["DUMP_RISK"])
    rsp.on_deployable_round_start(st)
    assert rsp.get_pending(st) is None


def test_is_hard_safety_dump_risk():
    d = _decision(deployable=False, final_action=FinalAction.NO_TRADE.value, regime="DUMP_RISK")
    assert rsp.is_hard_safety_block(d) is True


def test_soft_wait_not_hard_block():
    d = _decision(deployable=False, final_action=FinalAction.WAIT.value, regime="BALANCED_RANGE")
    assert rsp.is_hard_safety_block(d) is False
    assert rsp.should_force_active(d) is True


# ---- cycle_gate emergency-only + 15m recheck --------------------------------


def test_recheck_default_15_minutes():
    assert cg.RECHECK_SEC == 900.0


def test_emergency_only_skips_moderate_downside():
    f = {
        "atr_pct_5m": 1.8,
        "realized_vol_5m": 1.5,
        "ret_5m_last": -2.0,
        "rsi_5m": 38.0,
        "rsi_1h": 42.0,
        "ema_slope_1h_pct": -0.6,
        "volume_zscore_5m": 1.2,
        "spread_pct": 0.08,
        "wick_body_ratio_5m": 1.4,
        "adx_1h": 28.0,
    }
    st = _state()
    cfg = _cfg()
    v2 = cg.evaluate(f, reg.TRENDING_DOWN, 0.75, st, cfg)
    assert v2.holding is False
    assert cg.is_holding(st) is False


def test_dump_does_not_hold_when_v4_mid_turn_disabled():
    f = {
        "atr_pct_5m": 2.6,
        "realized_vol_5m": 2.8,
        "ret_5m_last": -4.2,
        "rsi_5m": 22.0,
        "rsi_1h": 30.0,
        "ema_slope_1h_pct": -1.1,
        "volume_zscore_5m": 3.4,
        "spread_pct": 0.30,
        "wick_body_ratio_5m": 2.6,
        "adx_1h": 38.0,
    }
    st = _state()
    cfg = _cfg()
    v = cg.evaluate(f, reg.DUMP_RISK, 0.9, st, cfg)
    assert v.holding is False
    assert cg.is_holding(st) is False


def test_dump_still_holds_when_legacy_gate_enabled(monkeypatch):
    monkeypatch.setattr(cg, "HOLD_ENABLED", True)
    f = {
        "atr_pct_5m": 2.6,
        "realized_vol_5m": 2.8,
        "ret_5m_last": -4.2,
        "rsi_5m": 22.0,
        "rsi_1h": 30.0,
        "ema_slope_1h_pct": -1.1,
        "volume_zscore_5m": 3.4,
        "spread_pct": 0.30,
        "wick_body_ratio_5m": 2.6,
        "adx_1h": 38.0,
    }
    st = _state()
    v = cg.evaluate(f, reg.DUMP_RISK, 0.9, st, _cfg())
    assert v.holding is True
    hold = st["_dynamic_cycle_hold"]
    assert int(hold.get("next_recheck_ms") or 0) > int(hold.get("since_ms") or 0)


def test_reset_for_new_cycle_clears_hold_and_pending():
    st = _state()
    st["_dynamic_cycle_engaged"] = True
    st["_dynamic_cycle_hold"] = {"active": True}
    rsp.mark_pending(st, cycle_id=2, reason="x")
    cg.reset_for_new_cycle(st)
    assert st.get("_dynamic_cycle_engaged") is None
    assert st.get("_dynamic_cycle_hold") is None
    assert rsp.get_pending(st) is None


# ---- cycle_manager resolve --------------------------------------------------


def test_resolve_hard_block_pending():
    st = _state()
    d = _decision(deployable=False, final_action=FinalAction.NO_TRADE.value, regime="DUMP_RISK", blocking=["DUMP_RISK"])
    d.selected_profile_name = "R8_HARD_BLOCK"
    d.telemetry = {"net_profile": {"key": "R8_HARD_BLOCK"}}
    ctx = cm._build_dps_context(st, _cfg(), 2, 500.0)
    applied, reasons, fallbacks, pending, pa_meta = cm._resolve_round_decision(
        st, d, _cfg(), cycle_id=2, market=MagicMock(), portfolio=MagicMock(), constraints=MagicMock(), ctx=ctx
    )
    assert pending is True
    assert applied.get("buy_disabled") is True
    assert "dps_non_deployable_round_paused" in fallbacks
    assert pa_meta.get("profile_key") == "R8_HARD_BLOCK"
    from app.botengine.dynamic import start_retry_policy as srp

    wl = srp.get_watchlist(st)
    assert wl is not None
    assert float(wl["retry_after_minutes"]) == pytest.approx(30.0)


def test_resolve_soft_wait_blocks_start_retry():
    st = _state()
    d = _decision(deployable=False, final_action=FinalAction.WAIT.value)
    d.params = MagicMock()
    d.params.buy_grid_count = 2
    d.params.sell_grid_count = 2
    d.selected_profile_name = "R2_BALANCED_RANGE"
    d.telemetry = {}
    ctx = cm._build_dps_context(st, _cfg(), 2, 500.0)
    applied, reasons, fallbacks, pending, pa_meta = cm._resolve_round_decision(
        st, d, _cfg(), cycle_id=2, market=MagicMock(), portfolio=MagicMock(), constraints=MagicMock(), ctx=ctx
    )
    from app.botengine.dynamic import start_retry_policy as srp

    assert pending is True
    assert applied.get("buy_disabled") is True
    assert "dps_non_deployable_round_paused" in fallbacks
    assert srp.get_watchlist(st) is not None


def test_need_recompute_respects_pending_until_retry():
    st = _state()
    st["dynamic_snapshot"] = {"cycle_id": 2}
    rsp.mark_pending(st, cycle_id=2, reason="stale", codes=["DATA_STALE"])
    assert cm.need_recompute(st) is False
    p = st["_dynamic_round_pending"]
    p["next_retry_ms"] = int(time.time() * 1000) - 1
    assert cm.need_recompute(st) is True


def test_stale_features_schedule_pending_retry():
    import asyncio

    st = _state()
    cfg = _cfg()
    feats = MagicMock()
    feats.data_fresh = False
    feats.error = "timeout"
    feats.to_dict.return_value = {"data_fresh": False}

    with patch.object(cm, "collect_features", new=AsyncMock(return_value=feats)):
        snap = asyncio.run(cm.build_snapshot(st, cfg, 50000.0))

    assert snap["data_fresh"] is False
    assert snap.get("round_pending") is True
    assert rsp.get_pending(st) is not None
    assert snap["applied"].get("buy_disabled") is True


def test_fresh_round_clears_pending_on_deployable():
    import asyncio

    st = _state()
    cfg = _cfg()
    feats = MagicMock()
    feats.data_fresh = True
    feats.to_dict.return_value = {"data_fresh": True}
    rsp.mark_pending(st, cycle_id=2, reason="old")

    deploy = _decision(deployable=True, final_action=FinalAction.ACTIVE_DEFENSIVE_GRID.value)
    deploy.params.to_dict = MagicMock(return_value={})
    deploy.confidence_score = 72
    deploy.decision_id = "d1"
    deploy.param_score = 65
    deploy.risk_state = "NORMAL"
    deploy.selected_profile_name = "TEST"
    deploy.telemetry = {"pool_version": "v6"}

    engine = MagicMock()
    engine.calculate_decision.return_value = deploy

    with patch.object(cm, "collect_features", new=AsyncMock(return_value=feats)), patch.object(
        cm, "collect_market_data", new=AsyncMock(return_value=MagicMock(ticker_price=50000.0))
    ), patch.object(
        cm,
        "portfolio_from_bot_state",
        return_value=MagicMock(total_equity_usdt=500.0, quote_value_usdt=500.0),
    ), patch.object(cm, "get_dps_engine", return_value=engine), patch.object(
        cm.DynamicParamScoreEngine,
        "decision_to_overlay",
        return_value={
            "buy_grids": cfg["buy_grids"],
            "sell_grids": cfg["sell_grids"],
            "base_alloc_pct": 50.0,
            "quote_alloc_pct": 50.0,
            "buy_disabled": False,
        },
    ):
        snap = asyncio.run(cm.build_snapshot(st, cfg, 50000.0))

    assert rsp.get_pending(st) is None
    assert snap["dps"]["deployable"] is True
    assert snap["applied"].get("plan_source") == "param_assistant_absolute"


def test_independent_params_per_cycle_id_in_context():
    st1 = _state(cycle_id=2)
    st2 = _state(cycle_id=5)
    c1 = cm._build_dps_context(st1, _cfg(), 2, 100.0)
    c2 = cm._build_dps_context(st2, _cfg(), 5, 100.0)
    assert c1.current_round_id == "2"
    assert c2.current_round_id == "5"
    assert c1.previous_round_id == "1"
    assert c2.previous_round_id == "4"
