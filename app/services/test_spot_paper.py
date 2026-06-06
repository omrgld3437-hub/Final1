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
    return {"manual_base": {}, "usdt_delta": 0.0}


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
    if type_u != "MARKET":
        raise ValueError("Test paper yalnızca MARKET emir destekler")

    base = sym.replace("USDT", "") if sym.endswith("USDT") else sym
    if not base or base in STABLE_ASSETS:
        raise ValueError("Geçersiz sembol")

    px = float(price) if price and float(price) > 0 else _resolve_price(sym)
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

        if side_u == "BUY":
            quote_in = float(quote_order_qty or 0)
            if quote_in <= 0 and quantity and float(quantity) > 0:
                quote_in = float(quantity) * px
            if quote_in <= 0:
                raise ValueError("Tutar giriniz")
            if quote_in > quote_av + 1e-8:
                raise ValueError(
                    f"Yetersiz kullanılabilir USDT (mevcut: {quote_av:.2f}, gerekli: {quote_in:.2f})"
                )
            fill_resp = build_paper_market_fill(
                sym, "BUY", quote_qty=quote_in, mid_price=px
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
                sym, "SELL", base_qty=sell_qty, mid_price=px
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

    order_id = f"test_paper_{int(time.time() * 1000)}"
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
