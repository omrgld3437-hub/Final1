"""
Leaderboard: top bots by profit % (structure or global). DB + PnlService only, no Binance.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Map backend strategy_id -> frontend structure_id
STRUCTURE_ID_MAP = {
    "dca_grid_trailing": "trailing_dca",
    "trdca_pro": "trdca_pro",
}


def _strategy_to_structure_id(strategy_id: str) -> str:
    s = (strategy_id or "").strip().lower()
    return STRUCTURE_ID_MAP.get(s) or "trailing_dca"


def get_top_by_structure(db: Session, structure_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Top bots by profit_pct_all for a structure. Returns list of { profit_pct, params } (no bot_id/account_id)."""
    limit = max(1, min(20, limit))
    try:
        rows = db.execute(
            text("""
                SELECT profit_pct_all, params_sanitized_json
                FROM bot_public_metrics
                WHERE structure_id = :sid AND profit_pct_all >= 0
                ORDER BY profit_pct_all DESC
                LIMIT :lim
            """),
            {"sid": structure_id, "lim": limit},
        ).fetchall()
        out = []
        for row in rows:
            pct = float(row[0]) if row[0] is not None else 0.0
            try:
                params = json.loads(row[1] or "{}")
            except Exception:
                params = {}
            out.append({"profit_pct": round(pct, 2), "params": params})
        return out
    except Exception as e:
        logger.warning("leaderboard get_top_by_structure failed: %s", e)
        return []


def get_global_top(db: Session, limit: int = 1) -> List[Dict[str, Any]]:
    """Global top bots by profit_pct_all. Only positive profit and only running bots that still exist.
    INNER JOIN bots ensures we never return metrics for deleted bots.
    Returns list of { structure_id, profit_pct, profit_pct_daily, daily_pnl_usd, cycles_count, params, running_since_iso }
    (no bot_id/account/balance)."""
    limit = max(1, min(20, limit))
    try:
        from app.bot.ledger import Ledger
        from app.services.pnl_service import PnlService

        rows = db.execute(
            text("""
                SELECT bpm.structure_id, bpm.profit_pct_all, bpm.params_sanitized_json, b.started_at, b.symbol, b.id, b.account_id, b.config_json
                FROM bot_public_metrics bpm
                INNER JOIN bots b ON b.id = bpm.bot_id
                WHERE bpm.profit_pct_all > 0
                  AND LOWER(TRIM(COALESCE(b.status, ''))) = 'running'
                ORDER BY bpm.profit_pct_all DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
        out = []
        for row in rows:
            sid = (row[0] or "").strip() or "trailing_dca"
            pct = float(row[1]) if row[1] is not None else 0.0
            try:
                params = json.loads(row[2] or "{}")
            except Exception:
                params = {}
            started_at = row[3]
            symbol = (row[4] or "").strip() if len(row) > 4 else None
            bot_id = int(row[5]) if row[5] is not None else None
            account_id = int(row[6]) if row[6] is not None else None
            config_json_raw = row[7] if len(row) > 7 else None
            if started_at is None:
                running_since_iso = None
            elif hasattr(started_at, "isoformat"):
                running_since_iso = started_at.isoformat()
                if running_since_iso and not running_since_iso.endswith("Z"):
                    running_since_iso += "Z"
            else:
                running_since_iso = str(started_at)
            if symbol and "symbol" not in params:
                params = dict(params)
                params["symbol"] = symbol

            cycles_count = 0
            profit_pct_daily = None
            daily_pnl_usd = None
            if bot_id is not None and account_id is not None:
                try:
                    cycle_ids = Ledger.get_cycle_ids(db, bot_id, account_id)
                    cycles_count = len(cycle_ids) if cycle_ids else 0
                except Exception:
                    pass
                try:
                    daily_pnl_usd = round(float(PnlService._daily_realized_for_bot_trades(db, bot_id, account_id)), 2)
                    initial = 0.0
                    if config_json_raw:
                        try:
                            cfg = json.loads(config_json_raw or "{}")
                            initial = float(cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0)
                        except Exception:
                            pass
                    if initial > 0 and daily_pnl_usd is not None:
                        profit_pct_daily = round((daily_pnl_usd / initial) * 100.0, 2)
                except Exception:
                    pass

            out.append({
                "structure_id": sid,
                "profit_pct": round(pct, 2),
                "profit_pct_daily": profit_pct_daily,
                "daily_pnl_usd": daily_pnl_usd,
                "cycles_count": cycles_count,
                "params": params,
                "running_since_iso": running_since_iso,
                "symbol": symbol,
            })
        return out
    except Exception as e:
        logger.warning("leaderboard get_global_top failed: %s", e)
        return []


def refresh_bot_public_metrics(db: Session, batch_size: int = 200) -> int:
    """
    Upsert bot_public_metrics from active bots. Uses PnlService (DB/price cache only, no Binance).
    Returns count of rows upserted.
    """
    from app.db.models import Bot
    from app.services.pnl_service import PnlService
    from app.services.copytrading_sanitize import sanitize_bot_params

    start = time.perf_counter()
    updated = 0
    try:
        bots = db.query(Bot).filter(Bot.status == "running").limit(batch_size).all()
        if not bots:
            bots = db.query(Bot).limit(batch_size).all()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for bot in bots:
            try:
                pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id)
                if pnl_data.get("error"):
                    continue
                total_usd = float(pnl_data.get("total_usd") or 0)
                cfg = json.loads(bot.config_json or "{}")
                initial = float(cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0)
                if initial <= 0:
                    continue
                profit_pct_all = (total_usd - initial) / initial * 100.0
                strategy_id = (cfg.get("strategy_id") or "").strip().lower() or "dca_grid_trailing"
                structure_id = _strategy_to_structure_id(strategy_id)
                params_json = json.dumps(sanitize_bot_params(bot, None, bot.config_json or "{}"), ensure_ascii=False)
                db.execute(
                    text("""
                        INSERT INTO bot_public_metrics (bot_id, account_id, structure_id, profit_pct_all, profit_pct_7d, profit_pct_30d, params_sanitized_json, updated_at)
                        VALUES (:bid, :aid, :sid, :pct, NULL, NULL, :params, :now)
                        ON CONFLICT(bot_id) DO UPDATE SET
                            account_id = :aid2,
                            structure_id = :sid2,
                            profit_pct_all = :pct2,
                            params_sanitized_json = :params2,
                            updated_at = :now2
                    """),
                    {
                        "bid": bot.id,
                        "aid": bot.account_id,
                        "sid": structure_id,
                        "pct": round(profit_pct_all, 4),
                        "params": params_json,
                        "now": now_iso,
                        "aid2": bot.account_id,
                        "sid2": structure_id,
                        "pct2": round(profit_pct_all, 4),
                        "params2": params_json,
                        "now2": now_iso,
                    },
                )
                updated += 1
            except Exception as e:
                logger.debug("leaderboard refresh bot %s skip: %s", getattr(bot, "id", ""), e)
        db.commit()
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("LEADERBOARD_REFRESH_OK count=%s duration_ms=%.0f", updated, duration_ms)
        return updated
    except Exception as e:
        db.rollback()
        logger.warning("LEADERBOARD_REFRESH_FAIL error_code=%s", str(e)[:100])
        raise
