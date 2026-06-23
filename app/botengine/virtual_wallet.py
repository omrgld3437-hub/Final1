"""
Per-bot virtual sub-wallet (virtual_base, virtual_quote) for budget check and fill updates.
Source of truth for "can this bot afford this order"; updated after each fill.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from sqlalchemy import text
from app.services.bot_status_utils import is_bot_capital_locked

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Epsilon for float comparison (SELL: allow when available >= required within precision)
_BASE_QTY_EPSILON = 1e-10

# Quote suffixes for symbol parsing (e.g. BTCUSDT -> base=BTC, quote=USDT)
_QUOTE_SUFFIXES = ("USDT", "BUSD", "FDUSD", "USDC")


def _symbol_to_base_quote(symbol: str) -> Tuple[str, str]:
    """Return (base_asset, quote_asset) for symbol e.g. BTCUSDT -> (BTC, USDT)."""
    s = (symbol or "").upper().strip()
    for q in _QUOTE_SUFFIXES:
        if s.endswith(q):
            base = (s[: -len(q)] or "").strip()
            return (base, q) if base else ("", q)
    return (s, "USDT")


def _purge_orphan_virtual_wallets(
    db: "Session", account_id: Optional[int] = None
) -> None:
    """Silinmiş botlara ait virtual_wallet satırlarını temizle (UI bot kilitli hayalet)."""
    try:
        if account_id is not None:
            db.execute(
                text("""
                    DELETE FROM bot_virtual_wallet
                    WHERE account_id = :aid
                      AND bot_id NOT IN (SELECT id FROM bots)
                """),
                {"aid": account_id},
            )
        else:
            db.execute(
                text(
                    "DELETE FROM bot_virtual_wallet WHERE bot_id NOT IN (SELECT id FROM bots)"
                ),
            )
        db.commit()
    except Exception as e:
        logger.warning(
            "purge_orphan_virtual_wallets failed account_id=%s: %s", account_id, e
        )
        try:
            db.rollback()
        except Exception:
            pass


def get_bot_locked_balances_for_account(
    db: "Session", account_id: int
) -> Dict[str, float]:
    """
    Return total bot-locked balance per asset for this account (bileşik dahil).
    virtual_wallet her tick sonunda state ile senkronize olduğu için güncel (bileşik) bakiye döner.
    Bu varlıklar bot tarafından kullanıldığı için harici alım/satımda kullanılamaz (available = free - bot_locked).
    Returns e.g. {"BTC": 0.5, "USDT": 1000.0}.
    Tablo boş veya senkron değilse bot_engine_state'ten fallback (çalışan botların base/quote bakiyesi).
    """
    _purge_orphan_virtual_wallets(db, account_id)
    out: Dict[str, float] = {}
    try:
        rows = db.execute(
            text("""
                SELECT w.symbol, w.virtual_base, w.virtual_quote, b.status
                FROM bot_virtual_wallet w
                INNER JOIN bots b ON b.id = w.bot_id
                WHERE w.account_id = :aid
            """),
            {"aid": account_id},
        ).fetchall()
        for row in rows or []:
            sym = (row[0] or "").strip()
            vb = float(row[1] or 0)
            vq = float(row[2] or 0)
            if not is_bot_capital_locked(row[3] if len(row) > 3 else ""):
                continue
            if not sym:
                continue
            base_asset, quote_asset = _symbol_to_base_quote(sym)
            if base_asset and vb > 0:
                out[base_asset] = out.get(base_asset, 0.0) + vb
            if quote_asset and vq > 0:
                out[quote_asset] = out.get(quote_asset, 0.0) + vq
    except Exception as e:
        logger.warning("get_bot_locked_balances_for_account error: %s", e)

    # Tablo boşsa veya toplam 0 ise: sermayesi hâlâ ayrılmış botların state'inden bot kilitli hesapla.
    if not out or sum(out.values()) <= 0:
        try:
            from app.db.models import Bot
            from app.botengine.state_store import load_state

            bots = (
                db.query(Bot)
                .filter(Bot.account_id == account_id)
                .all()
            )
            for bot in bots or []:
                if not is_bot_capital_locked(getattr(bot, "status", None)):
                    continue
                sym = (bot.symbol or "").strip().upper()
                if not sym or sym == "MULTI":
                    continue
                state = load_state(db, bot.id)
                if not state:
                    continue
                base_b = float(state.get("base_balance") or 0)
                quote_b = float(state.get("quote_balance") or 0)
                if base_b <= 0 and quote_b <= 0:
                    continue
                base_asset, quote_asset = _symbol_to_base_quote(sym)
                if base_asset and base_b > 0:
                    out[base_asset] = out.get(base_asset, 0.0) + base_b
                if quote_asset and quote_b > 0:
                    out[quote_asset] = out.get(quote_asset, 0.0) + quote_b
        except Exception as e:
            logger.debug("get_bot_locked_balances fallback from state: %s", e)
    return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_virtual_wallet(
    db: "Session",
    bot_id: int,
    symbol: str,
) -> Tuple[float, float]:
    """Return (virtual_base, virtual_quote). (0, 0) if no row."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    row = db.execute(
        text("""
            SELECT virtual_base, virtual_quote FROM bot_virtual_wallet
            WHERE bot_id = :bid AND symbol = :sym
        """),
        {"bid": bot_id, "sym": symbol},
    ).fetchone()
    if not row:
        return (0.0, 0.0)
    return (float(row[0] or 0), float(row[1] or 0))


def get_virtual_wallet_or_none(
    db: "Session",
    bot_id: int,
    symbol: str,
) -> Optional[Tuple[float, float]]:
    """Return (virtual_base, virtual_quote) if row exists, else None. Use for PnL total_usd = base*price + quote."""
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    try:
        row = db.execute(
            text("""
                SELECT virtual_base, virtual_quote FROM bot_virtual_wallet
                WHERE bot_id = :bid AND symbol = :sym
            """),
            {"bid": bot_id, "sym": symbol},
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return (float(row[0] or 0), float(row[1] or 0))


def ensure_virtual_wallet(
    db: "Session",
    bot_id: int,
    account_id: int,
    symbol: str,
    initial_quote_usdt: float,
) -> None:
    """
    Ensure a row exists. If not, insert with virtual_quote=initial_quote_usdt, virtual_base=0.
    If row exists, do not overwrite (idempotent init).
    """
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    row = db.execute(
        text("SELECT 1 FROM bot_virtual_wallet WHERE bot_id = :bid AND symbol = :sym"),
        {"bid": bot_id, "sym": symbol},
    ).fetchone()
    if row:
        return
    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        text("""
            INSERT INTO bot_virtual_wallet (bot_id, account_id, symbol, virtual_base, virtual_quote, updated_at)
            VALUES (:bid, :aid, :sym, 0, :quote, :upd)
        """),
        {
            "bid": bot_id,
            "aid": account_id,
            "sym": symbol,
            "quote": max(0.0, float(initial_quote_usdt)),
            "upd": now_s,
        },
    )
    db.commit()


def update_virtual_after_fill(
    db: "Session",
    bot_id: int,
    symbol: str,
    side: str,
    fill_qty: float,
    quote_value: float,
    fee_usdt: float = 0.0,
) -> None:
    """
    Update virtual wallet after a fill. BUY: base += fill_qty, quote -= quote_value + fee.
    SELL: base -= fill_qty, quote += quote_value - fee.
    """
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    side = (side or "").upper()
    fill_qty = max(0.0, float(fill_qty))
    quote_value = max(0.0, float(quote_value))
    fee_usdt = max(0.0, float(fee_usdt))

    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if side == "BUY":
        db.execute(
            text("""
                UPDATE bot_virtual_wallet
                SET virtual_base = virtual_base + :qty,
                    virtual_quote = MAX(0, virtual_quote - :quote - :fee),
                    updated_at = :upd
                WHERE bot_id = :bid AND symbol = :sym
            """),
            {
                "bid": bot_id,
                "sym": symbol,
                "qty": fill_qty,
                "quote": quote_value,
                "fee": fee_usdt,
                "upd": now_s,
            },
        )
    else:
        db.execute(
            text("""
                UPDATE bot_virtual_wallet
                SET virtual_base = MAX(0, virtual_base - :qty),
                    virtual_quote = virtual_quote + :quote - :fee,
                    updated_at = :upd
                WHERE bot_id = :bid AND symbol = :sym
            """),
            {
                "bid": bot_id,
                "sym": symbol,
                "qty": fill_qty,
                "quote": quote_value,
                "fee": fee_usdt,
                "upd": now_s,
            },
        )
    db.commit()


def sync_virtual_wallet_from_state(
    db: "Session",
    bot_id: int,
    account_id: int,
    symbol: str,
    base_balance: float,
    quote_balance: float,
) -> None:
    """
    Sync virtual_wallet row to match state base/quote (state is source of truth after apply_fill).
    Call after save_state so next tick does not overwrite state with stale virtual_wallet.
    """
    symbol = (symbol or "").upper().strip() or "BTCUSDT"
    base_balance = max(0.0, float(base_balance))
    quote_balance = max(0.0, float(quote_balance))
    now_s = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        text("""
            UPDATE bot_virtual_wallet
            SET virtual_base = :vb, virtual_quote = :vq, updated_at = :upd
            WHERE bot_id = :bid AND symbol = :sym
        """),
        {
            "bid": bot_id,
            "sym": symbol,
            "vb": base_balance,
            "vq": quote_balance,
            "upd": now_s,
        },
    )
    db.commit()


def check_virtual_budget(
    db: "Session",
    bot_id: int,
    symbol: str,
    side: str,
    quote_amount: float,
    base_qty: float,
    price: float,
    fee_buffer_pct: float = 0.002,
) -> Tuple[bool, str, Optional[float], Optional[float]]:
    """
    Check if virtual wallet has sufficient funds for the proposed order.
    Wallet is read once inside this function. Returns (ok, reason, required, available).
    When ok: (True, "", None, None). When not ok: required/available are set for SKIP payload.
    BUY: quote_amount + fee_buffer <= virtual_quote.
    SELL: base_qty <= virtual_base.
    """
    base, quote = get_virtual_wallet(db, bot_id, symbol)
    side = (side or "").upper()
    if side == "BUY":
        # Usable budget = virtual_quote * (1 - fee_buffer); required = quote_amount. Epsilon for float precision.
        available_quote = quote * (1.0 - fee_buffer_pct)
        if quote_amount > available_quote + _BASE_QTY_EPSILON:
            return (False, "INSUFFICIENT_VIRTUAL_FUNDS", quote_amount, available_quote)
        return (True, "", None, None)
    if side == "SELL":
        # Float precision: allow sell when available >= required - epsilon (avoids VIRTUAL_BUDGET_INSUFFICIENT when values differ only by rounding)
        if base < base_qty - _BASE_QTY_EPSILON:
            return (False, "INSUFFICIENT_VIRTUAL_FUNDS", base_qty, base)
        return (True, "", None, None)
    return (False, "INVALID_SIDE", None, None)
