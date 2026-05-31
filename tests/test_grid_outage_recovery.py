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


def test_buy_grid_not_reset_when_price_between_trigger_and_exec():
    """Dip olmadan gerçekleşme tetik üstünde — fiyat ikisi arasındayken tetik silinmez."""
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[99.0],
    )
    # exec = 99 * 1.003 = 99.297; P=99.15 tetik ile gerçekleşme arası
    apply_grid_outage_recovery(st, cfg, 99.15, gap_sec=60.0)
    assert st["buy_grid_trigger_price"][0] == pytest.approx(99.0)
    assert st.get("_outage_favorable_buy") == []


def test_buy_grid_favorable_when_price_rallied_past_exec():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
    )
    apply_grid_outage_recovery(st, cfg, 100.0, gap_sec=60.0)
    assert st["buy_grid_trigger_price"][0] == pytest.approx(99.0)
    assert 0 in st.get("_outage_favorable_buy", [])


def test_sell_grid_not_reset_when_price_between_exec_and_trigger():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[101.0],
    )
    # exec = 101 * 0.997 = 100.697; P=100.8 tetik altında ama gerçekleşme üstünde
    apply_grid_outage_recovery(st, cfg, 100.8, gap_sec=60.0)
    assert st["sell_grid_trigger_price"][0] == pytest.approx(101.0)
    assert st.get("_outage_favorable_sell") == []



def test_sell_favorable_when_price_below_trigger_but_at_exec():
    """Tepe tetik üstünde; fiyat tetik altında ama gerçekleşme eşiğinde — satış işlenmeli."""
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    # exec = 102 * 0.997 = 101.694; P=101.3 tetik altı, gerçekleşme altı
    apply_grid_outage_recovery(st, cfg, 101.3, gap_sec=60.0)
    assert st["sell_grid_trigger_price"][0] == pytest.approx(101.0)
    assert 0 in st.get("_outage_favorable_sell", [])


def test_sell_grid_favorable_when_price_at_exec():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    # exec = 102 * 0.997 = 101.694; P=101.5 <= exec → favorable
    apply_grid_outage_recovery(st, cfg, 101.5, gap_sec=60.0)
    assert 0 in st.get("_outage_favorable_sell", [])


def test_sell_grid_stays_armed_at_new_peak():
    cfg = _cfg()
    st = _state_with_gap(
        sell_grid_trigger_price=[101.0],
        sell_grid_peak_price=[102.0],
    )
    apply_grid_outage_recovery(st, cfg, 102.0, gap_sec=60.0)
    assert st["sell_grid_trigger_price"][0] == pytest.approx(101.0)
    assert st.get("_outage_favorable_sell") == []


def test_buy_favorable_when_price_below_execution():
    cfg = _cfg()
    st = _state_with_gap(
        buy_grid_trigger_price=[99.0],
        buy_grid_trough_price=[98.0],
    )
    # exec = 98 * 1.003 = 98.294; P=98.1 < exec → favorable
    apply_grid_outage_recovery(st, cfg, 98.1, gap_sec=60.0)
    assert 0 in st.get("_outage_favorable_buy", [])



def test_buy_favorable_when_price_below_execution():
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


def test_flush_outage_recovery_emits_connectivity_stable(monkeypatch):
    from app.botengine.strategies.grid_outage_recovery import flush_outage_recovery_log_to_events

    appended = []

    def fake_append(db, bot_id, account_id, typ, msg, meta):
        appended.append((typ, msg, meta))

    flush_calls = []

    def fake_flush(db, bot_id, **kw):
        flush_calls.append(bot_id)
        return True

    def fake_mark(db, bot, state, **kw):
        state["_pending_connectivity_stable"] = True

    monkeypatch.setattr(
        "app.botengine.state_store.append_event",
        fake_append,
    )

    import app.services.binance_connectivity as bc

    monkeypatch.setattr(bc, "flush_pending_connectivity_stable", fake_flush)
    monkeypatch.setattr(bc, "mark_pending_connectivity_stable", fake_mark)

    class FakeBot:
        id = 7
        account_id = 3
        status = "running"

    class FakeQ:
        def filter(self, *a):
            return self

        def first(self):
            return FakeBot()

    class FakeDb:
        def query(self, *a):
            return FakeQ()

    state = {
        "_outage_recovery_log": {
            "message": "Kopma sonrası grid değerlendirmesi",
            "meta": {"health_code": "OUTAGE_RECOVERY", "gap_sec": 36.0},
        },
        "_pending_connectivity_stable": False,
    }
    flush_outage_recovery_log_to_events(FakeDb(), 7, 3, state)
    assert len(appended) == 1
    assert appended[0][0] == "INFO"
    assert flush_calls == [7]
    assert "_outage_recovery_log" not in state
    assert "_pending_connectivity_stable" not in state
