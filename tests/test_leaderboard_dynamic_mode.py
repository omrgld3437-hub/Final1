"""Leaderboard dynamic_mode public block."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.leaderboard_service import (
    _cfg_dynamic_enabled,
    _public_dynamic_mode_for_leaderboard,
)


def test_public_dynamic_mode_disabled():
    out = _public_dynamic_mode_for_leaderboard(MagicMock(), 1, 1, json.dumps({}))
    assert out == {"enabled": False, "active": False}


def test_cfg_dynamic_enabled_accepts_string_true():
    assert _cfg_dynamic_enabled({"dynamic_mode": "true"}) is True
    assert _cfg_dynamic_enabled({"dynamic_mode": "false"}) is False


@patch("app.botengine.state_store.load_state")
@patch("app.botengine.dynamic.safety_gate.is_dynamic_mode_active", return_value=True)
@patch("app.botengine.dynamic.safety_gate.check_prerequisites")
def test_public_dynamic_mode_active_with_snapshot(mock_gate, _mock_active, mock_load):
    mock_gate.return_value.ok = True
    mock_load.return_value = {
        "dynamic_snapshot": {
            "cycle_id": 2,
            "regime": "TRENDING_UP",
            "data_fresh": True,
            "applied": {
                "base_alloc_pct": 55.0,
                "quote_alloc_pct": 45.0,
                "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 10.0}],
                "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0}],
            },
            "features": {"atr_pct_5m": 0.5, "adx_1h": 22.0},
        },
        "buy_grid_fired": [True, False],
        "sell_grid_fired": [False],
        "initial_allocation_done": True,
    }
    cfg = {
        "dynamic_mode": True,
        "max_buy_levels": 3,
    }
    out = _public_dynamic_mode_for_leaderboard(MagicMock(), 9, 1, json.dumps(cfg))
    assert out["enabled"] is True
    assert out["active"] is True
    assert out["snapshot"]["regime"] == "TRENDING_UP"
    assert out["position"]["buy_levels_fired"] == 1
    assert out["position"]["base_alloc_pct"] == 55.0
