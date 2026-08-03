"""
DCA + two-way Grid + Trailing strategy.
State machine: IDLE | TRAIL_SELL_GRID | TRAIL_BUY_GRID | TRAIL_REENTRY_BUY | TRAIL_PROFIT_SELL.
Plugin: DcaGridTrailingStrategy (strategy_id=dca_grid_trailing).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.models import BotEngineMode, DcaGridTrailingConfig
from app.botengine.fee_utils import symbol_base_asset
from app.botengine.trade_invariants import (
    CostBasisType,
    OrderStatus,
    OrderType,
    completion_price,
    completion_reached,
    price_from_reference,
    trigger_reached,
    update_extreme,
    valid_extreme,
    weighted_average_price,
)
from app.core.constants import DEFAULT_MIN_NOTIONAL_USDT
from app.botengine.skip_event_policy import grid_min_notional_blocked
from app.botengine.dynamic.safety_gate import DAILY_LOSS_RUNTIME_ENABLED
from app.botengine.strategies.base import Strategy
from app.botengine.strategies.grid_outage_recovery import (
    apply_grid_outage_recovery,
    should_apply_outage_recovery,
)

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
    from app.botengine.skip_event_policy import (
        grid_min_notional_blocked,
        mark_grid_min_notional_blocked,
    )
    from app.botengine.state_store import queue_engine_event

    if grid_min_notional_blocked(state, side, grid_index):
        return

    min_n = float(getattr(config, "min_notional_guard", DEFAULT_MIN_NOTIONAL_USDT) or DEFAULT_MIN_NOTIONAL_USDT)
    mark_grid_min_notional_blocked(
        state,
        side,
        grid_index,
        notional=notional,
        min_notional=min_n,
    )
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


def _within_planned_completion_slippage(
    side: str,
    current_price: float,
    planned_price: float,
    config: DcaGridTrailingConfig,
) -> bool:
    """Reject a market intent when a price gap is worse than the configured plan.

    A better price always passes: SELL above and BUY below the planned trailing
    completion price. This protects armed trails from outage/tick gaps.
    """
    planned = float(planned_price or 0)
    current = float(current_price or 0)
    if planned <= 0 or current <= 0:
        return False
    configured_max_slip = getattr(config, "max_slippage_pct", 0.5)
    max_slip = max(
        0.0,
        float(0.5 if configured_max_slip is None else configured_max_slip),
    )
    tolerance = max_slip / 100.0
    if str(side or "").upper() == "SELL":
        return current >= planned * (1.0 - tolerance)
    if str(side or "").upper() == "BUY":
        return current <= planned * (1.0 + tolerance)
    return False


TRAIL_FAST_TICK_MS_DEFAULT = 800
TRAIL_FAST_WAKE_MIN_SEC = 0.5


def _trail_fast_wake_sec(config: DcaGridTrailingConfig) -> float:
    """Dip/tepe veya kar trail aktifken tick aralığı (orchestrator min 0.5s)."""
    fast_ms = getattr(config, "trail_fast_tick_ms", None)
    if fast_ms is None:
        fast_ms = TRAIL_FAST_TICK_MS_DEFAULT
    try:
        fast_ms = int(fast_ms)
    except (TypeError, ValueError):
        fast_ms = TRAIL_FAST_TICK_MS_DEFAULT
    normal = config.tick_interval_ms / 1000.0
    return max(TRAIL_FAST_WAKE_MIN_SEC, min(normal, fast_ms / 1000.0))


def _is_trail_armed(state: Dict[str, Any], config: DcaGridTrailingConfig) -> bool:
    """Grid tetiklenmiş (dip/tepe takibi) veya tur kar trail modu aktif."""
    mode = state.get("mode") or BotEngineMode.IDLE.value
    if mode in (
        BotEngineMode.TRAIL_REENTRY_BUY.value,
        BotEngineMode.TRAIL_PROFIT_SELL.value,
        BotEngineMode.TRAIL_SELL_GRID.value,
        BotEngineMode.TRAIL_BUY_GRID.value,
    ):
        return True
    _ensure_sell_buy_lists(state, config)
    n = len(config.sell_grids)
    m = len(config.buy_grids)
    sell_fired = state.get("sell_grid_fired") or []
    sell_trig = state.get("sell_grid_trigger_price") or []
    for idx in range(n):
        if idx < len(sell_fired) and sell_fired[idx]:
            continue
        if idx < len(sell_trig) and sell_trig[idx] is not None:
            return True
    buy_fired = state.get("buy_grid_fired") or []
    buy_trig = state.get("buy_grid_trigger_price") or []
    for idx in range(m):
        if idx < len(buy_fired) and buy_fired[idx]:
            continue
        if idx < len(buy_trig) and buy_trig[idx] is not None:
            return True
    return False


def _finish_tick(
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
    actions: List[Dict[str, Any]],
    next_wake: float,
) -> Tuple[List[Dict[str, Any]], float]:
    if _is_trail_armed(state, config):
        next_wake = min(next_wake, _trail_fast_wake_sec(config))
    return actions, next_wake


def _ensure_sell_buy_lists(state: Dict[str, Any], cfg: DcaGridTrailingConfig) -> None:
    n = len(cfg.sell_grids)
    m = len(cfg.buy_grids)
    for k, default, size in [
        ("sell_grid_fired", False, n),
        ("sell_grid_trigger_price", None, n),
        ("sell_grid_peak_price", None, n),
        ("sell_grid_status", OrderStatus.WAITING_TRIGGER.value, n),
        ("buy_grid_fired", False, m),
        ("buy_grid_trigger_price", None, m),
        ("buy_grid_trough_price", None, m),
        ("buy_grid_status", OrderStatus.WAITING_TRIGGER.value, m),
    ]:
        arr = state.get(k)
        if not isinstance(arr, list):
            arr = []
        if isinstance(default, bool):
            base = [bool(arr[i]) if i < len(arr) else False for i in range(size)]
        else:
            base = [arr[i] if i < len(arr) else None for i in range(size)]
            if isinstance(default, str):
                base = [
                    str(arr[i]) if i < len(arr) and arr[i] else default
                    for i in range(size)
                ]
        state[k] = base
    if "sell_history" not in state:
        state["sell_history"] = []
    if "buy_history" not in state:
        state["buy_history"] = []


def get_cycle_grid_side(state: Dict[str, Any]) -> Optional[str]:
    """Tur yönü: None (ilk grid fill öncesi iki yön) | SELL | BUY."""
    side = state.get("cycle_grid_side")
    if side in ("SELL", "BUY"):
        return side
    return None


def _sell_grids_enabled(state: Dict[str, Any]) -> bool:
    side = get_cycle_grid_side(state)
    return side != "BUY"


def _buy_grids_enabled(state: Dict[str, Any]) -> bool:
    side = get_cycle_grid_side(state)
    return side != "SELL"


def _lock_cycle_grid_side(state: Dict[str, Any], side: str) -> None:
    """İlk başarılı grid fill sonrası tur yönünü kilitle; karşı yöndeki bekleyen tetikleri temizle."""
    if side not in ("SELL", "BUY") or state.get("cycle_grid_side"):
        return
    state["cycle_grid_side"] = side
    if side == "SELL":
        triggers = list(state.get("buy_grid_trigger_price") or [])
        troughs = list(state.get("buy_grid_trough_price") or [])
        fired = state.get("buy_grid_fired") or []
        for j in range(max(len(triggers), len(troughs))):
            if j < len(fired) and fired[j]:
                continue
            if j < len(triggers):
                triggers[j] = None
            if j < len(troughs):
                troughs[j] = None
        state["buy_grid_trigger_price"] = triggers
        state["buy_grid_trough_price"] = troughs
    else:
        triggers = list(state.get("sell_grid_trigger_price") or [])
        peaks = list(state.get("sell_grid_peak_price") or [])
        fired = state.get("sell_grid_fired") or []
        for i in range(max(len(triggers), len(peaks))):
            if i < len(fired) and fired[i]:
                continue
            if i < len(triggers):
                triggers[i] = None
            if i < len(peaks):
                peaks[i] = None
        state["sell_grid_trigger_price"] = triggers
        state["sell_grid_peak_price"] = peaks
    logger.info(
        "BOT_CYCLE_SIDE_LOCKED bot_id=%s cycle_id=%s side=%s",
        state.get("bot_id"),
        state.get("cycle_id"),
        side,
    )


def infer_cycle_grid_side(state: Dict[str, Any]) -> Optional[str]:
    """Tur yönünü yalnızca tamamlanmış bir grid fill'inden çıkar.

    Tetik/izleme durumu yön kilitlemez. Eski ``*_grid_fired`` bayrakları tek
    başına kanıt sayılmaz; fill fiyatı, tamamlandı statüsü, grid geçmişi veya
    ledger'da grid fill'i bulunmalıdır.
    """
    side = state.get("cycle_grid_side")
    if side in ("SELL", "BUY"):
        return side
    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    sell_fill = state.get("sell_grid_fill_price") or []
    buy_fill = state.get("buy_grid_fill_price") or []
    sell_status = state.get("sell_grid_status") or []
    buy_status = state.get("buy_grid_status") or []
    sell_h = [
        h
        for h in (state.get("sell_history") or [])
        if isinstance(h, dict) and h.get("grid_index") is not None
    ]
    buy_h = [
        h
        for h in (state.get("buy_history") or [])
        if isinstance(h, dict) and h.get("grid_index") is not None
    ]
    ledger_fills = (
        (state.get("cycle_ledger_current") or {}).get("fills") or []
        if isinstance(state.get("cycle_ledger_current") or {}, dict)
        else []
    )
    ledger_sell = any(
        isinstance(row, dict)
        and str(row.get("reason") or "") == "trail_sell_grid"
        for row in ledger_fills
    )
    ledger_buy = any(
        isinstance(row, dict)
        and str(row.get("reason") or "") == "trail_buy_grid"
        for row in ledger_fills
    )
    sell_completed = any(
        (i < len(sell_fill) and _f(sell_fill[i]) > 0)
        or (
            i < len(sell_status)
            and str(sell_status[i]).upper() == OrderStatus.COMPLETED.value
        )
        for i, fired in enumerate(sell_fired)
        if fired
    )
    buy_completed = any(
        (i < len(buy_fill) and _f(buy_fill[i]) > 0)
        or (
            i < len(buy_status)
            and str(buy_status[i]).upper() == OrderStatus.COMPLETED.value
        )
        for i, fired in enumerate(buy_fired)
        if fired
    )
    sell_any = sell_completed or bool(sell_h) or ledger_sell
    buy_any = buy_completed or bool(buy_h) or ledger_buy
    if not sell_any and not buy_any:
        return None
    if sell_any and not buy_any:
        return "SELL"
    if buy_any and not sell_any:
        return "BUY"
    first_sell_i = next((i for i, f in enumerate(sell_fired) if f), 999)
    first_buy_j = next((j for j, f in enumerate(buy_fired) if f), 999)
    if first_sell_i == 999 and sell_h:
        first_sell_i = int(sell_h[0].get("grid_index") or 0)
    if first_buy_j == 999 and buy_h:
        first_buy_j = int(buy_h[0].get("grid_index") or 0)
    return "SELL" if first_sell_i <= first_buy_j else "BUY"


def _heal_cycle_grid_side(state: Dict[str, Any]) -> None:
    """Mevcut turda grid fill var ama cycle_grid_side yoksa yönü geçmiş fill'lerden çıkar (migrate)."""
    if state.get("cycle_grid_side"):
        return
    inferred = infer_cycle_grid_side(state)
    if not inferred:
        return
    state["cycle_grid_side"] = inferred
    logger.info(
        "BOT_CYCLE_SIDE_HEALED bot_id=%s cycle_id=%s side=%s",
        state.get("bot_id"),
        state.get("cycle_id"),
        state.get("cycle_grid_side"),
    )


def _ensure_list_len(state: Dict[str, Any], key: str, size: int, default: Any) -> list:
    arr = state.get(key)
    if not isinstance(arr, list):
        arr = []
    while len(arr) < size:
        arr.append(default)
    state[key] = arr
    return arr


def _clear_grid_skip_for_filled(state: Dict[str, Any], side: str, idx: int) -> None:
    side_u = (side or "").upper()
    blocked_key = (
        "sell_grid_min_notional_blocked"
        if side_u == "SELL"
        else "buy_grid_min_notional_blocked"
    )
    blocked = state.get(blocked_key)
    if isinstance(blocked, dict):
        blocked.pop(str(idx), None)
        blocked.pop(idx, None)
        if not blocked:
            state.pop(blocked_key, None)
    active = state.get("active_health_skips")
    if isinstance(active, dict):
        for code in ("MIN_NOTIONAL", "MIN_NOTIONAL_AFTER_CAP"):
            row = active.get(code)
            if not isinstance(row, dict):
                continue
            if str(row.get("side") or "").upper() != side_u:
                continue
            grids = row.get("grid_indices") or []
            try:
                grid_nums = [int(g) for g in grids]
            except Exception:
                grid_nums = []
            if idx not in grid_nums:
                continue
            grid_nums = [g for g in grid_nums if g != idx]
            if grid_nums:
                row["grid_indices"] = grid_nums
            else:
                active.pop(code, None)
        if not active:
            state.pop("active_health_skips", None)


def _mark_grid_fill_state(
    state: Dict[str, Any],
    side: str,
    idx: Any,
    fill_price: Any,
    anchor_price: Any = None,
) -> bool:
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return False
    if i < 0:
        return False
    side_u = (side or "").upper()
    price_f = _f(fill_price) or 0.0
    anchor_f = _f(anchor_price) if anchor_price is not None else price_f
    anchor_f = anchor_f or price_f
    changed = False
    if side_u == "BUY":
        fired = _ensure_list_len(state, "buy_grid_fired", i + 1, False)
        fills = _ensure_list_len(state, "buy_grid_fill_price", i + 1, None)
        troughs = _ensure_list_len(state, "buy_grid_trough_price", i + 1, None)
        changed = changed or not bool(fired[i])
        fired[i] = True
        if price_f > 0 and fills[i] != price_f:
            fills[i] = price_f
            changed = True
        if troughs[i] is None and anchor_f > 0:
            troughs[i] = anchor_f
            changed = True
        statuses = _ensure_list_len(
            state, "buy_grid_status", i + 1, OrderStatus.WAITING_TRIGGER.value
        )
        statuses[i] = OrderStatus.COMPLETED.value
        _lock_cycle_grid_side(state, "BUY")
    elif side_u == "SELL":
        fired = _ensure_list_len(state, "sell_grid_fired", i + 1, False)
        fills = _ensure_list_len(state, "sell_grid_fill_price", i + 1, None)
        peaks = _ensure_list_len(state, "sell_grid_peak_price", i + 1, None)
        changed = changed or not bool(fired[i])
        fired[i] = True
        if price_f > 0 and fills[i] != price_f:
            fills[i] = price_f
            changed = True
        if peaks[i] is None and anchor_f > 0:
            peaks[i] = anchor_f
            changed = True
        statuses = _ensure_list_len(
            state, "sell_grid_status", i + 1, OrderStatus.WAITING_TRIGGER.value
        )
        statuses[i] = OrderStatus.COMPLETED.value
        _lock_cycle_grid_side(state, "SELL")
    else:
        return False
    before_skips = (
        str(state.get("active_health_skips") or "")
        + str(state.get("buy_grid_min_notional_blocked") or "")
        + str(state.get("sell_grid_min_notional_blocked") or "")
    )
    _clear_grid_skip_for_filled(state, side_u, i)
    after_skips = (
        str(state.get("active_health_skips") or "")
        + str(state.get("buy_grid_min_notional_blocked") or "")
        + str(state.get("sell_grid_min_notional_blocked") or "")
    )
    return changed or before_skips != after_skips


def _heal_grid_fill_flags_from_history(state: Dict[str, Any]) -> bool:
    """Eski state onarımı: history/ledger dolu ama fired/fill alanları eksik kalmış olabilir."""
    changed = False
    for side, hist_key in (("BUY", "buy_history"), ("SELL", "sell_history")):
        hist = state.get(hist_key) or []
        if not isinstance(hist, list):
            continue
        for row in hist:
            if not isinstance(row, dict) or row.get("grid_index") is None:
                continue
            changed = _mark_grid_fill_state(
                state,
                side,
                row.get("grid_index"),
                row.get("price") or row.get("execution_price"),
                row.get("execution_price") or row.get("price"),
            ) or changed
    ledger = state.get("cycle_ledger_current") or {}
    fills = ledger.get("fills") if isinstance(ledger, dict) else []
    if isinstance(fills, list):
        for row in fills:
            if not isinstance(row, dict) or row.get("slot_id") is None:
                continue
            reason = str(row.get("reason") or "")
            if reason == "trail_buy_grid":
                side = "BUY"
            elif reason == "trail_sell_grid":
                side = "SELL"
            else:
                continue
            changed = _mark_grid_fill_state(
                state,
                side,
                row.get("slot_id"),
                row.get("price"),
                row.get("price"),
            ) or changed
    if changed:
        for fired_key, mode_name, trail_key in (
            ("buy_grid_fired", BotEngineMode.TRAIL_BUY_GRID.value, "_trail_buy_grid_index"),
            ("sell_grid_fired", BotEngineMode.TRAIL_SELL_GRID.value, "_trail_sell_grid_index"),
        ):
            try:
                active_idx = int(state.get(trail_key))
            except (TypeError, ValueError):
                active_idx = -1
            fired = state.get(fired_key) or []
            if state.get("mode") == mode_name and active_idx >= 0 and active_idx < len(fired) and fired[active_idx]:
                state["mode"] = BotEngineMode.IDLE.value
                state.pop(trail_key, None)
        _heal_cycle_grid_side(state)
    return changed


def _heal_stale_cycle_close_flags(state: Dict[str, Any]) -> None:
    """
    Kar satışı/kar alımı emri verildi ama fill gelmeden kopma olursa
    _profit_exit_done / _cycle_complete takılı kalabilir; grid alış varken kar satışı devre dışı kalır.
    """
    if not state.get("initial_allocation_done"):
        return
    mode = state.get("mode") or BotEngineMode.IDLE.value
    if mode in (
        BotEngineMode.TRAIL_PROFIT_SELL.value,
        BotEngineMode.TRAIL_REENTRY_BUY.value,
    ):
        return

    profit_done = bool(state.get("_profit_exit_done"))
    reentry_done = bool(state.get("_reentry_done"))
    cycle_complete = bool(state.get("_cycle_complete"))
    if not (profit_done or reentry_done or cycle_complete):
        return

    ledger = state.get("cycle_ledger_current") or {}
    sell_qty_ledger = _f(ledger.get("sell_qty_total")) or 0.0
    buy_qty_ledger = _f(ledger.get("buy_qty_total")) or 0.0
    cycle_side = state.get("cycle_grid_side")
    stale = False
    reason = ""

    def _non_grid_sell() -> bool:
        return any(
            isinstance(x, dict) and x.get("grid_index") is None
            for x in (state.get("sell_history") or [])
        )

    def _non_grid_buy() -> bool:
        return any(
            isinstance(x, dict) and x.get("grid_index") is None
            for x in (state.get("buy_history") or [])
        )

    if cycle_side == "BUY" and (profit_done or cycle_complete):
        has_basis = bool(state.get("buy_history")) or buy_qty_ledger > 0
        if has_basis and sell_qty_ledger <= 0 and not _non_grid_sell():
            stale = True
            reason = "profit_exit_pending_no_sell_fill"
    elif cycle_side == "SELL" and (reentry_done or cycle_complete):
        has_basis = bool(state.get("sell_history")) or sell_qty_ledger > 0
        if has_basis and buy_qty_ledger <= 0 and not _non_grid_buy():
            stale = True
            reason = "reentry_pending_no_buy_fill"
    elif cycle_complete and not profit_done and not reentry_done:
        stale = True
        reason = "orphan_cycle_complete"

    if not stale:
        return

    state.pop("_profit_exit_done", None)
    state.pop("_reentry_done", None)
    state.pop("_cycle_complete", None)
    state.pop("_profit_exit_breakeven", None)
    state.pop("_profit_exit_trigger_price", None)
    state.pop("_reentry_avg_sell", None)
    state.pop("_reentry_max_buy_price", None)
    logger.info(
        "BOT_CYCLE_CLOSE_FLAGS_HEALED bot_id=%s cycle_id=%s reason=%s side=%s",
        state.get("bot_id"),
        state.get("cycle_id"),
        reason,
        cycle_side,
    )


def _try_trigger_sell_grid(
    state: Dict[str, Any],
    idx: int,
    P: float,
    s_i: float,
    *,
    base_balance: float = 0.0,
) -> bool:
    """Satış gridini tetikle; aynı tick'te birden fazla grid aynı canlı tepe (P) ile başlayabilir."""
    fired = state.get("sell_grid_fired") or []
    triggers = state.get("sell_grid_trigger_price") or []
    if idx < len(fired) and fired[idx]:
        return False
    if idx < len(triggers) and triggers[idx] is not None:
        return False
    if not trigger_reached(OrderType.SELL_GRID, P, s_i):
        return False
    while len(triggers) <= idx:
        triggers.append(None)
    triggers[idx] = s_i
    state["sell_grid_trigger_price"] = triggers
    peaks = state.get("sell_grid_peak_price") or []
    while len(peaks) <= idx:
        peaks.append(None)
    peaks[idx] = P
    state["sell_grid_peak_price"] = peaks
    statuses = _ensure_list_len(
        state, "sell_grid_status", idx + 1, OrderStatus.WAITING_TRIGGER.value
    )
    statuses[idx] = OrderStatus.TRAILING.value
    if _f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0:
        state["grid_reference_base"] = base_balance
    logger.info(
        "BOT_GRID_SELL_TRIGGER bot_id=%s grid=%s price=%.4f trigger=%.4f",
        state.get("bot_id"),
        idx,
        P,
        s_i,
    )
    return True


def _try_trigger_buy_grid(
    state: Dict[str, Any], idx: int, P: float, b_j: float
) -> bool:
    """Alım gridini tetikle; aynı tick'te birden fazla grid aynı canlı dip (P) ile başlayabilir."""
    fired = state.get("buy_grid_fired") or []
    triggers = state.get("buy_grid_trigger_price") or []
    if idx < len(fired) and fired[idx]:
        return False
    if idx < len(triggers) and triggers[idx] is not None:
        return False
    if not trigger_reached(OrderType.BUY_GRID, P, b_j):
        return False
    while len(triggers) <= idx:
        triggers.append(None)
    triggers[idx] = b_j
    state["buy_grid_trigger_price"] = triggers
    troughs = state.get("buy_grid_trough_price") or []
    while len(troughs) <= idx:
        troughs.append(None)
    troughs[idx] = P
    state["buy_grid_trough_price"] = troughs
    statuses = _ensure_list_len(
        state, "buy_grid_status", idx + 1, OrderStatus.WAITING_TRIGGER.value
    )
    statuses[idx] = OrderStatus.TRAILING.value
    logger.info(
        "BOT_GRID_BUY_TRIGGER bot_id=%s grid=%s price=%.4f trigger=%.4f",
        state.get("bot_id"),
        idx,
        P,
        b_j,
    )
    return True


def _sync_trailing_mode(state: Dict[str, Any], n: int, m: int) -> None:
    """Legacy mode/index for logging and UI; grids trail in parallel via per-grid arrays."""
    sell_trailing: List[int] = []
    buy_trailing: List[int] = []
    for i in range(n):
        fired = (
            bool(state["sell_grid_fired"][i])
            if i < len(state.get("sell_grid_fired") or [])
            else False
        )
        trig = (
            state["sell_grid_trigger_price"][i]
            if i < len(state.get("sell_grid_trigger_price") or [])
            else None
        )
        if not fired and trig is not None:
            sell_trailing.append(i)
    for j in range(m):
        fired = (
            bool(state["buy_grid_fired"][j])
            if j < len(state.get("buy_grid_fired") or [])
            else False
        )
        trig = (
            state["buy_grid_trigger_price"][j]
            if j < len(state.get("buy_grid_trigger_price") or [])
            else None
        )
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


def _cycle_reference_price(state: Dict[str, Any]) -> Optional[float]:
    """Return the immutable reference captured once for the current cycle.

    ``reference_price`` remains as a compatibility alias for old snapshots, but
    fills and live ticks must never overwrite either value during a cycle.
    """
    initial = _f(state.get("initial_reference_price"))
    if initial is not None and initial > 0:
        return initial
    legacy = _f(state.get("reference_price"))
    if legacy is not None and legacy > 0:
        state["initial_reference_price"] = legacy
        return legacy
    return None


def _invalidate_impossible_grid_states(
    state: Dict[str, Any], config: DcaGridTrailingConfig
) -> List[Dict[str, Any]]:
    """Cancel unsafe legacy trailing states instead of manufacturing an extreme.

    A BUY trough above its trigger (or SELL peak below its trigger) proves that
    trailing started without the required directional crossing. Such an order is
    returned to WAITING_TRIGGER and will only arm again through the normal gate.
    """
    invalid: List[Dict[str, Any]] = []
    for side, order_type, trigger_key, extreme_key, fired_key, status_key, size in (
        (
            "BUY",
            OrderType.BUY_GRID,
            "buy_grid_trigger_price",
            "buy_grid_trough_price",
            "buy_grid_fired",
            "buy_grid_status",
            len(config.buy_grids),
        ),
        (
            "SELL",
            OrderType.SELL_GRID,
            "sell_grid_trigger_price",
            "sell_grid_peak_price",
            "sell_grid_fired",
            "sell_grid_status",
            len(config.sell_grids),
        ),
    ):
        triggers = _ensure_list_len(state, trigger_key, size, None)
        extremes = _ensure_list_len(state, extreme_key, size, None)
        fired = _ensure_list_len(state, fired_key, size, False)
        statuses = _ensure_list_len(
            state, status_key, size, OrderStatus.WAITING_TRIGGER.value
        )
        for idx in range(size):
            trigger = triggers[idx]
            extreme = extremes[idx]
            if fired[idx] or trigger is None or extreme is None:
                continue
            try:
                is_valid = valid_extreme(order_type, trigger, extreme)
            except ValueError:
                is_valid = False
            if is_valid:
                continue
            invalid.append(
                {
                    "cycle_id": int(state.get("cycle_id") or 1),
                    "grid_id": idx,
                    "order_type": order_type.value,
                    "side": side,
                    "trigger_price": trigger,
                    "tracked_extreme_price": extreme,
                    "action": "CANCELLED_AND_REARMED",
                }
            )
            triggers[idx] = None
            extremes[idx] = None
            statuses[idx] = OrderStatus.WAITING_TRIGGER.value
        state[trigger_key] = triggers
        state[extreme_key] = extremes
        state[status_key] = statuses
    if invalid:
        audit = state.setdefault("invalid_grid_state_audit", [])
        audit.extend(invalid)
        state["invalid_grid_state_audit"] = audit[-200:]
        logger.error(
            "BOT_INVALID_GRID_STATE_CANCELLED bot_id=%s cycle_id=%s count=%s",
            state.get("bot_id"),
            state.get("cycle_id"),
            len(invalid),
        )
    return invalid


def _repair_profit_cost_basis_state(
    state: Dict[str, Any], config: DcaGridTrailingConfig
) -> Optional[Dict[str, Any]]:
    """Cancel and recalculate an armed legacy profit trail with the wrong basis."""
    mode = state.get("mode") or BotEngineMode.IDLE.value
    if mode == BotEngineMode.TRAIL_PROFIT_SELL.value:
        order_type = OrderType.PROFIT_SELL
        expected_type = CostBasisType.WEIGHTED_BUY_COST
        average = _avg_buy_price_for_trigger(state)
        pct = config.profit_exit_rise_pct
        stored_trigger = _f(state.get("_profit_exit_trigger_price"))
        stored_type = state.get("_profit_exit_cost_basis_type")
        trigger_key = "_profit_exit_trigger_price"
    elif mode == BotEngineMode.TRAIL_REENTRY_BUY.value:
        order_type = OrderType.PROFIT_REBUY
        expected_type = CostBasisType.WEIGHTED_SELL_PRICE
        average = _avg_sell_price_for_trigger(state)
        pct = config.profit_reentry_drop_pct
        stored_trigger = _f(state.get("_reentry_trigger_price"))
        stored_type = state.get("_reentry_cost_basis_type")
        trigger_key = "_reentry_trigger_price"
    else:
        return None
    if average is None or average <= 0:
        audit = {
            "cycle_id": int(state.get("cycle_id") or 1),
            "order_type": order_type.value,
            "old_cost_basis_type": stored_type,
            "cost_basis_type": expected_type.value,
            "cost_basis_price": None,
            "old_trigger_price": stored_trigger,
            "trigger_price": None,
            "action": "CANCELLED_NO_COMPLETED_GRID",
        }
        state.setdefault("invalid_profit_basis_audit", []).append(audit)
        state["invalid_profit_basis_audit"] = state["invalid_profit_basis_audit"][-100:]
        state["mode"] = BotEngineMode.IDLE.value
        state.pop("trail_anchor_price", None)
        state.pop("trail_activation_price", None)
        for key in (
            "_profit_exit_trigger_price",
            "_profit_exit_avg_buy",
            "_profit_exit_breakeven",
            "_profit_exit_cost_basis_type",
            "_profit_exit_linked_grid_ids",
            "_reentry_trigger_price",
            "_reentry_avg_sell",
            "_reentry_max_buy_price",
            "_reentry_cost_basis_type",
            "_reentry_linked_grid_ids",
        ):
            state.pop(key, None)
        logger.error(
            "BOT_INVALID_PROFIT_BASIS_CANCELLED bot_id=%s cycle_id=%s order_type=%s reason=no_completed_grid",
            state.get("bot_id"),
            state.get("cycle_id"),
            order_type.value,
        )
        return audit
    correct_trigger = float(price_from_reference(average, pct, order_type))
    tolerance = max(abs(correct_trigger) * 1e-12, 1e-12)
    if (
        stored_trigger is not None
        and abs(stored_trigger - correct_trigger) <= tolerance
        and stored_type == expected_type.value
    ):
        return None
    audit = {
        "cycle_id": int(state.get("cycle_id") or 1),
        "order_type": order_type.value,
        "old_cost_basis_type": stored_type,
        "cost_basis_type": expected_type.value,
        "cost_basis_price": average,
        "old_trigger_price": stored_trigger,
        "trigger_price": correct_trigger,
        "action": "CANCELLED_AND_RECALCULATED",
    }
    state.setdefault("invalid_profit_basis_audit", []).append(audit)
    state["invalid_profit_basis_audit"] = state["invalid_profit_basis_audit"][-100:]
    state["mode"] = BotEngineMode.IDLE.value
    state.pop("trail_anchor_price", None)
    state.pop("trail_activation_price", None)
    state[trigger_key] = correct_trigger
    if order_type == OrderType.PROFIT_SELL:
        state["_profit_exit_avg_buy"] = average
        state["_profit_exit_cost_basis_type"] = expected_type.value
    else:
        state["_reentry_avg_sell"] = average
        state["_reentry_cost_basis_type"] = expected_type.value
    logger.error(
        "BOT_INVALID_PROFIT_BASIS_CANCELLED bot_id=%s cycle_id=%s order_type=%s old_trigger=%s new_trigger=%.10f",
        state.get("bot_id"),
        state.get("cycle_id"),
        order_type.value,
        stored_trigger,
        correct_trigger,
    )
    return audit


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
    _heal_grid_fill_flags_from_history(state)
    _heal_cycle_grid_side(state)
    _heal_stale_cycle_close_flags(state)
    P = _f(price)
    if P is None or P <= 0:
        logger.warning(
            "BOT_STRATEGY_PRICE_INVALID bot_id=%s price=%s",
            state.get("bot_id", 0),
            price,
        )
        return [], config.tick_interval_ms / 1000.0
    _invalidate_impossible_grid_states(state, config)

    ref_raw = _cycle_reference_price(state)
    initial_done = bool(state.get("initial_allocation_done"))
    init_base_qty_val = _f(state.get("initial_alloc_base_qty"))
    init_base_qty = (init_base_qty_val or 0.0) if init_base_qty_val is not None else 0.0
    # Self-heal: ia_done True but initial_alloc_base_qty 0 (e.g. state save failed) -> use base_balance
    if initial_done and init_base_qty <= 0 and base_balance > 0:
        state["initial_alloc_base_qty"] = round(float(base_balance), 10)
        init_base_qty = base_balance
        logger.info(
            "BOT_STATE_HEALED bot_id=%s initial_alloc_base_qty was 0, set from base_balance=%.6f",
            state.get("bot_id", 0),
            base_balance,
        )
    elif initial_done and init_base_qty <= 0:
        logger.critical(
            "BOT_STRATEGY_IA_INVALID bot_id=%s ia_done=True but initial_alloc_base_qty=%.6f (impossible)",
            state.get("bot_id", 0),
            init_base_qty,
        )
    # Self-heal: ia_done True but reference_price None (e.g. state save failed after fill)
    if initial_done and ref_raw is None:
        state["reference_price"] = P
        state["initial_reference_price"] = P
        logger.info(
            "BOT_STATE_HEALED bot_id=%s reference_price was None, set to current price=%.2f",
            state.get("bot_id", 0),
            P,
        )
        ref_raw = P
    ref_val = _f(ref_raw)
    ref = (ref_val if ref_val is not None else 0.0) or P
    logger.debug(
        "BOT_STRATEGY_TICK bot_id=%s price=%.2f ref=%s ia_done=%s mode=%s base_bal=%.4f quote_bal=%.2f",
        state.get("bot_id", 0),
        P,
        ref,
        initial_done,
        state.get("mode", "IDLE"),
        base_balance,
        quote_balance,
    )
    from app.botengine.strategies.grid_outage_recovery import maybe_reset_cold_start_grids

    maybe_reset_cold_start_grids(state, config)
    apply_recovery, gap_sec = should_apply_outage_recovery(state, config)
    if apply_recovery:
        apply_grid_outage_recovery(state, config, P, gap_sec=gap_sec)
    _repair_profit_cost_basis_state(state, config)

    favorable_sell = set(state.get("_outage_favorable_sell") or [])
    favorable_buy = set(state.get("_outage_favorable_buy") or [])
    force_profit_sell = bool(state.get("_outage_force_profit_sell"))
    force_reentry_buy = bool(state.get("_outage_force_reentry_buy"))
    mode = state.get("mode") or BotEngineMode.IDLE.value
    cycle = int(state.get("cycle_id") or 1)
    n = len(config.sell_grids)
    m = len(config.buy_grids)
    actions: List[Dict[str, Any]] = []
    next_wake = config.tick_interval_ms / 1000.0

    # ---- Günlük kayıp limiti (daily_loss_limit_usd) ----
    # Disabled by operator policy in BOTH manual and dynamic mode. Keep the old
    # logic behind DAILY_LOSS_RUNTIME_ENABLED so this can be restored cleanly.
    if not DAILY_LOSS_RUNTIME_ENABLED:
        state.pop("_daily_loss_limit_hit", None)
    _dll = _f(getattr(config, "daily_loss_limit_usd", 0.0)) or 0.0
    if DAILY_LOSS_RUNTIME_ENABLED and _dll > 0 and initial_done:
        _current_equity = base_balance * P + quote_balance
        # Günlük referans: bugünkü TR günü başı equity; yoksa initial_capital
        _today_tr = None
        try:
            from app.utils.tz_utils import turkey_today_date_str

            _today_tr = turkey_today_date_str()
        except Exception:
            pass
        _dll_ref_date = state.get("_dll_ref_date")
        _dll_ref_usd = _f(state.get("_dll_ref_usd")) or 0.0
        if _dll_ref_date != _today_tr or _dll_ref_usd <= 0:
            # Yeni gün — referans equity'yi sıfırla
            state["_dll_ref_date"] = _today_tr
            state["_dll_ref_usd"] = round(_current_equity, 2)
            _dll_ref_usd = _current_equity
        _daily_loss = _dll_ref_usd - _current_equity
        if _daily_loss >= _dll:
            bot_id_log = state.get("bot_id", 0)
            logger.warning(
                "BOT_DAILY_LOSS_LIMIT_HIT bot_id=%s daily_limit=%.2f loss=%.2f equity=%.2f ref=%.2f — tick durduruldu",
                bot_id_log,
                _dll,
                _daily_loss,
                _current_equity,
                _dll_ref_usd,
            )
            if not state.get("_daily_loss_limit_hit"):
                state["_daily_loss_limit_hit"] = True
                from app.botengine.state_store import queue_engine_event

                queue_engine_event(
                    state,
                    "HEALTH_WARN",
                    f"Günlük kayıp limiti aşıldı — kayıp {_daily_loss:.2f} USDT, limit {_dll:.2f} USDT",
                    {
                        "error_code": "DAILY_LOSS_LIMIT",
                        "daily_loss_usd": round(_daily_loss, 4),
                        "daily_loss_limit_usd": _dll,
                        "current_equity": round(_current_equity, 4),
                        "ref_equity": round(_dll_ref_usd, 4),
                        "cycle_id": cycle,
                    },
                )
            return [], next_wake

    # ---- max_buy_levels hard limit ----
    # Kaç buy grid'i zaten tetiklendi? Limit zorunlu ve pozitif; yeni BUY bu sınırı aşamaz.
    _mbl = max(1, int(getattr(config, "max_buy_levels", 1) or 1))
    _fired_buys = sum(1 for x in (state.get("buy_grid_fired") or []) if x)
    state["_buy_levels_fired"] = _fired_buys
    state["_buy_levels_max"] = _mbl
    if _fired_buys >= _mbl:
        # Mevcut grid tetiklemelerini engelle ama trailing + profit exit çalışmaya devam etsin
        state["_buy_levels_blocked"] = True
    else:
        state.pop("_buy_levels_blocked", None)

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
            state.get("bot_id", 0),
            P,
            c,
            base_pct * 100,
            quote_pct * 100,
            c_base,
        )
        state["mode"] = BotEngineMode.IDLE.value
        actions.append(
            {
                "type": "place",
                "side": "BUY",
                "symbol": config.symbol,
                "quote_qty": c_base,
                "client_order_id": f"init_{state.get('bot_id', 0)}_c{cycle}",
                "reason": "initial_allocation",
                "_c_quote": c_quote,
                "trigger_price": P,
            }
        )
        logger.info(
            "BOT_STRATEGY_INITIAL_ALLOC_ACTION bot_id=%s quote_qty=%.2f (intent only)",
            state.get("bot_id", 0),
            c_base,
        )
        # İlk alım başarısız olursa kısa sürede tekrar dene (1s); başlar başlamaz alım yapılsın
        next_wake_initial = min(next_wake, 1.0)
        return actions, next_wake_initial
    else:
        logger.debug(
            "BOT_STRATEGY_INITIAL_DONE bot_id=%s ia_done=True skipping initial alloc",
            state.get("bot_id", 0),
        )

    # ---- Cycle-level exclusive trails (re-entry / profit exit) ----
    if mode == BotEngineMode.TRAIL_REENTRY_BUY.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(min(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 + config.profit_reentry_rise_pct / 100.0)
        max_buy = _f(state.get("_reentry_max_buy_price"))
        if P >= thr or force_reentry_buy:
            if not _within_planned_completion_slippage("BUY", P, thr, config):
                logger.debug(
                    "BOT_TRAIL_GAP_GUARD bot_id=%s side=BUY price=%.8f planned=%.8f max_slippage_pct=%.4f",
                    state.get("bot_id"),
                    P,
                    thr,
                    config.max_slippage_pct,
                )
                return _finish_tick(state, config, actions, next_wake)
            if (
                max_buy is not None
                and max_buy > 0
                and P > max_buy
                and not force_reentry_buy
            ):
                logger.info(
                    "BOT_REENTRY_HOLD bot_id=%s cycle_id=%s price=%.4f max_buy=%.4f decision=HOLD reason=buy_above_sell_basis",
                    state.get("bot_id"),
                    state.get("cycle_id"),
                    P,
                    max_buy,
                )
                return _finish_tick(state, config, actions, next_wake)
            qty_usdt = _reentry_buy_qty(state, config, quote_balance)
            if qty_usdt and qty_usdt > 0:
                actions.append(
                    {
                        "type": "place",
                        "side": "BUY",
                        "symbol": config.symbol,
                        "quote_qty": qty_usdt,
                        "client_order_id": _action_id(state, "reentry", 0),
                        "reason": "trail_reentry_buy",
                        "trigger_price": P,
                        "execution_price": thr,
                        "order_type": OrderType.PROFIT_REBUY.value,
                        "cost_basis_type": CostBasisType.WEIGHTED_SELL_PRICE.value,
                        "cost_basis_price": state.get("_reentry_avg_sell"),
                        "linked_grid_ids": state.get("_reentry_linked_grid_ids") or [],
                    }
                )
                state["mode"] = BotEngineMode.IDLE.value
                state["_reentry_done"] = True
                state["_cycle_complete"] = True
                state.pop("_reentry_avg_sell", None)
                state.pop("_reentry_max_buy_price", None)
                state.pop("_outage_force_reentry_buy", None)
        return _finish_tick(state, config, actions, next_wake)

    if mode == BotEngineMode.TRAIL_PROFIT_SELL.value:
        anchor = _f(state.get("trail_anchor_price") or P) or P
        state["trail_anchor_price"] = _f(max(anchor, P)) or P
        thr = state["trail_anchor_price"] * (1 - config.profit_exit_drop_pct / 100.0)
        breakeven_floor = _f(state.get("_profit_exit_breakeven"))
        if breakeven_floor is not None and breakeven_floor > 0:
            thr = max(thr, breakeven_floor)
        if P <= thr or force_profit_sell:
            if not _within_planned_completion_slippage("SELL", P, thr, config):
                logger.debug(
                    "BOT_TRAIL_GAP_GUARD bot_id=%s side=SELL price=%.8f planned=%.8f max_slippage_pct=%.4f",
                    state.get("bot_id"),
                    P,
                    thr,
                    config.max_slippage_pct,
                )
                return _finish_tick(state, config, actions, next_wake)
            if (
                breakeven_floor is not None
                and P < breakeven_floor
                and not force_profit_sell
            ):
                logger.info(
                    "BOT_PROFIT_EXIT_HOLD bot_id=%s cycle_id=%s price=%.4f breakeven=%.4f decision=HOLD reason=trail_would_sell_below_breakeven",
                    state.get("bot_id"),
                    state.get("cycle_id"),
                    P,
                    breakeven_floor,
                )
                return _finish_tick(state, config, actions, next_wake)
            qty = _profit_exit_sell_qty(state, config, base_balance)
            if qty and qty > 0:
                actions.append(
                    {
                        "type": "place",
                        "side": "SELL",
                        "symbol": config.symbol,
                        "quantity": qty,
                        "client_order_id": _action_id(state, "profit_exit", 0),
                        "reason": "trail_profit_sell",
                        "trigger_price": P,
                        "execution_price": thr,
                        "order_type": OrderType.PROFIT_SELL.value,
                        "cost_basis_type": CostBasisType.WEIGHTED_BUY_COST.value,
                        "cost_basis_price": state.get("_profit_exit_avg_buy"),
                        "linked_grid_ids": state.get("_profit_exit_linked_grid_ids") or [],
                    }
                )
                state["mode"] = BotEngineMode.IDLE.value
                state["_profit_exit_done"] = True
                state["_cycle_complete"] = True
                state.pop("_profit_exit_breakeven", None)
                state.pop("_profit_exit_trigger_price", None)
                state.pop("_outage_force_profit_sell", None)
        return _finish_tick(state, config, actions, next_wake)

    # ---- Per-grid parallel trailing (each grid independent) ----
    ref = _cycle_reference_price(state)
    if ref is None or ref <= 0:
        state["reference_price"] = P
        state["initial_reference_price"] = P
        ref = P
        logger.info(
            "BOT_STATE_HEALED bot_id=%s ref was None/0, set to price=%.2f",
            state.get("bot_id", 0),
            P,
        )
    if initial_done and (_f(state.get("grid_reference_quote") or 0) <= 0):
        if quote_balance > 0:
            state["grid_reference_quote"] = quote_balance
            if _f(state.get("grid_reference_base") or 0) <= 0 and base_balance > 0:
                state["grid_reference_base"] = base_balance
            if _f(state.get("cycle_start_equity") or 0) <= 0:
                current_eq = quote_balance + base_balance * (P or 0)
                state["cycle_start_equity"] = current_eq
            logger.info(
                "BOT_STATE_HEALED bot_id=%s grid_reference_quote=%.2f (quote_balance)",
                state.get("bot_id", 0),
                quote_balance,
            )

    sell_trail_pct = config.sell_trigger_trailing_pct
    buy_trail_pct = config.buy_trigger_trailing_pct
    sell_enabled = _sell_grids_enabled(state)
    buy_enabled = _buy_grids_enabled(state)
    cycle_side = get_cycle_grid_side(state)
    base_reserved = 0.0
    quote_reserved = 0.0

    # Active sell trails: update per-grid peak, execute when price retraces
    if sell_enabled:
        for idx in range(n):
            if idx < len(state["sell_grid_fired"]) and state["sell_grid_fired"][idx]:
                continue
            trigger_hit = (
                state["sell_grid_trigger_price"][idx]
                if idx < len(state["sell_grid_trigger_price"])
                else None
            )
            if trigger_hit is None:
                continue
            th_num = _f(trigger_hit) or P
            peaks = state["sell_grid_peak_price"]
            while len(peaks) <= idx:
                peaks.append(None)
            cur_peak = _f(peaks[idx]) if peaks[idx] is not None else th_num
            if not valid_extreme(OrderType.SELL_GRID, th_num, cur_peak):
                continue
            cur_peak = float(update_extreme(OrderType.SELL_GRID, cur_peak, P))
            peaks[idx] = cur_peak
            state["sell_grid_peak_price"] = peaks
            exec_thr = float(
                completion_price(OrderType.SELL_GRID, cur_peak, sell_trail_pct)
            )
            if completion_reached(
                OrderType.SELL_GRID, P, cur_peak, sell_trail_pct
            ) or idx in favorable_sell:
                if not _within_planned_completion_slippage(
                    "SELL", P, exec_thr, config
                ):
                    logger.debug(
                        "BOT_TRAIL_GAP_GUARD bot_id=%s side=SELL grid=%s price=%.8f planned=%.8f max_slippage_pct=%.4f",
                        state.get("bot_id"),
                        idx,
                        P,
                        exec_thr,
                        config.max_slippage_pct,
                    )
                    continue
                if grid_min_notional_blocked(state, "SELL", idx):
                    continue
                avail_base = max(0.0, (_f(base_balance) or 0.0) - base_reserved)
                qty = _sell_qty_for_grid(state, config, idx, avail_base, price=P)
                if qty and qty > 0:
                    if not _meets_min_notional(config, "SELL", P, qty=qty):
                        logger.debug(
                            "BOT_STRATEGY_GRID_SKIP bot_id=%s skip_reason=MIN_NOTIONAL side=SELL grid=%s notional=%.2f min=%.2f",
                            state.get("bot_id", 0),
                            idx,
                            qty * P,
                            getattr(config, "min_notional_guard", DEFAULT_MIN_NOTIONAL_USDT),
                        )
                        _queue_grid_skip(
                            state,
                            side="SELL",
                            grid_index=idx,
                            notional=qty * P,
                            config=config,
                            reason="trail_sell_grid",
                        )
                        continue
                    base_reserved += qty
                    actions.append(
                        {
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
                            "order_type": OrderType.SELL_GRID.value,
                            "cost_basis_type": CostBasisType.INITIAL_REFERENCE.value,
                            "cost_basis_price": ref,
                            "linked_grid_ids": [idx],
                        }
                    )

    # Active buy trails: update per-grid trough, execute when price rises
    if buy_enabled:
        # max_buy_levels hard guard: kaç BUY grid'i bu tick'e KADAR tetiklendi?
        _mbl_limit = max(1, int(getattr(config, "max_buy_levels", 1) or 1))
        _buy_fired_count = sum(1 for x in (state.get("buy_grid_fired") or []) if x)
        for idx in range(m):
            if idx < len(state["buy_grid_fired"]) and state["buy_grid_fired"][idx]:
                continue
            trigger_hit = (
                state["buy_grid_trigger_price"][idx]
                if idx < len(state["buy_grid_trigger_price"])
                else None
            )
            if trigger_hit is None:
                continue
            th_num = _f(trigger_hit) or P
            troughs = state["buy_grid_trough_price"]
            while len(troughs) <= idx:
                troughs.append(None)
            cur_trough = _f(troughs[idx]) if troughs[idx] is not None else th_num
            if not valid_extreme(OrderType.BUY_GRID, th_num, cur_trough):
                continue
            cur_trough = float(update_extreme(OrderType.BUY_GRID, cur_trough, P))
            troughs[idx] = cur_trough
            state["buy_grid_trough_price"] = troughs
            exec_thr = float(
                completion_price(OrderType.BUY_GRID, cur_trough, buy_trail_pct)
            )
            if completion_reached(
                OrderType.BUY_GRID, P, cur_trough, buy_trail_pct
            ) or idx in favorable_buy:
                if not _within_planned_completion_slippage(
                    "BUY", P, exec_thr, config
                ):
                    logger.debug(
                        "BOT_TRAIL_GAP_GUARD bot_id=%s side=BUY grid=%s price=%.8f planned=%.8f max_slippage_pct=%.4f",
                        state.get("bot_id"),
                        idx,
                        P,
                        exec_thr,
                        config.max_slippage_pct,
                    )
                    continue
                if grid_min_notional_blocked(state, "BUY", idx):
                    continue
                # max_buy_levels: bu seviye limiti aşıyorsa hard block
                if _buy_fired_count >= _mbl_limit:
                    logger.warning(
                        "BOT_BUY_LEVEL_BLOCKED bot_id=%s grid_idx=%s fired=%s max=%s — max_buy_levels hard limit",
                        state.get("bot_id", 0),
                        idx,
                        _buy_fired_count,
                        _mbl_limit,
                    )
                    from app.botengine.state_store import queue_engine_event

                    queue_engine_event(
                        state,
                        "SKIP_REASON",
                        f"max_buy_levels={_mbl_limit} aşıldı — grid {idx} engellendi",
                        {
                            "error_code": "MAX_BUY_LEVELS_EXCEEDED",
                            "grid_index": idx,
                            "fired": _buy_fired_count,
                            "max": _mbl_limit,
                        },
                    )
                    continue
                avail_quote = max(0.0, (_f(quote_balance) or 0.0) - quote_reserved)
                quote_q = _buy_qty_for_grid(state, config, idx, avail_quote, price=P)
                if quote_q and quote_q > 0:
                    if not _meets_min_notional(config, "BUY", P, quote_qty=quote_q):
                        logger.debug(
                            "BOT_STRATEGY_GRID_SKIP bot_id=%s skip_reason=MIN_NOTIONAL side=BUY grid=%s notional=%.2f min=%.2f",
                            state.get("bot_id", 0),
                            idx,
                            quote_q,
                            getattr(config, "min_notional_guard", DEFAULT_MIN_NOTIONAL_USDT),
                        )
                        _queue_grid_skip(
                            state,
                            side="BUY",
                            grid_index=idx,
                            notional=quote_q,
                            config=config,
                            reason="trail_buy_grid",
                        )
                        continue
                    quote_reserved += quote_q
                    _buy_fired_count += 1  # Bu tick'te tetiklenen buy sayısını artır
                    actions.append(
                        {
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
                            "order_type": OrderType.BUY_GRID.value,
                            "cost_basis_type": CostBasisType.INITIAL_REFERENCE.value,
                            "cost_basis_price": ref,
                            "linked_grid_ids": [idx],
                        }
                    )
                else:
                    logger.warning(
                        "BOT_STRATEGY_TRAIL_BUY_SKIP bot_id=%s grid_idx=%s price=%.2f thr=%.2f quote_balance=%.2f quote_q=%.2f",
                        state.get("bot_id", 0),
                        idx,
                        P,
                        exec_thr,
                        quote_balance,
                        quote_q or 0.0,
                    )

    state.pop("_outage_favorable_buy", None)
    state.pop("_outage_favorable_sell", None)

    # New sell grid triggers (parallel — aynı tick'te birden fazla seviye tetiklenebilir)
    if sell_enabled:
        batch_sell = 0
        for i in range(n):
            g = config.sell_grids[i] if i < len(config.sell_grids) else {}
            pct = _float(g.get("sell_grid_pct") or g.get("trigger_pct"), 0)
            s_i = float(price_from_reference(ref, pct, OrderType.SELL_GRID))
            if _try_trigger_sell_grid(state, i, P, s_i, base_balance=base_balance):
                batch_sell += 1
        if batch_sell > 1:
            logger.info(
                "BOT_GRID_PARALLEL_TRIGGER bot_id=%s side=SELL count=%s price=%.4f",
                state.get("bot_id"),
                batch_sell,
                P,
            )

    # New buy grid triggers (parallel)
    if buy_enabled:
        batch_buy = 0
        for j in range(m):
            g = config.buy_grids[j] if j < len(config.buy_grids) else {}
            pct = _float(g.get("buy_grid_pct") or g.get("trigger_pct"), 0)
            b_j = float(price_from_reference(ref, pct, OrderType.BUY_GRID))
            if _try_trigger_buy_grid(state, j, P, b_j):
                batch_buy += 1
        if batch_buy > 1:
            logger.info(
                "BOT_GRID_PARALLEL_TRIGGER bot_id=%s side=BUY count=%s price=%.4f",
                state.get("bot_id"),
                batch_buy,
                P,
            )

    _sync_trailing_mode(state, n, m)

    # ---- Re-entry / profit exit arming (tur yönü kilitli olunca ilgili kar gridi) ----
    sell_hist = state.get("sell_history") or []
    if cycle_side == "SELL" and sell_hist and not state.get("_reentry_done"):
        buy_fee = getattr(config, "buy_fee_rate", 0.001) or 0.001
        sell_fee = getattr(config, "sell_fee_rate", 0.001) or 0.001
        drop_pct = config.profit_reentry_drop_pct
        avg_sell = _avg_sell_price_for_trigger(state)
        arm_price = (
            float(price_from_reference(avg_sell, drop_pct, OrderType.PROFIT_REBUY))
            if avg_sell and avg_sell > 0
            else None
        )
        max_buy = (
            avg_sell * (1 - sell_fee) / (1 + buy_fee)
            if avg_sell and avg_sell > 0
            else None
        )
        if avg_sell and avg_sell > 0 and arm_price is not None and P <= arm_price:
            logger.info(
                "BOT_REENTRY_EVAL bot_id=%s cycle_id=%s avg_sell=%.4f arm=%.4f max_buy=%.4f price=%.4f decision=ARM",
                state.get("bot_id"),
                state.get("cycle_id"),
                avg_sell,
                arm_price,
                max_buy or 0,
                P,
            )
            state["trail_anchor_price"] = P
            state["trail_activation_price"] = P
            state["_reentry_avg_sell"] = avg_sell
            state["_reentry_max_buy_price"] = max_buy
            state["_reentry_trigger_price"] = arm_price
            state["_reentry_cost_basis_type"] = CostBasisType.WEIGHTED_SELL_PRICE.value
            state["_reentry_linked_grid_ids"] = _linked_grid_ids(
                sell_hist, state=state, side="SELL"
            )
            state["mode"] = BotEngineMode.TRAIL_REENTRY_BUY.value
            return _finish_tick(state, config, actions, next_wake)

    # D) Profit exit (after any buy) — fee-aware when pnl_mode=cycle_only_fee_aware_v1
    buy_hist = state.get("buy_history") or []
    init_q = _float(state.get("initial_alloc_base_qty"), 0)
    has_basis = bool(buy_hist or (init_q > 0 and state.get("initial_allocation_done")))
    if cycle_side == "BUY" and has_basis and not state.get("_profit_exit_done"):
        avg_buy = _avg_buy_price_for_trigger(state)
        if avg_buy and avg_buy > 0:
            trigger_price = float(
                price_from_reference(
                    avg_buy, config.profit_exit_rise_pct, OrderType.PROFIT_SELL
                )
            )
            if P >= trigger_price:
                state["trail_anchor_price"] = P
                state["trail_activation_price"] = P
                state["_profit_exit_breakeven"] = avg_buy
                state["_profit_exit_trigger_price"] = trigger_price
                state["_profit_exit_avg_buy"] = avg_buy
                state["_profit_exit_cost_basis_type"] = (
                    CostBasisType.WEIGHTED_BUY_COST.value
                )
                state["_profit_exit_linked_grid_ids"] = _linked_grid_ids(
                    buy_hist, state=state, side="BUY"
                )
                state["mode"] = BotEngineMode.TRAIL_PROFIT_SELL.value
                return _finish_tick(state, config, actions, next_wake)

    return _finish_tick(state, config, actions, next_wake)


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
    min_n = _float(getattr(config, "min_notional_guard", DEFAULT_MIN_NOTIONAL_USDT), DEFAULT_MIN_NOTIONAL_USDT)
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
    # Dynamic Mode V2 carries a Decimal-calculated absolute side amount through
    # the JSON boundary. Legacy grids continue to use percentage sizing.
    dynamic_amount = _f(g.get("dynamic_amount"))
    if dynamic_amount is not None:
        return _f(min(max(dynamic_amount, 0.0), base_balance)) or 0.0
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


def _quote_ref_for_buy_grid(
    state: Dict,
    config: DcaGridTrailingConfig,
    quote_balance: float,
) -> float:
    """Alım grid referansı: target_quote_usdt > quote_alloc*equity > grid_reference_quote > quote_balance."""
    buffer = _float(getattr(config, "available_quote_buffer_pct", 0.005), 0.005)
    tb = state.get("target_budgets")
    if isinstance(tb, dict):
        target_quote = _float(tb.get("target_quote_usdt"), 0)
        if target_quote > 0:
            return target_quote * (1.0 - buffer)
    eq = _f(state.get("cycle_start_equity") or 0) or 0.0
    if eq > 0:
        quote_alloc = _float(getattr(config, "quote_alloc_pct", 50), 50) / 100.0
        derived = eq * quote_alloc * (1.0 - buffer)
        if derived > 0:
            return derived
    ref = _f(state.get("grid_reference_quote") or 0) or 0.0
    if ref <= 0:
        return quote_balance
    return min(ref, quote_balance) if quote_balance > 0 else ref


def _buy_qty_for_grid(
    state: Dict,
    config: DcaGridTrailingConfig,
    idx: int,
    quote_balance: float,
    price: Optional[float] = None,
) -> float:
    """Alım miktarı = referans quote * grid yüzdesi (her grid kendi payı kadar)."""
    g = config.buy_grids[idx] if idx < len(config.buy_grids) else {}
    dynamic_amount = _f(g.get("dynamic_amount"))
    if dynamic_amount is not None:
        return _f(min(max(dynamic_amount, 0.0), quote_balance)) or 0.0
    pct = _float(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"), 10.0) / 100.0
    ref = _quote_ref_for_buy_grid(state, config, quote_balance)
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
    """Grid alımları VWAP: yalnız Binance fill `price` (kar tetik / reentry ile uyumlu)."""
    avg = weighted_average_price(
        _grid_fill_rows(state, "BUY"), required_side="BUY", grid_only=False
    )
    return float(avg) if avg is not None else None


def _avg_sell_price_for_trigger(state: Dict) -> Optional[float]:
    """Grid satışları VWAP: yalnız Binance fill `price` (kar alım tetik ile uyumlu)."""
    avg = weighted_average_price(
        _grid_fill_rows(state, "SELL"), required_side="SELL", grid_only=False
    )
    return float(avg) if avg is not None else None


def _linked_grid_ids(
    history: list,
    *,
    state: Optional[Dict[str, Any]] = None,
    side: Optional[str] = None,
) -> List[int]:
    linked: List[int] = []
    for row in history:
        if not isinstance(row, dict) or row.get("grid_index") is None:
            continue
        try:
            idx = int(row["grid_index"])
        except (TypeError, ValueError):
            continue
        if idx not in linked:
            linked.append(idx)
    if linked or state is None or side not in ("BUY", "SELL"):
        return linked
    fired = state.get(
        "buy_grid_fired" if side == "BUY" else "sell_grid_fired"
    ) or []
    return [idx for idx, done in enumerate(fired) if done]


def _grid_fill_rows(state: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    side_u = side.upper()
    history = state.get("buy_history" if side_u == "BUY" else "sell_history") or []
    explicit = [
        row
        for row in history
        if isinstance(row, dict)
        and (
            row.get("grid_index") is not None
            or str(row.get("reason") or "")
            == ("trail_buy_grid" if side_u == "BUY" else "trail_sell_grid")
        )
    ]
    if explicit:
        return explicit
    # Legacy snapshots did not persist grid_index/reason in history. Initial
    # allocation was never appended there, so rows are safely grid fills when a
    # grid-fired flag exists. Explicit profit close rows are still excluded.
    fired = state.get("buy_grid_fired" if side_u == "BUY" else "sell_grid_fired") or []
    if not any(fired):
        return []
    excluded = "trail_reentry_buy" if side_u == "BUY" else "trail_profit_sell"
    return [
        row
        for row in history
        if isinstance(row, dict) and str(row.get("reason") or "") != excluded
    ]


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


def _reentry_buy_qty(
    state: Dict, config: DcaGridTrailingConfig, quote_balance: float
) -> float:
    """Re-entry: use "all sell proceeds" equivalent. We approximate as quote to spend = sum(sell qty * sell price)."""
    h = state.get("sell_history") or []
    total = sum(_float(x.get("qty"), 0) * _float(x.get("price"), 0) for x in h)
    cap = min(quote_balance, total) if total else 0
    return _f(cap) or 0.0


def _profit_exit_sell_qty(
    state: Dict, config: DcaGridTrailingConfig, base_balance: float
) -> float:
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
    fee_amount: Optional[float] = None,
    fee_asset: str = "USDT",
) -> None:
    """Update state after a fill. Appends to sell_history/buy_history, updates balances, realized_pnl, fees.
    execution_price: trail gerçekleşme eşiği (grid UI); ortalama maliyet yalnız fill `price` ile hesaplanır."""
    q = _f(executed_qty) or 0.0
    p = _f(executed_price) or 0.0
    fee_val = _f(fee) or 0.0
    fee_raw = _f(fee_amount) if fee_amount is not None else fee_val
    fee_asset_u = (fee_asset or "USDT").upper()
    base_asset = symbol_base_asset(str(state.get("symbol") or ""))
    fee_in_base = bool(base_asset and fee_asset_u == base_asset)
    fee_in_quote = fee_asset_u in ("USDT", "USDC", "BUSD", "FDUSD")
    exec_p = _f(execution_price) if execution_price is not None else None
    state["fees_paid_usdt_cycle"] = (
        _f(state.get("fees_paid_usdt_cycle") or 0) or 0.0
    ) + fee_val
    r = (reason or "").strip()
    if side == "SELL":
        base_debit = q + (fee_raw if fee_in_base else 0.0)
        quote_fee = fee_raw if fee_in_quote else 0.0
        state["base_balance"] = (
            _f(state.get("base_balance") or 0) or 0.0
        ) - base_debit
        state["quote_balance"] = (
            (_f(state.get("quote_balance") or 0) or 0.0) + q * p - quote_fee
        )
        entry = {
            "grid_index": grid_index,
            "qty": q,
            "price": p,
            "side": "SELL",
            "reason": r,
            "fill_quantity": q,
            "fill_price": p,
            "fill_total": q * p,
            "fee_amount": fee_raw,
            "fee_asset": fee_asset_u,
            "fee_usdt": fee_val,
        }
        if exec_p is not None:
            entry["execution_price"] = exec_p
        state.setdefault("sell_history", []).append(entry)
        if r == "trail_sell_grid":
            _mark_grid_fill_state(state, "SELL", grid_index, p, exec_p or p)
        avg_buy = _avg_buy_price(state)
        cost = q * (_f(avg_buy or p) or p)
        state["realized_pnl_usdt_cycle"] = (
            _f(state.get("realized_pnl_usdt_cycle") or 0) or 0.0
        ) + (q * p - fee_val - cost)
    else:
        base_credit = max(0.0, q - (fee_raw if fee_in_base else 0.0))
        quote_fee = fee_raw if fee_in_quote else 0.0
        state["base_balance"] = (
            _f(state.get("base_balance") or 0) or 0.0
        ) + base_credit
        state["quote_balance"] = (
            (_f(state.get("quote_balance") or 0) or 0.0
        ) - q * p - quote_fee
        )
        if (reason or "").strip() != "initial_allocation":
            entry = {
                "grid_index": grid_index,
                "qty": q,
                "price": p,
                "side": "BUY",
                "reason": r,
                "fill_quantity": q,
                "fill_price": p,
                "fill_total": q * p,
                "fee_amount": fee_raw,
                "fee_asset": fee_asset_u,
                "fee_usdt": fee_val,
            }
            if exec_p is not None:
                entry["execution_price"] = exec_p
            state.setdefault("buy_history", []).append(entry)
            if r == "trail_buy_grid":
                _mark_grid_fill_state(state, "BUY", grid_index, p, exec_p or p)


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
        fee_amount: Any = None,
        fee_asset: str = "USDT",
    ) -> None:
        apply_fill_to_state(
            state,
            side,
            executed_qty,
            executed_price,
            fee,
            grid_index=grid_index,
            reason=reason,
            execution_price=execution_price,
            fee_amount=fee_amount,
            fee_asset=fee_asset,
        )


def _archive_cycle_grid_fills(state: Dict[str, Any], cycle_id: int) -> None:
    """Tur kapanmadan önce grid tetik/tepe-dip/gerçekleşme fiyatlarını arşivle (UI tur işlemleri modalı)."""
    archive = state.setdefault("cycle_grid_fills_archive", [])
    seen = {
        (
            int(e.get("cycle_id") or 0),
            int(e.get("grid_index") or -1),
            (e.get("side") or "").upper(),
        )
        for e in archive
        if isinstance(e, dict)
    }

    def _append(
        side: str, idx: int, fired: bool, trig_arr: list, ext_arr: list, fill_arr: list
    ) -> None:
        if not fired:
            return
        key = (cycle_id, idx, side)
        if key in seen:
            return
        trig = trig_arr[idx] if idx < len(trig_arr) else None
        ext = ext_arr[idx] if idx < len(ext_arr) else None
        exec_p = fill_arr[idx] if idx < len(fill_arr) else None
        hist_key = "sell_history" if side == "SELL" else "buy_history"
        hist = [
            h
            for h in (state.get(hist_key) or [])
            if isinstance(h, dict) and int(h.get("grid_index") or -1) == idx
        ]
        hist_row = hist[-1] if hist else {}
        archive.append(
            {
                "cycle_id": cycle_id,
                "grid_index": idx,
                "side": side,
                "trigger_price": _f(trig) if trig is not None else None,
                "extreme_price": _f(ext) if ext is not None else None,
                "execution_price": _f(exec_p)
                if exec_p is not None
                else (
                    _f(hist_row.get("execution_price"))
                    if hist_row.get("execution_price") is not None
                    else None
                ),
                "fill_price": _f(hist_row.get("price"))
                if hist_row.get("price") is not None
                else None,
                "qty": _f(hist_row.get("qty"))
                if hist_row.get("qty") is not None
                else None,
            }
        )
        seen.add(key)

    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    for i, fired in enumerate(sell_fired):
        _append(
            "SELL",
            i,
            bool(fired),
            state.get("sell_grid_trigger_price") or [],
            state.get("sell_grid_peak_price") or [],
            state.get("sell_grid_fill_price") or [],
        )
    for j, fired in enumerate(buy_fired):
        _append(
            "BUY",
            j,
            bool(fired),
            state.get("buy_grid_trigger_price") or [],
            state.get("buy_grid_trough_price") or [],
            state.get("buy_grid_fill_price") or [],
        )
    if len(archive) > 500:
        state["cycle_grid_fills_archive"] = archive[-500:]


def _avg_buy_grid_from_history(buy_hist: list) -> Optional[float]:
    grid_h = [
        x for x in buy_hist if isinstance(x, dict) and x.get("grid_index") is not None
    ]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in grid_h)
    return tv / tq


def _avg_sell_grid_from_history(sell_hist: list) -> Optional[float]:
    grid_h = [
        x for x in sell_hist if isinstance(x, dict) and x.get("grid_index") is not None
    ]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in grid_h)
    return tv / tq


def _archive_cycle_close_trade(state: Dict[str, Any], cycle_id: int) -> None:
    """Tur kapanış işlemi (kar satışı / kar alımı) detaylarını arşivle."""
    if not state.get("_profit_exit_done") and not state.get("_reentry_done"):
        return
    archive = state.setdefault("cycle_close_trades_archive", [])
    anchor = _f(state.get("trail_anchor_price"))
    ledger = state.get("cycle_ledger_current") or {}
    avg_ledger = ledger.get("avg_cost_quote_per_base")
    try:
        avg_ledger_f = float(avg_ledger) if avg_ledger is not None else None
    except (TypeError, ValueError):
        avg_ledger_f = None

    if state.get("_profit_exit_done"):
        reason = "trail_profit_sell"
        side = "SELL"
        hist = state.get("sell_history") or []
        row: Dict[str, Any] = {}
        for x in reversed(hist):
            if isinstance(x, dict) and x.get("grid_index") is None:
                row = x
                break
        if not row and hist:
            row = hist[-1] if isinstance(hist[-1], dict) else {}
        avg_cost = (
            _avg_buy_grid_from_history(state.get("buy_history") or []) or avg_ledger_f
        )
        archive.append(
            {
                "cycle_id": cycle_id,
                "reason": reason,
                "side": side,
                "qty": _f(row.get("qty")) or None,
                "fill_price": _f(row.get("price")) or None,
                "execution_price": _f(row.get("execution_price") or row.get("price"))
                or None,
                "tepe_price": anchor if anchor > 0 else None,
                "dip_price": None,
                "average_cost": round(avg_cost, 8) if avg_cost else None,
                "breakeven_price": _f(state.get("_profit_exit_breakeven"))
                if state.get("_profit_exit_breakeven") is not None
                else None,
                "trigger_price": _f(state.get("_profit_exit_trigger_price"))
                if state.get("_profit_exit_trigger_price") is not None
                else None,
            }
        )
    elif state.get("_reentry_done"):
        reason = "trail_reentry_buy"
        side = "BUY"
        hist = state.get("buy_history") or []
        row = {}
        for x in reversed(hist):
            if isinstance(x, dict) and x.get("grid_index") is None:
                row = x
                break
        if not row and hist:
            row = hist[-1] if isinstance(hist[-1], dict) else {}
        avg_cost = _avg_sell_grid_from_history(state.get("sell_history") or [])
        archive.append(
            {
                "cycle_id": cycle_id,
                "reason": reason,
                "side": side,
                "qty": _f(row.get("qty")) or None,
                "fill_price": _f(row.get("price")) or None,
                "execution_price": _f(row.get("execution_price") or row.get("price"))
                or None,
                "tepe_price": None,
                "dip_price": anchor if anchor > 0 else None,
                "average_cost": round(avg_cost, 8) if avg_cost else None,
                "breakeven_price": None,
                "trigger_price": None,
            }
        )
    if len(archive) > 200:
        state["cycle_close_trades_archive"] = archive[-200:]


def cycle_reset_after_fill(
    state: Dict[str, Any],
    new_reference_price: float,
    n: int,
    m: int,
    symbol: Optional[str] = None,
) -> None:
    """After re-entry or profit-exit fill: tur karı hesaplanır, cycle_id++, reference_price, grid referansları bileşik bakiyeye güncellenir."""
    old_cycle_id = int(state.get("cycle_id") or 1)
    from app.botengine.skip_event_policy import clear_skip_runtime_state

    clear_skip_runtime_state(state)
    from app.botengine.cycle_ledger import archive_cycle_ledger_fills

    archive_cycle_ledger_fills(state, old_cycle_id)
    _archive_cycle_grid_fills(state, old_cycle_id)
    _archive_cycle_close_trade(state, old_cycle_id)
    quote_bal = _f(state.get("quote_balance") or 0) or 0.0
    base_bal = _f(state.get("base_balance") or 0) or 0.0
    price = _f(new_reference_price) or new_reference_price
    current_equity = round(quote_bal + base_bal * price, 2)
    cycle_start = _f(state.get("cycle_start_equity") or 0) or 0.0
    state["last_cycle_profit_usdt"] = round(current_equity - cycle_start, 2)
    new_cycle_id = int(state.get("cycle_id") or 1) + 1
    state["cycle_id"] = new_cycle_id
    state["reference_price"] = price
    state["initial_reference_price"] = price
    state["sell_grid_fired"] = [False] * n
    state["sell_grid_status"] = [OrderStatus.WAITING_TRIGGER.value] * n
    state["sell_grid_trigger_price"] = [None] * n
    state["sell_grid_peak_price"] = [None] * n
    state["sell_grid_fill_price"] = [None] * n
    state["buy_grid_fired"] = [False] * m
    state["buy_grid_status"] = [OrderStatus.WAITING_TRIGGER.value] * m
    state["buy_grid_trigger_price"] = [None] * m
    state["buy_grid_trough_price"] = [None] * m
    state["buy_grid_fill_price"] = [None] * m
    state["sell_history"] = []
    state["buy_history"] = []
    state["cycle_start_equity"] = current_equity
    state["grid_reference_quote"] = quote_bal
    state["grid_reference_base"] = base_bal
    state.pop("_reentry_done", None)
    state.pop("_profit_exit_done", None)
    state.pop("_cycle_complete", None)
    state.pop("cycle_grid_side", None)
    # Dynamic Mode: yeni cycle başladı, orchestrator bir sonraki tick'te
    # snapshot'ı yeniden hesaplasın. Manuel modda bayrak görmezden gelinir.
    state["_dynamic_recompute_needed"] = True
    # Yeni tur henüz "engage" olmadı: cycle-entry risk gate yeniden karar verebilsin
    try:
        from app.botengine.dynamic.cycle_gate import reset_for_new_cycle

        reset_for_new_cycle(state)
    except Exception:
        state.pop("_dynamic_cycle_engaged", None)
        state.pop("_dynamic_cycle_hold", None)
        state.pop("_dynamic_round_pending", None)
    if symbol:
        from datetime import datetime, timezone
        from app.botengine.cycle_ledger import build_cycle_ledger_empty

        started_at = datetime.now(timezone.utc).isoformat()
        state["cycle_opened_at"] = started_at
        state["cycle_ledger_current"] = build_cycle_ledger_empty(
            new_cycle_id, symbol, started_at=started_at
        )
    else:
        started_at = None
    if new_cycle_id >= 2 and base_bal > 0 and price > 0:
        from datetime import datetime, timezone

        ts_open = started_at or datetime.now(timezone.utc).isoformat()
        state.setdefault("cycle_open_trades", []).append(
            {
                "cycle_id": new_cycle_id,
                "side": "BUY",
                "qty": round(base_bal, 10),
                "price": round(price, 10),
                "reference_price": round(price, 10),
                "quote_balance": round(quote_bal, 2),
                "equity_usdt": round(current_equity, 2),
                "ts": ts_open,
                "fee": 0.0,
            }
        )
        state["cycle_open_trades"] = state["cycle_open_trades"][-200:]
