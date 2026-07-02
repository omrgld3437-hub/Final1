"""Param Assistant must pick library profiles; symbols must not share generic fallback params."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.dynamic_param_score.consumer_policy import build_param_assistant_context
from app.services.dynamic_param_score.data_collector import (
    collect_market_data,
    default_exchange_constraints,
    portfolio_from_budget,
)
from app.services.dynamic_param_score.param_pool.selector import select_and_render
from app.services.dynamic_param_score.regime import classify_regime, determine_risk_state
from app.services.dynamic_param_score.scoring import compute_param_score, compute_sub_scores
from app.services.dynamic_param_score.indicators import compute_indicators

V4_SQLITE = (
    Path(__file__).resolve().parents[3] / "data" / "param_pool" / "v4" / "param_pool_v4.sqlite"
)


@pytest.mark.skipif(not V4_SQLITE.exists(), reason="v4 param pool sqlite not present")
@pytest.mark.asyncio
async def test_param_assistant_symbols_get_distinct_library_templates():
    async def decide(sym: str):
        market = await collect_market_data(sym)
        pf = portfolio_from_budget(1000, market.ticker_price)
        ind = compute_indicators(market, pf)
        c = default_exchange_constraints(sym)
        sub = compute_sub_scores(ind, pf, c)
        score = compute_param_score(sub)
        regime = classify_regime(ind, sub, pf, c, score)
        risk = determine_risk_state(regime, score, sub, pf, c, ind=ind)
        ctx = build_param_assistant_context(budget_usdt=1000, portfolio=pf)
        sel, params, _ = select_and_render(
            score, regime, risk, sub, ind, pf, c, ctx, 1000, 10, symbol=sym
        )
        p = params.to_dict() if params else {}
        return {
            "symbol": sym,
            "template_key": sel.selected_template_key,
            "buy_ladder": p.get("buy_grid_ladder_pcts") or [],
            "base": p.get("base_alloc_frac"),
            "pinned": sel.selection_context.get("pinned_fallback_template_key"),
            "runtime": bool(sel.selection_context.get("runtime_safe_profile_generated")),
        }

    btc = await decide("BTCUSDT")
    xlm = await decide("XLMUSDT")

    for row in (btc, xlm):
        key = row["template_key"] or ""
        assert not key.startswith("FALLBACK_"), f"{row['symbol']} must not use generic pinned fallback"
        assert row["pinned"] is None
        assert row["buy_ladder"] or row["base"] is not None

    assert btc["template_key"] != xlm["template_key"] or btc["buy_ladder"] != xlm["buy_ladder"]
