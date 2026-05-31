"""
İşlem Geçmişi Servisi – şifreli dosya deposu (hesap başına .enc).
TradeNormalized yedek/backfill; okuma dosyadan, RAM'de havuz tutulmaz.
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.utils.tz_utils import turkey_today_start_utc


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
            from datetime import timedelta
            start = end - timedelta(days=365)
        else:
            from datetime import timedelta
            start = today_start - timedelta(days=days - 1)
        return (start, end)

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
        Paginated transaction list from encrypted file store.
        type_filter: all | buy | sell | buysell | deposit | withdraw | depositwithdraw
        source_filter: all | spot | bot
        """
        from app.services.transaction_history_file_store import (
            ensure_buysell_dedup_v1,
            ledger_has_buysell,
            query_transactions,
            rebuild_from_db,
            sync_from_db_if_stale,
        )

        try:
            ensure_buysell_dedup_v1(db, account_id)
        except Exception:
            pass

        tf = (type_filter or "all").strip().lower()
        if tf in ("deposit", "withdraw", "depositwithdraw"):
            return query_transactions(
                account_id,
                period=period,
                type_filter=tf,
                source_filter=source_filter,
                page=page,
                per_page=TransactionHistoryService.PER_PAGE,
            )

        if not ledger_has_buysell(account_id):
            try:
                rebuild_from_db(db, account_id, days=90)
            except Exception:
                pass
        else:
            try:
                sync_from_db_if_stale(db, account_id, max_rows=60)
            except Exception:
                pass

        eff_tf = tf if tf not in ("all", "") else "buysell"
        return query_transactions(
            account_id,
            period=period,
            type_filter=eff_tf,
            source_filter=source_filter,
            page=page,
            per_page=TransactionHistoryService.PER_PAGE,
        )

    @staticmethod
    def get_transaction_detail(db: Session, account_id: int, trade_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Tek işlem detayı — önce dosya, yoksa DB."""
        from app.services.transaction_history_file_store import get_order_detail

        found = get_order_detail(account_id, trade_id, symbol)
        if found:
            return found

        from app.db.models import TradeNormalized, Bot
        import json as _json

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
                    cfg = _json.loads(b.config_json or "{}")
                    bot_name = (b.name or cfg.get("name") or f"Bot #{b.id}")[:64]
                except Exception:
                    bot_name = f"Bot #{t.bot_id}"
        from app.services.transaction_history_file_store import upsert_trade_fill

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
            bot_name=bot_name,
        )
        return get_order_detail(account_id, trade_id, symbol)
