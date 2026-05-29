"""
Cüzdan tablosu: Binance bakiyesinde olmayan bot-kilitli varlık satırları (test paper + canlı hesap).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

STABLE_ASSETS = frozenset({"USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"})


def get_running_bots_equity_usd(db: Any, account_id: int) -> float:
    """Çalışan botların güncel equity toplamı (test strip bot_locked_usd ile uyumlu)."""
    import json

    from app.db.models import Bot
    from app.botengine.state_store import load_state
    from app.services.bot_equity import compute_bot_equity_usd
    from app.services.pnl_service import PnlService

    total = 0.0
    try:
        bots = (
            db.query(Bot)
            .filter(Bot.account_id == int(account_id), Bot.status == "running")
            .all()
        )
    except Exception:
        return 0.0
    for bot in bots or []:
        try:
            cfg = json.loads(getattr(bot, "config_json", None) or "{}")
            initial_usd = float(
                cfg.get("initial_capital_usdt") or cfg.get("budget_usd") or cfg.get("bot_budget_quote") or 0
            )
        except Exception:
            initial_usd = 0.0
        state = load_state(db, bot.id) or {}
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, int(account_id))
        try:
            total += float(
                compute_bot_equity_usd(db, bot, state, pnl_data, initial_usd=initial_usd) or 0
            )
        except Exception:
            total += float(pnl_data.get("total_usd") or initial_usd or 0)
    return round(max(0.0, total), 2)


def wallet_prices_map_from_datahub() -> Dict[str, float]:
    try:
        from app.services.data_hub import data_hub

        raw = data_hub.get_all_prices() or {}
        return {sym: float(d.get("price") or 0) for sym, d in raw.items() if d}
    except Exception:
        return {}


def resolve_asset_price_usd(asset: str, qty: float, prices: Dict[str, float]) -> Tuple[Optional[float], Optional[float]]:
    """USD değeri ve birim fiyat (qty>0). Fiyat yoksa (None, None)."""
    if qty <= 0:
        return (0.0, None)
    if asset in STABLE_ASSETS:
        return (qty, 1.0)
    for quote in ("USDT", "BUSD", "FDUSD", "USDC"):
        raw = prices.get(f"{asset}{quote}")
        if raw is not None and float(raw) > 0:
            p = float(raw)
            return (qty * p, p)
    raw_inv = prices.get(f"USDT{asset}")
    if raw_inv is not None and float(raw_inv) > 0:
        p = float(raw_inv)
        return (qty / p, p)
    return (None, None)


def append_bot_only_wallet_asset_rows(
    assets: List[Dict[str, Any]],
    processed_assets: Set[str],
    bot_locked: Optional[Dict[str, float]],
    prices: Dict[str, float],
) -> Tuple[float, float]:
    """
    Bot kilitli ama cüzdan bakiyesinde görünmeyen varlıklar (ör. test hesapta ETH).
    Returns (added_total_usd, added_bot_locked_usd).
    """
    added_total = 0.0
    added_bot_locked = 0.0
    if not bot_locked:
        return (0.0, 0.0)
    for asset, qty in bot_locked.items():
        asset = (asset or "").strip()
        qty_f = float(qty or 0)
        if not asset or qty_f <= 0 or asset in processed_assets:
            continue
        value_usd, price_usd = resolve_asset_price_usd(asset, qty_f, prices)
        bot_locked_val = value_usd if value_usd is not None else 0.0
        row: Dict[str, Any] = {
            "asset": asset,
            "free": 0.0,
            "locked": 0.0,
            "total": qty_f,
            "bot_locked": round(qty_f, 8),
            "available": 0.0,
            "price_usd": round(price_usd, 8) if price_usd is not None else None,
            "value_usd": round(bot_locked_val, 2) if value_usd is not None else None,
            "free_usd": 0.0,
            "locked_usd": 0.0,
            "total_usd": round(bot_locked_val, 2) if value_usd is not None else None,
            "bot_locked_usd": round(bot_locked_val, 2) if value_usd is not None else None,
            "available_usd": 0.0,
        }
        assets.append(row)
        processed_assets.add(asset)
        if value_usd is not None:
            added_total += bot_locked_val
            added_bot_locked += bot_locked_val
    return (round(added_total, 2), round(added_bot_locked, 2))


def _test_running_bots_usdt_budget(db: Any, account_id: int) -> float:
    """Çalışan botların USDT başlangıç sermayesi (config initial_capital_usdt / budget_usd)."""
    import json

    from app.db.models import Bot

    total = 0.0
    try:
        bots = (
            db.query(Bot)
            .filter(Bot.account_id == int(account_id), Bot.status == "running")
            .all()
        )
    except Exception:
        return 0.0
    for bot in bots or []:
        try:
            raw = json.loads(getattr(bot, "config_json", None) or "{}")
            total += float(raw.get("initial_capital_usdt") or raw.get("budget_usd") or 0)
        except Exception:
            continue
    return round(max(0.0, total), 2)


def apply_test_wallet_equity_totals(wallet: Dict[str, Any], db: Any, account_id: int) -> None:
    """
    Test paper: satır bazlı bot_locked / available / total_usd; strip = satır toplamları.
    Çift sayım ve USDT satırında equity'nin tamamını bot_locked yapma hatası giderilir.
    """
    from app.services.test_account import is_test_account
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account

    if not wallet or not is_test_account(account_id, db):
        return

    prices = wallet_prices_map_from_datahub()
    bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
    equity = get_running_bots_equity_usd(db, account_id)

    sum_available = 0.0
    sum_bot_locked = 0.0
    sum_total = 0.0
    sum_free = 0.0

    for a in wallet.get("assets") or []:
        if not isinstance(a, dict):
            continue
        asset = (a.get("asset") or "").strip()
        free = float(a.get("free") or 0)
        locked = float(a.get("locked") or 0)
        bl_qty = float(bot_locked.get(asset, 0) or 0)

        if asset in STABLE_ASSETS:
            price = 1.0
            free_usd = free * price
            locked_usd = locked * price
            bl_usd = round(bl_qty * price, 2)
            row_total_usd = round(free_usd + locked_usd + bl_usd, 2)
            av_usd = max(0.0, row_total_usd - bl_usd - locked_usd)
            a["price_usd"] = price
            a["bot_locked"] = round(bl_qty, 8)
            a["available"] = round(max(0.0, free - bl_qty), 8)
            a["bot_locked_usd"] = bl_usd
            a["available_usd"] = round(av_usd, 2)
            a["free_usd"] = round(free_usd, 2)
            a["locked_usd"] = round(locked_usd, 2)
            a["total_usd"] = row_total_usd
            a["value_usd"] = row_total_usd
            a["total"] = round(free + locked + bl_qty, 8)
        else:
            free_usd, price = resolve_asset_price_usd(asset, free, prices)
            free_usd = free_usd if free_usd is not None else 0.0
            bl_usd, _ = resolve_asset_price_usd(asset, bl_qty, prices)
            bl_usd = bl_usd if bl_usd is not None else 0.0
            total_qty = free + locked + bl_qty
            total_val, _ = resolve_asset_price_usd(asset, total_qty, prices)
            total_val = total_val if total_val is not None else (free_usd + bl_usd)
            av_qty = max(0.0, free - bl_qty)
            av_usd = max(0.0, free_usd - bl_usd)
            a["bot_locked"] = round(bl_qty, 8)
            a["available"] = round(av_qty, 8)
            a["total"] = round(total_qty, 8)
            a["bot_locked_usd"] = round(bl_usd, 2)
            a["available_usd"] = round(av_usd, 2)
            a["free_usd"] = round(free_usd, 2)
            a["locked_usd"] = round((locked * price) if price else 0.0, 2)
            a["total_usd"] = round(total_val, 2)
            a["value_usd"] = round(total_val, 2)
            if price:
                a["price_usd"] = round(price, 8)

        sum_available += float(a.get("available_usd") or 0)
        sum_bot_locked += float(a.get("bot_locked_usd") or 0)
        sum_total += float(a.get("total_usd") or 0)
        sum_free += float(a.get("free_usd") or 0)

    from app.services.test_account import TEST_PAPER_BALANCE_USDT

    avail_pool = round(max(0.0, float(TEST_PAPER_BALANCE_USDT) - equity), 2)
    non_stable_rows = [
        a
        for a in wallet.get("assets") or []
        if isinstance(a, dict) and (a.get("asset") or "").strip() not in STABLE_ASSETS
    ]
    usdt_row = None
    for a in wallet.get("assets") or []:
        if not isinstance(a, dict):
            continue
        if (a.get("asset") or "").strip() in STABLE_ASSETS:
            usdt_row = a
            break

    if usdt_row is not None:
        usdt_locked = round(float(usdt_row.get("locked") or 0), 8)
        usdt_bl_qty = float(bot_locked.get("USDT", 0) or 0)
        usdt_budget = _test_running_bots_usdt_budget(db, account_id)
        if usdt_budget <= 0:
            usdt_budget = round(max(usdt_bl_qty, float(TEST_PAPER_BALANCE_USDT) - equity), 2)
        usdt_avail_qty = round(max(0.0, usdt_budget - usdt_bl_qty), 8)
        usdt_total_qty = round(usdt_budget, 8)
        usdt_bl_usd = round(usdt_bl_qty, 2)
        usdt_avail_usd = round(usdt_avail_qty, 2)
        usdt_locked_usd = round(usdt_locked, 2)
        usdt_deger_usd = round(usdt_total_qty, 2)
        usdt_row["price_usd"] = 1.0
        usdt_row["bot_locked"] = round(usdt_bl_qty, 8)
        usdt_row["bot_locked_usd"] = usdt_bl_usd
        usdt_row["available"] = usdt_avail_qty
        usdt_row["available_usd"] = usdt_avail_usd
        usdt_row["locked"] = usdt_locked
        usdt_row["locked_usd"] = usdt_locked_usd
        usdt_row["free"] = round(usdt_avail_qty + usdt_bl_qty, 8)
        usdt_row["free_usd"] = round(usdt_avail_usd + usdt_bl_usd, 2)
        usdt_row["total"] = usdt_total_qty
        usdt_row["total_usd"] = usdt_deger_usd
        usdt_row["value_usd"] = usdt_deger_usd
    elif avail_pool > 0:
        wallet.setdefault("assets", []).insert(
            0,
            {
                "asset": "USDT",
                "free": avail_pool,
                "locked": 0.0,
                "total": avail_pool,
                "bot_locked": 0.0,
                "available": avail_pool,
                "price_usd": 1.0,
                "free_usd": avail_pool,
                "locked_usd": 0.0,
                "total_usd": avail_pool,
                "value_usd": avail_pool,
                "bot_locked_usd": 0.0,
                "available_usd": avail_pool,
            },
        )

    row_bl = round(
        sum(float(a.get("bot_locked_usd") or 0) for a in wallet.get("assets") or [] if isinstance(a, dict)),
        2,
    )
    row_av = round(
        sum(float(a.get("available_usd") or 0) for a in wallet.get("assets") or [] if isinstance(a, dict)),
        2,
    )
    row_locked = round(
        sum(float(a.get("locked_usd") or 0) for a in wallet.get("assets") or [] if isinstance(a, dict)),
        2,
    )
    wallet["bot_locked_usd"] = row_bl
    wallet["available_usd"] = row_av
    wallet["locked_usd"] = row_locked
    wallet["total_usd"] = round(row_av + row_bl + row_locked, 2)
    if wallet["total_usd"] <= 0:
        wallet["total_usd"] = round(float(TEST_PAPER_BALANCE_USDT), 2)
    wallet["free_usd"] = round(
        sum(float(a.get("free_usd") or 0) for a in wallet.get("assets") or [] if isinstance(a, dict)),
        2,
    )
    wallet["locked_usd"] = round(
        sum(float(a.get("locked_usd") or 0) for a in wallet.get("assets") or [] if isinstance(a, dict)),
        2,
    )
