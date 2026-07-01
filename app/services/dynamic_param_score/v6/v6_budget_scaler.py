"""Scale profile to bot budget — does not change strategy percents."""

from __future__ import annotations

from typing import Any, Dict

from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile, V6InputContract


def budget_scale(profile: V6CatalogProfile, inp: V6InputContract) -> Dict[str, Any]:
    budget = float(inp.bot_budget_usdt)
    base_pct = profile.base_allocation_pct
    base_budget = budget * base_pct / 100.0
    quote_budget = budget - base_budget
    return {
        "bot_budget_usdt": budget,
        "base_allocation_pct": base_pct,
        "quote_allocation_pct": profile.quote_allocation_pct,
        "base_budget_usdt": round(base_budget, 2),
        "quote_budget_usdt": round(quote_budget, 2),
        "current_price": inp.current_price,
        "symbol": inp.symbol,
    }
