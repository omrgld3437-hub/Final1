"""
Behaviour tests for the project-wide audit fixes (PROJECT_WIDE_AUDIT_REPORT.md):
  P0.1 dynamic_mode string-bool parse
  P0.2 dynamic grid quantity percentages preserve the manual template
  P0.3 high-ATR grids no longer collapse to a single 8% level
  P1.1 RSI / liquidity gates do not mutate grid quantity percentages
  P1.2 DUMP_RISK fast 5m drop
  P1.4 confidence-weighted smoothing alpha
  P1.5 fee-aware minimum grid step
  P2.1 SQUEEZE 1h→5m fallback symmetry
  P2.2 BREAKOUT direction-aware (down → defensive)
  P2.3 features expose spread_bps
"""

from __future__ import annotations
import pytest

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import risk_engine as risk
from app.botengine.dynamic import safety_gate as sg
from app.botengine.dynamic.features import MarketFeatures
from app.botengine.dynamic.strategy_engine import (
    suggest,
    alpha_for_confidence,
    _fee_aware_min_step,
)
from app.botengine.models import DcaGridTrailingConfig, config_from_ui_payload
from app.utils.parse_utils import parse_bool


# ---------------------------------------------------------------------------
# P0.1 — string-bool parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True), (False, False),
        ("true", True), ("false", False),
        ("1", True), ("0", False),
        ("on", True), ("off", False),
        ("yes", True), ("no", False),
        (1, True), (0, False),
        (None, False), ("", False),
        ("garbage", False),
    ],
)
def test_parse_bool(value, expected):
    assert parse_bool(value) is expected


def test_dynamic_mode_string_false_is_off_in_model():
    cfg = DcaGridTrailingConfig({"symbol": "BTCUSDT", "max_buy_levels": 1, "dynamic_mode": "false"})
    assert cfg.dynamic_mode is False
    assert cfg.to_dict()["dynamic_mode"] is False


def test_dynamic_mode_string_false_in_ui_payload_no_daily_loss_injection():
    payload = {
        "symbol": "BTCUSDT", "budget_usd": 1000.0,
        "down": {"grids": [{"trigger_pct": 2.0, "qty_pct": 10.0}]},
        "max_buy_levels": 1, "dynamic_mode": "false",
    }
    cfg = config_from_ui_payload(payload)
    assert cfg.dynamic_mode is False
    # When off, the budget×5% default must NOT be injected.
    assert cfg.daily_loss_limit_usd == 0.0


def test_is_dynamic_mode_active_string_false():
    cfg = {"max_buy_levels": 3, "daily_loss_limit_usd": 25.0, "dynamic_mode": "false"}
    assert sg.is_dynamic_mode_active(cfg) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(n_buy=3, n_sell=3, buy_qty=15.0, sell_qty=15.0, fee=0.001):
    return {
        "base_alloc_pct": 50.0, "quote_alloc_pct": 50.0,
        "buy_fee_rate": fee, "sell_fee_rate": fee, "min_net_profit_rate": 0.0,
        "sell_grids": [{"sell_grid_pct": 2.0 * (i + 1), "sell_qty_pct_of_base": sell_qty} for i in range(n_sell)],
        "buy_grids": [{"buy_grid_pct": 2.0 * (i + 1), "buy_qty_pct_of_quote": buy_qty} for i in range(n_buy)],
        "sell_trigger_trailing_pct": 0.3, "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0, "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0, "profit_reentry_rise_pct": 0.3,
    }


def _buy_total(s):
    return sum(g["buy_qty_pct_of_quote"] for g in s.buy_grids)


def _sell_total(s):
    return sum(g["sell_qty_pct_of_base"] for g in s.sell_grids)


def _feat(**kw):
    base = dict(symbol="X", price=1000.0, atr_pct_5m=1.0, data_fresh=True)
    base.update(kw)
    return MarketFeatures(**base)


def _rr(regime, conf=0.8):
    return reg.RegimeResult(regime, regime, conf, {})


# ---------------------------------------------------------------------------
# P0.2 — grid quantity percentages preserve the manual template
# ---------------------------------------------------------------------------


def test_grid_qty_percentages_preserve_manual_template_in_risky_regimes():
    base = _cfg()
    f = _feat()
    dump = _buy_total(suggest(f, _rr(reg.DUMP_RISK), base))
    td = _buy_total(suggest(f, _rr(reg.TRENDING_DOWN), base))
    lvr = _buy_total(suggest(f, _rr(reg.LOW_VOL_RANGING), base))
    # Dynamic mode must not turn user-facing grid totals into confusing values
    # like 36.4/43.6. Defensive regimes use allocation / spacing, not qty drift.
    assert dump == pytest.approx(45.0, abs=0.1)
    assert td == pytest.approx(45.0, abs=0.1)
    assert lvr == pytest.approx(45.0, abs=0.1)


# ---------------------------------------------------------------------------
# P0.3 — high ATR no longer collapses all grids onto 8%
# ---------------------------------------------------------------------------


def test_high_atr_grids_not_degenerate():
    base = _cfg(n_buy=4)
    f = _feat(atr_pct_5m=6.0)  # extreme vol
    s = suggest(f, _rr(reg.DUMP_RISK), base)
    pcts = [g["buy_grid_pct"] for g in s.buy_grids]
    # strictly increasing, none above the hard bound, not all-equal
    assert pcts == sorted(pcts)
    assert len(set(pcts)) == len(pcts), f"degenerate (collapsed) grids: {pcts}"
    assert max(pcts) <= risk.BOUNDS["grid_step_pct"][1] + 1e-6
    # post risk-engine they must also stay non-degenerate
    out = risk.apply_safety(s, base).to_dict()
    rpcts = [g["buy_grid_pct"] for g in out["buy_grids"]]
    assert len(set(rpcts)) == len(rpcts), f"degenerate after risk: {rpcts}"


# ---------------------------------------------------------------------------
# P1.5 — fee-aware minimum grid step
# ---------------------------------------------------------------------------


def test_fee_aware_min_grid_step():
    base = _cfg(n_buy=2, fee=0.001)  # round-trip ~0.2%
    floor = _fee_aware_min_step(base, _feat())
    assert floor == pytest.approx(0.2, abs=0.01)
    f = _feat(atr_pct_5m=0.1)  # tiny ATR → raw step well below the fee floor
    s = suggest(f, _rr(reg.LOW_VOL_RANGING), base)
    assert s.buy_grids[0]["buy_grid_pct"] >= floor - 1e-6


def test_spread_widens_fee_floor():
    base = _cfg()
    floor_no_spread = _fee_aware_min_step(base, _feat())
    floor_wide = _fee_aware_min_step(base, _feat(spread_pct=0.5))
    assert floor_wide > floor_no_spread  # min step ≥ 2×spread


# ---------------------------------------------------------------------------
# P1.1 — RSI / liquidity must not mutate grid qty percentages
# ---------------------------------------------------------------------------


def test_rsi_overbought_keeps_manual_buy_quantities():
    base = _cfg()
    neutral = _buy_total(suggest(_feat(rsi_1h=50.0), _rr(reg.LOW_VOL_RANGING), base))
    overbought = _buy_total(suggest(_feat(rsi_1h=80.0), _rr(reg.LOW_VOL_RANGING), base))
    assert overbought == pytest.approx(neutral, abs=0.1)


def test_rsi_oversold_keeps_manual_sell_quantities():
    base = _cfg()
    neutral = _sell_total(suggest(_feat(rsi_1h=50.0), _rr(reg.LOW_VOL_RANGING), base))
    oversold = _sell_total(suggest(_feat(rsi_1h=20.0), _rr(reg.LOW_VOL_RANGING), base))
    assert oversold == pytest.approx(neutral, abs=0.1)


def test_wide_spread_and_low_volume_keep_manual_buy_quantities():
    base = _cfg()
    neutral = _buy_total(suggest(_feat(), _rr(reg.LOW_VOL_RANGING), base))
    wide = _buy_total(suggest(_feat(spread_pct=0.5), _rr(reg.LOW_VOL_RANGING), base))
    illiquid = _buy_total(suggest(_feat(volume_24h_usdt=10_000.0), _rr(reg.LOW_VOL_RANGING), base))
    assert wide == pytest.approx(neutral, abs=0.1)
    assert illiquid == pytest.approx(neutral, abs=0.1)


# ---------------------------------------------------------------------------
# P1.2 — DUMP fast 5m drop
# ---------------------------------------------------------------------------


def test_dump_fast_drop_5m():
    f = _feat(ret_5m_last=-4.0)  # single 5m bar down 4%
    r = reg.classify(f, None)
    assert r.regime == reg.DUMP_RISK


def test_no_dump_on_small_drop():
    f = _feat(ret_5m_last=-1.0)  # mild, below the fast-drop threshold
    r = reg.classify(f, None)
    assert r.regime != reg.DUMP_RISK


# ---------------------------------------------------------------------------
# P2.2 — BREAKOUT direction aware
# ---------------------------------------------------------------------------


def test_downward_breakout_is_defensive_not_neutral():
    down = reg.classify(_feat(atr_pct_5m=2.0, bbw_1h=7.0, volume_zscore_5m=2.5, ema_slope_1h_pct=-1.0), None)
    assert down.regime == reg.TRENDING_DOWN  # not neutral BREAKOUT
    up = reg.classify(_feat(atr_pct_5m=2.0, bbw_1h=7.0, volume_zscore_5m=2.5, ema_slope_1h_pct=1.0), None)
    assert up.regime == reg.BREAKOUT


# ---------------------------------------------------------------------------
# P2.1 — SQUEEZE fallback symmetry (1h missing → 5m)
# ---------------------------------------------------------------------------


def test_squeeze_falls_back_to_5m_bbw():
    # bbw_1h missing, bbw_5m narrow → should still classify SQUEEZE
    f = _feat(atr_pct_5m=0.5, bbw_1h=None, bbw_5m=2.0)
    r = reg.classify(f, None)
    assert r.regime == reg.SQUEEZE


# ---------------------------------------------------------------------------
# P1.4 — confidence-weighted smoothing alpha
# ---------------------------------------------------------------------------


def test_alpha_for_confidence_monotone():
    assert alpha_for_confidence(0.5) == pytest.approx(0.5)  # backward-compatible
    assert alpha_for_confidence(0.0) < alpha_for_confidence(0.5) < alpha_for_confidence(1.0)
    assert 0.3 <= alpha_for_confidence(0.0) <= 0.7
    assert 0.3 <= alpha_for_confidence(1.0) <= 0.7


# ---------------------------------------------------------------------------
# P2.3 — spread_bps exposed for leaderboard/UI
# ---------------------------------------------------------------------------


def test_features_expose_spread_bps():
    d = MarketFeatures(symbol="X", price=1.0, spread_pct=0.1, spread_bps=10.0).to_dict()
    assert "spread_bps" in d and d["spread_bps"] == 10.0
