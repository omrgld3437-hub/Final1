"""Apply adjuster delta to catalog profile."""

from __future__ import annotations

from typing import List

from app.services.dynamic_param_score.v6.constants import (
    MAX_GRID_COUNT,
    MIN_GRID_COUNT,
    QTY_TEMPLATES,
    SAFE_BUY_TRIM_TEMPLATES,
)
from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, GridLevel, V6CatalogProfile
from app.services.dynamic_param_score.v6.v6_quantizer import (
    apply_trailing_step_delta,
    profit_code_from_pct,
    profit_pct_from_code,
    quantize_base_pct,
    quantize_grid_distance,
    quantize_profit_trigger_pct,
    quantize_profile,
)


def _shift_grids(grids: List[GridLevel], delta_pct: int, *, is_buy: bool) -> List[GridLevel]:
    if not grids or delta_pct == 0:
        return grids
    out: List[GridLevel] = []
    for g in grids:
        dist = g.distance_pct + (-abs(delta_pct) if is_buy else abs(delta_pct))
        if is_buy and dist > 0:
            dist = -abs(dist)
        if not is_buy and dist < 0:
            dist = abs(dist)
        out.append(GridLevel(quantize_grid_distance(dist, is_buy=is_buy), g.amount_pct))
    return out


def _trim_grid_count(
    grids: List[GridLevel],
    count_delta: int,
    *,
    is_buy: bool,
) -> List[GridLevel]:
    if count_delta >= 0 or not grids:
        return grids
    n = max(MIN_GRID_COUNT, min(MAX_GRID_COUNT, len(grids) + count_delta))
    if n >= len(grids):
        return grids
    trimmed = grids[:n]
    tpls = QTY_TEMPLATES.get(n, [])
    if tpls:
        # Alım kademesi bütçeyi yakında tüketmemeli. V6'nın ilk iki-kademe
        # şablonu 60/40 olduğu için sayım azaltıldığında güvenlik politikasını
        # tersine çeviriyordu. Alımda daima derin kademeye en çok ağırlık veren
        # geçerli şablonu seç; satış tarafının mevcut önceliğini koru.
        amounts = (
            SAFE_BUY_TRIM_TEMPLATES.get(n, tpls[0])
            if is_buy
            else tpls[0]
        )
        return [GridLevel(trimmed[i].distance_pct, amounts[i]) for i in range(n)]
    return trimmed


def apply_delta(profile: V6CatalogProfile, delta: AdjusterDelta) -> V6CatalogProfile:
    p = profile.copy()
    base = quantize_base_pct(p.base_allocation_pct + delta.base_delta_steps * 5)
    p.base_allocation_pct = base
    p.quote_allocation_pct = 100 - base
    if delta.normal_buy_override is not None:
        p.normal_buy_enabled = not delta.normal_buy_override
        if not p.normal_buy_enabled and not bool((p.modules or {}).get("reference_plan_only")):
            p.buy_grids = []
    p.buy_grids = _shift_grids(p.buy_grids, delta.buy_grid_distance_delta, is_buy=True)
    p.sell_grids = _shift_grids(p.sell_grids, delta.sell_grid_distance_delta, is_buy=False)
    p.buy_grids = _trim_grid_count(
        p.buy_grids,
        delta.buy_grid_count_delta,
        is_buy=True,
    )
    p.sell_grids = _trim_grid_count(
        p.sell_grids,
        delta.sell_grid_count_delta,
        is_buy=False,
    )
    p.buy_trailing_code = apply_trailing_step_delta(p.buy_trailing_code, delta.buy_trailing_delta_steps)
    p.sell_trailing_code = apply_trailing_step_delta(p.sell_trailing_code, delta.sell_trailing_delta_steps)
    if p.buyback_after_sell_enabled and delta.buyback_trigger_delta:
        bp = profit_pct_from_code(p.buyback_trigger_code) + delta.buyback_trigger_delta
        p.buyback_trigger_code = profit_code_from_pct(quantize_profit_trigger_pct(bp))
    if p.profit_sell_after_buyback_enabled and delta.profit_sell_trigger_delta:
        sp = profit_pct_from_code(p.profit_sell_trigger_code) + delta.profit_sell_trigger_delta
        p.profit_sell_trigger_code = profit_code_from_pct(quantize_profit_trigger_pct(sp))
    return quantize_profile(p)
