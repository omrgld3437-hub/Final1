"""
Behaviour tests for live Dynamic Mode audit fixes that still apply after
legacy StrategyEngine / RiskEngine removal:

  P0.1 dynamic_mode string-bool parse
  P1.2 DUMP_RISK fast 5m drop
  P2.1 SQUEEZE 1h→5m fallback symmetry
  P2.2 BREAKOUT direction-aware (down → defensive)
  P2.3 features expose spread_bps
"""

from __future__ import annotations
import pytest

from app.botengine.dynamic import regime as reg
from app.botengine.dynamic import safety_gate as sg
from app.botengine.dynamic.features import MarketFeatures
from app.botengine.models import DcaGridTrailingConfig, config_from_ui_payload
from app.utils.parse_utils import parse_bool


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
    assert cfg.daily_loss_limit_usd == 0.0


def test_is_dynamic_mode_active_string_false():
    cfg = {"max_buy_levels": 3, "daily_loss_limit_usd": 25.0, "dynamic_mode": "false"}
    assert sg.is_dynamic_mode_active(cfg) is False


def _feat(**kw):
    base = dict(symbol="X", price=1000.0, atr_pct_5m=1.0, data_fresh=True)
    base.update(kw)
    return MarketFeatures(**base)


def test_dump_fast_drop_5m():
    f = _feat(ret_5m_last=-4.0)
    r = reg.classify(f, None)
    assert r.regime == reg.DUMP_RISK


def test_no_dump_on_small_drop():
    f = _feat(ret_5m_last=-1.0)
    r = reg.classify(f, None)
    assert r.regime != reg.DUMP_RISK


def test_downward_breakout_is_defensive_not_neutral():
    down = reg.classify(
        _feat(atr_pct_5m=2.0, bbw_1h=7.0, volume_zscore_5m=2.5, ema_slope_1h_pct=-1.0),
        None,
    )
    assert down.regime == reg.TRENDING_DOWN
    up = reg.classify(
        _feat(atr_pct_5m=2.0, bbw_1h=7.0, volume_zscore_5m=2.5, ema_slope_1h_pct=1.0),
        None,
    )
    assert up.regime == reg.BREAKOUT


def test_squeeze_falls_back_to_5m_bbw():
    f = _feat(atr_pct_5m=0.5, bbw_1h=None, bbw_5m=2.0)
    r = reg.classify(f, None)
    assert r.regime == reg.SQUEEZE


def test_features_expose_spread_bps():
    d = MarketFeatures(symbol="X", price=1.0, spread_pct=0.1, spread_bps=10.0).to_dict()
    assert "spread_bps" in d and d["spread_bps"] == 10.0
