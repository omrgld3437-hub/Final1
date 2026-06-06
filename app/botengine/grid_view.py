"""
Compute grid points and profit points for bot detail UI.
Uses state + config + current price. Peak/trough/execution update with live price.
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
    """Ortalama maliyet sadece grid satışlarıyla (reentry/profit_exit hariç). execution_price varsa onu kullan (gerçekleşme fiyatı)."""
    h = state.get("sell_history") or []
    grid_h = [x for x in h if x.get("grid_index") is not None]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(
        _f(x.get("qty")) * _f(x.get("execution_price") or x.get("price")) for x in grid_h
    )
    return tv / tq


def _avg_buy_price_grid_only(state: Dict) -> Optional[float]:
    """Ortalama maliyet sadece grid alışlarıyla (reentry/initial hariç). execution_price varsa onu kullan (gerçekleşme fiyatı)."""
    h = state.get("buy_history") or []
    grid_h = [x for x in h if x.get("grid_index") is not None]
    if not grid_h:
        return None
    tq = sum(_f(x.get("qty")) for x in grid_h)
    if tq <= 0:
        return None
    tv = sum(
        _f(x.get("qty")) * _f(x.get("execution_price") or x.get("price")) for x in grid_h
    )
    return tv / tq


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

    def _pct(g: Dict, key: str, alt: str) -> float:
        return _f(g.get(key) or g.get(alt))

    for i, g in enumerate(sell_grids):
        pct = _pct(g, "sell_grid_pct", "trigger_pct")
        raw_qty = _f(g.get("sell_qty_pct_of_base") or g.get("qty_pct"))
        qty_pct = raw_qty * 100.0 if 0 < raw_qty <= 1 else raw_qty  # 0-1 ise 0-100'e çevir (gösterim)
        fired = bool(sell_fired[i]) if i < len(sell_fired) else False
        trigger_hit = trigger_sell[i] if i < len(trigger_sell) else None
        th_num = _f(trigger_hit) if trigger_hit is not None else None
        # Tamamlanan grid: tetik fiyatı tetik anındaki fiyata dondur (güncellenmez)
        if fired and th_num is not None:
            trigger_price = round(th_num, 4)
        else:
            trigger_price = round(ref * (1 + pct / 100.0), 4) if ref_available else None
        anchor: Optional[float] = None
        execution_price: Optional[float] = None
        if fired or (mode == "TRAIL_SELL_GRID" and trail_sell_idx == i):
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
                anchor = trail_anchor if trail_anchor > 0 else (th_num or _f(price))
                anchor = max(anchor, _f(price))
                execution_price = anchor * (1 - sell_trail / 100.0)
        grid_points.append({
            "type": "sell",
            "i": i,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": round(th_num, 4) if th_num is not None else None,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "execution_price": round(execution_price, 4) if execution_price is not None else None,
            "active": active,
            "qty_pct": round(qty_pct, 1) if qty_pct else None,
        })

    for j, g in enumerate(buy_grids):
        pct = _pct(g, "buy_grid_pct", "trigger_pct")
        raw_qty = _f(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"))
        qty_pct = raw_qty * 100.0 if 0 < raw_qty <= 1 else raw_qty  # 0-1 ise 0-100'e çevir (gösterim)
        fired = bool(buy_fired[j]) if j < len(buy_fired) else False
        trigger_hit = trigger_buy[j] if j < len(trigger_buy) else None
        th_num = _f(trigger_hit) if trigger_hit is not None else None
        # Tamamlanan grid: tetik fiyatı tetik anındaki fiyata dondur (güncellenmez)
        if fired and th_num is not None:
            trigger_price = round(th_num, 4)
        else:
            trigger_price = round(ref * (1 - pct / 100.0), 4) if ref_available else None
        anchor = None
        execution_price = None
        if fired or (mode == "TRAIL_BUY_GRID" and trail_buy_idx == j):
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
                anchor = trail_anchor if trail_anchor > 0 else (th_num or _f(price))
                anchor = min(anchor, _f(price))
                execution_price = anchor * (1 + buy_trail / 100.0)
        grid_points.append({
            "type": "buy",
            "i": j,
            "trigger_price": trigger_price,
            "fired": fired,
            "trigger_hit_price": round(th_num, 4) if th_num is not None else None,
            "anchor": round(anchor, 4) if anchor is not None else None,
            "execution_price": round(execution_price, 4) if execution_price is not None else None,
            "active": active,
            "qty_pct": round(qty_pct, 1) if qty_pct else None,
        })

    avg_sell = _avg_sell_price(state)
    avg_buy = _avg_buy_price(state)
    avg_sell_grid = _avg_sell_price_grid_only(state)
    avg_buy_grid = _avg_buy_price_grid_only(state)
    reentry_done = bool(state.get("_reentry_done"))
    profit_exit_done = bool(state.get("_profit_exit_done"))

    reentry_trigger_hit = mode == "TRAIL_REENTRY_BUY"
    profit_exit_trigger_hit = mode == "TRAIL_PROFIT_SELL"

    if active and sell_hist and not reentry_done and avg_sell and avg_sell > 0:
        trigger = avg_sell * (1 - reentry_drop / 100.0)
        anchor = trail_anchor if trail_anchor > 0 and reentry_trigger_hit else min(price, trigger)
        anchor = min(anchor, price)
        execution = anchor * (1 + reentry_rise / 100.0)
        status = "tamamlandi" if reentry_done else ("tetiklendi" if reentry_trigger_hit else "bekliyor")
        profit_points.append({
            "type": "reentry",
            "trigger_price": round(trigger, 4),
            "average_cost": round(avg_sell_grid, 4) if avg_sell_grid else None,
            "profit_pct": round(reentry_drop, 2),
            "anchor": round(anchor, 4),
            "dip": round(anchor, 4) if reentry_trigger_hit else None,
            "tepe": None,
            "execution_price": round(execution, 4),
            "trigger_hit": reentry_trigger_hit,
            "status": status,
            "active": True,
        })

    if active and buy_hist and not profit_exit_done and avg_buy and avg_buy > 0:
        trigger = avg_buy * (1 + exit_rise / 100.0)
        anchor = trail_anchor if trail_anchor > 0 and profit_exit_trigger_hit else max(price, trigger)
        anchor = max(anchor, price)
        execution = anchor * (1 - exit_drop / 100.0)
        status = "tamamlandi" if profit_exit_done else ("tetiklendi" if profit_exit_trigger_hit else "bekliyor")
        profit_points.append({
            "type": "profit_exit",
            "trigger_price": round(trigger, 4),
            "average_cost": round(avg_buy_grid, 4) if avg_buy_grid else None,
            "profit_pct": round(exit_rise, 2),
            "anchor": round(anchor, 4),
            "tepe": round(anchor, 4) if profit_exit_trigger_hit else None,
            "dip": None,
            "execution_price": round(execution, 4),
            "trigger_hit": profit_exit_trigger_hit,
            "status": status,
            "active": True,
        })

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
