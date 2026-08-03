"""
Bot equity (USD): single source for dashboard list + bot detail live snapshot.
DCA: base_balance * last_price + quote_balance from engine state.
"""

import math
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.price_hub import price_hub


_MAX_REFERENCE_PRICE_RATIO = 20.0


def display_safe_bot_price(
    price: Any,
    state: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Reject non-finite or obviously mis-scaled market prices for bot equity.

    The engine reference is an accounting anchor, not a live quote.  It is still
    useful as a scale check: a newly received ETH price that is hundreds of
    times above/below the bot's own reference must not explode the card value.
    """
    try:
        candidate = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(candidate) or candidate <= 0:
        return None

    state = state or {}
    anchors = (
        state.get("reference_price"),
        state.get("initial_alloc_price"),
    )
    for raw_anchor in anchors:
        try:
            anchor = float(raw_anchor)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(anchor) or anchor <= 0:
            continue
        ratio = max(candidate, anchor) / min(candidate, anchor)
        if ratio >= _MAX_REFERENCE_PRICE_RATIO:
            return None
    return candidate


def _price_from_datahub(sym_pair: str) -> Optional[float]:
    try:
        from app.services.data_hub import data_hub

        p = data_hub.get_price((sym_pair or "").upper())
        if p is not None and float(p) > 0:
            return float(p)
    except Exception:
        pass
    return None


def get_bot_last_price(
    symbol: str,
    state: Optional[Dict[str, Any]] = None,
    pnl_data: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Match bots_engine /live: price_hub → data_hub → pnl current_price → state reference_price."""
    sym = (symbol or "").strip().upper()
    if sym:
        try:
            p = price_hub.get_price(sym)
            if p is not None and float(p) > 0:
                return float(p)
        except Exception:
            pass
        hub_p = _price_from_datahub(sym)
        if hub_p is not None and hub_p > 0:
            return hub_p
    if pnl_data:
        try:
            cp = float(pnl_data.get("current_price") or 0)
            if cp > 0:
                return cp
        except (TypeError, ValueError):
            pass
    if state:
        try:
            ref = float(state.get("reference_price") or 0)
            if ref > 0:
                return ref
        except (TypeError, ValueError):
            pass
    return None


def compute_bot_equity_usd(
    db: Session,
    bot: Any,
    state: Optional[Dict[str, Any]],
    pnl_data: Optional[Dict[str, Any]] = None,
    *,
    initial_usd: float = 0.0,
) -> float:
    """
    Live bot bakiyesi (USD). Tek sembol DCA: state base/quote + last price.
    MULTI/TRDCA: falls back to pnl_data total_usd or initial_usd.
    """
    import json

    state = state or {}
    sym = (getattr(bot, "symbol", None) or "").strip().upper()
    try:
        raw = json.loads(getattr(bot, "config_json", None) or "{}")
    except Exception:
        raw = {}
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_multi = sym == "MULTI" or strategy_id in ("trdca_pro", "multi_asset_rebalance")

    if pnl_data is None:
        try:
            from app.services.pnl_service import PnlService

            pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id) or {}
        except Exception:
            pnl_data = {}

    if is_multi:
        if not pnl_data.get("error"):
            try:
                return float(pnl_data.get("total_usd") or initial_usd or 0)
            except (TypeError, ValueError):
                pass
        return float(initial_usd or 0)

    ia_done = bool(state.get("initial_allocation_done"))
    base_b = float(state.get("base_balance") or 0)
    quote_b = float(state.get("quote_balance") or 0)
    last_price = display_safe_bot_price(
        get_bot_last_price(sym, state, pnl_data),
        state,
    )

    if last_price is not None and last_price > 0 and (base_b != 0 or quote_b != 0):
        return base_b * last_price + quote_b
    if not ia_done and (getattr(bot, "status", "") or "").lower() == "running":
        return 0.0
    if not pnl_data.get("error"):
        try:
            return float(pnl_data.get("total_usd") or initial_usd or 0)
        except (TypeError, ValueError):
            pass
    return float(initial_usd or 0)
