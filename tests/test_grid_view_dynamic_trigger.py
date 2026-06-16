"""
Grid-view display consistency tests, with focus on Dynamic Mode.

Core invariants verified:
  * A FIRED/armed sell grid displays its STORED trigger (ground truth), so that
    trigger <= peak always holds — even when Dynamic Mode used a grid % that
    differs from the manual config %.
  * A PENDING grid (not armed) displays the computed trigger (ref × (1±pct)).
  * The effective-config overlay surfaces snapshot.applied values when Dynamic
    Mode is active, and leaves the manual config untouched otherwise.
"""

from __future__ import annotations

from app.botengine.grid_view import compute_grid_profit_view
from app.api.bots_engine import _effective_grid_config


def _manual_cfg():
    return {
        "symbol": "ETHUSDT",
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [
            {"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 50.0},
            {"sell_grid_pct": 4.0, "sell_qty_pct_of_base": 50.0},
        ],
        "buy_grids": [
            {"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 50.0},
            {"buy_grid_pct": 4.0, "buy_qty_pct_of_quote": 50.0},
        ],
        "sell_trigger_trailing_pct": 0.5,
        "buy_trigger_trailing_pct": 0.5,
    }


# ---------------------------------------------------------------------------
# Fix 1 — fired grid uses stored trigger
# ---------------------------------------------------------------------------


def test_fired_sell_grid_uses_stored_trigger_not_recomputed():
    """
    Reproduces the real bug: cycle ref moved (dynamic), grid fired at a tighter
    real trigger. UI must show the stored trigger so trigger <= peak holds.
    """
    ref = 1581.16
    state = {
        "reference_price": ref,
        "sell_grid_fired": [True, True],
        # Real (stored) triggers — tighter than manual 2/4%
        "sell_grid_trigger_price": [1586.09, 1591.02],
        "sell_grid_peak_price": [1594.86, 1594.86],
        "sell_grid_fill_price": [1585.77, 1585.51],
        "buy_grid_fired": [False, False],
        "buy_grid_trigger_price": [None, None],
        "buy_grid_trough_price": [None, None],
        "buy_grid_fill_price": [None, None],
        "sell_history": [{}, {}],
        "mode": "IDLE",
    }
    gp, _pp, _meta = compute_grid_profit_view(state, _manual_cfg(), ref)
    sells = [p for p in gp if p["type"] == "sell"]
    assert len(sells) == 2
    # Stored triggers, NOT 1581×1.02=1612 / 1581×1.04=1644
    assert sells[0]["trigger_price"] == 1586.09
    assert sells[1]["trigger_price"] == 1591.02
    # Invariant: trigger <= peak for every fired sell grid
    for p in sells:
        assert p["trigger_price"] <= p["anchor"], (
            f"trigger {p['trigger_price']} > peak {p['anchor']}"
        )


def test_pending_sell_grid_uses_calc_trigger():
    """Not-armed grid (no stored trigger) → computed from ref × (1+pct)."""
    ref = 1000.0
    state = {
        "reference_price": ref,
        "sell_grid_fired": [False, False],
        "sell_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [None, None],
        "sell_grid_fill_price": [None, None],
        "buy_grid_fired": [False, False],
        "buy_grid_trigger_price": [None, None],
        "buy_grid_trough_price": [None, None],
        "buy_grid_fill_price": [None, None],
        "mode": "IDLE",
    }
    gp, _pp, _meta = compute_grid_profit_view(state, _manual_cfg(), ref)
    sells = [p for p in gp if p["type"] == "sell"]
    assert sells[0]["trigger_price"] == 1020.0  # 1000 × 1.02
    assert sells[1]["trigger_price"] == 1040.0  # 1000 × 1.04


def test_fired_buy_grid_uses_stored_trigger():
    ref = 1000.0
    state = {
        "reference_price": ref,
        "sell_grid_fired": [False, False],
        "sell_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [None, None],
        "sell_grid_fill_price": [None, None],
        "buy_grid_fired": [True, False],
        "buy_grid_trigger_price": [994.0, None],  # real trigger tighter than 2%
        "buy_grid_trough_price": [990.0, None],
        "buy_grid_fill_price": [993.0, None],
        "buy_history": [{}],
        "mode": "IDLE",
    }
    gp, _pp, _meta = compute_grid_profit_view(state, _manual_cfg(), ref)
    buys = [p for p in gp if p["type"] == "buy"]
    # Fired buy → stored trigger 994 (not 1000×0.98=980)
    assert buys[0]["trigger_price"] == 994.0
    # Invariant: trigger >= trough for fired buy grid
    assert buys[0]["trigger_price"] >= buys[0]["anchor"]
    # Pending buy → calc 1000×0.96 = 960
    assert buys[1]["trigger_price"] == 960.0


# ---------------------------------------------------------------------------
# Fix 2 — effective config overlay
# ---------------------------------------------------------------------------


def _snapshot_applied():
    return {
        "applied": {
            "base_alloc_pct": 25.0,
            "quote_alloc_pct": 75.0,
            "sell_grids": [
                {"sell_grid_pct": 0.31, "sell_qty_pct_of_base": 16.0},
                {"sell_grid_pct": 0.62, "sell_qty_pct_of_base": 18.0},
            ],
            "buy_grids": [
                {"buy_grid_pct": 0.31, "buy_qty_pct_of_quote": 16.0},
                {"buy_grid_pct": 0.62, "buy_qty_pct_of_quote": 18.0},
            ],
            "sell_trigger_trailing_pct": 0.41,
            "buy_trigger_trailing_pct": 0.41,
            "profit_exit_rise_pct": 1.2,
            "profit_reentry_drop_pct": 0.69,
        },
        "regime": "TRENDING_DOWN",
        "cycle_id": 3,
    }


def test_effective_config_overlays_when_dynamic_active():
    raw = dict(_manual_cfg())
    raw["dynamic_mode"] = True
    state = {"dynamic_snapshot": _snapshot_applied()}
    eff = _effective_grid_config(raw, state)
    assert eff.get("_dynamic_applied") is True
    assert eff["sell_grids"][0]["sell_grid_pct"] == 0.31
    assert eff["base_alloc_pct"] == 25.0
    assert eff["sell_trigger_trailing_pct"] == 0.41
    assert eff["profit_reentry_drop_pct"] == 0.69


def test_effective_config_manual_when_dynamic_off():
    raw = dict(_manual_cfg())
    raw["dynamic_mode"] = False
    state = {"dynamic_snapshot": _snapshot_applied()}
    eff = _effective_grid_config(raw, state)
    assert not eff.get("_dynamic_applied")
    # Manual grids preserved
    assert eff["sell_grids"][0]["sell_grid_pct"] == 2.0
    assert eff["base_alloc_pct"] == 50.0


def test_effective_config_manual_when_no_snapshot():
    raw = dict(_manual_cfg())
    raw["dynamic_mode"] = True  # flag on but no snapshot yet
    eff = _effective_grid_config(raw, {})
    assert not eff.get("_dynamic_applied")
    assert eff["sell_grids"][0]["sell_grid_pct"] == 2.0


def test_full_pipeline_dynamic_display_consistent():
    """End-to-end: dynamic overlay + stored trigger → pending grid shows dynamic %."""
    ref = 1000.0
    raw = dict(_manual_cfg())
    raw["dynamic_mode"] = True
    state = {
        "reference_price": ref,
        "dynamic_snapshot": _snapshot_applied(),
        "sell_grid_fired": [False, False],  # pending
        "sell_grid_trigger_price": [None, None],
        "sell_grid_peak_price": [None, None],
        "sell_grid_fill_price": [None, None],
        "buy_grid_fired": [False, False],
        "buy_grid_trigger_price": [None, None],
        "buy_grid_trough_price": [None, None],
        "buy_grid_fill_price": [None, None],
        "mode": "IDLE",
    }
    eff = _effective_grid_config(raw, state)
    gp, _pp, _meta = compute_grid_profit_view(state, eff, ref)
    sells = [p for p in gp if p["type"] == "sell"]
    # Pending grid trigger now uses DYNAMIC 0.31% → 1003.1, not manual 2% → 1020
    assert abs(sells[0]["trigger_price"] - 1003.1) < 0.5
