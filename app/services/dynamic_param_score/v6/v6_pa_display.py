"""V6 Param Assistant / Dashboard display labels (no V5 shelf language)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.v6.constants import DEFAULT_COST_FLOOR_PCT
from app.services.dynamic_param_score.regime_display import (
    V6_REGIME_LABELS,
    V6_MARKET_STATUS_PLAIN,
    build_regime_technical_label,
    market_status_plain,
    risk_tone_plain,
)

_DQ_LABELS = (
    (75, "Veri kalitesi zayıf · savunmacı filtre aktif"),
    (50, "Veri kapsaması sınırlı"),
    (25, "Veri kapsaması hafif sınırlı"),
    (0, "Veri kalitesi yeterli"),
)


def data_quality_risk_from_trace(adjuster_trace: Optional[List[Dict[str, Any]]]) -> int:
    for entry in adjuster_trace or []:
        if str(entry.get("name") or "") == "data_quality":
            return int(entry.get("score") or 0)
    return 0


def data_quality_label_from_risk(risk: int) -> str:
    for threshold, label in _DQ_LABELS:
        if risk >= threshold:
            return label
    return _DQ_LABELS[-1][1]


def _tags_from_final_id(final_profile_id: str) -> List[str]:
    if not final_profile_id:
        return []
    m = re.search(r"ADJ_([A-Z0-9_]+)_FINAL", str(final_profile_id))
    if not m:
        return []
    return [p for p in m.group(1).split("_") if p]


def _defensive_adjuster_signal(tags: List[str]) -> bool:
    for tag in tags:
        if tag.startswith("BTC_B") and tag not in ("BTC_B0", "BTC_B1"):
            return True
        if tag in ("F2", "F3"):
            return True
        if tag.startswith("V") and len(tag) == 2 and tag[1].isdigit() and int(tag[1]) >= 3:
            return True
        if tag.startswith("DQ") and tag not in ("DQ0", "DQ1"):
            return True
    return False


def risk_display_label(
    *,
    severity: str,
    adjuster_tags: Optional[List[str]] = None,
    final_profile_id: str = "",
) -> str:
    sev = str(severity or "STD").upper()
    tags = list(adjuster_tags or []) + _tags_from_final_id(final_profile_id)
    defensive = _defensive_adjuster_signal(tags)
    if sev == "DEF":
        return "Savunmacı"
    if sev == "ACT":
        return "Aktif"
    if defensive:
        return "Kontrollü savunmacı"
    return "Normal"


def safety_result_label_v6(
    *,
    deployable: bool,
    buy_grid_count: int,
    sell_grid_count: int,
    rebuy_enabled: bool,
    normal_buy_enabled: bool,
    deploy_block_reason: Optional[str] = None,
) -> str:
    if deploy_block_reason == "price_valid_false":
        return "Fiyat verisi geçersiz · profil üretilmedi"
    if deploy_block_reason == "restricted_by_liquidity":
        return "Düşük likidite · restricted teknik profil gösteriliyor"
    if deploy_block_reason == "conditional_probe_only":
        return "Conditional probe · otomatik deploy kapalı"
    if deploy_block_reason == "order_feasibility_restricted":
        return "Bütçe/minNotional nedeniyle otomatik deploy kapalı"
    if deploy_block_reason == "technical_block" and buy_grid_count == 0 and sell_grid_count == 0:
        return "İşlem yok · izleme modu"
    if sell_grid_count > 0 and buy_grid_count == 0 and not normal_buy_enabled:
        if rebuy_enabled:
            return "Alış kapalı · Satış ve kâr döngüsü aktif"
        return "Alış kapalı · Satış yönetimi aktif"
    if deployable:
        return "Uygulanabilir savunmacı profil"
    if sell_grid_count > 0 or buy_grid_count > 0:
        return "Savunmacı parametre seti gösteriliyor"
    return "Teknik profil üretilemedi"


def _format_grid_ladder(distances: Optional[List[Any]], *, is_buy: bool) -> str:
    if not distances:
        return ""
    parts: List[str] = []
    for raw in distances:
        try:
            dist = int(float(raw))
        except (TypeError, ValueError):
            continue
        parts.append(f"-{abs(dist)}%" if is_buy else f"+{dist}%")
    return " / ".join(parts)


def _trace_class_from_list(trace: Optional[List[Dict[str, Any]]], name: str) -> str:
    for entry in trace or []:
        if str(entry.get("name") or "") == name:
            return str(entry.get("class") or "")
    return ""


def _semantic_role_from_notes(opp: Optional[Dict[str, Any]]) -> str:
    opp = opp or {}
    role = str(opp.get("semantic_role") or "")
    if role:
        return role
    codes = {str(c) for c in (opp.get("reason_codes") or [])}
    if "R8_HARD_BLOCK" in codes:
        return "R8_HARD_BLOCK"
    if "CONDITIONAL_PROBE_ONLY" in codes:
        return "R8_CAPITULATION_CONDITIONAL_PROBE"
    if "R5_ACT_CLEAN_BREAKOUT" in codes:
        return "CLEAN_BREAKOUT"
    if "R5_STD_POST_BREAKOUT_COOLDOWN" in codes:
        return "POST_BREAKOUT_COOLDOWN"
    if "R5_DEF_PARABOLIC_OVEREXTENDED" in codes:
        return "PARABOLIC_OVEREXTENDED"
    if "R5_DEF_OVEREXTENDED" in codes:
        return "OVEREXTENDED_MOMENTUM"
    if "LOW_LIQUIDITY_RESTRICTED" in codes:
        return "LOW_LIQUIDITY_RESTRICTED"
    return ""


def _is_recovery_semantic(role: str) -> bool:
    return str(role or "").upper() in {"RECOVERY", "RECOVERY_BREAKOUT", "R6_RECOVERY_BREAKOUT"}


_R3_BUY_GRID_STATUS = (
    "Yakın alış gridleri açık; son kademe daha derin destek için ayrıldı"
)


def _r3_uptrend_compression_context(
    *,
    sub_profile_hint: str = "",
    scenario_name: str = "",
) -> bool:
    hint = str(sub_profile_hint or "")
    if "UPTREND_COMPRESSION" in hint or "UPTREND_OVERHEAT_COOLDOWN" in hint:
        return True
    return "yukarı eğilimli sıkışma" in str(scenario_name or "").lower()


def _r3_uptrend_overheat_cooldown_context(
    *,
    sub_profile_hint: str = "",
    scenario_name: str = "",
) -> bool:
    text = " ".join([str(sub_profile_hint or ""), str(scenario_name or "")]).lower()
    return "uptrend_overheat_cooldown" in text or "rsi yüksek cooldown" in text


def contextual_market_status_plain(
    regime_id: str,
    adjuster_trace: Optional[List[Dict[str, Any]]] = None,
    *,
    sub_profile_hint: str = "",
    scenario_name: str = "",
) -> str:
    """Volatility-aware plain status — avoids 'sert dalgalanıyor' when V1/V2."""
    rid = str(regime_id or "").upper()
    vol = _trace_class_from_list(adjuster_trace, "volatility")
    if rid == "R4":
        if vol in ("V1", "V2"):
            return "Orta volatilite aralık; gridler dengeli tutuldu"
        if vol == "V3":
            return "Dalgalı aralık; gridler orta-geniş tutuldu"
    if rid == "R2" and vol in ("V1",):
        return "Sakin yatay bölge; gridler 1 haftalık bot için yakın"
    if rid == "R3" and vol in ("V1", "V2"):
        if _r3_uptrend_overheat_cooldown_context(
            sub_profile_hint=sub_profile_hint,
            scenario_name=scenario_name,
        ):
            return "Ana eğilim güçlü ve likit; RSI yüksek, kısa vadede momentum soğuyor"
        if _r3_uptrend_compression_context(
            sub_profile_hint=sub_profile_hint,
            scenario_name=scenario_name,
        ):
            return (
                f"Yukarı eğilimli sıkışma / kontrollü soğuma; {_R3_BUY_GRID_STATUS}"
            )
        return f"Gürültülü ama kontrollü aralık; {_R3_BUY_GRID_STATUS}"
    return market_status_plain(rid)


def build_regime_headline(scen: Optional[Dict[str, Any]]) -> str:
    """Format canonical profile headline; never reclassify regime/profile meaning."""
    scen = scen or {}
    regime_id = str(scen.get("regime_id") or "").upper()
    canonical = str(
        scen.get("canonical_headline")
        or scen.get("headline")
        or scen.get("name")
        or ""
    ).strip()
    if not canonical:
        profile_key = str(scen.get("selected_profile_key") or scen.get("net_profile_key") or "")
        if profile_key:
            try:
                from app.services.dynamic_param_score.v6.net_profile_library import (
                    canonical_headline_for_key,
                )

                canonical = canonical_headline_for_key(profile_key)
            except Exception:
                canonical = ""
    if not canonical:
        canonical = V6_REGIME_LABELS.get(regime_id, regime_id)
    if regime_id and canonical:
        # Avoid "R5 · R5 · …" if canonical already prefixed.
        if canonical.upper().startswith(f"{regime_id} ·") or canonical.upper().startswith(f"{regime_id}·"):
            return canonical
        return f"{regime_id} · {canonical}"
    return canonical or regime_id or "—"


def build_regime_strategy_why(
    regime_id: str,
    display: Dict[str, Any],
    *,
    opportunity_notes: Optional[Dict[str, Any]] = None,
    adjuster_trace: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Plain Turkish: why this regime + grid shape was chosen."""
    rid = str(regime_id or "").upper()
    opp = opportunity_notes or {}
    trace = adjuster_trace or display.get("adjuster_trace") or []
    vol = _trace_class_from_list(trace, "volatility")
    grid = build_grid_plan_plain(display)
    base = int(display.get("base_allocation_pct") or 0)
    quote = int(display.get("quote_allocation_pct") or 100 - base)
    op_mode = build_operational_mode_plain(display, opportunity_notes)
    semantic_role = _semantic_role_from_notes(opp)
    scen = display.get("scenario_identity") or {}
    headline_context = " ".join(
        [str(scen.get("name") or ""), str(scen.get("sub_profile_hint") or "")]
    ).lower()

    if semantic_role in (
        "LOW_LIQUIDITY_RESTRICTED",
        "OVEREXTENDED_LOW_LIQUIDITY",
        "R3_RESTRICTED_LOW_LIQUIDITY_COMPRESSION",
        "R8_LOW_LIQUIDITY_RESTRICTED",
    ):
        return (
            "Likidite/spread riski normal grid için uygun değil; profil restricted tutuldu. "
            f"Plan: {grid}. Dağılım coin %{base} · USDT %{quote}. Mod: {op_mode}."
        )
    if semantic_role == "R8_HARD_BLOCK":
        return (
            "Spread, crash veya drawdown koşulu çok sert; yeni alış, satış sonrası geri alım ve kâr döngüsü kapalı. "
            f"Dağılım coin %{base} · USDT %{quote}. Mod: {op_mode}."
        )

    if rid == "R4":
        if vol in ("V1", "V2"):
            return (
                f"Rejim R4 seçildi ancak volatilite {vol or 'düşük'}; bu yüzden gridler aşırı genişletilmedi. "
                f"Plan: {grid}. Dağılım coin %{base} · USDT %{quote}. Mod: {op_mode}."
            )
        return (
            f"Dalgalanma yüksek; gridler genişletilir ama aktif kalır: {grid}. "
            "Amaç fitillerde al-sat döngüsünü çalıştırmak ve USDT rezervini erken tüketmemektir."
        )
    if rid == "R1":
        if semantic_role == "R1_STD_PULLBACK" or "geri çekilme" in headline_context or "pullback" in headline_context:
            return (
                "Ana trend yukarı ancak kısa vadede pullback sinyali var; coin tarafı orta-yüksek tutuldu, "
                f"USDT %{quote} geri çekilme alımları için korundu. Plan: {grid}."
            )
        if semantic_role == "R1_STD_TREND_COOLDOWN" or "soğuma" in headline_context or "cooldown" in headline_context:
            return (
                "Ana trend yukarı ancak momentum soğuyor; coin tarafı orta-yüksek tutuldu, "
                f"USDT %{quote} fiyat kovalamadan geri çekilme için ayrıldı. Plan: {grid}."
            )
        return (
            f"Yükseliş trendinde satış gridleri ve kâr döngüsü için coin tabanı %{base}'e yükseltildi "
            f"(USDT %{quote} dip alışları için). Amaç nakitte park etmek değil, al-sat devir hızı — plan: {grid}."
        )
    if rid == "R2":
        return (
            f"Yatay bölgede iki yönlü fırsat için gridler yakın tutuldu: {grid}. "
            "1 haftalık botta fiyatın gridlere ulaşması hedeflendi."
        )
    if rid == "R3":
        if _r3_uptrend_overheat_cooldown_context(
            sub_profile_hint=str(scen.get("sub_profile_hint") or ""),
            scenario_name=str(scen.get("name") or ""),
        ):
            return (
                "Ana eğilim güçlü ve likit, ancak RSI yüksek ve kısa momentum soğuyor; "
                f"gridler yakın/orta tutuldu, USDT %{quote} rezervi korunurken küçük/orta salınımlarda "
                f"kâr döngüsü hedeflenir. Plan: {grid}."
            )
        return (
            f"Hareket dar; gridler yakın tutulur: {grid}. "
            "Amaç küçük ama tekrarlanabilir kâr döngüsü üretmektir."
        )
    if rid == "R5":
        if semantic_role == "CLEAN_BREAKOUT":
            return (
                f"Temiz breakout onaylandığı için trend devamı planlandı: {grid}. "
                f"Dağılım coin %{base} · USDT %{quote}; satış gridleri yukarı tepkiyi kademeli toplar."
            )
        if semantic_role == "POST_BREAKOUT_COOLDOWN":
            return (
                "Trend güçlü fakat kısa vadeli momentum yavaşlıyor; sahte kırılım riskine karşı "
                f"USDT rezervi korundu. Plan: {grid}. Dağılım coin %{base} · USDT %{quote}."
            )
        if semantic_role in ("OVEREXTENDED_MOMENTUM", "PARABOLIC_OVEREXTENDED"):
            return (
                "Momentum güçlü fakat fiyat üst bölgede; yeni alımlar derine veya kapalı bırakıldı, "
                "yukarı tepkilerde kademeli kâr alınır. Amaç tepe riskini sınırlarken trend devamından pay almaktır. "
                f"Plan: {grid}. Dağılım coin %{base} · USDT %{quote}."
            )
        return (
            f"Breakout rejiminde kontrollü trend takibi için {grid}. "
            f"Dağılım coin %{base} · USDT %{quote}."
        )
    if rid == "R6":
        mode = str(opp.get("regime_opportunity") or opp.get("r6_mode") or "")
        if "CONTROLLED_ACTIVE" in mode:
            return (
                "Düşüş sonrası toparlanmada kontrollü aktif mod: alış açık, "
                f"satış ve kâr döngüsü birlikte — {grid}."
            )
        return (
            "Zayıf recovery koşullarında normal alış temkinli tutuldu; satış ağırlıklı yönetim ve "
            f"satış sonrası geri alım döngüsü — {grid}."
        )
    if rid == "R7":
        return (
            f"Düşüş trendinde yakın alış yerine derin kontrollü giriş: {grid}. "
            "Kovalamadan geri çekilmelerde fırsat aranır."
        )
    if rid == "R8":
        mode = str(opp.get("pb11_operational_mode") or "")
        if semantic_role == "R8_HARD_BLOCK" or mode == "no_trade_monitor" or "hard block" in headline_context:
            return "Hard block: yeni işlem yok; profil izleme modunda tutulur."
        if semantic_role == "R8_CAPITULATION_CONDITIONAL_PROBE":
            return (
                "Derin crash koşulu var; ana profil micro-base satış/geri alımda kalır, "
                "derin alış yalnızca conditional probe metadata olarak sunulur."
            )
        if "mod_b" in mode:
            return f"Crash profilinde derin kontrollü alış modu: {grid}."
        return (
            f"Sert düşüşte micro base (%{base}) ile satış yönetimi ve geri alım döngüsü: {grid}."
        )
    status = V6_MARKET_STATUS_PLAIN.get(rid, market_status_plain(rid))
    return f"{status} Bu rejimde önerilen grid planı: {grid}."


def build_profit_loop_plain(display: Dict[str, Any]) -> str:
    parts: List[str] = []
    if display.get("rebuy_enabled") or display.get("post_sell_buyback_enabled"):
        rt = display.get("rebuy_trigger_pct") or display.get("post_sell_buyback_trigger_pct")
        tr = display.get("rebuy_trailing_pct") or display.get("post_sell_buyback_trailing_pct")
        if rt is not None:
            seg = f"Satış sonrası kar alım: -%{rt}"
            if tr is not None:
                seg += f" · trailing %{tr}"
            parts.append(seg)
    if display.get("profit_sell_enabled") or display.get("post_buyback_profit_sell_enabled"):
        pt = display.get("profit_sell_trigger_pct") or display.get("post_buyback_profit_sell_trigger_pct")
        ptr = display.get("profit_sell_trailing_pct") or display.get("post_buyback_profit_sell_trailing_pct")
        if pt is not None:
            seg = f"Kar alım sonrası kar satış: +%{pt}"
            if ptr is not None:
                seg += f" · trailing %{ptr}"
            parts.append(seg)
    return " · ".join(parts) if parts else ""


def build_operational_mode_plain(
    display: Dict[str, Any],
    opportunity_notes: Optional[Dict[str, Any]] = None,
) -> str:
    opp = opportunity_notes or {}
    validity = opp.get("operational_validity") or {}
    mode = str(validity.get("mode") or "")
    semantic_role = _semantic_role_from_notes(opportunity_notes)
    if semantic_role in (
        "LOW_LIQUIDITY_RESTRICTED",
        "OVEREXTENDED_LOW_LIQUIDITY",
        "R3_RESTRICTED_LOW_LIQUIDITY_COMPRESSION",
        "R8_LOW_LIQUIDITY_RESTRICTED",
    ):
        return "Restricted · otomatik deploy kapalı"
    if semantic_role == "R8_CAPITULATION_CONDITIONAL_PROBE":
        return "Conditional probe · otomatik deploy kapalı"
    if semantic_role == "R8_HARD_BLOCK":
        return "İşlem yok · izleme modu"
    mapping = {
        "bilateral_grid": "İki yönlü grid aktif",
        "sell_management": "Satış yönetimi + geri alım",
        "deep_buy_only": "Derin alış odaklı",
        "micro_base_sell_rebuy": "Micro base · satış / geri alım",
        "deep_crash_entry": "Crash · derin kontrollü alış",
    }
    if mode in mapping:
        return mapping[mode]
    buy_n = int(display.get("buy_grid_count") or 0)
    sell_n = int(display.get("sell_grid_count") or 0)
    buy_on = bool(display.get("normal_buy_enabled"))
    scen = display.get("scenario_identity") or {}
    rid = str(scen.get("regime_id") or "").upper()
    scenario_name = str(scen.get("name") or "").lower()
    if rid == "R8" and "hard block" in scenario_name:
        return "İşlem yok · izleme modu"
    if rid == "R8" and sell_n > 0 and (not buy_on or buy_n == 0):
        return "Yeni alış kapalı · satış ve kontrollü kâr döngüsü aktif"
    if buy_n and sell_n:
        return "İki yönlü grid aktif"
    if sell_n and not buy_n:
        return "Satış yönetimi aktif"
    if buy_n:
        return "Alış grid aktif"
    return "Operasyonel profil"


def build_grid_strategy_plain(regime_id: str, display: Dict[str, Any]) -> str:
    """Short grid summary for tiles and chips."""
    buy_n = int(display.get("buy_grid_count") or 0)
    sell_n = int(display.get("sell_grid_count") or 0)
    plan = build_grid_plan_plain(display)
    rid = str(regime_id or "").upper()
    if rid in ("R2", "R3") and buy_n >= 1:
        hint = " · 1 haftalık bot için yakın grid"
    elif rid == "R4":
        hint = " · volatil aralık için geniş grid"
    elif rid == "R8":
        hint = " · crash savunması"
    else:
        hint = ""
    return f"{buy_n} alış · {sell_n} satış — {plan}{hint}"


def build_grid_plan_plain(display: Dict[str, Any]) -> str:
    buy_on = bool(display.get("normal_buy_enabled"))
    buy_txt = _format_grid_ladder(display.get("buy_grid_distances_pct"), is_buy=True) if buy_on else ""
    sell_txt = _format_grid_ladder(display.get("sell_grid_distances_pct"), is_buy=False)
    if not buy_txt and not sell_txt:
        return "Grid kapalı"
    if not buy_txt:
        return f"Alış kapalı · Satış {sell_txt}"
    if not sell_txt:
        return f"Alış {buy_txt} · Satış kapalı"
    return f"Alış {buy_txt} · Satış {sell_txt}"


def build_grid_plan_chips(display: Dict[str, Any]) -> Dict[str, Any]:
    buy_on = bool(display.get("normal_buy_enabled"))
    buy_dists = list(display.get("buy_grid_distances_pct") or []) if buy_on else []
    sell_dists = list(display.get("sell_grid_distances_pct") or [])
    return {
        "buy": [f"-{abs(int(float(d)))}%" for d in buy_dists],
        "sell": [f"+{int(float(d))}%" for d in sell_dists],
        "buy_closed": not buy_on or not buy_dists,
        "sell_closed": not sell_dists,
    }


def fee_display_v6(*, cost_floor_pct: float = DEFAULT_COST_FLOOR_PCT) -> Dict[str, Any]:
    floor = float(cost_floor_pct or DEFAULT_COST_FLOOR_PCT)
    return {
        "status": "v6_cost_floor",
        "fee_mode": "disabled",
        "fee_data_available": None,
        "fee_bad": False,
        "cost_floor_source": "v6_fixed_floor",
        "total_cost_floor_pct": floor,
        "mode_label": "Canlı fee kullanılmaz",
        "floor_label": f"Sabit cost floor %{floor:.1f}",
        "display_note": None,
    }


def build_v6_stream_lines(display: Dict[str, Any], *, symbol: str = "", param_score: Optional[int] = None) -> List[str]:
    """Short PA intro lines — plain Turkish, no technical profile IDs."""
    sym = str(symbol or "").upper()
    headline = str(display.get("regime_headline") or "V6 profil")
    status = str(display.get("market_status_plain") or "")
    why = str(display.get("regime_strategy_why") or "")
    grid = str(display.get("grid_strategy_plain") or display.get("grid_plan_plain") or "")
    op = str(display.get("operational_mode_plain") or "")
    profit = str(display.get("profit_loop_plain") or "")
    base = display.get("base_allocation_pct")
    quote = display.get("quote_allocation_pct")
    lines: List[str] = []
    if sym:
        lines.append(f"{sym} için {headline} seçildi.")
    else:
        lines.append(f"{headline} seçildi.")
    if status:
        lines.append(status + ".")
    if why and why != status:
        lines.append(why)
    elif grid:
        lines.append(f"Grid planı: {grid}.")
    if op:
        lines.append(f"Çalışma modu: {op}.")
    if base is not None and quote is not None:
        lines.append(f"Dağılım: coin %{int(base)} · USDT %{int(quote)}.")
    if profit:
        lines.append(f"Kâr döngüsü: {profit}.")
    if param_score is not None:
        lines.append(f"Parametre skoru {int(param_score)}/100 · komisyon tabanı %1,2 korunarak hesaplandı.")
    lines.append("Not: Bu karar Dynamic Param Score Engine tarafından üretildi; Dinamik Mod her tur başında aynı motoru kullanır.")
    return lines


def format_regime_stickiness_plain(sticky: Optional[Dict[str, Any]]) -> str:
    """User-facing explanation when soft stickiness holds a prior regime."""
    meta = sticky or {}
    if not meta.get("held"):
        return ""
    locked = str(meta.get("locked_regime_id") or "")
    candidate = str(meta.get("candidate_regime_id") or "")
    remaining = float(meta.get("confirm_remaining_sec") or 0.0)
    if remaining <= 0:
        mins = 0
    else:
        mins = max(1, int(round(remaining / 60.0)))
    if locked and candidate and locked != candidate:
        return (
            f"Rejim geçici olarak {locked} tutuluyor; aday {candidate} "
            f"için yaklaşık {mins} dk daha teyit bekleniyor."
        )
    return f"Yumuşak rejim teyidi sürüyor (~{mins} dk)."


def enrich_v6_display(
    display: Dict[str, Any],
    *,
    adjuster_trace: Optional[List[Dict[str, Any]]] = None,
    deployable: bool = True,
    deploy_block_reason: Optional[str] = None,
    opportunity_notes: Optional[Dict[str, Any]] = None,
    regime_stickiness: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add PA/DM-facing label fields to v6_display telemetry."""
    out = dict(display or {})
    dq_risk = data_quality_risk_from_trace(adjuster_trace or out.get("adjuster_trace"))
    final_id = str(out.get("final_profile_id") or "")
    severity = str(out.get("severity") or "STD")
    tags: List[str] = []
    for entry in adjuster_trace or out.get("adjuster_trace") or []:
        cls = entry.get("class")
        if cls:
            tags.append(str(cls))
    out["data_quality_risk"] = dq_risk
    out["data_quality_label"] = data_quality_label_from_risk(dq_risk)
    out["risk_display_label"] = risk_display_label(
        severity=severity,
        adjuster_tags=tags,
        final_profile_id=final_id,
    )
    scen = out.get("scenario_identity") or {}
    regime_id = str(scen.get("regime_id") or "")
    trace = list(adjuster_trace or out.get("adjuster_trace") or [])
    sub_hint = str(scen.get("sub_profile_hint") or out.get("sub_profile_hint") or "")
    scenario_name = str(scen.get("name") or "")
    out["market_status_plain"] = contextual_market_status_plain(
        regime_id,
        trace,
        sub_profile_hint=sub_hint,
        scenario_name=scenario_name,
    )
    semantic_role = _semantic_role_from_notes(opportunity_notes)
    headline_context = " ".join([str(scenario_name or ""), str(sub_hint or "")]).lower()
    r1_pullback_context = (
        regime_id == "R1"
        and ("geri çekilme" in headline_context or "pullback" in headline_context)
    )
    r1_cooldown_context = (
        regime_id == "R1"
        and ("soğuma" in headline_context or "cooldown" in headline_context)
    )
    if semantic_role in (
        "LOW_LIQUIDITY_RESTRICTED",
        "OVEREXTENDED_LOW_LIQUIDITY",
        "R3_RESTRICTED_LOW_LIQUIDITY_COMPRESSION",
        "R8_LOW_LIQUIDITY_RESTRICTED",
    ):
        out["market_status_plain"] = "Likidite/spread riski yüksek; restricted teknik profil"
    elif regime_id == "R5" and semantic_role == "POST_BREAKOUT_COOLDOWN":
        out["market_status_plain"] = "Breakout sonrası kontrollü soğuma; USDT rezervi korunur"
    elif regime_id == "R5" and semantic_role == "CLEAN_BREAKOUT":
        out["market_status_plain"] = "Temiz breakout; trend devamı kontrollü takip edilir"
    elif regime_id == "R5" and semantic_role in ("OVEREXTENDED_MOMENTUM", "PARABOLIC_OVEREXTENDED"):
        out["market_status_plain"] = "Üst bölgede momentum; yeni alımlar kısılır, satış/kâr yönetimi öne çıkar"
    elif regime_id == "R1" and (semantic_role == "R1_STD_PULLBACK" or r1_pullback_context):
        out["market_status_plain"] = "Ana trend yukarı; kısa vadede pullback/cooldown sinyali var"
    elif regime_id == "R1" and (semantic_role == "R1_STD_TREND_COOLDOWN" or r1_cooldown_context):
        out["market_status_plain"] = "Ana trend yukarı; momentum soğuyor, USDT rezervi korunur"
    elif regime_id == "R3" and _r3_uptrend_overheat_cooldown_context(
        sub_profile_hint=sub_hint,
        scenario_name=scenario_name,
    ):
        out["market_status_plain"] = "Ana eğilim güçlü ve likit; RSI yüksek, kısa vadede momentum soğuyor"
    elif regime_id == "R8" and semantic_role == "R8_CAPITULATION_CONDITIONAL_PROBE":
        out["market_status_plain"] = "Derin crash; conditional probe metadata var, deploy kapalı"
    elif regime_id == "R8" and (semantic_role == "R8_HARD_BLOCK" or "hard block" in scenario_name.lower()):
        out["market_status_plain"] = "Hard block; yeni işlem yok, izleme modu"
    # Primary headline is locked to PROFILE_COPY via selected_profile_key.
    # Display may add secondary status/why text, but must not rewrite the headline.
    out["regime_headline"] = build_regime_headline(scen)
    out["canonical_headline"] = str(
        scen.get("canonical_headline") or scen.get("headline") or scen.get("name") or ""
    )
    out["selected_profile_key"] = str(
        scen.get("selected_profile_key")
        or scen.get("net_profile_key")
        or out.get("profile_id")
        or out.get("catalog_profile_id")
        or ""
    )
    out["display_regime_technical"] = build_regime_technical_label(scen)
    out["risk_tone_plain"] = risk_tone_plain(out["risk_display_label"])
    out["grid_plan_plain"] = build_grid_plan_plain(out)
    out["grid_plan_chips"] = build_grid_plan_chips(out)
    out["grid_strategy_plain"] = build_grid_strategy_plain(regime_id, out)
    out["regime_strategy_why"] = build_regime_strategy_why(
        regime_id, out, opportunity_notes=opportunity_notes, adjuster_trace=trace
    )
    out["profit_loop_plain"] = build_profit_loop_plain(out)
    out["operational_mode_plain"] = build_operational_mode_plain(out, opportunity_notes)
    buy_n = int(out.get("buy_grid_count") or 0)
    sell_n = int(out.get("sell_grid_count") or 0)
    out["safety_result_label"] = safety_result_label_v6(
        deployable=deployable,
        buy_grid_count=buy_n,
        sell_grid_count=sell_n,
        rebuy_enabled=bool(out.get("rebuy_enabled")),
        normal_buy_enabled=bool(out.get("normal_buy_enabled")),
        deploy_block_reason=deploy_block_reason,
    )
    out["profile_tile_label"] = "V6 Profil Kimliği"
    out["fee_display"] = fee_display_v6()
    sticky = regime_stickiness or out.get("regime_stickiness") or {}
    out["regime_stickiness"] = sticky
    sticky_plain = format_regime_stickiness_plain(sticky)
    out["regime_stickiness_plain"] = sticky_plain
    if sticky_plain:
        why = str(out.get("regime_strategy_why") or "")
        if sticky_plain not in why:
            out["regime_strategy_why"] = (why + " " + sticky_plain).strip() if why else sticky_plain
    btc_entry = next((e for e in trace if str(e.get("name") or "") == "btc_context"), None)
    if isinstance(btc_entry, dict):
        out["btc_context"] = {
            "class": btc_entry.get("class"),
            "score": btc_entry.get("btc_market_risk_score", btc_entry.get("score")),
            "delta_multiplier": btc_entry.get("delta_multiplier"),
        }
    return out
