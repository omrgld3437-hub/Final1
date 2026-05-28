"""
Cycle Trade Ledger: single source of truth for cycle PnL (fee-aware, cycle-isolated).
Each cycle records only fills belonging to that cycle; realized_pnl_quote = sell_quote - buy_quote - fees.
"""
from __future__ import annotations
import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Reasons that belong to the current cycle (not initial_allocation)
CYCLE_FILL_REASONS = frozenset({
    "trail_buy_grid", "trail_sell_grid", "trail_reentry_buy", "trail_profit_sell",
})


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _symbol_to_base_quote(symbol: str) -> tuple:
    s = (symbol or "").upper().strip()
    if s.endswith("USDT"):
        return (s[:-4] or "BTC", "USDT")
    if s.endswith("BUSD"):
        return (s[:-4] or "BTC", "BUSD")
    return (s, "USDT")


# Inventory PnL: trail_sell_grid (SELL) + trail_reentry_buy (BUY) → coin advantage (base qty)
# Cash PnL: trail_buy_grid (BUY) + trail_profit_sell (SELL) → realized USDT
INVENTORY_REASONS = frozenset({"trail_sell_grid", "trail_reentry_buy"})
CASH_REASONS = frozenset({"trail_buy_grid", "trail_profit_sell"})
PNL_MODE_INVENTORY = "INVENTORY_QTY_V1"
PNL_MODE_CASH = "CASH_USDT_V1"


def build_cycle_ledger_empty(cycle_id: int, symbol: str) -> Dict[str, Any]:
    """Empty cycle ledger snapshot for a new cycle."""
    base_asset, quote_asset = _symbol_to_base_quote(symbol)
    return {
        "cycle_id": cycle_id,
        "symbol": symbol,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "fills": [],
        "buy_qty_total": 0.0,
        "buy_quote_total": 0.0,
        "buy_fee_total_quote": 0.0,
        "sell_qty_total": 0.0,
        "sell_quote_total": 0.0,
        "sell_fee_total_quote": 0.0,
        "avg_cost_quote_per_base": None,
        "realized_pnl_quote": 0.0,
        "breakeven_price": None,
        "matched_qty": 0.0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        # Dual PnL: Inventory (coin qty) + Cash (USDT)
        "inventory_coin_adv_qty": 0.0,
        "inventory_fees_usdt": 0.0,
        "cash_pnl_usdt": 0.0,
        "cash_fees_usdt": 0.0,
    }


def cycle_ledger_add_fill(
    ledger: Dict[str, Any],
    ts: str,
    order_id: Optional[str],
    client_order_id: Optional[str],
    side: str,
    qty: float,
    price: float,
    fee: float,
    fee_asset: str,
    reason: str,
    slot_id: Optional[int] = None,
    fee_raw: Optional[float] = None,
) -> None:
    """Append one fill to cycle ledger and recompute totals. Mutates ledger in place."""
    qty = max(0.0, _num(qty))
    price = max(0.0, _num(price))
    fee = max(0.0, _num(fee))
    if fee_asset and fee_asset.upper() != "USDT":
        logger.warning(
            "CYCLE_LEDGER fee_asset=%s not USDT; treating fee as quote for PnL (TODO: convert)",
            fee_asset,
        )
    fee_quote = fee  # assume fee already in quote (USDT) or converted by caller
    entry = {
        "ts": ts,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "side": (side or "").upper(),
        "qty": qty,
        "price": price,
        "fee": fee,
        "fee_asset": fee_asset or "USDT",
        "reason": reason or "",
    }
    if slot_id is not None:
        try:
            entry["slot_id"] = int(slot_id)
        except (TypeError, ValueError):
            pass
    if fee_raw is not None and fee_raw > 0:
        entry["fee_raw"] = round(float(fee_raw), 10)
    entry["fee_usdt"] = round(fee_quote, 8)
    ledger.setdefault("fills", []).append(entry)
    if side and side.upper() == "BUY":
        ledger["buy_qty_total"] = _num(ledger.get("buy_qty_total")) + qty
        ledger["buy_quote_total"] = _num(ledger.get("buy_quote_total")) + qty * price
        ledger["buy_fee_total_quote"] = _num(ledger.get("buy_fee_total_quote")) + fee_quote
    else:
        ledger["sell_qty_total"] = _num(ledger.get("sell_qty_total")) + qty
        ledger["sell_quote_total"] = _num(ledger.get("sell_quote_total")) + qty * price
        ledger["sell_fee_total_quote"] = _num(ledger.get("sell_fee_total_quote")) + fee_quote
    _cycle_ledger_recompute(ledger)


def _cycle_ledger_recompute(ledger: Dict[str, Any]) -> None:
    """
    Recompute derived: avg_cost, matched_qty, realized_pnl_quote; canonical cash totals; then dual PnL.
    Invariant (Spec §55 / cycle_end consistency):
      cash_pnl_usdt = sell_quote_total - buy_quote_total (gross)
      cash_fees_usdt = buy_fee_total_quote + sell_fee_total_quote
      realized_pnl_quote == realized_pnl_cycle_net = cash_pnl_usdt - cash_fees_usdt
    profit_usdt (gross) and pnl_usdt_net (net) must be derived from these only.
    """
    buy_qty = _num(ledger.get("buy_qty_total"))
    buy_quote = _num(ledger.get("buy_quote_total"))
    buy_fee = _num(ledger.get("buy_fee_total_quote"))
    sell_qty = _num(ledger.get("sell_qty_total"))
    sell_quote = _num(ledger.get("sell_quote_total"))
    sell_fee = _num(ledger.get("sell_fee_total_quote"))
    matched_qty = min(buy_qty, sell_qty) if (buy_qty > 0 and sell_qty > 0) else 0.0
    ledger["matched_qty"] = matched_qty
    if buy_qty > 0:
        ledger["avg_cost_quote_per_base"] = (buy_quote + buy_fee) / buy_qty
    else:
        ledger["avg_cost_quote_per_base"] = None
    total_fees = buy_fee + sell_fee
    realized = sell_quote - buy_quote - total_fees
    ledger["realized_pnl_quote"] = round(realized, 6)
    # Canonical cash totals for cycle_end payload (always consistent)
    ledger["cash_pnl_usdt"] = round(sell_quote - buy_quote, 6)
    ledger["cash_fees_usdt"] = round(total_fees, 6)
    _recompute_dual_pnl(ledger)


def _recompute_dual_pnl(ledger: Dict[str, Any]) -> None:
    """
    FIFO match fills into Inventory PnL (trail_sell_grid ↔ trail_reentry_buy) and Cash PnL (trail_buy_grid ↔ trail_profit_sell).
    Mutates ledger with inventory_coin_adv_qty, inventory_fees_usdt, cash_pnl_usdt, cash_fees_usdt.
    """
    fills = ledger.get("fills") or []
    inv_coin_adv = 0.0
    inv_fees = 0.0
    cash_pnl = 0.0
    cash_fees = 0.0

    # Inventory: queue of (qty_remaining, price, fee_total) for trail_sell_grid
    inv_sells: List[tuple] = []
    # Cash: queue of (qty_remaining, price, fee_total) for trail_buy_grid
    cash_buys: List[tuple] = []

    for e in fills:
        side = (e.get("side") or "").upper()
        reason = (e.get("reason") or "").strip()
        qty = max(0.0, _num(e.get("qty")))
        price = max(0.0, _num(e.get("price")))
        fee = max(0.0, _num(e.get("fee")))
        if qty <= 0:
            continue
        if reason == "trail_sell_grid" and side == "SELL":
            inv_sells.append([qty, price, fee])
        elif reason == "trail_reentry_buy" and side == "BUY":
            # Match this BUY FIFO against inv_sells
            buy_qty_rem = qty
            buy_fee_total = fee
            buy_qty_total = qty
            idx = 0
            while buy_qty_rem > 1e-12 and idx < len(inv_sells):
                sq, sp, sf = inv_sells[idx]
                if sq <= 0:
                    idx += 1
                    continue
                take = min(sq, buy_qty_rem)
                sell_fee_alloc = sf * (take / sq) if sq > 0 else 0
                buy_fee_alloc = buy_fee_total * (take / buy_qty_total) if buy_qty_total > 0 else 0
                sell_proceeds_net = take * sp - sell_fee_alloc
                buy_price_eff = price if price > 0 else 1.0
                buy_qty_equiv = sell_proceeds_net / buy_price_eff if buy_price_eff > 0 else 0
                inv_coin_adv += buy_qty_equiv - take
                inv_fees += sell_fee_alloc + buy_fee_alloc
                inv_sells[idx][0] = sq - take
                buy_qty_rem -= take
                if inv_sells[idx][0] <= 0:
                    idx += 1
            if buy_qty_rem > 0 and idx >= len(inv_sells):
                inv_fees += buy_fee_total * (buy_qty_rem / buy_qty_total) if buy_qty_total > 0 else 0
        elif reason == "trail_buy_grid" and side == "BUY":
            cash_buys.append([qty, price, fee])
        elif reason == "trail_profit_sell" and side == "SELL":
            sell_qty_rem = qty
            sell_fee_total = fee
            sell_qty_total = qty
            idx = 0
            while sell_qty_rem > 1e-12 and idx < len(cash_buys):
                bq, bp, bf = cash_buys[idx]
                if bq <= 0:
                    idx += 1
                    continue
                take = min(bq, sell_qty_rem)
                buy_fee_alloc = bf * (take / bq) if bq > 0 else 0
                sell_fee_alloc = sell_fee_total * (take / sell_qty_total) if sell_qty_total > 0 else 0
                gross = take * (price - bp)
                cash_pnl += gross - buy_fee_alloc - sell_fee_alloc
                cash_fees += buy_fee_alloc + sell_fee_alloc
                cash_buys[idx][0] = bq - take
                sell_qty_rem -= take
                if cash_buys[idx][0] <= 0:
                    idx += 1
            if sell_qty_rem > 0 and idx >= len(cash_buys):
                cash_fees += sell_fee_total * (sell_qty_rem / sell_qty_total) if sell_qty_total > 0 else 0

    ledger["inventory_coin_adv_qty"] = round(inv_coin_adv, 8)
    ledger["inventory_fees_usdt"] = round(inv_fees, 6)
    # Dual FIFO cash path (for strategy/display); canonical cash_pnl_usdt/cash_fees_usdt set in _cycle_ledger_recompute
    ledger["cash_fifo_pnl_usdt"] = round(cash_pnl, 6)
    ledger["cash_fifo_fees_usdt"] = round(cash_fees, 6)


def cycle_ledger_breakeven_price(
    ledger: Dict[str, Any],
    buy_fee_rate: float = 0.001,
    sell_fee_rate: float = 0.001,
) -> Optional[float]:
    """
    Fee-aware breakeven: price at which sell proceeds (after sell fee) equal buy cost (including buy fee).
    breakeven_price = avg_cost * (1 + buy_fee_rate) / (1 - sell_fee_rate).
    """
    avg = ledger.get("avg_cost_quote_per_base")
    if avg is None or avg <= 0:
        return None
    buy_fee_rate = max(0.0, min(1.0, _num(buy_fee_rate)))
    sell_fee_rate = max(0.0, min(1.0 - 1e-6, _num(sell_fee_rate)))
    return round(avg * (1.0 + buy_fee_rate) / (1.0 - sell_fee_rate), 6)


def cycle_ledger_trigger_price(
    ledger: Dict[str, Any],
    min_net_profit_rate: float = 0.001,
    buy_fee_rate: float = 0.001,
    sell_fee_rate: float = 0.001,
    profit_rise_pct: Optional[float] = None,
) -> Optional[float]:
    """
    Minimum price to arm profit-exit trailing SELL.
    trigger_price = breakeven_price * (1 + max(min_net_profit_rate, profit_rise_pct/100)).
    profit_rise_pct maps to UI "Kar satış tetik %" (profit_exit_rise_pct).
    """
    be = cycle_ledger_breakeven_price(ledger, buy_fee_rate, sell_fee_rate)
    if be is None or be <= 0:
        return None
    min_net = max(0.0, _num(min_net_profit_rate))
    rise = max(0.0, _num(profit_rise_pct) / 100.0) if profit_rise_pct is not None else 0.0
    effective_rate = max(min_net, rise)
    return round(be * (1.0 + effective_rate), 6)


def cycle_ledger_avg_sell_price(ledger: Dict[str, Any]) -> Optional[float]:
    """Weighted average sell price from cycle ledger (trail_sell_grid fills)."""
    sell_qty = _num(ledger.get("sell_qty_total"))
    sell_quote = _num(ledger.get("sell_quote_total"))
    if sell_qty <= 0:
        return None
    return sell_quote / sell_qty


def cycle_ledger_reentry_arm_price(
    ledger: Dict[str, Any],
    drop_pct: float,
) -> Optional[float]:
    """
    Price at or below which reentry trailing BUY may arm.
    arm_price = avg_sell * (1 - profit_reentry_drop_pct/100).
    """
    avg = cycle_ledger_avg_sell_price(ledger)
    if avg is None or avg <= 0:
        return None
    drop = max(0.0, _num(drop_pct) / 100.0)
    return round(avg * (1.0 - drop), 6)


def cycle_ledger_reentry_max_buy_price(
    ledger: Dict[str, Any],
    buy_fee_rate: float = 0.001,
    sell_fee_rate: float = 0.001,
) -> Optional[float]:
    """
    Fee-aware ceiling for reentry BUY: do not pay above avg_sell adjusted for round-trip fees.
    max_buy = avg_sell * (1 - sell_fee_rate) / (1 + buy_fee_rate).
    """
    avg = cycle_ledger_avg_sell_price(ledger)
    if avg is None or avg <= 0:
        return None
    sf = max(0.0, min(1.0, _num(sell_fee_rate)))
    bf = max(0.0, min(1.0, _num(buy_fee_rate)))
    return round(avg * (1.0 - sf) / (1.0 + bf), 6)


def cycle_ledger_with_basis(
    state: Dict[str, Any],
    ledger: Dict[str, Any],
    basis_mode: str = "grid_only",
) -> Dict[str, Any]:
    """
    Profit-exit cost basis: grid-only uses cycle ledger buys; total merges initial_allocation.
    Returns a shallow copy with recomputed avg_cost_quote_per_base (fills unchanged).
    """
    mode = (basis_mode or "grid_only").strip().lower()
    if mode != "total":
        return ledger
    init_q = _num(state.get("initial_alloc_base_qty"))
    init_p = _num(state.get("initial_alloc_price"))
    if init_q <= 0 or init_p <= 0 or not state.get("initial_allocation_done"):
        return ledger
    buy_qty = _num(ledger.get("buy_qty_total")) + init_q
    buy_quote = _num(ledger.get("buy_quote_total")) + init_q * init_p
    buy_fee = _num(ledger.get("buy_fee_total_quote"))
    if buy_qty <= 0:
        return ledger
    out = dict(ledger)
    out["buy_qty_total"] = buy_qty
    out["buy_quote_total"] = buy_quote
    out["avg_cost_quote_per_base"] = (buy_quote + buy_fee) / buy_qty
    return out


def cycle_ledger_from_state(state: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Load or create current cycle ledger from state. Does not mutate state."""
    current = state.get("cycle_ledger_current")
    if isinstance(current, dict) and current.get("symbol") == symbol:
        return current
    cycle_id = int(state.get("cycle_id") or 1)
    return build_cycle_ledger_empty(cycle_id, symbol)


def get_cycle_type_and_base_delta(
    close_reason: Optional[str],
    ledger: Optional[Dict[str, Any]],
) -> tuple:
    """
    Infer cycle_type and base_delta from close_reason and ledger.
    Returns (cycle_type: str, base_delta: float).
    - trail_profit_sell -> LONG_SCALP, base_delta=0
    - trail_reentry_buy -> INVENTORY_REBALANCE, base_delta = buy_qty_total - sell_qty_total
    """
    if (close_reason or "").strip() == "trail_profit_sell":
        return "LONG_SCALP", 0.0
    if (close_reason or "").strip() == "trail_reentry_buy":
        base_delta = 0.0
        if isinstance(ledger, dict):
            buy_qty = _num(ledger.get("buy_qty_total"))
            sell_qty = _num(ledger.get("sell_qty_total"))
            base_delta = round(buy_qty - sell_qty, 8)
        return "INVENTORY_REBALANCE", base_delta
    return "UNKNOWN", 0.0


def archive_cycle_ledger_fills(state: Dict[str, Any], cycle_id: int) -> None:
    """Tur kapanmadan önce cycle ledger fill listesini arşivle (tamamlanmış tur reason eşlemesi)."""
    ledger = state.get("cycle_ledger_current")
    if not isinstance(ledger, dict):
        return
    fills = ledger.get("fills") or []
    if not fills:
        return
    archive = state.setdefault("cycle_ledger_fills_archive", [])
    for block in archive:
        if isinstance(block, dict) and int(block.get("cycle_id") or 0) == int(cycle_id):
            return
    archive.append({
        "cycle_id": int(cycle_id),
        "fills": copy.deepcopy(fills),
        "avg_cost_quote_per_base": ledger.get("avg_cost_quote_per_base"),
        "buy_quote_total": ledger.get("buy_quote_total"),
        "sell_quote_total": ledger.get("sell_quote_total"),
    })
    if len(archive) > 50:
        state["cycle_ledger_fills_archive"] = archive[-50:]
