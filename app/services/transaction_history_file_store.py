"""
İşlem geçmişi şifreli dosya deposu — hesap başına, RAM'de tutulmaz.

Dosya: `.run/tx_history/{account_id}.enc` (AES-256-GCM v2 / legacy Fernet)
Kompakt JSON + tarih indeksi; istekte decrypt → filtre → sayfala → bırak.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.encryption import decrypt_bytes, encrypt_bytes, tx_history_file_context
from app.utils.tz_utils import TR_TZ, turkey_today_start_utc

logger = logging.getLogger(__name__)

_STORE_VERSION = 1
_MAX_ORDERS = 8000
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TX_ROOT = _PROJECT_ROOT / ".run" / "tx_history"

# Kompakt kayıt indeksleri
C_TIME, C_DATE, C_TYPE, C_SYM, C_QTY, C_PRICE, C_QUOTE, C_COMM, C_CASSET = range(9)
C_SRC, C_BID, C_BNAME, C_FILLS, C_OID, C_TID = 9, 10, 11, 12, 13, 14

_lock_guard = threading.Lock()
_account_locks: Dict[int, threading.Lock] = {}


def _account_lock(account_id: int) -> threading.Lock:
    with _lock_guard:
        if account_id not in _account_locks:
            _account_locks[account_id] = threading.Lock()
        return _account_locks[account_id]


def _ensure_dir() -> None:
    _TX_ROOT.mkdir(parents=True, exist_ok=True)


def _file_path(account_id: int) -> Path:
    return _TX_ROOT / f"{account_id}.enc"


def _rev_path(account_id: int) -> Path:
    return _TX_ROOT / f"{account_id}.rev"


def _read_rev_meta(account_id: int) -> Dict[str, Any]:
    path = _rev_path(account_id)
    if not path.is_file():
        return {"rev": 0, "latest": "", "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"rev": 0, "latest": "", "count": 0}


def _write_rev_meta(account_id: int, meta: Dict[str, Any]) -> None:
    _ensure_dir()
    path = _rev_path(account_id)
    fd, tmp = tempfile.mkstemp(dir=str(_TX_ROOT), suffix=".revtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _bump_revision_meta(account_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    prev = _read_rev_meta(account_id)
    rev_n = int(prev.get("rev") or 0) + 1
    latest = ""
    idx = data.get("idx") or []
    orders = data.get("orders") or {}
    if idx and idx[0] in orders:
        latest = orders[idx[0]][C_TIME]
    meta = {"rev": rev_n, "latest": latest, "count": len(orders)}
    if prev.get("bootstrapped"):
        meta["bootstrapped"] = True
        if prev.get("bootstrapped_at"):
            meta["bootstrapped_at"] = prev["bootstrapped_at"]
    _write_rev_meta(account_id, meta)
    return meta


def is_tx_history_bootstrapped(account_id: int) -> bool:
    return bool(_read_rev_meta(account_id).get("bootstrapped"))


def mark_tx_history_bootstrapped(account_id: int) -> None:
    meta = _read_rev_meta(account_id)
    meta["bootstrapped"] = True
    meta["bootstrapped_at"] = datetime.utcnow().isoformat() + "Z"
    _write_rev_meta(account_id, meta)


def clear_tx_history_bootstrap(account_id: int) -> None:
    """API anahtarı değişince Binance geçmişi yeniden çekilsin."""
    meta = _read_rev_meta(account_id)
    meta.pop("bootstrapped", None)
    meta.pop("bootstrapped_at", None)
    _write_rev_meta(account_id, meta)


_bootstrap_in_flight: set = set()
_bootstrap_guard = threading.Lock()


async def bootstrap_tx_history_from_binance(
    db: Any,
    account_id: int,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """
    İlk açılış / yeni hesap: Binance myTrades → TradeNormalized → şifreli dosya.
    Tamamlanınca rev meta bootstrapped=true.
    """
    with _bootstrap_guard:
        if account_id in _bootstrap_in_flight:
            return {"skipped": "in_flight"}
        if not force and is_tx_history_bootstrapped(account_id) and ledger_has_buysell(account_id):
            return {"skipped": "already_bootstrapped"}
        _bootstrap_in_flight.add(account_id)
    try:
        from app.db.models import Account
        from app.services.test_account import account_has_binance_keys, is_test_account

        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"skipped": "no_account"}
        if is_test_account(account_id, db) or not account_has_binance_keys(account):
            return {"skipped": "no_keys"}

        from app.services.finance_trade_sync import TradeSyncService

        svc = TradeSyncService(db)
        sync_result = await svc.sync_account_trades(account_id)
        rebuilt = rebuild_from_db(db, account_id, days=365)
        mark_tx_history_bootstrapped(account_id)
        logger.info(
            "tx_history bootstrap account_id=%s sync_new=%s rebuilt=%s",
            account_id,
            (sync_result or {}).get("new_count"),
            rebuilt,
        )
        return {"sync": sync_result, "rebuilt": rebuilt}
    except Exception as e:
        logger.warning("tx_history bootstrap account_id=%s: %s", account_id, e)
        return {"error": str(e)}
    finally:
        with _bootstrap_guard:
            _bootstrap_in_flight.discard(account_id)


def get_public_revision(account_id: int) -> Dict[str, Any]:
    """Hafif okuma — şifreli dosya açılmaz."""
    meta = _read_rev_meta(account_id)
    return {
        "revision": str(meta.get("rev") or 0),
        "latest_time": meta.get("latest") or "",
        "count": int(meta.get("count") or 0),
    }


def ensure_tx_history_fresh_from_db(db: Any, account_id: int) -> None:
    """DB'de dosyadan yeni bot işlemi varsa son kayıtları dosyaya yansıt (Binance sync yok)."""
    from sqlalchemy import text
    from app.db.models import Bot, Trade

    meta = _read_rev_meta(account_id)
    latest_file = meta.get("latest") or ""

    row = db.execute(
        text("SELECT MAX(ts) FROM trades WHERE account_id = :aid"),
        {"aid": account_id},
    ).fetchone()
    if not row or not row[0]:
        return
    max_ts = row[0]
    max_iso = _utc_iso(max_ts if isinstance(max_ts, datetime) else datetime.utcnow())
    if latest_file and max_iso <= latest_file:
        return

    q = db.query(Trade).filter(Trade.account_id == account_id)
    if latest_file:
        try:
            since = datetime.fromisoformat(latest_file.replace("Z", "+00:00")).replace(tzinfo=None)
            q = q.filter(Trade.ts > since)
        except Exception:
            pass
    trades = q.order_by(Trade.ts.asc()).limit(40).all()
    if not trades:
        return

    bot_names: Dict[int, str] = {}
    bot_ids = {t.bot_id for t in trades if t.bot_id}
    if bot_ids:
        for b in db.query(Bot).filter(Bot.id.in_(bot_ids)).all():
            try:
                cfg = json.loads(b.config_json or "{}")
                bot_names[b.id] = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
            except Exception:
                bot_names[b.id] = f"Bot #{b.id}"

    with _account_lock(account_id):
        ledger = _load_ledger_unlocked(account_id)
        existing_orders = ledger.get("orders") or {}

    for t in trades:
        sym = (t.symbol or "").upper()
        if not sym and t.bot_id:
            b = db.query(Bot).filter(Bot.id == t.bot_id).first()
            sym = (b.symbol or "").upper() if b else ""
        oid = str(t.order_id) if t.order_id else None
        if oid and f"o_{oid}" in existing_orders:
            continue
        quote = float(t.qty or 0) * float(t.price or 0)
        upsert_trade_fill(
            account_id,
            trade_id=str(t.id),
            order_id=oid,
            time=t.ts,
            side=t.side or "",
            symbol=sym,
            qty=float(t.qty or 0),
            price=float(t.price or 0),
            quote_qty=quote,
            commission=float(t.fee or 0),
            commission_asset=t.fee_asset or "USDT",
            is_maker=False,
            bot_id=t.bot_id,
            bot_name=bot_names.get(t.bot_id) if t.bot_id else None,
        )


def record_bot_trade_fill(
    db: Any,
    account_id: int,
    bot_id: int,
    trade: Any,
    symbol: str,
    *,
    quote_qty: Optional[float] = None,
) -> None:
    """Bot fill anında işlem geçmişi dosyasına yaz."""
    from app.db.models import Bot

    sym = (symbol or getattr(trade, "symbol", None) or "").upper()
    bot_name = None
    try:
        b = db.query(Bot).filter(Bot.id == bot_id).first()
        if b:
            cfg = json.loads(b.config_json or "{}")
            bot_name = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
            if not sym:
                sym = (b.symbol or "").upper()
    except Exception:
        bot_name = f"Bot #{bot_id}"
    qty = float(trade.qty or 0)
    price = float(trade.price or 0)
    quote = float(quote_qty) if quote_qty is not None and quote_qty > 0 else (qty * price if qty and price else 0.0)
    if quote > 0 and qty > 0:
        price = quote / qty
    upsert_trade_fill(
        account_id,
        trade_id=str(trade.order_id or trade.id),
        order_id=str(trade.order_id) if trade.order_id else None,
        time=trade.ts,
        side=trade.side or "",
        symbol=sym,
        qty=qty,
        price=price,
        quote_qty=quote,
        commission=float(trade.fee or 0),
        commission_asset=getattr(trade, "fee_asset", None) or "USDT",
        is_maker=False,
        bot_id=bot_id,
        bot_name=bot_name,
    )


def _empty_ledger(account_id: int) -> Dict[str, Any]:
    return {"v": _STORE_VERSION, "aid": account_id, "orders": {}, "idx": [], "dates": {}}


def _load_ledger_unlocked(account_id: int) -> Dict[str, Any]:
    path = _file_path(account_id)
    if not path.is_file():
        return _empty_ledger(account_id)
    try:
        raw = path.read_bytes()
        if not raw:
            return _empty_ledger(account_id)
        plain = decrypt_bytes(raw, context=tx_history_file_context(account_id))
        data = json.loads(plain.decode("utf-8"))
        if not isinstance(data, dict):
            return _empty_ledger(account_id)
        data.setdefault("orders", {})
        data.setdefault("idx", [])
        data.setdefault("dates", {})
        return data
    except Exception as e:
        logger.warning("tx_history load account_id=%s: %s", account_id, e)
        return _empty_ledger(account_id)


def _save_ledger_unlocked(account_id: int, data: Dict[str, Any]) -> None:
    _ensure_dir()
    path = _file_path(account_id)
    data["v"] = _STORE_VERSION
    data["aid"] = account_id
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    enc = encrypt_bytes(payload, context=tx_history_file_context(account_id))
    fd, tmp = tempfile.mkstemp(dir=str(_TX_ROOT), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(enc)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _bump_revision_meta(account_id, data)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ts_to_date_tr(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TR_TZ).strftime("%Y-%m-%d")


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _order_key(order_id: Optional[str], trade_id: str) -> str:
    if order_id:
        return f"o_{order_id}"
    return f"t_{trade_id}"


def _type_char(side: str, *, dw: Optional[str] = None) -> str:
    if dw == "deposit":
        return "d"
    if dw == "withdraw":
        return "w"
    s = (side or "").upper()
    return "b" if s == "BUY" else "s"


def _trade_fill_amounts(qty: float, price: float, quote_qty: float) -> Tuple[float, float, float]:
    """Binance quote_qty öncelikli; fiyat = notional / miktar."""
    q = float(qty or 0)
    quote = float(quote_qty or 0)
    pr = float(price or 0)
    if quote > 0 and q > 0:
        return q, round(quote / q, 12), quote
    if q > 0 and pr > 0:
        return q, pr, round(q * pr, 8)
    return q, pr, quote


def _normalize_buysell_amounts(rec: List[Any]) -> Tuple[float, float, float]:
    """USDT notional (quote) tek kaynak; fiyat = quote/qty."""
    qty = float(rec[C_QTY] or 0)
    quote = float(rec[C_QUOTE] or 0)
    price = float(rec[C_PRICE] or 0)
    tc = rec[C_TYPE]
    if tc not in ("b", "s") or qty <= 0:
        return qty, price, quote
    if quote > 0:
        return qty, round(quote / qty, 12), quote
    if price > 0:
        return qty, price, round(qty * price, 8)
    return qty, price, quote


def _expand_record(key: str, rec: List[Any]) -> Dict[str, Any]:
    tc = rec[C_TYPE]
    if tc == "d":
        tx_type, label = "deposit", "Yatırım"
    elif tc == "w":
        tx_type, label = "withdraw", "Çekim"
    elif tc == "b":
        tx_type, label = "buy", "Alım"
    else:
        tx_type, label = "sell", "Satım"
    src = rec[C_SRC]
    bot_id = rec[C_BID]
    is_bot = src == "b" or bot_id is not None
    qty, price, quote = _normalize_buysell_amounts(rec) if tc in ("b", "s") else (
        float(rec[C_QTY] or 0),
        float(rec[C_PRICE] or 0),
        float(rec[C_QUOTE] or 0),
    )
    return {
        "id": key if key.startswith(("o_", "t_", "dw_")) else f"ord_{rec[C_OID] or rec[C_TID]}",
        "trade_id": rec[C_TID],
        "order_id": rec[C_OID],
        "time": rec[C_TIME],
        "type": tx_type,
        "type_label": label,
        "symbol": rec[C_SYM] or "",
        "side": "BUY" if tc == "b" else "SELL" if tc == "s" else ("DEPOSIT" if tc == "d" else "WITHDRAW"),
        "qty": qty,
        "price": price,
        "quote_qty": quote,
        "commission": float(rec[C_COMM] or 0),
        "commission_asset": rec[C_CASSET] or "USDT",
        "is_maker": False,
        "source": "bot" if is_bot else "spot",
        "source_label": "Bot" if is_bot else "Spot",
        "platform": "TraderTrailing" if is_bot else "Binance",
        "bot_id": bot_id,
        "bot_name": rec[C_BNAME] or None,
        "fills_count": int(rec[C_FILLS] or 1),
    }


def _index_insert(data: Dict[str, Any], key: str, date_tr: str, time_iso: str) -> None:
    idx: List[str] = data["idx"]
    if key in idx:
        idx.remove(key)
    idx.insert(0, key)
    dates: Dict[str, List[str]] = data["dates"]
    day_keys = dates.setdefault(date_tr, [])
    if key in day_keys:
        day_keys.remove(key)
    day_keys.insert(0, key)
    while len(idx) > _MAX_ORDERS:
        old = idx.pop()
        orders = data["orders"]
        orders.pop(old, None)
        for dkeys in dates.values():
            if old in dkeys:
                dkeys.remove(old)


def upsert_trade_fill(
    account_id: int,
    *,
    trade_id: str,
    order_id: Optional[str],
    time: datetime,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    quote_qty: float,
    commission: float,
    commission_asset: str,
    is_maker: bool,
    bot_id: Optional[int],
    bot_name: Optional[str] = None,
) -> None:
    """Tek fill ekle veya aynı emirde birleştir."""
    key = _order_key(order_id, trade_id)
    time_iso = _utc_iso(time)
    date_tr = _ts_to_date_tr(time)
    src = "b" if bot_id else "s"
    tc = _type_char(side)

    with _account_lock(account_id):
        data = _load_ledger_unlocked(account_id)
        orders: Dict[str, List[Any]] = data["orders"]
        existing = orders.get(key)
        if existing and tc in ("b", "s"):
            if (
                abs(float(qty or 0) - float(existing[C_QTY] or 0)) < 1e-12
                and abs(float(quote_qty or 0) - float(existing[C_QUOTE] or 0)) < 0.02
            ):
                return
            if existing[C_SRC] == "b" and not bot_id:
                existing = None
        if existing and tc in ("b", "s"):
            total_qty = float(existing[C_QTY] or 0) + float(qty or 0)
            total_quote = float(existing[C_QUOTE] or 0) + float(quote_qty or 0)
            total_comm = float(existing[C_COMM] or 0) + float(commission or 0)
            avg_price = (total_quote / total_qty) if total_qty else float(price or 0)
            fills = int(existing[C_FILLS] or 1) + 1
            if time_iso > existing[C_TIME]:
                existing[C_TIME] = time_iso
                existing[C_DATE] = date_tr
            existing[C_QTY] = round(total_qty, 12)
            existing[C_PRICE] = round(avg_price, 12)
            existing[C_QUOTE] = round(total_quote, 8)
            existing[C_COMM] = round(total_comm, 8)
            existing[C_FILLS] = fills
            if bot_id and not existing[C_BID]:
                existing[C_BID] = bot_id
                existing[C_SRC] = "b"
            if bot_name and not existing[C_BNAME]:
                existing[C_BNAME] = bot_name
        else:
            orders[key] = [
                time_iso,
                date_tr,
                tc,
                (symbol or "").upper(),
                round(float(qty), 12),
                round(float(price), 12),
                round(float(quote_qty), 8),
                round(float(commission), 8),
                commission_asset or "USDT",
                src,
                bot_id,
                (bot_name or "")[:32],
                1,
                order_id,
                trade_id,
            ]
        _index_insert(data, key, date_tr, time_iso)
        _save_ledger_unlocked(account_id, data)


def upsert_deposit_withdraw(
    account_id: int,
    *,
    order_id: str,
    time: datetime,
    side: str,
    symbol: str,
    qty: float,
) -> None:
    """Yatırım/çekim kaydı (Binance fetch sonrası dosyaya)."""
    dw = "deposit" if (side or "").upper() == "DEPOSIT" else "withdraw"
    key = f"dw_{order_id or symbol}_{int(time.timestamp())}"
    time_iso = _utc_iso(time)
    date_tr = _ts_to_date_tr(time)
    tc = _type_char("", dw=dw)

    with _account_lock(account_id):
        data = _load_ledger_unlocked(account_id)
        if key in data["orders"]:
            return
        data["orders"][key] = [
            time_iso,
            date_tr,
            tc,
            (symbol or "").upper(),
            round(float(qty), 12),
            0.0,
            round(float(qty), 8),
            0.0,
            symbol or "USDT",
            "s",
            None,
            "",
            1,
            order_id,
            order_id,
        ]
        _index_insert(data, key, date_tr, time_iso)
        _save_ledger_unlocked(account_id, data)


def ledger_has_data(account_id: int) -> bool:
    data = _load_ledger_unlocked(account_id)
    return bool(data.get("orders"))


def ledger_has_buysell(account_id: int) -> bool:
    data = _load_ledger_unlocked(account_id)
    for rec in (data.get("orders") or {}).values():
        if rec[C_TYPE] in ("b", "s"):
            return True
    return False


def ledger_has_deposit_withdraw(account_id: int) -> bool:
    data = _load_ledger_unlocked(account_id)
    for rec in (data.get("orders") or {}).values():
        if rec[C_TYPE] in ("d", "w"):
            return True
    return False


def get_order_detail(account_id: int, trade_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    sym = (symbol or "").upper()
    tid = str(trade_id)
    with _account_lock(account_id):
        data = _load_ledger_unlocked(account_id)
        orders = data.get("orders") or {}
        for key, rec in orders.items():
            if str(rec[C_TID]) == tid and (rec[C_SYM] or "").upper() == sym:
                out = _expand_record(key, rec)
                out["details"] = {
                    "is_maker": False,
                    "order_id": rec[C_OID],
                    "commission_asset": rec[C_CASSET] or "USDT",
                }
                return out
    return None


def _repair_dates_index(data: Dict[str, Any]) -> bool:
    """dates indeksi eksik/bozuksa idx+orders üzerinden yeniden oluştur."""
    orders: Dict[str, List[Any]] = data.get("orders") or {}
    if not orders:
        return False
    dates: Dict[str, List[str]] = data.setdefault("dates", {})
    rebuilt: Dict[str, List[str]] = {}
    for key in data.get("idx") or []:
        rec = orders.get(key)
        if not rec:
            continue
        d = rec[C_DATE] if len(rec) > C_DATE else None
        if not d:
            continue
        rebuilt.setdefault(str(d), []).append(key)
    if rebuilt == dates and sum(len(v) for v in dates.values()) >= min(len(orders), 1):
        return False
    data["dates"] = rebuilt
    return True


def _collect_keys_for_period(data: Dict[str, Any], start_date: str, end_date: str) -> List[str]:
    """Tarih aralığındaki order key'leri — dates indeksi + idx fallback."""
    orders: Dict[str, List[Any]] = data.get("orders") or {}
    dates: Dict[str, List[str]] = data.get("dates") or {}
    keys_in_range: List[str] = []
    try:
        cur = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        while cur <= end_d:
            keys_in_range.extend(dates.get(cur.strftime("%Y-%m-%d"), []))
            cur += timedelta(days=1)
    except ValueError:
        keys_in_range = list(data.get("idx") or [])

    seen: set = set()
    unique_keys: List[str] = []
    for k in keys_in_range:
        if k not in seen and k in orders:
            seen.add(k)
            unique_keys.append(k)

    for k in data.get("idx") or []:
        rec = orders.get(k)
        if not rec:
            continue
        d = str(rec[C_DATE] if len(rec) > C_DATE else "")
        if d and start_date <= d <= end_date and k not in seen:
            seen.add(k)
            unique_keys.append(k)
    return unique_keys


def sync_from_db_if_stale(db: Any, account_id: int, *, max_rows: int = 500) -> int:
    """TradeNormalized'da dosyadan yeni kayıt varsa ekle (hafif kontrol)."""
    from sqlalchemy import func
    from app.db.models import TradeNormalized

    meta = get_public_revision(account_id)
    latest_file = meta.get("latest_time") or ""
    max_db = (
        db.query(func.max(TradeNormalized.time))
        .filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"]),
        )
        .scalar()
    )
    if not max_db:
        return 0
    max_iso = _utc_iso(max_db if isinstance(max_db, datetime) else datetime.utcnow())
    if latest_file and max_iso <= latest_file:
        return 0
    if not ledger_has_buysell(account_id):
        return rebuild_from_db(db, account_id)
    rows = (
        db.query(TradeNormalized)
        .filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.side.in_(["BUY", "SELL"]),
        )
        .order_by(TradeNormalized.time.desc())
        .limit(max_rows)
        .all()
    )
    if latest_file:
        try:
            since = datetime.fromisoformat(latest_file.replace("Z", "+00:00")).replace(tzinfo=None)
            rows = [r for r in rows if r.time and r.time > since]
        except Exception:
            pass
    if not rows:
        return rebuild_from_db(db, account_id, days=90)
    from app.db.models import Bot

    bot_names: Dict[int, str] = {}
    bot_ids = {r.bot_id for r in rows if r.bot_id}
    if bot_ids:
        for b in db.query(Bot).filter(Bot.id.in_(bot_ids)).all():
            try:
                cfg = json.loads(b.config_json or "{}")
                bot_names[b.id] = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
            except Exception:
                bot_names[b.id] = f"Bot #{b.id}"
    count = 0
    for t in reversed(rows):
        q, pr, quote = _trade_fill_amounts(t.qty, t.price, t.quote_qty)
        upsert_trade_fill(
            account_id,
            trade_id=str(t.trade_id),
            order_id=t.order_id,
            time=t.time,
            side=t.side or "",
            symbol=t.symbol or "",
            qty=q,
            price=pr,
            quote_qty=quote,
            commission=float(t.commission or 0),
            commission_asset=t.commission_asset or "USDT",
            is_maker=bool(t.is_maker),
            bot_id=t.bot_id,
            bot_name=bot_names.get(t.bot_id) if t.bot_id else None,
        )
        count += 1
    return count


def _period_date_bounds(period: str) -> Tuple[Optional[str], str]:
    today_tr = datetime.now(TR_TZ).date()
    end = today_tr.strftime("%Y-%m-%d")
    days_map = {"daily": 1, "weekly": 7, "monthly": 30, "all": None}
    days = days_map.get(period, 7)
    if days is None:
        start = (today_tr - timedelta(days=365)).strftime("%Y-%m-%d")
    else:
        start = (today_tr - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return start, end


def query_transactions(
    account_id: int,
    period: str = "weekly",
    type_filter: str = "all",
    source_filter: str = "all",
    page: int = 1,
    per_page: int = 20,
) -> Dict[str, Any]:
    """Dosyadan filtreli sayfalı liste; decrypt sonrası geçici işlem, kalıcı RAM yok."""
    start_date, end_date = _period_date_bounds(period)
    tf = (type_filter or "all").strip().lower()
    sf = (source_filter or "all").strip().lower()

    with _account_lock(account_id):
        data = _load_ledger_unlocked(account_id)
        if _repair_dates_index(data):
            _save_ledger_unlocked(account_id, data)
        orders: Dict[str, List[Any]] = data.get("orders") or {}

    unique_keys = _collect_keys_for_period(data, start_date, end_date)
    ordered_keys = sorted(unique_keys, key=lambda k: orders[k][C_TIME], reverse=True)

    filtered: List[str] = []
    for key in ordered_keys:
        rec = orders[key]
        tc = rec[C_TYPE]
        if tf in ("deposit",) and tc != "d":
            continue
        if tf in ("withdraw",) and tc != "w":
            continue
        if tf == "depositwithdraw" and tc not in ("d", "w"):
            continue
        if tf in ("buy",) and tc != "b":
            continue
        if tf in ("sell",) and tc != "s":
            continue
        if tf in ("buysell",) and tc not in ("b", "s"):
            continue
        if tf in ("all", "") and tc not in ("b", "s", "d", "w"):
            continue
        if sf == "spot" and rec[C_SRC] == "b":
            continue
        if sf == "bot" and rec[C_SRC] != "b":
            continue
        filtered.append(key)

    total = len(filtered)
    offset = max(0, page - 1) * per_page
    page_keys = filtered[offset : offset + per_page]
    items = [_expand_record(k, orders[k]) for k in page_keys]
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0

    today_start = turkey_today_start_utc()
    start_dt = today_start - timedelta(days={"daily": 0, "weekly": 6, "monthly": 29}.get(period, 6))
    if period == "all":
        start_dt = datetime.utcnow() - timedelta(days=365)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "period": period,
        "date_from": start_date,
        "date_to": end_date,
        "source": "file",
        **get_public_revision(account_id),
    }


def rebuild_from_db(db: Any, account_id: int, *, days: int = 365) -> int:
    """TradeNormalized → şifreli dosya (ilk okuma / backfill)."""
    from sqlalchemy import desc
    from app.db.models import Bot, TradeNormalized

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(TradeNormalized)
        .filter(
            TradeNormalized.account_id == account_id,
            TradeNormalized.time >= cutoff,
            TradeNormalized.side.in_(["BUY", "SELL"]),
        )
        .order_by(TradeNormalized.time.asc())
        .limit(15000)
        .all()
    )
    if not rows:
        return 0

    bot_names: Dict[int, str] = {}
    bot_ids = {r.bot_id for r in rows if r.bot_id}
    if bot_ids:
        for b in db.query(Bot).filter(Bot.id.in_(bot_ids)).all():
            try:
                cfg = json.loads(b.config_json or "{}")
                bot_names[b.id] = (b.name or cfg.get("name") or f"Bot #{b.id}")[:32]
            except Exception:
                bot_names[b.id] = f"Bot #{b.id}"

    count = 0
    for t in rows:
        q, pr, quote = _trade_fill_amounts(t.qty, t.price, t.quote_qty)
        upsert_trade_fill(
            account_id,
            trade_id=str(t.trade_id),
            order_id=t.order_id,
            time=t.time,
            side=t.side or "",
            symbol=t.symbol or "",
            qty=q,
            price=pr,
            quote_qty=quote,
            commission=float(t.commission or 0),
            commission_asset=t.commission_asset or "USDT",
            is_maker=bool(t.is_maker),
            bot_id=t.bot_id,
            bot_name=bot_names.get(t.bot_id) if t.bot_id else None,
        )
        count += 1
    return count
