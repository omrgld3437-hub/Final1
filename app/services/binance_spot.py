"""
FILE: binance_spot.py
Binance Spot API - single gateway for all Binance HTTP (public + signed).
Retry/backoff 429-418, logging (endpoint, latency, retry). No secrets in logs.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import logging
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Binance error log throttle: aynı (path, status/code) 5 dk içinde tekrar loglanmasın (tradeFee 400 vb. patlamayı keser)
_binance_error_log_throttle: Dict[Tuple[str, ...], float] = {}
_BINANCE_ERROR_THROTTLE_SEC = 300.0


def _should_log_binance_error(key: Tuple[str, ...]) -> bool:
    now = time.monotonic()
    if key in _binance_error_log_throttle:
        if now - _binance_error_log_throttle[key] < _BINANCE_ERROR_THROTTLE_SEC:
            return False
    _binance_error_log_throttle[key] = now
    return True

BINANCE_API = "https://api.binance.com"
BINANCE_TESTNET = "https://testnet.binance.vision"

# Rate-limit retry – keep total path bounded to avoid blocking request handlers
MAX_RETRIES = 2
INITIAL_BACKOFF = 0.5
BACKOFF_MULTIPLIER = 2.0
BINANCE_REQUEST_TIMEOUT_SEC = 8.0  # 8s (openOrders/account can be slow under load; was 4s)

# Per-request HTTP timeout
BINANCE_HTTP_TIMEOUT = httpx.Timeout(3.0, connect=2.0)


class DependencyFailure(Exception):
    """Raised when Binance retry budget exceeded or total timeout. Caller should return 503."""


class BinanceSignedError(Exception):
    """Binance API returned HTTP 200 but body has code != 0 (e.g. -2013 order does not exist)."""
    def __init__(self, code: int, msg: str, data: Optional[Dict[str, Any]] = None):
        self.code = code
        self.msg = msg or ""
        self.data = data or {}
        super().__init__(f"Binance code={code} msg={msg}")


class BinanceIPBannedError(Exception):
    """Binance 418 IP banned; caller should serve stale/cache until banned_until_ts (time.time())."""
    def __init__(self, banned_until_ts: float):
        self.banned_until_ts = banned_until_ts
        super().__init__(f"Binance IP banned until {banned_until_ts}")


# 418 "IP banned until XXX" sonrası signed istekleri bu süreye kadar atlama (global backoff)
# Mutable container so no "global" declaration needed in functions (avoids "used prior to global declaration")
_binance_ip_ban_state: dict = {"until_ts": 0.0}


def is_ip_banned() -> bool:
    return time.time() < _binance_ip_ban_state["until_ts"]


def ip_ban_remaining_sec() -> float:
    return max(0.0, _binance_ip_ban_state["until_ts"] - time.time())


def _parse_418_banned_until(text: str) -> Optional[float]:
    """Parse 'IP banned until 1770997257749' from Binance 418 body. Returns time.time() when retry OK (+60s buffer)."""
    import re
    m = re.search(r"IP banned until (\d+)", text or "")
    if not m:
        return None
    banned_ms = int(m.group(1))
    return banned_ms / 1000.0 + 60.0


class CircuitBreaker:
    """Circuit breaker: 3 consecutive failures -> open 30s -> half-open."""
    FAILURE_THRESHOLD = 3
    OPEN_SECONDS = 30.0
    _consecutive_failures = 0
    _state = "closed"  # closed | open | half_open
    _opened_at: float = 0.0

    @classmethod
    def record_success(cls) -> None:
        cls._consecutive_failures = 0
        cls._state = "closed"

    @classmethod
    def record_failure(cls) -> None:
        cls._consecutive_failures += 1
        if cls._consecutive_failures >= cls.FAILURE_THRESHOLD:
            cls._state = "open"
            cls._opened_at = time.monotonic()

    @classmethod
    def can_attempt(cls) -> bool:
        now = time.monotonic()
        if cls._state == "closed":
            return True
        if cls._state == "open":
            if now - cls._opened_at >= cls.OPEN_SECONDS:
                cls._state = "half_open"
                return True
            return False
        return True  # half_open: allow 1 probe

    @classmethod
    def get_state(cls) -> str:
        if cls._state == "open" and time.monotonic() - cls._opened_at >= cls.OPEN_SECONDS:
            cls._state = "half_open"
        return cls._state


# Binance server time cache (avoid -1021 timestamp outside recvWindow)
_binance_time_cache: Dict[bool, Tuple[int, float]] = {}  # testnet -> (server_time_ms, local_ts)
_BINANCE_TIME_CACHE_TTL = 30.0  # seconds
_BINANCE_TIME_STALE_MAX_SEC = 120.0  # extrapolate stale cache before local-ms fallback
_BINANCE_TIME_FETCH_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_BINANCE_TIME_WARN_THROTTLE_SEC = 300.0
_binance_time_warn_last = 0.0
_MAX_CLOCK_RETRIES = 2


def _read_binance_time_from_cache(testnet: bool, *, max_age_sec: float) -> Optional[int]:
    """Extrapolate cached server time; None if missing or older than max_age_sec."""
    cached = _binance_time_cache.get(testnet)
    if not cached:
        return None
    server_ms, local_ts = cached
    age = time.time() - local_ts
    if age > max_age_sec:
        return None
    return int(server_ms + age * 1000)


def _store_binance_time_cache(testnet: bool, server_ms: int) -> None:
    _binance_time_cache[testnet] = (server_ms, time.time())


def _log_binance_time_unavailable(reason: Optional[BaseException] = None) -> None:
    global _binance_time_warn_last
    now = time.monotonic()
    if now - _binance_time_warn_last < _BINANCE_TIME_WARN_THROTTLE_SEC:
        return
    _binance_time_warn_last = now
    extra = f" ({type(reason).__name__})" if reason else ""
    logger.warning(
        "Binance server time unavailable; using local timestamp%s. If you get -1021, sync clock: %s",
        extra,
        clock_sync_hint(),
    )


def invalidate_binance_time_cache(testnet: Optional[bool] = None) -> None:
    """Clear cached Binance server time. testnet=None clears both."""
    if testnet is None:
        _binance_time_cache.clear()
    else:
        _binance_time_cache.pop(testnet, None)


def clock_sync_hint() -> str:
    """OS-aware NTP resync hint for Binance -1021 (timestamp outside recvWindow)."""
    if sys.platform == "win32":
        return "Windows: w32tm /resync veya Ayarlar > Saat ile NTP senkronizasyonu yapın."
    if sys.platform == "darwin":
        return "macOS: sudo sntp -sS time.apple.com veya Sistem Ayarları > Tarih ve Saat > Otomatik ayarla."
    return "Linux: sudo timedatectl set-ntp true ile NTP senkronizasyonu yapın."


def _base_url(testnet: bool) -> str:
    return BINANCE_TESTNET if testnet else BINANCE_API


def build_signed_params(keys: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build params with timestamp + signature (testable pure function). Keys: .api_secret, .testnet."""
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params["signature"] = hmac.new(
        getattr(keys, "api_secret", "").encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return params


async def _public_get_json_impl(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    testnet: bool = False,
    client: Optional[httpx.AsyncClient] = None,
    request_id: Optional[str] = None,
) -> Any:
    """Public GET with retry/backoff. Circuit breaker: 3 failures -> open 30s."""
    if not CircuitBreaker.can_attempt():
        raise DependencyFailure("Binance circuit breaker open")
    t0 = time.perf_counter()
    last_exc = None
    backoff = INITIAL_BACKOFF
    retry_count = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            data = await _public_get(client, path, params, testnet)
            CircuitBreaker.record_success()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            try:
                from app.services.binance_metrics import BinanceMetrics
                BinanceMetrics.record(path, elapsed_ms, retry_count)
            except Exception:
                pass
            logger.debug(
                "binance_spot public_get path=%s latency_ms=%.0f attempt=%s request_id=%s",
                path, elapsed_ms, attempt + 1, request_id or "-"
            )
            return data
        except Exception as e:
            last_exc = e
            retry_count = attempt
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.warning(
                "binance_spot public_get path=%s attempt=%s status=%s request_id=%s error=%s",
                path, attempt + 1, status, request_id or "-", type(e).__name__
            )
            if attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            CircuitBreaker.record_failure()
            raise DependencyFailure(f"Binance retry budget exceeded: {e}") from last_exc
    if last_exc:
        CircuitBreaker.record_failure()
        raise DependencyFailure(f"Binance retry budget exceeded: {last_exc}") from last_exc
    return None


async def public_get_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    testnet: bool = False,
    client: Optional[httpx.AsyncClient] = None,
    request_id: Optional[str] = None,
) -> Any:
    """Public GET with retry/backoff. Total timeout 4s; raises DependencyFailure on exceed."""
    try:
        return await asyncio.wait_for(
            _public_get_json_impl(path, params, testnet, client, request_id),
            timeout=BINANCE_REQUEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        raise DependencyFailure("Binance request timeout (4s)") from e


async def _signed_json_impl(
    method: str,
    path: str,
    keys: Any,
    params: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
    request_id: Optional[str] = None,
) -> Any:
    """Signed request with retry/backoff. Circuit breaker: 3 failures -> open 30s."""
    if not CircuitBreaker.can_attempt():
        raise DependencyFailure("Binance circuit breaker open")
    t0 = time.perf_counter()
    last_exc = None
    backoff = INITIAL_BACKOFF
    retry_count = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            data = await _signed_request_impl(client, method, path, keys, params)
            CircuitBreaker.record_success()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            try:
                from app.services.binance_metrics import BinanceMetrics
                BinanceMetrics.record(path, elapsed_ms, retry_count)
            except Exception:
                pass
            logger.debug(
                "binance_spot signed method=%s path=%s latency_ms=%.0f attempt=%s request_id=%s",
                method, path, elapsed_ms, attempt + 1, request_id or "-"
            )
            return data
        except Exception as e:
            last_exc = e
            retry_count = attempt
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.warning(
                "binance_spot signed method=%s path=%s attempt=%s status=%s request_id=%s",
                method, path, attempt + 1, status, request_id or "-"
            )
            if attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            CircuitBreaker.record_failure()
            raise DependencyFailure(f"Binance retry budget exceeded: {e}") from last_exc
    if last_exc:
        CircuitBreaker.record_failure()
        raise DependencyFailure(f"Binance retry budget exceeded: {last_exc}") from last_exc
    return None


async def signed_json(
    method: str,
    path: str,
    keys: Any,
    params: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
    request_id: Optional[str] = None,
) -> Any:
    """Signed request with retry/backoff. Total timeout 4s; raises DependencyFailure on exceed."""
    try:
        return await asyncio.wait_for(
            _signed_json_impl(method, path, keys, params, client, request_id),
            timeout=BINANCE_REQUEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        raise DependencyFailure("Binance request timeout (4s)") from e


def _guard_no_per_symbol_ticker_price(path: str, params: Optional[Dict[str, Any]]) -> None:
    """v2: Per-symbol ticker/price forbidden; use ticker_price_all() bulk only."""
    if "ticker/price" in path and params and params.get("symbol"):
        raise RuntimeError("Per-symbol ticker/price forbidden; use ticker_price_all() bulk only")


async def _public_get(
    client: Optional[httpx.AsyncClient],
    path: str,
    params: Optional[Dict[str, Any]] = None,
    testnet: bool = False,
) -> Dict[str, Any]:
    """Public GET with optional retry/backoff on 429/418."""
    _guard_no_per_symbol_ticker_price(path, params)
    params = params or {}
    weight = await _rest_precheck("GET", path, params)
    base = _base_url(testnet)
    url = f"{base}{path}"
    last_exc = None
    backoff = INITIAL_BACKOFF
    t0 = time.perf_counter()
    for attempt in range(MAX_RETRIES + 1):
        try:
            if client is None:
                async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
                    r = await c.get(url, params=params)
            else:
                r = await client.get(url, params=params)
            if r.status_code in (429, 418):
                last_exc = RuntimeError(f"Binance rate limit: {r.status_code}")
                if r.status_code == 418:
                    until = _parse_418_banned_until(getattr(r, "text", "") or "")
                    if until is not None:
                        _binance_ip_ban_state["until_ts"] = until
                if attempt < MAX_RETRIES:
                    await _asyncio_sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                    continue
                r.raise_for_status()
            r.raise_for_status()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            try:
                from app.services.binance_rest_log import record_rest
                from app.services.binance_weight import record_weight_used
                record_rest("GET", path, params=params, weight=weight, status=r.status_code,
                            latency_ms=elapsed_ms, outcome="ok")
                record_weight_used(None, None, weight, elapsed_ms)
            except Exception:
                pass
            return r.json()
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code in (429, 418) and attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            try:
                from app.services.binance_rest_log import record_rest
                record_rest("GET", path, params=params, weight=weight,
                            status=getattr(e.response, "status_code", None),
                            latency_ms=(time.perf_counter() - t0) * 1000,
                            outcome="error", detail=str(e)[:120])
            except Exception:
                pass
            raise
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            try:
                from app.services.binance_rest_log import record_rest
                record_rest("GET", path, params=params, weight=weight,
                            latency_ms=(time.perf_counter() - t0) * 1000,
                            outcome="error", detail=str(e)[:120])
            except Exception:
                pass
            raise
    if last_exc:
        raise last_exc
    return {}


async def _asyncio_sleep(seconds: float):
    await asyncio.sleep(seconds)


def _sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


async def _get_binance_timestamp(
    client: Optional[httpx.AsyncClient],
    testnet: bool,
    force_refresh: bool = False,
) -> int:
    """Binance server time (ms). Cached 30s; stale extrapolation up to 120s before local fallback."""
    if force_refresh:
        invalidate_binance_time_cache(testnet)
    if not force_refresh:
        fresh = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_CACHE_TTL)
        if fresh is not None:
            return fresh
    if is_ip_banned():
        stale = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_STALE_MAX_SEC)
        if stale is not None:
            return stale
        return int(time.time() * 1000)
    base = _base_url(testnet)
    url = f"{base}/api/v3/time"
    last_exc: Optional[BaseException] = None
    for attempt in range(3):
        try:
            if client is not None:
                r = await client.get(url, timeout=_BINANCE_TIME_FETCH_TIMEOUT)
            else:
                async with httpx.AsyncClient(timeout=_BINANCE_TIME_FETCH_TIMEOUT) as c:
                    r = await c.get(url)
            r.raise_for_status()
            data = r.json()
            server_ms = int(data.get("serverTime", 0) or (time.time() * 1000))
            _store_binance_time_cache(testnet, server_ms)
            try:
                from app.services.binance_rest_log import record_rest
                from app.services.binance_weight import record_weight_used
                record_rest("GET", "/api/v3/time", weight=1, status=r.status_code, outcome="ok")
                record_weight_used(None, None, 1)
            except Exception:
                pass
            return server_ms
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await _asyncio_sleep(0.5 * (attempt + 1))
    stale = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_STALE_MAX_SEC)
    if stale is not None:
        return stale
    _log_binance_time_unavailable(last_exc)
    return int(time.time() * 1000)


def _path_weight(path: str, method: str, params: Optional[Dict[str, Any]] = None) -> int:
    """Binance endpoint weight (bulk ticker/24hr = 40)."""
    try:
        from app.services.binance_rest_log import compute_weight
        return compute_weight(path, method, params)
    except Exception:
        pass
    if "/api/v3/account" in path:
        return 10
    if "/api/v3/order" in path and method.upper() in ("POST", "DELETE"):
        return 1
    if "/api/v3/openOrders" in path or "/api/v3/allOrders" in path:
        return 10
    if "/api/v3/time" in path:
        return 1
    if "/api/v3/exchangeInfo" in path:
        return 10
    if "/api/v3/ticker/price" in path:
        return 2
    if "/api/v3/ticker/24hr" in path:
        return 40
    return 5


async def _rest_precheck(method: str, path: str, params: Optional[Dict[str, Any]] = None) -> int:
    """REST guard: ban/throttle/budget. Returns weight or raises."""
    from app.services.binance_rest_log import should_allow_rest, record_rest
    allowed, reason, weight = should_allow_rest(method, path, params)
    if not allowed:
        record_rest(method, path, params=params, weight=weight, outcome="skipped", detail=reason)
        if reason == "ip_banned":
            raise BinanceIPBannedError(_binance_ip_ban_state["until_ts"])
        raise DependencyFailure(f"REST blocked: {reason}")
    try:
        from app.services.binance_weight import request_weight_tokens
        ok = await request_weight_tokens(None, None, weight)
        if not ok:
            record_rest(method, path, params=params, weight=weight, outcome="denied", detail="weight_budget")
            raise DependencyFailure("Binance weight limit exceeded - call denied")
    except DependencyFailure:
        raise
    except Exception:
        pass
    return weight


async def _build_signed_request(
    client: Optional[httpx.AsyncClient],
    method: str,
    path: str,
    keys: Any,
    base_params: Dict[str, Any],
    force_refresh_time: bool = False,
) -> tuple:
    """Build url/headers/request_kw for a signed Binance call. Timestamp refreshed each call."""
    testnet = getattr(keys, "testnet", False)
    params = dict(base_params)
    params["timestamp"] = await _get_binance_timestamp(client, testnet, force_refresh=force_refresh_time)
    params["recvWindow"] = 60000
    params_str = {k: str(v) for k, v in params.items()}
    query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))
    signature = _sign(keys.api_secret, query_for_sign)
    final_query = query_for_sign + "&signature=" + signature
    base = _base_url(testnet)
    url = f"{base}{path}"
    headers = {"X-MBX-APIKEY": keys.api_key}
    logger.debug(
        "BINANCE_SIGN_DEBUG %s %s QUERY=%s",
        method.upper(), path, final_query.replace(signature, "***"),
    )
    if method.upper() == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        request_kw = {"content": final_query}
        req_url = url
    else:
        req_url = f"{url}?{final_query}"
        request_kw = {"url": req_url}
    return req_url, url, headers, request_kw, params


async def _signed_request_impl(
    client: Optional[httpx.AsyncClient],
    method: str,
    path: str,
    keys: Any,  # BinanceKeys-like: .api_key, .api_secret, .testnet
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Signed request impl: timestamp (ms), HMAC SHA256, X-MBX-APIKEY.
    Altın kural: İmzada kullandığın query string ile Binance'e gönderdiğin query string
    birebir aynı olmalı (sıra + encoding). params= kullanılmaz; query string elle URL'e eklenir.
    Timestamp = Binance server time (cached) to avoid -1021 recvWindow.
    Weight budget: deny call if insufficient tokens (sliding 60s).
    """
    base_params = dict(params or {})
    weight = await _rest_precheck(method, path, base_params)
    if time.time() < _binance_ip_ban_state["until_ts"]:
        raise BinanceIPBannedError(_binance_ip_ban_state["until_ts"])
    t0_req = time.perf_counter()
    testnet = getattr(keys, "testnet", False)
    last_exc = None
    backoff = INITIAL_BACKOFF
    http_method = method.upper()
    clock_retries = 0
    for attempt in range(MAX_RETRIES + 1):
        force_refresh_time = clock_retries > 0
        req_url, url, headers, request_kw, params = await _build_signed_request(
            client, method, path, keys, base_params, force_refresh_time=force_refresh_time,
        )
        try:
            if client is None:
                async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
                    if http_method == "GET":
                        r = await c.get(req_url, headers=headers)
                    elif http_method == "DELETE":
                        r = await c.delete(req_url, headers=headers)
                    else:
                        r = await c.post(url, headers=headers, **request_kw)
            else:
                if http_method == "GET":
                    r = await client.get(req_url, headers=headers)
                elif http_method == "DELETE":
                    r = await client.delete(req_url, headers=headers)
                else:
                    r = await client.post(url, headers=headers, **request_kw)
            if r.status_code in (429, 418):
                last_exc = RuntimeError(f"Binance rate limit: {r.status_code}")
                if r.status_code == 418:
                    until = _parse_418_banned_until(getattr(r, "text", "") or "")
                    if until is not None:
                        _binance_ip_ban_state["until_ts"] = until
                if attempt < MAX_RETRIES:
                    await _asyncio_sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                    continue
                r.raise_for_status()
            r.raise_for_status()
            data = r.json()
            elapsed_ms = (time.perf_counter() - t0_req) * 1000
            try:
                from app.services.binance_rest_log import record_rest
                from app.services.binance_weight import record_weight_used
                record_rest(method, path, params={k: v for k, v in params.items() if k != "signature"},
                            weight=weight, status=r.status_code, latency_ms=elapsed_ms, outcome="ok")
                record_weight_used(None, getattr(keys, "api_key", None), weight, elapsed_ms)
            except Exception:
                pass
            code = data.get("code", 0) if isinstance(data, dict) else 0
            if code not in (0, None):
                msg = data.get("msg", "Unknown error") if isinstance(data, dict) else "Unknown error"
                if code == -1021 and clock_retries < _MAX_CLOCK_RETRIES:
                    clock_retries += 1
                    invalidate_binance_time_cache(testnet)
                    logger.info(
                        "BINANCE_CLOCK_RETRY path=%s attempt=%s/%s",
                        path, clock_retries, _MAX_CLOCK_RETRIES,
                    )
                    continue
                if code in (-2015, -2008):
                    logger.debug("BINANCE_SIGNED_ERROR path=%s status=200 code=%s msg=%s", path, code, msg)
                else:
                    logger.warning("BINANCE_SIGNED_ERROR path=%s status=200 code=%s msg=%s", path, code, msg)
                try:
                    if _should_log_binance_error((path, "200", code)):
                        from app.error_logging import log_error_fire_and_forget
                        ctx = {"path": path, "method": method, "code": code}
                        if code == -1021:
                            ctx["hint"] = f"Sunucu saati ile Binance saati uyumsuz. {clock_sync_hint()}"
                        log_error_fire_and_forget("binance", msg, detail=None, context=ctx)
                except Exception:
                    pass
                raise BinanceSignedError(code, msg, data if isinstance(data, dict) else {})
            return data
        except httpx.HTTPStatusError as e:
            last_exc = e
            try:
                body = (e.response.text or "")[:500]
            except Exception:
                body = ""
            sc = getattr(e.response, "status_code", None)
            try:
                b = json.loads(body) if body else {}
                code = isinstance(b, dict) and b.get("code")
                msg = (isinstance(b, dict) and b.get("msg")) or ""
                is_invalid_key = (
                    sc == 401
                    or (sc == 400 and code in (-2015, -2008))
                )
                if sc == 400 and code == -2013:
                    raise BinanceSignedError(int(code), str(msg), b if isinstance(b, dict) else {})
                if sc == 400 and code == -1021 and clock_retries < _MAX_CLOCK_RETRIES:
                    clock_retries += 1
                    invalidate_binance_time_cache(testnet)
                    logger.info(
                        "BINANCE_CLOCK_RETRY path=%s attempt=%s/%s status=400",
                        path, clock_retries, _MAX_CLOCK_RETRIES,
                    )
                    continue
            except BinanceSignedError:
                raise
            except Exception:
                b = {}
                code = None
                is_invalid_key = sc == 401
            if is_invalid_key:
                logger.debug(
                    "BINANCE_SIGNED_ERROR status=401 Invalid API-key, IP, or permissions. Path=%s (API anahtari/IP/izinleri veya sunucu saati kontrol edin)",
                    path,
                )
            else:
                hint = f"API anahtari, IP beyaz listesi veya sunucu saati. {clock_sync_hint()}"
                logger.warning(
                    "BINANCE_SIGNED_ERROR path=%s status=%s body=%s hint=%s",
                    path, sc, body[:200] if body else "", hint,
                )
            if e.response.status_code == 418:
                until = _parse_418_banned_until(getattr(e.response, "text", "") or "")
                if until is not None:
                    _binance_ip_ban_state["until_ts"] = until
            if e.response.status_code in (429, 418) and attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            if not is_invalid_key:
                try:
                    sk = (path, str(getattr(e.response, "status_code", None)))
                    if _should_log_binance_error(sk):
                        from app.error_logging import log_error_fire_and_forget
                        ctx = {"path": path, "method": method}
                        try:
                            b = json.loads(body) if body else {}
                            if isinstance(b, dict) and b.get("code") == -2015:
                                ctx["hint"] = "IP değişmiş veya API anahtarı/izin hatası olabilir; Binance'te güncel IP ve izinleri kontrol edin."
                            if isinstance(b, dict) and b.get("code") == -1021:
                                ctx["hint"] = clock_sync_hint()
                        except Exception:
                            pass
                        log_error_fire_and_forget("binance", str(e), detail=traceback.format_exc(), context=ctx)
                except Exception:
                    pass
            raise
        except BinanceSignedError as e:
            if e.code == -1021 and clock_retries < _MAX_CLOCK_RETRIES:
                clock_retries += 1
                invalidate_binance_time_cache(testnet)
                logger.info(
                    "BINANCE_CLOCK_RETRY path=%s attempt=%s/%s signed_error",
                    path, clock_retries, _MAX_CLOCK_RETRIES,
                )
                continue
            raise
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            try:
                if _should_log_binance_error((path, "error", type(e).__name__)):
                    from app.error_logging import log_error_fire_and_forget
                    log_error_fire_and_forget("binance", str(e), detail=traceback.format_exc(), context={"path": path, "method": method})
            except Exception:
                pass
            raise
    if last_exc:
        raise last_exc
    return {}


async def _signed_request(
    client: Optional[httpx.AsyncClient],
    method: str,
    path: str,
    keys: Any,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Signed request with timeout. Raises DependencyFailure on exceed."""
    try:
        return await asyncio.wait_for(
            _signed_request_impl(client, method, path, keys, params),
            timeout=BINANCE_REQUEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as e:
        raise DependencyFailure("Binance signed request timeout (%ss)" % int(BINANCE_REQUEST_TIMEOUT_SEC)) from e


# ---------------------------------------------------------------------------
# /api/v3/account – tek nokta: TTL cache + inflight dedupe (hangi route çağırırsa çağırsın)
# ---------------------------------------------------------------------------
_ACCOUNT_CACHE_TTL = 45.0
_account_cache: Dict[tuple, tuple] = {}  # (testnet, api_key) -> (data, ts)
_account_inflight: Dict[tuple, asyncio.Task] = {}
_account_lock = asyncio.Lock()


async def _fetch_account_upstream(keys: Any, tag: str = "wallet") -> Dict[str, Any]:
    """Tek upstream çağrı – sadece cache miss veya TTL dolunca."""
    from app.services.binance_rest_log import rest_source
    client = getattr(keys, "_client", None)
    with rest_source(f"wallet.{tag}"):
        return await _signed_request(client, "GET", "/api/v3/account", keys, {})


def _account_cache_key(keys: Any) -> tuple:
    return (getattr(keys, "testnet", False), getattr(keys, "api_key", "") or "")


async def invalidate_account_cache_for_keys(keys: Any) -> None:
    """Emir (al/sat) sonrası cüzdan verisinin hemen güncellenmesi için account cache'ini temizler.
    Bir sonraki get_wallet çağrısı Binance'ten taze veri çeker."""
    cache_key = _account_cache_key(keys)
    async with _account_lock:
        _account_cache.pop(cache_key, None)
        _account_inflight.pop(cache_key, None)


async def get_wallet(keys: Any, tag: str = "wallet") -> Dict[str, Any]:
    """GET /api/v3/account - balances. TTL + inflight dedupe. tag logda görünür."""
    cache_key = _account_cache_key(keys)
    now = time.time()
    task = None
    is_creator = False
    async with _account_lock:
        if cache_key in _account_cache:
            data, ts = _account_cache[cache_key]
            if now - ts < _ACCOUNT_CACHE_TTL:
                logger.info("ACCOUNT_CALL tag=%s cache_hit=true upstream_call=false age_sec=%.2f", tag, now - ts)
                return data
        if cache_key in _account_inflight:
            task = _account_inflight[cache_key]
            logger.info("ACCOUNT_CALL tag=%s cache_hit=false in_flight_reuse", tag)
        else:
            task = asyncio.create_task(_fetch_account_upstream(keys, tag))
            _account_inflight[cache_key] = task
            is_creator = True
            logger.info("ACCOUNT_CALL tag=%s cache_hit=false upstream_call=true", tag)
    try:
        data = await asyncio.wait_for(task, timeout=BINANCE_REQUEST_TIMEOUT_SEC)
    except asyncio.TimeoutError as e:
        if is_creator:
            async with _account_lock:
                if cache_key in _account_inflight and _account_inflight[cache_key] == task:
                    del _account_inflight[cache_key]
        raise DependencyFailure("Binance account request timeout (4s)") from e
    except Exception:
        if is_creator:
            async with _account_lock:
                if cache_key in _account_inflight and _account_inflight[cache_key] == task:
                    del _account_inflight[cache_key]
        raise
    if is_creator:
        async with _account_lock:
            if cache_key in _account_inflight and _account_inflight[cache_key] == task:
                _account_cache[cache_key] = (data, time.time())
                del _account_inflight[cache_key]
    return data


async def get_open_orders(keys: Any, symbol: Optional[str] = None) -> List[Dict]:
    """GET /api/v3/openOrders. If symbol given, pass it."""
    from app.services.binance_rest_log import rest_source
    params = {}
    if symbol:
        params["symbol"] = symbol.upper()
    client = getattr(keys, "_client", None)
    with rest_source("bot.open_orders"):
        data = await _signed_request(client, "GET", "/api/v3/openOrders", keys, params)
    return data if isinstance(data, list) else (data.get("orders") or data.get("data") or [])


async def get_all_orders(keys: Any, symbol: str, limit: int = 20) -> List[Dict]:
    """GET /api/v3/allOrders. Recent orders for reconciliation (bounded)."""
    from app.services.binance_rest_log import rest_source
    params = {"symbol": symbol.upper(), "limit": min(limit, 100)}
    client = getattr(keys, "_client", None)
    with rest_source("bot.all_orders"):
        data = await _signed_request(client, "GET", "/api/v3/allOrders", keys, params)
    return data if isinstance(data, list) else (data.get("orders") or data.get("data") or [])


def _is_order_not_found(code: int, msg: str) -> bool:
    """True if Binance response means order does not exist (NOT_FOUND => proceed to place)."""
    if code == -2013:
        return True
    if code == -1021:
        return True  # timestamp/recvWindow; treat as transient, do not treat as FOUND
    msg_lower = (msg or "").lower()
    if "order does not exist" in msg_lower or "unknown order" in msg_lower:
        return True
    return False


def _is_valid_order_response(data: Any, symbol: str, orig_client_order_id: str) -> bool:
    """True only if response is a valid order (orderId, status, symbol, clientOrderId match)."""
    if not isinstance(data, dict):
        return False
    oid = data.get("orderId")
    if oid is None:
        return False
    try:
        if int(oid) <= 0:
            return False
    except (ValueError, TypeError):
        return False
    status = (data.get("status") or "").upper()
    if status not in ("NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED"):
        return False
    if (data.get("symbol") or "").upper() != (symbol or "").upper():
        return False
    coid = (data.get("clientOrderId") or data.get("origClientOrderId") or "").strip()
    if coid != (orig_client_order_id or "").strip():
        return False
    return True


async def get_order_by_client_order_id(keys: Any, symbol: str, orig_client_order_id: str) -> Optional[Dict[str, Any]]:
    """GET /api/v3/order?symbol=X&origClientOrderId=Y. Returns order if exists (open or filled), None if not found (e.g. -2013).
    Never treat HTTP 200 + code!=0 as success. -2013 / 'Order does not exist' => NOT_FOUND => caller may place order.
    """
    params = {"symbol": symbol.upper(), "origClientOrderId": orig_client_order_id}
    client = getattr(keys, "_client", None)
    logger.info(
        "RECONCILE_QUERY path=/api/v3/order symbol=%s origClientOrderId=%s",
        symbol, orig_client_order_id[:36] if orig_client_order_id else "",
    )
    try:
        data = await _signed_request(client, "GET", "/api/v3/order", keys, params)
        raw_trunc = (json.dumps(data) if isinstance(data, dict) else str(data))[:2000]
        logger.info("RECONCILE_RESPONSE_BODY decision=FOUND body_trunc=%s", raw_trunc)
        if not _is_valid_order_response(data, symbol, orig_client_order_id):
            logger.warning("RECONCILE_RESPONSE_BODY decision=INVALID_ORDER (missing orderId/status/symbol/coid) treating as NOT_FOUND")
            return None
        return data
    except BinanceSignedError as e:
        if _is_order_not_found(e.code, e.msg):
            logger.debug("RECONCILE_RESPONSE_BODY decision=NOT_FOUND code=%s msg=%s => proceed to place", e.code, e.msg)
            return None
        raw_trunc = (json.dumps(e.data) if e.data else e.msg)[:2000]
        logger.info("RECONCILE_RESPONSE_BODY decision=ERROR code=%s msg=%s body_trunc=%s", e.code, e.msg, raw_trunc)
        raise
    except httpx.HTTPStatusError as e:
        body = (getattr(e.response, "text", None) or "")[:500]
        logger.debug("RECONCILE_RESPONSE_BODY decision=HTTP_ERROR status=%s body_trunc=%s", getattr(e.response, "status_code", None), body[:500])
        try:
            b = e.response.json() if hasattr(e.response, "json") and callable(getattr(e.response, "json")) else {}
            if isinstance(b, dict) and _is_order_not_found(b.get("code", 0), b.get("msg", "")):
                logger.debug("RECONCILE_DECISION NOT_FOUND (HTTP %s code=%s) => proceed to place", getattr(e.response, "status_code", None), b.get("code"))
                return None
        except Exception:
            pass
        raise
    except Exception as e:
        body = ""
        try:
            if hasattr(e, "response") and getattr(e.response, "text", None):
                body = str(e.response.text or "")[:500]
            logger.debug("RECONCILE_RESPONSE_BODY decision=EXCEPTION body_trunc=%s", body[:2000])
            if hasattr(e, "response") and hasattr(e.response, "json"):
                try:
                    b = e.response.json()
                    if isinstance(b, dict) and _is_order_not_found(b.get("code", 0), b.get("msg", "")):
                        return None
                except Exception:
                    pass
        except Exception:
            pass
        if "-2013" in str(e) or "-2013" in body or "Unknown order" in str(e).lower() or "order does not exist" in str(e).lower():
            logger.debug("RECONCILE_DECISION NOT_FOUND (exception) => proceed to place")
            return None
        raise


async def get_my_trades(keys: Any, symbol: str, limit: int = 50, order_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """GET /api/v3/myTrades. If order_id given, filter to trades with that orderId (verify fill)."""
    params = {"symbol": symbol.upper(), "limit": min(limit, 100)}
    client = getattr(keys, "_client", None)
    data = await _signed_request(client, "GET", "/api/v3/myTrades", keys, params)
    trades = data if isinstance(data, list) else []
    if order_id is not None:
        oid_int = int(order_id)
        trades = [t for t in trades if int(t.get("orderId") or 0) == oid_int]
    return trades


async def cancel_order(keys: Any, symbol: str, order_id: int) -> Dict[str, Any]:
    """DELETE /api/v3/order - Cancel an active order."""
    params = {"symbol": symbol.upper(), "orderId": order_id}
    client = getattr(keys, "_client", None)
    return await _signed_request(client, "DELETE", "/api/v3/order", keys, params)


_exchange_info_inflight: Dict[str, asyncio.Task] = {}
_exchange_info_lock = asyncio.Lock()
EXCHANGE_INFO_TTL = 3600.0
# Kompakt cache: tam exchangeInfo JSON RAM'de tutulmaz
_exchange_compact_cache: Dict[str, Tuple[List[str], Dict[str, Dict[str, Any]], float]] = {}


def _exchange_cache_key(testnet: bool) -> str:
    return "testnet" if testnet else "live"


def _filters_from_exchange_symbol_entry(s: Dict[str, Any]) -> Dict[str, Any]:
    sym = (s.get("symbol") or "").upper().strip()
    out: Dict[str, Any] = {
        "step_size": 0.00001,
        "step_size_str": "0.00001",
        "min_qty": 0.00001,
        "min_qty_str": "0.00001",
        "tick_size": 0.01,
        "tick_size_str": "0.01",
        "min_notional": 5.0,
        "baseAsset": s.get("baseAsset"),
        "quoteAsset": s.get("quoteAsset"),
    }
    for f in s.get("filters") or []:
        t = f.get("filterType")
        if t == "LOT_SIZE":
            step_raw = str(f.get("stepSize") or "0.00001")
            min_raw = str(f.get("minQty") or step_raw)
            out["step_size_str"] = step_raw
            out["min_qty_str"] = min_raw
            out["step_size"] = float(step_raw)
            out["min_qty"] = float(min_raw)
        elif t == "PRICE_FILTER":
            tick_raw = str(f.get("tickSize") or "0.01")
            out["tick_size_str"] = tick_raw
            out["tick_size"] = float(tick_raw)
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            out["min_notional"] = float(f.get("minNotional") or f.get("notional") or 5)
    return out


def _ingest_exchange_info_payload(key: str, data: Dict[str, Any]) -> None:
    symbols_list: List[str] = []
    filters_map: Dict[str, Dict[str, Any]] = {}
    for s in data.get("symbols") or []:
        if (s.get("status") or "") != "TRADING":
            continue
        sym = (s.get("symbol") or "").strip().upper()
        if not sym:
            continue
        symbols_list.append(sym)
        filters_map[sym] = _filters_from_exchange_symbol_entry(s)
    symbols_list.sort()
    _exchange_compact_cache[key] = (symbols_list, filters_map, time.time())


def _exchange_info_lightweight(symbols_list: List[str]) -> Dict[str, Any]:
    """Eski fetch_exchange_info çağıranları için sembol listesi (filtre yok)."""
    return {"symbols": [{"symbol": s, "status": "TRADING"} for s in symbols_list]}


async def _ensure_exchange_compact(testnet: bool = False, force_refresh: bool = False) -> None:
    from app.services.binance_rest_log import rest_source

    key = _exchange_cache_key(testnet)
    now = time.time()
    if not force_refresh and key in _exchange_compact_cache:
        _, _, ts = _exchange_compact_cache[key]
        if now - ts < EXCHANGE_INFO_TTL:
            return
    task = None
    is_creator = False
    async with _exchange_info_lock:
        if not force_refresh and key in _exchange_compact_cache:
            _, _, ts = _exchange_compact_cache[key]
            if now - ts < EXCHANGE_INFO_TTL:
                return
        if key in _exchange_info_inflight:
            task = _exchange_info_inflight[key]
        else:

            async def _fetch():
                async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
                    with rest_source("binance.exchange_info"):
                        return await _public_get(c, "/api/v3/exchangeInfo", None, testnet)

            task = asyncio.create_task(_fetch())
            _exchange_info_inflight[key] = task
            is_creator = True
    try:
        data = await task
        if isinstance(data, dict):
            _ingest_exchange_info_payload(key, data)
    finally:
        if is_creator:
            async with _exchange_info_lock:
                if _exchange_info_inflight.get(key) is task:
                    del _exchange_info_inflight[key]


def get_symbol_filters_sync(symbol: str, testnet: bool = False) -> Optional[Dict[str, Any]]:
    """Senkron okuma — cache zaten yüklüyse (DataHub tick dışı)."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return None
    key = _exchange_cache_key(testnet)
    entry = _exchange_compact_cache.get(key)
    if not entry:
        return None
    return entry[1].get(sym)


async def get_cached_symbol_filters(
    symbol: str, testnet: bool = False, force_refresh: bool = False
) -> Optional[Dict[str, Any]]:
    """LOT_SIZE / PRICE_FILTER — kompakt RAM cache."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return None
    await _ensure_exchange_compact(testnet, force_refresh)
    key = _exchange_cache_key(testnet)
    entry = _exchange_compact_cache.get(key)
    if not entry:
        return None
    return entry[1].get(sym)


async def get_cached_trading_symbols(
    testnet: bool = False, force_refresh: bool = False
) -> List[str]:
    await _ensure_exchange_compact(testnet, force_refresh)
    key = _exchange_cache_key(testnet)
    entry = _exchange_compact_cache.get(key)
    if not entry:
        return []
    return list(entry[0])


async def fetch_exchange_info(testnet: bool = False, force_refresh: bool = False) -> Dict[str, Any]:
    """GET /api/v3/exchangeInfo — RAM'de yalnızca kompakt filtre indeksi tutulur."""
    await _ensure_exchange_compact(testnet, force_refresh)
    key = _exchange_cache_key(testnet)
    entry = _exchange_compact_cache.get(key)
    if not entry:
        return {"symbols": []}
    return _exchange_info_lightweight(entry[0])


async def ticker_price_all(testnet: bool = False) -> List[Dict]:
    """GET /api/v3/ticker/price (no symbol = all). Yalnızca data_hub ingest."""
    _assert_market_ingest_caller()
    from app.services.binance_rest_log import rest_source
    async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
        with rest_source("binance.ticker_price_all"):
            data = await _public_get(c, "/api/v3/ticker/price", None, testnet)
    return data if isinstance(data, list) else [data]


async def ticker_24h_all(testnet: bool = False, symbol: Optional[str] = None) -> Any:
    """GET /api/v3/ticker/24hr. Yalnızca data_hub ingest (+ tek sembol acil durum)."""
    _assert_market_ingest_caller(allow_single=bool(symbol))
    from app.services.binance_rest_log import rest_source
    params = {}
    src = "binance.ticker_24h_single" if symbol else "binance.ticker_24h_bulk"
    if symbol:
        params["symbol"] = symbol.upper()
    async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
        with rest_source(src):
            data = await _public_get(c, "/api/v3/ticker/24hr", params or None, testnet)
    return data


def _assert_market_ingest_caller(allow_single: bool = False) -> None:
    """Public ticker REST yalnızca data_hub (ingest) veya acil tek sembol."""
    import inspect
    for frame in inspect.stack()[2:8]:
        fn = (frame.filename or "").replace("\\", "/")
        if "/services/data_hub.py" in fn:
            return
        if allow_single and "/services/binance_spot.py" in fn:
            return
    raise RuntimeError(
        "Binance public ticker REST yalnızca data_hub ingest içindir. "
        "Okuma için app.services.market_data kullanın."
    )


def build_price_map_from_24h(ticker_24h_list: List[Dict]) -> Dict[str, float]:
    """
    Cüzdan değerlemesi: lastPrice (anlık piyasa) önce, yoksa weightedAvgPrice.
    Binance uygulaması bakiye değerini lastPrice ile gösterir; toplamın eşleşmesi için aynı kaynak kullanılır.
    ticker_24h_list: GET /api/v3/ticker/24hr cevabı (liste).
    Döner: symbol -> price (float).
    """
    out: Dict[str, float] = {}
    for r in (ticker_24h_list or []):
        sym = r.get("symbol")
        if not sym:
            continue
        try:
            last = r.get("lastPrice")
            wavg = r.get("weightedAvgPrice")
            p = None
            if last is not None and float(last) > 0:
                p = float(last)
            if p is None and wavg is not None and float(wavg) > 0:
                p = float(wavg)
            if p is not None and p > 0:
                out[sym] = p
        except (TypeError, ValueError):
            continue
    return out


async def place_order(keys: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/v3/order. Payload: symbol, side, type, quantity/quoteOrderQty, price, timeInForce, etc.
    Worker-only: web/API must never place orders; guard at deepest layer.
    """
    from app.core.config import is_worker_role
    from app.core.errors import AppError
    if not is_worker_role():
        raise AppError(
            "WORKER_ONLY_OPERATION",
            "Order placement is only allowed on worker process. Web/API cannot place orders.",
            status_code=403,
        )
    from app.core.config import is_worker_role
    logger.info(
        "BINANCE_PLACE_ORDER symbol=%s side=%s type=%s coid=%s worker_role=%s testnet=%s",
        payload.get("symbol"), payload.get("side"), payload.get("type"),
        payload.get("newClientOrderId", "")[:36] if payload.get("newClientOrderId") else "",
        is_worker_role(),
        getattr(keys, "testnet", None),
    )
    client = getattr(keys, "_client", None)
    return await _signed_request(client, "POST", "/api/v3/order", keys, payload)


async def get_trade_fee(keys: Any) -> List[Dict]:
    """GET /sapi/v1/asset/tradeFee - maker/taker per symbol."""
    client = getattr(keys, "_client", None)
    data = await _signed_request(client, "GET", "/sapi/v1/asset/tradeFee", keys, {})
    return data if isinstance(data, list) else (data.get("data") or [])


# ---------------------------------------------------------------------------
# Sync gateway (for bot engines that run in sync context)
# ---------------------------------------------------------------------------

def _sync_public_get(path: str, params: Optional[Dict[str, Any]] = None, testnet: bool = False) -> Any:
    """Sync public GET - single gateway, uses requests. Timeout 3s, max 4s total."""
    _guard_no_per_symbol_ticker_price(path, params)
    import requests
    base = _base_url(testnet)
    url = f"{base}{path}"
    params = params or {}
    t0 = time.perf_counter()
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=3)
            if r.status_code in (429, 418):
                if attempt < MAX_RETRIES:
                    time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
            r.raise_for_status()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug("binance_spot sync_public path=%s latency_ms=%.0f attempt=%s", path, elapsed_ms, attempt + 1)
            return r.json()
        except Exception as e:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
    return None


def _get_binance_timestamp_sync(testnet: bool, force_refresh: bool = False) -> int:
    """Binance server time (ms) for sync calls. Same cache/TTL as async path."""
    import requests
    if force_refresh:
        invalidate_binance_time_cache(testnet)
    if not force_refresh:
        fresh = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_CACHE_TTL)
        if fresh is not None:
            return fresh
    if is_ip_banned():
        stale = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_STALE_MAX_SEC)
        if stale is not None:
            return stale
        return int(time.time() * 1000)
    base = _base_url(testnet)
    last_exc: Optional[BaseException] = None
    for attempt in range(3):
        try:
            r = requests.get(f"{base}/api/v3/time", timeout=15)
            r.raise_for_status()
            data = r.json()
            server_ms = int(data.get("serverTime", 0) or (time.time() * 1000))
            _store_binance_time_cache(testnet, server_ms)
            try:
                from app.services.binance_rest_log import record_rest
                from app.services.binance_weight import record_weight_used
                record_rest("GET", "/api/v3/time", weight=1, status=r.status_code, outcome="ok")
                record_weight_used(None, None, 1)
            except Exception:
                pass
            return server_ms
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    stale = _read_binance_time_from_cache(testnet, max_age_sec=_BINANCE_TIME_STALE_MAX_SEC)
    if stale is not None:
        return stale
    _log_binance_time_unavailable(last_exc)
    return int(time.time() * 1000)


def _sync_signed_request(method: str, path: str, keys: Any, params: Optional[Dict[str, Any]] = None) -> Any:
    """Sync signed request. GET/DELETE: query string imza ile aynı sırada URL'e eklenir (params= yok)."""
    import requests
    base_params = dict(params or {})
    testnet = getattr(keys, "testnet", False)
    base = _base_url(testnet)
    url = f"{base}{path}"
    headers = {"X-MBX-APIKEY": keys.api_key}
    t0 = time.perf_counter()
    clock_retries = 0
    for attempt in range(MAX_RETRIES + 1):
        params = dict(base_params)
        params["timestamp"] = _get_binance_timestamp_sync(testnet, force_refresh=clock_retries > 0)
        params["recvWindow"] = 60000
        params_str = {k: str(v) for k, v in params.items()}
        query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))
        signature = _sign(keys.api_secret, query_for_sign)
        final_query = query_for_sign + "&signature=" + signature
        if method.upper() == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = final_query
            req_url = url
        else:
            req_url = f"{url}?{final_query}"
            body = None
        try:
            if method.upper() == "GET":
                r = requests.get(req_url, headers=headers, timeout=3)
            elif method.upper() == "DELETE":
                r = requests.delete(req_url, headers=headers, timeout=3)
            else:
                r = requests.post(req_url, headers=headers, data=body, timeout=3)
            if r.status_code in (429, 418):
                if attempt < MAX_RETRIES:
                    time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
            r.raise_for_status()
            data = r.json()
            code = data.get("code", 0) if isinstance(data, dict) else 0
            if code == -1021 and clock_retries < _MAX_CLOCK_RETRIES:
                clock_retries += 1
                invalidate_binance_time_cache(testnet)
                continue
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug("binance_spot sync_signed method=%s path=%s latency_ms=%.0f", method, path, elapsed_ms)
            return data
        except Exception as e:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
    return None
