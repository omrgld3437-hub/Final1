"""
FILE: finance_reports.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: Finance Reports & Analytics API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio
import json
import time

from app.db.session import get_db
from app.db.models import Account, TradeNormalized, AssetSnapshot, Bot
from app.utils.tz_utils import turkey_today_start_utc, parse_binance_ms_to_utc_naive
from app.services.finance_trade_sync import TradeSyncService
from app.services.finance_snapshot import SnapshotService
from app.services.finance_pnl_calculator import FinancePnlCalculator
from app.services.pnl_service import PnlService
from app.api.auth import require_auth, require_account_access

router = APIRouter()

# Trade sync: aynı anda tek sync (tüm hesaplar), ve hesap başına 5 dk cooldown
_trade_sync_lock = asyncio.Lock()
_trade_sync_last_at: Dict[int, float] = {}
TRADE_SYNC_COOLDOWN_SEC = 600  # 10 dakika (Binance 6000 weight/dk; myTrades agir)

# GET /finance/trades: start/end verilmezse son N gün (sınırsız sorgu ~30s+ önlenir)
FINANCE_TRADES_DEFAULT_DAYS = 365
# type_filter=all için daha kısa varsayılan aralık (SLOW_REQUEST 30s+ önleme)
FINANCE_TRADES_ALL_DEFAULT_DAYS = 90
FINANCE_TRADES_ALL_MAX_ROWS = (
    5000  # type_filter=all tek istekte en fazla bu kadar fill çekilir
)

# Deposit/withdraw kısa süreli cache (aynı hesap/tarih tekrar istekte Binance'e gitmesin)
_deposit_withdraw_cache: Dict[
    tuple, tuple
] = {}  # (account_id, start_ms, end_ms, symbol_filter) -> (deposits, withdrawals, expiry_ts)
_DEPOSIT_WITHDRAW_CACHE_TTL_SEC = 300  # 5 dakika
_DEPOSIT_WITHDRAW_FAILURE_CACHE_TTL_SEC = (
    90  # geçici Binance hatasında boş cache (tekrarlı SAPI spam önleme)
)
_DEPOSIT_WITHDRAW_CACHE_BUCKET_MS = 5 * 60 * 1000

# Deposit/withdraw 400/401 hata log throttle: aynı hesap+endpoint için en fazla 5 dakikada bir WARNING
_deposit_withdraw_error_ts: Dict[tuple, float] = {}
_deposit_withdraw_error_lock = asyncio.Lock()
_DEPOSIT_WITHDRAW_ERROR_THROTTLE_SEC = 300.0


def _bot_initial_usd(bot: Bot) -> float:
    try:
        config = json.loads(bot.config_json or "{}")
    except Exception:
        config = {}
    try:
        return float(
            config.get("initial_capital_usdt")
            or config.get("budget_usd")
            or config.get("bot_budget_usdt")
            or config.get("bot_budget_quote")
            or 0
        )
    except (TypeError, ValueError):
        return 0.0


def _bot_current_equity_usd(
    db: Session, bot: Bot, account_id: int
) -> tuple[float, float]:
    initial_usd = _bot_initial_usd(bot)
    pnl_data = PnlService.calculate_bot_pnl(db, bot.id, account_id)
    current_usd = (
        pnl_data.get("total_usd", initial_usd)
        if not pnl_data.get("error")
        else initial_usd
    )
    try:
        from app.botengine.state_store import load_state
        from app.services.bot_equity import compute_bot_equity_usd

        state = load_state(db, bot.id) or {}
        current_usd = compute_bot_equity_usd(
            db, bot, state, pnl_data, initial_usd=initial_usd
        )
    except Exception:
        pass
    return float(current_usd or 0.0), float(initial_usd or 0.0)


def _finance_bot_summary_row(
    bot: Bot, bot_pnl_30d: Dict, current_usd: float, initial_usd: float
) -> Dict:
    mark_to_market_pnl = current_usd - initial_usd
    mark_to_market_pct = (
        (mark_to_market_pnl / initial_usd * 100.0) if initial_usd > 0 else 0.0
    )
    realized_30d = float(bot_pnl_30d.get("pnl") or 0.0)
    return {
        "bot_id": bot.id,
        "id": bot.id,
        "symbol": bot.symbol,
        "status": bot.status,
        "mode": bot.mode,
        "pnl_30d": realized_30d,
        "realized_30d_pnl_usd": round(realized_30d, 2),
        "mark_to_market_pnl_usd": round(mark_to_market_pnl, 2),
        "total_pnl": round(mark_to_market_pnl, 2),
        "total_pnl_usd": round(mark_to_market_pnl, 2),
        "total_pnl_pct": round(mark_to_market_pct, 2),
        "fees": float(bot_pnl_30d.get("fees") or 0.0),
        "trades_count": int(bot_pnl_30d.get("count") or 0),
        "budget_usd": round(initial_usd, 2),
        "initial_usd": round(initial_usd, 2),
        "current_usd": round(current_usd, 2),
        "created_at": bot.created_at.isoformat()
        if hasattr(bot, "created_at") and bot.created_at
        else None,
        "started_at": bot.started_at.isoformat()
        if hasattr(bot, "started_at") and bot.started_at
        else None,
    }


async def _should_log_deposit_withdraw_error(account_id: int, kind: str) -> bool:
    """Aynı account_id+kind için True döner (log yazılacak); throttle süresi dolmamışsa False."""
    key = (account_id, kind)
    now = time.time()
    async with _deposit_withdraw_error_lock:
        last = _deposit_withdraw_error_ts.get(key)
        if last is not None and (now - last) < _DEPOSIT_WITHDRAW_ERROR_THROTTLE_SEC:
            return False
        _deposit_withdraw_error_ts[key] = now
        if len(_deposit_withdraw_error_ts) > 200:
            cutoff = now - _DEPOSIT_WITHDRAW_ERROR_THROTTLE_SEC * 2
            for k in [x for x, t in _deposit_withdraw_error_ts.items() if t < cutoff]:
                del _deposit_withdraw_error_ts[k]
        return True


@router.get("/finance/summary")
async def get_finance_summary(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Get finance summary: total value, PnL, top gainers/losers, bot summary. Auth required.
    """
    require_account_access(current, account_id)
    import logging

    logger = logging.getLogger(__name__)

    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Get latest snapshot
        latest_snapshot = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(desc(AssetSnapshot.timestamp))
            .first()
        )

        total_usd_value = latest_snapshot.total_usd_value if latest_snapshot else 0.0

        # Get initial value (first snapshot or sum of bot initial balances)
        initial_value = 0.0
        first_snapshot = (
            db.query(AssetSnapshot)
            .filter(AssetSnapshot.account_id == account_id)
            .order_by(AssetSnapshot.timestamp.asc())
            .first()
        )

        if first_snapshot:
            initial_value = first_snapshot.total_usd_value
        else:
            # Fallback: sum of bot initial balances
            bots = db.query(Bot).filter(Bot.account_id == account_id).all()
            for bot in bots:
                try:
                    config = json.loads(bot.config_json or "{}")
                    initial_value += float(
                        config.get("budget_usd") or config.get("bot_budget_quote") or 0
                    )
                except:
                    pass

        # Calculate PnL for today, last 7d and 30d. Bugün = Türkiye saati.
        now = datetime.utcnow()
        today_start = turkey_today_start_utc()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        calculator = FinancePnlCalculator(db)
        # Note: calculate_realized_pnl doesn't use prices yet, but commission_usd is calculated in trades endpoint
        pnl_today = calculator.calculate_realized_pnl(account_id, today_start, now)
        pnl_7d = calculator.calculate_realized_pnl(account_id, last_7d, now)
        pnl_30d = calculator.calculate_realized_pnl(account_id, last_30d, now)

        # Get unrealized PnL
        unrealized_data = calculator.calculate_unrealized_pnl(account_id)

        # Top gainers/losers (by symbol)
        top_gainers = sorted(
            pnl_30d["by_symbol"].items(), key=lambda x: x[1]["pnl"], reverse=True
        )[:5]
        top_losers = sorted(pnl_30d["by_symbol"].items(), key=lambda x: x[1]["pnl"])[:5]

        # Bot summary (current_usd = bot detay state panel ile aynı kaynak; toplam = KPI Bot Bakiyesi)
        bots = db.query(Bot).filter(Bot.account_id == account_id).all()
        bot_summary = []
        total_bot_equity_usd = 0.0
        for bot in bots:
            bot_pnl = pnl_30d["by_bot"].get(
                bot.id, {"pnl": 0.0, "fees": 0.0, "count": 0}
            )
            current_usd, initial_balance = _bot_current_equity_usd(db, bot, account_id)
            total_bot_equity_usd += current_usd
            bot_summary.append(
                _finance_bot_summary_row(bot, bot_pnl, current_usd, initial_balance)
            )

        # Günlük bot PnL = sadece o gün tamamlanan turların (cycle) kârlarının toplamı (dashboard KPI ile aynı)
        daily_bot_pnl_usd = PnlService.daily_realized_from_cycles_completed_today(
            db, account_id
        )
        daily_wallet_pnl_usd = 0.0
        wallet_start_of_day_usd = None
        try:
            last_wallet_before_today = (
                db.query(AssetSnapshot)
                .filter(
                    AssetSnapshot.account_id == account_id,
                    AssetSnapshot.timestamp < today_start,
                )
                .order_by(desc(AssetSnapshot.timestamp))
                .first()
            )
            if last_wallet_before_today and total_usd_value is not None:
                wallet_start_of_day_usd = float(
                    last_wallet_before_today.total_usd_value
                )
                daily_wallet_pnl_usd = float(total_usd_value) - wallet_start_of_day_usd
            else:
                first_snap_today = (
                    db.query(AssetSnapshot)
                    .filter(
                        AssetSnapshot.account_id == account_id,
                        AssetSnapshot.timestamp >= today_start,
                    )
                    .order_by(AssetSnapshot.timestamp.asc())
                    .first()
                )
                if first_snap_today and total_usd_value is not None:
                    wallet_start_of_day_usd = float(first_snap_today.total_usd_value)
                    daily_wallet_pnl_usd = (
                        float(total_usd_value) - wallet_start_of_day_usd
                    )
        except Exception:
            pass

        out = {
            "total_usd_value": total_usd_value,
            "initial_value": initial_value,
            "bots_balance_usd": round(total_bot_equity_usd, 2),
            "account": {
                "bots_balance_usd": round(total_bot_equity_usd, 2),
                "daily_bot_pnl_usd": round(daily_bot_pnl_usd, 2),
            },
            "daily_bot_pnl_usd": daily_bot_pnl_usd,
            "daily_wallet_pnl_usd": daily_wallet_pnl_usd,
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
            "top_gainers": [{"symbol": s, **d} for s, d in top_gainers],
            "top_losers": [{"symbol": s, **d} for s, d in top_losers],
            "bot_summary": bot_summary,
        }
        if wallet_start_of_day_usd is not None:
            out["wallet_start_of_day_usd"] = round(wallet_start_of_day_usd, 2)
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[finance/summary] Error: {e}")
        # Return minimal summary instead of 500 error
        return {
            "total_usd_value": 0.0,
            "initial_value": 0.0,
            "daily_bot_pnl_usd": 0.0,
            "daily_wallet_pnl_usd": 0.0,
            "today": {"pnl": 0.0, "fees": 0.0, "trades_count": 0},
            "last_7d": {"pnl": 0.0, "fees": 0.0, "trades_count": 0},
            "last_30d": {"pnl": 0.0, "fees": 0.0, "trades_count": 0},
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "top_gainers": [],
            "top_losers": [],
            "bot_summary": [],
            "data_status": "error",
            "error": str(e),
        }


@router.get("/finance/equity-curve")
async def get_equity_curve(
    account_id: int = Query(..., description="Account ID"),
    range: str = Query("7d", description="Range: 7d, 30d, custom"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Get equity curve data (time series). Auth required.
    """
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    snapshot_service = SnapshotService(db)

    start_time = None
    end_time = None

    if range == "7d":
        start_time = datetime.utcnow() - timedelta(days=7)
    elif range == "30d":
        start_time = datetime.utcnow() - timedelta(days=30)
    elif range == "custom" and start and end:
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))

    curve_data = snapshot_service.get_equity_curve(account_id, start_time, end_time)

    return {"account_id": account_id, "range": range, "data": curve_data}


@router.get("/finance/report")
async def get_finance_report(
    account_id: int = Query(..., description="Account ID"),
    period: str = Query("weekly", description="Period: daily, weekly, monthly, yearly"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Performans raporu: seçilen dönemde gerçekleşen kar (alım satım, yatırım/çekim hariç) ve komisyonlar.
    """
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    now = datetime.utcnow()
    today_start = turkey_today_start_utc()

    def _naive_utc(dt: datetime) -> datetime:
        """Ensure datetime is naive UTC for DB comparison (TradeNormalized.time is naive UTC)."""
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    if start and end:
        period_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        period_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        period_start = _naive_utc(period_start)
        period_end = _naive_utc(period_end)
    elif period == "daily":
        period_start = today_start
        period_end = now
    elif period == "weekly":
        period_start = now - timedelta(days=7)
        period_end = now
    elif period == "monthly":
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = now
    elif period == "yearly":
        period_start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        period_end = now
    else:
        period_start = now - timedelta(days=7)
        period_end = now

    # Ensure naive UTC for DB
    if getattr(period_start, "tzinfo", None):
        period_start = _naive_utc(period_start)
    if getattr(period_end, "tzinfo", None):
        period_end = _naive_utc(period_end)

    calculator = FinancePnlCalculator(db)
    pnl_data = calculator.calculate_realized_pnl(account_id, period_start, period_end)

    # Calculate metrics
    db.query(TradeNormalized).filter(
        TradeNormalized.account_id == account_id,
        TradeNormalized.time >= period_start,
        TradeNormalized.time <= period_end,
    ).all()

    # Win rate, profit factor, etc.
    gross_profit = 0.0
    gross_loss = 0.0

    # Simplified: calculate from realized PnL by symbol
    for symbol, data in pnl_data["by_symbol"].items():
        if data["pnl"] > 0:
            gross_profit += data["pnl"]
        else:
            gross_loss += abs(data["pnl"])

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    win_rate = (
        len([s for s, d in pnl_data["by_symbol"].items() if d["pnl"] > 0])
        / len(pnl_data["by_symbol"])
        if pnl_data["by_symbol"]
        else 0.0
    )

    return {
        "account_id": account_id,
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "realized_pnl": pnl_data["realized_pnl"],
        "fees": pnl_data["fees"],
        "net_pnl": pnl_data["realized_pnl"] - pnl_data["fees"],
        "trades_count": pnl_data["trades_count"],
        "by_symbol": pnl_data["by_symbol"],
        "by_bot": pnl_data["by_bot"],
        "metrics": {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        },
    }


_DEPOSIT_WITHDRAW_CACHE_MAX_KEYS = 100


def _clean_deposit_withdraw_cache():
    """Süresi dolan cache girdilerini temizle; max key sayısını aşmayı önle (RAM stabilitesi)."""
    now = time.monotonic()
    to_del = [
        k for k, v in _deposit_withdraw_cache.items() if len(v) >= 3 and v[2] < now
    ]
    for k in to_del:
        _deposit_withdraw_cache.pop(k, None)
    if len(_deposit_withdraw_cache) > _DEPOSIT_WITHDRAW_CACHE_MAX_KEYS:
        by_expiry = sorted(
            _deposit_withdraw_cache.items(),
            key=lambda x: x[1][2] if len(x[1]) >= 3 else 0,
        )
        for k, _ in by_expiry[
            : len(_deposit_withdraw_cache) - _DEPOSIT_WITHDRAW_CACHE_MAX_KEYS
        ]:
            _deposit_withdraw_cache.pop(k, None)


def _deposit_withdraw_cache_key(
    account_id: int,
    start_ms: int,
    end_ms: int,
    symbol_filter: Optional[str],
) -> tuple:
    """Bucket moving date ranges so repeated dashboard refreshes reuse the same SAPI result."""
    bucket = max(1, _DEPOSIT_WITHDRAW_CACHE_BUCKET_MS)
    key_start_ms = (int(start_ms) // bucket) * bucket
    key_end_ms = (int(end_ms) // bucket) * bucket
    if key_end_ms < key_start_ms:
        key_end_ms = int(end_ms)
    return (int(account_id), key_start_ms, key_end_ms, symbol_filter or "")


async def _fetch_deposit_withdraw(
    account_id: int,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    symbol_filter: Optional[str],
    db: Session,
) -> Tuple[List[Dict], List[Dict]]:
    """Binance SAPI'den yatırım ve çekim listesini çeker; 2 dk cache. (deposits, withdrawals) döner."""
    from app.services.test_account import is_test_account

    if is_test_account(account_id, db):
        return [], []
    import httpx
    from app.services.binance_assets import get_account_keys
    from app.services.binance_spot import _signed_request

    # Tarih yoksa son 90 gün (Binance SAPI sınırı)
    now = datetime.utcnow().replace(tzinfo=None)
    if end_time is None:
        end_time = now
    if start_time is None:
        start_time = now - timedelta(days=90)
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    # Binance: Time interval within 0-90 days; endTime must not be in the future
    ninety_days_ms = 90 * 24 * 3600 * 1000
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    if end_ms > now_ms:
        end_ms = now_ms
    if start_ms >= end_ms:
        start_ms = max(0, end_ms - ninety_days_ms)
    if end_ms - start_ms > ninety_days_ms:
        start_ms = end_ms - ninety_days_ms
    cache_key = _deposit_withdraw_cache_key(account_id, start_ms, end_ms, symbol_filter)
    _clean_deposit_withdraw_cache()
    cached = _deposit_withdraw_cache.get(cache_key)
    if cached is not None and len(cached) >= 3 and cached[2] > time.monotonic():
        return list(cached[0]), list(cached[1])

    try:
        keys = await get_account_keys(account_id, db)
    except Exception:
        return [], []

    deposits: List[Dict] = []
    withdrawals: List[Dict] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            params = {"startTime": start_ms, "endTime": end_ms, "limit": 1000}
            data = await _signed_request(
                client, "GET", "/sapi/v1/capital/deposit/hisrec", keys, params
            )
            if isinstance(data, list):
                deposits = data
            elif isinstance(data, dict) and "data" in data:
                deposits = data.get("data", [])
        except Exception as e:
            import logging
            from app.services.binance_spot import is_transient_upstream_error

            _log = logging.getLogger(__name__)
            if is_transient_upstream_error(e):
                _log.debug("deposit hisrec transient account_id=%s: %s", account_id, e)
                expiry = time.monotonic() + _DEPOSIT_WITHDRAW_FAILURE_CACHE_TTL_SEC
                _deposit_withdraw_cache[cache_key] = (deposits, withdrawals, expiry)
            elif await _should_log_deposit_withdraw_error(account_id, "deposit"):
                if getattr(e, "response", None) and getattr(
                    e.response, "status_code", None
                ) in (400, 401):
                    _log.debug(
                        "deposit hisrec account_id=%s: API anahtari gecersiz veya bu endpoint icin izin yok.",
                        account_id,
                    )
                else:
                    _log.warning(
                        "deposit hisrec error account_id=%s: %s", account_id, e
                    )
        try:
            params = {"startTime": start_ms, "endTime": end_ms, "limit": 1000}
            data = await _signed_request(
                client, "GET", "/sapi/v1/capital/withdraw/history", keys, params
            )
            if isinstance(data, list):
                withdrawals = data
            elif isinstance(data, dict) and "data" in data:
                withdrawals = data.get("data", [])
        except Exception as e:
            import logging
            from app.services.binance_spot import is_transient_upstream_error

            _log = logging.getLogger(__name__)
            if is_transient_upstream_error(e):
                _log.debug(
                    "withdraw history transient account_id=%s: %s", account_id, e
                )
                expiry = time.monotonic() + _DEPOSIT_WITHDRAW_FAILURE_CACHE_TTL_SEC
                _deposit_withdraw_cache[cache_key] = (deposits, withdrawals, expiry)
            elif await _should_log_deposit_withdraw_error(account_id, "withdraw"):
                if getattr(e, "response", None) and getattr(
                    e.response, "status_code", None
                ) in (400, 401):
                    _log.debug(
                        "withdraw history account_id=%s: API anahtari gecersiz veya bu endpoint icin izin yok.",
                        account_id,
                    )
                else:
                    _log.warning(
                        "withdraw history error account_id=%s: %s", account_id, e
                    )

    if symbol_filter:
        sym = symbol_filter.upper()
        deposits = [d for d in deposits if (d.get("coin") or "").upper() == sym]
        withdrawals = [w for w in withdrawals if (w.get("coin") or "").upper() == sym]
    expiry = time.monotonic() + _DEPOSIT_WITHDRAW_CACHE_TTL_SEC
    _deposit_withdraw_cache[cache_key] = (deposits, withdrawals, expiry)
    return deposits, withdrawals


def _normalize_deposit(row: Dict, insert_time: datetime) -> Dict:
    coin = (row.get("coin") or "").upper()
    amount = float(row.get("amount") or 0)
    return {
        "order_id": f"deposit_{row.get('id', row.get('txId', id(row)))}",
        "symbol": coin or "—",
        "side": "DEPOSIT",
        "type": "DEPOSIT",
        "executed_qty": amount,
        "avg_price": None,
        "quote_qty": 0,
        "commission": 0,
        "commission_usd": 0,
        "commission_asset": "",
        "first_fill_time": _utc_iso(insert_time),
        "last_fill_time": _utc_iso(insert_time),
        "time": _utc_iso(insert_time),
        "fills_count": 1,
        "bot_id": None,
        "is_bot": False,
        "source_label": "Binance",
    }


def _normalize_withdraw(row: Dict, apply_time: datetime) -> Dict:
    coin = (row.get("coin") or "").upper()
    amount = float(row.get("amount") or 0)
    return {
        "order_id": f"withdraw_{row.get('id', row.get('withdrawOrderId', id(row)))}",
        "symbol": coin or "—",
        "side": "WITHDRAW",
        "type": "WITHDRAW",
        "executed_qty": amount,
        "avg_price": None,
        "quote_qty": 0,
        "commission": float(row.get("transactionFee") or 0),
        "commission_usd": 0,
        "commission_asset": coin or "",
        "first_fill_time": _utc_iso(apply_time),
        "last_fill_time": _utc_iso(apply_time),
        "time": _utc_iso(apply_time),
        "fills_count": 1,
        "bot_id": None,
        "is_bot": False,
        "source_label": "Binance",
    }


def _naive_utc(dt: datetime) -> datetime:
    """Ensure datetime is naive UTC for DB comparison (TradeNormalized.time is naive UTC)."""
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_iso(dt: datetime) -> str:
    """Return ISO string with Z suffix so frontend parses as UTC (Turkey time display)."""
    s = dt.isoformat()
    return s if (s.endswith("Z") or "+" in s) else s + "Z"


@router.get("/finance/trades")
async def get_finance_trades(
    account_id: int = Query(..., description="Account ID"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    type_filter: Optional[str] = Query(
        None, description="all | buysell | depositwithdraw"
    ),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    bot_id: Optional[int] = Query(None, description="Filter by bot ID"),
    side: Optional[str] = Query(None, description="Filter by side: BUY/SELL"),
    limit: int = Query(100, description="Limit"),
    offset: int = Query(0, description="Offset"),
    sync: int = Query(
        0, description="1 = sync trades from Binance and fetch deposit/withdraw"
    ),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Get executed trades (order-based grouping) + deposit/withdraw from Binance. Auth required.
    - type_filter: all (default) = trades + deposit/withdraw; buysell = only alış/satış; depositwithdraw = only yatırım/çekim.
    - sync=1: sync myTrades and fetch deposit/withdraw so data is fresh when user opens İşlemler.
    """
    require_account_access(current, account_id)
    import logging

    logger = logging.getLogger(__name__)

    try:
        from sqlalchemy import func, distinct, case

        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Test (paper) hesabı: TradeNormalized boş, Trade tablosundan gerçekleşmiş bot işlemlerini döndür
        from app.services.test_account import is_test_account

        if is_test_account(account_id, db):
            return await _get_test_account_trades(
                account_id=account_id,
                start=start,
                end=end,
                type_filter=type_filter,
                symbol=symbol,
                bot_id=bot_id,
                side=side,
                limit=limit,
                offset=offset,
                db=db,
            )

        if sync:
            now = time.monotonic()
            last = _trade_sync_last_at.get(account_id, 0)
            if now - last < TRADE_SYNC_COOLDOWN_SEC:
                logger.info(
                    "[finance/trades] sync skipped (cooldown) account_id=%s", account_id
                )
            else:
                async with _trade_sync_lock:
                    last = _trade_sync_last_at.get(account_id, 0)
                    if now - last < TRADE_SYNC_COOLDOWN_SEC:
                        pass
                    else:
                        try:
                            _trade_sync_last_at[account_id] = time.monotonic()
                            svc = TradeSyncService(db)
                            await svc.sync_account_trades(account_id)
                        except Exception as e:
                            logger.warning(
                                "[finance/trades] sync_account_trades failed: %s", e
                            )

        start_time = None
        end_time = None
        if start:
            start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start_time = _naive_utc(start_time)
        if end:
            end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
            end_time = _naive_utc(end_time)

        # Tür filtresi: depositwithdraw = sadece yatırım/çekim (alış/satış HİÇ dönülmez)
        tf = (type_filter or "").strip().lower()
        if tf in ("depositwithdraw", "deposit_withdraw", "yatirim_cekim"):
            deposits, withdrawals = await _fetch_deposit_withdraw(
                account_id, start_time, end_time, symbol, db
            )
            start_naive = start_time
            end_naive = end_time
            dep_rows = []
            for d in deposits:
                insert_time = parse_binance_ms_to_utc_naive(d.get("insertTime"))
                if insert_time is None:
                    continue
                if start_naive and insert_time < start_naive:
                    continue
                if end_naive and insert_time > end_naive:
                    continue
                dep_rows.append(_normalize_deposit(d, insert_time))
            withdraw_rows = []
            for w in withdrawals:
                apply_time = parse_binance_ms_to_utc_naive(
                    w.get("applyTime") or w.get("completeTime")
                )
                if apply_time is None:
                    continue
                if start_naive and apply_time < start_naive:
                    continue
                if end_naive and apply_time > end_naive:
                    continue
                withdraw_rows.append(_normalize_withdraw(w, apply_time))
            combined = dep_rows + withdraw_rows
            combined.sort(key=lambda x: x["time"], reverse=True)
            total_orders = len(combined)
            paginated_orders = combined[offset : offset + limit]
            return {
                "total": total_orders,
                "limit": limit,
                "offset": offset,
                "trades": paginated_orders,
                "data_status": "ready",
                "request_id": f"req_{datetime.utcnow().timestamp()}",
            }

        # start/end yoksa son N gün (sınırsız sorgu 30s+ önlenir); type_filter=all için kısa aralık
        if start_time is None and end_time is None:
            now_utc = datetime.utcnow()
            end_time = now_utc
            default_days = (
                FINANCE_TRADES_ALL_DEFAULT_DAYS
                if (tf in ("all", ""))
                else FINANCE_TRADES_DEFAULT_DAYS
            )
            start_time = now_utc - timedelta(days=default_days)

        # Alış/satım (BUY/SELL) – TradeNormalized (Binance myTrades)
        base_query = db.query(TradeNormalized).filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"]),
        )
        if start_time is not None:
            base_query = base_query.filter(TradeNormalized.time >= start_time)
        if end_time is not None:
            base_query = base_query.filter(TradeNormalized.time <= end_time)
        if symbol:
            base_query = base_query.filter(TradeNormalized.symbol == symbol.upper())
        if bot_id:
            base_query = base_query.filter(TradeNormalized.bot_id == bot_id)
        if side:
            base_query = base_query.filter(TradeNormalized.side == side.upper())

        total_query = db.query(
            func.count(
                distinct(
                    case(
                        (
                            TradeNormalized.order_id.isnot(None),
                            TradeNormalized.order_id,
                        ),
                        else_=TradeNormalized.trade_id,
                    )
                )
            )
        ).filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"]),
        )
        if start_time is not None:
            total_query = total_query.filter(TradeNormalized.time >= start_time)
        if end_time is not None:
            total_query = total_query.filter(TradeNormalized.time <= end_time)
        if symbol:
            total_query = total_query.filter(TradeNormalized.symbol == symbol.upper())
        if bot_id:
            total_query = total_query.filter(TradeNormalized.bot_id == bot_id)
        if side:
            total_query = total_query.filter(TradeNormalized.side == side.upper())

        total_orders = total_query.scalar() or 0

        # Paginate at DB when only buysell: fetch order_keys for this page, then their fills (avoids loading 365 days)
        tf = (type_filter or "").strip().lower()
        use_db_pagination = tf == "buysell"
        order_key_col = func.coalesce(
            TradeNormalized.order_id, TradeNormalized.trade_id
        )

        if use_db_pagination:
            page_keys_query = db.query(
                order_key_col.label("ok"), func.max(TradeNormalized.time).label("mt")
            ).filter(
                TradeNormalized.account_id == account_id,
                TradeNormalized.side.in_(["BUY", "SELL"]),
            )
            if start_time is not None:
                page_keys_query = page_keys_query.filter(
                    TradeNormalized.time >= start_time
                )
            if end_time is not None:
                page_keys_query = page_keys_query.filter(
                    TradeNormalized.time <= end_time
                )
            if symbol:
                page_keys_query = page_keys_query.filter(
                    TradeNormalized.symbol == symbol.upper()
                )
            if bot_id:
                page_keys_query = page_keys_query.filter(
                    TradeNormalized.bot_id == bot_id
                )
            if side:
                page_keys_query = page_keys_query.filter(
                    TradeNormalized.side == side.upper()
                )
            page_keys_query = (
                page_keys_query.group_by(order_key_col)
                .order_by(desc(func.max(TradeNormalized.time)))
                .limit(limit)
                .offset(offset)
            )
            order_keys_rows = page_keys_query.all()
            order_keys = [r.ok for r in order_keys_rows]
            if not order_keys:
                all_fills = []
            else:
                all_fills = (
                    base_query.filter(order_key_col.in_(order_keys))
                    .order_by(desc(TradeNormalized.time))
                    .all()
                )
        else:
            # type_filter=all: cap rows to avoid SLOW_REQUEST 30s+ (merge with deposit/withdraw then paginate)
            all_fills = (
                base_query.order_by(desc(TradeNormalized.time))
                .limit(FINANCE_TRADES_ALL_MAX_ROWS)
                .all()
            )

        prices = {}

        # Helper function to convert commission to USD
        def convert_commission_to_usd(
            commission: float, commission_asset: str
        ) -> float:
            if commission <= 0:
                return 0.0

            # Stablecoins are 1:1 with USD
            STABLES = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"]
            if commission_asset in STABLES:
                return commission

            # Try direct assetUSDT (price = USDT per 1 asset)
            sym = f"{commission_asset}USDT"
            if sym in prices and prices[sym] and float(prices[sym]) > 0:
                return commission * float(prices[sym])
            # Try USDTasset (e.g. USDTTRY: price = TRY per 1 USDT -> usd = amount / price)
            sym_inv = f"USDT{commission_asset}"
            if sym_inv in prices and prices[sym_inv] and float(prices[sym_inv]) > 0:
                return commission / float(prices[sym_inv])

            # Try via BTC
            btc_sym = f"{commission_asset}BTC"
            if btc_sym in prices and "BTCUSDT" in prices:
                return commission * prices[btc_sym] * prices["BTCUSDT"]

            # Try via ETH
            eth_sym = f"{commission_asset}ETH"
            if eth_sym in prices and "ETHUSDT" in prices:
                return commission * prices[eth_sym] * prices["ETHUSDT"]

            return 0.0

        # Group fills by order_id (or trade_id if order_id is None)
        orders_map = {}

        for fill in all_fills:
            # Use order_id as key if available, otherwise use trade_id
            order_key = fill.order_id if fill.order_id else fill.trade_id

            if order_key not in orders_map:
                orders_map[order_key] = {
                    "order_id": fill.order_id,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "executed_qty": 0.0,
                    "quote_qty": 0.0,
                    "commission": 0.0,
                    "commission_usd": 0.0,
                    "commission_asset": fill.commission_asset or "USDT",
                    "first_fill_time": fill.time,
                    "last_fill_time": fill.time,
                    "fills_count": 0,
                    "bot_id": fill.bot_id,
                    "is_bot": fill.bot_id is not None and fill.bot_id > 0,
                    "price_sum": 0.0,  # For weighted average
                    "qty_sum": 0.0,
                }

            order = orders_map[order_key]

            # Aggregate fills
            order["executed_qty"] += fill.qty
            order["quote_qty"] += fill.quote_qty
            order["commission"] += fill.commission

            # Convert commission to USD
            fill_commission_usd = convert_commission_to_usd(
                fill.commission, fill.commission_asset or "USDT"
            )
            order["commission_usd"] += fill_commission_usd

            # Update time range
            if fill.time < order["first_fill_time"]:
                order["first_fill_time"] = fill.time
            if fill.time > order["last_fill_time"]:
                order["last_fill_time"] = fill.time

            order["fills_count"] += 1

            # For weighted average price
            order["price_sum"] += fill.price * fill.qty
            order["qty_sum"] += fill.qty

        # Calculate weighted average price and finalize orders
        orders_list = []
        for order_key, order in orders_map.items():
            # Calculate weighted average price
            if order["qty_sum"] > 0:
                avg_price = order["price_sum"] / order["qty_sum"]
            else:
                avg_price = 0.0

            orders_list.append(
                {
                    "order_id": order["order_id"] or order_key,
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "executed_qty": order["executed_qty"],
                    "avg_price": avg_price,
                    "quote_qty": order["quote_qty"],
                    "commission": order["commission"],
                    "commission_usd": order["commission_usd"],
                    "commission_asset": order["commission_asset"],
                    "first_fill_time": _utc_iso(order["first_fill_time"]),
                    "last_fill_time": _utc_iso(order["last_fill_time"]),
                    "time": _utc_iso(
                        order["last_fill_time"]
                    ),  # Use last fill time for sorting
                    "fills_count": order["fills_count"],
                    "bot_id": order["bot_id"],
                    "is_bot": order["is_bot"],
                    "source_label": None,  # set below
                }
            )

        # Resolve bot_id -> symbol for source_label (Kullanıcı / Bot {symbol})
        bot_ids = {o["bot_id"] for o in orders_list if o.get("bot_id")}
        bot_map = {}
        if bot_ids:
            bots = (
                db.query(Bot)
                .filter(Bot.id.in_(bot_ids), Bot.account_id == account_id)
                .all()
            )
            bot_map = {b.id: (b.symbol or "?") for b in bots}
        for o in orders_list:
            bid = o.get("bot_id")
            if bid and bid in bot_map:
                o["source_label"] = "Bot " + bot_map[bid]
            elif bid:
                o["source_label"] = "Bot (bilinmiyor)"
            else:
                o["source_label"] = "Kullanıcı"

        # Sort by last fill time (most recent first)
        orders_list.sort(key=lambda x: x["time"], reverse=True)
        # type_filter=all ve cap uygulandıysa toplamı gerçek emir sayısına indir (sayfalama tutarlı olsun)
        if not use_db_pagination and len(all_fills) >= FINANCE_TRADES_ALL_MAX_ROWS:
            total_orders = len(orders_list)

        # type_filter=buysell -> sadece alış/satış; type_filter=all veya yok -> trades + deposit/withdraw
        if tf == "buysell":
            paginated_orders = (
                orders_list
                if use_db_pagination
                else orders_list[offset : offset + limit]
            )
            return {
                "total": total_orders,
                "limit": limit,
                "offset": offset,
                "trades": paginated_orders,
                "data_status": "ready",
                "request_id": f"req_{datetime.utcnow().timestamp()}",
            }

        # Yanıt: Tümü (trades + deposit/withdraw)
        if side is None:
            deposits, withdrawals = await _fetch_deposit_withdraw(
                account_id, start_time, end_time, symbol, db
            )
            start_naive = start_time
            end_naive = end_time
            dep_rows = []
            for d in deposits:
                insert_time = parse_binance_ms_to_utc_naive(d.get("insertTime"))
                if insert_time is None:
                    continue
                if start_naive and insert_time < start_naive:
                    continue
                if end_naive and insert_time > end_naive:
                    continue
                dep_rows.append(_normalize_deposit(d, insert_time))
            withdraw_rows = []
            for w in withdrawals:
                apply_time = parse_binance_ms_to_utc_naive(
                    w.get("applyTime") or w.get("completeTime")
                )
                if apply_time is None:
                    continue
                if start_naive and apply_time < start_naive:
                    continue
                if end_naive and apply_time > end_naive:
                    continue
                withdraw_rows.append(_normalize_withdraw(w, apply_time))
            combined = orders_list + dep_rows + withdraw_rows
            combined.sort(key=lambda x: x["time"], reverse=True)
            total_orders = len(combined)
            paginated_orders = combined[offset : offset + limit]
        else:
            paginated_orders = orders_list[offset : offset + limit]

        return {
            "total": total_orders,
            "limit": limit,
            "offset": offset,
            "trades": paginated_orders,
            "data_status": "ready",
            "request_id": f"req_{datetime.utcnow().timestamp()}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[finance/trades] Error: {e}")
        # Return empty result instead of 500 error
        return {
            "total": 0,
            "limit": limit,
            "offset": offset,
            "trades": [],
            "data_status": "error",
            "error": str(e),
            "request_id": f"req_{datetime.utcnow().timestamp()}",
        }


async def _get_test_account_trades(
    account_id: int,
    start: Optional[str],
    end: Optional[str],
    type_filter: Optional[str],
    symbol: Optional[str],
    bot_id: Optional[int],
    side: Optional[str],
    limit: int,
    offset: int,
    db: Session,
) -> Dict:
    """Test (paper) hesabı için işlem geçmişi: Trade tablosundan bot emirlerini döndür."""
    from app.db.models import Trade

    tf = (type_filter or "").strip().lower()

    # Test hesabında yatırım/çekim yoktur
    if tf in ("depositwithdraw", "deposit_withdraw", "yatirim_cekim"):
        return {
            "total": 0,
            "limit": limit,
            "offset": offset,
            "trades": [],
            "data_status": "ready",
            "is_test": True,
            "request_id": f"req_{datetime.utcnow().timestamp()}",
        }

    # Tarih aralığı
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    if start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    if end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)
    if start_dt is None and end_dt is None:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=365)

    q = db.query(Trade).filter(Trade.account_id == account_id)
    if start_dt is not None:
        q = q.filter(Trade.ts >= start_dt)
    if end_dt is not None:
        q = q.filter(Trade.ts <= end_dt)
    if symbol:
        q = q.filter(Trade.symbol == symbol.upper())
    if bot_id:
        q = q.filter(Trade.bot_id == bot_id)
    if side:
        q = q.filter(Trade.side == side.upper())

    total = q.count()
    trades = q.order_by(desc(Trade.ts)).offset(offset).limit(limit).all()

    # Bot isimlerini çöz
    bot_ids = {t.bot_id for t in trades if t.bot_id}
    bot_map: Dict[int, str] = {}
    if bot_ids:
        bots = (
            db.query(Bot)
            .filter(Bot.id.in_(bot_ids), Bot.account_id == account_id)
            .all()
        )
        bot_map = {b.id: (b.symbol or "?") for b in bots}

    rows = []
    for t in trades:
        qty = float(t.qty or 0)
        price = float(t.price or 0)
        fee = float(t.fee or 0)
        quote_qty = qty * price
        bid = t.bot_id
        source = (
            ("Bot " + bot_map[bid])
            if bid and bid in bot_map
            else ("Bot (bilinmiyor)" if bid else "Kullanıcı")
        )
        ts_iso = (t.ts.isoformat() + "Z") if t.ts else None
        side_u = (t.side or "BUY").upper()
        rows.append(
            {
                "order_id": t.order_id or f"paper_{t.id}",
                "trade_id": t.order_id or f"paper_{t.id}",
                "symbol": t.symbol or "—",
                "side": side_u,
                "type": "buy" if side_u == "BUY" else "sell",
                "type_label": "Simüle Alış" if side_u == "BUY" else "Simüle Satış",
                # _txDisplayAmounts okuma alanları
                "qty": round(qty, 8),
                "price": round(price, 8),
                "quote_qty": round(quote_qty, 4),
                # finance_reports uyumluluğu
                "executed_qty": round(qty, 8),
                "avg_price": round(price, 8),
                "commission": round(fee, 8),
                "commission_usdt": round(fee, 4),
                "commission_asset": t.fee_asset or "USDT",
                "first_fill_time": ts_iso,
                "last_fill_time": ts_iso,
                "time": ts_iso,
                "fills_count": 1,
                "bot_id": bid,
                "is_bot": bid is not None,
                "source": "bot" if bid else "spot",
                "source_label": source,
                "platform": "TraderTrailing",
                "is_paper": True,
            }
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "trades": rows,
        "data_status": "ready",
        "is_test": True,
        "request_id": f"req_{datetime.utcnow().timestamp()}",
    }


@router.get("/finance/bots")
async def get_finance_bots(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Get bot list with PnL quick stats. Auth required.
    """
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    bots = db.query(Bot).filter(Bot.account_id == account_id).all()

    # Get 30d PnL for all bots
    now = datetime.utcnow()
    last_30d = now - timedelta(days=30)
    calculator = FinancePnlCalculator(db)
    pnl_30d = calculator.calculate_realized_pnl(account_id, last_30d, now)

    bot_list = []
    for bot in bots:
        bot_pnl = pnl_30d["by_bot"].get(bot.id, {"pnl": 0.0, "fees": 0.0, "count": 0})
        current_usd, initial_balance = _bot_current_equity_usd(db, bot, account_id)
        bot_list.append(
            _finance_bot_summary_row(bot, bot_pnl, current_usd, initial_balance)
        )

    return {"account_id": account_id, "bots": bot_list}


@router.get("/finance/bots/{bot_id}")
async def get_finance_bot_detail(
    bot_id: int,
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Get bot detail: strategy params, trades, equity curve, metrics. Auth required.
    """
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Get bot trades
    trades = (
        db.query(TradeNormalized)
        .filter(
            TradeNormalized.bot_id == bot_id, TradeNormalized.account_id == account_id
        )
        .order_by(TradeNormalized.time.asc())
        .all()
    )

    # Calculate PnL
    calculator = FinancePnlCalculator(db)
    now = datetime.utcnow()
    last_30d = now - timedelta(days=30)
    pnl_30d = calculator.calculate_realized_pnl(account_id, last_30d, now)
    bot_pnl = pnl_30d["by_bot"].get(bot_id, {"pnl": 0.0, "fees": 0.0, "count": 0})
    current_usd, initial_usd = _bot_current_equity_usd(db, bot, account_id)
    summary_row = _finance_bot_summary_row(bot, bot_pnl, current_usd, initial_usd)

    # Get config
    config = {}
    if bot.config_json:
        try:
            config = json.loads(bot.config_json)
        except:
            pass

    return {
        "bot_id": bot.id,
        "symbol": bot.symbol,
        "status": bot.status,
        "mode": bot.mode,
        "config": config,
        "pnl_30d": summary_row["pnl_30d"],
        "realized_30d_pnl_usd": summary_row["realized_30d_pnl_usd"],
        "mark_to_market_pnl_usd": summary_row["mark_to_market_pnl_usd"],
        "total_pnl": summary_row["total_pnl"],
        "total_pnl_usd": summary_row["total_pnl_usd"],
        "total_pnl_pct": summary_row["total_pnl_pct"],
        "current_usd": summary_row["current_usd"],
        "initial_usd": summary_row["initial_usd"],
        "budget_usd": summary_row["budget_usd"],
        "fees": summary_row["fees"],
        "trades_count": summary_row["trades_count"],
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "price": t.price,
                "qty": t.qty,
                "time": t.time.isoformat(),
            }
            for t in trades[-50:]  # Last 50 trades
        ],
    }


@router.post("/finance/sync")
async def trigger_finance_sync(
    account_id: int = Query(..., description="Account ID"),
    sync_type: str = Query("all", description="Sync type: trades, snapshot, all"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """
    Manually trigger sync. Auth required; only own account or admin.
    """
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    results = {}

    if sync_type in ["trades", "all"]:
        trade_sync = TradeSyncService(db)
        trade_result = await trade_sync.sync_account_trades(account_id)
        results["trades"] = trade_result

    if sync_type in ["snapshot", "all"]:
        snapshot_service = SnapshotService(db)
        snapshot = await snapshot_service.create_snapshot(
            account_id, source="manual_sync"
        )
        results["snapshot"] = {
            "success": snapshot is not None,
            "total_usd": snapshot.total_usd_value if snapshot else 0.0,
        }

    return {"account_id": account_id, "sync_type": sync_type, "results": results}
