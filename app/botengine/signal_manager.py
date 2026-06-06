"""Strategy signal facade for bot engine ticks."""

from __future__ import annotations

from app.botengine.strategies.dca_grid_trailing import tick_dca_grid_trailing
from app.botengine.strategies.trdca_pro import strategy_tick as tick_trdca_pro

__all__ = ["tick_dca_grid_trailing", "tick_trdca_pro"]
