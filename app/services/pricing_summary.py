"""
Üst ticker şeridi için canlı fiyat özeti: FX, metals, crypto.
Cache TTL ve in-flight dedupe ile tek endpoint.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# TTL saniye (exchangerate.host 120s – dakikada 1'den fazla upstream yok)
FX_TTL = 120.0
METALS_TTL = 120.0
CRYPTO_TTL = 2.0

# Cache
_fx_cache: Dict[str, Any] = {}
_fx_ts: float = 0
_fx_inflight: Optional[asyncio.Task] = None
_metals_cache: Dict[str, Any] = {}
_metals_ts: float = 0
_crypto_cache: Dict[str, float] = {}
_crypto_ts: float = 0
_last_result: Dict[str, Any] = {}
_inflight_lock = asyncio.Lock()
_http_client: Optional[httpx.AsyncClient] = None
_fx_day_open: Dict[str, float] = {}
_fx_day_open_date: str = ""


def _ticker_chg_from_hub(*symbols: str) -> Optional[float]:
    """Binance 24s % — DataHub ticker/24hr veya WS mini."""
    try:
        from app.services.data_hub import data_hub

        for sym in symbols:
            if not sym:
                continue
            pct = data_hub.get_change24h_pct(sym)
            if pct is not None and float(pct) == float(pct):
                return float(pct)
    except Exception as e:
        logger.debug("[pricing_summary] hub chg %s: %s", symbols, e)
    return None


def _fx_daily_chg_pct(field: str, current: Optional[float]) -> Optional[float]:
    """FX dış API: günün ilk kaydı (UTC) baz — hub yoksa."""
    global _fx_day_open, _fx_day_open_date
    if current is None or not (float(current) > 0):
        return None
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _fx_day_open_date != today:
        _fx_day_open = {}
        _fx_day_open_date = today
    cur = float(current)
    if field not in _fx_day_open:
        _fx_day_open[field] = cur
        return 0.0
    open_v = _fx_day_open[field]
    if open_v <= 0:
        return None
    return ((cur - open_v) / open_v) * 100.0


def _resolve_chg_pct(
    field: str, price: Optional[float], hub_symbols: tuple[str, ...]
) -> Optional[float]:
    pct = _ticker_chg_from_hub(*hub_symbols)
    if pct is not None:
        return pct
    return _fx_daily_chg_pct(field, price)


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0))
    return _http_client


async def _fetch_crypto() -> tuple[Optional[float], Optional[float], str]:
    """BTC/USD, ETH/USD. DataHub only (serve-stale). No direct Binance REST fallback."""
    from app.services.data_hub import data_hub

    btc, eth = None, None
    status = "error"
    try:
        p_btc = data_hub.get_price("BTCUSDT")  # float | None
        p_eth = data_hub.get_price("ETHUSDT")
        if p_btc and float(p_btc) > 0:
            btc = float(p_btc)
        if p_eth and float(p_eth) > 0:
            eth = float(p_eth)
        if btc is not None or eth is not None:
            status = "live"
    except Exception as e:
        logger.debug("[pricing_summary] DataHub crypto: %s", e)

    return btc, eth, status


async def _fetch_fx_upstream() -> tuple[
    Optional[float], Optional[float], Optional[float], str
]:
    """Tek upstream: ExchangeRate-API open access (ücretsiz, anahtar yok). Fallback: exchangerate.host."""
    usdtry, eurtry, gbptry = None, None, None
    status = "error"
    try:
        client = _get_client()
        # Önce open.er-api.com (ücretsiz, anahtar yok; günde bir güncelleme)
        r = await client.get("https://open.er-api.com/v6/latest/USD")
        if r.status_code != 200:
            raise RuntimeError(f"FX API status {r.status_code}")
        data = r.json()
        if data.get("result") == "error":
            raise RuntimeError(data.get("error-type", "unknown"))
        rates = data.get("rates") or {}
        usd_try = rates.get("TRY")
        usd_eur = rates.get("EUR")
        usd_gbp = rates.get("GBP")
        if usd_try is not None and float(usd_try) > 0:
            usdtry = float(usd_try)
        if usd_eur and usd_try is not None and float(usd_eur) != 0:
            eurtry = float(usd_try) / float(usd_eur)
        if usd_gbp and usd_try is not None and float(usd_gbp) != 0:
            gbptry = float(usd_try) / float(usd_gbp)
        if usdtry is not None:
            status = "live"
    except Exception as e:
        logger.debug("[pricing_summary] FX fetch (open.er-api): %s", e)
        try:
            # Fallback: exchangerate.host (sınırlı/anahtar gerekebilir)
            client = _get_client()
            r = await client.get(
                "https://api.exchangerate.host/latest",
                params={"base": "USD", "symbols": "TRY,EUR,GBP"},
            )
            if r.status_code == 200:
                data = r.json()
                rates = data.get("rates") or {}
                usd_try, usd_eur, usd_gbp = (
                    rates.get("TRY"),
                    rates.get("EUR"),
                    rates.get("GBP"),
                )
                if usd_try is not None and float(usd_try) > 0:
                    usdtry = float(usd_try)
                if usd_eur and usd_try is not None and float(usd_eur) != 0:
                    eurtry = float(usd_try) / float(usd_eur)
                if usd_gbp and usd_try is not None and float(usd_gbp) != 0:
                    gbptry = float(usd_try) / float(usd_gbp)
                if usdtry is not None:
                    status = "live"
        except Exception as e2:
            logger.debug("[pricing_summary] FX fetch fallback: %s", e2)
    return usdtry, eurtry, gbptry, status


async def _fetch_fx() -> tuple[Optional[float], Optional[float], Optional[float], str]:
    """USD/TRY, EUR/TRY, GBP/TRY. Open ER-API / exchangerate.host. TTL 120s + in-flight dedupe."""
    global _fx_cache, _fx_ts, _fx_inflight
    now = time.time()
    if _fx_ts and (now - _fx_ts) < FX_TTL and _fx_cache:
        return (
            _fx_cache.get("usdtry"),
            _fx_cache.get("eurtry"),
            _fx_cache.get("gbptry"),
            "live" if (now - _fx_ts) < FX_TTL else "stale",
        )
    task = None
    is_creator = False
    if _fx_inflight is not None:
        task = _fx_inflight
    else:
        _fx_inflight = asyncio.create_task(_fetch_fx_upstream())
        task = _fx_inflight
        is_creator = True
    try:
        usdtry, eurtry, gbptry, status = await asyncio.wait_for(task, timeout=10.0)
        if is_creator:
            _fx_inflight = None
            if usdtry is not None:
                _fx_cache = {"usdtry": usdtry, "eurtry": eurtry, "gbptry": gbptry}
                _fx_ts = time.time()
        return usdtry, eurtry, gbptry, status
    except Exception:
        if is_creator:
            _fx_inflight = None
        if _fx_cache:
            return (
                _fx_cache.get("usdtry"),
                _fx_cache.get("eurtry"),
                _fx_cache.get("gbptry"),
                "stale",
            )
        return None, None, None, "error"


async def _fetch_metals() -> tuple[Optional[float], str]:
    """Ons altın USD (XAUUSD). Binance PAXGUSDT (1 PAXG ≈ 1 troy oz). Status: live|stale|error."""
    global _metals_cache, _metals_ts
    now = time.time()
    if (
        _metals_ts
        and (now - _metals_ts) < METALS_TTL
        and _metals_cache.get("xauusd") is not None
    ):
        return _metals_cache.get("xauusd"), "live" if (
            now - _metals_ts
        ) < METALS_TTL else "stale"
    xauusd = None
    status = "error"
    try:
        from app.services.data_hub import data_hub

        p = data_hub.get_price("PAXGUSDT")
        if p is not None and float(p) > 0:
            xauusd = float(p)
            status = "live"
            _metals_cache = {"xauusd": xauusd}
            _metals_ts = now
    except Exception as e:
        logger.debug("[pricing_summary] Metals fetch: %s", e)
    if xauusd is None and _metals_cache.get("xauusd") is not None:
        xauusd = _metals_cache["xauusd"]
        status = "stale"
    return xauusd, status


def _gram_altin_tl(xauusd: Optional[float], usdtry: Optional[float]) -> Optional[float]:
    if xauusd is None or usdtry is None or xauusd <= 0:
        return None
    return (xauusd * usdtry) / 31.1034768


async def get_summary() -> Dict[str, Any]:
    """Tek çağrıda tüm ticker özeti. In-flight dedupe ile aynı anda gelen istekler tek upstream yapar."""
    global _last_result, _crypto_cache, _crypto_ts
    async with _inflight_lock:
        now = time.time()
        server_ts = int(now * 1000)

        crypto_ok = _crypto_ts and (now - _crypto_ts) < CRYPTO_TTL
        btcusd, ethusd = _crypto_cache.get("btcusd"), _crypto_cache.get("ethusd")
        crypto_status = "live"
        if not crypto_ok or btcusd is None or ethusd is None:
            btcusd, ethusd, crypto_status = await _fetch_crypto()
            if btcusd is not None or ethusd is not None:
                _crypto_cache = {"btcusd": btcusd, "ethusd": ethusd}
                _crypto_ts = now

        usdtry, eurtry, gbptry, fx_status = await _fetch_fx()
        xauusd, metals_status = await _fetch_metals()

        ons_altin_usd = xauusd
        gram_altin_tl = _gram_altin_tl(xauusd, usdtry)

        gold_chg = _resolve_chg_pct(
            "ons_altin_usd", ons_altin_usd, ("PAXGUSDT", "XAUUSDT")
        )

        out = {
            "ts": server_ts,
            "usdtry": usdtry,
            "eurtry": eurtry,
            "gbptry": gbptry,
            "btcusd": btcusd,
            "ethusd": ethusd,
            "xauusd": xauusd,
            "gram_altin_tl": gram_altin_tl,
            "ons_altin_usd": ons_altin_usd,
            "usdtry_chg_pct": _resolve_chg_pct("usdtry", usdtry, ("USDTTRY",)),
            "eurtry_chg_pct": _resolve_chg_pct("eurtry", eurtry, ("EURTRY", "EURUSDT")),
            "gbptry_chg_pct": _resolve_chg_pct("gbptry", gbptry, ("GBPTRY", "GBPUSDT")),
            "gram_altin_tl_chg_pct": gold_chg,
            "ons_altin_usd_chg_pct": gold_chg,
            "source_status": {
                "fx": fx_status,
                "metals": metals_status,
                "crypto": crypto_status,
            },
        }
        _last_result = out
        return out
