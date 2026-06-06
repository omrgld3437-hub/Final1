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

    # ---- Trailing modes (single active) ----
    if mode == BotEngineMode.TRAIL_SELL_GRID.value:
        idx = state.get("_trail_sell_grid_index", 0)
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(max(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 - config.sell_trigger_trailing_pct / 100.0)
        if P <= thr:
            qty = _sell_qty_for_grid(state, config, idx, base_balance, price=P)
            if qty and qty > 0:
                peak_at_exec = _f(state.get("trail_anchor_price") or P) or P
                actions.append({
                    "type": "place",
                    "side": "SELL",
                    "symbol": config.symbol,
                    "quantity": qty,
                    "client_order_id": _action_id(state, "sell_grid", idx),
                    "grid_index": idx,
                    "reason": "trail_sell_grid",
                    "trigger_price": P,
                    "execution_price": thr,
                    "trail_anchor_price": peak_at_exec,
                })
                state["mode"] = BotEngineMode.IDLE.value
        return actions, next_wake

    if mode == BotEngineMode.TRAIL_BUY_GRID.value:
        idx = state.get("_trail_buy_grid_index", 0)
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(min(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 + config.buy_trigger_trailing_pct / 100.0)
        if P >= thr:
            quote_q = _buy_qty_for_grid(state, config, idx, quote_balance, price=P)
            if quote_q and quote_q > 0:
                trough_at_exec = _f(state.get("trail_anchor_price") or P) or P
                actions.append({
                    "type": "place",
                    "side": "BUY",
                    "symbol": config.symbol,
                    "quote_qty": quote_q,
                    "client_order_id": _action_id(state, "buy_grid", idx),
                    "grid_index": idx,
                    "reason": "trail_buy_grid",
                    "trigger_price": P,
                    "execution_price": thr,
                    "trail_anchor_price": trough_at_exec,
                })
                state["mode"] = BotEngineMode.IDLE.value
            else:
                logger.warning(
                    "BOT_STRATEGY_TRAIL_BUY_SKIP bot_id=%s grid_idx=%s price=%.2f thr=%.2f quote_balance=%.2f quote_q=%.2f (price reached threshold but no buy: quote_q zero or below min)",
                    state.get("bot_id", 0), idx, P, thr, quote_balance, quote_q or 0.0,
                )
        return actions, next_wake

    if mode == BotEngineMode.TRAIL_REENTRY_BUY.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(min(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 + config.profit_reentry_rise_pct / 100.0)
        if P >= thr:
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
        return actions, next_wake

    if mode == BotEngineMode.TRAIL_PROFIT_SELL.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(max(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 - config.profit_exit_drop_pct / 100.0)
        if P <= thr:
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
        return actions, next_wake

    # ---- IDLE: check triggers ----
    ref = _f(state.get("reference_price"))
    if ref is None or ref <= 0:
        state["reference_price"] = P
        ref = P
        logger.info("BOT_STATE_HEALED bot_id=%s ref was None/0 in IDLE, set to price=%.2f", state.get("bot_id", 0), P)
    if initial_done and ((_f(state.get("grid_reference_quote") or 0) <= 0)):
        current_eq = quote_balance + base_balance * (P or 0)
        if current_eq > 0:
            state["grid_reference_quote"] = current_eq
            if (_f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0):
                state["grid_reference_base"] = base_balance
            if (_f(state.get("cycle_start_equity") or 0) <= 0):
                state["cycle_start_equity"] = current_eq
            logger.info("BOT_STATE_HEALED bot_id=%s grid_reference_quote=%.2f (equity), cycle_start_equity=%.2f", state.get("bot_id", 0), current_eq, state.get("cycle_start_equity"))

    # A) Sell grid trigger
    for i in range(n):
        if state["sell_grid_fired"][i]:
            continue
        g = config.sell_grids[i] if i < len(config.sell_grids) else {}
        pct = _float(g.get("sell_grid_pct") or g.get("trigger_pct"), 0)
        s_i = ref * (1 + pct / 100.0)
        if P >= s_i:
            state["sell_grid_trigger_price"][i] = P
            state["trail_anchor_price"] = P
            state["trail_activation_price"] = P
            if (_f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0):
                state["grid_reference_base"] = base_balance
            state["mode"] = BotEngineMode.TRAIL_SELL_GRID.value
            state["_trail_sell_grid_index"] = i
            return actions, next_wake

    # B) Buy grid trigger
    for j in range(m):
        if state["buy_grid_fired"][j]:
            continue
        g = config.buy_grids[j] if j < len(config.buy_grids) else {}
        pct = _float(g.get("buy_grid_pct") or g.get("trigger_pct"), 0)
        b_j = ref * (1 - pct / 100.0)
        if P <= b_j:
            state["buy_grid_trigger_price"][j] = P
            state["trail_anchor_price"] = P
            state["trail_activation_price"] = P
            state["mode"] = BotEngineMode.TRAIL_BUY_GRID.value
            state["_trail_buy_grid_index"] = j
            return actions, next_wake

    # C) Re-entry (after any sell)
    sell_hist = state.get("sell_history") or []
    if sell_hist and not state.get("_reentry_done"):
        avg_sell = _avg_sell_price_for_trigger(state)
        if avg_sell and avg_sell > 0:
            thr = avg_sell * (1 - config.profit_reentry_drop_pct / 100.0)
            if P <= thr:
                state["trail_anchor_price"] = P
                state["trail_activation_price"] = P
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
            )
            ledger = cycle_ledger_from_state(state, symbol)
            buy_fee = getattr(config, "buy_fee_rate", 0.001) or 0.001
            sell_fee = getattr(config, "sell_fee_rate", 0.001) or 0.001
            min_net = getattr(config, "min_net_profit_rate", 0.001) or 0.001
            breakeven = cycle_ledger_breakeven_price(ledger, buy_fee, sell_fee)
            trigger_price = cycle_ledger_trigger_price(ledger, min_net, buy_fee, sell_fee)
            avg_cost_cycle = ledger.get("avg_cost_quote_per_base")
            if trigger_price is not None and trigger_price > 0 and P >= trigger_price:
                logger.info(
                    "BOT_PROFIT_EXIT_EVAL bot_id=%s cycle_id=%s symbol=%s scope=cycle last_price=%.4f avg_cost_cycle=%.4f breakeven=%.4f trigger=%.4f decision=SELL reason=fee_aware_above_trigger",
                    state.get("bot_id"), state.get("cycle_id"), symbol, P, avg_cost_cycle or 0, breakeven or 0, trigger_price,
                )
                state["trail_anchor_price"] = P
                state["trail_activation_price"] = P
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