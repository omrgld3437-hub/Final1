"""Dynamic overlay contract — cycle_manager snapshot/applied semantics."""

from __future__ import annotations

from types import SimpleNamespace

from app.botengine.dynamic.cycle_manager import (
    _OVERLAY_FIELDS,
    _no_trade_overlay,
    apply_overlay,
)
from app.botengine.models import DcaGridTrailingConfig
from app.services.dynamic_param_score.adapters import params_to_grid_config
from app.services.dynamic_param_score.models import BotParams, FinalAction


from tests.dynamic_param_score.factories import make_bot_params


def _params(**kw):
    return make_bot_params(**kw)


def test_deployable_overlay_carries_safety_fields():
    overlay = params_to_grid_config(_params(sell_grid_count=3, sell_qty_distribution=[0.34, 0.33, 0.33]))
    assert overlay["max_base_exposure_frac"] == 0.56
    assert len(overlay["buy_grids"]) == 2
    assert len(overlay["sell_grids"]) == 3

    cfg = DcaGridTrailingConfig({"symbol": "SOLUSDT", "initial_capital_usdt": 50})
    apply_overlay(cfg, {"applied": overlay})
    assert cfg.max_base_exposure_frac == 0.56
    assert len(cfg.buy_grids) == 2
    assert len(cfg.sell_grids) == 3


def test_sell_management_only_overlay_shape():
    overlay = params_to_grid_config(
        _params(
            buy_grid_count=0,
            sell_grid_count=3,
            buy_qty_distribution=[],
            sell_qty_distribution=[0.34, 0.33, 0.33],
        )
    )
    assert overlay["buy_grids"] == []
    assert len(overlay["sell_grids"]) == 3
    assert overlay["buy_trigger_trailing_pct"] == 0.0
    assert overlay["profit_reentry_drop_pct"] == 0.0
    assert overlay["max_buy_levels"] == 0


def test_wait_clears_old_buy_grids():
    cfg_dict = {
        "symbol": "SOLUSDT",
        "base_alloc_pct": 50,
        "quote_alloc_pct": 50,
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 25}] * 4,
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25}] * 2,
    }
    decision = SimpleNamespace(
        final_action=FinalAction.WAIT.value,
        deployable=False,
        params=None,
        blocking_reasons=["WAIT"],
    )
    applied = _no_trade_overlay(cfg_dict, decision)
    assert applied["buy_grids"] == [], (
        "NO_TRADE/WAIT fallback preserved old buy grids; bot could keep buying despite DPS wait."
    )
    assert applied.get("max_buy_levels", 0) == 0
    assert applied["profit_reentry_drop_pct"] == 0.0
    assert "dps_no_trade" in applied.get("fallbacks", [])


def test_no_trade_clears_all_grids():
    cfg_dict = {
        "symbol": "SOLUSDT",
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 25}] * 4,
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 25}] * 2,
    }
    decision = SimpleNamespace(
        final_action=FinalAction.NO_TRADE.value,
        deployable=False,
        params=None,
        blocking_reasons=["NO_TRADE"],
    )
    applied = _no_trade_overlay(cfg_dict, decision)
    assert applied["buy_grids"] == []
    assert applied["sell_grids"] == []


def test_sell_management_only_dynamic_snapshot_overlay():
    from app.services.dynamic_param_score.adapters import params_to_grid_config
    from tests.dynamic_param_score.factories import make_bot_params

    overlay = params_to_grid_config(
        make_bot_params(buy_grid_count=0, sell_grid_count=3, buy_qty_distribution=[], sell_qty_distribution=[0.34, 0.33, 0.33])
    )
    cfg = {"symbol": "SOLUSDT", "buy_grids": [{"buy_grid_pct": 1}] * 4}
    from app.botengine.models import DcaGridTrailingConfig
    from app.botengine.dynamic.cycle_manager import apply_overlay

    live = DcaGridTrailingConfig({"symbol": "SOLUSDT", "initial_capital_usdt": 50, **cfg})
    apply_overlay(live, {"applied": overlay})
    assert live.buy_grids == []
    assert len(live.sell_grids) == 3
    assert live.max_buy_levels == 0
    assert live.max_base_exposure_frac == 0.56

    cfg_dict = {"symbol": "SOLUSDT", "buy_grids": [{"buy_grid_pct": 1}] * 4}
    params = _params(buy_grid_count=0, sell_grid_count=3, buy_qty_distribution=[])
    decision = SimpleNamespace(
        final_action=FinalAction.WAIT.value,
        deployable=False,
        params=params,
        blocking_reasons=["bilateral"],
    )
    applied = _no_trade_overlay(cfg_dict, decision)
    assert applied["buy_grids"] == []
