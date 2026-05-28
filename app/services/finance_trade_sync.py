"""
FILE: finance_trade_sync.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: Trade sync service - Binance myTrades'den incremental çekme
"""
from __future__ import annotations
from typing import Dict, List, Optional
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc
import httpx
import json

from app.db.models import Account, TradeNormalized, Bot

logger = logging.getLogger(__name__)


class TradeSyncService:
    """Binance myTrades'den incremental trade sync"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def sync_account_trades(self, account_id: int, limit: int = 1000) -> Dict:
        """
        Sync trades for an account from Binance
        Returns: {synced_count, new_count, error}
        """
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"error": "Account not found", "synced_count": 0, "new_count": 0}

        from app.services.test_account import is_test_account
        if is_test_account(account_id, self.db):
            return {"synced_count": 0, "new_count": 0}
        
        try:
            # Get account keys
            from app.services.binance_assets import get_account_keys
            keys = await get_account_keys(account_id, self.db)
            
            # Get last synced trade time (with 5min buffer to avoid missing trades)
            last_trade = self.db.query(TradeNormalized).filter(
                TradeNormalized.account_id == account_id
            ).order_by(desc(TradeNormalized.time)).first()
            
            start_time = None
            if last_trade:
                # Start from last trade time - 5min buffer (to catch any missed trades)
                # Binance myTrades can have slight delays, so buffer helps
                buffer_seconds = 300  # 5 minutes
                start_time = int((last_trade.time.timestamp() - buffer_seconds) * 1000)
            else:
                # First sync: get last 90 days
                from datetime import timedelta
                ninety_days_ago = datetime.utcnow() - timedelta(days=90)
                start_time = int(ninety_days_ago.timestamp() * 1000)
            
            # Fetch trades from Binance (hesap bot sembollerini mutlaka dahil et – bot işlemleri İşlemler panelinde görünsün)
            trades_data = await self._fetch_binance_trades(keys, account_id, start_time, limit)
            
            if not trades_data:
                return {"error": "Failed to fetch trades", "synced_count": 0, "new_count": 0}
            
            # Process and save trades with dedupe
            new_count = 0
            skipped_count = 0
            added_trades: List[TradeNormalized] = []
            
            for trade_data in trades_data:
                trade_id = str(trade_data.get("id", ""))
                symbol = trade_data.get("symbol", "").upper()
                
                if not trade_id or not symbol:
                    continue
                
                # Check if already exists (composite unique: account_id, symbol, trade_id)
                existing = self.db.query(TradeNormalized).filter(
                    TradeNormalized.account_id == account_id,
                    TradeNormalized.symbol == symbol,
                    TradeNormalized.trade_id == trade_id
                ).first()
                
                if existing:
                    skipped_count += 1
                    continue  # Skip duplicates
                
                # Create normalized trade
                normalized_trade = self._normalize_trade(trade_data, account_id)
                if normalized_trade:
                    try:
                        self.db.add(normalized_trade)
                        self.db.flush()  # Flush to catch unique constraint violations early
                        added_trades.append(normalized_trade)
                        new_count += 1
                    except Exception as e:
                        # Handle unique constraint violation gracefully
                        if "uq_trades_account_symbol_trade" in str(e) or "unique" in str(e).lower():
                            skipped_count += 1
                            self.db.rollback()
                            continue
                        else:
                            raise
            
            self.db.commit()

            try:
                from app.services.transaction_history_file_store import (
                    is_tx_history_bootstrapped,
                    ledger_has_buysell,
                    rebuild_from_db,
                    upsert_trade_fill,
                )
                import json as _json

                if added_trades:
                    bot_names: Dict[int, str] = {}
                    bot_ids = {t.bot_id for t in added_trades if t.bot_id}
                    if bot_ids:
                        for b in self.db.query(Bot).filter(Bot.id.in_(bot_ids)).all():
                            try:
                                cfg = _json.loads(b.config_json or "{}")
                                bot_names[b.id] = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
                            except Exception:
                                bot_names[b.id] = f"Bot #{b.id}"
                    for t in added_trades:
                        upsert_trade_fill(
                            account_id,
                            trade_id=str(t.trade_id),
                            order_id=t.order_id,
                            time=t.time,
                            side=t.side or "",
                            symbol=t.symbol or "",
                            qty=float(t.qty or 0),
                            price=float(t.price or 0),
                            quote_qty=float(t.quote_qty or 0),
                            commission=float(t.commission or 0),
                            commission_asset=t.commission_asset or "USDT",
                            is_maker=bool(t.is_maker),
                            bot_id=t.bot_id,
                            bot_name=bot_names.get(t.bot_id) if t.bot_id else None,
                        )
                if not is_tx_history_bootstrapped(account_id) or not ledger_has_buysell(account_id):
                    rebuild_from_db(self.db, account_id, days=365)
            except Exception as file_ex:
                logger.debug("[TradeSync] tx file store account_id=%s: %s", account_id, file_ex)

            return {
                "synced_count": len(trades_data),
                "new_count": new_count,
                "error": None
            }
            
        except Exception as e:
            from app.services.binance_assets import ACCOUNT_KEYS_MISSING, ACCOUNT_KEYS_EMPTY
            def _is_keys_missing(ex):
                if ex is None:
                    return False
                s = str(ex).strip()
                a = getattr(ex, "args", ()) or ()
                for code in (ACCOUNT_KEYS_MISSING, ACCOUNT_KEYS_EMPTY):
                    if code in s or any(code in str(x) for x in a):
                        return True
                return _is_keys_missing(getattr(ex, "__cause__", None))
            if _is_keys_missing(e):
                logger.info("[TradeSync] Account %s: API keys not configured, skipping trade sync.", account_id)
            else:
                logger.error("[TradeSync] Error syncing trades for account %s: %s", account_id, e)
            self.db.rollback()
            return {"error": str(e), "synced_count": 0, "new_count": 0}
    
    async def _fetch_binance_trades(self, keys, account_id: int, start_time: Optional[int] = None, limit: int = 1000) -> List[Dict]:
        """Fetch trades from Binance myTrades. Hesap bot sembollerini önce çek (bot işlemleri İşlemler panelinde görünsün)."""
        try:
            import httpx
            from app.services.binance_spot import _signed_request
            from app.services.market_data import get_symbols

            # Bu hesabın bot sembollerini mutlaka dahil et (bot alım/satım İşlemler’de görünsün)
            bot_raw = [(b.symbol or "").upper().strip() for b in self.db.query(Bot).filter(Bot.account_id == account_id).all()]
            bot_symbols = list(dict.fromkeys(s for s in bot_raw if s and s.endswith("USDT")))

            common_symbols = get_symbols("usdt")
            if not common_symbols:
                logger.warning("[TradeSync] Symbol cache empty, using common + bot symbols")
                common_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

            # Rate limit: max 40 symbols (myTrades = 10 weight each = 400 weight per sync; 6000/min limit)
            max_symbols = 40
            extra = [s for s in common_symbols if s not in bot_symbols][: max(0, max_symbols - len(bot_symbols))]
            symbols_to_fetch = list(bot_symbols) + extra
            if bot_symbols:
                logger.info("[TradeSync] Including bot symbols for account %s: %s", account_id, bot_symbols[:20])

            params = {
                "limit": limit
            }
            
            if start_time:
                params["startTime"] = start_time

            all_trades = []
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                for i, symbol in enumerate(symbols_to_fetch):
                    try:
                        # Spread requests to avoid 429 (Binance 6000 weight/min). myTrades = 10 weight.
                        if i > 0:
                            await asyncio.sleep(0.25)
                        trade_params = {"symbol": symbol, **params}
                        trades = await _signed_request(http_client, "GET", "/api/v3/myTrades", keys, trade_params)
                        if trades and isinstance(trades, list):
                            all_trades.extend(trades)
                    except httpx.HTTPStatusError as e:
                        sc = getattr(e.response, "status_code", None)
                        body = (getattr(e.response, "text") or "")[:200]
                        try:
                            b = json.loads(body) if body else {}
                            invalid_key = sc == 401 or (sc == 400 and isinstance(b, dict) and b.get("code") == -2015)
                        except Exception:
                            invalid_key = sc == 401
                        if sc == 429:
                            logger.warning(
                                "[TradeSync] Binance 429 (weight limit) for account %s; returning %s trades so far.",
                                account_id, len(all_trades),
                            )
                            break
                        if invalid_key:
                            logger.warning(
                                "[TradeSync] Invalid API-key/IP/permissions (401/-2015) for account %s; stopping myTrades fetch.",
                                account_id,
                            )
                            break
                        if "no trades" not in str(e).lower() and "404" not in str(e):
                            logger.debug("[TradeSync] Error fetching %s: %s", symbol, e)
                        continue
                    except Exception as e:
                        if "429" in str(e) or "weight" in str(e).lower():
                            logger.warning("[TradeSync] Binance rate limit for account %s; returning %s trades so far.", account_id, len(all_trades))
                            break
                        if "no trades" not in str(e).lower() and "404" not in str(e):
                            logger.debug("[TradeSync] Error fetching %s: %s", symbol, e)
                        continue
            
            # Sort by time (ascending for chronological order)
            all_trades.sort(key=lambda x: x.get("time", 0))
            
            return all_trades
            
        except Exception as e:
            logger.error(f"[TradeSync] Error fetching Binance trades: {e}")
            return []
    
    def _normalize_trade(self, trade_data: Dict, account_id: int) -> Optional[TradeNormalized]:
        """Normalize Binance trade data to TradeNormalized"""
        try:
            trade_id = str(trade_data.get("id", ""))
            if not trade_id:
                return None
            
            symbol = trade_data.get("symbol", "")
            order_id = str(trade_data.get("orderId", ""))
            side = "BUY" if trade_data.get("isBuyer", False) else "SELL"
            price = float(trade_data.get("price", 0))
            qty = float(trade_data.get("qty", 0))
            quote_qty = float(trade_data.get("quoteQty", 0))
            commission = float(trade_data.get("commission", 0))
            commission_asset = trade_data.get("commissionAsset", "USDT")
            time_ms = trade_data.get("time", 0)
            is_maker = trade_data.get("isMaker", False)
            
            # Convert time
            trade_time = datetime.utcfromtimestamp(time_ms / 1000.0)
            
            # Try to match with bot via orderId
            bot_id = None
            if order_id:
                # Check if any bot has this orderId in its execution logs
                # Match by order_id and symbol within same account
                from app.db.models import Bot
                matching_bot = self.db.query(Bot).filter(
                    Bot.account_id == account_id,
                    Bot.symbol == symbol
                ).first()
                
                # If we find a bot for this symbol, check if order_id matches
                # For now, we'll use symbol-based matching (more reliable)
                # TODO: Store order_id in bot execution logs for exact matching
                if matching_bot:
                    # Check if order was placed within bot's active period
                    # Simple heuristic: if bot is running and symbol matches, likely bot trade
                    if matching_bot.status == "running":
                        bot_id = matching_bot.id
            
            # Create normalized trade
            normalized = TradeNormalized(
                account_id=account_id,
                symbol=symbol,
                trade_id=trade_id,
                order_id=order_id if order_id else None,
                side=side,
                price=price,
                qty=qty,
                quote_qty=quote_qty,
                commission=commission,
                commission_asset=commission_asset,
                time=trade_time,
                is_maker=is_maker,
                bot_id=bot_id,
                tags_json=None
            )
            
            return normalized
            
        except Exception as e:
            logger.error(f"[TradeSync] Error normalizing trade: {e}")
            return None
    
    async def sync_all_accounts(self) -> Dict:
        """Sync trades for all accounts"""
        accounts = self.db.query(Account).all()
        results = {}
        
        for account in accounts:
            result = await self.sync_account_trades(account.id)
            results[account.id] = result
        
        return results
