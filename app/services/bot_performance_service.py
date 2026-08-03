"""
Bot performans: dosya tabanlı saatlik (bugün) + kalıcı günlük K/Z defteri.
DB bot_daily_pnl yedek/backfill; okuma .run/bot_perf/ dosyalarından.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.botengine.state_store import load_state
from app.db.models import Bot
from app.utils.tz_utils import TR_TZ

logger = logging.getLogger(__name__)

PERIOD_ALIASES = {
    "daily": "day",
    "day": "day",
    "1d": "day",
    "weekly": "week",
    "week": "week",
    "7d": "week",
    "monthly": "month",
    "month": "month",
    "30d": "month",
    "all": "all",
    "total": "all",
}

PERIOD_LABELS = {
    "day": "Günlük",
    "week": "Haftalık",
    "month": "Aylık",
    "all": "Genel",
}


def normalize_perf_period(period: str) -> str:
    p = (period or "all").strip().lower()
    return PERIOD_ALIASES.get(p, "all")


def performance_period_start_ts(period: str) -> Optional[datetime]:
    """Dönem başlangıcı (UTC). Günlük/haftalık/aylık = TR takvim günü (dual PNL ile aynı)."""
    p = normalize_perf_period(period)
    if p == "all":
        return None
    date_from, _, _ = period_calendar_range(period)
    if not date_from:
        return None
    start_tr = datetime.strptime(date_from, "%Y-%m-%d").replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=TR_TZ
    )
    return start_tr.astimezone(timezone.utc)


def _parse_ts_utc(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ts_to_date_tr(ts: Any) -> Optional[str]:
    dt = _parse_ts_utc(ts)
    if dt is None:
        return None
    return dt.astimezone(TR_TZ).strftime("%Y-%m-%d")


def _completed_cycle_side(entry: Dict[str, Any]) -> Optional[str]:
    if not entry or not isinstance(entry, dict):
        return None
    reason = str(
        entry.get("completed_reason") or entry.get("close_reason") or ""
    ).strip()
    ct = str(entry.get("cycle_type") or "").upper()
    if reason == "trail_profit_sell" or ct in ("CASH", "LONG_SCALP"):
        return "BUY"
    if reason == "trail_reentry_buy" or ct in ("INVENTORY", "INVENTORY_REBALANCE"):
        return "SELL"
    cash = float(entry.get("cash_pnl_usdt") or 0)
    inv = float(entry.get("inventory_coin_adv_qty") or 0)
    if abs(cash) >= 1e-15 and abs(inv) < 1e-15:
        return "BUY"
    if abs(inv) >= 1e-15:
        return "SELL"
    return None


def _completed_cycle_in_period(
    entry: Dict[str, Any], start_ts: Optional[datetime]
) -> bool:
    if start_ts is None:
        return True
    ts = _parse_ts_utc(entry.get("completed_at"))
    if ts is None:
        return False
    return ts >= start_ts


def _completed_cycle_in_tr_range(
    entry: Dict[str, Any], date_from: str, date_to: str
) -> bool:
    d = ts_to_date_tr(entry.get("completed_at"))
    if not d:
        return False
    return date_from <= d <= date_to


def resolve_perf_date_range(
    period: str,
    *,
    bot_id: Optional[int] = None,
    account_id: Optional[int] = None,
) -> Tuple[str, str, str]:
    """TR takvim aralığı (date_from, date_to, label). Genel için en eski tur günü."""
    date_from_opt, date_to, label = period_calendar_range(period)
    if date_from_opt:
        return date_from_opt, date_to, label
    if bot_id is not None:
        try:
            from app.services.bot_perf_file_store import earliest_bot_cycle_date

            earliest = earliest_bot_cycle_date(bot_id)
            if earliest:
                return earliest, date_to, label
        except Exception:
            pass
    if account_id is not None:
        try:
            from app.services.bot_perf_file_store import (
                load_account_rounds,
                load_daily_ledger,
            )

            round_days = [
                str(r.get("d"))
                for r in (load_account_rounds(account_id).get("r") or [])
                if isinstance(r, dict) and r.get("d")
            ]
            if round_days:
                return min(round_days), date_to, label
            days = (load_daily_ledger(account_id).get("days") or {}).keys()
            if days:
                return min(days), date_to, label
        except Exception:
            pass
    fallback = (datetime.now(TR_TZ).date() - timedelta(days=365)).strftime("%Y-%m-%d")
    return fallback, date_to, label


def _cycle_close_price_usdt(
    entry: Dict[str, Any], symbol: Optional[str] = None
) -> float:
    """Tur kapanış fiyatı (quote/base); yoksa sembol anlık fiyatı."""
    for key in ("close_price_quote_per_base", "close_px", "px"):
        try:
            v = float(entry.get(key) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    close_fill = entry.get("close_fill")
    if isinstance(close_fill, dict):
        for key in ("price", "execution_price"):
            try:
                v = float(close_fill.get(key) or 0)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    sym = (symbol or entry.get("symbol") or "").strip().upper()
    if sym:
        try:
            from app.services.market_data import get_price

            px = get_price(sym)
            if px and float(px) > 0:
                return float(px)
        except Exception:
            pass
    return 0.0


def _cycle_ledger_amounts(
    entry: Dict[str, Any], *, symbol: Optional[str] = None
) -> Tuple[float, float]:
    """Kapanan tur → USDT K/Z + komisyon. Yukarı (envanter) tur: coin kârı × kapanış kuru."""
    side = _completed_cycle_side(entry)
    cash_fees = float(entry.get("cash_fees_usdt") or 0)
    inv_fees = float(entry.get("inventory_fees_usdt") or 0)
    if side == "BUY":
        return float(entry.get("cash_pnl_usdt") or 0), cash_fees
    if side == "SELL":
        inv_qty = float(entry.get("inventory_coin_adv_qty") or 0)
        px = _cycle_close_price_usdt(entry, symbol)
        pnl_usd = inv_qty * px if px > 0 and abs(inv_qty) >= 1e-15 else 0.0
        return pnl_usd, inv_fees
    cash_pnl = float(entry.get("cash_pnl_usdt") or 0)
    inv_qty = float(entry.get("inventory_coin_adv_qty") or 0)
    px = _cycle_close_price_usdt(entry, symbol)
    inv_usd = inv_qty * px if px > 0 and abs(inv_qty) >= 1e-15 else 0.0
    return cash_pnl + inv_usd, cash_fees + inv_fees


def aggregate_dual_perf_closed_cycles(
    completed_cycles: Optional[List[Dict[str, Any]]],
    start_ts: Optional[datetime] = None,
    initial_capital: float = 0.0,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    completed = completed_cycles or []
    cash_pnl = 0.0
    cash_fees = 0.0
    cash_count = 0
    inv_pnl = 0.0
    inv_fees = 0.0
    inv_count = 0
    for entry in completed:
        if not isinstance(entry, dict):
            continue
        if date_from and date_to:
            if not _completed_cycle_in_tr_range(entry, date_from, date_to):
                continue
        elif not _completed_cycle_in_period(entry, start_ts):
            continue
        side = _completed_cycle_side(entry)
        if side == "BUY":
            cash_pnl += float(entry.get("cash_pnl_usdt") or 0)
            cash_fees += float(entry.get("cash_fees_usdt") or 0)
            cash_count += 1
        elif side == "SELL":
            inv_pnl += float(entry.get("inventory_coin_adv_qty") or 0)
            inv_fees += float(entry.get("inventory_fees_usdt") or 0)
            inv_count += 1
    cash_pct = (cash_pnl / initial_capital * 100.0) if initial_capital > 0 else None
    return {
        "cash_pnl_usdt": round(cash_pnl, 4),
        "cash_fees_usdt": round(cash_fees, 4),
        "cash_closed_cycles": cash_count,
        "cash_pnl_pct": round(cash_pct, 2) if cash_pct is not None else None,
        "inventory_pnl_coin": round(inv_pnl, 12),
        "inventory_fees_usdt": round(inv_fees, 4),
        "inventory_closed_cycles": inv_count,
        "inventory_pnl_pct": None,
    }


def estimate_annual_return_pct_12m(
    completed_cycles: Optional[List[Dict[str, Any]]],
    initial_capital: float,
    *,
    now: Optional[datetime] = None,
    symbol: Optional[str] = None,
) -> Optional[float]:
    """Annualize the bot's average monthly net USDT-equivalent return (max 12 months)."""
    if initial_capital <= 0:
        return None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now_utc - timedelta(days=365)
    rows: List[Tuple[datetime, float]] = []
    for entry in completed_cycles or []:
        if not isinstance(entry, dict):
            continue
        completed_at = _parse_ts_utc(entry.get("completed_at"))
        if completed_at is None or completed_at < cutoff or completed_at > now_utc:
            continue
        pnl_usdt, fees_usdt = _cycle_ledger_amounts(entry, symbol=symbol)
        rows.append((completed_at, float(pnl_usdt) - float(fees_usdt)))
    if not rows:
        return None
    first = min(row[0] for row in rows)
    observed_months = max(
        1,
        min(
            12,
            (now_utc.year - first.year) * 12 + now_utc.month - first.month + 1,
        ),
    )
    average_monthly_usdt = sum(row[1] for row in rows) / observed_months
    return round(average_monthly_usdt * 12.0 / initial_capital * 100.0, 2)


def estimate_live_bot_annual_return_pct_12m(
    current_equity: float,
    initial_capital: float,
    started_at: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Kapanmış tur yokken yalnız botun kendi canlı değişimini yıllıklandır."""
    if initial_capital <= 0 or current_equity < 0:
        return None
    started = _parse_ts_utc(started_at)
    if started is None:
        return None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if started > now_utc:
        return None
    observed_months = max(
        1,
        min(
            12,
            (now_utc.year - started.year) * 12
            + now_utc.month
            - started.month
            + 1,
        ),
    )
    net_change_usdt = float(current_equity) - float(initial_capital)
    return round(
        net_change_usdt * 12.0 / observed_months / initial_capital * 100.0,
        2,
    )


def base_from_symbol(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    if s == "MULTI":
        return "MULTI"
    for q in ("USDT", "FDUSD", "BUSD", "USDC"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _bot_config_initial(bot: Bot) -> float:
    try:
        cfg = (
            json.loads(bot.config_json or "{}")
            if getattr(bot, "config_json", None)
            else {}
        )
    except Exception:
        cfg = {}
    return float(
        cfg.get("initial_capital_usdt")
        or cfg.get("budget_usd")
        or cfg.get("bot_budget_usdt")
        or cfg.get("bot_budget_quote")
        or 0
    )


def _bot_strategy_id(bot: Bot) -> str:
    try:
        cfg = (
            json.loads(bot.config_json or "{}")
            if getattr(bot, "config_json", None)
            else {}
        )
    except Exception:
        cfg = {}
    return (cfg.get("strategy_id") or "").strip().lower()


def _is_trailing_dual_dca_bot(sym: str, strategy_id: str) -> bool:
    return sym != "MULTI" and strategy_id not in ("trdca_pro", "multi_asset_rebalance")


def _is_trailing_dual_dca(bot: Bot) -> bool:
    sym = (bot.symbol or "").strip().upper()
    return _is_trailing_dual_dca_bot(sym, _bot_strategy_id(bot))


def _status_label_from_code(status: Optional[str], deleted: bool = False) -> str:
    if deleted:
        return "Silindi"
    st = (status or "").lower()
    if st == "running":
        return "Çalışıyor"
    if st in ("paused", "paused_insufficient_balance"):
        return "Duraklatıldı"
    if st == "stopped":
        return "Durduruldu"
    return st or "—"


def period_calendar_range(period: str) -> Tuple[Optional[str], str, str]:
    """TR takvim günü aralığı: (date_from, date_to, label). all için date_from None."""
    norm = normalize_perf_period(period)
    today_tr = datetime.now(TR_TZ).date()
    today_str = today_tr.strftime("%Y-%m-%d")
    label = PERIOD_LABELS.get(norm, "Genel")
    if norm == "day":
        return today_str, today_str, label
    if norm == "week":
        start = (today_tr - timedelta(days=6)).strftime("%Y-%m-%d")
        return start, today_str, label
    if norm == "month":
        start = (today_tr - timedelta(days=29)).strftime("%Y-%m-%d")
        return start, today_str, label
    return None, today_str, label


def invalidate_account_performance_cache(db: Session, account_id: int) -> None:
    try:
        db.execute(
            text("DELETE FROM account_performance_cache WHERE account_id = :aid"),
            {"aid": account_id},
        )
        db.commit()
    except Exception as e:
        logger.debug(
            "invalidate_account_performance_cache account_id=%s: %s", account_id, e
        )
        try:
            db.rollback()
        except Exception:
            pass


def _upsert_bot_perf_store(
    db: Session,
    account_id: int,
    bot_id: int,
    symbol: str,
    strategy_id: str,
    initial_capital: float,
    completed_cycles: List[Dict[str, Any]],
    bot_status: str,
    deleted: bool,
) -> None:
    sym = (symbol or "").strip().upper()
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(
        completed_cycles if isinstance(completed_cycles, list) else [],
        ensure_ascii=False,
    )
    try:
        db.execute(
            text("""
                INSERT INTO bot_perf_archive (
                    account_id, bot_id, symbol, strategy_id, base_asset,
                    initial_capital_usd, completed_cycles_json, bot_status, archived_at, deleted
                ) VALUES (
                    :aid, :bid, :sym, :sid, :base, :init, :cycles, :status, :arch, :del
                )
                ON CONFLICT(bot_id) DO UPDATE SET
                    account_id = excluded.account_id,
                    symbol = excluded.symbol,
                    strategy_id = excluded.strategy_id,
                    base_asset = excluded.base_asset,
                    initial_capital_usd = excluded.initial_capital_usd,
                    completed_cycles_json = excluded.completed_cycles_json,
                    bot_status = excluded.bot_status,
                    archived_at = excluded.archived_at,
                    deleted = excluded.deleted
            """),
            {
                "aid": account_id,
                "bid": bot_id,
                "sym": sym,
                "sid": strategy_id,
                "base": base_from_symbol(sym),
                "init": initial_capital,
                "cycles": payload,
                "status": bot_status or "stopped",
                "arch": now_iso,
                "del": 1 if deleted else 0,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning("_upsert_bot_perf_store bot_id=%s: %s", bot_id, e)
        try:
            db.rollback()
        except Exception:
            pass


def rebuild_bot_daily_from_cycles(
    db: Session,
    account_id: int,
    bot_id: int,
    symbol: str,
    completed_cycles: List[Dict[str, Any]],
    *,
    deleted: bool = False,
) -> None:
    """Bot için tüm günlük satırları turlardan yeniden üret (idempotent)."""
    by_date: Dict[str, Dict[str, float]] = {}
    for entry in completed_cycles or []:
        if not isinstance(entry, dict):
            continue
        date_tr = ts_to_date_tr(entry.get("completed_at"))
        if not date_tr:
            continue
        sym_row = (symbol or entry.get("symbol") or "").strip().upper()
        pnl, fees = _cycle_ledger_amounts(entry, symbol=sym_row)
        bucket = by_date.setdefault(
            date_tr, {"pnl_usd": 0.0, "fees_usd": 0.0, "cycle_count": 0.0}
        )
        bucket["pnl_usd"] += pnl
        bucket["fees_usd"] += fees
        bucket["cycle_count"] += 1

    sym = (symbol or "").strip().upper()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            text("DELETE FROM bot_daily_pnl WHERE bot_id = :bid"), {"bid": bot_id}
        )
        for date_tr, agg in by_date.items():
            db.execute(
                text("""
                    INSERT INTO bot_daily_pnl (
                        bot_id, date_tr, account_id, symbol, pnl_usd, fees_usd,
                        cycle_count, bot_deleted, updated_at
                    ) VALUES (
                        :bid, :dt, :aid, :sym, :pnl, :fees, :cnt, :del, :now
                    )
                """),
                {
                    "bid": bot_id,
                    "dt": date_tr,
                    "aid": account_id,
                    "sym": sym,
                    "pnl": round(agg["pnl_usd"], 4),
                    "fees": round(agg["fees_usd"], 4),
                    "cnt": int(agg["cycle_count"]),
                    "del": 1 if deleted else 0,
                    "now": now_iso,
                },
            )
        db.commit()
    except Exception as e:
        logger.warning("rebuild_bot_daily_from_cycles bot_id=%s: %s", bot_id, e)
        try:
            db.rollback()
        except Exception:
            pass
        return
    try:
        from app.services.bot_perf_file_store import rebuild_bot_daily_in_file

        file_by_date = {
            d: (agg["pnl_usd"], agg["fees_usd"], int(agg["cycle_count"]))
            for d, agg in by_date.items()
        }
        rebuild_bot_daily_in_file(
            account_id, bot_id, sym, file_by_date, deleted=deleted
        )
        from app.services.bot_perf_file_store import rebuild_bot_cycles_file

        rebuild_bot_cycles_file(bot_id, account_id, sym, completed_cycles)
    except Exception as e:
        logger.debug("rebuild_bot_daily file bot_id=%s: %s", bot_id, e)


def sync_bot_cycles_file_from_state(
    db: Session,
    bot_id: int,
    account_id: int,
    state: Optional[Dict[str, Any]] = None,
) -> None:
    """Bot başlangıcında / okuma öncesi: perf dosyasını state ile hizala."""
    from app.services.bot_perf_file_store import reconcile_bot_cycles_file_with_state

    if state is None:
        state = load_state(db, bot_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        return
    sym = bot.symbol or ""
    completed = (state or {}).get("completed_cycle_dual_pnls") or []
    if not completed:
        for rec in _load_stored_bots(db, account_id):
            if rec["bot_id"] == bot_id:
                completed = rec.get("completed_cycles") or []
                sym = rec.get("symbol") or sym
                break
    reconcile_bot_cycles_file_with_state(bot_id, account_id, sym, completed)


def load_bot_closed_cycles_for_period(
    db: Session,
    bot_id: int,
    account_id: int,
    period: str,
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], str, str]:
    """State/arşiv tek kaynak; dosya yalnızca cache. Uyuşmazlıkta state kazanır."""
    from app.services.bot_perf_file_store import (
        query_bot_cycles_by_date_range,
        reconcile_bot_cycles_file_with_state,
    )

    if state is None:
        state = load_state(db, bot_id)
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    sym = (bot.symbol or "") if bot else ""
    completed = (state or {}).get("completed_cycle_dual_pnls") or []
    if not completed:
        for rec in _load_stored_bots(db, account_id):
            if rec["bot_id"] == bot_id:
                completed = rec.get("completed_cycles") or []
                sym = rec.get("symbol") or sym
                break
    reconcile_bot_cycles_file_with_state(bot_id, account_id, sym, completed)

    date_from, date_to, _ = resolve_perf_date_range(
        period, bot_id=bot_id, account_id=account_id
    )

    # Mevcut çalışma öncesindeki turları dışla: bot.started_at alt sınır olarak kullan.
    # Böylece bot yeniden başlatıldığında eski çalışmadan kalan döngüler performans bölümünde görünmez.
    started_at_date: Optional[str] = None
    if bot and getattr(bot, "started_at", None):
        try:
            sa = bot.started_at
            if sa.tzinfo is None:
                sa = sa.replace(tzinfo=timezone.utc)
            # TR saati (UTC+3) — ts_to_date_tr ile tutarlı
            sa_tr = sa.astimezone(timezone(timedelta(hours=3)))
            started_at_date = sa_tr.strftime("%Y-%m-%d")
        except Exception:
            pass
    if started_at_date and started_at_date > date_from:
        date_from = started_at_date

    cycles = query_bot_cycles_by_date_range(bot_id, date_from, date_to)
    return cycles, date_from, date_to


def record_bot_daily_cycle_pnl(
    db: Session,
    account_id: int,
    bot_id: int,
    symbol: str,
    cycle_entry: Dict[str, Any],
    *,
    deleted: bool = False,
    invalidate_cache: bool = True,
) -> None:
    """Tur kapanışında ilgili TR gününe K/Z ekle."""
    if not cycle_entry or not isinstance(cycle_entry, dict):
        return
    date_tr = ts_to_date_tr(cycle_entry.get("completed_at"))
    if not date_tr:
        return
    sym = (symbol or cycle_entry.get("symbol") or "").strip().upper()
    pnl, fees = _cycle_ledger_amounts(cycle_entry, symbol=sym)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            text("""
                INSERT INTO bot_daily_pnl (
                    bot_id, date_tr, account_id, symbol, pnl_usd, fees_usd,
                    cycle_count, bot_deleted, updated_at
                ) VALUES (
                    :bid, :dt, :aid, :sym, :pnl, :fees, 1, :del, :now
                )
                ON CONFLICT(bot_id, date_tr) DO UPDATE SET
                    pnl_usd = pnl_usd + excluded.pnl_usd,
                    fees_usd = fees_usd + excluded.fees_usd,
                    cycle_count = cycle_count + 1,
                    symbol = excluded.symbol,
                    bot_deleted = excluded.bot_deleted,
                    updated_at = excluded.updated_at
            """),
            {
                "bid": bot_id,
                "dt": date_tr,
                "aid": account_id,
                "sym": sym,
                "pnl": round(pnl, 4),
                "fees": round(fees, 4),
                "del": 1 if deleted else 0,
                "now": now_iso,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning("record_bot_daily_cycle_pnl bot_id=%s: %s", bot_id, e)
        try:
            db.rollback()
        except Exception:
            pass
        return
    try:
        from app.services.bot_perf_file_store import (
            record_bot_daily_pnl_file,
            record_closed_cycle_file,
            record_hourly_pnl,
        )

        ts = cycle_entry.get("completed_at")
        record_closed_cycle_file(bot_id, account_id, sym, cycle_entry)
        record_hourly_pnl(account_id, pnl, fees, ts=ts)
        record_bot_daily_pnl_file(
            account_id, bot_id, sym, date_tr, pnl, fees, deleted=deleted
        )
    except Exception as e:
        logger.debug("record_bot_daily file bot_id=%s: %s", bot_id, e)
    if invalidate_cache:
        invalidate_account_performance_cache(db, account_id)


def sync_bot_perf_store_from_state(
    db: Session,
    bot_id: int,
    account_id: int,
    state: Optional[Dict[str, Any]] = None,
    *,
    invalidate_cache: bool = True,
) -> None:
    """Aktif bot: completed_cycle_dual_pnls → bot_perf_archive (DB)."""
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        return
    if state is None:
        state = load_state(db, bot_id)
    completed = (state or {}).get("completed_cycle_dual_pnls") or []
    if not isinstance(completed, list):
        completed = []
    sym = bot.symbol or ""
    _upsert_bot_perf_store(
        db,
        account_id,
        bot_id,
        sym,
        _bot_strategy_id(bot),
        _bot_config_initial(bot),
        completed,
        getattr(bot, "status", None) or "stopped",
        deleted=False,
    )
    try:
        from app.services.bot_perf_file_store import rebuild_bot_cycles_file_if_changed

        rebuild_bot_cycles_file_if_changed(bot_id, account_id, sym, completed)
    except Exception as e:
        logger.debug("sync_bot_cycles file bot_id=%s: %s", bot_id, e)
    if invalidate_cache:
        invalidate_account_performance_cache(db, account_id)


def archive_bot_performance(db: Session, bot_id: int, account_id: int) -> None:
    """Bot silinmeden önce arşivle (deleted=1) ve günlük defteri güncelle."""
    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        return
    state = load_state(db, bot_id)
    completed = (state or {}).get("completed_cycle_dual_pnls") or []
    if not isinstance(completed, list):
        completed = []
    _upsert_bot_perf_store(
        db,
        account_id,
        bot_id,
        bot.symbol or "",
        _bot_strategy_id(bot),
        _bot_config_initial(bot),
        completed,
        getattr(bot, "status", None) or "stopped",
        deleted=True,
    )
    rebuild_bot_daily_from_cycles(
        db, account_id, bot_id, bot.symbol or "", completed, deleted=True
    )
    invalidate_account_performance_cache(db, account_id)


def _refresh_active_bot_stores(db: Session, account_id: int) -> None:
    """Aktif botların store kaydını state'ten güncelle (cache miss)."""
    bots = db.query(Bot).filter(Bot.account_id == account_id).all()
    for bot in bots:
        if not _is_trailing_dual_dca(bot):
            continue
        try:
            sync_bot_perf_store_from_state(
                db, bot.id, account_id, invalidate_cache=False
            )
        except Exception as e:
            logger.debug("refresh store bot_id=%s: %s", bot.id, e)


def _bot_has_daily_rows(db: Session, bot_id: int) -> bool:
    row = db.execute(
        text("SELECT 1 FROM bot_daily_pnl WHERE bot_id = :bid LIMIT 1"),
        {"bid": bot_id},
    ).fetchone()
    return row is not None


def ensure_account_rounds_ledger(
    db: Session, account_id: int, *, force_rebuild: bool = False
) -> None:
    """Hesap ham tur dosyası: tüm botların kapanan turları (tarih/saat)."""
    from app.services.bot_perf_file_store import (
        list_bot_completed_cycles,
        load_account_rounds,
        rebuild_account_rounds_file,
    )

    if not force_rebuild:
        existing = load_account_rounds(account_id).get("r") or []
        if existing:
            return

    bot_rounds: List[Tuple[int, str, List[Dict[str, Any]]]] = []
    seen_bots: set = set()

    for rec in _load_stored_bots(db, account_id):
        bid = int(rec["bot_id"])
        if bid in seen_bots:
            continue
        seen_bots.add(bid)
        sym = rec.get("symbol") or ""
        cycles = rec.get("completed_cycles") or []
        if not cycles:
            cycles = list_bot_completed_cycles(bid)
        bot_rounds.append((bid, sym, cycles))

    for bot in db.query(Bot).filter(Bot.account_id == account_id).all():
        if not _is_trailing_dual_dca(bot):
            continue
        bid = int(bot.id)
        if bid in seen_bots:
            continue
        seen_bots.add(bid)
        sym = bot.symbol or ""
        state = load_state(db, bid)
        cycles = (state or {}).get("completed_cycle_dual_pnls") or []
        if not cycles:
            cycles = list_bot_completed_cycles(bid)
        bot_rounds.append((bid, sym, cycles if isinstance(cycles, list) else []))

    if bot_rounds:
        rebuild_account_rounds_file(account_id, bot_rounds)


def ensure_account_daily_ledger(
    db: Session, account_id: int, *, force_rebuild: bool = False
) -> None:
    """Eksik bot günlük kayıtlarını arşivden doldur; force_rebuild tüm botları yeniden üretir."""
    if force_rebuild:
        _refresh_active_bot_stores(db, account_id)
    stored = _load_stored_bots(db, account_id)
    if not stored and not force_rebuild:
        from app.db.models import Bot

        for bot in db.query(Bot).filter(Bot.account_id == account_id).all():
            if not _is_trailing_dual_dca(bot):
                continue
            if _bot_has_daily_rows(db, bot.id):
                continue
            try:
                sync_bot_perf_store_from_state(
                    db, bot.id, account_id, invalidate_cache=False
                )
            except Exception as e:
                logger.debug(
                    "ensure_account_daily ledger sync bot_id=%s: %s", bot.id, e
                )
        stored = _load_stored_bots(db, account_id)
    for rec in stored:
        bid = rec["bot_id"]
        cycles = rec.get("completed_cycles") or []
        if not cycles and not force_rebuild:
            continue
        if force_rebuild or not _bot_has_daily_rows(db, bid):
            rebuild_bot_daily_from_cycles(
                db,
                account_id,
                bid,
                rec.get("symbol") or "",
                cycles,
                deleted=bool(rec.get("deleted")),
            )


def _load_stored_bots(db: Session, account_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT bot_id, symbol, strategy_id, base_asset, initial_capital_usd,
                   completed_cycles_json, bot_status, archived_at, deleted
            FROM bot_perf_archive
            WHERE account_id = :aid
            ORDER BY archived_at DESC
        """),
        {"aid": account_id},
    ).fetchall()
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for row in rows:
        bid = int(row[0])
        if bid in seen:
            continue
        seen.add(bid)
        try:
            cycles = json.loads(row[5] or "[]")
        except Exception:
            cycles = []
        out.append(
            {
                "bot_id": bid,
                "symbol": row[1] or "",
                "strategy_id": row[2] or "",
                "base_asset": row[3] or base_from_symbol(row[1] or ""),
                "initial_capital_usd": float(row[4] or 0),
                "completed_cycles": cycles if isinstance(cycles, list) else [],
                "bot_status": row[6] or "stopped",
                "archived_at": row[7],
                "deleted": bool(row[8]),
            }
        )
    return out


def _query_daily_series(
    db: Session, account_id: int, date_from: str, date_to: str
) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT date_tr,
                   ROUND(SUM(pnl_usd), 4) AS pnl,
                   ROUND(SUM(fees_usd), 4) AS fees,
                   SUM(cycle_count) AS cycles
            FROM bot_daily_pnl
            WHERE account_id = :aid AND date_tr >= :df AND date_tr <= :dt
            GROUP BY date_tr
            ORDER BY date_tr ASC
        """),
        {"aid": account_id, "df": date_from, "dt": date_to},
    ).fetchall()
    return [
        {
            "date_tr": r[0],
            "pnl_usd": float(r[1] or 0),
            "fees_usd": float(r[2] or 0),
            "cycle_count": int(r[3] or 0),
        }
        for r in rows
    ]


def _rebuild_daily_file_from_db(db: Session, account_id: int) -> None:
    """DB bot_daily_pnl → kalıcı günlük dosya (backfill)."""
    rows = db.execute(
        text("""
            SELECT bot_id, date_tr, symbol, pnl_usd, fees_usd, bot_deleted
            FROM bot_daily_pnl WHERE account_id = :aid
            ORDER BY date_tr ASC
        """),
        {"aid": account_id},
    ).fetchall()
    if not rows:
        return
    days: Dict[str, Any] = {}
    for row in rows:
        date_tr = str(row[1])
        bot_id = int(row[0])
        sym = (row[2] or "").upper()
        pnl = float(row[3] or 0)
        fees = float(row[4] or 0)
        deleted = bool(row[5])
        day = days.setdefault(date_tr, {"p": 0.0, "f": 0.0, "b": {}})
        day["b"][str(bot_id)] = [
            round(pnl, 4),
            round(fees, 4),
            sym,
            1 if deleted else 0,
        ]
    for day in days.values():
        bots = day.get("b") or {}
        day["p"] = round(sum(float(r[0] or 0) for r in bots.values()), 4)
        day["f"] = round(sum(float(r[1] or 0) for r in bots.values()), 4)
    try:
        from app.services.bot_perf_file_store import write_daily_ledger

        write_daily_ledger(account_id, days)
    except Exception as e:
        logger.debug("_rebuild_daily_file_from_db account_id=%s: %s", account_id, e)


def _ensure_daily_file(db: Session, account_id: int) -> None:
    from app.services.bot_perf_file_store import load_daily_ledger

    ledger = load_daily_ledger(account_id)
    if ledger.get("days"):
        return
    _rebuild_daily_file_from_db(db, account_id)


def _resolve_date_from_file(account_id: int, date_from: Optional[str]) -> str:
    if date_from:
        return date_from
    from app.services.bot_perf_file_store import load_daily_ledger

    ledger = load_daily_ledger(account_id)
    days = ledger.get("days") or {}
    if days:
        return min(days.keys())
    fallback = (datetime.now(TR_TZ).date() - timedelta(days=365)).strftime("%Y-%m-%d")
    return fallback


def _ensure_hourly_for_date(db: Session, account_id: int, date_tr: str) -> None:
    """Saatlik dosya boşsa arşiv turlarından (veya günlük defter/DB) doldur."""
    from app.services.bot_perf_file_store import (
        empty_hour_slots,
        hour_tr,
        hourly_has_activity,
        load_daily_ledger,
        load_hourly,
        write_hourly_data,
    )

    hourly_data = load_hourly(account_id, date_tr)
    if hourly_has_activity(hourly_data):
        return

    hours = empty_hour_slots()
    for rec in _load_stored_bots(db, account_id):
        for entry in rec.get("completed_cycles") or []:
            if not entry or not isinstance(entry, dict):
                continue
            if ts_to_date_tr(entry.get("completed_at")) != date_tr:
                continue
            sym_row = rec.get("symbol") or ""
            pnl, fees = _cycle_ledger_amounts(entry, symbol=sym_row)
            if abs(pnl) < 1e-15 and fees <= 0:
                continue
            h = hour_tr(entry.get("completed_at"))
            if h < 0 or h > 23:
                h = max(0, min(23, h))
            hours[h][0] = round(float(hours[h][0]) + pnl, 4)
            hours[h][1] = round(float(hours[h][1]) + fees, 4)

    def _slots_active(slots: List[List[float]]) -> bool:
        return any(abs(s[0]) >= 1e-9 or s[1] > 0 for s in slots)

    if not _slots_active(hours):
        ledger = load_daily_ledger(account_id)
        day = (ledger.get("days") or {}).get(date_tr) or {}
        day_pnl = float(day.get("p") or 0)
        day_fees = float(day.get("f") or 0)
        if abs(day_pnl) < 1e-9 and day_fees <= 0:
            db_rows = _query_daily_series(db, account_id, date_tr, date_tr)
            if db_rows:
                day_pnl = float(db_rows[0].get("pnl_usd") or 0)
                day_fees = float(db_rows[0].get("fees_usd") or 0)
        if abs(day_pnl) >= 1e-9 or day_fees > 0:
            today_str = datetime.now(TR_TZ).strftime("%Y-%m-%d")
            h = hour_tr() if date_tr == today_str else 12
            hours[h][0] = round(day_pnl, 4)
            hours[h][1] = round(day_fees, 4)

    if _slots_active(hours):
        write_hourly_data(account_id, date_tr, hours)


def _collect_rounds_for_period(
    db: Session,
    account_id: int,
    date_from: str,
    date_to: str,
    *,
    force_rebuild: bool = False,
) -> List[Dict[str, Any]]:
    """
    TR [date_from, date_to] içindeki kapanan turlar — dosya + canlı state birleşimi.
    Günlük ⊂ Haftalık ⊂ Aylık ⊂ Genel (aynı tur toplama mantığı, aralık genişler).
    """
    from app.services.bot_perf_file_store import (
        list_bot_completed_cycles,
        query_account_rounds_by_date_range,
        round_row_key,
        _raw_round_from_entry,
    )

    ensure_account_rounds_ledger(db, account_id, force_rebuild=force_rebuild)
    rounds = query_account_rounds_by_date_range(account_id, date_from, date_to)
    seen = {round_row_key(r) for r in rounds if isinstance(r, dict)}

    def _append_cycles(bot_id: int, symbol: str, cycles: List[Dict[str, Any]]) -> None:
        for entry in cycles or []:
            if not isinstance(entry, dict):
                continue
            d = ts_to_date_tr(entry.get("completed_at"))
            if not d or d < date_from or d > date_to:
                continue
            row = _raw_round_from_entry(bot_id, account_id, symbol, entry)
            if not row:
                continue
            key = round_row_key(row)
            if key in seen:
                continue
            seen.add(key)
            rounds.append(row)

    for bot in db.query(Bot).filter(Bot.account_id == account_id).all():
        if not _is_trailing_dual_dca(bot):
            continue
        sym = bot.symbol or ""
        state = load_state(db, bot.id)
        _append_cycles(
            int(bot.id), sym, (state or {}).get("completed_cycle_dual_pnls") or []
        )

    for rec in _load_stored_bots(db, account_id):
        bid = int(rec["bot_id"])
        sym = rec.get("symbol") or ""
        cycles = rec.get("completed_cycles") or []
        if not cycles:
            cycles = list_bot_completed_cycles(bid)
        _append_cycles(bid, sym, cycles if isinstance(cycles, list) else [])

    return rounds


def _build_breakdown(
    db: Session, account_id: int, period: str, *, force_rebuild: bool = False
) -> Dict[str, Any]:
    from app.services.bot_perf_file_store import sum_rounds_totals

    norm = normalize_perf_period(period)
    date_from_opt, date_to, label = resolve_perf_date_range(
        period, account_id=account_id
    )
    date_from = date_from_opt or _resolve_date_from_file(account_id, None)

    rounds = _collect_rounds_for_period(
        db, account_id, date_from, date_to, force_rebuild=force_rebuild
    )
    totals_pnl, totals_fees = sum_rounds_totals(rounds)

    return {
        "period": norm,
        "period_api": period,
        "period_label": label,
        "date_from": date_from if norm != "day" else date_to,
        "date_to": date_to,
        "totals": {
            "pnl_usd": totals_pnl,
            "fees_usd": totals_fees,
        },
        "pnl_usd": totals_pnl,
        "hourly_series": [],
        "daily_series": [],
        "cached": False,
    }


def _normalize_date_tr(value: Any) -> Optional[str]:
    """API/cache: YYYY-MM-DD (TR takvim günü); UTC ve saat bilgisini at."""
    if value is None:
        return None
    s = str(value).strip().replace(" UTC", "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def _ensure_date_range_on_result(
    db: Session, account_id: int, result: Dict[str, Any], period: str
) -> Dict[str, Any]:
    """date_from/date_to her zaman YYYY-MM-DD (Genel dahil)."""
    df = _normalize_date_tr(result.get("date_from"))
    dt = _normalize_date_tr(result.get("date_to"))
    if df and dt and df not in ("—", "-") and dt not in ("—", "-"):
        result["date_from"] = df
        result["date_to"] = dt
        return result
    date_from_opt, date_to, _label = resolve_perf_date_range(
        period, account_id=account_id
    )
    norm = normalize_perf_period(period)
    if norm == "day":
        result["date_from"] = date_to
        result["date_to"] = date_to
    else:
        result["date_from"] = date_from_opt or _resolve_date_from_file(account_id, None)
        result["date_to"] = date_to
    return result


def _load_perf_cache(
    db: Session, account_id: int, period_norm: str
) -> Optional[Dict[str, Any]]:
    try:
        row = db.execute(
            text("""
                SELECT payload_json FROM account_performance_cache
                WHERE account_id = :aid AND period = :p
            """),
            {"aid": account_id, "p": period_norm},
        ).fetchone()
        if not row or not row[0]:
            return None
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return None
        if data.get("date_from"):
            data["date_from"] = _normalize_date_tr(data["date_from"])
        if data.get("date_to"):
            data["date_to"] = _normalize_date_tr(data["date_to"])
        df = data.get("date_from")
        dt = data.get("date_to")
        if not df or not dt or df in ("—", "-") or dt in ("—", "-"):
            return None
        try:
            from app.services.bot_perf_file_store import account_rounds_revision

            if data.get("rounds_u") != account_rounds_revision(account_id):
                return None
        except Exception:
            pass
        data["cached"] = True
        return data
    except Exception as e:
        logger.debug("_load_perf_cache account_id=%s: %s", account_id, e)
    return None


def _save_perf_cache(
    db: Session, account_id: int, period_norm: str, payload: Dict[str, Any]
) -> None:
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        body = dict(payload)
        body.pop("cached", None)
        try:
            from app.services.bot_perf_file_store import account_rounds_revision

            body["rounds_u"] = account_rounds_revision(account_id)
        except Exception:
            pass
        series = body.get("daily_series")
        if isinstance(series, list) and len(series) > 93:
            body["daily_series"] = series[-93:]
        hourly = body.get("hourly_series")
        if isinstance(hourly, list) and len(hourly) > 24:
            body["hourly_series"] = hourly[-24:]
        db.execute(
            text("""
                INSERT INTO account_performance_cache (account_id, period, payload_json, updated_at)
                VALUES (:aid, :p, :json, :ts)
                ON CONFLICT(account_id, period) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
            """),
            {
                "aid": account_id,
                "p": period_norm,
                "json": json.dumps(body, ensure_ascii=False),
                "ts": now_iso,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning("_save_perf_cache account_id=%s: %s", account_id, e)
        try:
            db.rollback()
        except Exception:
            pass


def get_account_performance_breakdown(
    db: Session,
    account_id: int,
    period: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Günlük dosya + saatlik dosyadan hesap geneli K/Z; DB yedek/backfill."""
    norm = normalize_perf_period(period)
    if force_refresh:
        invalidate_account_performance_cache(db, account_id)
    elif norm != "day":
        cached = _load_perf_cache(db, account_id, norm)
        if cached is not None:
            return _ensure_date_range_on_result(db, account_id, cached, period)

    ensure_account_daily_ledger(db, account_id, force_rebuild=force_refresh)
    result = _build_breakdown(db, account_id, period, force_rebuild=force_refresh)
    result = _ensure_date_range_on_result(db, account_id, result, period)
    if norm != "day":
        _save_perf_cache(db, account_id, norm, result)
    return result
