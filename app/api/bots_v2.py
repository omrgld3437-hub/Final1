"""
FILE: bots_v2.py
VERSION: v1
DATE: 2026-01-21
CHANGE: Bot V2 API endpoints - create, start, stop, pause, state, grids, trades, logs; audit BOT_CREATE
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.bot.models_v2 import (
    BotV2, BotBalanceV2, BotGridV2, BotCycleV2, BotTradeV2, BotStateV2
)
from app.bot.worker_v2 import get_worker
from app.db.models import Account
from app.services.encryption import decrypt_account_api_key, decrypt_account_api_secret
from app.services import audit as audit_svc
from app.api.auth import require_auth, get_account_or_403, get_client_ip
from app.bot.binance_adapter_v2 import BinanceSpotAdapterV2

router = APIRouter()


class BotCreateV2Request(BaseModel):
    account_id: int
    symbol: str
    budget_usdt: float
    base_alloc_pct: float
    mode: str = "paper"
    ref_price_mode: str = "market_now"
    ref_price: Optional[float] = None
    up_grids: List[Dict[str, Any]]
    down_grids: List[Dict[str, Any]]
    profit_rebuy_trigger_pct: float = 1.5
    profit_rebuy_trailing_pct: float = 1.0
    profit_resell_trigger_pct: float = 2.0
    profit_resell_trailing_pct: float = 1.0
    polling_interval_ms: int = 2000
    slippage_bps: int = 10
    taker_fee_bps: int = 10


@router.post("/bots/create_v2")
async def create_bot_v2(
    request_body: BotCreateV2Request,
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Create a new Bot V2. Auth required."""
    get_account_or_403(current, request_body.account_id, db)
    # Validate account
    account = db.query(Account).filter(Account.id == request_body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Get reference price
    ref_price = request_body.ref_price
    if request_body.ref_price_mode == "market_now" or not ref_price:
        # Create adapter to get price
        if request_body.mode == "live":
            api_key = decrypt_account_api_key(account.id, account.api_key_enc)
            api_secret = decrypt_account_api_secret(account.id, account.api_secret_enc)
            adapter = BinanceSpotAdapterV2(request_body.account_id, "live", api_key, api_secret)
        else:
            adapter = BinanceSpotAdapterV2(request_body.account_id, "paper")
        ref_price = adapter.get_price(request_body.symbol)

    # Parse symbol
    quote_asset = "USDT"  # Default
    base_asset = request_body.symbol.replace(quote_asset, "")
    if len(base_asset) == 0:
        base_asset = request_body.symbol[:-4]  # Fallback

    # Create bot
    bot = BotV2(
        account_id=request_body.account_id,
        symbol=request_body.symbol,
        mode=request_body.mode,
        status="STOPPED",
        budget_usdt_initial=request_body.budget_usdt,
        budget_usdt_current=request_body.budget_usdt,
        base_alloc_pct=request_body.base_alloc_pct,
        ref_price_mode=request_body.ref_price_mode,
        ref_price=ref_price,
        polling_interval_ms=request_body.polling_interval_ms,
        slippage_bps=request_body.slippage_bps,
        taker_fee_bps=request_body.taker_fee_bps
    )
    db.add(bot)
    db.flush()

    # Initialize balances (split by base_alloc_pct)
    base_usdt_value = request_body.budget_usdt * (request_body.base_alloc_pct / 100.0)
    quote_usdt_value = request_body.budget_usdt - base_usdt_value
    base_qty = base_usdt_value / ref_price if ref_price > 0 else 0

    balances = BotBalanceV2(
        bot_id=bot.id,
        base_asset=base_asset,
        quote_asset=quote_asset,
        base_free=base_qty,
        quote_free=quote_usdt_value,
        base_value_usdt=base_usdt_value,
        total_value_usdt=request_body.budget_usdt
    )
    db.add(balances)

    # Create grids
    for idx, grid_data in enumerate(request_body.up_grids):
        trigger_abs = ref_price * (1 + grid_data["trigger_value"] / 100.0) if grid_data.get("trigger_type") == "PCT" else grid_data["trigger_value"]
        grid = BotGridV2(
            bot_id=bot.id,
            side="UP_SELL",
            idx=idx,
            trigger_type=grid_data.get("trigger_type", "PCT"),
            trigger_value=grid_data["trigger_value"],
            trigger_price_abs=trigger_abs,
            qty_pct=grid_data["qty_pct"],
            trailing_pct=grid_data["trailing_pct"],
            min_exec_usdt=grid_data.get("min_exec_usdt", 10.0),
            enabled=grid_data.get("enabled", True),
            state="IDLE"
        )
        db.add(grid)

    for idx, grid_data in enumerate(request_body.down_grids):
        trigger_abs = ref_price * (1 - grid_data["trigger_value"] / 100.0) if grid_data.get("trigger_type") == "PCT" else grid_data["trigger_value"]
        grid = BotGridV2(
            bot_id=bot.id,
            side="DOWN_BUY",
            idx=idx,
            trigger_type=grid_data.get("trigger_type", "PCT"),
            trigger_value=grid_data["trigger_value"],
            trigger_price_abs=trigger_abs,
            qty_pct=grid_data["qty_pct"],
            trailing_pct=grid_data["trailing_pct"],
            min_exec_usdt=grid_data.get("min_exec_usdt", 10.0),
            enabled=grid_data.get("enabled", True),
            state="IDLE"
        )
        db.add(grid)

    # Create initial cycle
    cycle = BotCycleV2(
        bot_id=bot.id,
        cycle_no=1,
        start_ts=datetime.utcnow(),
        status="OPEN"
    )
    db.add(cycle)

    # Create state
    state = BotStateV2(
        bot_id=bot.id,
        state_json='{"last_price": 0, "ref_price": 0}'
    )
    db.add(state)

    db.commit()
    db.refresh(bot)

    # İşlem geçmişi: bot oluşturma (V2)
    config_summary = {
        "symbol": request_body.symbol, "mode": request_body.mode, "budget_usdt": request_body.budget_usdt,
        "base_alloc_pct": request_body.base_alloc_pct, "up_grids_count": len(request_body.up_grids),
        "down_grids_count": len(request_body.down_grids),
    }
    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_CREATE", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=account.user_id, target_account_id=request_body.account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={
            "bot_id": bot.id, "account_id": request_body.account_id, "config_summary": config_summary,
            "user_agent": (request.headers.get("user-agent") or "")[:200],
        },
    )

    return {
        "bot_id": bot.id,
        "status": bot.status,
        "symbol": bot.symbol,
        "budget_usdt": bot.budget_usdt_current
    }


@router.post("/bots/{bot_id}/start")
async def start_bot_v2(
    bot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Start a Bot V2"""
    bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    get_account_or_403(current, bot.account_id, db)
    acc = db.query(Account).filter(Account.id == bot.account_id).first()

    bot.status = "RUNNING"
    bot.updated_at = datetime.utcnow()
    db.commit()

    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_START", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=acc.user_id if acc else None, target_account_id=bot.account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"bot_id": bot_id},
    )
    worker = get_worker()
    await worker.start_bot(bot_id, db)

    return {"status": "RUNNING"}


@router.post("/bots/{bot_id}/stop")
async def stop_bot_v2(
    bot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
):
    """Stop a Bot V2"""
    bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    get_account_or_403(current, bot.account_id, db)
    acc = db.query(Account).filter(Account.id == bot.account_id).first()

    worker = get_worker()
    await worker.stop_bot(bot_id)

    audit_svc.log_event(
        db, actor_type="admin" if current.get("is_admin") else "user", event_type="BOT_STOP", severity="INFO",
        actor_user_id=current.get("user_id"), target_user_id=acc.user_id if acc else None, target_account_id=bot.account_id,
        ip=get_client_ip(request), device_id=current.get("device_id"),
        request_id=getattr(request.state, "request_id", None),
        meta={"bot_id": bot_id},
    )
    return {"status": "STOPPED"}


@router.post("/bots/{bot_id}/pause")
async def pause_bot_v2(bot_id: int, db: Session = Depends(get_db)):
    """Pause a Bot V2"""
    worker = get_worker()
    await worker.pause_bot(bot_id)

    return {"status": "PAUSED"}


@router.post("/bots/{bot_id}/resume")
async def resume_bot_v2(bot_id: int, db: Session = Depends(get_db)):
    """Resume a Bot V2"""
    worker = get_worker()
    await worker.resume_bot(bot_id)

    return {"status": "RUNNING"}


@router.get("/bots/{bot_id}")
async def get_bot_v2(bot_id: int, db: Session = Depends(get_db)):
    """Get Bot V2 details"""
    bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    balances = db.query(BotBalanceV2).filter(BotBalanceV2.bot_id == bot_id).first()
    state = db.query(BotStateV2).filter(BotStateV2.bot_id == bot_id).first()

    return {
        "bot_id": bot.id,
        "account_id": bot.account_id,
        "symbol": bot.symbol,
        "mode": bot.mode,
        "status": bot.status,
        "budget_usdt_initial": bot.budget_usdt_initial,
        "budget_usdt_current": bot.budget_usdt_current,
        "base_alloc_pct": bot.base_alloc_pct,
        "ref_price": bot.ref_price,
        "balances": {
            "base_asset": balances.base_asset if balances else None,
            "quote_asset": balances.quote_asset if balances else None,
            "base_free": balances.base_free if balances else 0,
            "quote_free": balances.quote_free if balances else 0,
            "total_value_usdt": balances.total_value_usdt if balances else 0
        } if balances else None,
        "state": json.loads(state.state_json) if state and state.state_json else None
    }


@router.get("/bots/{bot_id}/grids")
async def get_bot_grids_v2(bot_id: int, db: Session = Depends(get_db)):
    """Get Bot V2 grids"""
    grids = db.query(BotGridV2).filter(BotGridV2.bot_id == bot_id).order_by(BotGridV2.idx).all()
    return [{
        "id": g.id,
        "side": g.side,
        "idx": g.idx,
        "trigger_price_abs": g.trigger_price_abs,
        "qty_pct": g.qty_pct,
        "trailing_pct": g.trailing_pct,
        "state": g.state,
        "extreme_price": g.extreme_price,
        "threshold_price": g.threshold_price,
        "executed_qty": g.executed_qty,
        "executed_avg_price": g.executed_avg_price
    } for g in grids]


@router.get("/bots/{bot_id}/trades")
async def get_bot_trades_v2(bot_id: int, limit: int = 100, db: Session = Depends(get_db)):
    """Get Bot V2 trades"""
    trades = db.query(BotTradeV2).filter(
        BotTradeV2.bot_id == bot_id
    ).order_by(BotTradeV2.ts.desc()).limit(limit).all()

    return [{
        "id": t.id,
        "ts": t.ts.isoformat(),
        "side": t.side,
        "qty": t.qty,
        "price": t.price,
        "quote_qty": t.quote_qty,
        "fee_usdt": t.fee_usdt,
        "reason": t.reason
    } for t in trades]


@router.get("/bots")
async def list_bots_v2(account_id: Optional[int] = None, db: Session = Depends(get_db)):
    """List Bot V2 instances"""
    query = db.query(BotV2)
    if account_id:
        query = query.filter(BotV2.account_id == account_id)

    bots = query.all()
    return [{
        "bot_id": b.id,
        "account_id": b.account_id,
        "symbol": b.symbol,
        "status": b.status,
        "mode": b.mode,
        "budget_usdt_current": b.budget_usdt_current
    } for b in bots]

