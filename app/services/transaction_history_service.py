"""
İşlem Geçmişi Servisi – Alım/satım/yatırım/çekim birleşik havuz.
TradeNormalized (Binance myTrades) + deposit/withdraw; Spot vs Bot kaynak ayrımı.
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models import TradeNormalized, Bot
from app.utils.tz_utils import turkey_today_start_utc


def _naive_utc(dt: datetime) -> datetime:
    if dt and dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_iso(dt: datetime) -> str:
    s = dt.isoformat()
    return s + "Z" if not (s.endswith("Z") or "+" in s) else s


class TransactionHistoryService:
    """İşlem geçmişi: tarih aralığı, tür, kaynak filtreleri, sayfalama."""

    PER_PAGE = 20
    PERIOD_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "all": None}

    @staticmethod
    def get_date_range(period: str) -> Tuple[Optional[datetime], datetime]:
        """(start_utc, end_utc) – period: daily|weekly|monthly|all."""
        today_start = turkey_today_start_utc()
        end = datetime.utcnow()
        days = TransactionHistoryService.PERIOD_DAYS.get(period, 1)
        if days is None:
            start = end - timedelta(days=365)
        else:
            start = today_start - timedelta(days=days - 1)
        return (start, end)

    @staticmethod
    def _trade_to_item(t: TradeNormalized, bot_name: Optional[str] = None) -> Dict[str, Any]:
        side = (t.side or "").upper()
        return {
            "id": f"tn_{t.id}",
            "trade_id": t.trade_id,
            "order_id": t.order_id,
            "time": _utc_iso(t.time),
            "type": "buy" if side == "BUY" else "sell",
            "type_label": "Alım" if side == "BUY" else "Satım",
            "symbol": t.symbol or "",
            "side": side,
            "qty": float(t.qty or 0),
            "price": float(t.price or 0),
            "quote_qty": float(t.quote_qty or 0),
            "commission": float(t.commission or 0),
            "commission_asset": t.commission_asset or "USDT",
            "is_maker": bool(t.is_maker),
            "source": "bot" if t.bot_id else "spot",
            "source_label": "Bot" if t.bot_id else "Spot",
            "platform": "TradeTrailing" if t.bot_id else "Binance",  # Bot emri platformdan; spot doğrudan borsa
            "bot_id": t.bot_id,
            "bot_name": bot_name,
        }

    @staticmethod
    def _fills_to_order_item(fills: List[TradeNormalized], bot_names: Dict[int, str]) -> Dict[str, Any]:
        """Birden fazla fill'i tek emir (order) satırına toplar."""
        if not fills:
            raise ValueError("fills empty")
        first = fills[0]
        last = max(fills, key=lambda f: f.time)
        side = (first.side or "").upper()
        total_qty = sum(float(f.qty or 0) for f in fills)
        total_quote = sum(float(f.quote_qty or 0) for f in fills)
        total_commission = sum(float(f.commission or 0) for f in fills)
        avg_price = total_quote / total_qty if total_qty else float(first.price or 0)
        bot_name = bot_names.get(first.bot_id) if first.bot_id else None
        return {
            "id": f"ord_{first.order_id or first.trade_id}",
            "trade_id": first.trade_id,
            "order_id": first.order_id,
            "time": _utc_iso(last.time),
            "type": "buy" if side == "BUY" else "sell",
            "type_label": "Alım" if side == "BUY" else "Satım",
            "symbol": first.symbol or "",
            "side": side,
            "qty": total_qty,
            "price": avg_price,
            "quote_qty": total_quote,
            "commission": total_commission,
            "commission_asset": first.commission_asset or "USDT",
            "is_maker": any(bool(f.is_maker) for f in fills),
            "source": "bot" if first.bot_id else "spot",
            "source_label": "Bot" if first.bot_id else "Spot",
            "platform": "TradeTrailing" if first.bot_id else "Binance",
            "bot_id": first.bot_id,
            "bot_name": bot_name,
            "fills_count": len(fills),
        }

    @staticmethod
    def get_transactions(
        db: Session,
        account_id: int,
        period: str = "weekly",
        type_filter: str = "all",
        source_filter: str = "all",
        page: int = 1,
    ) -> Dict[str, Any]:
        """
        Paginated transaction list.
        type_filter: all | buy | sell | deposit | withdraw
        source_filter: all | spot | bot
        """
        start_time, end_time = TransactionHistoryService.get_date_range(period)
        per_page = TransactionHistoryService.PER_PAGE
        offset = max(0, page - 1) * per_page

        tf = (type_filter or "all").strip().lower()
        sf = (source_filter or "all").strip().lower()

        # For now: only BUY/SELL from TradeNormalized (deposit/withdraw via separate fetch in API)
        if tf in ("deposit", "withdraw"):
            return {
                "items": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
                "period": period,
                "date_from": start_time.strftime("%Y-%m-%d") if start_time else None,
                "date_to": end_time.strftime("%Y-%m-%d"),
            }

        q = db.query(TradeNormalized).filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"]),
            TradeNormalized.time >= start_time,
            TradeNormalized.time <= end_time,
        )
        if tf == "buy":
            q = q.filter(TradeNormalized.side == "BUY")
        elif tf == "sell":
            q = q.filter(TradeNormalized.side == "SELL")
        if sf == "spot":
            q = q.filter(TradeNormalized.bot_id.is_(None))
        elif sf == "bot":
            q = q.filter(TradeNormalized.bot_id.isnot(None))

        # Emir bazında grupla: aynı order_id tek satır (parça parça fill yazma)
        MAX_FILLS = 5000
        rows = q.order_by(desc(TradeNormalized.time)).limit(MAX_FILLS).all()
        order_groups: Dict[Any, List[TradeNormalized]] = {}
        for r in rows:
            key = r.order_id if r.order_id else f"t_{r.trade_id}"
            order_groups.setdefault(key, []).append(r)
        # Grupları son fill zamanına göre azalan sırada
        sorted_groups = sorted(
            order_groups.values(),
            key=lambda fills: max(f.time for f in fills),
            reverse=True,
        )
        total = len(sorted_groups)
        paginated_groups = sorted_groups[offset : offset + per_page]

        bot_ids = list({f.bot_id for g in paginated_groups for f in g if f.bot_id})
        bot_names: Dict[int, str] = {}
        if bot_ids:
            for b in db.query(Bot).filter(Bot.id.in_(bot_ids)).all():
                try:
                    cfg = __import__("json").loads(b.config_json or "{}")
                    bot_names[b.id] = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
                except Exception:
                    bot_names[b.id] = f"Bot #{b.id}"

        items = [TransactionHistoryService._fills_to_order_item(g, bot_names) for g in paginated_groups]
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "period": period,
            "date_from": start_time.strftime("%Y-%m-%d") if start_time else None,
            "date_to": end_time.strftime("%Y-%m-%d"),
        }

    @staticmethod
    def get_transaction_detail(db: Session, account_id: int, trade_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Tek işlem detayı (trade_id + symbol ile)."""
        t = (
            db.query(TradeNormalized)
            .filter(
                TradeNormalized.account_id == account_id,
                TradeNormalized.trade_id == str(trade_id),
                TradeNormalized.symbol == (symbol or "").upper(),
            )
            .first()
        )
        if not t:
            return None
        bot_name = None
        if t.bot_id:
            b = db.query(Bot).filter(Bot.id == t.bot_id).first()
            if b:
                try:
                    cfg = __import__("json").loads(b.config_json or "{}")
                    bot_name = (b.name or cfg.get("name") or f"Bot #{b.id}")[:64]
                except Exception:
                    bot_name = f"Bot #{t.bot_id}"
        out = TransactionHistoryService._trade_to_item(t, bot_name)
        out["details"] = {
            "is_maker": bool(t.is_maker),
            "order_id": t.order_id,
            "commission_asset": t.commission_asset or "USDT",
        }
        return out
