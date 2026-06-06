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
_binance_time_cache_sync: Dict[bool, Tuple[int, float]] = {}
_BINANCE_TIME_CACHE_TTL = 30.0  # seconds


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
            try:
                from app.services.binance_weight import record_weight_used
                w = _path_weight(path, method)
                record_weight_used(None, getattr(keys, "api_key", None), w, elapsed_ms)
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
    base = _base_url(testnet)
    url = f"{base}{path}"
    params = params or {}
    last_exc = None
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES + 1):
        try:
            if client is None:
                async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
                    r = await c.get(url, params=params)
            else:
                r = await client.get(url, params=params)
            if r.status_code in (429, 418):
                last_exc = RuntimeError(f"Binance rate limit: {r.status_code}")
                if attempt < MAX_RETRIES:
                    await _asyncio_sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                    continue
                r.raise_for_status()
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code in (429, 418) and attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            raise
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                await _asyncio_sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue
            raise
    if last_exc:
        raise last_exc
    return {}


async def _asyncio_sleep(seconds: float):
    await asyncio.sleep(seconds)


def _sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


async def _get_binance_timestamp(client: Optional[httpx.AsyncClient], testnet: bool) -> int:
    """Binance server time (ms). Cached 30s to avoid -1021 (timestamp outside recvWindow)."""
    now_local = time.time()
    cached = _binance_time_cache.get(testnet)
    if cached:
        server_ms, local_ts = cached
        if now_local - local_ts < _BINANCE_TIME_CACHE_TTL:
            return int(server_ms + (now_local - local_ts) * 1000)
        # Cache expired but use extrapolation if drift is small (avoid wrong local clock)
        drift_s = now_local - local_ts
        if abs(drift_s) < 120:
            return int(server_ms + drift_s * 1000)
    base = _base_url(testnet)
    url = f"{base}/api/v3/time"
    for _ in range(2):
        try:
            if client is not None:
                r = await client.get(url)
            else:
                async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
                    r = await c.get(url)
            r.raise_for_status()
            data = r.json()
            server_ms = int(data.get("serverTime", 0) or (time.time() * 1000))
            _binance_time_cache[testnet] = (server_ms, time.time())
            return server_ms
        except Exception:
            await _asyncio_sleep(0.3)
    # Last resort: local time (401 if server clock wrong - user must sync time)
    local_ms = int(time.time() * 1000)
    logger.warning(
        "Binance server time unavailable; using local timestamp. If you get 401 Unauthorized, sync server clock (Windows: w32tm /resync or Settings > Time)."
    )
    return local_ms


def _path_weight(path: str, method: str) -> int:
    """Binance endpoint weight. Returns weight for request budget check."""
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
        return 1
    return 5


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
    try:
        from app.services.binance_weight import request_weight_tokens
        weight = _path_weight(path, method)
        allowed = await request_weight_tokens(None, getattr(keys, "api_key", None), weight)
        if not allowed:
            raise DependencyFailure("Binance weight limit exceeded - call denied")
    except DependencyFailure:
        raise
    except Exception:
        pass  # weight module optional
    if time.time() < _binance_ip_ban_state["until_ts"]:
        raise BinanceIPBannedError(_binance_ip_ban_state["until_ts"])
    params = dict(params or {})
    params["timestamp"] = await _get_binance_timestamp(client, getattr(keys, "testnet", False))
    params["recvWindow"] = 60000  # 60s tolerance (max allowed by Binance)
    params_str = {k: str(v) for k, v in params.items()}
    query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))
    signature = _sign(keys.api_secret, query_for_sign)
    final_query = query_for_sign + "&signature=" + signature
    base = _base_url(getattr(keys, "testnet", False))
    url = f"{base}{path}"
    headers = {"X-MBX-APIKEY": keys.api_key}
    logger.debug(
        "BINANCE_SIGN_DEBUG %s %s QUERY=%s",
        method.upper(), path, final_query.replace(signature, "***")
    )
    if method.upper() == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        request_kw = {"content": final_query}
    else:
        url_with_qs = f"{url}?{final_query}"
        request_kw = {"url": url_with_qs}
    last_exc = None
    backoff = INITIAL_BACKOFF
    http_method = method.upper()
    for attempt in range(MAX_RETRIES + 1):
        try:
            req_url = request_kw.get("url", url)
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
            # Binance bazen 200 OK ile {"code": -1022, "msg": "..."} gibi hata döner
            code = data.get("code", 0) if isinstance(data, dict) else 0
            if code not in (0, None):
                msg = data.get("msg", "Unknown error") if isinstance(data, dict) else "Unknown error"
                # -2015/-2008 (Invalid API-key/IP): DEBUG; diğerleri WARNING (sistem hatası)
                if code in (-2015, -2008):
                    logger.debug("BINANCE_SIGNED_ERROR path=%s status=200 code=%s msg=%s", path, code, msg)
                else:
                    logger.warning("BINANCE_SIGNED_ERROR path=%s status=200 code=%s msg=%s", path, code, msg)
                try:
                    if _should_log_binance_error((path, "200", code)):
                        from app.error_logging import log_error_fire_and_forget
                        ctx = {"path": path, "method": method, "code": code}
                        if code == -1021:
                            ctx["hint"] = "Sunucu saati ile Binance saati uyumsuz (recvWindow dışı). Uyku/uyanma, NTP veya sistem saati kayması olabilir."
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
            # 401 / 400(-2015, -2008) log flood: invalid key 5 dk içinde tekrar WARNING yazılmasın
            try:
                b = json.loads(body) if body else {}
                code = isinstance(b, dict) and b.get("code")
                msg = (isinstance(b, dict) and b.get("msg")) or ""
                is_invalid_key = (
                    sc == 401
                    or (sc == 400 and code in (-2015, -2008))  # -2008 = Invalid Api-Key ID
                )
                # -2013 "Order does not exist" => raise BinanceSignedError so reconcile treats as NOT_FOUND; avoid WARNING flood
                if sc == 400 and code == -2013:
                    raise BinanceSignedError(int(code), str(msg), b if isinstance(b, dict) else {})
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
                hint = "API anahtari, IP beyaz listesi veya sunucu saati (Binance ile uyumlu olmali). Windows: w32tm /resync"
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
            # 401/-2015 için error_logs'a yazma (zaten WARNING loglandı; tekrarlayan kayıt flood önlenir)
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
                        except Exception:
                            pass
                        log_error_fire_and_forget("binance", str(e), detail=traceback.format_exc(), context=ctx)
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
_ACCOUNT_CACHE_TTL = 30.0
_account_cache: Dict[tuple, tuple] = {}  # (testnet, api_key) -> (data, ts)
_account_inflight: Dict[tuple, asyncio.Task] = {}
_account_lock = asyncio.Lock()


async def _fetch_account_upstream(keys: Any) -> Dict[str, Any]:
    """Tek upstream çağrı – sadece cache miss veya TTL dolunca."""
    client = getattr(keys, "_client", None)
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
            task = asyncio.create_task(_fetch_account_upstream(keys))
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
    params = {}
    if symbol:
        params["symbol"] = symbol.upper()
    client = getattr(keys, "_client", None)
    data = await _signed_request(client, "GET", "/api/v3/openOrders", keys, params)
    return data if isinstance(data, list) else (data.get("orders") or data.get("data") or [])


async def get_all_orders(keys: Any, symbol: str, limit: int = 20) -> List[Dict]:
    """GET /api/v3/allOrders. Recent orders for reconciliation (bounded)."""
    params = {"symbol": symbol.upper(), "limit": min(limit, 100)}
    client = getattr(keys, "_client", None)
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


_exchange_info_cache: Dict[str, tuple] = {}  # key -> (data, ts)
EXCHANGE_INFO_TTL = 3600.0


async def fetch_exchange_info(testnet: bool = False, force_refresh: bool = False) -> Dict[str, Any]:
    """GET /api/v3/exchangeInfo. Cache 1 hour."""
    key = "testnet" if testnet else "live"
    now = time.time()
    if not force_refresh and key in _exchange_info_cache:
        data, ts = _exchange_info_cache[key]
        if now - ts < EXCHANGE_INFO_TTL:
            return data
    async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
        data = await _public_get(c, "/api/v3/exchangeInfo", None, testnet)
    _exchange_info_cache[key] = (data, now)
    return data


async def ticker_price_all(testnet: bool = False) -> List[Dict]:
    """GET /api/v3/ticker/price (no symbol = all)."""
    async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
        data = await _public_get(c, "/api/v3/ticker/price", None, testnet)
    return data if isinstance(data, list) else [data]


async def ticker_24h_all(testnet: bool = False, symbol: Optional[str] = None) -> Any:
    """GET /api/v3/ticker/24hr. If symbol given, single object else list."""
    params = {}
    if symbol:
        params["symbol"] = symbol.upper()
    async with httpx.AsyncClient(timeout=BINANCE_HTTP_TIMEOUT) as c:
        data = await _public_get(c, "/api/v3/ticker/24hr", params or None, testnet)
    return data


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


def _get_binance_timestamp_sync(testnet: bool) -> int:
    """Binance server time (ms) for sync calls. Cached 30s to avoid -1021."""
    import requests
    now_local = time.time()
    cached = _binance_time_cache_sync.get(testnet)
    if cached:
        server_ms, local_ts = cached
        if now_local - local_ts < _BINANCE_TIME_CACHE_TTL:
            return int(server_ms + (now_local - local_ts) * 1000)
    base = _base_url(testnet)
    try:
        r = requests.get(f"{base}/api/v3/time", timeout=2)
        r.raise_for_status()
        data = r.json()
        server_ms = int(data.get("serverTime", 0) or (time.time() * 1000))
        _binance_time_cache_sync[testnet] = (server_ms, time.time())
        return server_ms
    except Exception:
        return int(time.time() * 1000)


def _sync_signed_request(method: str, path: str, keys: Any, params: Optional[Dict[str, Any]] = None) -> Any:
    """Sync signed request. GET/DELETE: query string imza ile aynı sırada URL'e eklenir (params= yok)."""
    import requests
    params = dict(params or {})
    params["timestamp"] = _get_binance_timestamp_sync(getattr(keys, "testnet", False))
    params["recvWindow"] = 60000
    params_str = {k: str(v) for k, v in params.items()}
    query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))
    signature = _sign(keys.api_secret, query_for_sign)
    final_query = query_for_sign + "&signature=" + signature
    base = _base_url(getattr(keys, "testnet", False))
    url = f"{base}{path}"
    headers = {"X-MBX-APIKEY": keys.api_key}
    if method.upper() == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = final_query
    else:
        url = f"{url}?{final_query}"
        body = None
    t0 = time.perf_counter()
    for attempt in range(MAX_RETRIES + 1):
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=3)
            elif method.upper() == "DELETE":
                r = requests.delete(url, headers=headers, timeout=3)
            else:
                r = requests.post(url, headers=headers, data=body, timeout=3)
            if r.status_code in (429, 418):
                if attempt < MAX_RETRIES:
                    time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
            r.raise_for_status()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug("binance_spot sync_signed method=%s path=%s latency_ms=%.0f", method, path, elapsed_ms)
            return r.json()
        except Exception as e:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
    return None
