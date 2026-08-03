"""Acceptance tests for directional trailing and profit cost-basis invariants."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text

from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing
from app.botengine.strategies.grid_outage_recovery import apply_grid_outage_recovery
from app.botengine.trade_invariants import (
    CostBasisType,
    OrderType,
    price_from_reference,
    validate_cost_basis,
    weighted_average_price,
)
from app.db.schema_guard import ensure_trades_engine_columns


REFERENCE = 64980.021597
BUY_TRIGGER = 64330.22138103


def _cfg(**overrides):
    raw = {
        "symbol": "BTCUSDT",
        "initial_capital_usdt": 1000.0,
        "sell_grids": [{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 10.0}],
        "buy_grids": [{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 10.0}],
        "sell_trigger_trailing_pct": 0.5,
        "buy_trigger_trailing_pct": 0.5,
        "profit_exit_rise_pct": 1.5,
        "profit_exit_drop_pct": 0.5,
        "profit_reentry_drop_pct": 1.5,
        "profit_reentry_rise_pct": 0.5,
        "max_buy_levels": 5,
    }
    raw.update(overrides)
    return DcaGridTrailingConfig(raw)


def _state(**overrides):
    state = {
        "bot_id": 1,
        "symbol": "BTCUSDT",
        "cycle_id": 1,
        "mode": "IDLE",
        "initial_allocation_done": True,
        "reference_price": REFERENCE,
        "initial_reference_price": REFERENCE,
        "initial_alloc_base_qty": 1.0,
        "initial_alloc_price": REFERENCE,
        "grid_reference_base": 1.0,
        "grid_reference_quote": 1000.0,
        "base_balance": 1.0,
        "quote_balance": 1000.0,
        "sell_grid_fired": [False],
        "sell_grid_trigger_price": [None],
        "sell_grid_peak_price": [None],
        "buy_grid_fired": [False],
        "buy_grid_trigger_price": [None],
        "buy_grid_trough_price": [None],
        "sell_history": [],
        "buy_history": [],
    }
    state.update(overrides)
    return state


def test_1_buy_grid_does_not_trigger_above_trigger():
    state = _state()
    actions, _ = tick_dca_grid_trailing(
        state, _cfg(), 64668.39690201, 1.0, 1000.0
    )
    assert state["buy_grid_trigger_price"][0] is None
    assert state["buy_grid_trough_price"][0] is None
    assert state["buy_grid_status"][0] == "WAITING_TRIGGER"
    assert not [a for a in actions if a.get("side") == "BUY"]


def test_2_buy_grid_triggers_at_threshold_and_tracks_that_price():
    state = _state()
    actions, _ = tick_dca_grid_trailing(state, _cfg(), BUY_TRIGGER, 1.0, 1000.0)
    assert not actions
    assert state["buy_grid_status"][0] == "TRAILING"
    assert state["buy_grid_trigger_price"][0] == pytest.approx(BUY_TRIGGER)
    assert state["buy_grid_trough_price"][0] == pytest.approx(BUY_TRIGGER)


def test_3_new_buy_low_moves_down():
    state = _state(
        buy_grid_trigger_price=[BUY_TRIGGER],
        buy_grid_trough_price=[BUY_TRIGGER],
        buy_grid_status=["TRAILING"],
    )
    tick_dca_grid_trailing(state, _cfg(), 64000.0, 1.0, 1000.0)
    assert state["buy_grid_trough_price"][0] == pytest.approx(64000.0)


def test_4_buy_low_never_moves_up():
    state = _state(
        buy_grid_trigger_price=[BUY_TRIGGER],
        buy_grid_trough_price=[64000.0],
        buy_grid_status=["TRAILING"],
    )
    tick_dca_grid_trailing(state, _cfg(), 64100.0, 1.0, 1000.0)
    assert state["buy_grid_trough_price"][0] == pytest.approx(64000.0)


def test_5_buy_completion_requires_full_bounce():
    state = _state(
        buy_grid_trigger_price=[BUY_TRIGGER],
        buy_grid_trough_price=[64000.0],
        buy_grid_status=["TRAILING"],
    )
    actions_before, _ = tick_dca_grid_trailing(state, _cfg(), 64319.999, 1.0, 1000.0)
    assert not [a for a in actions_before if a.get("reason") == "trail_buy_grid"]
    actions_at, _ = tick_dca_grid_trailing(state, _cfg(), 64320.0, 1.0, 1000.0)
    buy = [a for a in actions_at if a.get("reason") == "trail_buy_grid"]
    assert len(buy) == 1
    assert buy[0]["execution_price"] == pytest.approx(64320.0)
    assert buy[0]["order_type"] == "BUY_GRID"


def test_6_sell_direction_is_exact_opposite():
    cfg = _cfg(sell_grids=[{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 10.0}])
    state = _state(reference_price=100.0, initial_reference_price=100.0)
    tick_dca_grid_trailing(state, cfg, 100.9, 1.0, 1000.0)
    assert state["sell_grid_trigger_price"][0] is None
    tick_dca_grid_trailing(state, cfg, 101.0, 1.0, 1000.0)
    assert state["sell_grid_trigger_price"][0] == pytest.approx(101.0)
    assert state["sell_grid_peak_price"][0] == pytest.approx(101.0)
    assert state["sell_grid_status"][0] == "TRAILING"


def test_7_profit_rebuy_uses_weighted_sell_price_not_initial_reference():
    cfg = _cfg()
    state = _state(
        reference_price=900.0,
        initial_reference_price=900.0,
        cycle_grid_side="SELL",
        sell_grid_fired=[True],
        sell_history=[
            {"grid_index": 0, "qty": 4.0, "price": 100.0, "side": "SELL"},
        ],
    )
    tick_dca_grid_trailing(state, cfg, 98.5, 1.0, 1000.0)
    assert state["_reentry_avg_sell"] == pytest.approx(100.0)
    assert state["_reentry_trigger_price"] == pytest.approx(98.5)
    assert state["_reentry_cost_basis_type"] == "WEIGHTED_SELL_PRICE"


def test_8_profit_sell_uses_weighted_buy_cost_not_initial_reference():
    cfg = _cfg()
    state = _state(
        reference_price=900.0,
        initial_reference_price=900.0,
        cycle_grid_side="BUY",
        buy_grid_fired=[True],
        buy_history=[
            {"grid_index": 0, "qty": 4.0, "price": 100.0, "side": "BUY"},
        ],
    )
    tick_dca_grid_trailing(state, cfg, 101.5, 1.0, 1000.0)
    assert state["_profit_exit_avg_buy"] == pytest.approx(100.0)
    assert state["_profit_exit_trigger_price"] == pytest.approx(101.5)
    assert state["_profit_exit_cost_basis_type"] == "WEIGHTED_BUY_COST"


def test_9_weighted_average_is_quantity_weighted():
    avg = weighted_average_price(
        [
            {"grid_index": 0, "qty": 1, "price": 90},
            {"grid_index": 1, "qty": 3, "price": 110},
        ]
    )
    assert avg == Decimal("105")


def test_10_cost_basis_types_cannot_be_mixed():
    validate_cost_basis(OrderType.BUY_GRID, CostBasisType.INITIAL_REFERENCE)
    validate_cost_basis(OrderType.SELL_GRID, CostBasisType.INITIAL_REFERENCE)
    validate_cost_basis(OrderType.PROFIT_SELL, CostBasisType.WEIGHTED_BUY_COST)
    validate_cost_basis(OrderType.PROFIT_REBUY, CostBasisType.WEIGHTED_SELL_PRICE)
    with pytest.raises(ValueError):
        validate_cost_basis(OrderType.PROFIT_SELL, CostBasisType.INITIAL_REFERENCE)
    with pytest.raises(ValueError):
        validate_cost_basis(OrderType.PROFIT_REBUY, CostBasisType.INITIAL_REFERENCE)


def test_outage_recovery_does_not_trigger_and_complete_same_event():
    state = _state()
    apply_grid_outage_recovery(state, _cfg(), BUY_TRIGGER, gap_sec=120.0)
    assert state["buy_grid_trigger_price"][0] == pytest.approx(BUY_TRIGGER)
    assert state["buy_grid_trough_price"][0] == pytest.approx(BUY_TRIGGER)
    assert state["_outage_favorable_buy"] == []


def test_initial_reference_is_immutable_during_cycle():
    state = _state(reference_price=1.0, initial_reference_price=REFERENCE)
    tick_dca_grid_trailing(state, _cfg(), 64668.0, 1.0, 1000.0)
    assert state["initial_reference_price"] == REFERENCE
    assert state["buy_grid_trigger_price"][0] is None


def test_decimal_trigger_matches_requested_example_exactly():
    assert price_from_reference(
        "64980.021597", "1", OrderType.BUY_GRID
    ) == Decimal("64330.22138103")


def test_legacy_armed_profit_order_with_fee_inflated_trigger_is_recalculated():
    state = _state(
        reference_price=900.0,
        initial_reference_price=900.0,
        cycle_grid_side="BUY",
        mode="TRAIL_PROFIT_SELL",
        trail_anchor_price=102.0,
        buy_grid_fired=[True],
        buy_history=[
            {"grid_index": 0, "qty": 2.0, "price": 100.0, "side": "BUY"}
        ],
        _profit_exit_trigger_price=101.7,
        _profit_exit_breakeven=100.2,
    )
    actions, _ = tick_dca_grid_trailing(state, _cfg(), 101.6, 1.0, 1000.0)
    assert not [a for a in actions if a.get("reason") == "trail_profit_sell"]
    assert state["_profit_exit_trigger_price"] == pytest.approx(101.5)
    assert state["_profit_exit_cost_basis_type"] == "WEIGHTED_BUY_COST"
    assert state["invalid_profit_basis_audit"][-1]["action"] == (
        "CANCELLED_AND_RECALCULATED"
    )


def test_legacy_profit_trail_without_completed_grid_is_cancelled():
    state = _state(
        mode="TRAIL_PROFIT_SELL",
        trail_anchor_price=101.0,
        trail_activation_price=101.0,
        _profit_exit_trigger_price=101.0,
        _profit_exit_cost_basis_type="INITIAL_REFERENCE",
    )
    actions, _ = tick_dca_grid_trailing(state, _cfg(), REFERENCE, 1.0, 1000.0)
    assert not [a for a in actions if a.get("reason") == "trail_profit_sell"]
    assert state["mode"] == "IDLE"
    assert "trail_anchor_price" not in state
    assert "_profit_exit_trigger_price" not in state
    assert state["invalid_profit_basis_audit"][-1]["action"] == (
        "CANCELLED_NO_COMPLETED_GRID"
    )


def test_trade_audit_columns_are_migrated_without_rewriting_existing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE trades (id INTEGER PRIMARY KEY, bot_id INTEGER, "
                "fee FLOAT, fee_asset VARCHAR(10))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO trades (id, bot_id, fee, fee_asset) "
                "VALUES (1, 9, 0.6, 'BTC')"
            )
        )
    ensure_trades_engine_columns(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("trades")}
    assert {
        "fee_amount",
        "fee_usdt",
        "order_type",
        "cost_basis_type",
        "cost_basis_price",
        "linked_grid_ids",
        "trigger_price",
        "tracked_extreme_price",
        "completion_price",
        "fill_total",
        "engine_status",
    } <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT fee FROM trades WHERE id=1")).scalar_one() == 0.6
