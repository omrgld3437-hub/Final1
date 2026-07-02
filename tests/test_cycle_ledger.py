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
    heal_cycle_opened_at,
    resolve_cycle_opened_at_for_cycle,
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


def test_cycle_opened_at_uses_latest_duplicate_open_trade_row():
    """Aynı tur için eski kalıntı varsa açık tur süresi son cycle_open_trades satırından başlar."""
    state = {
        "cycle_id": 6,
        "initial_allocation_done": True,
        "cycle_opened_at": "2026-06-02T02:09:00+00:00",
        "cycle_ledger_current": {
            "cycle_id": 6,
            "started_at": "2026-06-02T02:09:00+00:00",
        },
        "cycle_open_trades": [
            {
                "cycle_id": 6,
                "ts": "2026-06-02T02:09:00+00:00",
                "qty": 0.0061,
                "price": 1987.0,
            },
            {
                "cycle_id": 6,
                "ts": "2026-06-02T09:33:07+00:00",
                "qty": 0.0061,
                "price": 1987.0,
            },
        ],
    }

    heal_cycle_opened_at(state)

    assert state["cycle_opened_at"] == "2026-06-02T09:33:07+00:00"
    assert resolve_cycle_opened_at_for_cycle(state, 6) == "2026-06-02T09:33:07+00:00"


def test_cycle_ledger_pnl_buy_sell_fee():
    """NET realized_pnl_quote = sell_quote - buy_quote - total_fees."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "oid1",
        "cid1",
        "BUY",
        0.01,
        100_000.0,
        1.0,
        "USDT",
        "trail_buy_grid",
    )
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:05:00Z",
        "oid2",
        "cid2",
        "SELL",
        0.01,
        101_000.0,
        1.01,
        "USDT",
        "trail_profit_sell",
    )
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
    # Cycle-end invariant: cash_pnl_usdt is gross; realized_pnl_quote is net after fees.
    assert "cash_pnl_usdt" in led
    assert abs(led["cash_pnl_usdt"] - 10.0) < 1e-4
    assert abs(led["cash_fifo_pnl_usdt"] - 7.99) < 1e-4


def test_breakeven_price():
    """breakeven_price = avg_cost * (1 + buy_fee_rate) / (1 - sell_fee_rate)."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "oid1",
        "cid1",
        "BUY",
        1.0,
        100.0,
        0.1,
        "USDT",
        "trail_buy_grid",
    )
    # avg_cost_quote_per_base = (100 + 0.1) / 1 = 100.1
    be = cycle_ledger_breakeven_price(led, buy_fee_rate=0.001, sell_fee_rate=0.001)
    assert be is not None
    # be = 100.1 * 1.001 / 0.999 ≈ 100.3003...
    assert be > 100.1
    assert be < 101.0


def test_trigger_price_uses_profit_rise_pct():
    """UI Kar satış tetik % must dominate min_net_profit_rate when higher."""
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "oid1",
        "cid1",
        "BUY",
        1.0,
        100.0,
        0.0,
        "USDT",
        "trail_buy_grid",
    )
    be = cycle_ledger_breakeven_price(led, 0.001, 0.001)
    trigger_low = cycle_ledger_trigger_price(
        led, min_net_profit_rate=0.001, profit_rise_pct=0.0
    )
    trigger_1pct = cycle_ledger_trigger_price(
        led, min_net_profit_rate=0.001, profit_rise_pct=1.0
    )
    assert trigger_1pct is not None and trigger_low is not None
    assert trigger_1pct > trigger_low
    assert abs(trigger_1pct - be * 1.01) < 0.01


def test_cycle_ledger_with_total_basis_includes_initial():
    """basis_mode=total merges initial_allocation into profit-exit cost basis."""
    from app.botengine.cycle_ledger import cycle_ledger_with_basis

    led = build_cycle_ledger_empty(1, "ETHUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "o1",
        "c1",
        "BUY",
        0.0039,
        2039.69,
        0.0,
        "USDT",
        "trail_buy_grid",
    )
    state = {
        "initial_allocation_done": True,
        "initial_alloc_base_qty": 0.0048,
        "initial_alloc_price": 2067.63,
    }
    merged = cycle_ledger_with_basis(state, led, "total")
    expected_avg = (0.0039 * 2039.69 + 0.0048 * 2067.63) / (0.0039 + 0.0048)
    assert abs(merged["avg_cost_quote_per_base"] - expected_avg) < 0.01
    grid_only = cycle_ledger_with_basis(state, led, "grid_only")
    assert abs(grid_only["avg_cost_quote_per_base"] - 2039.69) < 0.01


def test_cycle_ledger_with_total_basis_includes_initial_alloc_fee():
    """basis_mode=total: initial_alloc_fee_quote dahil edilmeli; fee eksikse avg_cost düşük kalır (breakeven hatalı)."""
    from app.botengine.cycle_ledger import cycle_ledger_with_basis

    # Grid: 0.005 ETH @ 1900, fee = 0.95 USDT
    led = build_cycle_ledger_empty(1, "ETHUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "o1",
        "c1",
        "BUY",
        0.005,
        1900.0,
        0.95,
        "USDT",
        "trail_buy_grid",
    )

    # Initial alloc: 0.01 ETH @ 2000, fee = 2.0 USDT
    state_with_fee = {
        "initial_allocation_done": True,
        "initial_alloc_base_qty": 0.01,
        "initial_alloc_price": 2000.0,
        "initial_alloc_fee_quote": 2.0,
    }
    state_no_fee = {
        "initial_allocation_done": True,
        "initial_alloc_base_qty": 0.01,
        "initial_alloc_price": 2000.0,
        # initial_alloc_fee_quote eksik → geriye dönük uyumluluk: 0 kabul edilir
    }

    merged_fee = cycle_ledger_with_basis(state_with_fee, led, "total")
    merged_no_fee = cycle_ledger_with_basis(state_no_fee, led, "total")

    total_qty = 0.005 + 0.01  # 0.015
    total_quote = 0.005 * 1900.0 + 0.01 * 2000.0  # 9.5 + 20 = 29.5
    total_fee_with = 0.95 + 2.0  # 2.95
    total_fee_without = 0.95  # 0.95

    expected_with_fee = (total_quote + total_fee_with) / total_qty  # ~2196.67
    expected_no_fee = (total_quote + total_fee_without) / total_qty  # ~2030.0

    assert abs(merged_fee["avg_cost_quote_per_base"] - expected_with_fee) < 0.01, (
        f"fee dahil avg_cost yanlış: {merged_fee['avg_cost_quote_per_base']:.4f} != {expected_with_fee:.4f}"
    )
    assert abs(merged_no_fee["avg_cost_quote_per_base"] - expected_no_fee) < 0.01, (
        f"fee eksik avg_cost yanlış: {merged_no_fee['avg_cost_quote_per_base']:.4f} != {expected_no_fee:.4f}"
    )
    # fee dahil breakeven mutlaka fee eksikten büyük olmalı
    assert (
        merged_fee["avg_cost_quote_per_base"] > merged_no_fee["avg_cost_quote_per_base"]
    )


def test_reentry_arm_and_max_buy_price():
    """Reentry arms at avg_sell*(1-drop); max buy is fee-aware below avg sell."""
    from app.botengine.cycle_ledger import (
        cycle_ledger_reentry_arm_price,
        cycle_ledger_reentry_max_buy_price,
    )

    led = build_cycle_ledger_empty(1, "ETHUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "o1",
        "c1",
        "SELL",
        0.004,
        2050.0,
        0.0,
        "USDT",
        "trail_sell_grid",
    )
    arm = cycle_ledger_reentry_arm_price(led, drop_pct=1.0)
    max_buy = cycle_ledger_reentry_max_buy_price(led, 0.001, 0.001)
    assert arm is not None and abs(arm - 2050.0 * 0.99) < 0.01
    assert max_buy is not None and max_buy < 2050.0


def test_reentry_does_not_buy_above_sell_basis():
    """After dip, rally above avg sell must not execute trail_reentry_buy."""
    from app.botengine.models import DcaGridTrailingConfig
    from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing

    cfg = DcaGridTrailingConfig(
        {
            "symbol": "ETHUSDT",
            "profit_reentry_drop_pct": 1.0,
            "profit_reentry_rise_pct": 0.3,
            "pnl_mode": "cycle_only_fee_aware_v1",
        }
    )
    state = {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "reference_price": 2050.0,
        "sell_history": [
            {"qty": 0.004, "price": 2050.0, "execution_price": 2050.0, "grid_index": 0}
        ],
        "buy_history": [],
        "cycle_ledger_current": {
            "cycle_id": 1,
            "symbol": "ETHUSDT",
            "fills": [
                {
                    "side": "SELL",
                    "qty": 0.004,
                    "price": 2050.0,
                    "fee": 0,
                    "reason": "trail_sell_grid",
                }
            ],
            "buy_qty_total": 0.0,
            "buy_quote_total": 0.0,
            "sell_qty_total": 0.004,
            "sell_quote_total": 0.004 * 2050.0,
        },
    }
    # Arm on dip
    actions_arm, _ = tick_dca_grid_trailing(state, cfg, 2029.0, 0.0, 8.2)
    assert state.get("mode") == "TRAIL_REENTRY_BUY"
    assert not actions_arm
    # Rally above avg sell — must not buy
    actions_buy, _ = tick_dca_grid_trailing(state, cfg, 2060.0, 0.0, 8.2)
    assert not any(a.get("reason") == "trail_reentry_buy" for a in actions_buy)


def test_profit_exit_does_not_sell_below_breakeven_after_trail():
    """Reproduce bot-1 cycle: grid buy then crash must not trail-sell at a loss."""
    from app.botengine.models import DcaGridTrailingConfig
    from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing

    cfg = DcaGridTrailingConfig(
        {
            "symbol": "ETHUSDT",
            "initial_capital_usdt": 20.0,
            "base_alloc_pct": 50.0,
            "quote_alloc_pct": 50.0,
            "sell_grids": [],
            "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 40.0}],
            "profit_exit_rise_pct": 1.0,
            "profit_exit_drop_pct": 0.3,
            "pnl_mode": "cycle_only_fee_aware_v1",
            "basis_mode": "grid_only",
        }
    )
    state = {
        "bot_id": 1,
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "initial_alloc_base_qty": 0.0048,
        "initial_alloc_price": 2067.63,
        "reference_price": 2039.45,
        "grid_reference_base": 0.0048,
        "grid_reference_quote": 10.0,
        "buy_history": [{"qty": 0.0039, "price": 2039.69}],
        "sell_history": [],
        "buy_grid_fired": [True],
        "sell_grid_fired": [],
        "cycle_ledger_current": {
            "cycle_id": 1,
            "symbol": "ETHUSDT",
            "fills": [
                {
                    "side": "BUY",
                    "qty": 0.0039,
                    "price": 2039.69,
                    "fee": 0,
                    "reason": "trail_buy_grid",
                }
            ],
            "buy_qty_total": 0.0039,
            "buy_quote_total": 0.0039 * 2039.69,
            "buy_fee_total_quote": 0.0,
            "sell_qty_total": 0.0,
            "sell_quote_total": 0.0,
            "sell_fee_total_quote": 0.0,
            "avg_cost_quote_per_base": 2039.69,
        },
    }
    # Brief spike arms trailing (~2065) then crash to 2039 — must not sell at loss
    actions_arm, _ = tick_dca_grid_trailing(state, cfg, 2065.0, 0.0087, 5.0)
    assert state.get("mode") == "TRAIL_PROFIT_SELL"
    assert not actions_arm
    actions_sell, _ = tick_dca_grid_trailing(state, cfg, 2039.45, 0.0087, 5.0)
    assert not any(a.get("reason") == "trail_profit_sell" for a in actions_sell)


def test_parallel_sell_grids_trigger_independently():
    """Grid #2 must arm while grid #1 is still trailing (not fired)."""
    from app.botengine.models import DcaGridTrailingConfig
    from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing

    ref = 2059.84
    cfg = DcaGridTrailingConfig(
        {
            "symbol": "ETHUSDT",
            "sell_grids": [
                {"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 40.0},
                {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 60.0},
            ],
            "buy_grids": [],
            "sell_trigger_trailing_pct": 0.3,
        }
    )
    state = {
        "bot_id": 1,
        "cycle_id": 2,
        "mode": "TRAIL_SELL_GRID",
        "initial_allocation_done": True,
        "reference_price": ref,
        "grid_reference_base": 0.0048,
        "sell_grid_fired": [False, False],
        "sell_grid_trigger_price": [2059.8445, None],
        "sell_grid_peak_price": [2121.84, None],
        "buy_grid_fired": [],
        "buy_grid_trigger_price": [],
        "buy_grid_trough_price": [],
    }
    price = 2119.37
    actions, _ = tick_dca_grid_trailing(state, cfg, price, 0.0048, 10.0)
    assert state["sell_grid_trigger_price"][1] is not None, "grid 2 should trigger"
    assert abs(state["sell_grid_trigger_price"][1] - ref * 1.02) < 0.02, (
        "trigger stores threshold not tick price"
    )
    assert state["sell_grid_peak_price"][1] == price
    assert not any(a.get("grid_index") == 1 for a in actions), (
        "grid 2 should trail first, not sell immediately"
    )
    assert state["sell_grid_peak_price"][0] >= price


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
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "o1",
        "c1",
        "BUY",
        1.0,
        100.0,
        0.0,
        "USDT",
        "trail_buy_grid",
    )
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:05:00Z",
        "o2",
        "c2",
        "SELL",
        1.0,
        101.0,
        0.0,
        "USDT",
        "trail_profit_sell",
    )
    cycle_type2, base_delta2 = get_cycle_type_and_base_delta("trail_profit_sell", led)
    assert cycle_type2 == "LONG_SCALP"
    assert base_delta2 == 0.0


def test_cycle_type_reentry_buy_is_inventory_rebalance():
    """close_reason trail_reentry_buy -> INVENTORY_REBALANCE, base_delta = buy_qty_total - sell_qty_total."""
    cycle_type, base_delta = get_cycle_type_and_base_delta("trail_reentry_buy", None)
    assert cycle_type == "INVENTORY_REBALANCE"
    assert base_delta == 0.0
    led = build_cycle_ledger_empty(1, "BTCUSDT")
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:00:00Z",
        "o1",
        "c1",
        "BUY",
        1.02,
        100.0,
        0.0,
        "USDT",
        "trail_buy_grid",
    )
    cycle_ledger_add_fill(
        led,
        "2026-02-01T12:01:00Z",
        "o2",
        "c2",
        "SELL",
        1.0,
        99.0,
        0.0,
        "USDT",
        "trail_sell_grid",
    )
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
        led,
        "2026-02-17T15:37:25Z",
        "o1",
        "c1",
        "BUY",
        5.263,
        53.45,
        0.0,
        "USDT",
        "trail_reentry_buy",
    )
    cycle_ledger_add_fill(
        led,
        "2026-02-17T16:45:53Z",
        "o2",
        "c2",
        "SELL",
        5.084,
        55.34,
        0.28134856,
        "USDT",
        "trail_profit_sell",
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
