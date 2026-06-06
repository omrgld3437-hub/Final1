"""
FILE: finance.py
VERSION: v1
DATE: 2026-01-21
CHANGE: Financial Portfolio Management API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel
import json

from app.db.session import get_db
from app.db.models import Account, FinancialPortfolio, FinancialPortfolioSnapshot
from app.api.auth import require_auth, require_account_access

router = APIRouter()


class PortfolioItem(BaseModel):
    name: str
    targetWeight: float
    lastValue: Optional[float] = 0.0
    quantity: Optional[float] = 0.0


class PortfolioCreateRequest(BaseModel):
    name: str
    items: List[Dict]  # [{name, targetWeight, lastValue, quantity}]


class PortfolioSaveCurrentRequest(BaseModel):
    items_current: List[Dict]  # [{name, currentValue, quantity}]


@router.get("/finance/portfolio")
async def get_portfolio(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Get financial portfolio for account. Auth required."""
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    portfolio = (
        db.query(FinancialPortfolio)
        .filter(FinancialPortfolio.account_id == account_id)
        .first()
    )

    if not portfolio:
        return {
            "exists": False,
            "account_id": account_id,
            "name": "",
            "items": [],
            "last_total_usd": None,
            "current_total_usd": None,
            "updated_at": None,
        }

    items = []
    if portfolio.items_json:
        try:
            items = json.loads(portfolio.items_json)
        except:
            items = []

    return {
        "exists": True,
        "account_id": account_id,
        "name": portfolio.name or "",
        "items": items,
        "last_total_usd": portfolio.last_total_usd,
        "current_total_usd": portfolio.current_total_usd,
        "updated_at": portfolio.updated_at.isoformat()
        if portfolio.updated_at
        else None,
    }


@router.post("/finance/portfolio")
async def create_or_update_portfolio(
    account_id: int = Query(..., description="Account ID"),
    request: PortfolioCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Create or update financial portfolio (upsert). Auth required."""
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    portfolio = (
        db.query(FinancialPortfolio)
        .filter(FinancialPortfolio.account_id == account_id)
        .first()
    )

    # Calculate total
    total = sum(
        item.get("lastValue", item.get("initialValue", 0)) for item in request.items
    )

    # Normalize targetWeight if needed
    items_normalized = []
    for item in request.items:
        target_weight = item.get("targetWeight", 0)
        # If targetWeight not provided, calculate from initialValue
        if target_weight == 0 and total > 0:
            initial_value = item.get("lastValue", item.get("initialValue", 0))
            target_weight = initial_value / total
        items_normalized.append(
            {
                "name": item.get("name", ""),
                "targetWeight": target_weight,
                "lastValue": item.get("lastValue", item.get("initialValue", 0)),
                "quantity": item.get("quantity", 0),
            }
        )

    if portfolio:
        # Update existing
        portfolio.name = request.name
        portfolio.items_json = json.dumps(items_normalized)
        portfolio.last_total_usd = total
        portfolio.current_total_usd = total
        portfolio.updated_at = datetime.utcnow()
    else:
        # Create new
        portfolio = FinancialPortfolio(
            account_id=account_id,
            name=request.name,
            items_json=json.dumps(items_normalized),
            last_total_usd=total,
            current_total_usd=total,
        )
        db.add(portfolio)

    db.commit()
    db.refresh(portfolio)

    return {
        "account_id": account_id,
        "name": portfolio.name,
        "items": items_normalized,
        "last_total_usd": portfolio.last_total_usd,
    }


@router.post("/finance/portfolio/save-current")
async def save_current_portfolio(
    account_id: int = Query(..., description="Account ID"),
    request: PortfolioSaveCurrentRequest = Body(...),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Save current values and update reference (new reference). Auth required."""
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    portfolio = (
        db.query(FinancialPortfolio)
        .filter(FinancialPortfolio.account_id == account_id)
        .first()
    )
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Calculate new total
    total = sum(item.get("currentValue", 0) for item in request.items_current)

    if total <= 0:
        raise HTTPException(status_code=400, detail="Total must be greater than 0")

    # Update items with new targetWeight based on current values
    items = []
    for item in request.items_current:
        current_value = item.get("currentValue", 0)
        target_weight = current_value / total if total > 0 else 0
        items.append(
            {
                "name": item.get("name", ""),
                "targetWeight": target_weight,
                "lastValue": current_value,
                "quantity": item.get("quantity", 0),
            }
        )

    # Save snapshot before updating
    snapshot = FinancialPortfolioSnapshot(
        account_id=account_id,
        portfolio_id=portfolio.id,
        total_usd=total,
        items_json=json.dumps(items),
        note="New reference",
    )
    db.add(snapshot)

    # Update portfolio
    portfolio.items_json = json.dumps(items)
    portfolio.last_total_usd = total
    portfolio.current_total_usd = total
    portfolio.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(portfolio)

    return {
        "account_id": account_id,
        "name": portfolio.name,
        "items": items,
        "last_total_usd": portfolio.last_total_usd,
    }


@router.post("/finance/portfolio/reset")
async def reset_portfolio(
    account_id: int = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict:
    """Reset portfolio (delete). Auth required."""
    require_account_access(current, account_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    portfolio = (
        db.query(FinancialPortfolio)
        .filter(FinancialPortfolio.account_id == account_id)
        .first()
    )
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Delete portfolio (snapshots remain for history)
    db.delete(portfolio)
    db.commit()

    return {"message": "Portfolio reset", "account_id": account_id}


@router.get("/market/gold/gram_try")
async def get_gram_gold_try() -> Dict:
    """Get current gram gold price in TRY"""
    import httpx
    import os

    # Try to get from ticker endpoint cache or fetch fresh
    # First try from ticker if available, otherwise fetch from provider
    try:
        # Use ticker endpoint logic (reuse)
        from app.api.routes import _cache

        cache_key = "gram_altin_try"
        cached = _cache.get(cache_key)
        if cached:
            return {
                "gram_try": cached,
                "source": "cache",
                "ts": datetime.utcnow().isoformat(),
            }
    except:
        pass

    # Fetch fresh from provider (Metals-API or similar)
    api_key = os.getenv("METALS_API_KEY") or os.getenv("GOLD_API_KEY")

    if not api_key:
        # Fallback: DataHub cache only (no per-symbol Binance REST)
        try:
            from app.services.data_hub import data_hub

            usdttry = data_hub.get_price("USDTTRY")
            xau_usdt = data_hub.get_price("XAUUSDT")
            if (
                usdttry is not None
                and xau_usdt is not None
                and float(usdttry) > 0
                and float(xau_usdt) > 0
            ):
                usdttry_f = float(usdttry)
                xau_usdt_f = float(xau_usdt)
                gram_altin_try = (xau_usdt_f * usdttry_f) / 31.1034768
                return {
                    "gram_try": round(gram_altin_try, 2),
                    "source": "datahub",
                    "ts": datetime.utcnow().isoformat(),
                }
        except Exception:
            pass

        raise HTTPException(status_code=503, detail="Gold rate provider unavailable")

    # If API key available, use provider
    # Example with Metals-API (adjust as needed)
    try:
        async with httpx.AsyncClient() as client:
            # Metals-API endpoint (example - adjust based on actual API)
            resp = await client.get(
                "https://api.metals.live/v1/spot/gold",
                headers={"x-api-key": api_key},
                timeout=10.0,
            )
            if resp.status_code == 200:
                resp.json()
                # Adjust parsing based on actual API response format
                # This is a placeholder - adjust to actual API structure
                return {
                    "gram_try": 0,  # Parse from actual response
                    "source": "metals-api",
                    "ts": datetime.utcnow().isoformat(),
                }
    except:
        pass

    raise HTTPException(status_code=503, detail="Gold rate provider unavailable")
