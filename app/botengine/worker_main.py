"""
Engine Worker: ayrı proses. Bot loop'larını çalıştırır; web'den bağımsız.
Komut kaynağı: bot_engine_commands tablosu (START/STOP). Running botlar DB status ile ensure edilir.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Terminalde sadece hata/uyarı; stdout log dosyasına yönlendirildiğinde (worker.log) tam log — Türkiye saati
_console_level = logging.WARNING if (getattr(sys.stdout, "isatty", lambda: False)()) else logging.INFO
logging.basicConfig(
    level=_console_level,
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
# Log zamanları Türkiye saati (Europe/Istanbul)
try:
    from app.utils.tz_utils import TurkeyTimeFormatter
    for _h in logging.root.handlers:
        _h.setFormatter(TurkeyTimeFormatter("[%(asctime)s] %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
except Exception:
    pass
logger = logging.getLogger("app.botengine.worker")
logger.setLevel(logging.DEBUG)
# httpx her GET'i INFO ile yazmasın (market sync 2 sn'de bir worker.log'u doldurur)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# stdout dosyaya yönlendirildiğinde (worker.log) her satır hemen diske yazılsın; log sayfası Toplam istek sayacı güncel kalsın
for _h in logging.root.handlers:
    if getattr(_h, "stream", None) is sys.stdout:
        _orig_emit = _h.emit
        def _emit_flush(record):
            _orig_emit(record)
            _h.flush()
        _h.emit = _emit_flush
        break

# Ensure project root on path
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(os.path.dirname(_here))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Load .env so DATABASE_URL matches web server (worker must use same DB)
try:
    from dotenv import load_dotenv
    load_dotenv(str(_root / ".env"))
    os.chdir(_root)  # sqlite:///./dca.db is relative to cwd
except Exception:
    pass

# DB role: worker (write-heavy) vs web (read-heavy). Set before any app.db import.
os.environ.setdefault("DATABASE_ROLE", "worker")

# Ensure logs/ and .run/ exist (web + worker)
from pathlib import Path
_PROJECT_ROOT = Path(_root)
_LOGS_DIR = _PROJECT_ROOT / "logs"
_RUN_DIR = _PROJECT_ROOT / ".run"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)
_RUN_DIR.mkdir(parents=True, exist_ok=True)

# Engine metrics for Manager v3: bounded, written every 2s
_ENGINE_METRICS_TICK_TIMES: deque = deque(maxlen=5000)  # worker ticks; 60m window for manager Saatlik tick
_ENGINE_LAST_ERROR_TS: Optional[float] = None
_ENGINE_LAST_TICK_TS: Optional[float] = None
_ENGINE_LAST_PENDING_LEN: int = 0
_ENGINE_METRICS_LOOP_COUNT: int = 0


def _get_db():
    from app.db.base import SessionLocal
    return SessionLocal()


def _run_schema_guard():
    from app.db.base import engine
    from app.db.schema_guard import run_schema_guard
    run_schema_guard(engine)


def assert_bot_belongs_to_account(db, bot_id: int, account_id: int) -> Tuple[bool, Optional[Any]]:
    """Worker multi-tenant guard: bot.account_id == command.account_id. Returns (ok, bot_row)."""
    from app.db.models import Bot
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        return False, None
    if int(bot.account_id) != int(account_id):
        logger.warning("WORKER_SECURITY bot_id=%s command_account_id=%s bot_account_id=%s MISMATCH",
                      bot_id, account_id, bot.account_id)
        return False, bot
    return True, bot


def fetch_pending_commands(db, limit: int = 50) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT id, created_at, account_id, bot_id, command, payload_json, status, request_id
            FROM bot_engine_commands
            WHERE status = 'PENDING'
            ORDER BY id ASC
            LIMIT :lim
        """),
        {"lim": limit},
    ).fetchall()
    return [
        {
            "id": r[0],
            "created_at": r[1],
            "account_id": r[2],
            "bot_id": r[3],
            "command": r[4],
            "payload_json": r[5],
            "status": r[6],
            "request_id": r[7],
        }
        for r in rows
    ]


def mark_command_processing(db, cmd_id: int) -> bool:
    """Claim command: set PROCESSING. Returns True if we claimed it."""
    from sqlalchemy import text
    now = datetime.now(timezone.utc).isoformat()
    r = db.execute(
        text("""
            UPDATE bot_engine_commands
            SET status = 'PROCESSING', processed_at = :now
            WHERE id = :id AND status = 'PENDING'
        """),
        {"id": cmd_id, "now": now},
    )
    db.commit()
    return r.rowcount > 0


def reset_stale_processing_commands(db, max_age_sec: int = 120) -> int:
    """Worker crash recovery: reclaim commands stuck in PROCESSING."""
    from sqlalchemy import text
    try:
        r = db.execute(
            text("""
                UPDATE bot_engine_commands
                SET status = 'PENDING', processed_at = NULL, error_code = NULL, error_id = NULL
                WHERE status = 'PROCESSING'
                  AND processed_at IS NOT NULL
                  AND processed_at < datetime('now', :offset)
            """),
            {"offset": f"-{int(max_age_sec)} seconds"},
        )
        db.commit()
        n = r.rowcount or 0
        if n:
            logger.warning("WORKER_RECLAIM_STALE_COMMANDS count=%s max_age_sec=%s", n, max_age_sec)
        return n
    except Exception as e:
        db.rollback()
        logger.debug("reset_stale_processing_commands: %s", e)
        return 0


def mark_command_done(db, cmd_id: int, error_code: Optional[str] = None, error_id: Optional[str] = None):
    from sqlalchemy import text
    now = datetime.now(timezone.utc).isoformat()
    status = "ERROR" if error_code else "DONE"
    db.execute(
        text("""
            UPDATE bot_engine_commands
            SET status = :status, processed_at = :now, error_code = :err_code, error_id = :err_id
            WHERE id = :id
        """),
        {"id": cmd_id, "status": status, "now": now, "err_code": error_code or None, "err_id": error_id or None},
    )
    db.commit()


async def process_command(cmd: Dict[str, Any], db, v5_scheduler=None) -> None:
    """Process one command: assert account, then start_bot or stop_bot (or v5: register/unregister with scheduler)."""
    import json as _json

    from app.botengine.state_store import append_event, load_state, save_state
    from app.botengine.orchestrator import start_bot, stop_bot
    from app.db.models import Bot

    cmd_payload: Dict[str, Any] = {}
    try:
        raw_pl = cmd.get("payload_json")
        if raw_pl:
            cmd_payload = _json.loads(raw_pl) if isinstance(raw_pl, str) else dict(raw_pl)
    except Exception:
        cmd_payload = {}

    def _command_event_meta(bot_id: int) -> Dict[str, Any]:
        state = load_state(db, bot_id) or {}
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        meta: Dict[str, Any] = {
            "command_id": cmd_id,
            "command": command,
            "cycle_id": int(state.get("cycle_id") or 1),
        }
        if not bot:
            return meta
        symbol = (bot.symbol or state.get("symbol") or "").strip().upper()
        base_b = float(state.get("base_balance") or 0)
        quote_b = float(state.get("quote_balance") or 0)
        meta["symbol"] = symbol or None
        meta["base_balance"] = round(base_b, 10)
        meta["quote_balance"] = round(quote_b, 2)
        meta["initial_allocation_done"] = bool(state.get("initial_allocation_done"))
        cse = float(state.get("cycle_start_equity") or 0)
        if cse > 0:
            meta["cycle_start_equity"] = round(cse, 2)
        try:
            import json

            raw_cfg = json.loads(getattr(bot, "config_json", None) or "{}")
            ic = float(
                raw_cfg.get("initial_capital_usdt")
                or raw_cfg.get("budget_usd")
                or raw_cfg.get("bot_budget_usdt")
                or 0
            )
            if ic > 0:
                meta["initial_capital_usdt"] = round(ic, 2)
            if command == "START" and not cmd_payload.get("connectivity_resume"):
                from app.botengine.start_log_brief import merge_cold_start_brief_into_meta

                merge_cold_start_brief_into_meta(meta, raw_cfg)
        except Exception:
            pass
        try:
            from app.services.bot_equity import compute_bot_equity_usd, get_bot_last_price

            eq = compute_bot_equity_usd(db, bot, state)
            meta["equity_usd"] = round(float(eq), 2)
            lp = get_bot_last_price(symbol, state)
            if lp is not None and lp > 0:
                meta["last_price"] = round(float(lp), 4)
        except Exception:
            if base_b > 0 or quote_b > 0:
                ref = float(state.get("reference_price") or 0)
                if ref > 0:
                    meta["equity_usd"] = round(base_b * ref + quote_b, 2)
        if cmd_payload.get("connectivity_resume"):
            meta["connectivity_resume"] = True
            rr = (cmd_payload.get("resume_reason") or "").strip()
            if rr:
                meta["resume_reason"] = rr
            if cmd_payload.get("cycle_id") is not None:
                meta["cycle_id"] = int(cmd_payload["cycle_id"])
        resume_reason = (state.get("_connectivity_resume_reason") or "").strip()
        if resume_reason:
            meta["connectivity_resume"] = True
            meta["resume_reason"] = resume_reason
            try:
                from app.botengine.state_store import save_state

                state.pop("_connectivity_resume_reason", None)
                save_state(db, bot_id, int(bot.account_id), state)
            except Exception:
                pass
        return meta

    cmd_id = cmd["id"]
    account_id = int(cmd["account_id"])
    bot_id = int(cmd["bot_id"])
    command = (cmd.get("command") or "").strip().upper()

    ok, bot_row = assert_bot_belongs_to_account(db, bot_id, account_id)
    if not ok:
        if bot_row is None:
            mark_command_done(db, cmd_id, error_code="BOT_NOT_FOUND")
        else:
            mark_command_done(db, cmd_id, error_code="ACCOUNT_MISMATCH")
            try:
                append_event(db, bot_id, int(bot_row.account_id), "ERROR",
                            f"COMMAND_REJECTED command_id={cmd_id} account_mismatch",
                            {"command_id": cmd_id, "command": command, "error_code": "ACCOUNT_MISMATCH"})
            except Exception:
                pass
        return

    try:
        if command == "START":
            if v5_scheduler:
                from app.botengine.orchestrator import cancel_orchestrator_loop
                from app.botengine.bot_session import (
                    is_connectivity_resume_start,
                    mark_bot_run_started,
                    touch_bot_started_at,
                )
                st_pre = load_state(db, bot_id) or {}
                conn_resume = is_connectivity_resume_start(cmd_payload, st_pre)
                if not conn_resume:
                    cancel_orchestrator_loop(bot_id)
                bot = db.query(Bot).filter(Bot.id == bot_id).first()
                if bot:
                    bot.status = "running"
                    touch_bot_started_at(bot, connectivity_resume=conn_resume)
                    mark_bot_run_started(st_pre, connectivity_resume=conn_resume)
                    save_state(db, bot_id, account_id, st_pre)
                    db.commit()
                v5_scheduler.register_bot(bot_id, time.monotonic())
                mark_command_done(db, cmd_id)
                logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=START (v5 registered)", cmd_id, bot_id)
                start_meta = _command_event_meta(bot_id)
                is_conn_resume = bool(start_meta.get("connectivity_resume"))
                if not is_conn_resume:
                    try:
                        append_event(
                            db, bot_id, account_id, "INFO",
                            f"COMMAND_EXECUTED command_id={cmd_id} START", start_meta,
                        )
                    except Exception:
                        pass
                # İlk alımı hemen yap: soğuk başlatmada anında tick; bağlantı devamında atla (tur/grid korunur)
                st = load_state(db, bot_id) or {}
                skip_immediate = is_conn_resume and bool(st.get("initial_allocation_done"))
                if not skip_immediate:
                    try:
                        from app.botengine.bot_run import run_one_bot_tick
                        await run_one_bot_tick(bot_id, f"cmd{cmd_id}_immediate")
                        logger.info("WORKER_FIRST_TICK_EXECUTED bot_id=%s (initial allocation submitted)", bot_id)
                    except Exception as tick_err:
                        logger.info(
                            "WORKER_FIRST_TICK_FAILED bot_id=%s err=%s (scheduler will retry)",
                            bot_id, tick_err,
                        )
            else:
                st_pre = load_state(db, bot_id) or {}
                conn_resume = False
                try:
                    from app.botengine.bot_session import is_connectivity_resume_start

                    conn_resume = is_connectivity_resume_start(cmd_payload, st_pre)
                except Exception:
                    pass
                await start_bot(bot_id, db, connectivity_resume=conn_resume)
                mark_command_done(db, cmd_id)
                logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=START", cmd_id, bot_id)
                start_meta = _command_event_meta(bot_id)
                is_conn_resume = bool(start_meta.get("connectivity_resume"))
                if not is_conn_resume:
                    try:
                        append_event(
                            db, bot_id, account_id, "INFO",
                            f"COMMAND_EXECUTED command_id={cmd_id} START", start_meta,
                        )
                    except Exception:
                        pass
                st = load_state(db, bot_id) or {}
                skip_immediate = is_conn_resume and bool(st.get("initial_allocation_done"))
                if not skip_immediate:
                    try:
                        from app.botengine.bot_run import run_one_bot_tick
                        await run_one_bot_tick(bot_id, f"cmd{cmd_id}_immediate")
                        logger.info("WORKER_FIRST_TICK_EXECUTED bot_id=%s (initial allocation submitted)", bot_id)
                    except Exception as tick_err:
                        logger.info(
                            "WORKER_FIRST_TICK_FAILED bot_id=%s err=%s (loop will retry)",
                            bot_id, tick_err,
                        )
        elif command == "STOP":
            if v5_scheduler:
                v5_scheduler.unregister_bot(bot_id)
            await stop_bot(bot_id, db)
            mark_command_done(db, cmd_id)
            logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=STOP", cmd_id, bot_id)
            try:
                append_event(db, bot_id, account_id, "INFO", f"COMMAND_EXECUTED command_id={cmd_id} STOP", _command_event_meta(bot_id))
            except Exception:
                pass
        else:
            mark_command_done(db, cmd_id, error_code="UNKNOWN_COMMAND")
            logger.warning("WORKER_COMMAND_UNKNOWN command_id=%s command=%s", cmd_id, command)
    except Exception as e:
        import uuid
        error_id = str(uuid.uuid4())
        logger.exception("WORKER_COMMAND_FAILED command_id=%s bot_id=%s err=%s", cmd_id, bot_id, e)
        mark_command_done(db, cmd_id, error_code="COMMAND_FAILED", error_id=error_id)
        try:
            append_event(db, bot_id, account_id, "ERROR", f"COMMAND_FAILED {error_id} {e}",
                        {"command_id": cmd_id, "command": command, "error_code": "COMMAND_FAILED", "error_id": error_id})
        except Exception:
            pass


def _get_running_bot_ids(db) -> List[int]:
    from app.db.models import Bot
    return [b.id for b in db.query(Bot).filter(Bot.status == "running").all()]


async def _reconciler_background_task():
    """Periodic reconcile every 45s per account with non-final intents."""
    from app.botengine.reconcile import reconcile_account
    from app.botengine.intent_ledger import get_non_final_intents_for_account
    from app.services.binance_assets import get_account_keys
    from app.botengine.adapters.binance_adapter import BinanceAdapter
    from app.services.binance_spot import is_ip_banned
    interval = 45
    while True:
        await asyncio.sleep(interval)
        if is_ip_banned():
            continue
        try:
            db = _get_db()
            try:
                from sqlalchemy import text
                rows = db.execute(text(
                    "SELECT DISTINCT account_id FROM order_intents WHERE status NOT IN ('FILLED','CANCELED','REJECTED','FINAL')"
                )).fetchall()
                for (aid,) in rows:
                    try:
                        keys = await get_account_keys(aid, db)
                        if not keys:
                            continue
                        adapter = BinanceAdapter(aid, keys, paper_mode=False)
                        async def _get_all_orders(sym=None, limit=20, _adapter=adapter):
                            s = (sym or "").strip().upper()
                            if not s:
                                return []
                            return await _adapter.get_all_orders(s, limit)

                        await reconcile_account(
                            aid,
                            lambda sym=None: adapter.get_open_orders(sym),
                            _get_all_orders,
                            lambda sym, coid: adapter.get_order_by_client_order_id(sym, coid),
                            db,
                        )
                    except Exception as e:
                        logger.debug("reconciler account_id=%s err=%s", aid, e)
            finally:
                db.close()
        except Exception as e:
            logger.warning("reconciler_background err=%s", e)


def _running_bot_symbols() -> list:
    """Çalışan botların sembolleri — worker slim cache'te asla düşmesin."""
    from app.db.session import SessionLocal
    from app.db.models import Bot

    db = SessionLocal()
    try:
        rows = db.query(Bot.symbol).filter(Bot.status == "running").all()
        return sorted({(r[0] or "").strip().upper() for r in rows if r and r[0] and (r[0] or "").upper() != "MULTI"})
    except Exception:
        return []
    finally:
        db.close()


async def _market_sync_from_web_loop():
    """Worker: web sürecindeki DataHub cache'ini kopyala — tek Binance WS/REST web'de."""
    import httpx
    from app.services.market_data import import_from_peer_snapshot
    from app.services.data_hub import data_hub
    base = os.getenv("WEB_INTERNAL_URL", "http://127.0.0.1:8000").rstrip("/")
    interval = float(os.getenv("MARKET_SYNC_INTERVAL_SEC", "2"))
    failures = 0
    while True:
        try:
            syms = _running_bot_symbols()
            if syms:
                data_hub.pin_symbols(syms)
            params: dict = {"slim": 1}
            if syms:
                params["symbols"] = ",".join(syms)
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base}/api/data/prices", params=params)
            if r.status_code == 200:
                import_from_peer_snapshot(r.json())
                failures = 0
            else:
                failures += 1
        except Exception:
            failures += 1
        if failures >= 12 and os.getenv("WORKER_WS_FALLBACK", "0").strip() == "1":
            if not getattr(data_hub, "_ws_started", False):
                data_hub.start_ws(testnet=False)
                logger.warning("WORKER_MARKET_SYNC web unreachable — WS fallback (opt-in)")
        await asyncio.sleep(interval)


async def worker_loop():
    from app.botengine.orchestrator import ensure_running_bots, cancel_orchestrator_loop

    _run_schema_guard()
    logger.info("WORKER_START pid=%s", os.getpid())

    use_v5_scheduler = os.getenv("BOT_ENGINE_V5_SCHEDULER", "").strip() == "1"

    # Worker: piyasa verisi web DataHub'dan (SSOT); REST/WS yalnızca web leader'da.
    try:
        from app.services.data_hub import data_hub
        from app.services.binance_rest_log import start_rest_log_flush_task
        sync_from_web = os.getenv("MARKET_SYNC_FROM_WEB", "1").strip() == "1"
        if sync_from_web:
            asyncio.create_task(_market_sync_from_web_loop())
            await asyncio.sleep(2.5)
        elif os.getenv("DATAHUB_REST_IN_WORKER", "0").strip() == "1":
            data_hub.start_background_updates()
            data_hub.start_ws(testnet=False)
            await asyncio.sleep(2.0)
            await data_hub.warmup(timeout_sec=8.0)
        else:
            data_hub.start_ws(testnet=False)
            await asyncio.sleep(3.0)
        start_rest_log_flush_task()
        logger.info(
            "WORKER_MARKET prices_count=%s sync_from_web=%s ws=%s",
            len(getattr(data_hub, "prices", {})),
            sync_from_web,
            getattr(data_hub, "ws_status", "?"),
        )
    except Exception as e:
        logger.warning("WORKER_MARKET_START failed: %s", e)

    v5_scheduler = None
    if use_v5_scheduler:
        from app.botengine.scheduler import BotScheduler
        from app.botengine.bot_run import run_one_bot_tick
        from app.services.binance_weight import get_weight_used_last_60s, BINANCE_WEIGHT_LIMIT_PER_MIN
        v5_scheduler = BotScheduler()
        def _weight_check():
            used = get_weight_used_last_60s(None, None)
            return (used / BINANCE_WEIGHT_LIMIT_PER_MIN, BINANCE_WEIGHT_LIMIT_PER_MIN)
        v5_scheduler._weight_check = _weight_check
        async def _run_cb(bot_id: int, tick_id: str):
            return await run_one_bot_tick(bot_id, tick_id)
        v5_scheduler.register_run_callback(_run_cb)
        db2 = _get_db()
        try:
            for bid in _get_running_bot_ids(db2):
                cancel_orchestrator_loop(bid)
                v5_scheduler.register_bot(bid, time.monotonic())
        finally:
            db2.close()
        asyncio.create_task(_reconciler_background_task())
        asyncio.create_task(v5_scheduler.run_loop())
        logger.info("WORKER_V5_SCHEDULER_STARTED")
    else:
        db = _get_db()
        try:
            await ensure_running_bots(db)
        finally:
            db.close()

    heartbeat_interval = 60  # log WORKER_HEARTBEAT every 60s to avoid log spam
    command_poll_interval = 1.0
    last_heartbeat = 0
    loop_count = 0
    _worker_main_loop_count_file = _RUN_DIR / "worker_main_loop_count"

    global _ENGINE_LAST_TICK_TS, _ENGINE_LAST_PENDING_LEN, _ENGINE_METRICS_LOOP_COUNT
    while True:
        loop_count += 1
        _ENGINE_LAST_TICK_TS = time.time()
        _ENGINE_METRICS_TICK_TIMES.append(_ENGINE_LAST_TICK_TS)
        try:
            _RUN_DIR.mkdir(parents=True, exist_ok=True)
            _worker_main_loop_count_file.write_text(str(loop_count), encoding="utf-8")
        except OSError:
            pass
        try:
            db = _get_db()
            try:
                reset_stale_processing_commands(db)
                pending = fetch_pending_commands(db, limit=50)
                _ENGINE_LAST_PENDING_LEN = len(pending) if pending else 0
                if pending:
                    logger.info("WORKER_POLL fetched %s command(s) bot_ids=%s",
                                len(pending), [c.get("bot_id") for c in pending])
                for cmd in pending:
                    if not mark_command_processing(db, cmd["id"]):
                        continue
                    try:
                        await process_command(cmd, db, v5_scheduler=v5_scheduler)
                    except Exception as e:
                        logger.exception("process_command cmd_id=%s: %s", cmd["id"], e)
                        mark_command_done(db, cmd["id"], error_code="PROCESS_EXCEPTION")

                if loop_count % (heartbeat_interval * int(1 / command_poll_interval)) == 0:
                    from app.botengine.orchestrator import _tasks
                    n_bots = len(_tasks) if not v5_scheduler else len(v5_scheduler._registered)
                    n_pending = len(pending) if pending else 0
                    logger.debug("WORKER_HEARTBEAT active_bots=%s pending_commands=%s", n_bots, n_pending)
                    try:
                        (_RUN_DIR / "worker_active_bots").write_text(str(n_bots), encoding="utf-8")
                    except OSError:
                        pass
                    last_heartbeat = loop_count

                if loop_count % (10 * int(1 / command_poll_interval)) == 0 and loop_count > 0:
                    if v5_scheduler:
                        db2 = _get_db()
                        try:
                            for bid in _get_running_bot_ids(db2):
                                if bid not in v5_scheduler._registered:
                                    v5_scheduler.register_bot(bid, time.monotonic())
                        finally:
                            db2.close()
                    else:
                        await ensure_running_bots(db)

                # IP/API düzelince paused_error botları otomatik devam (probe + START).
                # Aktif Binance hatası varken daha sık kontrol et (hızlı toparlanma).
                try:
                    from app.services.binance_connectivity import active_failure as _af
                    from app.db.models import Bot as _BotM
                    _any_fail = any(
                        _af(int(aid))
                        for (aid,) in db.query(_BotM.account_id).distinct().all()
                        if aid
                    )
                except Exception:
                    _any_fail = False
                _resume_target_sec = 15 if _any_fail else 60
                auto_resume_interval = max(5, int(_resume_target_sec / command_poll_interval))
                if loop_count % auto_resume_interval == 0 and loop_count > 0:
                    try:
                        from app.services.binance_connectivity import run_connectivity_auto_resume_pass

                        n_ar = await run_connectivity_auto_resume_pass(db)
                        if n_ar:
                            logger.info("WORKER_CONNECTIVITY_AUTO_RESUME resumed=%s", n_ar)
                    except Exception as ar_err:
                        logger.debug("WORKER_CONNECTIVITY_AUTO_RESUME: %s", ar_err)

                # Grafik: bot detay sayfası kapalıyken de çalışan botlar için periyodik örnek (worker'da yazılsın)
                perf_sample_interval = 60  # saniyede bir döngü, 60 döngüde bir = ~60 sn
                if loop_count % perf_sample_interval == 0 and loop_count > 0:
                    try:
                        from app.db.models import Bot
                        from app.api.bots_engine import append_perf_chart_sample
                        _db = _get_db()
                        try:
                            running = _db.query(Bot).filter(Bot.status == "running").all()
                            for b in running:
                                try:
                                    append_perf_chart_sample(_db, b.id)
                                except Exception:
                                    pass
                        finally:
                            _db.close()
                    except Exception as e:
                        logger.debug("worker perf_chart_sample: %s", e)
                    try:
                        from app.botengine.health_watch import run_all_bot_health_checks
                        _db_h = _get_db()
                        try:
                            run_all_bot_health_checks(_db_h)
                        finally:
                            _db_h.close()
                    except Exception as e:
                        logger.debug("worker health_watch: %s", e)
            finally:
                db.close()
        except Exception as e:
            global _ENGINE_LAST_ERROR_TS
            _ENGINE_LAST_ERROR_TS = time.time()
            logger.exception("worker_loop iteration: %s", e)

        # Manager v3: write engine.metrics.json every ~2s (atomic)
        _ENGINE_METRICS_LOOP_COUNT += 1
        if _ENGINE_METRICS_LOOP_COUNT % 2 == 0:
            try:
                now = time.time()
                n_bots = 0
                try:
                    if v5_scheduler:
                        n_bots = len(v5_scheduler._registered)
                    else:
                        from app.botengine.orchestrator import _tasks
                        n_bots = len(_tasks)
                except Exception:
                    pass
                tick_rate_10s = sum(1 for t in _ENGINE_METRICS_TICK_TIMES if t >= now - 10)
                ticks_last_60m = sum(1 for t in _ENGINE_METRICS_TICK_TIMES if t >= now - 3600)
                last_tick_age = (now - _ENGINE_LAST_TICK_TS) if _ENGINE_LAST_TICK_TS else None
                snap = {
                    "pid": os.getpid(),
                    "active_bots": n_bots,
                    "last_tick_ts": _ENGINE_LAST_TICK_TS,
                    "last_tick_age_s": round(last_tick_age, 1) if last_tick_age is not None else None,
                    "tick_rate_10s": tick_rate_10s,
                    "ticks_last_60m": ticks_last_60m,
                    "pending_jobs": _ENGINE_LAST_PENDING_LEN,
                    "queue_len": _ENGINE_LAST_PENDING_LEN,
                    "open_orders": 0,
                    "safe_stop_count": 0,
                    "last_error_ts": _ENGINE_LAST_ERROR_TS,
                    "ts": round(now, 2),
                }
                tmp = _RUN_DIR / "engine.metrics.json.tmp"
                p = _RUN_DIR / "engine.metrics.json"
                tmp.write_text(json.dumps(snap, indent=2), encoding="utf-8")
                tmp.replace(p)
            except Exception as ex:
                logger.debug("engine_metrics write: %s", ex)

        await asyncio.sleep(command_poll_interval)


def main():
    try:
        _RUN_DIR.joinpath("worker.started_at").write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass
    # RAM capture (5 dk) veya RAM_PROBE
    if os.getenv("RAM_CAPTURE", "").strip() == "1":
        try:
            os.environ.setdefault("RAM_PROBE", "1")
            from app.observability.ram_capture import (
                register_default_capture_hooks,
                start_ram_capture_session,
            )

            register_default_capture_hooks("worker")
            start_ram_capture_session("worker")
        except Exception as e:
            logger.debug("RAM capture start skipped: %s", e)
    elif os.getenv("RAM_PROBE") == "1":
        try:
            from app.observability.ram_probe import start_ram_probe, register_probe_hook, write_snapshot_now
            interval = int(os.getenv("RAM_PROBE_INTERVAL", "30"))
            start_ram_probe(component="worker", interval_sec=interval)
            write_snapshot_now("worker", reason="startup")
            # Hooks for snapshot (run in probe thread)
            def hook_active_bots():
                try:
                    from app.botengine.orchestrator import _tasks
                    return {"active_bots": len(_tasks)}
                except Exception:
                    return {"active_bots": "NOT_FOUND"}
            def hook_active_tasks():
                try:
                    loop = asyncio.get_running_loop()
                    return {"active_tasks": len(asyncio.all_tasks(loop))}
                except RuntimeError:
                    return {"active_tasks": "NA"}
                except Exception:
                    return {"active_tasks": "NOT_FOUND"}
            def hook_ws_connections():
                try:
                    from app.services.binance_ws import _ws_connections
                    return {"ws_connections": len(_ws_connections)}
                except Exception:
                    return {"ws_connections": "NOT_FOUND"}
            def hook_cache_sizes():
                try:
                    from app.services.data_hub import data_hub
                    return {"prices_len": len(getattr(data_hub, "prices", [])), "all_symbols_len": len(getattr(data_hub, "all_symbols", []))}
                except Exception:
                    return {"cache_sizes": "NOT_FOUND"}
            register_probe_hook("active_bots", hook_active_bots)
            register_probe_hook("active_tasks", hook_active_tasks)
            register_probe_hook("ws_connections", hook_ws_connections)
            register_probe_hook("cache_sizes", hook_cache_sizes)
        except Exception as e:
            logger.debug("RAM probe start skipped: %s", e)
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
