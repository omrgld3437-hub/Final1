"""
Dynamic Mode full-capacity end-to-end logic tests.

Exercises the COMPLETE pipeline with synthetic-but-realistic candle series for
each market regime, and asserts that the produced parameters are internally
consistent and economically sensible:

    features -> regime -> suggest -> smooth -> risk(clamp) -> snapshot -> overlay

Key properties asserted (per the design report's "önce güvenlik" principle):
  1. Every applied value lands inside hard bounds.
  2. base_alloc + quote_alloc == 100, always.
  3. Grid trigger %s are strictly increasing (monotone).
  4. Grid qty distribution never grows faster than the anti-martingale cap.
  5. Defensive regimes (TRENDING_DOWN/DUMP_RISK) keep MORE quote than bullish.
  6. A cycle snapshot is immutable within the cycle (need_recompute=False until
     cycle_id changes or the recompute flag is set).
  7. Stale data falls back to previous applied params (no crash, no garbage).
"""

from __future__ import annotations
import asyncio
import math

import pytest

from app.botengine.dynamic import indicators as ind
from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import strategy_engine as se
from app.botengine.dynamic import risk_engine as risk
from app.botengine.dynamic import cycle_manager as cm
from app.botengine.dynamic.features import MarketFeatures
from app.botengine.dynamic.risk_engine import BOUNDS, GRID_GROWTH_R_MAX


# ---------------------------------------------------------------------------
# Synthetic candle generators
# ---------------------------------------------------------------------------


def _mk(closes, vol_mult=1.0):
    out = []
    for i, c in enumerate(closes):
        rng = c * 0.004 * vol_mult
        out.append(
            {
                "t": i * 300000,
                "o": c,
                "h": c + rng,
                "l": c - rng,
                "c": c,
                "v": 1000.0 * vol_mult,
            }
        )
    return out


def _ranging(n=120, base=1000.0, amp=0.003):
    return _mk([base * (1 + amp * math.sin(i / 3.0)) for i in range(n)])


def _uptrend(n=120, base=1000.0, slope=0.004):
    return _mk([base * (1 + slope * i) for i in range(n)])


def _downtrend(n=120, base=1000.0, slope=0.004):
    return _mk([base * (1 - slope * i) for i in range(n)])


def _high_vol(n=120, base=1000.0):
    return _mk([base * (1 + 0.02 * math.sin(i / 2.0)) for i in range(n)], vol_mult=4.0)


# ---------------------------------------------------------------------------
# Indicator sanity on synthetic series
# ---------------------------------------------------------------------------


def test_indicators_directionally_correct():
    up = _uptrend()
    down = _downtrend()
    assert ind.rsi(up, 14) > 60
    assert ind.rsi(down, 14) < 40
    # ATR% should be larger for high-vol series than calm ranging
    calm = ind.atr_pct(_ranging(), 14)
    wild = ind.atr_pct(_high_vol(), 14)
    assert wild is not None and calm is not None and wild > calm


# ---------------------------------------------------------------------------
# Full pipeline helper
# ---------------------------------------------------------------------------


def _features_from(candles_5m, candles_1h, price):
    """Mimic features.collect_features but offline (no network)."""
    f = MarketFeatures(symbol="TESTUSDT", price=price, data_fresh=True)
    f.atr_pct_5m = ind.atr_pct(candles_5m, 14)
    f.bbw_5m = ind.bollinger_band_width(candles_5m, 20)
    f.realized_vol_5m = ind.realized_vol_pct(candles_5m, 30)
    f.rsi_5m = ind.rsi(candles_5m, 14)
    f.volume_zscore_5m = ind.volume_zscore(candles_5m, 20)
    f.atr_pct_1h = ind.atr_pct(candles_1h, 14)
    f.bbw_1h = ind.bollinger_band_width(candles_1h, 20)
    f.adx_1h = ind.adx(candles_1h, 14)
    closes_1h = [c["c"] for c in candles_1h]
    f.ema_slope_1h_pct = ind.ema_slope_pct(closes_1h, 20, 5)
    f.rsi_1h = ind.rsi(candles_1h, 14)
    return f


def _base_cfg():
    return {
        "symbol": "TESTUSDT",
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 10.0},
            {"sell_grid_pct": 4.0, "sell_qty_pct_of_base": 15.0},
            {"sell_grid_pct": 6.0, "sell_qty_pct_of_base": 20.0},
        ],
        "buy_grids": [
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 10.0},
            {"buy_grid_pct": 4.0, "buy_qty_pct_of_quote": 15.0},
            {"buy_grid_pct": 6.0, "buy_qty_pct_of_quote": 20.0},
        ],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
        "max_buy_levels": 3,
        "daily_loss_limit_usd": 50.0,
        "dynamic_mode": True,
    }


def _run_pipeline(features, base_cfg, prev_applied=None, prev_regime_state=None):
    regime_result = reg.classify(features, prev_regime_state)
    suggestion = se.suggest(
        features, regime_result, base_cfg, {"buy_levels_fired": 0, "max_buy_levels": 3}
    )
    suggestion = se.smooth_against_prev(suggestion, prev_applied, alpha=0.5)
    clamped = risk.apply_safety(suggestion, base_cfg, prev_applied)
    return regime_result, clamped


def _assert_invariants(clamped):
    a = clamped.to_dict()
    # 1. bounds
    assert (
        BOUNDS["base_alloc_pct"][0]
        <= a["base_alloc_pct"]
        <= BOUNDS["base_alloc_pct"][1]
    )
    assert (
        BOUNDS["trailing_pct"][0]
        <= a["sell_trigger_trailing_pct"]
        <= BOUNDS["trailing_pct"][1]
    )
    # 2. allocation sums to 100
    assert abs(a["base_alloc_pct"] + a["quote_alloc_pct"] - 100.0) < 1e-6
    # 3. grid triggers monotone increasing
    for grids, key in (
        (a["sell_grids"], "sell_grid_pct"),
        (a["buy_grids"], "buy_grid_pct"),
    ):
        vals = [g[key] for g in grids]
        assert vals == sorted(vals), f"{key} not monotone: {vals}"
        for v in vals:
            assert BOUNDS["grid_step_pct"][0] <= v <= BOUNDS["grid_step_pct"][1]
    # 4. anti-martingale on qty distribution
    for grids, key in (
        (a["sell_grids"], "sell_qty_pct_of_base"),
        (a["buy_grids"], "buy_qty_pct_of_quote"),
    ):
        for i in range(1, len(grids)):
            prev = grids[i - 1][key]
            if prev > 0:
                assert grids[i][key] / prev <= GRID_GROWTH_R_MAX + 1e-6


def test_pipeline_all_regimes_invariants_hold():
    base = _base_cfg()
    scenarios = {
        "ranging": (_ranging(), _ranging(100, 1000.0, 0.002)),
        "uptrend": (_uptrend(), _uptrend(100, 1000.0, 0.006)),
        "downtrend": (_downtrend(), _downtrend(100, 1000.0, 0.006)),
        "high_vol": (_high_vol(), _high_vol(100)),
    }
    for name, (k5, k1h) in scenarios.items():
        f = _features_from(k5, k1h, k5[-1]["c"])
        regime_result, clamped = _run_pipeline(f, base)
        _assert_invariants(clamped)


def test_defensive_regime_keeps_more_quote_than_bullish():
    base = _base_cfg()
    # Force regimes directly to isolate allocation logic
    f = MarketFeatures(symbol="T", price=1000.0, atr_pct_5m=1.0, data_fresh=True)
    up = se.suggest(
        f, reg.RegimeResult(reg.TRENDING_UP, reg.TRENDING_UP, 0.8, {}), base
    )
    down = se.suggest(
        f, reg.RegimeResult(reg.TRENDING_DOWN, reg.TRENDING_DOWN, 0.8, {}), base
    )
    dump = se.suggest(f, reg.RegimeResult(reg.DUMP_RISK, reg.DUMP_RISK, 0.9, {}), base)
    up_c = risk.apply_safety(up, base).to_dict()
    down_c = risk.apply_safety(down, base).to_dict()
    dump_c = risk.apply_safety(dump, base).to_dict()
    # Downtrend keeps more quote (cash) than uptrend; dump keeps the most.
    assert down_c["quote_alloc_pct"] > up_c["quote_alloc_pct"]
    assert dump_c["quote_alloc_pct"] >= down_c["quote_alloc_pct"]


def test_higher_vol_widens_grid_step():
    base = _base_cfg()
    low = MarketFeatures(symbol="T", price=1000.0, atr_pct_5m=0.3, data_fresh=True)
    high = MarketFeatures(symbol="T", price=1000.0, atr_pct_5m=3.0, data_fresh=True)
    rr = reg.RegimeResult(reg.LOW_VOL_RANGING, reg.LOW_VOL_RANGING, 0.7, {})
    low_c = risk.apply_safety(se.suggest(low, rr, base), base).to_dict()
    high_c = risk.apply_safety(se.suggest(high, rr, base), base).to_dict()
    # First buy grid step is wider under higher volatility
    assert (
        high_c["buy_grids"][0]["buy_grid_pct"] > low_c["buy_grids"][0]["buy_grid_pct"]
    )


def test_rate_limiter_prevents_violent_jumps_across_cycles():
    base = _base_cfg()
    calm = MarketFeatures(symbol="T", price=1000.0, atr_pct_5m=0.3, data_fresh=True)
    spike = MarketFeatures(symbol="T", price=1000.0, atr_pct_5m=5.0, data_fresh=True)
    rr = reg.RegimeResult(reg.HIGH_VOL_RANGING, reg.HIGH_VOL_RANGING, 0.7, {})
    c1 = risk.apply_safety(se.suggest(calm, rr, base), base).to_dict()
    # Next cycle: huge vol spike, but rate limiter caps the change vs c1
    c2 = risk.apply_safety(se.suggest(spike, rr, base), base, prev_applied=c1).to_dict()
    prev = c1["sell_trigger_trailing_pct"]
    cur = c2["sell_trigger_trailing_pct"]
    assert abs(cur - prev) <= risk.MAX_RELATIVE_CHANGE * prev + 1e-6


# ---------------------------------------------------------------------------
# Snapshot lifecycle: immutability within a cycle
# ---------------------------------------------------------------------------


def test_snapshot_immutable_within_cycle():
    state = {"cycle_id": 5, "bot_id": 1}
    # No snapshot yet → recompute needed
    assert cm.need_recompute(state) is True
    # After building one for cycle 5, no recompute until cycle changes
    state["dynamic_snapshot"] = {"cycle_id": 5}
    assert cm.need_recompute(state) is False
    # New cycle → recompute
    state["cycle_id"] = 6
    assert cm.need_recompute(state) is True


def test_snapshot_recompute_flag_forces_rebuild():
    state = {"cycle_id": 5, "dynamic_snapshot": {"cycle_id": 5}}
    assert cm.need_recompute(state) is False
    state["_dynamic_recompute_needed"] = True
    assert cm.need_recompute(state) is True
    # flag is consumed
    assert "_dynamic_recompute_needed" not in state


def test_build_snapshot_stale_falls_back(monkeypatch):
    """When features are stale, snapshot reuses prev applied and never crashes."""

    async def fake_collect(symbol, price):
        return MarketFeatures(
            symbol=symbol, price=price, data_fresh=False, error="no_5m_klines"
        )

    monkeypatch.setattr(cm, "collect_features", fake_collect)
    base = _base_cfg()
    prev_applied = {
        "base_alloc_pct": 40.0,
        "quote_alloc_pct": 60.0,
        "sell_grids": base["sell_grids"],
        "buy_grids": base["buy_grids"],
        "sell_trigger_trailing_pct": 0.5,
        "buy_trigger_trailing_pct": 0.5,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
    }
    state = {
        "cycle_id": 2,
        "bot_id": 1,
        "dynamic_snapshot": {
            "cycle_id": 1,
            "applied": prev_applied,
            "regime": "LOW_VOL_RANGING",
        },
    }
    snap = asyncio.get_event_loop().run_until_complete(
        cm.build_snapshot(state, base, 1000.0)
    )
    assert snap["data_fresh"] is False
    assert snap["applied"]["base_alloc_pct"] == 40.0  # reused prev
    assert "data_stale_fallback" in snap["fallbacks"]


def test_build_snapshot_fresh_full_path(monkeypatch):
    """End-to-end build with fresh synthetic features produces valid snapshot."""
    k5 = _ranging()
    k1h = _ranging(100, 1000.0, 0.002)

    async def fake_collect(symbol, price):
        return _features_from(k5, k1h, price)

    monkeypatch.setattr(cm, "collect_features", fake_collect)
    base = _base_cfg()
    state = {"cycle_id": 1, "bot_id": 1, "buy_grid_fired": []}
    snap = asyncio.get_event_loop().run_until_complete(
        cm.build_snapshot(state, base, 1000.0)
    )
    assert snap["data_fresh"] is True
    assert snap["regime"] in reg.ALL_REGIMES
    a = snap["applied"]
    assert abs(a["base_alloc_pct"] + a["quote_alloc_pct"] - 100.0) < 1e-6
    # grid count preserved (same shape as manual config)
    assert len(a["sell_grids"]) == len(base["sell_grids"])
    assert len(a["buy_grids"]) == len(base["buy_grids"])
    # reasons + history present for explainability
    assert snap["reasons"]
    assert snap["history"]
