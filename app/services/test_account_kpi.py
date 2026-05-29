"""
Test hesabı dashboard KPI strip ile admin tile aynı kaynak:
TOPLAM SPOT = USDT kullanılabilir + çalışan bot equity + kilitli (canlı fiyat).
Günlük değişim = strip toplamı − TR günü açılış referansı (sunucu, dashboard localStorage ile uyumlu).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REF_ROOT = _PROJECT_ROOT / ".run" / "test_daily_spot_ref"


def _ref_path(account_id: int) -> Path:
    return _REF_ROOT / f"{int(account_id)}.json"


def _load_test_daily_spot_ref(account_id: int) -> Optional[Dict[str, Any]]:
    path = _ref_path(account_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception as e:
        logger.debug("test_daily_spot_ref load account_id=%s: %s", account_id, e)
        return None


def _save_test_daily_spot_ref(account_id: int, stored: Dict[str, Any]) -> None:
    path = _ref_path(account_id)
    try:
        _REF_ROOT.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        logger.warning("test_daily_spot_ref save account_id=%s: %s", account_id, e)


def set_test_daily_spot_ref_usd(
    account_id: int,
    ref_usd: float,
    date: Optional[str] = None,
    *,
    source: str = "dashboard",
) -> None:
    """Dashboard localStorage → sunucu; admin günlük değişim aynı referansı okur."""
    from app.utils.tz_utils import turkey_today_date_str

    ref = float(ref_usd or 0)
    if not account_id or ref <= 0:
        return
    today = (date or "").strip() or turkey_today_date_str()
    _save_test_daily_spot_ref(
        account_id,
        {"date": today, "ref_usd": round(ref, 8), "set_at": time.time(), "source": source},
    )


def get_test_daily_spot_ref_for_pnl(account_id: int, current_total: float) -> float:
    """Günlük değişim referansı: dashboard sync varsa dokunma; yoksa ilk toplam."""
    from app.utils.tz_utils import turkey_today_date_str

    today = turkey_today_date_str()
    stored = _load_test_daily_spot_ref(account_id)
    if stored and stored.get("date") == today:
        ref = float(stored.get("ref_usd") or 0)
        if ref > 0:
            return ref
    return get_or_set_test_daily_spot_ref_usd(account_id, current_total)


def get_or_set_test_daily_spot_ref_usd(account_id: int, current_total: float) -> float:
    """TR günü referansı: dashboard sync varsa onu kullan; yoksa ilk sunucu gözlemi."""
    from app.utils.tz_utils import turkey_today_date_str

    total = float(current_total or 0)
    if not account_id:
        return total
    today = turkey_today_date_str()
    stored = _load_test_daily_spot_ref(account_id)
    if stored and stored.get("date") == today:
        ref = float(stored.get("ref_usd") or 0)
        if ref > 0:
            return ref
    if total <= 0:
        return 0.0
    stored = {"date": today, "ref_usd": round(total, 8), "set_at": time.time(), "source": "server_seed"}
    _save_test_daily_spot_ref(account_id, stored)
    return float(stored["ref_usd"])


def compute_test_account_spot_strip_total_usd(
    wallet: Dict[str, Any],
    db: Any,
    account_id: int,
) -> Tuple[float, float, float, float]:
    """
    Dashboard kpiCuzdan / testAccountKpiTotalUsd ile uyumlu.
    Returns (total, available_usd, bot_equity_usd, locked_usd).
    """
    from app.services.wallet_display import (
        STABLE_ASSETS,
        get_running_bots_equity_usd,
        wallet_prices_map_from_datahub,
        resolve_asset_price_usd,
    )

    prices = wallet_prices_map_from_datahub()
    avail = 0.0
    locked = 0.0
    usdt_avail = 0.0

    for a in wallet.get("assets") or []:
        if not isinstance(a, dict):
            continue
        asset = (a.get("asset") or "").strip().upper()
        if not asset:
            continue
        av_qty = max(0.0, float(a.get("available") or 0))
        locked_qty = max(0.0, float(a.get("locked") or 0))
        if asset == "USDT" and av_qty > 0:
            usdt_avail = av_qty
        if asset in STABLE_ASSETS:
            if asset != "USDT" and av_qty > 0:
                avail += av_qty
            if locked_qty > 0:
                locked += locked_qty
        else:
            av_usd, _ = resolve_asset_price_usd(asset, av_qty, prices) if av_qty > 0 else (0.0, None)
            if av_usd:
                avail += float(av_usd)
            if locked_qty > 0:
                lk_usd, _ = resolve_asset_price_usd(asset, locked_qty, prices)
                if lk_usd:
                    locked += float(lk_usd)

    if usdt_avail > 0:
        avail = usdt_avail + avail
    elif avail <= 0:
        avail = float(wallet.get("available_usd") or 0)

    bot_eq = get_running_bots_equity_usd(db, account_id)
    if bot_eq <= 0:
        bot_eq = float(wallet.get("bot_locked_usd") or 0)

    total = round(avail + bot_eq + locked, 2)
    return total, round(avail, 2), round(bot_eq, 2), round(locked, 2)


def _running_bots_equity_from_snapshot_bots(bots: list) -> float:
    from app.services.bot_status_utils import is_bot_running

    total = 0.0
    for b in bots or []:
        if not isinstance(b, dict):
            continue
        st = b.get("display_status") or b.get("status") or ""
        if not is_bot_running(st):
            continue
        try:
            cu = float(b.get("current_usd") or 0)
        except (TypeError, ValueError):
            cu = 0.0
        if cu > 0:
            total += cu
    return round(total, 2)


async def compute_test_account_dashboard_spot_kpi_async(account_id: int, db: Any) -> Dict[str, float]:
    """
    Dashboard KPI strip ile aynı:
    USDT kullanılabilir + çalışan bot current_usd (snapshot/live) + kilitli.
    """
    from app.services.wallet_display import build_test_account_wallet, get_running_bots_equity_usd

    wallet = build_test_account_wallet(account_id, db) or {}
    _fallback_total, avail, _fb_bot, locked = compute_test_account_spot_strip_total_usd(
        wallet, db, account_id
    )
    bot_eq = 0.0
    try:
        from app.services.dashboard_snapshot import fetch_bots_and_account_kpis

        bot_raw = await fetch_bots_and_account_kpis(account_id, db)
        if not bot_raw.get("_error"):
            bot_eq = _running_bots_equity_from_snapshot_bots(bot_raw.get("bots") or [])
    except Exception as ex:
        logger.debug("test_spot_kpi fetch_bots account_id=%s: %s", account_id, ex)
    if bot_eq <= 0:
        bot_eq = get_running_bots_equity_usd(db, account_id)
    total = round(avail + bot_eq + locked, 2)
    if total <= 0:
        total = _fallback_total
    ref = get_test_daily_spot_ref_for_pnl(account_id, total)
    pnl_usd = round(total - ref, 2)
    pnl_pct = round((pnl_usd / ref * 100.0), 2) if ref > 0 else 0.0
    return {
        "spot_strip_total_usd": total,
        "available_usd": avail,
        "bot_locked_usd": bot_eq,
        "locked_usd": locked,
        "daily_wallet_pnl_usd": pnl_usd,
        "daily_wallet_pnl_pct": pnl_pct,
        "daily_spot_ref_usd": round(ref, 2),
    }


def compute_test_account_dashboard_spot_kpi(account_id: int, db: Any) -> Dict[str, float]:
    """Sync fallback; admin için compute_test_account_dashboard_spot_kpi_async kullanın."""
    from app.services.wallet_display import build_test_account_wallet, get_running_bots_equity_usd

    wallet = build_test_account_wallet(account_id, db) or {}
    _fallback_total, avail, _, locked = compute_test_account_spot_strip_total_usd(wallet, db, account_id)
    bot_eq = get_running_bots_equity_usd(db, account_id)
    total = round(avail + bot_eq + locked, 2)
    if total <= 0:
        total = _fallback_total
    ref = get_test_daily_spot_ref_for_pnl(account_id, total)
    pnl_usd = round(total - ref, 2)
    pnl_pct = round((pnl_usd / ref * 100.0), 2) if ref > 0 else 0.0
    return {
        "spot_strip_total_usd": total,
        "available_usd": avail,
        "bot_locked_usd": bot_eq,
        "locked_usd": locked,
        "daily_wallet_pnl_usd": pnl_usd,
        "daily_wallet_pnl_pct": pnl_pct,
        "daily_spot_ref_usd": round(ref, 2),
    }
