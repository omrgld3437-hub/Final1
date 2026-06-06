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
_ENGINE_METRICS_TICK_TIMES: deque = deque(maxlen=20)  # last ~10s of tick timestamps
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
    from app.botengine.state_store import append_event
    from app.botengine.orchestrator import start_bot, stop_bot
    from app.db.models import Bot

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
                bot = db.query(Bot).filter(Bot.id == bot_id).first()
                if bot:
                    bot.status = "running"
                    bot.started_at = datetime.now(timezone.utc)
                    db.commit()
                v5_scheduler.register_bot(bot_id, time.monotonic())
                mark_command_done(db, cmd_id)
                logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=START (v5 registered)", cmd_id, bot_id)
                try:
                    append_event(db, bot_id, account_id, "INFO", f"COMMAND_EXECUTED command_id={cmd_id} START", {"command_id": cmd_id, "command": "START"})
                except Exception:
                    pass
                # İlk alımı hemen yap: ilk tick'i komut işlerken çalıştır (kullanıcı "Oluştur" deyince anında market alım)
                try:
                    from app.botengine.bot_run import run_one_bot_tick
                    await run_one_bot_tick(bot_id, f"cmd{cmd_id}_immediate")
                    logger.info("WORKER_FIRST_TICK_EXECUTED bot_id=%s (initial allocation submitted)", bot_id)
                except Exception as tick_err:
                    logger.warning("WORKER_FIRST_TICK_FAILED bot_id=%s err=%s (scheduler will retry)", bot_id, tick_err)
            else:
                await start_bot(bot_id, db)
                mark_command_done(db, cmd_id)
                logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=START", cmd_id, bot_id)
                try:
                    append_event(db, bot_id, account_id, "INFO", f"COMMAND_EXECUTED command_id={cmd_id} START", {"command_id": cmd_id, "command": "START"})
                except Exception:
                    pass
                # İlk alımı hemen yap: ilk tick'i komut işlerken çalıştır
                try:
                    from app.botengine.bot_run import run_one_bot_tick
                    await run_one_bot_tick(bot_id, f"cmd{cmd_id}_immediate")
                    logger.info("WORKER_FIRST_TICK_EXECUTED bot_id=%s (initial allocation submitted)", bot_id)
                except Exception as tick_err:
                    logger.warning("WORKER_FIRST_TICK_FAILED bot_id=%s err=%s (loop will retry)", bot_id, tick_err)
        elif command == "STOP":
            if v5_scheduler:
                v5_scheduler.unregister_bot(bot_id)
            await stop_bot(bot_id, db)
            mark_command_done(db, cmd_id)
            logger.info("WORKER_COMMAND_EXECUTED command_id=%s bot_id=%s command=STOP", cmd_id, bot_id)
            try:
                append_event(db, bot_id, account_id, "INFO", f"COMMAND_EXECUTED command_id={cmd_id} STOP", {"command_id": cmd_id, "command": "STOP"})
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
    interval = 45
    while True:
        await asyncio.sleep(interval)
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
                        await reconcile_account(
                            aid,
                            lambda sym=None: adapter.get_open_orders(sym),
                            lambda sym=None, limit=20: adapter.get_all_orders(sym or "BTCUSDT", limit),
                            lambda sym, coid: adapter.get_order_by_client_order_id(sym, coid),
                            db,
                        )
                    except Exception as e:
                        logger.debug("reconciler account_id=%s err=%s", aid, e)
            finally:
                db.close()
        except Exception as e:
            logger.warning("reconciler_background err=%s", e)


async def worker_loop():
    from app.botengine.orchestrator import ensure_running_bots

    _run_schema_guard()
    logger.info("WORKER_START pid=%s", os.getpid())

    # Worker ayrı proses; DataHub fiyatları sadece web startup'ta dolduruluyordu. Burada da başlat ki BOT_TICK_PRICE_MISSING olmasın.
    try:
        from app.services.data_hub import data_hub
        data_hub.start_background_updates()
        await asyncio.sleep(2.0)
        await data_hub.warmup(timeout_sec=8.0)
        logger.info("WORKER_DATAHUB_WARMUP prices_count=%s", len(getattr(data_hub, "prices", {})))
    except Exception as e:
        logger.warning("WORKER_DATAHUB_START failed (bot fiyatları gecikebilir): %s", e)

    db = _get_db()
    try:
        await ensure_running_bots(db)
    finally:
        db.close()

    use_v5_scheduler = os.getenv("BOT_ENGINE_V5_SCHEDULER", "").strip() == "1"
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
                v5_scheduler.register_bot(bid, time.monotonic())
        finally:
            db2.close()
        asyncio.create_task(_reconciler_background_task())
        asyncio.create_task(v5_scheduler.run_loop())
        logger.info("WORKER_V5_SCHEDULER_STARTED")

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
                last_tick_age = (now - _ENGINE_LAST_TICK_TS) if _ENGINE_LAST_TICK_TS else None
                snap = {
                    "active_bots": n_bots,
                    "last_tick_ts": _ENGINE_LAST_TICK_TS,
                    "last_tick_age_s": round(last_tick_age, 1) if last_tick_age is not None else None,
                    "tick_rate_10s": tick_rate_10s,
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
    # RAM probe: JSONL to logs/ram_snapshots.log when RAM_PROBE=1 (inherit from parent; helper must not override)
    if os.getenv("RAM_PROBE") == "1":
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
