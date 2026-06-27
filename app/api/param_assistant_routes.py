"""
Parametre Asistanı API'si — Dynamic Param Score Engine.

Canlı karar artık ağır optimizer yerine merkezî DPS motorunu kullanır.
Eski async optimizer endpoint'leri uyumluluk için kalır ama /optimize
anında DPS sonucu döner (MC/backtest bekleme yok).

    POST /api/param-assistant/calculate     -> Param Assistant (consumer_policy=param_assistant)
    POST /api/dynamic-param-score/calculate -> Dynamic Mode tur simülasyonu (consumer_policy=dynamic_round_start)
    POST /api/param-assistant/optimize      -> DPS'e yönlendirilir (legacy path)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_auth
from app.services.dynamic_param_score import get_engine
from app.services.dynamic_param_score.adapters import (
    PARAM_ASSISTANT_RESULT_SCHEMA,
    decision_to_param_assistant_result,
)
from app.services.dynamic_param_score.data_collector import (
    collect_market_data,
    default_exchange_constraints,
    portfolio_from_budget,
    portfolio_from_user_scenario,
)
from app.services.dynamic_param_score.consumer_policy import build_param_assistant_context

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_LEVELS = ("professional_auto",)  # legacy — all map to DPS


class OptimizeRequest(BaseModel):
    symbol: str
    budget: float
    analysis_level: Optional[str] = "professional_auto"  # ignored
    first_start_buy_only: Optional[bool] = None
    base_balance_usdt: Optional[float] = None
    quote_balance_usdt: Optional[float] = None
    base_alloc_frac: Optional[float] = None
    dry_run: Optional[bool] = True


class EstimateRequest(BaseModel):
    analysis_level: Optional[str] = "professional_auto"


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


def _level(v: Optional[str]) -> str:
    return "professional_auto"


async def _run_dps(
    symbol: str,
    budget: float,
    *,
    first_start_buy_only: Optional[bool] = None,
    base_balance_usdt: Optional[float] = None,
    quote_balance_usdt: Optional[float] = None,
    base_alloc_frac: Optional[float] = None,
    dry_run: bool = True,
):
    market = await collect_market_data(symbol)
    price = float(market.ticker_price or 0.0)
    if base_balance_usdt is not None or quote_balance_usdt is not None or base_alloc_frac is not None:
        portfolio = portfolio_from_user_scenario(
            quote_budget_usdt=budget,
            price=price,
            base_balance_usdt=base_balance_usdt,
            quote_balance_usdt=quote_balance_usdt,
            base_alloc_frac=base_alloc_frac,
        )
    else:
        portfolio = portfolio_from_budget(budget, price)
    constraints = default_exchange_constraints(symbol)
    ctx = build_param_assistant_context(
        budget_usdt=budget,
        portfolio=portfolio,
        first_start_buy_only=first_start_buy_only,
        allow_live=not dry_run,
        allow_no_trade=True,
    )

    def _calc():
        return get_engine().calculate_decision(
            symbol=symbol,
            market_data=market,
            portfolio_state=portfolio,
            exchange_constraints=constraints,
            bot_context=ctx,
        )

    loop = asyncio.get_running_loop()
    decision = await loop.run_in_executor(None, _calc)
    return decision_to_param_assistant_result(decision, budget, symbol)


@router.get("/param-assistant/tiers")
async def list_tiers(current: dict = Depends(require_auth)):
    """Tek mod: Dynamic Param Score (anında hesaplama)."""
    return {
        "ok": True,
        "tiers": [
            {
                "key": "professional_auto",
                "label": "Parametre Skoru Analizi",
                "description": "Piyasa koşulları + portföy durumuna göre anında parametre skoru ve profil seçimi.",
                "requires_confirm": False,
                "eta_low_sec": 2,
                "eta_high_sec": 15,
                "cap_sec": 30,
                "cores": 1,
            }
        ],
    }


@router.post("/param-assistant/estimate")
async def estimate(req: EstimateRequest, current: dict = Depends(require_auth)):
    return {
        "ok": True,
        "eta_low_sec": 2,
        "eta_high_sec": 15,
        "cap_sec": 30,
        "cores": 1,
        "engine": "dynamic_param_score",
    }


@router.post("/param-assistant/calculate")
async def calculate(req: OptimizeRequest, current: dict = Depends(require_auth)):
    """Anında DPS kararı — önerilen yeni endpoint."""
    symbol = _normalize_symbol(req.symbol)
    if not symbol or len(symbol) < 5:
        raise HTTPException(status_code=400, detail="Geçersiz parite.")
    try:
        budget = float(req.budget)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Geçersiz bütçe.")
    if budget < 25:
        raise HTTPException(status_code=400, detail="Bütçe en az 25 USDT olmalı.")
    from app.services.user_readable_activity_logger import UserReadableActivityLogger

    uid = current.get("user_id")
    if uid:
        UserReadableActivityLogger.write_event(
            uid,
            "PARAM_ANALYSIS_STARTED",
            context={"symbol": symbol, "budget": budget},
        )
    result = await _run_dps(
        symbol,
        budget,
        first_start_buy_only=req.first_start_buy_only,
        base_balance_usdt=req.base_balance_usdt,
        quote_balance_usdt=req.quote_balance_usdt,
        base_alloc_frac=req.base_alloc_frac,
        dry_run=bool(req.dry_run if req.dry_run is not None else True),
    )
    if uid:
        rt = str(result.get("result_type") or result.get("action") or "").lower()
        evt = "PARAM_ANALYSIS_COMPLETED"
        if "no_trade" in rt or result.get("no_trade"):
            evt = "PARAM_RESULT_NO_TRADE"
        elif "deployable" in rt or result.get("deployable"):
            evt = "PARAM_RESULT_DEPLOYABLE"
        elif "recommended" in rt:
            evt = "PARAM_RESULT_RECOMMENDED"
        elif not result.get("ok", True):
            evt = "PARAM_ANALYSIS_FAILED"
        UserReadableActivityLogger.write_event(
            uid, evt, context={"symbol": symbol, "budget": budget}
        )
    return result


@router.post("/param-assistant/optimize")
async def start_optimize(req: OptimizeRequest, current: dict = Depends(require_auth)):
    """Legacy path — artık anında DPS döner (async job yok)."""
    symbol = _normalize_symbol(req.symbol)
    if not symbol or len(symbol) < 5:
        raise HTTPException(status_code=400, detail="Geçersiz parite.")
    try:
        budget = float(req.budget)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Geçersiz bütçe.")
    if budget < 25:
        raise HTTPException(status_code=400, detail="Bütçe en az 25 USDT olmalı.")
    from app.services.user_readable_activity_logger import UserReadableActivityLogger

    uid = current.get("user_id")
    if uid:
        UserReadableActivityLogger.write_event(
            uid,
            "PARAM_ANALYSIS_STARTED",
            context={"symbol": symbol, "budget": budget},
        )

    result = await _run_dps(
        symbol,
        budget,
        first_start_buy_only=req.first_start_buy_only,
        base_balance_usdt=req.base_balance_usdt,
        quote_balance_usdt=req.quote_balance_usdt,
        base_alloc_frac=req.base_alloc_frac,
        dry_run=bool(req.dry_run if req.dry_run is not None else True),
    )
    if uid:
        rt = str(result.get("result_type") or result.get("action") or "").lower()
        evt = "PARAM_ANALYSIS_COMPLETED"
        if "no_trade" in rt or result.get("no_trade"):
            evt = "PARAM_RESULT_NO_TRADE"
        elif "deployable" in rt or result.get("deployable"):
            evt = "PARAM_RESULT_DEPLOYABLE"
        elif "recommended" in rt:
            evt = "PARAM_RESULT_RECOMMENDED"
        elif not result.get("ok", True):
            evt = "PARAM_ANALYSIS_FAILED"
        UserReadableActivityLogger.write_event(
            uid, evt, context={"symbol": symbol, "budget": budget}
        )
    import uuid

    job_id = uuid.uuid4().hex[:16]
    return {
        "ok": True,
        "started": True,
        "job_id": job_id,
        "status": "done",
        "reused": False,
        "instant": True,
        "engine": "dynamic_param_score",
        "symbol": symbol,
        "budget": budget,
        "analysis_level": _level(req.analysis_level),
        "result_schema_version": PARAM_ASSISTANT_RESULT_SCHEMA,
        "result": result,
    }


@router.get("/param-assistant/active")
async def active_job(current: dict = Depends(require_auth)):
    return {"ok": True, "state": "none"}


@router.post("/param-assistant/optimize/{job_id}/cancel")
async def cancel_optimize(job_id: str, current: dict = Depends(require_auth)):
    return {"ok": True, "cancelled": False, "note": "instant_dps_no_job"}


@router.post("/param-assistant/cancel-active")
async def cancel_active(current: dict = Depends(require_auth)):
    return {"ok": True, "cancelled": 0}


@router.get("/param-assistant/optimize/{job_id}")
async def get_optimize(job_id: str, current: dict = Depends(require_auth)):
    raise HTTPException(
        status_code=404,
        detail="Anında DPS modunda iş kuyruğu yok. POST /param-assistant/calculate kullanın.",
    )
