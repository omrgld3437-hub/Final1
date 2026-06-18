"""
Execution: strategy actions -> orders via adapter. Idempotency, guards, apply_fill, cycle reset.
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy.orm import Session as SQLASession

from app.bot.ledger import Ledger
from app.botengine.adapters.binance_adapter import BinanceAdapter
from app.botengine.models import DcaGridTrailingConfig
from app.botengine.dca_manager import MaxBuyLevelsError, assert_can_open_buy_level
from app.botengine.risk import acquire_bot_lock, check_idempotency, guard_min_notional
from app.botengine.intent_ledger import (
    build_intent_id,
    build_client_order_id,
    upsert_intent,
    update_intent_filled,
    update_intent_sent,
    update_intent_unknown,
    update_intent_submitting,
)
from app.botengine.kill_switch import check_kill_switch
from app.botengine.locks import lease_still_valid, trade_lock_symbol
from app.botengine.state_store import append_event, load_state, save_state
from app.botengine.virtual_wallet import (
    check_virtual_budget,
    get_virtual_wallet,
    update_virtual_after_fill,
)
from app.botengine.cycle_ledger import (
    CYCLE_FILL_REASONS,
    PNL_MODE_CASH,
    PNL_MODE_INVENTORY,
    ensure_cycle_ledger,
    cycle_ledger_add_fill,
    get_cycle_type_and_base_delta,
)
from app.botengine.fee_utils import parse_fill_commission
from app.botengine.strategies.dca_grid_trailing import (
    apply_fill_to_state,
    cycle_reset_after_fill,
    _avg_buy_price_total,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Binance REST yavaş ortamda 3s yetersiz; reconcile yine devreye girer ama gecikme + ORDER_TIMEOUT uyarısı üretir.
EXEC_ORDER_TIMEOUT_SEC = 15.0


# ---------------------------------------------------------------------------
# Cycle event enrichment helpers (CYCLE_END / CYCLE_START meta zenginleştirme)
# ---------------------------------------------------------------------------


def _cycle_duration_sec(
    state: Dict[str, Any], ledger: Optional[Dict[str, Any]]
) -> Optional[float]:
    """Tur süresi saniye cinsinden. opened_at → şimdi."""
    opened = None
    if ledger:
        opened = ledger.get("started_at")
    if not opened:
        opened = state.get("cycle_opened_at")
    if not opened:
        return None
    try:
        s = str(opened).strip().replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
    except Exception:
        return None


def _grid_utilization(state: Dict[str, Any], config: Any) -> Dict[str, Any]:
    """Tur boyunca kaç sell/buy grid'i tetiklendi."""
    n = len(getattr(config, "sell_grids", []) or [])
    m = len(getattr(config, "buy_grids", []) or [])
    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    return {
        "sell_grids_fired": sum(1 for x in sell_fired if x),
        "sell_grids_total": n,
        "buy_grids_fired": sum(1 for x in buy_fired if x),
        "buy_grids_total": m,
    }


def _ledger_avg_prices(ledger: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ledger'dan ortalama alış/satış fiyatları."""
    if not ledger:
        return {}
    bq = float(ledger.get("buy_qty_total") or 0)
    bv = float(ledger.get("buy_quote_total") or 0)
    sq = float(ledger.get("sell_qty_total") or 0)
    sv = float(ledger.get("sell_quote_total") or 0)
    result: Dict[str, Any] = {}
    if bq > 0 and bv > 0:
        result["avg_buy_price"] = round(bv / bq, 8)
    if sq > 0 and sv > 0:
        result["avg_sell_price"] = round(sv / sq, 8)
    return result


def _cumulative_pnl(state: Dict[str, Any]) -> Dict[str, Any]:
    """Tüm tamamlanan turların kümülatif K/Z toplamı."""
    completed = state.get("completed_cycle_dual_pnls") or []
    cash_total = 0.0
    inv_total = 0.0
    for c in completed:
        cash_total += float(c.get("cash_pnl_usdt") or 0)
        inv_total += float(c.get("inventory_coin_adv_qty") or 0)
    return {
        "cum_cash_pnl_usdt": round(cash_total, 4),
        "cum_inventory_qty": round(inv_total, 8),
        "cum_cycles": len(completed),
    }


def _grid_trigger_prices(config: Any, reference_price: float) -> Dict[str, Any]:
    """Tüm sell/buy grid seviyelerinin tetikleme fiyatları."""
    ref = float(reference_price or 0)
    if ref <= 0:
        return {}
    sell_grids = getattr(config, "sell_grids", []) or []
    buy_grids = getattr(config, "buy_grids", []) or []
    sell_triggers = {}
    for i, g in enumerate(sell_grids):
        pct = float(g.get("sell_grid_pct") or g.get("trigger_pct") or 0)
        sell_triggers[f"Y{i + 1}"] = round(ref * (1 + pct / 100.0), 8)
    buy_triggers = {}
    for i, g in enumerate(buy_grids):
        pct = float(g.get("buy_grid_pct") or g.get("trigger_pct") or 0)
        buy_triggers[f"A{i + 1}"] = round(ref * (1 - pct / 100.0), 8)
    return {"sell_trigger_prices": sell_triggers, "buy_trigger_prices": buy_triggers}


def _rebalance_ratio(base_bal: float, quote_bal: float, price: float) -> Dict[str, Any]:
    """Gerçek base/quote oranı ve hedeften sapma."""
    if price <= 0:
        return {}
    base_usd = round(base_bal * price, 2)
    quote_usd = round(quote_bal, 2)
    total = base_usd + quote_usd
    if total <= 0:
        return {}
    return {
        "base_usd": base_usd,
        "quote_usd": quote_usd,
        "base_ratio_pct": round(base_usd / total * 100, 2),
        "quote_ratio_pct": round(quote_usd / total * 100, 2),
    }


def _build_cycle_end_meta(
    state: Dict[str, Any],
    config: Any,
    ledger: Optional[Dict[str, Any]],
    base_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """CYCLE_END meta'sını ek analitik verilerle zenginleştir."""
    meta = dict(base_meta)
    # Tur süresi
    dur = _cycle_duration_sec(state, ledger)
    if dur is not None:
        meta["duration_sec"] = dur
    # Grid dolum oranı (reset'ten önce çağrılmalı)
    meta.update(_grid_utilization(state, config))
    # Ortalama alış/satış fiyatları
    meta.update(_ledger_avg_prices(ledger))
    # Fiyat aralığı
    ph = state.get("_cycle_price_high")
    pl = state.get("_cycle_price_low")
    if ph is not None:
        meta["price_high"] = round(float(ph), 8)
    if pl is not None:
        meta["price_low"] = round(float(pl), 8)
    # Kümülatif K/Z (Bu tur dahil edilmeden önceki toplam; tur bittikten sonra state güncellenir)
    meta.update(_cumulative_pnl(state))
    return meta


def _build_cycle_start_meta(
    state: Dict[str, Any],
    config: Any,
    base_meta: Dict[str, Any],
    fill_price: float,
    base_bal: float,
    quote_bal: float,
) -> Dict[str, Any]:
    """CYCLE_START meta'sını ek analitik verilerle zenginleştir."""
    meta = dict(base_meta)
    # Grid tetikleme fiyatları
    meta.update(_grid_trigger_prices(config, fill_price))
    # Base/Quote rebalance oranı
    meta.update(_rebalance_ratio(base_bal, quote_bal, fill_price))
    # Hedef tahsis yüzdeleri
    meta["target_base_alloc_pct"] = float(getattr(config, "base_alloc_pct", 50) or 50)
    meta["target_quote_alloc_pct"] = float(getattr(config, "quote_alloc_pct", 50) or 50)
    # Breakeven tahmini: avg_cost * (1 + sell_fee) / (1 - sell_fee) yaklaşık
    sell_fee = float(getattr(config, "sell_fee_rate", 0.001) or 0.001)
    profit_exit_rise = float(getattr(config, "profit_exit_rise_pct", 1.0) or 1.0)
    estimated_breakeven = round(fill_price * (1 + sell_fee * 2), 6)
    estimated_profit_target = round(fill_price * (1 + profit_exit_rise / 100.0), 6)
    meta["estimated_breakeven"] = estimated_breakeven
    meta["estimated_profit_target"] = estimated_profit_target
    # Fiyat aralığı sıfırla (yeni tur için)
    state.pop("_cycle_price_high", None)
    state.pop("_cycle_price_low", None)
    state["_cycle_price_high"] = round(fill_price, 10)
    state["_cycle_price_low"] = round(fill_price, 10)
    return meta


# Sanal vs borsa bakiye doğrulama eşikleri (grid: locked emirler free'ye düşer)
BALANCE_DRIFT_BASE_WARN_PCT = 15.0
BALANCE_DRIFT_QUOTE_WARN_USD = 10.0
BALANCE_DRIFT_WORKER_LOG_COOLDOWN_SEC = 3600.0
_LAST_BALANCE_DRIFT_WORKER_LOG: Dict[int, Tuple[str, float]] = {}


def _asset_total_balance(balances: Dict[str, Any], asset: str) -> float:
    """free + locked — grid açık emirlerindeki kilitli miktar dahil."""
    row = balances.get(asset) or {}
    if not isinstance(row, dict):
        return 0.0
    return float(row.get("free") or 0) + float(row.get("locked") or 0)


def _compute_balance_drift_metrics(
    virt_base: float,
    virt_quote: float,
    real_base: float,
    real_quote: float,
) -> Tuple[float, float]:
    """Base sapma % ve quote mutlak sapma (USDT)."""
    ref_base = max(abs(virt_base), abs(real_base), 1e-8)
    base_drift_pct = (
        abs(real_base - virt_base) / ref_base * 100.0 if ref_base > 0 else 0.0
    )
    quote_drift = abs(real_quote - virt_quote)
    return base_drift_pct, quote_drift


def _balance_drift_severity(base_drift_pct: float, quote_drift: float) -> str:
    if (
        base_drift_pct > BALANCE_DRIFT_BASE_WARN_PCT
        or quote_drift > BALANCE_DRIFT_QUOTE_WARN_USD
    ):
        return "WARN"
    return "INFO"


def _should_log_balance_drift_worker(
    bot_id: int, base_drift_pct: float, quote_drift: float
) -> bool:
    """Aynı sapma profili için worker.log WARNING en fazla saatte bir."""
    key = f"{round(base_drift_pct, 1)}:{round(quote_drift, 2)}"
    now = time.time()
    prev = _LAST_BALANCE_DRIFT_WORKER_LOG.get(int(bot_id))
    if (
        prev
        and prev[0] == key
        and (now - prev[1]) < BALANCE_DRIFT_WORKER_LOG_COOLDOWN_SEC
    ):
        return False
    _LAST_BALANCE_DRIFT_WORKER_LOG[int(bot_id)] = (key, now)
    return True


async def _emit_balance_sync_check(
    adapter: Any,
    db: Any,
    bot_id: int,
    account_id: int,
    symbol: str,
    state: Dict[str, Any],
    price: float,
) -> None:
    """
    Periyodik sanal vs gerçek Binance bakiye doğrulaması.
    Gerçek bakiye = free+locked (grid açık emirleri dahil).
    WARN eşiği: base >15% veya USDT >$10; aynı profil en fazla saatte bir.
    Her 50 tick'te bir çağrılır (live botlarda).
    """
    try:
        balances = await adapter.get_account_balances()
    except Exception:
        return  # Binance erişilemiyorsa sessiz geç
    base_asset = (symbol or "BTCUSDT").replace("USDT", "").replace(
        "BUSD", ""
    ).strip() or "BTC"
    real_base = _asset_total_balance(balances, base_asset)
    real_quote = _asset_total_balance(balances, "USDT")
    virt_base = float(state.get("base_balance") or 0)
    virt_quote = float(state.get("quote_balance") or 0)
    base_drift_pct, quote_drift = _compute_balance_drift_metrics(
        virt_base, virt_quote, real_base, real_quote
    )
    severity = _balance_drift_severity(base_drift_pct, quote_drift)
    if severity == "WARN" and not _should_log_balance_drift_worker(
        bot_id, base_drift_pct, quote_drift
    ):
        return
    if severity == "WARN":
        msg = (
            f"Bakiye sapması tespit edildi · "
            f"Sanal {base_asset}: {virt_base:.6f} / Gerçek: {real_base:.6f} "
            f"(sapma %{base_drift_pct:.1f}) · "
            f"Sanal USDT: ${virt_quote:.2f} / Gerçek: ${real_quote:.2f} "
            f"(sapma ${quote_drift:.2f})"
        )
    else:
        severity = "INFO"
        msg = (
            f"Bakiye senkronizasyonu ✓ · "
            f"Sanal {base_asset}: {virt_base:.6f} ≈ Gerçek: {real_base:.6f} · "
            f"Sanal USDT: ${virt_quote:.2f} ≈ Gerçek: ${real_quote:.2f}"
        )
    from app.botengine.state_store import append_event as _ae

    _ae(
        db,
        bot_id,
        account_id,
        severity,
        msg,
        {
            f"virtual_{base_asset.lower()}": round(virt_base, 8),
            f"real_{base_asset.lower()}": round(real_base, 8),
            "virtual_usdt": round(virt_quote, 2),
            "real_usdt": round(real_quote, 2),
            f"drift_{base_asset.lower()}_pct": round(base_drift_pct, 2),
            "drift_usdt": round(quote_drift, 2),
            "price": round(float(price or 0), 8),
            "error_code": "BALANCE_DRIFT_WARN"
            if severity == "WARN"
            else "BALANCE_SYNC_OK",
        },
    )
    if severity == "WARN":
        logger.warning(
            "BOT_BALANCE_DRIFT bot_id=%s account_id=%s %s_drift=%.2f%% usdt_drift=%.2f",
            bot_id,
            account_id,
            base_asset.lower(),
            base_drift_pct,
            quote_drift,
        )


def _maybe_emit_grid_summary(
    db: Any,
    bot_id: int,
    account_id: int,
    state: Dict[str, Any],
    config: Any,
    new_cycle_id: int,
) -> None:
    """Her 10 turda bir grid kullanım özeti emitla (GRID_SUMMARY event)."""
    if new_cycle_id % 10 != 1 or new_cycle_id <= 1:
        return
    try:
        completed = state.get("completed_cycle_dual_pnls") or []
        # Son 10 tur
        last10 = completed[-10:] if len(completed) >= 10 else completed
        cash_turs = sum(1 for c in last10 if c.get("cycle_type") == "CASH")
        inv_turs = sum(1 for c in last10 if c.get("cycle_type") == "INVENTORY")
        cash_sum = sum(float(c.get("cash_pnl_usdt") or 0) for c in last10)
        inv_sum = sum(float(c.get("inventory_coin_adv_qty") or 0) for c in last10)
        symbol = getattr(config, "symbol", "") or state.get("symbol") or ""
        base_asset = (
            symbol.replace("USDT", "").replace("BUSD", "") if symbol else "BASE"
        )
        # Kümülatif toplamlar
        cum = _cumulative_pnl(state)
        from app.botengine.state_store import append_event as _ae

        _ae(
            db,
            bot_id,
            account_id,
            "GRID_SUMMARY",
            f"Tur {new_cycle_id - 10}–{new_cycle_id - 1} özet · "
            f"Nakit: {cash_turs} tur, +${round(cash_sum, 2)} · "
            f"Envanter: {inv_turs} tur, +{round(inv_sum, 4)} {base_asset}",
            {
                "from_cycle": new_cycle_id - 10,
                "to_cycle": new_cycle_id - 1,
                "cash_cycles": cash_turs,
                "inventory_cycles": inv_turs,
                "period_cash_pnl_usdt": round(cash_sum, 4),
                f"period_inventory_{base_asset.lower()}_qty": round(inv_sum, 8),
                "cum_cash_pnl_usdt": cum["cum_cash_pnl_usdt"],
                f"cum_inventory_{base_asset.lower()}_qty": cum["cum_inventory_qty"],
                "cum_cycles_total": cum["cum_cycles"],
            },
        )
    except Exception as ex:
        logger.debug("_maybe_emit_grid_summary bot_id=%s: %s", bot_id, ex)


# Track initial_allocation skip count per (bot_id, action_key) for WARN when > 3
_initial_alloc_skip_count: Dict[Tuple[int, str], int] = {}

# 401 / Invalid API-key: aynı bot için WARNING + event en fazla 10 dk'da bir (log/event flood önleme)
_exec_401_log_throttle: Dict[Tuple[int, ...], float] = {}
_EXEC_401_THROTTLE_SEC = 600.0
# 401 sonrası order denemeyi bu süre (saniye) boyunca durdur (state["backoff_until"])
_EXEC_401_BACKOFF_SEC = 300.0


def _is_401_unauthorized(err: Exception) -> bool:
    s = str(err).lower()
    return (
        "401" in s
        or "unauthorized" in s
        or "invalid api-key" in s
        or "-2015" in s
        or "permissions for action" in s
    )


def _should_log_exec_401(bot_id: int) -> bool:
    import time as _t

    key = (bot_id,)
    now = _t.monotonic()
    if (
        key in _exec_401_log_throttle
        and (now - _exec_401_log_throttle[key]) < _EXEC_401_THROTTLE_SEC
    ):
        return False
    _exec_401_log_throttle[key] = now
    return True


def _append_skip(
    db: Optional[SQLASession],
    bot_id: int,
    account_id: int,
    skip_reason: str,
    message: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    if db is None:
        return
    payload = dict(meta or {})
    payload["skip_reason"] = skip_reason
    append_event(db, bot_id, account_id, "SKIP_REASON", message, payload)


def _cycle_meta(
    state: Dict[str, Any], symbol: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    meta = {"cycle_id": int(state.get("cycle_id") or 1)}
    if symbol:
        meta["symbol"] = symbol
    meta.update(extra)
    return meta


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _current_cycle_sell_grid_qty(state: Dict[str, Any]) -> float:
    ledger = state.get("cycle_ledger_current")
    total = 0.0
    if isinstance(ledger, dict):
        for fill in ledger.get("fills") or []:
            if not isinstance(fill, dict):
                continue
            if (fill.get("side") or "").upper() != "SELL":
                continue
            if (fill.get("reason") or "").strip() != "trail_sell_grid":
                continue
            total += _num(fill.get("qty"))
    if total > 0:
        return total
    for row in state.get("sell_history") or []:
        if not isinstance(row, dict) or row.get("grid_index") is None:
            continue
        total += _num(row.get("qty"))
    return total


def _boost_reentry_quote_to_next_lot(
    state: Dict[str, Any],
    quote_qty: float,
    price: float,
    available_quote: float,
    filters: Dict[str, Any],
    buffer_pct: float = 0.001,
) -> Optional[Dict[str, float]]:
    """Raise re-entry quote enough to buy at least one lot step more than sold."""
    if quote_qty <= 0 or price <= 0 or available_quote <= quote_qty:
        return None
    sold_qty = _current_cycle_sell_grid_qty(state)
    if sold_qty <= 0:
        return None
    try:
        from app.botengine.order_qty import quantize_qty_down

        step_str = str(
            filters.get("step_size_str") or filters.get("stepSize") or ""
        ).strip()
        if not step_str:
            step_str = "0.00001"
        step = Decimal(step_str)
        if step <= 0:
            return None
        current_lot_qty, _ = quantize_qty_down(
            float(quote_qty) / float(price), step_str
        )
        if current_lot_qty > sold_qty + (float(step) / 2.0):
            return None
        sold_d = Decimal(str(sold_qty))
        price_d = Decimal(str(price))
        available_d = Decimal(str(available_quote))
        old_quote_d = Decimal(str(quote_qty))
        steps = (sold_d / step).to_integral_value(rounding=ROUND_FLOOR)
        target_qty_d = (steps + 1) * step
        if target_qty_d <= sold_d:
            target_qty_d += step
        buffer_d = Decimal("1") + Decimal(str(max(0.0, buffer_pct)))
        target_quote_d = target_qty_d * price_d * buffer_d
        if target_quote_d <= old_quote_d:
            return None
        if target_quote_d > available_d:
            return None
        return {
            "old_quote_qty": float(old_quote_d),
            "new_quote_qty": float(target_quote_d),
            "sold_qty": float(sold_d),
            "current_lot_qty": float(current_lot_qty),
            "target_qty": float(target_qty_d),
            "step_size": float(step),
        }
    except Exception:
        return None


def _fill_ts_from_order(order: Dict[str, Any]) -> datetime:
    """Binance order yanıtından UTC fill zamanı (transactTime öncelikli)."""
    for key in ("transactTime", "updateTime", "workingTime"):
        raw = order.get(key)
        if raw is None:
            continue
        try:
            ms = int(raw)
            if ms > 0:
                return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError):
            continue
    return datetime.now(timezone.utc)


def _parse_binance_order_error(e: Exception) -> Dict[str, Any]:
    """Extract Binance code/msg from adapter errors; map to skip_reason hints."""
    import json as _json
    import httpx
    from app.services.binance_spot import BinanceSignedError

    out: Dict[str, Any] = {
        "binance_code": None,
        "binance_msg": None,
        "skip_reason": "ORDER_FAILED",
        "error": str(e)[:500],
        "request_id": None,
    }
    try:
        if isinstance(e, BinanceSignedError):
            out["binance_code"] = getattr(e, "code", None)
            out["binance_msg"] = getattr(e, "msg", None) or ""
            data = getattr(e, "data", None)
            if isinstance(data, dict):
                out["request_id"] = (
                    data.get("requestId") or data.get("request_id")
                ) or None
        elif isinstance(e, httpx.HTTPStatusError) and getattr(e, "response", None):
            resp = e.response
            body = (getattr(resp, "text", None) or "")[:500]
            try:
                b = _json.loads(body) if body else {}
                if isinstance(b, dict):
                    out["binance_code"] = b.get("code")
                    out["binance_msg"] = b.get("msg")
                    out["request_id"] = (
                        b.get("requestId") or b.get("request_id")
                    ) or None
            except Exception:
                if body and "-2010" in body:
                    out["binance_code"] = -2010
            if out["request_id"] is None and hasattr(resp, "headers"):
                out["request_id"] = (
                    resp.headers.get("X-MBX-REQUEST-ID")
                    or resp.headers.get("x-request-id")
                ) or None
        code = out["binance_code"]
        if code == -2010:
            out["skip_reason"] = "INSUFFICIENT_BALANCE"
        elif code in (-1013, -1111, -1016):
            out["skip_reason"] = "LOT_SIZE"
        if out["binance_msg"]:
            out["error"] = str(out["binance_msg"])[:500]
    except Exception:
        pass
    return out


def _sync_initial_done_from_db(
    state: Dict[str, Any], db: "Session", bot_id: int
) -> bool:
    """If DB already has initial_allocation_done (from a real fill), copy to state. Never set ia_done=True here."""
    fresh = load_state(db, bot_id)
    if fresh and fresh.get("initial_allocation_done"):
        for k in (
            "initial_allocation_done",
            "reference_price",
            "cycle_id",
            "initial_alloc_base_qty",
            "initial_alloc_price",
            "initial_alloc_fee_quote",
            "base_balance",
            "quote_balance",
            "free_quote",
            "locked_quote",
            "last_fill_snapshot",
        ):
            if k in fresh:
                state[k] = fresh[k]
        return True
    return False


async def _write_fill_snapshot_to_state(
    state: Dict[str, Any],
    adapter: BinanceAdapter,
    config: DcaGridTrailingConfig,
    symbol: str,
) -> None:
    """
    After ORDER_FILLED: single source-of-truth snapshot from exchange + state.
    Writes free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total to state.
    Reduces virtual/real drift and overcommit risk.
    """
    try:
        balances = await adapter.get_account_balances()
    except Exception as e:
        err_s = str(e)
        # Emir öncesi bakiye kontrolü ile aynı 8s pencerede ikinci /account çağrısı
        # throttle'a takılır; apply_fill_to_state zaten state'i güncelledi.
        if "REST blocked: throttle" in err_s:
            logger.info(
                "write_fill_snapshot account throttled (%s) — using post-fill state balances",
                err_s,
            )
        else:
            logger.warning(
                "write_fill_snapshot get_account_balances failed: %s (using post-fill state)",
                e,
            )
        balances = None
    quote_asset = "USDT"
    if balances and quote_asset in balances:
        q = balances[quote_asset] or {}
        free_quote = _num(q.get("free"))
        locked_quote = _num(q.get("locked"))
    else:
        free_quote = _num(state.get("quote_balance"))
        locked_quote = 0.0
    base_qty = _num(state.get("base_balance"))
    avg_cost = _avg_buy_price_total(state)
    if avg_cost is None:
        avg_cost = _num(state.get("reference_price"))
    cycle_pnls = state.get("cycle_pnls") or []
    realized_pnl = sum(_num(c.get("pnl_usdt")) for c in cycle_pnls) + _num(
        state.get("realized_pnl_usdt_cycle")
    )
    fees_total = sum(_num(c.get("fees_usdt")) for c in cycle_pnls) + _num(
        state.get("fees_paid_usdt_cycle")
    )
    from datetime import datetime, timezone

    snapshot_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "free_quote": free_quote,
        "locked_quote": locked_quote,
        "base_qty": base_qty,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "fees_total": fees_total,
        "snapshot_at": snapshot_at,
    }
    state["last_fill_snapshot"] = snapshot
    state["free_quote"] = free_quote
    state["locked_quote"] = locked_quote
    logger.debug(
        "BOT_FILL_SNAPSHOT free_quote=%.2f locked_quote=%.2f base_qty=%.6f avg_cost=%.4f realized_pnl=%.4f fees_total=%.4f",
        free_quote,
        locked_quote,
        base_qty,
        avg_cost,
        realized_pnl,
        fees_total,
    )


async def run_actions(
    bot_id: int,
    account_id: int,
    actions: List[Dict[str, Any]],
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
    adapter: BinanceAdapter,
    db: Optional["Session"] = None,
    loop_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Execute actions (place only). Updates state in place. Returns list of {order_id, side, fill_qty, fill_price, fee, reason}.
    """
    results = []
    t0 = time.perf_counter()
    logger.info("run_actions start bot_id=%s", bot_id)
    try:
        check_kill_switch()
    except Exception as kill_err:
        logger.warning("run_actions kill_switch bot_id=%s: %s", bot_id, kill_err)
        return results
    async with await acquire_bot_lock(bot_id):
        pending_buy_level_actions = 0
        for a in actions:
            if a.get("type") != "place":
                continue
            reason = a.get("reason") or ""
            state_ver = state.get("state_version", 0)
            if reason == "initial_allocation":
                key = f"initial_allocation_{bot_id}_{state_ver}_0"
            else:
                key = (
                    f"{reason}_{a.get('grid_index', 0)}_{a.get('client_order_id', '')}"
                )
            try:
                binance_balances: Optional[Dict[str, Any]] = None
                # ia_done: only ever set after real fill (see below). On skip we never set it.
                if reason == "initial_allocation" and state.get(
                    "initial_allocation_done"
                ):
                    if db is not None and _sync_initial_done_from_db(state, db, bot_id):
                        logger.info(
                            "bot_engine execution skip initial_allocation already_done bot_id=%s sync_state",
                            bot_id,
                        )
                    continue
                if check_idempotency(bot_id, key):
                    if reason == "initial_allocation" and db is not None:
                        _sync_initial_done_from_db(state, db, bot_id)
                        if state.get("initial_allocation_done"):
                            save_state(db, bot_id, account_id, state)
                    logger.info(
                        "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=IDEMPOTENT_LOCK action_key=%s",
                        bot_id,
                        reason,
                        key,
                    )
                    if db is not None:
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "SKIP_REASON",
                            f"IDEMPOTENT_LOCK action_key={key}",
                            {
                                "reason": reason,
                                "skip_reason": "IDEMPOTENT_LOCK",
                                "action_key": key,
                            },
                        )
                    continue
                if (
                    reason == "initial_allocation"
                    and db is not None
                    and _sync_initial_done_from_db(state, db, bot_id)
                ):
                    logger.info(
                        "bot_engine execution skip initial_allocation already_done bot_id=%s sync_state",
                        bot_id,
                    )
                    continue
                # 401 backoff: API key geçersizken her tick order denemeyi durdur
                backoff_until = state.get("backoff_until")
                if (
                    backoff_until is not None
                    and isinstance(backoff_until, (int, float))
                    and time.time() < float(backoff_until)
                ):
                    logger.debug(
                        "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401_BACKOFF backoff_until=%.0f",
                        bot_id,
                        reason,
                        backoff_until,
                    )
                    continue
                side = (a.get("side") or "").upper()
                symbol = (
                    a.get("symbol") or getattr(config, "symbol", "BTCUSDT")
                ).upper()
                qty = _num(a.get("quantity"))
                quote_qty_raw = a.get("quote_qty")
                if side == "BUY" and reason == "trail_buy_grid":
                    try:
                        assert_can_open_buy_level(
                            state=state,
                            max_buy_levels=getattr(config, "max_buy_levels", 0),
                            pending_buy_actions=pending_buy_level_actions,
                            reason=reason,
                        )
                    except MaxBuyLevelsError as mbl_err:
                        logger.warning(
                            "BOT_EXECUTION_SKIP bot_id=%s skip_reason=MAX_BUY_LEVELS_EXCEEDED %s",
                            bot_id,
                            mbl_err,
                        )
                        _append_skip(
                            db,
                            bot_id,
                            account_id,
                            "MAX_BUY_LEVELS_EXCEEDED",
                            str(mbl_err),
                            _cycle_meta(
                                state,
                                symbol,
                                grid_index=a.get("grid_index"),
                                max_buy_levels=getattr(config, "max_buy_levels", 0),
                            ),
                        )
                        continue
                if reason == "initial_allocation":
                    try:
                        qq = float(quote_qty_raw) if quote_qty_raw is not None else None
                    except (TypeError, ValueError):
                        qq = None
                    if qq is None or qq <= 0:
                        logger.warning(
                            "BOT_EXECUTION_SKIP bot_id=%s reason=initial_allocation skip_reason=INVALID_ACTION quote_qty=%s",
                            bot_id,
                            quote_qty_raw,
                        )
                        if db is not None:
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "SKIP_REASON",
                                "INVALID_ACTION quote_qty missing or <= 0",
                                {
                                    "reason": "initial_allocation",
                                    "skip_reason": "INVALID_ACTION",
                                    "action_key": key,
                                },
                            )
                        continue
                    quote_qty = qq
                else:
                    quote_qty = _num(quote_qty_raw)
                    # TRDCA batch: quantity (base) verilmişse, quote_qty 0 ise qty*price kullan
                    if (
                        reason == "trdca_batch"
                        and side == "BUY"
                        and qty > 0
                        and quote_qty <= 0
                    ):
                        _p = adapter.get_price(symbol) or 0.0
                        if _p > 0:
                            quote_qty = qty * _p
                run_id = (state.get("run_id") or "").strip() or "0"
                if not run_id or run_id == "0":
                    logger.warning(
                        "run_actions bot_id=%s run_id missing in state (using 0); set run_id on START for unique coid",
                        bot_id,
                    )
                intent_id = None
                cycle_id_intent = int(state.get("cycle_id") or 1)
                if reason == "initial_allocation":
                    cycle_id_intent = 0
                _price_for_intent = adapter.get_price(symbol) or 0.0
                quote_qty_for_intent = (
                    quote_qty
                    if (side == "BUY" and quote_qty > 0)
                    else (qty * _price_for_intent)
                )
                if (
                    side == "BUY"
                    and quote_qty_for_intent <= 0
                    and qty > 0
                    and _price_for_intent > 0
                ):
                    quote_qty_for_intent = qty * _price_for_intent
                intent_id = build_intent_id(
                    bot_id,
                    cycle_id_intent,
                    symbol,
                    side,
                    qty,
                    quote_qty_for_intent,
                    reason,
                    a.get("grid_index"),
                    run_id=run_id,
                )
                client_order_id_raw = build_client_order_id(
                    bot_id,
                    cycle_id_intent,
                    symbol,
                    side,
                    qty,
                    quote_qty_for_intent,
                    reason,
                    a.get("grid_index"),
                    run_id=run_id,
                )
                client_order_id = client_order_id_raw[:36]
                if db is not None:
                    intent_row, is_new = upsert_intent(
                        db,
                        intent_id,
                        bot_id,
                        account_id,
                        symbol,
                        side,
                        qty,
                        "MARKET",
                        client_order_id,
                    )
                    if intent_row and intent_row.get("status") == "FILLED":
                        need_repair = reason == "initial_allocation" and not state.get(
                            "initial_allocation_done"
                        )
                        verified_filled = False
                        if need_repair:
                            try:
                                coid_repair = (
                                    intent_row.get("client_order_id") or client_order_id
                                )[:36]
                                existing_order = (
                                    await adapter.get_order_by_client_order_id(
                                        symbol, coid_repair
                                    )
                                )
                                if (
                                    existing_order
                                    and (existing_order.get("status") or "").upper()
                                    == "FILLED"
                                ):
                                    order_id_repair = existing_order.get("orderId")
                                    try:
                                        order_id_int = (
                                            int(order_id_repair)
                                            if order_id_repair is not None
                                            else 0
                                        )
                                    except (TypeError, ValueError):
                                        order_id_int = 0
                                    trades_for_order = (
                                        await adapter.get_my_trades_for_order(
                                            symbol, order_id_int
                                        )
                                        if order_id_int
                                        else []
                                    )
                                    trades_match_count = len(trades_for_order)
                                    if trades_match_count == 0:
                                        logger.info(
                                            "INITIAL_ALLOC_VERIFY result=FAIL orderId=%s trades_match_count=0 => NOT_FOUND, proceeding to place",
                                            order_id_repair,
                                        )
                                        verified_filled = False
                                    else:
                                        exec_qty = _num(
                                            existing_order.get("executedQty")
                                        )
                                        cum_quote = _num(
                                            existing_order.get("cummulativeQuoteQty")
                                        )
                                        fill_price_raw = (
                                            (cum_quote / exec_qty)
                                            if exec_qty
                                            else _num(
                                                (existing_order.get("fills") or [{}])[
                                                    0
                                                ].get("price")
                                            )
                                        )
                                        fill_price = round(float(fill_price_raw), 8)
                                        fee_raw, fee_asset, fee = parse_fill_commission(
                                            existing_order.get("fills") or [],
                                            symbol,
                                            fill_price,
                                        )
                                        _is_trdca_or_multi = (
                                            reason == "trdca_batch"
                                            or getattr(config, "symbol", None)
                                            == "MULTI"
                                        )
                                        if not _is_trdca_or_multi:
                                            apply_fill_to_state(
                                                state,
                                                side,
                                                exec_qty,
                                                fill_price,
                                                fee,
                                                grid_index=a.get("grid_index"),
                                                reason=reason,
                                                execution_price=a.get(
                                                    "execution_price"
                                                ),
                                            )
                                            if reason == "initial_allocation":
                                                state["initial_allocation_done"] = True
                                                if (
                                                    state.get("reference_price") is None
                                                    and fill_price
                                                ):
                                                    state["reference_price"] = (
                                                        fill_price
                                                    )
                                                logger.info(
                                                    "BOT_EXECUTION_REPAIR bot_id=%s initial_allocation_done=True base_balance=%.4f quote_balance=%.2f",
                                                    bot_id,
                                                    state.get("base_balance"),
                                                    state.get("quote_balance"),
                                                )
                                            if reason in CYCLE_FILL_REASONS:
                                                ledger = ensure_cycle_ledger(
                                                    state,
                                                    symbol,
                                                    int(state.get("cycle_id") or 1),
                                                )
                                                cycle_ledger_add_fill(
                                                    ledger,
                                                    ts=datetime.now(
                                                        timezone.utc
                                                    ).isoformat(),
                                                    order_id=str(
                                                        existing_order.get("orderId")
                                                    ),
                                                    client_order_id=coid_repair,
                                                    side=side,
                                                    qty=exec_qty,
                                                    price=fill_price,
                                                    fee=fee,
                                                    fee_asset=fee_asset,
                                                    reason=reason,
                                                    slot_id=a.get("grid_index"),
                                                    fee_raw=fee_raw,
                                                )
                                                state["cycle_ledger_current"] = ledger
                                            save_state(db, bot_id, account_id, state)
                                        if db is not None:
                                            try:
                                                Ledger.record_trade(
                                                    db,
                                                    bot_id,
                                                    account_id,
                                                    side,
                                                    exec_qty,
                                                    fill_price,
                                                    fee=fee,
                                                    fee_asset=fee_asset,
                                                    slot_id=a.get("grid_index"),
                                                    order_id=str(order_id_repair),
                                                    client_order_id=coid_repair,
                                                    symbol=symbol,
                                                    cycle_id=int(
                                                        state.get("cycle_id") or 1
                                                    ),
                                                )
                                            except Exception as led_ex:
                                                logger.warning(
                                                    "BOT_EXECUTION_REPAIR record_trade failed bot_id=%s order_id=%s err=%s",
                                                    bot_id,
                                                    order_id_repair,
                                                    led_ex,
                                                )
                                            append_event(
                                                db,
                                                bot_id,
                                                account_id,
                                                "ORDER_FILLED",
                                                f"repaired=true orderId={order_id_repair} trades_match={trades_match_count}",
                                                {
                                                    "repaired": True,
                                                    "orderId": order_id_repair,
                                                    "trades_match_count": trades_match_count,
                                                },
                                            )
                                        logger.info(
                                            "INITIAL_ALLOC_VERIFY result=OK orderId=%s trades_match_count=%s",
                                            order_id_repair,
                                            trades_match_count,
                                        )
                                        logger.info(
                                            "BOT_EXECUTION_REPAIR bot_id=%s reason=%s intent_already_filled state_synced_from_binance order_id=%s",
                                            bot_id,
                                            reason,
                                            order_id_repair,
                                        )
                                        verified_filled = True
                            except Exception as repair_err:
                                logger.debug(
                                    "intent_filled state repair failed: %s", repair_err
                                )
                        if verified_filled:
                            logger.info(
                                "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=INTENT_ALREADY_FILLED intent_id=%s",
                                bot_id,
                                reason,
                                intent_id,
                            )
                            continue
                    if not is_new and intent_row:
                        client_order_id = (
                            intent_row.get("client_order_id") or client_order_id
                        )[:36]
                    try:
                        existing_order = await adapter.get_order_by_client_order_id(
                            symbol, client_order_id
                        )
                        if existing_order:
                            status = (existing_order.get("status") or "").upper()
                            if status == "FILLED":
                                order_id_ex = existing_order.get("orderId")
                                try:
                                    order_id_ex_int = (
                                        int(order_id_ex)
                                        if order_id_ex is not None
                                        else 0
                                    )
                                except (TypeError, ValueError):
                                    order_id_ex_int = 0
                                trades_ex = (
                                    await adapter.get_my_trades_for_order(
                                        symbol, order_id_ex_int
                                    )
                                    if order_id_ex_int
                                    else []
                                )
                                trades_match_count = len(trades_ex)
                                if trades_match_count == 0:
                                    logger.info(
                                        "INITIAL_ALLOC_VERIFY result=FAIL orderId=%s trades_match_count=0 => NOT_FOUND, proceeding to place",
                                        order_id_ex,
                                    )
                                    existing_order = None
                                else:
                                    exec_qty = _num(existing_order.get("executedQty"))
                                    cum_quote = _num(
                                        existing_order.get("cummulativeQuoteQty")
                                    )
                                    fill_price_raw = (
                                        (cum_quote / exec_qty)
                                        if exec_qty
                                        else _num(
                                            (existing_order.get("fills") or [{}])[
                                                0
                                            ].get("price")
                                        )
                                    )
                                    fill_price = round(float(fill_price_raw), 8)
                                    fee_raw, fee_asset, fee = parse_fill_commission(
                                        existing_order.get("fills") or [],
                                        symbol,
                                        fill_price,
                                    )
                                    update_intent_filled(db, intent_id, order_id_ex)
                                    _is_trdca_or_multi = (
                                        reason == "trdca_batch"
                                        or getattr(config, "symbol", None) == "MULTI"
                                    )
                                    if not _is_trdca_or_multi:
                                        apply_fill_to_state(
                                            state,
                                            side,
                                            exec_qty,
                                            fill_price,
                                            fee,
                                            grid_index=a.get("grid_index"),
                                            reason=reason,
                                            execution_price=a.get("execution_price"),
                                        )
                                        if reason in CYCLE_FILL_REASONS:
                                            ledger = ensure_cycle_ledger(
                                                state,
                                                symbol,
                                                int(state.get("cycle_id") or 1),
                                            )
                                            cycle_ledger_add_fill(
                                                ledger,
                                                ts=datetime.now(
                                                    timezone.utc
                                                ).isoformat(),
                                                order_id=str(order_id_ex),
                                                client_order_id=client_order_id,
                                                side=side,
                                                qty=exec_qty,
                                                price=fill_price,
                                                fee=fee,
                                                fee_asset=fee_asset,
                                                reason=reason,
                                                slot_id=a.get("grid_index"),
                                                fee_raw=fee_raw,
                                            )
                                            state["cycle_ledger_current"] = ledger
                                        save_state(db, bot_id, account_id, state)
                                        if db is not None:
                                            try:
                                                Ledger.record_trade(
                                                    db,
                                                    bot_id,
                                                    account_id,
                                                    side,
                                                    exec_qty,
                                                    fill_price,
                                                    fee=fee,
                                                    fee_asset=fee_asset,
                                                    slot_id=a.get("grid_index"),
                                                    order_id=str(order_id_ex),
                                                    client_order_id=client_order_id,
                                                    symbol=symbol,
                                                    cycle_id=int(
                                                        state.get("cycle_id") or 1
                                                    ),
                                                )
                                            except Exception:
                                                pass
                                            append_event(
                                                db,
                                                bot_id,
                                                account_id,
                                                "ORDER_FILLED",
                                                f"repaired=true orderId={order_id_ex} trades_match={trades_match_count}",
                                                {
                                                    "repaired": True,
                                                    "orderId": order_id_ex,
                                                    "trades_match_count": trades_match_count,
                                                },
                                            )
                                    logger.info(
                                        "INITIAL_ALLOC_VERIFY result=OK orderId=%s trades_match_count=%s",
                                        order_id_ex,
                                        trades_match_count,
                                    )
                                    results.append(
                                        {
                                            "order_id": order_id_ex,
                                            "client_order_id": client_order_id,
                                            "side": side,
                                            "fill_qty": exec_qty,
                                            "fill_price": fill_price,
                                            "fee": fee,
                                            "reason": reason,
                                            "event_logged": True,
                                        }
                                    )
                                    if side == "BUY" and reason == "trail_buy_grid":
                                        pending_buy_level_actions += 1
                                    continue
                            if existing_order and status in ("NEW", "PARTIALLY_FILLED"):
                                logger.info(
                                    "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=ORDER_ALREADY_SENT intent_id=%s status=%s",
                                    bot_id,
                                    reason,
                                    intent_id,
                                    status,
                                )
                                continue
                    except Exception as recon_err:
                        logger.debug(
                            "get_order_by_client_order_id failed (proceeding): %s",
                            recon_err,
                        )
                else:
                    client_order_id = (
                        a.get("client_order_id") or f"be_{bot_id}_{key}"[:36]
                    )
                price = adapter.get_price(symbol) or 0.0
                notional = (quote_qty if side == "BUY" else qty * price) if price else 0
                min_notional = getattr(config, "min_notional_guard", 10.0)
                if not guard_min_notional(notional, min_notional):
                    logger.info(
                        "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=MIN_NOTIONAL notional=%.2f min=%.2f",
                        bot_id,
                        reason,
                        notional,
                        min_notional,
                    )
                    _append_skip(
                        db,
                        bot_id,
                        account_id,
                        "MIN_NOTIONAL",
                        f"MIN_NOTIONAL notional={notional:.2f} min={min_notional:.2f}",
                        _cycle_meta(
                            state,
                            symbol,
                            reason=reason,
                            side=side,
                            notional=round(float(notional), 4),
                            min_notional=float(min_notional),
                            grid_index=a.get("grid_index"),
                        ),
                    )
                    continue
                if reason == "initial_allocation":
                    fee_buffer_pct = float(
                        getattr(config, "initial_fee_buffer_pct", 0.002) or 0.002
                    )
                    required = float(quote_qty) * (1.0 + fee_buffer_pct)
                    logger.info(
                        "BOT_CFG bot_id=%s symbol=%s budget=%.2f base_pct=%.2f quote_pct=%.2f fee_buffer=%.4f",
                        bot_id,
                        symbol,
                        float(
                            getattr(config, "initial_capital_usdt", 0)
                            or getattr(config, "bot_budget_usdt", 0)
                            or 0
                        ),
                        float(getattr(config, "base_alloc_pct", 50) or 50),
                        float(getattr(config, "quote_alloc_pct", 50) or 50),
                        fee_buffer_pct,
                    )
                    binance_balances = await adapter.get_account_balances()
                    base_asset = (symbol or "BTCUSDT").replace("USDT", "") or "BTC"
                    quote_asset = "USDT"
                    base_free = float(
                        (binance_balances.get(base_asset) or {}).get("free") or 0
                    )
                    quote_free = float(
                        (binance_balances.get(quote_asset) or {}).get("free") or 0
                    )
                    logger.info(
                        "BOT_BALANCES bot_id=%s base_asset=%s base_free=%.6f quote_asset=%s quote_free=%.2f",
                        bot_id,
                        base_asset,
                        base_free,
                        quote_asset,
                        quote_free,
                    )
                    available = quote_free
                    eps = 1e-6
                    if available + eps < required:
                        # Cap initial_allocation to available balance so the first buy can execute (parametre bütçesi > cüzdan serbest bakiyesi olabilir)
                        capped_quote = round(
                            float(available) / (1.0 + fee_buffer_pct), 2
                        )
                        if capped_quote >= min_notional and capped_quote > 0:
                            logger.info(
                                "BOT_INITIAL_ALLOC_CAP bot_id=%s quote_qty=%.2f -> %.2f (available=%.2f insufficient for requested)",
                                bot_id,
                                quote_qty,
                                capped_quote,
                                available,
                            )
                            quote_qty = capped_quote
                            required = quote_qty * (1.0 + fee_buffer_pct)
                            if db is not None:
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "INFO",
                                    f"İlk alım miktarı bakiyeye göre düşürüldü: {quote_qty:.2f} {quote_asset} (mevcut bakiye: {available:.2f})",
                                    {
                                        "capped_quote_qty": quote_qty,
                                        "available": available,
                                        "action_key": key,
                                    },
                                )
                            decision = "EXECUTE"
                        else:
                            decision = "SKIP"
                            logger.info(
                                "BOT_REQUIRED bot_id=%s quote_qty=%.2f required=%.2f available=%.2f decision=%s",
                                bot_id,
                                quote_qty,
                                required,
                                available,
                                decision,
                            )
                            logger.warning(
                                "BOT_EXECUTION_SKIP bot_id=%s reason=initial_allocation skip_reason=INSUFFICIENT_QUOTE required=%.2f available=%.2f",
                                bot_id,
                                required,
                                available,
                            )
                            if db is not None:
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "SKIP_REASON",
                                    f"INSUFFICIENT_QUOTE required={required:.2f} available={available:.2f}",
                                    {
                                        "error_code": "INSUFFICIENT_QUOTE",
                                        "required": required,
                                        "available": available,
                                        "action_key": key,
                                    },
                                )
                            continue
                    else:
                        decision = "EXECUTE"
                    logger.info(
                        "BOT_REQUIRED bot_id=%s quote_qty=%.2f required=%.2f available=%.2f decision=%s",
                        bot_id,
                        quote_qty,
                        required,
                        available,
                        decision,
                    )
                    logger.info(
                        "BOT_INITIAL_ALLOC_BUDGET bot_id=%s quote_asset=%s quote_qty=%.2f fee_buffer=%.4f required=%.2f available=%.2f decision=%s",
                        bot_id,
                        quote_asset,
                        quote_qty,
                        fee_buffer_pct,
                        required,
                        available,
                        decision,
                    )
                elif db is not None:
                    fee_buffer_pct = 0.002
                    buffer_pct = float(
                        getattr(config, "available_quote_buffer_pct", 0.005) or 0.005
                    )
                    is_trdca_or_multi = (
                        reason == "trdca_batch"
                        or getattr(config, "symbol", None) == "MULTI"
                        or (getattr(config, "strategy_id", "") or "").strip().lower()
                        == "trdca_pro"
                    )
                    skip_virtual_check = adapter.paper_mode and is_trdca_or_multi
                    if side == "BUY" and not skip_virtual_check:
                        # Cap BUY: min(state free_quote, virtual_quote) * (1 - buffer); virtual sub-wallet is hard ceiling
                        _vb, _vq = get_virtual_wallet(db, bot_id, symbol)
                        free_quote = state.get("free_quote")
                        if free_quote is None:
                            free_quote = float(_vq)
                        vq_cap = float(_vq)
                        effective_quote = (
                            min(float(free_quote), vq_cap)
                            if vq_cap > 0
                            else float(free_quote)
                        )
                        combined_buffer = max(buffer_pct, fee_buffer_pct)
                        available_quote = max(
                            0.0, effective_quote * (1.0 - combined_buffer)
                        )
                        if quote_qty > available_quote and available_quote > 0:
                            old_qty = quote_qty
                            quote_qty = round(available_quote, 2)
                            logger.info(
                                "BOT_EXECUTION_CAP_QUOTE bot_id=%s reason=%s quote_qty_capped %.2f -> %.2f effective_quote=%.2f virtual_quote=%.2f free_quote=%.2f buffer=%.4f",
                                bot_id,
                                reason,
                                old_qty,
                                quote_qty,
                                effective_quote,
                                vq_cap,
                                float(free_quote),
                                combined_buffer,
                            )
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "INFO",
                                f"quote_qty_capped {old_qty:.2f} -> {quote_qty:.2f} (virtual available)",
                                {
                                    "reason": reason,
                                    "old_qty": old_qty,
                                    "quote_qty": quote_qty,
                                    "virtual_quote": _vq,
                                    "free_quote": free_quote,
                                    "effective_quote": effective_quote,
                                },
                            )
                            notional_capped = (
                                quote_qty if price and price > 0 else quote_qty
                            )
                            if not guard_min_notional(
                                notional_capped, config.min_notional_guard
                            ):
                                logger.info(
                                    "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=MIN_NOTIONAL_AFTER_CAP quote_qty=%.2f min=%.2f",
                                    bot_id,
                                    reason,
                                    quote_qty,
                                    config.min_notional_guard,
                                )
                                _append_skip(
                                    db,
                                    bot_id,
                                    account_id,
                                    "MIN_NOTIONAL_AFTER_CAP",
                                    f"MIN_NOTIONAL_AFTER_CAP quote_qty={quote_qty:.2f} min={config.min_notional_guard:.2f}",
                                    {
                                        "reason": reason,
                                        "side": side,
                                        "symbol": symbol,
                                        "quote_qty": round(float(quote_qty), 4),
                                        "min_notional": float(
                                            config.min_notional_guard
                                        ),
                                        "grid_index": a.get("grid_index"),
                                    },
                                )
                                continue
                        if (
                            reason == "trail_reentry_buy"
                            and price
                            and price > 0
                            and available_quote > quote_qty
                        ):
                            try:
                                buy_filters = await adapter.get_symbol_filters(symbol)
                            except Exception:
                                buy_filters = {}
                            boost = _boost_reentry_quote_to_next_lot(
                                state,
                                float(quote_qty),
                                float(price),
                                float(available_quote),
                                buy_filters,
                                buffer_pct=float(
                                    getattr(
                                        config,
                                        "reentry_lot_step_quote_buffer_pct",
                                        0.001,
                                    )
                                    or 0.001
                                ),
                            )
                            if boost and boost.get("new_quote_qty", 0) > quote_qty:
                                old_qty = float(quote_qty)
                                quote_qty = round(float(boost["new_quote_qty"]), 8)
                                logger.info(
                                    "BOT_REENTRY_COMPOUND_LOT_BOOST bot_id=%s quote_qty %.8f -> %.8f sold_qty=%.10f current_lot_qty=%.10f target_qty=%.10f step=%.10f available_quote=%.2f",
                                    bot_id,
                                    old_qty,
                                    quote_qty,
                                    boost.get("sold_qty", 0),
                                    boost.get("current_lot_qty", 0),
                                    boost.get("target_qty", 0),
                                    boost.get("step_size", 0),
                                    available_quote,
                                )
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "INFO",
                                    "Bileşik re-entry: alım miktarı bir üst lot adımına yükseltildi",
                                    {
                                        "reason": reason,
                                        "side": side,
                                        "symbol": symbol,
                                        "old_quote_qty": round(old_qty, 8),
                                        "quote_qty": quote_qty,
                                        "sold_qty": round(
                                            float(boost.get("sold_qty", 0)), 10
                                        ),
                                        "current_lot_qty": round(
                                            float(boost.get("current_lot_qty", 0)), 10
                                        ),
                                        "target_qty": round(
                                            float(boost.get("target_qty", 0)), 10
                                        ),
                                        "step_size": boost.get("step_size"),
                                        "available_quote": round(
                                            float(available_quote), 8
                                        ),
                                    },
                                )
                    if not skip_virtual_check:
                        ok, budget_reason, required, available = check_virtual_budget(
                            db,
                            bot_id,
                            symbol,
                            side,
                            quote_amount=quote_qty,
                            base_qty=qty,
                            price=price,
                            fee_buffer_pct=fee_buffer_pct,
                        )
                    else:
                        ok = True
                    if not ok:
                        _vq_skip = None
                        try:
                            _vq_skip = float(get_virtual_wallet(db, bot_id, symbol)[1])
                        except Exception:
                            pass
                        payload = {
                            "skip_reason": "VIRTUAL_BUDGET_INSUFFICIENT",
                            "error_code": "VIRTUAL_BUDGET_INSUFFICIENT",
                            "required": required,
                            "available": available,
                            "virtual_quote": _vq_skip,
                            "fee_buffer_pct": fee_buffer_pct if side == "BUY" else None,
                            "side": side,
                            "symbol": symbol,
                            "reason": reason,
                            "action_key": key,
                            "bot_id": bot_id,
                            "account_id": account_id,
                        }
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "SKIP_REASON",
                            f"VIRTUAL_BUDGET insufficient required={required} available={available} side={side} symbol={symbol}",
                            payload,
                        )
                        if reason == "initial_allocation":
                            k = (bot_id, key)
                            _initial_alloc_skip_count[k] = (
                                _initial_alloc_skip_count.get(k, 0) + 1
                            )
                            if _initial_alloc_skip_count[k] > 3:
                                logger.warning(
                                    "BOT_INITIAL_ALLOC_SAME_KEY_REPEATED bot_id=%s action_key=%s count=%s (budget insufficient)",
                                    bot_id,
                                    key,
                                    _initial_alloc_skip_count[k],
                                )
                        logger.warning(
                            "BOT_EXECUTION_SKIP error_code=VIRTUAL_BUDGET_INSUFFICIENT bot_id=%s account_id=%s reason=%s action_key=%s required=%s available=%s",
                            bot_id,
                            account_id,
                            reason,
                            key,
                            required,
                            available,
                        )
                        continue
                # Binance balance safety: BUY/SELL before sending order (virtual vs real drift). Paper mode: skip (simulated).
                if not adapter.paper_mode and side == "BUY":
                    try:
                        if (
                            reason == "initial_allocation"
                            and binance_balances is not None
                        ):
                            balances = binance_balances
                        else:
                            balances = await adapter.get_account_balances()
                        usdt = balances.get("USDT") or {}
                        free_usdt = float(usdt.get("free") or 0)
                        fee_buffer_usdt = 0.5
                        if quote_qty + fee_buffer_usdt > free_usdt:
                            logger.warning(
                                "BOT_EXECUTION_SKIP error_code=BINANCE_FREE_QUOTE_INSUFFICIENT bot_id=%s quote_qty=%.2f free_usdt=%.2f fee_buffer=%.2f",
                                bot_id,
                                quote_qty,
                                free_usdt,
                                fee_buffer_usdt,
                            )
                            if db is not None:
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "SKIP_REASON",
                                    f"BINANCE_FREE_QUOTE_INSUFFICIENT quote_qty={quote_qty:.2f} free_usdt={free_usdt:.2f}",
                                    {
                                        "skip_reason": "BINANCE_FREE_QUOTE_INSUFFICIENT",
                                        "error_code": "BINANCE_FREE_QUOTE_INSUFFICIENT",
                                        "quote_qty": quote_qty,
                                        "free_usdt": free_usdt,
                                        "reason": reason,
                                        "side": side,
                                        "grid_index": a.get("grid_index"),
                                    },
                                )
                            continue
                    except Exception as bal_err:
                        if _is_401_unauthorized(bal_err):
                            if not _should_log_exec_401(bot_id):
                                logger.debug(
                                    "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=401 (throttled)",
                                    bot_id,
                                )
                            else:
                                logger.warning(
                                    "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=401 Unauthorized (tekrar 10 dk içinde loglanmayacak)",
                                    bot_id,
                                )
                        else:
                            logger.warning(
                                "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s err=%s (proceeding)",
                                bot_id,
                                bal_err,
                            )
                elif not adapter.paper_mode and side == "SELL":
                    try:
                        balances = await adapter.get_account_balances()
                        base_asset = (symbol or "BTCUSDT").replace(
                            "USDT", ""
                        ).strip() or "BTC"
                        base_bal = balances.get(base_asset) or {}
                        free_base = float(base_bal.get("free") or 0)
                        base_buffer = 0.001
                        max_qty = (
                            free_base * (1.0 - base_buffer) if free_base >= 0 else 0.0
                        )
                        if qty > max_qty and max_qty > 0:
                            logger.info(
                                "BOT_EXECUTION_CAP_BASE bot_id=%s reason=%s qty=%.8f -> max_qty=%.8f free_base=%.8f",
                                bot_id,
                                reason,
                                qty,
                                max_qty,
                                free_base,
                            )
                            qty = max_qty
                        elif qty > max_qty:
                            logger.warning(
                                "BOT_EXECUTION_SKIP error_code=BINANCE_FREE_BASE_INSUFFICIENT bot_id=%s reason=%s qty=%.6f free_base=%.6f (virtual>real)",
                                bot_id,
                                reason,
                                qty,
                                free_base,
                            )
                            if db is not None:
                                append_event(
                                    db,
                                    bot_id,
                                    account_id,
                                    "SKIP_REASON",
                                    f"BINANCE_FREE_BASE_INSUFFICIENT qty={qty:.6f} free_base={free_base:.6f} (virtual balance > real)",
                                    {
                                        "skip_reason": "BINANCE_FREE_BASE_INSUFFICIENT",
                                        "error_code": "BINANCE_FREE_BASE_INSUFFICIENT",
                                        "qty": qty,
                                        "free_base": free_base,
                                        "base_asset": base_asset,
                                        "reason": reason,
                                        "side": side,
                                        "grid_index": a.get("grid_index"),
                                    },
                                )
                            continue
                    except Exception as bal_err:
                        if _is_401_unauthorized(bal_err):
                            if not _should_log_exec_401(bot_id):
                                logger.debug(
                                    "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=401 (throttled)",
                                    bot_id,
                                )
                            else:
                                logger.warning(
                                    "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=401 Unauthorized (tekrar 10 dk içinde loglanmayacak)",
                                    bot_id,
                                )
                        else:
                            logger.warning(
                                "BOT_EXECUTION_BALANCE_CHECK_FAIL bot_id=%s SELL err=%s (proceeding)",
                                bot_id,
                                bal_err,
                            )
                    if qty > 0:
                        try:
                            from app.botengine.order_qty import validate_market_sell_qty

                            sell_filters = await adapter.get_symbol_filters(symbol)
                            sell_price = adapter.get_price(symbol) or price or 0.0
                            lot_skip, qty_adj, _qty_str = validate_market_sell_qty(
                                qty,
                                sell_filters,
                                sell_price,
                            )
                            if lot_skip:
                                logger.info(
                                    "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=%s qty=%.8f min_qty=%s step=%s (preflight)",
                                    bot_id,
                                    reason,
                                    lot_skip,
                                    qty,
                                    sell_filters.get("min_qty"),
                                    sell_filters.get("step_size_str"),
                                )
                                if state.get("last_error_code") in (
                                    "LOT_SIZE",
                                    "MIN_NOTIONAL",
                                    "MIN_NOTIONAL_AFTER_CAP",
                                ):
                                    state.pop("last_error_code", None)
                                    state.pop("health_error_since", None)
                                _append_skip(
                                    db,
                                    bot_id,
                                    account_id,
                                    lot_skip,
                                    f"{lot_skip} qty={qty:.8f} adj={qty_adj:.8f} symbol={symbol}",
                                    {
                                        "reason": reason,
                                        "skip_reason": lot_skip,
                                        "error_code": lot_skip,
                                        "preflight": True,
                                        "qty": qty,
                                        "qty_adjusted": qty_adj,
                                        "min_qty": sell_filters.get("min_qty"),
                                        "step_size": sell_filters.get("step_size_str"),
                                        "side": side,
                                        "symbol": symbol,
                                        "grid_index": a.get("grid_index"),
                                    },
                                )
                                continue
                            qty = qty_adj
                        except Exception as filt_err:
                            logger.warning(
                                "BOT_EXECUTION_SELL_FILTER_CHECK_FAIL bot_id=%s err=%s",
                                bot_id,
                                filt_err,
                            )
                            _append_skip(
                                db,
                                bot_id,
                                account_id,
                                "ORDER_FAILED",
                                f"SELL filter check failed: {filt_err}",
                                {
                                    "reason": reason,
                                    "skip_reason": "ORDER_FAILED",
                                    "preflight": True,
                                    "side": side,
                                    "symbol": symbol,
                                    "grid_index": a.get("grid_index"),
                                },
                            )
                            continue
                if db is not None:
                    lock_sym = trade_lock_symbol(account_id, symbol)
                    if not lease_still_valid(db, account_id, lock_sym, bot_id):
                        logger.warning(
                            "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=LOCK_LEASE_EXPIRED symbol=%s",
                            bot_id,
                            reason,
                            lock_sym,
                        )
                        if intent_id:
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "SKIP_REASON",
                                "LOCK_LEASE_EXPIRED before submit",
                                {
                                    "reason": reason,
                                    "skip_reason": "LOCK_LEASE_EXPIRED",
                                    "symbol": lock_sym,
                                },
                            )
                        continue
                if db is not None and intent_id:
                    update_intent_submitting(db, intent_id)
                try:
                    from app.services.binance_weight import request_weight_tokens

                    weight = 1
                    if not adapter.paper_mode:
                        allowed = await request_weight_tokens(
                            account_id, getattr(adapter.keys, "api_key", None), weight
                        )
                        if not allowed:
                            if db is not None and intent_id:
                                update_intent_unknown(
                                    db,
                                    intent_id,
                                    error_code="WEIGHT_DENIED",
                                    error_id=str(uuid.uuid4()),
                                )
                            _append_skip(
                                db,
                                bot_id,
                                account_id,
                                "WEIGHT_DENIED",
                                "WEIGHT_DENIED rate limit",
                                {
                                    "reason": reason,
                                    "symbol": symbol,
                                    "side": side,
                                    "grid_index": a.get("grid_index"),
                                },
                            )
                            logger.warning(
                                "run_actions WEIGHT_DENIED bot_id=%s account_id=%s",
                                bot_id,
                                account_id,
                            )
                            continue
                    try:
                        logger.info(
                            "EXEC_ORDER_ATTEMPT bot_id=%s run_id=%s intent_id=%s coid=%s symbol=%s side=%s quote_qty=%s qty=%s paper=%s",
                            bot_id,
                            run_id,
                            intent_id or "",
                            (client_order_id or "")[:36],
                            symbol,
                            side,
                            quote_qty,
                            qty,
                            adapter.paper_mode,
                        )
                        if db is not None:
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "ORDER_ATTEMPT",
                                f"{side} attempt {symbol}",
                                _cycle_meta(
                                    state,
                                    symbol,
                                    side=side,
                                    quote_qty=round(float(quote_qty), 4)
                                    if quote_qty
                                    else None,
                                    qty=round(float(qty), 8) if qty else None,
                                    reason=reason,
                                    grid_index=a.get("grid_index"),
                                    client_order_id=client_order_id,
                                    paper=adapter.paper_mode,
                                ),
                            )
                        if side == "BUY":
                            res = await asyncio.wait_for(
                                adapter.place_market_buy(
                                    symbol, quote_qty, client_order_id
                                ),
                                timeout=EXEC_ORDER_TIMEOUT_SEC,
                            )
                        else:
                            res = await asyncio.wait_for(
                                adapter.place_market_sell(symbol, qty, client_order_id),
                                timeout=EXEC_ORDER_TIMEOUT_SEC,
                            )
                    except asyncio.TimeoutError:
                        if db is not None and intent_id:
                            update_intent_unknown(
                                db,
                                intent_id,
                                error_code="TIMEOUT",
                                error_id=str(uuid.uuid4()),
                            )
                        _append_skip(
                            db,
                            bot_id,
                            account_id,
                            "ORDER_TIMEOUT",
                            f"ORDER_TIMEOUT symbol={symbol} side={side}",
                            {
                                "reason": reason,
                                "symbol": symbol,
                                "side": side,
                                "client_order_id": client_order_id,
                                "grid_index": a.get("grid_index"),
                            },
                        )
                        logger.warning(
                            "run_actions TIMEOUT bot_id=%s intent_id=%s (reconcile will resolve)",
                            bot_id,
                            intent_id,
                        )
                        continue
                    if db is not None and intent_id:
                        update_intent_sent(db, intent_id)
                except Exception as e:
                    error_id = str(uuid.uuid4())
                    if isinstance(e, ValueError):
                        msg = str(e).lower()
                        if "lot_size" in msg or "min_qty" in msg:
                            parsed_err = {
                                "skip_reason": "LOT_SIZE",
                                "error": str(e)[:500],
                                "binance_code": -1013,
                                "binance_msg": str(e)[:200],
                                "request_id": None,
                            }
                        elif "min_notional" in msg or "notional" in msg:
                            parsed_err = {
                                "skip_reason": "MIN_NOTIONAL",
                                "error": str(e)[:500],
                                "binance_code": None,
                                "binance_msg": str(e)[:200],
                                "request_id": None,
                            }
                        else:
                            parsed_err = _parse_binance_order_error(e)
                    else:
                        parsed_err = _parse_binance_order_error(e)
                    insufficient = parsed_err["skip_reason"] == "INSUFFICIENT_BALANCE"
                    request_id = parsed_err.get("request_id")
                    if insufficient and db is not None:
                        from app.db.models import Bot

                        bot_row = db.query(Bot).filter(Bot.id == bot_id).first()
                        if bot_row:
                            bot_row.status = "paused_insufficient_balance"
                            db.commit()
                        state["last_error_code"] = "INSUFFICIENT_BALANCE"
                        state["backoff_until"] = time.time() + 60
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "ERROR",
                            "Yetersiz bakiye — bot beklemeye alındı. Cüzdana bakiye ekleyip botu yeniden başlatın.",
                            {
                                "error_code": "INSUFFICIENT_BALANCE",
                                "error_id": error_id,
                                "request_id": request_id,
                                "bot_id": bot_id,
                                "account_id": account_id,
                                "action_key": key,
                                "loop_id": loop_id,
                                "user_action_required": True,
                                "resume_hint": "START komutu ile yeniden başlatın",
                            },
                        )
                        try:
                            from app.services import audit as _audit_svc

                            _audit_svc.log_event(
                                db,
                                actor_type="system",
                                event_type="BOT_PAUSED_INSUFFICIENT_BALANCE",
                                severity="WARN",
                                target_account_id=account_id,
                                meta={
                                    "bot_id": bot_id,
                                    "error_id": error_id,
                                    "action_key": key,
                                },
                            )
                        except Exception:
                            pass
                        logger.warning(
                            "BOT_EXECUTION_INSUFFICIENT_BALANCE error_code=INSUFFICIENT_BALANCE error_id=%s request_id=%s bot_id=%s account_id=%s loop_id=%s (bot paused, kullanici START gerekli)",
                            error_id,
                            request_id or "-",
                            bot_id,
                            account_id,
                            loop_id or "",
                        )
                        continue
                    if _is_401_unauthorized(e):
                        state["backoff_until"] = time.time() + _EXEC_401_BACKOFF_SEC
                        state["last_error_code"] = "API_UNAUTHORIZED"
                        state["health_error_since"] = int(time.time())
                        if db is not None:
                            from app.db.models import Bot

                            bot_row = db.query(Bot).filter(Bot.id == bot_id).first()
                            if bot_row:
                                bot_row.status = "paused_error"
                                db.commit()
                            try:
                                from app.services.binance_connectivity import (
                                    emit_tur_connectivity_paused_info,
                                )

                                emit_tur_connectivity_paused_info(
                                    db, bot_id, account_id, "API_UNAUTHORIZED"
                                )
                            except Exception:
                                pass
                            cycle_id = int(state.get("cycle_id") or 1)
                            warn_meta = {
                                "error_code": "API_UNAUTHORIZED",
                                "health_code": "CONNECTIVITY_LOST",
                                "title": "Bağlantı kesildi",
                                "cause": "API anahtarı veya IP beyaz listesi",
                                "cycle_id": cycle_id,
                                "severity": "warn",
                                "error_id": error_id,
                                "action_key": key,
                            }
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "HEALTH_WARN",
                                "Binance API geçersiz — bot beklemeye alındı",
                                warn_meta,
                            )
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "ERROR",
                                "Binance 401 Unauthorized – API anahtarı geçersiz, IP beyaz listesi veya Spot izinlerini kontrol edin.",
                                {
                                    "error_code": "API_UNAUTHORIZED",
                                    "error_id": error_id,
                                    "bot_id": bot_id,
                                    "account_id": account_id,
                                    "action_key": key,
                                    "loop_id": loop_id,
                                },
                            )
                            try:
                                from app.services import audit as _audit_svc

                                _audit_svc.log_event(
                                    db,
                                    actor_type="system",
                                    event_type="BOT_PAUSED_API_UNAUTHORIZED",
                                    severity="WARN",
                                    target_account_id=account_id,
                                    meta={
                                        "bot_id": bot_id,
                                        "error_id": error_id,
                                        "action_key": key,
                                    },
                                )
                            except Exception:
                                pass
                            save_state(db, bot_id, account_id, state)
                        if not _should_log_exec_401(bot_id):
                            logger.debug(
                                "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401 bot paused (throttled log)",
                                bot_id,
                                reason,
                            )
                        else:
                            logger.warning(
                                "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=API_401 Unauthorized – bot paused_error, API key/IP/izinleri kontrol edin",
                                bot_id,
                                reason,
                            )
                        continue
                    skip_reason = parsed_err["skip_reason"]
                    logger.warning(
                        "BOT_EXECUTION_SKIP bot_id=%s reason=%s skip_reason=%s err=%s binance_code=%s",
                        bot_id,
                        reason,
                        skip_reason,
                        e,
                        parsed_err.get("binance_code"),
                    )
                    state["last_error_code"] = skip_reason
                    state["health_error_since"] = int(time.time())
                    if db is not None:
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "SKIP_REASON",
                            f"{skip_reason} err={parsed_err.get('error') or e}",
                            {
                                "reason": reason,
                                "skip_reason": skip_reason,
                                "error": parsed_err.get("error") or str(e),
                                "error_id": error_id,
                                "binance_code": parsed_err.get("binance_code"),
                                "binance_msg": parsed_err.get("binance_msg"),
                                "side": side,
                                "grid_index": a.get("grid_index"),
                            },
                        )
                    continue
                # Persist intent FILLED (idempotency: state saved AFTER intent persisted)
                if db is not None and intent_id:
                    update_intent_filled(db, intent_id, res.get("orderId"))
                # Parse fill
                fills = res.get("fills") or []
                exec_qty = _num(res.get("executedQty"))
                if exec_qty > 0:
                    state.pop("last_error_code", None)
                    state.pop("health_error_since", None)
                cum_quote = _num(res.get("cummulativeQuoteQty"))
                fill_price_raw = (
                    (cum_quote / exec_qty)
                    if exec_qty
                    else _num(fills[0].get("price"))
                    if fills
                    else 0
                )
                fill_price = round(float(fill_price_raw), 8)
                fee_raw, fee_asset, fee = parse_fill_commission(
                    fills, symbol, fill_price
                )
                is_multi_rebalance = getattr(config, "symbol", None) == "MULTI" or (
                    (getattr(config, "strategy_id", "") or "").strip().lower()
                    == "multi_asset_rebalance"
                )
                if reason == "trdca_batch":
                    results.append(
                        {
                            "order_id": res.get("orderId"),
                            "client_order_id": client_order_id,
                            "symbol": symbol,
                            "side": side,
                            "fill_qty": exec_qty,
                            "fill_price": fill_price,
                            "filled_quote": cum_quote,
                            "fee": fee,
                            "reason": reason,
                            "status": (res.get("status") or "FILLED").upper(),
                        }
                    )
                    continue
                if is_multi_rebalance:
                    results.append(
                        {
                            "order_id": res.get("orderId"),
                            "client_order_id": client_order_id,
                            "side": side,
                            "fill_qty": exec_qty,
                            "fill_price": fill_price,
                            "fee": fee,
                            "reason": reason,
                        }
                    )
                    if db is not None:
                        save_state(db, bot_id, account_id, state)
                    continue
                apply_fill_to_state(
                    state,
                    side,
                    exec_qty,
                    fill_price,
                    fee,
                    grid_index=a.get("grid_index"),
                    reason=reason,
                    execution_price=a.get("execution_price"),
                )
                # Cycle ledger: record only cycle-scoped fills (single source of truth for cycle PnL)
                if reason in CYCLE_FILL_REASONS:
                    ledger = ensure_cycle_ledger(
                        state, symbol, int(state.get("cycle_id") or 1)
                    )
                    ts_iso = datetime.now(timezone.utc).isoformat()
                    cycle_ledger_add_fill(
                        ledger,
                        ts=ts_iso,
                        order_id=str(res.get("orderId"))
                        if res.get("orderId") is not None
                        else None,
                        client_order_id=client_order_id,
                        side=side,
                        qty=exec_qty,
                        price=fill_price,
                        fee=fee,
                        fee_asset=fee_asset,
                        reason=reason,
                        slot_id=a.get("grid_index"),
                        fee_raw=fee_raw,
                    )
                    state["cycle_ledger_current"] = ledger
                fill_ts_utc = _fill_ts_from_order(res)
                # initial_allocation: ia_done ONLY when order really filled (exec_qty > 0)
                if reason == "initial_allocation":
                    if exec_qty <= 0:
                        logger.critical(
                            "BOT_INITIAL_ALLOC_FILL_INVALID bot_id=%s account_id=%s exec_qty=%s (ia_done NOT set)",
                            bot_id,
                            account_id,
                            exec_qty,
                        )
                    else:
                        state["initial_allocation_done"] = True
                        state["reference_price"] = fill_price
                        state["cycle_id"] = 1
                        _ts_open = fill_ts_utc.isoformat()
                        state["cycle_opened_at"] = _ts_open
                        state["initial_alloc_base_qty"] = round(float(exec_qty), 10)
                        state["initial_alloc_price"] = round(float(fill_price), 10)
                        state["initial_alloc_fee_quote"] = round(float(fee), 8)
                        C = _num(getattr(config, "initial_capital_usdt", 0))
                        state["quote_balance"] = round(
                            max(0.0, C - cum_quote - fee), 10
                        )
                        state["base_balance"] = round(float(exec_qty), 10)
                        state["grid_reference_quote"] = state["quote_balance"]
                        equity_usdt = round(
                            state["quote_balance"] + state["base_balance"] * fill_price,
                            2,
                        )
                        state["cycle_start_equity"] = equity_usdt
                        quote_alloc = (
                            _num(getattr(config, "quote_alloc_pct", 50)) / 100.0
                        )
                        base_alloc = _num(getattr(config, "base_alloc_pct", 50)) / 100.0
                        state["target_budgets"] = {
                            "equity_usdt": equity_usdt,
                            "target_quote_usdt": round(equity_usdt * quote_alloc, 2),
                            "target_base_usdt": round(equity_usdt * base_alloc, 2),
                            "ts": _ts_open,
                        }
                        tb_row = (
                            state.get("target_budgets")
                            if isinstance(state.get("target_budgets"), dict)
                            else {}
                        )
                        open_row = {
                            "cycle_id": 1,
                            "side": "BUY",
                            "qty": round(float(exec_qty), 10),
                            "price": round(float(fill_price), 10),
                            "reference_price": round(float(fill_price), 10),
                            "quote_balance": round(float(state["quote_balance"]), 2),
                            "equity_usdt": equity_usdt,
                            "ts": _ts_open,
                            "fee": round(float(fee), 8),
                        }
                        if tb_row.get("target_quote_usdt") is not None:
                            open_row["target_quote_usdt"] = round(
                                float(tb_row["target_quote_usdt"]), 2
                            )
                        if tb_row.get("target_base_usdt") is not None:
                            open_row["target_base_usdt"] = round(
                                float(tb_row["target_base_usdt"]), 2
                            )
                        state.setdefault("cycle_open_trades", []).append(open_row)
                        state["cycle_open_trades"] = state["cycle_open_trades"][-200:]
                        _initial_alloc_skip_count.pop((bot_id, key), None)
                if reason == "trail_sell_grid":
                    idx = a.get("grid_index", 0)
                    state.setdefault("sell_grid_fired", [])
                    if idx < len(state["sell_grid_fired"]):
                        state["sell_grid_fired"][idx] = True
                    # Tamamlanan grid için tepe fiyatını dondur (bir daha güncellenmez)
                    state.setdefault("sell_grid_peak_price", [])
                    while len(state["sell_grid_peak_price"]) <= idx:
                        state["sell_grid_peak_price"].append(None)
                    peak_val = a.get("trail_anchor_price") or state.get(
                        "trail_anchor_price"
                    )
                    if peak_val is not None:
                        state["sell_grid_peak_price"][idx] = float(peak_val)
                    # Binance'teki gerçek işlem fiyatını grid için sakla (UI'da Gerçekleşme fiyatı)
                    state.setdefault("sell_grid_fill_price", [])
                    while len(state["sell_grid_fill_price"]) <= idx:
                        state["sell_grid_fill_price"].append(None)
                    state["sell_grid_fill_price"][idx] = fill_price
                if reason == "trail_buy_grid":
                    idx = a.get("grid_index", 0)
                    state.setdefault("buy_grid_fired", [])
                    if idx < len(state["buy_grid_fired"]):
                        state["buy_grid_fired"][idx] = True
                    # Tamamlanan grid için dip fiyatını dondur (bir daha güncellenmez)
                    state.setdefault("buy_grid_trough_price", [])
                    while len(state["buy_grid_trough_price"]) <= idx:
                        state["buy_grid_trough_price"].append(None)
                    trough_val = a.get("trail_anchor_price") or state.get(
                        "trail_anchor_price"
                    )
                    if trough_val is not None:
                        state["buy_grid_trough_price"][idx] = float(trough_val)
                    # Binance'teki gerçek işlem fiyatını grid için sakla (UI'da Gerçekleşme fiyatı)
                    state.setdefault("buy_grid_fill_price", [])
                    while len(state["buy_grid_fill_price"]) <= idx:
                        state["buy_grid_fill_price"].append(None)
                    state["buy_grid_fill_price"][idx] = fill_price
                cycle_id_for_trade = int(state.get("cycle_id") or 1)
                fill_evt = {
                    "order_id": str(res.get("orderId"))
                    if res.get("orderId") is not None
                    else None,
                    "client_order_id": client_order_id,
                    "side": side,
                    "fill_qty": exec_qty,
                    "fill_price": fill_price,
                    "fee": fee,
                    "fee_asset": fee_asset,
                    "fee_raw": fee_raw,
                    "reason": reason,
                    "grid_index": a.get("grid_index"),
                    "symbol": symbol,
                    "cycle_id": cycle_id_for_trade,
                }
                if db is not None:
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "ORDER_FILLED",
                        f"{side} {exec_qty} @ {fill_price}",
                        fill_evt,
                        ts=fill_ts_utc,
                    )
                fill_evt["event_logged"] = True
                results.append(fill_evt)
                if side == "BUY" and reason == "trail_buy_grid":
                    pending_buy_level_actions += 1
                # Persist fill before tur kapanışı (CYCLE_END hata verse bile trades tablosunda kalsın)
                if db is not None:
                    try:
                        oid_early = res.get("orderId")
                        _ref_pre = state.get("reference_price")
                        ref_early = float(_ref_pre) if _ref_pre is not None else None
                        trade_row_early, inserted_early = Ledger.record_trade(
                            db,
                            bot_id,
                            account_id,
                            side,
                            exec_qty,
                            fill_price,
                            fee=fee,
                            fee_asset=fee_asset,
                            slot_id=a.get("grid_index"),
                            reference_price=ref_early,
                            order_id=str(oid_early) if oid_early is not None else None,
                            client_order_id=client_order_id,
                            symbol=symbol,
                            cycle_id=cycle_id_for_trade,
                        )
                        if inserted_early:
                            logger.info(
                                "BOT_TRADE_RECORDED bot_id=%s side=%s qty=%s price=%s fee=%s order_id=%s request_id=-",
                                bot_id,
                                side,
                                exec_qty,
                                fill_price,
                                fee,
                                oid_early,
                            )
                            try:
                                from app.services.transaction_history_file_store import (
                                    record_bot_trade_fill,
                                )

                                record_bot_trade_fill(
                                    db,
                                    account_id,
                                    bot_id,
                                    trade_row_early,
                                    symbol,
                                    quote_qty=cum_quote,
                                    fee_raw=fee_raw,
                                )
                            except Exception as tx_ex:
                                logger.debug(
                                    "tx_history record_bot_trade_fill bot_id=%s: %s",
                                    bot_id,
                                    tx_ex,
                                )
                    except Exception as ex:
                        logger.warning(
                            "bot_engine execution record_trade (early) failed bot_id=%s order_id=%s err=%s",
                            bot_id,
                            res.get("orderId"),
                            ex,
                        )
                if reason == "initial_allocation" and exec_qty > 0 and db is not None:
                    save_state(db, bot_id, account_id, state)
                    cid_ia = int(state.get("cycle_id") or 1)
                    tur_ts = fill_ts_utc + timedelta(seconds=1)
                    tb_ia = (
                        state.get("target_budgets")
                        if isinstance(state.get("target_budgets"), dict)
                        else {}
                    )
                    _base_ia = round(float(state.get("base_balance") or 0), 10)
                    _quote_ia = round(float(state.get("quote_balance") or 0), 2)
                    _ia_base_meta = {
                        "cycle_id": cid_ia,
                        "reason": "initial_allocation",
                        "first_tur": True,
                        "reference_price": round(float(fill_price), 10),
                        "base_qty": round(float(exec_qty), 10),
                        "base_balance": _base_ia,
                        "quote_balance": _quote_ia,
                        "equity_usdt": round(
                            float(state.get("cycle_start_equity") or 0), 2
                        ),
                        "target_quote_usdt": tb_ia.get("target_quote_usdt"),
                        "target_base_usdt": tb_ia.get("target_base_usdt"),
                        "symbol": symbol,
                    }
                    _ia_enriched = _build_cycle_start_meta(
                        state,
                        config,
                        _ia_base_meta,
                        float(fill_price),
                        _base_ia,
                        _quote_ia,
                    )
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "CYCLE_START",
                        "Tur başladı",
                        _ia_enriched,
                        ts=tur_ts,
                    )
                # Cycle reset MUST run before any load_state: in-memory state has _cycle_complete and updated balances.
                ref_price_for_ledger = state.get(
                    "reference_price"
                )  # referansı reset'ten önce al (gerçekleşme % doğru kalsın)
                if state.get("_cycle_complete") or reason in (
                    "trail_reentry_buy",
                    "trail_profit_sell",
                ):
                    pnl_mode = (
                        getattr(config, "pnl_mode", "cycle_only_fee_aware_v1")
                        or "cycle_only_fee_aware_v1"
                    )
                    ledger = state.get("cycle_ledger_current")
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        matched_qty = float(ledger.get("matched_qty") or 0)
                        # Dual PnL: primary by close_reason
                        close_reason = reason
                        pnl_primary_mode = (
                            PNL_MODE_CASH
                            if close_reason == "trail_profit_sell"
                            else (
                                PNL_MODE_INVENTORY
                                if close_reason == "trail_reentry_buy"
                                else "cycle_only_fee_aware_v1"
                            )
                        )
                        inv_coin_adv = float(ledger.get("inventory_coin_adv_qty") or 0)
                        inv_fees = float(ledger.get("inventory_fees_usdt") or 0)
                        cash_pnl = float(ledger.get("cash_pnl_usdt") or 0)
                        cash_fees = float(ledger.get("cash_fees_usdt") or 0)
                        # USDT net: only meaningful for Cash cycle; for Inventory cycle show 0 so UI uses inventory metric
                        if pnl_primary_mode == PNL_MODE_CASH:
                            pnl = round(cash_pnl, 4)
                            fees = round(cash_fees, 4)
                        else:
                            pnl = (
                                0.0
                                if pnl_primary_mode == PNL_MODE_INVENTORY
                                else round(
                                    float(ledger.get("realized_pnl_quote") or 0), 4
                                )
                            )
                            fees = (
                                round(inv_fees, 4)
                                if pnl_primary_mode == PNL_MODE_INVENTORY
                                else round(
                                    float(ledger.get("buy_fee_total_quote") or 0)
                                    + float(ledger.get("sell_fee_total_quote") or 0),
                                    4,
                                )
                            )
                    else:
                        pnl = round(float(state.get("realized_pnl_usdt_cycle") or 0), 4)
                        fees = round(float(state.get("fees_paid_usdt_cycle") or 0), 4)
                        matched_qty = None
                        close_reason = reason
                        pnl_primary_mode = "cycle_only_fee_aware_v1"
                        inv_coin_adv = inv_fees = cash_pnl = cash_fees = None
                    if not (pnl_mode == "cycle_only_fee_aware_v1" and ledger):
                        close_reason = reason
                    cycle_type, base_delta = get_cycle_type_and_base_delta(
                        close_reason, ledger
                    )
                    close_side = (
                        "SELL"
                        if close_reason == "trail_profit_sell"
                        else "BUY"
                        if close_reason == "trail_reentry_buy"
                        else (
                            "SELL" if "sell" in (close_reason or "").lower() else "BUY"
                        )
                    )
                    ts_iso = datetime.now(timezone.utc).isoformat()
                    # CYCLE_END invariant (Spec §55): derive ONLY from recomputed ledger. profit_usdt = gross, pnl_usdt_net = net.
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        float(ledger.get("cash_pnl_usdt") or 0)
                        fees_usdt_canon = float(ledger.get("cash_fees_usdt") or 0)
                        realized_net = float(ledger.get("realized_pnl_quote") or 0)
                        pnl = realized_net
                        fees = fees_usdt_canon
                    cycle_entry = {
                        "cycle_id": cycle_id_for_trade,
                        "pnl_usdt_net": pnl,
                        "fees_usdt": fees,
                        "matched_qty": matched_qty,
                        "cycle_type": cycle_type,
                        "base_delta": base_delta,
                        "close_reason": close_reason,
                        "close_side": close_side,
                        "pnl_mode": pnl_mode,
                        "pnl_primary_mode": pnl_primary_mode,
                        "inventory_coin_adv_qty": round(inv_coin_adv, 8)
                        if inv_coin_adv is not None
                        else None,
                        "inventory_fees_usdt": round(inv_fees, 4)
                        if inv_fees is not None
                        else None,
                        "cash_pnl_usdt": round(cash_pnl, 4)
                        if cash_pnl is not None
                        else None,
                        "cash_fees_usdt": round(cash_fees, 4)
                        if cash_fees is not None
                        else None,
                        "ts": ts_iso,
                    }
                    cycle_entry["pnl_usdt"] = pnl  # backward compat
                    if close_reason in ("trail_profit_sell", "trail_reentry_buy"):
                        close_fill: Dict[str, Any] = {
                            "qty": round(float(exec_qty), 10),
                            "price": round(float(fill_price), 8),
                            "execution_price": round(
                                float(a.get("execution_price") or fill_price), 8
                            ),
                            "tepe_price": round(
                                float(state.get("trail_anchor_price")), 8
                            )
                            if close_reason == "trail_profit_sell"
                            and state.get("trail_anchor_price") is not None
                            else None,
                            "dip_price": round(
                                float(state.get("trail_anchor_price")), 8
                            )
                            if close_reason == "trail_reentry_buy"
                            and state.get("trail_anchor_price") is not None
                            else None,
                        }
                        if close_reason == "trail_profit_sell":
                            if (
                                ledger
                                and ledger.get("avg_cost_quote_per_base") is not None
                            ):
                                close_fill["avg_cost_quote_per_base"] = round(
                                    float(ledger.get("avg_cost_quote_per_base")), 8
                                )
                        else:
                            from app.botengine.strategies.dca_grid_trailing import (
                                _avg_sell_grid_from_history,
                            )

                            avg_sell = _avg_sell_grid_from_history(
                                state.get("sell_history") or []
                            )
                            if avg_sell is not None:
                                close_fill["avg_sell_grid_quote_per_base"] = round(
                                    float(avg_sell), 8
                                )
                        cycle_entry["close_fill"] = close_fill
                    state.setdefault("cycle_pnls", []).append(cycle_entry)
                    state["realized_pnl_usdt_cycle"] = 0.0
                    state["fees_paid_usdt_cycle"] = 0.0
                    # Meta from ledger only: profit_usdt = cash_pnl (gross), pnl_usdt_net = realized_pnl_cycle_net
                    if pnl_mode == "cycle_only_fee_aware_v1" and ledger:
                        meta = {
                            "cycle_id": cycle_id_for_trade,
                            "symbol": symbol,
                            "profit_usdt": round(
                                float(ledger.get("cash_pnl_usdt") or 0), 2
                            ),
                            "pnl_usdt_net": round(
                                float(ledger.get("realized_pnl_quote") or 0), 4
                            ),
                            "realized_pnl_cycle_net": round(
                                float(ledger.get("realized_pnl_quote") or 0), 4
                            ),
                            "fees_usdt": round(
                                float(ledger.get("cash_fees_usdt") or 0), 4
                            ),
                            "buy_quote_total": ledger.get("buy_quote_total"),
                            "sell_quote_total": ledger.get("sell_quote_total"),
                            "fee_totals_quote": round(
                                float(ledger.get("cash_fees_usdt") or 0), 4
                            ),
                            "pnl_mode": pnl_mode,
                            "pnl_primary_mode": cycle_entry.get("pnl_primary_mode"),
                            "matched_qty": matched_qty,
                            "cycle_type": cycle_type,
                            "base_delta": base_delta,
                            "close_reason": close_reason,
                            "close_side": close_side,
                            "inventory_coin_adv_qty": cycle_entry.get(
                                "inventory_coin_adv_qty"
                            ),
                            "inventory_fees_usdt": cycle_entry.get(
                                "inventory_fees_usdt"
                            ),
                            "cash_pnl_usdt": round(
                                float(ledger.get("cash_pnl_usdt") or 0), 4
                            ),
                            "cash_fees_usdt": round(
                                float(ledger.get("cash_fees_usdt") or 0), 4
                            ),
                        }
                    else:
                        meta = {
                            "cycle_id": cycle_id_for_trade,
                            "symbol": symbol,
                            "profit_usdt": round(float(pnl), 2),
                            "pnl_usdt_net": pnl,
                            "pnl_mode": pnl_mode,
                            "pnl_primary_mode": cycle_entry.get("pnl_primary_mode"),
                            "matched_qty": matched_qty,
                            "fees_usdt": fees,
                            "cycle_type": cycle_type,
                            "base_delta": base_delta,
                            "close_reason": close_reason,
                            "close_side": close_side,
                            "inventory_coin_adv_qty": cycle_entry.get(
                                "inventory_coin_adv_qty"
                            ),
                            "inventory_fees_usdt": cycle_entry.get(
                                "inventory_fees_usdt"
                            ),
                            "cash_pnl_usdt": cycle_entry.get("cash_pnl_usdt"),
                            "cash_fees_usdt": cycle_entry.get("cash_fees_usdt"),
                        }
                    # Persist completed cycle dual PnL snapshot before reset (spec: completed_cycle_dual_pnls)
                    completed_list = state.get("completed_cycle_dual_pnls") or []
                    fills = ledger.get("fills") or []
                    last_fill_ts_iso = fills[-1].get("ts") if fills else ts_iso
                    cash_pnl = float(
                        ledger.get("cash_fifo_pnl_usdt")
                        if ledger.get("cash_fifo_pnl_usdt") is not None
                        else ledger.get("cash_pnl_usdt") or 0
                    )
                    cash_fees = float(
                        ledger.get("cash_fifo_fees_usdt")
                        if ledger.get("cash_fifo_fees_usdt") is not None
                        else ledger.get("cash_fees_usdt") or 0
                    )
                    inv_qty = float(ledger.get("inventory_coin_adv_qty") or 0)
                    inv_fees = float(ledger.get("inventory_fees_usdt") or 0)
                    cycle_type_snapshot = (
                        "CASH" if reason == "trail_profit_sell" else "INVENTORY"
                    )
                    completed_list.append(
                        {
                            "cycle_id": cycle_id_for_trade,
                            "cycle_type": cycle_type_snapshot,
                            "symbol": symbol,
                            "cash_pnl_usdt": round(cash_pnl, 8),
                            "cash_fees_usdt": round(cash_fees, 8),
                            "inventory_coin_adv_qty": round(inv_qty, 12),
                            "inventory_fees_usdt": round(inv_fees, 8),
                            "close_price_quote_per_base": round(float(fill_price), 8),
                            "started_at": ledger.get("started_at"),
                            "completed_at": last_fill_ts_iso,
                            "completed_reason": reason,
                        }
                    )
                    state["completed_cycle_dual_pnls"] = completed_list[
                        -200:
                    ]  # cap at 200
                    if db is not None:
                        try:
                            from app.services.bot_performance_service import (
                                record_bot_daily_cycle_pnl,
                                sync_bot_perf_store_from_state,
                            )

                            cycle_snapshot = completed_list[-1]
                            record_bot_daily_cycle_pnl(
                                db,
                                account_id,
                                bot_id,
                                symbol,
                                cycle_snapshot,
                                invalidate_cache=True,
                            )
                            sync_bot_perf_store_from_state(
                                db, bot_id, account_id, state, invalidate_cache=False
                            )
                        except Exception as perf_ex:
                            logger.debug(
                                "sync_bot_perf_store bot_id=%s: %s", bot_id, perf_ex
                            )
                    n = len(config.sell_grids)
                    m = len(config.buy_grids)
                    enriched_end_meta = _build_cycle_end_meta(
                        state, config, ledger, meta
                    )
                    cycle_reset_after_fill(state, fill_price, n, m, symbol=symbol)
                    if db is not None:
                        try:
                            cycle_end_ts = fill_ts_utc + timedelta(milliseconds=100)
                            cycle_start_ts = fill_ts_utc + timedelta(milliseconds=200)
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "CYCLE_END",
                                "Tur bitti",
                                enriched_end_meta,
                                ts=cycle_end_ts,
                            )
                            logger.info(
                                "BOT_CYCLE_END bot_id=%s cycle_id=%s pnl_usdt_net=%.4f cycle_type=%s base_delta=%s matched_qty=%s fees_usdt=%.4f pnl_mode=%s",
                                bot_id,
                                cycle_id_for_trade,
                                pnl,
                                cycle_type,
                                base_delta,
                                matched_qty,
                                fees,
                                pnl_mode,
                            )
                            new_cid = int(state.get("cycle_id") or 1)
                            quote_bal_cs = _num(state.get("quote_balance"))
                            base_bal_cs = _num(state.get("base_balance"))
                            equity_cs = round(
                                quote_bal_cs + base_bal_cs * fill_price, 2
                            )
                            quote_alloc_cs = (
                                _num(getattr(config, "quote_alloc_pct", 50)) / 100.0
                            )
                            base_alloc_cs = (
                                _num(getattr(config, "base_alloc_pct", 50)) / 100.0
                            )
                            target_quote_cs = round(equity_cs * quote_alloc_cs, 2)
                            target_base_cs = round(equity_cs * base_alloc_cs, 2)
                            state["target_budgets"] = {
                                "equity_usdt": equity_cs,
                                "target_quote_usdt": target_quote_cs,
                                "target_base_usdt": target_base_cs,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            }
                            # CYCLE_START base meta
                            _cs_base_meta = {
                                "cycle_id": new_cid,
                                "reference_price": round(float(fill_price), 10),
                                "base_qty": round(float(base_bal_cs), 10),
                                "base_balance": round(float(base_bal_cs), 10),
                                "quote_balance": round(float(quote_bal_cs), 2),
                                "equity_usdt": round(
                                    float(state.get("cycle_start_equity") or equity_cs),
                                    2,
                                ),
                                "target_quote_usdt": target_quote_cs,
                                "target_base_usdt": target_base_cs,
                                "symbol": symbol,
                                "carry_over": True,
                                "prev_close_reason": close_reason,
                            }
                            # CYCLE_START — zenginleştirilmiş meta (breakeven, grid fiyatları, rebalance oranı)
                            enriched_start_meta = _build_cycle_start_meta(
                                state,
                                config,
                                _cs_base_meta,
                                fill_price,
                                base_bal_cs,
                                quote_bal_cs,
                            )
                            append_event(
                                db,
                                bot_id,
                                account_id,
                                "CYCLE_START",
                                "Tur başladı",
                                enriched_start_meta,
                                ts=cycle_start_ts,
                            )
                            # Grid özet — her 10 turda bir
                            _maybe_emit_grid_summary(
                                db, bot_id, account_id, state, config, new_cid
                            )
                            for row in reversed(state.get("cycle_open_trades") or []):
                                if not isinstance(row, dict):
                                    continue
                                if int(row.get("cycle_id") or 0) != int(new_cid):
                                    continue
                                row["target_quote_usdt"] = target_quote_cs
                                row["target_base_usdt"] = target_base_cs
                                break
                        except Exception as cycle_evt_ex:
                            logger.warning(
                                "bot_engine CYCLE_END/START events failed bot_id=%s cycle_id=%s err=%s",
                                bot_id,
                                cycle_id_for_trade,
                                cycle_evt_ex,
                            )
                    # Reinvest policy: target budgets from equity (order sizing reference only; no rebalance order)
                    quote_bal = _num(state.get("quote_balance"))
                    base_bal = _num(state.get("base_balance"))
                    equity_usdt = round(quote_bal + base_bal * fill_price, 2)
                    quote_alloc = _num(getattr(config, "quote_alloc_pct", 50)) / 100.0
                    base_alloc = _num(getattr(config, "base_alloc_pct", 50)) / 100.0
                    target_quote_usdt = round(equity_usdt * quote_alloc, 2)
                    target_base_usdt = round(equity_usdt * base_alloc, 2)
                    if not isinstance(state.get("target_budgets"), dict) or not state[
                        "target_budgets"
                    ].get("target_quote_usdt"):
                        state["target_budgets"] = {
                            "equity_usdt": equity_usdt,
                            "target_quote_usdt": target_quote_usdt,
                            "target_base_usdt": target_base_usdt,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    logger.info(
                        "BOT_TARGET_BUDGETS_UPDATED bot_id=%s equity_usdt=%.2f target_quote=%.2f target_base=%.2f base_bal=%.6f quote_bal=%.2f price=%.4f",
                        bot_id,
                        equity_usdt,
                        target_quote_usdt,
                        target_base_usdt,
                        base_bal,
                        quote_bal,
                        fill_price,
                    )
                # Patch-1: persist fill to trades table (idempotent by order_id)
                if db is not None:
                    try:
                        oid = res.get("orderId")
                        ref_float = (
                            float(ref_price_for_ledger)
                            if ref_price_for_ledger is not None
                            else None
                        )
                        trade_row, inserted = Ledger.record_trade(
                            db,
                            bot_id,
                            account_id,
                            side,
                            exec_qty,
                            fill_price,
                            fee=fee,
                            fee_asset=fee_asset,
                            slot_id=a.get("grid_index"),
                            reference_price=ref_float,
                            order_id=str(oid) if oid is not None else None,
                            client_order_id=client_order_id,
                            symbol=symbol,
                            cycle_id=cycle_id_for_trade,
                        )
                        if inserted:
                            logger.info(
                                "BOT_TRADE_RECORDED bot_id=%s side=%s qty=%s price=%s fee=%s order_id=%s request_id=-",
                                bot_id,
                                side,
                                exec_qty,
                                fill_price,
                                fee,
                                oid,
                            )
                            try:
                                from app.services.transaction_history_file_store import (
                                    record_bot_trade_fill,
                                )

                                record_bot_trade_fill(
                                    db,
                                    account_id,
                                    bot_id,
                                    trade_row,
                                    symbol,
                                    quote_qty=cum_quote,
                                    fee_raw=fee_raw,
                                )
                            except Exception as tx_ex:
                                logger.debug(
                                    "tx_history record_bot_trade_fill bot_id=%s: %s",
                                    bot_id,
                                    tx_ex,
                                )
                    except Exception as ex:
                        logger.warning(
                            "bot_engine execution record_trade failed bot_id=%s order_id=%s err=%s",
                            bot_id,
                            res.get("orderId"),
                            ex,
                        )
                    try:
                        update_virtual_after_fill(
                            db, bot_id, symbol, side, exec_qty, cum_quote, fee
                        )
                    except Exception as ex:
                        logger.warning(
                            "bot_engine execution update_virtual_after_fill failed bot_id=%s err=%s",
                            bot_id,
                            ex,
                        )
                    # Önce snapshot (cache hâlâ geçerliyse kullanılır); sonra cache temizle —
                    # invalidate→fetch sırası throttle'a takılıp gereksiz WARNING üretiyordu.
                    try:
                        await _write_fill_snapshot_to_state(
                            state, adapter, config, symbol
                        )
                    except Exception as snap_err:
                        logger.warning(
                            "bot_engine execution write_fill_snapshot failed bot_id=%s err=%s",
                            bot_id,
                            snap_err,
                        )
                    if not adapter.paper_mode and adapter.keys:
                        try:
                            from app.services.binance_spot import (
                                invalidate_account_cache_for_keys,
                            )

                            await invalidate_account_cache_for_keys(adapter.keys)
                        except Exception:
                            pass
                trigger_price = _num(a.get("trigger_price"))
                if trigger_price and trigger_price > 0 and db is not None:
                    max_slip = float(getattr(config, "max_slippage_pct", 0.5) or 0.5)
                    slip_pct = abs(fill_price - trigger_price) / trigger_price * 100.0
                    if slip_pct > max_slip:
                        append_event(
                            db,
                            bot_id,
                            account_id,
                            "SLIPPAGE_WARN",
                            f"slip_pct={slip_pct:.2f} max={max_slip} trigger={trigger_price} fill={fill_price}",
                            {
                                "slip_pct": slip_pct,
                                "max_slippage_pct": max_slip,
                                "trigger_price": trigger_price,
                                "fill_price": fill_price,
                                "reason": reason,
                            },
                        )
                        logger.warning(
                            "BOT SLIPPAGE_WARN bot_id=%s slip_pct=%.2f trigger=%.2f fill=%.2f",
                            bot_id,
                            slip_pct,
                            trigger_price,
                            fill_price,
                        )
            except Exception as e:
                error_id = str(uuid.uuid4())
                logger.warning(
                    "RUN_ACTION_EXCEPTION error_code=RUN_ACTION_EXCEPTION error_id=%s bot_id=%s account_id=%s action_key=%s loop_id=%s err=%s",
                    error_id,
                    bot_id,
                    account_id,
                    key,
                    loop_id or "",
                    e,
                )
                if db is not None:
                    append_event(
                        db,
                        bot_id,
                        account_id,
                        "ERROR",
                        f"RUN_ACTION_EXCEPTION {error_id} {e!s}",
                        {
                            "error_code": "RUN_ACTION_EXCEPTION",
                            "error_id": error_id,
                            "bot_id": bot_id,
                            "account_id": account_id,
                            "action_key": key,
                            "loop_id": loop_id,
                        },
                    )
                    try:
                        from app.botengine.health_watch import emit_resilience_continue

                        emit_resilience_continue(
                            db,
                            bot_id,
                            account_id,
                            "RUN_ACTION_EXCEPTION",
                            str(e),
                            error_id=error_id,
                            loop_id=loop_id,
                        )
                    except Exception:
                        pass
                state["last_error_code"] = "RUN_ACTION_EXCEPTION"
                state["health_error_since"] = int(time.time())
                continue
    duration_ms = (time.perf_counter() - t0) * 1000
    logger.info("run_actions end bot_id=%s duration_ms=%.0f", bot_id, duration_ms)
    return results
