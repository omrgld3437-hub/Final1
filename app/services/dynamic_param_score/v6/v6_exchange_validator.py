"""Min-notional and exchange validation — spec §19."""

from __future__ import annotations

from typing import List, Tuple

from app.services.dynamic_param_score.v6.constants import (
    QTY_TEMPLATES,
    SAFE_BUY_TRIM_TEMPLATES,
)
from app.services.dynamic_param_score.v6.domain.types import GridLevel, V6CatalogProfile, V6InputContract


def _grid_notional_ok(
    budget_usdt: float,
    amount_pct: int,
    price: float,
    min_notional: float,
) -> bool:
    if price <= 0:
        return False
    notional = budget_usdt * amount_pct / 100.0
    return notional >= min_notional


def validate_and_trim_grids(
    profile: V6CatalogProfile,
    inp: V6InputContract,
    *,
    side: str,
) -> Tuple[List[GridLevel], bool]:
    """Return trimmed grids and whether budget adjustment occurred."""
    grids = profile.buy_grids if side == "buy" else profile.sell_grids
    if not grids:
        return [], False
    budget = inp.bot_budget_usdt
    if side == "buy":
        budget *= profile.quote_allocation_pct / 100.0
    else:
        budget *= profile.base_allocation_pct / 100.0
    adjusted = False
    working = list(grids)
    while working:
        ok = all(
            _grid_notional_ok(budget, g.amount_pct, inp.current_price, inp.min_notional)
            for g in working
        )
        if ok:
            break
        if len(working) > 1:
            working = working[:-1]
            tpls = QTY_TEMPLATES.get(len(working), [])
            if tpls:
                amounts = (
                    SAFE_BUY_TRIM_TEMPLATES.get(len(working), tpls[0])
                    if side == "buy"
                    else tpls[0]
                )
                working = [GridLevel(working[i].distance_pct, amounts[i]) for i in range(len(working))]
            adjusted = True
        else:
            working = []
            adjusted = True
            break
    return working, adjusted


def exchange_validate(profile: V6CatalogProfile, inp: V6InputContract) -> Tuple[V6CatalogProfile, List[str]]:
    notes: List[str] = []
    p = profile.copy()
    buy, adj_b = validate_and_trim_grids(p, inp, side="buy")
    sell, adj_s = validate_and_trim_grids(p, inp, side="sell")
    if adj_b:
        notes.append("budget_adjusted_buy_grids")
    if adj_s:
        notes.append("budget_adjusted_sell_grids")
    p.buy_grids = buy
    p.sell_grids = sell
    if not p.buy_grids and p.normal_buy_enabled:
        p.normal_buy_enabled = False
    return p, notes
