from __future__ import annotations

from app.services.bot_performance_service import _cycle_ledger_amounts


def test_inventory_cycle_pnl_uses_locked_close_price(monkeypatch):
    def fail_if_market_price_used(symbol):
        raise AssertionError("completed inventory PnL must not drift with live market price")

    monkeypatch.setattr("app.services.market_data.get_price", fail_if_market_price_used)

    pnl_usd, fees_usd = _cycle_ledger_amounts(
        {
            "cycle_type": "INVENTORY",
            "completed_reason": "trail_reentry_buy",
            "inventory_coin_adv_qty": 0.0061,
            "inventory_fees_usdt": 0.02,
            "close_price_quote_per_base": 1986.5,
        },
        symbol="ETHUSDT",
    )

    assert round(pnl_usd, 8) == round(0.0061 * 1986.5, 8)
    assert fees_usd == 0.02
