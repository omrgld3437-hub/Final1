"""
Bot performans dosya deposu — hızlı okuma için kompakt JSON.

- Saatlik (bugün): `.run/bot_perf/hourly/{account_id}_{date_tr}.json` — her gece yeni dosya (00:00 TR).
- Kalıcı günlük: `.run/bot_perf/daily/{account_id}.json` — bot başına günlük K/Z; haftalık/aylık/genel buradan.
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
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PERF_ROOT = _PROJECT_ROOT / ".run" / "bot_perf"


def _ensure_dirs() -> None:
    (_PERF_ROOT / "hourly").mkdir(parents=True, exist_ok=True)
    (_PERF_ROOT / "daily").mkdir(parents=True, exist_ok=True)


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
