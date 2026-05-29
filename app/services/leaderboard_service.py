"""
Leaderboard: top bots by profit % (structure or global). DB + PnlService only, no Binance.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Map backend strategy_id -> frontend structure_id
STRUCTURE_ID_MAP = {
    "dca_grid_trailing": "trailing_dca",
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
                SELECT bpm.profit_pct_all, bpm.params_sanitized_json, b.symbol, b.id, b.account_id, b.config_json
                FROM bot_public_metrics bpm
                INNER JOIN bots b ON b.id = bpm.bot_id
                WHERE bpm.structure_id = :sid AND bpm.profit_pct_all >= 0
                ORDER BY bpm.profit_pct_all DESC
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
            symbol = (row[2] or "").strip() if len(row) > 2 else None
            bot_id = int(row[3]) if len(row) > 3 and row[3] is not None else None
            account_id = int(row[4]) if len(row) > 4 and row[4] is not None else None
            config_json_raw = row[5] if len(row) > 5 else None
            ref_price = _reference_price_from_state(db, bot_id, account_id)
            params = _resolve_leaderboard_params(
                db, params, config_json_raw, bot_id, account_id, symbol, ref_price
            )
            out.append({"profit_pct": round(pct, 2), "params": params, "symbol": symbol})
        return out
    except Exception as e:
        logger.warning("leaderboard get_top_by_structure failed: %s", e)
        return []


def _running_since_iso(started_at) -> Optional[str]:
    """Normalize bot started_at to UTC ISO string (JS Date parses correctly with Z suffix)."""
    if started_at is None:
        return None
    if hasattr(started_at, "isoformat"):
        iso = started_at.isoformat()
        if iso and not iso.endswith("Z") and "+" not in iso[-7:]:
            iso += "Z"
        return iso
    s = str(started_at).strip()
    if not s:
        return None
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    if not s.endswith("Z") and "+" not in s[-7:]:
        s += "Z"
    return s


def _initial_capital_from_config(config_json_raw: Optional[str]) -> float:
    try:
        cfg = json.loads(config_json_raw or "{}")
        return float(cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0)
    except Exception:
        return 0.0


def _params_missing_strategy_detail(params: Dict[str, Any]) -> bool:
    if not params:
        return True
    if params.get("sell_grids") or params.get("buy_grids"):
        return False
    up = params.get("up") if isinstance(params.get("up"), dict) else {}
    down = params.get("down") if isinstance(params.get("down"), dict) else {}
    if up.get("grids") or down.get("grids"):
        return False
    return len(params) <= 3


_BUDGET_PARAM_KEYS = ("initial_capital_usdt", "budget_usd", "bot_budget_quote")


def _strip_budget_from_public_params(params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params or {})
    for k in _BUDGET_PARAM_KEYS:
        out.pop(k, None)
    return out


def _resolve_leaderboard_params(
    db: Session,
    params: Dict[str, Any],
    config_json_raw: Optional[str],
    bot_id: Optional[int],
    account_id: Optional[int],
    symbol: Optional[str],
    reference_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Full strategy params for Parametreleri görüntüle modal; re-sanitize if DB cache is stale."""
    from app.db.models import Bot
    from app.services.copytrading_sanitize import sanitize_bot_params

    out = dict(params or {})
    if _params_missing_strategy_detail(out) and config_json_raw:
        bot = db.query(Bot).filter(Bot.id == bot_id).first() if bot_id is not None else None
        out = sanitize_bot_params(bot, None, config_json_raw)
    ref = reference_price
    if ref is None and bot_id is not None:
        ref = _reference_price_from_state(db, bot_id, account_id)
    if ref is not None and float(ref) > 0:
        out["reference_price"] = round(float(ref), 8)
    if symbol and "symbol" not in out:
        out["symbol"] = symbol
    return _strip_budget_from_public_params(out)


def _reference_price_from_state(db: Session, bot_id: Optional[int], account_id: Optional[int]) -> Optional[float]:
    if bot_id is None:
        return None
    try:
        from app.botengine.state_store import load_state_json_extract

        ref = load_state_json_extract(db, bot_id, "$.reference_price")
        if ref is not None and float(ref) > 0:
            return round(float(ref), 8)
    except Exception:
        pass
    return None


def _bot_profit_metrics(db: Session, bot: Any) -> Dict[str, Any]:
    """
    Dashboard ile aynı equity: compute_bot_equity_usd (DCA state+price).
    PnlService virtual_wallet tek başına grid botlarda yanlış total_usd verebilir.
    """
    from app.botengine.state_store import load_state
    from app.services.bot_equity import compute_bot_equity_usd
    from app.services.pnl_service import PnlService

    initial = _initial_capital_from_config(getattr(bot, "config_json", None))
    out: Dict[str, Any] = {"total_pnl_usd": None, "profit_pct": None, "equity_usd": None}
    if initial <= 0:
        return out
    try:
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id)
        state = load_state(db, bot.id) or {}
        equity = float(
            compute_bot_equity_usd(db, bot, state, pnl_data, initial_usd=initial)
        )
        total_pnl_usd = round(equity - initial, 2)
        profit_pct = round((equity - initial) / initial * 100.0, 2)
        out["equity_usd"] = round(equity, 2)
        out["total_pnl_usd"] = total_pnl_usd
        out["profit_pct"] = profit_pct
    except Exception:
        pass
    return out


def _live_pnl_fields(
    db: Session,
    bot_id: Optional[int],
    account_id: Optional[int],
    config_json_raw: Optional[str],
    stored_profit_pct: Optional[float] = None,
) -> Dict[str, Any]:
    from app.db.models import Bot

    profit_pct = stored_profit_pct
    total_pnl_usd = None
    if bot_id is not None and account_id is not None:
        bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
        if bot:
            m = _bot_profit_metrics(db, bot)
            if m.get("profit_pct") is not None:
                profit_pct = m["profit_pct"]
            total_pnl_usd = m.get("total_pnl_usd")
    return {
        "total_pnl_usd": total_pnl_usd,
        "profit_pct": profit_pct,
    }


def _leaderboard_item_extras(
    db: Session,
    bot_id: Optional[int],
    account_id: Optional[int],
    config_json_raw: Optional[str],
) -> Dict[str, Any]:
    from app.bot.ledger import Ledger
    from app.services.pnl_service import PnlService

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
    return {
        "cycles_count": cycles_count,
        "profit_pct_daily": profit_pct_daily,
        "daily_pnl_usd": daily_pnl_usd,
    }


def _global_top_from_running_bots(db: Session, limit: int) -> List[Dict[str, Any]]:
    """Live fallback: running bots with profit_pct >= 0 when metrics cache is empty/stale."""
    from app.db.models import Bot
    from app.services.copytrading_sanitize import sanitize_bot_params

    candidates: List[tuple] = []
    bots = db.query(Bot).filter(Bot.status == "running").all()
    for bot in bots:
        try:
            cfg = json.loads(bot.config_json or "{}")
            initial = float(cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0)
            if initial <= 0:
                continue
            metrics = _bot_profit_metrics(db, bot)
            profit_pct = metrics.get("profit_pct")
            if profit_pct is None or float(profit_pct) < 0:
                continue
            profit_pct = float(profit_pct)
            strategy_id = (cfg.get("strategy_id") or "").strip().lower() or "dca_grid_trailing"
            structure_id = _strategy_to_structure_id(strategy_id)
            params = sanitize_bot_params(bot, None, bot.config_json or "{}")
            symbol = (bot.symbol or "").strip() or None
            if symbol and "symbol" not in params:
                params = dict(params)
                params["symbol"] = symbol
            candidates.append((profit_pct, structure_id, params, symbol, bot))
        except Exception:
            continue
    candidates.sort(key=lambda x: -x[0])
    out: List[Dict[str, Any]] = []
    for profit_pct, structure_id, params, symbol, bot in candidates[:limit]:
        extras = _leaderboard_item_extras(db, bot.id, bot.account_id, bot.config_json)
        live = _live_pnl_fields(db, bot.id, bot.account_id, bot.config_json, profit_pct)
        ref_price = _reference_price_from_state(db, bot.id, bot.account_id)
        params = _resolve_leaderboard_params(
            db, params, bot.config_json, bot.id, bot.account_id, symbol, ref_price
        )
        out.append({
            "structure_id": structure_id,
            "profit_pct": live["profit_pct"] if live["profit_pct"] is not None else round(profit_pct, 2),
            "total_pnl_usd": live["total_pnl_usd"],
            "profit_pct_daily": extras["profit_pct_daily"],
            "daily_pnl_usd": extras["daily_pnl_usd"],
            "cycles_count": extras["cycles_count"],
            "params": params,
            "running_since_iso": _running_since_iso(getattr(bot, "started_at", None)),
            "symbol": symbol,
            "reference_price": ref_price,
        })
    return out


def get_global_top(db: Session, limit: int = 1) -> List[Dict[str, Any]]:
    """Global top bots by profit_pct_all. Running bots with profit_pct_all >= 0 (break-even or profit).
    INNER JOIN bots ensures we never return metrics for deleted bots.
    Falls back to live PnL when metrics cache returns no rows.
    Returns list of { structure_id, profit_pct, total_pnl_usd, profit_pct_daily, daily_pnl_usd, cycles_count, params, running_since_iso, reference_price }
    (no bot_id/account/balance)."""
    limit = max(1, min(20, limit))
    try:
        rows = db.execute(
            text("""
                SELECT bpm.structure_id, bpm.profit_pct_all, bpm.params_sanitized_json, b.started_at, b.symbol, b.id, b.account_id, b.config_json
                FROM bot_public_metrics bpm
                INNER JOIN bots b ON b.id = bpm.bot_id
                WHERE LOWER(TRIM(COALESCE(b.status, ''))) = 'running'
                ORDER BY bpm.profit_pct_all DESC
                LIMIT :lim
            """),
            {"lim": max(limit * 3, limit)},
        ).fetchall()
        out: List[Dict[str, Any]] = []
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
            running_since_iso = _running_since_iso(started_at)
            ref_price = _reference_price_from_state(db, bot_id, account_id)
            params = _resolve_leaderboard_params(
                db, params, config_json_raw, bot_id, account_id, symbol, ref_price
            )
            extras = _leaderboard_item_extras(db, bot_id, account_id, config_json_raw)
            live = _live_pnl_fields(db, bot_id, account_id, config_json_raw, pct)
            live_pct = live["profit_pct"] if live["profit_pct"] is not None else round(pct, 2)
            live_pnl = live["total_pnl_usd"]
            if live_pnl is not None and float(live_pnl) < 0:
                continue
            if live_pct is not None and float(live_pct) < 0:
                continue
            out.append({
                "structure_id": sid,
                "profit_pct": live_pct,
                "total_pnl_usd": live_pnl,
                "profit_pct_daily": extras["profit_pct_daily"],
                "daily_pnl_usd": extras["daily_pnl_usd"],
                "cycles_count": extras["cycles_count"],
                "params": params,
                "running_since_iso": running_since_iso,
                "symbol": symbol,
                "reference_price": ref_price,
            })
            if len(out) >= limit:
                break
        if not out:
            out = _global_top_from_running_bots(db, limit)
        return out
    except Exception as e:
        logger.warning("leaderboard get_global_top failed: %s", e)
        try:
            return _global_top_from_running_bots(db, limit)
        except Exception:
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
                cfg = json.loads(bot.config_json or "{}")
                initial = float(cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0)
                if initial <= 0:
                    continue
                metrics = _bot_profit_metrics(db, bot)
                profit_pct_all = metrics.get("profit_pct")
                if profit_pct_all is None:
                    continue
                profit_pct_all = float(profit_pct_all)
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
