"""Human-readable explanations for Dynamic Param Score decisions."""

from __future__ import annotations

from app.services.dynamic_param_score.models import (
    BotParams,
    FinalAction,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.regime_display import (
    build_pattern_phrase,
    render_risk_opportunity_sentence,
    risk_label_from_route,
)
from app.services.dynamic_param_score.atmosphere import regime_text_for_explanation, regime_code_from_route

_REGIME_TR = {
    RegimeTag.NO_DATA.value: "veri yetersiz",
    RegimeTag.NO_TRADE.value: "işlem için uygun değil",
    RegimeTag.DUMP_RISK.value: "sert düşüş riski",
    RegimeTag.TRENDING_DOWN.value: "aşağı baskılı trend",
    RegimeTag.HIGH_VOL_UNSTABLE.value: "yüksek volatilite / dengesiz",
    RegimeTag.RANGE_LOW_VOL.value: "düşük volatilite aralık",
    RegimeTag.RANGE_HIGH_VOL.value: "yüksek volatilite aralık",
    RegimeTag.BALANCED_RANGE.value: "dengeli aralık",
    RegimeTag.TRENDING_UP.value: "yükseliş trendi",
    RegimeTag.BREAKOUT_RISK.value: "kırılım riski",
    RegimeTag.LOW_LIQUIDITY.value: "düşük likidite",
    RegimeTag.SPREAD_UNSAFE.value: "güvensiz spread",
}

_BLOCKING_TR = {
    "FEE_FLOOR_IMPOSSIBLE": "komisyon tabanı grid aralığına sığmıyor",
    "MIN_NOTIONAL_FAIL": "minimum emir tutarı karşılanamıyor",
    "BUDGET_TOO_SMALL": "bütçe çok düşük",
    "DATA_QUALITY_LOW": "veri kalitesi yetersiz",
    "LIQUIDITY_LOW": "likidite çok düşük",
    "SPREAD_HIGH": "spread çok yüksek",
    "DUMP_RISK": "sert düşüş riski",
    "PARAM_SCORE_TOO_LOW": "parametre skoru çok düşük",
    "SINGLE_LEVEL_TOO_LARGE": "tek kademe alım kotası çok büyük",
}

_TEMPLATE_WAIT_EXPLAIN = {
    "BALANCED_RANGE_60_69_FEE_BAD_WAIT": (
        "Emir boyutu geçerli; ancak mevcut grid aralığı fee/spread/trailing sonrası verimsiz kalıyor. "
        "Bu nedenle sistem beklemeye geçmedi, gridleri genişleterek ACTIVE_DEFENSIVE_GRID profili seçti."
    ),
}

_TEMPLATE_DEFENSIVE_EXPLAIN = {
    "ACTIVE_DEFENSIVE_GRID": (
        "Fee verimi düşük veya risk artmış; gridler genişletildi ve savunmacı aktif mod seçildi."
    ),
}

_TEMPLATE_SELL_EXPLAIN = {
    "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT": (
        "Yeni alış grid'i fee/headroom nedeniyle kapatıldı; mevcut base için satış yönetimi bırakıldı."
    ),
}

_TEMPLATE_WIDE_GRID_EXPLAIN = {
    "BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID": (
        "Fee verimi zayıf olduğu için dar grid yerine daha geniş aralıklı ve az kademeli dengeli grid seçildi."
    ),
}


def _blocking_tr(code: str) -> str:
    c = (code or "").strip().upper()
    return _BLOCKING_TR.get(c, c.replace("_", " ").lower())


_RISK_TR = {
    "SAFE": "güvenli",
    "NORMAL": "normal",
    "CAUTION": "dikkatli",
    "DEFENSIVE": "savunmacı",
    "BLOCKED": "engelli",
}


def _fee_wait_reason(sub: SubScores) -> str | None:
    fee = int(sub.fee_efficiency_score or 0)
    if fee < 30:
        return f"fee efficiency {fee}/100 olduğu için dar grid verimli değil"
    if fee < 50:
        return f"fee efficiency {fee}/100 zayıf; grid kâr alanı dar"
    return None


def _risk_context_reasons(risk_state: str, sub: SubScores) -> list[str]:
    """Risk state ile tutarlı nedenler — NORMAL iken savunmacı dil kullanma."""
    reasons: list[str] = []
    if risk_state == "DEFENSIVE":
        if sub.drawdown_risk_score < 40:
            reasons.append("drawdown riski yüksek")
        if sub.btc_market_risk_score < 40:
            reasons.append("BTC piyasa riski negatif")
    if sub.spread_score < 40:
        reasons.append("spread/fee verimliliği zayıf")
    if sub.liquidity_score < 40:
        reasons.append("likidite düşük")
    return reasons


def _rebalance_explain_suffix(rebalance_plan: dict | None) -> str:
    if not rebalance_plan:
        return ""
    notes = rebalance_plan.get("notes") or ""
    action = rebalance_plan.get("rebalance_action") or ""
    if action in ("NO_REBALANCE", "PASSIVE_REBALANCE"):
        if notes:
            return f" Dengeleme: {notes}"
        return ""
    allowed_q = rebalance_plan.get("allowed_rebalance_quote_usdt") or 0
    allowed_b = rebalance_plan.get("allowed_rebalance_base_usdt") or 0
    if allowed_q > 0:
        return f" Dengeleme: hedefe kademeli alış (bu tur en fazla ${allowed_q:.2f}). {notes}".strip()
    if allowed_b > 0:
        return f" Dengeleme: hedefe kademeli satış (bu tur en fazla ${allowed_b:.2f}). {notes}".strip()
    if notes:
        return f" Dengeleme: {notes}"
    return ""


def build_explanation(
    param_score: int,
    regime_tag: str,
    risk_state: str,
    final_action: str,
    sub: SubScores,
    params: BotParams | None,
    blocking: list,
    *,
    selected_template_key: str | None = None,
    fallback_reason: str | None = None,
    rebalance_plan: dict | None = None,
    indicators: dict | None = None,
    budget_usdt: float | None = None,
) -> str:
    route_key = str((indicators or {}).get("route_key") or "")
    regime_txt = regime_text_for_explanation(route_key, regime_tag)
    regime_label = regime_txt
    if route_key and len(route_key.split("|")) == 7:
        risk_txt = risk_label_from_route(route_key).lower()
    else:
        risk_txt = _RISK_TR.get(risk_state, risk_state)

    if final_action in (
        FinalAction.WAIT.value,
        FinalAction.WAIT_SAFETY.value,
        FinalAction.SAFE_WAIT.value,
    ):
        tmpl_hint = _TEMPLATE_WAIT_EXPLAIN.get(selected_template_key or "")
        if tmpl_hint:
            return (
                f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
                f"Risk durumu {risk_txt}. {tmpl_hint}"
            )
        fee_reason = _fee_wait_reason(sub)
        parts: list[str] = []
        if fee_reason:
            parts.append(fee_reason)
        if blocking:
            labels = [_blocking_tr(b) for b in blocking[:3]]
            parts.append("engeller: " + ", ".join(labels))
        elif fallback_reason in ("no_headroom_no_base", "no_eligible_template"):
            parts.append(
                "mevcut headroom/min-notional koşulları uygulanabilir grid üretmedi"
            )
        if not parts:
            parts.append("şu an yeni emir açılmıyor; izleme / bekleme modu")
        detail = "; ".join(parts).capitalize()
        return (
            f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
            f"Risk durumu {risk_txt}. {detail}. Bu yüzden sistem beklemeyi seçti."
        )

    if final_action == FinalAction.NO_TRADE.value:
        reasons = _risk_context_reasons(risk_state, sub)
        fee_reason = _fee_wait_reason(sub)
        if fee_reason and fee_reason not in reasons:
            reasons.insert(0, fee_reason)
        if blocking:
            labels = [_blocking_tr(b) for b in blocking[:3]]
            reasons.append("engeller: " + ", ".join(labels))
        reason_txt = ", ".join(reasons) if reasons else "koşullar uygun değil"
        return (
            f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
            f"Risk durumu {risk_txt}. {reason_txt.capitalize()}. "
            f"Bu koşulda yeni alış veya satış yönetimi önerilmedi."
        )

    if params is None and final_action in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
    ):
        fee_reason = _fee_wait_reason(sub)
        parts: list[str] = []
        if fee_reason:
            parts.append(fee_reason)
        if sub.liquidity_score < 50:
            parts.append("likidite düşük")
        if fallback_reason == "fee_bad_wide_grid_active":
            parts.append(
                "fee verimi düşük olduğu için geniş aralıklı savunmacı grid profili seçildi"
            )
        if blocking:
            parts.append("engeller: " + ", ".join(_blocking_tr(b) for b in blocking[:2]))
        detail = "; ".join(parts).capitalize() if parts else "Savunmacı mod seçildi"
        return (
            f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
            f"Risk durumu {risk_txt}. {detail}. "
            f"Canlı deploy güvenlik kapılarına bağlı; referans grid parametreleri gösterilebilir."
        )

    if params is None:
        reasons = _risk_context_reasons(risk_state, sub)
        fee_reason = _fee_wait_reason(sub)
        if fee_reason and fee_reason not in reasons:
            reasons.insert(0, fee_reason)
        if blocking:
            labels = [_blocking_tr(b) for b in blocking[:3]]
            reasons.append("engeller: " + ", ".join(labels))
        reason_txt = ", ".join(reasons) if reasons else "koşullar uygun değil"
        return (
            f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
            f"Risk durumu {risk_txt}. {reason_txt.capitalize()}. "
            f"Bu koşulda yeni alış veya satış yönetimi önerilmedi."
        )

    if final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        sell_n = int(params.sell_grid_count or 0) if params else 0
        base_pct = round(params.base_alloc_frac * 100, 1) if params else 0
        tmpl_hint = _TEMPLATE_SELL_EXPLAIN.get(selected_template_key or "")
        if tmpl_hint:
            return (
                f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
                f"Risk durumu {risk_txt}. {tmpl_hint} "
                f"Alış 0 · Satış {sell_n} kademe."
                + (f" Base tahsisi yaklaşık %{base_pct}." if base_pct else "")
            )
        fee_note = ""
        fee_reason = _fee_wait_reason(sub)
        if fee_reason:
            fee_note = f" {fee_reason.capitalize()};"
        return (
            f"Parametre Skoru {param_score}/100. Rejim {regime_label}. "
            f"Risk durumu {risk_txt}.{fee_note} "
            f"Yeni alış grid'i fee/headroom nedeniyle kapatıldı; mevcut base için satış yönetimi bırakıldı. "
            f"Alış 0 · Satış {sell_n} kademe. Base tahsisi yaklaşık %{base_pct}."
        )

    base_pct = round(params.base_alloc_frac * 100, 1)
    quote_pct = round(params.quote_alloc_frac * 100, 1)
    max_exp = round(params.max_base_exposure_frac * 100, 1)
    profile_hint = ""
    if selected_template_key and "WIDE_GRID" in selected_template_key:
        profile_hint = _TEMPLATE_WIDE_GRID_EXPLAIN.get(
            selected_template_key,
            "fee verimi düşük; geniş aralıklı düşük kademeli dengeli grid seçildi",
        )
    elif final_action == FinalAction.ACTIVE_DEFENSIVE_GRID.value:
        structure_note = ""
        profile_hint = ""
        ind = indicators or {}
        hh = bool(ind.get("higher_highs"))
        ll = bool(ind.get("lower_lows"))
        rs = float(ind.get("range_stability") or 0.5)
        pattern = build_pattern_phrase(higher_highs=hh, lower_lows=ll, range_stability=rs)
        if pattern and pattern != "belirsiz/chop yapı":
            structure_note = f" {pattern.capitalize()} nedeniyle savunmacı downbuy grid seçildi."
        elif ind.get("lower_lows") and not ind.get("higher_highs"):
            structure_note = " Lower lows yapısı nedeniyle alış tarafı satışa göre daha geniş açıldı."
        elif ind.get("higher_highs") and not ind.get("lower_lows"):
            structure_note = " Higher highs yapısı nedeniyle satış tarafı alışa göre daha geniş açıldı."
        else:
            structure_note = ""
        budget_note = ""
        if budget_usdt and params:
            budget_note = (
                f" Bütçe {budget_usdt:.0f} USDT olduğu için satış tarafında "
                f"{params.sell_grid_count} grid, alış tarafında {params.buy_grid_count} grid seçildi."
            )
        fee_note = ""
        if sub.fee_efficiency_score < 50:
            fee_note = " Fee verimi düşük olduğu için bekleme yapılmadı; gridler genişletildi."
        confidence_note = ""
        if param_score < 35:
            confidence_note = (
                " Güven düşük olduğu için ACTIVE_DEFENSIVE_GRID seçildi; "
                "alış rebalance güvenli görülmediği için alış merdiveni küçük tutuldu."
            )
        route_key = ""
        if indicators:
            route_key = str(indicators.get("route_key") or "")
        pool_note = (
            f"192.780 raflı V5 kütüphane canlıda taranmaz; "
            f"{route_key + ' route_key' if route_key else 'route imzası'} ile exact shelf lookup yapılır."
        )
        if fallback_reason:
            pool_note += f" Fallback: {fallback_reason}."
        if not profile_hint:
            profile_hint = (
                f"{structure_note}{budget_note}{fee_note}{confidence_note} {pool_note}"
            ).strip()
        elif structure_note or budget_note or fee_note or confidence_note:
            profile_hint = (
                f"{profile_hint}.{structure_note}{budget_note}{fee_note}{confidence_note}"
            ).strip()
    elif final_action == FinalAction.DEFENSIVE_GRID.value:
        profile_hint = "agresif grid yerine savunmacı profil seçildi"
    elif final_action == FinalAction.BALANCED_GRID.value:
        rc = regime_code_from_route(route_key) if route_key else ""
        if rc == "R5":
            profile_hint = "kırılım öncesi sıkışma profiline uygun grid seçildi"
        elif selected_template_key and "DOWNBUY" in selected_template_key.upper():
            profile_hint = (
                "geniş aralık ve BTC riski nedeniyle alış tarafı genişletilmiş "
                "savunmacı downbuy grid seçildi"
            )
        else:
            profile_hint = "dengeli grid profili seçildi"
    elif final_action == FinalAction.ACTIVE_GRID.value:
        profile_hint = "aktif aralık grid profili seçildi"
    elif final_action == FinalAction.TREND_TRAILING.value:
        profile_hint = "trend trailing profili seçildi"

    risk_opp = render_risk_opportunity_sentence(
        getattr(sub, "drawdown_risk_score", None),
        getattr(sub, "trend_score", None),
    )
    return (
        f"Parametre Skoru {param_score}/100. Rejim {regime_txt}, risk durumu {risk_txt}. "
        f"{risk_opp.capitalize()}. "
        f"Volatilite {sub.volatility_score}, BTC piyasa riski {sub.btc_market_risk_score}. "
        f"{profile_hint.capitalize()}. "
        f"Base tahsisi %{base_pct}, quote %{quote_pct}, maksimum base exposure %{max_exp} ile sınırlandı. "
        f"Alışlar {params.buy_grid_count} kademeye bölündü; "
        f"grid aralığı alış %{params.buy_grid_spacing_pct:.2f} / satış %{params.sell_grid_spacing_pct:.2f}."
        f"{_rebalance_explain_suffix(rebalance_plan)}"
    )
