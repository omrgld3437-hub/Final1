"""
FILE: engine_v2.py
VERSION: v1
DATE: 2026-01-21
CHANGE: DCA Bot V2 Engine - State machine with trailing extremes and profit cycles
"""

import json
import logging
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from app.bot.models_v2 import (
    BotV2,
    BotBalanceV2,
    BotGridV2,
    BotCycleV2,
    BotTradeV2,
    BotStateV2,
)
from app.bot.binance_adapter_v2 import BinanceSpotAdapterV2
from app.services.encryption import decrypt_account_api_key, decrypt_account_api_secret
from app.services import audit as audit_svc
from app.db.models import Account


class BotEngineV2:
    """Bot V2 Engine - Deterministic state machine"""

    def __init__(self, bot_id: int, db: Session):
        self.bot_id = bot_id
        self.db = db
        self.bot: Optional[BotV2] = None
        self.balances: Optional[BotBalanceV2] = None
        self.grids_up: List[BotGridV2] = []
        self.grids_down: List[BotGridV2] = []
        self.adapter: Optional[BinanceSpotAdapterV2] = None
        self.current_cycle: Optional[BotCycleV2] = None
        self.last_price: float = 0.0
        self.ref_price: float = 0.0

    def load(self):
        """Load bot and related data from DB"""
        self.bot = self.db.query(BotV2).filter(BotV2.id == self.bot_id).first()
        if not self.bot:
            raise ValueError(f"Bot {self.bot_id} not found")

        self.balances = (
            self.db.query(BotBalanceV2)
            .filter(BotBalanceV2.bot_id == self.bot_id)
            .first()
        )

        all_grids = (
            self.db.query(BotGridV2)
            .filter(BotGridV2.bot_id == self.bot_id, BotGridV2.enabled == True)
            .order_by(BotGridV2.idx)
            .all()
        )

        self.grids_up = [g for g in all_grids if g.side == "UP_SELL"]
        self.grids_down = [g for g in all_grids if g.side == "DOWN_BUY"]

        # Load active cycle
        self.current_cycle = (
            self.db.query(BotCycleV2)
            .filter(BotCycleV2.bot_id == self.bot_id, BotCycleV2.status == "OPEN")
            .order_by(BotCycleV2.cycle_no.desc())
            .first()
        )

        # Initialize adapter
        if self.bot.mode == "live":
            from app.db.models import Account

            account = (
                self.db.query(Account).filter(Account.id == self.bot.account_id).first()
            )
            if account:
                api_key = decrypt_account_api_key(account.id, account.api_key_enc)
                api_secret = decrypt_account_api_secret(
                    account.id, account.api_secret_enc
                )
                self.adapter = BinanceSpotAdapterV2(
                    self.bot.account_id, "live", api_key, api_secret
                )
        else:
            self.adapter = BinanceSpotAdapterV2(self.bot.account_id, "paper")

        # Load ref_price
        if self.bot.ref_price_mode == "market_now" or not self.bot.ref_price:
            self.ref_price = self.adapter.get_price(self.bot.symbol)
            if not self.bot.ref_price:
                self.bot.ref_price = self.ref_price
                self.db.commit()
        else:
            self.ref_price = self.bot.ref_price

    def tick(self):
        """Main tick loop - deterministic state machine update"""
        if self.bot.status != "RUNNING":
            return

        # Fetch current price
        self.last_price = self.adapter.get_price(self.bot.symbol)

        # 1. Update grid arming (IDLE -> ARMED)
        self._update_grid_arming()

        # 2. Update trailing logic (ARMED/TRAILING -> EXECUTED)
        self._update_trailing_executions()

        # 3. Check profit triggers
        self._check_profit_triggers()

        # 4. Update cycle if profit execution happened
        self._update_profit_executions()

        # 5. Check cycle completion
        if self.current_cycle:
            self._check_cycle_completion()

        # 6. Persist state
        self._persist_state()

    def _update_grid_arming(self):
        """Arm grids when price reaches trigger"""
        # UP grids (sell) - arm when price >= trigger
        for grid in self.grids_up:
            if grid.state == "IDLE" and self.last_price >= grid.trigger_price_abs:
                grid.state = "ARMED"
                grid.armed_at_price = self.last_price
                grid.extreme_price = self.last_price  # Start tracking peak
                grid.updated_at = datetime.utcnow()

        # DOWN grids (buy) - arm when price <= trigger
        for grid in self.grids_down:
            if grid.state == "IDLE" and self.last_price <= grid.trigger_price_abs:
                grid.state = "ARMED"
                grid.armed_at_price = self.last_price
                grid.extreme_price = self.last_price  # Start tracking dip
                grid.updated_at = datetime.utcnow()

    def _update_trailing_executions(self):
        """Execute trailing orders when threshold reached"""
        # UP sell grids - track peak, execute on drop
        for grid in self.grids_up:
            if grid.state in ["ARMED", "TRAILING"]:
                # Update extreme (peak)
                if grid.extreme_price is None:
                    grid.extreme_price = self.last_price
                grid.extreme_price = max(grid.extreme_price, self.last_price)
                grid.state = "TRAILING"

                # Calculate threshold (drop from peak by trailing_pct)
                threshold = grid.extreme_price * (1 - grid.trailing_pct / 100.0)
                grid.threshold_price = threshold

                # Execute if price dropped below threshold
                if self.last_price <= threshold:
                    self._execute_sell_grid(grid)

        # DOWN buy grids - track dip, execute on rise
        for grid in self.grids_down:
            if grid.state in ["ARMED", "TRAILING"]:
                # Update extreme (dip)
                if grid.extreme_price is None:
                    grid.extreme_price = self.last_price
                grid.extreme_price = min(grid.extreme_price, self.last_price)
                grid.state = "TRAILING"

                # Calculate threshold (rise from dip by trailing_pct)
                threshold = grid.extreme_price * (1 + grid.trailing_pct / 100.0)
                grid.threshold_price = threshold

                # Execute if price rose above threshold
                if self.last_price >= threshold:
                    self._execute_buy_grid(grid)

    def _execute_sell_grid(self, grid: BotGridV2):
        """Execute sell order for UP grid"""
        try:
            # Calculate qty (% of available base)
            qty = self.balances.base_free * (grid.qty_pct / 100.0)
            if qty <= 0:
                grid.state = "SKIPPED"
                return

            # Apply precision and check min notional
            qty = self.adapter.apply_precision(self.bot.symbol, qty, is_price=False)
            ok, msg = self.adapter.check_min_notional(
                self.bot.symbol, qty, self.last_price
            )
            if not ok:
                grid.state = "SKIPPED"
                return

            # Place market sell
            result = self.adapter.place_market_sell(
                self.bot.symbol,
                qty,
                slippage_bps=self.bot.slippage_bps,
                taker_fee_bps=self.bot.taker_fee_bps,
            )

            # Update grid state
            grid.state = "EXECUTED"
            grid.executed_qty = result["executedQty"]
            grid.executed_quote = result["cumulativeQuoteQty"]
            grid.executed_avg_price = (
                result["cumulativeQuoteQty"] / result["executedQty"]
            )
            grid.updated_at = datetime.utcnow()

            # Update balances
            self.balances.base_free -= result["executedQty"]
            self.balances.quote_free += (
                result["cumulativeQuoteQty"] - result["fee_usdt"]
            )

            # Create trade record
            self._create_trade(
                side="SELL",
                qty=result["executedQty"],
                price=grid.executed_avg_price,
                quote_qty=result["cumulativeQuoteQty"],
                fee_usdt=result["fee_usdt"],
                reason=f"GRID_UP_{grid.idx}",
            )

            # Update cycle aggregates
            if self.current_cycle:
                self._update_cycle_sell_aggregates(grid)

            self.db.commit()

        except Exception as e:
            logger.error("Error executing sell grid %s: %s", grid.idx, e)
            grid.state = "SKIPPED"
            self.db.rollback()

    def _execute_buy_grid(self, grid: BotGridV2):
        """Execute buy order for DOWN grid"""
        try:
            # Calculate quote to spend (% of available quote)
            quote_to_spend = self.balances.quote_free * (grid.qty_pct / 100.0)
            if quote_to_spend < grid.min_exec_usdt:
                grid.state = "SKIPPED"
                return

            # Place market buy
            result = self.adapter.place_market_buy(
                self.bot.symbol,
                quote_to_spend,
                slippage_bps=self.bot.slippage_bps,
                taker_fee_bps=self.bot.taker_fee_bps,
            )

            # Update grid state
            grid.state = "EXECUTED"
            grid.executed_qty = result["executedQty"]
            grid.executed_quote = result["cumulativeQuoteQty"]
            grid.executed_avg_price = (
                result["cumulativeQuoteQty"] / result["executedQty"]
            )
            grid.updated_at = datetime.utcnow()

            # Update balances
            self.balances.base_free += result["executedQty"]
            self.balances.quote_free -= (
                result["cumulativeQuoteQty"] + result["fee_usdt"]
            )

            # Create trade record
            self._create_trade(
                side="BUY",
                qty=result["executedQty"],
                price=grid.executed_avg_price,
                quote_qty=result["cumulativeQuoteQty"],
                fee_usdt=result["fee_usdt"],
                reason=f"GRID_DOWN_{grid.idx}",
            )

            # Update cycle aggregates
            if self.current_cycle:
                self._update_cycle_buy_aggregates(grid)

            self.db.commit()

        except Exception as e:
            logger.error("Error executing buy grid %s: %s", grid.idx, e)
            grid.state = "SKIPPED"
            self.db.rollback()

    def _update_cycle_sell_aggregates(self, grid: BotGridV2):
        """Update weighted average sell price in cycle"""
        if not self.current_cycle:
            return

        total_qty = self.current_cycle.sell_total_qty + grid.executed_qty
        if total_qty > 0:
            # Weighted average
            new_avg = (
                (self.current_cycle.sell_avg_price or 0)
                * self.current_cycle.sell_total_qty
                + grid.executed_avg_price * grid.executed_qty
            ) / total_qty
            self.current_cycle.sell_avg_price = new_avg
            self.current_cycle.sell_total_qty = total_qty
            self.current_cycle.sell_total_quote += grid.executed_quote

            if not self.current_cycle.direction:
                self.current_cycle.direction = "UP"

    def _update_cycle_buy_aggregates(self, grid: BotGridV2):
        """Update weighted average buy price in cycle"""
        if not self.current_cycle:
            return

        total_qty = self.current_cycle.buy_total_qty + grid.executed_qty
        if total_qty > 0:
            # Weighted average
            new_avg = (
                (self.current_cycle.buy_avg_price or 0)
                * self.current_cycle.buy_total_qty
                + grid.executed_avg_price * grid.executed_qty
            ) / total_qty
            self.current_cycle.buy_avg_price = new_avg
            self.current_cycle.buy_total_qty = total_qty
            self.current_cycle.buy_total_quote += grid.executed_quote

            if self.current_cycle.direction == "UP":
                self.current_cycle.direction = "MIXED"
            elif not self.current_cycle.direction:
                self.current_cycle.direction = "DOWN"

    def _check_profit_triggers(self):
        """Check if profit cycle should be armed"""
        if not self.current_cycle:
            return

        # Get config from bot (would need to add these fields or use a config JSON)
        # For now, use defaults from spec
        profit_rebuy_trigger_pct = 1.5  # TODO: load from bot config
        profit_resell_trigger_pct = 2.0  # TODO: load from bot config

        # If sells executed, check for profit rebuy
        if (
            self.current_cycle.sell_avg_price
            and self.current_cycle.profit_mode != "REBUY"
            and self.current_cycle.profit_mode != "RESELL"
        ):
            drop_threshold = self.current_cycle.sell_avg_price * (
                1 - profit_rebuy_trigger_pct / 100.0
            )
            if self.last_price <= drop_threshold:
                self.current_cycle.profit_mode = "REBUY"
                # Start tracking dip
                state_json = (
                    json.loads(self.bot.state.state_json) if self.bot.state else {}
                )
                state_json["profit_extreme"] = self.last_price
                state_json["profit_threshold"] = None
                if self.bot.state:
                    self.bot.state.state_json = json.dumps(state_json)

        # If buys executed, check for profit resell
        if (
            self.current_cycle.buy_avg_price
            and self.current_cycle.profit_mode != "REBUY"
            and self.current_cycle.profit_mode != "RESELL"
        ):
            rise_threshold = self.current_cycle.buy_avg_price * (
                1 + profit_resell_trigger_pct / 100.0
            )
            if self.last_price >= rise_threshold:
                self.current_cycle.profit_mode = "RESELL"
                # Start tracking peak
                state_json = (
                    json.loads(self.bot.state.state_json) if self.bot.state else {}
                )
                state_json["profit_extreme"] = self.last_price
                state_json["profit_threshold"] = None
                if self.bot.state:
                    self.bot.state.state_json = json.dumps(state_json)

    def _update_profit_executions(self):
        """Update profit trailing and execute if threshold reached"""
        if not self.current_cycle or not self.current_cycle.profit_mode:
            return

        state_json = json.loads(self.bot.state.state_json) if self.bot.state else {}
        profit_extreme = state_json.get("profit_extreme")

        if self.current_cycle.profit_mode == "REBUY":
            # Trailing dip for rebuy
            if profit_extreme is None:
                profit_extreme = self.last_price
            profit_extreme = min(profit_extreme, self.last_price)
            state_json["profit_extreme"] = profit_extreme

            profit_rebuy_trailing_pct = 1.0  # TODO: from config
            threshold = profit_extreme * (1 + profit_rebuy_trailing_pct / 100.0)
            state_json["profit_threshold"] = threshold

            if self.last_price >= threshold:
                self._execute_profit_rebuy()

        elif self.current_cycle.profit_mode == "RESELL":
            # Trailing peak for resell
            if profit_extreme is None:
                profit_extreme = self.last_price
            profit_extreme = max(profit_extreme, self.last_price)
            state_json["profit_extreme"] = profit_extreme

            profit_resell_trailing_pct = 1.0  # TODO: from config
            threshold = profit_extreme * (1 - profit_resell_trailing_pct / 100.0)
            state_json["profit_threshold"] = threshold

            if self.last_price <= threshold:
                self._execute_profit_resell()

        if self.bot.state:
            self.bot.state.state_json = json.dumps(state_json)

    def _execute_profit_rebuy(self):
        """Execute profit rebuy (buyback after sells)"""
        # TODO: Implement profit rebuy execution
        # Use sold quote proceeds to buyback base
        pass

    def _execute_profit_resell(self):
        """Execute profit resell (sell after buys)"""
        # TODO: Implement profit resell execution
        # Sell bought base for profit
        pass

    def _check_cycle_completion(self):
        """Check if cycle should be closed and restarted"""
        # TODO: Implement cycle completion logic
        pass

    def _create_trade(
        self,
        side: str,
        qty: float,
        price: float,
        quote_qty: float,
        fee_usdt: float,
        reason: str,
    ):
        """Create trade record and audit log."""
        ts_now = datetime.utcnow()
        trade = BotTradeV2(
            bot_id=self.bot_id,
            cycle_id=self.current_cycle.id if self.current_cycle else None,
            ts=ts_now,
            symbol=self.bot.symbol,
            side=side,
            qty=qty,
            price=price,
            quote_qty=quote_qty,
            fee_usdt=fee_usdt,
            fee_asset="USDT",
            reason=reason,
            mode=self.bot.mode,
        )
        self.db.add(trade)
        acc = self.db.query(Account).filter(Account.id == self.bot.account_id).first()
        audit_svc.log_event(
            self.db,
            actor_type="system",
            event_type="BOT_TRADE",
            severity="INFO",
            target_user_id=acc.user_id if acc else None,
            target_account_id=self.bot.account_id,
            meta={
                "bot_id": self.bot_id,
                "symbol": self.bot.symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "quote_qty": quote_qty,
                "fee_usdt": fee_usdt,
                "reason": reason,
                "trade_ts": ts_now.isoformat() if ts_now else None,
                "mode": self.bot.mode,
            },
        )

    def _persist_state(self):
        """Persist engine state to DB"""
        # Update bot timestamp
        self.bot.updated_at = datetime.utcnow()

        # Update state JSON
        state_data = {
            "last_price": self.last_price,
            "ref_price": self.ref_price,
            "base_free": self.balances.base_free,
            "quote_free": self.balances.quote_free,
            "profit_extreme": None,
            "profit_threshold": None,
        }

        if not self.bot.state:
            self.bot.state = BotStateV2(
                bot_id=self.bot_id, state_json=json.dumps(state_data)
            )
        else:
            existing = json.loads(self.bot.state.state_json)
            existing.update(state_data)
            self.bot.state.state_json = json.dumps(existing)

        # Update equity
        self.balances.base_value_usdt = self.balances.base_free * self.last_price
        self.balances.total_value_usdt = (
            self.balances.base_value_usdt + self.balances.quote_free
        )
        self.bot.budget_usdt_current = self.balances.total_value_usdt

        self.db.commit()
