"""Dynamic Param Score API routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_auth
from app.services.dynamic_param_score import get_engine
from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.data_collector import (
    collect_market_data,
    default_exchange_constraints,
    portfolio_from_budget,
)
from app.services.dynamic_param_score.consumer_policy import build_dynamic_round_context
logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_symbol(sym: str) -> str:
    s = (sym or "").upper().strip().replace("/", "").replace("-", "")
    if not s:
        return ""
    if not any(
        s.endswith(q)
        for q in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "TRY")
    ):
        s = s + "USDT"
    return s


class CalculateRequest(BaseModel):
    symbol: str
    budget: float = Field(ge=25)
    bot_id: Optional[int] = None
    cycle_id: Optional[int] = Field(default=1, ge=1)
    analysis_level: Optional[str] = None  # legacy — ignored


@router.post("/dynamic-param-score/calculate")
async def calculate_dynamic_param_score(
    req: CalculateRequest,
    current: dict = Depends(require_auth),
):
    symbol = _normalize_symbol(req.symbol)
    if not symbol or len(symbol) < 5:
        raise HTTPException(status_code=400, detail="Geçersiz parite.")

    market = await collect_market_data(symbol)
    portfolio = portfolio_from_budget(req.budget, market.ticker_price)
    constraints = default_exchange_constraints(symbol)
    ctx = build_dynamic_round_context(
        budget_usdt=req.budget,
        cycle_id=int(req.cycle_id or 1),
        bot_id=req.bot_id,
        allow_live=True,
        allow_no_trade=True,
    )

    decision = get_engine().calculate_decision(
        symbol=symbol,
        market_data=market,
        portfolio_state=portfolio,
        exchange_constraints=constraints,
        bot_context=ctx,
    )
    return {"ok": True, "decision": decision.to_dict()}
