"""
Bot Manager - Registry and Multi-Account Support
VERSION: v3.0 - DCA Bot V3 support
"""
import json
import logging
import asyncio
from typing import Dict, Optional, Tuple, Union
from app.bot.models import BotConfig, Slot
from app.bot.engine import BotEngine
try:
    from app.bot.dca_engine_v3 import DCABotEngineV3
except ImportError:
    DCABotEngineV3 = None  # DCA V3 not available
try:
    from app.bot.dca_worker_v3 import get_dca_worker
except ImportError:
    get_dca_worker = None  # DCA V3 worker not available
from sqlalchemy.orm import Session
from app.db.models import Bot

logger = logging.getLogger(__name__)


class BotManager:
    """Bot registry manager - multi-account support"""

    def __init__(self):
        self._bots: Dict[Tuple[int, int], Union[BotEngine, 'DCABotEngineV3']] = {}  # (account_id, bot_id) -> Engine
        self._bot_types: Dict[Tuple[int, int], str] = {}  # (account_id, bot_id) -> bot_type

    def get_bot(self, bot_id: int, account_id: int) -> Optional[Union[BotEngine, 'DCABotEngineV3']]:
        """Get bot engine instance - signature: get_bot(bot_id, account_id)"""
        key = (account_id, bot_id)
        return self._bots.get(key)
    
    def get_bot_type(self, bot_id: int, account_id: int) -> Optional[str]:
        """Get bot type"""
        key = (account_id, bot_id)
        return self._bot_types.get(key, "legacy")  # Default to legacy

    def register_bot(self, bot_id: int, account_id: int, engine: Union[BotEngine, 'DCABotEngineV3'], bot_type: str = "legacy"):
        """Register bot engine"""
        key = (account_id, bot_id)
        self._bots[key] = engine
        self._bot_types[key] = bot_type

    def unregister_bot(self, bot_id: int, account_id: int):
        """Unregister bot"""
        key = (account_id, bot_id)
        if key in self._bots:
            engine = self._bots[key]
            bot_type = self._bot_types.get(key, "legacy")
            
            # Stop engine based on type
            if bot_type == "dca":
                # DCA V3 uses async worker - stop via worker
                # Note: This is sync method, so we can't await
                # Worker will handle cleanup when bot status changes to stopped
                logger.info(f"Unregistering DCA V3 bot {bot_id} - worker will handle cleanup")
            elif hasattr(engine, 'is_running') and engine.is_running():
                engine.stop()
            
            del self._bots[key]
            if key in self._bot_types:
                del self._bot_types[key]

    def load_bot_from_db(self, db: Session, bot_id: int, account_id: int) -> Optional[Union[BotEngine, 'DCABotEngineV3']]:
        """Load bot from DB and create engine - supports both legacy and DCA V3"""
        bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
        if not bot:
            return None

        existing = self.get_bot(bot_id, account_id)
        if existing:
            return existing

        # Parse config JSON
        try:
            config_data = json.loads(bot.config_json or "{}")
        except Exception:
            config_data = {}
        
        # Check bot type
        bot_type = config_data.get("bot_type", "legacy")
        
        # DCA V3 bot
        if bot_type == "dca":
            return self._load_dca_v3_bot(bot, config_data, db)
        
        # Legacy bot (existing logic)
        return self._load_legacy_bot(bot, config_data, db)
    
    def _load_dca_v3_bot(self, bot: Bot, config_data: dict, db: Session) -> Optional['DCABotEngineV3']:
        """Load DCA V3 bot"""
        if DCABotEngineV3 is None:
            logger.error(f"DCA V3 engine not available - cannot load bot {bot.id}")
            return None
        try:
            engine = DCABotEngineV3(bot.id, bot.account_id, config_data, db)
            self.register_bot(bot.id, bot.account_id, engine, bot_type="dca")
            logger.info(f"DCA V3 Bot {bot.id} loaded successfully")
            return engine
        except Exception as e:
            logger.error(f"Error loading DCA V3 bot {bot.id}: {e}", exc_info=True)
            return None
    
    def _load_legacy_bot(self, bot: Bot, config_data: dict, db: Session) -> Optional[BotEngine]:
        """Load legacy bot (existing logic)"""
        
        # Remove fields that don't belong to BotConfig
        # CRITICAL: account_id, bot_id, and other non-BotConfig fields must be removed
        valid_fields = {'symbol', 'base_asset', 'quote_asset', 'grid_count', 'upper_price', 'lower_price', 'order_amount', 'mode'}
        filtered_data = {k: v for k, v in config_data.items() if k in valid_fields}
        
        # Explicitly remove account_id and bot_id if they exist (defensive)
        # CRITICAL: These fields must NEVER be passed to BotConfig
        filtered_data.pop('account_id', None)
        filtered_data.pop('bot_id', None)
        filtered_data.pop('id', None)
        filtered_data.pop('accountId', None)  # camelCase variant
        filtered_data.pop('botId', None)  # camelCase variant
        
        # Log filtered data for debugging (before creating BotConfig)
        logger.debug(f"[load_bot_from_db] Bot {bot_id}: filtered_data keys: {list(filtered_data.keys())}")
        logger.debug(f"[load_bot_from_db] Bot {bot_id}: filtered_data: {filtered_data}")
        
        # Note: We don't set defaults in filtered_data anymore - we'll extract them when creating BotConfig
        
        # Create config with ONLY valid BotConfig fields (explicit, no unpacking)
        # CRITICAL: Do NOT use **filtered_data or **config_data - only pass explicit fields
        try:
            # Extract values explicitly - never use **dict unpacking
            symbol_val = filtered_data.get('symbol') or bot.symbol or 'BTCUSDT'
            base_asset_val = filtered_data.get('base_asset')
            if not base_asset_val:
                # Extract from symbol
                sym = symbol_val
                base_asset_val = sym.replace('USDT', '').replace('BUSD', '').replace('FDUSD', '')
            
            quote_asset_val = filtered_data.get('quote_asset')
            if not quote_asset_val:
                sym = symbol_val
                if 'BUSD' in sym:
                    quote_asset_val = 'BUSD'
                elif 'FDUSD' in sym:
                    quote_asset_val = 'FDUSD'
                else:
                    quote_asset_val = 'USDT'
            
            config = BotConfig(
                symbol=symbol_val,
                base_asset=base_asset_val,
                quote_asset=quote_asset_val,
                grid_count=filtered_data.get('grid_count', 10),
                upper_price=filtered_data.get('upper_price', 0.0),
                lower_price=filtered_data.get('lower_price', 0.0),
                order_amount=filtered_data.get('order_amount', 0.0),
                mode=filtered_data.get('mode', bot.mode or 'paper')
            )
            
            # Override with DB values
            config.symbol = bot.symbol or config.symbol
            config.mode = bot.mode or config.mode
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"[BotConfig Error] Bot {bot_id}, Account {account_id}")
            logger.error(f"[BotConfig Error] Exception: {type(e).__name__}: {e}")
            logger.error(f"[BotConfig Error] Config data (raw): {config_data}")
            logger.error(f"[BotConfig Error] Filtered data: {filtered_data}")
            logger.error(f"[BotConfig Error] Full traceback:\n{error_trace}")
            logger.error(f"[BotConfig Error] BotConfig fields expected: symbol, base_asset, quote_asset, grid_count, upper_price, lower_price, order_amount, mode")
            raise

        # Create engine with explicit positional arguments
        try:
            logger.debug(f"[BotEngine] Creating engine: bot_id={bot_id}, account_id={account_id}, mode={config.mode}")
            logger.debug(f"[BotEngine] Config type: {type(config)}")
            logger.debug(f"[BotEngine] Config fields: {config.__dict__ if hasattr(config, '__dict__') else 'N/A'}")
            
            # Pass db session to engine for live mode API key access
            engine = BotEngine(bot_id, account_id, config, db=db)
            logger.debug(f"[BotEngine] Engine created successfully")
        except TypeError as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"[BotEngine Error] Bot {bot_id}, Account {account_id}")
            logger.error(f"[BotEngine Error] TypeError: {e}")
            logger.error(f"[BotEngine Error] BotConfig type: {type(config)}")
            logger.error(f"[BotEngine Error] BotConfig fields: {config.__dict__ if hasattr(config, '__dict__') else 'N/A'}")
            logger.error(f"[BotEngine Error] BotEngine.__init__ signature: (bot_id: int, account_id: int, config: BotConfig)")
            logger.error(f"[BotEngine Error] Arguments passed: bot_id={bot_id} (type: {type(bot_id).__name__}), account_id={account_id} (type: {type(account_id).__name__}), config={config} (type: {type(config).__name__})")
            logger.error(f"[BotEngine Error] Full traceback:\n{error_trace}")
            raise
        self.register_bot(bot_id, account_id, engine, bot_type="legacy")
        
        if bot.status == "running":
            engine.start()

        return engine

    def get_all_bots(self) -> Dict[Tuple[int, int], BotEngine]:
        """Get all registered bots"""
        return self._bots.copy()


# Global instance
bot_manager = BotManager()
