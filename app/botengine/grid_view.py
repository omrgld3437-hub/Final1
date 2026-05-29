"""
Compute grid points and profit points for bot detail UI.
Uses state + config. Dip/tepe yalnızca state'teki saklı tepe/dip (motor min/max ile günceller).
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


def _f(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return round(float(v), 10)
    except (TypeError, ValueError):
        return default


def _avg_sell_price(state: Dict) -> Optional[float]:
    h = state.get("sell_history") or []
    if not h:
        return None
    tq = sum(_f(x.get("qty")) for x in h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in h)
    return tv / tq


def _avg_buy_price(state: Dict) -> Optional[float]:
    h = state.get("buy_history") or []
    if not h:
        return None
    tq = sum(_f(x.get("qty")) for x in h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in h)
    return tv / tq


def _avg_sell_price_grid_only(state: Dict) -> Optional[float]:
    """Ortalama satış: yalnız kapanmış grid fill fiyatları (qty-ağırlıklı VWAP). execution_price = trail eşiği, dahil edilmez."""
    h = state.get("sell_history") or []
    grid_h = [x for x in h if x.get("grid_index") is not None]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in grid_h)
    return tv / tq


def _avg_buy_price_grid_only(state: Dict) -> Optional[float]:
    """Ortalama alım: yalnız kapanmış grid fill fiyatları (qty-ağırlıklı VWAP)."""
    h = state.get("buy_history") or []
    grid_h = [x for x in h if x.get("grid_index") is not None]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(_f(x.get("qty")) * _f(x.get("price")) for x in grid_h)
    return tv / tq


def _sell_qty_from_history(state: Dict, idx: int) -> Optional[float]:
    for h in state.get("sell_history") or []:
        if isinstance(h, dict) and int(h.get("grid_index") or -1) == idx:
            q = _f(h.get("qty"))
            if q > 0:
                return q
    return None


def _buy_usd_from_history(state: Dict, idx: int) -> Optional[float]:
    for h in state.get("buy_history") or []:
        if isinstance(h, dict) and int(h.get("grid_index") or -1) == idx:
            q = _f(h.get("qty"))
            p = _f(h.get("execution_price") or h.get("price"))
            if q > 0 and p > 0:
                return q * p
    return None


def _planned_sell_base_qty_display(
    state: Dict[str, Any],
    cfg_obj: Any,
    idx: int,
    price: float,
    base_bal: float,
) -> Optional[float]:
    """UI: tur başı planlanan satış miktarı; gerçekleşince sell_history qty (sabit gösterim)."""
    hist_q = _sell_qty_from_history(state, idx)
    if hist_q is not None:
        return hist_q
    try:
        from app.botengine.strategies.dca_grid_trailing import _float as strat_float
    except Exception:
        return None
    sell_grids = getattr(cfg_obj, "sell_grids", None) or []
    if idx >= len(sell_grids):
        return None
    g = sell_grids[idx]
    pct = strat_float(g.get("sell_qty_pct_of_base") or g.get("qty_pct"), 10.0) / 100.0
    ref_base = _f(state.get("grid_reference_base") or 0)
    if ref_base <= 0:
        ref_base = base_bal
    tb = state.get("target_budgets")
    buffer = strat_float(getattr(cfg_obj, "available_quote_buffer_pct", 0.005), 0.005)
    if isinstance(tb, dict) and price and price > 0:
        target_base = strat_float(tb.get("target_base_usdt"), 0)
        if target_base > 0:
            cap_base = (target_base / price) * (1.0 - buffer)
            ref_base = min(ref_base, cap_base)
    q = ref_base * pct
    return q if q > 0 else None


def _planned_reentry_usd_display(state: Dict[str, Any], quote_bal: float) -> Optional[float]:
    """Kar alım: planlanan USDT (sell_history proceeds cap, motor ile uyumlu)."""
    for h in state.get("buy_history") or []:
        if isinstance(h, dict) and str(h.get("reason") or "") == "trail_reentry_buy":
            q = _f(h.get("qty"))
            p = _f(h.get("price"))
            if q > 0 and p > 0:
                return round(q * p, 2)
    sell_h = state.get("sell_history") or []
    total = sum(_f(x.get("qty")) * _f(x.get("price")) for x in sell_h if isinstance(x, dict))
    if total <= 0:
        return None
    qb = _f(quote_bal)
    cap = min(qb, total) if qb > 0 else total
    return round(cap, 2) if cap > 0 else None


def _planned_profit_exit_base_qty_display(state: Dict[str, Any], base_bal: float) -> Optional[float]:
    """Kar satış: planlanan base miktarı (buy_history toplamı cap, motor ile uyumlu)."""
    for h in state.get("sell_history") or []:
        if isinstance(h, dict) and str(h.get("reason") or "") == "trail_profit_sell":
            q = _f(h.get("qty"))
            if q > 0:
                return round(q, 8)
    buy_h = state.get("buy_history") or []
    total_q = sum(_f(x.get("qty")) for x in buy_h if isinstance(x, dict))
    if total_q <= 0:
        return None
    bb = _f(base_bal)
    q = min(bb, total_q) if bb > 0 else total_q
    return round(q, 8) if q > 0 else None


def _planned_buy_usd_display(
    state: Dict[str, Any],
    cfg_obj: Any,
    idx: int,
    quote_bal: float,
) -> Optional[float]:
    """UI: tur başı planlanan alım tutarı; gerçekleşince buy_history notional (sabit gösterim)."""
    hist_usd = _buy_usd_from_history(state, idx)
    if hist_usd is not None:
        return hist_usd
    try:
        from app.botengine.strategies.dca_grid_trailing import (
            _float as strat_float,
            _quote_ref_for_buy_grid,
        )
    except Exception:
        return None
    buy_grids = getattr(cfg_obj, "buy_grids", None) or []
    if idx >= len(buy_grids):
        return None
    g = buy_grids[idx]
    pct = strat_float(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"), 10.0) / 100.0
    ref = _quote_ref_for_buy_grid(state, cfg_obj, quote_bal)
    q = ref * pct
    return q if q > 0 else None


def compute_grid_profit_view(
    state: Dict[str, Any],
    config: Dict[str, Any],
    price: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns (grid_points, profit_points, meta).
    grid_points: [ { type, i, trigger_price, fired, trigger_hit_price, anchor, execution_price, active } ]
    Tetik fiyatları tur başında (referans) ile hesaplanıp sabit kalır. Tepe/dip ve gerçekleşme tetikten sonra hareketlidir.
    meta: ref_display (ref > 0), ref_available (bool).
    """
    grid_points: List[Dict[str, Any]] = []
    profit_points: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}

    sell_grids = config.get("sell_grids") or config.get("up", {}).get("grids") or []
    buy_grids = config.get("buy_grids") or config.get("down", {}).get("grids") or []
    if not sell_grids and not buy_grids:
        return grid_points, profit_points, meta

    ref = _f(state.get("reference_price"))
    ref_available = ref > 0
    if ref_available:
        meta["ref_display"] = round(ref, 4)
    meta["ref_available"] = ref_available
    sell_trail = _f(config.get("sell_trigger_trailing_pct") or (config.get("up") or {}).get("trail_pct"), 0.3)
    buy_trail = _f(config.get("buy_trigger_trailing_pct") or (config.get("down") or {}).get("trail_pct"), 0.3)
    reentry_drop = _f(config.get("profit_reentry_drop_pct") or (config.get("profit") or {}).get("rebuy_trigger_pct"), 1.0)
    reentry_rise = _f(config.get("profit_reentry_rise_pct") or (config.get("profit") or {}).get("rebuy_trail_pct"), 0.3)
    exit_rise = _f(config.get("profit_exit_rise_pct") or (config.get("profit") or {}).get("resell_trigger_pct"), 1.0)
    exit_drop = _f(config.get("profit_exit_drop_pct") or (config.get("profit") or {}).get("resell_trail_pct"), 0.3)

    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    cycle_side = state.get("cycle_grid_side")
    if cycle_side not in ("SELL", "BUY"):
        cycle_side = None
    meta["cycle_grid_side"] = cycle_side
    sell_grids_enabled = cycle_side != "BUY"
    buy_grids_enabled = cycle_side != "SELL"
    trigger_sell = state.get("sell_grid_trigger_price") or []
    trigger_buy = state.get("buy_grid_trigger_price") or []
    sell_peak = state.get("sell_grid_peak_price") or []
    buy_trough = state.get("buy_grid_trough_price") or []
    sell_fill_price = state.get("sell_grid_fill_price") or []
    buy_fill_price = state.get("buy_grid_fill_price") or []
    mode = state.get("mode") or "IDLE"
    trail_anchor = _f(state.get("trail_anchor_price"))
    trail_sell_idx = state.get("_trail_sell_grid_index", -1)
    trail_buy_idx = state.get("_trail_buy_grid_index", -1)

    sell_hist = state.get("sell_history") or []
    buy_hist = state.get("buy_history") or []
    if not isinstance(sell_fired, list):
        sell_fired = []
    if not isinstance(buy_fired, list):
        buy_fired = []
    active = bool(sell_hist or buy_hist or any(sell_fired) or any(buy_fired))

    cfg_obj = None
    quote_bal = _f(state.get("quote_balance"))
    base_bal = _f(state.get("base_balance"))
    try:
        from app.botengine.models import DcaGridTrailingConfig
        from app.botengine.strategies.dca_grid_trailing import _quote_ref_for_buy_grid
        cfg_obj = DcaGridTrailingConfig(config)
        quote_pool = _quote_ref_for_buy_grid(state, cfg_obj, quote_bal)
        if quote_pool > 0:
            meta["quote_pool_usd"] = round(quote_pool, 2)
    except Exception:
        cfg_obj = None
        quote_pool = 0.0

    def _pct(g: Dict, key: str, alt: str) -> float:
        return _f(g.get(key) or g.get(alt))

    for i, g in enumerate(sell_grids):
        pct = _pct(g, "sell_grid_pct", "trigger_pct")
        raw_qty = _f(g.get("sell_qty_pct_of_base") or g.get("qty_pct"))
        qty_pct = raw_qty * 100.0 if 0 < raw_qty <= 1 else raw_qty  # 0-1 ise 0-100'e çevir (gösterim)
        fired = bool(sell_fired[i]) if i < len(sell_fired) else False
        trigger_hit = trigger_sell[i] if i < len(trigger_sell) else None
        th_num = _f(trigger_hit) if trigger_hit is not None else None
        calc_trigger = round(ref * (1 + pct / 100.0), 4) if ref_available else None
        trigger_price = calc_trigger
        if trigger_price is None and fired and th_num is not None:
            trigger_price = round(th_num, 4)
        anchor: Optional[float] = None
        execution_price: Optional[float] = None
        triggered_trailing = (not fired) and (th_num is not None)
        if fired or triggered_trailing:
            if fired:
                # Tamamlanan grid: sadece state'teki saklı değerler, canlı price/trail_anchor kullanılmaz
                if i < len(sell_fill_price) and sell_fill_price[i] is not None:
                    execution_price = _f(sell_fill_price[i])
                    anchor = _f(sell_peak[i]) if i < len(sell_peak) and sell_peak[i] is not None else execution_price
                elif i < len(sell_peak) and sell_peak[i] is not None:
                    anchor = _f(sell_peak[i])
                    execution_price = anchor * (1 - sell_trail / 100.0)
                elif th_num is not None:
                    anchor = th_num
                    execution_price = anchor * (1 - sell_trail / 100.0)
            else:
                if i < len(sell_peak) and sell_peak[i] is not None:
                    anchor = _f(sell_peak[i])
                elif th_num is not None:
                    anchor = th_num
                if anchor is not None:
                    execution_price = anchor * (1 - sell_trail / 100.0)
        planned_base_qty = None
        if cfg_obj is not None:
            planned_base_qty = _planned_sell_base_qty_display(state, cfg_obj, i, price, base_bal)
        grid_points.append({
            "type": "sell",
            "i": i,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": round(th_num, 4) if th_num is not None else None,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "execution_price": round(execution_price, 4) if execution_price is not None else None,
            "active": active,
            "enabled": sell_grids_enabled or fired,
            "disabled": not sell_grids_enabled and not fired,
            "qty_pct": round(qty_pct, 1) if qty_pct else None,
            "planned_base_qty": round(planned_base_qty, 8) if planned_base_qty else None,
        })

    for j, g in enumerate(buy_grids):
        pct = _pct(g, "buy_grid_pct", "trigger_pct")
        raw_qty = _f(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"))
        qty_pct = raw_qty * 100.0 if 0 < raw_qty <= 1 else raw_qty  # 0-1 ise 0-100'e çevir (gösterim)
        fired = bool(buy_fired[j]) if j < len(buy_fired) else False
        trigger_hit = trigger_buy[j] if j < len(trigger_buy) else None
        th_num = _f(trigger_hit) if trigger_hit is not None else None
        calc_trigger = round(ref * (1 - pct / 100.0), 4) if ref_available else None
        trigger_price = calc_trigger
        if trigger_price is None and fired and th_num is not None:
            trigger_price = round(th_num, 4)
        anchor = None
        execution_price = None
        triggered_trailing = (not fired) and (th_num is not None)
        if fired or triggered_trailing:
            if fired:
                # Tamamlanan grid: sadece state'teki saklı değerler, canlı price/trail_anchor kullanılmaz
                if j < len(buy_fill_price) and buy_fill_price[j] is not None:
                    execution_price = _f(buy_fill_price[j])
                    anchor = _f(buy_trough[j]) if j < len(buy_trough) and buy_trough[j] is not None else execution_price
                elif j < len(buy_trough) and buy_trough[j] is not None:
                    anchor = _f(buy_trough[j])
                    execution_price = anchor * (1 + buy_trail / 100.0)
                elif th_num is not None:
                    anchor = th_num
                    execution_price = anchor * (1 + buy_trail / 100.0)
            else:
                if j < len(buy_trough) and buy_trough[j] is not None:
                    anchor = _f(buy_trough[j])
                elif th_num is not None:
                    anchor = th_num
                if anchor is not None:
                    execution_price = anchor * (1 + buy_trail / 100.0)
        planned_usd = None
        if cfg_obj is not None:
            planned_usd = _planned_buy_usd_display(state, cfg_obj, j, quote_bal)
        grid_points.append({
            "type": "buy",
            "i": j,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": round(th_num, 4) if th_num is not None else None,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "execution_price": round(execution_price, 4) if execution_price is not None else None,
            "active": active,
            "enabled": buy_grids_enabled or fired,
            "disabled": not buy_grids_enabled and not fired,
            "qty_pct": round(qty_pct, 1) if qty_pct else None,
            "planned_usd": round(planned_usd, 2) if planned_usd else None,
        })

    avg_sell_grid = _avg_sell_price_grid_only(state)
    avg_buy_grid = _avg_buy_price_grid_only(state)
    if avg_sell_grid is not None:
        meta["avg_sell_grid"] = round(avg_sell_grid, 4)
    if avg_buy_grid is not None:
        meta["avg_buy_grid"] = round(avg_buy_grid, 4)
    reentry_done = bool(state.get("_reentry_done"))
    profit_exit_done = bool(state.get("_profit_exit_done"))
    quote_bal = _f(state.get("quote_balance") or 0)
    base_bal = _f(state.get("base_balance") or 0)

    reentry_trigger_hit = mode == "TRAIL_REENTRY_BUY"
    profit_exit_trigger_hit = mode == "TRAIL_PROFIT_SELL"

    if cycle_side == "SELL" and sell_hist and not reentry_done and avg_sell_grid and avg_sell_grid > 0:
        trigger = avg_sell_grid * (1 - reentry_drop / 100.0)
        if reentry_trigger_hit and trail_anchor > 0:
            anchor = trail_anchor
        elif reentry_trigger_hit:
            anchor = min(_f(price), trigger) if _f(price) > 0 else trigger
        else:
            anchor = None
        execution = (anchor * (1 + reentry_rise / 100.0)) if anchor is not None else None
        status = "tamamlandi" if reentry_done else ("tetiklendi" if reentry_trigger_hit else "bekliyor")
        planned_reentry_usd = _planned_reentry_usd_display(state, quote_bal)
        profit_points.append({
            "type": "reentry",
            "trigger_price": round(trigger, 4),
            "average_cost": round(avg_sell_grid, 4) if avg_sell_grid else None,
            "profit_pct": round(reentry_drop, 2),
            "planned_quote_usd": planned_reentry_usd,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "dip": round(anchor, 4) if (reentry_trigger_hit and anchor is not None) else None,
            "tepe": None,
            "execution_price": round(execution, 4) if execution is not None else None,
            "trigger_hit": reentry_trigger_hit,
            "status": status,
            "active": True,
            "enabled": True,
        })

    if cycle_side == "BUY" and buy_hist and not profit_exit_done and avg_buy_grid and avg_buy_grid > 0:
        trigger = avg_buy_grid * (1 + exit_rise / 100.0)
        if profit_exit_trigger_hit and trail_anchor > 0:
            anchor = trail_anchor
        elif profit_exit_trigger_hit:
            anchor = max(_f(price), trigger) if _f(price) > 0 else trigger
        else:
            anchor = None
        execution = (anchor * (1 - exit_drop / 100.0)) if anchor is not None else None
        status = "tamamlandi" if profit_exit_done else ("tetiklendi" if profit_exit_trigger_hit else "bekliyor")
        planned_exit_base = _planned_profit_exit_base_qty_display(state, base_bal)
        profit_points.append({
            "type": "profit_exit",
            "trigger_price": round(trigger, 4),
            "average_cost": round(avg_buy_grid, 4) if avg_buy_grid else None,
            "profit_pct": round(exit_rise, 2),
            "planned_base_qty": planned_exit_base,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "tepe": round(anchor, 4) if (profit_exit_trigger_hit and anchor is not None) else None,
            "dip": None,
            "execution_price": round(execution, 4) if execution is not None else None,
            "trigger_hit": profit_exit_trigger_hit,
            "status": status,
            "active": True,
            "enabled": True,
        })

    if cycle_side is None:
        meta["cycle_side_pending"] = True

    return grid_points, profit_points, meta


def compute_trdca_grid_view(
    state: Dict[str, Any],
    raw: Dict[str, Any],
    basket_price: float,
    current_usd: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    TRDCA DCA grid view: portföy değeri (basket) referans alınarak tetik noktaları.
    trigger/anchor/execution basket biriminde (USD). notional_usdt = sabit $ tutar.
    Returns (grid_points, profit_points, meta).
    """
    grid_points: List[Dict[str, Any]] = []
    profit_points: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}

    dca = raw.get("dca") or {}
    weights = dca.get("coin_weights") or {}
    if not weights:
        return grid_points, profit_points, meta

    grid_up = dca.get("grid_up_levels_pct") or [1.0, 2.0, 3.0]
    grid_down = dca.get("grid_down_levels_pct") or [1.0, 2.0, 3.0]
    up_notional = dca.get("grid_up_notional_usdt") or [200, 200, 200]
    down_notional = dca.get("grid_down_notional_usdt") or [200, 200, 200]
    up_notional_pct = dca.get("grid_up_notional_pct")  # Önceden belirlenen yüzde (UI'dan)
    down_notional_pct = dca.get("grid_down_notional_pct")
    sell_trail = _f(dca.get("sell_trail_back_pct"), 0.8) / 100.0
    buy_trail = _f(dca.get("buy_trail_up_pct"), 0.8) / 100.0

    # Referans portföy: bot kurulurken kullanılan bakiye. Yüzde = notional / initial_capital * 100 (veya config'teki notional_pct)
    initial_capital = _f(raw.get("initial_capital_usdt") or raw.get("bot_budget_usdt"), 0)

    dca_state = state.get("dca") or {}
    anchor = _f(state.get("anchor_price"))
    if anchor <= 0:
        anchor = basket_price if basket_price > 0 else current_usd
    if anchor <= 0:
        return grid_points, profit_points, meta

    meta["ref_display"] = round(anchor, 2)
    meta["ref_available"] = True
    meta["is_trdca"] = True
    meta["current_basket"] = round(basket_price, 2) if basket_price > 0 else None

    up_consumed = list(dca_state.get("grid_up_consumed") or []) + [False] * (len(grid_up) - len(dca_state.get("grid_up_consumed") or []))
    down_consumed = list(dca_state.get("grid_down_consumed") or []) + [False] * (len(grid_down) - len(dca_state.get("grid_down_consumed") or []))
    armed = dca_state.get("armed") or {}
    armed_type = armed.get("type") or "NONE"
    armed_idx = armed.get("level_idx")
    armed_peak_trough = _f(armed.get("peak_or_trough"))
    vwap_sell = dca_state.get("vwap_sell")
    vwap_buy = dca_state.get("vwap_buy")

    for i in range(len(grid_up)):
        pct = _f(grid_up[i])
        notional = up_notional[i] if i < len(up_notional) else 200
        fired = bool(up_consumed[i]) if i < len(up_consumed) else False
        trigger_price = round(anchor * (1 + pct / 100.0), 2)
        anchor_val: Optional[float] = None
        execution_price: Optional[float] = None
        if fired:
            exec_basket = (vwap_sell.get("price") if isinstance(vwap_sell, dict) else None) if vwap_sell else None
            if exec_basket and exec_basket > 0:
                execution_price = round(exec_basket * (1 - sell_trail), 2)
                anchor_val = round(exec_basket, 2)
            else:
                anchor_val = trigger_price
                execution_price = round(anchor_val * (1 - sell_trail), 2)
        elif armed_type == "UP_SELL" and armed_idx == i and armed_peak_trough > 0:
            anchor_val = max(armed_peak_trough, basket_price)
            execution_price = round(anchor_val * (1 - sell_trail), 2)
        npct = _f(up_notional_pct[i]) if up_notional_pct and i < len(up_notional_pct) else None
        if npct is None and initial_capital > 0:
            npct = round(notional * 100.0 / initial_capital, 2)
        grid_points.append({
            "type": "sell",
            "i": i,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": trigger_price if fired else None,
            "anchor": round(anchor_val, 2) if anchor_val is not None else None,
            "execution_price": execution_price,
            "active": True,
            "qty_pct": None,
            "notional_usdt": notional,
            "notional_pct": npct,
        })

    for j in range(len(grid_down)):
        pct = _f(grid_down[j])
        notional = down_notional[j] if j < len(down_notional) else 200
        fired = bool(down_consumed[j]) if j < len(down_consumed) else False
        trigger_price = round(anchor * (1 - pct / 100.0), 2)
        anchor_val: Optional[float] = None
        execution_price: Optional[float] = None
        if fired:
            exec_basket = (vwap_buy.get("price") if isinstance(vwap_buy, dict) else None) if vwap_buy else None
            if exec_basket and exec_basket > 0:
                execution_price = round(exec_basket * (1 + buy_trail), 2)
                anchor_val = round(exec_basket, 2)
            else:
                anchor_val = trigger_price
                execution_price = round(anchor_val * (1 + buy_trail), 2)
        elif armed_type == "DOWN_BUY" and armed_idx == j and armed_peak_trough > 0:
            anchor_val = min(armed_peak_trough, basket_price)
            execution_price = round(anchor_val * (1 + buy_trail), 2)
        npct = _f(down_notional_pct[j]) if down_notional_pct and j < len(down_notional_pct) else None
        if npct is None and initial_capital > 0:
            npct = round(notional * 100.0 / initial_capital, 2)
        grid_points.append({
            "type": "buy",
            "i": j,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": trigger_price if fired else None,
            "anchor": round(anchor_val, 2) if anchor_val is not None else None,
            "execution_price": execution_price,
            "active": True,
            "qty_pct": None,
            "notional_usdt": notional,
            "notional_pct": npct,
        })

    post_sell = dca.get("post_sell") or {}
    post_buy = dca.get("post_buy") or {}
    dip_trigger = _f(post_sell.get("dip_trigger_pct"), 2) / 100.0
    dip_trail = _f(post_sell.get("dip_trail_up_pct"), 0.8) / 100.0
    profit_trigger = _f(post_buy.get("profit_trigger_pct"), 2) / 100.0
    profit_trail = _f(post_buy.get("profit_sell_trail_back_pct"), 0.8) / 100.0
    dip_notional = _f(post_sell.get("dip_buy_notional_usdt"), 200)
    profit_notional = _f(post_buy.get("profit_sell_notional_usdt"), 200)

    vp_sell = _f(vwap_sell.get("price")) if vwap_sell and isinstance(vwap_sell, dict) else 0.0
    vp_buy = _f(vwap_buy.get("price")) if vwap_buy and isinstance(vwap_buy, dict) else 0.0

    # Kar alım (Re-entry): grid satıştan sonra portföy düşünce tetik, dip + trail ile alım
    if vp_sell > 0:
        trigger = round(vp_sell * (1 - dip_trigger), 2)
        peak_trough = armed_peak_trough if armed_peak_trough > 0 else basket_price
        anchor_val = min(peak_trough, basket_price)
        execution = round(anchor_val * (1 + dip_trail), 2)
        profit_points.append({
            "type": "reentry",
            "trigger_price": trigger,
            "average_cost": round(vp_sell, 2),
            "profit_pct": round(dip_trigger * 100, 2),
            "anchor": round(anchor_val, 2),
            "dip": round(anchor_val, 2),
            "tepe": None,
            "execution_price": execution,
            "trigger_hit": basket_price >= anchor_val * (1 + dip_trail),
            "status": "tetiklendi" if armed_type == "POSTSELL_DIP" else "bekliyor",
            "active": True,
            "notional_usdt": dip_notional,
        })
    elif basket_price > 0:
        trigger = round(basket_price * (1 - dip_trigger), 2)
        execution = round(basket_price * (1 + dip_trail), 2)
        profit_points.append({
            "type": "reentry",
            "trigger_price": trigger,
            "average_cost": None,
            "profit_pct": round(dip_trigger * 100, 2),
            "anchor": round(basket_price, 2),
            "dip": None,
            "tepe": None,
            "execution_price": execution,
            "trigger_hit": False,
            "status": "bekliyor",
            "active": True,
            "notional_usdt": dip_notional,
        })

    # Kar satış (Profit exit): grid alıştan sonra portföy yükselince tetik, tepe - trail ile satış
    if vp_buy > 0:
        trigger = round(vp_buy * (1 + profit_trigger), 2)
        peak_trough = armed_peak_trough if armed_peak_trough > 0 else basket_price
        anchor_val = max(peak_trough, basket_price)
        execution = round(anchor_val * (1 - profit_trail), 2)
        profit_points.append({
            "type": "profit_exit",
            "trigger_price": trigger,
            "average_cost": round(vp_buy, 2),
            "profit_pct": round(profit_trigger * 100, 2),
            "anchor": round(anchor_val, 2),
            "tepe": round(anchor_val, 2),
            "dip": None,
            "execution_price": execution,
            "trigger_hit": basket_price <= anchor_val * (1 - profit_trail),
            "status": "tetiklendi" if armed_type == "POSTBUY_PEAK" else "bekliyor",
            "active": True,
            "notional_usdt": profit_notional,
        })
    elif basket_price > 0:
        trigger = round(basket_price * (1 + profit_trigger), 2)
        execution = round(basket_price * (1 - profit_trail), 2)
        profit_points.append({
            "type": "profit_exit",
            "trigger_price": trigger,
            "average_cost": None,
            "profit_pct": round(profit_trigger * 100, 2),
            "anchor": round(basket_price, 2),
            "tepe": None,
            "dip": None,
            "execution_price": execution,
            "trigger_hit": False,
            "status": "bekliyor",
            "active": True,
            "notional_usdt": profit_notional,
        })

    return grid_points, profit_points, meta
