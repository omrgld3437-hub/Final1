"""
FILE: data_hub.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: YENİ - Global Data Hub - Tüm coin fiyatları ve market verilerini merkezi olarak yönetir
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

_DATAHUB_REST_LOCK_TIMEOUT = 55.0


def try_acquire_datahub_rest_leader() -> bool:
    """Çoklu uvicorn worker: REST döngüsünü tek proses çalıştırır (rest.log çift yük önleme)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lock_path = os.path.join(root, ".run", "datahub_rest.lock")
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    except Exception:
        pass
    now = time.time()
    if os.path.isfile(lock_path):
        try:
            if now - os.path.getmtime(lock_path) < _DATAHUB_REST_LOCK_TIMEOUT:
                return False
            os.unlink(lock_path)
        except Exception:
            return False
    try:
        with open(lock_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return False


# ============================================================
# GLOBAL DATA HUB - Merkezi Veri Yönetimi
# ============================================================
class DataHub:
    """Global data hub - tüm coin fiyatları, coin listesi, market verileri"""

    def __init__(self):
        # Coin prices: symbol -> {price, change24h, volume24h, ts}
        self.prices: Dict[str, Dict] = {}

        # Coin list: Top 100 coins with market data
        self.coin_list: List[Dict] = []
        self.coin_list_ts: float = 0

        # Account balances: account_id -> {balances, total_usd, ts}
        self.account_balances: Dict[int, Dict] = {}

        # Update intervals - REST loop: price 1-2s, 24h 5s, exchangeInfo/symbols 10 min
        self.PRICE_UPDATE_INTERVAL = 1.5
        self.TICKER_24H_UPDATE_INTERVAL = 60.0
        self.COIN_LIST_UPDATE_INTERVAL = 600.0
        self.BALANCE_UPDATE_INTERVAL = 10.0

        self.HUB_CACHE_TTL = 1.0
        self.PRICE_TTL = 120.0
        self.COIN_LIST_TTL = 600.0
        self.BALANCE_TTL = 5.0

        self.top_100_symbols: List[str] = []
        self._pinned_symbols: set = (
            set()
        )  # worker: çalışan bot sembolleri asla trim'den düşmez
        self._symbol_24h_fetch_ts: Dict[str, float] = {}
        self._price_ensure_task: Optional[asyncio.Task] = None  # tek sembol REST throttle
        self._symbol_price_fetch_ts: Dict[str, float] = {}
        self.all_symbols: List[str] = []
        self.all_symbols_ts: float = 0
        self.ALL_SYMBOLS_TTL = 600.0

        # Rate limit tracking
        self.last_rate_limit_check = 0.0
        self.rate_limit_backoff_until = 0.0
        self.rate_limit_backoff_level = 0  # 0=normal, 1=5s, 2=10s

        # In-flight dedupe for refresh
        self._refresh_inflight: Optional[asyncio.Task] = None
        self._refresh_lock = asyncio.Lock()

        # Hub data snapshot cache (for endpoint)
        self._hub_snapshot: Optional[Dict] = None
        self._hub_snapshot_ts: float = 0
        self._hub_snapshot_lock = asyncio.Lock()

        # Background task
        self._background_task: Optional[asyncio.Task] = None
        self._running = False
        self._warmup_done = False
        self._warmup_lock = asyncio.Lock()
        self._last_24h_ts: float = 0.0

        # WebSocket: live prices when connected
        self.ws_status: str = (
            "disabled"  # "connected" | "reconnecting" | "disabled" | "rest"
        )
        self.last_ws_update_ts: float = 0.0
        self._ws_client: Optional[Any] = None
        self._mini_ws: Dict[
            str, Dict
        ] = {}  # symbol -> {last, open, changePct, volume, quoteVolume}
        self._ws_started = False
        self.WS_STALE_SEC = (
            30.0  # 30s: WS mesaj gelmezse stale say, REST fallback devreye girer
        )
        self.REST_PRICE_INTERVAL_WHEN_WS = 30.0  # WS aktifken REST price seyrek
        self.BULK_REFRESH_MIN_INTERVAL = 10.0  # max 1 Binance ticker/price call per 10s
        self._last_bulk_refresh_ts: float = 0.0
        self._skip_rest_during_ban = True

        # RAM cap: Binance 2000+ sembol tutmak CPU/RAM tüketimine yol açar; sınırla
        self._MAX_PRICES = 600
        self._MAX_MINI_WS = 600
        self._MAX_ACCOUNT_BALANCES = 50

        # Serve-stale: UI gets last known price with is_stale flag; bots must not trade on stale
        self.DATAHUB_SERVE_STALE_FOR_UI = os.getenv(
            "DATAHUB_SERVE_STALE_FOR_UI", "1"
        ).strip().lower() in ("1", "true", "yes")

    def get_price_with_meta(self, symbol: str) -> Optional[Dict]:
        """
        Get price data with metadata. Returns None only if symbol never seen.
        When stale: returns last known price with is_stale=True (never None for stale).
        Structure: {price, change24h, volume24h, ts, is_stale}
        """
        symbol = symbol.upper()
        if symbol not in self.prices:
            return None
        data = self.prices[symbol]
        ts = data.get("ts", 0)
        now = time.time()
        age = now - ts
        is_stale = age > self.PRICE_TTL
        return {
            "price": data.get("price", 0.0),
            "change24h": data.get("change24h"),
            "volume24h": data.get("volume24h"),
            "low24h": data.get("low24h"),
            "high24h": data.get("high24h"),
            "ts": ts,
            "is_stale": is_stale,
        }

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get price for UI/display. When DATAHUB_SERVE_STALE_FOR_UI=True (default),
        returns price even when stale. Returns None only if symbol never seen or
        (when serve-stale disabled) when price is stale.
        """
        d = self.get_price_with_meta(symbol)
        if not d:
            return None
        if d.get("is_stale") and not self.DATAHUB_SERVE_STALE_FOR_UI:
            return None
        p = d.get("price")
        if p is None or (isinstance(p, (int, float)) and float(p) <= 0):
            return None
        return float(p)

    def get_change24h_pct(self, symbol: str) -> Optional[float]:
        """24s % — REST ticker merge veya WS miniTicker (open/close)."""
        sym = (symbol or "").upper().strip()
        if not sym:
            return None
        data = self.prices.get(sym) or {}
        if data.get("change24h_ts") is not None:
            val = data.get("change24h")
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        mini = self._mini_ws.get(sym)
        if mini and mini.get("changePct") is not None:
            try:
                return float(mini["changePct"])
            except (TypeError, ValueError):
                pass
        return None

    def _merge_ticker_24h_row(self, r: Dict, now: Optional[float] = None) -> None:
        """Tek /api/v3/ticker/24hr satırını prices cache'e işle."""
        sym = (r.get("symbol") or "").upper().strip()
        if not sym:
            return
        ts = now if now is not None else time.time()
        change24h = float(r.get("priceChangePercent", 0) or 0)
        volume24h = float(r.get("volume", 0) or 0)
        price = float(r.get("lastPrice", 0) or 0)
        prev = self.prices.get(sym) or {}
        entry = {
            **prev,
            "change24h": change24h,
            "volume24h": volume24h,
            "change24h_ts": ts,
            "low24h": float(r.get("lowPrice", 0) or 0),
            "high24h": float(r.get("highPrice", 0) or 0),
            "ts": ts,
        }
        if price > 0:
            entry["price"] = price
        elif prev.get("price"):
            entry["price"] = prev["price"]
        self.prices[sym] = entry

    def pin_symbols(self, symbols: List[str]) -> None:
        """Worker/bot: bu semboller RAM trim'de korunur."""
        for s in symbols or []:
            sym = (s or "").strip().upper()
            if sym:
                self._pinned_symbols.add(sym)

    def _preferred_price_symbols(self) -> set:
        pref = set(self.top_100_symbols or [])
        pref.update(
            c.get("symbol") for c in (self.coin_list or [])[:200] if c.get("symbol")
        )
        pref.update(self._pinned_symbols)
        return pref

    def _price_entry(self, symbol: str, data: Dict, now: float) -> Dict:
        ts = data.get("ts", 0)
        age = now - ts
        entry = {
            "price": data.get("price", 0.0),
            "change24h": data.get("change24h"),
            "volume24h": data.get("volume24h"),
            "low24h": data.get("low24h"),
            "high24h": data.get("high24h"),
            "ts": ts,
            "is_stale": age > self.PRICE_TTL,
        }
        if data.get("change24h_ts"):
            entry["change24h_ts"] = data.get("change24h_ts")
        return entry

    def get_prices_for_ui(
        self,
        max_extra: int = 200,
        ensure_symbols: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        """Dashboard/snapshot: öncelikli semboller + sınırlı ek — tam 600 kopyası yok."""
        if ensure_symbols:
            self.pin_symbols(ensure_symbols)
        if not self.prices:
            logger.info("datahub_cache_miss prices_empty=1")
        now = time.time()
        result: Dict[str, Dict] = {}
        preferred = self._preferred_price_symbols()
        for sym in preferred:
            data = self.prices.get(sym)
            if data:
                result[sym] = self._price_entry(sym, data, now)
        for sym in ensure_symbols or []:
            s = (sym or "").strip().upper()
            if s and s not in result and s in self.prices:
                result[s] = self._price_entry(s, self.prices[s], now)
        if len(result) < max(50, len(preferred) // 2):
            for symbol, data in list(self.prices.items()):
                if symbol in result:
                    continue
                result[symbol] = self._price_entry(symbol, data, now)
                if len(result) >= len(preferred) + max_extra:
                    break
        return result

    def get_all_prices(self) -> Dict[str, Dict]:
        """Tüm cache (max ~600). Ağır endpoint'ler için; UI tercihen get_prices_for_ui."""
        if not self.prices:
            logger.info("datahub_cache_miss prices_empty=1")
        now = time.time()
        result = {}
        for symbol, data in list(self.prices.items()):
            result[symbol] = self._price_entry(symbol, data, now)
        return result

    def get_coin_list(self) -> List[Dict]:
        """Get cached coin list"""
        age = time.time() - self.coin_list_ts
        if age > self.COIN_LIST_TTL:
            return []
        return self.coin_list.copy()

    def get_all_symbols(self) -> List[str]:
        """All symbols from Binance exchangeInfo (cache 600s)"""
        age = time.time() - self.all_symbols_ts
        if age > self.ALL_SYMBOLS_TTL or not self.all_symbols:
            return []
        return self.all_symbols.copy()

    def get_account_balance(self, account_id: int) -> Optional[Dict]:
        """Get cached account balance"""
        if account_id not in self.account_balances:
            return None

        data = self.account_balances[account_id]
        age = time.time() - data.get("ts", 0)
        if age > self.BALANCE_TTL:
            return None

        return data.get("data")

    def _ws_fresh(self) -> bool:
        return (
            self._ws_started
            and (time.time() - self.last_ws_update_ts) < self.WS_STALE_SEC
        )

    async def refresh_all_prices_bulk(self) -> None:
        """
        Single bulk call: GET /api/v3/ticker/price (no symbol = all). Updates DataHub cache.
        Rate limited: max once every BULK_REFRESH_MIN_INTERVAL (10s). WS fresh ise atlanır.
        """
        if self._ws_fresh():
            return
        now = time.time()
        if now - self._last_bulk_refresh_ts < self.BULK_REFRESH_MIN_INTERVAL:
            return
        if self._skip_rest_during_ban:
            try:
                from app.services.binance_spot import is_ip_banned

                if is_ip_banned():
                    return
            except Exception:
                pass
        try:
            from app.services.binance_rest_log import rest_source
            from app.services.binance_spot import ticker_price_all

            with rest_source("data_hub.bulk_price"):
                rows = await ticker_price_all(testnet=False)
            self._last_bulk_refresh_ts = time.time()
            for r in rows or []:
                sym = r.get("symbol")
                if not sym:
                    continue
                price = float(r.get("price", 0) or 0)
                prev = self.prices.get(sym) or {}
                entry = {
                    "price": price,
                    "volume24h": prev.get("volume24h"),
                    "ts": self._last_bulk_refresh_ts,
                }
                if prev.get("change24h_ts"):
                    entry["change24h"] = prev.get("change24h")
                    entry["change24h_ts"] = prev.get("change24h_ts")
                if prev.get("low24h") is not None:
                    entry["low24h"] = prev.get("low24h")
                if prev.get("high24h") is not None:
                    entry["high24h"] = prev.get("high24h")
                self.prices[sym] = {**prev, **entry}
            self._trim_prices()
            try:
                from app.observability.ram_capture import log_ram_event

                log_ram_event(
                    "datahub_bulk_price",
                    {"rows": len(rows or []), "prices_len": len(self.prices)},
                    component="web",
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug("[DataHub] refresh_all_prices_bulk error: %s", e)

    async def update_prices(self, symbols: Optional[List[str]] = None):
        """Delegates to refresh_all_prices_bulk (single bulk call, rate limited)."""
        await self.refresh_all_prices_bulk()

    async def update_ticker_24h(self):
        """Fetch /api/v3/ticker/24hr (all) and merge change24h/volume into self.prices."""
        if self._skip_rest_during_ban:
            try:
                from app.services.binance_spot import is_ip_banned

                if is_ip_banned():
                    return
            except Exception:
                pass
        try:
            from app.services.binance_rest_log import rest_source
            from app.services.binance_spot import ticker_24h_all

            with rest_source("data_hub.ticker_24h"):
                data = await ticker_24h_all(testnet=False)
            rows = data if isinstance(data, list) else [data] if data else []
            self._last_24h_ts = time.time()
            now = time.time()
            usdt_rows: List[Dict] = []
            for r in rows:
                sym = r.get("symbol")
                if not sym:
                    continue
                self._merge_ticker_24h_row(r, now)
                if str(sym).endswith("USDT"):
                    usdt_rows.append(r)
            self._trim_prices()
            self._rebuild_coin_list_from_usdt_rows(usdt_rows)
            try:
                from app.observability.ram_capture import log_ram_event

                log_ram_event(
                    "datahub_ticker_24h",
                    {
                        "rows_in": len(rows),
                        "usdt_rows": len(usdt_rows),
                        "prices_len": len(self.prices),
                        "coin_list_len": len(self.coin_list or []),
                    },
                    component="web",
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug("[DataHub] update_ticker_24h error: %s", e)

    def schedule_price_ensure(self, symbols: List[str]) -> None:
        """Cache miss için arka plan doldurma — GET /data/prices asla bekletmez."""
        syms = []
        seen: set = set()
        for raw in symbols or []:
            s = (raw or "").strip().upper()
            if not s or s in seen:
                continue
            seen.add(s)
            syms.append(s)
        if not syms:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._price_ensure_task and not self._price_ensure_task.done():
            return
        self._price_ensure_task = loop.create_task(self._ensure_symbols_background(syms))

    async def _ensure_symbols_background(self, symbols: List[str]) -> None:
        unique = list(dict.fromkeys(symbols))[:32]
        missing = [
            s
            for s in unique
            if float((self.prices.get(s) or {}).get("price") or 0) <= 0
        ]
        if not missing:
            return
        try:
            if not self.prices or len(missing) > 2:
                await self.refresh_all_prices_bulk()
                missing = [
                    s
                    for s in unique
                    if float((self.prices.get(s) or {}).get("price") or 0) <= 0
                ]
            if not missing:
                return
            sem = asyncio.Semaphore(5)

            async def _one(sym: str) -> None:
                async with sem:
                    await self.ensure_symbol_price(sym)

            await asyncio.gather(*(_one(s) for s in missing[:15]))
        except Exception as e:
            logger.debug("[DataHub] background price ensure failed: %s", e)

    async def ensure_symbol_price(self, symbol: str) -> bool:
        """Bot tick: pinned sembol cache'te yoksa tek sembol REST ile fiyat çek."""
        sym = (symbol or "").upper().strip()
        if not sym:
            return False
        meta = self.get_price_with_meta(sym)
        if meta and float(meta.get("price") or 0) > 0 and not meta.get("is_stale"):
            return True
        last = self._symbol_price_fetch_ts.get(sym, 0.0)
        if time.time() - last < 5.0:
            cached = self.prices.get(sym) or {}
            return float(cached.get("price") or 0) > 0
        self._symbol_price_fetch_ts[sym] = time.time()
        if len(self._symbol_price_fetch_ts) > 200:
            oldest = min(
                self._symbol_price_fetch_ts, key=self._symbol_price_fetch_ts.get
            )
            self._symbol_price_fetch_ts.pop(oldest, None)
        if self._skip_rest_during_ban:
            try:
                from app.services.binance_spot import is_ip_banned

                if is_ip_banned():
                    return False
            except Exception:
                pass
        try:
            from app.services.binance_rest_log import rest_source
            from app.services.binance_spot import ticker_24h_all

            with rest_source("data_hub.ticker_24h_single"):
                data = await ticker_24h_all(testnet=False, symbol=sym)
            row = (
                data
                if isinstance(data, dict)
                else (data[0] if isinstance(data, list) and data else None)
            )
            if row:
                self._merge_ticker_24h_row(row, time.time())
                self.pin_symbols([sym])
                return float((self.prices.get(sym) or {}).get("price") or 0) > 0
        except Exception as e:
            logger.debug("[DataHub] ensure_symbol_price %s: %s", sym, e)
        return False

    async def ensure_symbol_ticker_24h(self, symbol: str) -> bool:
        """Bot/UI: sembol için 24s % yoksa tek sembol REST (throttle)."""
        sym = (symbol or "").upper().strip()
        if not sym or self.get_change24h_pct(sym) is not None:
            return self.get_change24h_pct(sym) is not None
        last = self._symbol_24h_fetch_ts.get(sym, 0.0)
        if time.time() - last < 15.0:
            return False
        self._symbol_24h_fetch_ts[sym] = time.time()
        if len(self._symbol_24h_fetch_ts) > 200:
            oldest = min(self._symbol_24h_fetch_ts, key=self._symbol_24h_fetch_ts.get)
            self._symbol_24h_fetch_ts.pop(oldest, None)
        try:
            from app.services.binance_rest_log import rest_source
            from app.services.binance_spot import ticker_24h_all

            with rest_source("data_hub.ticker_24h_single"):
                data = await ticker_24h_all(testnet=False, symbol=sym)
            row = (
                data
                if isinstance(data, dict)
                else (data[0] if isinstance(data, list) and data else None)
            )
            if row:
                self._merge_ticker_24h_row(row)
                self.pin_symbols([sym])
                return True
        except Exception as e:
            logger.debug("[DataHub] ensure_symbol_ticker_24h %s: %s", sym, e)
        return False

    def _rebuild_coin_list_from_usdt_rows(self, rows: List[Dict]) -> None:
        coins = []
        for r in rows or []:
            sym = r.get("symbol", "")
            if not sym or not str(sym).endswith("USDT"):
                continue
            coins.append(
                {
                    "symbol": sym,
                    "price": float(r.get("lastPrice", 0) or 0),
                    "change24h": float(r.get("priceChangePercent", 0) or 0),
                    "volume24h": float(r.get("volume", 0) or 0),
                    "quoteVolume24h": float(r.get("quoteVolume", 0) or 0),
                    "marketCap": 0.0,
                }
            )
        coins.sort(key=lambda x: x.get("quoteVolume24h", 0), reverse=True)
        self.coin_list = coins[:200]
        self.top_100_symbols = [c["symbol"] for c in self.coin_list[:100]]
        self.coin_list_ts = time.time()

    async def update_coin_list(self):
        """Build coin_list from 24h ticker (USDT, top quote volume)."""
        try:
            if (
                self.coin_list
                and (time.time() - self.coin_list_ts) < self.COIN_LIST_UPDATE_INTERVAL
            ):
                return
            await self.update_ticker_24h()
        except Exception as e:
            logger.debug("[DataHub] update_coin_list error: %s", e)
            self.coin_list = []
            self.top_100_symbols = []
            self.coin_list_ts = time.time()

    async def update_all_symbols(self):
        """TRADING sembol listesi — kompakt exchangeInfo cache (binance_spot)."""
        try:
            from app.services.binance_spot import get_cached_trading_symbols

            symbols = await get_cached_trading_symbols(
                testnet=False, force_refresh=False
            )
            self.all_symbols = sorted(symbols)
            self.all_symbols_ts = time.time()
        except Exception as e:
            logger.debug("[DataHub] update_all_symbols error: %s", e)
            self.all_symbols = []
            self.all_symbols_ts = time.time()

    def get_symbols_for_scope(self, scope: str = "usdt") -> List[str]:
        """Symbol list by scope: usdt = *USDT only, all = all TRADING symbols. Uses cached all_symbols."""
        age = time.time() - self.all_symbols_ts
        if age > self.ALL_SYMBOLS_TTL or not self.all_symbols:
            return []
        if (scope or "").lower() == "all":
            return self.all_symbols.copy()
        return [s for s in self.all_symbols if s.endswith("USDT")]

    def get_symbol_filters_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Sembol filtreleri — binance_spot kompakt cache (senkron okuma)."""
        sym = (symbol or "").upper().strip()
        if not sym:
            return None
        try:
            from app.services.binance_spot import get_symbol_filters_sync

            return get_symbol_filters_sync(sym, testnet=False)
        except Exception:
            return None

    def import_prices_snapshot(self, prices: Dict[str, Any]) -> int:
        """Başka süreçten (web API) fiyat snapshot'ı — worker SSOT senkronu."""
        if not prices or not isinstance(prices, dict):
            return 0
        now = time.time()
        n = 0
        for sym, d in prices.items():
            if not sym or not isinstance(d, dict):
                continue
            s = sym.upper()
            p = d.get("price")
            if p is None or float(p) <= 0:
                continue
            prev = self.prices.get(s) or {}
            entry: Dict[str, Any] = {
                "price": float(p),
                "volume24h": d.get("volume24h", prev.get("volume24h")),
                "low24h": d.get("low24h", prev.get("low24h")),
                "high24h": d.get("high24h", prev.get("high24h")),
                "ts": now,
            }
            ch = d.get("change24h")
            if ch is not None:
                entry["change24h"] = float(ch)
                entry["change24h_ts"] = float(
                    d.get("change24h_ts") or prev.get("change24h_ts") or now
                )
            elif prev.get("change24h_ts"):
                entry["change24h"] = prev.get("change24h")
                entry["change24h_ts"] = prev.get("change24h_ts")
            self.prices[s] = {**prev, **entry}
            n += 1
        if n:
            self._trim_prices()
            if os.getenv("MARKET_SYNC_FROM_WEB", "").strip() == "1":
                cap = int(os.getenv("WORKER_MAX_PRICES", "200"))
                if len(self.prices) > cap:
                    preferred = self._preferred_price_symbols()
                    keep = set(self._pinned_symbols)
                    for sym in preferred:
                        if len(keep) >= cap:
                            break
                        keep.add(sym)
                    for sym in list(self.prices.keys()):
                        if sym not in keep and len(self.prices) > cap:
                            self.prices.pop(sym, None)
        return n

    def _trim_prices(self) -> None:
        """RAM: Binance 2000+ sembol tutmayı önle; öncelik: top_100 + coin_list, sonra en güncel."""
        if len(self.prices) <= self._MAX_PRICES:
            return
        preferred = set(self.top_100_symbols) | {
            c["symbol"] for c in self.coin_list[:200]
        }
        preferred.update(self._pinned_symbols)
        keep_keys = {k for k in self.prices if k in preferred}
        rest = [(k, self.prices[k]) for k in self.prices if k not in keep_keys]
        rest.sort(key=lambda x: x[1].get("ts", 0), reverse=True)
        for k, _ in rest[: self._MAX_PRICES - len(keep_keys)]:
            keep_keys.add(k)
        self.prices = {k: self.prices[k] for k in keep_keys}

    def _trim_mini_ws(self) -> None:
        """RAM: WebSocket mini ticker cache sınırı."""
        if len(self._mini_ws) <= self._MAX_MINI_WS:
            return
        keys = list(self._mini_ws.keys())[: self._MAX_MINI_WS]
        self._mini_ws = {k: self._mini_ws[k] for k in keys}

    def _trim_account_balances(self) -> None:
        """RAM: Cüzdan cache sınırı."""
        if len(self.account_balances) <= self._MAX_ACCOUNT_BALANCES:
            return
        by_ts = sorted(self.account_balances.items(), key=lambda x: x[1].get("ts", 0))
        for k, _ in by_ts[: len(by_ts) - self._MAX_ACCOUNT_BALANCES]:
            self.account_balances.pop(k, None)

    async def update_account_balance(self, account_id: int, balance_data: Dict):
        """Update account balance cache"""
        self.account_balances[account_id] = {"data": balance_data, "ts": time.time()}
        self._trim_account_balances()

    async def warmup(self, timeout_sec: float = 5.0) -> bool:
        """Blocking warmup: one price refresh so first request gets data. Returns True if prices non-empty."""
        async with self._warmup_lock:
            if self._warmup_done:
                return bool(self.prices)
            logger.info("datahub_warmup_start timeout_sec=%s", timeout_sec)
            try:
                await asyncio.wait_for(
                    self.refresh_all_prices_bulk(), timeout=timeout_sec
                )
            except asyncio.TimeoutError:
                logger.warning("datahub_warmup_end timeout")
            except Exception as e:
                logger.warning("datahub_warmup_end error=%s", e)
            self._warmup_done = True
            ready = bool(self.prices)
            logger.info(
                "datahub_warmup_end prices_ready=%s count=%s", ready, len(self.prices)
            )
            return ready

    async def _background_update_loop(self):
        """
        REST background loop: price every 1-2s, 24h every 5s, coin_list/symbols at interval.
        """
        last_price_update = 0.0
        last_24h_update = 0.0
        last_coin_list_update = 0.0
        last_all_symbols_update = 0.0

        logger.info("[DataHub] REST background loop starting (price 1-2s, 24h 5s)...")
        try:
            await self.update_prices()
            await self.update_ticker_24h()
            await self.update_coin_list()
            await self.update_all_symbols()
            last_price_update = last_24h_update = last_coin_list_update = (
                last_all_symbols_update
            ) = time.time()
        except Exception as e:
            logger.warning(
                "[DataHub] Initial REST update failed (will retry in loop): %s", e
            )
            now = time.time()
            last_price_update = last_24h_update = last_coin_list_update = (
                last_all_symbols_update
            ) = now

        last_market_probe = 0.0
        while self._running:
            try:
                now = time.time()
                ws_stale = (
                    self._ws_started
                    and (now - self.last_ws_update_ts) >= self.WS_STALE_SEC
                )
                price_interval = (
                    self.REST_PRICE_INTERVAL_WHEN_WS
                    if not ws_stale
                    else self.PRICE_UPDATE_INTERVAL
                )
                if not self._ws_fresh() and now - last_price_update >= price_interval:
                    await self.refresh_all_prices_bulk()
                    last_price_update = now
                ticker_iv = (
                    self.TICKER_24H_UPDATE_INTERVAL
                    if not self._ws_fresh()
                    else max(120.0, self.TICKER_24H_UPDATE_INTERVAL)
                )
                if now - last_24h_update >= ticker_iv:
                    await self.update_ticker_24h()
                    last_24h_update = now
                if now - last_coin_list_update >= self.COIN_LIST_UPDATE_INTERVAL:
                    await self.update_coin_list()
                    last_coin_list_update = now
                if now - last_all_symbols_update >= self.ALL_SYMBOLS_TTL:
                    await self.update_all_symbols()
                    last_all_symbols_update = now
                _ram_diag = (
                    os.getenv("RAM_PROBE_ENABLED") == "1"
                    or os.getenv("RAM_CAPTURE", "").strip() == "1"
                )
                if _ram_diag and now - last_market_probe >= 60.0:
                    last_market_probe = now
                    try:
                        from app.observability.ram_probe import probe_market_data

                        probe_market_data(
                            open_ws_count=1
                            if (self._ws_started and self._ws_client)
                            else 0,
                            cache_symbol_count=len(self.prices),
                            write_to_log=True,
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("[DataHub] Background update error: %s", e)
                await asyncio.sleep(5)

    def start_background_updates(self, rest_leader: bool = True):
        """Start background update service. rest_leader=False: sadece WS (çoklu uvicorn worker)."""
        if self._running:
            return
        if not rest_leader:
            logger.info("[DataHub] REST background loop skipped (not REST leader)")
            return

        self._running = True

        # Start background task (will be called from FastAPI startup)
        try:
            loop = asyncio.get_running_loop()
            self._background_task = loop.create_task(self._background_update_loop())
            logger.info(
                "[DataHub] Background update service started (REST leader pid=%s)",
                os.getpid(),
            )
        except RuntimeError:
            logger.warning("[DataHub] No event loop found, will start on startup event")

    def stop_background_updates(self):
        """Stop background update service"""
        self._running = False
        if self._background_task:
            self._background_task.cancel()
        self.stop_ws()
        logger.info("[DataHub] Background update service stopped")

    def _on_ws_message(self, payload: Dict[str, Any]) -> None:
        """Callback from BinanceWSClient: update prices and mini from !miniTicker@arr."""
        try:
            arr = payload.get("miniTicker") if isinstance(payload, dict) else None
            if not isinstance(arr, list):
                return
            now = time.time()
            for item in arr:
                s = (item.get("s") or "").strip()
                if not s:
                    continue
                try:
                    close = float(item.get("c") or 0)
                    open_ = float(item.get("o") or close)
                    high = float(item.get("h") or close)
                    low = float(item.get("l") or close)
                    vol = float(item.get("v") or 0)
                    quote_vol = float(item.get("q") or 0)
                except (TypeError, ValueError):
                    continue
                prev = self.prices.get(s) or {}
                change_pct = (
                    float((close - open_) / open_ * 100)
                    if open_ and open_ > 0
                    else None
                )
                entry = {
                    **prev,
                    "price": close,
                    "volume24h": vol,
                    "low24h": low,
                    "high24h": high,
                    "ts": now,
                }
                if change_pct is not None:
                    entry["change24h"] = change_pct
                    entry["change24h_ts"] = now
                elif prev.get("change24h_ts"):
                    entry["change24h"] = prev.get("change24h")
                    entry["change24h_ts"] = prev.get("change24h_ts")
                self.prices[s] = entry
                self._mini_ws[s] = {
                    "last": close,
                    "open": open_,
                    "changePct": change_pct
                    if change_pct is not None
                    else prev.get("change24h"),
                    "volume": vol,
                    "quoteVolume": quote_vol,
                    "marketCap": 0.0,
                }
            self.last_ws_update_ts = now
            self._trim_prices()
            self._trim_mini_ws()
        except Exception as e:
            logger.debug("[DataHub] WS on_message error: %s", e)

    def start_ws(self, testnet: bool = False) -> None:
        """Start WebSocket client (combined stream !miniTicker@arr). REST remains as fallback."""
        if self._ws_started:
            return
        try:
            from app.services.binance_ws import BinanceWSClient

            self._ws_client = BinanceWSClient(
                on_message=self._on_ws_message, testnet=testnet
            )
            self._ws_client.start()
            self._ws_started = True
            self.ws_status = "reconnecting"
            logger.info("[DataHub] WebSocket client started (testnet=%s)", testnet)
        except Exception as e:
            logger.warning(
                "[DataHub] WebSocket start failed: %s; REST fallback only", e
            )

    def stop_ws(self) -> None:
        """Stop WebSocket client."""
        self._ws_started = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
            self._ws_client = None
        self.ws_status = "disabled"
        logger.info("[DataHub] WebSocket client stopped")

    def _get_effective_ws_status(self) -> str:
        if not self._ws_started or not self._ws_client:
            return "rest"
        if time.time() - self.last_ws_update_ts < self.WS_STALE_SEC:
            return "connected"
        return "reconnecting"

    def get_status(self) -> Dict[str, Any]:
        """WS state and stale counts for operators / metrics."""
        status = self._get_effective_ws_status()
        # Map reconnecting -> stale for UI (green/yellow/red)
        ws_status = "stale" if status == "reconnecting" else status
        now = time.time()
        total = len(self.prices)
        stale_count = sum(
            1 for d in self.prices.values() if (now - d.get("ts", 0)) > self.PRICE_TTL
        )
        return {
            "ws_status": ws_status,
            "last_ws_message_ts": self.last_ws_update_ts,
            "stale_symbols_count": stale_count,
            "total_symbols": total,
        }

    async def _refresh_hub_snapshot(self) -> Dict:
        """Refresh hub snapshot (with in-flight dedupe)"""
        async with self._hub_snapshot_lock:
            # Check if refresh already in flight
            if self._refresh_inflight and not self._refresh_inflight.done():
                # Wait for existing refresh
                try:
                    return await self._refresh_inflight
                except Exception:
                    pass

            # Start new refresh
            async def do_refresh():
                try:
                    snapshot = {
                        "prices": self.get_prices_for_ui(),
                        "mini": self._build_mini_map(),
                        "coin_list": self.get_coin_list(),
                        "symbols": self.get_all_symbols(),
                        "ts": time.time(),
                        "data_status": "fresh",
                        "source": "cache",
                    }
                    return snapshot
                except Exception as e:
                    logger.error(f"[DataHub] Error refreshing snapshot: {e}")
                    # Return stale snapshot if available
                    if self._hub_snapshot:
                        stale_snapshot = self._hub_snapshot.copy()
                        stale_snapshot["data_status"] = "stale"
                        stale_snapshot["stale_reason"] = "refresh_error"
                        return stale_snapshot
                    # Empty snapshot
                    return {
                        "prices": {},
                        "mini": {},
                        "coin_list": [],
                        "symbols": [],
                        "ts": time.time(),
                        "data_status": "empty",
                    }

            # Create refresh task
            self._refresh_inflight = asyncio.create_task(do_refresh())
            snapshot = await self._refresh_inflight
            self._refresh_inflight = None

            # Update cache
            self._hub_snapshot = snapshot
            self._hub_snapshot_ts = time.time()

            return snapshot

    def _build_mini_map(self) -> Dict:
        """Build mini ticker map from WS mini, prices, and coin_list. Includes stale (serve-stale)."""
        mini_map = {}
        time.time()
        # Prefer WebSocket mini when fresh
        for symbol, m in self._mini_ws.items():
            mini_map[symbol] = dict(m)
        # From prices (fill gaps; include stale for serve-stale)
        for symbol, price_data in self.prices.items():
            if symbol not in mini_map:
                mini_map[symbol] = {
                    "last": price_data.get("price", 0.0),
                    "open": price_data.get("price", 0.0),
                    "changePct": price_data.get("change24h")
                    if price_data.get("change24h") is not None
                    else 0.0,
                    "volume": price_data.get("volume24h")
                    if price_data.get("volume24h") is not None
                    else 0.0,
                    "quoteVolume": (price_data.get("volume24h") or 0.0)
                    * (price_data.get("price") or 0.0),
                    "marketCap": 0.0,
                }
        # From coin_list (more complete data)
        for coin in self.coin_list:
            symbol = coin.get("symbol", "")
            if symbol and symbol not in mini_map:
                mini_map[symbol] = {
                    "last": coin.get("price", 0.0),
                    "open": coin.get("price", 0.0),
                    "changePct": coin.get("change24h", 0.0),
                    "volume": coin.get("volume24h", 0.0),
                    "quoteVolume": coin.get("quoteVolume24h", 0.0),
                    "marketCap": coin.get("marketCap", 0.0),
                }
        return mini_map

    async def get_hub_data(self, account_id: Optional[int] = None) -> Dict:
        """
        Hub snapshot: 1s cache. data_status/ws_status from real WS or REST state.
        """
        now = time.time()
        cache_age = now - self._hub_snapshot_ts

        if self._hub_snapshot and cache_age < self.HUB_CACHE_TTL:
            result = self._hub_snapshot.copy()
        else:
            result = await self._refresh_hub_snapshot()

        ws_status = self._get_effective_ws_status()
        result["ws_status"] = ws_status
        result["data_status"] = (
            "live"
            if (ws_status == "connected" or result.get("prices") or result.get("mini"))
            else result.get("data_status", "live")
        )
        result["last_ws_update_ts"] = self.last_ws_update_ts
        result["stale_age_ms"] = int(cache_age * 1000)
        return result


# Global instance
data_hub = DataHub()
