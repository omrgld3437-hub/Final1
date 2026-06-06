"""
Strategy registry: plugin by strategy_id. Default dca_grid_trailing.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, Type

from app.botengine.strategies.base import Strategy

logger = logging.getLogger(__name__)

_strategies: Dict[str, Strategy] = {}
_strategy_classes: Dict[str, Type[Strategy]] = {}


def register(strategy_cls: Type[Strategy]) -> Type[Strategy]:
    """Decorator: register a strategy class. strategy_id from class attribute."""
    sid = getattr(strategy_cls, "strategy_id", None) or strategy_cls.__name__
    _strategy_classes[sid] = strategy_cls
    _strategies[sid] = strategy_cls()
    logger.debug("strategy_registry: registered strategy_id=%s", sid)
    return strategy_cls


def get_strategy(strategy_id: str) -> Strategy:
    """Return strategy instance. Default dca_grid_trailing if missing."""
    if not strategy_id or not strategy_id.strip():
        strategy_id = "dca_grid_trailing"
    strategy_id = strategy_id.strip().lower()
    if strategy_id in _strategies:
        return _strategies[strategy_id]
    if strategy_id in _strategy_classes:
        inst = _strategy_classes[strategy_id]()
        _strategies[strategy_id] = inst
        return inst
    return _strategies.get("dca_grid_trailing")


def _ensure_default():
    if (
        "dca_grid_trailing" not in _strategies
        and "dca_grid_trailing" not in _strategy_classes
    ):
        try:
            from app.botengine.strategies.dca_grid_trailing import (
                DcaGridTrailingStrategy,
            )

            register(DcaGridTrailingStrategy)
        except Exception as e:
            logger.debug("registry default strategy: %s", e)
    if (
        "multi_asset_rebalance" not in _strategies
        and "multi_asset_rebalance" not in _strategy_classes
    ):
        try:
            from app.botengine.strategies.multi_asset_rebalance import (
                MultiAssetRebalanceStrategy,
            )

            register(MultiAssetRebalanceStrategy)
        except Exception as e:
            logger.debug("registry multi_asset_rebalance: %s", e)


def get_strategy_safe(strategy_id: Any) -> Strategy:
    """Like get_strategy but accepts None/config dict; default dca_grid_trailing."""
    _ensure_default()
    sid = None
    if isinstance(strategy_id, str):
        sid = strategy_id
    elif isinstance(strategy_id, dict):
        sid = strategy_id.get("strategy_id") or strategy_id.get("strategy")
    return get_strategy(sid or "dca_grid_trailing")


# Register default strategy on import so get_strategy("dca_grid_trailing") always works
_ensure_default()
