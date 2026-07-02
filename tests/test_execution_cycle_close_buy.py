"""Execution must not block cycle-closing re-entry under DPS buy_disabled overlays."""

from __future__ import annotations

from types import SimpleNamespace

from app.botengine.dynamic.cycle_gate import CYCLE_CLOSE_BUY_REASONS


def _would_skip_buy(config, reason: str) -> str | None:
    """Mirror execution.py buy-skip gate (no DB / adapter)."""
    skip = None
    if reason not in CYCLE_CLOSE_BUY_REASONS:
        if getattr(config, "buy_disabled", False):
            skip = "BUY_DISABLED"
        elif getattr(config, "sell_only_mode", False):
            skip = "SELL_ONLY_MODE"
        elif int(getattr(config, "max_buy_levels", 0) or 0) <= 0:
            skip = "MAX_BUY_LEVELS_ZERO"
    return skip


def test_trail_reentry_buy_allowed_when_buy_disabled():
    cfg = SimpleNamespace(
        buy_disabled=True,
        sell_only_mode=True,
        max_buy_levels=0,
    )
    assert _would_skip_buy(cfg, "trail_reentry_buy") is None


def test_trail_buy_grid_blocked_when_buy_disabled():
    cfg = SimpleNamespace(
        buy_disabled=True,
        sell_only_mode=False,
        max_buy_levels=2,
    )
    assert _would_skip_buy(cfg, "trail_buy_grid") == "BUY_DISABLED"


def test_initial_allocation_blocked_when_buy_disabled():
    cfg = SimpleNamespace(
        buy_disabled=True,
        sell_only_mode=False,
        max_buy_levels=2,
    )
    assert _would_skip_buy(cfg, "initial_allocation") == "BUY_DISABLED"
