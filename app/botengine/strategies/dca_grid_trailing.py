"""
DCA + two-way Grid + Trailing strategy.
State machine: IDLE | TRAIL_SELL_GRID | TRAIL_BUY_GRID | TRAIL_REENTRY_BUY | TRAIL_PROFIT_SELL.
Plugin: DcaGridTrailingStrategy (strategy_id=dca_grid_trailing).
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.models import BotEngineMode, DcaGridTrailingConfig
from app.botengine.strategies.base import Strategy

logger = logging.getLogger(__name__)


def _queue_grid_skip(
    state: Dict[str, Any],
    *,
    side: str,
    grid_index: int,
    notional: float,
    config: DcaGridTrailingConfig,
    reason: str,
) -> None:
    from app.botengine.state_store import queue_engine_event
    min_n = float(getattr(config, "min_notional_guard", 5.0) or 5.0)
    queue_engine_event(
        state,
        "SKIP_REASON",
        f"MIN_NOTIONAL side={side} notional={notional:.2f} min={min_n:.2f}",
        {
            "skip_reason": "MIN_NOTIONAL",
            "side": side,
            "grid_index": grid_index,
            "notional": round(float(notional), 4),
            "min_notional": min_n,
            "reason": reason,
            "cycle_id": int(state.get("cycle_id") or 1),
            "symbol": (config.symbol or "").upper().strip() or None,
        },
    )

def _f(v: Optional[float]) -> Optional[float]:
    """Safe float; None -> None (no crash). Callers must handle None."""
    if v is None:
        return None
    try:
        return round(float(v), 10)
    except (TypeError, ValueError):
        return None


def _ensure_sell_buy_lists(state: Dict[str, Any], cfg: DcaGridTrailingConfig) -> None:
    n = len(cfg.sell_grids)
    m = len(cfg.buy_grids)
    for k, default, size in [
        ("sell_grid_fired", False, n),
        ("sell_grid_trigger_price", None, n),
        ("sell_grid_peak_price", None, n),
        ("buy_grid_fired", False, m),
        ("buy_grid_trigger_price", None, m),
        ("buy_grid_trough_price", None, m),
    ]:
        arr = state.get(k)
        if not isinstance(arr, list):
            arr = []
        if isinstance(default, bool):
            base = [bool(arr[i]) if i < len(arr) else False for i in range(size)]
        else:
            base = [arr[i] if i < len(arr) else None for i in range(size)]
        state[k] = base
    if "sell_history" not in state:
        state["sell_history"] = []
    if "buy_history" not in state:
        state["buy_history"] = []


def _sync_trailing_mode(state: Dict[str, Any], n: int, m: int) -> None:
    """Legacy mode/index for logging and UI; grids trail in parallel via per-grid arrays."""
    sell_trailing: List[int] = []
    buy_trailing: List[int] = []
    for i in range(n):
        fired = bool(state["sell_grid_fired"][i]) if i < len(state.get("sell_grid_fired") or []) else False
        trig = state["sell_grid_trigger_price"][i] if i < len(state.get("sell_grid_trigger_price") or []) else None
        if not fired and trig is not None:
            sell_trailing.append(i)
    for j in range(m):
        fired = bool(state["buy_grid_fired"][j]) if j < len(state.get("buy_grid_fired") or []) else False
        trig = state["buy_grid_trigger_price"][j] if j < len(state.get("buy_grid_trigger_price") or []) else None
        if not fired and trig is not None:
            buy_trailing.append(j)
    if sell_trailing:
        state["mode"] = BotEngineMode.TRAIL_SELL_GRID.value
        state["_trail_sell_grid_index"] = sell_trailing[0]
        peaks = state.get("sell_grid_peak_price") or []
        if sell_trailing[0] < len(peaks) and peaks[sell_trailing[0]] is not None:
            state["trail_anchor_price"] = peaks[sell_trailing[0]]
    elif buy_trailing:
        state["mode"] = BotEngineMode.TRAIL_BUY_GRID.value
        state["_trail_buy_grid_index"] = buy_trailing[0]
        troughs = state.get("buy_grid_trough_price") or []
        if buy_trailing[0] < len(troughs) and troughs[buy_trailing[0]] is not None:
            state["trail_anchor_price"] = troughs[buy_trailing[0]]
    else:
        state["mode"] = BotEngineMode.IDLE.value


def tick_dca_grid_trailing(
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
    price: float,
    base_balance: float,
    quote_balance: float,
) -> Tuple[List[Dict[str, Any]], float]:
    """
    One strategy tick. Mutates state. Returns (actions, next_wakeup_sec).
    """
    _ensure_sell_buy_lists(state, config)
    P = _f(price)
    if P is None or P <= 0:
        logger.warning("BOT_STRATEGY_PRICE_INVALID bot_id=%s price=%s", state.get("bot_id", 0), price)
        return [], config.tick_interval_ms / 1000.0

    ref_raw = state.get("reference_price")
    initial_done = bool(state.get("initial_allocation_done"))
    init_base_qty_val = _f(state.get("initial_alloc_base_qty"))
    init_base_qty = (init_base_qty_val or 0.0) if init_base_qty_val is not None else 0.0
    # Self-heal: ia_done True but initial_alloc_base_qty 0 (e.g. state save failed) -> use base_balance
    if initial_done and init_base_qty <= 0 and base_balance > 0:
        state["initial_alloc_base_qty"] = round(float(base_balance), 10)
        init_base_qty = base_balance
        logger.info(
            "BOT_STATE_HEALED bot_id=%s initial_alloc_base_qty was 0, set from base_balance=%.6f",
            state.get("bot_id", 0), base_balance,
        )
    elif initial_done and init_base_qty <= 0:
        logger.critical(
            "BOT_STRATEGY_IA_INVALID bot_id=%s ia_done=True but initial_alloc_base_qty=%.6f (impossible)",
            state.get("bot_id", 0), init_base_qty,
        )
    # Self-heal: ia_done True but reference_price None (e.g. state save failed after fill)
    if initial_done and ref_raw is None:
        state["reference_price"] = P
        logger.info(
            "BOT_STATE_HEALED bot_id=%s reference_price was None, set to current price=%.2f",
            state.get("bot_id", 0), P,
        )
        ref_raw = P
    ref_val = _f(ref_raw)
    ref = (ref_val if ref_val is not None else 0.0) or P
    logger.debug(
        "BOT_STRATEGY_TICK bot_id=%s price=%.2f ref=%s ia_done=%s mode=%s base_bal=%.4f quote_bal=%.2f",
        state.get("bot_id", 0), P, ref, initial_done, state.get("mode", "IDLE"), base_balance, quote_balance
    )
    mode = state.get("mode") or BotEngineMode.IDLE.value
    cycle = int(state.get("cycle_id") or 1)
    n = len(config.sell_grids)
    m = len(config.buy_grids)
    actions: List[Dict[str, Any]] = []
    next_wake = config.tick_interval_ms / 1000.0

    # ---- Initial allocation (t0) ----
    # Strategy: only produce intent. ia_done set ONLY in execution after real fill. No state mutation here.
    if not initial_done:
        c = _f(config.initial_capital_usdt) or 0.0
        base_pct = (_f(config.base_alloc_pct) or 0.0) / 100.0
        quote_pct = (_f(config.quote_alloc_pct) or 0.0) / 100.0
        c_base = c * base_pct
        c_quote = c * quote_pct
        logger.info(
            "BOT_STRATEGY_INITIAL_ALLOC bot_id=%s price=%.2f budget=%.2f base_pct=%.1f quote_pct=%.1f base_qty_usdt=%.2f",
            state.get("bot_id", 0), P, c, base_pct * 100, quote_pct * 100, c_base
        )
        state["mode"] = BotEngineMode.IDLE.value
        actions.append({
            "type": "place",
            "side": "BUY",
            "symbol": config.symbol,
            "quote_qty": c_base,
            "client_order_id": f"init_{state.get('bot_id', 0)}_c{cycle}",
            "reason": "initial_allocation",
            "_c_quote": c_quote,
            "trigger_price": P,
        })
        logger.info("BOT_STRATEGY_INITIAL_ALLOC_ACTION bot_id=%s quote_qty=%.2f (intent only)", state.get("bot_id", 0), c_base)
        # İlk alım başarısız olursa kısa sürede tekrar dene (1s); başlar başlamaz alım yapılsın
        next_wake_initial = min(next_wake, 1.0)
        return actions, next_wake_initial
    else:
        logger.debug("BOT_STRATEGY_INITIAL_DONE bot_id=%s ia_done=True skipping initial alloc", state.get("bot_id", 0))

    # ---- Cycle-level exclusive trails (re-entry / profit exit) ----
    if mode == BotEngineMode.TRAIL_REENTRY_BUY.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(min(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 + config.profit_reentry_rise_pct / 100.0)
        max_buy = _f(state.get("_reentry_max_buy_price"))
        if P >= thr:
            if max_buy is not None and max_buy > 0 and P > max_buy:
                logger.info(
                    "BOT_REENTRY_HOLD bot_id=%s cycle_id=%s price=%.4f max_buy=%.4f decision=HOLD reason=buy_above_sell_basis",
                    state.get("bot_id"), state.get("cycle_id"), P, max_buy,
                )
                return actions, next_wake
            qty_usdt = _reentry_buy_qty(state, config, quote_balance)
            if qty_usdt and qty_usdt > 0:
                actions.append({
                    "type": "place",
                    "side": "BUY",
                    "symbol": config.symbol,
                    "quote_qty": qty_usdt,
                    "client_order_id": _action_id(state, "reentry", 0),
                    "reason": "trail_reentry_buy",
                    "trigger_price": P,
                    "execution_price": thr,
                })
                state["mode"] = BotEngineMode.IDLE.value
                state["_reentry_done"] = True
                state["_cycle_complete"] = True
                state.pop("_reentry_avg_sell", None)
                state.pop("_reentry_max_buy_price", None)
        return actions, next_wake

    if mode == BotEngineMode.TRAIL_PROFIT_SELL.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(max(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 - config.profit_exit_drop_pct / 100.0)
        breakeven_floor = _f(state.get("_profit_exit_breakeven"))
        if breakeven_floor is not None and breakeven_floor > 0:
            thr = max(thr, breakeven_floor)
        if P <= thr:
            if breakeven_floor is not None and P < breakeven_floor:
                logger.info(
                    "BOT_PROFIT_EXIT_HOLD bot_id=%s cycle_id=%s price=%.4f breakeven=%.4f decision=HOLD reason=trail_would_sell_below_breakeven",
                    state.get("bot_id"), state.get("cycle_id"), P, breakeven_floor,
                )
                return actions, next_wake
            qty = _profit_exit_sell_qty(state, config, base_balance)
            if qty and qty > 0:
                actions.append({
                    "type": "place",
                    "side": "SELL",
                    "symbol": config.symbol,
                    "quantity": qty,
                    "client_order_id": _action_id(state, "profit_exit", 0),
                    "reason": "trail_profit_sell",
                    "trigger_price": P,
                    "execution_price": thr,
                })
                state["mode"] = BotEngineMode.IDLE.value
                state["_profit_exit_done"] = True
                state["_cycle_complete"] = True
                state.pop("_profit_exit_breakeven", None)
                state.pop("_profit_exit_trigger_price", None)
        return actions, next_wake

    # ---- Per-grid parallel trailing (each grid independent) ----
    ref = _f(state.get("reference_price"))
    if ref is None or ref <= 0:
        state["reference_price"] = P
        ref = P
        logger.info("BOT_STATE_HEALED bot_id=%s ref was None/0, set to price=%.2f", state.get("bot_id", 0), P)
    if initial_done and ((_f(state.get("grid_reference_quote") or 0) <= 0)):
        current_eq = quote_balance + base_balance * (P or 0)
        if current_eq > 0:
            state["grid_reference_quote"] = current_eq
            if (_f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0):
                state["grid_reference_base"] = base_balance
            if (_f(state.get("cycle_start_equity") or 0) <= 0):
                state["cycle_start_equity"] = current_eq
            logger.info("BOT_STATE_HEALED bot_id=%s grid_reference_quote=%.2f (equity), cycle_start_equity=%.2f", state.get("bot_id", 0), current_eq, state.get("cycle_start_equity"))

    sell_trail_pct = config.sell_trigger_trailing_pct
    buy_trail_pct = config.buy_trigger_trailing_pct

    # Active sell trails: update per-grid peak, execute when price retraces
    for idx in range(n):
        if idx < len(state["sell_grid_fired"]) and state["sell_grid_fired"][idx]:
            continue
        trigger_hit = state["sell_grid_trigger_price"][idx] if idx < len(state["sell_grid_trigger_price"]) else None
        if trigger_hit is None:
            continue
        th_num = _f(trigger_hit) or P
        peaks = state["sell_grid_peak_price"]
        while len(peaks) <= idx:
            peaks.append(None)
        cur_peak = _f(peaks[idx]) if peaks[idx] is not None else th_num
        cur_peak = max(cur_peak, P)
        peaks[idx] = cur_peak
        state["sell_grid_peak_price"] = peaks
        exec_thr = cur_peak * (1 - sell_trail_pct / 100.0)
        if P <= exec_thr:
            qty = _sell_qty_for_grid(state, config, idx, base_balance, price=P)
            if qty and qty > 0:
                if not _meets_min_notional(config, "SELL", P, qty=qty):
                    logger.debug(
                        "BOT_STRATEGY_GRID_SKIP bot_id=%s skip_reason=MIN_NOTIONAL side=SELL grid=%s notional=%.2f min=%.2f",
                        state.get("bot_id", 0), idx, qty * P, getattr(config, "min_notional_guard", 5.0),
                    )
                    _queue_grid_skip(state, side="SELL", grid_index=idx, notional=qty * P, config=config, reason="trail_sell_grid")
                    continue
                actions.append({
                    "type": "place",
                    "side": "SELL",
                    "symbol": config.symbol,
                    "quantity": qty,
                    "client_order_id": _action_id(state, "sell_grid", idx),
                    "grid_index": idx,
                    "reason": "trail_sell_grid",
                    "trigger_price": P,
                    "execution_price": exec_thr,
                    "trail_anchor_price": cur_peak,
                })

    # Active buy trails: update per-grid trough, execute when price rises
    for idx in range(m):
        if idx < len(state["buy_grid_fired"]) and state["buy_grid_fired"][idx]:
            continue
        trigger_hit = state["buy_grid_trigger_price"][idx] if idx < len(state["buy_grid_trigger_price"]) else None
        if trigger_hit is None:
            continue
        th_num = _f(trigger_hit) or P
        troughs = state["buy_grid_trough_price"]
        while len(troughs) <= idx:
            troughs.append(None)
        cur_trough = _f(troughs[idx]) if troughs[idx] is not None else th_num
        cur_trough = min(cur_trough, P)
        troughs[idx] = cur_trough
        state["buy_grid_trough_price"] = troughs
        exec_thr = cur_trough * (1 + buy_trail_pct / 100.0)
        if P >= exec_thr:
            quote_q = _buy_qty_for_grid(state, config, idx, quote_balance, price=P)
            if quote_q and quote_q > 0:
                if not _meets_min_notional(config, "BUY", P, quote_qty=quote_q):
                    logger.debug(
                        "BOT_STRATEGY_GRID_SKIP bot_id=%s skip_reason=MIN_NOTIONAL side=BUY grid=%s notional=%.2f min=%.2f",
                        state.get("bot_id", 0), idx, quote_q, getattr(config, "min_notional_guard", 5.0),
                    )
                    _queue_grid_skip(state, side="BUY", grid_index=idx, notional=quote_q, config=config, reason="trail_buy_grid")
                    continue
                actions.append({
                    "type": "place",
                    "side": "BUY",
                    "symbol": config.symbol,
                    "quote_qty": quote_q,
                    "client_order_id": _action_id(state, "buy_grid", idx),
                    "grid_index": idx,
                    "reason": "trail_buy_grid",
                    "trigger_price": P,
                    "execution_price": exec_thr,
                    "trail_anchor_price": cur_trough,
                })
            else:
                logger.warning(
                    "BOT_STRATEGY_TRAIL_BUY_SKIP bot_id=%s grid_idx=%s price=%.2f thr=%.2f quote_balance=%.2f quote_q=%.2f",
                    state.get("bot_id", 0), idx, P, exec_thr, quote_balance, quote_q or 0.0,
                )

    # New sell grid triggers (parallel — do not block on other open grids)
    for i in range(n):
        if state["sell_grid_fired"][i]:
            continue
        if state["sell_grid_trigger_price"][i] is not None:
            continue
        g = config.sell_grids[i] if i < len(config.sell_grids) else {}
        pct = _float(g.get("sell_grid_pct") or g.get("trigger_pct"), 0)
        s_i = ref * (1 + pct / 100.0)
        if P >= s_i:
            state["sell_grid_trigger_price"][i] = P
            peaks = state["sell_grid_peak_price"]
            while len(peaks) <= i:
                peaks.append(None)
            peaks[i] = P
            state["sell_grid_peak_price"] = peaks
            if (_f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0):
                state["grid_reference_base"] = base_balance
            logger.info(
                "BOT_GRID_SELL_TRIGGER bot_id=%s grid=%s price=%.4f trigger=%.4f ref=%.4f",
                state.get("bot_id", 0), i, P, s_i, ref,
            )

    # New buy grid triggers
    for j in range(m):
        if state["buy_grid_fired"][j]:
            continue
        if state["buy_grid_trigger_price"][j] is not None:
            continue
        g = config.buy_grids[j] if j < len(config.buy_grids) else {}
        pct = _float(g.get("buy_grid_pct") or g.get("trigger_pct"), 0)
        b_j = ref * (1 - pct / 100.0)
        if P <= b_j:
            state["buy_grid_trigger_price"][j] = P
            troughs = state["buy_grid_trough_price"]
            while len(troughs) <= j:
                troughs.append(None)
            troughs[j] = P
            state["buy_grid_trough_price"] = troughs
            logger.info(
                "BOT_GRID_BUY_TRIGGER bot_id=%s grid=%s price=%.4f trigger=%.4f ref=%.4f",
                state.get("bot_id", 0), j, P, b_j, ref,
            )

    _sync_trailing_mode(state, n, m)

    # ---- Re-entry / profit exit arming (only closed grid fills in history) ----
    sell_hist = state.get("sell_history") or []
    if sell_hist and not state.get("_reentry_done"):
        pnl_mode = getattr(config, "pnl_mode", "legacy") or "legacy"
        symbol = (config.symbol or "").upper().strip() or "BTCUSDT"
        buy_fee = getattr(config, "buy_fee_rate", 0.001) or 0.001
        sell_fee = getattr(config, "sell_fee_rate", 0.001) or 0.001
        drop_pct = config.profit_reentry_drop_pct
        avg_sell = None
        arm_price = None
        max_buy = None
        if pnl_mode == "cycle_only_fee_aware_v1":
            from app.botengine.cycle_ledger import (
                cycle_ledger_from_state,
                cycle_ledger_avg_sell_price,
                cycle_ledger_reentry_arm_price,
                cycle_ledger_reentry_max_buy_price,
            )
            ledger = cycle_ledger_from_state(state, symbol)
            avg_sell = cycle_ledger_avg_sell_price(ledger)
            if avg_sell and avg_sell > 0:
                arm_price = cycle_ledger_reentry_arm_price(ledger, drop_pct)
                max_buy = cycle_ledger_reentry_max_buy_price(ledger, buy_fee, sell_fee)
        if avg_sell is None or avg_sell <= 0:
            avg_sell = _avg_sell_price_for_trigger(state)
            if avg_sell and avg_sell > 0:
                arm_price = avg_sell * (1 - drop_pct / 100.0)
                max_buy = avg_sell * (1 - sell_fee) / (1 + buy_fee)
        if avg_sell and avg_sell > 0 and arm_price is not None and P <= arm_price:
            logger.info(
                "BOT_REENTRY_EVAL bot_id=%s cycle_id=%s avg_sell=%.4f arm=%.4f max_buy=%.4f price=%.4f decision=ARM",
                state.get("bot_id"), state.get("cycle_id"), avg_sell, arm_price, max_buy or 0, P,
            )
            state["trail_anchor_price"] = P
            state["trail_activation_price"] = P
            state["_reentry_avg_sell"] = avg_sell
            state["_reentry_max_buy_price"] = max_buy
            state["mode"] = BotEngineMode.TRAIL_REENTRY_BUY.value
            return actions, next_wake

    # D) Profit exit (after any buy) — fee-aware when pnl_mode=cycle_only_fee_aware_v1
    buy_hist = state.get("buy_history") or []
    init_q = _float(state.get("initial_alloc_base_qty"), 0)
    has_basis = bool(buy_hist or (init_q > 0 and state.get("initial_allocation_done")))
    if has_basis and not state.get("_profit_exit_done"):
        pnl_mode = getattr(config, "pnl_mode", "legacy") or "legacy"
        symbol = (config.symbol or "").upper().strip() or "BTCUSDT"
        if pnl_mode == "cycle_only_fee_aware_v1":
            from app.botengine.cycle_ledger import (
                cycle_ledger_from_state,
                cycle_ledger_breakeven_price,
                cycle_ledger_trigger_price,
                cycle_ledger_with_basis,
            )
            basis_mode = getattr(config, "basis_mode", "grid_only") or "grid_only"
            ledger = cycle_ledger_with_basis(
                state, cycle_ledger_from_state(state, symbol), basis_mode,
            )
            buy_fee = getattr(config, "buy_fee_rate", 0.001) or 0.001
            sell_fee = getattr(config, "sell_fee_rate", 0.001) or 0.001
            min_net = getattr(config, "min_net_profit_rate", 0.001) or 0.001
            profit_rise = getattr(config, "profit_exit_rise_pct", 1.0) or 1.0
            breakeven = cycle_ledger_breakeven_price(ledger, buy_fee, sell_fee)
            trigger_price = cycle_ledger_trigger_price(
                ledger, min_net, buy_fee, sell_fee, profit_rise_pct=profit_rise,
            )
            avg_cost_cycle = ledger.get("avg_cost_quote_per_base")
            if trigger_price is not None and trigger_price > 0 and P >= trigger_price:
                logger.info(
                    "BOT_PROFIT_EXIT_EVAL bot_id=%s cycle_id=%s symbol=%s scope=cycle basis=%s last_price=%.4f avg_cost_cycle=%.4f breakeven=%.4f trigger=%.4f rise_pct=%.2f decision=ARM reason=fee_aware_above_trigger",
                    state.get("bot_id"), state.get("cycle_id"), symbol, basis_mode, P, avg_cost_cycle or 0, breakeven or 0, trigger_price, profit_rise,
                )
                state["trail_anchor_price"] = P
                state["trail_activation_price"] = P
                state["_profit_exit_breakeven"] = breakeven
                state["_profit_exit_trigger_price"] = trigger_price
                state["mode"] = BotEngineMode.TRAIL_PROFIT_SELL.value
                return actions, next_wake
            if trigger_price is not None and P < trigger_price and breakeven is not None and P < breakeven:
                logger.info(
                    "BOT_PROFIT_EXIT_EVAL bot_id=%s cycle_id=%s symbol=%s scope=cycle last_price=%.4f breakeven=%.4f trigger=%.4f decision=HOLD reason=below_breakeven",
                    state.get("bot_id"), state.get("cycle_id"), symbol, P, breakeven, trigger_price or 0,
                )
        else:
            use_total = getattr(config, "basis_mode", "grid_only") == "total"
            avg_buy = _avg_buy_price_total(state) if use_total else _avg_buy_price_for_trigger(state)
            if avg_buy and avg_buy > 0:
                thr = avg_buy * (1 + config.profit_exit_rise_pct / 100.0)
                if P >= thr:
                    state["trail_anchor_price"] = P
                    state["trail_activation_price"] = P
                    state["_profit_exit_breakeven"] = thr
                    state["_profit_exit_trigger_price"] = thr
                    state["mode"] = BotEngineMode.TRAIL_PROFIT_SELL.value
                    return actions, next_wake

    return actions, next_wake


def _float(x: Any, default: float) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _action_id(state: Dict, prefix: str, idx: int) -> str:
    """Deterministic client order id: botId-cycle-reason-gridIndex (no timestamp)."""
    bid = state.get("bot_id") or 0
    cy = state.get("cycle_id") or 1
    return f"be_{bid}_c{cy}_{prefix}_{idx}"[:36]


def _meets_min_notional(
    config: DcaGridTrailingConfig,
    side: str,
    price: float,
    qty: Optional[float] = None,
    quote_qty: Optional[float] = None,
) -> bool:
    """Binance min notional guard — grid intent üretmeden önce kontrol."""
    min_n = _float(getattr(config, "min_notional_guard", 5.0), 5.0)
    if min_n <= 0:
        return True
    if (side or "").upper() == "BUY":
        return (quote_qty or 0) >= min_n
    return (qty or 0) * (price or 0) >= min_n


def _sell_qty_for_grid(
    state: Dict,
    config: DcaGridTrailingConfig,
    idx: int,
    base_balance: float,
    price: Optional[float] = None,
) -> float:
    """Satış miktarı = referans base * grid yüzdesi. target_budgets varsa referans target_base_usdt/price ile sınırlanır (bileşik büyüme)."""
    g = config.sell_grids[idx] if idx < len(config.sell_grids) else {}
    pct = _float(g.get("sell_qty_pct_of_base") or g.get("qty_pct"), 10.0) / 100.0
    ref_base = _f(state.get("grid_reference_base") or 0) or 0.0
    if ref_base <= 0:
        ref_base = base_balance
    tb = state.get("target_budgets")
    buffer = _float(getattr(config, "available_quote_buffer_pct", 0.005), 0.005)
    if isinstance(tb, dict) and price and price > 0:
        target_base = _float(tb.get("target_base_usdt"), 0)
        if target_base > 0:
            cap_base = (target_base / price) * (1.0 - buffer)
            ref_base = min(ref_base, cap_base)
    return _f(min(ref_base * pct, base_balance)) or 0.0


def _buy_qty_for_grid(
    state: Dict,
    config: DcaGridTrailingConfig,
    idx: int,
    quote_balance: float,
    price: Optional[float] = None,
) -> float:
    """Alım miktarı = referans quote * grid yüzdesi. target_budgets varsa referans target_quote_usdt ile sınırlanır (bileşik büyüme)."""
    g = config.buy_grids[idx] if idx < len(config.buy_grids) else {}
    pct = _float(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"), 10.0) / 100.0
    ref = _f(state.get("grid_reference_quote") or 0) or 0.0
    if ref <= 0:
        ref = quote_balance
    tb = state.get("target_budgets")
    buffer = _float(getattr(config, "available_quote_buffer_pct", 0.005), 0.005)
    if isinstance(tb, dict):
        target_quote = _float(tb.get("target_quote_usdt"), 0)
        if target_quote > 0:
            cap_quote = target_quote * (1.0 - buffer)
            ref = min(ref, cap_quote)
    return _f(min(ref * pct, quote_balance)) or 0.0


def _avg_sell_price(state: Dict) -> Optional[float]:
    h = state.get("sell_history") or []
    if not h:
        return None
    total_q = sum(_float(x.get("qty"), 0) for x in h)
    if total_q <= 0:
        return None
    total_v = sum(_float(x.get("qty"), 0) * _float(x.get("price"), 0) for x in h)
    return total_v / total_q if total_q else None


def _avg_buy_price(state: Dict) -> Optional[float]:
    """Grid-only cost basis (buy_history), fill fiyatı; PnL için."""
    h = state.get("buy_history") or []
    if not h:
        return None
    total_q = sum(_float(x.get("qty"), 0) for x in h)
    if total_q <= 0:
        return None
    total_v = sum(_float(x.get("qty"), 0) * _float(x.get("price"), 0) for x in h)
    return total_v / total_q if total_q else None


def _avg_buy_price_for_trigger(state: Dict) -> Optional[float]:
    """Grid alımları ortalama: execution_price varsa onu kullan (gerçekleşme fiyatı), yoksa fill. Tetik/UI ile uyumlu."""
    h = state.get("buy_history") or []
    if not h:
        return None
    total_q = sum(_float(x.get("qty"), 0) for x in h)
    if total_q <= 0:
        return None
    total_v = sum(
        _float(x.get("qty"), 0) * _float(x.get("execution_price") or x.get("price"), 0) for x in h
    )
    return total_v / total_q if total_q else None


def _avg_sell_price_for_trigger(state: Dict) -> Optional[float]:
    """Grid satışları ortalama: execution_price varsa onu kullan, yoksa fill. Tetik/UI ile uyumlu."""
    h = state.get("sell_history") or []
    if not h:
        return None
    total_q = sum(_float(x.get("qty"), 0) for x in h)
    if total_q <= 0:
        return None
    total_v = sum(
        _float(x.get("qty"), 0) * _float(x.get("execution_price") or x.get("price"), 0) for x in h
    )
    return total_v / total_q if total_q else None


def _avg_buy_price_total(state: Dict) -> Optional[float]:
    """Total cost basis: initial alloc + grid buys. Used when basis_mode=total."""
    init_q = _float(state.get("initial_alloc_base_qty"), 0)
    init_p = _float(state.get("initial_alloc_price"), 0)
    h = state.get("buy_history") or []
    grid_q = sum(_float(x.get("qty"), 0) for x in h)
    grid_v = sum(_float(x.get("qty"), 0) * _float(x.get("price"), 0) for x in h)
    total_q = init_q + grid_q
    if total_q <= 0:
        return None
    total_v = init_q * init_p + grid_v
    return total_v / total_q


def _reentry_buy_qty(state: Dict, config: DcaGridTrailingConfig, quote_balance: float) -> float:
    """Re-entry: use "all sell proceeds" equivalent. We approximate as quote to spend = sum(sell qty * sell price)."""
    h = state.get("sell_history") or []
    total = sum(_float(x.get("qty"), 0) * _float(x.get("price"), 0) for x in h)
    cap = min(quote_balance, total) if total else 0
    return _f(cap) or 0.0


def _profit_exit_sell_qty(state: Dict, config: DcaGridTrailingConfig, base_balance: float) -> float:
    """Profit exit: sell "extra" base from down-grid buys. We sell all bought in buy grids (simplified)."""
    h = state.get("buy_history") or []
    total_q = sum(_float(x.get("qty"), 0) for x in h)
    return _f(min(base_balance, total_q) if total_q else 0) or 0.0


def apply_fill_to_state(
    state: Dict[str, Any],
    side: str,
    executed_qty: float,
    executed_price: float,
    fee: float,
    grid_index: Optional[int] = None,
    reason: str = "",
    execution_price: Optional[float] = None,
) -> None:
    """Update state after a fill. Appends to sell_history/buy_history, updates balances, realized_pnl, fees.
    execution_price: gerçekleşme fiyatı (tetik seviyesi); ortalama maliyet/tetik hesaplarında kullanılır, yoksa fill fiyatı kullanılır."""
    q = _f(executed_qty) or 0.0
    p = _f(executed_price) or 0.0
    fee_val = _f(fee) or 0.0
    exec_p = _f(execution_price) if execution_price is not None else None
    state["fees_paid_usdt_cycle"] = (_f(state.get("fees_paid_usdt_cycle") or 0) or 0.0) + fee_val
    if side == "SELL":
        state["base_balance"] = (_f(state.get("base_balance") or 0) or 0.0) - q
        state["quote_balance"] = (_f(state.get("quote_balance") or 0) or 0.0) + q * p - fee_val
        entry = {"grid_index": grid_index, "qty": q, "price": p}
        if exec_p is not None:
            entry["execution_price"] = exec_p
        state.setdefault("sell_history", []).append(entry)
        avg_buy = _avg_buy_price(state)
        cost = q * (_f(avg_buy or p) or p)
        state["realized_pnl_usdt_cycle"] = (_f(state.get("realized_pnl_usdt_cycle") or 0) or 0.0) + (q * p - fee_val - cost)
    else:
        # BUY: quote decreases by cost (q*p) + fee (fee in quote/USDT). So quote_balance -= (q*p + fee).
        state["base_balance"] = (_f(state.get("base_balance") or 0) or 0.0) + q
        state["quote_balance"] = (_f(state.get("quote_balance") or 0) or 0.0) - q * p - fee_val
        if (reason or "").strip() != "initial_allocation":
            entry = {"grid_index": grid_index, "qty": q, "price": p}
            if exec_p is not None:
                entry["execution_price"] = exec_p
            state.setdefault("buy_history", []).append(entry)


class DcaGridTrailingStrategy(Strategy):
    """Plugin wrapper for tick_dca_grid_trailing and apply_fill_to_state."""

    strategy_id = "dca_grid_trailing"

    def tick(
        self,
        state: Dict[str, Any],
        config: Any,
        price: float,
        base_balance: float,
        quote_balance: float,
    ) -> Tuple[List[Dict[str, Any]], float]:
        return tick_dca_grid_trailing(state, config, price, base_balance, quote_balance)

    def apply_fill(
        self,
        state: Dict[str, Any],
        side: str,
        executed_qty: float,
        executed_price: float,
        fee: float,
        grid_index: Any = None,
        reason: str = "",
        execution_price: Any = None,
    ) -> None:
        apply_fill_to_state(
            state, side, executed_qty, executed_price, fee,
            grid_index=grid_index, reason=reason, execution_price=execution_price,
        )


def cycle_reset_after_fill(
    state: Dict[str, Any], new_reference_price: float, n: int, m: int, symbol: Optional[str] = None
) -> None:
    """After re-entry or profit-exit fill: tur karı hesaplanır, cycle_id++, reference_price, grid referansları bileşik bakiyeye güncellenir."""
    quote_bal = _f(state.get("quote_balance") or 0) or 0.0
    base_bal = _f(state.get("base_balance") or 0) or 0.0
    price = _f(new_reference_price) or new_reference_price
    current_equity = round(quote_bal + base_bal * price, 2)
    cycle_start = _f(state.get("cycle_start_equity") or 0) or 0.0
    state["last_cycle_profit_usdt"] = round(current_equity - cycle_start, 2)
    new_cycle_id = int(state.get("cycle_id") or 1) + 1
    state["cycle_id"] = new_cycle_id
    state["reference_price"] = price
    state["sell_grid_fired"] = [False] * n
    state["sell_grid_trigger_price"] = [None] * n
    state["sell_grid_peak_price"] = [None] * n
    state["sell_grid_fill_price"] = [None] * n
    state["buy_grid_fired"] = [False] * m
    state["buy_grid_trigger_price"] = [None] * m
    state["buy_grid_trough_price"] = [None] * m
    state["buy_grid_fill_price"] = [None] * m
    state["sell_history"] = []
    state["buy_history"] = []
    state["cycle_start_equity"] = current_equity
    state["grid_reference_quote"] = current_equity
    state["grid_reference_base"] = base_bal
    state.pop("_reentry_done", None)
    state.pop("_profit_exit_done", None)
    state.pop("_cycle_complete", None)
    if symbol:
        from app.botengine.cycle_ledger import build_cycle_ledger_empty
        state["cycle_ledger_current"] = build_cycle_ledger_empty(new_cycle_id, symbol)
        started_at = (state.get("cycle_ledger_current") or {}).get("started_at")
    else:
        started_at = None
    if new_cycle_id >= 2 and base_bal > 0 and price > 0:
        from datetime import datetime, timezone
        ts_open = started_at or datetime.now(timezone.utc).isoformat()
        state.setdefault("cycle_open_trades", []).append({
            "cycle_id": new_cycle_id,
            "side": "BUY",
            "qty": round(base_bal, 10),
            "price": round(price, 10),
            "reference_price": round(price, 10),
            "ts": ts_open,
            "fee": 0.0,
        })
        state["cycle_open_trades"] = state["cycle_open_trades"][-200:]