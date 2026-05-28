"""Grid outage recovery — bağlantı kopması sonrası tetik/tepe-dip davranışı."""
from datetime import datetime, timedelta, timezone

import pytest

from app.botengine.models import DcaGridTrailingConfig, BotEngineMode
from app.botengine.strategies.grid_outage_recovery import (
    apply_grid_outage_recovery,
    gap_threshold_sec,
    should_apply_outage_recovery,
)
from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing


def _cfg(**kw):
    base = {
        "symbol": "ETHUSDT",
        "initial_capital_usdt": 100.0,
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 10.0}],
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0}],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "tick_interval_ms": 2000,
    }
    base.update(kw)
    return DcaGridTrailingConfig(base)


def _state_with_gap(**extra):
    st = {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "reference_price": 100.0,
        "grid_reference_base": 1.0,
        "grid_reference_quote": 50.0,
        "base_balance": 1.0,
        "quote_balance": 50.0,
        "sell_grid_fired": [False],
        "buy_grid_fired": [False],
        "sell_grid_trigger_price": [None],
        "buy_grid_trigger_price": [None],
        "sell_grid_peak_price": [None],
        "buy_grid_trough_price": [None],
        "sell_history": [],
        "buy_history": [],
        "last_tick_at": datetime.now(timezone.utc) - timedelta(seconds=120),
    }
    st.update(extra)
    return st


def test_gap_detection_respects_threshold():
    cfg = _cfg()
    st = _state_with_gap()
    ok, gap = should_apply_outage_recovery(st, cfg)
    assert ok is True
    assert gap is not None and gap >= gap_threshold_sec(cfg)


def test_gray_zone_no_trigger_unchanged():
    cfg = _cfg()
    st = _state_with_gap()
    apply_grid_outage_recovery(st, cfg, 100.5, gap_sec=60.0)
    assert st["sell_grid_trigger_price"][0] is None
    assert st["buy_grid_trigger_price"][0] is None
    assert st.get("_outage_favorable_buy") == []
    assert st.get("_outage_favorable_sell") == []


def test_buy_grid_reset_when_price_above_trigger():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
    )
    apply_grid_outage_recovery(st, cfg, 100.0, gap_sec=60.0)
    assert st["buy_grid_trigger_price"][0] is None
    assert st["buy_grid_trough_price"][0] is None


def test_sell_grid_reset_when_price_below_trigger():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    apply_grid_outage_recovery(st, cfg, 100.0, gap_sec=60.0)
    assert st["sell_grid_trigger_price"][0] is None
    assert st["sell_grid_peak_price"][0] is None


def test_buy_favorable_when_price_below_execution():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
    )
    # exec = 98 * 1.003 = 98.294; P=98.1 < exec → favorable
    apply_grid_outage_recovery(st, cfg, 98.1, gap_sec=60.0)
    assert 0 in st.get("_outage_favorable_buy", [])


def test_sell_favorable_when_price_above_execution():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    # exec = 102 * 0.997 = 101.694; P=102 > exec → favorable
    apply_grid_outage_recovery(st, cfg, 102.0, gap_sec=60.0)
    assert 0 in st.get("_outage_favorable_sell", [])


def test_waiting_buy_grid_triggers_offline():
    cfg = _cfg()
    st = _state_with_gap()
    apply_grid_outage_recovery(st, cfg, 98.0, gap_sec=60.0)
    assert st["buy_grid_trigger_price"][0] == pytest.approx(99.0)


def test_buy_reanchor_does_not_raise_trough():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
    )
    # exec = 98 * 1.003 = 98.294; P=98.5 in [exec, trigger] — eski kod trough=P yapardı
    apply_grid_outage_recovery(st, cfg, 98.5, gap_sec=60.0)
    assert st["buy_grid_trough_price"][0] == pytest.approx(98.0)


def test_sell_reanchor_does_not_lower_peak():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    # exec = 102 * 0.997 = 101.694; P=101.8 in [trigger, exec] — eski kod peak=P yapardı
    apply_grid_outage_recovery(st, cfg, 101.8, gap_sec=60.0)
    assert st["sell_grid_peak_price"][0] == pytest.approx(102.0)


def test_tick_executes_favorable_buy_after_outage():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
        last_tick_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    actions, _ = tick_dca_grid_trailing(st, cfg, 98.1, 1.0, 50.0)
    assert any(a.get("reason") == "trail_buy_grid" for a in actions)


def test_profit_exit_force_on_new_high_after_gap():
    cfg = _cfg(
        sell_grids=[],
        buy_grids=[{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0}],
        profit_exit_drop_pct=0.3,
    )
    st = _state_with_gap(
        mode=BotEngineMode.TRAIL_PROFIT_SELL.value,
        trail_anchor_price=100.0,
        _profit_exit_breakeven=99.0,
        buy_history=[{"qty": 0.01, "price": 99.5}],
        buy_grid_fired=[True],
    )
    apply_grid_outage_recovery(st, cfg, 105.0, gap_sec=120.0)
    assert st.get("_outage_force_profit_sell") is True
