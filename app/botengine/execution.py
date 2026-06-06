"""
Execution: strategy actions -> orders via adapter. Idempotency, guards, apply_fill, cycle reset.
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.orm import Session as SQLASession

from app.bot.ledger import Ledger
from app.botengine.adapters.binance_adapter import BinanceAdapter
from app.botengine.models import DcaGridTrailingConfig
from app.botengine.risk import acquire_bot_lock, check_idempotency, guard_min_notional
from app.botengine.intent_ledger import (
    build_intent_id,
    build_client_order_id,
    upsert_intent,
    update_intent_filled,
    update_intent_sent,
    update_intent_unknown,
    update_intent_rejected,
    update_intent_submitting,
)
from app.botengine.kill_switch import check_kill_switch
from app.botengine.state_store import append_event, load_state, save_state
from app.botengine.virtual_wallet import check_virtual_budget, get_virtual_wallet, update_virtual_after_fill
from app.botengine.cycle_ledger import (
    CYCLE_FILL_REASONS,
    PNL_MODE_CASH,
    PNL_MODE_INVENTORY,
    build_cycle_ledger_empty,
    cycle_ledger_add_fill,
    cycle_ledger_from_state,
    get_cycle_type_and_base_delta,
)
from app.botengine.strategies.dca_grid_trailing import (
    apply_fill_to_state,
    cycle_reset_after_fill,
    _avg_buy_price_total,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Track initial_allocation skip count per (bot_id, action_key) for WARN when > 3
_initial_alloc_skip_count: Dict[Tuple[int, str], int] = {}

# 401 / Invalid API-key: aynı bot için WARNING + event en fazla 10 dk'da bir (log/event flood önleme)
_exec_401_log_throttle: Dict[Tuple[int, ...], float] = {}
_EXEC_401_THROTTLE_SEC = 600.0
# 401 sonrası order denemeyi bu süre (saniye) boyunca durdur (state["backoff_until"])
_EXEC_401_BACKOFF_SEC = 300.0


def _is_401_unauthorized(err: Exception) -> bool:
    s = str(err).lower()
    return "401" in s or "unauthorized" in s or "invalid api-key" in s or "-2015" in s or "permissions for action" in s


def _should_log_exec_401(bot_id: int) -> bool:
    import time as _t
    key = (bot_id,)
    now = _t.monotonic()
    if key in _exec_401_log_throttle and (now - _exec_401_log_throttle[key]) < _EXEC_401_THROTTLE_SEC:
        return False
    _exec_401_log_throttle[key] = now
    return True

# Transaction event hooks for debugging (only register once)
_events_registered = False
if not _events_registered:
    @event.listens_for(SQLASession, "after_begin")
    def receive_after_begin(session, transaction, connection):
        """Log transaction begin."""
        logger.debug("BOT_DB_TX_BEGIN session_id=%s", id(session))

    @event.listens_for(SQLASession, "after_commit")
    def receive_after_commit(session):
        """Log transaction commit."""
        logger.debug("BOT_DB_TX_COMMIT session_id=%s", id(session))

    @event.listens_for(SQLASession, "after_rollback")
    def receive_after_rollback(session):
        """Log transaction rollback at DEBUG only (expected when e.g. TradeSync fails for ACCOUNT_KEYS_MISSING)."""
        logger.debug("BOT_DB_TX_ROLLBACK session_id=%s", id(session))
    
    _events_registered = True


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sync_initial_done_from_db(state: Dict[str, Any], db: "Session", bot_id: int) -> bool:
    """If DB already has initial_allocation_done (from a real fill), copy to state. Never set ia_done=True here."""
    from app.botengine.state_store import load_state
    fresh = load_state(db, bot_id)
    if fresh and fresh.get("initial_allocation_done"):
        for k in ("initial_allocation_done", "reference_price", "cycle_id", "initial_alloc_base_qty", "initial_alloc_price", "base_balance", "quote_balance", "free_quote", "locked_quote", "last_fill_snapshot"):
            if k in fresh:
                state[k] = fresh[k]
        return True
    return False


async def _write_fill_snapshot_to_state(
    state: Dict[str, Any],
    adapter: BinanceAdapter,
    config: DcaGridTrailingConfig,
    symbol: str,
) -> None:
    """
    After ORDER_FILLED: single source-of-truth snapshot from exchange + state.
    Writes free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total to state.
    Reduces virtual/real drift and overcommit risk.
    """
    try:
        balances = await adapter.get_account_balances()
    except Exception as e:
        logger.warning("write_fill_snapshot get_account_balances failed: %s (using virtual)", e)
        balances = None
    quote_asset = "USDT"
    if balances and quote_asset in balances:
        q = balances[quote_asset] or {}
        free_quote = _num(q.get("free"))
        locked_quote = _num(q.get("locked"))
    else:
        free_quote = _num(state.get("quote_balance"))
        locked_quote = 0.0
    base_qty = _num(state.get("base_balance"))
    avg_cost = _avg_buy_price_total(state)
    if avg_cost is None:
        avg_cost = _num(state.get("reference_price"))
    cycle_pnls = state.get("cycle_pnls") or []
    realized_pnl = sum(_num(c.get("pnl_usdt")) for c in cycle_pnls) + _num(state.get("realized_pnl_usdt_cycle"))
    fees_total = sum(_num(c.get("fees_usdt")) for c in cycle_pnls) + _num(state.get("fees_paid_usdt_cycle"))
    from datetime import datetime, timezone
    snapshot_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "free_quote": free_quote,
        "locked_quote": locked_quote,
        "base_qty": base_qty,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "fees_total": fees_total,
        "snapshot_at": snapshot_at,
    }
    state["last_fill_snapshot"] = snapshot
    state["free_quote"] = free_quote
    state["locked_quote"] = locked_quote
    logger.debug(
        "BOT_FILL_SNAPSHOT free_quote=%.2f locked_quote=%.2f base_qty=%.6f avg_cost=%.4f realized_pnl=%.4f fees_total=%.4f",
        free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total,
    )


async def run_actions(
    bot_id: int,
    account_id: int,
    actions: List[Dict[str, Any]],
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
    adapter: BinanceAdapter,
    db: Optional["Session"] = None,
    loop_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Execute actions (place only). Updates state in place. Returns list of {order_id, side, fill_qty, fill_price, fee, reason}.
    """
    results = []
    t0 = time.perf_counter()
    logger.info("run_actions start bot_id=%s", bot_id)
    try:
        check_kill_switch()
    except Exception as kill_err:
        logger.warning("run_actions kill_switch bot_id=%s: %s", bot_id, kill_err)
        return results
    async with await acquire_bot_lock(bot_id):
        for a in actions:
            if a.get("type") != "place":
                continue
            reason = a.get("reason") or ""
            state_ver = state.get("state_version", 0)
            if reason == "initial_allocation":
                key = f"initial_allocation_{bot_id}_{state_ver}_0"
            else:
                key = f"{reason}_{a.get('grid_index', 0)}_{a.get('client_order_id', '')}"
            try:
                binance_balances: Optional[Dict[str, Any]] = None
                # ia_done: only ever set after real fill (see below). On skip we never set it.
                if reason == "initial_allocation" and state.get("initial_allocation_done"):
                    if db is not None and _sync_initial_done_from_db(state, db, bot_id):
                        logger.info("bot_engine execution skip initial_allocation already_done bot_id=%s sync_state", bot_id)
                    continue
                if check_idempotency(bot_id, key):
                    if reason == "initial_allocation" and db is not None:
                        _sync_initial_done_from_db(state, db, bot_id)
                        if state.get("initial_allocation_done"):
                            save_state(db, bot_id, account_id, state)
                    logger.info("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=IDEMPOTENT_LOCK action_key=%s", bot_id, reason, key)
                    if db is not None:
                        append_event(db, bot_id, account_id, "SKIP_REASON", f"IDEMPOTENT_LOCK action_key={key}", {"reason": reason, "skip_reason": "IDEMPOTENT_LOCK", "action_key": key})
                    continue
                if reason == "initial_allocation" and db is not None and _sync_initial_done_from_db(state, db, bot_id):
                    logger.info("bot_engine execution skip initial_allocation already_done bot_id=%s sync_state", bot_id)
                    continue
                # 401 backoff: API key geçersizken her tick order denemeyi durdur
                backoff_until = state.get("backoff_until")
                if backoff_until is not None and isinstance(backoff_until, (int, float)) and time.time() < float(backoff_until):
                    logger.debug("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401_BACKOFF backoff_until=%.0f", bot_id, reason, backoff_until)
                    continue
                side = (a.get("side") or "").upper()
                symbol = (a.get("symbol") or getattr(config, "symbol", "BTCUSDT")).upper()
                qty = _num(a.get("quantity"))
                quote_qty_raw = a.get("quote_qty")
                if reason == "initial_allocation":
                    try:
                        qq = float(quote_qty_raw) if quote_qty_raw is not None else None
                    except (TypeError, ValueError):
                        qq = None
                    if qq is None or qq <= 0:
                        logger.warning(
                            "BOT_EXECUTION_SKIP bot_id=%s reason=initial_allocation skip_reason=INVALID_ACTION quote_qty=%s",
                            bot_id, quote_qty_raw,
                        )
                        if db is not None:
                            append_event(db, bot_id, account_id, "SKIP_REASON", "INVALID_ACTION quote_qty missing or <= 0", {"reason": "initial_allocation", "skip_reason": "INVALID_ACTION", "action_key": key})
                        continue
                    quote_qty = qq
                else:
                    quote_qty = _num(quote_qty_raw)
                    # TRDCA batch: quantity (base) verilmişse, quote_qty 0 ise qty*price kullan
                    if reason == "trdca_batch" and side == "BUY" and qty > 0 and quote_qty <= 0:
                        _p = adapter.get_price(symbol) or 0.0
                        if _p > 0:
                            quote_qty = qty * _p
                run_id = (state.get("run_id") or "").strip() or "0"
                if not run_id or run_id == "0":
                    logger.warning("run_actions bot_id=%s run_id missing in state (using 0); set run_id on START for unique coid", bot_id)
                intent_id = None
                cycle_id_intent = int(state.get("cycle_id") or 1)
                if reason == "initial_allocation":
                    cycle_id_intent = 0
                _price_for_intent = adapter.get_price(symbol) or 0.0
                quote_qty_for_intent = quote_qty if (side == "BUY" and quote_qty > 0) else (qty * _price_for_intent)
                if side == "BUY" and quote_qty_for_intent <= 0 and qty > 0 and _price_for_intent > 0:
                    quote_qty_for_intent = qty * _price_for_intent
                intent_id = build_intent_id(bot_id, cycle_id_intent, symbol, side, qty, quote_qty_for_intent, reason, a.get("grid_index"), run_id=run_id)
                client_order_id_raw = build_client_order_id(bot_id, cycle_id_intent, symbol, side, qty, quote_qty_for_intent, reason, a.get("grid_index"), run_id=run_id)
                client_order_id = client_order_id_raw[:36]
                if db is not None:
                    intent_row, is_new = upsert_intent(db, intent_id, bot_id, account_id, symbol, side, qty, "MARKET", client_order_id)
                    if intent_row and intent_row.get("status") == "FILLED":
                        need_repair = reason == "initial_allocation" and not state.get("initial_allocation_done")
                        verified_filled = False
                        if need_repair:
                            try:
                                coid_repair = (intent_row.get("client_order_id") or client_order_id)[:36]
                                existing_order = await adapter.get_order_by_client_order_id(symbol, coid_repair)
                                if existing_order and (existing_order.get("status") or "").upper() == "FILLED":
                                    order_id_repair = existing_order.get("orderId")
                                    try:
                                        order_id_int = int(order_id_repair) if order_id_repair is not None else 0
                                    except (TypeError, ValueError):
                                        order_id_int = 0
                                    trades_for_order = await adapter.get_my_trades_for_order(symbol, order_id_int) if order_id_int else []
                                    trades_match_count = len(trades_for_order)
                                    if trades_match_count == 0:
                                        logger.info(
                                            "INITIAL_ALLOC_VERIFY result=FAIL orderId=%s trades_match_count=0 => NOT_FOUND, proceeding to place",
                                            order_id_repair,
                                        )
                                        verified_filled = False
                                    else:
                                        exec_qty = _num(existing_order.get("executedQty"))
                                        cum_quote = _num(existing_order.get("cummulativeQuoteQty"))
                                        fill_price_raw = (cum_quote / exec_qty) if exec_qty else _num((existing_order.get("fills") or [{}])[0].get("price"))
                                        fill_price = round(float(fill_price_raw), 4)
                                        fee = sum(_num(f.get("commission")) for f in (existing_order.get("fills") or []))
                                        _is_trdca_or_multi = (reason == "trdca_batch" or getattr(config, "symbol", None) == "MULTI")
                                        if not _is_trdca_or_multi:
                                            apply_fill_to_state(state, side, exec_qty, fill_price, fee, grid_index=a.get("grid_index"), reason=reason, execution_price=a.get("execution_price"))
                                            if reason == "initial_allocation":
                                                state["initial_allocation_done"] = True
                                                if state.get("reference_price") is None and fill_price:
                                                    state["reference_price"] = fill_price
                                                logger.info("BOT_EXECUTION_REPAIR bot_id=%s initial_allocation_done=True base_balance=%.4f quote_balance=%.2f", bot_id, state.get("base_balance"), state.get("quote_balance"))
                                            if reason in CYCLE_FILL_REASONS:
                                                ledger = cycle_ledger_from_state(state, symbol)
                                                if ledger.get("cycle_id") != state.get("cycle_id"):
                                                    ledger = build_cycle_ledger_empty(int(state.get("cycle_id") or 1), symbol)
                                                cycle_ledger_add_fill(ledger, ts=datetime.now(timezone.utc).isoformat(), order_id=str(existing_order.get("orderId")), client_order_id=coid_repair, side=side, qty=exec_qty, price=fill_price, fee=fee, fee_asset="USDT", reason=reason)
                                                state["cycle_ledger_current"] = ledger
                                            save_state(db, bot_id, account_id, state)
                                        if db is not None:
                                            try:
                                                Ledger.record_trade(
                                                    db, bot_id, account_id, side, exec_qty, fill_price, fee=fee, fee_asset="USDT",
                                                    slot_id=a.get("grid_index"), order_id=str(order_id_repair), client_order_id=coid_repair, symbol=symbol,
                                                    cycle_id=int(state.get("cycle_id") or 1),
                                                )
                                            except Exception as led_ex:
                                                logger.warning("BOT_EXECUTION_REPAIR record_trade failed bot_id=%s order_id=%s err=%s", bot_id, order_id_repair, led_ex)
                                            append_event(db, bot_id, account_id, "ORDER_FILLED", f"repaired=true orderId={order_id_repair} trades_match={trades_match_count}", {"repaired": True, "orderId": order_id_repair, "trades_match_count": trades_match_count})
                                        logger.info(
                                            "INITIAL_ALLOC_VERIFY result=OK orderId=%s trades_match_count=%s",
                                            order_id_repair, trades_match_count,
                                        )
                                        logger.info("BOT_EXECUTION_REPAIR bot_id=%s reason=%s intent_already_filled state_synced_from_binance order_id=%s", bot_id, reason, order_id_repair)
                                        verified_filled = True
                            except Exception as repair_err:
                                logger.debug("intent_filled state repair failed: %s", repair_err)
                        if verified_filled:
                            logger.info("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=INTENT_ALREADY_FILLED intent_id=%s", bot_id, reason, intent_id)
                            continue
                    if not is_new and intent_row:
                        client_order_id = (intent_row.get("client_order_id") or client_order_id)[:36]
                    try:
                        existing_order = await adapter.get_order_by_client_order_id(symbol, client_order_id)
                        if existing_order:
                            status = (existing_order.get("status") or "").upper()
                            if status == "FILLED":
                                order_id_ex = existing_order.get("orderId")
                                try:
                                    order_id_ex_int = int(order_id_ex) if order_id_ex is not None else 0
                                except (TypeError, ValueError):
                                    order_id_ex_int = 0
                                trades_ex = await adapter.get_my_trades_for_order(symbol, order_id_ex_int) if order_id_ex_int else []
                                trades_match_count = len(trades_ex)
                                if trades_match_count == 0:
                                    logger.info(
                                        "INITIAL_ALLOC_VERIFY result=FAIL orderId=%s trades_match_count=0 => NOT_FOUND, proceeding to place",
                                        order_id_ex,
                                    )
                                    existing_order = None
                                else:
                                    exec_qty = _num(existing_order.get("executedQty"))
                                    cum_quote = _num(existing_order.get("cummulativeQuoteQty"))
                                    fill_price_raw = (cum_quote / exec_qty) if exec_qty else _num((existing_order.get("fills") or [{}])[0].get("price"))
                                    fill_price = round(float(fill_price_raw), 4)
                                    fee = sum(_num(f.get("commission")) for f in (existing_order.get("fills") or []))
                                    update_intent_filled(db, intent_id, order_id_ex)
                                    _is_trdca_or_multi = (reason == "trdca_batch" or getattr(config, "symbol", None) == "MULTI")
                                    if not _is_trdca_or_multi:
                                        apply_fill_to_state(state, side, exec_qty, fill_price, fee, grid_index=a.get("grid_index"), reason=reason, execution_price=a.get("execution_price"))
                                        if reason in CYCLE_FILL_REASONS:
                                            ledger = cycle_ledger_from_state(state, symbol)
                                            if ledger.get("cycle_id") != state.get("cycle_id"):
                                                ledger = build_cycle_ledger_empty(int(state.get("cycle_id") or 1), symbol)
                                            cycle_ledger_add_fill(ledger, ts=datetime.now(timezone.utc).isoformat(), order_id=str(order_id_ex), client_order_id=client_order_id, side=side, qty=exec_qty, price=fill_price, fee=fee, fee_asset="USDT", reason=reason)
                                            state["cycle_ledger_current"] = ledger
                                        save_state(db, bot_id, account_id, state)
                                        if db is not None:
                                            try:
                                                Ledger.record_trade(db, bot_id, account_id, side, exec_qty, fill_price, fee=fee, fee_asset="USDT", slot_id=a.get("grid_index"), order_id=str(order_id_ex), client_order_id=client_order_id, symbol=symbol, cycle_id=int(state.get("cycle_id") or 1))
                                            except Exception:
                                                pass
                                            append_event(db, bot_id, account_id, "ORDER_FILLED", f"repaired=true orderId={order_id_ex} trades_match={trades_match_count}", {"repaired": True, "orderId": order_id_ex, "trades_match_count": trades_match_count})
                                    logger.info("INITIAL_ALLOC_VERIFY result=OK orderId=%s trades_match_count=%s", order_id_ex, trades_match_count)
                                    results.append({"order_id": order_id_ex, "client_order_id": client_order_id, "side": side, "fill_qty": exec_qty, "fill_price": fill_price, "fee": fee, "reason": reason})
                                    continue
                            if existing_order and status in ("NEW", "PARTIALLY_FILLED"):
                                logger.info("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=ORDER_ALREADY_SENT intent_id=%s status=%s", bot_id, reason, intent_id, status)
                                continue
                    except Exception as recon_err:
                        logger.debug("get_order_by_client_order_id failed (proceeding): %s", recon_err)
                else:
                    client_order_id = a.get("client_order_id") or f"be_{bot_id}_{key}"[:36]
                price = adapter.get_price(symbol) or 0.0
                notional = (quote_qty if side == "BUY" else qty * price) if price else 0
                min_notional = getattr(config, "min_notional_guard", 10.0)
                if not guard_min_notional(notional, min_notional):
                    logger.warning("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=MIN_NOTIONAL notional=%.2f min=%.2f", bot_id, reason, notional, min_notional)
                    if db is not None:
                        append_event(db, bot_id, account_id, "SKIP_REASON", f"MIN_NOTIONAL notional={notional:.2f} min={min_notional:.2f}", {"reason": reason, "skip_reason": "MIN_NOTIONAL", "notional": notional, "min_notional": min_notional})
                    continue
                if reason == "initial_allocation":
                    fee_buffer_pct = float(getattr(config, "initial_fee_buffer_pct", 0.002) or 0.002)
                    required = float(quote_qty) * (1.0 + fee_buffer_pct)
                    logger.info(
                        "BOT_CFG bot_id=%s symbol=%s budget=%.2f base_pct=%.2f quote_pct=%.2f fee_buffer=%.4f",
                        bot_id, symbol,
                        float(getattr(config, "initial_capital_usdt", 0) or getattr(config, "bot_budget_usdt", 0) or 0),
                        float(getattr(config, "base_alloc_pct", 50) or 50),
                        float(getattr(config, "quote_alloc_pct", 50) or 50),
                        fee_buffer_pct,
                    )
                    binance_balances = await adapter.get_account_balances()
                    base_asset = (symbol or "BTCUSDT").replace("USDT", "") or "BTC"
                    quote_asset = "USDT"
                    base_free = float((binance_balances.get(base_asset) or {}).get("free") or 0)
                    quote_free = float((binance_balances.get(quote_asset) or {}).get("free") or 0)
                    logger.info(
                        "BOT_BALANCES bot_id=%s base_asset=%s base_free=%.6f quote_asset=%s quote_free=%.2f",
                        bot_id, base_asset, base_free, quote_asset, quote_free,
                    )
                    available = quote_free
                    eps = 1e-6
                    if available + eps < required:
                        # Cap initial_allocation to available balance so the first buy can execute (parametre bütçesi > cüzdan serbest bakiyesi olabilir)
                        capped_quote = round(float(available) / (1.0 + fee_buffer_pct), 2)
                        if capped_quote >= min_notional and capped_quote > 0:
                            logger.info(
                                "BOT_INITIAL_ALLOC_CAP bot_id=%s quote_qty=%.2f -> %.2f (available=%.2f insufficient for requested)",
                                bot_id, quote_qty, capped_quote, available,
                            )
                            quote_qty = capped_quote
                            required = quote_qty * (1.0 + fee_buffer_pct)
                            if db is not None:
                                append_event(db, bot_id, account_id, "INFO", f"İlk alım miktarı bakiyeye göre düşürüldü: {quote_qty:.2f} {quote_asset} (mevcut bakiye: {available:.2f})", {"capped_quote_qty": quote_qty, "available": available, "action_key": key})
                            decision = "EXECUTE"
                        else:
                            decision = "SKIP"
                            logger.info(
                                "BOT_REQUIRED bot_id=%s quote_qty=%.2f required=%.2f available=%.2f decision=%s",
                                bot_id, quote_qty, required, available, decision,
                            )
                            logger.warning(
                                "BOT_EXECUTION_SKIP bot_id=%s reason=initial_allocation skip_reason=INSUFFICIENT_QUOTE required=%.2f available=%.2f",
                                bot_id, required, available,
                            )
                            if db is not None:
                                append_event(db, bot_id, account_id, "SKIP_REASON", f"INSUFFICIENT_QUOTE required={required:.2f} available={available:.2f}", {
                                    "error_code": "INSUFFICIENT_QUOTE", "required": required, "available": available, "action_key": key,
                                })
                            continue
                    else:
                        decision = "EXECUTE"
                    logger.info(
                        "BOT_REQUIRED bot_id=%s quote_qty=%.2f required=%.2f available=%.2f decision=%s",
                        bot_id, quote_qty, required, available, decision,
                    )
                    logger.info(
                        "BOT_INITIAL_ALLOC_BUDGET bot_id=%s quote_asset=%s quote_qty=%.2f fee_buffer=%.4f required=%.2f available=%.2f decision=%s",
                        bot_id, quote_asset, quote_qty, fee_buffer_pct, required, available, decision,
                    )
                elif db is not None:
                    fee_buffer_pct = 0.002
                    buffer_pct = float(getattr(config, "available_quote_buffer_pct", 0.005) or 0.005)
                    is_trdca_or_multi = (
                        reason == "trdca_batch"
                        or getattr(config, "symbol", None) == "MULTI"
                        or (getattr(config, "strategy_id", "") or "").strip().lower() == "trdca_pro"
                    )
                    skip_virtual_check = adapter.paper_mode and is_trdca_or_multi
                    if side == "BUY" and not skip_virtual_check:
                        # Cap BUY to available_quote_for_orders = free_quote * (1 - buffer); prefer real free_quote from last fill snapshot
                        _vb, _vq = get_virtual_wallet(db, bot_id, symbol)
                        free_quote = state.get("free_quote")
                        if free_quote is None:
                            free_quote = float(_vq)
                        available_quote = max(0.0, float(free_quote) * (1.0 - buffer_pct))
                        if quote_qty > available_quote and available_quote > 0:
                            old_qty = quote_qty
                            quote_qty = round(available_quote, 2)
                            logger.info(
                                "BOT_EXECUTION_CAP_QUOTE bot_id=%s reason=%s quote_qty_capped %.2f -> %.2f (virtual available) free_quote=%.2f buffer_pct=%.4f",
                                bot_id, reason, old_qty, quote_qty, free_quote, buffer_pct,
                            )
                            append_event(db, bot_id, account_id, "INFO", f"quote_qty_capped {old_qty:.2f} -> {quote_qty:.2f} (virtual available)", {"reason": reason, "old_qty": old_qty, "quote_qty": quote_qty, "virtual_quote": _vq, "free_quote": free_quote})
                            notional_capped = quote_qty if price and price > 0 else quote_qty
                            if not guard_min_notional(notional_capped, config.min_notional_guard):
                                logger.warning("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=MIN_NOTIONAL_AFTER_CAP quote_qty=%.2f min=%.2f", bot_id, reason, quote_qty, config.min_notional_guard)
                                append_event(db, bot_id, account_id, "SKIP_REASON", f"MIN_NOTIONAL_AFTER_CAP quote_qty={quote_qty:.2f} min={config.min_notional_guard:.2f}", {"reason": reason, "skip_reason": "MIN_NOTIONAL_AFTER_CAP", "quote_qty": quote_qty})
                                continue
                    if not skip_virtual_check:
                        ok, budget_reason, required, available = check_virtual_budget(
                            db, bot_id, symbol, side,
                            quote_amount=quote_qty,
                            base_qty=qty,
                            price=price,
                            fee_buffer_pct=fee_buffer_pct,
                        )
                    else:
                        ok = True
                    if not ok:
                        payload = {
                            "error_code": "VIRTUAL_BUDGET_INSUFFICIENT",
                            "required": required,
                            "available": available,
                            "side": side,
                            "symbol": symbol,
                            "action_key": key,
                            "bot_id": bot_id,
                            "account_id": account_id,
                        }
                        append_event(
                            db, bot_id, account_id, "SKIP_REASON",
                            f"VIRTUAL_BUDGET insufficient required={required} available={available} side={side} symbol={symbol}",
                            payload,
                        )
                        if reason == "initial_allocation":
                            k = (bot_id, key)
                            _initial_alloc_skip_count[k] = _initial_alloc_skip_count.get(k, 0) + 1
                            if _initial_alloc_skip_count[k] > 3:
                                logger.warning(
                                    "BOT_INITIAL_ALLOC_SAME_KEY_REPEATED bot_id=%s action_key=%s count=%s (budget insufficient)",
                                    bot_id, key, _initial_alloc_skip_count[k],
                                )
                        logger.warning(
                            "BOT_EXECUTION_SKIP error_code=VIRTUAL_BUDGET_INSUFFICIENT bot_id=%s account_id=%s reason=%s action_key=%s required=%s available=%s",
                            bot_id, account_id, reason, key, required, available,
                        )
                        continue
                # Binance balance safety: BUY/SELL before sending order (virtual vs real drift). Paper mode: skip (simulated).
                if not adapter.paper_mode and side == "BUY":
                    try:
                        if reason == "initial_allocation" and binance_balances is not None:
                            balances = binance_balances
                        else:
                            balances = await adapter.get_account_balances()
                        usdt = balances.get("USDT") or {}
                        free_usdt = float(usdt.get("free") or 0)
                        fee_buffer_usdt = 0.5
                        if quote_qty + fee_buffer_usdt > free_usdt:
                            logger.warning(
                                "BOT_EXECUTION_SKIP error_code=BINANCE_FREE_QUOTE_INSUFFICIENT bot_id=%s quote_qty=%.2f free_usdt=%.2f fee_buffer=%.2f",
                                bot_id, quote_qty, free_usdt, fee_buffer_usdt,
                            )
                            if db is not None:
                                append_event(db, bot_id, account_id, "SKIP_REASON", f"BINANCE_FREE_QUOTE_INSUFFICIENT quote_qty={quote_qty:.2f} free_usdt={free_usdt:.2f}", {"error_code": "BINANCE_FREE_QUOTE_INSUFFICIENT", "quote_qty": quote_qty, "free_usdt": free_usdt})
                            continue
                    except Exception as bal_err:
                        if _is_401_unauthorized(bal_err):
                            if not _should_log_exec_401(bot_id):
                                logger.debug("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=401 (throttled)", bot_id)
                            else:
                                logger.warning("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=401 Unauthorized (tekrar 10 dk içinde loglanmayacak)", bot_id)
                        else:
                            logger.warning("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=%s (proceeding)", bot_id, bal_err)
                elif not adapter.paper_mode and side == "SELL":
                    try:
                        balances = await adapter.get_account_balances()
                        base_asset = (symbol or "BTCUSDT").replace("USDT", "").strip() or "BTC"
                        base_bal = balances.get(base_asset) or {}
                        free_base = float(base_bal.get("free") or 0)
                        base_buffer = 0.001
                        if qty > free_base * (1.0 - base_buffer) and free_base >= 0:
                            logger.warning(
                                "BOT_EXECUTION_SKIP error_code=BINANCE_FREE_BASE_INSUFFICIENT bot_id=%s reason=%s qty=%.6f free_base=%.6f (virtual>real)",
                                bot_id, reason, qty, free_base,
                            )
                            if db is not None:
                                append_event(
                                    db, bot_id, account_id, "SKIP_REASON",
                                    f"BINANCE_FREE_BASE_INSUFFICIENT qty={qty:.6f} free_base={free_base:.6f} (virtual balance > real)",
                                    {"error_code": "BINANCE_FREE_BASE_INSUFFICIENT", "qty": qty, "free_base": free_base, "base_asset": base_asset, "reason": reason, "action_key": key},
                                )
                            continue
                    except Exception as bal_err:
                        if _is_401_unauthorized(bal_err):
                            if not _should_log_exec_401(bot_id):
                                logger.debug("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=401 (throttled)", bot_id)
                            else:
                                logger.warning("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=401 Unauthorized (tekrar 10 dk içinde loglanmayacak)", bot_id)
                        else:
                            logger.warning("BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=%s (proceeding)", bot_id, bal_err)
                if db is not None and intent_id:
                    update_intent_submitting(db, intent_id)
                try:
                    from app.services.binance_weight import request_weight_tokens
                    weight = 1
                    if not adapter.paper_mode:
                        allowed = await request_weight_tokens(account_id, getattr(adapter.keys, "api_key", None), weight)
                        if not allowed:
                            if db is not None and intent_id:
                                update_intent_unknown(db, intent_id, error_code="WEIGHT_DENIED", error_id=str(uuid.uuid4()))
                            logger.warning("run_actions WEIGHT_DENIED bot_id=%s account_id=%s", bot_id, account_id)
                            continue
                    try:
                        from app.core.config import is_worker_role
                        logger.info(
                            "EXEC_ORDER_ATTEMPT bot_id=%s run_id=%s intent_id=%s coid=%s symbol=%s side=%s quote_qty=%s qty=%s paper=%s",
                            bot_id, run_id, intent_id or "", (client_order_id or "")[:36], symbol, side, quote_qty, qty, adapter.paper_mode,
                        )
                        if side == "BUY":
                            res = await asyncio.wait_for(adapter.place_market_buy(symbol, quote_qty, client_order_id), timeout=3.0)
                        else:
                            res = await asyncio.wait_for(adapter.place_market_sell(symbol, qty, client_order_id), timeout=3.0)
                    except asyncio.TimeoutError:
                        if db is not None and intent_id:
                            update_intent_unknown(db, intent_id, error_code="TIMEOUT", error_id=str(uuid.uuid4()))
                        logger.warning("run_actions TIMEOUT bot_id=%s intent_id=%s (reconcile will resolve)", bot_id, intent_id)
                        continue
                    if db is not None and intent_id:
                        update_intent_sent(db, intent_id)
                except Exception as e:
                    error_id = str(uuid.uuid4())
                    insufficient = False
                    request_id = None
                    try:
                        import httpx
                        import json as _json
                        from app.services.binance_spot import BinanceSignedError
                        if isinstance(e, BinanceSignedError):
                            if getattr(e, "code", None) == -2010:
                                insufficient = True
                            request_id = None
                            if isinstance(getattr(e, "data", None), dict):
                                request_id = (e.data.get("requestId") or e.data.get("request_id")) or None
                        elif isinstance(e, httpx.HTTPStatusError) and getattr(e, "response", None):
                            resp = e.response
                            body = (getattr(resp, "text", None) or "")[:500]
                            try:
                                b = _json.loads(body) if body else {}
                                if isinstance(b, dict) and b.get("code") == -2010:
                                    insufficient = True
                                request_id = (b.get("requestId") or b.get("request_id")) if isinstance(b, dict) else None
                            except Exception:
                                if body and "-2010" in body:
                                    insufficient = True
                            if getattr(resp, "status_code", None) == 400 and not insufficient and body and "-2010" in body:
                                insufficient = True
                            if request_id is None and hasattr(resp, "headers"):
                                request_id = (resp.headers.get("X-MBX-REQUEST-ID") or resp.headers.get("x-request-id")) or None
                    except Exception:
                        pass
                    if insufficient and db is not None:
                        from app.db.models import Bot
                        bot_row = db.query(Bot).filter(Bot.id == bot_id).first()
                        if bot_row:
                            bot_row.status = "paused_insufficient_balance"
                            db.commit()
                        state["last_error_code"] = "INSUFFICIENT_BALANCE"
                        state["backoff_until"] = time.time() + 60
                        append_event(db, bot_id, account_id, "ERROR", f"INSUFFICIENT_BALANCE {error_id} {e!s}", {
                            "error_code": "INSUFFICIENT_BALANCE", "error_id": error_id, "request_id": request_id, "bot_id": bot_id, "account_id": account_id, "action_key": key, "loop_id": loop_id,
                        })
                        logger.warning(
                            "BOT_EXECUTION_INSUFFICIENT_BALANCE error_code=INSUFFICIENT_BALANCE error_id=%s request_id=%s bot_id=%s account_id=%s loop_id=%s (60s backoff, bot paused)",
                            error_id, request_id or "-", bot_id, account_id, loop_id or "",
                        )
                        continue
                    if _is_401_unauthorized(e):
                        state["backoff_until"] = time.time() + _EXEC_401_BACKOFF_SEC
                        state["last_error_code"] = "API_UNAUTHORIZED"
                        if db is not None:
                            from app.db.models import Bot
                            bot_row = db.query(Bot).filter(Bot.id == bot_id).first()
                            if bot_row:
                                bot_row.status = "paused_error"
                                db.commit()
                            append_event(db, bot_id, account_id, "ERROR", "Binance 401 Unauthorized – API anahtarı geçersiz, IP beyaz listesi veya Spot izinlerini kontrol edin.", {
                                "error_code": "API_UNAUTHORIZED", "error_id": error_id, "bot_id": bot_id, "account_id": account_id, "action_key": key, "loop_id": loop_id,
                            })
                            save_state(db, bot_id, account_id, state)
                        if not _should_log_exec_401(bot_id):
                            logger.debug("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401 bot paused (throttled log)", bot_id, reason)
                        else:
                            logger.warning("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401 Unauthorized – bot paused_error, API key/IP/izinleri kontrol edin", bot_id, reason)
                        continue
                    logger.warning("BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=ORDER_FAILED err=%s", bot_id, reason, e)
                    state["last_error_code"] = "ORDER_FAILED"
                    if db is not None:
                        append_event(db, bot_id, account_id, "SKIP_REASON", f"ORDER_FAILED err={str(e)}", {"reason": reason, "skip_reason": "ORDER_FAILED", "error": str(e), "error_id": error_id})
                    continue
                # Persist intent FILLED (idempotency: state saved AFTER intent persisted)
                if db is not None and intent_id:
                    update_intent_filled(db, intent_id, res.get("orderId"))
                # Parse fill
                fills = res.get("fills") or []
                exec_qty = _num(res.get("executedQty"))
                cum_quote = _num(res.get("cummulativeQuoteQty"))
                fill_price_raw = (cum_quote / exec_qty) if exec_qty else _num(fills[0].get("price")) if fills else 0
                fill_price = round(float(fill_price_raw), 4)
                fee = sum(_num(f.get("commission")) for f in fills)
                fee_asset = (fills[0].get("commissionAsset") or "").strip() if fills else ""
                if fee_asset and fee_asset != "USDT" and fee > 0:
                    # Komisyon USDT değilse (örn. BNB) USDT karşılığına çevir; böylece Trade.fee ve performans toplamı anlamlı olur
                    try:
                        from app.services.price_hub import price_hub
                        p = price_hub.get_price(fee_asset + "USDT") or price_hub.get_price("USDT" + fee_asset)
                        if p is not None and float(p) > 0:
                            fee = fee * float(p)
                            fee_asset = "USDT"
                        else:
                            fee = 0
                    except Exception as _ex:
                        logger.debug("fee_convert %s->USDT failed: %s", fee_asset, _ex)
                        fee = 0
                is_multi_rebalance = (
                    getattr(config, "symbol", None) == "MULTI"
                    or ((getattr(config, "strategy_id", "") or "").strip().lower() == "multi_asset_rebalance")
                )
                if reason == "trdca_batch":
                    results.append({
                        "order_id": res.get("orderId"),
                        "client_order_id": client_order_id,
                        "symbol": symbol,
                        "side": side,
                        "fill_qty": exec_qty,
                        "fill_price": fill_price,
                        "fee": fee,
                        "reason": reason,
                        "status": (res.get("status") or "FILLED").upper(),
                    })
                    continue
                if is_multi_rebalance:
                    results.append({
                        "order_id": res.get("orderId"),
                        "client_order_id": client_order_id,
                        "side": side,
                        "fill_qty": exec_qty,
                        "fill_price": fill_price,
                        "fee": fee,
                        "reason": reason,
                    })
                    if db is not None:
                        save_state(db, bot_id, account_id, state)
                    continue
                apply_fill_to_state(
                    state,
                    side,
                    exec_qty,
                    fill_price,
                    fee,
                    grid_index=a.get("grid_index"),
                    reason=reason,
                    execution_price=a.get("execution_price"),
                )
                # Cycle ledger: record only cycle-scoped fills (single source of truth for cycle PnL)
                if reason in CYCLE_FILL_REASONS:
                    ledger = cycle_ledger_from_state(state, symbol)
                    if ledger.get("cycle_id") != state.get("cycle_id"):
                        ledger = build_cycle_ledger_empty(int(state.get("cycle_id") or 1), symbol)
                    ts_iso = datetime.now(timezone.utc).isoformat()
                    cycle_ledger_add_fill(
                        ledger,
                        ts=ts_iso,
                        order_id=str(res.get("orderId")) if res.get("orderId") is not None else None,
                        client_order_id=client_order_id,
                        side=side,
                        qty=exec_qty,
                        price=fill_price,
                        fee=fee,
                        fee_asset="USDT",
                        reason=reason,
                    )
                    state["cycle_ledger_current"] = ledger
                # initial_allocation: ia_done ONLY when order really filled (exec_qty > 0)
                if reason == "initial_allocation":
                    if exec_qty <= 0:
                        logger.critical(
                            "BOT_INITIAL_ALLOC_FILL_INVALID bot_id=%s account_id=%s exec_qty=%s (ia_done NOT set)",
                            bot_id, account_id, exec_qty,
                        )
                    else:
                        state["initial_allocation_done"] = True
                        state["reference_price"] = fill_price
                        state["cycle_id"] = 1
                        state["initial_alloc_base_qty"] = round(float(exec_qty), 10)
                        state["initial_alloc_price"] = round(float(fill_price), 10)
                        C = _num(getattr(config, "initial_capital_usdt", 0))
                        state["quote_balance"] = round(max(0.0, C - cum_quote - fee), 10)
                        state["base_balance"] = round(float(exec_qty), 10)
                        state["grid_reference_quote"] = state["quote_balance"]
                        state["cycle_start_equity"] = round(state["quote_balance"] + state["base_balance"] * fill_price, 2)
                        _initial_alloc_skip_count.pop((bot_id, key), None)
                        if db is not None:
                            save_state(db, bot_id, account_id, state)
                if reason == "trail_sell_grid":
                    idx = a.get("grid_index", 0)
                    state.setdefault("sell_grid_fired", [])
                    if idx < len(state["sell_grid_fired"]):
                        state["sell_grid_fired"][idx] = True
                    # Tamamlanan grid için tepe fiyatını dondur (bir daha güncellenmez)
                    state.setdefault("sell_grid_peak_price", [])
                    while len(state["sell_grid_peak_price"]) <= idx:
                        state["sell_grid_peak_price"].append(None)
                    peak_val = a.get("trail_anchor_price") or state.get("trail_anchor_price")
                    if peak_val is not None:
                        state["sell_grid_peak_price"][idx] = float(peak_val)
                    # Binance'teki gerçek işlem fiyatını grid için sakla (UI'da Gerçekleşme fiyatı)
                    state.setdefault("sell_grid_fill_price", [])
                    while len(state["sell_grid_fill_price"]) <= idx:
                        state["sell_grid_fill_price"].append(None)
                    state["sell_grid_fill_price"][idx] = fill_price
                if reason == "trail_buy_grid":
                    idx = a.get("grid_index", 0)
                    state.setdefault("buy_grid_fired", [])
                    if idx < len(state["buy_grid_fired"]):
                        state["buy_grid_fired"][idx] = True
                    # Tamamlanan grid için dip fiyatını dondur (bir daha güncellenmez)
                    state.setdefault("buy_grid_trough_price", [])
                    while len(state["buy_grid_trough_price"]) <= idx:
                        state["buy_grid_trough_price"].append(None)
                    trough_val = a.get("trail_anchor_price") or state.get("trail_anchor_price")
                    if trough_val is not None:
                        state["buy_grid_trough_price"][idx] = float(trough_val)
                    # Binance'teki gerçek işlem fiyatını grid için sakla (UI'da Gerçekleşme fiyatı)
                    state.setdefault("buy_grid_fill_price", [])
                    while len(state["buy_grid_fill_price"]) <= idx:
                        state["buy_grid_fill_price"].append(None)
                    state["buy_grid_fill_price"][idx] = fill_price
                results.append({
                    "order_id": res.get("orderId"),
                    "client_order_id": client_order_id,
                    "side": side,
                    "fill_qty": exec_qty,
                    "fill_price": fill_price,
                    "fee": fee,
                    "reason": reason,
                })
                # Cycle reset MUST run before any load_state: in-memory state has _cycle_complete and updated balances.
                cycle_id_for_trade = int(state.get("cycle_id") or 1)
                ref_price_for_ledger = state.get("reference_price")  # referansı reset'ten önce al (gerçekleşme % doğru kalsın)
                if state.get("_cycle_complete") or reason in ("trail_reentry_buy", "trail_profit_sell"):
                    pnl_mode = getattr(config, "pnl_mode", "cycle_only_fee_aware_v1") or "cycle_only_fee_aware_v1"
                    ledger = state.get("cycle_ledger_current")
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        matched_qty = float(ledger.get("matched_qty") or 0)
                        # Dual PnL: primary by close_reason
                        close_reason = reason
                        pnl_primary_mode = PNL_MODE_CASH if close_reason == "trail_profit_sell" else (PNL_MODE_INVENTORY if close_reason == "trail_reentry_buy" else "cycle_only_fee_aware_v1")
                        inv_coin_adv = float(ledger.get("inventory_coin_adv_qty") or 0)
                        inv_fees = float(ledger.get("inventory_fees_usdt") or 0)
                        cash_pnl = float(ledger.get("cash_pnl_usdt") or 0)
                        cash_fees = float(ledger.get("cash_fees_usdt") or 0)
                        # USDT net: only meaningful for Cash cycle; for Inventory cycle show 0 so UI uses inventory metric
                        if pnl_primary_mode == PNL_MODE_CASH:
                            pnl = round(cash_pnl, 4)
                            fees = round(cash_fees, 4)
                        else:
                            pnl = 0.0 if pnl_primary_mode == PNL_MODE_INVENTORY else round(float(ledger.get("realized_pnl_quote") or 0), 4)
                            fees = round(inv_fees, 4) if pnl_primary_mode == PNL_MODE_INVENTORY else round(float(ledger.get("buy_fee_total_quote") or 0) + float(ledger.get("sell_fee_total_quote") or 0), 4)
                    else:
                        pnl = round(float(state.get("realized_pnl_usdt_cycle") or 0), 4)
                        fees = round(float(state.get("fees_paid_usdt_cycle") or 0), 4)
                        matched_qty = None
                        close_reason = reason
                        pnl_primary_mode = "cycle_only_fee_aware_v1"
                        inv_coin_adv = inv_fees = cash_pnl = cash_fees = None
                    if not (pnl_mode == "cycle_only_fee_aware_v1" and ledger):
                        close_reason = reason
                    cycle_type, base_delta = get_cycle_type_and_base_delta(close_reason, ledger)
                    close_side = "SELL" if close_reason == "trail_profit_sell" else "BUY" if close_reason == "trail_reentry_buy" else ("SELL" if "sell" in (close_reason or "").lower() else "BUY")
                    ts_iso = datetime.now(timezone.utc).isoformat()
                    # CYCLE_END invariant (Spec §55): derive ONLY from recomputed ledger. profit_usdt = gross, pnl_usdt_net = net.
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        cash_pnl_gross = float(ledger.get("cash_pnl_usdt") or 0)
                        fees_usdt_canon = float(ledger.get("cash_fees_usdt") or 0)
                        realized_net = float(ledger.get("realized_pnl_quote") or 0)
                        pnl = realized_net
                        fees = fees_usdt_canon
                    cycle_entry = {
                        "cycle_id": cycle_id_for_trade,
                        "pnl_usdt_net": pnl,
                        "fees_usdt": fees,
                        "matched_qty": matched_qty,
                        "cycle_type": cycle_type,
                        "base_delta": base_delta,
                        "close_reason": close_reason,
                        "close_side": close_side,
                        "pnl_mode": pnl_mode,
                        "pnl_primary_mode": pnl_primary_mode,
                        "inventory_coin_adv_qty": round(inv_coin_adv, 8) if inv_coin_adv is not None else None,
                        "inventory_fees_usdt": round(inv_fees, 4) if inv_fees is not None else None,
                        "cash_pnl_usdt": round(cash_pnl, 4) if cash_pnl is not None else None,
                        "cash_fees_usdt": round(cash_fees, 4) if cash_fees is not None else None,
                        "ts": ts_iso,
                    }
                    cycle_entry["pnl_usdt"] = pnl  # backward compat
                    state.setdefault("cycle_pnls", []).append(cycle_entry)
                    state["realized_pnl_usdt_cycle"] = 0.0
                    state["fees_paid_usdt_cycle"] = 0.0
                    # Meta from ledger only: profit_usdt = cash_pnl (gross), pnl_usdt_net = realized_pnl_cycle_net
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        meta = {
                            "cycle_id": cycle_id_for_trade,
                            "profit_usdt": round(float(ledger.get("cash_pnl_usdt") or 0), 2),
                            "pnl_usdt_net": round(float(ledger.get("realized_pnl_quote") or 0), 4),
                            "realized_pnl_cycle_net": round(float(ledger.get("realized_pnl_quote") or 0), 4),
                            "fees_usdt": round(float(ledger.get("cash_fees_usdt") or 0), 4),
                            "buy_quote_total": ledger.get("buy_quote_total"),
                            "sell_quote_total": ledger.get("sell_quote_total"),
                            "fee_totals_quote": round(float(ledger.get("cash_fees_usdt") or 0), 4),
                            "pnl_mode": pnl_mode,
                            "pnl_primary_mode": cycle_entry.get("pnl_primary_mode"),
                            "matched_qty": matched_qty,
                            "cycle_type": cycle_type,
                            "base_delta": base_delta,
                            "close_reason": close_reason,
                            "close_side": close_side,
                            "inventory_coin_adv_qty": cycle_entry.get("inventory_coin_adv_qty"),
                            "inventory_fees_usdt": cycle_entry.get("inventory_fees_usdt"),
                            "cash_pnl_usdt": round(float(ledger.get("cash_pnl_usdt") or 0), 4),
                            "cash_fees_usdt": round(float(ledger.get("cash_fees_usdt") or 0), 4),
                        }
                    else:
                        meta = {
                            "cycle_id": cycle_id_for_trade,
                            "profit_usdt": round(float(pnl), 2),
                            "pnl_usdt_net": pnl,
                            "pnl_mode": pnl_mode,
                            "pnl_primary_mode": cycle_entry.get("pnl_primary_mode"),
                            "matched_qty": matched_qty,
                            "fees_usdt": fees,
                            "cycle_type": cycle_type,
                            "base_delta": base_delta,
                            "close_reason": close_reason,
                            "close_side": close_side,
                            "inventory_coin_adv_qty": cycle_entry.get("inventory_coin_adv_qty"),
                            "inventory_fees_usdt": cycle_entry.get("inventory_fees_usdt"),
                            "cash_pnl_usdt": cycle_entry.get("cash_pnl_usdt"),
                            "cash_fees_usdt": cycle_entry.get("cash_fees_usdt"),
                        }
                    # Persist completed cycle dual PnL snapshot before reset (spec: completed_cycle_dual_pnls)
                    completed_list = state.get("completed_cycle_dual_pnls") or []
                    fills = ledger.get("fills") or []
                    last_fill_ts_iso = fills[-1].get("ts") if fills else ts_iso
                    cash_pnl = float(ledger.get("cash_fifo_pnl_usdt") if ledger.get("cash_fifo_pnl_usdt") is not None else ledger.get("cash_pnl_usdt") or 0)
                    cash_fees = float(ledger.get("cash_fifo_fees_usdt") if ledger.get("cash_fifo_fees_usdt") is not None else ledger.get("cash_fees_usdt") or 0)
                    inv_qty = float(ledger.get("inventory_coin_adv_qty") or 0)
                    inv_fees = float(ledger.get("inventory_fees_usdt") or 0)
                    cycle_type_snapshot = "CASH" if reason == "trail_profit_sell" else "INVENTORY"
                    completed_list.append({
                        "cycle_id": cycle_id_for_trade,
                        "cycle_type": cycle_type_snapshot,
                        "cash_pnl_usdt": round(cash_pnl, 8),
                        "cash_fees_usdt": round(cash_fees, 8),
                        "inventory_coin_adv_qty": round(inv_qty, 12),
                        "inventory_fees_usdt": round(inv_fees, 8),
                        "completed_at": last_fill_ts_iso,
                        "completed_reason": reason,
                    })
                    state["completed_cycle_dual_pnls"] = completed_list[-200:]  # cap at 200
                    n = len(config.sell_grids)
                    m = len(config.buy_grids)
                    cycle_reset_after_fill(state, fill_price, n, m, symbol=symbol)
                    # Reinvest policy: target budgets from equity (order sizing reference only; no rebalance order)
                    quote_bal = _num(state.get("quote_balance"))
                    base_bal = _num(state.get("base_balance"))
                    equity_usdt = round(quote_bal + base_bal * fill_price, 2)
                    quote_alloc = _num(getattr(config, "quote_alloc_pct", 50)) / 100.0
                    base_alloc = _num(getattr(config, "base_alloc_pct", 50)) / 100.0
                    target_quote_usdt = round(equity_usdt * quote_alloc, 2)
                    target_base_usdt = round(equity_usdt * base_alloc, 2)
                    state["target_budgets"] = {
                        "equity_usdt": equity_usdt,
                        "target_quote_usdt": target_quote_usdt,
                        "target_base_usdt": target_base_usdt,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                    logger.info(
                        "BOT_TARGET_BUDGETS_UPDATED bot_id=%s equity_usdt=%.2f target_quote=%.2f target_base=%.2f base_bal=%.6f quote_bal=%.2f price=%.4f",
                        bot_id, equity_usdt, target_quote_usdt, target_base_usdt, base_bal, quote_bal, fill_price,
                    )
                    if db is not None:
                        append_event(db, bot_id, account_id, "CYCLE_END", "Tur bitti", meta)
                        logger.info(
                            "BOT_CYCLE_END bot_id=%s cycle_id=%s pnl_usdt_net=%.4f cycle_type=%s base_delta=%s matched_qty=%s fees_usdt=%.4f pnl_mode=%s",
                            bot_id, cycle_id_for_trade, pnl, cycle_type, base_delta, matched_qty, fees, pnl_mode,
                        )
                # Patch-1: persist fill to trades table (idempotent by order_id)
                if db is not None:
                    try:
                        oid = res.get("orderId")
                        ref_float = float(ref_price_for_ledger) if ref_price_for_ledger is not None else None
                        _, inserted = Ledger.record_trade(
                            db,
                            bot_id,
                            account_id,
                            side,
                            exec_qty,
                            fill_price,
                            fee=fee,
                            fee_asset="USDT",
                            slot_id=a.get("grid_index"),
                            reference_price=ref_float,
                            order_id=str(oid) if oid is not None else None,
                            client_order_id=client_order_id,
                            symbol=symbol,
                            cycle_id=cycle_id_for_trade,
                        )
                        if inserted:
                            logger.info(
                                "BOT_TRADE_RECORDED bot_id=%s side=%s qty=%s price=%s fee=%s order_id=%s request_id=-",
                                bot_id, side, exec_qty, fill_price, fee, oid,
                            )
                    except Exception as ex:
                        logger.warning("bot_engine execution record_trade failed bot_id=%s order_id=%s err=%s", bot_id, res.get("orderId"), ex)
                    try:
                        update_virtual_after_fill(db, bot_id, symbol, side, exec_qty, cum_quote, fee)
                    except Exception as ex:
                        logger.warning("bot_engine execution update_virtual_after_fill failed bot_id=%s err=%s", bot_id, ex)
                    try:
                        await _write_fill_snapshot_to_state(state, adapter, config, symbol)
                    except Exception as snap_err:
                        logger.warning("bot_engine execution write_fill_snapshot failed bot_id=%s err=%s", bot_id, snap_err)
                trigger_price = _num(a.get("trigger_price"))
                if trigger_price and trigger_price > 0 and db is not None:
                    max_slip = float(getattr(config, "max_slippage_pct", 0.5) or 0.5)
                    slip_pct = abs(fill_price - trigger_price) / trigger_price * 100.0
                    if slip_pct > max_slip:
                        append_event(
                            db, bot_id, account_id, "SLIPPAGE_WARN",
                            f"slip_pct={slip_pct:.2f} max={max_slip} trigger={trigger_price} fill={fill_price}",
                            {"slip_pct": slip_pct, "max_slippage_pct": max_slip, "trigger_price": trigger_price, "fill_price": fill_price, "reason": reason},
                        )
                        logger.warning("BOT SLIPPAGE_WARN bot_id=%s slip_pct=%.2f trigger=%.2f fill=%.2f", bot_id, slip_pct, trigger_price, fill_price)
            except Exception as e:
                error_id = str(uuid.uuid4())
                logger.exception(
                    "RUN_ACTION_EXCEPTION error_code=RUN_ACTION_EXCEPTION error_id=%s bot_id=%s account_id=%s action_key=%s loop_id=%s",
                    error_id, bot_id, account_id, key, loop_id or "",
                )
                if db is not None:
                    append_event(db, bot_id, account_id, "ERROR", f"RUN_ACTION_EXCEPTION {error_id} {e!s}", {
                        "error_code": "RUN_ACTION_EXCEPTION", "error_id": error_id, "bot_id": bot_id, "account_id": account_id, "action_key": key, "loop_id": loop_id,
                    })
                # state mutation must persist to state_store (orchestrator saves at tick end)
                state["last_error_code"] = "RUN_ACTION_EXCEPTION"
                continue
    duration_ms = (time.perf_counter() - t0) * 1000
    logger.info("run_actions end bot_id=%s duration_ms=%.0f", bot_id, duration_ms)
    return results
