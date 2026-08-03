"""
Test hesabı manuel spot paper: kullanılabilir USDT havuzundan hayali al/sat.
Durum: .run/test_spot_paper/{account_id}.json (yalnızca test hesabı).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PAPER_ROOT = _PROJECT_ROOT / ".run" / "test_spot_paper"
_lock_guard = threading.Lock()
_account_locks: Dict[int, threading.Lock] = {}

STABLE_ASSETS = frozenset({"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"})


def _account_lock(account_id: int) -> threading.Lock:
    with _lock_guard:
        if account_id not in _account_locks:
            _account_locks[account_id] = threading.Lock()
        return _account_locks[account_id]


def _paper_path(account_id: int) -> Path:
    return _PAPER_ROOT / f"{int(account_id)}.json"


def _empty_state() -> Dict[str, Any]:
    return {"manual_base": {}, "usdt_delta": 0.0, "pending_orders": []}


def load_paper_state(account_id: int) -> Dict[str, Any]:
    path = _paper_path(account_id)
    if not path.is_file():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _empty_state()
        manual = (
            raw.get("manual_base") if isinstance(raw.get("manual_base"), dict) else {}
        )
        manual_clean = {
            str(k).upper(): max(0.0, float(v or 0))
            for k, v in manual.items()
            if k and float(v or 0) > 0
        }
        return {
            "manual_base": manual_clean,
            "usdt_delta": float(raw.get("usdt_delta") or 0),
            "pending_orders": [
                row
                for row in (raw.get("pending_orders") or [])
                if isinstance(row, dict) and str(row.get("status") or "") == "NEW"
            ],
        }
    except Exception as e:
        logger.warning("test_spot_paper load failed account_id=%s: %s", account_id, e)
        return _empty_state()


def save_paper_state(account_id: int, state: Dict[str, Any]) -> None:
    _PAPER_ROOT.mkdir(parents=True, exist_ok=True)
    path = _paper_path(account_id)
    payload = {
        "manual_base": state.get("manual_base") or {},
        "usdt_delta": round(float(state.get("usdt_delta") or 0), 8),
        "pending_orders": state.get("pending_orders") or [],
        "updated_at": time.time(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _find_asset_row(wallet: Dict[str, Any], asset: str) -> Optional[Dict[str, Any]]:
    sym = (asset or "").strip().upper()
    for a in wallet.get("assets") or []:
        if isinstance(a, dict) and (a.get("asset") or "").strip().upper() == sym:
            return a
    return None


def _usdt_available_from_wallet(wallet: Dict[str, Any]) -> float:
    row = _find_asset_row(wallet, "USDT")
    if not row:
        return max(0.0, float(wallet.get("available_usd") or 0))
    av = row.get("available")
    if av is not None:
        return max(0.0, float(av))
    return max(0.0, float(row.get("available_usd") or 0))


def apply_paper_to_test_wallet(wallet: Dict[str, Any], account_id: int) -> None:
    """build_test_account_wallet sonrası: manuel base + USDT delta uygula."""
    if not wallet:
        return
    state = load_paper_state(account_id)
    usdt_delta = float(state.get("usdt_delta") or 0)
    manual_base: Dict[str, float] = state.get("manual_base") or {}
    pending_orders = state.get("pending_orders") or []

    usdt_row = _find_asset_row(wallet, "USDT")
    if usdt_row is not None and abs(usdt_delta) > 1e-12:
        av = max(0.0, float(usdt_row.get("available") or 0) + usdt_delta)
        bl = float(usdt_row.get("bot_locked") or 0)
        locked = float(usdt_row.get("locked") or 0)
        usdt_row["available"] = round(av, 8)
        usdt_row["available_usd"] = round(av, 2)
        usdt_row["free"] = round(av + bl, 8)
        usdt_row["free_usd"] = round(av + bl, 2)
        total_qty = round(av + bl + locked, 8)
        usdt_row["total"] = total_qty
        usdt_row["total_usd"] = round(total_qty, 2)
        usdt_row["value_usd"] = usdt_row["total_usd"]

    for asset, qty in manual_base.items():
        asset = (asset or "").upper()
        if not asset or asset in STABLE_ASSETS or qty <= 0:
            continue
        row = _find_asset_row(wallet, asset)
        if row is None:
            wallet.setdefault("assets", []).append(
                {
                    "asset": asset,
                    "free": round(qty, 8),
                    "locked": 0.0,
                    "bot_locked": 0.0,
                    "available": round(qty, 8),
                    "available_usd": None,
                    "total": round(qty, 8),
                }
            )
            continue
        manual_av = round(float(manual_base.get(asset, 0) or 0), 8)
        bot_bl = float(row.get("bot_locked") or 0)
        locked = float(row.get("locked") or 0)
        row["available"] = round(manual_av, 8)
        row["free"] = round(manual_av + bot_bl, 8)
        row["total"] = round(manual_av + bot_bl + locked, 8)

    # LIMIT emirler Binance gibi serbest bakiyeden düşülür ve emir kilidine
    # taşınır. Bot kilidi ile emir kilidi birbirinden ayrı kalır.
    for order in pending_orders:
        if not isinstance(order, dict) or str(order.get("status") or "") != "NEW":
            continue
        symbol = str(order.get("symbol") or "").upper()
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        side = str(order.get("side") or "").upper()
        qty = max(0.0, float(order.get("origQty") or 0))
        limit_price = max(0.0, float(order.get("price") or 0))
        if side == "BUY":
            reserve_asset = "USDT"
            reserve_qty = qty * limit_price
        else:
            reserve_asset = base
            reserve_qty = qty
        row = _find_asset_row(wallet, reserve_asset)
        if row is None or reserve_qty <= 0:
            continue
        available_qty = max(0.0, float(row.get("available") or 0))
        reserved = min(available_qty, reserve_qty)
        row["available"] = round(max(0.0, available_qty - reserved), 8)
        row["free"] = round(max(0.0, float(row.get("free") or 0) - reserved), 8)
        row["locked"] = round(float(row.get("locked") or 0) + reserved, 8)
        row["total"] = round(
            float(row.get("free") or 0) + float(row.get("locked") or 0),
            8,
        )
        if reserve_asset in STABLE_ASSETS:
            row["available_usd"] = round(float(row.get("available") or 0), 2)
            row["locked_usd"] = round(float(row.get("locked") or 0), 2)

    av_usd = 0.0
    bl_usd = 0.0
    for a in wallet.get("assets") or []:
        if not isinstance(a, dict):
            continue
        asset_sym = (a.get("asset") or "").upper()
        if asset_sym in STABLE_ASSETS:
            av_usd += float(a.get("available") or 0)
            bl_usd += float(a.get("bot_locked") or 0)
        else:
            from app.services.wallet_display import (
                wallet_prices_map_from_datahub,
                resolve_asset_price_usd,
            )

            prices = wallet_prices_map_from_datahub()
            av_val, _ = resolve_asset_price_usd(
                asset_sym, float(a.get("available") or 0), prices
            )
            bl_val, _ = resolve_asset_price_usd(
                asset_sym, float(a.get("bot_locked") or 0), prices
            )
            if av_val:
                av_usd += av_val
            if bl_val:
                bl_usd += bl_val
    wallet["available_usd"] = round(av_usd, 2)
    wallet["bot_locked_usd"] = round(bl_usd, 2)
    wallet["locked_usd"] = round(
        sum(
            float(row.get("locked_usd") or 0)
            for row in (wallet.get("assets") or [])
            if isinstance(row, dict)
        ),
        2,
    )


def spot_balances_from_wallet(
    wallet: Dict[str, Any],
    base_asset: str,
    quote_asset: str,
    bot_locked: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    bot_locked = bot_locked or {}
    base = (base_asset or "").upper()
    quote = (quote_asset or "USDT").upper()
    base_row = _find_asset_row(wallet, base)
    quote_row = _find_asset_row(wallet, quote)
    base_free = float(base_row.get("free") or 0) if base_row else 0.0
    quote_free = float(quote_row.get("free") or 0) if quote_row else 0.0
    base_bl = float(bot_locked.get(base, 0) or 0)
    quote_bl = float(bot_locked.get(quote, 0) or 0)
    base_av = (
        float(base_row.get("available") or 0)
        if base_row
        else max(0.0, base_free - base_bl)
    )
    quote_av = (
        float(quote_row.get("available") or 0)
        if quote_row
        else max(0.0, quote_free - quote_bl)
    )
    return {
        "base_balance": base_free,
        "quote_balance": quote_free,
        "base_available": max(0.0, base_av),
        "quote_available": max(0.0, quote_av),
        "base_locked": base_bl,
        "quote_locked": quote_bl,
    }


def _resolve_price(symbol: str) -> float:
    from app.services.market_data import get_price_map_flat

    sym = (symbol or "").upper()
    base = sym.replace("USDT", "") if sym.endswith("USDT") else sym
    prices = get_price_map_flat() or {}
    px = prices.get(sym) or prices.get(f"{base}USDT")
    if px is not None and float(px) > 0:
        return float(px)
    raise ValueError(f"Fiyat bulunamadı: {symbol}")


def _quantize_step(qty: float, step: str = "0.00000001") -> float:
    try:
        d = Decimal(str(qty)).quantize(Decimal(str(step)), rounding=ROUND_DOWN)
        return float(d)
    except Exception:
        return round(float(qty), 8)


def list_test_paper_open_orders(
    account_id: int, symbol: Optional[str] = None
) -> list[Dict[str, Any]]:
    sym = (symbol or "").strip().upper()
    rows = load_paper_state(account_id).get("pending_orders") or []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("status") or "") == "NEW"
        and (not sym or str(row.get("symbol") or "").upper() == sym)
    ]


def cancel_test_paper_order(
    account_id: int, symbol: str, order_id: int
) -> Dict[str, Any]:
    sym = (symbol or "").strip().upper()
    with _account_lock(account_id):
        state = load_paper_state(account_id)
        rows = state.get("pending_orders") or []
        found = None
        kept = []
        for row in rows:
            matches = (
                isinstance(row, dict)
                and str(row.get("symbol") or "").upper() == sym
                and str(row.get("orderId")) == str(order_id)
                and str(row.get("status") or "") == "NEW"
            )
            if matches:
                found = dict(row)
            else:
                kept.append(row)
        if found is None:
            raise ValueError("ORDER_NOT_FOUND")
        state["pending_orders"] = kept
        save_paper_state(account_id, state)
    found["status"] = "CANCELED"
    return found


def _apply_paper_fill_to_state(
    state: Dict[str, Any],
    symbol: str,
    side: str,
    fill_resp: Dict[str, Any],
) -> None:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    manual_base: Dict[str, float] = dict(state.get("manual_base") or {})
    executed_qty = float(fill_resp.get("executedQty") or 0)
    executed_quote = float(fill_resp.get("cummulativeQuoteQty") or 0)
    if side == "BUY":
        manual_base[base] = round(
            float(manual_base.get(base, 0) or 0) + executed_qty, 8
        )
        state["usdt_delta"] = round(
            float(state.get("usdt_delta") or 0) - executed_quote, 8
        )
    else:
        available = float(manual_base.get(base, 0) or 0)
        remaining = round(max(0.0, available - executed_qty), 8)
        if remaining <= 1e-12:
            manual_base.pop(base, None)
        else:
            manual_base[base] = remaining
        state["usdt_delta"] = round(
            float(state.get("usdt_delta") or 0) + executed_quote, 8
        )
    state["manual_base"] = manual_base


def process_test_paper_limit_orders(
    account_id: int, prices: Optional[Dict[str, float]] = None
) -> list[Dict[str, Any]]:
    """Fill crossed GTC LIMIT orders at their limit price on the next price observation."""
    from app.services.test_simulation import build_paper_market_fill

    filled: list[Dict[str, Any]] = []
    with _account_lock(account_id):
        state = load_paper_state(account_id)
        pending = state.get("pending_orders") or []
        kept = []
        for order in pending:
            if not isinstance(order, dict) or str(order.get("status") or "") != "NEW":
                continue
            sym = str(order.get("symbol") or "").upper()
            try:
                market_price = float((prices or {}).get(sym) or _resolve_price(sym))
                limit_price = float(order.get("price") or 0)
                qty = float(order.get("origQty") or 0)
            except (TypeError, ValueError):
                kept.append(order)
                continue
            side = str(order.get("side") or "").upper()
            crossed = (side == "BUY" and market_price <= limit_price) or (
                side == "SELL" and market_price >= limit_price
            )
            if not crossed:
                kept.append(order)
                continue
            if side == "BUY":
                fill = build_paper_market_fill(
                    sym,
                    "BUY",
                    quote_qty=qty * limit_price,
                    mid_price=limit_price,
                    slippage_bps=0,
                )
            else:
                fill = build_paper_market_fill(
                    sym,
                    "SELL",
                    base_qty=qty,
                    mid_price=limit_price,
                    slippage_bps=0,
                )
            fill["orderId"] = order.get("orderId")
            fill["side"] = side
            fill["type"] = "LIMIT"
            fill["price"] = str(limit_price)
            _apply_paper_fill_to_state(state, sym, side, fill)
            filled.append(fill)
        state["pending_orders"] = kept
        if filled:
            save_paper_state(account_id, state)
    return filled


def execute_test_paper_order(
    db: Any,
    account_id: int,
    symbol: str,
    side: str,
    order_type: str,
    quantity: Optional[float] = None,
    quote_order_qty: Optional[float] = None,
    price: Optional[float] = None,
) -> Dict[str, Any]:
    from app.services.test_account import is_test_account
    from app.services.wallet_display import build_test_account_wallet

    if not is_test_account(account_id, db):
        raise ValueError("NOT_TEST_ACCOUNT")

    sym = (symbol or "").upper()
    side_u = (side or "").upper()
    type_u = (order_type or "MARKET").upper()
    if type_u not in ("MARKET", "LIMIT"):
        raise ValueError("Desteklenmeyen emir tipi")

    base = sym.replace("USDT", "") if sym.endswith("USDT") else sym
    if not base or base in STABLE_ASSETS:
        raise ValueError("Geçersiz sembol")

    market_px = _resolve_price(sym)
    px = float(price) if type_u == "LIMIT" and price and float(price) > 0 else market_px
    if px <= 0:
        raise ValueError("Fiyat geçersiz")

    from app.services.test_simulation import (
        build_paper_market_fill,
        sync_paper_order_latency,
    )

    sync_paper_order_latency()
    fill_resp: Dict[str, Any] = {}

    with _account_lock(account_id):
        wallet = build_test_account_wallet(account_id, db)
        quote_av = _usdt_available_from_wallet(wallet)
        state = load_paper_state(account_id)
        manual_base: Dict[str, float] = dict(state.get("manual_base") or {})

        if type_u == "LIMIT":
            qty_in = float(quantity or 0)
            if qty_in <= 0:
                raise ValueError("Miktar giriniz")
            if side_u == "BUY":
                required_quote = qty_in * px
                if required_quote > quote_av + 1e-8:
                    raise ValueError(
                        f"Yetersiz kullanılabilir USDT (mevcut: {quote_av:.2f}, gerekli: {required_quote:.2f})"
                    )
            elif side_u == "SELL":
                available_base = float(
                    (_find_asset_row(wallet, base) or {}).get("available") or 0
                )
                if qty_in > available_base + 1e-12:
                    raise ValueError(
                        f"Yetersiz satılabilir {base} (mevcut: {available_base:.8f})"
                    )
            else:
                raise ValueError("Geçersiz side")
            marketable = (side_u == "BUY" and market_px <= px) or (
                side_u == "SELL" and market_px >= px
            )
            if not marketable:
                order_id = int(time.time() * 1000)
                pending_order = {
                    "orderId": order_id,
                    "symbol": sym,
                    "side": side_u,
                    "type": "LIMIT",
                    "price": str(px),
                    "origQty": str(_quantize_step(qty_in)),
                    "executedQty": "0",
                    "cummulativeQuoteQty": "0",
                    "status": "NEW",
                    "timeInForce": "GTC",
                    "time": order_id,
                    "paper": True,
                }
                state.setdefault("pending_orders", []).append(pending_order)
                save_paper_state(account_id, state)
                return pending_order

        if side_u == "BUY":
            quote_in = float(quote_order_qty or 0)
            if quote_in <= 0 and quantity and float(quantity) > 0:
                effective_buy_price = (
                    min(market_px, px) if type_u == "LIMIT" else px
                )
                quote_in = float(quantity) * effective_buy_price
            if quote_in <= 0:
                raise ValueError("Tutar giriniz")
            if quote_in > quote_av + 1e-8:
                raise ValueError(
                    f"Yetersiz kullanılabilir USDT (mevcut: {quote_av:.2f}, gerekli: {quote_in:.2f})"
                )
            fill_resp = build_paper_market_fill(
                sym,
                "BUY",
                quote_qty=quote_in,
                mid_price=min(market_px, px) if type_u == "LIMIT" else px,
                slippage_bps=0 if type_u == "LIMIT" else 5,
            )
            executed_qty = float(fill_resp["executedQty"])
            executed_quote = float(fill_resp["cummulativeQuoteQty"])
            if executed_qty <= 0:
                raise ValueError("Miktar çok küçük")
            manual_base[base] = round(
                float(manual_base.get(base, 0) or 0) + executed_qty, 8
            )
            state["usdt_delta"] = round(
                float(state.get("usdt_delta") or 0) - executed_quote, 8
            )
        elif side_u == "SELL":
            qty_in = float(quantity or 0)
            if qty_in <= 0:
                raise ValueError("Miktar giriniz")
            avail_base = float(manual_base.get(base, 0) or 0)
            if qty_in > avail_base + 1e-12:
                raise ValueError(
                    f"Yetersiz satılabilir {base} (mevcut: {avail_base:.8f})"
                )
            sell_qty = _quantize_step(min(qty_in, avail_base))
            fill_resp = build_paper_market_fill(
                sym,
                "SELL",
                base_qty=sell_qty,
                mid_price=max(market_px, px) if type_u == "LIMIT" else px,
                slippage_bps=0 if type_u == "LIMIT" else 5,
            )
            executed_qty = float(fill_resp["executedQty"])
            executed_quote = float(fill_resp["cummulativeQuoteQty"])
            new_base = round(avail_base - executed_qty, 8)
            if new_base <= 1e-12:
                manual_base.pop(base, None)
            else:
                manual_base[base] = new_base
            state["usdt_delta"] = round(
                float(state.get("usdt_delta") or 0) + executed_quote, 8
            )
        else:
            raise ValueError("Geçersiz side")

        state["manual_base"] = manual_base
        save_paper_state(account_id, state)
        px = float((fill_resp.get("fills") or [{}])[0].get("price") or px)

    order_id = int(time.time() * 1000)
    return {
        "orderId": order_id,
        "symbol": sym,
        "side": side_u,
        "type": type_u,
        "executedQty": str(executed_qty),
        "cummulativeQuoteQty": str(executed_quote),
        "price": str(px),
        "status": "FILLED",
        "paper": True,
        "fills": fill_resp.get("fills") or [],
    }
