#!/usr/bin/env python3
"""Ayserose yerel 5dk backtest aracı.

Bu dosya ayrı bir yerel web ekranı açar; canlı sunucuya, kullanıcı hesaplarına
ve gerçek emirlere dokunmaz. Ekonomik simülasyon doğrudan projenin
``run_backtest`` / ``dca_grid_trailing`` kodunu, dinamik tur kararları ise aynı
Dynamic Param Score V6 ve rejim çarpanı akışını çağırır.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import csv
import io
import json
import math
import re
import shutil
import socket
import sqlite3
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

# Doğrudan ``python backtest/app.py`` çalıştırıldığında bu klasördeki app.py,
# projenin gerçek ``app`` paketini gölgelemesin.
_BOOT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOOT_PROJECT_ROOT) in sys.path:
    sys.path.remove(str(_BOOT_PROJECT_ROOT))
sys.path.insert(0, str(_BOOT_PROJECT_ROOT))

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.botengine.dynamic import cycle_manager
from app.services.dynamic_param_score.adapters import (
    decision_to_param_assistant_result,
    params_to_grid_config,
)
from app.services.dynamic_param_score.consumer_policy import (
    build_dynamic_round_context,
    build_param_assistant_context,
)
from app.services.dynamic_param_score.data_collector import default_exchange_constraints
from app.services.dynamic_param_score.engine import get_engine
from app.services.dynamic_param_score.models import (
    BtcReferenceData,
    Candle,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
from app.services.param_optimizer.backtest import run_backtest


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "candles.sqlite3"
RUN_DIR = DATA_DIR / "runs"
UI_PATH = ROOT / "ui.html"
LEGACY_DB_PATH = PROJECT_ROOT / "data" / "local_backtest" / "candles.sqlite3"
BINANCE_BASE = "https://api.binance.com"
DAY_MS = 86_400_000
YEAR_DAYS = 365
WARMUP_DAYS = 35
INTERVAL_MS = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000}
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _closed_end(interval: str, now_ms: Optional[int] = None) -> int:
    step = INTERVAL_MS[interval]
    return (int(now_ms or _now_ms()) // step) * step


def normalize_symbol(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    if value.endswith("USDT"):
        value = value[:-4]
    if not value or len(value) > 12 or not re.fullmatch(r"[A-Z0-9]+", value):
        raise ValueError("Coin adı geçersiz.")
    return value + "USDT"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _date_ms(value: Optional[str], *, end_of_day: bool = False) -> Optional[int]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Tarih biçimi geçersiz.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day and "T" not in raw:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(parsed.timestamp() * 1000)


class BacktestRequest(BaseModel):
    coin: str = Field(min_length=1, max_length=20)
    balance: float = Field(gt=0, le=100_000_000)
    dynamic_mode: bool = False
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    params: Dict[str, Any]


class ParameterAssistantRequest(BaseModel):
    coin: str = Field(min_length=1, max_length=20)
    balance: float = Field(gt=0, le=100_000_000)
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    start_date: str


class CandleStore:
    """OHLCV-only SQLite cache with gap-aware incremental completion."""

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path == DB_PATH and not path.exists() and LEGACY_DB_PATH.is_file():
            # Eski önbelleği silmeden yeni backtest klasörüne kopyala.
            shutil.copy2(LEGACY_DB_PATH, path)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    o REAL NOT NULL,
                    h REAL NOT NULL,
                    l REAL NOT NULL,
                    c REAL NOT NULL,
                    v REAL NOT NULL,
                    PRIMARY KEY(symbol, interval, open_time)
                );
                CREATE TABLE IF NOT EXISTS coverage (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    covered_start INTEGER NOT NULL,
                    covered_end INTEGER NOT NULL,
                    checked_at INTEGER NOT NULL,
                    PRIMARY KEY(symbol, interval)
                );
                CREATE INDEX IF NOT EXISTS ix_candles_range
                ON candles(symbol, interval, open_time);
                """
            )

    def times(self, symbol: str, interval: str, start: int, end: int) -> List[int]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT open_time FROM candles
                WHERE symbol=? AND interval=? AND open_time>=? AND open_time<?
                ORDER BY open_time
                """,
                (symbol, interval, start, end),
            ).fetchall()
        return [int(r[0]) for r in rows]

    def coverage(self, symbol: str, interval: str) -> Optional[sqlite3.Row]:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM coverage WHERE symbol=? AND interval=?",
                (symbol, interval),
            ).fetchone()

    def save(self, symbol: str, interval: str, candles: Iterable[Mapping[str, Any]]) -> int:
        rows = [
            (
                symbol,
                interval,
                int(c["t"]),
                float(c["o"]),
                float(c["h"]),
                float(c["l"]),
                float(c["c"]),
                float(c.get("v") or 0),
            )
            for c in candles
        ]
        if not rows:
            return 0
        with self.connect() as db:
            db.executemany(
                """
                INSERT INTO candles(symbol,interval,open_time,o,h,l,c,v)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,interval,open_time) DO UPDATE SET
                    o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v
                """,
                rows,
            )
        return len(rows)

    def mark_covered(self, symbol: str, interval: str, start: int, end: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO coverage(symbol,interval,covered_start,covered_end,checked_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(symbol,interval) DO UPDATE SET
                    covered_start=MIN(coverage.covered_start,excluded.covered_start),
                    covered_end=MAX(coverage.covered_end,excluded.covered_end),
                    checked_at=excluded.checked_at
                """,
                (symbol, interval, start, end, _now_ms()),
            )

    def load(self, symbol: str, interval: str, start: int, end: int) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT open_time,o,h,l,c,v FROM candles
                WHERE symbol=? AND interval=? AND open_time>=? AND open_time<?
                ORDER BY open_time
                """,
                (symbol, interval, start, end),
            ).fetchall()
        return [
            {
                "t": int(r["open_time"]),
                "o": float(r["o"]),
                "h": float(r["h"]),
                "l": float(r["l"]),
                "c": float(r["c"]),
                "v": float(r["v"]),
            }
            for r in rows
        ]


def _missing_ranges(
    existing: List[int], start: int, end: int, step: int, coverage: Optional[sqlite3.Row]
) -> List[tuple[int, int]]:
    """Return [start,end) gaps; never re-request a known pre-listing prefix."""
    wanted_start = start
    if coverage and int(coverage["covered_start"]) <= start:
        wanted_start = max(start, int(coverage["covered_end"]))
    if not existing:
        return [(wanted_start, end)] if wanted_start < end else []

    ranges: List[tuple[int, int]] = []
    cov_start = int(coverage["covered_start"]) if coverage else None
    if cov_start is None or cov_start > start:
        if existing[0] > start:
            ranges.append((start, existing[0]))
    for left, right in zip(existing, existing[1:]):
        gap_start = left + step
        if right > gap_start:
            ranges.append((gap_start, right))
    tail = existing[-1] + step
    if tail < end:
        ranges.append((tail, end))
    return ranges


async def _fetch_range(
    client: httpx.AsyncClient,
    store: CandleStore,
    symbol: str,
    interval: str,
    start: int,
    end: int,
    progress: Callable[[str], None],
) -> int:
    step = INTERVAL_MS[interval]
    cursor = start
    total = 0
    retries = 0
    while cursor < end:
        try:
            response = await client.get(
                "/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end - 1,
                    "limit": 1000,
                },
            )
            if response.status_code in (418, 429):
                retries += 1
                if retries > 5:
                    response.raise_for_status()
                await asyncio.sleep(min(30, 2**retries))
                continue
            response.raise_for_status()
            raw = response.json()
            part = []
            for row in raw if isinstance(raw, list) else []:
                try:
                    ts = int(row[0])
                    if start <= ts < end:
                        part.append(
                            {
                                "t": ts,
                                "o": float(row[1]),
                                "h": float(row[2]),
                                "l": float(row[3]),
                                "c": float(row[4]),
                                "v": float(row[5]),
                            }
                        )
                except (IndexError, TypeError, ValueError):
                    continue
            if not part:
                break
            store.save(symbol, interval, part)
            total += len(part)
            next_cursor = int(part[-1]["t"]) + step
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            retries = 0
            progress(f"{symbol} {interval}: {total:,} eksik mum tamamlandı")
            if len(part) < 1000:
                break
            await asyncio.sleep(0.12)
        except httpx.HTTPError:
            retries += 1
            if retries > 4:
                raise
            await asyncio.sleep(min(12, 2**retries))
    return total


async def ensure_series(
    client: httpx.AsyncClient,
    store: CandleStore,
    symbol: str,
    interval: str,
    start: int,
    end: int,
    progress: Callable[[str], None],
) -> List[Dict[str, Any]]:
    step = INTERVAL_MS[interval]
    start = (start // step) * step
    end = (end // step) * step
    existing = store.times(symbol, interval, start, end)
    gaps = _missing_ranges(existing, start, end, step, store.coverage(symbol, interval))
    if not gaps:
        progress(f"{symbol} {interval}: önbellek güncel ({len(existing):,} mum)")
    for gap_start, gap_end in gaps:
        progress(f"{symbol} {interval}: eksik aralık indiriliyor")
        await _fetch_range(client, store, symbol, interval, gap_start, gap_end, progress)
    store.mark_covered(symbol, interval, start, end)
    out = store.load(symbol, interval, start, end)
    if len(out) < 20:
        raise ValueError(f"{symbol} {interval} için yeterli geçmiş bulunamadı.")
    return out


async def fetch_constraints(client: httpx.AsyncClient, symbol: str, fee_rate: float) -> ExchangeConstraints:
    fallback = default_exchange_constraints(symbol)
    fallback.taker_fee_pct = fee_rate * 100
    fallback.maker_fee_pct = fee_rate * 100
    try:
        response = await client.get("/api/v3/exchangeInfo", params={"symbol": symbol})
        response.raise_for_status()
        symbols = response.json().get("symbols") or []
        filters = {f.get("filterType"): f for f in (symbols[0].get("filters") or [])}
        lot = filters.get("LOT_SIZE") or {}
        price_filter = filters.get("PRICE_FILTER") or {}
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return ExchangeConstraints(
            min_notional=_finite(notional.get("minNotional"), fallback.min_notional),
            step_size=_finite(lot.get("stepSize"), fallback.step_size),
            tick_size=_finite(price_filter.get("tickSize"), fallback.tick_size),
            min_qty=_finite(lot.get("minQty"), fallback.min_qty),
            taker_fee_pct=fee_rate * 100,
            maker_fee_pct=fee_rate * 100,
            estimated_slippage_pct=fallback.estimated_slippage_pct,
        )
    except Exception:
        return fallback


def resample(candles: List[Dict[str, Any]], target_ms: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    bucket = -1
    for c in candles:
        b = int(c["t"]) // target_ms
        if b != bucket:
            if cur:
                out.append(cur)
            bucket = b
            cur = dict(c)
            cur["t"] = b * target_ms
        else:
            assert cur is not None
            cur["h"] = max(float(cur["h"]), float(c["h"]))
            cur["l"] = min(float(cur["l"]), float(c["l"]))
            cur["c"] = float(c["c"])
            cur["v"] = float(cur["v"]) + float(c["v"])
    if cur:
        out.append(cur)
    return out


def _slice_before(
    candles: List[Dict[str, Any]], timestamps: List[int], as_of: int, limit: int
) -> List[Dict[str, Any]]:
    idx = bisect.bisect_left(timestamps, as_of)
    return candles[max(0, idx - limit) : idx]


def _to_candles(rows: List[Dict[str, Any]]) -> List[Candle]:
    return [Candle.from_dict(x) for x in rows]


class HistoricalDynamicAdapter:
    """Causal bridge from cached history into the production V6 round flow."""

    def __init__(
        self,
        symbol: str,
        budget: float,
        base_params: Dict[str, Any],
        coin_5m: List[Dict[str, Any]],
        btc_1h: List[Dict[str, Any]],
        btc_4h: List[Dict[str, Any]],
        constraints: ExchangeConstraints,
        events: List[Dict[str, Any]],
        diagnostics: List[Dict[str, Any]],
        progress_cb: Optional[Callable[[int, int], None]] = None,
        total_bars: int = 1,
    ):
        self.symbol = symbol
        self.budget = budget
        self.base_params = base_params
        self.c5 = coin_5m
        self.c15 = resample(coin_5m, 900_000)
        self.c1h = resample(coin_5m, 3_600_000)
        self.c4h = resample(coin_5m, 14_400_000)
        self.btc1 = btc_1h
        self.btc4 = btc_4h
        self.times = {
            id(rows): [int(c["t"]) for c in rows]
            for rows in (self.c5, self.c15, self.c1h, self.c4h, self.btc1, self.btc4)
        }
        self.steps = {
            id(self.c5): INTERVAL_MS["5m"],
            id(self.c15): 900_000,
            id(self.c1h): INTERVAL_MS["1h"],
            id(self.c4h): INTERVAL_MS["4h"],
            id(self.btc1): INTERVAL_MS["1h"],
            id(self.btc4): INTERVAL_MS["4h"],
        }
        self.constraints = constraints
        self.events = events
        self.diagnostics = diagnostics
        self.progress_cb = progress_cb
        self.total_bars = max(1, int(total_bars))
        self.last_cycle = 0
        self.last_decision_ts = 0
        self.round_pending = False
        self.next_retry_ts = 0
        self.decision_count = 0
        self.reference_set = False

    def _slice(self, rows: List[Dict[str, Any]], as_of: int, limit: int) -> List[Dict[str, Any]]:
        # Türetilmiş 15dk/1s/4s mumun zaman damgası mum açılışıdır. Doğrudan
        # ``as_of`` ile kesmek o henüz kapanmadan tüm high/low/close değerlerini
        # göstererek geleceğe bakış üretirdi. Yalnız kapanmış kovaları görünür kıl.
        step = self.steps[id(rows)]
        closed_cutoff = (int(as_of) // step) * step
        return _slice_before(rows, self.times[id(rows)], closed_cutoff, limit)

    def market(self, as_of: int, price: float) -> MarketDataBundle:
        c5 = self._slice(self.c5, as_of, 2016)
        c15 = self._slice(self.c15, as_of, 672)
        c1 = self._slice(self.c1h, as_of, 240)
        c4 = self._slice(self.c4h, as_of, 42)
        b1 = self._slice(self.btc1, as_of, 240)
        b4 = self._slice(self.btc4, as_of, 42)
        if c5 and int(c5[-1]["t"]) >= as_of:
            self.diagnostics.append(
                {"severity": "ERROR", "code": "FUTURE_DATA_LEAK", "ts": as_of, "detail": c5[-1]["t"]}
            )
        quote_volume = sum(float(c["v"]) * float(c["c"]) for c in c1[-24:])
        base_volume = sum(float(c["v"]) for c in c1[-24:])
        btc_ref = None
        if b1:
            closes = [float(c["c"]) for c in b1]
            from app.botengine.dynamic.indicators import ema_last

            def ret(n: int, rows: List[Dict[str, Any]]) -> Optional[float]:
                if len(rows) <= n or float(rows[-n - 1]["c"]) <= 0:
                    return None
                return (float(rows[-1]["c"]) / float(rows[-n - 1]["c"]) - 1) * 100

            one_hour_rets = [
                (closes[i] / closes[i - 1] - 1) * 100
                for i in range(max(1, len(closes) - 6), len(closes))
                if closes[i - 1] > 0
            ]
            btc_ref = BtcReferenceData(
                candles_1h=_to_candles(b1),
                candles_4h=_to_candles(b4),
                return_1h_pct=ret(1, b1),
                return_4h_pct=ret(1, b4) if len(b4) > 1 else ret(4, b1),
                return_24h_pct=ret(24, b1),
                price=closes[-1],
                ema200_1h=ema_last(closes, 200) if len(closes) >= 200 else None,
                crash_velocity=min(one_hour_rets) if one_hour_rets else None,
            )
        return MarketDataBundle(
            symbol=self.symbol,
            base_asset=self.symbol[:-4],
            quote_asset="USDT",
            ticker_price=price,
            volume_24h=base_volume,
            quote_volume_24h=quote_volume,
            market_timestamp=as_of,
            candles_5m=_to_candles(c5),
            candles_15m=_to_candles(c15),
            candles_1h=_to_candles(c1),
            candles_4h=_to_candles(c4),
            orderbook_top=None,
            btc_reference_data=btc_ref,
            data_window={"source": "local_backtest_cache", "causal": True},
        )

    def before_tick(self, ctx: Dict[str, Any]) -> None:
        state = ctx["state"]
        cycle_id = int(state.get("cycle_id") or 1)
        if cycle_id == self.last_cycle and not self.round_pending:
            return
        as_of = int(ctx["ts"])
        if self.round_pending and as_of < self.next_retry_ts:
            ctx["skip_strategy"] = True
            return
        if cycle_id == self.last_cycle and as_of <= self.last_decision_ts:
            ctx["skip_strategy"] = bool(self.round_pending)
            return
        if not self.reference_set:
            cycle_manager.set_reference(state, self.base_params, source="local_backtest")
            self.reference_set = True
        price = float(ctx["price"])
        market = self.market(as_of, price)
        base = float(ctx["base_balance"])
        quote = float(ctx["quote_balance"])
        equity = quote + base * price
        portfolio = PortfolioState(
            base_balance=base,
            quote_balance=quote,
            base_value_usdt=base * price,
            quote_value_usdt=quote,
            total_equity_usdt=equity,
            current_base_exposure_frac=(base * price / equity) if equity > 0 else 0,
        )
        dps_ctx = build_dynamic_round_context(
            budget_usdt=equity,
            cycle_id=cycle_id,
            bot_id=None,
            last_rebalance_round_id=None,
            allow_live=True,
            allow_no_trade=True,
        )
        decision = get_engine().calculate_decision(
            symbol=self.symbol,
            market_data=market,
            portfolio_state=portfolio,
            exchange_constraints=self.constraints,
            bot_context=dps_ctx,
            persist=False,
        )
        pending = not bool(decision.deployable and decision.params)
        applied = (
            params_to_grid_config(
                decision.params,
                pool_version=decision.params.pool_version,
                ui_display=True,
            )
            if decision.params and not pending
            else {}
        )
        reasons = list(decision.blocking_reasons or [])
        fallbacks: List[str] = []
        if not pending:
            cycle_manager.apply_overlay(ctx["config"], {"applied": applied})
            sell_count = len(applied.get("sell_grids") or [])
            buy_count = len(applied.get("buy_grids") or [])
            for key, count, default in (
                ("sell_grid_fired", sell_count, False),
                ("sell_grid_trigger_price", sell_count, None),
                ("sell_grid_peak_price", sell_count, None),
                ("sell_grid_fill_price", sell_count, None),
                ("buy_grid_fired", buy_count, False),
                ("buy_grid_trigger_price", buy_count, None),
                ("buy_grid_trough_price", buy_count, None),
                ("buy_grid_fill_price", buy_count, None),
            ):
                state[key] = [default] * count
            cycle_manager._sync_target_budgets(
                state,
                applied,
                price=price,
                cycle_id=cycle_id,
                portfolio=portfolio,
            )
            self.next_retry_ts = 0
        else:
            self.next_retry_ts = as_of + 30 * 60 * 1000
            ctx["skip_strategy"] = True
        raw = decision.params.to_dict() if decision.params else None
        self.events.append(
            {
                "event": "dynamic_decision",
                "ts": as_of,
                "cycle_id": cycle_id,
                "decision_id": decision.decision_id,
                "regime": decision.regime_tag,
                "risk_state": decision.risk_state,
                "final_action": decision.final_action,
                "deployable": decision.deployable,
                "round_pending": pending,
                "param_score": decision.param_score,
                "risk_score": decision.risk_score,
                "profile": decision.selected_profile_name,
                "engine_version": (decision.telemetry or {}).get("engine_version"),
                "market_price": price,
                "portfolio_equity": equity,
                "portfolio_base_balance": base,
                "portfolio_quote_balance": quote,
                "portfolio_base_exposure_frac": portfolio.current_base_exposure_frac,
                "exchange_min_notional": self.constraints.min_notional,
                "exchange_step_size": self.constraints.step_size,
                "exchange_tick_size": self.constraints.tick_size,
                "market_5m_last_ts": int(market.candles_5m[-1].t) if market.candles_5m else None,
                "market_5m_count": len(market.candles_5m or []),
                "market_15m_count": len(market.candles_15m or []),
                "market_1h_count": len(market.candles_1h or []),
                "blocking_reasons": _json(decision.blocking_reasons),
                "warnings": _json(decision.warnings),
                "reasons": _json(reasons),
                "fallbacks": _json(fallbacks),
                "raw_params": _json(raw),
                "applied_params": _json(applied),
                "telemetry": _json(decision.telemetry),
            }
        )
        self.decision_count += 1
        if self.progress_cb:
            self.progress_cb(self.decision_count, int(ctx.get("bar_index") or 0))
        self.last_cycle = cycle_id
        self.last_decision_ts = as_of
        self.round_pending = bool(pending)


def validate_params(params: Dict[str, Any], balance: float, symbol: str) -> Dict[str, Any]:
    p = dict(params or {})
    base = _finite(p.get("base_alloc_pct"), 50)
    quote = _finite(p.get("quote_alloc_pct"), 100 - base)
    if base < 0 or quote < 0 or abs(base + quote - 100) > 0.05:
        raise ValueError("Base ve USDT oranlarının toplamı 100 olmalı.")

    def grids(
        key: str, pct_key: str, qty_key: str, *, allow_empty: bool = False
    ) -> List[Dict[str, float]]:
        rows = p.get(key) or []
        if not isinstance(rows, list) or (not rows and not allow_empty):
            raise ValueError(f"{key} en az bir satır içermeli.")
        out = []
        for row in rows:
            distance = _finite(row.get(pct_key))
            qty = _finite(row.get(qty_key))
            if distance <= 0 or qty <= 0:
                raise ValueError(f"{key} mesafe ve miktarları sıfırdan büyük olmalı.")
            out.append({pct_key: distance, qty_key: qty})
        if out and abs(sum(x[qty_key] for x in out) - 100) > 0.2:
            raise ValueError(f"{key} miktarlarının toplamı 100 olmalı.")
        return out

    p["symbol"] = symbol
    p["initial_capital_usdt"] = balance
    p["base_alloc_pct"] = base
    p["quote_alloc_pct"] = quote
    p["buy_grids"] = grids(
        "buy_grids", "buy_grid_pct", "buy_qty_pct_of_quote", allow_empty=True
    )
    p["sell_grids"] = grids(
        "sell_grids", "sell_grid_pct", "sell_qty_pct_of_base", allow_empty=True
    )
    if not p["buy_grids"] and not p["sell_grids"]:
        raise ValueError("En az bir alış veya satış grid yüzeyi gerekli.")
    p["buy_disabled"] = bool(p.get("buy_disabled") or not p["buy_grids"])
    p["max_buy_levels"] = int(
        p.get("max_buy_levels") if p.get("max_buy_levels") is not None else len(p["buy_grids"])
    )
    p.setdefault("max_base_exposure_frac", 1.0)
    p.setdefault("rebuy_enabled", True)
    p.setdefault("resell_enabled", True)
    p.setdefault("min_notional_guard", 10.0)
    return p


def _audit_diagnostics(event: Dict[str, Any], diagnostics: List[Dict[str, Any]]) -> None:
    for key in ("base_after", "quote_after", "equity"):
        if key in event and not math.isfinite(_finite(event.get(key), float("nan"))):
            diagnostics.append(
                {"severity": "ERROR", "code": "NON_FINITE_VALUE", "ts": event.get("ts"), "detail": key}
            )
    # State muhasebesi 10 ondalığa yuvarlandığı için tam bakiye tüketen BUY'da
    # birkaç milyonluk USDT negatif tozu oluşabilir; ekonomik eksi bakiye değildir.
    if _finite(event.get("base_after")) < -1e-5 or _finite(event.get("quote_after")) < -1e-5:
        diagnostics.append(
            {
                "severity": "ERROR",
                "code": "NEGATIVE_BALANCE",
                "ts": event.get("ts"),
                "detail": _json(event),
            }
        )


def cycle_rows(events: List[Dict[str, Any]], symbol: str) -> List[Dict[str, Any]]:
    base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol
    out: List[Dict[str, Any]] = []
    for event in events:
        if event.get("event") != "fill" or not event.get("cycle_closed"):
            continue
        ts = int(event.get("ts") or 0)
        out.append(
            {
                "cycle_id": int(event.get("cycle_id") or len(out) + 1),
                "closed_at": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(),
                "month": datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m"),
                "direction": event.get("cycle_direction"),
                "profit_usdt": round(_finite(event.get("cycle_profit_usdt")), 8),
                "profit_coin": round(_finite(event.get("cycle_profit_coin")), 12),
                "profit_coin_asset": base_asset,
                "profit_coin_method": "Tur USDT kârı / tur kapanış fiyatı",
                "inventory_coin_profit": round(
                    _finite(event.get("inventory_coin_profit")), 12
                ),
                "cash_profit_usdt": round(_finite(event.get("cash_profit_usdt")), 8),
                "close_price": round(_finite(event.get("fill_price")), 10),
                "commission_usdt": round(_finite(event.get("cycle_fee_usdt")), 8),
                "commission_included_in_profit": True,
            }
        )
    return out


def monthly_rows(
    equity_events: List[Dict[str, Any]],
    initial: float,
    cycles: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    initial_coin_price: Optional[float] = None,
) -> List[Dict[str, Any]]:
    endings: Dict[str, Dict[str, Any]] = {}
    for row in equity_events:
        month = datetime.fromtimestamp(int(row["ts"]) / 1000, tz=timezone.utc).strftime("%Y-%m")
        endings[month] = row
    out = []
    previous = initial
    first_coin_price = _finite(initial_coin_price)
    previous_coin_price = first_coin_price
    for month in sorted(endings):
        end = float(endings[month]["equity"])
        end_coin_price = _finite(endings[month].get("close"))
        bot_return_pct = (end / previous - 1) * 100 if previous > 0 else 0.0
        coin_return_pct = (
            (end_coin_price / previous_coin_price - 1) * 100
            if previous_coin_price > 0 and end_coin_price > 0
            else 0.0
        )
        bot_return_vs_initial_pct = (end / initial - 1) * 100 if initial > 0 else 0.0
        coin_return_vs_initial_pct = (
            (end_coin_price / first_coin_price - 1) * 100
            if first_coin_price > 0 and end_coin_price > 0
            else 0.0
        )
        month_cycles = [row for row in (cycles or []) if row.get("month") == month]
        month_fills = [
            row
            for row in (events or [])
            if row.get("event") == "fill"
            and datetime.fromtimestamp(int(row.get("ts") or 0) / 1000, timezone.utc).strftime(
                "%Y-%m"
            )
            == month
        ]
        out.append(
            {
                "month": month,
                "start_equity": round(previous, 4),
                "end_equity": round(end, 4),
                "monthly_pnl": round(end - previous, 4),
                "monthly_return_pct": round(bot_return_pct, 4),
                "bot_return_pct": round(bot_return_pct, 4),
                "coin_return_pct": round(coin_return_pct, 4),
                "alpha_pct": round(bot_return_pct - coin_return_pct, 4),
                "pnl_vs_initial": round(end - initial, 4),
                "return_vs_initial_pct": round(bot_return_vs_initial_pct, 4),
                "coin_return_vs_initial_pct": round(coin_return_vs_initial_pct, 4),
                "alpha_vs_initial_pct": round(
                    bot_return_vs_initial_pct - coin_return_vs_initial_pct, 4
                ),
                "cycle_count": len(month_cycles),
                "up_cycles": sum(1 for row in month_cycles if row.get("direction") == "UP"),
                "down_cycles": sum(1 for row in month_cycles if row.get("direction") == "DOWN"),
                "cycle_profit_usdt": round(
                    sum(_finite(row.get("profit_usdt")) for row in month_cycles), 8
                ),
                "cycle_profit_coin": round(
                    sum(_finite(row.get("profit_coin")) for row in month_cycles), 12
                ),
                "commission_usdt": round(
                    sum(_finite(row.get("fee")) for row in month_fills), 8
                ),
            }
        )
        previous = end
        if end_coin_price > 0:
            previous_coin_price = end_coin_price
    return out


def _csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    keys: List[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def build_export(
    job_id: str,
    request: Dict[str, Any],
    summary: Dict[str, Any],
    monthly: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    diagnostics: List[Dict[str, Any]],
    cycles: Optional[List[Dict[str, Any]]] = None,
    source_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Path:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / f"{job_id}.zip"
    fills = [x for x in events if x.get("event") == "fill"]
    equity = [x for x in events if x.get("event") == "equity"]
    dynamic = [x for x in events if x.get("event") == "dynamic_decision"]
    params_rows = [{"key": k, "value": _json(v) if isinstance(v, (dict, list)) else v} for k, v in request.items()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, rows in {
            "summary.csv": [summary],
            "monthly.csv": monthly,
            "cycles.csv": cycles or [],
            "fills.csv": fills,
            "equity_5m.csv": equity,
            "dynamic_decisions.csv": dynamic,
            "diagnostics.csv": diagnostics,
            "parameters.csv": params_rows,
            "all_events.csv": events,
            "source_coin_5m_execution.csv": (source_data or {}).get("execution") or [],
            "source_coin_5m.csv": (source_data or {}).get("coin5") or [],
            "source_btc_5m.csv": (source_data or {}).get("btc5") or [],
            "source_btc_1h_derived_from_5m.csv": (source_data or {}).get("btc1") or [],
            "source_btc_4h_derived_from_5m.csv": (source_data or {}).get("btc4") or [],
        }.items():
            zf.writestr(name, _csv_bytes(rows))
    return path


async def prepare_data(
    symbol: str,
    fee_rate: float,
    progress: Callable[[str], None],
    *,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> Dict[str, Any]:
    store = CandleStore()
    end5 = int(end_ms or _closed_end("5m"))
    start5 = int(start_ms or (end5 - YEAR_DAYS * DAY_MS))
    if start5 >= end5:
        raise ValueError("Bitiş tarihi başlangıç tarihinden sonra olmalı.")
    warmup_start5 = start5 - WARMUP_DAYS * DAY_MS
    async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=30.0) as client:
        coin5 = await ensure_series(client, store, symbol, "5m", warmup_start5, end5, progress)
        execution = [row for row in coin5 if int(row["t"]) >= start5]
        btc_symbol = "BTCUSDT"
        btc5 = await ensure_series(client, store, btc_symbol, "5m", warmup_start5, end5, progress)
        # Dinamik motorun çoklu zaman dilimi bağlamı ayrı ve daha kaba bir
        # kaynaktan indirilmez; aynı 5 dakikalık fiyat yolundan deterministik
        # biçimde türetilir.
        btc1 = resample(btc5, INTERVAL_MS["1h"])
        btc4 = resample(btc1, INTERVAL_MS["4h"])
        constraints = await fetch_constraints(client, symbol, fee_rate)
    gaps = []
    # ``execution`` coin5'in bir yıllık alt kümesidir; ayrıca taramak aynı
    # boşluğu iki kez raporlardı.
    for rows, interval in ((coin5, "5m"), (btc5, "5m")):
        step = INTERVAL_MS[interval]
        for a, b in zip(rows, rows[1:]):
            if int(b["t"]) - int(a["t"]) > step:
                gaps.append({"interval": interval, "after": a["t"], "before": b["t"]})
    return {
        "execution": execution,
        "coin5": coin5,
        "btc5": btc5,
        "btc1": btc1,
        "btc4": btc4,
        "constraints": constraints,
        "gaps": gaps,
        "start": start5,
        "end": end5,
    }


def _set_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(updates)


def run_job(job_id: str, request: Dict[str, Any]) -> None:
    try:
        symbol = normalize_symbol(request["coin"])
        balance = float(request["balance"])
        params = validate_params(request["params"], balance, symbol)
        params["fee_rate"] = float(request["fee_rate"])
        _set_job(job_id, status="running", stage="Veriler hazırlanıyor", progress=5)

        def progress(message: str) -> None:
            _set_job(job_id, message=message)

        start_ms = _date_ms(request.get("start_date"))
        end_ms = _date_ms(request.get("end_date"), end_of_day=True)
        prepared = asyncio.run(
            prepare_data(
                symbol,
                float(request["fee_rate"]),
                progress,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
        _set_job(job_id, stage="Gerçek strateji motoru çalışıyor", progress=72)
        events: List[Dict[str, Any]] = []
        diagnostics: List[Dict[str, Any]] = [
            {
                "severity": "INFO",
                "code": "INTRABAR_PATH_ASSUMPTION",
                "ts": prepared["start"],
                "detail": "5m mumlarda yön bazlı sıklaştırılmış O-L-H-C / O-H-L-C yolu kullanıldı.",
            },
            {
                "severity": "INFO",
                "code": "HISTORICAL_ORDERBOOK_UNAVAILABLE",
                "ts": prepared["start"],
                "detail": "Geçmiş order book bulunmadığı için V6 spread alanında güvenli varsayım kullanıldı.",
            },
        ]
        for gap in prepared["gaps"]:
            diagnostics.append(
                {"severity": "WARN", "code": "CANDLE_GAP", "ts": gap["after"], "detail": _json(gap)}
            )

        dynamic_adapter = None
        if request.get("dynamic_mode"):
            dynamic_adapter = HistoricalDynamicAdapter(
                symbol,
                balance,
                params,
                prepared["coin5"],
                prepared["btc1"],
                prepared["btc4"],
                prepared["constraints"],
                events,
                diagnostics,
                progress_cb=lambda decision_count, bar_index: _set_job(
                    job_id,
                    message=f"Dinamik V6: {decision_count} karar işlendi",
                    progress=min(96, 72 + int(bar_index / max(1, len(prepared["execution"])) * 23)),
                ),
                total_bars=len(prepared["execution"]),
            )

        def audit(event: Dict[str, Any]) -> None:
            events.append(event)
            _audit_diagnostics(event, diagnostics)

        with RUN_LOCK:
            result = run_backtest(
                prepared["execution"],
                params,
                balance,
                symbol,
                fee_rate=float(request["fee_rate"]),
                slippage_bps=float(request["slippage_bps"]),
                intrabar=True,
                adaptive_intrabar=True,
                record_equity=True,
                before_tick=dynamic_adapter.before_tick if dynamic_adapter else None,
                audit_hook=audit,
            )

        equity_events = [x for x in events if x.get("event") == "equity"]
        cycles = cycle_rows(events, symbol)
        initial_coin_price = _finite(
            (prepared["execution"][0] if prepared["execution"] else {}).get("o")
        )
        months = monthly_rows(
            equity_events,
            balance,
            cycles,
            events,
            initial_coin_price=initial_coin_price,
        )
        dynamic_events = [x for x in events if x.get("event") == "dynamic_decision"]
        if request.get("dynamic_mode") and result.cycles_closed > 0 and not dynamic_events:
            diagnostics.append(
                {
                    "severity": "ERROR",
                    "code": "DYNAMIC_DECISION_MISSING",
                    "ts": prepared["end"],
                    "detail": "Tur kapanmasına rağmen dinamik karar üretilmedi.",
                }
            )
        error_count = sum(1 for d in diagnostics if d.get("severity") == "ERROR")
        warning_count = sum(1 for d in diagnostics if d.get("severity") == "WARN")
        summary = result.to_dict()
        summary.update(
            {
                "symbol": symbol,
                "dynamic_mode": bool(request.get("dynamic_mode")),
                "period_start": datetime.fromtimestamp(prepared["start"] / 1000, timezone.utc).isoformat(),
                "period_end": datetime.fromtimestamp(prepared["end"] / 1000, timezone.utc).isoformat(),
                "execution_interval": "5m",
                "strategy_engine": "app.botengine.strategies.dca_grid_trailing",
                "dynamic_engine": "Parametre Asistanı · doğrudan profil uygulaması",
                "dynamic_decisions": len(dynamic_events),
                "diagnostic_errors": error_count,
                "diagnostic_warnings": warning_count,
                "cache_db": str(DB_PATH),
                "base_asset": symbol[:-4],
                "bot_return_pct": round(float(result.return_pct), 6),
                "coin_return_pct": round(float(result.buy_hold_return_pct), 6),
                "alpha_pct": round(
                    float(result.return_pct) - float(result.buy_hold_return_pct), 6
                ),
                "alpha_formula": "bot_return_pct - coin_return_pct",
                "cycles_up": sum(1 for row in cycles if row["direction"] == "UP"),
                "cycles_down": sum(1 for row in cycles if row["direction"] == "DOWN"),
                "cycle_profit_usdt_total": round(
                    sum(_finite(row["profit_usdt"]) for row in cycles), 8
                ),
                "cycle_profit_coin_total": round(
                    sum(_finite(row["profit_coin"]) for row in cycles), 12
                ),
                "commission_rate_pct": round(float(request["fee_rate"]) * 100, 6),
                "commission_applied_to": "Her alış ve her satış işlemi",
                "net_pnl_includes_commission": True,
                "monthly_pnl_includes_commission": True,
                "cycle_pnl_includes_commission": True,
            }
        )
        export_path = build_export(
            job_id,
            request,
            summary,
            months,
            events,
            diagnostics,
            cycles=cycles,
            source_data={
                "execution": prepared["execution"],
                "coin5": prepared["coin5"],
                "btc5": prepared["btc5"],
                "btc1": prepared["btc1"],
                "btc4": prepared["btc4"],
            },
        )
        _set_job(
            job_id,
            status="completed",
            stage="Tamamlandı",
            message="Backtest tamamlandı.",
            progress=100,
            result={
                "summary": summary,
                "monthly": months,
                "cycles": cycles,
                "diagnostics": diagnostics[:200],
            },
            export_path=str(export_path),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="failed",
            stage="Hata",
            message=str(exc),
            progress=100,
            error=traceback.format_exc(),
        )


app = FastAPI(title="Ayserose Local Backtest", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    if not UI_PATH.exists():
        return HTMLResponse("<h1>backtest/ui.html bulunamadı.</h1>", status_code=500)
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    import os

    return {
        "ok": True,
        "service": "ayserose-local-backtest",
        "pid": os.getpid(),
        "port": int(os.environ.get("BACKTEST_PORT") or 0),
        "execution_interval": "5m",
    }


@app.post("/api/parameter-assistant")
async def historical_parameter_assistant(
    body: ParameterAssistantRequest,
) -> Dict[str, Any]:
    symbol = normalize_symbol(body.coin)
    start_ms = _date_ms(body.start_date)
    if start_ms is None or start_ms >= _closed_end("5m"):
        raise HTTPException(400, "Başlangıç tarihi geçmişte olmalı.")

    try:
        prepared = await prepare_data(
            symbol,
            float(body.fee_rate),
            lambda _message: None,
            start_ms=start_ms,
            end_ms=start_ms + INTERVAL_MS["5m"],
        )
        adapter = HistoricalDynamicAdapter(
            symbol,
            float(body.balance),
            {},
            prepared["coin5"],
            prepared["btc1"],
            prepared["btc4"],
            prepared["constraints"],
            [],
            [],
        )
        visible = adapter._slice(adapter.c5, start_ms, 2016)
        if not visible:
            raise ValueError("Başlangıç tarihinden önce analiz verisi bulunamadı.")
        price = float(visible[-1]["c"])
        market = adapter.market(start_ms, price)
        portfolio = PortfolioState(
            base_balance=0.0,
            quote_balance=float(body.balance),
            base_value_usdt=0.0,
            quote_value_usdt=float(body.balance),
            total_equity_usdt=float(body.balance),
            current_base_exposure_frac=0.0,
        )
        context = build_param_assistant_context(
            budget_usdt=float(body.balance),
            portfolio=portfolio,
            first_start_buy_only=False,
            allow_live=False,
            allow_no_trade=True,
        )
        decision = get_engine().calculate_decision(
            symbol=symbol,
            market_data=market,
            portfolio_state=portfolio,
            exchange_constraints=prepared["constraints"],
            bot_context=context,
            persist=False,
        )
        result = decision_to_param_assistant_result(
            decision, float(body.balance), symbol
        )
        result["backtest_config"] = (
            params_to_grid_config(
                decision.params,
                pool_version=decision.params.pool_version,
                ui_display=True,
            )
            if decision.params
            else None
        )
        result.update(
            {
                "ok": True,
                "analysis_as_of_ms": start_ms,
                "historical_replay": True,
                "future_candles_visible": False,
                "message": "Öneri yalnız başlangıç anından önce kapanmış mumlarla üretildi.",
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/backtests")
def start_backtest(body: BacktestRequest) -> Dict[str, Any]:
    symbol = normalize_symbol(body.coin)
    job_id = uuid.uuid4().hex[:12]
    request = body.model_dump()
    request["coin"] = symbol
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "Sırada",
            "message": "Backtest hazırlanıyor.",
            "progress": 0,
            "created_at": _now_ms(),
        }
    threading.Thread(target=run_job, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id, "symbol": symbol}


@app.get("/api/backtests/{job_id}")
def get_backtest(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    if not job:
        raise HTTPException(404, "Backtest bulunamadı.")
    job.pop("export_path", None)
    job.pop("error", None)
    return job


@app.get("/api/backtests/{job_id}/export")
def export_backtest(job_id: str) -> FileResponse:
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    path = Path(str(job.get("export_path") or ""))
    if job.get("status") != "completed" or not path.is_file():
        raise HTTPException(404, "Dışa aktarım henüz hazır değil.")
    symbol = job.get("result", {}).get("summary", {}).get("symbol", "BACKTEST")
    return FileResponse(path, media_type="application/zip", filename=f"{symbol}_{job_id}_backtest_csv.zip")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ayserose yerel backtest ekranı")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    requested_port = args.port
    selected_port = requested_port
    while selected_port <= requested_port + 30:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", selected_port))
                break
            except OSError:
                selected_port += 1
    if selected_port > requested_port + 30:
        raise RuntimeError("8765-8795 aralığında kullanılabilir port bulunamadı.")
    if selected_port != requested_port:
        print(f"{requested_port} portu kullanımda; {selected_port} seçildi.")
    import os

    os.environ["BACKTEST_PORT"] = str(selected_port)
    url = f"http://127.0.0.1:{selected_port}"
    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Ayserose backtest: {url}")
    print("Kapatmak için Ctrl+C")
    uvicorn.run(app, host="127.0.0.1", port=selected_port, log_level="warning")


if __name__ == "__main__":
    main()
