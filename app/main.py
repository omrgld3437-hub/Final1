"""
FILE: main.py
VERSION: v6
DATE: 2026-01-21
CHANGE: Add Python logging configuration - console + file logging with rotation
"""

"""
FastAPI Main Entry Point
"""
# urllib3/LibreSSL uyarisini en basta bastir (sonraki importlar urllib3 yukleyebilir)
import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Query, Depends, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import traceback
import os
import sys
import logging
import asyncio
import time
import uuid
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
BASE_DIR = Path(__file__).resolve().parents[1]  # Project root
LOGS_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / ".run"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)

# Root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Türkiye saati (Europe/Istanbul) tüm loglarda
from app.utils.tz_utils import TurkeyTimeFormatter

# Console handler: terminalde sadece hata/uyarı; log dosyasına yönlendirildiğinde (web.log) tam log
console_handler = logging.StreamHandler()
console_handler.setLevel(
    logging.WARNING if getattr(sys.stdout, "isatty", lambda: False)() else logging.INFO
)
console_formatter = TurkeyTimeFormatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# File handler (rotating)
file_handler = RotatingFileHandler(
    LOGS_DIR / "app.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
)
file_handler.setLevel(logging.INFO)
file_formatter = TurkeyTimeFormatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Az log gürültüsü: httpx/httpcore her isteği INFO ile yazmasın (login/dashboard konsolu sade kalsın)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class LocalLogsPageFilter(logging.Filter):
    """Logs sayfası ve /api/local/logs isteklerini terminale yazdırma (ayıklama HTML'de yapılıyor)."""

    def filter(self, record):
        msg = record.getMessage() or ""
        if "/api/local/logs" in msg or "logs.html" in msg:
            return False
        return True


class WebSocketCloseFilter(logging.Filter):
    """WebSocket normal kapanma ve bağlantı kesintisi ERROR loglarını bastır (1000/1001/1012, IncompleteRead, Cancelled)."""

    _SUPPRESS_NAMES = frozenset(
        {
            "ConnectionClosedOK",
            "ConnectionClosedError",
            "CancelledError",
            "IncompleteReadError",
            "ConnectionClosed",
        }
    )

    def filter(self, record):
        if record.levelno < logging.ERROR:
            return True
        msg = (record.getMessage() or "") + (str(record.exc_text or ""))
        exc = None
        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
        # Exception chain (cause, context)
        exc_chain = []
        e = exc
        while e:
            exc_chain.append(type(e).__name__)
            e = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
        if exc:
            exc_name = type(exc).__name__
            if exc_name == "ConnectionClosedOK":
                return False
            if exc_name == "ConnectionClosedError":
                code = getattr(exc, "code", None)
                if code in (1000, 1001, 1006, 1012, None):
                    return False
            if exc_name in ("CancelledError", "IncompleteReadError"):
                return False
            if self._SUPPRESS_NAMES & set(exc_chain):
                return False
        if any(
            k in msg
            for k in (
                "ConnectionClosedOK",
                "ConnectionClosedError",
                "ConnectionClosed",
                "no close frame",
                "sent 1012",
                "service restart",
                "IncompleteReadError",
                "0 bytes read",
                "CancelledError",
            )
        ):
            return False
        if "ASGI application" in msg and (
            "websocket" in msg.lower()
            or "ConnectionClosed" in msg
            or "IncompleteRead" in msg
            or "CancelledError" in msg
        ):
            return False
        return True


class AsyncioTransientErrorFilter(logging.Filter):
    """DNS/ağ geçici asyncio gürültüsünü err-web panelinden düşür (Future exception was never retrieved)."""

    _SUPPRESS_FRAGMENTS = (
        "Future exception was never retrieved",
        "Task exception was never retrieved",
        "Exception in callback",
        "nodename nor servname",
        "gaierror",
        "ConnectError",
        "ConnectTimeout",
        "ConnectionResetError",
        "forcibly closed",
        "_call_connection_lost",
        "_ProactorBasePipeTransport",
    )

    def filter(self, record):
        msg = (record.getMessage() or "") + (str(record.exc_text or ""))
        if record.exc_info and record.exc_info[1]:
            en = type(record.exc_info[1]).__name__
            if en in (
                "gaierror",
                "ConnectionResetError",
                "ConnectError",
                "ConnectTimeout",
            ):
                return False
        if any(frag in msg for frag in self._SUPPRESS_FRAGMENTS):
            return False
        return True


logging.getLogger("uvicorn.access").addFilter(LocalLogsPageFilter())
logging.getLogger("uvicorn.error").addFilter(WebSocketCloseFilter())
logging.getLogger("uvicorn").addFilter(WebSocketCloseFilter())
logger.addFilter(WebSocketCloseFilter())
_asyncio_noise_filter = AsyncioTransientErrorFilter()
logging.getLogger("asyncio").addFilter(_asyncio_noise_filter)
if getattr(sys.stdout, "isatty", lambda: False)():
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Bot engine logger
bot_logger = logging.getLogger("app.bot")
bot_logger.setLevel(logging.INFO)

# Bot engine: terminalde sadece WARNING+ (log dosyasına yönlendirildiğinde INFO+)
botengine_logger = logging.getLogger("app.botengine")
botengine_logger.setLevel(logging.DEBUG)
botengine_logger.propagate = False
botengine_console = logging.StreamHandler()
botengine_console.setLevel(
    logging.WARNING if getattr(sys.stdout, "isatty", lambda: False)() else logging.INFO
)
botengine_console.setFormatter(console_formatter)
botengine_logger.addHandler(botengine_console)

logger.info("Logging configured - console + file: logs/app.log")

from app.api import routes, ws, admin, bots_v2, finance, spot_routes, auth, bots_engine
from app.api import data_hub_routes, finance_reports, pricing_routes
from app import server_state as server_state

try:
    from app.api import market_data_routes
except ImportError:
    market_data_routes = None
from app.services.data_hub import data_hub

app = FastAPI(title="TraderTrailing", version="1.0.0")


@app.get("/api/debug/build-info")
async def debug_build_info():
    """Deploy teşhisi: sunucunun okuduğu UI dizini ve dashboard sürümü. Giriş gerekmez; ilk sırada kayıtlı."""
    import re

    ui_dir_path = BASE_DIR / "ui"
    dashboard_path = ui_dir_path / "dashboard.html"
    dashboard_version = None
    if dashboard_path.exists():
        try:
            raw = dashboard_path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"VERSION:\s*(\S+)", raw)
            if m:
                dashboard_version = m.group(1).strip()
        except Exception:
            pass
    return {
        "base_dir": str(BASE_DIR),
        "ui_dir": str(ui_dir_path),
        "dashboard_html_version": dashboard_version,
        "dashboard_exists": dashboard_path.exists(),
    }


# GZip compression for API responses (Accept-Encoding: gzip)
try:
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1024)
except Exception:
    pass


# Startup: Start data hub background service
@app.on_event("startup")
async def startup_event():
    """Start background services on startup. Sync DB işlemleri thread'de çalıştırılarak açılış hızlandırılır."""
    logger.info("Starting background services...")

    loop = asyncio.get_running_loop()

    # Her açılışta yeni boot_id → sunucu kapandığında tüm oturumlar iptal
    from app import boot_id as _bid

    _bid.set_boot_id()
    logger.info("Boot ID set (server restart = all sessions invalidated)")

    # Schema guard: sync DB I/O event loop'u bloke etmesin diye thread'de çalıştır
    try:
        from app.db.base import engine, DATABASE_URL
        from app.db.schema_guard import run_schema_guard

        await loop.run_in_executor(None, lambda: run_schema_guard(engine))
        logger.info("Schema guard completed (devices columns check)")
        if "sqlite" in DATABASE_URL:
            db_path = DATABASE_URL.replace("sqlite:///", "").split("?")[0]
            logger.info("Veritabani: %s (guncellemede korunur)", db_path)
    except Exception as e:
        logger.warning("Schema guard skipped or failed: %s", e)

    # Audit SERVER_START: sunucu hazır olsun diye beklemeden arka planda yaz
    async def _audit_server_start():
        try:
            from app.db.session import SessionLocal
            from app.services import audit as audit_svc
            from app.boot_id import get_boot_id

            def _sync():
                _db = SessionLocal()
                try:
                    audit_svc.log_event(
                        _db,
                        actor_type="system",
                        event_type="SERVER_START",
                        severity="INFO",
                        meta={"version": "1.0.0", "boot_id": get_boot_id()},
                    )
                finally:
                    _db.close()

            await loop.run_in_executor(None, _sync)
        except Exception as e:
            logger.warning("audit SERVER_START failed: %s", e)

    asyncio.create_task(_audit_server_start())

    # Yerel test hesabı (test / 123) — yoksa oluştur; sadece localhost'tan giriş (girişten önce hazır olsun diye beklenir)
    async def _ensure_test_account():
        try:
            from app.db.session import SessionLocal
            from app.services.test_account import ensure_test_account

            def _sync():
                _db = SessionLocal()
                try:
                    ensure_test_account(_db)
                finally:
                    _db.close()

            await loop.run_in_executor(None, _sync)
        except Exception as e:
            logger.warning("ensure_test_account failed: %s", e)

    await _ensure_test_account()

    # İlk admin yoksa otomatik oluştur (varsayılan şifre yok; ilk girişte yazılan şifre kalıcı olur)
    async def _ensure_first_admin():
        try:
            from app.db.session import SessionLocal
            from app.db.models import User, Account
            from app.api.auth import get_initial_admin_unset_hash
            from app.utils.account_code import generate_account_code
            from app.services.encryption import encrypt_text

            _USERNAME = "Admin"

            def _sync():
                _db = SessionLocal()
                try:
                    admin = _db.query(User).filter(User.is_admin == True).first()
                    if admin:
                        admin.username = _USERNAME
                        admin.failed_login_attempts = 0
                        _db.commit()
                        logger.info(
                            "First-admin: Admin zaten var (kullanici adi: %s)",
                            _USERNAME,
                        )
                        return
                    account = Account(
                        account_code=generate_account_code(_db),
                        name="Admin",
                        exchange="BINANCE",
                        api_key_enc=encrypt_text(""),
                        api_secret_enc=encrypt_text(""),
                        mode="live",
                        is_first_login=False,
                    )
                    _db.add(account)
                    _db.flush()
                    _db.refresh(account)
                    user = User(
                        username=_USERNAME,
                        password_hash=get_initial_admin_unset_hash(),
                        name="Admin",
                        surname="",
                        phone=None,
                        is_admin=True,
                        is_approved=True,
                        is_suspended=False,
                        must_change_password=False,
                        account_id=account.id,
                    )
                    _db.add(user)
                    _db.flush()
                    _db.refresh(user)
                    account.user_id = user.id
                    _db.commit()
                    logger.info(
                        "First-admin: Ilk admin olusturuldu (Admin). Ilk girisinde yazacagi sifre kalici olacak."
                    )
                finally:
                    _db.close()

            await loop.run_in_executor(None, _sync)
        except Exception as e:
            logger.warning("ensure_first_admin failed: %s", e)

    await _ensure_first_admin()

    # Start data hub background updates (REST: price 1–2s, 24h 60s) — tek worker leader
    from app.services.data_hub import try_acquire_datahub_rest_leader

    rest_leader = try_acquire_datahub_rest_leader()
    if rest_leader and not data_hub._running:
        data_hub._running = True
        loop = asyncio.get_running_loop()
        data_hub._background_task = loop.create_task(data_hub._background_update_loop())
        logger.info(
            "[DataHub] Background update service started (REST leader pid=%s)",
            os.getpid(),
        )
    elif not rest_leader:
        logger.info(
            "[DataHub] REST loop skipped — another worker is REST leader (pid=%s)",
            os.getpid(),
        )
    # Warmup: one price fetch so first snapshot request gets data (up to 5s)
    try:
        warmup_timeout = float(os.environ.get("DATAHUB_WARMUP_TIMEOUT_SEC", "5.0"))
        await asyncio.wait_for(
            data_hub.warmup(warmup_timeout), timeout=warmup_timeout + 1.0
        )
    except Exception as e:
        logger.debug("[DataHub] Warmup skipped or failed: %s", e)
    # WebSocket combined stream (fallback: REST remains active)
    data_hub.start_ws(testnet=False)
    try:
        from app.services.server_public_ip import start_server_public_ip_refresh

        start_server_public_ip_refresh()
    except Exception as e:
        logger.debug("server_public_ip refresh start skipped: %s", e)
    try:
        from app.services.binance_rest_log import start_rest_log_flush_task

        start_rest_log_flush_task()
    except Exception as e:
        logger.debug("REST log flush start skipped: %s", e)

    # Bot engine: worker ayrı proses (start.command ile worker_main.py). Web task yaratmaz.

    # RAM probe / 5dk capture (RAM_CAPTURE=1 → logs/ram_capture_*_{web}.jsonl)
    try:
        if os.getenv("RAM_CAPTURE", "").strip() == "1":
            os.environ.setdefault("RAM_PROBE", "1")
            os.environ.setdefault("RAM_PROBE_ENABLED", "1")
            from app.observability.ram_capture import (
                register_default_capture_hooks,
                start_ram_capture_session,
            )

            register_default_capture_hooks("web")
            start_ram_capture_session("web")
        else:
            from app.observability.ram_probe import start_ram_probe

            if (
                os.getenv("RAM_PROBE", "").strip() == "1"
                or os.getenv("RAM_PROBE_ENABLED", "").strip() == "1"
            ):
                interval = int(os.getenv("RAM_PROBE_INTERVAL", "30"))
                start_ram_probe(component="web", interval_sec=interval)
    except Exception as e:
        logger.debug("RAM probe/capture start skipped: %s", e)

    # Grafik: tarayıcı kapalıyken de çalışan botlar için periyodik örnek (sekme arka planda grafik durmasın)
    async def _perf_chart_sample_loop():
        from app.db.session import SessionLocal
        from app.db.models import Bot
        from app.api.bots_engine import append_perf_chart_sample

        interval = 60
        while True:
            await asyncio.sleep(interval)
            try:

                def _sync():
                    _db = SessionLocal()
                    try:
                        bots = _db.query(Bot).filter(Bot.status == "running").all()
                        for b in bots:
                            try:
                                append_perf_chart_sample(_db, b.id)
                            except Exception:
                                pass
                    finally:
                        _db.close()

                await loop.run_in_executor(None, _sync)
            except Exception as e:
                logger.debug("perf_chart_sample_loop: %s", e)

    asyncio.create_task(_perf_chart_sample_loop())

    # error_logs temizleme: 30 günden eski kayıtları günde bir kez sil
    async def _error_logs_cleanup_loop():
        from app.db.schema_guard import cleanup_old_error_logs
        from app.db.base import engine as _engine

        while True:
            await asyncio.sleep(24 * 3600)
            try:

                def _sync():
                    cleanup_old_error_logs(_engine, retain_days=30)

                await loop.run_in_executor(None, _sync)
            except Exception as e:
                logger.debug("error_logs_cleanup_loop: %s", e)

    asyncio.create_task(_error_logs_cleanup_loop())

    # Leaderboard refresh: bot_public_metrics every 60s (DB/PnlService only, no Binance). Single-run lock for multi-worker.
    async def _leaderboard_refresh_loop():
        from app.db.session import SessionLocal
        from app.services.leaderboard_service import refresh_bot_public_metrics

        interval = 60
        lock_path = RUN_DIR / "leaderboard_refresh.lock"
        lock_timeout = 55  # max hold so another worker can take over
        while True:
            await asyncio.sleep(interval)
            try:
                if lock_path.exists():
                    try:
                        mtime = lock_path.stat().st_mtime
                        if time.time() - mtime > lock_timeout:
                            lock_path.unlink()
                    except Exception:
                        pass
                if lock_path.exists():
                    continue
                try:
                    lock_path.write_text(str(os.getpid()), encoding="utf-8")
                except Exception:
                    continue
                try:

                    def _sync():
                        _db = SessionLocal()
                        try:
                            refresh_bot_public_metrics(_db)
                        finally:
                            _db.close()

                    await loop.run_in_executor(None, _sync)
                finally:
                    try:
                        if lock_path.exists():
                            lock_path.unlink()
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("LEADERBOARD_REFRESH_FAIL error_code=%s", str(e)[:100])

    asyncio.create_task(_leaderboard_refresh_loop())

    # Manager v3: write web metrics to .run/web.metrics.json every 2s (atomic)
    if RequestMetrics is not None:

        async def _web_metrics_writer_loop():
            import json as _json

            while True:
                await asyncio.sleep(2)
                try:
                    snap = RequestMetrics.snapshot_web_metrics()
                    snap["pid"] = os.getpid()
                    p = RUN_DIR / "web.metrics.json"
                    tmp = RUN_DIR / "web.metrics.json.tmp"
                    tmp.write_text(
                        _json.dumps(snap, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    tmp.replace(p)
                except Exception as e:
                    logger.debug("web_metrics_writer: %s", e)

        asyncio.create_task(_web_metrics_writer_loop())

    logger.info("Background services started")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop background services on shutdown"""
    logger.info("Stopping background services...")

    # Stop data hub (includes WS)
    data_hub.stop_background_updates()
    logger.info("Background services stopped")


# No-cache for UI and build-info: her commit sonrası değişiklik anında yansısın (tarayıcı/proxy önbelleği yok)
@app.middleware("http")
async def no_cache_ui_middleware(request, call_next):
    response = await call_next(request)
    path = (request.url.path or "").rstrip("/")
    if path.startswith("/ui/") or path == "/api/debug/build-info":
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# RAM capture: /api istekleri (RAM_CAPTURE=1, 5 dk oturum)
@app.middleware("http")
async def ram_capture_api_middleware(request, call_next):
    try:
        from app.observability.ram_capture import (
            is_capture_enabled,
            log_ram_event,
            _quick_rss_mb,
        )
    except ImportError:
        return await call_next(request)
    if not is_capture_enabled():
        return await call_next(request)
    path = request.url.path or ""
    if not path.startswith("/api/"):
        return await call_next(request)
    method = getattr(request, "method", "GET") or "GET"
    rss0 = _quick_rss_mb()
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    rss1 = _quick_rss_mb()
    resp_bytes = None
    try:
        cl = response.headers.get("content-length")
        if cl is not None:
            resp_bytes = int(cl)
    except (TypeError, ValueError):
        pass
    log_all = os.getenv("RAM_CAPTURE_HTTP_ALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    heavy = (
        log_all
        or duration_ms >= 80
        or (resp_bytes is not None and resp_bytes >= 8192)
        or path.startswith("/api/dashboard")
        or path.startswith("/api/bots")
        or path.startswith("/api/finance")
        or path.startswith("/api/data")
    )
    if heavy:
        log_ram_event(
            "http_request",
            {
                "method": method,
                "path": path,
                "status": getattr(response, "status_code", None),
                "duration_ms": duration_ms,
                "response_bytes": resp_bytes,
                "rss_mb": rss1,
                "rss_delta_mb": round(rss1 - rss0, 3)
                if rss0 is not None and rss1 is not None
                else None,
            },
            component="web",
        )
    return response


# Request ID: X-Request-ID propagated client->server->logs->errors (correlation ID)
@app.middleware("http")
async def request_id_middleware(request, call_next):
    rid = (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Request-Id")
        or str(uuid.uuid4())
    )
    request.state.request_id = rid
    server_state.increment_request_count()
    try:
        response = await call_next(request)
    except RuntimeError as e:
        if "No response returned" in str(e):
            r = JSONResponse(status_code=499, content={"detail": "client_disconnect"})
            r.headers["X-Request-ID"] = rid
            return r
        raise
    response.headers["X-Request-ID"] = rid
    return response


# Security headers, CSRF, request metrics (optional: sunucuda modül yoksa atla, uygulama yine çalışsın)
try:
    from app.middleware.security_headers import security_headers_middleware

    @app.middleware("http")
    async def _security_headers(request, call_next):
        return await security_headers_middleware(request, call_next)

    from app.middleware.csrf import csrf_middleware

    @app.middleware("http")
    async def _csrf(request, call_next):
        return await csrf_middleware(request, call_next)

    from app.middleware.request_metrics import RequestMetrics
except ImportError as _e:
    logger.warning("Middleware import skipped (app.middleware missing?): %s", _e)
    RequestMetrics = None

# 200 OK access log UI'da gösterilmez; bu eşiği aşan 200 istekler WARN (SLOW_REQUEST) olarak loglanır
SLOW_REQUEST_MS = int(os.environ.get("SLOW_REQUEST_MS", "4000"))
# Ağır path'ler (DB/API yoğun) için daha yüksek eşik; yoksa varsayılan SLOW_REQUEST_MS kullanılır
SLOW_REQUEST_MS_HEAVY_PATHS = {
    "/api/finance/trades": 15000,
    "/api/admin/accounts": 12000,
    "/api/dashboard/snapshot": 10000,
}
# Aynı path için SLOW_REQUEST en fazla 2 dakikada bir loglanır (log patlaması önlenir)
_slow_request_log_ts = {}
_slow_request_lock = asyncio.Lock()
SLOW_REQUEST_LOG_THROTTLE_SEC = 120.0


@app.middleware("http")
async def request_metrics_middleware(request, call_next):
    start = time.perf_counter()
    path = request.url.path or ""
    method = getattr(request, "method", "GET") or "GET"
    client_ip = ""
    if request.client:
        client_ip = request.client.host or ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip() or client_ip
    user_agent = request.headers.get("user-agent") or ""

    if client_ip:
        try:
            from app.services.ip_blocklist import is_ip_blocked

            if is_ip_blocked(client_ip):
                return JSONResponse(
                    status_code=403, content={"detail": "IP engellendi."}
                )
        except Exception:
            pass

    try:
        response = await call_next(request)
    except RuntimeError as e:
        if "No response returned" not in str(e):
            raise
        # İstemci bağlantıyı kesti (refresh, sekme kapatma, navigate away) → Starlette "No response returned".
        # 499 dön, 500 kascade ve binlerce error log / istek patlamasını kes.
        duration_ms = (time.perf_counter() - start) * 1000
        if RequestMetrics:
            RequestMetrics.record(method, path, 499, duration_ms, client_ip, user_agent)
        return JSONResponse(status_code=499, content={"detail": "client_disconnect"})

    duration_ms = (time.perf_counter() - start) * 1000
    status = getattr(response, "status_code", 200)
    if RequestMetrics:
        RequestMetrics.record(method, path, status, duration_ms, client_ip, user_agent)

    # 200 OK ama yavaş istek → WARN (aynı path için en fazla 2 dk'da bir)
    slow_threshold_ms = SLOW_REQUEST_MS_HEAVY_PATHS.get(path, SLOW_REQUEST_MS)
    do_log_slow = False
    if status == 200 and duration_ms > slow_threshold_ms:
        now_ts = time.time()
        async with _slow_request_lock:
            last = _slow_request_log_ts.get(path)
            if last is None or (now_ts - last) >= SLOW_REQUEST_LOG_THROTTLE_SEC:
                _slow_request_log_ts[path] = now_ts
                do_log_slow = True
                if len(_slow_request_log_ts) > 200:
                    cutoff = now_ts - SLOW_REQUEST_LOG_THROTTLE_SEC * 2
                    for k in [p for p, t in _slow_request_log_ts.items() if t < cutoff]:
                        del _slow_request_log_ts[k]
        if do_log_slow:
            request_id = getattr(request.state, "request_id", None)
            query_hint = ""
            if path == "/api/admin/accounts":
                qs = str(getattr(getattr(request, "url", None), "query", "") or "")
                if qs:
                    query_hint = " query=" + qs[:120]
            logger.warning(
                "SLOW_REQUEST method=%s path=%s status=200 duration_ms=%.0f request_id=%s ip=%s%s",
                method,
                path,
                duration_ms,
                request_id,
                client_ip,
                query_hint,
            )

    # 404 (route bulunamadı) ve 5xx yanıtlarını error_logs'a yaz; 499 yazma (istemci kesintisi)
    if status == 404 or status >= 500:
        user_id, account_id, is_admin = None, None, False
        try:
            auth = (
                request.headers.get("Authorization")
                or request.headers.get("authorization")
                or ""
            )
            token = auth[7:].strip() if auth.startswith("Bearer ") else None
            if token:
                from app.api.auth import _session_get

                session = _session_get(token)
                if session:
                    user_id = session.get("user_id")
                    account_id = session.get("account_id")
                    is_admin = session.get("is_admin", False)
        except Exception:
            pass
        request_id = getattr(request.state, "request_id", None)
        try:
            from app.db.session import SessionLocal
            from app.error_logging import persist_error

            db = SessionLocal()
            try:
                persist_error(
                    db,
                    "backend",
                    f"HTTP {status} – {method} {path}",
                    detail=f"Yanıt kodu: {status}. Route bulunamadı veya sunucu hatası.",
                    path=path,
                    method=method,
                    request_id=request_id,
                    user_id=user_id,
                    account_id=account_id,
                    user_agent=(user_agent or "")[:512],
                    client_ip=client_ip or None,
                    context={"status_code": status, "durum": "response_after_route"},
                    is_admin=is_admin,
                    level="error" if status >= 500 else "warning",
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning("error_log middleware persist failed: %s", e)

    # Breach detection: sadece 2xx yanıtında tetiklenir; yetkisiz erişim başarılı olmuş gibi görünürse uyarı + isteğe bağlı kapatma/hesap askıya alma
    if 200 <= status < 300:
        try:
            from app.api.auth import _session_get
            from app.db.session import SessionLocal

            auth = (
                request.headers.get("Authorization")
                or request.headers.get("authorization")
                or ""
            )
            token = (
                auth[7:].strip() if auth.startswith("Bearer ") else None
            ) or request.cookies.get("auth_token")
            session = None
            if token:
                _db = SessionLocal()
                try:
                    session = _session_get(token, _db)
                finally:
                    _db.close()
            path = request.url.path
            method = getattr(request, "method", "GET") or "GET"

            # Admin: 2xx döndü ama oturum admin değil veya yok
            if path.startswith("/api/admin") or (
                path == "/ui/admin.html" and method == "GET"
            ):
                if not token or not session or not session.get("is_admin"):
                    server_state.add_breach_event(
                        "admin_accessed_without_auth",
                        path,
                        method,
                        client_ip,
                        "Admin alanına yetkisiz erişim tespit edildi (2xx yanıt).",
                        session_user_id=session.get("user_id") if session else None,
                        session_account_id=session.get("account_id")
                        if session
                        else None,
                    )
                    logger.critical(
                        "BREACH: Admin alanına yetkisiz erişim path=%s method=%s ip=%s token=%s",
                        path,
                        method,
                        client_ip,
                        "var" if token else "yok",
                    )
                    if os.environ.get("BREACH_SHUTDOWN") == "1":

                        def _shutdown():
                            import time

                            time.sleep(0.5)
                            os._exit(1)

                        import threading

                        threading.Thread(target=_shutdown, daemon=True).start()

            # Hesap kapsamlı API: 2xx döndü ama oturum bu hesaba ait değil ve admin değil
            requested_account_id = None
            if path.startswith("/api/accounts/") and len(path.split("/")) >= 4:
                try:
                    parts = path.rstrip("/").split("/")
                    idx = next((i for i, p in enumerate(parts) if p == "accounts"), -1)
                    if idx >= 0 and idx + 1 < len(parts) and parts[idx + 1].isdigit():
                        requested_account_id = int(parts[idx + 1])
                except (ValueError, StopIteration):
                    pass
            if requested_account_id is None and request.scope.get("query_string"):
                q = request.scope.get("query_string", b"").decode(
                    "utf-8", errors="ignore"
                )
                for part in q.split("&"):
                    if part.startswith("account_id="):
                        try:
                            requested_account_id = int(part.split("=", 1)[1].strip())
                        except (ValueError, IndexError):
                            pass
                        break
            # Hesap breach: sadece hesap kapsamlı path'lerde (yanlış tetikleme önlenir)
            account_scoped_prefixes = (
                "/api/accounts/",
                "/api/dashboard/summary",
                "/api/bots-engine",
                "/api/bots/",
                "/api/finance/",
            )
            is_account_scoped = any(path.startswith(p) for p in account_scoped_prefixes)
            if (
                is_account_scoped
                and requested_account_id is not None
                and session
                and not session.get("is_admin")
            ):
                sid = session.get("account_id")
                if sid is not None and int(sid) != int(requested_account_id):
                    server_state.add_breach_event(
                        "account_accessed_unauthorized",
                        path,
                        method,
                        client_ip,
                        "Başka hesaba yetkisiz erişim tespit edildi (2xx yanıt). Hesap askıya alındı.",
                        session_user_id=session.get("user_id"),
                        session_account_id=sid,
                        requested_account_id=requested_account_id,
                    )
                    logger.critical(
                        "BREACH: Yetkisiz hesap erişimi path=%s account=%s session_account=%s user_id=%s ip=%s",
                        path,
                        requested_account_id,
                        sid,
                        session.get("user_id"),
                        client_ip,
                    )
                    try:
                        from app.db.session import SessionLocal
                        from app.db.models import User

                        db = SessionLocal()
                        try:
                            uid = session.get("user_id")
                            if uid:
                                u = db.query(User).filter(User.id == uid).first()
                                if u and not getattr(u, "is_admin", False):
                                    u.is_suspended = True
                                    db.commit()
                                    logger.warning(
                                        "BREACH: user_id=%s askıya alındı.", uid
                                    )
                        finally:
                            db.close()
                    except Exception as e:
                        logger.exception("BREACH: Hesap askıya alma hatası: %s", e)
        except Exception as e:
            logger.warning("breach_detection failed: %s", e)

    return response


# Lockdown: sadece giriş sayfası (admin girişi için) + admin sayfası ve ilgili API'ler erişilebilir
def _lockdown_whitelist(path: str) -> bool:
    p = (path or "").rstrip("/")
    # Ana sayfa ve giriş sayfası – admin giriş yapabilsin
    if p in ("/", "/ui/login.html"):
        return True
    # Admin paneli ve hesap görüntüleme (admin “hesaba gir” ile dashboard açılır)
    if p in ("/ui/admin.html", "/ui/dashboard.html"):
        return True
    # Giriş sayfası ve admin için statik dosyalar + js (maintenanceOverlay) + vendor (Lightweight Charts vb.)
    if p.startswith("/ui/assets/") or p.startswith("/ui/vendor/"):
        return True
    # Oturum doğrulama (boot_id) ve bakım ekranı retry (health)
    if p in ("/api/boot-id", "/api/health"):
        return True
    # Deploy teşhisi: sunucunun okuduğu ui dizini ve dashboard sürümü (giriş gerekmez; trailing slash kabul)
    if p == "/api/debug/build-info":
        return True
    # Giriş, çıkış, token doğrulama – admin girişi için gerekli
    if p.startswith("/api/auth/"):
        return True
    # Hata raporlama (frontend her durumda gönderebilsin)
    if p == "/api/log-error":
        return True
    # Admin API'leri whitelist'te DEĞİL: lockdown'da sadece Bearer + admin session ile erişilebilir (bypass önlenir)
    return False


@app.middleware("http")
async def lockdown_middleware(request, call_next):
    if not server_state.get_lockdown():
        return await call_next(request)
    if _lockdown_whitelist(request.url.path):
        return await call_next(request)
    # Path whitelist’te değil; isteği sadece oturumu geçerli admin yapabilir (admin panelinden hesaba gir vb.)
    auth_header = (
        request.headers.get("authorization")
        or request.headers.get("Authorization")
        or ""
    )
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from app.api.auth import _session_get

            session = _session_get(token)
            if session and session.get("is_admin"):
                return await call_next(request)
        except Exception:
            pass
    logger.warning(
        "Lockdown: blocking path (whitelist'te yok) path=%s", request.url.path
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=503,
        content={
            "detail": "Sunucu erişime kapalı. Sadece yönetici erişebilir.",
            "login_url": "/ui/login.html",
        },
        headers={"Retry-After": "60"},
    )


# CORS: production'da explicit ALLOWED_ORIGINS zorunlu; wildcard kullanilmaz.
from app.core.config import get_cors_config

_cors_cfg = get_cors_config()
_cors_origins = _cors_cfg["allow_origins"]
if not _cors_origins and _cors_cfg["is_production"]:
    suggested = (
        ",".join(_cors_cfg.get("suggested_origins") or [])
        or "https://tradertrailing.com,https://www.tradertrailing.com"
    )
    raise RuntimeError(
        f"Production CORS requires ALLOWED_ORIGINS. Suggested: {suggested}"
    )
if _cors_cfg.get("invalid_origins"):
    logger.warning(
        "CORS: invalid ALLOWED_ORIGINS ignored: %s", _cors_cfg["invalid_origins"]
    )
if not os.environ.get("ALLOWED_ORIGINS", "").strip() and not _cors_cfg["is_production"]:
    logger.warning(
        "CORS: ALLOWED_ORIGINS empty; development localhost origins enabled. Suggested production origins: %s",
        ",".join(_cors_cfg.get("suggested_origins") or []) or "-",
    )
logger.info(
    "CORS origins configured env=%s origins=%s", _cors_cfg["environment"], _cors_origins
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_cfg["allow_credentials"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-CSRF-Token"],
    expose_headers=["X-Request-ID"],
)


class _WebSocketCloseSuppressMiddleware:
    """WebSocket normal kapanmalarini (1000/1001) ERROR olarak loglamayi engeller."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":

            async def wrapped_send(msg):
                try:
                    await send(msg)
                except Exception as e:
                    try:
                        from websockets.exceptions import (
                            ConnectionClosedOK,
                            ConnectionClosedError,
                        )

                        if isinstance(e, (ConnectionClosedOK, ConnectionClosedError)):
                            code = getattr(e, "code", 1000)
                            if code in (1000, 1001, 1006, 1012) or code is None:
                                return
                    except ImportError:
                        pass
                    raise

            send = wrapped_send
        try:
            await self._app(scope, receive, send)
        except Exception as exc:
            try:
                from websockets.exceptions import (
                    ConnectionClosedOK,
                    ConnectionClosedError,
                )

                if isinstance(exc, (ConnectionClosedOK, ConnectionClosedError)):
                    code = getattr(exc, "code", 1000)
                    if (
                        code in (1000, 1001, 1006, 1012) or code is None
                    ):  # normal / going away / abnormal / restart
                        logger.debug("WebSocket close code=%s", code)
                        return
            except ImportError:
                pass
            raise


app.add_middleware(_WebSocketCloseSuppressMiddleware)


try:
    from app.core.errors import AppError

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        """AppError: standardized error body with error_code, error_id, request_id."""
        request_id = getattr(request.state, "request_id", None)
        body = exc.to_dict()
        if body.get("error") and request_id and not body["error"].get("request_id"):
            body["error"]["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=body)
except ImportError:
    pass


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Yakalanmayan tüm hataları error_logs'a yazar ve 500 döner."""
    request_id = getattr(request.state, "request_id", None)
    path = request.url.path if request.url else None
    method = request.method if request.method else None
    client_ip = ""
    if request.client:
        client_ip = request.client.host or ""
    forwarded = request.headers.get("x-forwarded-for") if request.headers else None
    if forwarded:
        client_ip = forwarded.split(",")[0].strip() or client_ip
    user_agent = (
        (request.headers.get("user-agent") or "")[:512] if request.headers else None
    )
    user_id, account_id, is_admin = None, None, False
    try:
        auth = (
            request.headers.get("Authorization")
            or request.headers.get("authorization")
            or ""
        )
        token = auth[7:].strip() if auth.startswith("Bearer ") else None
        if token:
            from app.api.auth import _session_get

            session = _session_get(token)
            if session:
                user_id = session.get("user_id")
                account_id = session.get("account_id")
                is_admin = session.get("is_admin", False)
    except Exception:
        pass
    # WebSocket normal kapanma (1000/1001) veya istemci bağlantı kesti: ERROR loglama / persist etme
    try:
        from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

        if isinstance(exc, (ConnectionClosedOK, ConnectionClosedError)) and getattr(
            exc, "code", 1000
        ) in (1000, 1001):
            logger.debug("WebSocket normal close, skip persist.")
            return JSONResponse(status_code=200, content={})
    except ImportError:
        pass
    if "No response returned" in (str(exc) or ""):
        logger.debug(
            "Unhandled No response returned (client disconnect), skip persist."
        )
    else:
        try:
            from app.db.session import SessionLocal
            from app.error_logging import persist_error

            db = SessionLocal()
            try:
                persist_error(
                    db,
                    "backend",
                    str(exc) or type(exc).__name__,
                    detail=traceback.format_exc(),
                    path=path,
                    method=method,
                    request_id=request_id,
                    user_id=user_id,
                    account_id=account_id,
                    user_agent=user_agent,
                    client_ip=client_ip,
                    is_admin=is_admin,
                    level="error",
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning("global_exception_handler persist failed: %s", e)
    logger.exception("Unhandled exception: %s", exc)
    error_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": {
                "error_code": "INTERNAL_ERROR",
                "error_id": error_id,
                "request_id": request_id,
                "message": "Sunucu hatası.",
            },
        },
    )


# Yaygın API hata kodları için kısa Türkçe açıklama (error_logs'ta okunabilirlik için)
ERROR_CODE_DESCRIPTIONS = {
    "UNAUTHORIZED": "Giriş yapılmamış veya oturum süresi dolmuş",
    "FORBIDDEN": "Bu kaynağa erişim yetkisi yok",
    "ACCOUNT_NOT_FOUND": "Hesap bulunamadı",
    "ACCOUNT_ISOLATED": "Hesap adminden izole",
    "USER_NOT_FOUND": "Kullanıcı bulunamadı",
    "NOT_FOUND": "Kayıt bulunamadı",
    "PENDING_APPROVAL": "Admin onayı bekleniyor",
    "IP_APPROVAL_REQUIRED": "IP onay talebi bekleniyor",
    "RATE_LIMITED": "Çok fazla istek; kısa süre sonra tekrar deneyin",
    "BINANCE_AUTH": "Binance API kimlik hatası",
    "BINANCE_RATE_LIMIT": "Binance istek limiti aşıldı",
    "BINANCE_UPSTREAM_ERROR": "Binance sunucu hatası",
    "INTERNAL_ERROR": "Sunucu iç hatası",
}


def _format_http_detail(status: int, detail) -> tuple:
    """
    HTTPException detail'ından log için okunabilir, tekrarsız mesaj ve context üretir.
    Returns: (message_for_log: str, context_dict: dict)
    """
    status_label = {
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
    }.get(status, f"HTTP {status}")
    if isinstance(detail, dict):
        msg = (detail.get("message") or "").strip()
        code = detail.get("error_code") or ""
        req_id = detail.get("request_id")
        desc = ERROR_CODE_DESCRIPTIONS.get(code, "") if code else ""
        # Tek satırda net açıklama: mesaj varsa onu kullan, yoksa kod açıklaması; kod parantezde
        parts = [f"{status} {status_label}"]
        if msg:
            parts.append(msg)
        elif desc:
            parts.append(desc)
        if code:
            parts.append(f"({code})")
        # Aynı anlama gelen tekrar ekleme (mesaj zaten varsa desc ekleme)
        message_for_log = " – ".join(parts).strip() or f"HTTP {status}"
        context = {
            "status_code": status,
            "error_code": code or None,
            "message": msg or None,
            "request_id": req_id,
        }
        if detail.get("details"):
            context["details"] = detail.get("details")
        return message_for_log[:500], {
            k: v for k, v in context.items() if v is not None
        }
    # str veya diğer
    raw = (str(detail) if detail else "")[:1000]
    message_for_log = f"{status} {status_label}" + (f" – {raw[:500]}" if raw else "")
    return message_for_log, {"status_code": status, "detail": raw}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """4xx/5xx HTTPException'ları error_logs'a yazar; mesaj ve context açıklayıcı/yapılandırılmış."""
    status = exc.status_code
    if status >= 400:
        path = request.url.path if request.url else None
        method = request.method if request.method else None
        request_id = getattr(request.state, "request_id", None)
        client_ip = ""
        if request.client:
            client_ip = request.client.host or ""
        if request.headers.get("x-forwarded-for"):
            client_ip = (
                request.headers.get("x-forwarded-for").split(",")[0].strip()
                or client_ip
            )
        user_agent = (request.headers.get("user-agent") or "")[:512]
        user_id, account_id, is_admin = None, None, False
        try:
            auth = (
                request.headers.get("Authorization")
                or request.headers.get("authorization")
                or ""
            )
            token = auth[7:].strip() if auth.startswith("Bearer ") else None
            if token:
                from app.api.auth import _session_get

                session = _session_get(token)
                if session:
                    user_id = session.get("user_id")
                    account_id = session.get("account_id")
                    is_admin = session.get("is_admin", False)
        except Exception:
            pass
        message_for_log, context = _format_http_detail(status, exc.detail)
        ident = getattr(request.state, "error_log_identifier", None)
        if ident is not None:
            context = dict(context) if context else {}
            context["attempted_identifier"] = str(ident)[:128]
        # Admin test endpoint'e yetkisiz 403 yazma (manager/panelde gürültü olmasın)
        if status == 403 and path == "/api/admin/error-logs/test":
            pass  # skip persist
        else:
            try:
                from app.db.session import SessionLocal
                from app.error_logging import persist_error

                db = SessionLocal()
                try:
                    persist_error(
                        db,
                        "backend",
                        message_for_log,
                        detail=f"path={path} method={method} durum={status}",
                        path=path,
                        method=method,
                        request_id=request_id,
                        user_id=user_id,
                        account_id=account_id,
                        user_agent=user_agent,
                        client_ip=client_ip,
                        context=context,
                        is_admin=is_admin,
                        level="error" if status >= 500 else "warning",
                    )
                finally:
                    db.close()
            except Exception as e:
                logger.warning("http_exception_handler persist failed: %s", e)
    if isinstance(exc.detail, dict):
        content = {"detail": exc.detail, **exc.detail}
    else:
        content = {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=content)


# API routes
# Manager panel (v2) sadece 127.0.0.1:7999'da çalışır (manager_server).
app.include_router(auth.router, prefix="/api")  # Authentication
app.include_router(data_hub_routes.router, prefix="/api")  # YENİ - Data Hub
if market_data_routes:
    app.include_router(market_data_routes.router, prefix="/api")  # YENİ - Market Data
app.include_router(finance_reports.router, prefix="/api")  # YENİ - Finance Reports
app.include_router(
    pricing_routes.router, prefix="/api/pricing"
)  # Üst ticker canlı fiyat
app.include_router(routes.router, prefix="/api")
_home_routes_loaded = False
for _home_mod in ("app.api.routes.home",):
    try:
        home_routes = __import__(_home_mod, fromlist=["router"])
        app.include_router(home_routes.router, prefix="/api")
        _home_routes_loaded = True
        break
    except ImportError:
        continue
    except Exception as e:
        logger.warning("Flash Home routes not loaded from %s: %s", _home_mod, e)
if not _home_routes_loaded:
    logger.warning(
        "Flash Home routes not loaded. /api/home/fast and /api/home/wallet/refresh will use fallback."
    )

try:
    from app.api import dashboard_stream

    app.include_router(dashboard_stream.router, prefix="/api")
except ImportError as e:
    logger.warning("Dashboard SSE routes not loaded: %s", e)

try:
    from app.api.routes import dashboard_bootstrap

    app.include_router(dashboard_bootstrap.router, prefix="/api")
except ImportError as e:
    logger.warning("Dashboard bootstrap not loaded: %s", e)

if not _home_routes_loaded:
    from fastapi import Depends
    from app.api.auth import require_auth, require_account_access

    @app.get("/api/home/fast")
    async def _fallback_home_fast(
        account_id: int = Query(..., description="Account ID"),
        current: dict = Depends(require_auth),
    ):
        """Fallback when app.api.routes.home is not loaded. Returns minimal payload so dashboard does not 404."""
        require_account_access(current, account_id)
        return {
            "ok": True,
            "data": {
                "prices": {},
                "kpis": {},
                "wallet_cached": None,
                "wallet_cached_at": None,
                "wallet_live_inflight": False,
            },
            "meta": {
                "request_id": "",
                "server_ms": 0,
                "payload_bytes": 0,
                "cache": False,
                "stale": True,
                "generated_at": None,
            },
        }

    @app.post("/api/home/wallet/refresh")
    async def _fallback_home_wallet_refresh(
        account_id: int = Query(..., description="Account ID"),
        current: dict = Depends(require_auth),
    ):
        """Fallback when app.api.routes.home is not loaded."""
        require_account_access(current, account_id)
        return {
            "ok": True,
            "data": {"inflight": False, "wallet_live": None, "wallet_live_at": None},
        }

    @app.get("/api/home/wallet/status")
    async def _fallback_home_wallet_status(
        account_id: int = Query(..., description="Account ID"),
        current: dict = Depends(require_auth),
    ):
        """Fallback when app.api.routes.home is not loaded."""
        require_account_access(current, account_id)
        return {"inflight": False, "last_live_at": None, "cooldown_until": None}


app.include_router(admin.router, prefix="/api")
app.include_router(bots_v2.router, prefix="/api")
app.include_router(bots_engine.router, prefix="/api/bots-engine")
app.include_router(finance.router, prefix="/api")
app.include_router(spot_routes.router, prefix="/api")  # YENİ - Spot Engine
app.include_router(ws.router, prefix="/api/ws")
try:
    from app.api import leaderboard

    app.include_router(leaderboard.router, prefix="/api")
except ImportError as e:
    logger.warning("Leaderboard API not loaded: %s", e)

# Debug routes (only in development)
try:
    from app.api import trace_routes

    app.include_router(trace_routes.router, prefix="/api")
except ImportError:
    pass


@app.get("/api/boot-id")
async def api_boot_id():
    """Sunucu her açılışta yeni boot_id. İstemci eşleşmezse oturum iptal."""
    from app.boot_id import get_boot_id

    return {"boot_id": get_boot_id()}


@app.post("/api/admin/error-logs/test")
async def api_admin_create_test_error(request: Request):
    """Hata logları ekranını test etmek için tek seferlik örnek kayıt. Sadece admin."""
    from app.api.auth import _session_get
    from app.db.session import SessionLocal
    from app.error_logging import persist_error
    from datetime import datetime

    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    token = auth[7:].strip() if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(
            status_code=401, detail={"message": "Yetkilendirme gerekli"}
        )
    session = _session_get(token)
    if not session or not session.get("is_admin"):
        raise HTTPException(
            status_code=403, detail={"message": "Bu işlem için admin yetkisi gerekli"}
        )
    db = SessionLocal()
    try:
        rid = persist_error(
            db,
            source="server",
            message="[TEST] Hata logları ekranı test kaydı – bilinçli oluşturuldu.",
            detail="Bu kayıt Ayarlar → Hatalar ekranını test etmek için otomatik eklendi.\nKaldırmak isterseniz veritabanından silebilirsiniz.",
            path="/api/admin/error-logs/test",
            method="POST",
            request_id=f"test-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            user_id=session.get("user_id"),
            account_id=session.get("account_id"),
            user_agent="Admin test",
            client_ip=None,
            context={"test": True, "purpose": "error_logs_ui_test"},
            is_admin=True,
            level="error",
        )
        return {"ok": True, "message": "Test hatası oluşturuldu.", "error_log_id": rid}
    finally:
        db.close()


def _api_admin_error_logs_auth(request: Request):
    """Admin token check for error-logs GET. Raises 401/403."""
    from app.api.auth import _session_get

    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    token = auth[7:].strip() if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(
            status_code=401, detail={"message": "Yetkilendirme gerekli"}
        )
    session = _session_get(token)
    if not session or not session.get("is_admin"):
        raise HTTPException(
            status_code=403, detail={"message": "Bu işlem için admin yetkisi gerekli"}
        )
    return session


@app.post("/api/error-logs/clear")
async def api_error_logs_clear(
    request: Request,
    account_id: int = Query(..., description="Account ID"),
):
    """Test hesabının backend hata loglarını siler (dashboard Sıfırla). Yenileyince liste boş kalır."""
    from app.db.session import SessionLocal
    from app.db.models import ErrorLog
    from app.services.test_account import is_test_account
    from app.api.auth import _session_get

    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    token = auth[7:].strip() if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Yetkilendirme gerekli")
    session = _session_get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Oturum geçersiz")
    session_account_id = session.get("account_id")
    db = SessionLocal()
    try:
        if session_account_id is not None and is_test_account(session_account_id, db):
            account_id = session_account_id
        else:
            raise HTTPException(
                status_code=403,
                detail="Bu özellik sadece test hesabında kullanılabilir.",
            )
        deleted = db.query(ErrorLog).filter(ErrorLog.account_id == account_id).delete()
        db.commit()
        return {"ok": True, "deleted": deleted}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Loglar silinirken hata oluştu.")
    finally:
        db.close()


@app.get("/api/admin/error-logs")
async def api_admin_error_logs(
    request: Request,
    grouped: bool = True,
    max_unique: int = 50,
    after_id: Optional[int] = None,
):
    """Hata logları listesi. Admin panelden çağrılır."""
    from app.db.session import SessionLocal
    from app.db.models import ErrorLog, User, Account
    from sqlalchemy import desc
    import json

    _api_admin_error_logs_auth(request)
    db = SessionLocal()
    try:
        q = db.query(ErrorLog).order_by(desc(ErrorLog.id))
        if after_id is not None:
            q = q.filter(ErrorLog.id > after_id)
        if grouped:
            rows = q.limit(min(max_unique * 20, 2000)).all()
            seen = {}
            for row in rows:
                key = (row.source or "", row.message or "", row.path or "")
                if key not in seen:
                    seen[key] = []
                seen[key].append(row)
            groups = list(seen.items())[:max_unique]
            errors = []
            for _key, group in groups:
                rep = group[0]
                user_label = None
                account_label = None
                if rep.user_id:
                    u = db.query(User).filter(User.id == rep.user_id).first()
                    if u:
                        user_label = u.username or (
                            f"Denenen: {(u.phone or '')[:8]}..."
                            if u.phone
                            else str(u.id)
                        )
                if rep.account_id:
                    a = db.query(Account).filter(Account.id == rep.account_id).first()
                    if a:
                        account_label = a.name or a.account_code or str(a.id)
                ctx = None
                if getattr(rep, "context_json", None):
                    try:
                        ctx = (
                            json.loads(rep.context_json)
                            if isinstance(rep.context_json, str)
                            else rep.context_json
                        )
                    except Exception:
                        ctx = None
                errors.append(
                    {
                        "id": rep.id,
                        "source": rep.source or "",
                        "message": rep.message or "",
                        "detail": getattr(rep, "detail", None) or None,
                        "path": getattr(rep, "path", None) or None,
                        "context": ctx,
                        "user_label": user_label,
                        "account_label": account_label,
                        "is_admin": bool(getattr(rep, "is_admin", False)),
                        "created_at": rep.created_at.isoformat() + "Z"
                        if rep.created_at
                        else None,
                        "occurrence_count": len(group),
                        "client_ip": getattr(rep, "client_ip", None) or None,
                        "user_agent": getattr(rep, "user_agent", None) or None,
                        "request_id": getattr(rep, "request_id", None) or None,
                    }
                )
        else:
            rows = q.limit(max_unique).all()
            errors = []
            for row in rows:
                user_label = None
                account_label = None
                if row.user_id:
                    u = db.query(User).filter(User.id == row.user_id).first()
                    if u:
                        user_label = u.username or (
                            f"Denenen: {(u.phone or '')[:8]}..."
                            if u.phone
                            else str(u.id)
                        )
                if row.account_id:
                    a = db.query(Account).filter(Account.id == row.account_id).first()
                    if a:
                        account_label = a.name or a.account_code or str(a.id)
                ctx = None
                if getattr(row, "context_json", None):
                    try:
                        ctx = (
                            json.loads(row.context_json)
                            if isinstance(row.context_json, str)
                            else row.context_json
                        )
                    except Exception:
                        ctx = None
                errors.append(
                    {
                        "id": row.id,
                        "source": row.source or "",
                        "message": row.message or "",
                        "detail": getattr(row, "detail", None) or None,
                        "path": getattr(row, "path", None) or None,
                        "context": ctx,
                        "user_label": user_label,
                        "account_label": account_label,
                        "is_admin": bool(getattr(row, "is_admin", False)),
                        "created_at": row.created_at.isoformat() + "Z"
                        if row.created_at
                        else None,
                        "occurrence_count": 1,
                        "client_ip": getattr(row, "client_ip", None) or None,
                        "user_agent": getattr(row, "user_agent", None) or None,
                        "request_id": getattr(row, "request_id", None) or None,
                    }
                )
        return {"errors": errors}
    finally:
        db.close()


@app.get("/api/admin/error-logs/count")
async def api_admin_error_logs_count(request: Request):
    """Hata logları toplam sayı ve son id. Admin panelden çağrılır."""
    from app.db.session import SessionLocal
    from app.db.models import ErrorLog
    from sqlalchemy import desc

    _api_admin_error_logs_auth(request)
    db = SessionLocal()
    try:
        cnt = db.query(ErrorLog).count()
        latest = db.query(ErrorLog).order_by(desc(ErrorLog.id)).first()
        latest_id = latest.id if latest else None
        return {"count": cnt, "latest_id": latest_id}
    except Exception as e:
        logger.warning("[Admin] get_error_logs_count failed: %s", e)
        return {"count": 0, "latest_id": None}
    finally:
        db.close()


@app.post("/api/admin/error-logs/clear")
async def api_admin_error_logs_clear(request: Request):
    """Tüm hata loglarını siler. Admin panelde 'Hataları sıfırla' sonrası sadece yeni hatalar listelenir."""
    from app.db.session import SessionLocal
    from app.db.models import ErrorLog

    _api_admin_error_logs_auth(request)
    db = SessionLocal()
    try:
        deleted = db.query(ErrorLog).delete()
        db.commit()
        logger.info("[Admin] error_logs cleared: %s rows deleted", deleted)
        return {"success": True, "deleted": deleted, "message": "Hatalar silindi."}
    except Exception as e:
        db.rollback()
        logger.warning("[Admin] error_logs clear failed: %s", e)
        raise HTTPException(status_code=500, detail="Hatalar silinemedi.")
    finally:
        db.close()


# Admin pop-up endpoints (main.py'de kayitli olsun; 404 onlenir)
from app.api.admin import (
    list_admin_popups,
    create_admin_popup,
    delete_admin_popup,
    get_admin_popup_detail,
    _require_admin,
    CreatePopupRequest,
)
from app.db.session import get_db
from sqlalchemy.orm import Session


@app.get("/api/admin/popups")
async def api_admin_list_popups(
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return await list_admin_popups(current=current, db=db)


@app.get("/api/admin/popups/{popup_id}")
async def api_admin_get_popup_detail(
    popup_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return await get_admin_popup_detail(popup_id=popup_id, current=current, db=db)


@app.post("/api/admin/popups")
async def api_admin_create_popup(
    req: CreatePopupRequest = Body(...),
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return await create_admin_popup(req=req, current=current, db=db)


@app.delete("/api/admin/popups/{popup_id}")
async def api_admin_delete_popup(
    popup_id: int,
    current: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return await delete_admin_popup(popup_id=popup_id, current=current, db=db)


@app.get("/api/health")
async def api_health():
    """Sağlık kontrolü — DB, DataHub ve worker durumunu döner. Auth yok."""
    from datetime import datetime, timezone

    _project_root = str(BASE_DIR) if BASE_DIR else ""
    total_requests = None
    db_ok = False
    db_error = None
    binance_fail = False
    worker_running = False
    prices_count = 0
    try:
        from app.middleware.request_metrics import get_metrics

        total_requests = get_metrics().get("total_requests")
    except Exception:
        pass
    try:
        from app.db.base import SessionLocal

        _db = SessionLocal()
        try:
            _db.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ok = True
        finally:
            _db.close()
    except Exception as _dbe:
        db_error = str(_dbe)[:120]
    try:
        from app.services.data_hub import data_hub

        prices_count = len(getattr(data_hub, "prices", {}) or {})
    except Exception:
        pass
    try:
        from app.botengine.worker_main import is_worker_running

        worker_running = bool(is_worker_running())
    except Exception:
        pass
    try:
        from app.services.binance_connectivity import _by_account

        binance_fail = len(_by_account) > 0
    except Exception:
        pass
    status = "ok" if db_ok else "degraded"
    return {
        "ok": db_ok,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "lockdown": server_state.get_lockdown(),
        "project_path": _project_root,
        "total_requests": total_requests,
        "db": "ok" if db_ok else f"error: {db_error}",
        "prices_count": prices_count,
        "worker_running": worker_running,
        "binance_failure_active": binance_fail,
    }


@app.get("/api/ready")
async def api_ready():
    """Readiness probe — yük dengeleyici için. DB + DataHub hazır olduğunda 200, değilse 503 döner."""
    from fastapi.responses import JSONResponse

    db_ok = False
    prices_ok = False
    try:
        from app.db.base import SessionLocal

        _db = SessionLocal()
        try:
            _db.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ok = True
        finally:
            _db.close()
    except Exception:
        pass
    try:
        from app.services.data_hub import data_hub

        prices_ok = len(getattr(data_hub, "prices", {}) or {}) > 0
    except Exception:
        pass
    ready = db_ok
    payload = {"ready": ready, "db": db_ok, "prices": prices_ok}
    return JSONResponse(content=payload, status_code=200 if ready else 503)


@app.get("/api/config/public")
async def api_config_public():
    """Public config for UI: auth mode and CSRF. No auth required. Used for cookie-primary and CSRF header."""
    try:
        from app.core.config import get_security_config

        cfg = get_security_config()
        return {
            "auth_cookie_primary": cfg.get("auth_cookie_primary", False),
            "csrf_double_submit": cfg.get("auth_csrf_double_submit", False),
            "dashboard_sse_enabled": os.environ.get("DASHBOARD_SSE_ENABLED", "1")
            .strip()
            .lower()
            in ("1", "true", "yes"),
        }
    except Exception:
        return {
            "auth_cookie_primary": False,
            "csrf_double_submit": False,
            "dashboard_sse_enabled": False,
        }


@app.get("/api/health/marketdata")
async def api_health_marketdata():
    """Market data readiness: prices_ready true when DataHub has at least one price (warmup or background)."""
    try:
        from app.services.data_hub import data_hub

        prices_ready = bool(
            getattr(data_hub, "prices", None) and len(data_hub.prices) > 0
        )
        return {
            "ok": True,
            "prices_ready": prices_ready,
            "prices_count": len(getattr(data_hub, "prices", {})),
        }
    except Exception:
        return {"ok": True, "prices_ready": False, "prices_count": 0}


# Log sayfası (7999) Yeniden Başlat öncesi istek sayacını sıfırlamak için; sadece localhost
@app.post("/api/debug/reset-request-count")
async def reset_request_count(request: Request):
    """Sadece 127.0.0.1'den çağrılabilir; toplam istek sayacını sıfırlar (sistem yeniden başlatıldığında)."""
    if request.client and request.client.host != "127.0.0.1":
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    try:
        if RequestMetrics is not None:
            RequestMetrics.reset_counts()
        return {"ok": True}
    except Exception:
        return {"ok": False}


# Debug metrics (dev only or when DEBUG_METRICS=1; prod'da auth ile korunmalı)
@app.get("/debug/metrics")
async def debug_metrics():
    """Request observability: top endpoints by count/latency, status summary, RPS, Binance calls, cache hit rate."""
    if os.getenv("ENV", "").lower() == "prod" and not os.getenv("DEBUG_METRICS"):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Not found"})
    from app.middleware.request_metrics import get_metrics
    from app.services.binance_metrics import BinanceMetrics
    from app.api.routes import get_binance_cache_stats

    out = get_metrics()
    out["binance"] = BinanceMetrics.to_dict()
    out["binance_cache"] = get_binance_cache_stats()
    try:
        from app.services.binance_weight import get_metrics as weight_metrics
        from app.services.binance_rest_log import get_live_snapshot

        out["binance_weight"] = weight_metrics()
        out["binance_rest_window"] = get_live_snapshot()
    except Exception:
        pass
    return out


@app.get("/api/debug/rest-load")
async def debug_rest_load():
    """Anlık REST pencere özeti + rest.log yolu. DEBUG_METRICS=1 veya dev."""
    if os.getenv("ENV", "").lower() == "prod" and not os.getenv("DEBUG_METRICS"):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Not found"})
    from app.services.binance_rest_log import get_live_snapshot, REST_LOG_PATH

    snap = get_live_snapshot()
    snap["log_file"] = str(REST_LOG_PATH)
    return snap


@app.get("/api/health/ram")
async def api_health_ram():
    """Latest RAM snapshot when RAM_PROBE=1. Returns 404 if probe disabled."""
    if (
        os.getenv("RAM_PROBE", "").strip() != "1"
        and os.getenv("RAM_PROBE_ENABLED", "").strip() != "1"
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Set RAM_PROBE=1"})
    from app.observability.ram_probe import get_last_snapshot

    snap = get_last_snapshot()
    if snap is None:
        return {"detail": "No snapshot yet", "ok": True}
    return snap


@app.get("/api/debug/ram-snapshot")
async def debug_ram_snapshot():
    """RAM root cause: tek snapshot + gc.collect sonrası obje sayıları. RAM_PROBE=1 ile anlamlı."""
    if (
        os.getenv("RAM_PROBE", "").strip() != "1"
        and os.getenv("RAM_PROBE_ENABLED", "").strip() != "1"
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Set RAM_PROBE=1"})
    from app.observability.ram_probe import take_snapshot, gc_collect_and_count

    snapshot = take_snapshot(label="api_debug")
    gc_result = gc_collect_and_count()
    return {"snapshot": snapshot, "gc_after_collect": gc_result}


@app.get("/api/debug/db-mode")
async def debug_db_mode():
    """Return journal_mode, synchronous, role (web|worker). Validates WAL is active."""
    from sqlalchemy import text
    from app.db.base import engine, DATABASE_URL

    role = os.getenv("DATABASE_ROLE", "web").strip().lower()
    journal_mode = synchronous = "n/a"
    if "sqlite" in str(DATABASE_URL):
        with engine.connect() as conn:
            r1 = conn.execute(text("PRAGMA journal_mode")).scalar()
            r2 = conn.execute(text("PRAGMA synchronous")).scalar()
            journal_mode = str(r1) if r1 else "unknown"
            synchronous = str(r2) if r2 else "unknown"
    return {"journal_mode": journal_mode, "synchronous": synchronous, "role": role}


@app.get("/api/debug/resource-usage")
async def debug_resource_usage():
    """RAM/CPU tüketim teşhisi: DataHub, oturum ve cache boyutları. Yüksek RAM genelde DataHub.prices (binlerce sembol) veya oturum/cache birikiminden kaynaklanır."""
    from app.services.data_hub import data_hub
    from app.api import auth as auth_mod
    from app.api.routes import _price_cache

    data_hub_counts = {
        "prices_len": len(data_hub.prices),
        "mini_ws_len": len(data_hub._mini_ws),
        "account_balances_len": len(data_hub.account_balances),
        "all_symbols_len": len(data_hub.all_symbols),
        "coin_list_len": len(data_hub.coin_list),
        "max_prices_cap": data_hub._MAX_PRICES,
        "max_mini_ws_cap": data_hub._MAX_MINI_WS,
    }
    sessions_count = len(getattr(auth_mod, "_sessions", {}))
    price_cache_len = len(_price_cache)
    return {
        "data_hub": data_hub_counts,
        "auth_sessions_count": sessions_count,
        "price_cache_len": price_cache_len,
        "diagnosis": (
            "RAM tüketimi: DataHub.prices ve _mini_ws sınırlandı (max 600). "
            "Yüksek CPU: DataHub arka plan döngüsü (1–2s fiyat, 5s 24h). "
            "İşlem yokken yüksekse DataHub REST/WS güncellemeleri veya diğer arka plan görevleri etkendir."
        ),
    }


# Static files and UI
BASE_DIR = Path(__file__).resolve().parents[1]  # Project root
UI_DIR = BASE_DIR / "ui"
ui_dir = str(UI_DIR)

# Coin logoları: uzun süreli cache ile sayfa yenilemede yeniden yüklenmesin
COINS_DIR = UI_DIR / "assets" / "coins"
COIN_LOGO_CACHE_MAX_AGE = 31 * 24 * 60 * 60  # 31 gün saniye cinsinden


@app.get("/ui/assets/coins/{filename:path}")
async def serve_coin_logo(filename: str):
    """Coin logo PNG dosyaları – tarayıcı cache (31 gün) ile sayfa yenilemede flicker olmaz."""
    if not filename or ".." in filename or not filename.endswith(".png"):
        raise HTTPException(status_code=404, detail="Not found")
    if "/" in filename:
        raise HTTPException(status_code=404, detail="Not found")
    path = COINS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=%d, immutable" % COIN_LOGO_CACHE_MAX_AGE,
        },
    )


app.mount(
    "/ui/assets", StaticFiles(directory=os.path.join(ui_dir, "assets")), name="assets"
)
_ui_js_dir = os.path.join(ui_dir, "assets", "js")
if os.path.isdir(_ui_js_dir):
    app.mount("/ui/js", StaticFiles(directory=_ui_js_dir), name="ui_js")
app.mount(
    "/ui/vendor", StaticFiles(directory=os.path.join(ui_dir, "vendor")), name="vendor"
)


# EXPLICIT ROUTES FOR CRITICAL PAGES (BEFORE catch-all)
# These must be registered BEFORE the catch-all /ui/{path:path} route


@app.get("/ui/admin.html")
async def ui_admin_html(request: Request):
    """Admin paneli: sadece giriş yapmış ve is_admin olan kullanıcı erişebilir; aksi halde login'e yönlendir.
    Oturum auth_sessions tablosundan okunur (DB ile)."""
    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    token = (
        auth[7:].strip() if auth.startswith("Bearer ") else None
    ) or request.cookies.get("auth_token")
    if not token:
        return RedirectResponse(url="/ui/login.html", status_code=302)
    try:
        from app.api.auth import _session_get
        from app.db.session import get_db

        db_gen = get_db()
        db = next(db_gen)
        try:
            session = _session_get(token, db)
            if not session or not session.get("is_admin"):
                return RedirectResponse(url="/ui/login.html", status_code=302)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
    except Exception:
        return RedirectResponse(url="/ui/login.html", status_code=302)
    return FileResponse(
        UI_DIR / "admin.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/ui/dashboard.html")
async def ui_dashboard():
    """Serve dashboard.html with no-cache headers - PINNED to exact file"""
    return FileResponse(
        UI_DIR / "dashboard.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/")
async def root():
    """Ana sayfa: doğrudan login (TraderTrailing giriş) sayfasına yönlendir"""
    return RedirectResponse(url="/ui/login.html", status_code=302)


@app.get("/favicon.ico")
async def favicon():
    """204 No Content – tarayıcı favicon isteği 404 log spam önlenir."""
    return Response(status_code=204)


@app.get("/trader-trailing")
async def trader_trailing():
    """Kavram sayfası"""
    return FileResponse(
        UI_DIR / "trader-trailing.html",
        headers={
            "Cache-Control": "public, max-age=300",
        },
    )


@app.get("/robots.txt")
async def robots_txt():
    """robots.txt"""
    return FileResponse(
        UI_DIR / "robots.txt",
        media_type="text/plain",
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/sitemap.xml")
async def sitemap_xml():
    """sitemap.xml"""
    return FileResponse(
        UI_DIR / "sitemap.xml",
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/ui/login.html")
async def ui_login():
    """Serve login.html"""
    return FileResponse(
        UI_DIR / "login.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/ui/logs.html")
async def ui_logs_redirect():
    """Manager panel 127.0.0.1:7999'da; 8000'den gelenleri 7999/ui'ya yönlendir."""
    return RedirectResponse(url="http://127.0.0.1:7999/ui", status_code=302)


@app.get("/ui/{path:path}")
async def ui_page(path: str):
    """Serve other UI pages with no-cache headers (catch-all for remaining paths)"""
    file_path = UI_DIR / path
    if file_path.exists() and file_path.suffix == ".html":
        return FileResponse(
            file_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {"error": "Page not found"}


if __name__ == "__main__":
    import sys
    import uvicorn

    # uvloop sadece Unix'te var; Windows'ta ModuleNotFoundError onlenir
    run_kw = {"host": "0.0.0.0", "port": 8000, "workers": 2}
    if sys.platform != "win32":
        run_kw["loop"] = "uvloop"
        run_kw["http"] = "httptools"
    uvicorn.run(app, **run_kw)
