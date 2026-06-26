"""Churn protection — avoid cancel/replace on small parameter drift."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

REBALANCE_THRESHOLD_TOTAL_PP = 15.0
SPACING_CHANGE_PCT_THRESHOLD = 10.0
TRAILING_CHANGE_PCT_THRESHOLD = 10.0
TAKE_PROFIT_CHANGE_PCT_THRESHOLD = 10.0


def _pct_change(old: float, new: float) -> float:
    if old <= 0 and new <= 0:
        return 0.0
    base = max(abs(old), abs(new), 1e-9)
    return abs(float(new) - float(old)) / base * 100.0


def should_preserve_orders(
    prev_applied: Optional[Dict[str, Any]],
    new_applied: Dict[str, Any],
    *,
    rebalance_plan: Optional[Dict[str, Any]] = None,
    risk_state_changed: bool = False,
    route_changed: bool = False,
    spread_unsafe: bool = False,
    dump_risk: bool = False,
    exposure_breach: bool = False,
) -> Tuple[bool, List[str]]:
    """Return (preserve, reasons). True = do not cancel/replace open orders."""
    reasons: List[str] = []
    prev = prev_applied or {}
    if not prev:
        return False, ["no_previous_snapshot"]

    if spread_unsafe or dump_risk or exposure_breach:
        return False, ["safety_override"]

    if risk_state_changed or route_changed:
        return False, ["material_regime_or_route_change"]

    rb = rebalance_plan or {}
    delta_pp = float(rb.get("rebalance_delta_total_pp") or 0.0)
    if delta_pp > REBALANCE_THRESHOLD_TOTAL_PP and rb.get("rebalance_decision") == "EXECUTE":
        return False, ["meaningful_rebalance_pending"]

    buy_n_old = len(prev.get("buy_grids") or [])
    buy_n_new = len(new_applied.get("buy_grids") or [])
    sell_n_old = len(prev.get("sell_grids") or [])
    sell_n_new = len(new_applied.get("sell_grids") or [])
    if buy_n_old != buy_n_new or sell_n_old != sell_n_new:
        return False, ["grid_count_changed"]

    for field, threshold in (
        ("buy_trigger_trailing_pct", TRAILING_CHANGE_PCT_THRESHOLD),
        ("sell_trigger_trailing_pct", TRAILING_CHANGE_PCT_THRESHOLD),
        ("profit_exit_rise_pct", TAKE_PROFIT_CHANGE_PCT_THRESHOLD),
        ("profit_reentry_drop_pct", TAKE_PROFIT_CHANGE_PCT_THRESHOLD),
    ):
        ch = _pct_change(float(prev.get(field) or 0), float(new_applied.get(field) or 0))
        if ch >= threshold:
            return False, [f"{field}_change_{ch:.1f}pct"]

    old_buy = (prev.get("buy_grids") or [{}])[0] if prev.get("buy_grids") else {}
    new_buy = (new_applied.get("buy_grids") or [{}])[0] if new_applied.get("buy_grids") else {}
    spacing_ch = _pct_change(
        float(old_buy.get("buy_grid_pct") or 0),
        float(new_buy.get("buy_grid_pct") or 0),
    )
    if spacing_ch >= SPACING_CHANGE_PCT_THRESHOLD:
        return False, [f"grid_spacing_change_{spacing_ch:.1f}pct"]

    if delta_pp <= REBALANCE_THRESHOLD_TOTAL_PP:
        reasons.append("small_base_quote_delta")
    reasons.append("within_churn_thresholds")
    return True, reasons
