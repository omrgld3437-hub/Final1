"""Live execution exposure cap parity with DPS overlay."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.botengine.dynamic.cycle_manager import _OVERLAY_FIELDS, apply_overlay
from app.botengine.models import DcaGridTrailingConfig
from app.services.dynamic_param_score.adapters import params_to_grid_config
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.feasibility import allowed_buy_quote_usdt
from app.services.dynamic_param_score.models import BotParams
from tests.dynamic_param_score.factories import make_portfolio_state


from tests.dynamic_param_score.factories import make_bot_params


def _sample_params(**kw):
    return make_bot_params(**kw)


def test_exposure_cap_allowed_below_min_notional():
    pf = make_portfolio_state(budget_usdt=50, base_exposure_frac=0.54, price=100)
    allowed = allowed_buy_quote_usdt(pf, max_base_exposure_frac=0.56, current_price=100)
    assert allowed < 5.0
    assert allowed <= 1.0 + 0.01


def test_exposure_cap_clamps_requested_quote():
    pf = make_portfolio_state(budget_usdt=100, base_exposure_frac=0.50, price=100)
    allowed = allowed_buy_quote_usdt(pf, max_base_exposure_frac=0.56, current_price=100)
    requested = 20.0
    capped = min(requested, allowed)
    assert capped <= 8.0 + 0.01
    assert capped >= 5.0 or capped == 0.0


def test_max_base_exposure_frac_in_overlay_fields():
    assert "max_base_exposure_frac" in _OVERLAY_FIELDS
    assert "max_buy_levels" in _OVERLAY_FIELDS
    assert "min_net_profit_rate" in _OVERLAY_FIELDS


def test_dps_overlay_reaches_live_config():
    params = _sample_params(max_base_exposure_frac=0.56, buy_grid_count=2)
    overlay = params_to_grid_config(params)
    assert overlay.get("max_base_exposure_frac") == 0.56
    assert overlay.get("max_buy_levels") == 2

    cfg = DcaGridTrailingConfig(
        {
            "symbol": "SOLUSDT",
            "initial_capital_usdt": 50,
            "base_alloc_pct": 50,
            "quote_alloc_pct": 50,
            "sell_grids": [],
            "buy_grids": [],
        }
    )
    assert getattr(cfg, "max_base_exposure_frac", 1.0) == 1.0
    snapshot = {"applied": overlay}
    diffs = apply_overlay(cfg, snapshot)
    assert getattr(cfg, "max_base_exposure_frac") == 0.56
    assert diffs.get("max_base_exposure_frac") == {"old": 1.0, "new": 0.56}
    assert cfg.max_buy_levels == 2


def test_engine_decision_to_overlay_includes_safety_fields():
    engine = DynamicParamScoreEngine()
    params = _sample_params()
    overlay = params_to_grid_config(params)
    assert overlay["max_base_exposure_frac"] == 0.56
    assert overlay["max_buy_levels"] == 2
    assert "min_net_profit_rate" in overlay
