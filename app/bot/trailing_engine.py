"""
Trailing Grid DCA Bot Engine
Two-way trailing grid with profit triggers and compound growth cycles
"""
import logging
import threading
import time
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

from app.bot.models import (
    TrailingGridConfig, GridSlot, SlotState,
    QtyMode, ProceedsMode
)
from app.services.price_hub import price_hub
# Optional Binance imports - will be added later
try:
    from app.services.binance_client import BinanceClient
except ImportError:
    BinanceClient = None
from app.bot.ledger import Ledger
from sqlalchemy.orm import Session


class BotState(Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    PRICE_STALE = "PRICE_STALE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class ProfitState(Enum):
    IDLE = "IDLE"
    TRAIL = "TRAIL"
    DONE = "DONE"


class TrailingGridEngine:
    """Two-way trailing grid DCA bot engine"""
    
    def __init__(self, bot_id: int, account_id: int, config: TrailingGridConfig, db: Session, account):
        self.bot_id = bot_id
        self.account_id = account_id
        self.config = config
        self.db = db
        self.account = account
        
        # State
        self.state = BotState.INIT
        self.up_slots: List[GridSlot] = []
        self.down_slots: List[GridSlot] = []
        self.rebuy_state = ProfitState.IDLE
        self.resell_state = ProfitState.IDLE
        
        # Cycle tracking
        self.cycle_id = 0
        self.cycle_start_ts: Optional[datetime] = None
        self.cycle_start_equity = 0.0
        self.start_price = 0.0  # P0
        
        # Balances
        self.base_balance = 0.0
        self.quote_balance = 0.0
        self.initial_base_balance = 0.0
        self.initial_quote_balance = 0.0
        
        # Profit tracking
        self.avg_sell_price = 0.0
        self.total_sold_base = 0.0
        self.total_proceeds_quote = 0.0
        self.avg_buy_cost = 0.0
        self.total_bought_base = 0.0
        self.total_spent_quote = 0.0
        
        # Trailing tracking
        self.rebuy_peak = 0.0
        self.rebuy_trough = 0.0
        self.resell_peak = 0.0
        self.resell_trough = 0.0
        
        # Order cooldown
        self.last_order_ts = 0
        self.order_in_flight = False
        
        # Binance client (lazy load)
        self.binance_client: Optional[BinanceClient] = None
        
        # Threading
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def _get_binance_client(self) -> Optional[BinanceClient]:
        """Get or create Binance client"""
        if self.binance_client:
            return self.binance_client
        
        if self.account.mode == "live":
            # Decrypt and create client
            try:
                from app.services.encryption import decrypt_account_api_key, decrypt_account_api_secret
                api_key = decrypt_account_api_key(self.account_id, self.account.api_key_enc)
                api_secret = decrypt_account_api_secret(self.account_id, self.account.api_secret_enc)
                self.binance_client = BinanceClient(api_key, api_secret, testnet=False)
                return self.binance_client
            except Exception as e:
                logger.error("Error creating Binance client: %s", e)
                return None
        else:
            # Paper mode - return None (simulated trades)
            return None
    
    def _initialize_cycle(self):
        """Initialize a new cycle"""
        self.cycle_id += 1
        self.cycle_start_ts = datetime.utcnow()
        
        # Get current price
        current_price = price_hub.get_price(self.config.symbol)
        if not current_price:
            # Try to fetch
            client = self._get_binance_client()
            if client:
                try:
                    current_price = client.get_ticker_price(self.config.symbol)
                    price_hub.update_price(self.config.symbol, current_price)
                except:
                    current_price = 0.0
        
        if not current_price or current_price <= 0:
            self.state = BotState.ERROR
            return False
        
        self.start_price = current_price
        
        # Initial allocation
        total_budget = self.config.bot_budget_quote
        base_notional = total_budget * (self.config.alloc_base_pct / 100.0)
        quote_notional = total_budget * (self.config.alloc_quote_pct / 100.0)
        
        # Execute initial market buy for base allocation
        if base_notional >= self.config.min_notional_quote:
            try:
                if self.config.mode == "live" and self.binance_client:
                    order = self.binance_client.place_market_order(
                        self.config.symbol,
                        "BUY",
                        quote_order_qty=base_notional
                    )
                    # Parse fills
                    executed_qty = float(order.get("executedQty", 0))
                    executed_notional = float(order.get("cummulativeQuoteQty", 0))
                    fills = order.get("fills", [])
                    total_fee = sum(float(f.get("commission", 0)) for f in fills)
                    
                    self.base_balance = executed_qty
                    self.quote_balance = quote_notional
                else:
                    # Paper mode simulation
                    fee = base_notional * self.config.fee_rate
                    executed_qty = (base_notional - fee) / current_price
                    executed_notional = base_notional
                    total_fee = fee
                    
                    self.base_balance = executed_qty
                    self.quote_balance = quote_notional
                
                self.initial_base_balance = self.base_balance
                self.initial_quote_balance = self.quote_balance
                self.cycle_start_equity = self.quote_balance + (self.base_balance * current_price)
                
                # Record trade
                Ledger.record_trade(
                    self.db, self.bot_id, self.account_id,
                    "BUY", executed_qty, current_price,
                    fee=total_fee, slot_id=-1, cycle_id=1  # -1 for initial allocation
                )
            except Exception as e:
                logger.error("Error in initial allocation: %s", e)
                self.state = BotState.ERROR
                return False
        
        # Initialize grid slots
        self._init_grid_slots(current_price)
        
        # Reset profit tracking
        self.avg_sell_price = 0.0
        self.total_sold_base = 0.0
        self.total_proceeds_quote = 0.0
        self.avg_buy_cost = 0.0
        self.total_bought_base = 0.0
        self.total_spent_quote = 0.0
        self.rebuy_state = ProfitState.IDLE
        self.resell_state = ProfitState.IDLE
        
        self.state = BotState.RUNNING
        return True
    
    def _init_grid_slots(self, p0: float):
        """Initialize UP and DOWN grid slots"""
        self.up_slots = []
        self.down_slots = []
        
        # UP grid (sell side)
        if self.config.up_grid_steps:
            steps = self.config.up_grid_steps[:self.config.up_grid_count]
        else:
            steps = [self.config.up_grid_step_pct * (i + 1) for i in range(self.config.up_grid_count)]
        
        for i, step_pct in enumerate(steps):
            target_price = p0 * (1 + step_pct / 100.0)
            slot = GridSlot(
                slot_id=i,
                direction="UP",
                target_price=target_price
            )
            self.up_slots.append(slot)
        
        # DOWN grid (buy side)
        if self.config.down_grid_steps:
            steps = self.config.down_grid_steps[:self.config.down_grid_count]
        else:
            steps = [self.config.down_grid_step_pct * (i + 1) for i in range(self.config.down_grid_count)]
        
        for i, step_pct in enumerate(steps):
            target_price = p0 * (1 - step_pct / 100.0)
            slot = GridSlot(
                slot_id=i,
                direction="DOWN",
                target_price=target_price
            )
            self.down_slots.append(slot)
    
    def _calculate_sell_qty(self, slot: GridSlot) -> float:
        """Calculate sell quantity for UP slot"""
        if self.config.up_sell_qty_mode == "FIXED_BASE_QTY":
            return self.config.up_sell_qty_value
        elif self.config.up_sell_qty_mode == "PCT_OF_BASE_BALANCE":
            return self.base_balance * (self.config.up_sell_qty_value / 100.0)
        elif self.config.up_sell_qty_mode == "PCT_OF_INITIAL_BASE":
            return self.initial_base_balance * (self.config.up_sell_qty_value / 100.0)
        return 0.0
    
    def _calculate_buy_notional(self, slot: GridSlot) -> float:
        """Calculate buy notional for DOWN slot"""
        if self.config.down_buy_qty_mode == "FIXED_QUOTE_NOTIONAL":
            return self.config.down_buy_qty_value
        elif self.config.down_buy_qty_mode == "PCT_OF_QUOTE_BALANCE":
            return self.quote_balance * (self.config.down_buy_qty_value / 100.0)
        elif self.config.down_buy_qty_mode == "PCT_OF_INITIAL_QUOTE":
            return self.initial_quote_balance * (self.config.down_buy_qty_value / 100.0)
        return 0.0
    
    def _tick(self):
        """Main tick loop - evaluate all conditions and execute orders"""
        try:
            # Get current price
            current_price = price_hub.get_price(self.config.symbol)
            if not current_price:
                # Try to fetch
                client = self._get_binance_client()
                if client:
                    try:
                        current_price = client.get_ticker_price(self.config.symbol)
                        price_hub.update_price(self.config.symbol, current_price)
                    except:
                        pass
            
            if not current_price or current_price <= 0:
                self.state = BotState.PRICE_STALE
                return
            
            # Check price staleness
            # (Implementation would check last update time)
            
            # Process UP slots
            for slot in self.up_slots:
                if slot.state == SlotState.WAIT:
                    if current_price >= slot.target_price:
                        slot.state = SlotState.TRIGGERED
                        slot.peak_price = current_price
                
                elif slot.state == SlotState.TRIGGERED:
                    slot.peak_price = max(slot.peak_price or current_price, current_price)
                    slot.state = SlotState.TRAIL
                
                elif slot.state == SlotState.TRAIL:
                    slot.peak_price = max(slot.peak_price, current_price)
                    drop_threshold = slot.peak_price * (1 - self.config.up_sell_trailing_pct / 100.0)
                    
                    if current_price <= drop_threshold:
                        # Execute sell
                        qty = self._calculate_sell_qty(slot)
                        if qty > 0 and self.base_balance >= qty:
                            self._execute_sell(slot, qty, current_price)
                
                elif slot.state == SlotState.EXECUTED:
                    pass  # Done
            
            # Process DOWN slots
            for slot in self.down_slots:
                if slot.state == SlotState.WAIT:
                    if current_price <= slot.target_price:
                        slot.state = SlotState.TRIGGERED
                        slot.trough_price = current_price
                
                elif slot.state == SlotState.TRIGGERED:
                    slot.trough_price = min(slot.trough_price or current_price, current_price)
                    slot.state = SlotState.TRAIL
                
                elif slot.state == SlotState.TRAIL:
                    slot.trough_price = min(slot.trough_price, current_price)
                    rise_threshold = slot.trough_price * (1 + self.config.down_buy_trailing_pct / 100.0)
                    
                    if current_price >= rise_threshold:
                        # Execute buy
                        notional = self._calculate_buy_notional(slot)
                        if notional >= self.config.min_notional_quote and self.quote_balance >= notional:
                            self._execute_buy(slot, notional, current_price)
                
                elif slot.state == SlotState.EXECUTED:
                    pass  # Done
            
            # Process profit triggers
            self._process_profit_triggers(current_price)
            
            # Check cycle completion
            self._check_cycle_completion(current_price)
            
        except Exception as e:
            logger.error("Bot %s tick error: %s", self.bot_id, e)
            import traceback
            traceback.print_exc()
    
    def _execute_sell(self, slot: GridSlot, qty: float, expected_price: float):
        """Execute market sell order"""
        if self.order_in_flight:
            return
        
        now = time.time() * 1000
        if now - self.last_order_ts < self.config.cooldown_ms:
            return
        
        self.order_in_flight = True
        try:
            if self.config.mode == "live" and self.binance_client:
                order = self.binance_client.place_market_order(
                    self.config.symbol, "SELL", quantity=qty
                )
                executed_qty = float(order.get("executedQty", 0))
                executed_notional = float(order.get("cummulativeQuoteQty", 0))
                fills = order.get("fills", [])
                total_fee = sum(float(f.get("commission", 0)) for f in fills)
                avg_price = executed_notional / executed_qty if executed_qty > 0 else expected_price
            else:
                # Paper mode
                fee = qty * expected_price * self.config.fee_rate
                executed_qty = qty
                executed_notional = qty * expected_price
                total_fee = fee
                avg_price = expected_price
            
            # Update balances
            self.base_balance -= executed_qty
            self.quote_balance += (executed_notional - total_fee)
            
            # Update slot
            slot.state = SlotState.EXECUTED
            slot.executed_price = avg_price
            slot.executed_qty = executed_qty
            slot.executed_notional = executed_notional
            slot.fee = total_fee
            
            # Update profit tracking
            self.total_sold_base += executed_qty
            self.total_proceeds_quote += (executed_notional - total_fee)
            if self.total_sold_base > 0:
                self.avg_sell_price = self.total_proceeds_quote / self.total_sold_base
            
            # Record trade
            Ledger.record_trade(
                self.db, self.bot_id, self.account_id,
                "SELL", executed_qty, avg_price,
                fee=total_fee, slot_id=slot.slot_id, cycle_id=1
            )
            
            self.last_order_ts = now
            
        except Exception as e:
            logger.error("Error executing sell: %s", e)
        finally:
            self.order_in_flight = False
    
    def _execute_buy(self, slot: GridSlot, notional: float, expected_price: float):
        """Execute market buy order"""
        if self.order_in_flight:
            return
        
        now = time.time() * 1000
        if now - self.last_order_ts < self.config.cooldown_ms:
            return
        
        self.order_in_flight = True
        try:
            if self.config.mode == "live" and self.binance_client:
                order = self.binance_client.place_market_order(
                    self.config.symbol, "BUY", quote_order_qty=notional
                )
                executed_qty = float(order.get("executedQty", 0))
                executed_notional = float(order.get("cummulativeQuoteQty", 0))
                fills = order.get("fills", [])
                total_fee = sum(float(f.get("commission", 0)) for f in fills)
                avg_price = executed_notional / executed_qty if executed_qty > 0 else expected_price
            else:
                # Paper mode
                fee = notional * self.config.fee_rate
                executed_qty = (notional - fee) / expected_price
                executed_notional = notional
                total_fee = fee
                avg_price = expected_price
            
            # Update balances
            self.base_balance += executed_qty
            self.quote_balance -= notional
            
            # Update slot
            slot.state = SlotState.EXECUTED
            slot.executed_price = avg_price
            slot.executed_qty = executed_qty
            slot.executed_notional = executed_notional
            slot.fee = total_fee
            slot.qty = executed_qty
            slot.notional_quote = notional
            
            # Update profit tracking
            self.total_bought_base += executed_qty
            self.total_spent_quote += notional
            if self.total_bought_base > 0:
                self.avg_buy_cost = self.total_spent_quote / self.total_bought_base
            
            # Record trade
            Ledger.record_trade(
                self.db, self.bot_id, self.account_id,
                "BUY", executed_qty, avg_price,
                fee=total_fee, slot_id=slot.slot_id, cycle_id=1
            )
            
            self.last_order_ts = now
            
        except Exception as e:
            logger.error("Error executing buy: %s", e)
        finally:
            self.order_in_flight = False
    
    def _process_profit_triggers(self, current_price: float):
        """Process profit rebuy and resell triggers"""
        # REBUY trigger (after UP sells)
        if self.total_sold_base > 0 and self.avg_sell_price > 0:
            drop_threshold = self.avg_sell_price * (1 - self.config.rebuy_trigger_drop_from_avg_sell_pct / 100.0)
            
            if self.rebuy_state == ProfitState.IDLE:
                if current_price <= drop_threshold:
                    self.rebuy_state = ProfitState.TRAIL
                    self.rebuy_trough = current_price
            
            elif self.rebuy_state == ProfitState.TRAIL:
                self.rebuy_trough = min(self.rebuy_trough, current_price)
                rise_threshold = self.rebuy_trough * (1 + self.config.rebuy_trailing_up_pct / 100.0)
                
                if current_price >= rise_threshold:
                    # Execute rebuy
                    if self.config.rebuy_use_proceeds_mode == "ALL_UP_SELL_PROCEEDS":
                        rebuy_notional = self.total_proceeds_quote
                    else:
                        rebuy_notional = self.quote_balance * (self.config.rebuy_use_proceeds_value / 100.0)
                    
                    if rebuy_notional >= self.config.min_notional_quote:
                        # Similar to buy execution
                        # ... (implementation similar to _execute_buy)
                        self.rebuy_state = ProfitState.DONE
        
        # RESELL trigger (after DOWN buys)
        if self.total_bought_base > 0 and self.avg_buy_cost > 0:
            rise_threshold = self.avg_buy_cost * (1 + self.config.resell_trigger_rise_from_avg_buy_pct / 100.0)
            
            if self.resell_state == ProfitState.IDLE:
                if current_price >= rise_threshold:
                    self.resell_state = ProfitState.TRAIL
                    self.resell_peak = current_price
            
            elif self.resell_state == ProfitState.TRAIL:
                self.resell_peak = max(self.resell_peak, current_price)
                drop_threshold = self.resell_peak * (1 - self.config.resell_trailing_down_pct / 100.0)
                
                if current_price <= drop_threshold:
                    # Execute resell
                    if self.config.resell_sell_mode == "SELL_ALL_DOWN_BOUGHT_BASE":
                        resell_qty = self.total_bought_base
                    else:
                        resell_qty = self.base_balance * (self.config.resell_sell_value / 100.0)
                    
                    if resell_qty > 0 and self.base_balance >= resell_qty:
                        # Similar to sell execution
                        # ... (implementation similar to _execute_sell)
                        self.resell_state = ProfitState.DONE
    
    def _check_cycle_completion(self, current_price: float):
        """Check if cycle should close and start new one"""
        cycle_complete = False
        
        # Cycle closes when rebuy or resell completes
        if self.rebuy_state == ProfitState.DONE or self.resell_state == ProfitState.DONE:
            cycle_complete = True
        
        if cycle_complete:
            # Calculate cycle PnL
            current_equity = self.quote_balance + (self.base_balance * current_price)
            realized_pnl = current_equity - self.cycle_start_equity
            
            # Update bot budget (compound growth)
            self.config.bot_budget_quote = current_equity
            
            # Record snapshot
            from app.services.pnl_service import PnlService
            pnl_data = {
                "total_usd": current_equity,
                "realized": realized_pnl,
                "unrealized": 0.0,
                "daily": 0.0,  # Would need reference
                "monthly": 0.0
            }
            PnlService.save_snapshot(self.db, self.bot_id, self.account_id, pnl_data)
            
            # Start new cycle
            self._initialize_cycle()
    
    def _run_loop(self):
        """Run bot loop in background thread"""
        if not self._initialize_cycle():
            return
        
        while self._running:
            try:
                if self.state == BotState.RUNNING:
                    self._tick()
                
                time.sleep(0.25)  # 250ms tick
            except Exception as e:
                logger.error("Bot %s loop error: %s", self.bot_id, e)
                import traceback
                traceback.print_exc()
                time.sleep(1.0)
    
    def start(self):
        """Start bot"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
    
    def stop(self):
        """Stop bot"""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._thread:
                self._thread.join(timeout=5.0)
    
    def is_running(self) -> bool:
        """Check if bot is running"""
        with self._lock:
            return self._running
    
    def get_status(self) -> dict:
        """Get bot status"""
        return {
            "bot_id": self.bot_id,
            "account_id": self.account_id,
            "symbol": self.config.symbol,
            "state": self.state.value if isinstance(self.state, Enum) else str(self.state),
            "cycle_id": self.cycle_id,
            "mode": self.config.mode
        }
    
    def get_all_slots(self) -> List[GridSlot]:
        """Get all slots (UP + DOWN)"""
        with self._lock:
            return self.up_slots.copy() + self.down_slots.copy()


