"""
Multi-asset rebalance strategy.
Rebalance portfolio to target % per asset (USDT pairs). Trigger: threshold / interval / hybrid.
Strategy does not hold API/DB; worker passes state, config, prices; returns (actions, next_wake_sec).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Tuple

from app.botengine.strategies.base import Strategy

logger = logging.getLogger(__name__)


class MultiAssetRebalanceStrategy(Strategy):
    """Multi-asset rebalance: maintain target % per coin; rebalance on threshold/interval/hybrid."""

    strategy_id = "multi_asset_rebalance"

    def tick(
        self,
        state: Dict[str, Any],
        config: Any,
        price: float,
        base_balance: float,
        quote_balance: float,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        One tick. Uses config: assets[], rebalance_mode, threshold_pct, interval_sec, min_trade_usdt.
        next_wake = interval_sec (from rebalance). Full rebalance logic (prices, balances, orders)
        is wired in orchestrator/execution; here we return no actions and log params.
        """
        next_wake_sec = 3600.0
        try:
            assets = getattr(config, "assets", None) or []
            rebalance_mode = getattr(config, "rebalance_mode", "threshold")
            threshold_pct = getattr(config, "threshold_pct", 2.0)
            interval_sec = max(1, getattr(config, "interval_sec", 3600))
            min_trade_usdt = getattr(config, "min_notional_guard", 10.0)
            next_wake_sec = float(interval_sec)
            if assets:
                logger.info(
                    "REB_MULTI_TICK bot_id=%s mode=%s threshold_pct=%s interval_sec=%s min_trade_usdt=%s assets=%s",
                    state.get("bot_id"),
                    rebalance_mode,
                    threshold_pct,
                    interval_sec,
                    min_trade_usdt,
                    [a.get("symbol") for a in assets],
                )
        except Exception as e:
            logger.debug("multi_asset_rebalance tick config read: %s", e)
        return [], next_wake_sec

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
        """Update state after a fill. Multi-asset: per-symbol state can be extended later."""
        pass
