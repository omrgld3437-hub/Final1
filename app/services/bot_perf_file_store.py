"""
Bot performans dosya deposu — hızlı okuma için kompakt JSON.

- Kapanan tur: `.run/bot_perf/bots/{bot_id}.json` — bot başına kapanan turlar.
- Hesap ham tur: `.run/bot_perf/accounts/{account_id}.json` — tüm botlar, tarih/saat + USDT K/Z (dashboard filtresi).
- Saatlik (bugün): `.run/bot_perf/hourly/{account_id}_{date_tr}.json` — yedek.
- Kalıcı günlük: `.run/bot_perf/daily/{account_id}.json` — yedek.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.utils.tz_utils import TR_TZ

logger = logging.getLogger(__name__)

_STORE_VERSION = 1
_ACCOUNT_ROUNDS_VERSION = 1
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PERF_ROOT = _PROJECT_ROOT / ".run" / "bot_perf"
_MAX_ACCOUNT_ROUNDS = 50000


def _ensure_dirs() -> None:
    (_PERF_ROOT / "hourly").mkdir(parents=True, exist_ok=True)
    (_PERF_ROOT / "daily").mkdir(parents=True, exist_ok=True)
    (_PERF_ROOT / "bots").mkdir(parents=True, exist_ok=True)
    (_PERF_ROOT / "accounts").mkdir(parents=True, exist_ok=True)


def _bot_cycles_path(bot_id: int) -> Path:
    return _PERF_ROOT / "bots" / f"{bot_id}.json"


def _account_rounds_path(account_id: int) -> Path:
    return _PERF_ROOT / "accounts" / f"{account_id}.json"


_MAX_BOT_CYCLES = 2000


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _hourly_path(account_id: int, date_tr: str) -> Path:
    return _PERF_ROOT / "hourly" / f"{account_id}_{date_tr}.json"


def _daily_path(account_id: int) -> Path:
    return _PERF_ROOT / "daily" / f"{account_id}.json"


def _empty_hours() -> List[List[float]]:
    return [[0.0, 0.0] for _ in range(24)]


def _today_tr() -> str:
    return datetime.now(TR_TZ).strftime("%Y-%m-%d")


def _hour_tr(ts: Optional[Any] = None) -> int:
    if ts is None:
        return datetime.now(TR_TZ).hour
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return datetime.now(TR_TZ).hour
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TR_TZ).hour


def ts_to_date_tr(ts: Any) -> Optional[str]:
    if ts is None:
        return _today_tr()
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TR_TZ).strftime("%Y-%m-%d")


def hour_tr(ts: Optional[Any] = None) -> int:
    """TR saat dilimi (0–23)."""
    return _hour_tr(ts)


def empty_hour_slots() -> List[List[float]]:
    return _empty_hours()


def hourly_has_activity(data: Dict[str, Any]) -> bool:
    for slot in data.get("h") or _empty_hours():
        if slot and (abs(float(slot[0] or 0)) >= 1e-9 or float(slot[1] or 0) > 0):
            return True
    return False


def write_hourly_data(account_id: int, date_tr: str, hours: List[List[float]]) -> None:
    """Saatlik K/Z dosyasını tamamen yaz (backfill)."""
    payload = {
        "v": _STORE_VERSION,
        "aid": account_id,
        "d": date_tr,
        "h": hours if isinstance(hours, list) and len(hours) == 24 else _empty_hours(),
        "u": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(_hourly_path(account_id, date_tr), payload)


def load_hourly(account_id: int, date_tr: Optional[str] = None) -> Dict[str, Any]:
    """Bugünkü saatlik K/Z dosyası (24 slot)."""
    dt = date_tr or _today_tr()
    path = _hourly_path(account_id, dt)
    if not path.is_file():
        return {
            "v": _STORE_VERSION,
            "aid": account_id,
            "d": dt,
            "h": _empty_hours(),
            "u": datetime.now(timezone.utc).isoformat(),
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid hourly payload")
        hours = data.get("h")
        if not isinstance(hours, list) or len(hours) != 24:
            data["h"] = _empty_hours()
        return data
    except Exception as e:
        logger.debug("load_hourly account_id=%s: %s", account_id, e)
        return {
            "v": _STORE_VERSION,
            "aid": account_id,
            "d": dt,
            "h": _empty_hours(),
            "u": datetime.now(timezone.utc).isoformat(),
        }


def record_hourly_pnl(
    account_id: int,
    pnl_usd: float,
    fees_usd: float,
    *,
    ts: Any = None,
) -> None:
    """Tur kapanışında mevcut TR saat dilimine ekle."""
    date_tr = ts_to_date_tr(ts) or _today_tr()
    hour = _hour_tr(ts)
    path = _hourly_path(account_id, date_tr)
    data = load_hourly(account_id, date_tr)
    hours = data.get("h") or _empty_hours()
    if hour < 0 or hour > 23:
        hour = max(0, min(23, hour))
    slot = hours[hour]
    if not isinstance(slot, list) or len(slot) < 2:
        slot = [0.0, 0.0]
    slot[0] = round(float(slot[0]) + float(pnl_usd), 4)
    slot[1] = round(float(slot[1]) + float(fees_usd), 4)
    hours[hour] = slot
    data["h"] = hours
    data["u"] = datetime.now(timezone.utc).isoformat()
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.warning("record_hourly_pnl account_id=%s: %s", account_id, e)


def hourly_to_series(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    hours = data.get("h") or _empty_hours()
    for i, slot in enumerate(hours):
        pnl = float(slot[0]) if slot and len(slot) > 0 else 0.0
        fees = float(slot[1]) if slot and len(slot) > 1 else 0.0
        out.append(
            {
                "hour": i,
                "label": f"{i:02d}:00",
                "pnl_usd": round(pnl, 4),
                "fees_usd": round(fees, 4),
            }
        )
    return out


def load_daily_ledger(account_id: int) -> Dict[str, Any]:
    path = _daily_path(account_id)
    if not path.is_file():
        return {"v": _STORE_VERSION, "aid": account_id, "days": {}, "u": datetime.now(timezone.utc).isoformat()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid daily payload")
        if "days" not in data or not isinstance(data["days"], dict):
            data["days"] = {}
        return data
    except Exception as e:
        logger.debug("load_daily_ledger account_id=%s: %s", account_id, e)
        return {"v": _STORE_VERSION, "aid": account_id, "days": {}, "u": datetime.now(timezone.utc).isoformat()}


def record_bot_daily_pnl_file(
    account_id: int,
    bot_id: int,
    symbol: str,
    date_tr: str,
    pnl_usd: float,
    fees_usd: float,
    *,
    deleted: bool = False,
) -> None:
    """Kalıcı günlük dosyaya bot satırı ekle/güncelle."""
    path = _daily_path(account_id)
    data = load_daily_ledger(account_id)
    days: Dict[str, Any] = data.setdefault("days", {})
    day = days.setdefault(date_tr, {"p": 0.0, "f": 0.0, "b": {}})
    bots: Dict[str, Any] = day.setdefault("b", {})
    key = str(bot_id)
    prev = bots.get(key) or [0.0, 0.0, (symbol or "").upper(), 1 if deleted else 0]
    new_pnl = round(float(prev[0]) + float(pnl_usd), 4)
    new_fees = round(float(prev[1]) + float(fees_usd), 4)
    sym = (symbol or prev[2] or "").upper()
    bots[key] = [new_pnl, new_fees, sym, 1 if deleted else 0]

    total_pnl = 0.0
    total_fees = 0.0
    for rec in bots.values():
        if isinstance(rec, list) and len(rec) >= 2:
            total_pnl += float(rec[0] or 0)
            total_fees += float(rec[1] or 0)
    day["p"] = round(total_pnl, 4)
    day["f"] = round(total_fees, 4)
    data["u"] = datetime.now(timezone.utc).isoformat()
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.warning("record_bot_daily_pnl_file account_id=%s bot_id=%s: %s", account_id, bot_id, e)


def rebuild_bot_daily_in_file(
    account_id: int,
    bot_id: int,
    symbol: str,
    by_date: Dict[str, Tuple[float, float, int]],
    *,
    deleted: bool = False,
) -> None:
    """Bot için dosyadaki günlük satırları yeniden yaz (silme/backfill)."""
    path = _daily_path(account_id)
    data = load_daily_ledger(account_id)
    days: Dict[str, Any] = data.setdefault("days", {})
    key = str(bot_id)
    sym = (symbol or "").upper()

    for date_tr, day in list(days.items()):
        bots = day.get("b") or {}
        if key in bots:
            del bots[key]
        if not bots:
            if date_tr not in by_date:
                del days[date_tr]
                continue
        total_pnl = 0.0
        total_fees = 0.0
        for rec in bots.values():
            if isinstance(rec, list) and len(rec) >= 2:
                total_pnl += float(rec[0] or 0)
                total_fees += float(rec[1] or 0)
        day["p"] = round(total_pnl, 4)
        day["f"] = round(total_fees, 4)

    for date_tr, (pnl, fees, cnt) in by_date.items():
        day = days.setdefault(date_tr, {"p": 0.0, "f": 0.0, "b": {}})
        bots = day.setdefault("b", {})
        bots[key] = [round(pnl, 4), round(fees, 4), sym, 1 if deleted else 0]
        total_pnl = sum(float(r[0] or 0) for r in bots.values() if isinstance(r, list))
        total_fees = sum(float(r[1] or 0) for r in bots.values() if isinstance(r, list))
        day["p"] = round(total_pnl, 4)
        day["f"] = round(total_fees, 4)

    data["u"] = datetime.now(timezone.utc).isoformat()
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.warning("rebuild_bot_daily_in_file account_id=%s bot_id=%s: %s", account_id, bot_id, e)


def write_daily_ledger(account_id: int, days: Dict[str, Any]) -> None:
    payload = {
        "v": _STORE_VERSION,
        "aid": account_id,
        "days": days,
        "u": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(_daily_path(account_id), payload)


def query_daily_series_from_file(
    account_id: int,
    date_from: str,
    date_to: str,
) -> List[Dict[str, Any]]:
    data = load_daily_ledger(account_id)
    days: Dict[str, Any] = data.get("days") or {}
    out: List[Dict[str, Any]] = []
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return out
    current = start
    while current <= end:
        d_str = current.strftime("%Y-%m-%d")
        rec = days.get(d_str) or {}
        out.append(
            {
                "date_tr": d_str,
                "pnl_usd": round(float(rec.get("p") or 0), 4),
                "fees_usd": round(float(rec.get("f") or 0), 4),
            }
        )
        current += timedelta(days=1)
    return out


def sum_daily_from_file(account_id: int, date_from: str, date_to: str) -> Tuple[float, float]:
    series = query_daily_series_from_file(account_id, date_from, date_to)
    pnl = sum(d["pnl_usd"] for d in series)
    fees = sum(d["fees_usd"] for d in series)
    return round(pnl, 2), round(fees, 2)


def _base_from_symbol(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    if s == "MULTI":
        return "MULTI"
    for q in ("USDT", "FDUSD", "BUSD", "USDC"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _compact_cycle(entry: Dict[str, Any], *, symbol: str = "") -> Optional[Dict[str, Any]]:
    """Tamamlanan tur → kompakt kayıt."""
    if not entry or not isinstance(entry, dict):
        return None
    at = entry.get("completed_at")
    if not at:
        return None
    date_tr = ts_to_date_tr(at)
    if not date_tr:
        return None
    cid = entry.get("cycle_id")
    sym = (entry.get("symbol") or symbol or "").upper()
    px = 0.0
    for key in ("close_price_quote_per_base", "close_px", "px"):
        try:
            v = float(entry.get(key) or 0)
            if v > 0:
                px = v
                break
        except (TypeError, ValueError):
            pass
    if px <= 0:
        close_fill = entry.get("close_fill")
        if isinstance(close_fill, dict):
            for key in ("price", "execution_price"):
                try:
                    v = float(close_fill.get(key) or 0)
                    if v > 0:
                        px = v
                        break
                except (TypeError, ValueError):
                    pass
    row = {
        "i": int(cid) if cid is not None else 0,
        "t": str(at),
        "d": date_tr,
        "r": str(entry.get("completed_reason") or entry.get("close_reason") or "")[:32],
        "ct": str(entry.get("cycle_type") or "")[:16],
        "cp": round(float(entry.get("cash_pnl_usdt") or 0), 8),
        "cf": round(float(entry.get("cash_fees_usdt") or 0), 8),
        "iq": round(float(entry.get("inventory_coin_adv_qty") or 0), 12),
        "if": round(float(entry.get("inventory_fees_usdt") or 0), 8),
    }
    if sym:
        row["sy"] = sym[:24]
    if px > 0:
        row["px"] = round(px, 8)
    return row


def expand_cycle(compact: Dict[str, Any]) -> Dict[str, Any]:
    """Kompakt kayıt → aggregate_dual_perf uyumlu dict."""
    out = {
        "cycle_id": compact.get("i"),
        "completed_at": compact.get("t"),
        "completed_reason": compact.get("r"),
        "cycle_type": compact.get("ct"),
        "cash_pnl_usdt": float(compact.get("cp") or 0),
        "cash_fees_usdt": float(compact.get("cf") or 0),
        "inventory_coin_adv_qty": float(compact.get("iq") or 0),
        "inventory_fees_usdt": float(compact.get("if") or 0),
    }
    if compact.get("sy"):
        out["symbol"] = compact.get("sy")
    if compact.get("px") is not None:
        out["close_price_quote_per_base"] = float(compact.get("px") or 0)
    return out


def _cycle_dedupe_key(compact: Dict[str, Any]) -> str:
    return f"{compact.get('i')}|{compact.get('t')}"


def load_bot_cycles_file(bot_id: int) -> Dict[str, Any]:
    path = _bot_cycles_path(bot_id)
    if not path.is_file():
        return {"v": _STORE_VERSION, "bid": bot_id, "aid": None, "sym": "", "c": [], "u": datetime.now(timezone.utc).isoformat()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid bot cycles payload")
        if not isinstance(data.get("c"), list):
            data["c"] = []
        return data
    except Exception as e:
        logger.debug("load_bot_cycles_file bot_id=%s: %s", bot_id, e)
        return {"v": _STORE_VERSION, "bid": bot_id, "aid": None, "sym": "", "c": [], "u": datetime.now(timezone.utc).isoformat()}


def list_bot_completed_cycles(bot_id: int) -> List[Dict[str, Any]]:
    data = load_bot_cycles_file(bot_id)
    out: List[Dict[str, Any]] = []
    for row in data.get("c") or []:
        if isinstance(row, dict):
            out.append(expand_cycle(row))
    return out


def _completed_cycles_dedupe_keys(
    completed_cycles: List[Dict[str, Any]],
    *,
    symbol: str = "",
) -> set:
    keys: set = set()
    for entry in completed_cycles or []:
        if not isinstance(entry, dict):
            continue
        compact = _compact_cycle(entry, symbol=symbol)
        if compact:
            keys.add(_cycle_dedupe_key(compact))
    return keys


def reconcile_bot_cycles_file_with_state(
    bot_id: int,
    account_id: int,
    symbol: str,
    completed_cycles: List[Dict[str, Any]],
) -> bool:
    """State/arşiv tek kaynak; dosya `aid` veya tur kümesi uyuşmazsa yeniden yazar."""
    data = load_bot_cycles_file(bot_id)
    file_aid = data.get("aid")
    file_keys = {
        _cycle_dedupe_key(c)
        for c in (data.get("c") or [])
        if isinstance(c, dict)
    }
    state_keys = _completed_cycles_dedupe_keys(completed_cycles, symbol=symbol)
    mismatch = False
    if file_aid is not None and int(file_aid) != int(account_id):
        mismatch = True
    elif file_keys != state_keys:
        mismatch = True
    if mismatch:
        rebuild_bot_cycles_file(bot_id, account_id, symbol, completed_cycles)
        return True
    return False


def query_bot_cycles_by_date_range(
    bot_id: int,
    date_from: str,
    date_to: str,
) -> List[Dict[str, Any]]:
    """TR takvim günü [date_from, date_to] içindeki kapanan turlar."""
    out: List[Dict[str, Any]] = []
    for entry in list_bot_completed_cycles(bot_id):
        d = ts_to_date_tr(entry.get("completed_at"))
        if d and date_from <= d <= date_to:
            out.append(entry)
    return out


def earliest_bot_cycle_date(bot_id: int) -> Optional[str]:
    dates: List[str] = []
    for entry in list_bot_completed_cycles(bot_id):
        d = ts_to_date_tr(entry.get("completed_at"))
        if d:
            dates.append(d)
    return min(dates) if dates else None


def _account_round_dedupe_key(row: Dict[str, Any]) -> str:
    return f"{row.get('bid')}|{row.get('cid')}|{row.get('t')}"


def _raw_round_from_entry(
    bot_id: int,
    account_id: int,
    symbol: str,
    entry: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Hesap ham tur defteri satırı (tarih/saat + USDT K/Z)."""
    if not entry or not isinstance(entry, dict):
        return None
    at = entry.get("completed_at")
    if not at:
        return None
    date_tr = ts_to_date_tr(at)
    if not date_tr:
        return None
    sym = (entry.get("symbol") or symbol or "").upper()
    from app.services.bot_performance_service import _cycle_ledger_amounts

    pnl_usd, fees_usd = _cycle_ledger_amounts(entry, symbol=sym)
    cid = entry.get("cycle_id")
    side = None
    try:
        from app.services.bot_performance_service import _completed_cycle_side

        side = _completed_cycle_side(entry)
    except Exception:
        pass
    px = 0.0
    for key in ("close_price_quote_per_base", "close_px", "px"):
        try:
            v = float(entry.get(key) or 0)
            if v > 0:
                px = v
                break
        except (TypeError, ValueError):
            pass
    return {
        "bid": bot_id,
        "aid": account_id,
        "sym": sym,
        "base": _base_from_symbol(sym),
        "cid": int(cid) if cid is not None else 0,
        "t": str(at),
        "d": date_tr,
        "h": hour_tr(at),
        "side": side or "",
        "cp": round(float(entry.get("cash_pnl_usdt") or 0), 8),
        "cf": round(float(entry.get("cash_fees_usdt") or 0), 8),
        "iq": round(float(entry.get("inventory_coin_adv_qty") or 0), 12),
        "if": round(float(entry.get("inventory_fees_usdt") or 0), 8),
        "px": round(px, 8) if px > 0 else None,
        "pnl": round(pnl_usd, 4),
        "fee": round(fees_usd, 4),
    }


def load_account_rounds(account_id: int) -> Dict[str, Any]:
    path = _account_rounds_path(account_id)
    if not path.is_file():
        return {
            "v": _ACCOUNT_ROUNDS_VERSION,
            "aid": account_id,
            "r": [],
            "u": datetime.now(timezone.utc).isoformat(),
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid account rounds payload")
        if not isinstance(data.get("r"), list):
            data["r"] = []
        return data
    except Exception as e:
        logger.debug("load_account_rounds account_id=%s: %s", account_id, e)
        return {
            "v": _ACCOUNT_ROUNDS_VERSION,
            "aid": account_id,
            "r": [],
            "u": datetime.now(timezone.utc).isoformat(),
        }


def append_account_round(
    account_id: int,
    bot_id: int,
    symbol: str,
    cycle_entry: Dict[str, Any],
) -> None:
    """Tur kapanışında hesap ham defterine ekle."""
    row = _raw_round_from_entry(bot_id, account_id, symbol, cycle_entry)
    if not row:
        return
    path = _account_rounds_path(account_id)
    data = load_account_rounds(account_id)
    rounds: List[Any] = data.get("r") or []
    key = _account_round_dedupe_key(row)
    existing = {_account_round_dedupe_key(r) for r in rounds if isinstance(r, dict)}
    if key in existing:
        return
    rounds.append(row)
    if len(rounds) > _MAX_ACCOUNT_ROUNDS:
        rounds = rounds[-_MAX_ACCOUNT_ROUNDS:]
    data["r"] = rounds
    data["aid"] = account_id
    data["u"] = datetime.now(timezone.utc).isoformat()
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.warning("append_account_round account_id=%s: %s", account_id, e)


def rebuild_account_rounds_file(
    account_id: int,
    bot_rounds: List[Tuple[int, str, List[Dict[str, Any]]]],
) -> None:
    """Tüm bot turlarından hesap ham defterini yeniden yaz."""
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for bot_id, symbol, cycles in bot_rounds:
        for entry in cycles or []:
            expanded = entry
            if entry and "completed_at" not in entry and entry.get("t"):
                expanded = expand_cycle(entry)
            row = _raw_round_from_entry(bot_id, account_id, symbol, expanded)
            if not row:
                continue
            key = _account_round_dedupe_key(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda r: (r.get("d") or "", r.get("t") or ""))
    if len(rows) > _MAX_ACCOUNT_ROUNDS:
        rows = rows[-_MAX_ACCOUNT_ROUNDS:]
    payload = {
        "v": _ACCOUNT_ROUNDS_VERSION,
        "aid": account_id,
        "r": rows,
        "u": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _atomic_write_json(_account_rounds_path(account_id), payload)
    except Exception as e:
        logger.warning("rebuild_account_rounds_file account_id=%s: %s", account_id, e)


def round_row_key(row: Dict[str, Any]) -> str:
    return _account_round_dedupe_key(row)


def account_rounds_revision(account_id: int) -> str:
    """Dosya güncelleme damgası — performans cache geçerliliği."""
    return str(load_account_rounds(account_id).get("u") or "")


def sum_rounds_totals(rounds: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Kapanan tur satırlarından USDT K/Z + komisyon toplamı."""
    pnl = 0.0
    fees = 0.0
    for row in rounds or []:
        if not isinstance(row, dict):
            continue
        pnl += float(row.get("pnl") or 0)
        fees += float(row.get("fee") or 0)
    return round(pnl, 2), round(fees, 2)


def query_account_rounds_by_date_range(
    account_id: int,
    date_from: str,
    date_to: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in load_account_rounds(account_id).get("r") or []:
        if not isinstance(row, dict):
            continue
        d = row.get("d") or ts_to_date_tr(row.get("t"))
        if d and date_from <= d <= date_to:
            out.append(row)
    return out


def aggregate_rounds_to_daily_series(
    rounds: List[Dict[str, Any]],
    date_from: str,
    date_to: str,
) -> List[Dict[str, Any]]:
    """Yalnızca aktivitesi olan günler (sıfır satır yok)."""
    by_date: Dict[str, Dict[str, float]] = {}
    for row in rounds:
        d = row.get("d")
        if not d or d < date_from or d > date_to:
            continue
        bucket = by_date.setdefault(d, {"pnl_usd": 0.0, "fees_usd": 0.0})
        bucket["pnl_usd"] += float(row.get("pnl") or 0)
        bucket["fees_usd"] += float(row.get("fee") or 0)
    out: List[Dict[str, Any]] = []
    for d in sorted(by_date.keys()):
        agg = by_date[d]
        pnl = round(agg["pnl_usd"], 4)
        fees = round(agg["fees_usd"], 4)
        if abs(pnl) < 1e-9 and fees <= 0:
            continue
        out.append({"date_tr": d, "pnl_usd": pnl, "fees_usd": fees})
    return out


def aggregate_rounds_to_hourly_series(
    rounds: List[Dict[str, Any]],
    date_tr: str,
) -> List[Dict[str, Any]]:
    hours = empty_hour_slots()
    for row in rounds:
        if (row.get("d") or "") != date_tr:
            continue
        pnl = float(row.get("pnl") or 0)
        fees = float(row.get("fee") or 0)
        if abs(pnl) < 1e-9 and fees <= 0:
            continue
        h = int(row.get("h") if row.get("h") is not None else hour_tr(row.get("t")))
        if h < 0 or h > 23:
            h = max(0, min(23, h))
        hours[h][0] = round(float(hours[h][0]) + pnl, 4)
        hours[h][1] = round(float(hours[h][1]) + fees, 4)
    return hourly_to_series({"h": hours})


def record_closed_cycle_file(
    bot_id: int,
    account_id: int,
    symbol: str,
    cycle_entry: Dict[str, Any],
) -> None:
    """Tur kapanışında anında dosyaya ekle (idempotent)."""
    compact = _compact_cycle(cycle_entry, symbol=symbol)
    if not compact:
        return
    path = _bot_cycles_path(bot_id)
    data = load_bot_cycles_file(bot_id)
    cycles: List[Any] = data.get("c") or []
    key = _cycle_dedupe_key(compact)
    existing_keys = {_cycle_dedupe_key(c) for c in cycles if isinstance(c, dict)}
    if key in existing_keys:
        return
    cycles.append(compact)
    if len(cycles) > _MAX_BOT_CYCLES:
        cycles = cycles[-_MAX_BOT_CYCLES:]
    data["c"] = cycles
    data["bid"] = bot_id
    data["aid"] = account_id
    data["sym"] = (symbol or data.get("sym") or "").upper()
    data["u"] = datetime.now(timezone.utc).isoformat()
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.warning("record_closed_cycle_file bot_id=%s: %s", bot_id, e)
    try:
        append_account_round(account_id, bot_id, symbol, cycle_entry)
    except Exception as e:
        logger.debug("append_account_round bot_id=%s: %s", bot_id, e)


_cycles_rebuild_fp: Dict[int, str] = {}
_MAX_CYCLES_REBUILD_FP = 800


def _completed_cycles_fingerprint(completed_cycles: List[Dict[str, Any]]) -> str:
    n = len(completed_cycles or [])
    if n == 0:
        return "0"
    last = completed_cycles[-1] if isinstance(completed_cycles[-1], dict) else {}
    return f"{n}:{last.get('completed_at') or last.get('cycle_id') or ''}"


def rebuild_bot_cycles_file_if_changed(
    bot_id: int,
    account_id: int,
    symbol: str,
    completed_cycles: List[Dict[str, Any]],
) -> bool:
    """Fingerprint değişmediyse disk yazma atlanır (sync tick RAM/IO)."""
    fp = _completed_cycles_fingerprint(completed_cycles)
    if _cycles_rebuild_fp.get(bot_id) == fp:
        return False
    _cycles_rebuild_fp[bot_id] = fp
    if len(_cycles_rebuild_fp) > _MAX_CYCLES_REBUILD_FP:
        for k in list(_cycles_rebuild_fp.keys())[: _MAX_CYCLES_REBUILD_FP // 2]:
            _cycles_rebuild_fp.pop(k, None)
    rebuild_bot_cycles_file(bot_id, account_id, symbol, completed_cycles)
    return True


def rebuild_bot_cycles_file(
    bot_id: int,
    account_id: int,
    symbol: str,
    completed_cycles: List[Dict[str, Any]],
) -> None:
    """State/arşiv backfill — yalnızca tamamlanan turlar."""
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in completed_cycles or []:
        compact = _compact_cycle(entry, symbol=symbol)
        if not compact:
            continue
        key = _cycle_dedupe_key(compact)
        if key in seen:
            continue
        seen.add(key)
        rows.append(compact)
    rows.sort(key=lambda c: (c.get("d") or "", c.get("t") or ""))
    if len(rows) > _MAX_BOT_CYCLES:
        rows = rows[-_MAX_BOT_CYCLES:]
    payload = {
        "v": _STORE_VERSION,
        "bid": bot_id,
        "aid": account_id,
        "sym": (symbol or "").upper(),
        "c": rows,
        "u": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _atomic_write_json(_bot_cycles_path(bot_id), payload)
    except Exception as e:
        logger.warning("rebuild_bot_cycles_file bot_id=%s: %s", bot_id, e)


def sum_bot_daily_from_file(
    account_id: int,
    bot_id: int,
    date_from: str,
    date_to: str,
) -> Tuple[float, float, int]:
    """Hesap günlük defterinden tek bot toplamı (dashboard ile uyumlu yedek)."""
    data = load_daily_ledger(account_id)
    days: Dict[str, Any] = data.get("days") or {}
    key = str(bot_id)
    pnl = 0.0
    fees = 0.0
    cycles = 0
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return 0.0, 0.0, 0
    current = start
    while current <= end:
        d_str = current.strftime("%Y-%m-%d")
        rec = (days.get(d_str) or {}).get("b") or {}
        row = rec.get(key)
        if isinstance(row, list) and len(row) >= 2:
            pnl += float(row[0] or 0)
            fees += float(row[1] or 0)
            cycles += 1
        current += timedelta(days=1)
    return round(pnl, 4), round(fees, 4), cycles
