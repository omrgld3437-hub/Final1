"""
Bot Engine API: create, list, detail, start, stop, update-config, events, trades.
Auth: require_auth + get_account_or_403(bot.account_id) for bot-specific routes.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import threading
import time
import uuid
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _bot_run_started_at_for_api(
    bot: Any, state: Optional[Dict[str, Any]], db: Session
) -> Optional[str]:
    """UI süre sayacı — oturum başlangıcı (connectivity/worker yeniden başlatmada sıfırlanmaz)."""
    from app.botengine.bot_session import bot_run_started_at_iso

    return bot_run_started_at_iso(bot, state, db)


def _bot_run_started_at_dt(bot: Any, state: Optional[Dict[str, Any]], db: Session):
    """datetime for daily PnL / perf chart session filter."""
    iso = _bot_run_started_at_for_api(bot, state, db)
    if not iso:
        return getattr(bot, "started_at", None)
    try:
        s = iso.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return getattr(bot, "started_at", None)


# ---------------------------------------------------------------------------
# Live snapshot cache: TTL 2s, key = bot_id. Thread-safe. No historical DB.
# ---------------------------------------------------------------------------
_LIVE_CACHE: Dict[int, Tuple[dict, float]] = {}
_LIVE_CACHE_LOCK = threading.Lock()
_LIVE_CACHE_TTL_SEC = 3.0
_LIVE_BATCH_MAX_BOTS = 50

# Session alpha (oturum performansı hero): TTL 60s — ağır PnL/performance endpoint'inden ayrı.
_SESSION_ALPHA_CACHE: Dict[int, Tuple[dict, float]] = {}
_SESSION_ALPHA_CACHE_LOCK = threading.Lock()
_SESSION_ALPHA_CACHE_TTL_SEC = 60.0


def invalidate_session_alpha_cache(bot_id: int) -> None:
    with _SESSION_ALPHA_CACHE_LOCK:
        _SESSION_ALPHA_CACHE.pop(int(bot_id), None)


def _session_alpha_get_cached(bot_id: int) -> Optional[dict]:
    now = datetime.now(timezone.utc).timestamp()
    with _SESSION_ALPHA_CACHE_LOCK:
        entry = _SESSION_ALPHA_CACHE.get(bot_id)
        if not entry:
            return None
        data, expiry = entry
        if now >= expiry:
            del _SESSION_ALPHA_CACHE[bot_id]
            return None
        return data


def _session_alpha_set_cached(bot_id: int, data: dict) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _SESSION_ALPHA_CACHE_LOCK:
        _SESSION_ALPHA_CACHE[bot_id] = (data, now + _SESSION_ALPHA_CACHE_TTL_SEC)


def invalidate_live_snapshot_cache(bot_id: int) -> None:
    """State kaydedildiğinde live TTL önbelleğini temizle."""
    with _LIVE_CACHE_LOCK:
        _LIVE_CACHE.pop(int(bot_id), None)
    invalidate_session_alpha_cache(bot_id)


def _live_snapshot_get_cached(bot_id: int) -> Optional[dict]:
    now = datetime.now(timezone.utc).timestamp()
    with _LIVE_CACHE_LOCK:
        entry = _LIVE_CACHE.get(bot_id)
        if not entry:
            return None
        data, expiry = entry
        if now >= expiry:
            del _LIVE_CACHE[bot_id]
            return None
        return data


def _live_snapshot_set_cached(bot_id: int, data: dict) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _LIVE_CACHE_LOCK:
        _LIVE_CACHE[bot_id] = (data, now + _LIVE_CACHE_TTL_SEC)


# ---------------------------------------------------------------------------
# Perf chart data: deterministic bucket engine + LRU cache. O(n). Max 500 points.
# ---------------------------------------------------------------------------
BUCKET_SECONDS = {"1m": 60, "5m": 300, "1h": 3600, "4h": 14400, "1d": 86400}
WINDOW_SECONDS = {
    "1h": 86400,
    "4h": 259200,
    "1d": 2592000,
    "7d": 7776000,
    "30d": 31536000,
}
PERF_SERIES_MAX_POINTS = 500


class PerfLRUCache:
    """Thread-safe LRU + TTL cache for perf chart responses. Key = (bot_id, range, bucket)."""

    max_entries = 100
    ttl_seconds = 5
    _storage: OrderedDict = OrderedDict()
    _lock = threading.Lock()

    @classmethod
    def _key(cls, bot_id: int, range_val: str, bucket: str) -> Tuple[int, str, str]:
        return (bot_id, range_val, bucket)

    @classmethod
    def get(cls, bot_id: int, range_val: str, bucket: str) -> Optional[dict]:
        key = cls._key(bot_id, range_val, bucket)
        now = datetime.now(timezone.utc).timestamp()
        with cls._lock:
            if key not in cls._storage:
                return None
            entry = cls._storage[key]
            if now >= entry["expiry"]:
                del cls._storage[key]
                return None
            cls._storage.move_to_end(key)
            return entry["value"]

    @classmethod
    def set(cls, bot_id: int, range_val: str, bucket: str, value: dict) -> None:
        key = cls._key(bot_id, range_val, bucket)
        now = datetime.now(timezone.utc).timestamp()
        with cls._lock:
            if key in cls._storage:
                cls._storage.move_to_end(key)
            cls._storage[key] = {"value": value, "expiry": now + cls.ttl_seconds}
            while len(cls._storage) > cls.max_entries:
                cls._storage.popitem(last=False)


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.auth import get_account_or_403, require_auth, get_client_ip
from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.api.bots_engine_services import detail_err as _detail_err
from app.botengine.models import DcaGridTrailingConfig, config_from_ui_payload
from app.botengine.dca_manager import (
    MaxBuyLevelsError,
    normalize_max_buy_levels_payload,
)
from app.services import audit as audit_svc
from app.botengine.orchestrator import delete_bot_fully, invalidate_config_cache
from app.botengine.state_store import (
    ensure_state_row,
    list_events,
    load_state,
    normalize_event_ts_iso_z,
    save_state,
)
from app.botengine.grid_view import compute_grid_profit_view, compute_trdca_grid_view
from app.db.session import get_db
from app.db.models import Bot, Account, Trade, PnlSnapshot
from app.services.pnl_service import PnlService, ensure_daily_ref_and_compute
from app.services.price_hub import price_hub
from app.services.perf_chart_state import (
    seed_perf_chart_state_on_bot_start,
    compute_trdca_parite_pct,
    build_bot_alpha_performance,
    resolve_session_alpha_performance,
)

router = APIRouter()

BINANCE_PUBLIC = "https://api.binance.com"


def _get_price_from_datahub(sym_pair: str) -> Optional[float]:
    """DataHub cache only; stale data is never a live-price candidate."""
    try:
        from app.services.data_hub import data_hub

        meta = data_hub.get_price_with_meta(sym_pair.upper())
        if not meta or meta.get("is_stale"):
            return None
        p = meta.get("price")
        if p is not None and float(p) > 0:
            return float(p)
    except Exception:
        pass
    return None


def _resolve_bot_live_price(
    sym: str,
    state: Optional[Dict[str, Any]] = None,
    *,
    pnl_price: Optional[float] = None,
) -> float:
    """Resolve a genuinely live market price.

    A cycle reference and the last trade are accounting anchors, not market
    prices. They must never be published as ``current_price``.
    """
    sym_u = (sym or "").strip().upper()
    live = 0.0
    try:
        p = price_hub.get_price(sym_u)
        if p is not None and float(p) > 0:
            live = float(p)
    except Exception:
        pass
    if live <= 0 and sym_u:
        hub_p = _get_price_from_datahub(sym_u)
        if hub_p is not None and float(hub_p) > 0:
            live = float(hub_p)
    return live


def _bot_price_meta(sym: str) -> Dict[str, Any]:
    """Return display-safe price metadata without promoting stale values."""
    sym_u = (sym or "").strip().upper()
    meta = price_hub.get_price_with_meta(sym_u) if sym_u else None
    if not meta:
        return {
            "price": None,
            "source": None,
            "is_stale": True,
            "age_s": None,
        }
    ts = _float_or_none(meta.get("ts"))
    age_s = max(0.0, time.time() - ts) if ts else None
    price = _float_or_none(meta.get("price"))
    stale = bool(meta.get("is_stale")) or price is None
    return {
        "price": None if stale else price,
        "source": "data_hub",
        "is_stale": stale,
        "age_s": round(age_s, 1) if age_s is not None else None,
        "last_known_price": price if stale else None,
    }


def _float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _price_ratio_too_wide(a: Optional[float], b: Optional[float], limit: float = 20.0) -> bool:
    if not a or not b or a <= 0 or b <= 0:
        return False
    lo = min(float(a), float(b))
    hi = max(float(a), float(b))
    return lo > 0 and (hi / lo) >= limit


def _state_reference_looks_wrong(
    ref: Optional[float], anchors: List[float], live_price: Optional[float] = None
) -> bool:
    if not ref or ref <= 0:
        return True
    checks = [p for p in anchors if p and p > 0]
    if live_price and live_price > 0:
        checks.append(float(live_price))
    if not checks:
        return False
    return any(_price_ratio_too_wide(ref, p) for p in checks)


def _same_symbol_trade_prices(
    db: Session,
    bot_id: int,
    symbol: str,
    cycle_id: Optional[int] = None,
    limit: int = 80,
) -> List[float]:
    prices: List[float] = []
    if not symbol or symbol == "MULTI":
        return prices
    try:
        q = db.query(Trade).filter(Trade.bot_id == bot_id, Trade.symbol == symbol)
        if cycle_id is not None:
            q = q.filter(Trade.cycle_id == int(cycle_id))
        rows = q.order_by(Trade.ts.asc(), Trade.id.asc()).limit(limit).all()
        for row in rows:
            p = _float_or_none(getattr(row, "price", None))
            if p:
                prices.append(p)
    except Exception as ex:
        logger.debug("same_symbol_trade_prices bot_id=%s symbol=%s: %s", bot_id, symbol, ex)
    return prices


def _state_ledger_fill_prices(state: Optional[Dict[str, Any]], symbol: str, cycle_id: int) -> List[float]:
    out: List[float] = []
    if not state:
        return out
    ledger = state.get("cycle_ledger_current") or {}
    if isinstance(ledger, dict):
        led_sym = str(ledger.get("symbol") or symbol).upper()
        if led_sym == symbol and int(state.get("cycle_id") or 1) == int(cycle_id):
            for fill in ledger.get("fills") or []:
                if isinstance(fill, dict):
                    p = _float_or_none(fill.get("price"))
                    if p:
                        out.append(p)
    for block in state.get("cycle_ledger_fills_archive") or []:
        if not isinstance(block, dict):
            continue
        if int(block.get("cycle_id") or 0) != int(cycle_id):
            continue
        if str(block.get("symbol") or symbol).upper() != symbol:
            continue
        for fill in block.get("fills") or []:
            if isinstance(fill, dict):
                p = _float_or_none(fill.get("price"))
                if p:
                    out.append(p)
    return out


def _recompute_grid_trigger_arrays_from_ref(
    state: Dict[str, Any], raw_config: Dict[str, Any], ref: float
) -> None:
    if not state or ref <= 0:
        return
    buy_grids = raw_config.get("buy_grids") or raw_config.get("down_grids") or []
    sell_grids = raw_config.get("sell_grids") or raw_config.get("up_grids") or []
    if isinstance(buy_grids, list) and buy_grids:
        state["buy_grid_trigger_price"] = [
            round(ref * (1.0 - float((g or {}).get("buy_grid_pct") or (g or {}).get("trigger_pct") or 0) / 100.0), 10)
            for g in buy_grids
            if isinstance(g, dict)
        ]
    if isinstance(sell_grids, list) and sell_grids:
        state["sell_grid_trigger_price"] = [
            round(ref * (1.0 + float((g or {}).get("sell_grid_pct") or (g or {}).get("trigger_pct") or 0) / 100.0), 10)
            for g in sell_grids
            if isinstance(g, dict)
        ]


def _repair_bot_state_reference_if_needed(
    db: Session,
    bot: Bot,
    state: Optional[Dict[str, Any]],
    raw_config: Dict[str, Any],
    live_price: Optional[float],
) -> bool:
    if not state:
        return False
    symbol = (bot.symbol or "").strip().upper()
    if not symbol or symbol == "MULTI":
        return False
    cycle_id = int(state.get("cycle_id") or 1)
    anchors = _state_ledger_fill_prices(state, symbol, cycle_id)
    anchors.extend(_same_symbol_trade_prices(db, bot.id, symbol, cycle_id=cycle_id))
    anchors = [p for p in anchors if p and p > 0]
    ref = _float_or_none(state.get("reference_price"))
    if not _state_reference_looks_wrong(ref, anchors, live_price):
        return False
    candidate = anchors[0] if anchors else (_float_or_none(live_price) or None)
    if not candidate:
        return False
    candidate = round(float(candidate), 10)
    old_ref = ref
    state["reference_price"] = candidate
    if _state_reference_looks_wrong(_float_or_none(state.get("initial_alloc_price")), anchors, live_price):
        state["initial_alloc_price"] = candidate
    for row in state.get("cycle_open_trades") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("cycle_id") or 0) != cycle_id:
            continue
        rp = _float_or_none(row.get("reference_price") or row.get("price"))
        if _state_reference_looks_wrong(rp, anchors, live_price):
            row["reference_price"] = candidate
            row["price"] = candidate
            row["reference_repaired"] = True
        break
    _recompute_grid_trigger_arrays_from_ref(state, raw_config or {}, candidate)
    state["reference_repair"] = {
        "old_reference_price": old_ref,
        "new_reference_price": candidate,
        "symbol": symbol,
        "cycle_id": cycle_id,
        "source": "same_symbol_trade_or_live_price",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    persisted = False
    try:
        save_state(db, bot.id, bot.account_id, state)
        persisted = True
        invalidate_live_snapshot_cache(bot.id)
    except Exception as ex:
        logger.warning(
            "BOT_REFERENCE_REPAIR_SAVE_DEFERRED bot_id=%s symbol=%s err=%s",
            bot.id,
            symbol,
            ex,
        )
    try:
        from app.botengine.state_store import append_event

        if persisted:
            append_event(
                db,
                bot.id,
                bot.account_id,
                "INFO",
                f"Tur referans fiyatı onarıldı · {symbol} {old_ref} → {candidate}",
                {
                    "error_code": "REFERENCE_PRICE_REPAIRED",
                    "old_reference_price": old_ref,
                    "new_reference_price": candidate,
                    "symbol": symbol,
                    "cycle_id": cycle_id,
                },
                state=state,
            )
    except Exception:
        pass
    logger.warning(
        "BOT_REFERENCE_REPAIRED bot_id=%s symbol=%s cycle_id=%s old_ref=%s new_ref=%s",
        bot.id,
        symbol,
        cycle_id,
        old_ref,
        candidate,
    )
    return True


async def _fetch_prices_parallel(
    assets: List[str], quote_asset: str
) -> Dict[str, float]:
    """Asset listesi için fiyatları DataHub'dan al (bulk-only, no per-symbol REST)."""
    out: Dict[str, float] = {}
    for a in assets:
        if a == quote_asset:
            continue
        sym = f"{a}{quote_asset}"
        p = _get_price_from_datahub(sym)
        if p is not None:
            out[a] = p
    return out


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", None) or uuid.uuid4())[:16]


def _worker_process_alive() -> bool:
    """True if engine worker PID file exists and process responds to signal 0."""
    try:
        root = Path(__file__).resolve().parents[2]
        pid_path = root / ".run" / "worker.pid"
        if not pid_path.is_file():
            return False
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, ProcessLookupError):
        return False


def _parse_event_ts_ms(ts: Any) -> int:
    """Event ts → UTC epoch ms (UI sıralama)."""
    if ts is None:
        return 0
    try:
        if isinstance(ts, datetime):
            dt = ts
        else:
            s = str(ts).strip().replace(" ", "T")
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            elif "+" not in s[10:] and s.count("-") <= 2:
                s = s + "+00:00"
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _is_first_tur_cycle_start(ev: Dict[str, Any]) -> bool:
    if (ev.get("type") or "") != "CYCLE_START":
        return False
    meta = ev.get("meta") or {}
    return bool(
        meta.get("first_tur")
        or (meta.get("reason") or "").strip() == "initial_allocation"
    )


def _find_initial_alloc_fill(
    events: List[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    found: Optional[Dict[str, Any]] = None
    for ev in events:
        if (ev.get("type") or "") != "ORDER_FILLED":
            continue
        meta = ev.get("meta") or {}
        if (meta.get("reason") or "").strip() != "initial_allocation":
            continue
        if int(meta.get("cycle_id") or 0) != int(cycle_id):
            continue
        fid = int(ev.get("id") or 0)
        if found is None or fid > int(found.get("id") or 0):
            found = ev
    return found


def _event_sort_timestamp(ev: Dict[str, Any], events: List[Dict[str, Any]]) -> int:
    """Tur 1 CYCLE_START (+1sn) ile ilk base aynı kümede; listede tur üstte."""
    ts = _parse_event_ts_ms(ev.get("ts"))
    if not _is_first_tur_cycle_start(ev):
        return ts
    meta = ev.get("meta") or {}
    cid = int(meta.get("cycle_id") or 1)
    fill = _find_initial_alloc_fill(events, cid)
    if not fill:
        return ts
    fts = _parse_event_ts_ms(fill.get("ts"))
    if fts <= 0:
        return ts
    if ts >= fts and (ts - fts) <= 8000:
        return fts
    return ts


def _event_ui_sort_rank(ev: Dict[str, Any]) -> int:
    """Aynı kümede: ilk base üstte, Tur başlatıldı hemen altında (yeniden→eskiye okununca)."""
    meta = ev.get("meta") or {}
    if (ev.get("type") or "") == "ORDER_FILLED" and (
        meta.get("reason") or ""
    ).strip() == "initial_allocation":
        return 2
    if _is_first_tur_cycle_start(ev):
        return 1
    return 0


def _sort_engine_events_asc(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        events,
        key=lambda e: (
            _event_sort_timestamp(e, events),
            _event_ui_sort_rank(e),
            int(e.get("id") or 0),
        ),
    )


def _sort_engine_events_desc(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        events,
        key=lambda e: (
            _event_sort_timestamp(e, events),
            _event_ui_sort_rank(e),
            int(e.get("id") or 0),
        ),
        reverse=True,
    )


def _synthetic_cycle_start_event_id(cycle_id: int) -> int:
    """Stable negative id for UI merge (not persisted to bot_engine_events)."""
    return -(int(cycle_id) * 100 + 1)


def _synthetic_cycle_end_event_id(cycle_id: int) -> int:
    """Stable negative id; distinct from CYCLE_START synthetic id."""
    return -(int(cycle_id) * 100 + 2)


def _logged_cycle_start_ids(events: List[Dict[str, Any]]) -> set:
    logged: set = set()
    for ev in events:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        meta = ev.get("meta") or {}
        try:
            logged.add(int(meta.get("cycle_id") or 0))
        except (TypeError, ValueError):
            pass
    return logged


def _logged_cycle_end_ids(events: List[Dict[str, Any]]) -> set:
    logged: set = set()
    for ev in events:
        if (ev.get("type") or "") != "CYCLE_END":
            continue
        meta = ev.get("meta") or {}
        try:
            logged.add(int(meta.get("cycle_id") or 0))
        except (TypeError, ValueError):
            pass
    logged.discard(0)
    return logged


def _db_logged_cycle_end_ids(db: Session, bot_id: int) -> set:
    """Persisted CYCLE_END cycle_ids — incremental /events slice için sentetik tekrarını önler."""
    logged: set = set()
    try:
        rows = db.execute(
            text("""
                SELECT meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND event_type = 'CYCLE_END' AND id > 0
            """),
            {"bid": bot_id},
        ).fetchall()
        for row in rows:
            if not row or not row[0]:
                continue
            try:
                meta = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            except Exception:
                meta = {}
            try:
                logged.add(int(meta.get("cycle_id") or 0))
            except (TypeError, ValueError):
                pass
    except Exception as e:
        logger.debug("_db_logged_cycle_end_ids bot_id=%s: %s", bot_id, e)
    logged.discard(0)
    return logged


def _db_logged_cycle_start_ids(db: Session, bot_id: int) -> set:
    """Persisted CYCLE_START cycle_ids — incremental poll sentetik tekrarını önler."""
    logged: set = set()
    try:
        rows = db.execute(
            text("""
                SELECT meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND event_type = 'CYCLE_START' AND id > 0
            """),
            {"bid": bot_id},
        ).fetchall()
        for row in rows:
            if not row or not row[0]:
                continue
            try:
                meta = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            except Exception:
                meta = {}
            try:
                logged.add(int(meta.get("cycle_id") or 0))
            except (TypeError, ValueError):
                pass
    except Exception as e:
        logger.debug("_db_logged_cycle_start_ids bot_id=%s: %s", bot_id, e)
    logged.discard(0)
    return logged


def _ts_plus_ms(ts: Optional[str], ms: int) -> Optional[str]:
    base = _parse_event_ts_ms(ts)
    if base <= 0:
        return normalize_event_ts_iso_z(ts) if ts else None
    dt = datetime.fromtimestamp((base + ms) / 1000.0, tz=timezone.utc)
    return normalize_event_ts_iso_z(dt.isoformat())


def _infer_base_before_first_grid_fill_in_tur(
    events: List[Dict[str, Any]],
    cycle_id: int,
    current_base: float,
) -> Optional[float]:
    """Aktif turda ilk grid satışından önceki base (mevcut base + satılan qty)."""
    try:
        cur_b = float(current_base or 0)
    except (TypeError, ValueError):
        return None
    if cur_b <= 0:
        return None
    earliest_ms = 0
    earliest_qty = 0.0
    for ev in events or []:
        if (ev.get("type") or "") != "ORDER_FILLED":
            continue
        meta = ev.get("meta") or {}
        try:
            if int(meta.get("cycle_id") or 0) != int(cycle_id):
                continue
        except (TypeError, ValueError):
            continue
        if meta.get("grid_index") is None:
            continue
        if (meta.get("reason") or "").strip() != "trail_sell_grid":
            continue
        side = (meta.get("side") or "").upper()
        if side and side != "SELL":
            continue
        try:
            qty = float(meta.get("fill_qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            continue
        ms = _parse_event_ts_ms(ev.get("ts"))
        if earliest_ms == 0 or (ms > 0 and ms < earliest_ms):
            earliest_ms = ms
            earliest_qty = qty
    if earliest_qty <= 0:
        return None
    return round(cur_b + earliest_qty, 10)


def _find_cycle_close_fill(
    events: List[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    """Tur kapanış emri (kar satışı / re-entry) — sonraki tur açılış zamanı için."""
    found: Optional[Dict[str, Any]] = None
    for ev in events:
        if (ev.get("type") or "") != "ORDER_FILLED":
            continue
        meta = ev.get("meta") or {}
        if int(meta.get("cycle_id") or 0) != int(cycle_id):
            continue
        if (meta.get("reason") or "").strip() not in (
            "trail_profit_sell",
            "trail_reentry_buy",
        ):
            continue
        eid = int(ev.get("id") or 0)
        if found is None or eid > int(found.get("id") or 0):
            found = ev
    return found


def _find_cycle_end_event(
    events: List[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    found: Optional[Dict[str, Any]] = None
    for ev in events:
        if (ev.get("type") or "") != "CYCLE_END":
            continue
        if int((ev.get("meta") or {}).get("cycle_id") or 0) != int(cycle_id):
            continue
        eid = int(ev.get("id") or 0)
        if found is None or eid > int(found.get("id") or 0):
            found = ev
    return found


def _cycle_open_trade_row(
    state: Dict[str, Any], cycle_id: int
) -> Optional[Dict[str, Any]]:
    for row in reversed(state.get("cycle_open_trades") or []):
        if not isinstance(row, dict):
            continue
        if int(row.get("cycle_id") or 0) == int(cycle_id):
            return row
    return None


def _initial_capital_usdt_from_state(
    state: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
) -> float:
    try:
        cfg = state.get("config") if isinstance(state.get("config"), dict) else {}
        c = float(
            cfg.get("initial_capital_usdt")
            or cfg.get("budget_usd")
            or cfg.get("bot_budget_usdt")
            or state.get("initial_capital_usdt")
            or 0
        )
        if c > 0:
            return c
    except (TypeError, ValueError):
        pass
    for ev in events or []:
        if (ev.get("type") or "") != "INFO":
            continue
        msg = ev.get("message") or ""
        if "COMMAND_EXECUTED" not in msg or "START" not in msg:
            continue
        try:
            ic = float((ev.get("meta") or {}).get("initial_capital_usdt") or 0)
        except (TypeError, ValueError):
            ic = 0.0
        if ic > 0:
            return ic
    return 0.0


def _tur1_wallet_snapshot(
    state: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Tur 1 açılış: initial_allocation fill + başlangıç sermayesi (güncel state değil)."""
    fill_ev = _find_initial_allocation_fill(events)
    if not fill_ev:
        return None
    fm = fill_ev.get("meta") or {}
    try:
        fill_qty = float(fm.get("fill_qty") or state.get("initial_alloc_base_qty") or 0)
        fill_price = float(
            fm.get("fill_price") or state.get("initial_alloc_price") or 0
        )
        fee = float(fm.get("fee") or 0)
        cum_quote = float(fm.get("cum_quote") or 0)
    except (TypeError, ValueError):
        return None
    if fill_qty <= 0 or fill_price <= 0:
        return None
    if cum_quote <= 0:
        cum_quote = fill_qty * fill_price
    capital = _initial_capital_usdt_from_state(state, events)
    if capital <= 0:
        try:
            capital = float(state.get("cycle_start_equity") or 0)
        except (TypeError, ValueError):
            capital = 0.0
    if capital <= 0:
        capital = round(cum_quote + fee + fill_qty * fill_price, 2)
    quote_bal = round(max(0.0, capital - cum_quote - fee), 2)
    base_bal = round(fill_qty, 10)
    equity = round(quote_bal + base_bal * fill_price, 2)
    return {
        "base_balance": base_bal,
        "base_qty": base_bal,
        "quote_balance": quote_bal,
        "equity_usdt": equity,
        "reference_price": round(fill_price, 10),
        "symbol": fm.get("symbol") or state.get("symbol"),
    }


def _cycle_start_meta_stale_for_past_tur(
    state: Dict[str, Any],
    cycle_id: int,
    meta: Dict[str, Any],
) -> bool:
    """Meta güncel cüzdanla aynıysa (tur içi işlem sonrası) tur açılış snapshot değildir."""
    try:
        cur_q = round(float(state.get("quote_balance") or 0), 2)
        cur_b = round(float(state.get("base_balance") or 0), 10)
        meta_q = meta.get("quote_balance")
        meta_b = meta.get("base_balance") or meta.get("base_qty")
        if meta_q is None or meta_b is None:
            return False
        if round(float(meta_q), 2) == cur_q and round(float(meta_b), 10) == cur_b:
            return True
    except (TypeError, ValueError):
        pass
    row = _cycle_open_trade_row(state, int(cycle_id))
    if not row:
        return False
    try:
        rq = row.get("quote_balance")
        rb = row.get("qty")
        if rq is None or rb is None:
            return False
        meta_q = meta.get("quote_balance")
        meta_b = meta.get("base_balance") or meta.get("base_qty")
        if meta_q is None or meta_b is None:
            return False
        return round(float(meta_q), 2) != round(float(rq), 2) or round(
            float(meta_b), 10
        ) != round(float(rb), 10)
    except (TypeError, ValueError):
        return False


def _equity_looks_base_only_usd(
    equity: Any,
    base: Any,
    ref: Any,
) -> bool:
    """equity ≈ base×ref ise quote yok sayılır (yanlış equity_usdt heal)."""
    try:
        eq = float(equity)
        base_f = float(base)
        ref_f = float(ref)
    except (TypeError, ValueError):
        return False
    if base_f <= 0 or ref_f <= 0:
        return False
    base_usd = base_f * ref_f
    if base_usd <= 0:
        return False
    return abs(eq - base_usd) <= max(0.05, base_usd * 0.015)


def _sanitize_cycle_start_wallet(out: Dict[str, Any]) -> Dict[str, Any]:
    """Base-only equity ve türetilmiş quote=0 kalıntılarını temizle; tutarlı equity hesapla."""
    if not out:
        return out
    try:
        base_f = float(out.get("base_balance") or out.get("base_qty") or 0)
        ref_f = float(out.get("reference_price") or 0)
    except (TypeError, ValueError):
        return out
    eq_raw = out.get("equity_usdt")
    if eq_raw is None:
        eq_raw = out.get("equity_usd")
    quote_raw = out.get("quote_balance")
    if (
        eq_raw is not None
        and base_f > 0
        and ref_f > 0
        and _equity_looks_base_only_usd(eq_raw, base_f, ref_f)
    ):
        out.pop("equity_usdt", None)
        out.pop("equity_usd", None)
        try:
            if quote_raw is not None and float(quote_raw) < 0.01:
                out.pop("quote_balance", None)
        except (TypeError, ValueError):
            out.pop("quote_balance", None)
    try:
        quote_f = (
            float(out.get("quote_balance"))
            if out.get("quote_balance") is not None
            else None
        )
    except (TypeError, ValueError):
        quote_f = None
    if quote_f is not None and quote_f >= 0.01 and base_f > 0 and ref_f > 0:
        out["equity_usdt"] = round(quote_f + base_f * ref_f, 2)
    return out


def _snapshot_from_cycle_open_row(
    state: Dict[str, Any], cycle_id: int
) -> Dict[str, Any]:
    """Tur açılış anı — cycle_open_trades (tur içi fill ile değişmez)."""
    row = _cycle_open_trade_row(state, int(cycle_id))
    if not row:
        return {}
    out: Dict[str, Any] = {"symbol": row.get("symbol") or state.get("symbol")}
    try:
        base_f = float(row.get("qty") or 0)
    except (TypeError, ValueError):
        base_f = 0.0
    try:
        ref_f = float(row.get("reference_price") or row.get("price") or 0)
    except (TypeError, ValueError):
        ref_f = 0.0
    if base_f > 0:
        out["base_balance"] = round(base_f, 10)
        out["base_qty"] = out["base_balance"]
    if ref_f > 0:
        out["reference_price"] = round(ref_f, 10)
    for key in (
        "quote_balance",
        "equity_usdt",
        "target_quote_usdt",
        "target_base_usdt",
    ):
        if row.get(key) is not None:
            try:
                out[key] = round(float(row[key]), 2)
            except (TypeError, ValueError):
                pass
    if (
        out.get("equity_usdt") is None
        and out.get("quote_balance") is not None
        and base_f > 0
        and ref_f > 0
    ):
        out["equity_usdt"] = round(float(out["quote_balance"]) + base_f * ref_f, 2)
    elif (
        out.get("quote_balance") is None
        and out.get("equity_usdt") is not None
        and base_f > 0
        and ref_f > 0
        and not _equity_looks_base_only_usd(out["equity_usdt"], base_f, ref_f)
    ):
        out["quote_balance"] = round(float(out["equity_usdt"]) - base_f * ref_f, 2)
    return _sanitize_cycle_start_wallet(out)


def _snapshot_from_frozen_cycle_start_equity(
    state: Dict[str, Any],
    cycle_id: int,
    events: List[Dict[str, Any]],
    open_row_snap: Dict[str, Any],
) -> Dict[str, Any]:
    """Aktif tur: cycle_start_equity + açılış base/ref (canlı quote/base kullanılmaz)."""
    try:
        cur_cid = int(state.get("cycle_id") or 0)
        cid = int(cycle_id)
    except (TypeError, ValueError):
        return {}
    if cur_cid != cid:
        return {}
    try:
        cse = float(state.get("cycle_start_equity") or 0)
    except (TypeError, ValueError):
        cse = 0.0
    if cse <= 0:
        return {}
    db_ev = _find_cycle_start_event(events, cid)
    dm = (db_ev.get("meta") or {}) if db_ev else {}
    try:
        ref_f = float(
            open_row_snap.get("reference_price")
            or dm.get("reference_price")
            or state.get("reference_price")
            or 0
        )
    except (TypeError, ValueError):
        ref_f = 0.0
    try:
        live_base = float(state.get("base_balance") or 0)
    except (TypeError, ValueError):
        live_base = 0.0
    inferred_base = _infer_base_before_first_grid_fill_in_tur(events, cid, live_base)
    try:
        base_f = float(
            open_row_snap.get("base_balance")
            or open_row_snap.get("base_qty")
            or inferred_base
            or dm.get("base_qty")
            or dm.get("base_balance")
            or 0
        )
    except (TypeError, ValueError):
        base_f = 0.0
    if ref_f <= 0 or base_f <= 0:
        return {}
    quote_bal = round(cse - base_f * ref_f, 2)
    return {
        "base_balance": round(base_f, 10),
        "base_qty": round(base_f, 10),
        "quote_balance": max(0.0, quote_bal),
        "equity_usdt": round(cse, 2),
        "reference_price": round(ref_f, 10),
        "symbol": dm.get("symbol") or state.get("symbol"),
    }


def _cycle_start_wallet_snapshot(
    state: Dict[str, Any],
    cycle_id: int,
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Tur açılış cüzdanı — cycle_open_trades / CYCLE_START meta / frozen; asla canlı quote/base."""
    cid = int(cycle_id)
    merged_em = _merged_cycle_start_meta_from_events(events, cid)
    open_row_snap = _sanitize_cycle_start_wallet(
        _snapshot_from_cycle_open_row(state, cid)
    )
    db_ev = _find_cycle_start_event(events, cid)
    db_meta = (db_ev.get("meta") or {}) if db_ev else {}

    out: Dict[str, Any] = {}
    for src in (open_row_snap, merged_em, db_meta):
        if not isinstance(src, dict):
            continue
        for key, val in src.items():
            if val is not None and out.get(key) is None:
                out[key] = val

    if cid == 1:
        snap = _tur1_wallet_snapshot(state, events)
        if snap:
            for key, val in snap.items():
                if val is not None and out.get(key) is None:
                    out[key] = val

    frozen = _snapshot_from_frozen_cycle_start_equity(state, cid, events, open_row_snap)
    if frozen.get("quote_balance") is not None:
        for key, val in frozen.items():
            if val is not None:
                out[key] = val

    # CYCLE_START event meta (en zengin DB kaydı) quote/equity için öncelikli
    for key in (
        "quote_balance",
        "equity_usdt",
        "equity_usd",
        "base_balance",
        "base_qty",
        "reference_price",
        "symbol",
        "target_quote_usdt",
        "target_base_usdt",
    ):
        val = merged_em.get(key)
        if val is None:
            val = db_meta.get(key)
        if val is None:
            continue
        if key in ("quote_balance", "equity_usdt", "equity_usd"):
            out[key] = val
        elif out.get(key) is None:
            out[key] = val

    if out.get("equity_usdt") is None and out.get("equity_usd") is not None:
        out["equity_usdt"] = out.get("equity_usd")

    return _finalize_cycle_start_wallet(_sanitize_cycle_start_wallet(out))


def _apply_cycle_start_wallet_snapshot(
    meta: Dict[str, Any],
    snap: Dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    if not snap:
        return
    for key in (
        "base_balance",
        "base_qty",
        "quote_balance",
        "equity_usdt",
        "reference_price",
        "symbol",
        "target_quote_usdt",
        "target_base_usdt",
    ):
        val = snap.get(key)
        if val is None:
            continue
        if overwrite or meta.get(key) is None:
            meta[key] = val


def _build_synthetic_cycle_start(
    cycle_id: int,
    ts: str,
    state: Dict[str, Any],
    *,
    symbol: Optional[str],
    events: Optional[List[Dict[str, Any]]] = None,
    prev_close_reason: Optional[str] = None,
    reference_price: Optional[float] = None,
    base_qty: Optional[float] = None,
) -> Dict[str, Any]:
    cur_cid = int(state.get("cycle_id") or 0)
    row = _cycle_open_trade_row(state, cycle_id)
    if row:
        reference_price = (
            reference_price or row.get("reference_price") or row.get("price")
        )
        base_qty = base_qty or row.get("qty")
        if not ts:
            ts = normalize_event_ts_iso_z(row.get("ts") or state.get("cycle_opened_at"))
    if cur_cid == cycle_id:
        reference_price = reference_price or state.get("reference_price")
        if base_qty is None:
            base_qty = state.get("grid_reference_base")
    try:
        ref_f = float(reference_price) if reference_price is not None else 0.0
    except (TypeError, ValueError):
        ref_f = 0.0
    try:
        base_f = float(base_qty) if base_qty is not None else 0.0
    except (TypeError, ValueError):
        base_f = 0.0
    meta: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "reference_price": round(ref_f, 10) if ref_f > 0 else None,
        "base_qty": round(base_f, 10) if base_f > 0 else None,
        "symbol": symbol,
        "carry_over": True,
        "synthetic": True,
    }
    if prev_close_reason:
        meta["prev_close_reason"] = prev_close_reason
    snap = _cycle_start_wallet_snapshot(state, int(cycle_id), events or [])
    _apply_cycle_start_wallet_snapshot(meta, snap, overwrite=True)
    return {
        "id": _synthetic_cycle_start_event_id(cycle_id),
        "ts": normalize_event_ts_iso_z(ts),
        "type": "CYCLE_START",
        "message": "Tur başladı",
        "meta": meta,
    }


def _completed_dual_pnl_entry(
    state: Dict[str, Any], cycle_id: int
) -> Optional[Dict[str, Any]]:
    for row in state.get("completed_cycle_dual_pnls") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("cycle_id") or 0) == int(cycle_id):
            return row
    return None


def _find_cycle_start_event(
    events: List[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    found: Optional[Dict[str, Any]] = None
    best_score = -(10**9)
    for ev in events:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        if int((ev.get("meta") or {}).get("cycle_id") or 0) != int(cycle_id):
            continue
        score = _cycle_start_richness_score(ev)
        eid = int(ev.get("id") or 0)
        if (
            found is None
            or score > best_score
            or (score == best_score and eid > int(found.get("id") or 0))
        ):
            found = ev
            best_score = score
    return found


def _meta_from_cycle_pnl_entry(
    entry: Dict[str, Any], symbol: Optional[str]
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "cycle_id": int(entry.get("cycle_id") or 0),
        "symbol": symbol,
        "synthetic": True,
        "pnl_usdt_net": entry.get("pnl_usdt_net", entry.get("pnl_usdt")),
        "realized_pnl_cycle_net": entry.get("pnl_usdt_net", entry.get("pnl_usdt")),
        "fees_usdt": entry.get("fees_usdt"),
        "pnl_mode": entry.get("pnl_mode"),
        "pnl_primary_mode": entry.get("pnl_primary_mode"),
        "cycle_type": entry.get("cycle_type"),
        "close_reason": entry.get("close_reason"),
        "close_side": entry.get("close_side"),
        "matched_qty": entry.get("matched_qty"),
        "base_delta": entry.get("base_delta"),
        "inventory_coin_adv_qty": entry.get("inventory_coin_adv_qty"),
        "inventory_fees_usdt": entry.get("inventory_fees_usdt"),
        "cash_pnl_usdt": entry.get("cash_pnl_usdt"),
        "cash_fees_usdt": entry.get("cash_fees_usdt"),
    }
    if entry.get("cash_pnl_usdt") is not None:
        try:
            meta["profit_usdt"] = round(float(entry["cash_pnl_usdt"]), 2)
        except (TypeError, ValueError):
            pass
    return meta


def _meta_from_dual_pnl_entry(
    dual: Dict[str, Any], symbol: Optional[str]
) -> Dict[str, Any]:
    cycle_type = (dual.get("cycle_type") or "CASH").strip().upper()
    completed_reason = (dual.get("completed_reason") or "").strip()
    if not completed_reason:
        completed_reason = (
            "trail_profit_sell" if cycle_type == "CASH" else "trail_reentry_buy"
        )
    pnl_primary_mode = "INVENTORY" if cycle_type == "INVENTORY" else "CASH"
    meta: Dict[str, Any] = {
        "cycle_id": int(dual.get("cycle_id") or 0),
        "symbol": dual.get("symbol") or symbol,
        "synthetic": True,
        "cycle_type": cycle_type,
        "pnl_primary_mode": pnl_primary_mode,
        "close_reason": completed_reason,
        "close_side": "SELL" if completed_reason == "trail_profit_sell" else "BUY",
        "inventory_coin_adv_qty": dual.get("inventory_coin_adv_qty"),
        "inventory_fees_usdt": dual.get("inventory_fees_usdt"),
        "cash_pnl_usdt": dual.get("cash_pnl_usdt"),
        "cash_fees_usdt": dual.get("cash_fees_usdt"),
        "fees_usdt": dual.get("cash_fees_usdt"),
    }
    if dual.get("cash_pnl_usdt") is not None:
        try:
            gross = float(dual["cash_pnl_usdt"])
            meta["profit_usdt"] = round(gross, 2)
            fees = float(dual.get("cash_fees_usdt") or 0)
            meta["pnl_usdt_net"] = round(gross - fees, 4)
            meta["realized_pnl_cycle_net"] = meta["pnl_usdt_net"]
        except (TypeError, ValueError):
            pass
    return meta


def _cycle_has_closure_evidence(
    events: List[Dict[str, Any]],
    state: Dict[str, Any],
    cycle_id: int,
) -> bool:
    if _cycle_pnl_entry(state, cycle_id):
        return True
    if _completed_dual_pnl_entry(state, cycle_id):
        return True
    if _find_cycle_close_fill(events, cycle_id):
        return True
    if _find_cycle_start_event(events, cycle_id + 1):
        return True
    try:
        cur = int(state.get("cycle_id") or 0)
    except (TypeError, ValueError):
        cur = 0
    return cur > int(cycle_id)


def _build_synthetic_cycle_end(
    cycle_id: int,
    ts: str,
    state: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    symbol = state.get("symbol")
    entry = _cycle_pnl_entry(state, cycle_id)
    dual = _completed_dual_pnl_entry(state, cycle_id)
    if entry:
        meta = _meta_from_cycle_pnl_entry(entry, symbol)
    elif dual:
        meta = _meta_from_dual_pnl_entry(dual, symbol)
    else:
        close_fill = _find_cycle_close_fill(events, cycle_id)
        if not close_fill:
            return None
        fm = close_fill.get("meta") or {}
        meta = {
            "cycle_id": cycle_id,
            "symbol": symbol or fm.get("symbol"),
            "close_reason": (fm.get("reason") or "").strip(),
            "synthetic": True,
        }
    return {
        "id": _synthetic_cycle_end_event_id(cycle_id),
        "ts": normalize_event_ts_iso_z(ts),
        "type": "CYCLE_END",
        "message": "Tur bitti",
        "meta": meta,
    }


def _merge_synthetic_cycle_end_events(
    events: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    db: Optional[Session] = None,
    bot_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Backfill CYCLE_END when DB row missing (exception after fill, legacy bots)."""
    if not state:
        return events
    logged = _logged_cycle_end_ids(events)
    if db is not None and bot_id is not None:
        logged |= _db_logged_cycle_end_ids(db, bot_id)
    needed: set = set()

    for entry in state.get("cycle_pnls") or []:
        if not isinstance(entry, dict):
            continue
        try:
            c = int(entry.get("cycle_id") or 0)
        except (TypeError, ValueError):
            continue
        if c >= 1:
            needed.add(c)

    for dual in state.get("completed_cycle_dual_pnls") or []:
        if not isinstance(dual, dict):
            continue
        try:
            c = int(dual.get("cycle_id") or 0)
        except (TypeError, ValueError):
            continue
        if c >= 1:
            needed.add(c)

    for ev in events:
        ty = ev.get("type") or ""
        meta = ev.get("meta") or {}
        if ty == "ORDER_FILLED":
            reason = (meta.get("reason") or "").strip()
            if reason not in ("trail_profit_sell", "trail_reentry_buy"):
                continue
            try:
                c = int(meta.get("cycle_id") or 0)
            except (TypeError, ValueError):
                c = 0
            if c >= 1:
                needed.add(c)
        elif ty == "CYCLE_START":
            try:
                c = int(meta.get("cycle_id") or 0)
            except (TypeError, ValueError):
                c = 0
            if c >= 2:
                needed.add(c - 1)

    synthetic: List[Dict[str, Any]] = []
    for cid in sorted(needed):
        if cid < 1 or cid in logged:
            continue
        if _find_cycle_end_event(events, cid):
            continue
        if not _cycle_has_closure_evidence(events, state, cid):
            continue

        ts: Optional[str] = None
        close_fill = _find_cycle_close_fill(events, cid)
        if close_fill:
            ts = _ts_plus_ms(close_fill.get("ts"), 100)

        entry = _cycle_pnl_entry(state, cid)
        if entry and entry.get("ts"):
            ts = ts or _ts_plus_ms(normalize_event_ts_iso_z(entry.get("ts")), 100)

        dual = _completed_dual_pnl_entry(state, cid)
        if dual and dual.get("completed_at"):
            ts = ts or _ts_plus_ms(
                normalize_event_ts_iso_z(dual.get("completed_at")), 100
            )

        next_start = _find_cycle_start_event(events, cid + 1)
        if next_start and next_start.get("ts"):
            ts = ts or _ts_plus_ms(next_start.get("ts"), -100)

        if not ts:
            continue

        built = _build_synthetic_cycle_end(cid, ts, state, events)
        if built:
            synthetic.append(built)
            logged.add(cid)

    if not synthetic:
        return events
    return list(events) + synthetic


def _merge_synthetic_cycle_start_events(
    events: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    db: Optional[Session] = None,
    bot_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Backfill CYCLE_START when DB row missing (RUN_ACTION_EXCEPTION, legacy bots)."""
    if not state:
        return events
    logged = _logged_cycle_start_ids(events)
    if db is not None and bot_id is not None:
        logged |= _db_logged_cycle_start_ids(db, bot_id)
    symbol = state.get("symbol")
    needed: set = set()
    try:
        cur = int(state.get("cycle_id") or 0)
        if cur >= 2:
            needed.add(cur)
    except (TypeError, ValueError):
        pass
    for row in state.get("cycle_open_trades") or []:
        try:
            c = int(row.get("cycle_id") or 0)
            if c >= 2:
                needed.add(c)
        except (TypeError, ValueError):
            pass
    for ev in events:
        ty = ev.get("type") or ""
        meta = ev.get("meta") or {}
        if ty == "CYCLE_END":
            try:
                needed.add(int(meta.get("cycle_id") or 0) + 1)
            except (TypeError, ValueError):
                pass
        elif ty == "ORDER_FILLED":
            reason = (meta.get("reason") or "").strip()
            try:
                c = int(meta.get("cycle_id") or 0)
            except (TypeError, ValueError):
                c = 0
            if c >= 2:
                needed.add(c)
            if reason in ("trail_profit_sell", "trail_reentry_buy") and c >= 1:
                needed.add(c + 1)

    synthetic: List[Dict[str, Any]] = []
    for cid in sorted(needed):
        if cid < 2 or cid in logged:
            continue
        if any(
            (e.get("type") or "") == "CYCLE_START"
            and int((e.get("meta") or {}).get("cycle_id") or 0) == int(cid)
            and _cycle_start_is_complete(e.get("meta") or {})
            for e in events
        ):
            continue
        ts: Optional[str] = None
        prev_close_reason: Optional[str] = None
        ref_price: Optional[float] = None
        base_qty: Optional[float] = None

        end_ev = _find_cycle_end_event(events, cid - 1)
        if end_ev:
            ts = _ts_plus_ms(end_ev.get("ts"), 200)
            em = end_ev.get("meta") or {}
            prev_close_reason = em.get("close_reason")
        close_fill = _find_cycle_close_fill(events, cid - 1)
        if close_fill:
            if not ts:
                ts = _ts_plus_ms(close_fill.get("ts"), 200)
            fm = close_fill.get("meta") or {}
            prev_close_reason = prev_close_reason or fm.get("reason")
            try:
                ref_price = float(fm.get("fill_price") or 0) or None
            except (TypeError, ValueError):
                ref_price = None

        if not ts:
            earliest: Optional[Dict[str, Any]] = None
            for ev in events:
                if (ev.get("type") or "") != "ORDER_FILLED":
                    continue
                if int((ev.get("meta") or {}).get("cycle_id") or 0) != cid:
                    continue
                eid = int(ev.get("id") or 0)
                if earliest is None or (eid > 0 and eid < int(earliest.get("id") or 0)):
                    earliest = ev
            if earliest:
                ts = _ts_plus_ms(earliest.get("ts"), -200)
                try:
                    ref_price = (
                        float((earliest.get("meta") or {}).get("fill_price") or 0)
                        or ref_price
                    )
                except (TypeError, ValueError):
                    pass

        if not ts and int(state.get("cycle_id") or 0) == cid:
            ledger = state.get("cycle_ledger_current") or {}
            ts = normalize_event_ts_iso_z(
                (ledger.get("started_at") if isinstance(ledger, dict) else None)
                or state.get("cycle_opened_at")
                or state.get("last_tick_at")
            )

        open_row = _cycle_open_trade_row(state, cid)
        if open_row and open_row.get("ts"):
            ts = normalize_event_ts_iso_z(open_row.get("ts")) or ts

        if not ts:
            continue

        synthetic.append(
            _build_synthetic_cycle_start(
                cid,
                ts,
                state,
                symbol=symbol,
                events=events,
                prev_close_reason=prev_close_reason,
                reference_price=ref_price,
                base_qty=base_qty,
            )
        )
        logged.add(cid)

    if not synthetic:
        return _dedupe_cycle_start_events(events)
    merged = list(events) + synthetic
    return _dedupe_cycle_start_events(merged)


def _cycle_start_is_complete(meta: Dict[str, Any]) -> bool:
    return (
        meta.get("quote_balance") is not None
        or meta.get("equity_usdt") is not None
        or meta.get("equity_usd") is not None
    )


def _merged_cycle_start_meta_from_events(
    events: List[Dict[str, Any]],
    cycle_id: int,
) -> Dict[str, Any]:
    """Aynı tur için tüm CYCLE_START meta alanlarını birleştir (eksik Quote/Bakiye heal)."""
    candidates: List[Dict[str, Any]] = []
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        try:
            if int((ev.get("meta") or {}).get("cycle_id") or 0) != int(cycle_id):
                continue
        except (TypeError, ValueError):
            continue
        candidates.append(ev)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda e: (_cycle_start_richness_score(e), int(e.get("id") or 0)),
        reverse=True,
    )
    merged: Dict[str, Any] = {}
    for ev in candidates:
        meta = ev.get("meta") or {}
        for key in (
            "base_balance",
            "base_qty",
            "quote_balance",
            "equity_usdt",
            "equity_usd",
            "reference_price",
            "symbol",
            "target_quote_usdt",
            "target_base_usdt",
        ):
            if merged.get(key) is None and meta.get(key) is not None:
                merged[key] = meta[key]
    return merged


def _finalize_cycle_start_wallet(out: Dict[str, Any]) -> Dict[str, Any]:
    """Quote/Bakiye eksikse base+ref veya equity'den türet."""
    if not out:
        return out
    try:
        base_f = float(out.get("base_balance") or out.get("base_qty") or 0)
        ref_f = float(out.get("reference_price") or 0)
    except (TypeError, ValueError):
        return out
    if base_f <= 0 or ref_f <= 0:
        return out
    eq = out.get("equity_usdt")
    if eq is None:
        eq = out.get("equity_usd")
    quote = out.get("quote_balance")
    try:
        if eq is not None and quote is None:
            if not _equity_looks_base_only_usd(eq, base_f, ref_f):
                out["quote_balance"] = round(max(0.0, float(eq) - base_f * ref_f), 2)
        elif quote is not None and eq is None:
            out["equity_usdt"] = round(float(quote) + base_f * ref_f, 2)
    except (TypeError, ValueError):
        pass
    return _sanitize_cycle_start_wallet(out)


def _enrich_cycle_start_events_meta(
    events: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
) -> None:
    """CYCLE_START meta: tur açılış snapshot (geçmiş turda güncel cüzdan asla yazılmaz)."""
    if not state:
        return
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        meta = ev.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            ev["meta"] = meta
        try:
            cid = int(meta.get("cycle_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid < 1:
            continue
        snap = _cycle_start_wallet_snapshot(state, cid, events)
        is_first = bool(
            meta.get("first_tur")
            or (meta.get("reason") or "").strip() == "initial_allocation"
        )
        stale = _cycle_start_meta_stale_for_past_tur(state, cid, meta)
        overwrite = is_first or stale or bool(meta.get("synthetic"))
        if snap.get("quote_balance") is not None:
            _apply_cycle_start_wallet_snapshot(meta, snap, overwrite=True)
        elif overwrite or not _cycle_start_is_complete(meta):
            _apply_cycle_start_wallet_snapshot(meta, snap, overwrite=overwrite)
        _apply_cycle_start_wallet_snapshot(
            meta, _merged_cycle_start_meta_from_events(events, cid), overwrite=False
        )
        fin = _finalize_cycle_start_wallet(meta)
        for key, val in fin.items():
            if val is not None:
                meta[key] = val
        if meta.get("symbol") is None and state.get("symbol"):
            meta["symbol"] = state.get("symbol")


def _cycle_start_richness_score(ev: Dict[str, Any]) -> int:
    """Yüksek = UI'da tercih edilen satır (tam Quote/Bakiye, DB kaydı)."""
    meta = ev.get("meta") or {}
    score = 0
    if int(ev.get("id") or 0) > 0:
        score += 500
    if not meta.get("synthetic"):
        score += 200
    if _cycle_start_is_complete(meta):
        score += 150
    if meta.get("equity_usdt") is not None or meta.get("equity_usd") is not None:
        score += 100
    if meta.get("quote_balance") is not None:
        score += 50
    if meta.get("base_balance") is not None:
        score += 25
    if meta.get("base_qty") is not None:
        score += 10
    if not _cycle_start_is_complete(meta):
        score -= 1000
    if meta.get("synthetic") and not _cycle_start_is_complete(meta):
        score -= 400
    return score


def _dedupe_cycle_start_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aynı tur için birden fazla CYCLE_START → en zengin tek satır."""
    best: Dict[int, Dict[str, Any]] = {}
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        try:
            cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid < 1:
            continue
        prev = best.get(cid)
        if prev is None or _cycle_start_richness_score(
            ev
        ) > _cycle_start_richness_score(prev):
            best[cid] = ev
    if not best:
        return list(events or [])
    out: List[Dict[str, Any]] = []
    emitted: set = set()
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_START":
            out.append(ev)
            continue
        try:
            cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
        except (TypeError, ValueError):
            out.append(ev)
            continue
        if cid < 1:
            out.append(ev)
            continue
        if cid in emitted:
            continue
        out.append(best[cid])
        emitted.add(cid)
    return out


def _cycle_end_richness_score(ev: Dict[str, Any]) -> int:
    score = 0
    try:
        eid = int(ev.get("id") or 0)
    except (TypeError, ValueError):
        eid = 0
    if eid > 0:
        score += 1000 + eid
    elif eid < 0:
        score += 200 + abs(eid)
    meta = ev.get("meta") or {}
    if not meta.get("synthetic"):
        score += 300
    if (
        meta.get("pnl_usdt_net") is not None
        or meta.get("inventory_coin_adv_qty") is not None
    ):
        score += 120
    if (
        meta.get("realized_pnl_cycle_net") is not None
        or meta.get("fees_usdt") is not None
    ):
        score += 60
    return score


def _dedupe_cycle_end_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aynı tur için birden fazla CYCLE_END (DB + sentetik / çift yazım) → tek satır."""
    best: Dict[int, Dict[str, Any]] = {}
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_END":
            continue
        try:
            cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid < 1:
            continue
        prev = best.get(cid)
        if prev is None or _cycle_end_richness_score(ev) > _cycle_end_richness_score(
            prev
        ):
            best[cid] = ev
    if not best:
        return list(events or [])
    out: List[Dict[str, Any]] = []
    emitted: set = set()
    for ev in events or []:
        if (ev.get("type") or "") != "CYCLE_END":
            out.append(ev)
            continue
        try:
            cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
        except (TypeError, ValueError):
            out.append(ev)
            continue
        if cid < 1:
            out.append(ev)
            continue
        if cid in emitted:
            continue
        out.append(best[cid])
        emitted.add(cid)
    return out


def _has_tur1_cycle_start(events: List[Dict[str, Any]]) -> bool:
    for ev in events:
        if (ev.get("type") or "") != "CYCLE_START":
            continue
        try:
            if int((ev.get("meta") or {}).get("cycle_id") or 0) != 1:
                continue
        except (TypeError, ValueError):
            continue
        return True
    return False


def _find_initial_allocation_fill(
    events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    found: Optional[Dict[str, Any]] = None
    for ev in events:
        if (ev.get("type") or "") != "ORDER_FILLED":
            continue
        meta = ev.get("meta") or {}
        if (meta.get("reason") or "").strip() != "initial_allocation":
            continue
        fid = int(ev.get("id") or 0)
        if found is None or fid > int(found.get("id") or 0):
            found = ev
    return found


def _merge_synthetic_tur_after_initial_fill(
    events: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """İlk base alımından sonra Tur 1 açıldı satırı yoksa (eski botlar) UI için sentetik CYCLE_START."""
    if _has_tur1_cycle_start(events):
        return events
    fill_ev = _find_initial_allocation_fill(events)
    if not fill_ev:
        return events
    fm = fill_ev.get("meta") or {}
    synth_id = _synthetic_cycle_start_event_id(1)
    if any(int(e.get("id") or 0) == synth_id for e in events):
        return events
    cid = 1
    st = state or {}
    fill_price = float(
        fm.get("fill_price")
        or st.get("reference_price")
        or st.get("initial_alloc_price")
        or 0
    )
    fill_qty = float(
        fm.get("fill_qty")
        or st.get("initial_alloc_base_qty")
        or st.get("base_balance")
        or 0
    )
    fill_ts = fill_ev.get("ts")
    tur_ts = fill_ts
    try:
        base_ms = _parse_event_ts_ms(fill_ts)
        if base_ms > 0:
            tur_ts = datetime.fromtimestamp(
                (base_ms + 1000) / 1000.0, tz=timezone.utc
            ).isoformat()
    except Exception:
        pass
    snap = _tur1_wallet_snapshot(st, events) or {}
    synthetic = {
        "id": synth_id,
        "ts": normalize_event_ts_iso_z(tur_ts or fill_ts or st.get("last_tick_at")),
        "type": "CYCLE_START",
        "message": "Tur başladı",
        "meta": {
            "cycle_id": cid,
            "reason": "initial_allocation",
            "first_tur": True,
            "synthetic": True,
            "reference_price": snap.get("reference_price")
            or (round(fill_price, 10) if fill_price > 0 else None),
            "base_qty": snap.get("base_qty")
            or (round(fill_qty, 10) if fill_qty > 0 else None),
            "base_balance": snap.get("base_balance")
            or (round(fill_qty, 10) if fill_qty > 0 else None),
            "quote_balance": snap.get("quote_balance"),
            "equity_usdt": snap.get("equity_usdt"),
            "symbol": snap.get("symbol") or fm.get("symbol") or st.get("symbol"),
        },
    }
    merged = list(events) + [synthetic]
    return _sort_engine_events_desc(merged)


def _row_to_engine_event(row: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if row[4]:
        try:
            meta = json.loads(row[4])
        except Exception:
            meta = {}
    return {
        "id": row[0],
        "ts": normalize_event_ts_iso_z(row[1]),
        "type": row[2],
        "message": row[3] or "",
        "meta": meta,
    }


def _merge_anchor_events(
    events: List[Dict[str, Any]],
    anchors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not anchors:
        return events
    have = {int(e.get("id") or 0) for e in events if int(e.get("id") or 0) > 0}
    merged = list(events)
    for ev in anchors:
        eid = int(ev.get("id") or 0)
        if eid > 0 and eid not in have:
            merged.append(ev)
            have.add(eid)
    return merged


def _fetch_lifecycle_anchor_events(
    db: Session, bot_id: int, session_start_id: int = 0
) -> List[Dict[str, Any]]:
    """Bot başlangıç + tur satırları — limit penceresinin dışında kalsa da tabloda kalsın."""
    anchors: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(ev: Dict[str, Any], key: str) -> None:
        if key in seen:
            return
        eid = int(ev.get("id") or 0)
        if eid <= 0:
            return
        seen.add(key)
        anchors.append(ev)

    sid = int(session_start_id or 0)
    try:
        if sid > 0:
            start_rows = db.execute(
                text("""
                    SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                    WHERE bot_id = :bid AND id = :sid
                    LIMIT 1
                """),
                {"bid": bot_id, "sid": sid},
            ).fetchall()
            for row in start_rows:
                _add(_row_to_engine_event(row), "bot_start")
            fill_row = db.execute(
                text("""
                    SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                    WHERE bot_id = :bid AND id >= :sid AND event_type = 'ORDER_FILLED'
                      AND (message LIKE '%initial_allocation%' OR meta_json LIKE '%initial_allocation%')
                    ORDER BY id ASC LIMIT 1
                """),
                {"bid": bot_id, "sid": sid},
            ).fetchone()
            if fill_row:
                _add(_row_to_engine_event(fill_row), "initial_fill")
            cycle_rows = db.execute(
                text("""
                    SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                    WHERE bot_id = :bid AND id >= :sid
                      AND event_type IN ('CYCLE_START', 'CYCLE_END')
                    ORDER BY id ASC LIMIT 240
                """),
                {"bid": bot_id, "sid": sid},
            ).fetchall()
            for row in cycle_rows:
                ev = _row_to_engine_event(row)
                try:
                    cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
                except (TypeError, ValueError):
                    cid = 0
                if cid >= 1:
                    _add(ev, f"{ev.get('type') or 'EV'}:{cid}")
            return anchors

        start_rows = db.execute(
            text("""
                SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND event_type = 'INFO'
                  AND message LIKE '%COMMAND_EXECUTED%' AND message LIKE '%START%'
                ORDER BY id ASC LIMIT 8
            """),
            {"bid": bot_id},
        ).fetchall()
        for row in start_rows:
            ev = _row_to_engine_event(row)
            meta = ev.get("meta") or {}
            if meta.get("connectivity_resume") is True:
                continue
            _add(ev, "bot_start")
            break

        fill_row = db.execute(
            text("""
                SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND event_type = 'ORDER_FILLED'
                  AND (message LIKE '%initial_allocation%' OR meta_json LIKE '%initial_allocation%')
                ORDER BY id ASC LIMIT 1
            """),
            {"bid": bot_id},
        ).fetchone()
        if fill_row:
            _add(_row_to_engine_event(fill_row), "initial_fill")

        cycle_rows = db.execute(
            text("""
                SELECT id, ts, event_type, message, meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND event_type = 'CYCLE_START'
                ORDER BY id ASC LIMIT 120
            """),
            {"bid": bot_id},
        ).fetchall()
        for row in cycle_rows:
            ev = _row_to_engine_event(row)
            try:
                cid = int((ev.get("meta") or {}).get("cycle_id") or 0)
            except (TypeError, ValueError):
                cid = 0
            if cid == 1:
                _add(ev, "tur1_start")
                break
    except Exception as ex:
        logger.debug("lifecycle anchor events bot_id=%s: %s", bot_id, ex)
    return anchors


def _enrich_command_start_events(
    events: List[Dict[str, Any]],
    bot: Any,
    state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ensure COMMAND_EXECUTED START rows carry budget fields for UI Bakiye display."""
    state = state or {}
    try:
        raw_cfg = json.loads(getattr(bot, "config_json", None) or "{}")
    except Exception:
        raw_cfg = {}
    initial_capital = float(
        raw_cfg.get("initial_capital_usdt")
        or raw_cfg.get("budget_usd")
        or raw_cfg.get("bot_budget_usdt")
        or 0
    )
    for ev in events:
        if (ev.get("type") or "") != "INFO":
            continue
        msg = ev.get("message") or ""
        if "COMMAND_EXECUTED" not in msg or "START" not in msg:
            continue
        meta = dict(ev.get("meta") or {})
        if initial_capital > 0 and meta.get("initial_capital_usdt") is None:
            meta["initial_capital_usdt"] = round(initial_capital, 2)
        pre_alloc = (
            float(meta.get("base_balance") or 0) == 0
            and float(meta.get("quote_balance") or 0) == 0
            and float(meta.get("equity_usd") or 0) == 0
        )
        if pre_alloc:
            meta["initial_allocation_done"] = False
        elif meta.get("initial_allocation_done") is None:
            meta["initial_allocation_done"] = bool(state.get("initial_allocation_done"))
        if pre_alloc or not meta.get("initial_allocation_done"):
            try:
                from app.botengine.start_log_brief import (
                    merge_cold_start_brief_into_meta,
                )

                merge_cold_start_brief_into_meta(meta, raw_cfg)
            except Exception:
                pass
        if not pre_alloc and meta.get("cycle_start_equity") is None:
            cse = float(state.get("cycle_start_equity") or 0)
            if cse > 0:
                meta["cycle_start_equity"] = round(cse, 2)
        ev["meta"] = meta
    return events


@router.get("")
async def bots_list(
    request: Request,
    account_id: int = Query(..., description="Account scope"),
    fast: bool = Query(False, description="Skip expensive health diagnostics"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List bots for account. require_auth + get_account_or_403(account_id)."""
    rid = _request_id(request)
    get_account_or_403(current, account_id, db)
    rows = (
        db.query(Bot).filter(Bot.account_id == account_id).order_by(Bot.id.desc()).all()
    )
    from app.botengine.state_store import load_states_bulk, load_states_list_meta

    state_meta = load_states_list_meta(db, [r.id for r in rows])
    state_full: Dict[int, Dict[str, Any]] = {}
    account_failure = None
    account_wallet_alert = None
    if not fast:
        from app.botengine.health_watch import _account_wallet_stale_alert

        state_full = load_states_bulk(db, [r.id for r in rows])
        # Account-level connectivity bir kez çözülür; bot başına tekrar sorgulanmaz.
        try:
            from app.services.binance_connectivity import active_failure

            account_failure = active_failure(account_id)
        except Exception:
            account_failure = None
        account_wallet_alert = (
            None if account_failure else _account_wallet_stale_alert(db, account_id)
        )
    out = []
    for r in rows:
        raw = json.loads(r.config_json or "{}")
        meta = state_meta.get(r.id) or {}
        state = state_full.get(r.id) or {}
        health_alerts = []
        if not fast:
            from app.botengine.health_watch import (
                _expected_tick_interval_sec,
                _parse_last_tick_ts,
                evaluate_bot_health_lite,
            )

            health_alerts = evaluate_bot_health_lite(
                r,
                state,
                account_failure=account_failure,
                account_wallet_alert=account_wallet_alert,
            )
            last_tick_ts = _parse_last_tick_ts(state)
            if last_tick_ts is not None:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                tick_age = now_ts - last_tick_ts
                crit_thresh = max(300.0, _expected_tick_interval_sec(r) * 12.0)
                if tick_age < crit_thresh:
                    health_alerts = [
                        a
                        for a in health_alerts
                        if str((a or {}).get("code") or "").upper() != "LOOP_TASK_MISSING"
                    ]
        has_crit = any(
            (a.get("level") or "").lower() == "critical" for a in health_alerts
        )
        has_warn = any((a.get("level") or "").lower() == "warn" for a in health_alerts)
        health_level = (
            "both"
            if (has_crit and has_warn)
            else ("critical" if has_crit else ("warn" if has_warn else None))
        )
        ia_done = bool(meta.get("initial_allocation_done"))
        st = (r.status or "stopped").lower()
        display_status = st
        if st == "running" and not ia_done:
            display_status = "starting"
        out.append(
            {
                "bot_id": r.id,
                "bot_code": getattr(r, "bot_code", None) or str(r.id),
                "account_id": r.account_id,
                "symbol": r.symbol,
                "status": st,
                "display_status": display_status,
                "initial_allocation_done": ia_done,
                **(
                    {
                        "health_alert_level": health_level,
                        "health_alerts": health_alerts,
                    }
                    if not fast
                    else {}
                ),
                "config": raw,
                "last_tick_at": meta.get("last_tick_at"),
                "created_at": r.started_at.isoformat() + "Z"
                if getattr(r, "started_at", None)
                else None,
            }
        )
    return {"bots": out, "request_id": rid}


class BotCreateBody(BaseModel):
    account_id: int
    config_json: Optional[Any] = None


async def _ensure_binance_ready_for_bot_create(
    account_id: int, db: Session, rid: str
) -> None:
    """Live bot creation must fail fast when Binance signed account access is down."""
    from app.services.test_account import is_test_account

    if is_test_account(account_id, db):
        return
    from app.services.binance_connectivity import (
        note_binance_failure,
        note_binance_success,
        probe_account_binance,
    )

    ok, code, msg = await probe_account_binance(account_id, db)
    if ok:
        note_binance_success(account_id)
        return
    err_code = code or "BINANCE_UNREACHABLE"
    message = msg or "Binance bağlantısı doğrulanamadı."
    note_binance_failure(account_id, err_code, message, "bot_create", emit_async=False)
    status_code = 403 if err_code in {"API_UNAUTHORIZED", "ACCOUNT_KEYS_EMPTY", "ACCOUNT_KEYS_DECRYPT_FAIL", "ACCOUNT_KEYS_MISSING"} else 503
    raise HTTPException(
        status_code=status_code,
        detail=_detail_err(
            err_code,
            "Binance bağlantısı doğrulanmadan canlı bot oluşturulamaz: " + message,
            rid,
        ),
    )


def create_bot_engine_core(
    account_id: int, config_dict: Dict[str, Any], db: Session
) -> Dict[str, Any]:
    """Shared create logic. config_dict = UI payload. Returns bot_id, bot_code, account_id, symbol, status."""
    raw = normalize_max_buy_levels_payload(config_dict or {})
    cfg = config_from_ui_payload(raw)
    from app.botengine.symbols import normalize_bot_trading_symbol

    symbol = normalize_bot_trading_symbol(
        (raw.get("symbol") or cfg.symbol or "BTCUSDT").upper().strip()
    )
    if symbol != (raw.get("symbol") or "").upper().strip():
        raw["symbol"] = symbol
        cfg = config_from_ui_payload(raw)
    # Yeni botlar her zaman canlı modda oluşturulur.
    mode = "live" if not cfg.paper_mode else "paper"
    stored_cfg = cfg.to_dict()
    for key in (
        "config_source",
        "param_assistant_job_id",
        "param_assistant_decision",
        "param_assistant_confidence",
        "param_assistant",
        "regime_tag",
        "dynamic_preview_regime",
        "display_regime_label",
        "selected_template_key",
        "regime_engine",
    ):
        if key in (config_dict or {}):
            stored_cfg[key] = config_dict[key]
    config_json = json.dumps(stored_cfg, ensure_ascii=False)
    for _ in range(20):
        bot_code = str(random.randint(100_000, 999_999))
        if db.query(Bot).filter(Bot.bot_code == bot_code).first() is None:
            break
    else:
        bot_code = str(random.randint(100_000, 999_999)) + str(uuid.uuid4().hex)[:4]
    bot = Bot(
        account_id=account_id,
        symbol=symbol,
        mode=mode,
        config_json=config_json,
        status="stopped",
        bot_code=bot_code,
        max_buy_levels=cfg.max_buy_levels,
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    ensure_state_row(db, bot.id, bot.account_id, symbol)
    # P0-4: Parametre asistanının optimize ettiği config ile açılan DİNAMİK botta,
    # sizing referansını "param_assistant" olarak işaretle. Aksi halde dinamik mod
    # ilk turda manuel config'i referans dondurur ve asistanın bulduğu yapı kaybolur.
    try:
        cfg_source = str((config_dict or {}).get("config_source") or "").strip().lower()
        if cfg_source == "param_assistant" and bool(getattr(cfg, "dynamic_mode", False)):
            from app.botengine.dynamic import cycle_manager as _dyn_cm

            st = load_state(db, bot.id) or {}
            if _dyn_cm.set_reference(st, cfg.to_dict(), source="param_assistant"):
                _pa = (config_dict or {}).get("param_assistant") or {}
                st["_dynamic_reference_meta"] = {
                    "source": "param_assistant",
                    "job_id": (config_dict or {}).get("param_assistant_job_id")
                    or _pa.get("job_id"),
                    "decision": (config_dict or {}).get("param_assistant_decision")
                    or _pa.get("decision"),
                    "confidence": (config_dict or {}).get("param_assistant_confidence")
                    or _pa.get("confidence"),
                }
                save_state(db, bot.id, bot.account_id, st)
                db.commit()
    except Exception as _ref_err:
        logger.debug(
            "param_assistant reference wiring failed bot_id=%s: %s", bot.id, _ref_err
        )
    return {
        "bot_id": bot.id,
        "bot_code": bot.bot_code,
        "account_id": bot.account_id,
        "symbol": bot.symbol,
        "status": bot.status,
    }


@router.post("")
async def bots_create(
    request: Request,
    body: BotCreateBody,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Create bot. require_auth + get_account_or_403(account_id)."""
    rid = _request_id(request)
    get_account_or_403(current, body.account_id, db)
    raw = body.config_json or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=_detail_err(
                    "INVALID_CONFIG_JSON", "config_json geçerli JSON olmalı", rid
                ),
            )
    # Dynamic Mode prerequisite gate. Current policy keeps only max_buy_levels
    # as a structural prerequisite; daily loss / stop-loss / emergency brakes
    # are disabled behind flags.
    try:
        _probe = config_from_ui_payload(raw)
    except MaxBuyLevelsError:
        _probe = None  # surfaced consistently by create_bot_engine_core below
    if _probe is not None and bool(getattr(_probe, "dynamic_mode", False)):
        from app.botengine.dynamic import safety_gate as _dyn_gate

        _g = _dyn_gate.check_prerequisites(_probe.to_dict())
        if not _g.ok:
            raise HTTPException(
                status_code=400,
                detail=_detail_err(
                    "DYNAMIC_MODE_PREREQS_MISSING",
                    "Dynamic Mode açılabilmesi için zorunlu koruma katmanları eksik: "
                    + "; ".join(_g.violations),
                    rid,
                ),
            )
    await _ensure_binance_ready_for_bot_create(body.account_id, db, rid)
    _manual_regime, _manual_regime_label = _dynamic_preview_regime_from_config(raw)
    if not _manual_regime and not _manual_regime_label:
        try:
            raw = {
                **raw,
                **(
                    await _calculate_manual_regime_preview(
                        raw,
                        symbol=str(raw.get("symbol") or ""),
                    )
                ),
            }
        except Exception as preview_exc:
            # Rejim etiketi tanısaldır; geçici piyasa verisi sorunu güvenli bot
            # oluşturma işlemini engellememelidir. İlk detay isteği yeniden dener.
            logger.debug("bot create manual regime preview failed: %s", preview_exc)
    try:
        result = create_bot_engine_core(body.account_id, raw, db)
    except MaxBuyLevelsError as e:
        raise HTTPException(
            status_code=400, detail=_detail_err("MAX_BUY_LEVELS_INVALID", str(e), rid)
        )
    return {**result, "request_id": rid}


def _resolve_bot(bot_id: int, account_id: Optional[int], current: dict, db: Session):
    q = db.query(Bot).filter(Bot.id == bot_id)
    if account_id is not None:
        q = q.filter(Bot.account_id == account_id)
    bot = q.first()
    if not bot:
        return None
    get_account_or_403(current, bot.account_id, db)
    return bot


def _config_for_grid_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure config has sell_grids/buy_grids for grid_view (handles up/down.grids-only payloads)."""
    if raw.get("sell_grids") or raw.get("buy_grids"):
        return raw
    try:
        cfg = DcaGridTrailingConfig(raw)
        return cfg.to_dict()
    except Exception:
        return raw


# Fields the dynamic snapshot may override for grid-view display purposes.
_DYN_GRID_OVERLAY_FIELDS = (
    "base_alloc_pct",
    "quote_alloc_pct",
    "sell_grids",
    "buy_grids",
    "sell_trigger_trailing_pct",
    "buy_trigger_trailing_pct",
    "profit_exit_rise_pct",
    "profit_exit_drop_pct",
    "profit_reentry_drop_pct",
    "profit_reentry_rise_pct",
)


def _dynamic_regime_label(regime: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    label = str(fallback or "").strip() or None
    regime = str(regime or "").strip().upper() or None
    if label and regime and label.startswith(f"{regime} · "):
        label = label.split(" · ", 1)[1].strip() or label
    if regime:
        try:
            from app.services.dynamic_param_score.regime_display import (
                V6_REGIME_LABELS,
                LEGACY_REGIME_PLAIN,
            )

            label = (
                V6_REGIME_LABELS.get(regime)
                or LEGACY_REGIME_PLAIN.get(regime)
                or label
            )
        except Exception:
            pass
    return label


def _dynamic_regime_from_template(template: Any) -> Optional[str]:
    template = str(template or "").strip()
    if not template.startswith("DPLV6_"):
        return None
    parts = template.split("_")
    if len(parts) >= 2 and parts[1].startswith("R"):
        return parts[1].split("-", 1)[0].strip().upper() or None
    return None


def _dynamic_preview_regime_from_config(raw: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """First-cycle Dynamic Mode banner: recover the regime the bot was created with."""
    raw = raw or {}
    pa = raw.get("param_assistant") if isinstance(raw.get("param_assistant"), dict) else {}
    regime = (
        pa.get("regime_tag")
        or raw.get("regime_tag")
        or raw.get("dynamic_preview_regime")
    )
    label = (
        pa.get("display_regime_label")
        or pa.get("market_status_plain")
        or raw.get("display_regime_label")
        or raw.get("market_status_plain")
    )
    template = str(
        pa.get("template_key")
        or raw.get("selected_template_key")
        or raw.get("template_key")
        or ""
    )
    if not regime:
        regime = _dynamic_regime_from_template(template)
    regime = str(regime or "").strip().upper() or None
    label = str(label or "").strip() or None
    label = _dynamic_regime_label(regime, label)
    return regime, label


def _dynamic_nested_str(data: Any, *path: str) -> Optional[str]:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if cur is None:
        return None
    val = str(cur).strip()
    return val or None


def _dynamic_preview_regime_from_decision_row(row: Any) -> Tuple[Optional[str], Optional[str]]:
    """Recover a Dynamic Mode start regime from a persisted DPS decision row."""
    try:
        data = dict(row or {})
    except Exception:
        data = row or {}
    get = data.get if hasattr(data, "get") else lambda _k, _d=None: _d
    selected_profile = get("selected_profile_name")
    regime = str(get("regime_tag") or "").strip().upper() or _dynamic_regime_from_template(selected_profile)
    telemetry = {}
    raw_telemetry = get("telemetry_json")
    if raw_telemetry:
        try:
            parsed = json.loads(raw_telemetry)
            if isinstance(parsed, dict):
                telemetry = parsed
        except Exception:
            telemetry = {}
    label = (
        _dynamic_nested_str(telemetry, "v6_display", "display_regime_technical")
        or _dynamic_nested_str(telemetry, "scenario_alignment", "regime_label")
        or _dynamic_nested_str(telemetry, "param_pool", "selection_context", "scenario_identity", "name")
        or _dynamic_nested_str(telemetry, "market_signature", "scenario", "name")
        or _dynamic_nested_str(telemetry, "v6_display", "regime_label")
        or _dynamic_nested_str(telemetry, "scenario_alignment", "regime_headline")
    )
    return regime or None, _dynamic_regime_label(regime, label)


def _dynamic_started_at_ms(bot: Any) -> Optional[int]:
    started_at = getattr(bot, "started_at", None)
    if not started_at:
        return None
    try:
        if isinstance(started_at, str):
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        elif isinstance(started_at, datetime):
            dt = started_at
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _dynamic_preview_regime_from_recent_decision(
    db: Session, bot: Any
) -> Tuple[Optional[str], Optional[str]]:
    """Fallback for existing bots whose config lacks the PA regime metadata."""
    symbol = str(getattr(bot, "symbol", "") or "").strip().upper()
    if not symbol:
        return None, None
    try:
        started_ms = _dynamic_started_at_ms(bot)
        row = None
        if started_ms:
            row = db.execute(
                text(
                    """
                    SELECT regime_tag, selected_profile_name, telemetry_json
                    FROM dynamic_param_decisions
                    WHERE symbol = :symbol
                      AND run_source = 'param_assistant'
                      AND timestamp BETWEEN :min_ts AND :max_ts
                    ORDER BY
                      CASE WHEN timestamp <= :started_ts THEN 0 ELSE 1 END,
                      ABS(timestamp - :started_ts) ASC
                    LIMIT 1
                    """
                ),
                {
                    "symbol": symbol,
                    "started_ts": started_ms,
                    "min_ts": started_ms - 2 * 60 * 60 * 1000,
                    "max_ts": started_ms + 15 * 60 * 1000,
                },
            ).mappings().first()
        if row is None:
            row = db.execute(
                text(
                    """
                    SELECT regime_tag, selected_profile_name, telemetry_json
                    FROM dynamic_param_decisions
                    WHERE bot_id = :bot_id
                      AND symbol = :symbol
                      AND run_source = 'dynamic_round_start'
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """
                ),
                {"bot_id": getattr(bot, "id", None), "symbol": symbol},
            ).mappings().first()
        if row is None and not started_ms:
            row = db.execute(
                text(
                    """
                    SELECT regime_tag, selected_profile_name, telemetry_json
                    FROM dynamic_param_decisions
                    WHERE symbol = :symbol
                      AND run_source = 'param_assistant'
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """
                ),
                {"symbol": symbol},
            ).mappings().first()
        return _dynamic_preview_regime_from_decision_row(row) if row else (None, None)
    except Exception as e:
        logger.debug("dynamic preview decision fallback failed bot_id=%s: %s", getattr(bot, "id", None), e)
        return None, None


async def _calculate_manual_regime_preview(
    raw: Dict[str, Any],
    *,
    symbol: str,
) -> Dict[str, Any]:
    """Manuel parametreleri değiştirmeden V6 motoruyla yalnız ana rejimi hesapla."""
    normalized_symbol = str(symbol or raw.get("symbol") or "").strip().upper()
    if not normalized_symbol or normalized_symbol == "MULTI":
        return {}
    from app.services.dynamic_param_score import get_engine
    from app.services.dynamic_param_score.consumer_policy import (
        build_param_assistant_context,
    )
    from app.services.dynamic_param_score.data_collector import (
        collect_market_data,
        default_exchange_constraints,
        portfolio_from_user_scenario,
    )

    cfg = _config_for_grid_view(raw or {})
    budget = float(
        cfg.get("initial_capital_usdt")
        or cfg.get("budget_usd")
        or cfg.get("bot_budget_usdt")
        or 0
    )
    if budget <= 0:
        return {}
    base_pct = float(cfg.get("base_alloc_pct") or 0)
    quote_pct = float(cfg.get("quote_alloc_pct") or max(0.0, 100.0 - base_pct))
    market = await asyncio.wait_for(
        collect_market_data(normalized_symbol),
        timeout=20,
    )
    portfolio = portfolio_from_user_scenario(
        quote_budget_usdt=budget,
        price=float(market.ticker_price or 0),
        base_balance_usdt=budget * base_pct / 100.0,
        quote_balance_usdt=budget * quote_pct / 100.0,
        base_alloc_frac=base_pct / 100.0,
    )
    constraints = default_exchange_constraints(normalized_symbol)
    context = build_param_assistant_context(
        budget_usdt=budget,
        portfolio=portfolio,
        allow_live=True,
        allow_no_trade=True,
    )
    loop = asyncio.get_running_loop()
    decision = await loop.run_in_executor(
        None,
        lambda: get_engine().calculate_decision(
            symbol=normalized_symbol,
            market_data=market,
            portfolio_state=portfolio,
            exchange_constraints=constraints,
            bot_context=context,
        ),
    )
    regime, label = _dynamic_preview_regime_from_decision_row(
        {
            "regime_tag": decision.regime_tag,
            "selected_profile_name": decision.selected_profile_name,
            "telemetry_json": json.dumps(decision.telemetry or {}, ensure_ascii=False),
        }
    )
    if not regime and not label:
        return {}
    return {
        "regime_tag": regime,
        "dynamic_preview_regime": regime,
        "display_regime_label": label or _dynamic_regime_label(regime),
        "selected_template_key": decision.selected_profile_name,
        "regime_engine": "dynamic_param_score_v6",
    }


def _effective_grid_config(
    raw: Dict[str, Any], state: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Config dict for grid_view. When Dynamic Mode is active and a snapshot exists,
    overlay the snapshot's APPLIED values so the UI shows the SAME numbers the bot
    actually ran on this cycle (grid %s, trailing, profit triggers). Otherwise
    returns the manual config unchanged (manual mode behaviour is byte-identical).
    """
    cfg = _config_for_grid_view(raw)
    try:
        from app.botengine.dynamic import cycle_manager as _dyn_cm
        from app.utils.parse_utils import parse_bool

        if not parse_bool((raw or {}).get("dynamic_mode")):
            return cfg
        if not _dyn_cm.dynamic_overlay_allowed(state or {}):
            return cfg
        snap = (state or {}).get("dynamic_snapshot") or {}
        try:
            if int(snap.get("cycle_id") or 0) != int((state or {}).get("cycle_id") or 1):
                return cfg
        except (TypeError, ValueError):
            return cfg
        applied = snap.get("applied") or {}
        if not applied:
            return cfg
        merged = dict(cfg)
        for k in _DYN_GRID_OVERLAY_FIELDS:
            if applied.get(k) is not None:
                merged[k] = applied[k]
        merged["_dynamic_applied"] = True
        merged["_dynamic_regime"] = snap.get("regime")
        return merged
    except Exception:
        return cfg


@router.get("/{bot_id}")
async def bots_detail(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bot detail + state + grid_points/profit_points for UI. require_auth + get_account_or_403(bot.account_id)."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    state = load_state(db, bot.id)
    _heal_cycle_opened_at_state(db, bot, state)
    raw = json.loads(bot.config_json or "{}")
    sym = (bot.symbol or "").strip().upper()
    _stored_regime, _stored_regime_label = _dynamic_preview_regime_from_config(raw)
    if not _stored_regime and not _stored_regime_label:
        _stored_regime, _stored_regime_label = (
            _dynamic_preview_regime_from_recent_decision(db, bot)
        )
        preview_patch: Dict[str, Any] = {}
        if _stored_regime or _stored_regime_label:
            preview_patch = {
                "regime_tag": _stored_regime,
                "dynamic_preview_regime": _stored_regime,
                "display_regime_label": _stored_regime_label,
                "regime_engine": "dynamic_param_score_v6",
            }
        else:
            try:
                preview_patch = await _calculate_manual_regime_preview(
                    raw,
                    symbol=sym,
                )
            except Exception as preview_exc:
                logger.debug(
                    "manual regime preview failed bot_id=%s: %s",
                    bot.id,
                    preview_exc,
                )
        if preview_patch:
            raw = {**raw, **preview_patch}
            try:
                bot.config_json = json.dumps(raw, ensure_ascii=False)
                db.commit()
            except Exception as persist_exc:
                db.rollback()
                logger.debug(
                    "manual regime preview persist failed bot_id=%s: %s",
                    bot.id,
                    persist_exc,
                )

    # Resolve freshness before PnL so a stale cache/last trade cannot become
    # current_price and corrupt equity/performance.
    price_meta = _bot_price_meta(sym)
    from app.services.bot_equity import display_safe_bot_price

    live_price = float(display_safe_bot_price(price_meta.get("price"), state) or 0)

    # PnL + live price for UI (current_price, current_usd, daily_pnl_*, price_24h)
    pnl_data: Dict[str, Any] = {}
    try:
        pnl_data = PnlService.calculate_bot_pnl(
            db,
            bot.id,
            bot.account_id,
            current_price=live_price or None,
            price_is_stale=bool(price_meta.get("is_stale")),
        ) or {}
    except Exception as e:
        logger.debug("bots_detail pnl failed bot_id=%s: %s", bot.id, e)
    if pnl_data.get("error"):
        pnl_data = {}
    if _repair_bot_state_reference_if_needed(db, bot, state, raw, live_price):
        live_price = float(
            display_safe_bot_price(_bot_price_meta(sym).get("price"), state) or 0
        )

    # 24h ticker: paralel başlat, MULTI/TRDCA işlemleriyle birlikte çalışsın
    price_24h_change_pct = None

    async def _fetch_24h_ticker():
        out = {}
        if not sym or sym == "MULTI":
            return out
        try:
            from app.services.data_hub import data_hub
            from app.services.market_data import get_ticker_24h

            data_hub.pin_symbols([sym])
            t = get_ticker_24h(sym)
            pct = t.get("priceChangePercent")
            if pct is not None:
                out["pct"] = round(float(pct), 2)
            last_p = t.get("lastPrice")
            if (
                not t.get("is_stale")
                and last_p is not None
                and float(last_p) > 0
            ):
                out["price"] = float(last_p)
        except Exception as e:
            logger.debug("bots_detail 24h ticker failed symbol=%s: %s", sym, e)
        return out

    t24 = asyncio.create_task(_fetch_24h_ticker()) if sym else None

    price = float((state or {}).get("reference_price") or 0)
    if price <= 0 and live_price > 0:
        price = live_price
    if live_price <= 0 and price > 0:
        live_price = price
    current_usd = float(pnl_data.get("total_usd") or 0)
    daily_usd = float(pnl_data.get("daily") or 0)
    daily_pnl_pct = pnl_data.get("daily_pnl_pct")
    if daily_pnl_pct is None:
        daily_pnl_pct = (
            (daily_usd / current_usd * 100.0)
            if current_usd and current_usd > 0
            else 0.0
        )
    else:
        daily_pnl_pct = float(daily_pnl_pct)

    config_for_grid = _effective_grid_config(raw, state)
    grid_points: List[Dict[str, Any]] = []
    profit_points: List[Dict[str, Any]] = []
    reference_display: Optional[float] = None
    grid_meta: Optional[Dict[str, Any]] = None
    _strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_trdca = _strategy_id == "trdca_pro"
    if not is_trdca:
        view_price = live_price if live_price > 0 else price
        try:
            grid_points, profit_points, meta = compute_grid_profit_view(
                state or {}, config_for_grid, view_price
            )
            reference_display = meta.get("ref_display")
            grid_meta = meta
        except Exception as e:
            logger.warning("bots_detail grid_view failed bot_id=%s: %s", bot.id, e)

    # MULTI/TRDCA: canlı base_value_usd (coinlerin USD toplamı) ve quote_balance (USDT)
    base_value_usd: Optional[float] = None
    quote_balance_usd: Optional[float] = None
    rebalancing_details: List[Dict[str, Any]] = []
    trdca_prices_cache: Optional[Dict[str, float]] = None  # parite için fiyat cache
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    initial_capital = float(
        raw.get("initial_capital_usdt")
        or raw.get("budget_usd")
        or raw.get("bot_budget_quote")
        or 0
    )
    is_test = False
    try:
        from app.services.test_account import is_test_account

        is_test = is_test_account(bot.account_id, db)
    except Exception:
        pass
    if sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance"):
        adapter = None
        quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()
        assets = set()
        trb = raw.get("trb") or {}
        for k in (trb.get("target_weights_all") or {}).keys():
            if k and str(k).upper() != quote_asset:
                assets.add(str(k).strip().upper())
        dca = raw.get("dca") or {}
        for k in (dca.get("coin_weights") or {}).keys():
            if k and str(k).upper() != quote_asset:
                assets.add(str(k).strip().upper())
        if raw.get("assets"):
            for a in raw["assets"]:
                s = (
                    (a.get("symbol") or "")
                    .upper()
                    .replace("USDT", "")
                    .replace("FDUSD", "")
                    .strip()
                )
                if s and s != quote_asset:
                    assets.add(s)
        assets.add(quote_asset)
        # Test hesabı + state'te virtual_balances: paper modda allocation sonrası gerçek bakiyeyi göster
        vb = (state or {}).get("virtual_balances")
        if is_test and vb and isinstance(vb, dict):
            base_value_usd = 0.0
            prices = await _fetch_prices_parallel(list(assets), quote_asset)
            for a in assets:
                if a == quote_asset:
                    continue
                free = float(vb.get(a) or 0)
                p = prices.get(a)
                if free > 0 and p and p > 0:
                    base_value_usd += free * p
            quote_balance_usd = float(vb.get(quote_asset) or 0)
            live_total = base_value_usd + quote_balance_usd
            if live_total > 0:
                current_usd = live_total
            # Eski state: vb'de 10k (test default) ve base 0 ise config'teki initial_capital kullan
            try:
                from app.services.test_account import TEST_PAPER_BALANCE_USDT

                if (
                    is_test
                    and initial_capital > 0
                    and base_value_usd == 0
                    and quote_balance_usd == TEST_PAPER_BALANCE_USDT
                ):
                    quote_balance_usd = initial_capital
                    live_total = initial_capital
                    current_usd = initial_capital
            except Exception:
                pass
        # Effective balances for this bot (worker uses initial_capital cap for live; API must match)
        effective_balances_map: Optional[Dict[str, float]] = None
        if base_value_usd is None or quote_balance_usd is None:
            try:
                from app.services.binance_assets import get_account_keys
                from app.botengine.adapters.binance_adapter import BinanceAdapter

                keys = None
                try:
                    keys = await get_account_keys(bot.account_id, db)
                except Exception:
                    pass
                if keys or is_test:
                    adapter = BinanceAdapter(bot.account_id, keys, paper_mode=is_test)
                    balances = await adapter.get_account_balances()
                    # Build balances_map once for USD calc and rebalancing (same source as worker)
                    effective_balances_map = {}
                    for a in assets:
                        b = balances.get(a) or {}
                        effective_balances_map[a] = float(b.get("free") or 0)
                    base_value_usd = 0.0
                    prices = await _fetch_prices_parallel(list(assets), quote_asset)
                    for a in assets:
                        if a == quote_asset:
                            continue
                        free = effective_balances_map.get(a) or 0
                        p = prices.get(a)
                        if p is None or float(p) <= 0:
                            p = adapter.get_price(f"{a}{quote_asset}")
                            p = float(p) if p and float(p) > 0 else 0.0
                        if free > 0 and p and float(p) > 0:
                            base_value_usd += free * float(p)
                    quote_free = float(effective_balances_map.get(quote_asset) or 0)
                    quote_balance_usd = quote_free
                    # Test hesabı: adapter 10k döner; config'teki initial_capital (örn. 5000) kullan
                    if is_test and initial_capital > 0:
                        quote_balance_usd = initial_capital
                        if effective_balances_map is not None:
                            effective_balances_map[quote_asset] = initial_capital
                    live_total = base_value_usd + quote_balance_usd
                    if live_total > 0:
                        current_usd = live_total
                    # Live (non-test) TRDCA/MULTI: worker caps effective portfolio to initial_capital; UI must match
                    if (
                        not is_test
                        and initial_capital > 0
                        and live_total > initial_capital
                        and effective_balances_map
                    ):
                        scale = initial_capital / live_total
                        for k in effective_balances_map:
                            effective_balances_map[k] = (
                                float(effective_balances_map.get(k) or 0) * scale
                            )
                        base_value_usd = base_value_usd * scale
                        quote_balance_usd = quote_balance_usd * scale
                        current_usd = initial_capital
            except Exception as e:
                logger.debug(
                    "bots_detail multi balances failed bot_id=%s: %s", bot.id, e
                )
        # Test hesabı + bakiye alınamadı: paper fallback (initial_capital ile başlangıç)
        if (
            is_test
            and initial_capital > 0
            and (base_value_usd is None or quote_balance_usd is None)
        ):
            base_value_usd = base_value_usd if base_value_usd is not None else 0.0
            quote_balance_usd = (
                quote_balance_usd if quote_balance_usd is not None else initial_capital
            )
            if current_usd <= 0:
                current_usd = initial_capital

        # Rebalancing detayları: her coin için miktar, referans %, anlık %, rebalancinge kalan %
        target_weights = (
            (raw.get("trb") or {}).get("target_weights_all")
            or (raw.get("dca") or {}).get("coin_weights")
            or {}
        )
        if not target_weights and raw.get("assets"):
            for a in raw["assets"]:
                asset_sym = (
                    (a.get("symbol") or "")
                    .upper()
                    .replace("USDT", "")
                    .replace("FDUSD", "")
                    .strip()
                )
                if asset_sym:
                    target_weights[asset_sym] = float(a.get("target_pct") or 0) / 100.0
        if target_weights and (
            sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance")
        ):
            balances_map = {}
            if effective_balances_map:
                balances_map = dict(effective_balances_map)
            elif vb and isinstance(vb, dict):
                balances_map = dict(vb)
                # Eski test default (10k) düzelt: rebalancing hesapları için initial_capital kullan
                try:
                    from app.services.test_account import TEST_PAPER_BALANCE_USDT

                    if (
                        is_test
                        and initial_capital > 0
                        and float(vb.get(quote_asset) or 0) == TEST_PAPER_BALANCE_USDT
                    ):
                        base_sum = sum(
                            float(vb.get(a) or 0) for a in assets if a != quote_asset
                        )
                        if base_sum == 0:
                            balances_map[quote_asset] = initial_capital
                except Exception:
                    pass
            elif adapter:
                try:
                    bal = await adapter.get_account_balances()
                    for a in assets:
                        b = bal.get(a) or {}
                        balances_map[a] = float(b.get("free") or 0)
                    # Live + initial_capital cap: scale to match worker
                    if not is_test and initial_capital > 0 and balances_map:
                        prices_tmp = await _fetch_prices_parallel(
                            list(assets), quote_asset
                        )
                        actual_total = 0.0
                        for a in assets:
                            qty = float(balances_map.get(a) or 0)
                            p = (
                                float(prices_tmp.get(a) or 0)
                                if a != quote_asset
                                else 1.0
                            )
                            if p <= 0 and adapter and a != quote_asset:
                                p = float(adapter.get_price(f"{a}{quote_asset}") or 0)
                            actual_total += qty * p
                        if actual_total > initial_capital:
                            scale = initial_capital / actual_total
                            for a in list(balances_map.keys()):
                                balances_map[a] = balances_map[a] * scale
                except Exception:
                    pass
            if not balances_map and is_test and initial_capital > 0:
                balances_map = {quote_asset: initial_capital}
            total_usd_val = float(current_usd or 0)
            if total_usd_val <= 0:
                total_usd_val = (base_value_usd or 0) + (quote_balance_usd or 0)
            # Rebalancing panel: base coinler + quote (USDT) satiri (parametrelerle base/quote tutarli)
            base_assets = sorted(
                a
                for a in target_weights.keys()
                if a and str(a).strip().upper() != quote_asset
            )
            if not base_assets:
                base_assets = sorted(a for a in assets if a != quote_asset)
            prices_map = await _fetch_prices_parallel(base_assets, quote_asset)
            for a in base_assets:
                qty = float(balances_map.get(a) or 0)
                target_pct = float(target_weights.get(a) or 0) * 100.0
                price = float(prices_map.get(a) or 0)
                if price <= 0 and adapter:
                    price = float(adapter.get_price(f"{a}{quote_asset}") or 0)
                value_usd = qty * price if price else 0
                current_pct = (
                    (value_usd / total_usd_val * 100.0) if total_usd_val > 0 else 0.0
                )
                gap_pct = target_pct - current_pct
                rebalancing_details.append(
                    {
                        "asset": a,
                        "qty": round(qty, 8),
                        "price": round(price, 6) if price else 0,
                        "value_usd": round(value_usd, 2),
                        "target_pct": round(target_pct, 2),
                        "current_pct": round(current_pct, 2),
                        "gap_pct": round(gap_pct, 2),
                    }
                )
            # Quote (USDT) satiri: Referans % = hedef agirliktan; Anlik % = portfoydeki quote orani (base/quote bolunmesi netlesir)
            quote_target_pct = float(target_weights.get(quote_asset) or 0) * 100.0
            quote_value = float(quote_balance_usd or 0)
            quote_current_pct = (
                (quote_value / total_usd_val * 100.0) if total_usd_val > 0 else 0.0
            )
            if quote_target_pct != 0 or quote_value > 0:
                rebalancing_details.append(
                    {
                        "asset": quote_asset,
                        "qty": round(float(balances_map.get(quote_asset) or 0), 8),
                        "price": 1.0,
                        "value_usd": round(quote_value, 2),
                        "target_pct": round(quote_target_pct, 2),
                        "current_pct": round(quote_current_pct, 2),
                        "gap_pct": round(quote_target_pct - quote_current_pct, 2),
                    }
                )

        # TRDCA: grid noktaları portföy değeri (basket) referans alınarak
        if is_trdca:
            coin_weights = (raw.get("dca") or {}).get("coin_weights") or {}
            basket_price = 0.0
            if coin_weights:
                try:
                    prices_map = await _fetch_prices_parallel(
                        list(coin_weights.keys()), quote_asset
                    )
                    trdca_prices_cache = prices_map
                    for asset, w in coin_weights.items():
                        if asset == quote_asset:
                            basket_price += float(w) * 1.0
                            continue
                        p = prices_map.get(asset) or 0
                        basket_price += float(w) * p
                except Exception as e:
                    logger.debug("bots_detail trdca basket failed: %s", e)
            if basket_price <= 0:
                basket_price = float(current_usd or 0)
            try:
                grid_points, profit_points, meta = compute_trdca_grid_view(
                    state or {}, raw, basket_price, float(current_usd or 0)
                )
                reference_display = meta.get("ref_display")
                grid_meta = meta
            except Exception as e:
                logger.warning("bots_detail trdca grid_view failed: %s", e)

    if t24:
        try:
            t24_result = await t24
            if t24_result.get("pct") is not None:
                price_24h_change_pct = t24_result["pct"]
            if t24_result.get("price") and float(t24_result["price"]) > 0:
                safe_ticker_price = display_safe_bot_price(
                    t24_result["price"],
                    state,
                )
                if safe_ticker_price is not None:
                    live_price = safe_ticker_price
                    try:
                        price_hub.update_price(bot.symbol or "", live_price)
                    except Exception:
                        pass
        except Exception:
            pass

    # A delete request can commit while the ticker/balance awaits above are in
    # flight. Re-resolve before touching an expired ORM row.
    bot = (
        db.query(Bot)
        .populate_existing()
        .filter(Bot.id == bot_id)
        .first()
    )
    if not bot:
        raise HTTPException(
            status_code=404,
            detail=_detail_err("NOT_FOUND", "Bot not found", rid),
        )

    # Tek sembol DCA: ilk yüklemede /live ile aynı değerleri döndür (state + anlık fiyat); bakiye/KZ birkaç saniye yanlış görünmesin
    if (
        state
        and live_price is not None
        and live_price > 0
        and sym
        and sym != "MULTI"
        and strategy_id not in ("trdca_pro", "multi_asset_rebalance")
    ):
        base_b = float(state.get("base_balance") or 0)
        quote_b = float(state.get("quote_balance") or 0)
        equity_from_state = base_b * live_price + quote_b
        current_usd = equity_from_state
        init_cap_detail = float(
            raw.get("initial_capital_usdt")
            or raw.get("budget_usd")
            or raw.get("bot_budget_quote")
            or 0
        )
        if state.get("initial_allocation_done"):
            daily_usd, daily_pnl_pct = ensure_daily_ref_and_compute(
                state,
                equity_from_state,
                init_cap_detail,
                _bot_run_started_at_dt(bot, state, db),
                db=db,
                bot_id=bot.id,
                account_id=bot.account_id,
                persist=True,
            )

    _ia_done = bool(state and state.get("initial_allocation_done"))
    _st = (bot.status or "stopped").lower()
    _display_status = (
        "starting"
        if _st == "running" and not _ia_done and (current_usd or 0) <= 0.01
        else _st
    )
    result = {
        "bot_id": bot.id,
        "bot_code": getattr(bot, "bot_code", None) or str(bot.id),
        "account_id": bot.account_id,
        "symbol": bot.symbol,
        "status": _st,
        "display_status": _display_status,
        "initial_allocation_done": _ia_done,
        "config": raw,
        "state": state,
        "grid_points": grid_points,
        "profit_points": profit_points,
        "reference_display": reference_display,
        "grid_meta": grid_meta,
        "current_price": live_price if live_price > 0 else None,
        "price_stale": bool(price_meta.get("is_stale")),
        "price_age_s": price_meta.get("age_s"),
        "price_source": price_meta.get("source"),
        "current_usd": round(current_usd, 2) if current_usd else None,
        "base_value_usd": round(base_value_usd, 2)
        if base_value_usd is not None
        else None,
        "quote_balance_usd": round(quote_balance_usd, 2)
        if quote_balance_usd is not None
        else None,
        "daily_pnl_usd": round(daily_usd, 2) if daily_usd is not None else None,
        "daily_pnl_pct": round(daily_pnl_pct, 2) if daily_pnl_pct is not None else None,
        "price_24h_change_pct": price_24h_change_pct,
        "started_at": _bot_run_started_at_for_api(bot, state, db),
        "request_id": rid,
        "rebalancing_details": rebalancing_details,
    }

    # TRDCA: performans grafiği için parite_pct (portföyün ağırlıklı ortalama % değişimi) ve bot_pct
    if strategy_id == "trdca_pro" and initial_capital > 0 and current_usd is not None:
        try:
            row = db.execute(
                text(
                    "SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"
                ),
                {"bid": bot.id},
            ).fetchone()
            payload = json.loads(row[0]) if row and row[0] else {}
            baseline = payload.get("baseline") or {}
            initial_prices = baseline.get("initial_prices")
            coin_weights = baseline.get("coin_weights")
            if initial_prices and coin_weights:
                cw_keys = [
                    k for k in coin_weights if k and str(k).upper() != quote_asset
                ]
                if trdca_prices_cache and all(k in trdca_prices_cache for k in cw_keys):
                    current_prices = trdca_prices_cache
                else:
                    current_prices = await _fetch_prices_parallel(cw_keys, quote_asset)
                parite_pct_val = compute_trdca_parite_pct(
                    initial_prices, coin_weights, current_prices, quote_asset
                )
                bot_pct_val = (
                    (float(current_usd) - initial_capital) / initial_capital * 100.0
                )
                result["parite_pct"] = (
                    round(parite_pct_val, 2) if parite_pct_val is not None else None
                )
                result["bot_pct"] = round(bot_pct_val, 2)
        except Exception:
            pass

    # Dual PNL (Cash vs Inventory) for Trailing DCA — perfPanel + tradesPanel
    if (
        state
        and sym
        and sym != "MULTI"
        and strategy_id not in ("trdca_pro", "multi_asset_rebalance")
    ):
        try:
            from app.botengine.cycle_ledger import resolve_cycle_opened_at

            ledger = state.get("cycle_ledger_current")
            current_price = (
                float(live_price or 0)
                if live_price
                else (float(pnl_data.get("current_price") or 0) if pnl_data else 0)
            )
            cash_pnl_cur = 0.0
            cash_fees_cur = 0.0
            inv_qty_cur = 0.0
            inv_fees_cur = 0.0
            fills_count = 0
            started_at = None
            if isinstance(ledger, dict) and ledger.get("symbol") == sym:
                cash_pnl_cur = float(
                    ledger.get("cash_fifo_pnl_usdt")
                    if ledger.get("cash_fifo_pnl_usdt") is not None
                    else ledger.get("cash_pnl_usdt") or 0
                )
                cash_fees_cur = float(
                    ledger.get("cash_fifo_fees_usdt")
                    if ledger.get("cash_fifo_fees_usdt") is not None
                    else ledger.get("cash_fees_usdt") or 0
                )
                inv_qty_cur = float(ledger.get("inventory_coin_adv_qty") or 0)
                inv_fees_cur = float(ledger.get("inventory_fees_usdt") or 0)
                fills_count = len(ledger.get("fills") or [])
                started_at = resolve_cycle_opened_at(state, ledger)

            completed = state.get("completed_cycle_dual_pnls") or []
            completed_sorted = sorted(
                completed, key=lambda x: int(x.get("cycle_id") or 0), reverse=True
            )

            cash_total = cash_pnl_cur + sum(
                float(c.get("cash_pnl_usdt") or 0) for c in completed
            )
            cash_fees_total = cash_fees_cur + sum(
                float(c.get("cash_fees_usdt") or 0) for c in completed
            )
            inv_qty_total = inv_qty_cur + sum(
                float(c.get("inventory_coin_adv_qty") or 0) for c in completed
            )
            inv_fees_total = inv_fees_cur + sum(
                float(c.get("inventory_fees_usdt") or 0) for c in completed
            )
            inv_usdt_equiv = (
                (inv_qty_total * current_price - inv_fees_total)
                if current_price > 0
                else (0.0 - inv_fees_total)
            )

            result["dual_pnl"] = {
                "current_price": round(current_price, 4) if current_price else None,
                "current_cycle": {
                    "cycle_id": int(state.get("cycle_id") or 1),
                    "cash_pnl_usdt": round(cash_pnl_cur, 4),
                    "cash_fees_usdt": round(cash_fees_cur, 4),
                    "inventory_coin_adv_qty": round(inv_qty_cur, 12),
                    "inventory_fees_usdt": round(inv_fees_cur, 4),
                    "fills_count": fills_count,
                    "started_at": started_at,
                },
                "completed_cycles": completed_sorted,
                "aggregates": {
                    "cash_pnl_usdt_total": round(cash_total, 4),
                    "cash_fees_usdt_total": round(cash_fees_total, 4),
                    "inventory_coin_adv_qty_total": round(inv_qty_total, 12),
                    "inventory_fees_usdt_total": round(inv_fees_total, 4),
                    "inventory_usdt_equiv_total": round(inv_usdt_equiv, 4),
                },
            }
        except Exception as e:
            logger.debug("bots_detail dual_pnl failed bot_id=%s: %s", bot.id, e)

    if (
        state
        and sym
        and sym != "MULTI"
        and strategy_id not in ("trdca_pro", "multi_asset_rebalance")
    ):
        try:
            snap = _build_live_snapshot_from_state(bot, state, db)
            if snap.get("stale"):
                result["stale"] = True
            if snap.get("equity_unavailable"):
                result["equity_unavailable"] = True
            lt_norm = snap.get("last_tick_at")
            if lt_norm is not None and isinstance(result.get("state"), dict):
                result["state"] = {**result["state"], "last_tick_at": lt_norm}
        except Exception as e:
            logger.debug("bots_detail live_snap merge failed bot_id=%s: %s", bot.id, e)

    # ---- Dynamic Mode snapshot (only present if dynamic_mode active) ----
    try:
        from app.botengine.dynamic import safety_gate as _dyn_gate
        from app.botengine.dynamic import cycle_manager as _dyn_cm
        from app.utils.parse_utils import parse_bool

        _gate_chk = _dyn_gate.check_prerequisites(raw or {})
        _dyn_first_cycle_manual = not _dyn_cm.dynamic_overlay_allowed(state or {})
        _dyn_gate_active = _dyn_gate.is_dynamic_mode_active(raw or {})
        _dyn_raw_snap = (state or {}).get("dynamic_snapshot")
        _cfg_preview_regime, _cfg_preview_regime_label = _dynamic_preview_regime_from_config(raw or {})
        _dyn_preview_regime = (
            _dyn_raw_snap.get("regime") if isinstance(_dyn_raw_snap, dict) else None
        ) or _cfg_preview_regime
        _dyn_preview_regime_label = _cfg_preview_regime_label
        if not _dyn_preview_regime:
            _decision_regime, _decision_regime_label = _dynamic_preview_regime_from_recent_decision(db, bot)
            _dyn_preview_regime = _decision_regime
            _dyn_preview_regime_label = _decision_regime_label
        elif not _dyn_preview_regime_label:
            _dyn_preview_regime_label = _dynamic_regime_label(_dyn_preview_regime)
        _dyn_snap = None if _dyn_first_cycle_manual else _dyn_raw_snap
        _dyn_emergency = (
            (state or {}).get("_dyn_emergency")
            if _dyn_gate.EMERGENCY_CHECKS_ENABLED and not _dyn_first_cycle_manual
            else None
        )
        _dyn_hold = (
            (state or {}).get("_dynamic_cycle_hold")
            if not _dyn_first_cycle_manual
            else None
        )
        _dyn_stance = (
            (_dyn_snap.get("stance") if isinstance(_dyn_snap, dict) else None)
        )
        # P0-4: sizing referans kaynağı (snapshot oluşmadan da görünür) —
        # "param_assistant" ise bot asistan önerisiyle açılmıştır.
        _dyn_ref = (state or {}).get("_dynamic_reference")
        _dyn_ref_meta = (state or {}).get("_dynamic_reference_meta")
        _dyn_reference = {
            "source": (
                _dyn_ref.get("_source") if isinstance(_dyn_ref, dict) else None
            )
            or "initial_config",
            "schema_version": (
                int(_dyn_ref.get("_schema_version") or 1)
                if isinstance(_dyn_ref, dict)
                else 1
            ),
            "grid_counts": {
                "buy": len(_dyn_ref.get("buy_grids") or [])
                if isinstance(_dyn_ref, dict)
                else 0,
                "sell": len(_dyn_ref.get("sell_grids") or [])
                if isinstance(_dyn_ref, dict)
                else 0,
            },
            "meta": _dyn_ref_meta if isinstance(_dyn_ref_meta, dict) else {},
        }
        result["dynamic_mode"] = {
            "enabled": (
                parse_bool((raw or {}).get("dynamic_mode"))
                or parse_bool((raw or {}).get("dynamic_mode_v2"))
            ),
            "active": (
                (
                    _dyn_gate_active
                    and not _dyn_first_cycle_manual
                )
                or (
                    parse_bool((raw or {}).get("dynamic_mode_v2"))
                    and isinstance(
                        (state or {}).get("dynamic_v2_snapshot"), dict
                    )
                )
            ),
            "first_cycle_manual": _dyn_first_cycle_manual,
            "safety_gate": {
                "ok": _gate_chk.ok,
                "violations": _gate_chk.violations,
                "injected_defaults": _gate_chk.injected_defaults,
            },
            "snapshot": _dyn_snap if isinstance(_dyn_snap, dict) else None,
            "preview_regime": _dyn_preview_regime,
            "preview_regime_label": _dyn_preview_regime_label,
            "stance": _dyn_stance if isinstance(_dyn_stance, dict) else None,
            "cycle_hold": _dyn_hold if isinstance(_dyn_hold, dict) and _dyn_hold.get("active") else None,
            "emergency": _dyn_emergency,
            "reference": _dyn_reference,
            "engine_version": (
                "V2"
                if parse_bool((raw or {}).get("dynamic_mode_v2"))
                else "LEGACY"
            ),
            "v2": (
                (state or {}).get("dynamic_v2_snapshot")
                if parse_bool((raw or {}).get("dynamic_mode_v2"))
                else None
            ),
        }
        if parse_bool((raw or {}).get("dynamic_mode_v2")):
            _v2_snapshot = (state or {}).get("dynamic_v2_snapshot")
            if isinstance(_v2_snapshot, dict):
                # Existing UI consumes snapshot.applied/baseline. Expose the V2
                # package through that stable contract while retaining v2 detail.
                result["dynamic_mode"]["snapshot"] = {
                    **_v2_snapshot,
                    "baseline": dict(raw or {}),
                }
    except Exception as e:
        logger.debug("bots_detail dynamic_mode block failed bot_id=%s: %s", bot.id, e)

    try:
        alpha_perf = resolve_session_alpha_performance(
            db,
            bot,
            state,
            pnl_data=pnl_data,
            live_price=live_price if live_price > 0 else None,
        )
        if alpha_perf:
            result["session_alpha_performance"] = alpha_perf
            result["bot_alpha_performance"] = alpha_perf
            result["real_performance_pct"] = alpha_perf.get("alpha_pct")
    except Exception as e:
        logger.debug("bots_detail alpha_perf failed bot_id=%s: %s", bot.id, e)

    return result


def _resolve_account_id(
    account_id: Optional[int], account_code: Optional[str], db: Session
) -> Optional[int]:
    """account_id yoksa account_code ile çöz. None dönerse account_id kullanılmaz (bot id ile bulunur)."""
    if account_id is not None:
        return account_id
    if account_code and str(account_code).strip():
        acc = (
            db.query(Account)
            .filter(Account.account_code == str(account_code).strip())
            .first()
        )
        if acc:
            return acc.id
    return None


def _merge_bot_cycle_ids(db: Session, bot_id: int, account_id: int) -> List[int]:
    """Tur numaraları: trades tablosu + bot state (açık/kapanmış turlar). En yeni önce."""
    from app.bot.ledger import Ledger

    ids: set[int] = set(Ledger.get_cycle_ids(db, bot_id, account_id))
    state = load_state(db, bot_id)
    if state:
        cur = int(state.get("cycle_id") or 0)
        if cur > 0:
            ids.add(cur)
        for entry in state.get("cycle_pnls") or []:
            cid = entry.get("cycle_id")
            if cid is not None:
                ids.add(int(cid))
        for entry in state.get("completed_cycle_dual_pnls") or []:
            cid = entry.get("cycle_id")
            if cid is not None:
                ids.add(int(cid))
    if not ids:
        return [1]
    return sorted(ids, reverse=True)


def _parse_ts_utc(ts: Any) -> Optional[datetime]:
    """Trade/ledger ts → UTC aware datetime (naive DB ts assumed UTC)."""
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


def _heal_cycle_opened_at_state(
    db: Session, bot: Any, state: Optional[Dict[str, Any]]
) -> None:
    """Eksik tur başlangıcını state, gerçekleşen işlem veya bot oturumundan onar."""
    if not state or not isinstance(state, dict):
        return
    from app.botengine.cycle_ledger import heal_cycle_opened_at, sync_ledger_started_at

    before = state.get("cycle_opened_at")
    heal_cycle_opened_at(state)
    if not state.get("cycle_opened_at") and state.get("initial_allocation_done"):
        cycle_id = int(state.get("cycle_id") or 1)
        first_trade = (
            db.query(Trade)
            .filter(
                Trade.bot_id == int(bot.id),
                Trade.account_id == int(bot.account_id),
                Trade.cycle_id == cycle_id,
            )
            .order_by(Trade.ts.asc(), Trade.id.asc())
            .first()
        )
        opened_at = _parse_ts_utc(first_trade.ts) if first_trade is not None else None
        if opened_at is None and cycle_id == 1:
            opened_at = _parse_ts_utc(
                state.get("bot_run_started_at")
                or _bot_run_started_at_for_api(bot, state, db)
                or getattr(bot, "started_at", None)
            )
        if opened_at is not None:
            state["cycle_opened_at"] = opened_at.isoformat()
    ledger = state.get("cycle_ledger_current")
    if isinstance(ledger, dict):
        sync_ledger_started_at(state, ledger)
    if before != state.get("cycle_opened_at"):
        try:
            from app.botengine.state_store import save_state

            save_state(db, bot.id, bot.account_id, state)
        except Exception as e:
            logger.debug("heal cycle_opened_at save failed bot_id=%s: %s", bot.id, e)


def _backfill_trades_from_ledger_fills(
    db: Session,
    bot: Any,
    fills: List[Dict[str, Any]],
    cycle_id: int,
    symbol: str,
) -> None:
    """Arşiv defterinde olup trades tablosunda eksik kalan işlemleri idempotent yazar (UI + raporlar)."""
    from app.bot.ledger import Ledger

    sym = (symbol or "").upper()
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        oid = f.get("order_id")
        if oid is None or not str(oid).strip():
            continue
        try:
            fee = float(
                f.get("fee_usdt")
                if f.get("fee_usdt") is not None
                else f.get("fee") or 0
            )
        except (TypeError, ValueError):
            fee = 0.0
        try:
            fee_raw = float(
                f.get("fee_raw")
                if f.get("fee_raw") is not None
                else f.get("fee_amount") or 0
            )
        except (TypeError, ValueError):
            fee_raw = 0.0
        try:
            Ledger.record_trade(
                db,
                bot.id,
                bot.account_id,
                (f.get("side") or "BUY").upper(),
                float(f.get("qty") or 0),
                float(f.get("price") or 0),
                fee=fee,
                fee_asset=(f.get("fee_asset") or "USDT"),
                fee_amount=fee_raw if fee_raw > 0 else None,
                fee_usdt=fee,
                slot_id=f.get("slot_id"),
                order_id=str(oid),
                client_order_id=f.get("client_order_id"),
                symbol=sym,
                cycle_id=int(cycle_id),
            )
        except Exception as e:
            logger.debug(
                "backfill trade from ledger bot_id=%s cycle_id=%s order_id=%s: %s",
                bot.id,
                cycle_id,
                oid,
                e,
            )


def _synthetic_trades_from_state(
    state: Dict[str, Any],
    symbol: str,
    cycle_id: int,
) -> List[Dict[str, Any]]:
    """Paper/test: DB boşken state history + grid fired → tur işlem listesi."""
    if not state or int(state.get("cycle_id") or 1) != int(cycle_id):
        return []
    sym = (symbol or "").upper()
    out: List[Dict[str, Any]] = []
    seq = 0

    def _append_hist(
        rows: List[Dict[str, Any]], side: str, default_reason: str
    ) -> None:
        nonlocal seq
        for h in rows or []:
            if not isinstance(h, dict):
                continue
            try:
                qty = float(h.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            reason = (
                str(h.get("reason") or default_reason or "").strip() or default_reason
            )
            gi = h.get("grid_index")
            slot = int(gi) if gi is not None and str(gi).strip() != "" else None
            out.append(
                {
                    "id": f"state_{cycle_id}_{seq}",
                    "ts": h.get("ts") or h.get("time"),
                    "side": side,
                    "qty": qty,
                    "price": h.get("price"),
                    "fee": h.get("fee") if h.get("fee") is not None else 0,
                    "symbol": sym,
                    "cycle_id": int(cycle_id),
                    "reason": reason,
                    "slot_id": slot,
                    "client_order_id": f"state_{side.lower()}_{cycle_id}_{seq}",
                    "synthetic_from_state": True,
                }
            )
            seq += 1

    _append_hist(state.get("sell_history") or [], "SELL", "trail_sell_grid")
    _append_hist(state.get("buy_history") or [], "BUY", "trail_buy_grid")

    hist_slots = {
        ((t.get("side") or "").upper(), int(t["slot_id"]))
        for t in out
        if t.get("slot_id") is not None
    }

    def _append_fired(fired: Any, fills: Any, side: str, reason: str) -> None:
        nonlocal seq
        if not isinstance(fired, list):
            return
        fill_list = fills if isinstance(fills, list) else []
        side_u = (side or "").upper()
        for i, flag in enumerate(fired):
            if not flag:
                continue
            if (side_u, i) in hist_slots:
                continue
            price = None
            if i < len(fill_list) and fill_list[i] is not None:
                try:
                    price = float(fill_list[i])
                except (TypeError, ValueError):
                    price = None
            if price is None or price <= 0:
                continue
            out.append(
                {
                    "id": f"gridfired_{cycle_id}_{seq}",
                    "ts": None,
                    "side": side,
                    "qty": None,
                    "price": price,
                    "fee": 0,
                    "symbol": sym,
                    "cycle_id": int(cycle_id),
                    "reason": reason,
                    "slot_id": i,
                    "client_order_id": f"gridfired_{side.lower()}_{cycle_id}_{i}",
                    "synthetic_from_state": True,
                    "grid_detail": {
                        "grid_index": i,
                        "grid_label": f"Grid #{i + 1}",
                        "display_label": f"{'Grid satış' if side == 'SELL' else 'Grid alım'} #{i + 1}",
                    },
                }
            )
            seq += 1

    _append_fired(
        state.get("sell_grid_fired"),
        state.get("sell_grid_fill_price"),
        "SELL",
        "trail_sell_grid",
    )
    _append_fired(
        state.get("buy_grid_fired"),
        state.get("buy_grid_fill_price"),
        "BUY",
        "trail_buy_grid",
    )
    return _merge_cycle_trades(out) if out else out


def _ledger_fills_to_trade_dicts(
    fills: List[Dict[str, Any]],
    symbol: str,
    cycle_id: int,
) -> List[Dict[str, Any]]:
    """cycle_ledger_current fills → trades API format (açık tur, henüz DB'ye yazılmamış işlemler)."""
    out: List[Dict[str, Any]] = []
    sym = (symbol or "").upper()
    for i, f in enumerate(fills or []):
        if not isinstance(f, dict):
            continue
        out.append(
            {
                "id": f"ledger_{cycle_id}_{i}",
                "ts": f.get("ts"),
                "side": f.get("side"),
                "qty": f.get("qty"),
                "price": f.get("price"),
                "fee": f.get("fee_usdt")
                if f.get("fee_usdt") is not None
                else f.get("fee"),
                "fee_raw": f.get("fee_raw"),
                "fee_usdt": f.get("fee_usdt")
                if f.get("fee_usdt") is not None
                else f.get("fee"),
                "fee_asset": f.get("fee_asset"),
                "order_id": f.get("order_id"),
                "client_order_id": f.get("client_order_id"),
                "symbol": sym,
                "cycle_id": cycle_id,
                "reason": f.get("reason"),
                "slot_id": f.get("slot_id"),
            }
        )
    return out


def _trade_fee_usdt(
    t: Dict[str, Any],
    symbol: str,
    config_raw: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Komisyon USDT karşılığı. Binance: alışta base coin, satışta USDT."""
    if t.get("fee_usdt") is not None:
        try:
            v = float(t["fee_usdt"])
            return v if v > 0 else None
        except (TypeError, ValueError):
            pass
    try:
        fee = float(t.get("fee") or 0)
    except (TypeError, ValueError):
        fee = 0.0
    if fee <= 0:
        fee = 0.0
    fee_asset = (t.get("fee_asset") or "USDT").strip().upper()
    try:
        price = float(t.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    from app.botengine.fee_utils import commission_to_usdt, symbol_base_asset

    symbol_base_asset(symbol)
    qty = float(t.get("qty") or 0) if t.get("qty") is not None else 0.0
    notional = qty * price if qty > 0 and price > 0 else 0.0
    if fee > 0:
        if fee_asset == "USDT":
            return fee
        if notional > 0 and fee <= notional * 0.02:
            return fee
        usdt = commission_to_usdt(fee, fee_asset, symbol, price)
        if usdt > 0:
            return usdt
    if qty > 0 and price > 0 and config_raw:
        side = (t.get("side") or "").upper()
        rate = float(
            config_raw.get("sell_fee_rate" if side == "SELL" else "buy_fee_rate")
            or config_raw.get("fee_rate")
            or 0.001
        )
        est = qty * price * rate
        return est if est > 0 else None
    return None


def _enrich_trades_fee(
    trades: List[Dict[str, Any]],
    symbol: str,
    config_raw: Optional[Dict[str, Any]] = None,
) -> None:
    """fee_usdt / fee_raw alanlarını trade dict'lerine ekle (UI komisyon satırı)."""
    from app.botengine.fee_utils import symbol_base_asset

    base = symbol_base_asset(symbol)
    for t in trades:
        if not isinstance(t, dict):
            continue
        fee_usdt = _trade_fee_usdt(t, symbol, config_raw)
        if fee_usdt is not None:
            t["fee_usdt"] = round(fee_usdt, 6)
        fee_asset = (t.get("fee_asset") or "USDT").strip().upper()
        try:
            px = float(t.get("price") or 0)
            qty = float(t.get("qty") or 0)
        except (TypeError, ValueError):
            px = qty = 0.0
        notional = qty * px if qty > 0 and px > 0 else 0.0
        if t.get("fee_raw") is None and fee_asset != "USDT":
            try:
                raw = float(t.get("fee") or 0)
            except (TypeError, ValueError):
                raw = 0.0
            if raw > 0 and (notional <= 0 or raw > notional * 0.02):
                t["fee_raw"] = raw
        elif t.get("fee_raw") is not None:
            try:
                t["fee_raw"] = float(t["fee_raw"])
            except (TypeError, ValueError):
                pass
        if (
            t.get("fee_raw") is None
            and fee_usdt
            and fee_asset != "USDT"
            and base
            and fee_asset == base
        ):
            try:
                px = float(t.get("price") or 0)
                if px > 0:
                    t["fee_raw"] = round(fee_usdt / px, 10)
            except (TypeError, ValueError):
                pass


def _trade_dedupe_key(t: Dict[str, Any]) -> str:
    oid = t.get("order_id")
    if oid:
        return f"oid:{oid}"
    cid = t.get("client_order_id")
    if cid:
        return f"cid:{cid}"
    tid = t.get("id")
    if tid is not None:
        return f"id:{tid}"
    return f"row:{t.get('ts')}:{t.get('side')}:{t.get('qty')}:{t.get('price')}"


def _trade_richness(t: Dict[str, Any]) -> int:
    """DB kaydı (slot_id, reference_price) ledger kopyasından zenginse onu tercih et."""
    score = 0
    if t.get("slot_id") is not None:
        score += 4
    if t.get("reason"):
        score += 2
    if t.get("reference_price") is not None:
        score += 2
    if t.get("order_id"):
        score += 1
    return score


def _merge_trade_dict(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Aynı işlemin iki temsilini birleştir; boş alanları doldur."""
    primary, secondary = (a, b) if _trade_richness(a) >= _trade_richness(b) else (b, a)
    out = dict(primary)
    for k, v in secondary.items():
        if v is not None and out.get(k) is None:
            out[k] = v
    return out


def _trade_alias_keys(t: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    oid = t.get("order_id")
    if oid is not None and str(oid).strip():
        keys.append(f"oid:{oid}")
    cid = t.get("client_order_id")
    if cid:
        keys.append(f"cid:{str(cid)}")
    side = (t.get("side") or "").upper()
    slot = t.get("slot_id")
    if side and slot is not None:
        try:
            keys.append(f"slot:{side}:{int(slot)}")
        except (TypeError, ValueError):
            pass
    qty, price = t.get("qty"), t.get("price")
    if side and qty is not None and price is not None:
        try:
            keys.append(f"row:{side}:{float(qty):.8f}:{float(price):.4f}")
        except (TypeError, ValueError):
            pass
    elif side and slot is not None and price is not None:
        try:
            keys.append(f"slotp:{side}:{int(slot)}:{float(price):.4f}")
        except (TypeError, ValueError):
            pass
    return keys


def _merge_cycle_trades(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Birleştir; aynı işlem (order_id / client_order_id / side+qty+price) tek satır."""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    alias_to_primary: Dict[str, str] = {}

    def _primary_for(t: Dict[str, Any]) -> str:
        for a in _trade_alias_keys(t):
            if a in alias_to_primary:
                return alias_to_primary[a]
        return _trade_dedupe_key(t)

    for group in groups:
        for t in group or []:
            if not isinstance(t, dict):
                continue
            pk = _primary_for(t)
            if pk in merged:
                merged[pk] = _merge_trade_dict(merged[pk], t)
            else:
                merged[pk] = t
                order.append(pk)
            for a in _trade_alias_keys(t):
                alias_to_primary[a] = pk
    out = [merged[k] for k in order]
    out.sort(key=lambda x: str(x.get("ts") or ""))
    return out


def _resolve_cycle_reference_price(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    trades: List[Dict[str, Any]],
) -> Optional[float]:
    """Tur referans fiyatı (grid/kar satışı gerçekleşme % için)."""
    ordered = sorted(trades or [], key=lambda x: str(x.get("ts") or ""))
    for t in ordered:
        try:
            rp = float(t.get("reference_price") or 0)
            if rp > 0:
                return rp
        except (TypeError, ValueError):
            pass
    if state:
        row = _cycle_open_trade_row(state, int(cycle_id))
        if row:
            try:
                rp = float(row.get("reference_price") or row.get("price") or 0)
                if rp > 0:
                    return rp
            except (TypeError, ValueError):
                pass
    for t in ordered:
        if (t.get("side") or "").upper() != "BUY":
            continue
        cid = (t.get("client_order_id") or "").lower()
        reason = (t.get("reason") or "").strip().lower()
        if cid.startswith("cycle_open_") or reason == "initial_allocation":
            try:
                p = float(t.get("price") or 0)
                if p > 0:
                    return p
            except (TypeError, ValueError):
                pass
    for t in ordered:
        if (t.get("side") or "").upper() == "BUY":
            try:
                p = float(t.get("price") or 0)
                if p > 0:
                    return p
            except (TypeError, ValueError):
                pass
    if state and int(state.get("cycle_id") or 0) == int(cycle_id):
        try:
            rp = float(state.get("reference_price") or 0)
            if rp > 0:
                return rp
        except (TypeError, ValueError):
            pass
    return None


def _enrich_trades_reference_prices(
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
) -> None:
    """Eksik reference_price → tur referansı (kar satışı / grid gerçekleşme %)."""
    ref = _resolve_cycle_reference_price(state, cycle_id, trades)
    if ref is None or ref <= 0:
        return
    ref_r = round(ref, 10)
    for t in trades or []:
        if t.get("reference_price") is None:
            t["reference_price"] = ref_r


def _sanitize_trades_for_bot_symbol(
    trades: List[Dict[str, Any]], symbol: str
) -> List[Dict[str, Any]]:
    sym = (symbol or "").strip().upper()
    if not sym or sym == "MULTI":
        return trades
    out: List[Dict[str, Any]] = []
    for t in trades or []:
        tsym = (t.get("symbol") or "").strip().upper()
        if tsym and tsym != sym:
            continue
        out.append(t)
    return out


def _derive_cycle_reference_from_sane_trades(
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    live_price: Optional[float] = None,
) -> Optional[float]:
    anchors: List[float] = []
    for t in sorted(trades or [], key=lambda x: str(x.get("ts") or "")):
        p = _float_or_none(t.get("price"))
        if p:
            anchors.append(p)
    if state:
        anchors.extend(_state_ledger_fill_prices(state, str(state.get("symbol") or ""), int(cycle_id)))
    if live_price and live_price > 0:
        anchors.append(float(live_price))
    anchors = [p for p in anchors if p and p > 0]
    if not anchors:
        return None
    return round(float(anchors[0]), 10)


def _repair_trade_reference_prices(
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    live_price: Optional[float] = None,
) -> None:
    candidate = _derive_cycle_reference_from_sane_trades(trades, state, cycle_id, live_price)
    if not candidate:
        return
    anchors = [candidate]
    if live_price and live_price > 0:
        anchors.append(float(live_price))
    for t in trades or []:
        rp = _float_or_none(t.get("reference_price"))
        if rp is None or _state_reference_looks_wrong(rp, anchors, live_price):
            t["reference_price"] = candidate


def _hydrate_trades_from_cycle_ledger(
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
) -> None:
    """Ledger fill alanlarını (reason, slot_id) DB satırlarına tamamla."""
    if not state or not trades:
        return
    cur_cid = int(state.get("cycle_id") or 1)
    fills: List[Dict[str, Any]] = []
    if cur_cid == int(cycle_id):
        ledger = state.get("cycle_ledger_current") or {}
        if isinstance(ledger, dict):
            fills.extend(ledger.get("fills") or [])
    for block in state.get("cycle_ledger_fills_archive") or []:
        if not isinstance(block, dict):
            continue
        if int(block.get("cycle_id") or 0) == int(cycle_id):
            fills.extend(block.get("fills") or [])
            break
    by_oid: Dict[str, Dict[str, Any]] = {}
    by_cid: Dict[str, Dict[str, Any]] = {}
    for f in fills:
        if not isinstance(f, dict):
            continue
        oid = f.get("order_id")
        if oid is not None and str(oid).strip():
            by_oid[str(oid)] = f
        cid = f.get("client_order_id")
        if cid:
            by_cid[str(cid)] = f
    for t in trades:
        f = None
        oid = t.get("order_id")
        if oid is not None and str(oid).strip():
            f = by_oid.get(str(oid))
        if f is None:
            cid = t.get("client_order_id")
            if cid:
                f = by_cid.get(str(cid))
        if not f:
            continue
        if not t.get("reason") and f.get("reason"):
            t["reason"] = f.get("reason")
        if t.get("slot_id") is None and f.get("slot_id") is not None:
            t["slot_id"] = f.get("slot_id")
        if t.get("reference_price") is None and f.get("reference_price") is not None:
            t["reference_price"] = f.get("reference_price")


def _cycle_pnl_entry(
    state: Optional[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    for row in state.get("cycle_pnls") or []:
        if isinstance(row, dict) and int(row.get("cycle_id") or 0) == int(cycle_id):
            return row
    return None


def _trade_has_grid_slot(t: Dict[str, Any]) -> bool:
    slot = t.get("slot_id")
    if slot is None:
        return False
    try:
        return int(slot) >= 0
    except (TypeError, ValueError):
        return False


def _tag_cycle_close_trades(
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
) -> None:
    """Tamamlanmış tur kapanış işlemini cycle_pnls ile eşleştir; reason alanını doldur."""
    if not state or not trades:
        return
    entry = _cycle_pnl_entry(state, cycle_id)
    if not entry:
        return
    close_reason = (entry.get("close_reason") or "").strip()
    if close_reason not in ("trail_profit_sell", "trail_reentry_buy"):
        return
    close_side = (
        entry.get("close_side")
        or ("SELL" if close_reason == "trail_profit_sell" else "BUY")
    ).upper()
    close_fill = (
        entry.get("close_fill") if isinstance(entry.get("close_fill"), dict) else {}
    )

    def _matches_close_fill(t: Dict[str, Any]) -> bool:
        if (t.get("side") or "").upper() != close_side:
            return False
        try:
            tq = float(t.get("qty") or 0)
            tp = float(t.get("price") or 0)
            cq = float(close_fill.get("qty") or 0)
            cp = float(close_fill.get("price") or 0)
        except (TypeError, ValueError):
            return False
        if cq <= 0 or cp <= 0:
            return False
        return abs(tq - cq) <= max(1e-6, cq * 1e-4) and abs(tp - cp) <= max(
            0.5, cp * 0.02
        )

    target: Optional[Dict[str, Any]] = None
    if close_fill:
        for t in trades:
            if _matches_close_fill(t):
                target = t
                break

    if target is None:
        side_trades = sorted(
            [t for t in trades if (t.get("side") or "").upper() == close_side],
            key=lambda x: str(x.get("ts") or ""),
        )
        non_grid = [t for t in side_trades if not _trade_has_grid_slot(t)]
        if non_grid:
            target = non_grid[-1]
        elif side_trades:
            target = side_trades[-1]

    if target is None:
        return
    if not target.get("reason"):
        target["reason"] = close_reason
    target["is_cycle_close"] = True


def _cycle_open_to_trade_dicts(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    symbol: str,
) -> List[Dict[str, Any]]:
    """Tur 2+ açılış base pozisyonu (önceki tur devri). Tur 1 initial_allocation DB kaydıyla gelir."""
    if not state or int(cycle_id) < 2:
        return []
    sym = (symbol or "").upper()
    out: List[Dict[str, Any]] = []
    row = _cycle_open_trade_row(state, int(cycle_id))
    if row:
        qty = float(row.get("qty") or 0)
        price = float(row.get("price") or 0)
        if qty > 0 and price > 0:
            cid = f"cycle_open_{cycle_id}"
            out.append(
                {
                    "id": cid,
                    "ts": row.get("ts"),
                    "side": (row.get("side") or "BUY").upper(),
                    "qty": qty,
                    "price": price,
                    "fee": float(row.get("fee") or 0),
                    "fee_asset": "USDT",
                    "client_order_id": cid,
                    "symbol": sym,
                    "cycle_id": int(cycle_id),
                    "reference_price": row.get("reference_price") or price,
                }
            )
    if out:
        return out
    if int(state.get("cycle_id") or 1) != int(cycle_id):
        return []
    base_bal = float(state.get("grid_reference_base") or state.get("base_balance") or 0)
    ref = float(state.get("reference_price") or 0)
    if base_bal <= 0 or ref <= 0:
        return []
    ledger = state.get("cycle_ledger_current") or {}
    ts = ledger.get("started_at") if isinstance(ledger, dict) else None
    completed = state.get("completed_cycle_dual_pnls") or []
    if not ts and completed:
        prev = [
            c for c in completed if int(c.get("cycle_id") or 0) == int(cycle_id) - 1
        ]
        if prev:
            ts = prev[-1].get("completed_at")
    cid = f"cycle_open_{cycle_id}"
    return [
        {
            "id": cid,
            "ts": ts,
            "side": "BUY",
            "qty": round(base_bal, 10),
            "price": round(ref, 10),
            "fee": 0.0,
            "fee_asset": "USDT",
            "client_order_id": cid,
            "symbol": sym,
            "cycle_id": int(cycle_id),
            "reference_price": round(ref, 10),
        }
    ]


def _build_live_snapshot_from_state(
    bot: Bot, state: Optional[Dict[str, Any]], db: Session
) -> dict:
    """Build the freshest single-bot snapshot; one-time repair may query the first trade."""
    _heal_cycle_opened_at_state(db, bot, state)
    status = (bot.status or "stopped").lower()
    raw = json.loads(bot.config_json or "{}")
    initial_capital = float(
        raw.get("initial_capital_usdt")
        or raw.get("budget_usd")
        or raw.get("bot_budget_quote")
        or 0
    )

    last_tick_at: Optional[int] = None
    last_error_code: Optional[str] = None
    if state:
        lt = state.get("last_tick_at")
        if lt is not None:
            if hasattr(lt, "timestamp"):
                last_tick_at = int(lt.timestamp())
            else:
                try:
                    last_tick_at = int(lt)
                except (TypeError, ValueError):
                    try:
                        s = str(lt).strip()
                        if s:
                            if "T" not in s and " " in s:
                                s = s.replace(" ", "T", 1)
                            if not (s.endswith("Z") or "+" in s[10:] or "-" in s[10:]):
                                s = s + "+00:00"
                            last_tick_at = int(
                                datetime.fromisoformat(
                                    s.replace("Z", "+00:00")
                                ).timestamp()
                            )
                    except Exception:
                        pass
        last_error_code = state.get("last_error_code")
        if isinstance(last_error_code, str):
            last_error_code = last_error_code.strip() or None
        else:
            last_error_code = None

    sym = (bot.symbol or "").strip().upper()
    price_meta = _bot_price_meta(sym)
    from app.services.bot_equity import display_safe_bot_price

    last_price = display_safe_bot_price(price_meta.get("price"), state)
    price_source = price_meta.get("source")

    equity: Optional[float] = 0.0
    equity_unavailable = False
    if state and last_price is not None and last_price > 0:
        base_b = float(state.get("base_balance") or 0)
        quote_b = float(state.get("quote_balance") or 0)
        equity = base_b * last_price + quote_b
    elif state:
        base_b = float(state.get("base_balance") or 0)
        quote_b = float(state.get("quote_balance") or 0)
        if base_b > 0 and last_price is None:
            equity_unavailable = True
            equity = 0.0
        else:
            equity = quote_b
    else:
        equity_unavailable = True

    pnl_pct: Optional[float] = None
    if initial_capital > 0 and equity is not None and not equity_unavailable:
        pnl_pct = (equity - initial_capital) / initial_capital * 100.0

    # Günlük K/Z: TR gece 00:00 equity referansı (state daily_ref_usd)
    daily_pnl_usd: Optional[float] = None
    daily_pnl_pct: Optional[float] = None
    daily_ref_usd: Optional[float] = None
    if (
        state
        and equity is not None
        and not equity_unavailable
        and state.get("initial_allocation_done")
    ):
        daily_pnl_usd, daily_pnl_pct = ensure_daily_ref_and_compute(
            state,
            equity,
            initial_capital,
            _bot_run_started_at_dt(bot, state, db),
            db=db,
            bot_id=bot.id,
            account_id=bot.account_id,
            persist=True,
        )
        _dr = state.get("daily_ref_usd")
        if _dr is not None and float(_dr) > 0:
            daily_ref_usd = float(_dr)

    stale = bool(price_meta.get("is_stale"))
    if last_tick_at is not None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if (now_ts - last_tick_at) > 30:
            stale = True

    base_balance = float(state.get("base_balance") or 0) if state else 0
    quote_balance = float(state.get("quote_balance") or 0) if state else 0
    cycle_id = int(state.get("cycle_id") or 1) if state else 1
    initial_allocation_done = (
        state.get("initial_allocation_done") is True if state else False
    )
    first_buy_pending = (
        status == "running" and not initial_allocation_done and base_balance <= 0
    )
    if first_buy_pending and pnl_pct is not None:
        pnl_pct = 0.0

    out: Dict[str, Any] = {
        "status": status,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "equity": round(equity, 2) if equity is not None else 0,
        "last_price": last_price,
        "last_tick_at": last_tick_at,
        "last_error_code": last_error_code,
        "price_source": price_source,
        "price_stale": bool(price_meta.get("is_stale")),
        "price_age_s": price_meta.get("age_s"),
        "initial_capital": initial_capital,
        "daily_pnl_usd": round(daily_pnl_usd, 2) if daily_pnl_usd is not None else None,
        "daily_pnl_pct": round(daily_pnl_pct, 2) if daily_pnl_pct is not None else None,
        "daily_ref_usd": round(daily_ref_usd, 2) if daily_ref_usd is not None else None,
        "base_balance": base_balance,
        "quote_balance": quote_balance,
        "cycle_id": cycle_id,
        "cycle_opened_at": (
            str(state.get("cycle_opened_at")).strip()
            if state
            and isinstance(state.get("cycle_opened_at"), str)
            and str(state.get("cycle_opened_at")).strip()
            else None
        ),
        "first_buy_pending": first_buy_pending,
        "initial_allocation_done": initial_allocation_done,
    }
    if stale:
        out["stale"] = True
    if equity_unavailable:
        out["equity_unavailable"] = True
    if (
        state
        and equity is not None
        and not equity_unavailable
        and not first_buy_pending
        and initial_allocation_done
        and (base_balance <= 0 or price_source in ("price_hub", "data_hub"))
    ):
        try:
            PnlService.save_snapshot_if_due(
                db,
                bot.id,
                bot.account_id,
                {
                    "total_usd": float(equity),
                    "realized": 0.0,
                    "unrealized": float(equity) - initial_capital
                    if initial_capital > 0
                    else 0.0,
                    "daily": daily_pnl_usd or 0.0,
                    "monthly": 0.0,
                },
            )
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.debug("live snapshot pnl persist skipped bot_id=%s: %s", bot.id, e)
    return out


@router.get("/{bot_id}/grid-points")
async def bots_grid_points(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lightweight grid/profit view for live tepe-dip updates. State + price only; no trades/PnL DB."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    state = load_state(db, bot.id) or {}
    raw = json.loads(bot.config_json or "{}")
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    sym = (bot.symbol or "").strip().upper()
    is_trdca = strategy_id == "trdca_pro" or sym == "MULTI"

    price_meta = _bot_price_meta(sym)
    from app.services.bot_equity import display_safe_bot_price

    live_price = float(display_safe_bot_price(price_meta.get("price"), state) or 0)
    if not is_trdca and _repair_bot_state_reference_if_needed(db, bot, state, raw, live_price):
        live_price = float(
            display_safe_bot_price(_resolve_bot_live_price(sym, state), state) or 0
        )

    config_for_grid = _effective_grid_config(raw, state)
    grid_points: List[Dict[str, Any]] = []
    profit_points: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    reference_display: Optional[float] = None

    if is_trdca:
        quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()
        coin_weights = (raw.get("dca") or {}).get("coin_weights") or {}
        basket_price = 0.0
        current_usd = 0.0
        if coin_weights:
            try:
                prices_map = await _fetch_prices_parallel(
                    list(coin_weights.keys()), quote_asset
                )
                for asset, w in coin_weights.items():
                    if str(asset).upper() == quote_asset:
                        basket_price += float(w)
                    else:
                        basket_price += float(w) * float(prices_map.get(asset) or 0)
            except Exception as e:
                logger.debug(
                    "bots_grid_points trdca basket failed bot_id=%s: %s", bot.id, e
                )
        if basket_price <= 0:
            float(state.get("base_balance") or 0)
            quote_b = float(state.get("quote_balance") or 0)
            basket_price = quote_b
            current_usd = quote_b
        else:
            current_usd = basket_price
        try:
            grid_points, profit_points, meta = compute_trdca_grid_view(
                state, raw, basket_price, current_usd
            )
            reference_display = meta.get("ref_display")
        except Exception as e:
            logger.warning("bots_grid_points trdca failed bot_id=%s: %s", bot.id, e)
    else:
        view_price = (
            live_price if live_price > 0 else float(state.get("reference_price") or 0)
        )
        try:
            grid_points, profit_points, meta = compute_grid_profit_view(
                state, config_for_grid, view_price
            )
            reference_display = meta.get("ref_display")
        except Exception as e:
            logger.warning("bots_grid_points failed bot_id=%s: %s", bot.id, e)

    return {
        "grid_points": grid_points,
        "profit_points": profit_points,
        "reference_display": reference_display,
        "meta": meta,
        "symbol": bot.symbol,
        "current_price": round(live_price, 8) if live_price > 0 else None,
        "price_stale": bool(price_meta.get("is_stale")),
        "price_age_s": price_meta.get("age_s"),
        "state": {
            "base_balance": state.get("base_balance"),
            "quote_balance": state.get("quote_balance"),
            "sell_history": state.get("sell_history"),
            "buy_history": state.get("buy_history"),
            "mode": state.get("mode"),
            "cycle_id": state.get("cycle_id"),
            "cycle_grid_side": meta.get("cycle_grid_side")
            or state.get("cycle_grid_side"),
        },
        "config": config_for_grid,
        "request_id": rid,
    }


@router.get("/batch/live")
async def bots_live_batch(
    request: Request,
    account_id: Optional[int] = Query(None, description="Account scope"),
    account_code: Optional[str] = Query(None),
    bot_ids: str = Query(..., description="Comma-separated bot ids (max 50)"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Batch live snapshots: one HTTP round-trip for dashboard equity polls."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    if resolved_account_id is None:
        if account_code and str(account_code).strip():
            raise HTTPException(
                status_code=404,
                detail=_detail_err("ACCOUNT_NOT_FOUND", "Account not found", rid),
            )
        raise HTTPException(
            status_code=422,
            detail=_detail_err(
                "ACCOUNT_REQUIRED", "account_id or account_code is required", rid
            ),
        )
    get_account_or_403(current, resolved_account_id, db)
    id_list: List[int] = []
    for part in (bot_ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            id_list.append(int(part))
        except ValueError:
            continue
    id_list = id_list[:_LIVE_BATCH_MAX_BOTS]
    if not id_list:
        return {"live": {}, "request_id": rid}
    bots = (
        db.query(Bot)
        .filter(Bot.account_id == resolved_account_id, Bot.id.in_(id_list))
        .all()
    )
    from app.botengine.state_store import load_states_bulk

    states = load_states_bulk(db, [b.id for b in bots])
    live_out: Dict[str, dict] = {}
    for bot in bots:
        cached = _live_snapshot_get_cached(bot.id)
        if cached is not None:
            live_out[str(bot.id)] = cached
            continue
        state = states.get(bot.id)
        data = _build_live_snapshot_from_state(bot, state, db)
        _live_snapshot_set_cached(bot.id, data)
        live_out[str(bot.id)] = data
    return {"live": live_out, "request_id": rid}


@router.get("/{bot_id}/live")
async def bots_live(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Live snapshot: always read current state; dashboard batch keeps its short cache."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    state = load_state(db, bot.id)
    data = _build_live_snapshot_from_state(bot, state, db)
    return data


@router.get("/{bot_id}/session-alpha")
async def bots_session_alpha(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Oturum performansı (alpha): run-start baseline + canlı equity/fiyat. TTL 60s; dönem filtresinden bağımsız."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    cached = _session_alpha_get_cached(bot.id)
    if cached is not None:
        return cached

    state = load_state(db, bot.id)
    sym = (bot.symbol or "").strip().upper()
    live_px = _resolve_bot_live_price(sym, state)
    session_alpha: Optional[Dict[str, Any]] = None
    try:
        session_alpha = resolve_session_alpha_performance(
            db,
            bot,
            state,
            live_price=live_px if live_px > 0 else None,
        )
    except Exception as e:
        logger.debug("bots_session_alpha bot_id=%s: %s", bot.id, e)

    real_performance_pct: Optional[float] = None
    if session_alpha:
        real_performance_pct = session_alpha.get("alpha_pct")

    result: Dict[str, Any] = {
        "request_id": rid,
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "real_performance_pct": real_performance_pct,
    }
    if session_alpha is not None:
        result["session_alpha_performance"] = session_alpha
        result["bot_alpha_performance"] = session_alpha

    _session_alpha_set_cached(bot.id, result)
    return result


@router.get("/{bot_id}/perf-narrative")
async def bots_perf_narrative(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    month: Optional[str] = Query(
        None, description="YYYY-MM; yoksa ay listesi + genel özet"
    ),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Aylık performans özeti ve kural tabanlı Türkçe yorum (tur/piyasa/sürdürülebilirlik)."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    session_alpha_pct: Optional[float] = None
    try:
        state = load_state(db, bot.id)
        sym = (bot.symbol or "").strip().upper()
        live_px = _resolve_bot_live_price(sym, state)
        sa = resolve_session_alpha_performance(
            db, bot, state, live_price=live_px if live_px > 0 else None
        )
        if sa:
            session_alpha_pct = sa.get("alpha_pct")
    except Exception as e:
        logger.debug("bots_perf_narrative session_alpha bot_id=%s: %s", bot.id, e)

    from app.services.bot_perf_narrative import (
        build_perf_narrative_month_detail,
        build_perf_narrative_overview,
    )

    if month and str(month).strip():
        mk = str(month).strip()
        if len(mk) == 7 and mk[4] == "-":
            detail = build_perf_narrative_month_detail(
                db, bot, mk, session_alpha_pct=session_alpha_pct
            )
            if detail.get("error") == "MONTH_BEFORE_BOT_START":
                raise HTTPException(
                    status_code=400,
                    detail=_detail_err(
                        "INVALID_MONTH", detail.get("message") or "Invalid month", rid
                    ),
                )
            detail["request_id"] = rid
            return detail

    overview = build_perf_narrative_overview(
        db, bot, session_alpha_pct=session_alpha_pct
    )
    overview["request_id"] = rid
    return overview


def _compute_perf_series(
    bot_id: int,
    range_val: str,
    bucket: str,
    db: Session,
    bot_started_ts: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Deterministic bucket engine. O(n). No average/interpolate. Returns (series, meta)."""
    now = int(datetime.now(timezone.utc).timestamp())
    window_sec = WINDOW_SECONDS.get(range_val)
    if not window_sec:
        return [], {"baseline_equity": None, "points": 0}
    window_start = now - window_sec
    bucket_sec = BUCKET_SECONDS.get(bucket)
    if not bucket_sec:
        return [], {"baseline_equity": None, "points": 0}

    payload = _load_perf_chart_payload(db, bot_id)
    samples = payload.get("samples") if isinstance(payload.get("samples"), list) else []
    baseline = payload.get("baseline") or {}
    baseline_bot0 = (
        baseline.get("bot0") if isinstance(baseline.get("bot0"), (int, float)) else 0.0
    )
    baseline_parite0 = (
        baseline.get("parite0")
        if isinstance(baseline.get("parite0"), (int, float))
        else 0.0
    )
    baseline_equity = baseline_bot0

    if bot_started_ts is not None:
        samples = [
            s
            for s in samples
            if isinstance(s, dict) and (s.get("ts") or 0) >= bot_started_ts
        ]
    samples = [
        s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= window_start
    ]
    if not samples:
        return [], {"baseline_equity": baseline_equity, "points": 0}

    bucket_map: Dict[int, Dict[str, Any]] = {}
    for s in samples:
        ts = s.get("ts")
        if ts is None:
            continue
        bucket_ts = (int(ts) // bucket_sec) * bucket_sec
        bot_pct = s.get("botPct") if "botPct" in s else s.get("bot_pct")
        parite_pct = s.get("paritePct") if "paritePct" in s else s.get("basket_pct")
        bucket_map[bucket_ts] = {
            "ts": bucket_ts,
            "bot_pct": bot_pct,
            "basket_pct": parite_pct,
        }

    series = sorted(bucket_map.values(), key=lambda x: x["ts"])
    if len(series) > PERF_SERIES_MAX_POINTS:
        step = (len(series) + PERF_SERIES_MAX_POINTS - 1) // PERF_SERIES_MAX_POINTS
        series = series[::step]
    meta = {
        "baseline_equity": baseline_equity,
        "baseline_bot0": baseline_bot0,
        "baseline_parite0": baseline_parite0,
        "points": len(series),
    }
    return series, meta


@router.get("/{bot_id}/perf-chart-data")
async def bots_perf_chart_data(
    request: Request,
    bot_id: int,
    range: str = Query(..., description="1h, 4h, 1d, 7d, 30d"),
    bucket: str = Query(..., description="1m, 5m, 1h, 4h, 1d"),
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Perf chart series only. Deterministic bucket engine. LRU cache. Max 500 points. Backend CPU < 40ms."""
    rid = _request_id(request)
    valid_ranges = ("1h", "4h", "1d", "7d", "30d")
    valid_buckets = ("1m", "5m", "1h", "4h", "1d")
    if range not in valid_ranges or bucket not in valid_buckets:
        raise HTTPException(
            status_code=400,
            detail=_detail_err("INVALID_PARAMS", "range or bucket invalid", rid),
        )
    if range == "1h" and bucket != "1h":
        bucket = "1h"

    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    state_perf = load_state(db, bot.id) or {}
    started_dt = _bot_run_started_at_dt(bot, state_perf, db)
    started_ts = int(started_dt.timestamp()) if started_dt is not None else None

    cached = PerfLRUCache.get(bot.id, range, bucket)
    if cached is not None:
        return cached

    series, meta = _compute_perf_series(bot.id, range, bucket, db, started_ts)
    if range == "1h" and meta["points"] < 3 and bucket == "1h":
        series, meta = _compute_perf_series(bot.id, range, "5m", db, started_ts)
        meta["points"] = len(series)
        bucket = "5m"

    result = {"range": range, "bucket": bucket, "series": series, "meta": meta}
    PerfLRUCache.set(bot.id, range, bucket, result)
    return result


@router.get("/{bot_id}/perf-chart-state")
async def bots_get_perf_chart_state(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bot performans grafiği state (baseline, samples, range). Yeni tarayıcıda grafik buradan yüklenir."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    payload = _load_perf_chart_payload(db, bot.id)
    if not payload:
        return {"baseline": None, "samples": [], "range": "4h", "request_id": rid}
    try:
        baseline = payload.get("baseline")
        samples = (
            payload.get("samples") if isinstance(payload.get("samples"), list) else []
        )
        range_val = (
            payload.get("range")
            if payload.get("range") in ("1m", "5m", "1h", "4h", "1d", "1w")
            else "4h"
        )
        # Sadece bu çalıştırma (oturum started_at) sonrası veriyi göster
        state_pc = load_state(db, bot.id) or {}
        started_dt = _bot_run_started_at_dt(bot, state_pc, db)
        if started_dt is not None:
            started_ts = int(started_dt.timestamp())
            samples = [
                s
                for s in samples
                if isinstance(s, dict) and (s.get("ts") or 0) >= started_ts
            ]
            if baseline and (baseline.get("ts0") or 0) < started_ts:
                baseline = None
        return {
            "baseline": baseline,
            "samples": samples,
            "range": range_val,
            "request_id": rid,
        }
    except Exception:
        return {"baseline": None, "samples": [], "range": "4h", "request_id": rid}


class PerfChartStateBody(BaseModel):
    baseline: Optional[dict] = None
    samples: Optional[List[dict]] = None
    range: Optional[str] = "4h"


@router.put("/{bot_id}/perf-chart-state")
async def bots_put_perf_chart_state(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    body: Optional[PerfChartStateBody] = None,
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bot performans grafiği state kaydet (baseline, samples, range). Frontend saveStorage ile birlikte çağırır."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    payload = {
        "baseline": body.baseline if body else None,
        "samples": body.samples if body and isinstance(body.samples, list) else [],
        "range": (
            body.range if body and body.range in ("1h", "4h", "1d", "1w") else "4h"
        )
        or "4h",
    }
    now = datetime.utcnow()
    db.execute(
        text("""
            INSERT INTO bot_perf_chart_state (bot_id, chart_payload, updated_at)
            VALUES (:bid, :payload, :upd)
            ON CONFLICT(bot_id) DO UPDATE SET chart_payload = :payload, updated_at = :upd
        """),
        {"bid": bot.id, "payload": json.dumps(payload, ensure_ascii=False), "upd": now},
    )
    db.commit()
    return {"ok": True, "bot_id": bot.id, "request_id": rid}


PERF_CHART_MAX_AGE_SEC = 7 * 24 * 3600  # 7 gün


def _load_perf_chart_payload(db: Session, bot_id: int) -> Dict[str, Any]:
    """bot_perf_chart_state tek SELECT helper'ı. Yoksa boş dict döner."""
    try:
        row = db.execute(
            text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
            {"bid": bot_id},
        ).fetchone()
    except Exception:
        return {}
    if not row or not row[0]:
        return {}
    try:
        data = json.loads(row[0])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _compute_trdca_pnl_breakdown(
    db: Session,
    bot_id: int,
    account_id: int,
    state: Dict[str, Any],
    raw_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    TRDCA için Rebalance (Adet) ve DCA PnL ayrımı.
    - Rebalance PnL (Adet): Her coin için TRB işlemlerinden adet bazlı PnL.
    - DCA PnL: USDT kazancı (DCA satışlardan); adet kazancı DCA alımlardan -> rebalance adet PnL'e eklenir.
    """
    out = {"rebalance_pnl": [], "dca_pnl_usd": 0.0, "dca_adet_pnl": []}
    try:
        all_trades = (
            db.query(Trade)
            .filter(Trade.bot_id == bot_id, Trade.account_id == account_id)
            .order_by(Trade.ts.asc())
            .all()
        )
        quote_asset = (raw_config.get("quote_asset") or "USDT").strip().upper()

        def _base_from_symbol(sym: str) -> str:
            if not sym:
                return ""
            s = (sym or "").upper().replace(quote_asset, "").strip()
            return s

        trb_by_coin: Dict[str, Dict[str, float]] = {}
        dca_by_coin: Dict[str, Dict[str, float]] = {}
        dca_sell_revenue = 0.0
        dca_buy_cost = 0.0
        dca_fees = 0.0

        for t in all_trades:
            coid = (t.client_order_id or "").strip()
            sym = (t.symbol or "").strip()
            base = _base_from_symbol(sym)
            if not base:
                continue
            qty = float(t.qty or 0)
            price = float(t.price or 0)
            fee = float(t.fee or 0)
            side = (t.side or "").upper()

            if coid.startswith("TRB-"):
                d = trb_by_coin.setdefault(
                    base,
                    {
                        "buy_qty": 0.0,
                        "buy_cost": 0.0,
                        "sell_qty": 0.0,
                        "sell_revenue": 0.0,
                    },
                )
                if side == "BUY":
                    d["buy_qty"] += qty
                    d["buy_cost"] += qty * price
                else:
                    d["sell_qty"] += qty
                    d["sell_revenue"] += qty * price
            elif coid.startswith("DCA-"):
                d = dca_by_coin.setdefault(
                    base,
                    {
                        "buy_qty": 0.0,
                        "buy_cost": 0.0,
                        "sell_qty": 0.0,
                        "sell_revenue": 0.0,
                    },
                )
                if side == "BUY":
                    d["buy_qty"] += qty
                    d["buy_cost"] += qty * price
                    dca_buy_cost += qty * price
                else:
                    d["sell_qty"] += qty
                    d["sell_revenue"] += qty * price
                    dca_sell_revenue += qty * price
                dca_fees += fee

        def _get_price(base: str) -> float:
            sym_pair = f"{base}{quote_asset}"
            return _get_price_from_datahub(sym_pair) or 0.0

        for base, d in trb_by_coin.items():
            current_qty = d["buy_qty"] - d["sell_qty"]
            p = _get_price(base)
            cost_basis = d["buy_cost"] - d["sell_revenue"]
            current_value = current_qty * p if p > 0 else 0.0
            pnl = current_value - cost_basis
            out["rebalance_pnl"].append(
                {"asset": base, "pnl_usd": round(pnl, 2), "qty": round(current_qty, 8)}
            )

        for base, d in dca_by_coin.items():
            p = _get_price(base)
            if d["buy_qty"] > 0 and p > 0:
                current_value = d["buy_qty"] * p
                cost = d["buy_cost"]
                adet_pnl = current_value - cost
                out["dca_adet_pnl"].append(
                    {
                        "asset": base,
                        "pnl_usd": round(adet_pnl, 2),
                        "qty": round(d["buy_qty"], 8),
                    }
                )

        out["dca_pnl_usd"] = round(dca_sell_revenue - dca_buy_cost - dca_fees, 2)
    except Exception as e:
        logger.debug("_compute_trdca_pnl_breakdown bot_id=%s: %s", bot_id, e)
    return out


def append_perf_chart_sample(db: Session, bot_id: int) -> None:
    """Çalışan bot için grafik örneklemesi ekler (tarayıcı kapalıyken sunucu kayıt yapar).
    TRDCA: Parite % = portföy coinlerinin ağırlıklı ortalama % değişimi (ilk fiyatlara göre)."""
    try:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot or (getattr(bot, "status", None) or "").lower() != "running":
            return
        state = load_state(db, bot.id)
        raw = json.loads(bot.config_json or "{}")
        strategy_id = (raw.get("strategy_id") or "").strip().lower()
        is_trdca = strategy_id == "trdca_pro"
        quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()

        pnl_data: Dict[str, Any] = {}
        try:
            pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id) or {}
        except Exception:
            pass
        if pnl_data.get("error"):
            pnl_data = {}
        current_usd = float(pnl_data.get("total_usd") or 0)
        initial_capital = float(
            raw.get("initial_capital_usdt")
            or raw.get("budget_usd")
            or raw.get("bot_budget_usdt")
            or raw.get("bot_budget_quote")
            or 0
        )
        payload = _load_perf_chart_payload(db, bot_id)
        baseline = payload.get("baseline") or {}

        live_price = float(pnl_data.get("current_price") or 0)
        if live_price <= 0:
            try:
                hub_p = price_hub.get_price(bot.symbol or "")
                if hub_p is not None and float(hub_p) > 0:
                    live_price = float(hub_p)
            except Exception:
                pass
        if live_price <= 0:
            live_price = float((state or {}).get("reference_price") or 0)

        alpha_sample = build_bot_alpha_performance(
            db,
            bot,
            state,
            current_usd=current_usd,
            current_price=live_price if live_price > 0 else None,
            chart_payload=payload,
            pnl_data=pnl_data,
        )
        bot_pct = None
        parite_pct = None
        if alpha_sample:
            bot_pct = alpha_sample.get("balance_pct")
            parite_pct = alpha_sample.get("coin_pct")
        elif initial_capital > 0:
            bot_pct = (current_usd - initial_capital) / initial_capital * 100.0

        if parite_pct is None and is_trdca:
            initial_prices = baseline.get("initial_prices")
            coin_weights = baseline.get("coin_weights")
            if not initial_prices or not coin_weights:
                target_weights = (
                    (raw.get("trb") or {}).get("target_weights_all")
                    or (raw.get("dca") or {}).get("coin_weights")
                    or {}
                )
                base_assets = [
                    a
                    for a in target_weights
                    if a and str(a).strip().upper() != quote_asset
                ]
                if base_assets:
                    initial_prices = _fetch_prices_for_assets(base_assets, quote_asset)
                    total_w = sum(
                        float(target_weights.get(a) or 0) for a in base_assets
                    )
                    coin_weights = (
                        {
                            a: float(target_weights.get(a) or 0) / total_w
                            for a in base_assets
                        }
                        if total_w > 0
                        else {}
                    )
                    if initial_prices and coin_weights:
                        baseline["initial_prices"] = initial_prices
                        baseline["coin_weights"] = coin_weights
                        payload["baseline"] = baseline
            if initial_prices and coin_weights:
                current_prices = _fetch_prices_for_assets(
                    list(coin_weights.keys()), quote_asset
                )
                parite_pct = compute_trdca_parite_pct(
                    initial_prices, coin_weights, current_prices, quote_asset
                )
        elif parite_pct is None:
            config_for_grid = _effective_grid_config(raw, state)
            reference_display = None
            try:
                view_price = (
                    live_price
                    if live_price > 0
                    else float((state or {}).get("reference_price") or 0)
                )
                _, _, meta = compute_grid_profit_view(
                    state or {}, config_for_grid, view_price
                )
                reference_display = meta.get("ref_display")
            except Exception:
                pass
            ref_price = (
                reference_display
                if reference_display is not None and reference_display > 0
                else float((state or {}).get("reference_price") or 0)
            )
            parite_pct = (
                (live_price - ref_price) / ref_price * 100.0
                if (ref_price and ref_price > 0 and live_price > 0)
                else None
            )

        if bot_pct is None and parite_pct is None:
            return
        if not payload:
            return
        baseline = payload.get("baseline")
        samples = payload.get("samples")
        if not isinstance(samples, list) or not baseline:
            return
        now_sec = int(datetime.now(timezone.utc).timestamp())
        samples.append({"ts": now_sec, "botPct": bot_pct, "paritePct": parite_pct})
        cut = now_sec - PERF_CHART_MAX_AGE_SEC
        samples[:] = [
            s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= cut
        ]
        # Sadece bu çalıştırma (oturum started_at) sonrası örnekleri sakla
        state_pc = load_state(db, bot_id) or {}
        started_dt = _bot_run_started_at_dt(bot, state_pc, db)
        if started_dt is not None:
            started_ts = int(started_dt.timestamp())
            samples[:] = [s for s in samples if (s.get("ts") or 0) >= started_ts]
            if baseline and (baseline.get("ts0") or 0) < started_ts:
                preserved = {
                    k: baseline[k]
                    for k in (
                        "start_balance_usd",
                        "start_coin_price",
                        "initial_prices",
                        "coin_weights",
                    )
                    if baseline.get(k) is not None
                }
                baseline = {"bot0": 0.0, "parite0": 0.0, "ts0": started_ts, **preserved}
                payload["baseline"] = baseline
        payload["samples"] = samples
        payload["range"] = (
            payload.get("range")
            if payload.get("range") in ("1h", "4h", "1d", "1w")
            else "4h"
        )
        now = datetime.utcnow()
        db.execute(
            text(
                "UPDATE bot_perf_chart_state SET chart_payload = :payload, updated_at = :upd WHERE bot_id = :bid"
            ),
            {
                "bid": bot_id,
                "payload": json.dumps(payload, ensure_ascii=False),
                "upd": now,
            },
        )
        db.commit()
    except Exception as e:
        logger.debug("append_perf_chart_sample bot_id=%s: %s", bot_id, e)
        try:
            db.rollback()
        except Exception:
            pass


@router.delete("/{bot_id}/perf-chart-state")
async def bots_delete_perf_chart_state(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bot performans grafiği state sil (bot başlatıldığında grafik sıfırdan başlasın)."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    db.execute(
        text("DELETE FROM bot_perf_chart_state WHERE bot_id = :bid"), {"bid": bot.id}
    )
    db.commit()
    return {"ok": True, "bot_id": bot.id, "request_id": rid}


def _insert_engine_command(
    db: Session,
    account_id: int,
    bot_id: int,
    command: str,
    payload_json: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Optional[int]:
    """Insert into bot_engine_commands; returns command id."""
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "created_at": now,
        "account_id": account_id,
        "bot_id": bot_id,
        "command": command,
        "payload_json": payload_json,
        "request_id": request_id,
    }
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    is_postgres = getattr(dialect, "name", "") == "postgresql"
    if is_postgres:
        row = db.execute(
            text("""
                INSERT INTO bot_engine_commands (created_at, account_id, bot_id, command, payload_json, status, request_id)
                VALUES (:created_at, :account_id, :bot_id, :command, :payload_json, 'PENDING', :request_id)
                RETURNING id
            """),
            params,
        ).fetchone()
        db.commit()
        return int(row[0]) if row and row[0] else None
    db.execute(
        text("""
            INSERT INTO bot_engine_commands (created_at, account_id, bot_id, command, payload_json, status, request_id)
            VALUES (:created_at, :account_id, :bot_id, :command, :payload_json, 'PENDING', :request_id)
        """),
        params,
    )
    db.commit()
    row = db.execute(text("SELECT last_insert_rowid()")).fetchone()
    return int(row[0]) if row and row[0] else None


@router.post("/{bot_id}/start")
async def bots_start(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Start bot: DB status + command queue. Worker işler (web task yaratmaz)."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    # Test hesabı paper modda kalmalı (API key yok)
    from app.services.test_account import is_test_account

    if (getattr(bot, "mode", None) or "").lower() == "paper" and not is_test_account(
        bot.account_id, db
    ):
        bot.mode = "live"
        try:
            raw = json.loads(bot.config_json or "{}")
            raw["mode"] = "live"
            raw["paper_mode"] = False
            bot.config_json = json.dumps(raw, ensure_ascii=False)
        except Exception:
            pass
        db.commit()
        state = load_state(db, bot.id)
        if state and state.get("initial_allocation_done"):
            state["initial_allocation_done"] = False
            state.pop("initial_alloc_base_qty", None)
            state.pop("initial_alloc_price", None)
            save_state(db, bot.id, bot.account_id, state)
    ensure_state_row(
        db, bot.id, bot.account_id, (bot.symbol or "").upper() or "BTCUSDT"
    )

    strategy_id = ""
    try:
        raw_cfg = json.loads(bot.config_json or "{}")
        strategy_id = (raw_cfg.get("strategy_id") or "").strip().lower()
    except Exception:
        raw_cfg = {}
    if (
        strategy_id not in ("trdca_pro", "multi_asset_rebalance")
        and (bot.symbol or "").upper() != "MULTI"
    ):
        try:
            raw_cfg = normalize_max_buy_levels_payload(raw_cfg)
            if getattr(bot, "max_buy_levels", None) != raw_cfg.get("max_buy_levels"):
                bot.max_buy_levels = int(raw_cfg["max_buy_levels"])
                bot.config_json = json.dumps(raw_cfg, ensure_ascii=False)
                db.commit()
        except MaxBuyLevelsError as e:
            raise HTTPException(
                status_code=400,
                detail=_detail_err("MAX_BUY_LEVELS_INVALID", str(e), rid),
            )
        from app.botengine.config_validate import validate_dca_payload
        from app.botengine.state_store import append_event

        ok_grid, grid_err, grid_viol, min_budget = validate_dca_payload(raw_cfg)
        if not ok_grid:
            append_event(
                db,
                bot.id,
                bot.account_id,
                "ERROR",
                grid_err,
                {
                    "error_code": "GRID_NOTIONAL_TOO_LOW",
                    "violations": grid_viol,
                    "min_budget_usdt": min_budget,
                },
            )
            raise HTTPException(
                status_code=400,
                detail=_detail_err("GRID_NOTIONAL_TOO_LOW", grid_err, rid),
            )

    # Live modda bakiye kontrolü: yetersizse başlatma, PAUSED_ERROR önlenir
    is_test = is_test_account(bot.account_id, db)
    if not is_test and (getattr(bot, "mode", None) or "").lower() == "live":
        try:
            raw = json.loads(bot.config_json or "{}")
            budget = float(
                raw.get("initial_capital_usdt")
                or raw.get("budget_usd")
                or raw.get("bot_budget_usdt")
                or 0
            )
            sym = (bot.symbol or "").upper().strip()
            if sym == "MULTI":
                quote_asset = (
                    raw.get("quote_asset") or "USDT"
                ).strip().upper() or "USDT"
            else:
                # Tek-sembol parite: bilinen quote son ekleri (USDT/FDUSD/BUSD/USDC/TUSD/BTC/ETH).
                cfg_q = (raw.get("quote_asset") or "").strip().upper()
                quote_asset = None
                for suf in ("USDT", "FDUSD", "BUSD", "USDC", "TUSD", "BTC", "ETH"):
                    if sym.endswith(suf) and len(sym) > len(suf):
                        quote_asset = suf
                        break
                if not quote_asset:
                    quote_asset = cfg_q or "USDT"
            if budget > 0:
                from app.services.binance_assets import get_account_keys
                from app.botengine.adapters.binance_adapter import BinanceAdapter

                keys = await get_account_keys(bot.account_id, db)
                adapter = BinanceAdapter(bot.account_id, keys, paper_mode=False)
                balances = await adapter.get_account_balances()
                free = float((balances.get(quote_asset) or {}).get("free") or 0)
                if budget > free:
                    raise HTTPException(
                        status_code=400,
                        detail=_detail_err(
                            "INSUFFICIENT_BALANCE",
                            "Yetersiz bakiye. Bot bütçesi: %.2f %s, kullanılabilir: %.2f %s. Bütçeyi düşürün veya cüzdana bakiye ekleyin."
                            % (budget, quote_asset, free, quote_asset),
                            rid,
                        ),
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("bots_start balance check failed bot_id=%s: %s", bot.id, e)
            # API/network hatasında başlatmayı engellemeyebiliriz; yine de dene

    from app.botengine.bot_session import mark_bot_run_started, touch_bot_started_at

    bot.status = "running"
    touch_bot_started_at(bot, connectivity_resume=False)
    db.commit()
    seed_perf_chart_state_on_bot_start(db, bot.id)
    invalidate_live_snapshot_cache(bot.id)
    sym = (bot.symbol or "").upper().strip()
    if sym and sym != "MULTI":
        try:
            from app.services.data_hub import data_hub

            data_hub.pin_symbols([sym])
            # Fiyat ısınması komut kuyruğunu bekletmemeli. Worker aynı sembolü
            # ilk tick'te güvenli biçimde doğrular; web yalnızca önden ısıtır.
            asyncio.create_task(data_hub.ensure_symbol_price(sym))
        except Exception as e:
            logger.debug("bots_start pin_price bot_id=%s sym=%s: %s", bot.id, sym, e)
    try:
        from app.api.routes import invalidate_dashboard_summary_cache

        invalidate_dashboard_summary_cache(bot.account_id)
    except Exception:
        pass
    command_id = _insert_engine_command(
        db, bot.account_id, bot.id, "START", request_id=rid
    )
    state = load_state(db, bot.id) or {}
    state["run_id"] = f"cmd{command_id}"
    mark_bot_run_started(state, connectivity_resume=False)
    try:
        from app.botengine.strategies.grid_outage_recovery import (
            prepare_grids_for_cold_run_start,
        )

        prepare_grids_for_cold_run_start(state, raw_cfg)
    except Exception:
        pass
    save_state(db, bot.id, bot.account_id, state)
    logger.info("BOT_RUN_ID set bot_id=%s run_id=cmd%s", bot.id, command_id)
    account = db.query(Account).filter(Account.id == bot.account_id).first()
    audit_svc.log_event(
        db,
        actor_type="admin" if current.get("is_admin") else "user",
        event_type="BOT_START",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=account.user_id if account else None,
        target_account_id=bot.account_id,
        ip=get_client_ip(request),
        device_id=current.get("device_id"),
        request_id=rid,
        meta={
            "bot_id": bot.id,
            "account_id": bot.account_id,
            "symbol": (bot.symbol or "") or "",
        },
    )
    worker_alive = _worker_process_alive()
    msg = "Command queued; worker will start the bot."
    if not worker_alive:
        msg = "Komut kuyruğa alındı ancak Bot Engine worker çalışmıyor. start.command veya worker.log kontrol edin."
    return {
        "ok": True,
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "request_id": rid,
        "command_id": command_id,
        "bot_status": "running",
        "worker_alive": worker_alive,
        "message": msg,
    }


@router.post("/{bot_id}/stop")
async def bots_stop(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Stop bot: DB status + command queue. Worker işler."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    from app.botengine.bot_session import clear_bot_run_started

    bot.status = "stopped"
    state = load_state(db, bot.id) or {}
    clear_bot_run_started(state)
    save_state(db, bot.id, bot.account_id, state)
    db.commit()
    invalidate_live_snapshot_cache(bot.id)
    command_id = _insert_engine_command(
        db, bot.account_id, bot.id, "STOP", request_id=rid
    )
    account = db.query(Account).filter(Account.id == bot.account_id).first()
    audit_svc.log_event(
        db,
        actor_type="admin" if current.get("is_admin") else "user",
        event_type="BOT_STOP",
        severity="INFO",
        actor_user_id=current.get("user_id"),
        target_user_id=account.user_id if account else None,
        target_account_id=bot.account_id,
        ip=get_client_ip(request),
        device_id=current.get("device_id"),
        request_id=rid,
        meta={
            "bot_id": bot.id,
            "account_id": bot.account_id,
            "symbol": (bot.symbol or "") or "",
        },
    )
    try:
        from app.api.routes import (
            invalidate_dashboard_summary_cache,
            invalidate_wallet_cache,
        )

        invalidate_dashboard_summary_cache(bot.account_id)
        await invalidate_wallet_cache(bot.account_id)
    except Exception:
        pass
    return {
        "ok": True,
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "request_id": rid,
        "command_id": command_id,
        "bot_status": "stopped",
        "message": "Command queued; worker will stop the bot.",
    }


def _is_worker_only_order_error(e: Exception) -> bool:
    """True if e is the worker-only order placement guard (Web/API cannot place orders)."""
    try:
        from app.core.errors import AppError

        if (
            isinstance(e, AppError)
            and getattr(e, "error_code", None) == "WORKER_ONLY_OPERATION"
        ):
            return True
    except Exception:
        pass
    s = str(e).lower()
    return "only allowed on worker" in s or "web/api cannot place" in s


def _delete_convert_error_skippable(e: Exception, is_test_account: bool) -> bool:
    """Convert başarısız olsa da silmeye devam (test/paper, API yok, worker-only)."""
    if is_test_account:
        return True
    if _is_worker_only_order_error(e):
        return True
    s = str(e).lower()
    return (
        "api anahtarı" in s or "api anahtari" in s or "api key" in s or "api keys" in s
    )


async def _wallet_for_bot_delete(keys, get_wallet):
    """Deletion may wait through a short Binance account endpoint wobble."""
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            return await get_wallet(keys, tag=f"bot_delete_convert_{attempt + 1}")
        except Exception as exc:
            last_error = exc
            if attempt >= 2:
                break
            await asyncio.sleep(0.4 * (attempt + 1))
    assert last_error is not None
    raise last_error


async def _wait_for_stop_command(
    db: Session, command_id: int, timeout_sec: float = 3.0
) -> str:
    """Let the worker cancel its in-memory bot loop before runtime rows are removed."""
    deadline = time.monotonic() + max(0.0, timeout_sec)
    status = "PENDING"
    while time.monotonic() < deadline:
        row = db.execute(
            text("SELECT status FROM bot_engine_commands WHERE id = :id"),
            {"id": command_id},
        ).fetchone()
        db.commit()
        status = str(row[0] if row else "MISSING").upper()
        if status in {"DONE", "ERROR", "MISSING"}:
            return status
        await asyncio.sleep(0.15)
    return status


async def _sell_symbol_base_on_delete(
    db: Session, account_id: int, bot_id: int, symbol: str
) -> None:
    """Bot silinmeden önce Binance base → quote (açık emirleri iptal et, free+locked sat)."""
    from app.services.binance_assets import get_account_keys
    from app.services.binance_spot import cancel_order, get_open_orders, get_wallet
    from app.services.spot_engine import SpotEngine, spot_cache

    sym = (symbol or "").upper().strip()
    if not sym:
        return
    keys = await get_account_keys(account_id, db)
    if not keys:
        raise ValueError("API anahtarı bulunamadı")

    try:
        open_orders = await get_open_orders(keys, symbol=sym)
        for o in open_orders or []:
            oid = o.get("orderId")
            if oid is None:
                continue
            try:
                await cancel_order(keys, sym, int(oid))
            except Exception as ce:
                logger.warning(
                    "bots_delete convert cancel_order bot_id=%s symbol=%s order=%s err=%s",
                    bot_id,
                    sym,
                    oid,
                    ce,
                )
    except Exception as e:
        logger.warning(
            "bots_delete convert list_orders bot_id=%s symbol=%s err=%s", bot_id, sym, e
        )

    spot_cache.invalidate_balance(account_id)

    async with SpotEngine(keys) as engine:
        flt = await engine._get_symbol_filters(sym)
        base_asset = (flt.get("base_asset") or sym.replace("USDT", "")).upper()
        wallet_data = await _wallet_for_bot_delete(keys, get_wallet)
        balances = wallet_data.get("balances") or []
        base_qty = 0.0
        for b in balances:
            if (b.get("asset") or "").upper() == base_asset:
                base_qty = float(b.get("free") or 0) + float(b.get("locked") or 0)
                break
        if base_qty <= 0:
            return
        min_notional = float(flt.get("min_notional") or DEFAULT_MIN_NOTIONAL_USDT)
        price = 0.0
        try:
            from app.services.market_data import get_price

            price = float(get_price(sym) or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            spot = await engine.get_quick_data(sym, account_id)
            price = float(spot.price or 0)
        notional = base_qty * price if price else 0
        if notional < min_notional:
            logger.info(
                "bots_delete convert skip bot_id=%s symbol=%s notional=%.2f min=%.2f",
                bot_id,
                sym,
                notional,
                min_notional,
            )
            return
        await engine.place_order(
            sym, "SELL", "MARKET", quantity=base_qty, allow_web=True
        )
        spot_cache.invalidate_balance(account_id)
        logger.info(
            "bots_delete convert_base_to_quote bot_id=%s symbol=%s base_qty=%.8f",
            bot_id,
            sym,
            base_qty,
        )


@router.post("/{bot_id}/delete")
async def bots_delete(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Delete bot fully (stop + delete state, events, wallet, trades, bot).
    Body: { \"convert_base_to_quote\": true } -> önce Binance'te base varlığı piyasa emri ile USDT'ye satar, sonra siler."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    convert_base = body.get("convert_base_to_quote") is True
    from app.services.test_account import is_test_account

    is_test = is_test_account(bot.account_id, db)
    delete_account_id = bot.account_id
    stop_command_id: Optional[int] = None
    conversion_completed = False
    if convert_base and is_test:
        logger.info("bots_delete skip convert (test/paper account) bot_id=%s", bot.id)
        convert_base = False
    if convert_base:
        bot.status = "stopped"
        db.commit()
        stop_command_id = _insert_engine_command(
            db, bot.account_id, bot.id, "STOP", request_id=rid
        )
        symbol = (bot.symbol or "BTCUSDT").upper().strip()
        raw = json.loads(bot.config_json or "{}")
        quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()
        if symbol == "MULTI":

            def _norm_base(s: str) -> str:
                s = (s or "").strip().upper()
                for suf in ("USDT", "FDUSD", "BUSD"):
                    if s.endswith(suf):
                        s = s[: -len(suf)]
                        break
                return s if s and s != quote_asset else ""

            assets = set()
            trb = raw.get("trb") or {}
            for k in (trb.get("target_weights_all") or {}).keys():
                n = _norm_base(str(k))
                if n:
                    assets.add(n)
            dca = raw.get("dca") or {}
            for k in (dca.get("coin_weights") or {}).keys():
                n = _norm_base(str(k))
                if n:
                    assets.add(n)
            if raw.get("assets"):
                for a in raw["assets"]:
                    sym = a.get("symbol", a) if isinstance(a, dict) else a
                    n = _norm_base(str(sym))
                    if n:
                        assets.add(n)
            try:
                for base_asset in assets:
                    if base_asset == quote_asset:
                        continue
                    sym_pair = f"{base_asset}{quote_asset}"
                    try:
                        await _sell_symbol_base_on_delete(
                            db, bot.account_id, bot.id, sym_pair
                        )
                    except Exception as e:
                        logger.warning(
                            "bots_delete convert_base_to_quote MULTI %s failed bot_id=%s: %s",
                            sym_pair,
                            bot.id,
                            e,
                        )
            except Exception as e:
                logger.warning(
                    "bots_delete convert_base_to_quote MULTI failed bot_id=%s: %s",
                    bot.id,
                    e,
                )
                raise HTTPException(
                    status_code=400, detail=_detail_err("CONVERT_FAILED", str(e), rid)
                )
        elif symbol and len(symbol) > 4 and symbol.endswith(("USDT", "FDUSD", "BUSD")):
            try:
                await _sell_symbol_base_on_delete(db, bot.account_id, bot.id, symbol)
                conversion_completed = True
            except Exception as e:
                logger.warning(
                    "bots_delete convert_base_to_quote failed bot_id=%s err=%s",
                    bot.id,
                    e,
                )
                if not _is_worker_only_order_error(
                    e
                ) and not _delete_convert_error_skippable(e, is_test):
                    raise HTTPException(
                        status_code=400,
                        detail=_detail_err("CONVERT_FAILED", str(e), rid),
                    )
        try:
            from app.api.routes import (
                invalidate_dashboard_summary_cache,
                invalidate_open_orders_cache,
                invalidate_wallet_cache,
            )

            invalidate_dashboard_summary_cache(bot.account_id)
            await invalidate_wallet_cache(bot.account_id)
            await invalidate_open_orders_cache(bot.account_id)
        except Exception:
            pass
    if stop_command_id is None:
        bot.status = "stopped"
        db.commit()
        stop_command_id = _insert_engine_command(
            db, bot.account_id, bot.id, "STOP", request_id=rid
        )
    await _wait_for_stop_command(db, stop_command_id)
    invalidate_live_snapshot_cache(bot.id)
    await delete_bot_fully(bot.id, db)
    try:
        from app.api.routes import invalidate_dashboard_summary_cache

        invalidate_dashboard_summary_cache(delete_account_id)
    except Exception:
        pass
    return {
        "ok": True,
        "bot_id": bot_id,
        "request_id": rid,
        "message": (
            "Bot silindi; base varlık quote bakiyeye dönüştürüldü."
            if conversion_completed
            else "Bot silindi; mevcut coin bakiyesi cüzdanda korundu."
        ),
    }


@router.post("/{bot_id}/update-config")
async def bots_update_config(
    request: Request,
    bot_id: int,
    body: dict,
    account_id: Optional[int] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Update bot config_json."""
    rid = _request_id(request)
    bot = _resolve_bot(bot_id, account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    try:
        normalized_body = normalize_max_buy_levels_payload(body or {})
        cfg = config_from_ui_payload(normalized_body)
    except MaxBuyLevelsError as e:
        raise HTTPException(
            status_code=400, detail=_detail_err("MAX_BUY_LEVELS_INVALID", str(e), rid)
        )
    # Dynamic Mode safety gate. Current policy keeps only max_buy_levels as a
    # structural prerequisite; daily loss / stop-loss / emergency brakes are
    # disabled behind flags. Reject only if the active gate reports a violation.
    if bool(getattr(cfg, "dynamic_mode", False)):
        try:
            from app.botengine.dynamic import safety_gate as _dyn_gate

            _g = _dyn_gate.check_prerequisites(cfg.to_dict())
            if not _g.ok:
                raise HTTPException(
                    status_code=400,
                    detail=_detail_err(
                        "DYNAMIC_MODE_PREREQS_MISSING",
                        "Dynamic Mode açılabilmesi için zorunlu koruma katmanları eksik: "
                        + "; ".join(_g.violations),
                        rid,
                    ),
                )
        except HTTPException:
            raise
        except Exception as _gex:
            logger.warning(
                "bots_update_config dynamic gate failed bot_id=%s err=%s", bot.id, _gex
            )
    bot.config_json = json.dumps(cfg.to_dict(), ensure_ascii=False)
    bot.max_buy_levels = cfg.max_buy_levels
    db.commit()
    invalidate_config_cache(bot.id)
    return {"ok": True, "bot_id": bot.id, "request_id": rid}


@router.get("/{bot_id}/health")
async def bots_health(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Per-bot health snapshot for UI alerts (tick stale, errors, order failures). Does not stop bot."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    from app.botengine.health_watch import (
        evaluate_bot_health,
        _expected_tick_interval_sec,
        _parse_last_tick_ts,
    )

    try:
        from app.services.binance_connectivity import sync_bot_connectivity_on_view

        await sync_bot_connectivity_on_view(db, bot, source="health_poll")
    except Exception as e:
        logger.debug("bots_health connectivity probe bot_id=%s: %s", bot.id, e)
    state = load_state(db, bot.id) or {}
    dismiss_id = int(state.get("engine_log_dismiss_before_id") or 0)
    if not dismiss_id and int(state.get("health_ack_at") or 0) > 0:
        from app.botengine.engine_log_ack import max_resettable_event_id

        dismiss_id = max_resettable_event_id(list_events(db, bot.id, limit=120))
    alerts = evaluate_bot_health(bot, state, db)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    last_tick = _parse_last_tick_ts(state)
    tick_age = (now_ts - last_tick) if last_tick is not None else None
    interval_s = _expected_tick_interval_sec(bot)
    if tick_age is not None and tick_age < max(60.0, interval_s * 5.0):
        alerts = [
            a
            for a in alerts
            if str((a or {}).get("code") or "").upper() != "LOOP_TASK_MISSING"
        ]
    display_last_error_code = state.get("last_error_code")
    if display_last_error_code:
        active_codes = {
            str((a or {}).get("code") or "").upper()
            for a in alerts
            if isinstance(a, dict)
        }
        if (
            str(display_last_error_code).upper()
            in {
                "BOT_LOOP_TOPLEVEL_EXCEPTION",
                "BOT_LOOP_TRDCA_EXCEPTION",
                "BOT_TICK_EXCEPTION",
                "RUN_ACTION_EXCEPTION",
            }
            and not active_codes
        ):
            display_last_error_code = None
    conn_fail = None
    connectivity_ok = True
    try:
        from app.services.binance_connectivity import active_failure

        rec = active_failure(bot.account_id)
        if rec:
            connectivity_ok = False
            conn_fail = {
                "error_code": rec.get("error_code"),
                "message": rec.get("message"),
                "source": rec.get("source"),
            }
    except Exception:
        pass
    return {
        "ok": True,
        "bot_id": bot.id,
        "status": (bot.status or "stopped").lower(),
        "alerts": alerts,
        "last_tick_at": last_tick,
        "tick_age_s": round(tick_age, 1) if tick_age is not None else None,
        "tick_interval_s": interval_s,
        "last_error_code": display_last_error_code,
        "health_ack_at": int(state.get("health_ack_at") or 0),
        "engine_log_dismiss_before_id": dismiss_id,
        "connectivity_failure": conn_fail,
        "connectivity_ok": connectivity_ok,
        "request_id": rid,
    }


@router.post("/{bot_id}/health/ack")
async def bots_health_ack(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Operator acknowledged health banner: clear last_error_code and stamp health_ack_at."""
    rid = _request_id(request)
    if not current.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail=_detail_err(
                "FORBIDDEN",
                "Bot motor logları yalnızca admin kullanıcılar içindir",
                rid,
            ),
        )
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    state = load_state(db, bot.id) or {}
    now_ts = int(datetime.now(timezone.utc).timestamp())
    prev_err = state.pop("last_error_code", None) or ""
    prev_err = str(prev_err).strip() or None
    state["health_ack_at"] = now_ts
    if prev_err:
        state["health_ack_error"] = prev_err
    state.pop("health_error_since", None)
    from app.botengine.engine_log_ack import max_resettable_event_id

    ack_events = list_events(db, bot.id, limit=500)
    dismiss_before = max_resettable_event_id(ack_events)
    state["engine_log_dismiss_before_id"] = dismiss_before
    save_state(db, bot.id, bot.account_id, state)
    return {
        "ok": True,
        "bot_id": bot.id,
        "cleared_error": prev_err,
        "health_ack_at": now_ts,
        "engine_log_dismiss_before_id": dismiss_before,
        "request_id": rid,
    }


@router.get("/{bot_id}/events")
async def bots_events(
    request: Request,
    bot_id: int,
    limit: int = Query(100, ge=1, le=500),
    after_id: Optional[int] = Query(None),
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List bot engine events."""
    rid = _request_id(request)
    if not current.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail=_detail_err(
                "FORBIDDEN",
                "Bot motor logları yalnızca admin kullanıcılar içindir",
                rid,
            ),
        )
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    try:
        from app.services.binance_connectivity import sync_bot_connectivity_on_view

        # force_probe=False: /health (bot sayfası) zaten prob yapar; ikinci 8s cüzdan çağrısı UI timeout + flicker üretir.
        await sync_bot_connectivity_on_view(
            db,
            bot,
            source="events_load" if after_id is None else "events_poll",
            force_probe=False,
        )
    except Exception as e:
        logger.debug("bots_events connectivity probe bot_id=%s: %s", bot.id, e)
    state = load_state(db, bot.id)
    session_start_id = 0
    session_limit = 5000
    try:
        from app.botengine.bot_session import resolve_bot_session_start_event_id

        session_start_id = resolve_bot_session_start_event_id(db, bot.id, state or {})
    except Exception as sess_ex:
        logger.debug("bots_events session_start bot_id=%s: %s", bot.id, sess_ex)
    fetch_limit = limit
    since_id: Optional[int] = None
    if session_start_id > 0:
        since_id = session_start_id
        if after_id is None:
            # Oturum tam yüklemesi: istemci limit=500 gönderse bile tüm oturum (≤5000).
            fetch_limit = session_limit
        else:
            fetch_limit = min(limit, 100)
    events = list_events(
        db,
        bot.id,
        limit=fetch_limit,
        after_id=after_id,
        since_id=since_id,
    )
    if after_id is None:
        dismiss_before = int((state or {}).get("engine_log_dismiss_before_id") or 0)
        if dismiss_before > 0:
            from app.botengine.engine_log_ack import filter_events_for_dismiss

            events = filter_events_for_dismiss(events, dismiss_before)
        try:
            anchors = _fetch_lifecycle_anchor_events(
                db, bot.id, session_start_id=session_start_id
            )
            if dismiss_before > 0:
                anchors = filter_events_for_dismiss(anchors, dismiss_before)
            events = _merge_anchor_events(events, anchors)
        except Exception as anchor_ex:
            logger.debug(
                "bots_events lifecycle anchors bot_id=%s: %s", bot.id, anchor_ex
            )
    try:
        if after_id is None:
            # İlk yükleme: anchor/sentetik satırlar + dedupe + enrich tam paket.
            events = _enrich_command_start_events(events, bot, state)
            events = _merge_synthetic_cycle_end_events(
                events, state, db=db, bot_id=bot.id
            )
            events = _merge_synthetic_cycle_start_events(
                events, state, db=db, bot_id=bot.id
            )
            events = _merge_synthetic_tur_after_initial_fill(events, state)
            _enrich_cycle_start_events_meta(events, state)
            events = _dedupe_cycle_end_events(events)
            events = _dedupe_cycle_start_events(events)[:fetch_limit]
        else:
            # Incremental poll: sentetik backfill yeni event üretmez; yalnız meta-enrich yeterli.
            events = _enrich_command_start_events(events, bot, state)
            _enrich_cycle_start_events_meta(events, state)
        events = _sort_engine_events_desc(events)
    except Exception as enrich_ex:
        logger.exception(
            "bots_events enrich failed bot_id=%s after_id=%s: %s",
            bot.id,
            after_id,
            enrich_ex,
        )
        events = _sort_engine_events_desc(list(events or []))[:fetch_limit]
    conn_fail = None
    connectivity_ok = True
    try:
        from app.services.binance_connectivity import active_failure

        rec = active_failure(bot.account_id)
        if rec:
            connectivity_ok = False
            conn_fail = {
                "error_code": rec.get("error_code"),
                "message": rec.get("message"),
                "source": rec.get("source"),
            }
    except Exception:
        pass
    return {
        "events": events,
        "session_start_event_id": session_start_id,
        "connectivity_failure": conn_fail,
        "connectivity_ok": connectivity_ok,
        "request_id": rid,
    }


@router.get("/{bot_id}/cycles")
async def bots_cycles(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List cycle_ids (tur numbers) for bot. TRDCA: dca_cycles and trb_cycles separately."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    raw = json.loads(bot.config_json or "{}")
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_trdca = strategy_id == "trdca_pro" or (bot.symbol or "").upper() == "MULTI"
    dca_cycles = _merge_bot_cycle_ids(db, bot.id, bot.account_id)
    if not is_trdca:
        return {
            "cycles": dca_cycles,
            "dca_cycles": dca_cycles,
            "trb_cycles": [],
            "request_id": rid,
        }
    state = load_state(db, bot.id)
    trb = (state or {}).get("trb") or {}
    trb_count = int(trb.get("trb_cycles_count") or 0)
    trb_cycles = list(range(1, trb_count + 1)) if trb_count > 0 else []
    return {
        "cycles": dca_cycles,
        "dca_cycles": dca_cycles,
        "trb_cycles": trb_cycles,
        "request_id": rid,
    }


def _grid_qty_pct_display(raw: Any) -> Optional[float]:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if 0 < v <= 1:
        return round(v * 100.0, 2)
    return round(v, 2)


def _grid_pct_from_config(g: Dict[str, Any], side: str) -> Optional[float]:
    if side == "SELL":
        v = g.get("sell_grid_pct") or g.get("trigger_pct")
    else:
        v = g.get("buy_grid_pct") or g.get("trigger_pct")
    try:
        return round(float(v), 4) if v is not None else None
    except (TypeError, ValueError):
        return None


def _is_cycle_trades_panel_row(t: Dict[str, Any]) -> bool:
    """Tur işlemleri panelinde listelenen satırlar (ilk base / tur devri hariç)."""
    cid = (t.get("client_order_id") or "").lower()
    if cid.startswith("cycle_open_"):
        return False
    if cid.startswith("init_") or "c0i" in cid:
        return False
    if (t.get("reason") or "").lower() == "initial_allocation":
        return False
    return True


def _is_grid_trade_row(t: Dict[str, Any]) -> bool:
    cid = (t.get("client_order_id") or "").lower()
    if cid.startswith("cycle_open_") or "init_" in cid or cid.startswith("init"):
        return False
    reason = (t.get("reason") or "").lower()
    if reason in (
        "initial_allocation",
        "trail_reentry_buy",
        "trail_profit_sell",
        "reentry",
        "profit_exit",
    ):
        return False
    if "reentry" in cid or "profit_exit" in cid:
        return False
    slot = t.get("slot_id")
    if slot is not None:
        try:
            if int(slot) >= 0:
                return True
        except (TypeError, ValueError):
            pass
    if reason in ("trail_sell_grid", "trail_buy_grid"):
        return True
    if t.get("grid_detail"):
        return True
    return False


def _trail_pct_for_side(cfg: Dict[str, Any], side: str) -> Optional[float]:
    try:
        if side == "SELL":
            v = cfg.get("sell_trigger_trailing_pct")
            if v is None:
                v = (cfg.get("up") or {}).get("trail_pct")
        else:
            v = cfg.get("buy_trigger_trailing_pct")
            if v is None:
                v = (cfg.get("down") or {}).get("trail_pct")
        return round(float(v), 4) if v is not None else None
    except (TypeError, ValueError):
        return None


def _archive_lookup_trade(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    side: str,
    qty: Any,
    price: Any,
) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    try:
        qf = float(qty or 0)
        pf = float(price or 0)
    except (TypeError, ValueError):
        return None
    if qf <= 0 or pf <= 0:
        return None
    side_u = (side or "").upper()
    best: Optional[Dict[str, Any]] = None
    best_score = float("inf")
    for row in state.get("cycle_grid_fills_archive") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("cycle_id") or 0) != int(cycle_id):
            continue
        if (row.get("side") or "").upper() != side_u:
            continue
        try:
            rq = float(row.get("qty") or 0)
            rp = float(row.get("fill_price") or row.get("execution_price") or 0)
        except (TypeError, ValueError):
            continue
        if abs(rq - qf) > max(1e-6, qf * 1e-4):
            continue
        score = abs(rp - pf) if rp > 0 else 0.0
        if score < best_score:
            best_score = score
            best = row
    return best if best_score <= max(0.5, pf * 0.02) else None


def _resolve_trade_grid_index(
    t: Dict[str, Any],
    trades: List[Dict[str, Any]],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    side: str,
) -> int:
    try:
        if t.get("slot_id") is not None:
            idx = int(t.get("slot_id"))
            if idx >= 0:
                return idx
    except (TypeError, ValueError):
        pass
    archived = _archive_lookup_trade(
        state, cycle_id, side, t.get("qty"), t.get("price")
    )
    if archived and archived.get("grid_index") is not None:
        return int(archived["grid_index"])
    cur_cid = int(state.get("cycle_id") or 1) if state else None
    if state and cur_cid is not None and int(cur_cid) == int(cycle_id):
        hist_key = "sell_history" if side == "SELL" else "buy_history"
        try:
            tq = float(t.get("qty") or 0)
            float(t.get("price") or 0)
        except (TypeError, ValueError):
            tq = 0.0
        for h in reversed(state.get(hist_key) or []):
            if not isinstance(h, dict):
                continue
            gi = h.get("grid_index")
            if gi is None:
                continue
            try:
                if abs(float(h.get("qty") or 0) - tq) <= max(1e-6, tq * 1e-4):
                    return int(gi)
            except (TypeError, ValueError):
                continue
    peers = [
        x
        for x in trades
        if (x.get("side") or "").upper() == side and _is_grid_trade_row(x)
    ]
    peers.sort(key=lambda x: str(x.get("ts") or ""))
    for i, p in enumerate(peers):
        if (
            p is t
            or (p.get("id") is not None and p.get("id") == t.get("id"))
            or (p.get("order_id") and p.get("order_id") == t.get("order_id"))
        ):
            try:
                if p.get("slot_id") is not None and int(p.get("slot_id")) >= 0:
                    return int(p.get("slot_id"))
            except (TypeError, ValueError):
                pass
            return i
    return -1


def _extreme_from_execution(
    side: str, exec_p: float, trail_pct: float
) -> Optional[float]:
    if exec_p <= 0 or trail_pct <= 0:
        return None
    try:
        if side == "SELL":
            denom = 1.0 - trail_pct / 100.0
            return exec_p / denom if denom > 0 else None
        return exec_p / (1.0 + trail_pct / 100.0)
    except (ZeroDivisionError, ValueError):
        return None


def _archive_lookup(
    state: Optional[Dict[str, Any]], cycle_id: int, grid_index: int, side: str
) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    side_u = (side or "").upper()
    for row in state.get("cycle_grid_fills_archive") or []:
        if not isinstance(row, dict):
            continue
        if (
            int(row.get("cycle_id") or 0) == int(cycle_id)
            and int(row.get("grid_index") or -1) == int(grid_index)
            and (row.get("side") or "").upper() == side_u
        ):
            return row
    return None


def _state_grid_arrays(
    state: Dict[str, Any], side: str, idx: int
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if side == "SELL":
        trigs = state.get("sell_grid_trigger_price") or []
        exts = state.get("sell_grid_peak_price") or []
        fills = state.get("sell_grid_fill_price") or []
    else:
        trigs = state.get("buy_grid_trigger_price") or []
        exts = state.get("buy_grid_trough_price") or []
        fills = state.get("buy_grid_fill_price") or []
    trig = trigs[idx] if idx < len(trigs) else None
    ext = exts[idx] if idx < len(exts) else None
    exec_p = fills[idx] if idx < len(fills) else None

    def _sf(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return _sf(trig), _sf(ext), _sf(exec_p)


def _enrich_trades_grid_detail(
    trades: List[Dict[str, Any]],
    config_raw: Dict[str, Any],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
) -> None:
    """Tur işlemleri listesine grid modal alanları ekle (mutates trades in place)."""
    cfg = _config_for_grid_view(config_raw)
    sell_grids = cfg.get("sell_grids") or (cfg.get("up") or {}).get("grids") or []
    buy_grids = cfg.get("buy_grids") or (cfg.get("down") or {}).get("grids") or []
    trail_sell = _trail_pct_for_side(cfg, "SELL")
    trail_buy = _trail_pct_for_side(cfg, "BUY")
    cur_cid = int(state.get("cycle_id") or 1) if state else None
    cycle_ref: Optional[float] = None
    for t in trades:
        if not _is_grid_trade_row(t):
            continue
        side = (t.get("side") or "").upper()
        idx = _resolve_trade_grid_index(t, trades, state, cycle_id, side)
        if idx < 0:
            continue
        if t.get("slot_id") is None:
            t["slot_id"] = idx
        grids = sell_grids if side == "SELL" else buy_grids
        gcfg = grids[idx] if idx < len(grids) and isinstance(grids[idx], dict) else {}
        grid_pct = _grid_pct_from_config(gcfg, side)
        if side == "SELL":
            qty_pct = _grid_qty_pct_display(
                gcfg.get("sell_qty_pct_of_base") or gcfg.get("qty_pct")
            )
        else:
            qty_pct = _grid_qty_pct_display(
                gcfg.get("buy_qty_pct_of_quote") or gcfg.get("qty_pct")
            )
        trail_pct = trail_sell if side == "SELL" else trail_buy
        trig: Optional[float] = None
        extreme: Optional[float] = None
        exec_p: Optional[float] = None
        archived = _archive_lookup(state, cycle_id, idx, side) or _archive_lookup_trade(
            state, cycle_id, side, t.get("qty"), t.get("price")
        )
        if archived:
            trig = archived.get("trigger_price")
            extreme = archived.get("extreme_price")
            exec_p = archived.get("execution_price")
        if state and cur_cid == int(cycle_id):
            fired_list = (
                state.get("sell_grid_fired")
                if side == "SELL"
                else state.get("buy_grid_fired")
            )
            if (
                isinstance(fired_list, list)
                and idx < len(fired_list)
                and fired_list[idx]
            ):
                t_trig, t_ext, t_exec = _state_grid_arrays(state, side, idx)
                trig = trig if trig is not None else t_trig
                extreme = extreme if extreme is not None else t_ext
                exec_p = exec_p if exec_p is not None else t_exec
            hist_key = "sell_history" if side == "SELL" else "buy_history"
            for h in reversed(state.get(hist_key) or []):
                if not isinstance(h, dict) or int(h.get("grid_index") or -1) != idx:
                    continue
                try:
                    if abs(float(h.get("qty") or 0) - float(t.get("qty") or 0)) > 1e-6:
                        continue
                except (TypeError, ValueError):
                    pass
                if h.get("execution_price") is not None and exec_p is None:
                    try:
                        exec_p = float(h["execution_price"])
                    except (TypeError, ValueError):
                        pass
                break
        if cycle_ref is None:
            try:
                cycle_ref = float(t.get("reference_price") or 0) or None
            except (TypeError, ValueError):
                cycle_ref = None
        ref_p = cycle_ref
        if ref_p is None:
            try:
                ref_p = float(t.get("reference_price") or 0) or None
            except (TypeError, ValueError):
                ref_p = None
        if trig is None and grid_pct is not None and cycle_ref and cycle_ref > 0:
            trig = (
                cycle_ref * (1 + grid_pct / 100.0)
                if side == "SELL"
                else cycle_ref * (1 - grid_pct / 100.0)
            )
        if ref_p is None and state and int(state.get("cycle_id") or 0) == int(cycle_id):
            try:
                ref_p = float(state.get("reference_price") or 0) or None
            except (TypeError, ValueError):
                ref_p = None
        trigger_level: Optional[float] = None
        if ref_p and ref_p > 0 and grid_pct is not None:
            trigger_level = (
                ref_p * (1 + float(grid_pct) / 100.0)
                if side == "SELL"
                else ref_p * (1 - float(grid_pct) / 100.0)
            )
        if trigger_level is not None:
            trig = trigger_level
        trigger_hit: Optional[float] = None
        fill_p = t.get("price")
        try:
            fill_f = float(fill_p) if fill_p is not None else None
        except (TypeError, ValueError):
            fill_f = None
        if fill_f is not None:
            exec_p = fill_f
        extreme_basis = fill_f if fill_f is not None else exec_p
        if extreme is None and extreme_basis is not None and trail_pct is not None:
            extreme = _extreme_from_execution(
                side, float(extreme_basis), float(trail_pct)
            )
        avg_buy_p: Optional[float] = None
        avg_buy_quote: Optional[float] = None
        if side == "SELL":
            avg_buy_p, avg_buy_quote = _avg_buy_price_for_grid_sell(
                state, cycle_id, trades
            )
        elif side == "BUY" and fill_f is not None:
            avg_buy_p = fill_f
            avg_buy_quote = (
                (fill_f * float(t.get("qty") or 0))
                if t.get("qty") is not None
                else None
            )
        grid_side_label = "Grid satış" if side == "SELL" else "Grid alım"
        display_label = f"{grid_side_label} #{idx + 1}"
        t["grid_detail"] = {
            "grid_index": idx,
            "grid_label": f"Grid #{idx + 1}",
            "display_label": display_label,
            "grid_type": "Satış gridi" if side == "SELL" else "Alış gridi",
            "side": side,
            "grid_pct": grid_pct,
            "qty_pct": qty_pct,
            "trailing_pct": trail_pct,
            "trigger_price": round(trig, 8) if trig is not None else None,
            "trigger_level_price": round(trigger_level, 8)
            if trigger_level is not None
            else None,
            "trigger_hit_price": round(trigger_hit, 8)
            if trigger_hit is not None
            else None,
            "trigger_pct_basis": "reference_price",
            "extreme_price": round(extreme, 8) if extreme is not None else None,
            "execution_price": round(exec_p, 8) if exec_p is not None else None,
            "reference_price": round(ref_p, 8) if ref_p is not None else None,
            "extreme_pct_from_reference": round(
                (float(extreme) / ref_p - 1.0) * 100.0, 4
            )
            if extreme is not None and ref_p
            else None,
            "completion_pct_from_reference": round(
                (float(exec_p) / ref_p - 1.0) * 100.0, 4
            )
            if exec_p is not None and ref_p
            else None,
            "completion_pct_from_extreme": round(
                (float(exec_p) / float(extreme) - 1.0) * 100.0, 4
            )
            if exec_p is not None and extreme
            else None,
            "average_buy_price": round(avg_buy_p, 8) if avg_buy_p is not None else None,
            "average_buy_quote_usdt": round(float(avg_buy_quote), 2)
            if avg_buy_quote is not None
            else None,
            "extreme_label": "Tepe fiyat" if side == "SELL" else "Dip fiyat",
        }


def _resolve_trade_reason(t: Dict[str, Any]) -> str:
    reason = (t.get("reason") or "").strip().lower()
    if reason:
        return reason
    cid = (t.get("client_order_id") or "").lower()
    if "profit_exit" in cid:
        return "trail_profit_sell"
    if "reentry" in cid:
        return "trail_reentry_buy"
    return reason


def _is_cycle_close_trade_row(t: Dict[str, Any]) -> bool:
    if t.get("trade_detail"):
        return True
    if t.get("is_cycle_close"):
        return True
    reason = _resolve_trade_reason(t)
    return reason in ("trail_profit_sell", "trail_reentry_buy")


def _profit_params_from_config(
    cfg: Dict[str, Any], trade_type: str
) -> Tuple[Optional[float], Optional[float]]:
    profit = cfg.get("profit") or {}
    try:
        if trade_type == "profit_exit":
            rise = cfg.get("profit_exit_rise_pct") or profit.get("resell_trigger_pct")
            drop = cfg.get("profit_exit_drop_pct") or profit.get("resell_trail_pct")
        else:
            rise = cfg.get("profit_reentry_drop_pct") or profit.get("rebuy_trigger_pct")
            drop = cfg.get("profit_reentry_rise_pct") or profit.get("rebuy_trail_pct")
        return (
            round(float(rise), 4) if rise is not None else None,
            round(float(drop), 4) if drop is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def _ledger_archive_block(
    state: Optional[Dict[str, Any]], cycle_id: int
) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    for block in state.get("cycle_ledger_fills_archive") or []:
        if isinstance(block, dict) and int(block.get("cycle_id") or 0) == int(cycle_id):
            return block
    return None


def _grid_cost_totals(
    rows: List[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float]]:
    """(ortalama fiyat, toplam quote USDT)"""
    if not rows:
        return None, None
    try:
        tq = sum(float(r.get("qty") or 0) for r in rows)
        if tq <= 0:
            return None, None
        tv = sum(float(r.get("qty") or 0) * float(r.get("price") or 0) for r in rows)
        return tv / tq, tv
    except (TypeError, ValueError):
        return None, None


def _avg_buy_price_for_grid_sell(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Satış gridi modalı: tur içi ortalama alım maliyeti (USDT/base)."""
    if state:
        cid = int(cycle_id)
        ledger = None
        if int(state.get("cycle_id") or 0) == cid:
            ledger = state.get("cycle_ledger_current")
        if not ledger:
            ledger = _ledger_archive_block(state, cid)
        if isinstance(ledger, dict):
            try:
                avg = ledger.get("avg_cost_quote_per_base")
                if avg is not None and float(avg) > 0:
                    bq = ledger.get("buy_quote_total")
                    return float(avg), (float(bq) if bq is not None else None)
            except (TypeError, ValueError):
                pass
        try:
            init_q = float(state.get("initial_alloc_base_qty") or 0)
            init_p = float(state.get("initial_alloc_price") or 0)
            if init_q > 0 and init_p > 0:
                return init_p, init_q * init_p
        except (TypeError, ValueError):
            pass
    avg, quote = _cost_basis_for_close_trade(state, cycle_id, "profit_exit", trades)
    return avg, quote


def _avg_grid_cost_from_ledger_fills(
    fills: List[Dict[str, Any]], trade_type: str
) -> Optional[float]:
    avg, _ = _grid_cost_totals_from_ledger_fills(fills, trade_type)
    return avg


def _grid_cost_totals_from_ledger_fills(
    fills: List[Dict[str, Any]],
    trade_type: str,
) -> Tuple[Optional[float], Optional[float]]:
    if trade_type == "profit_exit":
        reason, side = "trail_buy_grid", "BUY"
    else:
        reason, side = "trail_sell_grid", "SELL"
    rows = [
        f
        for f in fills
        if isinstance(f, dict)
        and (f.get("reason") or "") == reason
        and (f.get("side") or "").upper() == side
    ]
    return _grid_cost_totals(rows)


def _cost_basis_for_close_trade(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    trade_type: str,
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Ortalama maliyet ve grid bazlı toplam harcanan/kazanılan quote (USDT)."""
    if state:
        if trade_type == "profit_exit":
            hist = [
                h
                for h in (state.get("buy_history") or [])
                if isinstance(h, dict) and h.get("grid_index") is not None
            ]
        else:
            hist = [
                h
                for h in (state.get("sell_history") or [])
                if isinstance(h, dict) and h.get("grid_index") is not None
            ]
        avg, quote = _grid_cost_totals(hist)
        if avg is not None:
            return avg, quote
        block = _ledger_archive_block(state, cycle_id)
        if block:
            fills = block.get("fills") or []
            avg, quote = _grid_cost_totals_from_ledger_fills(fills, trade_type)
            if avg is not None:
                return avg, quote
            try:
                stored = block.get("avg_cost_quote_per_base")
                if trade_type == "profit_exit":
                    quote_key = "buy_quote_total"
                else:
                    quote_key = "sell_quote_total"
                buy_quote = block.get(quote_key)
                if stored is not None and float(stored) > 0 and buy_quote is not None:
                    return float(stored), float(buy_quote)
            except (TypeError, ValueError):
                pass
    if trades:
        grid_side = "BUY" if trade_type == "profit_exit" else "SELL"
        grid_rows = [
            x
            for x in trades
            if (x.get("side") or "").upper() == grid_side and _trade_has_grid_slot(x)
        ]
        avg, quote = _grid_cost_totals(grid_rows)
        if avg is not None:
            return avg, quote
    return None, None


def _avg_cost_for_close_trade(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    trade_type: str,
) -> Optional[float]:
    if not state:
        return None
    from app.botengine.strategies.dca_grid_trailing import (
        _avg_buy_grid_from_history,
        _avg_sell_grid_from_history,
    )

    if trade_type == "profit_exit":
        avg = _avg_buy_grid_from_history(state.get("buy_history") or [])
    else:
        avg = _avg_sell_grid_from_history(state.get("sell_history") or [])
    if avg is not None:
        return float(avg)
    block = _ledger_archive_block(state, cycle_id)
    if not block:
        return None
    try:
        stored = block.get("avg_cost_quote_per_base")
        if stored is not None and float(stored) > 0:
            return float(stored)
    except (TypeError, ValueError):
        pass
    fills = block.get("fills") or []
    avg = _avg_grid_cost_from_ledger_fills(fills, trade_type)
    if avg is not None:
        return avg
    return None


def _lookup_close_archive(
    state: Optional[Dict[str, Any]],
    cycle_id: int,
    reason: str,
    side: str,
    qty: Any,
    price: Any,
) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    try:
        qf = float(qty or 0)
        pf = float(price or 0)
    except (TypeError, ValueError):
        return None
    side_u = (side or "").upper()
    reason_l = (reason or "").lower()
    best: Optional[Dict[str, Any]] = None
    best_score = float("inf")
    for row in state.get("cycle_close_trades_archive") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("cycle_id") or 0) != int(cycle_id):
            continue
        if (row.get("reason") or "").lower() != reason_l:
            continue
        if (row.get("side") or "").upper() != side_u:
            continue
        rq = float(row.get("qty") or 0)
        rp = float(row.get("fill_price") or row.get("execution_price") or 0)
        if qf > 0 and abs(rq - qf) > max(1e-6, qf * 1e-4):
            continue
        score = abs(rp - pf) if rp > 0 and pf > 0 else 0.0
        if score < best_score:
            best_score = score
            best = row
    if best is None:
        matches = [
            row
            for row in (state.get("cycle_close_trades_archive") or [])
            if isinstance(row, dict)
            and int(row.get("cycle_id") or 0) == int(cycle_id)
            and (row.get("reason") or "").lower() == reason_l
        ]
        if len(matches) == 1:
            return matches[0]
    if best is None:
        return None
    if pf <= 0 or best_score <= max(0.5, pf * 0.02):
        return best
    return None


def _breakeven_from_avg(
    avg_cost: Optional[float], cfg: Dict[str, Any]
) -> Optional[float]:
    if avg_cost is None or avg_cost <= 0:
        return None
    try:
        buy_fee = float(cfg.get("buy_fee_rate") or 0.001)
        sell_fee = float(cfg.get("sell_fee_rate") or 0.001)
        denom = 1.0 - sell_fee
        if denom <= 0:
            return None
        return round(avg_cost * (1.0 + buy_fee) / denom, 8)
    except (TypeError, ValueError):
        return None


def _close_trade_fill_price(
    t: Dict[str, Any],
    close_fill: Dict[str, Any],
    archived: Optional[Dict[str, Any]],
) -> Optional[float]:
    """Binance fill (gerçekleşen) — trail eşiği değil."""
    arch = archived if isinstance(archived, dict) else {}
    for raw in (
        close_fill.get("price"),
        t.get("price"),
        arch.get("fill_price"),
        arch.get("price"),
    ):
        if raw is None:
            continue
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _close_trade_trail_execution_price(
    close_fill: Dict[str, Any],
    archived: Optional[Dict[str, Any]],
) -> Optional[float]:
    """Trailing gerçekleşme eşiği (canlı/grid); dolu işlemde UI fill gösterir."""
    arch = archived if isinstance(archived, dict) else {}
    for raw in (arch.get("execution_price"), close_fill.get("execution_price")):
        if raw is None:
            continue
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _enrich_trades_close_detail(
    trades: List[Dict[str, Any]],
    config_raw: Dict[str, Any],
    state: Optional[Dict[str, Any]],
    cycle_id: int,
) -> None:
    """Kar satışı / kar alımı işlemlerine modal alanları ekle."""
    cfg = _config_for_grid_view(config_raw)
    for t in trades:
        if not _is_cycle_close_trade_row(t):
            continue
        reason = _resolve_trade_reason(t)
        if reason not in ("trail_profit_sell", "trail_reentry_buy"):
            continue
        trade_type = "profit_exit" if reason == "trail_profit_sell" else "reentry"
        side = (
            t.get("side") or ("SELL" if trade_type == "profit_exit" else "BUY")
        ).upper()
        trigger_pct, trailing_pct = _profit_params_from_config(cfg, trade_type)
        pnl_entry = _cycle_pnl_entry(state, cycle_id)
        close_fill = (
            (pnl_entry or {}).get("close_fill")
            if isinstance((pnl_entry or {}).get("close_fill"), dict)
            else {}
        )
        archived = _lookup_close_archive(
            state, cycle_id, reason, side, t.get("qty"), t.get("price")
        )
        avg_cost = archived.get("average_cost") if archived else None
        avg_quote: Optional[float] = None
        trigger = archived.get("trigger_price") if archived else None
        tepe = archived.get("tepe_price") if archived else None
        dip = archived.get("dip_price") if archived else None
        fill_p = _close_trade_fill_price(t, close_fill, archived)
        trail_exec_p = _close_trade_trail_execution_price(close_fill, archived)
        if close_fill:
            if (
                trade_type == "profit_exit"
                and avg_cost is None
                and close_fill.get("avg_cost_quote_per_base") is not None
            ):
                try:
                    avg_cost = float(close_fill["avg_cost_quote_per_base"])
                except (TypeError, ValueError):
                    pass
            if (
                trade_type == "reentry"
                and avg_cost is None
                and close_fill.get("avg_sell_grid_quote_per_base") is not None
            ):
                try:
                    avg_cost = float(close_fill["avg_sell_grid_quote_per_base"])
                except (TypeError, ValueError):
                    pass
            if tepe is None and close_fill.get("tepe_price") is not None:
                try:
                    tepe = float(close_fill["tepe_price"])
                except (TypeError, ValueError):
                    pass
            if dip is None and close_fill.get("dip_price") is not None:
                try:
                    dip = float(close_fill["dip_price"])
                except (TypeError, ValueError):
                    pass
        exec_p = fill_p if fill_p is not None else trail_exec_p
        if state and int(state.get("cycle_id") or 1) == int(cycle_id):
            if trade_type == "profit_exit" and state.get("_profit_exit_done"):
                anchor = state.get("trail_anchor_price")
                if tepe is None and anchor is not None:
                    try:
                        tepe = float(anchor)
                    except (TypeError, ValueError):
                        pass
            if trade_type == "reentry" and state.get("_reentry_done"):
                anchor = state.get("trail_anchor_price")
                if dip is None and anchor is not None:
                    try:
                        dip = float(anchor)
                    except (TypeError, ValueError):
                        pass
        basis_avg, basis_quote = _cost_basis_for_close_trade(
            state, cycle_id, trade_type, trades
        )
        if avg_cost is None and basis_avg is not None:
            avg_cost = basis_avg
        if avg_quote is None and basis_quote is not None:
            avg_quote = basis_quote
        if avg_cost is not None and trigger_pct is not None:
            if trade_type == "profit_exit":
                trigger = float(avg_cost) * (1.0 + float(trigger_pct) / 100.0)
            else:
                trigger = float(avg_cost) * (1.0 - float(trigger_pct) / 100.0)
        extreme_basis = fill_p if fill_p is not None else exec_p
        if trade_type == "profit_exit":
            if (
                tepe is None
                and extreme_basis is not None
                and trailing_pct is not None
                and trailing_pct > 0
            ):
                tepe = _extreme_from_execution(
                    "SELL", float(extreme_basis), float(trailing_pct)
                )
        else:
            if (
                dip is None
                and extreme_basis is not None
                and trailing_pct is not None
                and trailing_pct > 0
            ):
                dip = _extreme_from_execution(
                    "BUY", float(extreme_basis), float(trailing_pct)
                )
        label = "Kar satışı" if trade_type == "profit_exit" else "Kar alımı"
        pnl_net = (pnl_entry or {}).get("pnl_usdt_net")
        inv_adv = (pnl_entry or {}).get("inventory_coin_adv_qty")
        if t.get("reference_price") is None:
            cycle_ref = _resolve_cycle_reference_price(state, cycle_id, trades)
            if cycle_ref is not None and cycle_ref > 0:
                t["reference_price"] = round(cycle_ref, 10)
        t["trade_detail"] = {
            "trade_type": trade_type,
            "label": label,
            "side": side,
            "trigger_pct": trigger_pct,
            "trailing_pct": trailing_pct,
            "average_cost": round(float(avg_cost), 8) if avg_cost is not None else None,
            "average_cost_quote_usdt": round(float(avg_quote), 2)
            if avg_quote is not None
            else None,
            "trigger_price": round(float(trigger), 8) if trigger is not None else None,
            "tepe_price": round(float(tepe), 8) if tepe is not None else None,
            "dip_price": round(float(dip), 8) if dip is not None else None,
            "fill_price": round(float(fill_p), 8) if fill_p is not None else None,
            "execution_price": round(float(fill_p), 8)
            if fill_p is not None
            else (round(float(trail_exec_p), 8) if trail_exec_p is not None else None),
            "completion_pct_from_cost": round(
                (float(exec_p) / float(avg_cost) - 1.0) * 100.0, 4
            )
            if exec_p is not None and avg_cost is not None and float(avg_cost) > 0
            else None,
            "completion_pct_from_extreme": round(
                (float(exec_p) / float(tepe if trade_type == "profit_exit" else dip) - 1.0)
                * 100.0,
                4,
            )
            if exec_p is not None
            and (tepe if trade_type == "profit_exit" else dip) is not None
            and float(tepe if trade_type == "profit_exit" else dip) > 0
            else None,
            "trail_execution_price": round(float(trail_exec_p), 8)
            if trail_exec_p is not None
            else None,
            "realized_profit_usdt": round(float(pnl_net), 4)
            if pnl_net is not None
            else None,
            "inventory_coin_adv_qty": round(float(inv_adv), 8)
            if inv_adv is not None
            else None,
        }


@router.get("/{bot_id}/trades")
async def bots_trades(
    request: Request,
    bot_id: int,
    limit: int = Query(50, le=200),
    cycle_id: Optional[int] = Query(
        None, description="Filter by tur/round; omit for all"
    ),
    cycle_type: Optional[str] = Query(None, description="dca or trb; TRDCA only"),
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List trades for bot, optionally for a single cycle (tur). TRDCA: cycle_type=dca|trb."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )
    from app.bot.ledger import Ledger

    ct = (cycle_type or "dca").strip().lower()
    if ct == "trb":
        trades = []
    else:
        trades = Ledger.get_trades_dict(
            db, bot.id, bot.account_id, limit=limit, cycle_id=cycle_id
        )
    cycle_summary: Optional[Dict[str, Any]] = None
    state = load_state(db, bot.id) if cycle_id is not None else None
    if state:
        _heal_cycle_opened_at_state(db, bot, state)
    sym = (bot.symbol or "").upper()
    raw_config_for_repair = json.loads(bot.config_json or "{}")
    live_price_for_repair = _resolve_bot_live_price(sym, state) if state else None
    if state:
        _repair_bot_state_reference_if_needed(
            db, bot, state, raw_config_for_repair, live_price_for_repair
        )
    extra: List[Dict[str, Any]] = []
    if cycle_id is not None and ct != "trb" and state:
        cur_cid = int(state.get("cycle_id") or 1)
        if cur_cid == int(cycle_id):
            ledger = state.get("cycle_ledger_current") or {}
            if isinstance(ledger, dict) and (
                not ledger.get("symbol") or ledger.get("symbol") == sym
            ):
                extra.extend(
                    _ledger_fills_to_trade_dicts(
                        ledger.get("fills") or [], sym, int(cycle_id)
                    )
                )
        for block in state.get("cycle_ledger_fills_archive") or []:
            if not isinstance(block, dict):
                continue
            if int(block.get("cycle_id") or 0) != int(cycle_id):
                continue
            arch_fills = block.get("fills") or []
            _backfill_trades_from_ledger_fills(db, bot, arch_fills, int(cycle_id), sym)
            extra.extend(_ledger_fills_to_trade_dicts(arch_fills, sym, int(cycle_id)))
    if cycle_id is not None and ct != "trb":
        trades = _merge_cycle_trades(trades, extra)
        if extra:
            trades = Ledger.get_trades_dict(
                db, bot.id, bot.account_id, limit=limit, cycle_id=cycle_id
            )
            trades = _merge_cycle_trades(trades, extra)
        trades = _sanitize_trades_for_bot_symbol(trades, sym)
        if state and int(state.get("cycle_id") or 1) == int(cycle_id) and not trades:
            synth = _synthetic_trades_from_state(state, sym, int(cycle_id))
            if synth:
                trades = _merge_cycle_trades(trades, synth)
                trades = _sanitize_trades_for_bot_symbol(trades, sym)
    if cycle_id is not None and ct == "trb":
        cycle_summary = {
            "cycle_type": "trb",
            "trade_count": 0,
            "note": "Rebalancing tur işlemleri ayrı kaydedilmiyor.",
        }
    elif cycle_id is not None:
        ts_list: List[datetime] = []
        for t in trades:
            dt = _parse_ts_utc(t.get("ts"))
            if dt is not None:
                ts_list.append(dt)
        is_open_cycle = state is not None and int(state.get("cycle_id") or 1) == int(
            cycle_id
        )
        duration_sec = 0.0
        started_at_iso: Optional[str] = None
        completed_snapshot: Optional[Dict[str, Any]] = None
        completed_snapshot_side: Optional[str] = None
        if state and isinstance(state.get("completed_cycle_dual_pnls"), list):
            for c in state["completed_cycle_dual_pnls"]:
                if isinstance(c, dict) and int(c.get("cycle_id") or 0) == int(cycle_id):
                    completed_snapshot = c
                    break
        if is_open_cycle:
            from app.botengine.cycle_ledger import resolve_cycle_opened_at_for_cycle

            started_at_iso = resolve_cycle_opened_at_for_cycle(state, int(cycle_id))
            start_dt = _parse_ts_utc(started_at_iso)
            if start_dt is not None:
                duration_sec = max(
                    0.0, (datetime.now(timezone.utc) - start_dt).total_seconds()
                )
        elif completed_snapshot:
            started_at_iso = completed_snapshot.get("started_at")
            start_dt = _parse_ts_utc(started_at_iso)
            end_dt = _parse_ts_utc(completed_snapshot.get("completed_at"))
            if start_dt is not None and end_dt is not None:
                duration_sec = max(0.0, (end_dt - start_dt).total_seconds())
            elif len(ts_list) >= 2:
                try:
                    duration_sec = (max(ts_list) - min(ts_list)).total_seconds()
                except Exception as e:
                    logger.warning(
                        "bots_trades duration_sec failed bot_id=%s cycle_id=%s: %s",
                        bot.id,
                        cycle_id,
                        e,
                    )
            from app.services.bot_performance_service import _completed_cycle_side

            snap_side = _completed_cycle_side(completed_snapshot)
            if snap_side in ("SELL", "BUY"):
                completed_snapshot_side = snap_side
        elif len(ts_list) >= 2:
            try:
                duration_sec = (max(ts_list) - min(ts_list)).total_seconds()
            except Exception as e:
                logger.warning(
                    "bots_trades duration_sec failed bot_id=%s cycle_id=%s: %s",
                    bot.id,
                    cycle_id,
                    e,
                )
        pnl_usdt = None
        cycle_entry = None
        if state and isinstance(state.get("cycle_pnls"), list):
            for c in state["cycle_pnls"]:
                if not isinstance(c, dict):
                    continue
                if c.get("cycle_id") == cycle_id:
                    pnl_usdt = c.get("pnl_usdt")
                    cycle_entry = c
                    break

        def _safe_float(v: Any) -> Optional[float]:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        pnl_f = _safe_float(pnl_usdt)
        cycle_summary = {
            "cycle_type": "Açık tur"
            if is_open_cycle and cycle_entry is None
            else "dca",
            "is_open": bool(is_open_cycle),
            "completed": not bool(is_open_cycle),
            "duration_sec": round(duration_sec, 1) if duration_sec else None,
            "trade_count": sum(1 for t in trades if _is_cycle_trades_panel_row(t)),
            "pnl_usdt": round(pnl_f, 2) if pnl_f is not None else None,
        }
        if started_at_iso:
            cycle_summary["started_at"] = started_at_iso
        if completed_snapshot and completed_snapshot.get("completed_at"):
            cycle_summary["completed_at"] = completed_snapshot.get("completed_at")
        if completed_snapshot and isinstance(
            completed_snapshot.get("cycle_parameters"), dict
        ):
            cycle_summary["cycle_parameters"] = completed_snapshot.get(
                "cycle_parameters"
            )
            cycle_summary["dynamic_regime"] = completed_snapshot.get(
                "dynamic_regime"
            )
        elif not is_open_cycle and (
            int(cycle_id) == 1
            or not parse_bool(raw_config_for_repair.get("dynamic_mode"))
        ):
            # Dinamik mod ilk turda bilinçli olarak devreye girmez; dolayısıyla
            # eski Tur 1 kayıtlarında snapshot bulunmayabilir. Tur 1'in gerçek
            # parametreleri botun değişmez başlangıç yapılandırmasıdır. Sabit
            # modda da bütün turlar aynı yapılandırmayı kullanır.
            cycle_summary["cycle_parameters"] = raw_config_for_repair
            cycle_summary["parameter_source"] = (
                "initial_cycle_config"
                if int(cycle_id) == 1
                else "static_bot_config"
            )
        elif is_open_cycle and state:
            dynamic_snapshot = state.get("dynamic_snapshot")
            current_parameters = None
            current_regime = None
            if isinstance(dynamic_snapshot, dict):
                snapshot_cycle_id = int(
                    dynamic_snapshot.get("cycle_id") or state.get("cycle_id") or 0
                )
                if snapshot_cycle_id == int(cycle_id):
                    applied = dynamic_snapshot.get("applied")
                    if isinstance(applied, dict) and applied:
                        current_parameters = applied
                    current_regime = dynamic_snapshot.get("regime")
            if current_parameters is None:
                frozen = state.get("_dynamic_reference")
                if isinstance(frozen, dict) and frozen:
                    current_parameters = frozen
            if current_parameters is None and isinstance(raw_config_for_repair, dict):
                # İlk tur ve sabit modda dinamik snapshot henüz oluşmaz. İşlemler
                # ekranı yine de aktif turun gerçekten kullandığı bot ayarlarını
                # (özellikle alış/satış grid dizilerini) göstermelidir.
                current_parameters = raw_config_for_repair
            if current_parameters:
                cycle_summary["cycle_parameters"] = current_parameters
                cycle_summary["dynamic_regime"] = current_regime
        if cycle_entry is not None:
            cycle_summary["cycle_type"] = cycle_entry.get("cycle_type") or "dca"
            cycle_summary["pnl_primary_mode"] = cycle_entry.get("pnl_primary_mode")
            cycle_summary["inventory_coin_adv_qty"] = cycle_entry.get(
                "inventory_coin_adv_qty"
            )
            cycle_summary["inventory_fees_usdt"] = cycle_entry.get(
                "inventory_fees_usdt"
            )
            cycle_summary["cash_pnl_usdt"] = cycle_entry.get("cash_pnl_usdt")
            cycle_summary["cash_fees_usdt"] = cycle_entry.get("cash_fees_usdt")
            cycle_summary["close_reason"] = cycle_entry.get("close_reason")
        elif is_open_cycle:
            ledger = state.get("cycle_ledger_current") or {}
            if isinstance(ledger, dict):
                cycle_summary["cash_pnl_usdt"] = (
                    ledger.get("cash_fifo_pnl_usdt")
                    if ledger.get("cash_fifo_pnl_usdt") is not None
                    else ledger.get("cash_pnl_usdt")
                )
                cycle_summary["cash_fees_usdt"] = (
                    ledger.get("cash_fifo_fees_usdt")
                    if ledger.get("cash_fifo_fees_usdt") is not None
                    else ledger.get("cash_fees_usdt")
                )
                cycle_summary["inventory_coin_adv_qty"] = ledger.get(
                    "inventory_coin_adv_qty"
                )
                cycle_summary["inventory_fees_usdt"] = ledger.get("inventory_fees_usdt")
            from app.botengine.strategies.dca_grid_trailing import infer_cycle_grid_side

            side = infer_cycle_grid_side(state)
            if side in ("SELL", "BUY"):
                cycle_summary["cycle_grid_side"] = side
        if cycle_entry is not None and not cycle_summary.get("cycle_grid_side"):
            ct = cycle_entry.get("cycle_type") or ""
            if ct == "LONG_SCALP":
                cycle_summary["cycle_grid_side"] = "BUY"
            elif ct == "INVENTORY_REBALANCE":
                cycle_summary["cycle_grid_side"] = "SELL"
            else:
                from app.services.bot_performance_service import _completed_cycle_side

                entry_side = _completed_cycle_side(cycle_entry)
                if entry_side in ("SELL", "BUY"):
                    cycle_summary["cycle_grid_side"] = entry_side
        if completed_snapshot_side and not cycle_summary.get("cycle_grid_side"):
            cycle_summary["cycle_grid_side"] = completed_snapshot_side
        if not is_open_cycle:
            result_kind = None
            result_amount = None
            result_unit = None
            result_pct = None
            source = cycle_entry or completed_snapshot or {}
            close_reason = str(
                source.get("close_reason")
                or source.get("completed_reason")
                or ""
            )
            primary_mode = str(source.get("pnl_primary_mode") or "").lower()
            if close_reason == "trail_reentry_buy" or primary_mode in (
                "inventory_coin",
                "inventory_qty_v1",
            ):
                result_kind = "coin"
                result_amount = _safe_float(source.get("inventory_coin_adv_qty"))
                matched_qty = _safe_float(source.get("matched_qty"))
                if result_amount is not None and matched_qty and matched_qty > 0:
                    result_pct = result_amount / matched_qty * 100.0
                result_unit = sym
                for quote_suffix in ("USDT", "USDC", "FDUSD", "BUSD"):
                    if result_unit.endswith(quote_suffix):
                        result_unit = result_unit[: -len(quote_suffix)]
                        break
            else:
                result_kind = "quote"
                result_amount = _safe_float(source.get("pnl_usdt_net"))
                if result_amount is None:
                    gross = _safe_float(source.get("cash_pnl_usdt"))
                    fees = _safe_float(source.get("cash_fees_usdt"))
                    if gross is not None:
                        result_amount = gross - (fees or 0.0)
                result_unit = "USDT"
                config_initial_for_cycle = float(
                    raw_config_for_repair.get("initial_capital_usdt")
                    or raw_config_for_repair.get("budget_usd")
                    or raw_config_for_repair.get("bot_budget_quote")
                    or 0
                )
                if (
                    result_amount is not None
                    and config_initial_for_cycle > 0
                ):
                    result_pct = result_amount / config_initial_for_cycle * 100.0
            cycle_summary["result_kind"] = result_kind
            cycle_summary["result_amount"] = (
                round(float(result_amount), 10)
                if result_amount is not None
                else None
            )
            cycle_summary["result_unit"] = result_unit
            cycle_summary["result_pct"] = (
                round(float(result_pct), 4) if result_pct is not None else None
            )
    if cycle_id is not None and ct != "trb" and trades:
        cfg_raw = raw_config_for_repair
        _tag_cycle_close_trades(trades, state, int(cycle_id))
        _hydrate_trades_from_cycle_ledger(trades, state, int(cycle_id))
        _repair_trade_reference_prices(
            trades, state, int(cycle_id), live_price_for_repair
        )
        _enrich_trades_reference_prices(trades, state, int(cycle_id))
        _tag_cycle_close_trades(trades, state, int(cycle_id))
        _enrich_trades_fee(trades, sym, cfg_raw)
        _enrich_trades_grid_detail(trades, cfg_raw, state, int(cycle_id))
        _enrich_trades_close_detail(trades, cfg_raw, state, int(cycle_id))
    if cycle_id is not None and cycle_summary is not None:
        cycle_reference = _resolve_cycle_reference_price(
            state, int(cycle_id), trades
        )
        cycle_summary["reference_price"] = (
            round(float(cycle_reference), 10)
            if cycle_reference is not None and float(cycle_reference) > 0
            else None
        )
    return {
        "trades": trades,
        "cycle_summary": cycle_summary,
        "cycle_type": ct,
        "request_id": rid,
    }


def _completed_cycle_side(entry: Dict[str, Any]) -> Optional[str]:
    from app.services.bot_performance_service import _completed_cycle_side as _side

    return _side(entry)


def _completed_cycle_in_period(
    entry: Dict[str, Any], start_ts: Optional[datetime]
) -> bool:
    from app.services.bot_performance_service import (
        _completed_cycle_in_period as _in_period,
    )

    return _in_period(entry, start_ts)


def _aggregate_dual_perf_closed_cycles(
    state: Optional[Dict[str, Any]],
    start_ts: Optional[datetime],
    initial_capital: float,
) -> Dict[str, Any]:
    from app.services.bot_performance_service import aggregate_dual_perf_closed_cycles

    completed = (state or {}).get("completed_cycle_dual_pnls") or []
    return aggregate_dual_perf_closed_cycles(completed, start_ts, initial_capital)


def _performance_period_range(period: str):
    """Return (start_ts, end_ts) for period. end_ts=None means now."""
    from app.services.bot_performance_service import performance_period_start_ts

    return (performance_period_start_ts(period), None)


@router.get("/{bot_id}/performance")
async def bots_performance(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    period: str = Query("all", description="all, day, week, month"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bot performance: PnL, fees, cycles (tur), chart series. Metrics filtered by period; chart always from bot start."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(
            status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid)
        )

    state_for_pnl = load_state(db, bot.id)
    sym_perf = (bot.symbol or "").strip().upper()
    perf_price_meta = _bot_price_meta(sym_perf)
    live_px_alpha = float(perf_price_meta.get("price") or 0)
    pnl_data = PnlService.calculate_bot_pnl(
        db,
        bot.id,
        bot.account_id,
        current_price=live_px_alpha or None,
        price_is_stale=bool(perf_price_meta.get("is_stale")),
    )
    if pnl_data.get("error"):
        pnl_data = {
            "total_usd": 0.0,
            "realized": 0.0,
            "unrealized": 0.0,
            "daily": 0.0,
            "monthly": 0.0,
            "current_price": 0.0,
        }

    now = datetime.now(timezone.utc)
    from app.services.bot_performance_service import (
        load_bot_closed_cycles_for_period,
        normalize_perf_period,
        resolve_perf_date_range,
    )

    perf_date_from, perf_date_to, perf_period_label = resolve_perf_date_range(
        period, bot_id=bot.id, account_id=bot.account_id
    )
    start_ts, _ = _performance_period_range(period)

    session_alpha: Optional[Dict[str, Any]] = None
    try:
        session_alpha = resolve_session_alpha_performance(
            db,
            bot,
            state_for_pnl,
            pnl_data=pnl_data,
            live_price=live_px_alpha if live_px_alpha > 0 else None,
        )
    except Exception as e:
        logger.debug("bots_performance session_alpha bot_id=%s: %s", bot.id, e)

    real_performance_pct: Optional[float] = None
    balance_change_pct: Optional[float] = None
    price_change_pct: Optional[float] = None
    if session_alpha:
        real_performance_pct = float(session_alpha.get("alpha_pct") or 0.0)
        balance_change_pct = session_alpha.get("balance_pct")
        price_change_pct = session_alpha.get("coin_pct")

    # Trades in period (grafik/legacy); metrik kartları dosyadaki kapanan turlardan
    q_trades = db.query(Trade).filter(
        Trade.bot_id == bot.id, Trade.account_id == bot.account_id
    )
    if start_ts:
        q_trades = q_trades.filter(Trade.ts >= start_ts)
    trades_in_period = q_trades.order_by(Trade.ts.asc()).all()
    trades_count = len(trades_in_period)
    fees_usd = sum(float(t.fee or 0) for t in trades_in_period)

    total_usd = float(pnl_data.get("total_usd", 0) or 0)
    realized = float(pnl_data.get("realized", 0) or 0)

    # Initial and PnL for selected period. "all" = başlangıç sermayesine göre (başlar başlamaz kar göstermemek için).
    cfg_perf = (
        json.loads(bot.config_json or "{}") if getattr(bot, "config_json", None) else {}
    )
    config_initial = float(
        cfg_perf.get("initial_capital_usdt")
        or cfg_perf.get("budget_usd")
        or cfg_perf.get("bot_budget_usdt")
        or cfg_perf.get("bot_budget_quote")
        or 0
    )

    if start_ts and trades_in_period:
        # Period start: first snapshot before start_ts or first trade in period as proxy
        first_snap = (
            db.query(PnlSnapshot)
            .filter(
                PnlSnapshot.bot_id == bot.id,
                PnlSnapshot.account_id == bot.account_id,
                PnlSnapshot.ts < start_ts,
            )
            .order_by(PnlSnapshot.ts.desc())
            .first()
        )
        initial_usd = float(first_snap.total_usd) if first_snap else 0.0
        if initial_usd <= 0:
            first_buy = next((t for t in trades_in_period if t.side == "BUY"), None)
            if first_buy:
                initial_usd = float(first_buy.qty * first_buy.price)
        # End-of-period value: current total_usd
        pnl_usd = total_usd - initial_usd if initial_usd > 0 else (total_usd - 0)
    else:
        # period "all": referans = başlangıç sermayesi (config); böylece bot başlar başlamaz +%100 kar görünmez
        initial_usd = config_initial if config_initial > 0 else 0.0
        if initial_usd <= 0:
            first_buy = (
                db.query(Trade)
                .filter(
                    Trade.bot_id == bot.id,
                    Trade.account_id == bot.account_id,
                    Trade.side == "BUY",
                )
                .order_by(Trade.ts.asc())
                .first()
            )
            if first_buy:
                initial_usd = float(first_buy.qty * first_buy.price)
        if initial_usd <= 0:
            initial_usd = total_usd
        pnl_usd = total_usd - initial_usd
    # PNL kartı: Trailing DCA — yalnızca kapanmış turlar, yön bazlı dual ledger toplamı.
    strategy_id_perf = (cfg_perf.get("strategy_id") or "").strip().lower()
    is_trailing_dual_dca = sym_perf != "MULTI" and strategy_id_perf not in (
        "trdca_pro",
        "multi_asset_rebalance",
    )
    dual_perf: Optional[Dict[str, Any]] = None
    initial_for_pnl = config_initial if config_initial > 0 else (initial_usd or 0.0)
    cur_px_perf = float(pnl_data.get("current_price") or 0)
    if is_trailing_dual_dca:
        closed_cycles, perf_date_from, perf_date_to = load_bot_closed_cycles_for_period(
            db, bot.id, bot.account_id, period, state_for_pnl
        )
        from app.services.bot_performance_service import (
            aggregate_dual_perf_closed_cycles,
        )

        dual_perf = aggregate_dual_perf_closed_cycles(
            closed_cycles,
            initial_capital=initial_for_pnl,
            date_from=perf_date_from,
            date_to=perf_date_to,
        )
        dual_perf["current_cycle_id"] = int((state_for_pnl or {}).get("cycle_id") or 1)
        dual_perf["period_date_from"] = perf_date_from
        dual_perf["period_date_to"] = perf_date_to
        dual_perf["period_label"] = perf_period_label
        pnl_usd = float(dual_perf["cash_pnl_usdt"])
        pnl_pct = float(dual_perf["cash_pnl_pct"] or 0.0)
        fees_usd = float(dual_perf["cash_fees_usdt"]) + float(
            dual_perf.get("inventory_fees_usdt") or 0
        )
    if dual_perf is not None and initial_for_pnl > 0 and cur_px_perf > 0:
        inv_coin = float(dual_perf.get("inventory_pnl_coin") or 0)
        dual_perf["inventory_pnl_pct"] = round(
            inv_coin * cur_px_perf / initial_for_pnl * 100.0, 2
        )
    elif dual_perf is not None:
        dual_perf["inventory_pnl_pct"] = None
    elif state_for_pnl and state_for_pnl.get("cycle_pnls"):
        pnl_usd = 0.0
        for c in state_for_pnl["cycle_pnls"]:
            p = c.get("pnl_usdt_net") or c.get("pnl_usdt")
            if p is not None:
                pnl_usd += float(p)
    else:
        pnl_usd = 0.0
        from sqlalchemy import text

        q_events = db.execute(
            text("""
                SELECT meta_json FROM bot_engine_events
                WHERE bot_id = :bid AND account_id = :aid AND event_type = 'CYCLE_END'
                ORDER BY ts ASC
            """),
            {"bid": bot.id, "aid": bot.account_id},
        ).fetchall()
        for row in q_events:
            if row[0]:
                try:
                    meta = json.loads(row[0])
                    p = meta.get("profit_usdt")
                    if p is not None:
                        pnl_usd += float(p)
                except Exception:
                    pass
    if not is_trailing_dual_dca:
        pnl_pct = (pnl_usd / initial_for_pnl * 100.0) if initial_for_pnl > 0 else 0.0

    # Aktif tur: state + ledger birleşimi (/cycles ile aynı kaynak)
    merged_cycles = _merge_bot_cycle_ids(db, bot.id, bot.account_id)
    cycles_count = max(merged_cycles) if merged_cycles else 0

    # Chart: always from bot start; two series as % from start (balance % and parite %)
    chart_series: List[Dict[str, Any]] = []
    pair_series: List[Dict[str, Any]] = []
    strategy_id_chart = (cfg_perf.get("strategy_id") or "").strip().lower()

    # TRDCA: Parite = portföy coinlerinin dağılıma göre ağırlıklı ortalama % değişimi. Grafik bot_perf_chart_state samples'tan.
    if strategy_id_chart == "trdca_pro":
        row_chart = db.execute(
            text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
            {"bid": bot.id},
        ).fetchone()
        payload_chart = json.loads(row_chart[0]) if row_chart and row_chart[0] else {}
        samples_trdca = payload_chart.get("samples") or []
        baseline_chart = payload_chart.get("baseline") or {}
        if samples_trdca and isinstance(samples_trdca, list):
            init_cap = config_initial if config_initial > 0 else 10000.0
            for s in samples_trdca:
                ts_val = s.get("ts")
                bot_pct_val = s.get("botPct")
                parite_pct_val = s.get("paritePct")
                if ts_val is None:
                    continue
                try:
                    dt = datetime.fromtimestamp(int(ts_val), tz=timezone.utc)
                    t_str = dt.isoformat()
                except Exception:
                    t_str = str(ts_val)
                bp = float(bot_pct_val) if bot_pct_val is not None else 0.0
                pp = float(parite_pct_val) if parite_pct_val is not None else 0.0
                val_usd = init_cap * (1.0 + bp / 100.0) if init_cap > 0 else 0.0
                chart_series.append(
                    {"t": t_str, "value": round(val_usd, 2), "pct": round(bp, 2)}
                )
                pair_series.append(
                    {
                        "t": t_str,
                        "price": 100.0 * (1.0 + pp / 100.0),
                        "pct": round(pp, 2),
                    }
                )
            if chart_series and total_usd is not None:
                last_val = chart_series[-1].get("value", 0)
                if abs(float(total_usd) - last_val) > 0.01:
                    bp_now = (
                        (total_usd / init_cap - 1.0) * 100.0 if init_cap > 0 else 0.0
                    )
                    chart_series.append(
                        {
                            "t": now.isoformat(),
                            "value": round(float(total_usd), 2),
                            "pct": round(bp_now, 2),
                        }
                    )
                    parite_now = pair_series[-1].get("pct") if pair_series else 0.0
                    init_prices = baseline_chart.get("initial_prices") or {}
                    coin_weights_b = baseline_chart.get("coin_weights") or {}
                    quote_a = (cfg_perf.get("quote_asset") or "USDT").strip().upper()
                    if init_prices and coin_weights_b:
                        try:
                            curr_prices = await _fetch_prices_parallel(
                                list(coin_weights_b.keys()), quote_a
                            )
                            parite_pct_live = compute_trdca_parite_pct(
                                init_prices, coin_weights_b, curr_prices, quote_a
                            )
                            if parite_pct_live is not None:
                                parite_now = round(parite_pct_live, 2)
                        except Exception:
                            pass
                    pair_series.append(
                        {
                            "t": now.isoformat(),
                            "price": 100.0 * (1.0 + parite_now / 100.0),
                            "pct": parite_now,
                        }
                    )
        elif (
            strategy_id_chart == "trdca_pro"
            and total_usd is not None
            and config_initial > 0
        ):
            init_cap = config_initial
            bp_now = (total_usd / init_cap - 1.0) * 100.0
            parite_now = 0.0
            row_b = db.execute(
                text(
                    "SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"
                ),
                {"bid": bot.id},
            ).fetchone()
            payload_b = json.loads(row_b[0]) if row_b and row_b[0] else {}
            baseline_chart = payload_b.get("baseline") or {}
            init_prices = baseline_chart.get("initial_prices") or {}
            coin_weights_b = baseline_chart.get("coin_weights") or {}
            quote_a = (cfg_perf.get("quote_asset") or "USDT").strip().upper()
            if init_prices and coin_weights_b:
                try:
                    curr_prices = await _fetch_prices_parallel(
                        list(coin_weights_b.keys()), quote_a
                    )
                    parite_pct_live = compute_trdca_parite_pct(
                        init_prices, coin_weights_b, curr_prices, quote_a
                    )
                    if parite_pct_live is not None:
                        parite_now = round(parite_pct_live, 2)
                except Exception:
                    pass
            chart_series = [
                {
                    "t": now.isoformat(),
                    "value": round(float(total_usd), 2),
                    "pct": round(bp_now, 2),
                }
            ]
            pair_series = [
                {
                    "t": now.isoformat(),
                    "price": 100.0 * (1.0 + parite_now / 100.0),
                    "pct": parite_now,
                }
            ]

    all_snapshots = []
    all_trades = []
    if not chart_series and not pair_series:
        all_snapshots = (
            db.query(PnlSnapshot)
            .filter(
                PnlSnapshot.bot_id == bot.id, PnlSnapshot.account_id == bot.account_id
            )
            .order_by(PnlSnapshot.ts.asc())
            .all()
        )
        all_trades = (
            db.query(Trade)
            .filter(Trade.bot_id == bot.id, Trade.account_id == bot.account_id)
            .order_by(Trade.ts.asc())
            .all()
        )
        if all_snapshots or all_trades:
            # Align timestamps: union of snapshot and trade times, sorted
            times = set()
            for s in all_snapshots:
                t = s.ts.isoformat() if hasattr(s.ts, "isoformat") else str(s.ts)
                times.add((s.ts, t))
            for t in all_trades:
                ts = t.ts
                t_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                times.add((ts, t_str))
            sorted_times = sorted(times, key=lambda x: x[0])
            if not sorted_times and total_usd is not None:
                sorted_times = [(now, now.isoformat())]

            first_ts = sorted_times[0][0] if sorted_times else now
            init_usd = (
                float(all_snapshots[0].total_usd) if all_snapshots else total_usd or 0.0
            )
            init_price = (
                float(all_trades[0].price)
                if all_trades
                else float(pnl_data.get("current_price") or 0) or 0.0
            )
            if init_price <= 0:
                init_price = 1.0

            snap_idx = 0
            trade_idx = 0
            for ts, t_str in sorted_times:
                while (
                    snap_idx < len(all_snapshots) and all_snapshots[snap_idx].ts <= ts
                ):
                    snap_idx += 1
                while trade_idx < len(all_trades) and all_trades[trade_idx].ts <= ts:
                    trade_idx += 1
                last_usd = (
                    float(all_snapshots[snap_idx - 1].total_usd)
                    if snap_idx > 0
                    else init_usd
                )
                last_price = (
                    float(all_trades[trade_idx - 1].price)
                    if trade_idx > 0
                    else init_price
                )
                balance_pct = (
                    (last_usd / init_usd - 1.0) * 100.0 if init_usd > 0 else 0.0
                )
                price_pct = (
                    (last_price / init_price - 1.0) * 100.0 if init_price > 0 else 0.0
                )
                chart_series.append(
                    {"t": t_str, "value": last_usd, "pct": round(balance_pct, 2)}
                )
                pair_series.append(
                    {"t": t_str, "price": last_price, "pct": round(price_pct, 2)}
                )

            # Resample: ilk 24 saat tüm noktalar; sonrası saat başı bir nokta (grafik bot açıldığından itibaren, kalp atışı gibi)
            one_day = timedelta(days=1)
            cutoff_24h = first_ts + one_day
            resampled_indices = set()
            last_hour_bucket = None
            for i, (ts, _) in enumerate(sorted_times):
                if ts <= cutoff_24h:
                    resampled_indices.add(i)
                else:
                    hour_bucket = int((ts - first_ts).total_seconds() // 3600)
                    if last_hour_bucket is None or hour_bucket != last_hour_bucket:
                        resampled_indices.add(i)
                        last_hour_bucket = hour_bucket
            if sorted_times:
                resampled_indices.add(0)
                resampled_indices.add(len(sorted_times) - 1)
            if resampled_indices:
                chart_series = [
                    chart_series[i]
                    for i in range(len(chart_series))
                    if i in resampled_indices
                ]
                pair_series = [
                    pair_series[i]
                    for i in range(len(pair_series))
                    if i in resampled_indices
                ]

            if not chart_series and total_usd is not None:
                chart_series = [{"t": now.isoformat(), "value": total_usd, "pct": 0.0}]
                pair_series = [
                    {
                        "t": now.isoformat(),
                        "price": float(pnl_data.get("current_price") or 0),
                        "pct": 0.0,
                    }
                ]
            if len(chart_series) == 1 and total_usd is not None:
                cur_price = float(pnl_data.get("current_price") or 0) or (
                    float(all_trades[-1].price) if all_trades else 0
                )
                init_usd_chart = float(chart_series[0]["value"])
                init_price_chart = (
                    float(pair_series[0]["price"])
                    if pair_series and pair_series[0].get("price")
                    else cur_price or 1.0
                )
                balance_pct = (
                    (total_usd / init_usd_chart - 1.0) * 100.0
                    if init_usd_chart > 0
                    else 0.0
                )
                price_pct = (
                    (cur_price / init_price_chart - 1.0) * 100.0
                    if init_price_chart > 0
                    else 0.0
                )
                chart_series.append(
                    {
                        "t": now.isoformat(),
                        "value": total_usd,
                        "pct": round(balance_pct, 2),
                    }
                )
                pair_series.append(
                    {
                        "t": now.isoformat(),
                        "price": cur_price,
                        "pct": round(price_pct, 2),
                    }
                )

    # Rapor için: başlangıç/güncel fiyat (perfReport'ta "—" çıkmaması için)
    state = state_for_pnl or load_state(db, bot.id)
    reference_price = None
    if all_trades:
        reference_price = float(all_trades[0].price)
    elif (
        pair_series
        and len(pair_series) > 0
        and pair_series[0].get("price") is not None
        and float(pair_series[0]["price"]) > 0
    ):
        reference_price = float(pair_series[0]["price"])
    if reference_price is None and state and (state.get("reference_price") or 0) > 0:
        reference_price = float(state["reference_price"])
    # Current price is market data only. Trades/reference/pair history remain
    # historical anchors and are never promoted to a live price.
    current_price_out = live_px_alpha if live_px_alpha > 0 else None
    if (
        reference_price is None
        and current_price_out is not None
        and current_price_out > 0
    ):
        reference_price = current_price_out
    if reference_price is not None and reference_price <= 0:
        reference_price = None
    if current_price_out is not None and current_price_out <= 0:
        current_price_out = None

    # Rapor için: botun config'taki bütçesi (Başlangıç bakiyesi = kullanıcının belirlediği bütçe)
    config_budget_usd = round(config_initial, 2) if config_initial > 0 else None

    # Cycle PnL (son tur): state.cycle_pnls son eleman; API contract geriye dönük uyumlu
    cycle_pnl_last = None
    cycle_pnl_last_net = None
    cycle_id_last = None
    cycle_type_last = None
    cycle_base_delta_last = None
    target_budgets = None
    pnl_calculation_mode = cfg_perf.get("pnl_mode", "cycle_only_fee_aware_v1")
    if state_for_pnl and state_for_pnl.get("cycle_pnls"):
        last_cycle = state_for_pnl["cycle_pnls"][-1]
        cycle_id_last = last_cycle.get("cycle_id")
        p = last_cycle.get("pnl_usdt_net") or last_cycle.get("pnl_usdt")
        if p is not None:
            cycle_pnl_last = round(float(p), 2)
            cycle_pnl_last_net = round(float(p), 2)
        if last_cycle.get("pnl_mode"):
            pnl_calculation_mode = last_cycle["pnl_mode"]
        cycle_type_last = last_cycle.get("cycle_type")
        bd = last_cycle.get("base_delta")
        if bd is not None:
            cycle_base_delta_last = round(float(bd), 8)
    if state_for_pnl and state_for_pnl.get("target_budgets"):
        tb = state_for_pnl["target_budgets"]
        if isinstance(tb, dict) and any(
            k in tb for k in ("equity_usdt", "target_quote_usdt", "target_base_usdt")
        ):
            target_budgets = {
                k: round(float(v), 2) if isinstance(v, (int, float)) else v
                for k, v in tb.items()
                if k in ("equity_usdt", "target_quote_usdt", "target_base_usdt", "ts")
            }

    current_cycle_id = (
        int(state_for_pnl.get("cycle_id") or 1)
        if state_for_pnl
        else (cycles_count or 1)
    )
    completed_cycles_for_projection = (
        state_for_pnl.get("completed_cycle_dual_pnls") or []
        if isinstance(state_for_pnl, dict)
        else []
    )
    from app.services.bot_performance_service import (
        estimate_annual_return_pct_12m,
        estimate_live_bot_annual_return_pct_12m,
    )

    annual_initial_usd = config_initial if config_initial > 0 else initial_usd
    annual_return_pct_12m = estimate_annual_return_pct_12m(
        completed_cycles_for_projection,
        annual_initial_usd,
        now=now,
        symbol=sym_perf,
    )
    annual_return_source = "bot_12m_average"
    if annual_return_pct_12m is None:
        annual_return_pct_12m = estimate_live_bot_annual_return_pct_12m(
            total_usd,
            annual_initial_usd,
            getattr(bot, "started_at", None),
            now=now,
        )
        annual_return_source = "bot_live_since_start"
    if annual_return_pct_12m is None:
        # Yalnız bu botun verisi kullanılabilir. Kendi başlangıç verisi dahi
        # henüz hazır değilse başka bot yerine nötr değer gösterilir.
        annual_return_pct_12m = 0.0
        annual_return_source = "bot_data_pending"
    daily_gain_usd = float(pnl_data.get("daily") or 0.0)
    monthly_gain_usd = float(pnl_data.get("monthly") or 0.0)
    stable_initial_usd = (
        config_initial if config_initial > 0 else initial_usd
    )

    result = {
        "request_id": rid,
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct, 2),
        "real_performance_pct": round(real_performance_pct, 2)
        if real_performance_pct is not None
        else None,
        "balance_change_pct": balance_change_pct,
        "price_change_pct": price_change_pct,
        "period": normalize_perf_period(period),
        "period_label": perf_period_label,
        "trades_count": trades_count,
        "cycles_count": cycles_count,
        "current_cycle_id": current_cycle_id,
        "fees_usd": round(fees_usd, 2),
        "realized": round(realized, 2),
        "total_usd": round(total_usd, 2),
        "initial_usd": round(stable_initial_usd, 2),
        "balance_start_usd": round(initial_usd, 2),
        "config_budget_usd": config_budget_usd,
        "balance_end_usd": round(total_usd, 2),
        "reference_price": round(reference_price, 8)
        if reference_price is not None
        else None,
        "current_price": round(current_price_out, 8)
        if current_price_out is not None
        else None,
        "price_stale": bool(perf_price_meta.get("is_stale")),
        "price_age_s": perf_price_meta.get("age_s"),
        "data_quality": "stale_snapshot"
        if perf_price_meta.get("is_stale")
        else "live",
        "chart_series": chart_series,
        "pair_series": pair_series,
        "cycle_pnl_last": cycle_pnl_last,
        "cycle_pnl_last_net": cycle_pnl_last_net,
        "cycle_id_last": cycle_id_last,
        "cycle_type_last": cycle_type_last,
        "cycle_base_delta_last": cycle_base_delta_last,
        "target_budgets": target_budgets,
        "pnl_calculation_mode": pnl_calculation_mode,
        "realized_pnl_total": round(realized, 2),
        "fees_total": round(fees_usd, 2),
        "daily_gain_usd": round(daily_gain_usd, 2),
        "daily_gain_pct": round(
            daily_gain_usd / stable_initial_usd * 100.0, 2
        )
        if stable_initial_usd > 0
        else None,
        "monthly_gain_usd": round(monthly_gain_usd, 2),
        "monthly_gain_pct": round(
            monthly_gain_usd / stable_initial_usd * 100.0, 2
        )
        if stable_initial_usd > 0
        else None,
        "estimated_annual_return_pct_12m": annual_return_pct_12m,
        "estimated_annual_return_source": annual_return_source,
    }
    if dual_perf is not None:
        result["dual_perf"] = dual_perf
    if session_alpha is not None:
        result["session_alpha_performance"] = session_alpha
        result["bot_alpha_performance"] = session_alpha

    strategy_id = (cfg_perf.get("strategy_id") or "").strip().lower()
    if strategy_id == "trdca_pro":
        result["is_trdca"] = True
        pnl_breakdown = _compute_trdca_pnl_breakdown(
            db, bot.id, bot.account_id, state_for_pnl, cfg_perf
        )
        result["rebalance_pnl"] = pnl_breakdown.get("rebalance_pnl") or []
        result["dca_pnl_usd"] = pnl_breakdown.get("dca_pnl_usd") or 0.0
        result["dca_adet_pnl"] = pnl_breakdown.get("dca_adet_pnl") or []

    return result
