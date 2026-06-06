"""
Strategy interface for plugin architecture.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple


class Strategy(ABC):
    """Base for bot strategies. tick() returns (actions, next_wake_sec); apply_fill() mutates state."""

    strategy_id: str = "base"

    @abstractmethod
    def tick(
        self,
        state: Dict[str, Any],
        config: Any,
        price: float,
        base_balance: float,
        quote_balance: float,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """One strategy tick. Mutates state. Returns (actions, next_wakeup_sec)."""
        ...

    def apply_fill(
        self,
        state: Dict[str, Any],
        side: str,
        executed_qty: float,
        executed_price: float,
        fee: float,
        grid_index: Any = None,
        reason: str = "",
        execution_price: Any = None,
    ) -> None:
        """Update state after a fill. Default: no-op; subclass overrides."""
        pass
