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
import uuid
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Live snapshot cache: TTL 2s, key = bot_id. Thread-safe. No historical DB.
# ---------------------------------------------------------------------------
_LIVE_CACHE: Dict[int, Tuple[dict, float]] = {}
_LIVE_CACHE_LOCK = threading.Lock()
_LIVE_CACHE_TTL_SEC = 2.0


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
WINDOW_SECONDS = {"1h": 86400, "4h": 259200, "1d": 2592000, "7d": 7776000, "30d": 31536000}
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
from sqlalchemy import func, text

from app.api.auth import get_account_or_403, require_auth, get_client_ip
from app.botengine.models import DcaGridTrailingConfig, config_from_ui_payload
from app.services import audit as audit_svc
from app.botengine.orchestrator import delete_bot_fully, invalidate_config_cache
from app.botengine.state_store import append_event, ensure_state_row, list_events, load_state, save_state
from app.botengine.grid_view import compute_grid_profit_view, compute_trdca_grid_view
from app.db.session import get_db
from app.db.models import Bot, Account, Trade, PnlSnapshot
from app.services.pnl_service import PnlService
from app.services.price_hub import price_hub
from app.utils.tz_utils import turkey_today_start_utc
from app.services.perf_chart_state import (
    seed_perf_chart_state_on_bot_start,
    compute_trdca_parite_pct,
)

router = APIRouter()

BINANCE_PUBLIC = "https://api.binance.com"


def _get_price_from_datahub(sym_pair: str) -> Optional[float]:
    """DataHub cache only. No per-symbol Binance REST."""
    try:
        from app.services.data_hub import data_hub
        p = data_hub.get_price(sym_pair.upper())
        if p is not None and float(p) > 0:
            return float(p)
    except Exception:
        pass
    return None


async def _fetch_prices_parallel(assets: List[str], quote_asset: str) -> Dict[str, float]:
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


def _detail_err(code: str, message: str, request_id: str) -> dict:
    return {"error_code": code, "message": message, "request_id": request_id}


@router.get("")
async def bots_list(
    request: Request,
    account_id: int = Query(..., description="Account scope"),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List bots for account. require_auth + get_account_or_403(account_id)."""
    rid = _request_id(request)
    get_account_or_403(current, account_id, db)
    rows = db.query(Bot).filter(Bot.account_id == account_id).order_by(Bot.id.desc()).all()
    out = []
    for r in rows:
        raw = json.loads(r.config_json or "{}")
        state = load_state(db, r.id)
        ia_done = bool(state and state.get("initial_allocation_done"))
        st = (r.status or "stopped").lower()
        display_status = st
        if st == "running" and not ia_done:
            display_status = "starting"
        out.append({
            "bot_id": r.id,
            "bot_code": getattr(r, "bot_code", None) or str(r.id),
            "account_id": r.account_id,
            "symbol": r.symbol,
            "status": st,
            "display_status": display_status,
            "initial_allocation_done": ia_done,
            "config": raw,
            "last_tick_at": state.get("last_tick_at") if state else None,
            "created_at": r.started_at.isoformat() + "Z" if getattr(r, "started_at", None) else None,
        })
    return {"bots": out, "request_id": rid}


class BotCreateBody(BaseModel):
    account_id: int
    config_json: Optional[dict] = None


def create_bot_engine_core(account_id: int, config_dict: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """Shared create logic. config_dict = UI payload. Returns bot_id, bot_code, account_id, symbol, status."""
    raw = config_dict or {}
    cfg = config_from_ui_payload(raw)
    symbol = (raw.get("symbol") or cfg.symbol or "BTCUSDT").upper().strip()
    # Yeni botlar her zaman canlı modda oluşturulur.
    mode = "live" if not cfg.paper_mode else "paper"
    config_json = json.dumps(cfg.to_dict(), ensure_ascii=False)
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
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    ensure_state_row(db, bot.id, bot.account_id, symbol)
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
    result = create_bot_engine_core(body.account_id, raw, db)
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    state = load_state(db, bot.id)
    raw = json.loads(bot.config_json or "{}")
    price = float((state or {}).get("reference_price") or 0)

    # PnL + live price for UI (current_price, current_usd, daily_pnl_*, price_24h)
    pnl_data: Dict[str, Any] = {}
    try:
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id) or {}
    except Exception as e:
        logger.debug("bots_detail pnl failed bot_id=%s: %s", bot.id, e)
    if pnl_data.get("error"):
        pnl_data = {}
    live_price = float(pnl_data.get("current_price") or 0)
    if live_price <= 0:
        try:
            hub_p = price_hub.get_price(bot.symbol or "")
            if hub_p is not None and float(hub_p) > 0:
                live_price = float(hub_p)
        except Exception:
            pass

    # 24h ticker: paralel başlat, MULTI/TRDCA işlemleriyle birlikte çalışsın
    price_24h_change_pct = None
    sym = (bot.symbol or "").strip().upper()
    async def _fetch_24h_ticker():
        out = {}
        if not sym or sym == "MULTI":
            return out
        try:
            from app.services.market_data import get_ticker_24h
            t = get_ticker_24h(sym)
            pct = t.get("priceChangePercent")
            if pct is not None:
                out["pct"] = round(float(pct), 2)
            last_p = t.get("lastPrice")
            if last_p is not None and float(last_p) > 0:
                out["price"] = float(last_p)
        except Exception as e:
            logger.debug("bots_detail 24h ticker failed symbol=%s: %s", sym, e)
        return out
    t24 = asyncio.create_task(_fetch_24h_ticker()) if sym else None

    if price <= 0 and live_price > 0:
        price = live_price
    current_usd = float(pnl_data.get("total_usd") or 0)
    daily_usd = float(pnl_data.get("daily") or 0)
    daily_pnl_pct = pnl_data.get("daily_pnl_pct")
    if daily_pnl_pct is None:
        daily_pnl_pct = (daily_usd / current_usd * 100.0) if current_usd and current_usd > 0 else 0.0
    else:
        daily_pnl_pct = float(daily_pnl_pct)

    config_for_grid = _config_for_grid_view(raw)
    grid_points: List[Dict[str, Any]] = []
    profit_points: List[Dict[str, Any]] = []
    reference_display: Optional[float] = None
    grid_meta: Optional[Dict[str, Any]] = None
    _strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_trdca = _strategy_id == "trdca_pro"
    if not is_trdca:
        view_price = live_price if live_price > 0 else price
        try:
            grid_points, profit_points, meta = compute_grid_profit_view(state or {}, config_for_grid, view_price)
            reference_display = meta.get("ref_display")
        except Exception as e:
            logger.warning("bots_detail grid_view failed bot_id=%s: %s", bot.id, e)

    # MULTI/TRDCA: canlı base_value_usd (coinlerin USD toplamı) ve quote_balance (USDT)
    base_value_usd: Optional[float] = None
    quote_balance_usd: Optional[float] = None
    rebalancing_details: List[Dict[str, Any]] = []
    trdca_prices_cache: Optional[Dict[str, float]] = None  # parite için fiyat cache
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    initial_capital = float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or raw.get("bot_budget_quote") or 0)
    is_test = False
    try:
        from app.services.test_account import is_test_account
        is_test = is_test_account(bot.account_id, db)
    except Exception:
        pass
    if (sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance")):
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
                s = (a.get("symbol") or "").upper().replace("USDT", "").replace("FDUSD", "").strip()
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
                if is_test and initial_capital > 0 and base_value_usd == 0 and quote_balance_usd == TEST_PAPER_BALANCE_USDT:
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
                    if not is_test and initial_capital > 0 and live_total > initial_capital and effective_balances_map:
                        scale = initial_capital / live_total
                        for k in effective_balances_map:
                            effective_balances_map[k] = float(effective_balances_map.get(k) or 0) * scale
                        base_value_usd = base_value_usd * scale
                        quote_balance_usd = quote_balance_usd * scale
                        current_usd = initial_capital
            except Exception as e:
                logger.debug("bots_detail multi balances failed bot_id=%s: %s", bot.id, e)
        # Test hesabı + bakiye alınamadı: paper fallback (initial_capital ile başlangıç)
        if is_test and initial_capital > 0 and (base_value_usd is None or quote_balance_usd is None):
            base_value_usd = base_value_usd if base_value_usd is not None else 0.0
            quote_balance_usd = quote_balance_usd if quote_balance_usd is not None else initial_capital
            if current_usd <= 0:
                current_usd = initial_capital

        # Rebalancing detayları: her coin için miktar, referans %, anlık %, rebalancinge kalan %
        target_weights = (raw.get("trb") or {}).get("target_weights_all") or (raw.get("dca") or {}).get("coin_weights") or {}
        if not target_weights and raw.get("assets"):
            for a in raw["assets"]:
                sym = (a.get("symbol") or "").upper().replace("USDT", "").replace("FDUSD", "").strip()
                if sym:
                    target_weights[sym] = float(a.get("target_pct") or 0) / 100.0
        if target_weights and (sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance")):
            balances_map = {}
            if effective_balances_map:
                balances_map = dict(effective_balances_map)
            elif vb and isinstance(vb, dict):
                balances_map = dict(vb)
                # Eski test default (10k) düzelt: rebalancing hesapları için initial_capital kullan
                try:
                    from app.services.test_account import TEST_PAPER_BALANCE_USDT
                    if is_test and initial_capital > 0 and float(vb.get(quote_asset) or 0) == TEST_PAPER_BALANCE_USDT:
                        base_sum = sum(float(vb.get(a) or 0) for a in assets if a != quote_asset)
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
                        prices_tmp = await _fetch_prices_parallel(list(assets), quote_asset)
                        actual_total = 0.0
                        for a in assets:
                            qty = float(balances_map.get(a) or 0)
                            p = float(prices_tmp.get(a) or 0) if a != quote_asset else 1.0
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
            base_assets = sorted(a for a in target_weights.keys() if a and str(a).strip().upper() != quote_asset)
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
                current_pct = (value_usd / total_usd_val * 100.0) if total_usd_val > 0 else 0.0
                gap_pct = target_pct - current_pct
                rebalancing_details.append({
                    "asset": a,
                    "qty": round(qty, 8),
                    "price": round(price, 6) if price else 0,
                    "value_usd": round(value_usd, 2),
                    "target_pct": round(target_pct, 2),
                    "current_pct": round(current_pct, 2),
                    "gap_pct": round(gap_pct, 2),
                })
            # Quote (USDT) satiri: Referans % = hedef agirliktan; Anlik % = portfoydeki quote orani (base/quote bolunmesi netlesir)
            quote_target_pct = float(target_weights.get(quote_asset) or 0) * 100.0
            quote_value = float(quote_balance_usd or 0)
            quote_current_pct = (quote_value / total_usd_val * 100.0) if total_usd_val > 0 else 0.0
            if quote_target_pct != 0 or quote_value > 0:
                rebalancing_details.append({
                    "asset": quote_asset,
                    "qty": round(float(balances_map.get(quote_asset) or 0), 8),
                    "price": 1.0,
                    "value_usd": round(quote_value, 2),
                    "target_pct": round(quote_target_pct, 2),
                    "current_pct": round(quote_current_pct, 2),
                    "gap_pct": round(quote_target_pct - quote_current_pct, 2),
                })

        # TRDCA: grid noktaları portföy değeri (basket) referans alınarak
        if is_trdca:
            coin_weights = (raw.get("dca") or {}).get("coin_weights") or {}
            basket_price = 0.0
            if coin_weights:
                try:
                    prices_map = await _fetch_prices_parallel(list(coin_weights.keys()), quote_asset)
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
                live_price = float(t24_result["price"])
                try:
                    price_hub.update_price(bot.symbol or "", live_price)
                except Exception:
                    pass
        except Exception:
            pass

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
        today_start = turkey_today_start_utc()
        today_date = today_start.strftime("%Y-%m-%d")
        daily_ref_date = state.get("daily_ref_date")
        daily_ref_usd = float(state.get("daily_ref_usd") or 0)
        if daily_ref_date == today_date and daily_ref_usd and daily_ref_usd > 0:
            daily_usd = equity_from_state - daily_ref_usd
            daily_pnl_pct = (daily_usd / daily_ref_usd) * 100.0

    _ia_done = bool(state and state.get("initial_allocation_done"))
    _st = (bot.status or "stopped").lower()
    _display_status = "starting" if _st == "running" and not _ia_done and (current_usd or 0) <= 0.01 else _st
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
        "current_usd": round(current_usd, 2) if current_usd else None,
        "base_value_usd": round(base_value_usd, 2) if base_value_usd is not None else None,
        "quote_balance_usd": round(quote_balance_usd, 2) if quote_balance_usd is not None else None,
        "daily_pnl_usd": round(daily_usd, 2) if daily_usd is not None else None,
        "daily_pnl_pct": round(daily_pnl_pct, 2) if daily_pnl_pct is not None else None,
        "price_24h_change_pct": price_24h_change_pct,
        "started_at": bot.started_at.isoformat() + "Z" if getattr(bot, "started_at", None) else None,
        "request_id": rid,
        "rebalancing_details": rebalancing_details,
    }

    # TRDCA: performans grafiği için parite_pct (portföyün ağırlıklı ortalama % değişimi) ve bot_pct
    if strategy_id == "trdca_pro" and initial_capital > 0 and current_usd is not None:
        try:
            row = db.execute(
                text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
                {"bid": bot.id},
            ).fetchone()
            payload = json.loads(row[0]) if row and row[0] else {}
            baseline = payload.get("baseline") or {}
            initial_prices = baseline.get("initial_prices")
            coin_weights = baseline.get("coin_weights")
            if initial_prices and coin_weights:
                cw_keys = [k for k in coin_weights if k and str(k).upper() != quote_asset]
                if trdca_prices_cache and all(k in trdca_prices_cache for k in cw_keys):
                    current_prices = trdca_prices_cache
                else:
                    current_prices = await _fetch_prices_parallel(cw_keys, quote_asset)
                parite_pct_val = compute_trdca_parite_pct(initial_prices, coin_weights, current_prices, quote_asset)
                bot_pct_val = (float(current_usd) - initial_capital) / initial_capital * 100.0
                result["parite_pct"] = round(parite_pct_val, 2) if parite_pct_val is not None else None
                result["bot_pct"] = round(bot_pct_val, 2)
        except Exception:
            pass

    # Dual PNL (Cash vs Inventory) for Trailing DCA — perfPanel + tradesPanel
    if state and sym and sym != "MULTI" and strategy_id not in ("trdca_pro", "multi_asset_rebalance"):
        try:
            ledger = state.get("cycle_ledger_current")
            current_price = float(live_price or 0) if live_price else (float(pnl_data.get("current_price") or 0) if pnl_data else 0)
            cash_pnl_cur = 0.0
            cash_fees_cur = 0.0
            inv_qty_cur = 0.0
            inv_fees_cur = 0.0
            fills_count = 0
            started_at = None
            if isinstance(ledger, dict) and ledger.get("symbol") == sym:
                cash_pnl_cur = float(ledger.get("cash_fifo_pnl_usdt") if ledger.get("cash_fifo_pnl_usdt") is not None else ledger.get("cash_pnl_usdt") or 0)
                cash_fees_cur = float(ledger.get("cash_fifo_fees_usdt") if ledger.get("cash_fifo_fees_usdt") is not None else ledger.get("cash_fees_usdt") or 0)
                inv_qty_cur = float(ledger.get("inventory_coin_adv_qty") or 0)
                inv_fees_cur = float(ledger.get("inventory_fees_usdt") or 0)
                fills_count = len(ledger.get("fills") or [])
                started_at = ledger.get("started_at")

            completed = state.get("completed_cycle_dual_pnls") or []
            completed_sorted = sorted(completed, key=lambda x: int(x.get("cycle_id") or 0), reverse=True)

            cash_total = cash_pnl_cur + sum(float(c.get("cash_pnl_usdt") or 0) for c in completed)
            cash_fees_total = cash_fees_cur + sum(float(c.get("cash_fees_usdt") or 0) for c in completed)
            inv_qty_total = inv_qty_cur + sum(float(c.get("inventory_coin_adv_qty") or 0) for c in completed)
            inv_fees_total = inv_fees_cur + sum(float(c.get("inventory_fees_usdt") or 0) for c in completed)
            inv_usdt_equiv = (inv_qty_total * current_price - inv_fees_total) if current_price > 0 else (0.0 - inv_fees_total)

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

    return result


def _resolve_account_id(account_id: Optional[int], account_code: Optional[str], db: Session) -> Optional[int]:
    """account_id yoksa account_code ile çöz. None dönerse account_id kullanılmaz (bot id ile bulunur)."""
    if account_id is not None:
        return account_id
    if account_code and str(account_code).strip():
        acc = db.query(Account).filter(Account.account_code == str(account_code).strip()).first()
        if acc:
            return acc.id
    return None


def _build_live_snapshot_from_state(bot: Bot, state: Optional[Dict[str, Any]], db: Session) -> dict:
    """Build live snapshot from bot_engine_state + Bot only. No historical DB. Response < 15ms CPU."""
    status = (bot.status or "stopped").lower()
    raw = json.loads(bot.config_json or "{}")
    initial_capital = float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or raw.get("bot_budget_quote") or 0)

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
                    pass
        last_error_code = state.get("last_error_code")
        if isinstance(last_error_code, str):
            last_error_code = last_error_code.strip() or None
        else:
            last_error_code = None

    last_price: Optional[float] = None
    sym = (bot.symbol or "").strip().upper()
    try:
        p = price_hub.get_price(sym)
        if p is not None and float(p) > 0:
            last_price = float(p)
    except Exception:
        pass
    if last_price is None and sym:
        hub_p = _get_price_from_datahub(sym)
        if hub_p is not None and float(hub_p) > 0:
            last_price = float(hub_p)
    if last_price is None and state:
        ref = state.get("reference_price")
        if ref is not None:
            try:
                last_price = float(ref)
            except (TypeError, ValueError):
                pass

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

    # Günlük K/Z: TR gece 00:00 referansı; bot aynı gün açıldıysa ilk tick'te ref set edilir
    daily_pnl_usd: Optional[float] = None
    daily_pnl_pct: Optional[float] = None
    if state and equity is not None and not equity_unavailable:
        today_start = turkey_today_start_utc()
        today_date = today_start.strftime("%Y-%m-%d")
        daily_ref_date = state.get("daily_ref_date")
        daily_ref_usd = float(state.get("daily_ref_usd") or 0)
        if daily_ref_date == today_date and daily_ref_usd and daily_ref_usd > 0:
            daily_pnl_usd = equity - daily_ref_usd
            daily_pnl_pct = (daily_pnl_usd / daily_ref_usd) * 100.0

    stale = False
    if last_tick_at is not None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if (now_ts - last_tick_at) > 30:
            stale = True

    base_balance = float(state.get("base_balance") or 0) if state else 0
    initial_allocation_done = state.get("initial_allocation_done") is True if state else False
    first_buy_pending = status == "running" and not initial_allocation_done and base_balance <= 0
    if first_buy_pending and pnl_pct is not None:
        pnl_pct = 0.0

    out: Dict[str, Any] = {
        "status": status,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "equity": round(equity, 2) if equity is not None else 0,
        "last_price": last_price,
        "last_tick_at": last_tick_at,
        "last_error_code": last_error_code,
        "initial_capital": initial_capital,
        "daily_pnl_usd": round(daily_pnl_usd, 2) if daily_pnl_usd is not None else None,
        "daily_pnl_pct": round(daily_pnl_pct, 2) if daily_pnl_pct is not None else None,
        "base_balance": base_balance,
        "first_buy_pending": first_buy_pending,
    }
    if stale:
        out["stale"] = True
    if equity_unavailable:
        out["equity_unavailable"] = True
    return out


@router.get("/{bot_id}/live")
async def bots_live(
    request: Request,
    bot_id: int,
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Live snapshot only: status, pnl_pct, equity, last_price, last_tick_at. TTL cache 2s. No historical DB. < 15ms CPU."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))

    cached = _live_snapshot_get_cached(bot.id)
    if cached is not None:
        return cached

    state = load_state(db, bot.id)
    data = _build_live_snapshot_from_state(bot, state, db)
    _live_snapshot_set_cached(bot.id, data)
    return data


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

    row = db.execute(
        text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
        {"bid": bot_id},
    ).fetchone()
    payload = json.loads(row[0]) if row and row[0] else {}
    samples = payload.get("samples") if isinstance(payload.get("samples"), list) else []
    baseline = payload.get("baseline") or {}
    baseline_bot0 = baseline.get("bot0") if isinstance(baseline.get("bot0"), (int, float)) else 0.0
    baseline_parite0 = baseline.get("parite0") if isinstance(baseline.get("parite0"), (int, float)) else 0.0
    baseline_equity = baseline_bot0

    if bot_started_ts is not None:
        samples = [s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= bot_started_ts]
    samples = [s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= window_start]
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
        bucket_map[bucket_ts] = {"ts": bucket_ts, "bot_pct": bot_pct, "basket_pct": parite_pct}

    series = sorted(bucket_map.values(), key=lambda x: x["ts"])
    if len(series) > PERF_SERIES_MAX_POINTS:
        step = (len(series) + PERF_SERIES_MAX_POINTS - 1) // PERF_SERIES_MAX_POINTS
        series = series[::step]
    meta = {"baseline_equity": baseline_equity, "baseline_bot0": baseline_bot0, "baseline_parite0": baseline_parite0, "points": len(series)}
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
        raise HTTPException(status_code=400, detail=_detail_err("INVALID_PARAMS", "range or bucket invalid", rid))
    if range == "1h" and bucket != "1h":
        bucket = "1h"

    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))

    started_ts = None
    if getattr(bot, "started_at", None) is not None:
        started_ts = int(bot.started_at.timestamp())

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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    row = db.execute(
        text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
        {"bid": bot.id},
    ).fetchone()
    if not row or not row[0]:
        return {"baseline": None, "samples": [], "range": "4h", "request_id": rid}
    try:
        payload = json.loads(row[0])
        baseline = payload.get("baseline")
        samples = payload.get("samples") if isinstance(payload.get("samples"), list) else []
        range_val = payload.get("range") if payload.get("range") in ("1m", "5m", "1h", "4h", "1d", "1w") else "4h"
        # Sadece bu çalıştırma (started_at) sonrası veriyi göster; eski çalıştırmadan kalan veri 1 gün önce gibi görünmesin
        started_at = getattr(bot, "started_at", None)
        if started_at is not None:
            started_ts = int(started_at.timestamp())
            samples = [s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= started_ts]
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    payload = {
        "baseline": body.baseline if body else None,
        "samples": body.samples if body and isinstance(body.samples, list) else [],
        "range": (body.range if body and body.range in ("1h", "4h", "1d", "1w") else "4h") or "4h",
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
                d = trb_by_coin.setdefault(base, {"buy_qty": 0.0, "buy_cost": 0.0, "sell_qty": 0.0, "sell_revenue": 0.0})
                if side == "BUY":
                    d["buy_qty"] += qty
                    d["buy_cost"] += qty * price
                else:
                    d["sell_qty"] += qty
                    d["sell_revenue"] += qty * price
            elif coid.startswith("DCA-"):
                d = dca_by_coin.setdefault(base, {"buy_qty": 0.0, "buy_cost": 0.0, "sell_qty": 0.0, "sell_revenue": 0.0})
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
            out["rebalance_pnl"].append({"asset": base, "pnl_usd": round(pnl, 2), "qty": round(current_qty, 8)})

        for base, d in dca_by_coin.items():
            p = _get_price(base)
            if d["buy_qty"] > 0 and p > 0:
                current_value = d["buy_qty"] * p
                cost = d["buy_cost"]
                adet_pnl = current_value - cost
                out["dca_adet_pnl"].append({"asset": base, "pnl_usd": round(adet_pnl, 2), "qty": round(d["buy_qty"], 8)})

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
            raw.get("initial_capital_usdt") or raw.get("budget_usd")
            or raw.get("bot_budget_usdt") or raw.get("bot_budget_quote") or 0
        )
        bot_pct = (current_usd - initial_capital) / initial_capital * 100.0 if initial_capital > 0 else None

        row = db.execute(
            text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"),
            {"bid": bot_id},
        ).fetchone()
        payload = json.loads(row[0]) if row and row[0] else {}
        baseline = payload.get("baseline") or {}

        parite_pct = None
        if is_trdca:
            initial_prices = baseline.get("initial_prices")
            coin_weights = baseline.get("coin_weights")
            if not initial_prices or not coin_weights:
                target_weights = (raw.get("trb") or {}).get("target_weights_all") or (raw.get("dca") or {}).get("coin_weights") or {}
                base_assets = [a for a in target_weights if a and str(a).strip().upper() != quote_asset]
                if base_assets:
                    initial_prices = _fetch_prices_for_assets(base_assets, quote_asset)
                    total_w = sum(float(target_weights.get(a) or 0) for a in base_assets)
                    coin_weights = {a: float(target_weights.get(a) or 0) / total_w for a in base_assets} if total_w > 0 else {}
                    if initial_prices and coin_weights:
                        baseline["initial_prices"] = initial_prices
                        baseline["coin_weights"] = coin_weights
                        payload["baseline"] = baseline
            if initial_prices and coin_weights:
                current_prices = _fetch_prices_for_assets(list(coin_weights.keys()), quote_asset)
                parite_pct = compute_trdca_parite_pct(initial_prices, coin_weights, current_prices, quote_asset)
        else:
            live_price = float(pnl_data.get("current_price") or 0)
            if live_price <= 0:
                try:
                    hub_p = price_hub.get_price(bot.symbol or "")
                    if hub_p is not None and float(hub_p) > 0:
                        live_price = float(hub_p)
                except Exception:
                    pass
            config_for_grid = _config_for_grid_view(raw)
            reference_display = None
            try:
                view_price = live_price if live_price > 0 else float((state or {}).get("reference_price") or 0)
                _, _, meta = compute_grid_profit_view(state or {}, config_for_grid, view_price)
                reference_display = meta.get("ref_display")
            except Exception:
                pass
            ref_price = reference_display if reference_display is not None and reference_display > 0 else float((state or {}).get("reference_price") or 0)
            parite_pct = (live_price - ref_price) / ref_price * 100.0 if (ref_price and ref_price > 0 and live_price > 0) else None

        if bot_pct is None and parite_pct is None:
            return
        if not row or not row[0]:
            return
        baseline = payload.get("baseline")
        samples = payload.get("samples")
        if not isinstance(samples, list) or not baseline:
            return
        now_sec = int(datetime.now(timezone.utc).timestamp())
        samples.append({"ts": now_sec, "botPct": bot_pct, "paritePct": parite_pct})
        cut = now_sec - PERF_CHART_MAX_AGE_SEC
        samples[:] = [s for s in samples if isinstance(s, dict) and (s.get("ts") or 0) >= cut]
        # Sadece bu çalıştırma (started_at) sonrası örnekleri sakla
        started_at = getattr(bot, "started_at", None)
        if started_at is not None:
            started_ts = int(started_at.timestamp())
            samples[:] = [s for s in samples if (s.get("ts") or 0) >= started_ts]
            if baseline and (baseline.get("ts0") or 0) < started_ts:
                baseline = {"bot0": 0.0, "parite0": 0.0, "ts0": started_ts}
                payload["baseline"] = baseline
        payload["samples"] = samples
        payload["range"] = payload.get("range") if payload.get("range") in ("1h", "4h", "1d", "1w") else "4h"
        now = datetime.utcnow()
        db.execute(
            text("UPDATE bot_perf_chart_state SET chart_payload = :payload, updated_at = :upd WHERE bot_id = :bid"),
            {"bid": bot_id, "payload": json.dumps(payload, ensure_ascii=False), "upd": now},
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    db.execute(text("DELETE FROM bot_perf_chart_state WHERE bot_id = :bid"), {"bid": bot.id})
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
    db.execute(
        text("""
            INSERT INTO bot_engine_commands (created_at, account_id, bot_id, command, payload_json, status, request_id)
            VALUES (:created_at, :account_id, :bot_id, :command, :payload_json, 'PENDING', :request_id)
        """),
        {
            "created_at": now,
            "account_id": account_id,
            "bot_id": bot_id,
            "command": command,
            "payload_json": payload_json,
            "request_id": request_id,
        },
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    # Test hesabı paper modda kalmalı (API key yok)
    from app.services.test_account import is_test_account
    if (getattr(bot, "mode", None) or "").lower() == "paper" and not is_test_account(bot.account_id, db):
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
    ensure_state_row(db, bot.id, bot.account_id, (bot.symbol or "").upper() or "BTCUSDT")

    # Live modda bakiye kontrolü: yetersizse başlatma, PAUSED_ERROR önlenir
    is_test = is_test_account(bot.account_id, db)
    if not is_test and (getattr(bot, "mode", None) or "").lower() == "live":
        try:
            raw = json.loads(bot.config_json or "{}")
            budget = float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or raw.get("bot_budget_usdt") or 0)
            sym = (bot.symbol or "").upper().strip()
            quote_asset = (raw.get("quote_asset") or "USDT").strip().upper() if sym in ("MULTI",) else (sym[-4:] if len(sym) >= 4 and sym.endswith("USDT") else "USDT")
            if not quote_asset:
                quote_asset = "USDT"
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

    bot.status = "running"
    bot.started_at = datetime.now(timezone.utc)
    db.commit()
    seed_perf_chart_state_on_bot_start(db, bot.id)
    command_id = _insert_engine_command(db, bot.account_id, bot.id, "START", request_id=rid)
    state = load_state(db, bot.id) or {}
    state["run_id"] = f"cmd{command_id}"
    save_state(db, bot.id, bot.account_id, state)
    logger.info("BOT_RUN_ID set bot_id=%s run_id=cmd%s", bot.id, command_id)
    account = db.query(Account).filter(Account.id == bot.account_id).first()
    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_START", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=account.user_id if account else None, target_account_id=bot.account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=rid,
        meta={"bot_id": bot.id, "account_id": bot.account_id, "symbol": (bot.symbol or "") or ""},
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    bot.status = "stopped"
    db.commit()
    command_id = _insert_engine_command(db, bot.account_id, bot.id, "STOP", request_id=rid)
    account = db.query(Account).filter(Account.id == bot.account_id).first()
    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_STOP", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=account.user_id if account else None, target_account_id=bot.account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=rid,
        meta={"bot_id": bot.id, "account_id": bot.account_id, "symbol": (bot.symbol or "") or ""},
    )
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
        if isinstance(e, AppError) and getattr(e, "error_code", None) == "WORKER_ONLY_OPERATION":
            return True
    except Exception:
        pass
    s = str(e).lower()
    return "only allowed on worker" in s or "web/api cannot place" in s


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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    body = {}
    try:
        body = await request.json() if request.body else {}
    except Exception:
        pass
    if not isinstance(body, dict):
        body = {}
    convert_base = body.get("convert_base_to_quote") is True
    if convert_base:
        bot.status = "stopped"
        db.commit()
        _insert_engine_command(db, bot.account_id, bot.id, "STOP", request_id=rid)
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
                from app.services.binance_assets import get_account_keys
                from app.botengine.adapters.binance_adapter import BinanceAdapter
                keys = await get_account_keys(bot.account_id, db)
                if keys:
                    adapter = BinanceAdapter(bot.account_id, keys, paper_mode=False)
                    balances = await adapter.get_account_balances()
                    for base_asset in assets:
                        if base_asset == quote_asset:
                            continue
                        sym_pair = f"{base_asset}{quote_asset}"
                        base_free = float((balances.get(base_asset) or {}).get("free", 0) or 0)
                        if base_free > 0:
                            try:
                                filters = await adapter.get_symbol_filters(sym_pair)
                                min_notional = float(filters.get("min_notional") or 5.0)
                                price = adapter.get_price(sym_pair) or 0.0
                                if not price or price <= 0:
                                    from app.services.market_data import get_price
                                    price = get_price(sym_pair) or 0.0
                                notional = base_free * price if price else 0
                                if notional >= min_notional:
                                    client_order_id = "convert_delete_" + str(bot.id) + "_" + base_asset
                                    await adapter.place_market_sell(sym_pair, base_free, client_order_id)
                                    logger.info("bots_delete convert_base_to_quote MULTI bot_id=%s %s qty=%.8f", bot.id, sym_pair, base_free)
                                else:
                                    logger.info("bots_delete convert_base_to_quote skip MULTI bot_id=%s %s notional=%.2f < min=%.2f", bot.id, sym_pair, notional, min_notional)
                            except Exception as e:
                                logger.warning("bots_delete convert_base_to_quote MULTI %s failed bot_id=%s: %s", sym_pair, bot.id, e)
                else:
                    logger.warning("bots_delete convert_base_to_quote MULTI no keys bot_id=%s account_id=%s", bot.id, bot.account_id)
            except Exception as e:
                logger.warning("bots_delete convert_base_to_quote MULTI failed bot_id=%s: %s", bot.id, e)
                if not _is_worker_only_order_error(e):
                    raise HTTPException(status_code=400, detail=_detail_err("CONVERT_FAILED", str(e), rid))
        elif symbol and len(symbol) > 4 and symbol.endswith(("USDT", "FDUSD", "BUSD")):
            base_asset = symbol[:-5] if symbol.endswith("FDUSD") else symbol[:-4]
            try:
                from app.services.binance_assets import get_account_keys
                from app.botengine.adapters.binance_adapter import BinanceAdapter
                keys = await get_account_keys(bot.account_id, db)
                if keys:
                    adapter = BinanceAdapter(bot.account_id, keys, paper_mode=False)
                    balances = await adapter.get_account_balances()
                    base_free = float((balances.get(base_asset) or {}).get("free", 0) or 0)
                    if base_free > 0:
                        filters = await adapter.get_symbol_filters(symbol)
                        min_notional = float(filters.get("min_notional") or 5.0)
                        price = adapter.get_price(symbol) or 0.0
                        if not price or price <= 0:
                            from app.services.market_data import get_price
                            price = get_price(symbol) or 0.0
                        notional = base_free * price if price else 0
                        if notional >= min_notional:
                            client_order_id = "convert_delete_" + str(bot.id)
                            await adapter.place_market_sell(symbol, base_free, client_order_id)
                            logger.info("bots_delete convert_base_to_quote bot_id=%s symbol=%s base_qty=%.8f", bot.id, symbol, base_free)
                        else:
                            logger.info("bots_delete convert_base_to_quote skip bot_id=%s notional=%.2f < min=%.2f", bot.id, notional, min_notional)
                else:
                    logger.warning("bots_delete convert_base_to_quote no keys bot_id=%s account_id=%s", bot.id, bot.account_id)
            except Exception as e:
                logger.warning("bots_delete convert_base_to_quote failed bot_id=%s err=%s", bot.id, e)
                if not _is_worker_only_order_error(e):
                    raise HTTPException(status_code=400, detail=_detail_err("CONVERT_FAILED", str(e), rid))
    _insert_engine_command(db, bot.account_id, bot.id, "STOP", request_id=rid)
    await delete_bot_fully(bot.id, db)
    return {"ok": True, "bot_id": bot_id, "request_id": rid}


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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    cfg = config_from_ui_payload(body or {})
    bot.config_json = json.dumps(cfg.to_dict(), ensure_ascii=False)
    db.commit()
    invalidate_config_cache(bot.id)
    return {"ok": True, "bot_id": bot.id, "request_id": rid}


@router.get("/{bot_id}/events")
async def bots_events(
    request: Request,
    bot_id: int,
    limit: int = Query(100, le=500),
    after_id: Optional[int] = Query(None),
    account_id: Optional[int] = Query(None),
    account_code: Optional[str] = Query(None),
    current: dict = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List bot engine events."""
    rid = _request_id(request)
    resolved_account_id = _resolve_account_id(account_id, account_code, db)
    bot = _resolve_bot(bot_id, resolved_account_id, current, db)
    if not bot:
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    events = list_events(db, bot.id, limit=limit, after_id=after_id)
    return {"events": events, "request_id": rid}


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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    from app.bot.ledger import Ledger
    raw = json.loads(bot.config_json or "{}")
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_trdca = strategy_id == "trdca_pro" or (bot.symbol or "").upper() == "MULTI"
    dca_cycles = Ledger.get_cycle_ids(db, bot.id, bot.account_id)
    if not dca_cycles:
        dca_cycles = [1]
    if not is_trdca:
        return {"cycles": dca_cycles, "dca_cycles": dca_cycles, "trb_cycles": [], "request_id": rid}
    state = load_state(db, bot.id)
    trb = (state or {}).get("trb") or {}
    trb_count = int(trb.get("trb_cycles_count") or 0)
    trb_cycles = list(range(1, trb_count + 1)) if trb_count > 0 else []
    return {"cycles": dca_cycles, "dca_cycles": dca_cycles, "trb_cycles": trb_cycles, "request_id": rid}


@router.get("/{bot_id}/trades")
async def bots_trades(
    request: Request,
    bot_id: int,
    limit: int = Query(50, le=200),
    cycle_id: Optional[int] = Query(None, description="Filter by tur/round; omit for all"),
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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))
    from app.bot.ledger import Ledger
    ct = (cycle_type or "dca").strip().lower()
    if ct == "trb":
        trades = []
    else:
        trades = Ledger.get_trades_dict(db, bot.id, bot.account_id, limit=limit, cycle_id=cycle_id)
    cycle_summary: Optional[Dict[str, Any]] = None
    if cycle_id is not None and ct == "trb":
        cycle_summary = {"cycle_type": "trb", "trade_count": 0, "note": "Rebalancing tur işlemleri ayrı kaydedilmiyor."}
    elif cycle_id is not None and trades:
        ts_list = []
        for t in trades:
            ts_str = t.get("ts")
            if ts_str:
                try:
                    ts_list.append(datetime.fromisoformat(ts_str.replace("Z", "+00:00")))
                except Exception:
                    pass
        duration_sec = 0.0
        if len(ts_list) >= 2:
            duration_sec = (max(ts_list) - min(ts_list)).total_seconds()
        state = load_state(db, bot.id)
        pnl_usdt = None
        cycle_entry = None
        if state and state.get("cycle_pnls"):
            for c in state["cycle_pnls"]:
                if c.get("cycle_id") == cycle_id:
                    pnl_usdt = c.get("pnl_usdt")
                    cycle_entry = c
                    break
        cycle_summary = {
            "cycle_type": "dca",
            "duration_sec": round(duration_sec, 1),
            "trade_count": len(trades),
            "pnl_usdt": round(float(pnl_usdt), 2) if pnl_usdt is not None else None,
        }
        if cycle_entry is not None:
            cycle_summary["pnl_primary_mode"] = cycle_entry.get("pnl_primary_mode")
            cycle_summary["inventory_coin_adv_qty"] = cycle_entry.get("inventory_coin_adv_qty")
            cycle_summary["inventory_fees_usdt"] = cycle_entry.get("inventory_fees_usdt")
            cycle_summary["cash_pnl_usdt"] = cycle_entry.get("cash_pnl_usdt")
            cycle_summary["cash_fees_usdt"] = cycle_entry.get("cash_fees_usdt")
            cycle_summary["close_reason"] = cycle_entry.get("close_reason")
    return {"trades": trades, "cycle_summary": cycle_summary, "cycle_type": ct, "request_id": rid}


def _performance_period_range(period: str):
    """Return (start_ts, end_ts) for period. end_ts=None means now."""
    now = datetime.now(timezone.utc)
    if period == "day" or period == "1d":
        return (now - timedelta(days=1), None)
    if period == "week" or period == "7d":
        return (now - timedelta(days=7), None)
    if period == "month" or period == "30d":
        return (now - timedelta(days=30), None)
    return (None, None)  # all


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
        raise HTTPException(status_code=404, detail=_detail_err("NOT_FOUND", "Bot not found", rid))

    pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id)
    if pnl_data.get("error"):
        pnl_data = {"total_usd": 0.0, "realized": 0.0, "unrealized": 0.0, "daily": 0.0, "monthly": 0.0, "current_price": 0.0}

    now = datetime.now(timezone.utc)
    start_ts, _ = _performance_period_range(period)

    # Trades in period: count + sum(fee) for this bot only
    q_trades = db.query(Trade).filter(Trade.bot_id == bot.id, Trade.account_id == bot.account_id)
    if start_ts:
        q_trades = q_trades.filter(Trade.ts >= start_ts)
    trades_in_period = q_trades.order_by(Trade.ts.asc()).all()
    trades_count = len(trades_in_period)
    fees_usd = sum(float(t.fee or 0) for t in trades_in_period)

    total_usd = float(pnl_data.get("total_usd", 0) or 0)
    realized = float(pnl_data.get("realized", 0) or 0)

    # Initial and PnL for selected period. "all" = başlangıç sermayesine göre (başlar başlamaz kar göstermemek için).
    cfg_perf = json.loads(bot.config_json or "{}") if getattr(bot, "config_json", None) else {}
    config_initial = float(
        cfg_perf.get("initial_capital_usdt") or cfg_perf.get("budget_usd")
        or cfg_perf.get("bot_budget_usdt") or cfg_perf.get("bot_budget_quote") or 0
    )

    if start_ts and trades_in_period:
        # Period start: first snapshot before start_ts or first trade in period as proxy
        first_snap = (
            db.query(PnlSnapshot)
            .filter(PnlSnapshot.bot_id == bot.id, PnlSnapshot.account_id == bot.account_id, PnlSnapshot.ts < start_ts)
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
            first_buy = db.query(Trade).filter(Trade.bot_id == bot.id, Trade.account_id == bot.account_id, Trade.side == "BUY").order_by(Trade.ts.asc()).first()
            if first_buy:
                initial_usd = float(first_buy.qty * first_buy.price)
        if initial_usd <= 0:
            initial_usd = total_usd
        pnl_usd = total_usd - initial_usd
    # PNL kartı: her tur tamamlandıkça eklenen kar toplamı. Önce state.cycle_pnls kullan (bu tur dahil anında yansır); yoksa CYCLE_END eventlerinden topla.
    state_for_pnl = load_state(db, bot.id)
    pnl_usd = 0.0
    if state_for_pnl and state_for_pnl.get("cycle_pnls"):
        for c in state_for_pnl["cycle_pnls"]:
            p = c.get("pnl_usdt_net") or c.get("pnl_usdt")
            if p is not None:
                pnl_usd += float(p)
    else:
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
    # Yüzde her zaman başlangıç sermayesine göre (dönem değişince saçma değer çıkmaması için)
    initial_for_pnl = config_initial if config_initial > 0 else (initial_usd or 1.0)
    pnl_pct = (pnl_usd / initial_for_pnl * 100.0) if initial_for_pnl > 0 else 0.0
    real_performance_pct = pnl_pct

    # Cycles (tur) count for this bot
    from app.bot.ledger import Ledger
    cycles = Ledger.get_cycle_ids(db, bot.id, bot.account_id)
    cycles_count = max(cycles) if cycles else 0

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
                chart_series.append({"t": t_str, "value": round(val_usd, 2), "pct": round(bp, 2)})
                pair_series.append({"t": t_str, "price": 100.0 * (1.0 + pp / 100.0), "pct": round(pp, 2)})
            if chart_series and total_usd is not None:
                last_val = chart_series[-1].get("value", 0)
                if abs(float(total_usd) - last_val) > 0.01:
                    bp_now = (total_usd / init_cap - 1.0) * 100.0 if init_cap > 0 else 0.0
                    chart_series.append({"t": now.isoformat(), "value": round(float(total_usd), 2), "pct": round(bp_now, 2)})
                    parite_now = pair_series[-1].get("pct") if pair_series else 0.0
                    init_prices = baseline_chart.get("initial_prices") or {}
                    coin_weights_b = baseline_chart.get("coin_weights") or {}
                    quote_a = (cfg_perf.get("quote_asset") or "USDT").strip().upper()
                    if init_prices and coin_weights_b:
                        try:
                            curr_prices = await _fetch_prices_parallel(list(coin_weights_b.keys()), quote_a)
                            parite_pct_live = compute_trdca_parite_pct(init_prices, coin_weights_b, curr_prices, quote_a)
                            if parite_pct_live is not None:
                                parite_now = round(parite_pct_live, 2)
                        except Exception:
                            pass
                    pair_series.append({"t": now.isoformat(), "price": 100.0 * (1.0 + parite_now / 100.0), "pct": parite_now})
        elif strategy_id_chart == "trdca_pro" and total_usd is not None and config_initial > 0:
            init_cap = config_initial
            bp_now = (total_usd / init_cap - 1.0) * 100.0
            parite_now = 0.0
            row_b = db.execute(text("SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"), {"bid": bot.id}).fetchone()
            payload_b = json.loads(row_b[0]) if row_b and row_b[0] else {}
            baseline_chart = payload_b.get("baseline") or {}
            init_prices = baseline_chart.get("initial_prices") or {}
            coin_weights_b = baseline_chart.get("coin_weights") or {}
            quote_a = (cfg_perf.get("quote_asset") or "USDT").strip().upper()
            if init_prices and coin_weights_b:
                try:
                    curr_prices = await _fetch_prices_parallel(list(coin_weights_b.keys()), quote_a)
                    parite_pct_live = compute_trdca_parite_pct(init_prices, coin_weights_b, curr_prices, quote_a)
                    if parite_pct_live is not None:
                        parite_now = round(parite_pct_live, 2)
                except Exception:
                    pass
            chart_series = [{"t": now.isoformat(), "value": round(float(total_usd), 2), "pct": round(bp_now, 2)}]
            pair_series = [{"t": now.isoformat(), "price": 100.0 * (1.0 + parite_now / 100.0), "pct": parite_now}]

    all_snapshots = []
    all_trades = []
    if not chart_series and not pair_series:
        all_snapshots = (
            db.query(PnlSnapshot)
            .filter(PnlSnapshot.bot_id == bot.id, PnlSnapshot.account_id == bot.account_id)
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
            init_usd = float(all_snapshots[0].total_usd) if all_snapshots else total_usd or 0.0
            init_price = float(all_trades[0].price) if all_trades else float(pnl_data.get("current_price") or 0) or 0.0
            if init_price <= 0:
                init_price = 1.0

            snap_idx = 0
            trade_idx = 0
            for ts, t_str in sorted_times:
                while snap_idx < len(all_snapshots) and all_snapshots[snap_idx].ts <= ts:
                    snap_idx += 1
                while trade_idx < len(all_trades) and all_trades[trade_idx].ts <= ts:
                    trade_idx += 1
                last_usd = float(all_snapshots[snap_idx - 1].total_usd) if snap_idx > 0 else init_usd
                last_price = float(all_trades[trade_idx - 1].price) if trade_idx > 0 else init_price
                balance_pct = (last_usd / init_usd - 1.0) * 100.0 if init_usd > 0 else 0.0
                price_pct = (last_price / init_price - 1.0) * 100.0 if init_price > 0 else 0.0
                chart_series.append({"t": t_str, "value": last_usd, "pct": round(balance_pct, 2)})
                pair_series.append({"t": t_str, "price": last_price, "pct": round(price_pct, 2)})

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
                chart_series = [chart_series[i] for i in range(len(chart_series)) if i in resampled_indices]
                pair_series = [pair_series[i] for i in range(len(pair_series)) if i in resampled_indices]

            if not chart_series and total_usd is not None:
                chart_series = [{"t": now.isoformat(), "value": total_usd, "pct": 0.0}]
                pair_series = [{"t": now.isoformat(), "price": float(pnl_data.get("current_price") or 0), "pct": 0.0}]
            if len(chart_series) == 1 and total_usd is not None:
                cur_price = float(pnl_data.get("current_price") or 0) or (float(all_trades[-1].price) if all_trades else 0)
                init_usd_chart = float(chart_series[0]["value"])
                init_price_chart = float(pair_series[0]["price"]) if pair_series and pair_series[0].get("price") else cur_price or 1.0
                balance_pct = (total_usd / init_usd_chart - 1.0) * 100.0 if init_usd_chart > 0 else 0.0
                price_pct = (cur_price / init_price_chart - 1.0) * 100.0 if init_price_chart > 0 else 0.0
                chart_series.append({"t": now.isoformat(), "value": total_usd, "pct": round(balance_pct, 2)})
                pair_series.append({"t": now.isoformat(), "price": cur_price, "pct": round(price_pct, 2)})

    # Rapor için: başlangıç/güncel fiyat (perfReport'ta "—" çıkmaması için)
    state = state_for_pnl or load_state(db, bot.id)
    reference_price = None
    if all_trades:
        reference_price = float(all_trades[0].price)
    elif pair_series and len(pair_series) > 0 and pair_series[0].get("price") is not None and float(pair_series[0]["price"]) > 0:
        reference_price = float(pair_series[0]["price"])
    if reference_price is None and state and (state.get("reference_price") or 0) > 0:
        reference_price = float(state["reference_price"])
    current_price_out = None
    if pnl_data.get("current_price") and float(pnl_data.get("current_price") or 0) > 0:
        current_price_out = float(pnl_data["current_price"])
    elif all_trades:
        current_price_out = float(all_trades[-1].price)
    elif pair_series and len(pair_series) > 0 and pair_series[-1].get("price") is not None and float(pair_series[-1]["price"]) > 0:
        current_price_out = float(pair_series[-1]["price"])
    if current_price_out is None and state and (state.get("reference_price") or 0) > 0:
        current_price_out = float(state["reference_price"])
    if current_price_out is None or current_price_out <= 0:
        try:
            hub_p = price_hub.get_price(bot.symbol or "")
            if hub_p is not None and float(hub_p) > 0:
                current_price_out = float(hub_p)
        except Exception:
            pass
    if reference_price is None and current_price_out is not None and current_price_out > 0:
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
        if isinstance(tb, dict) and any(k in tb for k in ("equity_usdt", "target_quote_usdt", "target_base_usdt")):
            target_budgets = {k: round(float(v), 2) if isinstance(v, (int, float)) else v for k, v in tb.items() if k in ("equity_usdt", "target_quote_usdt", "target_base_usdt", "ts")}

    result = {
        "request_id": rid,
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct, 2),
        "real_performance_pct": round(real_performance_pct, 2),
        "trades_count": trades_count,
        "cycles_count": cycles_count,
        "fees_usd": round(fees_usd, 2),
        "realized": round(realized, 2),
        "total_usd": round(total_usd, 2),
        "initial_usd": round(initial_usd, 2),
        "balance_start_usd": round(initial_usd, 2),
        "config_budget_usd": config_budget_usd,
        "balance_end_usd": round(total_usd, 2),
        "reference_price": round(reference_price, 8) if reference_price is not None else None,
        "current_price": round(current_price_out, 8) if current_price_out is not None else None,
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
    }

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
