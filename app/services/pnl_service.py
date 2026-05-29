"""
PnL Calculation Service
Günlük K/Z: Her gece 00:00 (Türkiye) bot bakiyesi (Base+Quote USD) sabit referans alınır;
bu referansa göre değişim 23:59'a kadar günlük K/Z olarak gösterilir. Her gün referans sıfırlanır.

Bot Performans Havuzu: account_daily_realized_pnl tablosu günlük gerçekleşen PnL'ı saklar.
Bot silinse/kapatılsa bile PnL hafızada kalır. Günlük/Haftalık/Aylık/Genel özetleri bu havuzdan hesaplanır.
"""
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.db.models import Trade, PnlSnapshot, Bot
from app.utils.tz_utils import (
    turkey_today_start_utc,
    turkey_today_date_str,
    turkey_day_start_utc_for_date,
    turkey_day_end_utc_for_date,
    bot_started_on_tr_date,
)

# FIFO fallback: çok uzun geçmişte tam trade listesi RAM patlamasını önler
_MAX_FIFO_TRADES_ROWS = 4000
from sqlalchemy import text
from app.services.price_hub import price_hub


def _get_virtual_wallet_or_none(db: Session, bot_id: int, symbol: str):
    """Lazy import to avoid circular deps."""
    try:
        from app.botengine.virtual_wallet import get_virtual_wallet_or_none
        return get_virtual_wallet_or_none(db, bot_id, symbol)
    except Exception:
        return None


def _fetch_price_from_datahub(symbol_pair: str) -> float:
    """Get price from DataHub cache only. No per-symbol Binance REST."""
    try:
        from app.services.data_hub import data_hub
        p = data_hub.get_price(symbol_pair.upper())
        return float(p) if p is not None and float(p) > 0 else 0.0
    except Exception:
        return 0.0


def _compute_multi_total_usd_from_state(db: Session, bot_id: int, account_id: int, raw: dict) -> float:
    """
    MULTI/TRDCA paper botlar için state.virtual_balances üzerinden total_usd hesapla.
    virtual_wallet MULTI için 0/0 döndüğünde dashboard summary'de doğru bakiye gösterilsin.
    """
    from app.botengine.state_store import load_state
    state = load_state(db, bot_id) or {}
    vb = state.get("virtual_balances")
    if not vb or not isinstance(vb, dict):
        return 0.0
    quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()
    assets = set()
    for k in (raw.get("trb") or {}).get("target_weights_all") or {}:
        if k and str(k).upper() != quote_asset:
            assets.add(str(k).strip().upper())
    for k in (raw.get("dca") or {}).get("coin_weights") or {}:
        if k and str(k).upper() != quote_asset:
            assets.add(str(k).strip().upper())
    for a in raw.get("assets") or []:
        s = (a.get("symbol") or "").upper().replace("USDT", "").replace("FDUSD", "").strip()
        if s and s != quote_asset:
            assets.add(s)
    assets.add(quote_asset)
    base_value_usd = 0.0
    for a in assets:
        if a == quote_asset:
            continue
        free = float(vb.get(a) or 0)
        if free <= 0:
            continue
        sym_pair = f"{a}{quote_asset}"
        p = price_hub.get_price(sym_pair)
        if p is None or p <= 0:
            p = _fetch_price_from_datahub(sym_pair)
        if p and p > 0:
            base_value_usd += free * p
    quote_balance = float(vb.get(quote_asset) or 0)
    total = base_value_usd + quote_balance
    if total > 0:
        return total
    initial_capital = float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or raw.get("bot_budget_quote") or 0)
    if initial_capital > 0:
        try:
            from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
            if is_test_account(account_id, db) and quote_balance == TEST_PAPER_BALANCE_USDT and base_value_usd == 0:
                return initial_capital
        except Exception:
            pass
        if base_value_usd == 0 and quote_balance == 0:
            return initial_capital
    return 0.0


def _fee_quote(t: Trade) -> float:
    """Fee in quote (USDT). Yeni kayıtlarda fee=USDT; fee_asset yalnızca gösterim."""
    try:
        fee = float(t.fee or 0)
    except (TypeError, ValueError):
        return 0.0
    if fee <= 0:
        return 0.0
    asset = (getattr(t, "fee_asset", None) or "USDT").upper()
    if asset == "USDT":
        return fee
    sym = (getattr(t, "symbol", None) or "").upper()
    try:
        px = float(t.price or 0)
        qty = float(t.qty or 0)
    except (TypeError, ValueError):
        px = qty = 0.0
    notional = qty * px if qty > 0 and px > 0 else 0.0
    if notional > 0 and fee <= notional * 0.02:
        return fee
    from app.botengine.fee_utils import commission_to_usdt

    return commission_to_usdt(fee, asset, sym, px)


def _apply_stale_return(
    db: Session, bot_id: int, account_id: int, state: dict, out: Dict, initial_capital: float
) -> None:
    """When stale: fill total_usd/daily from last_fill_snapshot or last PnlSnapshot; do not update state or write snapshot."""
    snap = state.get("last_fill_snapshot") or {}
    if isinstance(snap, dict) and snap.get("snapshot_at") and snap.get("total_usd") is not None:
        out["total_usd"] = float(snap["total_usd"])
        return
    last_row = (
        db.query(PnlSnapshot)
        .filter(PnlSnapshot.bot_id == bot_id, PnlSnapshot.account_id == account_id)
        .order_by(PnlSnapshot.ts.desc())
        .first()
    )
    if last_row:
        out["total_usd"] = float(last_row.total_usd)
        out["daily"] = float(last_row.daily or 0)
        out["daily_pnl_pct"] = round((out["daily"] / float(last_row.total_usd or 1) * 100.0), 2) if last_row.total_usd else 0.0
        out["monthly"] = float(last_row.monthly or 0)


def _equity_at_tr_day_open(
    db: Session,
    bot_id: int,
    account_id: int,
    today_date: str,
) -> Optional[float]:
    """TR gün başı (00:00) civarı equity: önce gece yarısından önceki son PnlSnapshot."""
    try:
        day_start = turkey_day_start_utc_for_date(today_date)
    except ValueError:
        return None
    row = (
        db.query(PnlSnapshot)
        .filter(
            PnlSnapshot.bot_id == bot_id,
            PnlSnapshot.account_id == account_id,
            PnlSnapshot.ts < day_start,
        )
        .order_by(PnlSnapshot.ts.desc())
        .first()
    )
    if row and row.total_usd is not None:
        return float(row.total_usd)
    row_today = (
        db.query(PnlSnapshot)
        .filter(
            PnlSnapshot.bot_id == bot_id,
            PnlSnapshot.account_id == account_id,
            PnlSnapshot.ts >= day_start,
        )
        .order_by(PnlSnapshot.ts.asc())
        .first()
    )
    if row_today and row_today.total_usd is not None:
        return float(row_today.total_usd)
    return None


def ensure_daily_ref_and_compute(
    state: dict,
    total_usd: float,
    initial_capital: float,
    bot_started_at,
    db: Optional[Session] = None,
    bot_id: Optional[int] = None,
    account_id: Optional[int] = None,
    persist: bool = True,
) -> tuple[float, float]:
    """
    Günlük K/Z: TR gece 00:00 (23:59 sonrası) mevcut equity referans; gün içinde equity − referans.
    Bot aynı gün açıldıysa referans = başlangıç sermayesi (bot bakiyesi hareketi günlük K/Z'de görünür).
    Toplam K/Z (initial_capital bazlı) ile karıştırılmaz.
    """
    if not state.get("initial_allocation_done"):
        return 0.0, 0.0
    from app.botengine.state_store import save_state

    today_date = turkey_today_date_str()
    started_today = bot_started_on_tr_date(bot_started_at, today_date)
    daily_ref_date = state.get("daily_ref_date")
    daily_ref_usd = float(state.get("daily_ref_usd") or 0)
    changed = False

    if daily_ref_date != today_date or daily_ref_usd <= 0:
        if started_today and initial_capital > 0:
            state["daily_ref_usd"] = float(initial_capital)
            daily_ref_usd = float(initial_capital)
        else:
            state["daily_ref_usd"] = float(total_usd)
            daily_ref_usd = float(total_usd)
        state["daily_ref_date"] = today_date
        changed = True
    elif (
        started_today
        and initial_capital > 0
        and daily_ref_date == today_date
        and abs(daily_ref_usd - float(total_usd)) < 1e-6
        and abs(float(total_usd) - initial_capital) > 0.005
    ):
        # Aynı gün açılan bot: ref yanlışlıkla ilk tick equity'sine yazılmış — başlangıç sermayesine heal
        state["daily_ref_usd"] = float(initial_capital)
        daily_ref_usd = float(initial_capital)
        changed = True
    elif (
        not started_today
        and initial_capital > 0
        and abs(daily_ref_usd - initial_capital) < 1e-6
        and abs(float(total_usd) - initial_capital) > 1e-6
        and db is not None
        and bot_id is not None
        and account_id is not None
    ):
        # Eski mantık (initial_capital referans) kalmış çok günlük bot — gün açılış equity'sine heal
        open_eq = _equity_at_tr_day_open(db, bot_id, account_id, today_date)
        if open_eq is None or open_eq <= 0:
            open_eq = float(total_usd)
        state["daily_ref_usd"] = open_eq
        daily_ref_usd = open_eq
        changed = True

    if changed and persist and db is not None and bot_id is not None and account_id is not None:
        save_state(db, bot_id, account_id, state)

    daily = float(total_usd) - daily_ref_usd
    pct = (daily / daily_ref_usd * 100.0) if daily_ref_usd > 0 else 0.0
    return daily, pct


class PnlService:
    """PnL calculation service. Spec §8/§50: total_usd priority virtual_wallet > initial_capital_override > fifo_trades."""

    @staticmethod
    def calculate_bot_pnl(
        db: Session,
        bot_id: int,
        account_id: int,
        symbol: Optional[str] = None,
        now_utc_naive: Optional[datetime] = None,
        current_price: Optional[float] = None,
        price_is_stale: bool = False,
    ) -> Dict:
        """
        Calculate current PnL. When price_is_stale or price invalid: return last snapshot without updating daily_ref or writing PnlSnapshot.
        """
        bot = db.query(Bot).filter(Bot.id == bot_id, Bot.account_id == account_id).first()
        if not bot:
            return {"error": "Bot not found"}
        sym = (bot.symbol or "").strip().upper()
        if symbol is None:
            symbol = sym
        if current_price is None:
            current_price = price_hub.get_price(bot.symbol)
        price_valid = current_price is not None and float(current_price) > 0

        # Prefer virtual wallet for total_usd (base*price+quote) when engine has a row
        vw = _get_virtual_wallet_or_none(db, bot_id, bot.symbol or "")
        trades: Optional[List[Any]] = None

        raw = {}
        try:
            raw = json.loads(bot.config_json or "{}") if getattr(bot, "config_json", None) else {}
        except Exception:
            pass
        strategy_id = (raw.get("strategy_id") or "").strip().lower()
        is_multi = sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance")
        initial_capital = float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or raw.get("bot_budget_quote") or 0)
        from app.botengine.state_store import load_state, save_state
        state = load_state(db, bot_id) or {}

        total_usd = 0.0
        base_qty = 0.0
        quote_qty = 0.0
        realized = 0.0
        unrealized = 0.0
        pnl_mode_used = "fifo_trades"

        if vw is not None:
            vb, vq = vw
            if not price_valid and trades:
                current_price = trades[-1].price
                price_valid = current_price and float(current_price) > 0
            total_usd = float(vb) * (float(current_price or 0.0)) + float(vq)
            base_qty = float(vb)
            quote_qty = float(vq)
            pnl_mode_used = "virtual_wallet"
            if is_multi and total_usd <= 0:
                fallback = _compute_multi_total_usd_from_state(db, bot_id, account_id, raw)
                if fallback > 0:
                    total_usd = fallback
        elif not state.get("initial_allocation_done") and not is_multi:
            _base_s = float(state.get("base_balance") or 0)
            _quote_s = float(state.get("quote_balance") or 0)
            _px = float(current_price or 0) if price_valid else 0.0
            if _base_s > 0 or _quote_s > 0:
                total_usd = _base_s * _px + _quote_s
                pnl_mode_used = "state_balances"
            else:
                total_usd = 0.0
                pnl_mode_used = "pending_initial_allocation"
        elif is_multi:
            total_usd = _compute_multi_total_usd_from_state(db, bot_id, account_id, raw)
            if total_usd <= 0 and initial_capital > 0:
                total_usd = initial_capital
            base_qty = 0.0
            quote_qty = total_usd
            pnl_mode_used = "initial_capital_override" if total_usd == initial_capital else "virtual_wallet"
        else:
            if trades is None:
                trades = (
                    db.query(Trade)
                    .filter(Trade.bot_id == bot_id, Trade.account_id == account_id)
                    .order_by(Trade.ts.desc())
                    .limit(_MAX_FIFO_TRADES_ROWS)
                    .all()
                )
                trades = list(reversed(trades))
            if not trades:
                out = {
                    "total_usd": 0.0,
                    "realized": 0.0,
                    "unrealized": 0.0,
                    "daily": 0.0,
                    "daily_pnl_pct": 0.0,
                    "monthly": 0.0,
                    "base_qty": 0.0,
                    "quote_qty": 0.0,
                    "current_price": current_price or 0.0,
                    "stale": False,
                    "pnl_mode_used": "fifo_trades",
                }
                if price_is_stale or (pnl_mode_used == "virtual_wallet" and not price_valid):
                    _apply_stale_return(db, bot_id, account_id, state, out, initial_capital)
                return out
            base_qty = 0.0
            quote_qty = 0.0
            total_cost = 0.0
            for t in trades:
                qty = float(t.qty)
                price = float(t.price)
                fee_q = _fee_quote(t)
                if t.side == "BUY":
                    base_qty += qty
                    total_cost += qty * price + fee_q
                    quote_qty -= qty * price + fee_q
                elif t.side == "SELL":
                    if base_qty > 0:
                        avg_buy = total_cost / base_qty
                        sell_qty = min(qty, base_qty)
                        realized += (price - avg_buy) * sell_qty - fee_q
                        base_qty -= sell_qty
                        total_cost -= avg_buy * sell_qty
                    quote_qty += qty * price - fee_q
            if not price_valid and trades:
                current_price = trades[-1].price
                price_valid = current_price and float(current_price) > 0
            avg_buy_final = total_cost / base_qty if base_qty > 0 else None
            unrealized = (float(current_price or 0) - avg_buy_final) * base_qty if (base_qty > 0 and avg_buy_final is not None and current_price) else 0.0
            total_usd = quote_qty + base_qty * float(current_price or 0.0)
            pnl_mode_used = "fifo_trades"

        now = now_utc_naive or datetime.utcnow()
        today_start = turkey_today_start_utc()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_snap = db.query(PnlSnapshot).filter(
            PnlSnapshot.bot_id == bot_id,
            PnlSnapshot.account_id == account_id,
            PnlSnapshot.ts >= month_start
        ).order_by(PnlSnapshot.ts.asc()).first()

        today_date = turkey_today_date_str()
        # Stale or invalid price: do NOT update daily_ref or write snapshot (Spec B)
        if price_is_stale or (pnl_mode_used == "virtual_wallet" and not price_valid):
            out = {
                "total_usd": total_usd,
                "realized": realized,
                "unrealized": unrealized,
                "daily": 0.0,
                "daily_pnl_pct": 0.0,
                "monthly": 0.0,
                "base_qty": base_qty,
                "quote_qty": quote_qty,
                "current_price": current_price or 0.0,
                "stale": True,
                "pnl_mode_used": pnl_mode_used,
            }
            _apply_stale_return(db, bot_id, account_id, state, out, initial_capital)
            return out
        if state.get("initial_allocation_done"):
            daily, daily_pnl_pct = ensure_daily_ref_and_compute(
                state,
                total_usd,
                initial_capital,
                getattr(bot, "started_at", None),
                db=db,
                bot_id=bot_id,
                account_id=account_id,
                persist=True,
            )
        else:
            daily = 0.0
            daily_pnl_pct = 0.0

        monthly = total_usd - monthly_snap.total_usd if monthly_snap else total_usd - initial_capital

        return {
            "total_usd": total_usd,
            "realized": realized,
            "unrealized": unrealized,
            "daily": daily,
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "monthly": monthly,
            "base_qty": base_qty,
            "quote_qty": quote_qty,
            "current_price": current_price or 0.0,
            "stale": False,
            "pnl_mode_used": pnl_mode_used,
        }

    @staticmethod
    def _daily_realized_for_bot_trades(db: Session, bot_id: int, account_id: int) -> float:
        """Spec §10: One bot's cycles completed today (Turkey day); FIFO with fees. Used before bot delete to cache."""
        today_start = turkey_today_start_utc()
        today_str = today_start.strftime("%Y-%m-%d")
        today_end = turkey_day_end_utc_for_date(today_str)
        trades = (
            db.query(Trade)
            .filter(Trade.bot_id == bot_id, Trade.account_id == account_id)
            .order_by(Trade.ts.asc())
            .all()
        )
        if not trades:
            return 0.0
        from collections import defaultdict
        by_cycle = defaultdict(list)
        for t in trades:
            cid = t.cycle_id if t.cycle_id is not None else 1
            by_cycle[cid].append(t)
        total = 0.0
        for cycle_trades in by_cycle.values():
            if not cycle_trades:
                continue
            last_ts = max(t.ts for t in cycle_trades)
            if last_ts < today_start or last_ts >= today_end:
                continue
            base_qty = 0.0
            total_cost = 0.0
            realized = 0.0
            for t in cycle_trades:
                qty = float(t.qty)
                price = float(t.price)
                fee_q = _fee_quote(t)
                if t.side == "BUY":
                    base_qty += qty
                    total_cost += qty * price + fee_q
                elif t.side == "SELL" and base_qty > 0:
                    avg_buy = total_cost / base_qty
                    sell_qty = min(qty, base_qty)
                    realized += (price - avg_buy) * sell_qty - fee_q
                    base_qty -= sell_qty
                    total_cost -= avg_buy * sell_qty
            total += realized
        return total

    @staticmethod
    def get_account_daily_realized_cache(db: Session, account_id: int, date_tr: str) -> float:
        """Hesap bazlı günlük gerçekleşen PnL cache (silinen botlardan bugün kapanan turlar)."""
        row = db.execute(
            text(
                "SELECT amount_usd FROM account_daily_realized_pnl WHERE account_id = :aid AND date_tr = :dt"
            ),
            {"aid": account_id, "dt": date_tr},
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    @staticmethod
    def add_to_account_daily_realized_cache(db: Session, account_id: int, date_tr: str, amount_usd: float) -> None:
        """Silinen botun bugünkü gerçekleşen PnL'ini cache'e ekler (INSERT veya UPDATE)."""
        now_iso = datetime.utcnow().isoformat()
        db.execute(
            text("""
                INSERT INTO account_daily_realized_pnl (account_id, date_tr, amount_usd, updated_at)
                VALUES (:aid, :dt, :amt, :now)
                ON CONFLICT(account_id, date_tr) DO UPDATE SET
                    amount_usd = amount_usd + excluded.amount_usd,
                    updated_at = excluded.updated_at
            """),
            {"aid": account_id, "dt": date_tr, "amt": amount_usd, "now": now_iso},
        )
        db.commit()

    @staticmethod
    def daily_realized_from_cycles_completed_today(db: Session, account_id: int) -> float:
        """
        Günlük PnL = sadece o gün tamamlanan turların (cycle) kârlarının toplamı.
        Tur "bugün tamamlandı" = o turun son işleminin tarihi bugün (Türkiye 00:00+).
        Silinen botların bugünkü kârı account_daily_realized_pnl cache'inden eklenir.
        """
        today_start = turkey_today_start_utc()
        today_str = today_start.strftime("%Y-%m-%d")
        today_end = turkey_day_end_utc_for_date(today_str)
        bots = db.query(Bot).filter(Bot.account_id == account_id).all()
        total_daily = 0.0
        from collections import defaultdict
        for bot in bots:
            trades = (
                db.query(Trade)
                .filter(Trade.bot_id == bot.id, Trade.account_id == account_id)
                .order_by(Trade.ts.asc())
                .all()
            )
            if not trades:
                continue
            by_cycle = defaultdict(list)
            for t in trades:
                cid = t.cycle_id if t.cycle_id is not None else 1
                by_cycle[cid].append(t)
            for cycle_trades in by_cycle.values():
                if not cycle_trades:
                    continue
                last_ts = max(t.ts for t in cycle_trades)
                if last_ts < today_start or last_ts >= today_end:
                    continue
                base_qty = 0.0
                total_cost = 0.0
                realized = 0.0
                for t in cycle_trades:
                    qty = float(t.qty)
                    price = float(t.price)
                    fee_q = _fee_quote(t)
                    if t.side == "BUY":
                        base_qty += qty
                        total_cost += qty * price + fee_q
                    elif t.side == "SELL" and base_qty > 0:
                        avg_buy = total_cost / base_qty
                        sell_qty = min(qty, base_qty)
                        realized += (price - avg_buy) * sell_qty - fee_q
                        base_qty -= sell_qty
                        total_cost -= avg_buy * sell_qty
                total_daily += realized
        total_daily += PnlService.get_account_daily_realized_cache(db, account_id, today_str)
        return total_daily

    @staticmethod
    def save_snapshot(db: Session, bot_id: int, account_id: int, pnl_data: Dict):
        """Save PnL snapshot"""
        snapshot = PnlSnapshot(
            bot_id=bot_id,
            account_id=account_id,
            ts=datetime.utcnow(),
            total_usd=pnl_data["total_usd"],
            realized=pnl_data["realized"],
            unrealized=pnl_data["unrealized"],
            daily=pnl_data["daily"],
            monthly=pnl_data["monthly"]
        )
        db.add(snapshot)
        db.commit()

    # --- Bot Performans Havuzu (günlük/haftalık/aylık/genel) ---

    @staticmethod
    def _realized_for_date_from_trades(db: Session, account_id: int, date_tr: str) -> float:
        """Spec §10/§59: Cycles completed on date_tr (Turkey day); FIFO realized with fees in quote subtracted."""
        from collections import defaultdict
        try:
            day_start = turkey_day_start_utc_for_date(date_tr)
            day_end = turkey_day_end_utc_for_date(date_tr)
        except ValueError:
            return 0.0
        bots = db.query(Bot).filter(Bot.account_id == account_id).all()
        total = 0.0
        for bot in bots:
            trades = (
                db.query(Trade)
                .filter(Trade.bot_id == bot.id, Trade.account_id == account_id)
                .order_by(Trade.ts.asc())
                .all()
            )
            if not trades:
                continue
            by_cycle = defaultdict(list)
            for t in trades:
                cid = t.cycle_id if t.cycle_id is not None else 1
                by_cycle[cid].append(t)
            for cycle_trades in by_cycle.values():
                if not cycle_trades:
                    continue
                last_ts = max(t.ts for t in cycle_trades)
                if last_ts < day_start or last_ts >= day_end:
                    continue
                base_qty = 0.0
                total_cost = 0.0
                realized = 0.0
                for t in cycle_trades:
                    qty = float(t.qty)
                    price = float(t.price)
                    fee_q = _fee_quote(t)
                    if t.side == "BUY":
                        base_qty += qty
                        total_cost += qty * price + fee_q
                    elif t.side == "SELL" and base_qty > 0:
                        avg_buy = total_cost / base_qty
                        sell_qty = min(qty, base_qty)
                        realized += (price - avg_buy) * sell_qty - fee_q
                        base_qty -= sell_qty
                        total_cost -= avg_buy * sell_qty
                total += realized
        return total

    @staticmethod
    def consolidate_date(db: Session, account_id: int, date_tr: str) -> float:
        """
        Belirli tarihin PnL'ını havuzda günceller. Cache (silinen botlar) + Trade'dan hesaplanan değeri birleştirir.
        Bot silinse bile PnL hafızada kalır.
        """
        from_cache = PnlService.get_account_daily_realized_cache(db, account_id, date_tr)
        from_trades = PnlService._realized_for_date_from_trades(db, account_id, date_tr)
        total = from_cache + from_trades
        now_iso = datetime.utcnow().isoformat()
        db.execute(
            text("""
                INSERT INTO account_daily_realized_pnl (account_id, date_tr, amount_usd, updated_at)
                VALUES (:aid, :dt, :amt, :now)
                ON CONFLICT(account_id, date_tr) DO UPDATE SET
                    amount_usd = excluded.amount_usd,
                    updated_at = excluded.updated_at
            """),
            {"aid": account_id, "dt": date_tr, "amt": total, "now": now_iso},
        )
        db.commit()
        return total

    @staticmethod
    def get_aggregated_pnl(
        db: Session, account_id: int, period: str
    ) -> Dict[str, any]:
        """
        Seçilen dönem için toplam bot PnL.
        period: daily | weekly | monthly | all
        Silinen/kapatılan botlar dahil (havuzdan).
        """
        today = turkey_today_start_utc()
        today_str = today.strftime("%Y-%m-%d")
        labels = {
            "daily": ("Günlük", 1),
            "weekly": ("Haftalık", 7),
            "monthly": ("Aylık", 30),
            "all": ("Genel", None),
        }
        label, days = labels.get(period, ("Günlük", 1))

        if period == "daily":
            pnl = PnlService.daily_realized_from_cycles_completed_today(db, account_id)
            return {
                "pnl_usd": round(pnl, 2),
                "period": period,
                "period_label": label,
                "date_from": today_str,
                "date_to": today_str,
            }

        if days is None:
            date_from = None
            date_to = today_str
        else:
            date_from_dt = today - timedelta(days=days)
            date_from = date_from_dt.strftime("%Y-%m-%d")
            date_to = today_str

        total = 0.0
        if date_from:
            current = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
            while current <= end:
                d_str = current.strftime("%Y-%m-%d")
                if d_str == today_str:
                    total += PnlService.daily_realized_from_cycles_completed_today(db, account_id)
                else:
                    PnlService.consolidate_date(db, account_id, d_str)
                    total += PnlService.get_account_daily_realized_cache(db, account_id, d_str)
                current += timedelta(days=1)
        else:
            date_from_dt = today - timedelta(days=365)
            date_from = date_from_dt.strftime("%Y-%m-%d")
            current = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(today_str, "%Y-%m-%d").date()
            while current <= end:
                d_str = current.strftime("%Y-%m-%d")
                if d_str == today_str:
                    total += PnlService.daily_realized_from_cycles_completed_today(db, account_id)
                else:
                    PnlService.consolidate_date(db, account_id, d_str)
                    total += PnlService.get_account_daily_realized_cache(db, account_id, d_str)
                current += timedelta(days=1)

        return {
            "pnl_usd": round(total, 2),
            "period": period,
            "period_label": label,
            "date_from": date_from if date_from else "—",
            "date_to": date_to,
        }
