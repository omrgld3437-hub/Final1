"""
Parametre Asistanı API'si.

Bütçe + parite alır; geçmiş + indikatörler + gerçek strateji
backtest'i + Monte Carlo gelecek simülasyonu ile en iyi tüm bot parametrelerini
hesaplar. Derin otomatik seviye full CPU + 1-6 saat tavanlı async job:

    GET  /api/param-assistant/tiers           -> seviye listesi
    POST /api/param-assistant/estimate        -> {tier} için tahmini süre (onay öncesi)
    POST /api/param-assistant/optimize        -> {job_id}
    GET  /api/param-assistant/optimize/{id}   -> ilerleme/ETA/sonuç
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_auth
from app.services.param_optimizer import jobs as opt_jobs
from app.services.param_optimizer.tiers import TIERS

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_LEVELS = ("soft", "medium", "high")


class OptimizeRequest(BaseModel):
    symbol: str
    budget: float
    analysis_level: Optional[str] = "high"


class EstimateRequest(BaseModel):
    analysis_level: Optional[str] = "high"


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
    lv = (v or "high").strip().lower()
    return lv if lv in _VALID_LEVELS else "high"


def _owner_key(current: dict) -> str:
    """Hesap başına asistan sahipliği. Hesap yoksa kullanıcıya, o da yoksa anon."""
    aid = current.get("account_id")
    if aid:
        return f"acc:{aid}"
    uid = current.get("user_id")
    return f"usr:{uid}" if uid else "anon"


@router.get("/param-assistant/tiers")
async def list_tiers(current: dict = Depends(require_auth)):
    """Analiz seviyeleri + her biri için tahmini süre."""
    out = []
    for key in _VALID_LEVELS:
        t = TIERS[key]
        est = opt_jobs.estimate_for(key)
        out.append(
            {
                "key": t.key,
                "label": t.label,
                "description": t.description,
                "requires_confirm": t.requires_confirm,
                "eta_low_sec": est["eta_low_sec"],
                "eta_high_sec": est["eta_high_sec"],
                "cap_sec": est["cap_sec"],
                "cores": est["cores"],
            }
        )
    return {"ok": True, "tiers": out}


@router.post("/param-assistant/estimate")
async def estimate(req: EstimateRequest, current: dict = Depends(require_auth)):
    """Seçilen seviye için tahmini süre (Yüksek onay diyaloğu için)."""
    return {"ok": True, **opt_jobs.estimate_for(_level(req.analysis_level))}


@router.post("/param-assistant/optimize")
async def start_optimize(req: OptimizeRequest, current: dict = Depends(require_auth)):
    symbol = _normalize_symbol(req.symbol)
    if not symbol or len(symbol) < 5:
        raise HTTPException(status_code=400, detail="Geçersiz parite.")
    try:
        budget = float(req.budget)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Geçersiz bütçe.")
    if budget < 25:
        raise HTTPException(status_code=400, detail="Bütçe en az 25 USDT olmalı.")

    level = _level(req.analysis_level)
    owner = _owner_key(current)
    existing = opt_jobs.get_running_job_for_owner(owner)
    if existing is not None:
        job = existing
        reused = True
    else:
        job = await opt_jobs.create_job(
            symbol, budget, analysis_level=level, owner_key=owner
        )
        reused = False
    return {
        "ok": True,
        "job_id": job.id,
        "status": job.status,
        "reused": reused,
        "requested_symbol": symbol,
        "symbol": job.symbol,
        "budget": job.budget,
        "analysis_level": job.tier,
        "tier_label": job.tier_label,
        "cores": job.cores,
        "time_budget_sec": job.time_budget_sec,
        "eta_total_sec": job.eta_total_sec,
        "queue_position": opt_jobs.running_count(),
    }


@router.get("/param-assistant/active")
async def active_job(current: dict = Depends(require_auth)):
    """Modal açılışında: devam eden işe yeniden bağlan ya da bitmiş öneriyi tek-sefer ver.

    state: running | finished | error | none
    """
    state = opt_jobs.get_owner_attach_state(_owner_key(current))
    return {"ok": True, **state}


@router.post("/param-assistant/optimize/{job_id}/cancel")
async def cancel_optimize(job_id: str, current: dict = Depends(require_auth)):
    res = opt_jobs.cancel_job(job_id, owner_key=_owner_key(current))
    if res.get("forbidden"):
        raise HTTPException(status_code=403, detail="Bu analizi sonlandırma yetkin yok.")
    return {"ok": True, **res}


@router.post("/param-assistant/cancel-active")
async def cancel_active(current: dict = Depends(require_auth)):
    return {"ok": True, **opt_jobs.cancel_running_jobs_for_owner(_owner_key(current))}


@router.get("/param-assistant/optimize/{job_id}")
async def get_optimize(job_id: str, current: dict = Depends(require_auth)):
    job = opt_jobs.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Optimizasyon işi bulunamadı (zaman aşımına uğramış olabilir).",
        )
    return job.public()
