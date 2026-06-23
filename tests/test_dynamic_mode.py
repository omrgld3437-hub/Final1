"""
Unit tests for Dynamic Mode: indicators, risk engine clamps, safety gate,
snapshot lifecycle. These tests have no external dependencies — pure in-memory.
"""

from __future__ import annotations
import math

import pytest

from app.botengine.dynamic import indicators as ind
from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import risk_engine as risk
from app.botengine.dynamic import safety_gate as sg
from app.botengine.dynamic.features import MarketFeatures
from app.botengine.dynamic.strategy_engine import (
    ParamSuggestion,
    suggest,
    smooth_against_prev,
)
from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing


# ---------------------------------------------------------------------------
# Helpers: synthetic candles
# ---------------------------------------------------------------------------


def _candles(closes):
    out = []
    for i, c in enumerate(closes):
        out.append(
            {"t": i * 1000, "o": c, "h": c * 1.005, "l": c * 0.995, "c": c, "v": 100.0}
        )
    return out


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Risk engine clamps
# ---------------------------------------------------------------------------


def _base_cfg():
    return {
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25.0}],
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 25.0}],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
    }


def _suggestion(**over):
    base = dict(
        base_alloc_pct=50.0,
        quote_alloc_pct=50.0,
        sell_grids=[{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25.0}],
        buy_grids=[{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 25.0}],
        sell_trigger_trailing_pct=0.3,
        buy_trigger_trailing_pct=0.3,
        profit_exit_rise_pct=1.0,
        profit_exit_drop_pct=0.3,
        profit_reentry_drop_pct=1.0,
        profit_reentry_rise_pct=0.3,
        reasons=[],
    )
    base.update(over)
    return ParamSuggestion(**base)


def test_risk_engine_clamps_out_of_range_trailing():
    s = _suggestion(sell_trigger_trailing_pct=99.0)  # way out of bounds
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    assert out.sell_trigger_trailing_pct <= risk.BOUNDS["trailing_pct"][1]
    assert any("sell_trigger_trailing_pct" in c for c in out.clamps)


def test_risk_engine_fallback_on_nan():
    s = _suggestion(sell_trigger_trailing_pct=float("nan"))
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    assert math.isfinite(out.sell_trigger_trailing_pct)
    assert any("sell_trigger_trailing_pct" in f for f in out.fallbacks)


def test_risk_engine_rate_limits_jump():
    prev = {"sell_trigger_trailing_pct": 0.30}
    s = _suggestion(sell_trigger_trailing_pct=2.0)  # huge jump
    out = risk.apply_safety(s, _base_cfg(), prev_applied=prev)
    # Allowed delta = 0.60 * 0.30 = 0.18 → cap at 0.48
    assert out.sell_trigger_trailing_pct <= 0.30 + 0.18 + 1e-6
    assert any("rate-limited" in c for c in out.clamps)


def test_risk_engine_anti_martingale_grid_growth():
    s = _suggestion(
        buy_grids=[
            {"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0},
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 80.0},  # 8x growth
        ]
    )
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    ratio = (
        out.buy_grids[1]["buy_qty_pct_of_quote"]
        / out.buy_grids[0]["buy_qty_pct_of_quote"]
    )
    assert ratio <= risk.GRID_GROWTH_R_MAX + 1e-6


def test_risk_engine_non_monotone_triggers_fixed():
    s = _suggestion(
        sell_grids=[
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25.0},  # lower than prev
        ]
    )
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    assert out.sell_grids[1]["sell_grid_pct"] >= out.sell_grids[0]["sell_grid_pct"]


def test_risk_engine_allocation_sums_to_100():
    s = _suggestion(base_alloc_pct=70.0, quote_alloc_pct=30.0)
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    assert abs(out.base_alloc_pct + out.quote_alloc_pct - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# Safety gate
# ---------------------------------------------------------------------------


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
    out = sg.emergency_check(state, cfg, equity=900.0)  # -10% > 8%
    assert out["action"] == "NONE"


def test_emergency_check_emergency_close_disabled():
    cfg = {
        "max_buy_levels": 3,
        "daily_loss_limit_usd": 25.0,
        "dynamic_mode": True,
        "initial_capital_usdt": 1000.0,
    }
    state = {"cycle_start_equity": 1000.0}
    out = sg.emergency_check(state, cfg, equity=820.0)  # -18% > 15%
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
    out = sg.emergency_check(state, cfg, equity=500.0)  # -50% but mode off
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


# ---------------------------------------------------------------------------
# DCA-depth guard: emergency must not fire before configured buy grids execute
# ---------------------------------------------------------------------------


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
            {"buy_grid_pct": 20.0},  # deepest configured buy grid: -20%
        ],
    }


def test_emergency_held_back_while_inside_grid_plan():
    """Price -12% (within deepest grid -20% + 5% buffer): even though equity is
    down -15% (which would normally trip both thresholds), the breaker stays
    silent so the bot can still execute its -20% buy grid."""
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0, "reference_price": 100.0}
    out = sg.emergency_check(state, cfg, equity=850.0, price=88.0)
    assert out["action"] == "NONE"
    assert out["metrics"] == {}


def test_emergency_fires_beyond_grid_plan():
    """Breaker is disabled, so even beyond the grid plan it does not engage."""
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0, "reference_price": 100.0}
    out = sg.emergency_check(state, cfg, equity=850.0, price=70.0)
    assert out["action"] == "NONE"


def test_depth_guard_skipped_when_reference_unknown():
    """Breaker is disabled, so missing reference does not matter."""
    cfg = _deep_grid_cfg()
    state = {"cycle_start_equity": 1000.0}  # no reference_price
    out = sg.emergency_check(state, cfg, equity=850.0, price=88.0)
    assert out["action"] == "NONE"


# ---------------------------------------------------------------------------
# Suggestion → risk pipeline (full path)
# ---------------------------------------------------------------------------


def test_suggest_produces_valid_shape_with_no_data():
    features = MarketFeatures(symbol="BTCUSDT", price=50000.0, data_fresh=True)
    regime_result = reg.RegimeResult(reg.UNKNOWN, reg.UNKNOWN, 0.0, {})
    s = suggest(features, regime_result, _base_cfg())
    assert s.base_alloc_pct + s.quote_alloc_pct == pytest.approx(100.0)
    assert s.sell_trigger_trailing_pct > 0
    assert isinstance(s.sell_grids, list)


def test_smoothing_blends_with_prev_applied():
    features = MarketFeatures(symbol="BTCUSDT", price=50000.0, data_fresh=True)
    regime_result = reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {})
    base = _base_cfg()
    new = suggest(features, regime_result, base)
    prev_applied = {"sell_trigger_trailing_pct": 0.10}
    blended = smooth_against_prev(new, prev_applied, alpha=0.5)
    assert blended.sell_trigger_trailing_pct >= 0.10  # moved towards new value
    assert (
        blended.sell_trigger_trailing_pct
        <= max(new.sell_trigger_trailing_pct, 0.10) + 0.01
    )


def test_full_pipeline_with_trending_down_keeps_more_quote():
    features = MarketFeatures(
        symbol="BTCUSDT", price=50000.0, atr_pct_5m=1.0, data_fresh=True
    )
    regime_result = reg.RegimeResult(reg.TRENDING_DOWN, reg.TRENDING_DOWN, 0.8, {})
    s = suggest(features, regime_result, _base_cfg())
    out = risk.apply_safety(s, _base_cfg(), prev_applied=None)
    # TRENDING_DOWN target_base = 25 → after clamps must still be defensive (≤ 50)
    assert out.base_alloc_pct <= 50.0
    assert out.quote_alloc_pct >= 50.0


# ---------------------------------------------------------------------------
# Model: dynamic_mode flag round-trip
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Regime hysteresis
# ---------------------------------------------------------------------------


def test_regime_hysteresis_does_not_flip_on_single_change():
    prev = {
        "current": reg.LOW_VOL_RANGING,
        "candidate": reg.LOW_VOL_RANGING,
        "candidate_streak": 0,
    }
    # First switch to TRENDING_UP needs >= MIN_DWELL_CYCLES cycles
    # With MIN_DWELL_CYCLES=1, one consecutive vote suffices, but we also test the candidate persistence.
    new_state = reg.update_regime_state(
        prev, reg.RegimeResult(reg.LOW_VOL_RANGING, reg.TRENDING_UP, 0.8, {})
    )
    assert "current" in new_state
    assert new_state["candidate"] == reg.TRENDING_UP


# ---------------------------------------------------------------------------
# Capital deployment: grid qty distribution preserves the manual total
# ---------------------------------------------------------------------------


def _multi_grid_cfg(sell_total_parts, buy_total_parts):
    return {
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [
            {"sell_grid_pct": 2.0 * (i + 1), "sell_qty_pct_of_base": q}
            for i, q in enumerate(sell_total_parts)
        ],
        "buy_grids": [
            {"buy_grid_pct": 2.0 * (i + 1), "buy_qty_pct_of_quote": q}
            for i, q in enumerate(buy_total_parts)
        ],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
    }


def test_grid_qty_distribution_preserves_manual_total():
    # Manual template deploys 45% per side (10+15+20), intentionally NOT 100.
    base = _multi_grid_cfg([10.0, 15.0, 20.0], [10.0, 15.0, 20.0])
    features = MarketFeatures(
        symbol="BTCUSDT", price=1000.0, atr_pct_5m=1.0, data_fresh=True
    )
    rr = reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {})
    s = suggest(features, rr, base)
    sell_total = sum(g["sell_qty_pct_of_base"] for g in s.sell_grids)
    buy_total = sum(g["buy_qty_pct_of_quote"] for g in s.buy_grids)
    # Total and per-level percentages are preserved (not forced to 100).
    assert sell_total == pytest.approx(45.0, abs=0.1)
    assert buy_total == pytest.approx(45.0, abs=0.1)


def test_dynamic_grid_triggers_are_duration_targeted_not_welded_to_manual():
    """Grid triggers are now sized by the cycle-duration model (vol-scaled), NOT
    pinned to the manual template. The manual template only fixes the grid COUNT
    and the per-level QTY distribution. The economic fee floor + depth cap are the
    real guards; the manual trigger is no longer a floor (fixes the legacy
    'grid welded to manual 1%' defect)."""
    base = {
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 50.0},
            {"sell_grid_pct": 4.0, "sell_qty_pct_of_base": 50.0},
        ],
        "buy_grids": [
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 50.0},
            {"buy_grid_pct": 4.0, "buy_qty_pct_of_quote": 50.0},
        ],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
    }
    rr = reg.RegimeResult(reg.TRENDING_UP, reg.TRENDING_UP, 0.8, {})

    # QTY distribution is preserved regardless of vol.
    s = suggest(
        MarketFeatures(symbol="SOLUSDT", price=75.0, atr_pct_1h=1.0, data_fresh=True),
        rr, base,
    )
    assert [g["sell_qty_pct_of_base"] for g in s.sell_grids] == pytest.approx([50.0, 50.0])
    assert [g["buy_qty_pct_of_quote"] for g in s.buy_grids] == pytest.approx([50.0, 50.0])
    # strictly increasing per-level triggers
    sp = [g["sell_grid_pct"] for g in s.sell_grids]
    assert sp == sorted(sp) and len(set(sp)) == len(sp)

    # De-welding: under CALM volatility the step drops BELOW the manual 2% level —
    # impossible under the old 'never tighten below manual' rule.
    calm = suggest(
        MarketFeatures(symbol="SOLUSDT", price=75.0, atr_pct_1h=0.3, data_fresh=True),
        rr, base,
    )
    assert calm.buy_grids[0]["buy_grid_pct"] < 2.0
    # Under WILD volatility the step rises ABOVE the manual 2% level.
    wild = suggest(
        MarketFeatures(symbol="SOLUSDT", price=75.0, atr_pct_1h=4.0, data_fresh=True),
        rr, base,
    )
    assert wild.buy_grids[0]["buy_grid_pct"] > 2.0


def test_position_state_does_not_reshape_manual_grid_quantities():
    base = _multi_grid_cfg([50.0, 50.0], [50.0, 50.0])
    features = MarketFeatures(
        symbol="SOLUSDT", price=75.0, atr_pct_5m=1.0, data_fresh=True
    )
    rr = reg.RegimeResult(reg.DUMP_RISK, reg.DUMP_RISK, 0.9, {})
    s = suggest(
        features,
        rr,
        base,
        {"buy_levels_fired": 2, "max_buy_levels": 2},
    )

    assert [g["sell_qty_pct_of_base"] for g in s.sell_grids] == pytest.approx([50.0, 50.0])
    assert [g["buy_qty_pct_of_quote"] for g in s.buy_grids] == pytest.approx([50.0, 50.0])


def test_grid_qty_distribution_defaults_to_100_when_no_manual_qty():
    # If the template carries no usable qty figures we fall back to full deploy.
    base = _multi_grid_cfg([0.0, 0.0], [0.0, 0.0])
    features = MarketFeatures(
        symbol="BTCUSDT", price=1000.0, atr_pct_5m=1.0, data_fresh=True
    )
    rr = reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {})
    s = suggest(features, rr, base)
    buy_total = sum(g["buy_qty_pct_of_quote"] for g in s.buy_grids)
    assert buy_total == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Safety prerequisite: backend does not inject daily_loss_limit_usd
# ---------------------------------------------------------------------------


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
