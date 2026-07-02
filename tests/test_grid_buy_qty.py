"""Grid alım miktarı: quote payının grid yüzdesi kadar kullanılmalı (tüm equity değil)."""

from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import _buy_qty_for_grid


def _cfg():
    return DcaGridTrailingConfig(
        {
            "initial_capital_usdt": 55,
            "quote_alloc_pct": 50,
            "base_alloc_pct": 50,
            "buy_grids": [
                {"trigger_pct": 1, "qty_pct": 50, "trail_pct": 0.5},
                {"trigger_pct": 2, "qty_pct": 50, "trail_pct": 0.5},
            ],
            "sell_grids": [],
        }
    )


def test_buy_qty_uses_quote_allocation_not_total_equity():
    """55$ bütçe, 50/50 dağılım → grid #1 alımı ~13.75$ (quote payının %50'si)."""
    state = {
        "grid_reference_quote": 55.0,  # eski hatalı heal (equity)
        "cycle_start_equity": 55.0,
        "target_budgets": {
            "equity_usdt": 55.0,
            "target_quote_usdt": 27.5,
            "target_base_usdt": 27.5,
        },
    }
    cfg = _cfg()
    quote_bal = 27.5
    qty = _buy_qty_for_grid(state, cfg, 0, quote_bal)
    assert 13.0 <= qty <= 14.0, f"expected ~13.75, got {qty}"


def test_buy_qty_derives_from_equity_when_no_target_budgets():
    state = {
        "grid_reference_quote": 55.0,
        "cycle_start_equity": 55.0,
    }
    cfg = _cfg()
    qty = _buy_qty_for_grid(state, cfg, 0, 27.5)
    assert 13.0 <= qty <= 14.0, f"expected ~13.75, got {qty}"


def test_second_grid_gets_remaining_quote_slice():
    state = {
        "cycle_start_equity": 55.0,
        "target_budgets": {"target_quote_usdt": 27.5},
    }
    cfg = _cfg()
    qty = _buy_qty_for_grid(state, cfg, 1, 13.7)
    assert 6.5 <= qty <= 13.7, f"expected up to ~13.7, got {qty}"
