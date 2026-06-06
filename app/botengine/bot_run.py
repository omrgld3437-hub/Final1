"""
Bot Engine v5 – Single bot run: load state, DataHub price check, lock with heartbeat,
strategy_tick => actions => intents => persist => submit (weight-governed), update state, return next_run_at.
"""

from __future__ import annotations
import json
import logging
import time
from datetime import datetime

from app.botengine.adapters.binance_adapter import BinanceAdapter
from app.botengine.locks import (
    lease_still_valid,
    symbol_lock_with_heartbeat,
    trade_lock_symbol,
)
from app.botengine.state_store import load_state, save_state, ensure_state_row
from app.botengine.strategies.registry import get_strategy_safe
from app.botengine.models import (
    DcaGridTrailingConfig,
    config_multi_asset_from_payload,
    config_trdca_pro_from_payload,
    build_trdca_pro_state_skeleton,
)
from app.botengine.strategies.trdca_pro import strategy_tick as trdca_strategy_tick
from app.botengine.virtual_wallet import ensure_virtual_wallet, get_virtual_wallet

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
        status_lower = str(bot.status or "").lower()
        if status_lower != "running":
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
                config_multi_asset_from_payload(raw)
                if is_multi
                else DcaGridTrailingConfig(raw)
            )
        from app.botengine.orchestrator import _config_cache_put

        _config_cache_put(bot_id, cfg)
        from app.services.test_account import test_account_paper_execution
        from app.core.config import is_worker_role

        bot_mode = str(getattr(bot, "mode", None) or "").strip().lower()
        acct_test = test_account_paper_execution(account_id, db)
        if state and state.get("run_id"):
            if acct_test:
                logger.debug(
                    "BOT_RUN_ID run_id=%s bot_id=%s (test)", state.get("run_id"), bot_id
                )
            else:
                logger.debug(
                    "BOT_RUN_ID run_id=%s bot_id=%s", state.get("run_id"), bot_id
                )
        if not state:
            if is_trdca:
                state = build_trdca_pro_state_skeleton(
                    bot_id, account_id, getattr(cfg, "quote_asset", "USDT")
                )
            else:
                state = {
                    "bot_id": bot_id,
                    "account_id": account_id,
                    "symbol": symbol,
                    "status": "running",
                    "cycle_id": 1,
                    "state_version": 0,
                }
            save_state(db, bot_id, account_id, state)
        paper_mode = acct_test or (bot_mode == "paper")
        keys = None
        has_keys = False
        if not acct_test:
            from app.services.binance_assets import get_account_keys

            try:
                keys = await get_account_keys(account_id, db)
            except Exception as e:
                logger.info(
                    "bot_run get_account_keys bot_id=%s err=%s (tick skipped, retry)",
                    bot_id,
                    e,
                )
                keys = None
            has_keys = keys is not None
        # (A) Live bot + no keys => FAIL FAST: pause bot (test hesabı hariç)
        if bot_mode == "live" and not has_keys and not acct_test:
            state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
            save_state(db, bot_id, account_id, state)
            bot.status = "paused_error"
            db.commit()
            try:
                from app.services import audit as _audit_svc

                _audit_svc.log_event(
                    db,
                    actor_type="system",
                    event_type="BOT_PAUSED_NO_KEYS",
                    severity="WARN",
                    target_account_id=account_id,
                    meta={"bot_id": bot_id, "error_code": "ACCOUNT_KEYS_MISSING"},
                )
            except Exception:
                pass
            logger.warning(
                "BOT_LIVE_NO_KEYS bot_id=%s account_id=%s paused_error (FAIL FAST)",
                bot_id,
                account_id,
            )
            return time.monotonic() + 30.0
        if not keys and not paper_mode:
            state["last_error_code"] = "ACCOUNT_KEYS_MISSING"
            save_state(db, bot_id, account_id, state)
            return time.monotonic() + 30.0
        adapter = BinanceAdapter(account_id, keys, paper_mode=paper_mode)
        getattr(keys, "testnet", None) if keys else None
        mode_log = (
            "BOT_MODE_CHECK bot_id=%s account_id=%s bot.mode=%s paper_mode=%s has_keys=%s is_worker_role=%s test_account=%s",
            bot_id,
            account_id,
            bot_mode,
            paper_mode,
            has_keys,
            is_worker_role(),
            acct_test,
        )
        if acct_test:
            logger.debug(*mode_log)
        else:
            logger.debug(*mode_log)
        lock_symbol = trade_lock_symbol(account_id, symbol)
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
                        base = (
                            sym.replace(quote_asset, "") if quote_asset in sym else sym
                        )
                        price = prices.get(base) or prices.get(sym) or 0.0
                        actions.append(
                            {
                                "type": "place",
                                "side": side,
                                "symbol": sym,
                                "quantity": qty,
                                "quote_qty": (qty * price)
                                if side == "BUY" and price
                                else None,
                                "client_order_id": leg.get("client_order_id"),
                                "reason": "trdca_batch",
                            }
                        )
                    async with symbol_lock_with_heartbeat(
                        account_id, lock_symbol, bot_id, get_db=_get_db
                    ) as acquired:
                        if acquired and lease_still_valid(
                            db, account_id, lock_symbol, bot_id
                        ):
                            await run_actions(
                                bot_id,
                                account_id,
                                actions,
                                state,
                                cfg,
                                adapter,
                                db=db,
                                loop_id=tick_id,
                            )
            save_state(db, bot_id, account_id, state)
            if state.get("_pending_connectivity_stable"):
                try:
                    from app.services.binance_connectivity import (
                        flush_pending_connectivity_stable,
                    )

                    flush_pending_connectivity_stable(
                        db, bot_id, after_loop_restart=True
                    )
                except Exception:
                    pass
            return next_wake
        price = adapter.get_price(symbol) if symbol != "MULTI" else None
        if symbol and symbol != "MULTI" and (not price or price <= 0):
            logger.debug(
                "bot_run bot_id=%s tick_id=%s price=stale symbol=%s",
                bot_id,
                tick_id,
                symbol,
            )
            return next_wake
        if is_multi or symbol == "MULTI":
            price = 1.0
        base_balance = float(state.get("base_balance") or 0)
        quote_balance = float(state.get("quote_balance") or 0)
        ensure_virtual_wallet(
            db,
            bot_id,
            account_id,
            symbol or "BTCUSDT",
            float(getattr(cfg, "initial_capital_usdt", 0) or 0),
        )
        vb, vq = get_virtual_wallet(db, bot_id, symbol or "BTCUSDT")
        state["base_balance"] = vb
        state["quote_balance"] = vq
        base_balance, quote_balance = vb, vq
        strategy = get_strategy_safe(raw)
        actions, next_wake_sec = strategy.tick(
            state, cfg, price or 0, base_balance, quote_balance
        )
        try:
            from app.botengine.strategies.grid_outage_recovery import (
                flush_outage_recovery_log_to_events,
            )

            flush_outage_recovery_log_to_events(db, bot_id, account_id, state)
        except Exception as olog_ex:
            logger.debug("outage_recovery_log bot_id=%s: %s", bot_id, olog_ex)
        state["last_tick_at"] = datetime.utcnow()
        interval_sec = (
            getattr(cfg, "interval_sec", 3600)
            if is_multi
            else (getattr(cfg, "tick_interval_ms", 5000) / 1000.0)
        )
        next_wake = time.monotonic() + max(
            0.5, next_wake_sec if next_wake_sec is not None else interval_sec
        )
        if actions:
            async with symbol_lock_with_heartbeat(
                account_id, lock_symbol, bot_id, get_db=_get_db
            ) as acquired:
                if acquired and lease_still_valid(db, account_id, lock_symbol, bot_id):
                    await run_actions(
                        bot_id,
                        account_id,
                        actions,
                        state,
                        cfg,
                        adapter,
                        db=db,
                        loop_id=tick_id,
                    )
        save_state(db, bot_id, account_id, state)
        if state.get("_pending_connectivity_stable"):
            try:
                from app.services.binance_connectivity import (
                    flush_pending_connectivity_stable,
                )

                flush_pending_connectivity_stable(db, bot_id, after_loop_restart=True)
            except Exception:
                pass
        return next_wake
    except Exception as e:
        logger.exception("bot_run bot_id=%s tick_id=%s: %s", bot_id, tick_id, e)
        return time.monotonic() + 30.0
    finally:
        db.close()
