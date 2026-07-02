"""
Tests for the cycle-duration-targeted sizing (app/botengine/dynamic/cycle_duration.py)
and its integration into the strategy engine.

Covers:
  * volatility estimate (1h primary, 5m fallback, bounds)
  * G(T) = σ·sqrt(2T/π) and its exact inverse predicted_days
  * regime-aware target days + low-confidence damping toward T_CENTER
  * overrun → widen span ; churn → lengthen target (owner's feedback policy)
  * suggest() now (a) un-welds the grid from the manual 1% floor,
    (b) widens take-profit to a multi-day target, (c) preserves qty distribution,
    (d) softens the ADX cliff, (e) reconciles RSI-vs-regime contradiction.
"""

from __future__ import annotations

import math
import pytest

from app.botengine.dynamic import cycle_duration as cd
from app.botengine.dynamic import cycle_manager as cm
from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import risk_engine as risk
from app.botengine.dynamic.features import MarketFeatures
from app.botengine.dynamic.strategy_engine import suggest, compute_stance


def _feat(**kw):
    base = dict(symbol="X", price=100.0, atr_pct_5m=0.4, atr_pct_1h=1.0, data_fresh=True)
    base.update(kw)
    return MarketFeatures(**base)


def _rr(regime, conf=0.8):
    return reg.RegimeResult(regime, regime, conf, {})


def _cfg(n=3, qty=30.0):
    return {
        "base_alloc_pct": 50.0, "quote_alloc_pct": 50.0,
        "buy_fee_rate": 0.001, "sell_fee_rate": 0.001, "min_net_profit_rate": 0.0,
        "sell_grids": [{"sell_grid_pct": 1.0 * (i + 1), "sell_qty_pct_of_base": qty} for i in range(n)],
        "buy_grids": [{"buy_grid_pct": 1.0 * (i + 1), "buy_qty_pct_of_quote": qty} for i in range(n)],
        "sell_trigger_trailing_pct": 0.3, "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0, "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0, "profit_reentry_rise_pct": 0.3,
    }


# ---- volatility -------------------------------------------------------------


def test_daily_vol_prefers_1h_and_falls_back_to_5m():
    v1 = cd.daily_vol_pct(_feat(atr_pct_1h=1.0, atr_pct_5m=0.4))
    assert v1 == pytest.approx(1.0 * math.sqrt(24) * cd.ATR_TO_STD, rel=1e-6)
    v2 = cd.daily_vol_pct(_feat(atr_pct_1h=None, atr_pct_5m=0.4))
    assert v2 == pytest.approx(0.4 * math.sqrt(288) * cd.ATR_TO_STD, rel=1e-6)


def test_daily_vol_none_when_no_atr():
    assert cd.daily_vol_pct(_feat(atr_pct_1h=None, atr_pct_5m=None)) is None


def test_daily_vol_clamped():
    hi = cd.daily_vol_pct(_feat(atr_pct_1h=100.0))
    assert hi == pytest.approx(cd.SIGMA_CEIL_PCT)
    lo = cd.daily_vol_pct(_feat(atr_pct_1h=0.001, atr_pct_5m=None))
    assert lo == pytest.approx(cd.SIGMA_FLOOR_PCT)


# ---- duration math ----------------------------------------------------------


def test_favorable_excursion_formula_and_inverse():
    sigma = 5.0
    for t in (1.0, 3.0, 7.0):
        g = cd.favorable_excursion_pct(sigma, t)
        assert g == pytest.approx(sigma * math.sqrt(2 * t / math.pi), rel=1e-9)
        # predicted_days is the exact inverse for t in the valid window
        assert cd.predicted_days(sigma, g) == pytest.approx(t, rel=1e-9)


def test_favorable_excursion_monotone():
    assert cd.favorable_excursion_pct(5, 1) < cd.favorable_excursion_pct(5, 7)
    assert cd.favorable_excursion_pct(3, 3) < cd.favorable_excursion_pct(6, 3)


# ---- regime target + low-confidence damping ---------------------------------


def test_regime_target_days_within_window():
    for rg in (reg.LOW_VOL_RANGING, reg.TRENDING_UP, reg.TRENDING_DOWN, reg.DUMP_RISK):
        t = cd.regime_target_days(rg, 0.9)
        assert cd.MIN_DAYS <= t <= cd.MAX_DAYS


def test_defensive_regime_targets_faster_than_bullish():
    # high confidence so the regime is fully expressed
    down = cd.regime_target_days(reg.TRENDING_DOWN, 0.9)
    up = cd.regime_target_days(reg.TRENDING_UP, 0.9)
    assert down < up


def test_low_confidence_damps_toward_center():
    # a coin-flip TRENDING_UP must not push the target far from neutral
    far = cd.regime_target_days(reg.TRENDING_UP, 0.9)
    near = cd.regime_target_days(reg.TRENDING_UP, 0.40)
    assert abs(near - cd.T_CENTER) < abs(far - cd.T_CENTER)
    assert near == pytest.approx(cd.T_CENTER, abs=1e-9)  # at/below CONF_FLOOR → fully neutral


# ---- overrun / churn feedback ----------------------------------------------


def test_overrun_widens_span():
    base = cd.compute(_feat(), reg.LOW_VOL_RANGING, 0.7, recent_cycle_days=[3.0, 3.0])
    stuck = cd.compute(_feat(), reg.LOW_VOL_RANGING, 0.7, recent_cycle_days=[12.0, 14.0])
    assert stuck.span_frac > base.span_frac
    assert stuck.grid_span_pct > base.grid_span_pct


def test_churn_lengthens_target():
    base = cd.compute(_feat(), reg.LOW_VOL_RANGING, 0.7, recent_cycle_days=[3.0, 3.0])
    churn = cd.compute(_feat(), reg.LOW_VOL_RANGING, 0.7, recent_cycle_days=[0.2, 0.3])
    assert churn.t_target_days > base.t_target_days


# ---- compute() basic contract ----------------------------------------------


def test_compute_ok_and_bounds():
    ds = cd.compute(_feat(atr_pct_1h=1.05), reg.LOW_VOL_RANGING, 0.7)
    assert ds.ok
    assert cd.TP_RISE_BOUNDS[0] <= ds.profit_exit_rise_pct <= cd.TP_RISE_BOUNDS[1]
    # SOL-like (σ≈3%/day) → multi-percent take-profit, NOT the welded ~1%
    assert ds.profit_exit_rise_pct > 2.0


def test_compute_not_ok_without_vol():
    ds = cd.compute(_feat(atr_pct_1h=None, atr_pct_5m=None), reg.UNKNOWN, 0.5)
    assert ds.ok is False


# ---- integration with suggest() --------------------------------------------


def test_suggest_unwelds_grid_from_manual_floor():
    # Manual template is 1/2/3%. Under LOW vol the duration grid step is BELOW 1%,
    # which the legacy code floored back up to the manual 1%. It must no longer.
    base = _cfg()
    low = _feat(atr_pct_1h=0.25, atr_pct_5m=0.1)  # very calm
    s = suggest(low, _rr(reg.LOW_VOL_RANGING), base)
    first = s.buy_grids[0]["buy_grid_pct"]
    assert first < 1.0  # not pinned to the manual 1% template floor
    # still strictly increasing and within bounds after the risk engine
    out = risk.apply_safety(s, base).to_dict()
    pcts = [g["buy_grid_pct"] for g in out["buy_grids"]]
    assert pcts == sorted(pcts) and len(set(pcts)) == len(pcts)


def test_suggest_take_profit_is_multi_day_targeted():
    base = _cfg()
    s = suggest(_feat(atr_pct_1h=1.05), _rr(reg.LOW_VOL_RANGING), base)
    # vol-scaled TP, far above the legacy welded ~1%
    assert s.profit_exit_rise_pct > 2.0


def test_suggest_grid_widens_with_volatility():
    base = _cfg()
    calm = suggest(_feat(atr_pct_1h=0.4), _rr(reg.LOW_VOL_RANGING), base)
    wild = suggest(_feat(atr_pct_1h=3.0), _rr(reg.LOW_VOL_RANGING), base)
    assert wild.buy_grids[0]["buy_grid_pct"] > calm.buy_grids[0]["buy_grid_pct"]


def test_suggest_preserves_qty_distribution():
    base = _cfg(n=3, qty=30.0)
    s = suggest(_feat(), _rr(reg.LOW_VOL_RANGING), base)
    assert [g["buy_qty_pct_of_quote"] for g in s.buy_grids] == [30.0, 30.0, 30.0]


# ---- Bulgu 4: ADX ramp + RSI/regime reconciliation --------------------------


def test_adx_ramp_does_not_zero_reward_just_above_25():
    # ADX 28 (just into "trend") must NOT collapse grid reward to 0 (legacy cliff).
    st = compute_stance(_feat(adx_1h=28.0, atr_pct_5m=0.4), _rr(reg.LOW_VOL_RANGING))
    assert st.reward_score > 0.0


def test_rsi_contradiction_reduces_defensiveness():
    # regime says DOWN but RSI is bullish and slope ~flat → less defensive than
    # the same DOWN regime with bearish RSI.
    bullish = compute_stance(
        _feat(rsi_1h=60.0, rsi_5m=59.0, ema_slope_1h_pct=-0.1, adx_1h=28.0),
        _rr(reg.TRENDING_DOWN, conf=0.45),
    )
    bearish = compute_stance(
        _feat(rsi_1h=35.0, rsi_5m=34.0, ema_slope_1h_pct=-0.1, adx_1h=28.0),
        _rr(reg.TRENDING_DOWN, conf=0.45),
    )
    assert bullish.score > bearish.score  # less defensive (higher stance)


# ---- reference resolution: "param asistanının yaptığı ilk kodlar referans" ---


def test_reference_freezes_initial_config_once():
    state = {"cycle_id": 2}
    cfg = _cfg(n=3, qty=30.0)
    cfg["base_alloc_pct"] = 55.0
    ref_cfg = cm._reference_cfg(state, cfg)
    assert state["_dynamic_reference"]["_source"] == "initial_config"
    assert len(ref_cfg["buy_grids"]) == 3
    # A later config edit (2 levels, different alloc) must NOT change the frozen
    # reference structure used by sizing.
    edited = _cfg(n=2, qty=50.0)
    edited["base_alloc_pct"] = 20.0
    edited["buy_fee_rate"] = 0.002
    ref_cfg2 = cm._reference_cfg(state, edited)
    assert len(ref_cfg2["buy_grids"]) == 3                       # frozen count
    assert [g["buy_qty_pct_of_quote"] for g in ref_cfg2["buy_grids"]] == [30.0, 30.0, 30.0]
    assert ref_cfg2["base_alloc_pct"] == 55.0                    # frozen alloc
    assert ref_cfg2["buy_fee_rate"] == 0.002                     # fees from LIVE cfg


def test_set_reference_overrides_initial():
    state = {"cycle_id": 5}
    pa_cfg = _cfg(n=2, qty=50.0)                                 # param-assistant output
    assert cm.set_reference(state, pa_cfg, source="param_assistant") is True
    live = _cfg(n=3, qty=30.0)
    ref_cfg = cm._reference_cfg(state, live)
    assert state["_dynamic_reference"]["_source"] == "param_assistant"
    assert len(ref_cfg["buy_grids"]) == 2                        # reference wins over live
