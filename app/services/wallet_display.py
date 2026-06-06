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
    from app.services.bot_status_utils import is_bot_running
    from app.services.pnl_service import PnlService

    total = 0.0
    try:
        bots = [
            b
            for b in db.query(Bot).filter(Bot.account_id == int(account_id)).all()
            if is_bot_running(getattr(b, "status", None))
        ]
    except Exception:
        return 0.0
    for bot in bots or []:
        try:
            cfg = json.loads(getattr(bot, "config_json", None) or "{}")
            initial_usd = float(
                cfg.get("initial_capital_usdt")
                or cfg.get("budget_usd")
                or cfg.get("bot_budget_quote")
                or 0
            )
        except Exception:
            initial_usd = 0.0
        state = load_state(db, bot.id) or {}
        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, int(account_id))
        try:
            total += float(
                compute_bot_equity_usd(
                    db, bot, state, pnl_data, initial_usd=initial_usd
                )
                or 0
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


def resolve_asset_price_usd(
    asset: str, qty: float, prices: Dict[str, float]
) -> Tuple[Optional[float], Optional[float]]:
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
    try:
        from app.services.market_data import get_price

        for quote in ("USDT", "BUSD", "FDUSD", "USDC"):
            sym = f"{asset}{quote}"
            px = get_price(sym)
            if px is not None and float(px) > 0:
                p = float(px)
                return (qty * p, p)
    except Exception:
        pass
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
            "bot_locked_usd": round(bot_locked_val, 2)
            if value_usd is not None
            else None,
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
    from app.services.bot_status_utils import is_bot_running

    total = 0.0
    try:
        bots = [
            b
            for b in db.query(Bot).filter(Bot.account_id == int(account_id)).all()
            if is_bot_running(getattr(b, "status", None))
        ]
    except Exception:
        return 0.0
    for bot in bots or []:
        try:
            raw = json.loads(getattr(bot, "config_json", None) or "{}")
            total += float(
                raw.get("initial_capital_usdt") or raw.get("budget_usd") or 0
            )
        except Exception:
            continue
    return round(max(0.0, total), 2)


def build_test_account_wallet(account_id: int, db: Any) -> Dict[str, Any]:
    """Test paper cüzdanı — /api/binance/wallet ve dashboard snapshot ile aynı sözleşme."""
    from datetime import datetime, timezone
    import time

    from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account

    if not is_test_account(account_id, db):
        return {}
    prices = wallet_prices_map_from_datahub()
    bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
    from app.api.routes import _wallet_response

    balances = [{"asset": "USDT", "free": str(TEST_PAPER_BALANCE_USDT), "locked": "0"}]
    out = _wallet_response(account_id, balances, prices, bot_locked=bot_locked)
    apply_test_wallet_equity_totals(out, db, account_id)
    try:
        from app.services.test_spot_paper import apply_paper_to_test_wallet

        apply_paper_to_test_wallet(out, account_id)
    except Exception:
        pass
    out["keys_configured"] = True
    ts_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out["ts"] = ts_iso
    out["ts_ms"] = int(time.time() * 1000)
    out["data_status"] = "fresh"
    enrich_test_wallet_dashboard_kpi(out, db, account_id)
    return out


def apply_test_wallet_equity_totals(
    wallet: Dict[str, Any], db: Any, account_id: int
) -> None:
    """
    Test paper: satır bazlı bot_locked / available / total_usd; strip = satır toplamları.
    USDT (kullanılabilir + bot kilitli) + base (ör. ETH bot kilitli) satırları; toplam = 10k paper.
    Strip ve USDT Toplam qty: çalışan botların config bütçesi (initial_capital_usdt); equity/mark-to-market kullanılmaz.
    """
    from app.services.test_account import is_test_account, TEST_PAPER_BALANCE_USDT
    from app.botengine.virtual_wallet import get_bot_locked_balances_for_account

    if not wallet or not is_test_account(account_id, db):
        return

    prices = wallet_prices_map_from_datahub()
    bot_locked = get_bot_locked_balances_for_account(db, account_id) or {}
    # Test paper: strip ve USDT satırı config bütçesi ile (mark-to-market equity değil — fiyat oynaklığı Toplam qty flicker yapar)
    allocated = _test_running_bots_usdt_budget(db, account_id)
    avail_pool = round(max(0.0, float(TEST_PAPER_BALANCE_USDT) - allocated), 2)

    assets: List[Dict[str, Any]] = wallet.setdefault("assets", [])
    processed: Set[str] = {
        (a.get("asset") or "").strip()
        for a in assets
        if isinstance(a, dict) and (a.get("asset") or "").strip()
    }
    append_bot_only_wallet_asset_rows(assets, processed, bot_locked, prices)

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
        usdt_avail_qty = round(avail_pool, 8)
        usdt_total_qty = round(usdt_avail_qty + usdt_bl_qty + usdt_locked, 8)
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

    usdt_bl_usd_val = float(bot_locked.get("USDT", 0) or 0)
    non_stable_rows = [
        a
        for a in wallet.get("assets") or []
        if isinstance(a, dict) and (a.get("asset") or "").strip() not in STABLE_ASSETS
    ]
    if non_stable_rows and allocated > usdt_bl_usd_val:
        remaining_usd = round(max(0.0, allocated - usdt_bl_usd_val), 2)
        priced: List[Tuple[Dict[str, Any], float]] = []
        for base_row in non_stable_rows:
            asset_sym = (base_row.get("asset") or "").strip()
            bl_qty = float(base_row.get("bot_locked") or 0) or float(
                bot_locked.get(asset_sym, 0) or 0
            )
            bl_usd, px = resolve_asset_price_usd(asset_sym, bl_qty, prices)
            bl_usd = float(bl_usd or 0.0)
            if bl_qty <= 0 and remaining_usd > 0:
                _, px = resolve_asset_price_usd(asset_sym, 1.0, prices)
                if px and px > 0:
                    bl_qty = remaining_usd / len(non_stable_rows) / px
                    bl_usd, _ = resolve_asset_price_usd(asset_sym, bl_qty, prices)
                    bl_usd = float(bl_usd or 0.0)
            priced.append((base_row, bl_usd))
        total_non_stable_usd = sum(x[1] for x in priced)
        for base_row, bl_usd in priced:
            asset_sym = (base_row.get("asset") or "").strip()
            if total_non_stable_usd > 0 and remaining_usd > 0:
                share = (
                    bl_usd / total_non_stable_usd if bl_usd > 0 else 1.0 / len(priced)
                )
                base_bl_usd = round(remaining_usd * share, 2)
            else:
                base_bl_usd = round(bl_usd, 2)
            base_bl_qty = float(base_row.get("bot_locked") or 0) or float(
                bot_locked.get(asset_sym, 0) or 0
            )
            base_row["bot_locked"] = round(base_bl_qty, 8)
            base_row["bot_locked_usd"] = base_bl_usd
            base_row["total_usd"] = base_bl_usd
            base_row["value_usd"] = base_bl_usd
            base_row["available_usd"] = 0.0
            base_row["available"] = 0.0
            base_row["free_usd"] = 0.0
            base_row["free"] = 0.0
            base_row["locked_usd"] = 0.0
            base_row["locked"] = 0.0
            if base_bl_qty <= 0 and base_bl_usd > 0:
                _, px = resolve_asset_price_usd(asset_sym, 1.0, prices)
                if px and px > 0:
                    base_bl_qty = base_bl_usd / px
                    base_row["bot_locked"] = round(base_bl_qty, 8)
            base_row["total"] = round(base_bl_qty, 8) if base_bl_qty > 0 else 0.0
            if base_bl_qty > 0 and base_bl_usd > 0:
                base_row["price_usd"] = round(base_bl_usd / base_bl_qty, 8)

    row_locked = round(
        sum(
            float(a.get("locked_usd") or 0)
            for a in wallet.get("assets") or []
            if isinstance(a, dict)
        ),
        2,
    )
    bot_equity = get_running_bots_equity_usd(db, account_id)
    wallet["bot_locked_usd"] = bot_equity
    wallet["available_usd"] = avail_pool
    wallet["locked_usd"] = row_locked
    wallet["total_usd"] = round(float(TEST_PAPER_BALANCE_USDT), 2)
    wallet["free_usd"] = round(
        sum(
            float(a.get("free_usd") or 0)
            for a in wallet.get("assets") or []
            if isinstance(a, dict)
        ),
        2,
    )


def enrich_test_wallet_dashboard_kpi(
    wallet: Dict[str, Any], db: Any, account_id: int
) -> None:
    """Dashboard KPI strip + admin tile: spot_kpi_total_usd, daily_wallet_pnl_*."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.services.test_account_kpi import (
            compute_test_account_spot_strip_total_usd,
            get_test_daily_spot_ref_for_pnl,
        )

        total, _, bot_eq, _locked = compute_test_account_spot_strip_total_usd(
            wallet, db, account_id
        )
        ref = get_test_daily_spot_ref_for_pnl(account_id, total)
        pnl_usd = round(total - ref, 2)
        pnl_pct = round((pnl_usd / ref * 100.0), 2) if ref > 0 else 0.0
        wallet["spot_kpi_total_usd"] = total
        wallet["daily_wallet_pnl_usd"] = pnl_usd
        wallet["daily_wallet_pnl_pct"] = pnl_pct
        wallet["bot_locked_usd"] = bot_eq
    except Exception as ex:
        logger.debug(
            "enrich_test_wallet_dashboard_kpi account_id=%s: %s", account_id, ex
        )
