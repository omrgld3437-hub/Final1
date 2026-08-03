"""
Trade Ledger - Record and Snapshot Management
"""

from datetime import datetime, timezone
import json
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.db.models import Trade


class Ledger:
    """Trade ledger manager"""

    @staticmethod
    def _trade_ts_iso_utc(dt: Optional[datetime]) -> Optional[str]:
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")

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
        fee_amount: Optional[float] = None,
        fee_usdt: Optional[float] = None,
        order_type: Optional[str] = None,
        cost_basis_type: Optional[str] = None,
        cost_basis_price: Optional[float] = None,
        linked_grid_ids: Optional[List[int]] = None,
        trigger_price: Optional[float] = None,
        tracked_extreme_price: Optional[float] = None,
        completion_price: Optional[float] = None,
        engine_status: Optional[str] = None,
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
            fee_amount=fee_amount if fee_amount is not None else fee,
            fee_usdt=fee_usdt if fee_usdt is not None else fee,
            slot_id=slot_id,
            reference_price=reference_price,
            order_id=str(order_id) if order_id is not None else None,
            client_order_id=client_order_id,
            symbol=symbol,
            cycle_id=cycle_id if cycle_id is not None else 1,
            order_type=order_type,
            cost_basis_type=cost_basis_type,
            cost_basis_price=cost_basis_price,
            linked_grid_ids=json.dumps(linked_grid_ids or []),
            trigger_price=trigger_price,
            tracked_extreme_price=tracked_extreme_price,
            completion_price=completion_price,
            fill_total=qty * price,
            engine_status=engine_status,
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

            q = q.filter(
                or_(
                    Trade.cycle_id == cycle_id,
                    (Trade.cycle_id.is_(None)) & (cycle_id == 1),
                )
            )
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
                "ts": Ledger._trade_ts_iso_utc(t.ts),
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "fee": t.fee,
                "fee_asset": t.fee_asset,
                "fee_amount": getattr(t, "fee_amount", None),
                "fee_usdt": getattr(t, "fee_usdt", None),
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
