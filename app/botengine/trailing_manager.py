"""Trailing strategy facade."""

from __future__ import annotations

from app.botengine.strategies.dca_grid_trailing import (
    DcaGridTrailingStrategy,
    tick_dca_grid_trailing,
)

__all__ = ["DcaGridTrailingStrategy", "tick_dca_grid_trailing"]
