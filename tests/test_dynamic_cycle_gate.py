"""
Tests for the Dynamic Mode cycle-entry risk gate (cycle_gate.py) and the
behaviour stance (strategy_engine.compute_stance).

Covers:
  * risk model: high on a flash drop / DUMP, low on a calm range
  * hold state machine: start at HOLD_ON, hysteresis release after
    RELEASE_CONFIRM low-risk checks, max-hold ceiling, not-applicable guards
  * action filtering: withholds fresh buys, keeps de-risking, engages cycle
  * stance: directionally correct + only reinforces the regime bias
"""

from __future__ import annotations

import time

import pytest

from app.botengine.dynamic import cycle_gate as cg
from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import strategy_engine as se
from app.botengine.dynamic.features import MarketFeatures


@pytest.fixture(autouse=True)
def _legacy_cycle_hold_enabled_for_gate_unit_tests(monkeypatch):
    """Gate unit tests exercise legacy hold logic; V4 production default is OFF."""
    monkeypatch.setattr(cg, "HOLD_ENABLED", True)


# ---- feature fixtures -------------------------------------------------------

def _calm_features() -> dict:
    return {
        "atr_pct_5m": 0.5,
        "realized_vol_5m": 0.6,
        "ret_5m_last": 0.05,
        "rsi_5m": 52.0,
        "rsi_1h": 51.0,
        "ema_slope_1h_pct": 0.05,
        "volume_zscore_5m": 0.2,
        "spread_pct": 0.02,
        "wick_body_ratio_5m": 0.8,
        "adx_1h": 15.0,
    }


def _dump_features() -> dict:
    return {
        "atr_pct_5m": 2.6,
        "realized_vol_5m": 2.8,
        "ret_5m_last": -4.2,        # flash crash 5m bar
        "rsi_5m": 22.0,
        "rsi_1h": 30.0,
        "ema_slope_1h_pct": -1.1,
        "volume_zscore_5m": 3.4,    # panic volume
        "spread_pct": 0.30,         # liquidity stress
        "wick_body_ratio_5m": 2.6,
        "adx_1h": 38.0,
    }


def _cfg(buy_grids=2, max_buy_levels=3) -> dict:
    return {
        "symbol": "BTCUSDT",
        "max_buy_levels": max_buy_levels,
        "buy_grids": [
            {"buy_grid_pct": 2.0 * (i + 1), "buy_qty_pct_of_quote": 50.0}
            for i in range(buy_grids)
        ],
        "sell_grids": [{"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 100.0}],
    }


def _state(cycle_id=2, **over) -> dict:
    s = {
        "bot_id": 1,
        "cycle_id": cycle_id,
        "buy_grid_fired": [False, False],
        "quote_balance": 100.0,
        "initial_allocation_done": True,
    }
    s.update(over)
    return s


# ---- risk model -------------------------------------------------------------

def test_risk_low_on_calm_range():
    v = cg.compute_risk(_calm_features(), reg.LOW_VOL_RANGING, 0.7)
    assert v.risk_score <= cg.HOLD_OFF, v.to_dict()


def test_risk_high_on_dump():
    v = cg.compute_risk(_dump_features(), reg.DUMP_RISK, 0.9)
    assert v.risk_score >= cg.HOLD_ON, v.to_dict()


def test_bearish_gate_suppresses_uptrend_churn():
    # High vol/volume but UP slope + green bar → not a hold-worthy downside risk.
    f = _dump_features()
    f["ret_5m_last"] = 1.5
    f["ema_slope_1h_pct"] = 0.8
    v = cg.compute_risk(f, reg.TRENDING_UP, 0.8)
    assert v.risk_score < cg.HOLD_ON, v.to_dict()


# ---- hold state machine -----------------------------------------------------

def test_hold_starts_on_high_risk():
    st = _state()
    v = cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert v.holding is True
    assert cg.is_holding(st) is True


def test_emergency_only_no_hold_on_moderate_trend_down():
    f = _dump_features()
    f["ret_5m_last"] = -2.0
    f["spread_pct"] = 0.08
    f["volume_zscore_5m"] = 1.0
    st = _state()
    v = cg.evaluate(f, reg.TRENDING_DOWN, 0.75, st, _cfg())
    assert v.holding is False


def test_hold_releases_after_confirm_streak():
    st = _state()
    cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert cg.is_holding(st)
    # First calm check: eligible but not yet confirmed (RELEASE_CONFIRM=2 default)
    cg.evaluate(_calm_features(), reg.LOW_VOL_RANGING, 0.7, st, _cfg())
    if cg.RELEASE_CONFIRM >= 2:
        assert cg.is_holding(st), "should not release on a single calm check"
    # Enough consecutive calm checks → released
    for _ in range(cg.RELEASE_CONFIRM):
        cg.evaluate(_calm_features(), reg.LOW_VOL_RANGING, 0.7, st, _cfg())
    assert cg.is_holding(st) is False


def test_hold_max_ceiling_releases(monkeypatch):
    monkeypatch.setattr(cg, "MAX_HOLD_SEC", 0.0)  # any held time exceeds ceiling
    st = _state()
    cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    # next eval (still high risk) must release due to the ceiling
    v = cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert v.holding is False
    assert v.released_reason == "max_hold_reached"


def test_cycle1_never_holds():
    st = _state(cycle_id=1, initial_allocation_done=False, quote_balance=0.0)
    v = cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert v.holding is False


def test_no_buy_capacity_never_holds():
    st = _state(buy_grid_fired=[True, True, True])  # DCA cap exhausted
    cfg = _cfg(max_buy_levels=3)
    st["buy_grid_fired"] = [True, True, True]
    v = cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, cfg)
    assert v.holding is False


def test_engaged_cycle_not_re_held():
    st = _state()
    cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert cg.is_holding(st)
    cg.mark_engaged(st)
    v = cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert v.holding is False
    assert cg.cycle_engaged(st) is True


# ---- action filtering -------------------------------------------------------

def test_filter_blocks_fresh_buys_keeps_derisking():
    st = _state()
    cg.evaluate(_dump_features(), reg.DUMP_RISK, 0.9, st, _cfg())
    assert cg.is_holding(st)
    actions = [
        {"reason": "trail_buy_grid", "side": "BUY"},
        {"reason": "initial_allocation", "side": "BUY"},
        {"reason": "trail_sell_grid", "side": "SELL"},
        {"reason": "trail_profit_sell", "side": "SELL"},
        {"reason": "trail_reentry_buy", "side": "BUY"},
    ]
    kept, blocked = cg.filter_actions(st, actions)
    reasons = {a["reason"] for a in kept}
    assert blocked == 2
    assert "trail_buy_grid" not in reasons
    assert "initial_allocation" not in reasons
    assert "trail_sell_grid" in reasons
    assert "trail_profit_sell" in reasons
    assert "trail_reentry_buy" in reasons  # cycle-close re-entry is allowed


def test_filter_marks_engaged_when_not_holding():
    st = _state()
    # not holding → a fresh buy commits the cycle
    kept, blocked = cg.filter_actions(st, [{"reason": "trail_buy_grid"}])
    assert blocked == 0
    assert cg.cycle_engaged(st) is True


# ---- stance -----------------------------------------------------------------

def _mf(**over) -> MarketFeatures:
    base = dict(
        symbol="BTCUSDT", price=100.0, atr_pct_5m=1.0, adx_1h=15.0,
        ema_slope_1h_pct=0.1, realized_vol_5m=0.8, spread_pct=0.02,
        rsi_1h=50.0, rsi_5m=50.0,
    )
    base.update(over)
    return MarketFeatures(**base)


def test_stance_defensive_in_downtrend():
    f = _mf(adx_1h=40.0, ema_slope_1h_pct=-1.2, realized_vol_5m=2.5)
    s = se.compute_stance(f, reg.RegimeResult(reg.TRENDING_DOWN, reg.TRENDING_DOWN, 0.8, {}))
    assert s.label == se.STANCE_DEFENSIVE
    assert s.score < 0


def test_stance_aggressive_in_calm_range():
    f = _mf(adx_1h=12.0, ema_slope_1h_pct=0.1, realized_vol_5m=0.6, atr_pct_5m=1.0)
    s = se.compute_stance(f, reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {}))
    assert s.label == se.STANCE_AGGRESSIVE
    assert s.score > 0


def test_stance_reduces_base_in_dump_vs_calm():
    base_cfg = {
        "base_alloc_pct": 50.0, "quote_alloc_pct": 50.0,
        "sell_grids": [{"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 100.0}],
        "buy_grids": [{"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 100.0}],
        "fee_rate": 0.001,
    }
    calm = _mf(adx_1h=12.0, ema_slope_1h_pct=0.1, realized_vol_5m=0.6)
    dump = _mf(adx_1h=40.0, ema_slope_1h_pct=-1.5, realized_vol_5m=3.0, ret_5m_last=-4.0)
    sug_calm = se.suggest(calm, reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {}), base_cfg)
    sug_dump = se.suggest(dump, reg.RegimeResult(reg.DUMP_RISK, reg.DUMP_RISK, 0.9, {}), base_cfg)
    assert sug_dump.base_alloc_pct < sug_calm.base_alloc_pct
    assert sug_calm.stance is not None and sug_dump.stance is not None
    assert sug_dump.stance["label"] == se.STANCE_DEFENSIVE


def test_suggest_exposes_stance_dict():
    base_cfg = {
        "base_alloc_pct": 50.0, "quote_alloc_pct": 50.0,
        "sell_grids": [{"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 100.0}],
        "buy_grids": [{"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 100.0}],
    }
    f = _mf()
    sug = se.suggest(f, reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.6, {}), base_cfg)
    assert isinstance(sug.stance, dict)
    assert {"score", "label", "reward_score", "risk_score"} <= set(sug.stance)
