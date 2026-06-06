"""
Bot Engine v5 – Single bot run: load state, DataHub price check, lock with heartbeat,
strategy_tick => actions => intents => persist => submit (weight-governed), update state, return next_run_at.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.adapters.binance_adapter import BinanceAdapter
from app.botengine.locks import symbol_lock_with_heartbeat
from app.botengine.state_store import load_state, save_state, ensure_state_row
from app.botengine.strategies.registry import get_strategy_safe
from app.botengine.models import (
    DcaGridTrailingConfig,
    config_from_ui_payload,
    config_multi_asset_from_payload,
    config_trdca_pro_from_payload,
    build_trdca_pro_state_skeleton,
    TrdcaProConfig,
)
from app.botengine.strategies.trdca_pro import strategy_tick as trdca_strategy_tick
from app.botengine.virtual_wallet import ensure_virtual_wallet, get_virtual_wallet
from app.botengine.intent_ledger import STATUS_PERSISTED, FINAL_STATUSES

logger = logging.getLogger(__name__)


def _get_db():
    from app.db.base import SessionLocal
    return SessionLocal()


async def run_one_bot_tick(bot_id: int, tick_id: str) -> float:
    """
    Run one bot tick. Returns next_run_at (monotonic time).
    - Load state; if price from DataHub is stale => no new intents (still can reconcile).
    - Acquire (account_id, symbol) lock with heartbeat before any submit.
    - Strategy tick => actions => persist intents => submit (via execution.run_actions).
    - Release lock in finally; compute next_run_at from strategy/cooldowns.
    """
    from app.db.models import Bot
    from app.botengine.execution import run_actions
    from app.botengine.orchestrator import _config_cache

    db = _get_db()
    try:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot:
            logger.warning("bot_run bot_id=%s not found", bot_id)
            return time.monotonic() + 60.0
        account_id = bot.account_id
        symbol = (bot.symbol or "").upper()
        status_lower = (str(bot.status or "").lower())
        if status_lower not in ("running", "paused_error"):
            return time.monotonic() + 60.0
        ensure_state_row(db, bot_id, account_id, symbol or "BTCUSDT")
        state = load_state(db, bot_id)
        raw = json.loads(bot.config_json or "{}")
        strategy_id_raw = (raw.get("strategy_id") or "").strip().lower()
        is_trdca = strategy_id_raw == "trdca_pro"
        is_multi = strategy_id_raw == "multi_asset_rebalance"
        if is_trdca:
            cfg = _config_cache.get(bot_id) or config_trdca_pro_from_payload(raw)
            symbol = "MULTI"
        else:
            cfg = _config_cache.get(bot_id) or (
                config_multi_asset_from_payload(raw) if is_multi else DcaGridTrailingConfig(raw)
            )
        _config_cache[bot_id] = cfg
        if state and state.get("run_id"):
            logger.info("BOT_RUN_ID run_id=%s bot_id=%s", state.get("run_id"), bot_id)
        if not state:
            if is_trdca:
                state = build_trdca_pro_state_skeleton(bot_id, account_id, getattr(cfg, "quote_asset", "USDT"))
            else:
                state = {"bot_id": bot_id, "account_id": account_id, "symbol": symbol, "status": "running", "cycle_id": 1, "state_version": 0}
            save_state(db, bot_id, account_id, state)

        from app.services.binance_assets import get_account_keys
        from app.db.models import User
        from app.services.test_account import is_test_account_username
        from app.core.config import is_worker_role
        bot_mode = (str(getattr(bot, "mode", None) or "").strip().lower())
        # Production rule: paper_mode only from DB; live bot never simulated
        paper_mode = (bot_mode == "paper")
        try:
            keys = await get_account_keys(account_id, db)
        except Exception as e:
            logger.warning("bot_run get_account_keys bot_id=%s err=%s", bot_id, e)
            keys = None
        has_keys = keys is not None
        # (A) Live bot + no keys => FAIL FAST: pause bot, do not run as paper
        if bot_mode == "live" and not has_keys:
            state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
            save_state(db, bot_id, account_id, state)
            bot.status = "paused_error"
            db.commit()
            logger.warning("BOT_LIVE_NO_KEYS bot_id=%s account_id=%s paused_error (FAIL FAST)", bot_id, account_id)
            return time.monotonic() + 30.0
        if not keys and not paper_mode:
            state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
            save_state(db, bot_id, account_id, state)
            return time.monotonic() + 30.0
        adapter = BinanceAdapter(account_id, keys, paper_mode=paper_mode)
        testnet = getattr(keys, "testnet", None) if keys else None
        logger.info(
            "BOT_MODE_CHECK bot_id=%s account_id=%s bot.mode=%s paper_mode=%s has_keys=%s is_worker_role=%s",
            bot_id, account_id, bot_mode, paper_mode, has_keys, is_worker_role(),
        )
        lock_symbol = symbol if symbol else "BTCUSDT"
        next_wake = time.monotonic() + (getattr(cfg, "tick_interval_ms", 5000) / 1000.0)
        if is_trdca:
            from app.botengine.orchestrator import _build_trdca_snapshot
            snapshot = await _build_trdca_snapshot(adapter, state, cfg)
            next_state, decision = trdca_strategy_tick(snapshot, state, cfg)
            state.update(next_state)
            state["last_tick_at"] = datetime.utcnow()
            dec_type = decision.get("type") or "NOOP"
            if dec_type == "ACTIONS":
                actions_list = decision.get("actions") or []
                if actions_list:
                    batch = actions_list[0]
                    legs = batch.get("legs") or []
                    prices = snapshot.get("prices_last") or {}
                    quote_asset = getattr(cfg, "quote_asset", "USDT")
                    actions = []
                    for leg in legs:
                        sym = (leg.get("symbol") or "").upper()
                        side = (leg.get("side") or "BUY").upper()
                        qty = float(leg.get("qty") or 0)
                        base = sym.replace(quote_asset, "") if quote_asset in sym else sym
                        price = prices.get(base) or prices.get(sym) or 0.0
                        actions.append({
                            "type": "place", "side": side, "symbol": sym,
                            "quantity": qty, "quote_qty": (qty * price) if side == "BUY" and price else None,
                            "client_order_id": leg.get("client_order_id"), "reason": "trdca_batch",
                        })
                    async with symbol_lock_with_heartbeat(account_id, lock_symbol, bot_id, get_db=_get_db):
                        await run_actions(bot_id, account_id, actions, state, cfg, adapter, db=db, loop_id=tick_id)
            save_state(db, bot_id, account_id, state)
            return next_wake
        price = adapter.get_price(symbol) if symbol and symbol != "MULTI" else None
        if symbol and symbol != "MULTI" and (not price or price <= 0):
            logger.debug("bot_run bot_id=%s tick_id=%s price=stale symbol=%s", bot_id, tick_id, symbol)
            return next_wake
        if is_multi or symbol == "MULTI":
            price = 1.0
        base_balance = float(state.get("base_balance") or 0)
        quote_balance = float(state.get("quote_balance") or 0)
        ensure_virtual_wallet(db, bot_id, account_id, symbol or "BTCUSDT", float(getattr(cfg, "initial_capital_usdt", 0) or 0))
        vb, vq = get_virtual_wallet(db, bot_id, symbol or "BTCUSDT")
        state["base_balance"] = vb
        state["quote_balance"] = vq
        base_balance, quote_balance = vb, vq
        strategy = get_strategy_safe(raw)
        actions, next_wake_sec = strategy.tick(state, cfg, price or 0, base_balance, quote_balance)
        state["last_tick_at"] = datetime.utcnow()
        interval_sec = getattr(cfg, "interval_sec", 3600) if is_multi else (getattr(cfg, "tick_interval_ms", 5000) / 1000.0)
        next_wake = time.monotonic() + max(0.5, next_wake_sec if next_wake_sec is not None else interval_sec)
        if actions:
            async with symbol_lock_with_heartbeat(account_id, lock_symbol, bot_id, get_db=_get_db):
                await run_actions(bot_id, account_id, actions, state, cfg, adapter, db=db, loop_id=tick_id)
        save_state(db, bot_id, account_id, state)
        return next_wake
    except Exception as e:
        logger.exception("bot_run bot_id=%s tick_id=%s: %s", bot_id, tick_id, e)
        return time.monotonic() + 30.0
    finally:
        db.close()
