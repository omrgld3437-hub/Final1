"""
Trade Ledger - Record and Snapshot Management
"""
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.db.models import Trade


class Ledger:
    """Trade ledger manager"""

    @staticmethod
    def record_trade(
        db: Session,
        bot_id: int,
        account_id: int,
        side: str,
        qty: float,
        price: float,
        fee: float = 0.0,
        fee_asset: str = "USDT",
        slot_id: Optional[int] = None,
        reference_price: Optional[float] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        cycle_id: Optional[int] = None,
    ) -> Tuple[Trade, bool]:
        """
        Record a trade. Idempotent when order_id is provided: if (bot_id, order_id)
        already exists, skip insert and return (existing, False). Else return (trade, True).
        cycle_id: tur/round (1, 2, 3...); if None, defaults to 1.
        """
        if order_id is not None:
            existing = (
                db.query(Trade)
                .filter(Trade.bot_id == bot_id, Trade.order_id == str(order_id))
                .first()
            )
            if existing:
                return (existing, False)
        trade = Trade(
            bot_id=bot_id,
            account_id=account_id,
            ts=datetime.utcnow(),
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            fee_asset=fee_asset,
            slot_id=slot_id,
            reference_price=reference_price,
            order_id=str(order_id) if order_id is not None else None,
            client_order_id=client_order_id,
            symbol=symbol,
            cycle_id=cycle_id if cycle_id is not None else 1,
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        return (trade, True)

    @staticmethod
    def get_trades(
        db: Session,
        bot_id: int,
        account_id: int,
        limit: int = 50,
        cycle_id: Optional[int] = None,
    ) -> List[Trade]:
        """Get recent trades, optionally filtered by cycle_id."""
        q = db.query(Trade).filter(
            Trade.bot_id == bot_id,
            Trade.account_id == account_id,
        )
        if cycle_id is not None:
            from sqlalchemy import or_
            q = q.filter(or_(Trade.cycle_id == cycle_id, (Trade.cycle_id.is_(None)) & (cycle_id == 1)))
        return q.order_by(Trade.ts.desc()).limit(limit).all()

    @staticmethod
    def get_trades_dict(
        db: Session,
        bot_id: int,
        account_id: int,
        limit: int = 50,
        cycle_id: Optional[int] = None,
    ) -> List[Dict]:
        """Get trades as dict list, optionally filtered by cycle_id."""
        trades = Ledger.get_trades(db, bot_id, account_id, limit, cycle_id=cycle_id)
        out = []
        for t in trades:
            d = {
                "id": t.id,
                "ts": t.ts.isoformat() if t.ts else None,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "fee": t.fee,
                "fee_asset": t.fee_asset,
                "slot_id": t.slot_id,
                "reference_price": getattr(t, "reference_price", None),
            }
            if getattr(t, "order_id", None) is not None:
                d["order_id"] = t.order_id
            if getattr(t, "client_order_id", None) is not None:
                d["client_order_id"] = t.client_order_id
            if getattr(t, "symbol", None) is not None:
                d["symbol"] = t.symbol
            if getattr(t, "cycle_id", None) is not None:
                d["cycle_id"] = t.cycle_id
            out.append(d)
        return out

    @staticmethod
    def get_cycle_ids(db: Session, bot_id: int, account_id: int) -> List[int]:
        """Distinct cycle_ids for this bot, newest first. Treats NULL as 1 for backward compat."""
        from sqlalchemy import distinct
        rows = (
            db.query(distinct(Trade.cycle_id))
            .filter(Trade.bot_id == bot_id, Trade.account_id == account_id)
            .all()
        )
        ids = [r[0] if r[0] is not None else 1 for r in rows]
        seen = set()
        uniq = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return sorted(uniq, reverse=True) if uniq else [1]
