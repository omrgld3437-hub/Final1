"""Grid notional preflight validation."""
from app.botengine.config_validate import (
    MIN_GRID_NOTIONAL_USDT,
    compute_min_budget_usdt,
    validate_dca_grid_notionals,
    validate_dca_payload,
)
from app.botengine.models import DcaGridTrailingConfig


def _cfg(budget, base_pct=50, quote_pct=50, sell_grids=None, buy_grids=None):
    return DcaGridTrailingConfig({
        "symbol": "ETHUSDT",
        "initial_capital_usdt": budget,
        "base_alloc_pct": base_pct,
        "quote_alloc_pct": quote_pct,
        "sell_grids": sell_grids or [],
        "buy_grids": buy_grids or [],
        "min_notional_guard": 5.0,
    })


def test_50_usd_three_equal_sell_grids_rejected():
    cfg = _cfg(50, sell_grids=[
        {"sell_grid_pct": 1, "sell_qty_pct_of_base": 33.33},
        {"sell_grid_pct": 2, "sell_qty_pct_of_base": 33.33},
        {"sell_grid_pct": 3, "sell_qty_pct_of_base": 33.34},
    ])
    ok, msg, viol, min_b = validate_dca_grid_notionals(cfg)
    assert not ok
    assert len(viol) == 3
    assert min_b is not None and min_b > 50
    assert "minimum bütçe" in msg
    assert MIN_GRID_NOTIONAL_USDT == 10.0


def test_mixed_grids_only_small_ones_fail():
    cfg = _cfg(50, sell_grids=[
        {"sell_qty_pct_of_base": 60},
        {"sell_qty_pct_of_base": 40},
    ], buy_grids=[
        {"buy_qty_pct_of_quote": 80},
        {"buy_qty_pct_of_quote": 20},
    ])
    ok, msg, viol, min_b = validate_dca_grid_notionals(cfg)
    assert not ok
    sides = {(v["side"], v["index"]) for v in viol}
    assert ("sell", 1) in sides
    assert ("buy", 1) in sides
    assert min_b is not None and min_b >= 50.26


def test_all_grids_above_min_passes():
    cfg = _cfg(100, sell_grids=[{"sell_qty_pct_of_base": 50}], buy_grids=[{"buy_qty_pct_of_quote": 50}])
    ok, msg, viol, min_b = validate_dca_grid_notionals(cfg)
    assert ok
    assert not viol
    assert min_b is None


def test_compute_min_budget_20_usd_40pct_sell():
    cfg = _cfg(20, sell_grids=[{"sell_qty_pct_of_base": 40}], buy_grids=[{"buy_qty_pct_of_quote": 40}])
    min_b = compute_min_budget_usdt(cfg)
    assert min_b is not None and min_b >= 50.26
    ok, msg, viol, _ = validate_dca_grid_notionals(cfg)
    assert not ok
    assert "50." in msg or "51." in msg


def test_validate_dca_payload_ui_shape():
    ok, msg, viol, min_b = validate_dca_payload({
        "symbol": "ETHUSDT",
        "budget_usd": 20,
        "allocation": {"base_pct": 50, "quote_pct": 50},
        "up": {"grids": [{"trigger_pct": 1, "qty_pct": 40}, {"trigger_pct": 2, "qty_pct": 60}]},
        "down": {"grids": [{"trigger_pct": 1, "qty_pct": 40}]},
        "max_buy_levels": 1,
    })
    assert not ok
    assert viol
    assert min_b is not None
