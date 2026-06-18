"""
Bot performans özeti: aylık tur verisi + kural tabanlı Türkçe yorum (AI benzeri anlatım).
Veri kaynağı: completed_cycle_dual_pnls + bot_perf dosyası; bot.started_at alt sınır.
"""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.botengine.state_store import load_state
from app.db.models import Bot
from app.services.bot_perf_narrative_templates import pick as _pick, pool_size  # noqa: F401
from app.services.bot_performance_service import (
    _bot_config_initial,
    _completed_cycle_side,
    _cycle_close_price_usdt,
    _parse_ts_utc,
    aggregate_dual_perf_closed_cycles,
    base_from_symbol,
    ts_to_date_tr,
)
from app.utils.tz_utils import TR_TZ

MONTH_NAMES_TR = (
    "",
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


def month_key_to_label(month_key: str) -> str:
    try:
        y, m = month_key.split("-", 1)
        mi = int(m)
        if 1 <= mi <= 12:
            return f"{MONTH_NAMES_TR[mi]} {y}"
    except (TypeError, ValueError):
        pass
    return month_key


def _bot_started_at_tr(bot: Bot) -> Optional[datetime]:
    sa = getattr(bot, "started_at", None)
    if sa is None:
        return None
    if sa.tzinfo is None:
        sa = sa.replace(tzinfo=timezone.utc)
    return sa.astimezone(TR_TZ)


def _bot_start_month_key(bot: Bot) -> str:
    sa_tr = _bot_started_at_tr(bot)
    if sa_tr is not None:
        return sa_tr.strftime("%Y-%m")
    return datetime.now(TR_TZ).strftime("%Y-%m")


def _cycle_month_key(entry: Dict[str, Any]) -> Optional[str]:
    d = ts_to_date_tr(entry.get("completed_at"))
    if not d or len(d) < 7:
        return None
    return d[:7]


def _cycle_dedupe_key(entry: Dict[str, Any]) -> str:
    cid = entry.get("cycle_id")
    at = entry.get("completed_at") or ""
    return f"{cid}:{at}"


def load_bot_completed_cycles_merged(
    db: Session, bot: Bot, state: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """State + dosya birleşimi; started_at sonrası."""
    from app.services.bot_perf_file_store import (
        list_bot_completed_cycles,
        reconcile_bot_cycles_file_with_state,
    )

    state = state if state is not None else load_state(db, bot.id)
    sym = (bot.symbol or "").strip().upper()
    completed = list((state or {}).get("completed_cycle_dual_pnls") or [])
    try:
        reconcile_bot_cycles_file_with_state(bot.id, bot.account_id, sym, completed)
        file_cycles = list_bot_completed_cycles(bot.id)
    except Exception:
        file_cycles = []

    seen = {_cycle_dedupe_key(c) for c in completed if isinstance(c, dict)}
    merged = [c for c in completed if isinstance(c, dict)]
    for entry in file_cycles:
        if not isinstance(entry, dict):
            continue
        key = _cycle_dedupe_key(entry)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)

    start_month = _bot_start_month_key(bot)
    start_sa = _bot_started_at_tr(bot)
    out: List[Dict[str, Any]] = []
    for entry in merged:
        mk = _cycle_month_key(entry)
        if mk is None:
            continue
        if mk < start_month:
            continue
        if start_sa is not None:
            ts = _parse_ts_utc(entry.get("completed_at"))
            if ts is not None and ts < start_sa.astimezone(timezone.utc):
                continue
        out.append(entry)

    out.sort(
        key=lambda e: (
            _parse_ts_utc(e.get("completed_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    return out


def enumerate_month_keys_from_start(start_month_key: str) -> List[str]:
    """Bot açılış ayından bugünkü TR ayına kadar (dahil) YYYY-MM listesi."""
    now = datetime.now(TR_TZ)
    end_key = now.strftime("%Y-%m")
    try:
        sy, sm = [int(x) for x in start_month_key.split("-", 1)]
    except (TypeError, ValueError):
        return [end_key]
    keys: List[str] = []
    y, m = sy, sm
    while True:
        key = f"{y:04d}-{m:02d}"
        keys.append(key)
        if key >= end_key:
            break
        m += 1
        if m > 12:
            m = 1
            y += 1
    return keys


def _month_date_range(month_key: str) -> Tuple[str, str]:
    y, m = [int(x) for x in month_key.split("-", 1)]
    last = monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"


def _format_usd(v: float) -> str:
    # Always carry an explicit sign so a loss never reads like a gain
    # (e.g. -$0.35, not "$0.35").
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):.2f}"


def _format_cost_usd(v: float) -> str:
    return f"${abs(v):.2f}"


def _format_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _alpha_reading(session_alpha_pct: Optional[float]) -> str:
    if session_alpha_pct is None:
        return ""
    if session_alpha_pct >= 2:
        return (
            "Alpha pozitif: bot, aynı dönemde aynı sermayeyle coini yalnızca elde tutma "
            "(al-tut) senaryosunu geçmiş; yani aktif grid ticareti benchmark'ın üzerine "
            "net değer katmış."
        )
    if session_alpha_pct <= -2:
        return (
            "Alpha negatif: kapanan turlar USDT kârı üretmiş olsa da, oturum genelinde "
            "bot al-tut benchmarkının gerisinde kalmış. Bu bir zarar değil, bir fırsat "
            "maliyetidir: bu pencerede coini hiç işlem yapmadan tutmak daha yüksek "
            "getiri sağlayabilirdi."
        )
    return (
        "Alpha nötre yakın: botun getirisi ile coini yalnızca elde tutma senaryosu "
        "birbirine yakın seyretmiş; aktif ticaret bu pencerede belirgin bir avantaj veya "
        "dezavantaj yaratmamış."
    )


def _cycle_duration_hours(entry: Dict[str, Any]) -> Optional[float]:
    start = _parse_ts_utc(entry.get("started_at"))
    end = _parse_ts_utc(entry.get("completed_at"))
    if start is None or end is None:
        return None
    secs = (end - start).total_seconds()
    if secs < 0:
        return None
    return round(secs / 3600.0, 1)


def _market_regime_label(pct_change: Optional[float]) -> str:
    if pct_change is None:
        return "belirsiz"
    if pct_change >= 3.0:
        return "yükseliş eğilimli"
    if pct_change <= -3.0:
        return "düşüş eğilimli"
    return "yatay / dalgalı"


def _sustainability_assessment(
    *,
    net_cash: float,
    gross_cash: float,
    fees: float,
    cycles: int,
    win_cycles: int,
    cash_cycles: int,
    inv_cycles: int,
    session_alpha_pct: Optional[float] = None,
) -> Tuple[int, str, List[str]]:
    """Compute the sustainability score (unchanged arithmetic) and return the
    list of TEMPLATE CATEGORIES that explain it. The builder turns each category
    into a varied, professional sentence from the permanent pool."""
    score = 50
    cats: List[str] = []
    if cycles == 0:
        return 40, "Veri yetersiz", ["__no_data__"]

    if net_cash > 0:
        score += 18
        cats.append("sustain_net_pos")
    elif net_cash < 0:
        score -= 15
        cats.append("sustain_net_neg")

    if cycles >= 2:
        win_rate = win_cycles / cycles
        if win_rate >= 0.6:
            score += 12
            cats.append("sustain_winrate_high")
        elif win_rate < 0.4:
            score -= 10
            cats.append("sustain_winrate_low")

    fee_ratio = (fees / abs(gross_cash)) if abs(gross_cash) > 1e-9 else 0.0
    if fee_ratio <= 0.15:
        score += 10
        cats.append("sustain_fee_low")
    elif fee_ratio > 0.35:
        score -= 8
        cats.append("sustain_fee_high")

    if cash_cycles > 0 and inv_cycles > 0:
        score += 8
        cats.append("sustain_dual")
    elif cycles >= 3 and (cash_cycles == 0 or inv_cycles == 0):
        score -= 5
        cats.append("sustain_single")

    if session_alpha_pct is not None:
        if session_alpha_pct >= 2:
            score += 6
            cats.append("sustain_alpha_pos")
        elif session_alpha_pct <= -2:
            score -= 8
            cats.append("sustain_alpha_neg")
        else:
            cats.append("sustain_alpha_flat")

    score = max(0, min(100, score))
    if score >= 75:
        label = "Güçlü"
    elif score >= 55:
        label = "Orta"
    else:
        label = "Zayıf"
    return score, label, cats


def _narrate_single_cycle(
    entry: Dict[str, Any], base_asset: str, initial_capital: float, seed: str = ""
) -> Dict[str, Any]:
    side = _completed_cycle_side(entry) or "?"
    cid = entry.get("cycle_id")
    reason = str(entry.get("completed_reason") or entry.get("close_reason") or "")
    cash = float(entry.get("cash_pnl_usdt") or 0)
    cash_fees = float(entry.get("cash_fees_usdt") or 0)
    inv = float(entry.get("inventory_coin_adv_qty") or 0)
    inv_fees = float(entry.get("inventory_fees_usdt") or 0)
    close_px = _cycle_close_price_usdt(entry, entry.get("symbol"))
    dur_h = _cycle_duration_hours(entry)

    net_usd = cash - cash_fees if side == "BUY" else 0.0
    outcome = (
        "kârlı"
        if (side == "BUY" and net_usd > 0) or (side == "SELL" and inv > 0)
        else (
            "zararlı"
            if (side == "BUY" and net_usd < 0) or (side == "SELL" and inv < 0)
            else "nötr"
        )
    )

    if side == "BUY":
        direction = "Aşağı yön — nakit turu"
        lead_cat = (
            "cycle_buy_neutral"
            if net_usd == 0
            else "cycle_buy_loss"
            if net_usd < 0
            else "cycle_buy_profit"
        )
        mech_cat = (
            "cycle_mech_profit_sell"
            if reason == "trail_profit_sell"
            else "cycle_mech_buy_generic"
        )
    else:
        direction = "Yukarı yön — envanter turu"
        lead_cat = (
            "cycle_sell_neutral"
            if inv == 0
            else "cycle_sell_loss"
            if inv < 0
            else "cycle_sell_profit"
        )
        mech_cat = (
            "cycle_mech_reentry"
            if reason == "trail_reentry_buy"
            else "cycle_mech_sell_generic"
        )

    cinputs = {
        "cid": cid,
        "base": base_asset,
        "gross_c": _format_usd(cash),
        "fees_c": _format_cost_usd(cash_fees),
        "net_c": _format_usd(net_usd),
        "inv_c": f"{'+' if inv >= 0 else ''}{inv:.8f}",
        "dur_h": f"{dur_h:.1f}" if dur_h is not None else "",
    }
    cseed = f"{seed}|{cid}"

    # Lead (carries the figures + outcome) + mechanism, both from the pool.
    parts = [_pick(lead_cat, cseed, cinputs), _pick(mech_cat, cseed, cinputs)]
    if close_px > 0:
        parts.append(f"Kapanış fiyatı {close_px:.4f} USDT/{base_asset}.")
    if dur_h is not None:
        parts.append(
            _pick("cycle_dur_short" if dur_h < 24 else "cycle_dur_long", cseed, cinputs)
        )
    if initial_capital > 0 and side == "BUY" and cash != 0:
        parts.append(
            f"Başlangıç bütçesine göre net nakit etki {_format_pct(net_usd / initial_capital * 100)}."
        )
    parts = [p for p in parts if p]

    return {
        "cycle_id": cid,
        "side": side,
        "direction_label": direction,
        "outcome": outcome,
        "cash_pnl_usdt": round(cash, 4),
        "cash_fees_usdt": round(cash_fees, 4),
        "inventory_coin_adv_qty": round(inv, 12),
        "inventory_fees_usdt": round(inv_fees, 4),
        "close_price": round(close_px, 8) if close_px > 0 else None,
        "duration_hours": dur_h,
        "narrative": " ".join(parts),
    }


def build_month_narrative(
    *,
    month_key: str,
    cycles: List[Dict[str, Any]],
    symbol: str,
    initial_capital: float,
    session_alpha_pct: Optional[float] = None,
) -> Dict[str, Any]:
    base_asset = base_from_symbol(symbol)
    date_from, date_to = _month_date_range(month_key)
    agg = aggregate_dual_perf_closed_cycles(
        cycles, initial_capital=initial_capital, date_from=date_from, date_to=date_to
    )
    month_cycles = [c for c in cycles if _cycle_month_key(c) == month_key]

    cash_pnl = float(agg.get("cash_pnl_usdt") or 0)
    cash_fees = float(agg.get("cash_fees_usdt") or 0)
    inv_coin = float(agg.get("inventory_pnl_coin") or 0)
    inv_fees = float(agg.get("inventory_fees_usdt") or 0)
    cash_closed = int(agg.get("cash_closed_cycles") or 0)
    inv_closed = int(agg.get("inventory_closed_cycles") or 0)
    total_cycles = cash_closed + inv_closed
    net_cash = cash_pnl - cash_fees

    prices = [
        _cycle_close_price_usdt(c, symbol)
        for c in month_cycles
        if _cycle_close_price_usdt(c, symbol) > 0
    ]
    price_change_pct: Optional[float] = None
    if len(prices) >= 2 and prices[0] > 0:
        price_change_pct = (prices[-1] - prices[0]) / prices[0] * 100.0

    seed = f"{month_key}|{symbol}"
    cycle_narratives = [
        _narrate_single_cycle(c, base_asset, initial_capital, seed)
        for c in month_cycles
    ]
    win_cycles = sum(1 for cn in cycle_narratives if cn.get("outcome") == "kârlı")
    win_rate = (win_cycles / total_cycles) if total_cycles > 0 else 0.0

    score, score_label, sustain_cats = _sustainability_assessment(
        net_cash=net_cash,
        gross_cash=cash_pnl,
        fees=cash_fees + inv_fees,
        cycles=total_cycles,
        win_cycles=win_cycles,
        cash_cycles=cash_closed,
        inv_cycles=inv_closed,
        session_alpha_pct=session_alpha_pct,
    )

    label = month_key_to_label(month_key)
    regime = _market_regime_label(price_change_pct)
    total_fee = cash_fees + inv_fees

    # Rich, pre-formatted inputs the template pool fills with REAL data.
    inputs: Dict[str, Any] = {
        "label": label,
        "symbol": symbol,
        "base": base_asset,
        "total": total_cycles,
        "cash_closed": cash_closed,
        "inv_closed": inv_closed,
        "gross": _format_usd(cash_pnl),
        "fees": _format_cost_usd(cash_fees),
        "net": _format_usd(net_cash),
        "inv_coin": f"{'+' if inv_coin >= 0 else ''}{inv_coin:.8f}",
        "inv_fees": _format_cost_usd(inv_fees),
        "total_fees": _format_cost_usd(total_fee),
        "fee_per_cycle": _format_cost_usd(total_fee / total_cycles)
        if total_cycles > 0
        else "$0.00",
        "alpha": _format_pct(session_alpha_pct)
        if session_alpha_pct is not None
        else "",
        "regime": regime,
        "price_change": _format_pct(price_change_pct)
        if price_change_pct is not None
        else "",
        # Absolute magnitude for directional verbs ("3.50% gerilemiş") so a
        # signed value never collides with the verb's own direction.
        "price_abs": f"{abs(price_change_pct):.2f}%"
        if price_change_pct is not None
        else "",
        "winrate": f"%{win_rate * 100:.0f}",
        "score": score,
        "score_label": score_label,
    }

    # ---- Headline (covers every dual-leg scenario) ----
    if total_cycles == 0:
        hl_cat = "headline.no_cycles"
    elif net_cash > 0.005:  # cash leg clearly positive
        if session_alpha_pct is not None and session_alpha_pct > 2:
            hl_cat = "headline.pos_alpha_pos"
        elif session_alpha_pct is not None and session_alpha_pct < -2:
            hl_cat = "headline.pos_alpha_neg"
        else:
            hl_cat = "headline.pos_alpha_flat"
    elif net_cash < -0.005:  # cash leg negative
        if session_alpha_pct is not None and session_alpha_pct > 2:
            hl_cat = "headline.neg_alpha_pos"  # lost cash but beat a falling market
        else:
            hl_cat = "headline.neg"
    else:  # cash ~ 0 → let the inventory (coin) leg lead
        if inv_closed > 0 and inv_coin > 1e-12:
            hl_cat = "headline.inv_led"
        elif inv_closed > 0 and inv_coin < -1e-12:
            hl_cat = "headline.inv_led_neg"
        else:
            hl_cat = "headline.zero"
    headline = _pick(hl_cat, seed, inputs)

    # ---- Summary ----
    cash_led = abs(net_cash) <= 0.005 and inv_closed > 0
    summary_paragraphs = [
        _pick("summary_intro", seed, inputs),
        _pick("summary_cash_inv_led" if cash_led else "summary_cash", seed, inputs),
    ]
    if inv_closed > 0:
        # "avantaj" wording only when the coin change is non-negative.
        inv_cat = "summary_inv_present" if inv_coin >= 0 else "summary_inv_neg"
        summary_paragraphs.append(_pick(inv_cat, seed, inputs))
    elif total_cycles > 0:
        summary_paragraphs.append(_pick("summary_inv_absent", seed, inputs))
    if session_alpha_pct is not None:
        a_band = (
            "alpha_pos"
            if session_alpha_pct >= 2
            else "alpha_neg"
            if session_alpha_pct <= -2
            else "alpha_flat"
        )
        summary_paragraphs.append(
            _pick("alpha_def", seed, inputs) + " " + _pick(a_band, seed, inputs)
        )

    # ---- Market context ----
    market_paragraphs: List[str] = []
    if price_change_pct is not None:
        regime_cat = {
            "yükseliş eğilimli": "market_up",
            "düşüş eğilimli": "market_down",
            "yatay / dalgalı": "market_flat",
        }.get(regime, "market_flat")
        market_paragraphs.append(_pick(regime_cat, seed, inputs))
        market_paragraphs.append(_pick("market_caveat", seed, inputs))
        if price_change_pct > 0 and net_cash < 0:
            market_paragraphs.append(_pick("market_up_cash_neg", seed, inputs))
        elif price_change_pct < 0 and net_cash > 0:
            market_paragraphs.append(_pick("market_down_cash_pos", seed, inputs))
    else:
        market_paragraphs.append(_pick("market_unknown", seed, inputs))

    # ---- Strategy balance ----
    strategy_paragraphs: List[str] = []
    if cash_closed > inv_closed * 2:
        strategy_paragraphs.append(_pick("strategy_cash_heavy", seed, inputs))
        if inv_closed == 0 and cash_closed > 0:
            strategy_paragraphs.append(_pick("strategy_single_leg", seed, inputs))
    elif inv_closed > cash_closed * 2:
        strategy_paragraphs.append(_pick("strategy_inv_heavy", seed, inputs))
    elif total_cycles > 0:
        strategy_paragraphs.append(_pick("strategy_balanced", seed, inputs))

    # ---- Fees ----
    fee_paragraphs = [
        _pick("fees_zero" if total_fee <= 0 else "fees_total", seed, inputs)
    ]
    if total_cycles > 0 and total_fee > 0:
        fee_paragraphs.append(_pick("fees_per_cycle", seed, inputs))

    # ---- Sustainability notes (one varied sentence per scored factor) ----
    if total_cycles == 0:
        sustain_notes = [
            "Bu ay henüz kapanmış tur bulunmuyor; sürdürülebilirlik puanı veri "
            "yetersizliği nedeniyle nötrün altında tutuldu."
        ]
    else:
        sustain_notes = [
            _pick(cat, f"{seed}|s{i}", inputs) for i, cat in enumerate(sustain_cats)
        ]

    # ---- Outlook ----
    outlook_paragraphs: List[str] = []
    if total_cycles > 0:
        if score >= 75 and session_alpha_pct is not None and session_alpha_pct < -2:
            outlook_paragraphs.append(_pick("outlook_strong_alpha_neg", seed, inputs))
        elif score >= 75:
            outlook_paragraphs.append(_pick("outlook_strong", seed, inputs))
        elif score >= 55:
            outlook_paragraphs.append(_pick("outlook_medium", seed, inputs))
        else:
            outlook_paragraphs.append(_pick("outlook_weak", seed, inputs))
        if session_alpha_pct is not None and session_alpha_pct < -2:
            outlook_paragraphs.append(_pick("outlook_alpha_neg_reminder", seed, inputs))
        elif session_alpha_pct is not None and session_alpha_pct > 2:
            outlook_paragraphs.append(_pick("outlook_alpha_pos_note", seed, inputs))

    return {
        "month_key": month_key,
        "month_label": label,
        "headline": headline,
        "metrics": {
            "total_cycles": total_cycles,
            "cash_closed_cycles": cash_closed,
            "inventory_closed_cycles": inv_closed,
            "cash_pnl_usdt": round(cash_pnl, 4),
            "cash_fees_usdt": round(cash_fees, 4),
            "net_cash_usdt": round(net_cash, 4),
            "inventory_pnl_coin": round(inv_coin, 12),
            "inventory_fees_usdt": round(inv_fees, 4),
            "price_change_pct": round(price_change_pct, 2)
            if price_change_pct is not None
            else None,
            "market_regime": regime,
            "sustainability_score": score,
            "sustainability_label": score_label,
        },
        "sections": [
            {
                "id": "summary",
                "title": "Genel değerlendirme",
                "paragraphs": summary_paragraphs,
            },
            {
                "id": "market",
                "title": "Piyasa bağlamı",
                "paragraphs": market_paragraphs,
            },
            {
                "id": "cycles",
                "title": "Tur bazlı analiz",
                "items": cycle_narratives,
            },
            {
                "id": "strategy",
                "title": "Strateji dengesi",
                "paragraphs": strategy_paragraphs,
            },
            {
                "id": "fees",
                "title": "Komisyon verimliliği",
                "paragraphs": fee_paragraphs,
            },
            {
                "id": "sustainability",
                "title": "Sürdürülebilirlik",
                "score": score,
                "label": score_label,
                "paragraphs": sustain_notes,
            },
            {
                "id": "outlook",
                "title": "Öngörü",
                "paragraphs": outlook_paragraphs,
            },
        ],
    }


def build_perf_narrative_overview(
    db: Session,
    bot: Bot,
    *,
    session_alpha_pct: Optional[float] = None,
) -> Dict[str, Any]:
    state = load_state(db, bot.id)
    sym = (bot.symbol or "").strip().upper()
    initial = _bot_config_initial(bot)
    cycles = load_bot_completed_cycles_merged(db, bot, state)
    start_month = _bot_start_month_key(bot)
    month_keys = enumerate_month_keys_from_start(start_month)

    months_out: List[Dict[str, Any]] = []
    for mk in reversed(month_keys):
        date_from, date_to = _month_date_range(mk)
        agg = aggregate_dual_perf_closed_cycles(
            cycles, initial_capital=initial, date_from=date_from, date_to=date_to
        )
        total = int(agg.get("cash_closed_cycles") or 0) + int(
            agg.get("inventory_closed_cycles") or 0
        )
        net = float(agg.get("cash_pnl_usdt") or 0) - float(
            agg.get("cash_fees_usdt") or 0
        )
        one_line = (
            f"{total} tur · net nakit {_format_usd(net)}"
            if total > 0
            else "Henüz kapanmış tur yok"
        )
        months_out.append(
            {
                "month_key": mk,
                "month_label": month_key_to_label(mk),
                "year": int(mk.split("-")[0]),
                "total_cycles": total,
                "net_cash_usdt": round(net, 2),
                "one_line": one_line,
                "has_activity": total > 0,
            }
        )

    years = sorted({m["year"] for m in months_out}, reverse=True)
    show_year_filter = len(month_keys) > 12

    overview_lines = [
        f"Bot {month_key_to_label(start_month)} tarihinden beri çalışıyor; "
        f"{len(month_keys)} ay takvim penceresi listeleniyor.",
        f"Toplam {len(cycles)} kapanmış tur kayıtlı (mevcut oturum, started_at sonrası).",
    ]
    if session_alpha_pct is not None:
        overview_lines.append(
            f"Güncel oturum performansı (alpha): {_format_pct(session_alpha_pct)}."
        )

    return {
        "bot_id": bot.id,
        "symbol": sym,
        "start_month_key": start_month,
        "months": months_out,
        "years": years,
        "show_year_filter": show_year_filter,
        "overview_paragraphs": overview_lines,
    }


def build_perf_narrative_month_detail(
    db: Session,
    bot: Bot,
    month_key: str,
    *,
    session_alpha_pct: Optional[float] = None,
) -> Dict[str, Any]:
    start_month = _bot_start_month_key(bot)
    if month_key < start_month:
        return {
            "error": "MONTH_BEFORE_BOT_START",
            "message": "Seçilen ay bot başlangıcından önce.",
        }
    state = load_state(db, bot.id)
    sym = (bot.symbol or "").strip().upper()
    initial = _bot_config_initial(bot)
    cycles = load_bot_completed_cycles_merged(db, bot, state)
    detail = build_month_narrative(
        month_key=month_key,
        cycles=cycles,
        symbol=sym,
        initial_capital=initial,
        session_alpha_pct=session_alpha_pct,
    )
    detail["symbol"] = sym
    detail["initial_capital_usdt"] = round(initial, 2) if initial > 0 else None
    return detail
