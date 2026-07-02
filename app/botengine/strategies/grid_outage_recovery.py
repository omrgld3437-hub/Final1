"""
Grid / kar alım — bağlantı kopması veya tick boşluğu sonrası state düzeltmesi.

Kopma sırasında tick çalışmadığı için tepe/dip/gerçekleşme güncellenmez; erişim dönünce
mevcut fiyata göre grid ve kar alım durumu yeniden değerlendirilir. Emir üretimi tick içinde
normal akış + _outage_* bayrakları ile yapılır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.models import BotEngineMode, DcaGridTrailingConfig

logger = logging.getLogger(__name__)


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 10)
    except (TypeError, ValueError):
        return None


def _float(x: Any, default: float) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def gap_threshold_sec(config: DcaGridTrailingConfig) -> float:
    tick = max(1.0, _float(getattr(config, "tick_interval_ms", 5000), 5000) / 1000.0)
    return max(30.0, tick * 3.0)


def _parse_state_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def seconds_since_last_tick(state: Dict[str, Any]) -> Optional[float]:
    dt = _parse_state_dt(state.get("last_tick_at"))
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds())


def is_cold_run_start(state: Dict[str, Any]) -> bool:
    """STOP sonrası yeni START — son tick önceki oturuma ait; outage recovery değil."""
    run_dt = _parse_state_dt(state.get("bot_run_started_at"))
    tick_dt = _parse_state_dt(state.get("last_tick_at"))
    if run_dt is None or tick_dt is None:
        return False
    return tick_dt < run_dt


def clear_pending_grid_triggers(
    state: Dict[str, Any], config: DcaGridTrailingConfig
) -> None:
    """Armed (tetiklenmiş) ama henüz fired olmamış grid tetiklerini sıfırla."""
    n = len(config.sell_grids)
    m = len(config.buy_grids)
    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    sell_trig = list(state.get("sell_grid_trigger_price") or [])
    buy_trig = list(state.get("buy_grid_trigger_price") or [])
    sell_peak = list(state.get("sell_grid_peak_price") or [])
    buy_trough = list(state.get("buy_grid_trough_price") or [])
    cleared = False
    for i in range(n):
        if i < len(sell_fired) and sell_fired[i]:
            continue
        if i < len(sell_trig) and sell_trig[i] is not None:
            sell_trig[i] = None
            cleared = True
        if i < len(sell_peak) and sell_peak[i] is not None:
            sell_peak[i] = None
    for j in range(m):
        if j < len(buy_fired) and buy_fired[j]:
            continue
        if j < len(buy_trig) and buy_trig[j] is not None:
            buy_trig[j] = None
            cleared = True
        if j < len(buy_trough) and buy_trough[j] is not None:
            buy_trough[j] = None
    state["sell_grid_trigger_price"] = sell_trig
    state["buy_grid_trigger_price"] = buy_trig
    state["sell_grid_peak_price"] = sell_peak
    state["buy_grid_trough_price"] = buy_trough
    if cleared:
        mode = state.get("mode") or BotEngineMode.IDLE.value
        if mode in (
            BotEngineMode.TRAIL_SELL_GRID.value,
            BotEngineMode.TRAIL_BUY_GRID.value,
        ):
            state["mode"] = BotEngineMode.IDLE.value
        logger.info(
            "BOT_COLD_START_GRID_RESET bot_id=%s cycle_id=%s",
            state.get("bot_id"),
            state.get("cycle_id"),
        )


def maybe_reset_cold_start_grids(
    state: Dict[str, Any], config: DcaGridTrailingConfig
) -> None:
    if not is_cold_run_start(state):
        return
    if state.get("_cold_start_grids_cleared"):
        return
    clear_pending_grid_triggers(state, config)
    state["_cold_start_grids_cleared"] = True


def prepare_grids_for_cold_run_start(
    state: Dict[str, Any], config_raw: Dict[str, Any]
) -> None:
    """STOP→START sonrası bekleyen grid tetiklerini temizle (UI + ilk tick)."""
    try:
        cfg = DcaGridTrailingConfig(config_raw)
    except Exception:
        return
    maybe_reset_cold_start_grids(state, cfg)


def should_apply_outage_recovery(
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
) -> Tuple[bool, Optional[float]]:
    gap = seconds_since_last_tick(state)
    if gap is None:
        return False, None
    if is_cold_run_start(state):
        return False, gap
    threshold = gap_threshold_sec(config)
    if gap < threshold:
        return False, gap
    return True, gap


def _clear_outage_flags(state: Dict[str, Any]) -> None:
    state["_outage_favorable_buy"] = []
    state["_outage_favorable_sell"] = []
    state["_outage_force_profit_sell"] = False
    state["_outage_force_reentry_buy"] = False


def _reset_sell_grid_trigger(state: Dict[str, Any], idx: int) -> None:
    triggers = state.get("sell_grid_trigger_price") or []
    peaks = state.get("sell_grid_peak_price") or []
    if idx < len(triggers):
        triggers[idx] = None
    if idx < len(peaks):
        peaks[idx] = None
    state["sell_grid_trigger_price"] = triggers
    state["sell_grid_peak_price"] = peaks


def _log_note(log_notes: Optional[List[str]], text: str) -> None:
    if log_notes is not None and text:
        log_notes.append(text)


def _recover_sell_grid(
    state: Dict[str, Any],
    idx: int,
    P: float,
    trigger: float,
    sell_trail_pct: float,
    favorable: List[int],
    log_notes: Optional[List[str]] = None,
) -> None:
    peaks = state.get("sell_grid_peak_price") or []
    while len(peaks) <= idx:
        peaks.append(None)
    had_real_peak = peaks[idx] is not None
    peak = _f(peaks[idx]) if peaks[idx] is not None else trigger
    peak = max(peak or trigger, trigger, P)
    exec_thr = peak * (1.0 - sell_trail_pct / 100.0)

    if P <= exec_thr:
        if not had_real_peak:
            # Gerçek tur içi tepe hiç gözlenmemiş (kopma, grid'in ilk tetiklendiği
            # anı da kapsıyor): peak burada trigger'dan fabrike edildi (gerçek bir
            # veri değil). Bunu hemen "favorable" sayıp satmak, hiç doğrulanmamış
            # kurgusal bir tepeye göre erken/abartılı satışa yol açıyordu (Tepe
            # fiyat hiç gözlenmeden satış tetikleniyordu). Gerçek bir geçmiş tepe
            # yokken canlı tick'teki gibi davran: yalnızca peak'ten
            # sell_trail_pct kadar gerçek bir geri çekilme gözlenince sat.
            peaks[idx] = peak
            state["sell_grid_peak_price"] = peaks
            logger.info(
                "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=CONTINUE_TRAIL_NO_HISTORY price=%.4f exec=%.4f trigger=%.4f",
                state.get("bot_id"),
                idx,
                P,
                exec_thr,
                trigger,
            )
            return
        peaks[idx] = peak
        state["sell_grid_peak_price"] = peaks
        favorable.append(idx)
        _log_note(
            log_notes,
            f"Üst satış grid #{idx + 1}: kopma sonrası uygun fiyat; kaçırılan satış işlenecek.",
        )
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=EXEC_FAVORABLE price=%.4f exec=%.4f peak=%.4f",
            state.get("bot_id"),
            idx,
            P,
            exec_thr,
            peak,
        )
        return

    if exec_thr < trigger and P < trigger:
        peaks[idx] = max(peak, P)
        state["sell_grid_peak_price"] = peaks
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=CONTINUE_TRAIL price=%.4f exec=%.4f trigger=%.4f",
            state.get("bot_id"),
            idx,
            P,
            exec_thr,
            trigger,
        )
        return

    if exec_thr >= trigger and P < trigger:
        _reset_sell_grid_trigger(state, idx)
        _log_note(
            log_notes,
            f"Üst satış grid #{idx + 1}: fiyat tetik altına indi ({P:.2f} < {trigger:.2f}); "
            "kesinti sırasındaki tetik geçersiz sayıldı, grid yeniden bekliyor (tur aynı).",
        )
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=RESET reason=price_below_trigger price=%.4f trigger=%.4f",
            state.get("bot_id"),
            idx,
            P,
            trigger,
        )
        return

    if P <= exec_thr and P >= trigger:
        peak = max(peak, P)
        peaks[idx] = peak
        state["sell_grid_peak_price"] = peaks
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=REANCHOR_PEAK price=%.4f exec=%.4f",
            state.get("bot_id"),
            idx,
            P,
            peak * (1.0 - sell_trail_pct / 100.0),
        )
        return

    peaks[idx] = peak
    state["sell_grid_peak_price"] = peaks
    logger.info(
        "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=REANCHOR_PEAK price=%.4f exec=%.4f",
        state.get("bot_id"),
        idx,
        P,
        peak * (1.0 - sell_trail_pct / 100.0),
    )


def _recover_buy_grid(
    state: Dict[str, Any],
    idx: int,
    P: float,
    trigger: float,
    buy_trail_pct: float,
    favorable: List[int],
    log_notes: Optional[List[str]] = None,
) -> None:
    troughs = state.get("buy_grid_trough_price") or []
    while len(troughs) <= idx:
        troughs.append(None)
    had_real_trough = troughs[idx] is not None
    trough = _f(troughs[idx]) if troughs[idx] is not None else trigger
    trough = min(trough or trigger, trigger, P)
    exec_thr = trough * (1.0 + buy_trail_pct / 100.0)

    if P < exec_thr:
        if exec_thr > trigger and P > trigger:
            troughs[idx] = trough
            state["buy_grid_trough_price"] = troughs
            logger.info(
                "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=CONTINUE_TRAIL price=%.4f exec=%.4f trigger=%.4f",
                state.get("bot_id"),
                idx,
                P,
                exec_thr,
                trigger,
            )
            return
        troughs[idx] = trough
        state["buy_grid_trough_price"] = troughs
        if not had_real_trough:
            # Gerçek tur içi dip hiç gözlenmemiş (kopma, grid'in ilk tetiklendiği
            # anı da kapsıyor): trough burada P'den türetildiği için P'ye eşit
            # ya da çok yakın çıkar. Bunu hemen "favorable" sayıp ateşlemek,
            # trailing yüzdesini fiilen sıfırlayıp Dip fiyat ≈ Gerçekleşme
            # fiyatı sonucunu doğuruyordu. Gerçek bir geçmiş dip yokken canlı
            # tick'teki gibi davran: yalnızca trough'tan buy_trail_pct kadar
            # gerçek bir sıçrama gözlenince ateşle.
            logger.info(
                "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=CONTINUE_TRAIL_NO_HISTORY price=%.4f exec=%.4f trigger=%.4f",
                state.get("bot_id"),
                idx,
                P,
                exec_thr,
                trigger,
            )
            return
        favorable.append(idx)
        _log_note(
            log_notes,
            f"Alt alım grid #{idx + 1}: kopma sonrası uygun fiyat; kaçırılan alım işlenecek.",
        )
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=EXEC_FAVORABLE price=%.4f exec=%.4f trough=%.4f",
            state.get("bot_id"),
            idx,
            P,
            exec_thr,
            trough,
        )
        return

    if P >= exec_thr:
        troughs[idx] = trough
        state["buy_grid_trough_price"] = troughs
        if P <= trigger:
            trough = min(trough, P)
            troughs[idx] = trough
            state["buy_grid_trough_price"] = troughs
            logger.info(
                "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=REANCHOR_TROUGH price=%.4f exec=%.4f",
                state.get("bot_id"),
                idx,
                P,
                exec_thr,
            )
            return
        favorable.append(idx)
        _log_note(
            log_notes,
            f"Alt alım grid #{idx + 1}: kopma sonrası uygun fiyat; kaçırılan alım işlenecek.",
        )
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=EXEC_FAVORABLE price=%.4f exec=%.4f trough=%.4f",
            state.get("bot_id"),
            idx,
            P,
            exec_thr,
            trough,
        )
        return

    trough = min(trough, P)
    troughs[idx] = trough
    state["buy_grid_trough_price"] = troughs
    logger.info(
        "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=REANCHOR_TROUGH price=%.4f exec=%.4f",
        state.get("bot_id"),
        idx,
        P,
        trough * (1.0 + buy_trail_pct / 100.0),
    )


def _recover_waiting_sell_grid(
    state: Dict[str, Any],
    idx: int,
    P: float,
    trigger: float,
    sell_trail_pct: float,
    favorable: List[int],
    *,
    base_balance: float = 0.0,
) -> None:
    from app.botengine.strategies.dca_grid_trailing import _try_trigger_sell_grid

    if not _try_trigger_sell_grid(state, idx, P, trigger, base_balance=base_balance):
        return
    exec_thr = P * (1.0 - sell_trail_pct / 100.0)
    if P > exec_thr:
        favorable.append(idx)
    logger.info(
        "BOT_OUTAGE_RECOVERY bot_id=%s grid=sell idx=%s action=TRIGGER_WHILE_OFFLINE price=%.4f trigger=%.4f",
        state.get("bot_id"),
        idx,
        P,
        trigger,
    )


def _recover_waiting_buy_grid(
    state: Dict[str, Any],
    idx: int,
    P: float,
    trigger: float,
    buy_trail_pct: float,
    favorable: List[int],
) -> None:
    from app.botengine.strategies.dca_grid_trailing import _try_trigger_buy_grid

    if not _try_trigger_buy_grid(state, idx, P, trigger):
        return
    exec_thr = P * (1.0 + buy_trail_pct / 100.0)
    if P < exec_thr:
        favorable.append(idx)
    logger.info(
        "BOT_OUTAGE_RECOVERY bot_id=%s grid=buy idx=%s action=TRIGGER_WHILE_OFFLINE price=%.4f trigger=%.4f",
        state.get("bot_id"),
        idx,
        P,
        trigger,
    )


def _recover_profit_exit(
    state: Dict[str, Any], config: DcaGridTrailingConfig, P: float
) -> None:
    old_anchor = _f(state.get("trail_anchor_price"))
    anchor = max(old_anchor or P, P)
    state["trail_anchor_price"] = anchor
    drop_pct = _float(config.profit_exit_drop_pct, 0.3)
    thr = anchor * (1.0 - drop_pct / 100.0)
    breakeven = _f(state.get("_profit_exit_breakeven"))
    if breakeven is not None and breakeven > 0:
        thr = max(thr, breakeven)
    if P <= thr:
        state["_outage_force_profit_sell"] = True
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s mode=TRAIL_PROFIT_SELL action=EXEC_MISSED_DROP price=%.4f thr=%.4f",
            state.get("bot_id"),
            P,
            thr,
        )
    elif old_anchor is not None and anchor > old_anchor and P >= thr:
        state["_outage_force_profit_sell"] = True
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s mode=TRAIL_PROFIT_SELL action=EXEC_NEW_HIGH price=%.4f thr=%.4f anchor=%.4f",
            state.get("bot_id"),
            P,
            thr,
            anchor,
        )


def _recover_reentry_buy(
    state: Dict[str, Any], config: DcaGridTrailingConfig, P: float
) -> None:
    old_anchor = _f(state.get("trail_anchor_price"))
    anchor = min(old_anchor or P, P)
    state["trail_anchor_price"] = anchor
    rise_pct = _float(config.profit_reentry_rise_pct, 0.3)
    thr = anchor * (1.0 + rise_pct / 100.0)
    max_buy = _f(state.get("_reentry_max_buy_price"))
    if max_buy is not None and max_buy > 0 and P > max_buy:
        return
    if P >= thr:
        state["_outage_force_reentry_buy"] = True
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s mode=TRAIL_REENTRY_BUY action=EXEC_MISSED_RISE price=%.4f thr=%.4f",
            state.get("bot_id"),
            P,
            thr,
        )
    elif old_anchor is not None and anchor < old_anchor and P <= thr:
        state["_outage_force_reentry_buy"] = True
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s mode=TRAIL_REENTRY_BUY action=EXEC_NEW_LOW price=%.4f thr=%.4f anchor=%.4f",
            state.get("bot_id"),
            P,
            thr,
            anchor,
        )


def _flush_connectivity_stable_after_outage(
    db: Any,
    bot_id: int,
    state: Dict[str, Any],
    *,
    previous_error: str = "OUTAGE_RECOVERY",
) -> None:
    """Kopma değerlendirme logundan sonra yeşil stabil satır (CONNECTIVITY_STABLE)."""
    try:
        from app.db.models import Bot
        from app.services.binance_connectivity import (
            flush_pending_connectivity_stable,
            mark_pending_connectivity_stable,
        )

        bot = db.query(Bot).filter(Bot.id == int(bot_id)).first()
        if not bot or (bot.status or "").lower() != "running":
            return
        if not state.get("_pending_connectivity_stable"):
            mark_pending_connectivity_stable(
                db, bot, state, previous_error=previous_error
            )
        flush_pending_connectivity_stable(db, bot_id, after_loop_restart=False)
    except Exception as e:
        logger.debug("outage_recovery stable bot_id=%s: %s", bot_id, e)
    finally:
        state.pop("_pending_connectivity_stable", None)
        state.pop("_pending_connectivity_stable_at", None)
        state.pop("_pending_connectivity_stable_prev_err", None)


def flush_outage_recovery_log_to_events(
    db: Any, bot_id: int, account_id: int, state: Dict[str, Any]
) -> None:
    """tick sonrası kopma değerlendirme notunu bot_engine_events'e yaz."""
    log = state.pop("_outage_recovery_log", None)
    if not log or db is None:
        return
    try:
        from app.botengine.state_store import append_event

        append_event(
            db,
            bot_id,
            account_id,
            "INFO",
            log.get("message") or "Kopma sonrası grid değerlendirmesi",
            log.get("meta") or {},
        )
        meta = log.get("meta") or {}
        prev_err = (
            meta.get("health_code") or meta.get("error_code") or "OUTAGE_RECOVERY"
        ).strip()
        _flush_connectivity_stable_after_outage(
            db, bot_id, state, previous_error=prev_err or "OUTAGE_RECOVERY"
        )
    except Exception as e:
        logger.debug("flush_outage_recovery_log bot_id=%s: %s", bot_id, e)


def apply_grid_outage_recovery(
    state: Dict[str, Any],
    config: DcaGridTrailingConfig,
    price: float,
    *,
    gap_sec: Optional[float] = None,
) -> None:
    """
    Kopma / tick boşluğu sonrası grid ve kar-alım state'ini günceller.
    Senaryo 1 (gri bölge, tetik yok): değişiklik yok.
    Tetikli gridler: kaçan tetik sıfırlanır; uygun fiyatta anında işlem bayrağı;
    kaçırılan gerçekleşmede tepe/dip yeniden hesaplanır.
    """
    P = _f(price)
    if P is None or P <= 0:
        return
    if not state.get("initial_allocation_done"):
        return

    _clear_outage_flags(state)
    favorable_buy: List[int] = []
    favorable_sell: List[int] = []
    log_notes: List[str] = []

    ref = _f(state.get("reference_price"))
    if ref is None or ref <= 0:
        ref = P

    n = len(config.sell_grids)
    m = len(config.buy_grids)
    sell_trail = _float(config.sell_trigger_trailing_pct, 0.3)
    buy_trail = _float(config.buy_trigger_trailing_pct, 0.3)
    cycle_side = state.get("cycle_grid_side")
    if cycle_side not in ("SELL", "BUY"):
        cycle_side = None
    sell_enabled = cycle_side != "BUY"
    buy_enabled = cycle_side != "SELL"

    mode = state.get("mode") or BotEngineMode.IDLE.value
    if mode == BotEngineMode.TRAIL_PROFIT_SELL.value:
        _recover_profit_exit(state, config, P)
    elif mode == BotEngineMode.TRAIL_REENTRY_BUY.value:
        _recover_reentry_buy(state, config, P)

    sell_fired = state.get("sell_grid_fired") or []
    buy_fired = state.get("buy_grid_fired") or []
    sell_triggers = state.get("sell_grid_trigger_price") or []
    buy_triggers = state.get("buy_grid_trigger_price") or []
    base_bal = _f(state.get("base_balance")) or 0.0
    parallel_sell = 0
    parallel_buy = 0

    for i in range(n):
        if not sell_enabled:
            break
        if i < len(sell_fired) and sell_fired[i]:
            continue
        trig = sell_triggers[i] if i < len(sell_triggers) else None
        trig_f = _f(trig)
        if trig_f is not None:
            _recover_sell_grid(
                state, i, P, trig_f, sell_trail, favorable_sell, log_notes
            )
        else:
            g = config.sell_grids[i] if i < len(config.sell_grids) else {}
            pct = _float(g.get("sell_grid_pct") or g.get("trigger_pct"), 0)
            s_i = ref * (1.0 + pct / 100.0)
            if P >= s_i:
                before = sell_triggers[i] if i < len(sell_triggers) else None
                _recover_waiting_sell_grid(
                    state, i, P, s_i, sell_trail, favorable_sell, base_balance=base_bal
                )
                if (
                    before is None
                    and i < len(state.get("sell_grid_trigger_price") or [])
                    and state["sell_grid_trigger_price"][i] is not None
                ):
                    parallel_sell += 1

    for j in range(m):
        if not buy_enabled:
            break
        if j < len(buy_fired) and buy_fired[j]:
            continue
        trig = buy_triggers[j] if j < len(buy_triggers) else None
        trig_f = _f(trig)
        if trig_f is not None:
            _recover_buy_grid(state, j, P, trig_f, buy_trail, favorable_buy, log_notes)
        else:
            g = config.buy_grids[j] if j < len(config.buy_grids) else {}
            pct = _float(g.get("buy_grid_pct") or g.get("trigger_pct"), 0)
            b_j = ref * (1.0 - pct / 100.0)
            if P <= b_j:
                before = buy_triggers[j] if j < len(buy_triggers) else None
                _recover_waiting_buy_grid(state, j, P, b_j, buy_trail, favorable_buy)
                if (
                    before is None
                    and j < len(state.get("buy_grid_trigger_price") or [])
                    and state["buy_grid_trigger_price"][j] is not None
                ):
                    parallel_buy += 1

    if parallel_sell > 1 or parallel_buy > 1:
        logger.info(
            "BOT_OUTAGE_PARALLEL_TRIGGER bot_id=%s sell=%s buy=%s price=%.4f",
            state.get("bot_id"),
            parallel_sell,
            parallel_buy,
            P,
        )

    state["_outage_favorable_buy"] = favorable_buy
    state["_outage_favorable_sell"] = favorable_sell
    state["_outage_recovery_at"] = datetime.now(timezone.utc).isoformat()

    cycle_id = int(state.get("cycle_id") or 1)
    summary_lines: List[str] = []
    if gap_sec is not None:
        summary_lines.append(
            f"Bağlantı/tick boşluğu {gap_sec:.0f} sn — Tur {cycle_id} devam ediyor (yeni tur açılmadı)."
        )
    if log_notes:
        summary_lines.extend(log_notes)
    elif gap_sec is not None:
        summary_lines.append("Aktif grid tetikleri geçerli; ek sıfırlama gerekmedi.")
    if summary_lines:
        state["_outage_recovery_log"] = {
            "message": "Kopma sonrası grid değerlendirmesi",
            "meta": {
                "health_code": "OUTAGE_RECOVERY",
                "gap_sec": gap_sec,
                "cycle_id": cycle_id,
                "price": P,
                "tur_restarted": False,
                "actions": log_notes,
                "summary": " ".join(summary_lines),
            },
        }

    if gap_sec is not None:
        logger.info(
            "BOT_OUTAGE_RECOVERY bot_id=%s gap_sec=%.1f price=%.4f favorable_buy=%s favorable_sell=%s notes=%s",
            state.get("bot_id"),
            gap_sec,
            P,
            favorable_buy,
            favorable_sell,
            len(log_notes),
        )
