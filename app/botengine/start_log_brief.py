"""İlk bot START logu için kısa config özeti (bot_engine_events meta)."""

from __future__ import annotations

from typing import Any, Dict, List


def _grid_sell_short(g: Dict[str, Any], idx: int) -> str:
    pct = (
        g.get("sell_grid_pct")
        if g.get("sell_grid_pct") is not None
        else g.get("trigger_pct")
    )
    qty = (
        g.get("sell_qty_pct_of_base")
        if g.get("sell_qty_pct_of_base") is not None
        else g.get("qty_pct")
    )
    p = f"+{pct}" if pct is not None else "—"
    q = f"{qty}%B" if qty is not None else "—"
    return f"Y#{idx + 1} {p}% {q}"


def _grid_buy_short(g: Dict[str, Any], idx: int) -> str:
    pct = (
        g.get("buy_grid_pct")
        if g.get("buy_grid_pct") is not None
        else g.get("trigger_pct")
    )
    qty = (
        g.get("buy_qty_pct_of_quote")
        if g.get("buy_qty_pct_of_quote") is not None
        else g.get("qty_pct")
    )
    p = f"-{pct}" if pct is not None else "—"
    q = f"{qty}%Q" if qty is not None else "—"
    return f"A#{idx + 1} {p}% {q}"


def build_cold_start_brief_meta(raw_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Kısa kodlar: alloc %, grid adetleri, seviye satırları."""
    raw_cfg = raw_cfg or {}
    sell: List[Dict[str, Any]] = list(raw_cfg.get("sell_grids") or [])
    buy: List[Dict[str, Any]] = list(raw_cfg.get("buy_grids") or [])
    out: Dict[str, Any] = {
        "cold_start_config": True,
        "base_alloc_pct": round(float(raw_cfg.get("base_alloc_pct", 50) or 50), 1),
        "quote_alloc_pct": round(float(raw_cfg.get("quote_alloc_pct", 50) or 50), 1),
        "sell_grid_count": len(sell),
        "buy_grid_count": len(buy),
        "sell_grids_brief": [_grid_sell_short(g, i) for i, g in enumerate(sell[:16])],
        "buy_grids_brief": [_grid_buy_short(g, i) for i, g in enumerate(buy[:16])],
    }
    st = raw_cfg.get("sell_trigger_trailing_pct")
    bt = raw_cfg.get("buy_trigger_trailing_pct")
    if st is not None:
        out["sell_trail_pct"] = round(float(st), 2)
    if bt is not None:
        out["buy_trail_pct"] = round(float(bt), 2)
    pr = raw_cfg.get("profit_reentry_drop_pct") or (raw_cfg.get("profit") or {}).get(
        "rebuy_trigger_pct"
    )
    pe = raw_cfg.get("profit_exit_rise_pct") or (raw_cfg.get("profit") or {}).get(
        "resell_trigger_pct"
    )
    if pr is not None:
        out["profit_reentry_pct"] = round(float(pr), 2)
    if pe is not None:
        out["profit_exit_pct"] = round(float(pe), 2)
    return out


def merge_cold_start_brief_into_meta(
    meta: Dict[str, Any],
    raw_cfg: Dict[str, Any],
    *,
    cold_only: bool = True,
) -> Dict[str, Any]:
    if cold_only:
        if meta.get("connectivity_resume"):
            return meta
        if meta.get("initial_allocation_done"):
            return meta
    meta.update(build_cold_start_brief_meta(raw_cfg))
    return meta
