"""
FILE: finance_pnl_calculator.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: Comprehensive PnL calculator - realized + unrealized, positions, aggregates
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import timedelta
import json

from app.db.models import Account, TradeNormalized, PnlRealized, Bot
from app.services.price_hub import price_hub

logger = logging.getLogger(__name__)


class FinancePnlCalculator:
    """Comprehensive PnL calculator for finance module"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def calculate_realized_pnl(self, account_id: int, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict:
        """
        Calculate realized PnL using Average Cost method
        Returns: {realized_pnl, fees, trades_count, by_symbol, by_bot}
        """
        # Sadece spot/bot alım satım (BUY/SELL); yatırım/çekim hariç
        query = self.db.query(TradeNormalized).filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"])
        )
        if start_time:
            query = query.filter(TradeNormalized.time >= start_time)
        if end_time:
            query = query.filter(TradeNormalized.time <= end_time)
        
        trades = query.order_by(TradeNormalized.time.asc()).all()
        
        # Track positions per symbol
        positions: Dict[str, Dict] = {}  # symbol -> {avg_cost, qty, total_cost}
        realized_pnl = 0.0
        total_fees_usd = 0.0
        
        by_symbol: Dict[str, Dict] = {}
        by_bot: Dict[int, Dict] = {}
        
        def _commission_to_usd(commission: float, commission_asset: str) -> float:
            """Convert commission to USD using Binance price_hub (e.g. BNB -> BNBUSDT)."""
            if commission <= 0:
                return 0.0
            asset = (commission_asset or "USDT").strip().upper()
            if not asset:
                return 0.0
            STABLES = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"]
            if asset in STABLES:
                return commission
            # Try {asset}USDT (price = USDT per 1 unit)
            sym = f"{asset}USDT"
            p = price_hub.get_price(sym)
            if p is not None and p > 0:
                return commission * float(p)
            # Try USDT{asset} (e.g. USDTTRY: price = TRY per 1 USDT -> usd = amount / price)
            sym_inv = f"USDT{asset}"
            p = price_hub.get_price(sym_inv)
            if p is not None and p > 0:
                return commission / float(p)
            # Fallback: use trade's quote if same symbol (e.g. commission in BNB, no BNBUSDT in cache)
            return commission  # unconverted; prefer logging in production

        for trade in trades:
            symbol = trade.symbol
            side = trade.side
            price = trade.price
            qty = trade.qty
            commission = trade.commission
            commission_asset = (trade.commission_asset or "USDT").strip()
            
            fee_usd = _commission_to_usd(commission, commission_asset)
            total_fees_usd += fee_usd
            
            # Initialize symbol tracking
            if symbol not in positions:
                positions[symbol] = {"avg_cost": 0.0, "qty": 0.0, "total_cost": 0.0}
            if symbol not in by_symbol:
                by_symbol[symbol] = {"pnl": 0.0, "fees": 0.0, "count": 0}
            if trade.bot_id and trade.bot_id not in by_bot:
                by_bot[trade.bot_id] = {"pnl": 0.0, "fees": 0.0, "count": 0}
            
            # Komisyon her işlemde (alış ve satış) hesaplanır; dönem filtresine göre toplam doğru olur
            by_symbol[symbol]["fees"] += fee_usd
            if trade.bot_id:
                by_bot[trade.bot_id]["fees"] += fee_usd
            
            pos = positions[symbol]
            
            if side == "BUY":
                # Add to position
                new_cost = price * qty
                pos["total_cost"] += new_cost
                pos["qty"] += qty
                if pos["qty"] > 0:
                    pos["avg_cost"] = pos["total_cost"] / pos["qty"]
            elif side == "SELL":
                # Realize PnL
                if pos["qty"] > 0:
                    pnl = (price - pos["avg_cost"]) * qty
                    realized_pnl += pnl
                    pos["qty"] -= qty
                    pos["total_cost"] = pos["avg_cost"] * pos["qty"]  # Update cost basis
                    
                    by_symbol[symbol]["pnl"] += pnl
                    by_symbol[symbol]["count"] += 1
                    if trade.bot_id:
                        by_bot[trade.bot_id]["pnl"] += pnl
                        by_bot[trade.bot_id]["count"] += 1
        
        # Count all trades (no grouping)
        trades_count = len(trades)
        
        return {
            "realized_pnl": realized_pnl,
            "fees": total_fees_usd,
            "trades_count": trades_count,  # Count all trades, not grouped
            "by_symbol": by_symbol,
            "by_bot": by_bot
        }
    
    def calculate_unrealized_pnl(self, account_id: int) -> Dict:
        """
        Calculate unrealized PnL from current positions
        Returns: {unrealized_pnl, positions}
        """
        # Get current positions (from trades or positions table)
        positions_data = self._get_current_positions(account_id)
        
        unrealized_pnl = 0.0
        positions = []
        
        for symbol, pos_data in positions_data.items():
            avg_cost = pos_data["avg_cost"]
            qty = pos_data["qty"]
            
            if qty <= 0:
                continue
            
            # Get current price
            current_price = price_hub.get_price(symbol)
            if not current_price:
                # Try to get from last trade
                last_trade = self.db.query(TradeNormalized).filter(
                    TradeNormalized.account_id == account_id,
                    TradeNormalized.symbol == symbol
                ).order_by(desc(TradeNormalized.time)).first()
                if last_trade:
                    current_price = last_trade.price
                else:
                    current_price = avg_cost  # Fallback
            
            unrealized = (current_price - avg_cost) * qty
            unrealized_pnl += unrealized
            
            positions.append({
                "symbol": symbol,
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "unrealized_pnl": unrealized
            })
        
        return {
            "unrealized_pnl": unrealized_pnl,
            "positions": positions
        }
    
    def _get_current_positions(self, account_id: int) -> Dict[str, Dict]:
        """Get current positions from trades (Average Cost method)"""
        trades = self.db.query(TradeNormalized).filter(
            TradeNormalized.account_id == account_id
        ).order_by(TradeNormalized.time.asc()).all()
        
        positions: Dict[str, Dict] = {}
        
        for trade in trades:
            symbol = trade.symbol
            side = trade.side
            price = trade.price
            qty = trade.qty
            
            if symbol not in positions:
                positions[symbol] = {"avg_cost": 0.0, "qty": 0.0, "total_cost": 0.0}
            
            pos = positions[symbol]
            
            if side == "BUY":
                new_cost = price * qty
                pos["total_cost"] += new_cost
                pos["qty"] += qty
                if pos["qty"] > 0:
                    pos["avg_cost"] = pos["total_cost"] / pos["qty"]
            elif side == "SELL":
                pos["qty"] -= qty
                pos["total_cost"] = pos["avg_cost"] * pos["qty"]
        
        # Filter out zero positions
        return {k: v for k, v in positions.items() if v["qty"] > 0}
    
    def calculate_period_pnl(self, account_id: int, period_type: str, period_start: datetime, period_end: datetime) -> Optional[PnlRealized]:
        """
        Calculate and cache period PnL (daily/weekly/monthly)
        Returns: PnlRealized record
        """
        # Check if already calculated
        existing = self.db.query(PnlRealized).filter(
            PnlRealized.account_id == account_id,
            PnlRealized.period_type == period_type,
            PnlRealized.period_start == period_start
        ).first()
        
        # Calculate
        pnl_data = self.calculate_realized_pnl(account_id, period_start, period_end)
        
        if existing:
            # Update
            existing.realized_pnl_usd = pnl_data["realized_pnl"]
            existing.fees_usd = pnl_data["fees"]
            existing.trades_count = pnl_data["trades_count"]
            existing.by_symbol_json = json.dumps(pnl_data["by_symbol"])
            existing.by_bot_json = json.dumps(pnl_data["by_bot"])
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            return existing
        else:
            # Create
            pnl_realized = PnlRealized(
                account_id=account_id,
                period_type=period_type,
                period_start=period_start,
                period_end=period_end,
                realized_pnl_usd=pnl_data["realized_pnl"],
                fees_usd=pnl_data["fees"],
                trades_count=pnl_data["trades_count"],
                by_symbol_json=json.dumps(pnl_data["by_symbol"]),
                by_bot_json=json.dumps(pnl_data["by_bot"])
            )
            self.db.add(pnl_realized)
            self.db.commit()
            self.db.refresh(pnl_realized)
            return pnl_realized
