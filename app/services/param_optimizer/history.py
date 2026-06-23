"""
Sunucu tarafı derin geçmiş klines çekimi (hibrit çözünürlük + disk cache).

Veri planı:
  * daily   : indikatör/rejim için ~4 yıl 1d
  * hourly  : kısa-vade ATR için son ~720 saat 1h
  * backtest: hibrit fiyat yolu —
        son `fine_days` gün  -> ince çözünürlük (varsayılan 15m)
        daha eski (max_days'e kadar) -> kaba çözünürlük (varsayılan 1h)
    Backtest motoru değişken mum süreleriyle çalışabildiği için iki seri
    birleştirilir (yakın geçmiş ince, uzak geçmiş ucuz).

Çekim, mevcut public_get_json (retry/backoff) üzerinden sayfalı yapılır. Sonuç
sembol+interval bazında diske kalıcı cache'lenir; sonraki çalışmada sadece
eksik yeni mumlar ve gerekiyorsa eksik eski aralıklar eklenir.
"""

from __future__ import annotations

import json
import logging
import os
import time
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.param_optimizer.cancel import ParamOptimizerCancelled

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = os.getenv(
    "PARAM_OPTIMIZER_CACHE_DIR",
    str(_PROJECT_ROOT / "data" / "param_optimizer_cache"),
)
_BINANCE_MAX_LIMIT = 1000
_DAY_MS = 86_400_000
_KLINES_MIN_INTERVAL_SEC = float(os.getenv("PARAM_OPTIMIZER_KLINES_MIN_INTERVAL_SEC", "0.35"))
_KLINES_RATE_COOLDOWN_SEC = float(os.getenv("PARAM_OPTIMIZER_KLINES_RATE_COOLDOWN_SEC", "90"))
_KLINES_CONCURRENCY = max(1, int(os.getenv("PARAM_OPTIMIZER_KLINES_CONCURRENCY", "1")))
_KLINES_SEM = asyncio.Semaphore(_KLINES_CONCURRENCY)
_KLINES_THROTTLE_LOCK = asyncio.Lock()
_KLINES_LAST_REQUEST_MONO = 0.0
_KLINES_COOLDOWN_UNTIL_MONO = 0.0

_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

# Cache tazelik eşiği (sn) — interval'a göre
_CACHE_TTL = {
    "1d": 12 * 3600,
    "1h": 4 * 3600,
    "30m": 3 * 3600,
    "15m": 2 * 3600,
    "5m": 3600,
}


def _interval_ms(interval: str) -> int:
    return _INTERVAL_MS.get((interval or "1d").lower(), _DAY_MS)


def _candles_per_day(interval: str) -> float:
    return _DAY_MS / float(_interval_ms(interval))


def _parse(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        try:
            out.append(
                {
                    "t": int(c[0]),
                    "o": float(c[1]),
                    "h": float(c[2]),
                    "l": float(c[3]),
                    "c": float(c[4]),
                    "v": float(c[5]),
                }
            )
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _dedupe(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for c in candles:
        seen[int(c["t"])] = c
    return [seen[t] for t in sorted(seen.keys())]


def _resample_ohlcv(candles: List[Dict[str, Any]], target_ms: int) -> List[Dict[str, Any]]:
    """İnce/saatlik mumlardan daha kaba OHLCV seri üret."""
    if not candles:
        return []
    out: List[Dict[str, Any]] = []
    bucket = None
    cur = None
    for c in _dedupe(candles):
        try:
            b = int(c["t"]) // int(target_ms)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        close = float(c.get("c") or 0.0)
        if b != bucket:
            if cur is not None:
                out.append(cur)
            bucket = b
            cur = {
                "t": b * int(target_ms),
                "o": float(c.get("o") or close),
                "h": float(c.get("h") or close),
                "l": float(c.get("l") or close),
                "c": close,
                "v": float(c.get("v") or 0.0),
            }
        else:
            cur["h"] = max(cur["h"], float(c.get("h") or close))
            lo = float(c.get("l") or close)
            if lo > 0:
                cur["l"] = min(cur["l"], lo)
            cur["c"] = close or cur["c"]
            cur["v"] = float(cur.get("v") or 0.0) + float(c.get("v") or 0.0)
    if cur is not None:
        out.append(cur)
    return _dedupe(out)


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------
def _cache_path(symbol: str, interval: str) -> str:
    safe = "".join(ch for ch in symbol.upper() if ch.isalnum())
    return os.path.join(_CACHE_DIR, f"{safe}_{interval}.json")


def _load_cache(
    symbol: str, interval: str, min_bars: int, *, allow_stale: bool = False
) -> Optional[List[Dict[str, Any]]]:
    path = _cache_path(symbol, interval)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
            blob = json.load(fh)
        ttl = _CACHE_TTL.get(interval.lower(), 3 * 3600)
        if not allow_stale and time.time() - float(blob.get("fetched_at", 0)) > ttl:
            return None
        candles = blob.get("candles") or []
        if len(candles) < min_bars:
            return None
        return candles
    except Exception as e:
        logger.debug("param_optimizer cache load fail %s: %s", path, e)
        return None


def _save_cache(symbol: str, interval: str, candles: List[Dict[str, Any]]) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _cache_path(symbol, interval)
        existing: List[Dict[str, Any]] = []
        if os.path.exists(path):
            try:
                with open(path, "r") as fh:
                    blob = json.load(fh)
                existing = blob.get("candles") or []
            except Exception:
                existing = []
        merged = _dedupe(list(existing) + list(candles or []))
        with open(_cache_path(symbol, interval), "w") as fh:
            json.dump(
                {
                    "fetched_at": time.time(),
                    "symbol": symbol,
                    "interval": interval,
                    "candles": merged,
                },
                fh,
            )
    except Exception as e:
        logger.debug("param_optimizer cache save fail: %s", e)


def _merge_and_cache(
    symbol: str, interval: str, existing: List[Dict[str, Any]], extra: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    merged = _dedupe(list(existing or []) + list(extra or []))
    if merged:
        _save_cache(symbol, interval, merged)
    return merged


# ---------------------------------------------------------------------------
# Çekim
# ---------------------------------------------------------------------------
def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc or "").lower()
    return any(
        token in msg
        for token in (
            "rate limit",
            "weight limit",
            "weight_budget",
            "ip banned",
            "too many requests",
            "429",
            "418",
        )
    )


async def _klines_throttle() -> None:
    """Parametre asistanı klines çekimlerini Binance'e nazik yay."""
    global _KLINES_LAST_REQUEST_MONO
    async with _KLINES_THROTTLE_LOCK:
        now = time.monotonic()
        if now < _KLINES_COOLDOWN_UNTIL_MONO:
            await asyncio.sleep(_KLINES_COOLDOWN_UNTIL_MONO - now)
            now = time.monotonic()
        wait = _KLINES_MIN_INTERVAL_SEC - (now - _KLINES_LAST_REQUEST_MONO)
        if wait > 0:
            await asyncio.sleep(wait)
        _KLINES_LAST_REQUEST_MONO = time.monotonic()


def _note_rate_limit() -> None:
    global _KLINES_COOLDOWN_UNTIL_MONO
    _KLINES_COOLDOWN_UNTIL_MONO = max(
        _KLINES_COOLDOWN_UNTIL_MONO,
        time.monotonic() + max(1.0, _KLINES_RATE_COOLDOWN_SEC),
    )


async def _fetch_chunk(
    symbol: str,
    interval: str,
    limit: int,
    end_time: Optional[int] = None,
    start_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    from app.services.binance_spot import public_get_json
    from app.services.binance_rest_log import rest_source

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": int(min(limit, _BINANCE_MAX_LIMIT)),
    }
    if start_time is not None:
        params["startTime"] = int(start_time)
    if end_time is not None:
        params["endTime"] = int(end_time)
    await _klines_throttle()
    async with _KLINES_SEM:
        try:
            with rest_source("param_optimizer.klines"):
                raw = await public_get_json("/api/v3/klines", params, testnet=False)
        except Exception as e:
            if _is_rate_limit_error(e):
                _note_rate_limit()
            raise
    return _parse(raw)


async def fetch_series_after(
    symbol: str,
    interval: str,
    start_time: int,
    *,
    end_time: Optional[int] = None,
    max_bars: int = 5000,
    pace_sec: float = 0.05,
) -> List[Dict[str, Any]]:
    """Cache'in son mumundan sonra eksik yeni mumları ileri yönde çek."""
    interval_ms = _interval_ms(interval)
    cursor = int(start_time)
    end_limit = int(end_time if end_time is not None else time.time() * 1000)
    out: List[Dict[str, Any]] = []
    chunks = 0
    max_chunks = max(1, int(max_bars) // _BINANCE_MAX_LIMIT + 3)
    while cursor <= end_limit and len(out) < max_bars and chunks < max_chunks:
        want = min(_BINANCE_MAX_LIMIT, max_bars - len(out))
        try:
            part = await _fetch_chunk(
                symbol,
                interval,
                want,
                end_time=end_limit,
                start_time=cursor,
            )
        except Exception as e:
            logger.warning(
                "param_optimizer fetch %s %s append fail: %s", symbol, interval, e
            )
            break
        if not part:
            break
        part = [c for c in part if int(c.get("t", 0)) >= cursor]
        if not part:
            break
        out.extend(part)
        next_cursor = int(part[-1]["t"]) + interval_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        chunks += 1
        if len(part) < want:
            break
        delay = max(float(pace_sec or 0.0), _KLINES_MIN_INTERVAL_SEC)
        if delay:
            await asyncio.sleep(delay)
    return _dedupe(out)


async def fetch_series(
    symbol: str,
    interval: str,
    total: int,
    *,
    end_time: Optional[int] = None,
    pace_sec: float = 0.05,
) -> List[Dict[str, Any]]:
    """`total` mum hedefiyle geri doğru sayfalı çekim."""
    total = max(1, int(total))
    out: List[Dict[str, Any]] = []
    cursor = end_time
    chunks = 0
    max_chunks = total // _BINANCE_MAX_LIMIT + 3
    while len(out) < total and chunks < max_chunks:
        want = min(_BINANCE_MAX_LIMIT, total - len(out) + 1)
        try:
            part = await _fetch_chunk(symbol, interval, want, cursor)
        except Exception as e:
            logger.warning(
                "param_optimizer fetch %s %s chunk fail: %s", symbol, interval, e
            )
            break
        if not part:
            break
        out = part + out
        cursor = int(part[0]["t"]) - 1
        chunks += 1
        if len(part) < want - 1:  # daha eski veri yok
            break
        delay = max(float(pace_sec or 0.0), _KLINES_MIN_INTERVAL_SEC)
        if delay:
            await asyncio.sleep(delay)
    return _dedupe(out)[-total:]


async def fetch_history(
    symbol: str,
    *,
    fine_interval: str = "15m",
    fine_days: int = 365,
    coarse_interval: str = "1h",
    max_days: int = 1460,
    use_cache: bool = True,
    progress_cb=None,
) -> Dict[str, Any]:
    """daily + hourly + hibrit backtest serisi döndür."""
    symbol = (symbol or "BTCUSDT").upper().strip()

    def _emit(msg: str, **kw):
        if progress_cb:
            try:
                progress_cb({"stage": "fetch", "message": msg, **kw})
            except ParamOptimizerCancelled:
                raise
            except Exception:
                pass

    async def _series(
        interval: str, total: int, min_bars: int, label: str
    ) -> List[Dict[str, Any]]:
        interval_ms = _interval_ms(interval)
        if use_cache:
            c = _load_cache(symbol, interval, 1, allow_stale=True)
            if c is not None:
                c = _dedupe(c)
                _emit(f"{symbol} {label}: kalıcı önbellekten {len(c)} mum", bars=len(c))
                latest = int(c[-1]["t"]) if c else 0
                missing_new = 0
                if latest:
                    missing_new = max(
                        0,
                        int((int(time.time() * 1000) - latest) / max(interval_ms, 1)),
                    )
                if missing_new > 0:
                    add_cap = max(1000, min(max(total, missing_new + 3), total * 2))
                    fresh = await fetch_series_after(
                        symbol,
                        interval,
                        latest + interval_ms,
                        max_bars=add_cap,
                    )
                    if fresh:
                        c = _merge_and_cache(symbol, interval, c, fresh)
                        _emit(
                            f"{symbol} {label}: {len(fresh)} yeni mum eklendi",
                            bars=len(c),
                            appended=len(fresh),
                        )
                if len(c) >= min_bars:
                    return c[-max(total, len(c)) :]
                _emit(
                    f"{symbol} {label}: önbellek eksik, eski aralık tamamlanıyor…",
                    bars=len(c),
                )
        _emit(f"{symbol} {label} verisi çekiliyor…")
        c = await fetch_series(symbol, interval, total)
        if len(c) < min_bars and use_cache:
            stale = _load_cache(symbol, interval, min_bars, allow_stale=True)
            if stale is not None:
                _emit(
                    f"{symbol} {label}: canlı çekim zayıf, eski önbellek kullanılıyor ({len(stale)} mum)",
                    bars=len(stale),
                    stale_cache=True,
                )
                return stale
        if c:
            _save_cache(symbol, interval, c)
        _emit(f"{symbol} {label}: {len(c)} mum alındı", bars=len(c))
        return c

    # daily (feature)
    daily = await _series("1d", max_days, min_bars=30, label="günlük geçmiş")
    # hourly (kısa ATR)
    hourly = await _series("1h", 720, min_bars=48, label="saatlik")

    # hibrit backtest serisi
    fine_total = int(fine_days * _candles_per_day(fine_interval))
    fine = await _series(
        fine_interval,
        fine_total,
        min_bars=int(_candles_per_day(fine_interval) * 30),
        label=f"{fine_interval} ince ({fine_days}g)",
    )
    backtest = list(fine)
    coarse_days = max_days if not fine else max(0, max_days - fine_days)
    if coarse_days > 30:
        coarse_total = int(coarse_days * _candles_per_day(coarse_interval))
        older_end = int(fine[0]["t"]) - 1 if fine else None
        coarse_min_bars = int(_candles_per_day(coarse_interval) * min(coarse_days, 30))
        coarse_cache = _load_cache(symbol, coarse_interval, coarse_min_bars) if use_cache else None
        if coarse_cache is None and use_cache:
            coarse_cache = _load_cache(
                symbol, coarse_interval, coarse_min_bars, allow_stale=True
            )
            if coarse_cache is not None:
                _emit(
                    f"{symbol} {coarse_interval} uzak geçmiş: eski önbellek hazır ({len(coarse_cache)} mum)",
                    bars=len(coarse_cache),
                    stale_cache=True,
                )
        older = [
            c
            for c in (coarse_cache or [])
            if older_end is None or int(c.get("t", 0)) <= older_end
        ]
        older = _dedupe(older)[-coarse_total:] if older else []
        if len(older) >= min(coarse_total, coarse_min_bars):
            _emit(
                f"{symbol} {coarse_interval} uzak geçmiş: önbellekten {len(older)} mum",
                bars=len(older),
            )
        else:
            remaining = max(0, coarse_total - len(older))
            fetch_end = int(older[0]["t"]) - 1 if older else older_end
            _emit(
                f"{symbol} {coarse_interval} uzak geçmiş eksik, {remaining} mum tamamlanıyor…"
            )
            fetched_old = await fetch_series(
                symbol, coarse_interval, remaining, end_time=fetch_end
            )
            if fetched_old and coarse_cache:
                older = _merge_and_cache(symbol, coarse_interval, coarse_cache, fetched_old)
                older = [
                    c
                    for c in older
                    if older_end is None or int(c.get("t", 0)) <= older_end
                ][-coarse_total:]
            elif fetched_old:
                older = _dedupe(fetched_old + older)[-coarse_total:]
                _save_cache(symbol, coarse_interval, older)
            elif older:
                _emit(
                    f"{symbol} {coarse_interval} uzak geçmiş: canlı çekim zayıf, önbellekten {len(older)} mum",
                    bars=len(older),
                    stale_cache=True,
                )
        backtest = _dedupe(older + fine)
        _emit(
            f"{symbol} backtest serisi hazır: {len(backtest)} mum", bars=len(backtest)
        )

    if len(backtest) < 60 and hourly:
        backtest = _dedupe(list(hourly) + backtest)
        _emit(
            f"{symbol} backtest serisi saatlik yedekle güçlendirildi: {len(backtest)} mum",
            bars=len(backtest),
            fallback_interval="1h",
        )

    if not backtest:
        backtest = list(daily)

    if len(daily) < 30 and backtest:
        daily_from_bt = _resample_ohlcv(backtest, _DAY_MS)
        if len(daily_from_bt) > len(daily):
            daily = daily_from_bt
            _emit(
                f"{symbol} günlük gösterge serisi backtest mumlarından üretildi: {len(daily)} gün",
                bars=len(daily),
                fallback_interval="synthetic_1d",
            )

    return {
        "daily": daily,
        "hourly": hourly,
        "backtest": backtest,
        "meta": {
            "daily_bars": len(daily),
            "hourly_bars": len(hourly),
            "backtest_bars": len(backtest),
            "fine_interval": fine_interval,
            "coarse_interval": coarse_interval,
            "span_days": round((backtest[-1]["t"] - backtest[0]["t"]) / _DAY_MS, 1)
            if len(backtest) > 1
            else 0,
        },
    }
