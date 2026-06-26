"""
Orchestrator: per-bot asyncio tasks, start/stop, crash recovery.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Log sayfası "Toplam istek": her BOT_LOOP_START'ta sayacı artırıp .run/worker_loop_count'a yazarız; Manager bu dosyadan okur
_WORKER_LOOP_COUNT_FILE = (
    Path(__file__).resolve().parents[2] / ".run" / "worker_loop_count"
)
_worker_loop_count = 0
_worker_loop_count_loaded = False


def _load_worker_loop_count_from_file() -> None:
    """İlk engine çalışmasında sayacı dosyadan yükle (yeniden başlamalarda kümülatif kalsın)."""
    global _worker_loop_count, _worker_loop_count_loaded
    if _worker_loop_count_loaded:
        return
    _worker_loop_count_loaded = True
    if _WORKER_LOOP_COUNT_FILE.exists():
        try:
            s = _WORKER_LOOP_COUNT_FILE.read_text(encoding="utf-8").strip()
            if s.isdigit():
                _worker_loop_count = int(s)
        except (OSError, ValueError):
            pass


def _write_worker_loop_count() -> None:
    """Mevcut döngü sayısını .run/worker_loop_count dosyasına yaz (Manager okur)."""
    try:
        _WORKER_LOOP_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_LOOP_COUNT_FILE.write_text(str(_worker_loop_count), encoding="utf-8")
    except OSError:
        pass


from sqlalchemy.orm import Session
from sqlalchemy import text

from app.botengine.adapters.binance_adapter import BinanceAdapter
from app.botengine.execution import run_actions
from app.botengine.locks import (
    release_symbol_lock,
    try_acquire_symbol_lock,
    renew_symbol_lock,
    lease_still_valid,
    trade_lock_symbol,
    HEARTBEAT_RENEWAL_INTERVAL_SEC,
)
from app.botengine.models import (
    DcaGridTrailingConfig,
    TrdcaProConfig,
    config_multi_asset_from_payload,
    config_trdca_pro_from_payload,
    build_trdca_pro_state_skeleton,
)
from app.botengine.state_store import (
    append_event,
    ensure_state_row,
    get_events_diagnostic_summary,
    load_state,
    save_state,
    flush_queued_events,
)
from app.botengine.strategies.registry import get_strategy_safe
from app.botengine.strategies.trdca_pro import strategy_tick as trdca_strategy_tick
from app.botengine.virtual_wallet import (
    ensure_virtual_wallet,
    get_virtual_wallet,
    sync_virtual_wallet_from_state,
)
from app.services.pnl_service import ensure_daily_ref_and_compute
from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.utils.tz_utils import turkey_today_date_str

logger = logging.getLogger(__name__)


def _emit_cycle_hold_event(state: Dict[str, Any], verdict, *, holding: bool) -> None:
    """Queue a bot-detail engine event when the cycle-entry risk gate starts or
    releases a hold, so the operator sees "yeni tur risk nedeniyle bekletiliyor".
    Best-effort: never raises."""
    try:
        from app.botengine.state_store import queue_engine_event

        if holding:
            queue_engine_event(
                state,
                "DYN_CYCLE_HOLD",
                "Yeni tur risk nedeniyle bekletiliyor — "
                f"risk={verdict.risk_score:.2f}, rejim={verdict.regime}. "
                f"{verdict.clear_hint}",
                {
                    "cycle_id": state.get("cycle_id"),
                    "risk_score": round(verdict.risk_score, 4),
                    "regime": verdict.regime,
                    "reasons": verdict.reasons[:6],
                    "breakdown": verdict.breakdown,
                    "clear_hint": verdict.clear_hint,
                },
            )
        else:
            queue_engine_event(
                state,
                "DYN_CYCLE_RELEASE",
                "Risk geçti — yeni tur serbest bırakıldı "
                f"(risk={verdict.risk_score:.2f}, sebep={verdict.released_reason}).",
                {
                    "cycle_id": state.get("cycle_id"),
                    "risk_score": round(verdict.risk_score, 4),
                    "released_reason": verdict.released_reason,
                    "regime": verdict.regime,
                },
            )
    except Exception as _ev_err:  # pragma: no cover
        logger.debug("DYN_CYCLE_HOLD event_queue failed: %s", _ev_err)


_tasks: Dict[int, asyncio.Task] = {}
_stop_requested: Set[int] = set()
_reconcile_last_ts: Dict[int, float] = {}
_config_cache: Dict[
    int, object
] = {}  # DcaGridTrailingConfig | MultiAssetRebalanceConfig
_CONFIG_CACHE_MAX = 64
_task_create_lock = asyncio.Lock()
_bot_diag_logged: Set[int] = set()


def _config_cache_put(bot_id: int, cfg: object) -> None:
    if bot_id not in _config_cache and len(_config_cache) >= _CONFIG_CACHE_MAX:
        try:
            _config_cache.pop(next(iter(_config_cache)))
        except StopIteration:
            pass
    _config_cache[bot_id] = cfg


def invalidate_config_cache(bot_id: int) -> None:
    """Clear cached config for bot (e.g. after update-config). Next tick will load fresh from DB."""
    _config_cache.pop(bot_id, None)


_loop_instances: Dict[int, str] = {}  # bot_id -> loop_instance_id
_engine_tick_task: Optional[asyncio.Task] = None
# Throttle noisy events: "no price" / PRICE_STALE_OR_MISSING at most once per 5 min per bot
_last_stale_event_ts: Dict[int, float] = {}
_STALE_EVENT_THROTTLE_SEC = 300


async def _engine_tick_loop() -> None:
    """Heartbeat + per ~60s ensure running bots (restart crashed loops while DB status=running)."""
    tick_count = 0
    logged_zero_once = False
    while True:
        await asyncio.sleep(5)
        n = len(_tasks)
        tick_count += 1
        if tick_count % 12 == 0:
            db = None
            try:
                db = _get_db()
                await ensure_running_bots(db, recovery_source="engine_tick")
            except Exception as tick_err:
                logger.debug("ENGINE_TICK ensure_running_bots: %s", tick_err)
            finally:
                if db is not None:
                    db.close()
        if n > 0:
            logged_zero_once = False
            if tick_count % 12 == 0:
                logger.debug("ENGINE_TICK active_bots=%s", n)
        else:
            if not logged_zero_once:
                logger.debug("ENGINE_TICK active_bots=0")
                logged_zero_once = True


def _get_db():
    from app.db.session import SessionLocal

    db = SessionLocal()
    # DB session tracking
    session_id = id(db)
    try:
        conn_id = id(db.connection()) if hasattr(db, "connection") else None
        bind_info = str(db.get_bind()) if hasattr(db, "get_bind") else None
    except Exception:
        conn_id = None
        bind_info = None
    logger.debug(
        "BOT_DB_SESSION session_id=%s conn_id=%s bind=%s",
        session_id,
        conn_id,
        bind_info,
    )
    return db


def _apply_fills_to_virtual_balances(
    balances: Dict[str, float],
    fills: List[Dict[str, Any]],
    quote_asset: str,
) -> Dict[str, float]:
    """Paper mode: apply simulated fills to balances. Mutates and returns balances."""
    out = dict(balances)
    for f in fills or []:
        sym = (f.get("symbol") or "").upper()
        side = (f.get("side") or "BUY").upper()
        qty = float(
            f.get("filled_qty") or f.get("executedQty") or f.get("fill_qty") or 0
        )
        quote_val = float(f.get("filled_quote") or f.get("cummulativeQuoteQty") or 0)
        if not sym or qty <= 0:
            continue
        base = sym.replace(quote_asset, "") if quote_asset in sym else sym
        if side == "BUY":
            out[quote_asset] = out.get(quote_asset, 0) - quote_val
            out[base] = out.get(base, 0) + qty
        else:
            out[base] = out.get(base, 0) - qty
            out[quote_asset] = out.get(quote_asset, 0) + quote_val
    return out


async def _build_trdca_snapshot(
    adapter: BinanceAdapter,
    state: Dict[str, Any],
    cfg: TrdcaProConfig,
) -> Dict[str, Any]:
    """Build snapshot for TRDCA strategy: ts, balances_free, prices_last, filters, open_order, fills."""
    ts_ms = int(time.time() * 1000)
    quote_asset = getattr(cfg, "quote_asset", "USDT")
    assets = set()
    for k in getattr(cfg, "dca_coin_weights", {}).keys():
        if k != quote_asset:
            assets.add(k)
    for k in getattr(cfg, "trb_target_weights_all", {}).keys():
        if k != quote_asset:
            assets.add(k)
    assets.add(quote_asset)
    # Paper mode: virtual_balances varsa kullan; yoksa initial_capital ile başlat (config'teki bütçe)
    if adapter.paper_mode and state.get("virtual_balances"):
        vb = state["virtual_balances"]
        initial = float(getattr(cfg, "initial_capital_usdt", 0) or 0)
        try:
            from app.services.test_account import TEST_PAPER_BALANCE_USDT

            # Eski default (10k) düzelt: allocation yoksa initial_capital kullan
            if (
                initial > 0
                and float(vb.get(quote_asset) or 0) == TEST_PAPER_BALANCE_USDT
            ):
                base_sum = sum(
                    float(vb.get(a) or 0) for a in assets if a != quote_asset
                )
                if base_sum == 0:
                    balances_free = {
                        a: (initial if a == quote_asset else 0.0) for a in assets
                    }
                else:
                    balances_free = {a: float(vb.get(a) or 0) for a in assets}
            else:
                balances_free = {a: float(vb.get(a) or 0) for a in assets}
        except Exception:
            balances_free = {a: float(vb.get(a) or 0) for a in assets}
    elif adapter.paper_mode:
        initial = float(
            getattr(cfg, "initial_capital_usdt", 0)
            or getattr(cfg, "bot_budget_usdt", 0)
            or 0
        )
        if initial <= 0:
            from app.services.test_account import TEST_PAPER_BALANCE_USDT

            initial = float(TEST_PAPER_BALANCE_USDT)
        balances_free = {a: (initial if a == quote_asset else 0.0) for a in assets}
    else:
        # Gerçek hesap: belirlenen bakiye (initial_capital_usdt) ile sınırla
        balances = await adapter.get_account_balances()
        balances_free = {}
        for a in assets:
            b = balances.get(a) or {}
            balances_free[a] = float(b.get("free") or 0)
        # initial_capital > 0 ise efektif bakiye bu tutarla sınırlanır
        initial = float(getattr(cfg, "initial_capital_usdt", 0) or 0)
        if initial > 0:
            prices_tmp = {}
            for a in assets:
                if a == quote_asset:
                    prices_tmp[a] = 1.0
                else:
                    sym = f"{a}{quote_asset}"
                    p = adapter.get_price(sym)
                    if p is not None and float(p) > 0:
                        prices_tmp[a] = float(p)
                    else:
                        prices_tmp[a] = 0.0
            actual_total = sum(
                balances_free.get(a, 0) * prices_tmp.get(a, 0) for a in assets
            )
            if actual_total > initial:
                scale = initial / actual_total
                for a in assets:
                    balances_free[a] = balances_free.get(a, 0) * scale
    symbols = [f"{a}{quote_asset}" for a in assets if a != quote_asset]
    prices_last = {quote_asset: 1.0}
    for a in assets:
        if a == quote_asset:
            continue
        sym = f"{a}{quote_asset}"
        p = adapter.get_price(sym)
        if p is not None and float(p) > 0:
            prices_last[a] = float(p)
            prices_last[sym] = float(p)
    filters = {}
    for sym in symbols:
        f = await adapter.get_symbol_filters(sym)
        step = float(f.get("step_size") or f.get("stepSize") or 0.00001)
        min_qty = float(f.get("min_qty") or f.get("minQty") or step)
        mn = float(f.get("min_notional") or f.get("minNotional") or DEFAULT_MIN_NOTIONAL_USDT)
        filters[sym] = {"minQty": min_qty, "stepSize": step, "minNotional": mn}
    open_orders = await adapter.get_open_orders(symbol=None)
    open_order = None
    for o in open_orders or []:
        sym = (o.get("symbol") or "").upper()
        if sym in symbols:
            open_order = {
                "client_order_id": o.get("clientOrderId") or "",
                "status": o.get("status") or "NEW",
            }
            break
    fills = state.pop("_pending_fills", [])
    return {
        "ts": ts_ms,
        "balances_free": balances_free,
        "prices_last": prices_last,
        "filters": filters,
        "open_order": open_order,
        "fills": fills if fills else None,
    }


async def _bot_loop(bot_id: int) -> None:
    """Single-bot loop: load state -> price -> strategy -> execution -> save -> sleep."""
    loop_instance_id = str(uuid.uuid4())[:8]
    process_id = os.getpid()
    _loop_instances[bot_id] = loop_instance_id
    logger.info(
        "BOT_LOOP_START bot_id=%s loop=%s pid=%s", bot_id, loop_instance_id, process_id
    )
    global _worker_loop_count
    _worker_loop_count += 1
    _write_worker_loop_count()

    bot = None
    account_id = 0
    symbol = ""
    try:
        from app.db.models import Bot

        db = _get_db()
        try:
            bot = db.query(Bot).filter(Bot.id == bot_id).first()
            if not bot:
                logger.warning("bot_engine loop bot_id=%s not found", bot_id)
                return
            account_id = bot.account_id
            from app.botengine.symbols import normalize_bot_trading_symbol

            raw_sym = (bot.symbol or "").upper()
            symbol = normalize_bot_trading_symbol(raw_sym)
            if symbol != raw_sym:
                logger.info(
                    "BOT_SYMBOL_HEAL bot_id=%s %s -> %s", bot_id, raw_sym, symbol
                )
                bot.symbol = symbol
                try:
                    cfg_raw = json.loads(bot.config_json or "{}")
                    if cfg_raw.get("symbol"):
                        cfg_raw["symbol"] = symbol
                        bot.config_json = json.dumps(cfg_raw, ensure_ascii=False)
                except Exception:
                    pass
                db.commit()
            ensure_state_row(db, bot_id, account_id, symbol)
            if bot_id not in _bot_diag_logged:
                _bot_diag_logged.add(bot_id)
                try:
                    diag = get_events_diagnostic_summary(db, bot_id, limit=40)
                    logger.info(
                        "BOT_TEŞHIS_DUMP bot_id=%s total_events=%s by_type=%s skip_reasons=%s",
                        bot_id,
                        diag.get("total", 0),
                        diag.get("by_type") or {},
                        diag.get("skip_reasons") or {},
                    )
                    for le in (diag.get("last_events") or [])[:5]:
                        logger.info(
                            "BOT_TEŞHIS_EVENT id=%s type=%s message=%s",
                            le.get("id"),
                            le.get("type"),
                            (le.get("message") or "")[:200],
                        )
                except Exception as diag_err:
                    logger.warning("BOT_TEŞHIS_DUMP bot_id=%s err=%s", bot_id, diag_err)
        finally:
            db.close()

        tick_count = 0
        while bot_id not in _stop_requested:
            db = _get_db()
            paper_mode = False
            try:
                row = db.query(Bot).filter(Bot.id == bot_id).first()
                status_lower = (str(row.status or "").lower()) if row else ""
                if not row or status_lower != "running":
                    break
                raw = json.loads(row.config_json or "{}")
                strategy_id_raw = (raw.get("strategy_id") or "").strip().lower()
                is_multi = strategy_id_raw == "multi_asset_rebalance"
                is_trdca = strategy_id_raw == "trdca_pro"
                if is_trdca:
                    cfg = _config_cache.get(bot_id) or config_trdca_pro_from_payload(
                        raw
                    )
                    symbol = "MULTI"
                else:
                    cfg = _config_cache.get(bot_id) or (
                        config_multi_asset_from_payload(raw)
                        if is_multi
                        else DcaGridTrailingConfig(raw)
                    )
                _config_cache_put(bot_id, cfg)
                state = load_state(db, bot_id)
                if not state:
                    if is_trdca:
                        state = build_trdca_pro_state_skeleton(
                            bot_id, account_id, getattr(cfg, "quote_asset", "USDT")
                        )
                    else:
                        state = {
                            "bot_id": bot_id,
                            "account_id": account_id,
                            "symbol": symbol,
                            "status": "running",
                            "cycle_id": 1,
                            "state_version": 0,
                        }
                    save_state(db, bot_id, account_id, state)
                elif is_trdca and (
                    state.get("dca") is None or state.get("trb") is None
                ):
                    sk = build_trdca_pro_state_skeleton(
                        bot_id, account_id, getattr(cfg, "quote_asset", "USDT")
                    )
                    for k, v in sk.items():
                        if state.get(k) is None:
                            state[k] = v
                    save_state(db, bot_id, account_id, state)
                else:
                    state["bot_id"] = bot_id
                    # initial_allocation_done sadece execution'da gerçek fill sonrası set edilir.
                    # Paper modda kaydedilen simüle init trade'leri sayma; yoksa live'a geçince gerçek alım atlanır.
                from app.services.test_account import test_account_paper_execution
                from app.core.config import is_worker_role

                bot_mode = str(getattr(row, "mode", None) or "").strip().lower()
                acct_test = test_account_paper_execution(account_id, db)
                if state.get("run_id"):
                    if acct_test:
                        logger.debug(
                            "BOT_RUN_ID run_id=%s bot_id=%s (test)",
                            state.get("run_id"),
                            bot_id,
                        )
                    else:
                        logger.debug(
                            "BOT_RUN_ID run_id=%s bot_id=%s",
                            state.get("run_id"),
                            bot_id,
                        )
                # Production: paper_mode from DB; test hesabı her zaman paper, API anahtarı yok
                paper_mode = acct_test or (bot_mode == "paper")
                keys = None
                has_keys = False
                if not acct_test:
                    try:
                        from app.services.binance_assets import get_account_keys

                        keys = await get_account_keys(account_id, db)
                        has_keys = keys is not None
                    except Exception as e:
                        logger.info(
                            "BOT_ACCOUNT_KEYS_FAIL bot_id=%s account_id=%s err=%s (tick skipped, retry)",
                            bot_id,
                            account_id,
                            e,
                        )
                        keys = None
                        has_keys = False
                # (A) Live bot + no keys => FAIL FAST: do not run as paper, pause bot (test hesabı hariç)
                if bot_mode == "live" and not has_keys and not acct_test:
                    row.status = "paused_error"
                    db.commit()
                    state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
                    state["retry_at"] = datetime.utcnow()
                    save_state(db, bot_id, account_id, state)
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "ERROR",
                        "API anahtarı gerekli (live bot)",
                        {"error_code": "ACCOUNT_KEYS_MISSING"},
                    )
                    try:
                        from app.services import audit as _audit_svc

                        _audit_svc.log_event(
                            db,
                            actor_type="system",
                            event_type="BOT_PAUSED_NO_KEYS",
                            severity="WARN",
                            target_account_id=account_id,
                            meta={
                                "bot_id": bot_id,
                                "error_code": "ACCOUNT_KEYS_MISSING",
                            },
                        )
                    except Exception:
                        pass
                    logger.warning(
                        "BOT_LIVE_NO_KEYS bot_id=%s account_id=%s paused_error (FAIL FAST)",
                        bot_id,
                        account_id,
                    )
                    await asyncio.sleep(30)
                    continue
                if not has_keys and not paper_mode:
                    state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
                    state["retry_at"] = datetime.utcnow()
                    save_state(db, bot_id, account_id, state)
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "ERROR",
                        "API anahtarı gerekli",
                        {"error_code": "ACCOUNT_KEYS_MISSING"},
                    )
                    await asyncio.sleep(30)
                    continue

                adapter = BinanceAdapter(account_id, keys, paper_mode=paper_mode)
                mode_log = (
                    "BOT_MODE_CHECK bot_id=%s account_id=%s bot.mode=%s paper_mode=%s has_keys=%s is_worker_role=%s test_account=%s",
                    bot_id,
                    account_id,
                    bot_mode,
                    paper_mode,
                    has_keys,
                    is_worker_role(),
                    acct_test,
                )
                if acct_test:
                    logger.debug(*mode_log)
                else:
                    logger.debug(*mode_log)
                if not paper_mode and not is_trdca and symbol and symbol != "MULTI":
                    try:
                        from app.botengine.intent_ledger import (
                            reconcile_open_orders_for_bot,
                        )
                        from app.services.binance_spot import is_ip_banned

                        now_ts = time.time()
                        if (
                            not is_ip_banned()
                            and now_ts - _reconcile_last_ts.get(bot_id, 0) >= 60
                        ):
                            await reconcile_open_orders_for_bot(
                                adapter, bot_id, account_id, db, symbol
                            )
                            _reconcile_last_ts[bot_id] = now_ts
                    except Exception as recon_err:
                        logger.debug(
                            "reconcile_open_orders_for_bot bot_id=%s err=%s",
                            bot_id,
                            recon_err,
                        )
                if is_trdca:
                    next_wake = getattr(cfg, "tick_interval_ms", 1000) / 1000.0
                else:
                    next_wake = (
                        getattr(cfg, "interval_sec", 3600)
                        if (is_multi or symbol == "MULTI")
                        else getattr(cfg, "tick_interval_ms", 5000) / 1000.0
                    )
                if is_trdca:
                    try:
                        snapshot = await _build_trdca_snapshot(adapter, state, cfg)
                        next_state, decision = trdca_strategy_tick(snapshot, state, cfg)
                        state.update(next_state)
                        state["last_tick_at"] = datetime.utcnow()
                        dec_type = decision.get("type") or "NOOP"
                        if dec_type == "SAFE_STOP":
                            save_state(db, bot_id, account_id, state)
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "ERROR",
                                (decision.get("reason") or {}).get(
                                    "error_code", "SAFE_STOP"
                                ),
                                decision.get("reason"),
                            )
                        elif dec_type == "RESUME_PENDING":
                            save_state(db, bot_id, account_id, state)
                        elif dec_type == "ACTIONS":
                            actions_list = decision.get("actions") or []
                            if actions_list:
                                batch = actions_list[0]
                                legs = batch.get("legs") or []
                                prices = snapshot.get("prices_last") or {}
                                quote_asset = getattr(cfg, "quote_asset", "USDT")
                                trdca_actions = []
                                for leg in legs:
                                    sym = (leg.get("symbol") or "").upper()
                                    side = (leg.get("side") or "BUY").upper()
                                    qty = float(leg.get("qty") or 0)
                                    base = (
                                        sym.replace(quote_asset, "")
                                        if quote_asset in sym
                                        else sym
                                    )
                                    price = prices.get(base) or prices.get(sym) or 0.0
                                    trdca_actions.append(
                                        {
                                            "type": "place",
                                            "side": side,
                                            "symbol": sym,
                                            "quantity": qty,
                                            "quote_qty": (qty * price)
                                            if side == "BUY" and price
                                            else None,
                                            "client_order_id": leg.get(
                                                "client_order_id"
                                            ),
                                            "reason": "trdca_batch",
                                        }
                                    )
                                lock_sym = trade_lock_symbol(account_id, "MULTI")
                                lock_held = try_acquire_symbol_lock(
                                    db, account_id, lock_sym, bot_id
                                )
                                if not lock_held:
                                    from app.botengine.skip_event_policy import evaluate_skip_log

                                    evaluate_skip_log(
                                        state,
                                        "LOCK_BUSY",
                                        {
                                            "symbol": lock_sym,
                                            "cycle_id": int(state.get("cycle_id") or 1),
                                        },
                                    )
                                elif not lease_still_valid(
                                    db, account_id, lock_sym, bot_id
                                ):
                                    try:
                                        release_symbol_lock(
                                            db, account_id, lock_sym, bot_id
                                        )
                                    except Exception:
                                        pass
                                    append_event(
                                        db,
                                        bot_id,
                                        account_id,
                                        "LOCK_LEASE_EXPIRED",
                                        "lease not valid before submit skip trade",
                                        {"account_id": account_id, "symbol": lock_sym},
                                    )
                                    logger.info(
                                        "BOT_TICK bot_id=%s lease_not_valid symbol=%s skip submit (expected during lock handoff)",
                                        bot_id,
                                        lock_sym,
                                    )
                                else:
                                    run_result = await run_actions(
                                        bot_id,
                                        account_id,
                                        trdca_actions,
                                        state,
                                        cfg,
                                        adapter,
                                        db=db,
                                        loop_id=loop_instance_id,
                                    )
                                    pending_fills = []
                                    for r in run_result:
                                        st = (r.get("status") or "FILLED").upper()
                                        pending_fills.append(
                                            {
                                                "client_order_id": r.get(
                                                    "client_order_id"
                                                )
                                                or "",
                                                "symbol": r.get("symbol") or "",
                                                "side": r.get("side") or "BUY",
                                                "status": st,
                                                "filled_qty": r.get("fill_qty") or 0,
                                                "filled_quote": r.get("filled_quote")
                                                if r.get("filled_quote") is not None
                                                else (r.get("fill_price") or 0)
                                                * (r.get("fill_qty") or 0),
                                                "fee": r.get("fee") or 0,
                                                "event_ts": int(time.time() * 1000),
                                            }
                                        )
                                    state["_pending_fills"] = pending_fills
                                    for r in run_result:
                                        if r.get("event_logged"):
                                            continue
                                        append_event(
                                            db,
                                            bot_id,
                                            account_id,
                                            "ORDER_FILLED",
                                            f"{r.get('side')} {r.get('fill_qty')} @ {r.get('fill_price')}",
                                            r,
                                        )
                                    # Paper mode: güncel sanal bakiyeyi state'e yaz (bots_detail gösterebilsin)
                                    if paper_mode:
                                        base_bal = dict(
                                            snapshot.get("balances_free") or {}
                                        )
                                        state["virtual_balances"] = (
                                            _apply_fills_to_virtual_balances(
                                                base_bal, pending_fills, quote_asset
                                            )
                                        )
                                    try:
                                        release_symbol_lock(
                                            db, account_id, lock_sym, bot_id
                                        )
                                    except Exception as ex:
                                        logger.debug(
                                            "bot_engine release_symbol_lock bot_id=%s err=%s",
                                            bot_id,
                                            ex,
                                        )
                        # Paper mode: ilk tick veya NOOP sonrası virtual_balances yoksa adapter'dan başlat
                        if paper_mode and not state.get("virtual_balances"):
                            state["virtual_balances"] = dict(
                                snapshot.get("balances_free") or {}
                            )
                        save_state(db, bot_id, account_id, state)
                        tick_count += 1
                        if tick_count == 1 and state.get(
                            "_pending_connectivity_stable"
                        ):
                            try:
                                from app.services.binance_connectivity import (
                                    flush_pending_connectivity_stable,
                                )

                                flush_pending_connectivity_stable(
                                    db, bot_id, after_loop_restart=True
                                )
                            except Exception:
                                pass
                    except Exception as tick_err:
                        error_id = str(uuid.uuid4())
                        logger.info(
                            "BOT_LOOP_TRDCA_EXCEPTION error_id=%s bot_id=%s %s (absorbed, loop continues)",
                            error_id,
                            bot_id,
                            tick_err,
                        )
                        state["last_error_code"] = "BOT_LOOP_TRDCA_EXCEPTION"
                        state["health_error_since"] = int(time.time())
                        save_state(db, bot_id, account_id, state)
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "ERROR",
                            f"BOT_LOOP_TRDCA_EXCEPTION {error_id} {tick_err}",
                            {
                                "error_code": "BOT_LOOP_TRDCA_EXCEPTION",
                                "error_id": error_id,
                                "loop_id": loop_instance_id,
                            },
                        )
                        try:
                            from app.botengine.health_watch import (
                                emit_resilience_continue,
                            )

                            emit_resilience_continue(
                                db,
                                bot_id,
                                account_id,
                                "BOT_LOOP_TRDCA_EXCEPTION",
                                str(tick_err),
                                error_id=error_id,
                                loop_id=loop_instance_id,
                            )
                        except Exception:
                            pass
                    from app.services.test_simulation import paper_tick_sleep_seconds

                    await asyncio.sleep(
                        paper_tick_sleep_seconds(
                            next_wake, paper_mode, test_account=acct_test
                        )
                    )
                    continue
                if is_multi or symbol == "MULTI":
                    # Multi-asset rebalance: no single symbol price; strategy uses per-asset prices later
                    price = 1.0
                    base_balance = 0.0
                    quote_balance = 0.0
                    state["base_balance"] = base_balance
                    state["quote_balance"] = quote_balance
                else:
                    # data_hub only; no price_hub/ticker fallback (eliminates N× Binance REST)
                    price = adapter.get_price(symbol)
                    if not price or price <= 0:
                        try:
                            from app.services.data_hub import data_hub
                            from app.services.market_data import (
                                refresh_worker_symbol_from_web,
                            )

                            data_hub.pin_symbols([symbol])
                            refetched = await refresh_worker_symbol_from_web(symbol)
                            if refetched and refetched > 0:
                                price = refetched
                            elif os.getenv("DATAHUB_REST_IN_WORKER", "0").strip() == "1":
                                await data_hub.ensure_symbol_price(symbol)
                                price = adapter.get_price(symbol)
                        except Exception:
                            pass
                    if not price or price <= 0:
                        logger.debug(
                            "BOT_PRICE bot_id=%s loop=%s tick=%s status=STALE symbol=%s",
                            bot_id,
                            loop_instance_id,
                            tick_count,
                            symbol,
                        )
                        now_ts = time.time()
                        if not state.get("price_stale_since"):
                            state["price_stale_since"] = int(now_ts)
                            save_state(db, bot_id, account_id, state)
                        if (
                            now_ts - _last_stale_event_ts.get(bot_id, 0)
                        ) >= _STALE_EVENT_THROTTLE_SEC:
                            _last_stale_event_ts[bot_id] = now_ts
                            logger.info(
                                "BOT_TICK_PRICE_MISSING bot_id=%s loop=%s tick=%s symbol=%s price=%s skip_trade=True next_wake=%.1f",
                                bot_id,
                                loop_instance_id,
                                tick_count,
                                symbol,
                                price,
                                next_wake,
                            )
                            try:
                                from app.botengine.health_watch import emit_price_stale

                                emit_price_stale(db, bot_id, account_id, symbol)
                            except Exception:
                                pass
                        from app.services.test_simulation import (
                            paper_tick_sleep_seconds,
                        )

                        await asyncio.sleep(
                            paper_tick_sleep_seconds(
                                next_wake, paper_mode, test_account=acct_test
                            )
                        )
                        continue
                    if state.pop("price_stale_since", None):
                        save_state(db, bot_id, account_id, state)
                    logger.debug(
                        "BOT_PRICE bot_id=%s loop=%s tick=%s status=OK price=%.2f symbol=%s",
                        bot_id,
                        loop_instance_id,
                        tick_count,
                        price,
                        symbol,
                    )
                    # Tur içi fiyat aralığı takibi (_cycle_price_high / _cycle_price_low)
                    if state.get("initial_allocation_done"):
                        _ph = state.get("_cycle_price_high")
                        _pl = state.get("_cycle_price_low")
                        if _ph is None or price > _ph:
                            state["_cycle_price_high"] = round(price, 10)
                        if _pl is None or price < _pl:
                            state["_cycle_price_low"] = round(price, 10)
                    init_quote = float(
                        getattr(cfg, "initial_capital_usdt", 0)
                        or getattr(cfg, "bot_budget_usdt", 0)
                        or 0
                    )
                    if init_quote <= 0 and paper_mode:
                        from app.services.test_account import TEST_PAPER_BALANCE_USDT

                        init_quote = float(TEST_PAPER_BALANCE_USDT)
                    ensure_virtual_wallet(db, bot_id, account_id, symbol, init_quote)
                    # State'te ilk alım yapılmışsa (repair veya fill sonrası) virtual_wallet güncel olmayabilir; önce state'ten sync et ki bakiye ezilmesin
                    if state.get("initial_allocation_done") and (
                        float(state.get("base_balance") or 0) != 0
                        or float(state.get("quote_balance") or 0) != 0
                    ):
                        try:
                            sync_virtual_wallet_from_state(
                                db,
                                bot_id,
                                account_id,
                                symbol,
                                float(state.get("base_balance") or 0),
                                float(state.get("quote_balance") or 0),
                            )
                        except Exception as sync_err:
                            logger.debug(
                                "orchestrator pre-tick sync_virtual_wallet_from_state bot_id=%s err=%s",
                                bot_id,
                                sync_err,
                            )
                    vb, vq = get_virtual_wallet(db, bot_id, symbol)
                    state["base_balance"] = vb
                    state["quote_balance"] = vq
                    base_balance = vb
                    quote_balance = vq

                try:
                    strategy = get_strategy_safe(raw)
                    # ============================================================
                    # Dynamic Mode hook (gated). Runs ONLY when dynamic_mode=True
                    # and safety prerequisites are met. Manuel mod = no-op.
                    # ============================================================
                    try:
                        from app.botengine.dynamic import (
                            cycle_manager as dyn_cm,
                            safety_gate as dyn_gate,
                        )

                        _cfg_dict_for_dyn = (
                            cfg.to_dict() if hasattr(cfg, "to_dict") else {}
                        )
                        if dyn_gate.is_dynamic_mode_active(_cfg_dict_for_dyn):
                            _dyn_snapshot_rebuilt = False
                            if not dyn_cm.dynamic_overlay_allowed(state):
                                if state.get("dynamic_snapshot"):
                                    state.pop("dynamic_snapshot", None)
                                state["_dynamic_first_cycle_manual"] = True
                                logger.debug(
                                    "DYN_FIRST_CYCLE_MANUAL bot_id=%s cycle=%s — using manual cfg",
                                    bot_id,
                                    state.get("cycle_id") or 1,
                                )
                            else:
                                state.pop("_dynamic_first_cycle_manual", None)
                            if dyn_cm.dynamic_overlay_allowed(state) and dyn_cm.need_recompute(state):
                                # Dynamic suggestions MUST derive from the user's
                                # MANUAL config every cycle. `cfg` is cached and
                                # mutated in-place by apply_overlay, so cfg.to_dict()
                                # carries the PREVIOUS cycle's overlay and would let
                                # the base drift cycle-over-cycle. Re-derive a clean
                                # manual base from config_json (never overlaid).
                                try:
                                    _dyn_base = DcaGridTrailingConfig(raw).to_dict()
                                except Exception:
                                    _dyn_base = _cfg_dict_for_dyn
                                _new_snap = await dyn_cm.build_snapshot(
                                    state, _dyn_base, float(price or 0.0)
                                )
                                state["dynamic_snapshot"] = _new_snap
                                _diffs = dyn_cm.apply_overlay(cfg, _new_snap)
                                _dyn_snapshot_rebuilt = True
                                logger.info(
                                    "DYN_SNAPSHOT_BUILT bot_id=%s cycle=%s regime=%s data_fresh=%s clamps=%s fallbacks=%s diffs=%s",
                                    bot_id,
                                    _new_snap.get("cycle_id"),
                                    _new_snap.get("regime"),
                                    _new_snap.get("data_fresh"),
                                    len(_new_snap.get("clamps") or []),
                                    len(_new_snap.get("fallbacks") or []),
                                    list((_diffs or {}).keys()),
                                )
                                logger.debug(
                                    "DYN_SNAPSHOT_DETAIL bot_id=%s reasons=%s clamps=%s diffs=%s",
                                    bot_id,
                                    _new_snap.get("reasons"),
                                    _new_snap.get("clamps"),
                                    _diffs,
                                )
                                # Bot-detay event'i: kullanıcı UI'da görsün
                                try:
                                    from app.botengine.state_store import (
                                        queue_engine_event,
                                    )

                                    queue_engine_event(
                                        state,
                                        "DYN_SNAPSHOT",
                                        f"Dynamic snapshot built: regime={_new_snap.get('regime')} "
                                        f"fresh={_new_snap.get('data_fresh')} "
                                        f"clamps={len(_new_snap.get('clamps') or [])}",
                                        {
                                            "cycle_id": _new_snap.get("cycle_id"),
                                            "regime": _new_snap.get("regime"),
                                            "data_fresh": _new_snap.get("data_fresh"),
                                            "applied": _new_snap.get("applied"),
                                            "reasons": (_new_snap.get("reasons") or [])[
                                                :8
                                            ],
                                            "clamps": (_new_snap.get("clamps") or [])[
                                                :8
                                            ],
                                            "fallbacks": _new_snap.get("fallbacks")
                                            or [],
                                        },
                                    )
                                except Exception as _ev_err:
                                    logger.debug(
                                        "DYN_SNAPSHOT event_queue failed bot_id=%s err=%s",
                                        bot_id,
                                        _ev_err,
                                    )
                            else:
                                # Snapshot still valid: re-apply overlay (in case cfg was
                                # rebuilt from raw dict this tick).
                                _existing = state.get("dynamic_snapshot") or {}
                                if _existing:
                                    dyn_cm.apply_overlay(cfg, _existing)
                                    logger.debug(
                                        "DYN_SNAPSHOT_REUSED bot_id=%s cycle=%s regime=%s",
                                        bot_id,
                                        _existing.get("cycle_id"),
                                        _existing.get("regime"),
                                    )
                            # Cycle-entry risk gate (legacy) — V4 default OFF; no mid-turn hold.
                            if dyn_cm.dynamic_overlay_allowed(state):
                                try:
                                    from app.botengine.dynamic import (
                                        cycle_gate as _dyn_cgate,
                                    )

                                    if _dyn_cgate.HOLD_ENABLED:
                                        _gate_cfg = (
                                            cfg.to_dict()
                                            if hasattr(cfg, "to_dict")
                                            else _cfg_dict_for_dyn
                                        )
                                        _was_hold = _dyn_cgate.is_holding(state)
                                        _gv = None
                                        if _dyn_snapshot_rebuilt:
                                            _snap2 = state.get("dynamic_snapshot") or {}
                                            if _snap2.get("data_fresh"):
                                                _gv = _dyn_cgate.evaluate(
                                                    _snap2.get("features") or {},
                                                    _snap2.get("regime"),
                                                    _snap2.get("regime_confidence") or 0.0,
                                                    state,
                                                    _gate_cfg,
                                                )
                                        elif _was_hold and not _dyn_cgate.cycle_engaged(
                                            state
                                        ):
                                            _hold_st = state.get("_dynamic_cycle_hold") or {}
                                            _now_ms = int(time.time() * 1000)
                                            _next_re = int(
                                                _hold_st.get("next_recheck_ms") or 0
                                            )
                                            if _next_re <= _now_ms:
                                                _gv = await _dyn_cgate.maintain(
                                                    state, _gate_cfg, float(price or 0.0)
                                                )
                                                if isinstance(
                                                    state.get("_dynamic_cycle_hold"), dict
                                                ):
                                                    state["_dynamic_cycle_hold"][
                                                        "next_recheck_ms"
                                                    ] = _now_ms + int(
                                                        _dyn_cgate.RECHECK_SEC * 1000
                                                    )
                                        if _gv is not None:
                                            _now_hold = _dyn_cgate.is_holding(state)
                                            if _now_hold and not _was_hold:
                                                _emit_cycle_hold_event(
                                                    state, _gv, holding=True
                                                )
                                                logger.info(
                                                    "DYN_CYCLE_HOLD bot_id=%s cycle=%s risk=%.2f regime=%s reasons=%s",
                                                    bot_id,
                                                    state.get("cycle_id"),
                                                    _gv.risk_score,
                                                    _gv.regime,
                                                    _gv.reasons[:4],
                                                )
                                            elif _was_hold and not _now_hold:
                                                _emit_cycle_hold_event(
                                                    state, _gv, holding=False
                                                )
                                                logger.info(
                                                    "DYN_CYCLE_RELEASE bot_id=%s cycle=%s risk=%.2f reason=%s",
                                                    bot_id,
                                                    state.get("cycle_id"),
                                                    _gv.risk_score,
                                                    _gv.released_reason,
                                                )
                                    else:
                                        state.pop("_dynamic_cycle_hold", None)
                                        state.pop("_dynamic_cycle_engaged", None)
                                except Exception as _cgate_err:
                                    logger.debug(
                                        "DYN_CYCLE_GATE_FAIL bot_id=%s err=%s",
                                        bot_id,
                                        _cgate_err,
                                    )
                                    state.pop("_dynamic_cycle_hold", None)
                        else:
                            # dynamic_mode False (or prerequisites missing) → strip any
                            # stale snapshot so the UI does not show outdated data.
                            if state.get("dynamic_snapshot"):
                                logger.debug(
                                    "DYN_DEACTIVATED bot_id=%s cycle=%s — clearing snapshot",
                                    bot_id,
                                    state.get("cycle_id"),
                                )
                                state.pop("dynamic_snapshot", None)
                    except Exception as dyn_err:
                        logger.warning(
                            "DYN_HOOK_EXCEPTION bot_id=%s err=%s — falling back to manual cfg",
                            bot_id,
                            dyn_err,
                        )
                    # ============================================================
                    t0 = time.perf_counter()
                    actions, next_wake = strategy.tick(
                        state, cfg, price, base_balance, quote_balance
                    )
                    # Dynamic cycle-entry HOLD filter (legacy; V4 default off).
                    if state.get("dynamic_snapshot") is not None and actions:
                        try:
                            from app.botengine.dynamic import cycle_gate as _dyn_cgate2

                            if _dyn_cgate2.HOLD_ENABLED:
                                actions, _held_blocked = _dyn_cgate2.filter_actions(
                                    state, actions
                                )
                                if _held_blocked:
                                    next_wake = min(
                                        next_wake, _dyn_cgate2.RECHECK_SEC
                                    )
                                    _hold_st = state.get("_dynamic_cycle_hold") or {}
                                    logger.info(
                                        "DYN_CYCLE_HOLD_BLOCK bot_id=%s cycle=%s blocked=%s risk=%.2f regime=%s",
                                        bot_id,
                                        state.get("cycle_id"),
                                        _held_blocked,
                                        float(_hold_st.get("risk_score") or 0.0),
                                        _hold_st.get("regime"),
                                    )
                        except Exception as _hold_filter_err:
                            logger.debug(
                                "DYN_CYCLE_HOLD_FILTER_FAIL bot_id=%s err=%s",
                                bot_id,
                                _hold_filter_err,
                            )
                    # Pending round-start retry (hard safety / stale data): wake at 15m
                    try:
                        from app.botengine.dynamic import round_start_policy as _rsp

                        _pend = _rsp.get_pending(state)
                        if _pend:
                            _now_ms2 = int(time.time() * 1000)
                            _retry_ms = int(_pend.get("next_retry_ms") or 0)
                            if _retry_ms > _now_ms2:
                                _sec = max(1.0, (_retry_ms - _now_ms2) / 1000.0)
                                next_wake = min(next_wake, _sec)
                    except Exception:
                        pass
                    # ============================================================
                    # Dynamic emergency check (cycle + portfolio circuit breaker).
                    # Current operator policy disables this brake; keep the old
                    # logic behind the safety_gate flag and clear stale state.
                    # ============================================================
                    try:
                        from app.botengine.dynamic import safety_gate as _sg

                        _cfg_for_emg = cfg.to_dict() if hasattr(cfg, "to_dict") else {}
                        _dyn_active_for_emg = _sg.is_dynamic_mode_active(_cfg_for_emg)
                        if (
                            not _sg.EMERGENCY_CHECKS_ENABLED
                            and state.get("_dyn_emergency")
                        ):
                            state.pop("_dyn_emergency", None)
                        if (
                            _sg.EMERGENCY_CHECKS_ENABLED
                            and _dyn_active_for_emg
                            and state.get("initial_allocation_done")
                        ):
                            _equity_now = float(base_balance) * float(
                                price or 0
                            ) + float(quote_balance)
                            _emg = _sg.emergency_check(
                                state,
                                _cfg_for_emg,
                                _equity_now,
                                price=float(price or 0),
                            )
                            if _emg["action"] != "NONE":
                                logger.warning(
                                    "DYN_EMERGENCY bot_id=%s action=%s reason=%s metrics=%s",
                                    bot_id,
                                    _emg["action"],
                                    _emg["reason"],
                                    _emg.get("metrics"),
                                )
                                try:
                                    flush_queued_events(db, bot_id, account_id, state)
                                    row.status = "paused_error"
                                    state["last_error_code"] = "DYN_" + _emg["action"]
                                    state["_dyn_emergency"] = {
                                        "action": _emg["action"],
                                        "reason": _emg["reason"],
                                        "metrics": _emg.get("metrics"),
                                        "ts": int(time.time() * 1000),
                                    }
                                    save_state(db, bot_id, account_id, state)
                                    db.commit()
                                    append_event(
                                        db,
                                        bot_id,
                                        account_id,
                                        "ERROR",
                                        f"DYN {_emg['action']}: {_emg['reason']}",
                                        {
                                            "error_code": "DYN_" + _emg["action"],
                                            **(_emg.get("metrics") or {}),
                                        },
                                    )
                                except Exception as _emg_ex:
                                    logger.debug(
                                        "DYN_EMERGENCY persist failed bot_id=%s err=%s",
                                        bot_id,
                                        _emg_ex,
                                    )
                                # Don't issue actions this tick
                                await asyncio.sleep(next_wake)
                                continue
                    except Exception as _emg_err:
                        logger.debug(
                            "DYN_EMERGENCY_CHECK_FAIL bot_id=%s err=%s",
                            bot_id,
                            _emg_err,
                        )
                    # Günlük kayıp limiti devre dışı bırakıldıysa eski state
                    # bayrağı da botu durdurmasın.
                    try:
                        from app.botengine.dynamic.safety_gate import (
                            DAILY_LOSS_RUNTIME_ENABLED as _dll_runtime_enabled,
                        )
                    except Exception:
                        _dll_runtime_enabled = False
                    if not _dll_runtime_enabled and state.get("_daily_loss_limit_hit"):
                        state.pop("_daily_loss_limit_hit", None)
                    # Günlük kayıp limiti aşıldıysa botu durdur
                    if _dll_runtime_enabled and state.get("_daily_loss_limit_hit"):
                        try:
                            flush_queued_events(db, bot_id, account_id, state)
                            row.status = "paused_error"
                            state["last_error_code"] = "DAILY_LOSS_LIMIT"
                            save_state(db, bot_id, account_id, state)
                            db.commit()
                            logger.warning(
                                "BOT_DAILY_LOSS_LIMIT_PAUSED bot_id=%s account_id=%s",
                                bot_id,
                                account_id,
                            )
                        except Exception as _dll_ex:
                            logger.debug(
                                "daily_loss_limit pause bot_id=%s: %s", bot_id, _dll_ex
                            )
                        await asyncio.sleep(next_wake)
                        continue
                    try:
                        from app.botengine.strategies.grid_outage_recovery import (
                            flush_outage_recovery_log_to_events,
                        )

                        flush_outage_recovery_log_to_events(
                            db, bot_id, account_id, state
                        )
                    except Exception as olog_ex:
                        logger.debug(
                            "outage_recovery_log bot_id=%s: %s", bot_id, olog_ex
                        )
                    flush_queued_events(db, bot_id, account_id, state)
                    (time.perf_counter() - t0) * 1000

                    logger.debug(
                        "BOT_TICK_SUMMARY bot_id=%s actions=%s next_wake=%s initial_allocation_done=%s quote=%s base=%s price=%s",
                        bot_id,
                        len(actions) if actions else 0,
                        next_wake,
                        state.get("initial_allocation_done"),
                        state.get("quote_balance"),
                        state.get("base_balance"),
                        price,
                    )

                    state["last_tick_at"] = datetime.utcnow()
                    lock_held = False
                    if actions:
                        lock_sym = trade_lock_symbol(account_id, symbol)
                        lock_held = try_acquire_symbol_lock(
                            db, account_id, lock_sym, bot_id
                        )
                        if not lock_held:
                            from app.botengine.skip_event_policy import evaluate_skip_log

                            evaluate_skip_log(
                                state,
                                "LOCK_BUSY",
                                {
                                    "symbol": lock_sym,
                                    "cycle_id": int(state.get("cycle_id") or 1),
                                },
                            )
                            logger.info(
                                "BOT_TICK bot_id=%s LOCK_BUSY symbol=%s skip trade",
                                bot_id,
                                lock_sym,
                            )
                        elif not lease_still_valid(db, account_id, lock_sym, bot_id):
                            try:
                                release_symbol_lock(db, account_id, lock_sym, bot_id)
                            except Exception:
                                pass
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "LOCK_LEASE_EXPIRED",
                                "lease not valid before submit skip trade",
                                {"account_id": account_id, "symbol": lock_sym},
                            )
                            logger.info(
                                "BOT_TICK bot_id=%s lease_not_valid symbol=%s skip submit (expected during lock handoff)",
                                bot_id,
                                lock_sym,
                            )
                        else:
                            for a in actions:
                                ak = (
                                    (a.get("reason") or "unknown")
                                    + "_"
                                    + str(a.get("grid_index", ""))
                                )
                                if a.get("reason") == "initial_allocation":
                                    ak = f"initial_allocation_{bot_id}_{state.get('state_version', 0)}_0"
                                logger.info(
                                    "BOT_ACTION bot_id=%s loop=%s tick=%s action_key=%s type=%s reason=%s symbol=%s quote_qty=%s qty=%s",
                                    bot_id,
                                    loop_instance_id,
                                    tick_count,
                                    ak,
                                    (a.get("side") or "").upper(),
                                    a.get("reason") or "",
                                    a.get("symbol"),
                                    a.get("quote_qty"),
                                    a.get("quantity"),
                                )
                            stop_hb = asyncio.Event()

                            async def _heartbeat_renew(acc_id: int, sym: str, bid: int):
                                while not stop_hb.is_set():
                                    await asyncio.sleep(HEARTBEAT_RENEWAL_INTERVAL_SEC)
                                    if stop_hb.is_set():
                                        break
                                    try:
                                        _db = _get_db()
                                        try:
                                            renew_symbol_lock(_db, acc_id, sym, bid)
                                        finally:
                                            _db.close()
                                    except Exception:
                                        pass

                            hb_task = asyncio.create_task(
                                _heartbeat_renew(account_id, lock_sym, bot_id)
                            )
                            try:
                                run_result = await run_actions(
                                    bot_id,
                                    account_id,
                                    actions,
                                    state,
                                    cfg,
                                    adapter,
                                    db=db,
                                    loop_id=loop_instance_id,
                                )
                            finally:
                                stop_hb.set()
                                hb_task.cancel()
                                try:
                                    await hb_task
                                except asyncio.CancelledError:
                                    pass
                            for r in run_result:
                                if r.get("event_logged"):
                                    continue
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "ORDER_FILLED",
                                    f"{r['side']} {r['fill_qty']} @ {r['fill_price']}",
                                    r,
                                )
                            if os.getenv("RAM_PROBE_ENABLED") == "1":
                                try:
                                    from app.observability.ram_probe import (
                                        probe_bot_event,
                                    )

                                    probe_bot_event(
                                        "ORDER_FILLED", bot_id=bot_id, write_to_log=True
                                    )
                                except Exception:
                                    pass
                            try:
                                release_symbol_lock(db, account_id, lock_sym, bot_id)
                            except Exception as ex:
                                logger.debug(
                                    "bot_engine release_symbol_lock bot_id=%s err=%s",
                                    bot_id,
                                    ex,
                                )
                            lock_held = False
                    save_state(db, bot_id, account_id, state)
                    # BNB fee dönüşüm uyarılarını bot event'e çevir
                    _fee_warns = (
                        state.get("cycle_ledger_current", {}).get(
                            "_fee_conversion_warn"
                        )
                        or []
                    )
                    if _fee_warns:
                        for _fw in _fee_warns:
                            try:
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "WARN",
                                    f"Komisyon USDT'ye çevrilemedi: {_fw.get('fee_asset')} "
                                    f"{_fw.get('fee_raw'):.8f} — dönem K/Z eksik hesaplanıyor",
                                    {"error_code": "FEE_CONVERSION_FAILED", **_fw},
                                )
                            except Exception:
                                pass
                        try:
                            state["cycle_ledger_current"].pop(
                                "_fee_conversion_warn", None
                            )
                        except Exception:
                            pass
                    if state.get("_pending_connectivity_stable"):
                        try:
                            from app.services.binance_connectivity import (
                                flush_pending_connectivity_stable,
                            )

                            flush_pending_connectivity_stable(
                                db, bot_id, after_loop_restart=False
                            )
                        except Exception:
                            pass
                        state.pop("_pending_connectivity_stable", None)
                        state.pop("_pending_connectivity_stable_at", None)
                        state.pop("_pending_connectivity_stable_prev_err", None)
                    try:
                        sync_virtual_wallet_from_state(
                            db,
                            bot_id,
                            account_id,
                            symbol,
                            float(state.get("base_balance") or 0),
                            float(state.get("quote_balance") or 0),
                        )
                    except Exception as sync_err:
                        logger.debug(
                            "bot_engine sync_virtual_wallet_from_state failed bot_id=%s err=%s",
                            bot_id,
                            sync_err,
                        )
                    # Günlük K/Z referansı: gece 00:00 (Türkiye) equity; gün değişince ref=equity
                    if state.get("initial_allocation_done"):
                        equity = float(state.get("base_balance") or 0) * float(
                            price or 0
                        ) + float(state.get("quote_balance") or 0)
                        init_cap_tick = float(
                            raw.get("initial_capital_usdt")
                            or raw.get("budget_usd")
                            or raw.get("bot_budget_quote")
                            or 0
                        )
                        ensure_daily_ref_and_compute(
                            state,
                            equity,
                            init_cap_tick,
                            getattr(row, "started_at", None),
                            db,
                            bot_id,
                            account_id,
                            True,
                        )
                    # Skip routine TICK log (elapsed_ms/actions) to reduce noise; only errors/skips/fills are logged

                    # Periyodik sanal vs gerçek bakiye doğrulaması (live, her 50 tick, ilk alım sonrası)
                    if (
                        not paper_mode
                        and not acct_test
                        and state.get("initial_allocation_done")
                        and tick_count > 0
                        and tick_count % 50 == 0
                    ):
                        try:
                            from app.botengine.execution import _emit_balance_sync_check

                            await _emit_balance_sync_check(
                                adapter, db, bot_id, account_id, symbol, state, price
                            )
                        except Exception as _bsc_ex:
                            logger.debug(
                                "balance_sync_check bot_id=%s: %s", bot_id, _bsc_ex
                            )

                    tick_count += 1
                    state_ver = state.get("state_version", 0)
                    if os.getenv("RAM_PROBE_ENABLED") == "1" and tick_count % 60 == 0:
                        try:
                            from app.observability.ram_probe import probe_bot_event

                            probe_bot_event(
                                "cycle_tick",
                                bot_id=bot_id,
                                task_count=len(_tasks),
                                write_to_log=True,
                            )
                        except Exception:
                            pass
                    logger.debug("BOT_TICK bot_id=%s state_ver=%s", bot_id, state_ver)
                except Exception as tick_err:
                    error_id = str(uuid.uuid4())
                    logger.info(
                        "BOT_LOOP_TOPLEVEL_EXCEPTION error_id=%s bot_id=%s account_id=%s loop_id=%s error=%s (absorbed)",
                        error_id,
                        bot_id,
                        account_id or 0,
                        loop_instance_id,
                        tick_err,
                    )
                    try:
                        state_err = load_state(db, bot_id) or {}
                        state_err["last_error_code"] = "BOT_TICK_EXCEPTION"
                        state_err["health_error_since"] = int(time.time())
                        save_state(db, bot_id, account_id, state_err)
                    except Exception:
                        pass
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "ERROR",
                        f"BOT_TICK_EXCEPTION {error_id} {tick_err}",
                        {
                            "error_code": "BOT_TICK_EXCEPTION",
                            "error_id": error_id,
                            "bot_id": bot_id,
                            "account_id": account_id or 0,
                            "loop_id": loop_instance_id,
                        },
                    )
                    try:
                        from app.botengine.health_watch import emit_resilience_continue

                        emit_resilience_continue(
                            db,
                            bot_id,
                            account_id,
                            "BOT_TICK_EXCEPTION",
                            str(tick_err),
                            error_id=error_id,
                            loop_id=loop_instance_id,
                        )
                    except Exception:
                        pass
            finally:
                db.close()

            from app.services.test_simulation import paper_tick_sleep_seconds

            await asyncio.sleep(
                paper_tick_sleep_seconds(next_wake, paper_mode, test_account=acct_test)
            )
    except asyncio.CancelledError:
        logger.info("bot_engine loop cancelled bot_id=%s", bot_id)
    except Exception as e:
        error_id = str(uuid.uuid4())
        logger.exception(
            "BOT_LOOP_FATAL error_id=%s bot_id=%s account_id=%s loop_id=%s error=%s",
            error_id,
            bot_id,
            account_id or 0,
            loop_instance_id,
            e,
        )
        try:
            d = _get_db()
            try:
                state = load_state(d, bot_id) or {}
                state["last_error_code"] = "BOT_LOOP_TOPLEVEL_EXCEPTION"
                state["health_error_since"] = int(time.time())
                save_state(d, bot_id, account_id or 0, state)
            except Exception:
                pass
            append_event(
                d,
                bot_id,
                account_id or 0,
                "ERROR",
                f"BOT_LOOP_TOPLEVEL_EXCEPTION {error_id} {e}",
                {
                    "error_code": "BOT_LOOP_TOPLEVEL_EXCEPTION",
                    "error_id": error_id,
                    "bot_id": bot_id,
                    "account_id": account_id or 0,
                    "loop_id": loop_instance_id,
                },
            )
            d.close()
        except Exception:
            pass
        await asyncio.sleep(2)
    finally:
        cancelled = bot_id in _stop_requested
        _stop_requested.discard(bot_id)
        _tasks.pop(bot_id, None)
        _loop_instances.pop(bot_id, None)
        logger.info(
            "BOT_LOOP_END bot_id=%s loop=%s cancelled=%s",
            bot_id,
            loop_instance_id,
            cancelled,
        )
        if not cancelled:
            await _try_restart_bot_loop(bot_id, loop_instance_id, "loop_exit")


async def _try_restart_bot_loop(
    bot_id: int, loop_instance_id: str, reason: str
) -> bool:
    """Restart asyncio loop when DB status is still running (crash recovery)."""
    if bot_id in _stop_requested:
        return False
    db = _get_db()
    account_id = 0
    try:
        from app.db.models import Bot

        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot or (bot.status or "").lower() != "running":
            return False
        account_id = bot.account_id
        try:
            from app.botengine.health_watch import emit_loop_auto_restart

            emit_loop_auto_restart(
                db, bot_id, account_id, reason, loop_id=loop_instance_id
            )
        except Exception:
            pass
    finally:
        db.close()
    async with _task_create_lock:
        if bot_id in _tasks and not _tasks[bot_id].done():
            return False
        _tasks[bot_id] = asyncio.create_task(_bot_loop(bot_id))
        logger.info(
            "BOT_LOOP_RESTART bot_id=%s reason=%s prev_loop=%s",
            bot_id,
            reason,
            loop_instance_id,
        )
    return True


async def start_bot(
    bot_id: int, db: Session, *, connectivity_resume: bool = False
) -> bool:
    from app.db.models import Bot
    from app.botengine.bot_session import mark_bot_run_started, touch_bot_started_at
    from app.botengine.state_store import load_state, save_state
    from app.services.perf_chart_state import seed_perf_chart_state_on_bot_start

    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        return False
    account_id = bot.account_id
    bot.status = "running"
    touch_bot_started_at(bot, connectivity_resume=connectivity_resume)
    state = load_state(db, bot_id) or {}
    mark_bot_run_started(state, connectivity_resume=connectivity_resume)
    save_state(db, bot_id, account_id, state)
    db.commit()
    if not connectivity_resume:
        seed_perf_chart_state_on_bot_start(db, bot_id)
        try:
            from app.services.bot_performance_service import (
                sync_bot_cycles_file_from_state,
            )

            sync_bot_cycles_file_from_state(db, bot_id, account_id, state)
        except Exception as e:
            logger.debug("sync_bot_cycles_file_from_state bot_id=%s: %s", bot_id, e)
    logger.info(
        "BOT_STATUS_CHANGED bot_id=%s account_id=%s status=running", bot_id, account_id
    )
    db.refresh(bot)
    if (bot.status or "").lower() != "running":
        logger.warning(
            "BOT_START_DB_VERIFY_FAIL bot_id=%s account_id=%s status_after_commit=%s",
            bot_id,
            account_id,
            bot.status,
        )
    _stop_requested.discard(bot_id)
    async with _task_create_lock:
        if bot_id in _tasks:
            existing_loop = _loop_instances.get(bot_id, "unknown")
            logger.info(
                "BOT_START_SKIPPED_ALREADY_RUNNING bot_id=%s existing_loop=%s (expected)",
                bot_id,
                existing_loop,
            )
            return True
        t = asyncio.create_task(_bot_loop(bot_id))
        _tasks[bot_id] = t
    if os.getenv("RAM_PROBE_ENABLED") == "1":
        try:
            from app.observability.ram_probe import probe_bot_event

            probe_bot_event(
                "start", bot_id=bot_id, task_count=len(_tasks), write_to_log=True
            )
        except Exception:
            pass
    logger.info("bot_engine started bot_id=%s", bot_id)
    return True


def cancel_orchestrator_loop(bot_id: int) -> None:
    """Stop asyncio _bot_loop task only (no DB status change). Used when v5 scheduler owns ticks."""
    _stop_requested.add(bot_id)
    task = _tasks.pop(bot_id, None)
    if task and not task.done():
        task.cancel()


async def stop_bot(bot_id: int, db: Session) -> bool:
    from app.db.models import Bot
    from app.botengine.bot_session import clear_bot_run_started
    from app.botengine.state_store import load_state, save_state

    _stop_requested.add(bot_id)
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if bot:
        bot.status = "stopped"
        st = load_state(db, bot_id) or {}
        clear_bot_run_started(st)
        save_state(db, bot_id, bot.account_id, st)
        db.commit()
    task = _tasks.get(bot_id)
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        _tasks.pop(bot_id, None)
    _config_cache.pop(bot_id, None)
    if os.getenv("RAM_PROBE_ENABLED") == "1":
        try:
            from app.observability.ram_probe import probe_bot_event

            probe_bot_event(
                "stop", bot_id=bot_id, task_count=len(_tasks), write_to_log=True
            )
        except Exception:
            pass
    logger.info("bot_engine stopped bot_id=%s", bot_id)
    return True


_ensure_running_bots_first_run = True


async def ensure_running_bots(
    db: Session, recovery_source: str = "worker_poll"
) -> None:
    """Start loops for all DB bots with status=running (crash recovery)."""
    global _ensure_running_bots_first_run
    from app.db.models import Bot
    from app.services.perf_chart_state import seed_perf_chart_state_on_bot_start

    _load_worker_loop_count_from_file()
    _write_worker_loop_count()
    pid = os.getpid()
    running_in_db = db.query(Bot).filter(Bot.status == "running").all()
    if _ensure_running_bots_first_run:
        logger.debug("BOT_ENGINE_STARTED pid=%s module=%s", pid, __name__)
        _ensure_running_bots_first_run = False
    global _engine_tick_task
    if _engine_tick_task is None or _engine_tick_task.done():
        _engine_tick_task = asyncio.create_task(_engine_tick_loop())
    logger.debug("bot_engine ensure_running_bots started")
    recovered = []
    for bot in running_in_db:
        async with _task_create_lock:
            if bot.id in _tasks:
                continue
            # Başlangıç tarihini sadece yeni start'ta güncelle; server restart'ta mevcut started_at korunur
            if getattr(bot, "started_at", None) is None:
                bot.started_at = datetime.now(timezone.utc)
                db.commit()
                seed_perf_chart_state_on_bot_start(db, bot.id)
            try:
                from app.botengine.health_watch import emit_loop_auto_restart

                emit_loop_auto_restart(
                    db,
                    bot.id,
                    bot.account_id,
                    recovery_source,
                )
            except Exception:
                pass
            t = asyncio.create_task(_bot_loop(bot.id))
            _tasks[bot.id] = t
            recovered.append(bot.id)
    if recovered:
        logger.info(
            "bot_engine ensure_running_bots recovered %s bots bot_ids=%s source=%s",
            len(recovered),
            recovered,
            recovery_source,
        )
    else:
        logger.debug("bot_engine ensure_running_bots recovered 0 bots bot_ids=[]")


async def delete_bot_fully(bot_id: int, db: Session) -> None:
    """Stop bot, then release symbol lock, persist today's realized PnL to cache, delete virtual wallet, events, state, trades, pnl, bot. Patch-2 + multibot."""
    from app.db.models import Bot, Trade, PnlSnapshot
    from app.services.pnl_service import PnlService

    await stop_bot(bot_id, db)
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if bot:
        try:
            release_symbol_lock(
                db, bot.account_id, trade_lock_symbol(bot.account_id), bot_id
            )
        except Exception:
            pass
        # Performans arşivi + günlük KPI cache
        try:
            from app.services.bot_performance_service import archive_bot_performance

            archive_bot_performance(db, bot_id, bot.account_id)
        except Exception as e:
            logger.warning("delete_bot_fully archive bot_id=%s: %s", bot_id, e)
        today_str = turkey_today_date_str()
        bot_today_realized = PnlService._daily_realized_for_bot_trades(
            db, bot_id, bot.account_id
        )
        if bot_today_realized != 0:
            PnlService.add_to_account_daily_realized_cache(
                db, bot.account_id, today_str, bot_today_realized
            )
    db.execute(
        text("DELETE FROM bot_virtual_wallet WHERE bot_id = :bid"), {"bid": bot_id}
    )
    db.execute(
        text("DELETE FROM bot_engine_events WHERE bot_id = :bid"), {"bid": bot_id}
    )
    db.execute(
        text("DELETE FROM bot_engine_state WHERE bot_id = :bid"), {"bid": bot_id}
    )
    db.query(Trade).filter(Trade.bot_id == bot_id).delete(synchronize_session=False)
    db.query(PnlSnapshot).filter(PnlSnapshot.bot_id == bot_id).delete(
        synchronize_session=False
    )
    if bot:
        db.query(Bot).filter(Bot.id == bot_id).delete(synchronize_session=False)
    db.commit()
    logger.info("bot_engine delete_bot_fully bot_id=%s", bot_id)
