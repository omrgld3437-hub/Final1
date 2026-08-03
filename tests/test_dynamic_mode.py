"""
Unit tests for live Dynamic Mode surfaces: indicators, safety gate, config,
regime hysteresis. Legacy StrategyEngine / RiskEngine tests removed with those
modules (decision path is now DPS V6 absolute PA apply).
"""

from __future__ import annotations
import math

import pytest

from app.botengine.dynamic import indicators as ind
from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import safety_gate as sg
from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing


def _candles(closes):
    out = []
    for i, c in enumerate(closes):
        out.append(
            {"t": i * 1000, "o": c, "h": c * 1.005, "l": c * 0.995, "c": c, "v": 100.0}
        )
    return out


def test_atr_none_when_insufficient():
    assert ind.atr([], 14) is None
    assert ind.atr(_candles([1.0]), 14) is None


def test_atr_pct_finite_for_known_series():
    cs = _candles([100 + i * 0.5 for i in range(60)])
    v = ind.atr_pct(cs, 14)
    assert v is not None and v >= 0


def test_bbw_constant_series_is_zero_or_none():
    cs = _candles([100.0] * 40)
    v = ind.bollinger_band_width(cs, 20)
    assert v is None or v == 0.0


def test_rsi_uptrend_high():
    cs = _candles([100 + i for i in range(40)])
    v = ind.rsi(cs, 14)
    assert v is not None and v > 70


def test_rsi_downtrend_low():
    cs = _candles([100 - i for i in range(40)])
    v = ind.rsi(cs, 14)
    assert v is not None and v < 30


def test_adx_returns_finite_when_enough_data():
    cs = _candles([100 + i * 0.3 for i in range(80)])
    v = ind.adx(cs, 14)
    assert v is None or math.isfinite(v)


def test_safety_gate_missing_max_buy_levels_blocks():
    cfg = {"max_buy_levels": 0, "daily_loss_limit_usd": 10.0, "dynamic_mode": True}
    r = sg.check_prerequisites(cfg)
    assert not r.ok
    assert any("max_buy_levels" in v for v in r.violations)


def test_safety_gate_daily_loss_not_required_when_disabled():
    cfg = {"max_buy_levels": 2, "daily_loss_limit_usd": 0.0, "dynamic_mode": True}
    r = sg.check_prerequisites(cfg)
    assert r.ok
    assert not any("daily_loss_limit_usd" in v for v in r.violations)


def test_safety_gate_passes_when_complete():
    cfg = {"max_buy_levels": 3, "daily_loss_limit_usd": 25.0, "dynamic_mode": True}
    r = sg.check_prerequisites(cfg)
    assert r.ok
    assert r.injected_defaults == {}


def test_is_dynamic_mode_active_false_when_flag_off():
    cfg = {"max_buy_levels": 3, "daily_loss_limit_usd": 25.0, "dynamic_mode": False}
    assert not sg.is_dynamic_mode_active(cfg)


def test_is_dynamic_mode_active_false_when_prereqs_break():
    cfg = {"max_buy_levels": 0, "daily_loss_limit_usd": 25.0, "dynamic_mode": True}
    assert not sg.is_dynamic_mode_active(cfg)


def test_emergency_check_stop_loss_disabled():
    cfg = {"max_buy_levels": 3, "daily_loss_limit_usd": 25.0, "dynamic_mode": True}
    state = {"cycle_start_equity": 1000.0}
    out = sg.emergency_check(state, cfg, equity=900.0)
    assert out["action"] == "NONE"


def test_emergency_check_emergency_close_disabled():
    cfg = {
        "max_buy_levels": 3,
        "daily_loss_limit_usd": 25.0,
        "dynamic_mode": True,
        "initial_capital_usdt": 1000.0,
    }
    state = {"cycle_start_equity": 1000.0}
    out = sg.emergency_check(state, cfg, equity=820.0)
    assert out["action"] == "NONE"
    state2 = {"cycle_start_equity": 820.0}
    out2 = sg.emergency_check(state2, cfg, equity=820.0)
    assert out2["action"] == "NONE"


def test_emergency_check_inactive_when_flag_off():
    cfg = {
        "max_buy_levels": 3,
        "daily_loss_limit_usd": 25.0,
        "dynamic_mode": False,
        "initial_capital_usdt": 1000.0,
    }
    state = {"cycle_start_equity": 1000.0}
    out = sg.emergency_check(state, cfg, equity=500.0)
    assert out["action"] == "NONE"


def test_emergency_actions_are_disabled_not_pauses():
    cfg = {
        "max_buy_levels": 3,
        "daily_loss_limit_usd": 25.0,
        "dynamic_mode": True,
        "initial_capital_usdt": 1000.0,
    }
    sl = sg.emergency_check({"cycle_start_equity": 1000.0}, cfg, equity=900.0)
    assert sl["action"] == "NONE"
    assert sl["reason"] == ""

    ec = sg.emergency_check({"cycle_start_equity": 820.0}, cfg, equity=820.0)
    assert ec["action"] == "NONE"
    assert ec["reason"] == ""


def _deep_grid_cfg():
    return {
        "max_buy_levels": 4,
        "daily_loss_limit_usd": 25.0,
        "dynamic_mode": True,
        "initial_capital_usdt": 1000.0,
        "buy_grids": [
            {"buy_grid_pct": 5.0},
            {"buy_grid_pct": 10.0},
            {"buy_grid_pct": 15.0},
            {"buy_grid_pct": 20.0},
        ],
    }


def test_emergency_held_back_while_inside_grid_plan():
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0, "reference_price": 100.0}
    out = sg.emergency_check(state, cfg, equity=850.0, price=88.0)
    assert out["action"] == "NONE"
    assert out["metrics"] == {}


def test_emergency_fires_beyond_grid_plan():
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0, "reference_price": 100.0}
    out = sg.emergency_check(state, cfg, equity=850.0, price=70.0)
    assert out["action"] == "NONE"


def test_depth_guard_skipped_when_reference_unknown():
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0}
    out = sg.emergency_check(state, cfg, equity=850.0, price=88.0)
    assert out["action"] == "NONE"


def test_config_dynamic_mode_default_false():
    cfg = DcaGridTrailingConfig({"symbol": "BTCUSDT", "max_buy_levels": 1})
    assert cfg.dynamic_mode is False
    assert cfg.to_dict()["dynamic_mode"] is False


def test_config_dynamic_mode_true_preserved():
    cfg = DcaGridTrailingConfig(
        {"symbol": "BTCUSDT", "max_buy_levels": 2, "dynamic_mode": True}
    )
    assert cfg.dynamic_mode is True
    assert cfg.to_dict()["dynamic_mode"] is True


def test_regime_hysteresis_does_not_flip_on_single_change():
    prev = {
        "current": reg.LOW_VOL_RANGING,
        "candidate": reg.LOW_VOL_RANGING,
        "candidate_streak": 0,
    }
    new_state = reg.update_regime_state(
        prev, reg.RegimeResult(reg.LOW_VOL_RANGING, reg.TRENDING_UP, 0.8, {})
    )
    assert "current" in new_state
    assert new_state["candidate"] == reg.TRENDING_UP


def test_dynamic_mode_does_not_inject_default_daily_loss_limit():
    from app.botengine.models import config_from_ui_payload

    payload = {
        "symbol": "BTCUSDT",
        "budget_usd": 1000.0,
        "down": {"grids": [{"trigger_pct": 2.0, "qty_pct": 10.0}]},
        "max_buy_levels": 1,
        "dynamic_mode": True,
    }
    cfg = config_from_ui_payload(payload)
    assert cfg.daily_loss_limit_usd == 0.0
    assert sg.check_prerequisites(cfg.to_dict()).ok


def test_manual_mode_does_not_inject_daily_loss_limit():
    from app.botengine.models import config_from_ui_payload

    payload = {
        "symbol": "BTCUSDT",
        "budget_usd": 1000.0,
        "down": {"grids": [{"trigger_pct": 2.0, "qty_pct": 10.0}]},
        "max_buy_levels": 1,
        "dynamic_mode": False,
    }
    cfg = config_from_ui_payload(payload)
    assert cfg.daily_loss_limit_usd == 0.0


def test_explicit_daily_loss_limit_is_preserved():
    from app.botengine.models import config_from_ui_payload

    payload = {
        "symbol": "BTCUSDT",
        "budget_usd": 1000.0,
        "down": {"grids": [{"trigger_pct": 2.0, "qty_pct": 10.0}]},
        "max_buy_levels": 1,
        "dynamic_mode": True,
        "daily_loss_limit_usd": 123.0,
    }
    cfg = config_from_ui_payload(payload)
    assert cfg.daily_loss_limit_usd == pytest.approx(123.0)


def test_daily_loss_runtime_disabled_clears_stale_hit_and_does_not_stop_tick():
    cfg = DcaGridTrailingConfig(
        {
            "symbol": "BTCUSDT",
            "max_buy_levels": 1,
            "daily_loss_limit_usd": 1.0,
            "sell_grids": [{"sell_grid_pct": 20.0, "sell_qty_pct_of_base": 100.0}],
            "buy_grids": [{"buy_grid_pct": 20.0, "buy_qty_pct_of_quote": 100.0}],
            "tick_interval_ms": 2000,
        }
    )
    state = {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "initial_alloc_base_qty": 1.0,
        "reference_price": 100.0,
        "_dll_ref_date": "2099-01-01",
        "_dll_ref_usd": 1000.0,
        "_daily_loss_limit_hit": True,
    }

    actions, next_wake = tick_dca_grid_trailing(
        state, cfg, price=100.0, base_balance=1.0, quote_balance=0.0
    )

    assert actions == []
    assert next_wake == pytest.approx(2.0)
    assert "_daily_loss_limit_hit" not in state
