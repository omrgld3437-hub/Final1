"""
Bot engine state RAM sınırları — persist öncesi zorunlu trim.

Tur/işlem detayı dosya ve DB arşivinde; state yalnızca motor için gerekli son kayıtları tutar.
"""
from __future__ import annotations

from typing import Any, Dict, List

# execution.py / cycle_ledger / dca_grid_trailing ile uyumlu
MAX_COMPLETED_CYCLE_DUAL = 200
MAX_CYCLE_LEDGER_FILLS_ARCHIVE = 50
MAX_CYCLE_GRID_FILLS_ARCHIVE = 500
MAX_CYCLE_LEDGER_FILLS_CURRENT = 120
MAX_GRID_HISTORY_PER_SIDE = 80
MAX_CYCLE_PNLS = 100
MAX_PENDING_ENGINE_EVENTS = 40


def _trim_list(items: Any, max_len: int) -> List[Any]:
    if not isinstance(items, list):
        return []
    if len(items) <= max_len:
        return items
    return items[-max_len:]


def _trim_ledger_block(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    out = dict(block)
    fills = out.get("fills")
    if isinstance(fills, list) and len(fills) > MAX_CYCLE_LEDGER_FILLS_CURRENT:
        out["fills"] = fills[-MAX_CYCLE_LEDGER_FILLS_CURRENT:]
    return out


def trim_bot_state_for_persist(state: Dict[str, Any]) -> Dict[str, Any]:
    """save_state öncesi: JSON boyutunu sınırla (idempotent)."""
    if not state or not isinstance(state, dict):
        return state or {}

    s = state

    if "completed_cycle_dual_pnls" in s:
        s["completed_cycle_dual_pnls"] = _trim_list(
            s.get("completed_cycle_dual_pnls"), MAX_COMPLETED_CYCLE_DUAL
        )
    if "cycle_pnls" in s:
        s["cycle_pnls"] = _trim_list(s.get("cycle_pnls"), MAX_CYCLE_PNLS)
    if "cycle_ledger_fills_archive" in s:
        s["cycle_ledger_fills_archive"] = _trim_list(
            s.get("cycle_ledger_fills_archive"), MAX_CYCLE_LEDGER_FILLS_ARCHIVE
        )
    if "cycle_grid_fills_archive" in s:
        s["cycle_grid_fills_archive"] = _trim_list(
            s.get("cycle_grid_fills_archive"), MAX_CYCLE_GRID_FILLS_ARCHIVE
        )
    if "sell_history" in s:
        s["sell_history"] = _trim_list(s.get("sell_history"), MAX_GRID_HISTORY_PER_SIDE)
    if "buy_history" in s:
        s["buy_history"] = _trim_list(s.get("buy_history"), MAX_GRID_HISTORY_PER_SIDE)

    ledger = s.get("cycle_ledger_current")
    if isinstance(ledger, dict):
        s["cycle_ledger_current"] = _trim_ledger_block(ledger)

    pending = s.get("_pending_engine_events")
    if isinstance(pending, list) and len(pending) > MAX_PENDING_ENGINE_EVENTS:
        s["_pending_engine_events"] = pending[-MAX_PENDING_ENGINE_EVENTS:]

    return s
