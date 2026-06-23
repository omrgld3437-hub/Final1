"""
Dashboard Snapshot - Aggregated endpoint data fetchers.
Each fetch runs concurrently with 3s timeout. Partial response on task failure.
"""

from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy import desc, text

logger = logging.getLogger(__name__)

SNAPSHOT_TASK_TIMEOUT = 3.0


async def fetch_prices() -> Dict[str, Any]:
    """Get all prices from DataHub. Sync call wrapped in thread."""
    try:
        from app.services.data_hub import data_hub

        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, data_hub.get_prices_for_ui),
            timeout=SNAPSHOT_TASK_TIMEOUT,
        )
        return result or {}
    except asyncio.TimeoutError:
        logger.warning("[snapshot] fetch_prices timeout")
        return {"_error": "timeout"}
    except Exception as e:
        logger.warning("[snapshot] fetch_prices error: %s", e)
        return {"_error": str(e)}


async def fetch_bots_and_account_kpis(account_id: int, db: Session) -> Dict[str, Any]:
    """
    Build bots array + account KPIs (DB only, no Binance).
    spot_balance_usd and daily_wallet_* come from wallet; caller merges.
    """
    try:
        from app.db.models import Account, Bot, Trade, User
        from app.services.pnl_service import PnlService
        from app.bot.ledger import Ledger
        from app.botengine.state_store import load_state
        from app.botengine.health_watch import (
            _account_wallet_stale_alert,
            evaluate_bot_health_lite,
            summarize_health_alert_level,
        )
        from app.services.bot_equity import compute_bot_equity_usd
        from zoneinfo import ZoneInfo
        from app.utils.tz_utils import turkey_today_date_str

        TR_TZ = ZoneInfo("Europe/Istanbul")

        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"_error": "Account not found"}

        bots = db.query(Bot).filter(Bot.account_id == account_id).all()
        total_bots = len(bots)
        from app.services.bot_status_utils import count_running_bots

        active_bots = count_running_bots(bots)
        total_profit_usd = 0.0
        total_bot_equity_usd = 0.0
        total_bot_initial_usd = 0.0
        daily_pnl_usd_acc = 0.0
        bots_array = []
        try:
            from app.services.binance_connectivity import active_failure

            account_failure = active_failure(account_id)
        except Exception:
            account_failure = None
        account_wallet_alert = (
            None if account_failure else _account_wallet_stale_alert(db, account_id)
        )

        last_trade_by_bot: Dict[int, Optional[str]] = {}
        if bots:
            try:
                rows = db.execute(
                    text("""
                        SELECT bot_id, MAX(ts) as last_ts FROM trades
                        WHERE account_id = :aid
                        GROUP BY bot_id
                    """),
                    {"aid": account_id},
                ).fetchall()
                for row in rows:
                    bot_id, last_ts = row[0], row[1]
                    last_trade_by_bot[bot_id] = (
                        last_ts.isoformat() + "Z" if last_ts else None
                    )
            except Exception as e:
                logger.debug(
                    "[snapshot] batch last_trade query failed, fallback per-bot: %s", e
                )
                last_trade_by_bot = {}

        today_date_loop = turkey_today_date_str()
        for bot in bots:
            pnl_data = PnlService.calculate_bot_pnl(db, bot.id, account_id)
            initial_usd = 0.0
            try:
                cfg = json.loads(bot.config_json or "{}")
                initial_usd = float(
                    cfg.get("budget_usd")
                    or cfg.get("bot_budget_quote")
                    or cfg.get("initial_capital_usdt")
                    or 0
                )
            except Exception:
                pass
            current_usd = (
                pnl_data.get("total_usd", initial_usd)
                if not pnl_data.get("error")
                else initial_usd
            )
            daily_bot = pnl_data.get("daily", 0.0) if not pnl_data.get("error") else 0.0
            daily_pnl_pct = (daily_bot / initial_usd * 100) if initial_usd > 0 else 0.0
            # Tek sembol DCA: list K/Z = bot detay ile aynı (state + fiyat)
            sym_ = (bot.symbol or "").strip().upper()
            strategy_id_ = (
                (json.loads(bot.config_json or "{}").get("strategy_id") or "")
                .strip()
                .lower()
            )
            state_ = load_state(db, bot.id) or {}
            ia_done_ = bool(state_.get("initial_allocation_done"))
            cycle_id_ = int(state_.get("cycle_id") or 1)
            display_status_ = bot.status or "stopped"
            if (display_status_ or "").lower() == "running" and not ia_done_:
                display_status_ = "starting"
            if (
                sym_
                and sym_ != "MULTI"
                and strategy_id_ not in ("trdca_pro", "multi_asset_rebalance")
            ):
                try:
                    current_usd = compute_bot_equity_usd(
                        db, bot, state_, pnl_data, initial_usd=initial_usd
                    )
                    ref_date_ = state_.get("daily_ref_date")
                    ref_usd_ = float(state_.get("daily_ref_usd") or 0)
                    if ref_date_ == today_date_loop and ref_usd_ > 0:
                        daily_bot = current_usd - ref_usd_
                        daily_pnl_pct = (daily_bot / ref_usd_) * 100.0
                except Exception:
                    pass
            elif sym_ == "MULTI" or strategy_id_ in (
                "trdca_pro",
                "multi_asset_rebalance",
            ):
                try:
                    current_usd = compute_bot_equity_usd(
                        db, bot, state_, pnl_data, initial_usd=initial_usd
                    )
                except Exception:
                    pass
            daily_pnl_usd_acc += daily_bot
            if not pnl_data.get("error"):
                total_bot_equity_usd += current_usd
                total_bot_initial_usd += initial_usd
                if ia_done_ and current_usd > 0:
                    try:
                        PnlService.save_snapshot_if_due(
                            db,
                            bot.id,
                            account_id,
                            {
                                "total_usd": current_usd,
                                "realized": float(pnl_data.get("realized") or 0.0),
                                "unrealized": current_usd - initial_usd
                                if initial_usd > 0
                                else 0.0,
                                "daily": daily_bot,
                                "monthly": float(pnl_data.get("monthly") or 0.0),
                            },
                        )
                    except Exception as snap_ex:
                        logger.debug(
                            "[snapshot] pnl snapshot persist skipped bot_id=%s: %s",
                            bot.id,
                            snap_ex,
                        )
                        try:
                            db.rollback()
                        except Exception:
                            pass

            last_trade_at = last_trade_by_bot.get(bot.id)
            if last_trade_at is None and bot.id not in last_trade_by_bot:
                last_t = (
                    db.query(Trade)
                    .filter(
                        Trade.bot_id == bot.id,
                        Trade.account_id == account_id,
                    )
                    .order_by(Trade.ts.desc())
                    .first()
                )
                last_trade_at = (
                    last_t.ts.isoformat() + "Z"
                    if last_t and getattr(last_t, "ts", None)
                    else None
                )

            total_pnl_usd_bot = current_usd - initial_usd
            total_profit_usd += total_pnl_usd_bot
            total_pnl_pct_bot = (
                (total_pnl_usd_bot / initial_usd * 100) if initial_usd > 0 else 0.0
            )
            cycles = Ledger.get_cycle_ids(db, bot.id, account_id)
            total_cycles_completed = max(cycles) if cycles else 0
            if cycle_id_ > total_cycles_completed:
                total_cycles_completed = cycle_id_
            try:
                bot_config = json.loads(bot.config_json or "{}")
            except Exception:
                bot_config = {}
            health_alerts = evaluate_bot_health_lite(
                bot,
                state_,
                account_failure=account_failure,
                account_wallet_alert=account_wallet_alert,
            )
            bots_array.append(
                {
                    "bot_id": bot.id,
                    "id": bot.id,
                    "bot_code": getattr(bot, "bot_code", None) or str(bot.id),
                    "symbol": bot.symbol,
                    "config": bot_config,
                    "status": bot.status or "stopped",
                    "display_status": display_status_,
                    "initial_allocation_done": ia_done_,
                    "cycle_id": cycle_id_,
                    "base_balance": round(float(state_.get("base_balance") or 0), 8),
                    "quote_balance": round(float(state_.get("quote_balance") or 0), 8),
                    "budget_usd": round(initial_usd, 2),
                    "initial_usd": round(initial_usd, 2),
                    "current_usd": round(current_usd, 2),
                    "daily_pnl_usd": round(daily_bot, 2),
                    "daily_pnl_pct": round(daily_pnl_pct, 2),
                    "total_pnl_usd": round(total_pnl_usd_bot, 2),
                    "total_pnl_pct": round(total_pnl_pct_bot, 2),
                    "account_id": account_id,
                    "last_trade_at": last_trade_at,
                    "total_cycles_completed": total_cycles_completed,
                    "health_alert_level": summarize_health_alert_level(health_alerts),
                    "health_alerts": health_alerts,
                }
            )

        daily_bot_pnl_usd_kpi = PnlService.daily_realized_from_cycles_completed_today(
            db, account_id
        )
        user_name = user_surname = user_phone = None
        if account.user_id:
            u = db.query(User).filter(User.id == account.user_id).first()
            if u:
                user_name = u.name
                user_surname = u.surname
                user_phone = u.phone

        today_tr = datetime.now(TR_TZ).strftime("%Y-%m-%d")
        account_kpis = {
            "id": account.id,
            "account_code": getattr(account, "account_code", None) or None,
            "name": account.name,
            "user_name": user_name,
            "user_surname": user_surname,
            "user_phone": user_phone,
            "bots_balance_usd": round(total_bot_equity_usd, 2),
            "bots_initial_usd": round(total_bot_initial_usd, 2),
            "daily_bot_pnl_usd": round(daily_bot_pnl_usd_kpi, 2),
            "total_pnl_usd": round(total_bot_equity_usd - total_bot_initial_usd, 2),
            "total_bots": total_bots,
            "active_bots": active_bots,
        }

        return {
            "bots": bots_array,
            "account": account_kpis,
            "daily_bot_pnl_usd_kpi": daily_bot_pnl_usd_kpi,
            "total_profit_usd": total_profit_usd,
            "total_bot_equity_usd": total_bot_equity_usd,
            "ref_date": today_tr,
        }
    except Exception as e:
        logger.warning("[snapshot] fetch_bots_and_account_kpis error: %s", e)
        return {"_error": str(e)}


async def fetch_finance_pnl(account_id: int, db: Session) -> Dict[str, Any]:
    """Build finance PnL summary (DB only)."""
    try:
        from app.db.models import Account, Bot, AssetSnapshot
        from app.services.finance_pnl_calculator import FinancePnlCalculator
        from app.services.pnl_service import PnlService
        from app.utils.tz_utils import turkey_today_start_utc

        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"_error": "Account not found"}

        latest_snapshot = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(desc(AssetSnapshot.timestamp))
            .first()
        )
        total_usd_value = latest_snapshot.total_usd_value if latest_snapshot else 0.0

        first_snapshot = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(AssetSnapshot.timestamp.asc())
            .first()
        )
        initial_value = first_snapshot.total_usd_value if first_snapshot else 0.0
        if not first_snapshot:
            bots = db.query(Bot).filter(Bot.account_id == account_id).all()
            for bot in bots:
                try:
                    config = json.loads(bot.config_json or "{}")
                    initial_value += float(
                        config.get("budget_usd") or config.get("bot_budget_quote") or 0
                    )
                except Exception:
                    pass

        now = datetime.utcnow()
        today_start = turkey_today_start_utc()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        calculator = FinancePnlCalculator(db)
        pnl_today = calculator.calculate_realized_pnl(account_id, today_start, now)
        pnl_7d = calculator.calculate_realized_pnl(account_id, last_7d, now)
        pnl_30d = calculator.calculate_realized_pnl(account_id, last_30d, now)
        unrealized_data = calculator.calculate_unrealized_pnl(account_id)
        daily_bot_pnl_usd = PnlService.daily_realized_from_cycles_completed_today(
            db, account_id
        )

        return {
            "total_usd_value": total_usd_value,
            "initial_value": initial_value,
            "daily_bot_pnl_usd": daily_bot_pnl_usd,
            "today": {
                "pnl": pnl_today["realized_pnl"],
                "fees": pnl_today["fees"],
                "trades_count": pnl_today["trades_count"],
            },
            "last_7d": {
                "pnl": pnl_7d["realized_pnl"],
                "fees": pnl_7d["fees"],
                "trades_count": pnl_7d["trades_count"],
            },
            "last_30d": {
                "pnl": pnl_30d["realized_pnl"],
                "fees": pnl_30d["fees"],
                "trades_count": pnl_30d["trades_count"],
            },
            "realized_pnl": pnl_30d["realized_pnl"],
            "unrealized_pnl": unrealized_data["unrealized_pnl"],
            "total_fees": pnl_30d["fees"],
            "top_gainers": [],
            "top_losers": [],
            "bot_summary": [],
        }
    except Exception as e:
        logger.warning("[snapshot] fetch_finance_pnl error: %s", e)
        return {"_error": str(e)}
