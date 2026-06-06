"""
Unit tests: Cycle Ledger PnL (fee-aware, cycle-isolated).
- Ledger PnL: simple buy+sell+fee => net PnL correct.
- Breakeven formula: buy_fee + sell_fee verification.
- Profit-exit guard: trigger_price >= breakeven.
- Cycle type and base_delta from close_reason.
"""
import pytest
from app.botengine.cycle_ledger import (
    build_cycle_ledger_empty,
    cycle_ledger_add_fill,
    cycle_ledger_breakeven_price,
    cycle_ledger_trigger_price,
    get_cycle_type_and_base_delta,
    CYCLE_FILL_REASONS,
)


def test_cycle_ledger_empty():
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    assert led["cycle_id"] == 1
    assert led["symbol"] == "BTCUSDT"
    assert led["base_asset"] == "BTC"
    assert led["quote_asset"] == "USDT"
    assert led["fills"] == []
    assert led["buy_qty_total"] == 0.0
    assert led["sell_qty_total"] == 0.0
    assert led["realized_pnl_quote"] == 0.0


def test_cycle_ledger_pnl_buy_sell_fee():
    """NET realized_pnl_quote = sell_quote - buy_quote - total_fees."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(led, "2026-02-01T12:00:00Z", "oid1", "cid1", "BUY", 0.01, 100_000.0, 1.0, "USDT", "trail_buy_grid")
    cycle_ledger_add_fill(led, "2026-02-01T12:05:00Z", "oid2", "cid2", "SELL", 0.01, 101_000.0, 1.01, "USDT", "trail_profit_sell")
    # buy_quote = 1000, buy_fee = 1; sell_quote = 1010, sell_fee = 1.01
    # realized = 1010 - 1000 - (1 + 1.01) = 7.99
    assert led["buy_qty_total"] == 0.01
    assert led["buy_quote_total"] == 1000.0
    assert led["buy_fee_total_quote"] == 1.0
    assert led["sell_qty_total"] == 0.01
    assert led["sell_quote_total"] == 1010.0
    assert led["sell_fee_total_quote"] == 1.01
    assert abs(led["realized_pnl_quote"] - 7.99) < 1e-6
    assert led["matched_qty"] == 0.01
    assert led["avg_cost_quote_per_base"] == (1000.0 + 1.0) / 0.01  # 100100
    # Dual PnL: Cash (trail_buy_grid + trail_profit_sell) => cash_pnl_usdt
    assert "cash_pnl_usdt" in led
    assert abs(led["cash_pnl_usdt"] - 7.99) < 1e-4


def test_breakeven_price():
    """breakeven_price = avg_cost * (1 + buy_fee_rate) / (1 - sell_fee_rate)."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(led, "2026-02-01T12:00:00Z", "oid1", "cid1", "BUY", 1.0, 100.0, 0.1, "USDT", "trail_buy_grid")
    # avg_cost_quote_per_base = (100 + 0.1) / 1 = 100.1
    be = cycle_ledger_breakeven_price(led, buy_fee_rate=0.001, sell_fee_rate=0.001)
    assert be is not None
    # be = 100.1 * 1.001 / 0.999 ≈ 100.3003...
    assert be > 100.1
    assert be < 101.0


def test_trigger_price_above_breakeven():
    """trigger_price = breakeven_price * (1 + min_net_profit_rate)."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(led, "2026-02-01T12:00:00Z", "oid1", "cid1", "BUY", 1.0, 100.0, 0.0, "USDT", "trail_buy_grid")
    be = cycle_ledger_breakeven_price(led, 0.001, 0.001)
    trigger = cycle_ledger_trigger_price(led, min_net_profit_rate=0.001, buy_fee_rate=0.001, sell_fee_rate=0.001)
    assert trigger is not None
    assert trigger >= be
    assert trigger <= be * 1.01


def test_cycle_fill_reasons():
    assert "trail_buy_grid" in CYCLE_FILL_REASONS
    assert "trail_profit_sell" in CYCLE_FILL_REASONS
    assert "initial_allocation" not in CYCLE_FILL_REASONS


def test_cycle_type_profit_sell_is_long_scalp():
    """close_reason trail_profit_sell -> LONG_SCALP, base_delta=0."""
    cycle_type, base_delta = get_cycle_type_and_base_delta("trail_profit_sell", None)
    assert cycle_type == "LONG_SCALP"
    assert base_delta == 0.0
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(led, "2026-02-01T12:00:00Z", "o1", "c1", "BUY", 1.0, 100.0, 0.0, "USDT", "trail_buy_grid")
    cycle_ledger_add_fill(led, "2026-02-01T12:05:00Z", "o2", "c2", "SELL", 1.0, 101.0, 0.0, "USDT", "trail_profit_sell")
    cycle_type2, base_delta2 = get_cycle_type_and_base_delta("trail_profit_sell", led)
    assert cycle_type2 == "LONG_SCALP"
    assert base_delta2 == 0.0


def test_cycle_type_reentry_buy_is_inventory_rebalance():
    """close_reason trail_reentry_buy -> INVENTORY_REBALANCE, base_delta = buy_qty_total - sell_qty_total."""
    cycle_type, base_delta = get_cycle_type_and_base_delta("trail_reentry_buy", None)
    assert cycle_type == "INVENTORY_REBALANCE"
    assert base_delta == 0.0
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(led, "2026-02-01T12:00:00Z", "o1", "c1", "BUY", 1.02, 100.0, 0.0, "USDT", "trail_buy_grid")
    cycle_ledger_add_fill(led, "2026-02-01T12:01:00Z", "o2", "c2", "SELL", 1.0, 99.0, 0.0, "USDT", "trail_sell_grid")
    cycle_type2, base_delta2 = get_cycle_type_and_base_delta("trail_reentry_buy", led)
    assert cycle_type2 == "INVENTORY_REBALANCE"
    assert abs(base_delta2 - 0.02) < 1e-8  # 1.02 - 1.00 = 0.02


def test_target_budgets_equity_100_50_50():
    """equity=100, base_alloc=50%, quote_alloc=50% -> target_base_usdt=50, target_quote_usdt=50."""
    equity_usdt = 100.0
    quote_alloc = 0.5
    base_alloc = 0.5
    target_quote_usdt = round(equity_usdt * quote_alloc, 2)
    target_base_usdt = round(equity_usdt * base_alloc, 2)
    assert target_quote_usdt == 50.0
    assert target_base_usdt == 50.0


def test_cycle_end_consistency_profit_usdt_and_pnl_net():
    """
    CYCLE_END invariant: profit_usdt = cash_pnl_usdt (gross), pnl_usdt_net = realized_pnl_cycle_net.
    Cycle2 from task: BUY 5.263 @53.45, SELL 5.084 @55.34 fee 0.28134856.
    cash_pnl_usdt = sell_quote - buy_quote ≈ 0.0412, realized_pnl_cycle_net ≈ -0.2401.
    """
    led = build_cycle_ledger_empty(2, "ETHUSDT")
    cycle_ledger_add_fill(
        led, "2026-02-17T15:37:25Z", "o1", "c1", "BUY", 5.263, 53.45, 0.0, "USDT", "trail_reentry_buy"
    )
    cycle_ledger_add_fill(
        led, "2026-02-17T16:45:53Z", "o2", "c2", "SELL", 5.084, 55.34, 0.28134856, "USDT", "trail_profit_sell"
    )
    # Canonical totals from recompute
    cash_pnl = float(led.get("cash_pnl_usdt") or 0)
    fees = float(led.get("cash_fees_usdt") or 0)
    realized_net = float(led.get("realized_pnl_quote") or 0)
    assert abs(cash_pnl - (5.084 * 55.34 - 5.263 * 53.45)) < 0.001  # ~0.0412
    assert abs(realized_net - (cash_pnl - fees)) < 1e-6
    assert abs(realized_net - (-0.2401)) < 0.01
    assert abs(cash_pnl - 0.0412) < 0.01
    # Cycle_end payload must use these: profit_usdt == cash_pnl, pnl_usdt_net == realized_net
    profit_usdt = round(cash_pnl, 2)
    pnl_usdt_net = round(realized_net, 4)
    assert profit_usdt != 0
    assert abs(pnl_usdt_net - (-0.2401)) < 0.001
