"""
Bot Engine - Trading Bot Core
VERSION: v2 - Binance API integration with comprehensive error handling
"""
import asyncio
import threading
import logging
import time
from typing import List, Optional
from app.bot.models import BotConfig, Slot
from app.services.price_hub import price_hub
# Optional Binance imports - will be added later
try:
    from app.services.binance_client import (
        BinanceClient,
        BinanceAPIError,
        InsufficientBalanceError,
        InvalidAPIKeyError,
        NetworkError
    )
except ImportError:
    BinanceClient = None
    BinanceAPIError = Exception
    InsufficientBalanceError = Exception
    InvalidAPIKeyError = Exception
    NetworkError = Exception
from app.services.encryption import decrypt_account_api_key, decrypt_account_api_secret
from sqlalchemy.orm import Session
from app.db.models import Account

logger = logging.getLogger(__name__)


class BotEngine:
    """Bot engine - tick loop for trading logic with Binance API integration"""

    def __init__(self, bot_id: int, account_id: int, config: BotConfig, db: Optional[Session] = None):
        self.bot_id = bot_id
        self.account_id = account_id
        self.config = config
        self.db = db
        self.slots: List[Slot] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Binance client (lazy load - only for live mode)
        self.binance_client: Optional[BinanceClient] = None
        self.account: Optional[Account] = None
        
        # Error tracking
        self.last_error: Optional[str] = None
        self.error_count = 0
        self.max_errors = 10  # Stop bot after too many errors

    def _init_slots(self):
        """Initialize grid slots"""
        if not self.config.upper_price or not self.config.lower_price:
            return
        
        if self.config.upper_price <= self.config.lower_price:
            return

        self.slots = []
        price_range = self.config.upper_price - self.config.lower_price
        slot_size = price_range / self.config.grid_count

        for i in range(self.config.grid_count):
            slot_price = self.config.lower_price + (i * slot_size)
            self.slots.append(Slot(
                slot_id=i,
                price=slot_price,
                qty=0.0,
                filled=False
            ))

    def _get_binance_client(self) -> Optional[BinanceClient]:
        """Get or create Binance client (lazy load)"""
        if self.binance_client:
            return self.binance_client
        
        # Only for live mode
        if self.config.mode != "live":
            return None
        
        # Load account if not loaded
        if not self.account and self.db:
            self.account = self.db.query(Account).filter(Account.id == self.account_id).first()
        
        if not self.account:
            logger.error(f"Bot {self.bot_id}: Account {self.account_id} not found")
            return None
        
        # Check if API keys exist
        if not self.account.api_key_enc or not self.account.api_secret_enc:
            logger.error(f"Bot {self.bot_id}: Live mode requires API keys, but account {self.account_id} has no API keys")
            self.last_error = "Live mode requires Binance API keys"
            return None
        
        try:
            # Decrypt and create client
            api_key = decrypt_account_api_key(self.account_id, self.account.api_key_enc)
            api_secret = decrypt_account_api_secret(self.account_id, self.account.api_secret_enc)
            
            if not api_key or not api_secret:
                logger.error(f"Bot {self.bot_id}: Failed to decrypt API keys")
                self.last_error = "Failed to decrypt API keys"
                return None
            
            self.binance_client = BinanceClient(api_key, api_secret, testnet=False)
            logger.info(f"Bot {self.bot_id}: Binance client created successfully")
            return self.binance_client
            
        except InvalidAPIKeyError as e:
            logger.error(f"Bot {self.bot_id}: Invalid API keys: {e.message}")
            self.last_error = f"Invalid API keys: {e.message}"
            return None
        except NetworkError as e:
            logger.error(f"Bot {self.bot_id}: Network error: {e.message}")
            self.last_error = f"Network error: {e.message}"
            return None
        except Exception as e:
            logger.error(f"Bot {self.bot_id}: Error creating Binance client: {e}")
            self.last_error = f"Error creating Binance client: {str(e)}"
            return None
    
    def _check_balance_before_order(self, side: str, quantity: float, quote_qty: float) -> tuple[bool, str]:
        """Check if account has sufficient balance before placing order"""
        if self.config.mode != "live":
            return True, ""  # Paper mode - always allow
        
        client = self._get_binance_client()
        if not client:
            return False, self.last_error or "Binance client not available"
        
        try:
            if side == "BUY":
                # Check quote asset balance
                balance = client.get_balance(self.config.quote_asset)
                if balance < quote_qty:
                    return False, f"Insufficient {self.config.quote_asset} balance. Required: {quote_qty:.2f}, Available: {balance:.2f}"
            elif side == "SELL":
                # Check base asset balance
                balance = client.get_balance(self.config.base_asset)
                if balance < quantity:
                    return False, f"Insufficient {self.config.base_asset} balance. Required: {quantity:.8f}, Available: {balance:.8f}"
            
            return True, ""
        except Exception as e:
            logger.error(f"Bot {self.bot_id}: Error checking balance: {e}")
            return False, f"Error checking balance: {str(e)}"
    
    def _execute_order(self, side: str, quantity: Optional[float] = None, quote_qty: Optional[float] = None) -> Optional[dict]:
        """Execute order with comprehensive error handling"""
        if self.config.mode != "live":
            # Paper mode - simulate order
            logger.info(f"Bot {self.bot_id}: Paper mode - simulating {side} order")
            return {
                "orderId": f"paper_{int(time.time() * 1000)}",
                "executedQty": str(quantity or 0),
                "cummulativeQuoteQty": str(quote_qty or 0),
                "status": "FILLED",
                "fills": []
            }
        
        client = self._get_binance_client()
        if not client:
            logger.error(f"Bot {self.bot_id}: Cannot execute order - Binance client not available")
            return None
        
        # Check balance before order
        if side == "BUY" and quote_qty:
            sufficient, error_msg = self._check_balance_before_order(side, 0, quote_qty)
            if not sufficient:
                logger.warning(f"Bot {self.bot_id}: {error_msg}")
                self.last_error = error_msg
                return None
        elif side == "SELL" and quantity:
            sufficient, error_msg = self._check_balance_before_order(side, quantity, 0)
            if not sufficient:
                logger.warning(f"Bot {self.bot_id}: {error_msg}")
                self.last_error = error_msg
                return None
        
        try:
            result = client.place_market_order(
                symbol=self.config.symbol,
                side=side,
                quantity=quantity,
                quote_order_qty=quote_qty
            )
            logger.info(f"Bot {self.bot_id}: {side} order executed successfully: {result.get('orderId')}")
            self.error_count = 0  # Reset error count on success
            self.last_error = None
            return result
            
        except InsufficientBalanceError as e:
            logger.error(f"Bot {self.bot_id}: Insufficient balance: {e.message}")
            self.last_error = f"Insufficient balance: {e.message}"
            self.error_count += 1
            return None
        except InvalidAPIKeyError as e:
            logger.error(f"Bot {self.bot_id}: Invalid API key: {e.message}")
            self.last_error = f"Invalid API key: {e.message}"
            self.error_count += 1
            # Stop bot on invalid API key
            self.stop()
            return None
        except NetworkError as e:
            logger.error(f"Bot {self.bot_id}: Network error: {e.message}")
            self.last_error = f"Network error: {e.message}"
            self.error_count += 1
            return None
        except BinanceAPIError as e:
            logger.error(f"Bot {self.bot_id}: Binance API error: {e.message} (code: {e.code})")
            self.last_error = f"Binance API error: {e.message}"
            self.error_count += 1
            return None
        except Exception as e:
            logger.error(f"Bot {self.bot_id}: Unexpected error executing order: {e}")
            self.last_error = f"Unexpected error: {str(e)}"
            self.error_count += 1
            return None
    
    def _tick(self):
        """Main tick loop"""
        # Placeholder for trading logic
        # In real implementation, this would:
        # 1. Get current price
        # 2. Check grid slots
        # 3. Execute orders if needed
        # 4. Update slots
        
        # Check error count - stop bot if too many errors
        if self.error_count >= self.max_errors:
            logger.error(f"Bot {self.bot_id}: Too many errors ({self.error_count}), stopping bot")
            self.stop()
            return
        
        # For now, just log that bot is running
        # Real trading logic will be implemented based on bot type
        pass

    def _run_loop(self):
        """Run bot loop in background thread"""
        self._init_slots()
        
        while self._running:
            try:
                self._tick()
                # Sleep to prevent tight loop
                threading.Event().wait(1.0)  # 1 second tick
            except Exception as e:
                print(f"Bot {self.bot_id} error: {e}")
                threading.Event().wait(5.0)

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

    def get_slots(self) -> List[Slot]:
        """Get current slots"""
        with self._lock:
            return self.slots.copy()

    def get_status(self) -> dict:
        """Get bot status"""
        return {
            "bot_id": self.bot_id,
            "account_id": self.account_id,
            "symbol": self.config.symbol,
            "status": "running" if self.is_running() else "stopped",
            "slot_count": len(self.slots),
            "mode": self.config.mode
        }

