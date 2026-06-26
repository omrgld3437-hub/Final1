"""
Karar kapanışı (decision closure) — "teşhis → eylem" bağını kuran katman.

Profesör eleştirisinin özü: sistem doğru teşhisi yapıyor (OOS önceliği, maruziyet
kayması ayrıştırması, kuyruk/örneklem farkındalığı) ama sonra KENDİ ÇÜRÜTTÜĞÜ seti
yine "öneri" diye teslim ediyor. Burada o boşluğu kapatıyoruz:

  1) DÜRÜST KIYAS manşeti: bot OOS getirisini, "hedeflenen tahsisi pasif tutma"
     (intended_static_return) ile kıyasla — buy&hold değil. Yenmesi en kolay kıyasla
     övünmeyi bırak; asıl soru "hiç işlem yapmadan hedef portföyü tutmaktan iyi mi?".
  2) ÇEKİLME (abstention): pasif tutmayı yenmiyorsa / güven düşükse / aşırı-uydurma
     bayrakları varsa seti ÖNERME — kararı kullanıcıya devretmek için uyarı yığma.
  3) OLASILIK UZLAŞTIRMA: "MC kâr olasılığı %88" ile "güven 12/100" çelişkisini tek
     bir kalibre P(dağıtıma değer) sayısına indir; örneklem küçükse 0.5'e çek.
  4) AŞIRI-UYDURMA BAYRAKLARI: PF=52, MC n=26 gibi değerler özellik değil kırmızı
     bayraktır — öyle işaretle.
  5) SAHTE HASSASİYET: güven düşük/karar deploy değilse iki-ondalık "kesin" sayı basma
     (precision=coarse) — çıpalama (anchoring) yapma.

Bu modül SAF: yalnızca elde olan metriklerden okur, motoru çalıştırmaz.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Eşikler (env yerine sabit; gerekirse ObjectiveConfig benzeri taşınabilir)
_DEPLOY_CONF = 55          # bunun altında en fazla "izleme"
_ABSTAIN_CONF = 35         # bunun altında çekil
_PF_OVERFIT = 10.0         # in-sample profit factor bunu aşarsa aşırı-uydurma bayrağı
# Tek profesyonel mod (professional_auto) MC kâr olasılığının istatistiksel
# olarak anlamlı/canlıya yeterli sayılması için taban (önceden 300 — eski
# orta/yüksek tier'lar içindi; artık tek mod hedefi 2400, canlı taban 600).
_MC_MIN_PATHS = 600
_DRIFT_CAP = 0.12          # |maruziyet kayması| bunu aşarsa bayrak (fraction)
_EPS = 1e-9


def _num(d: Optional[Dict[str, Any]], key: str, default: float = 0.0) -> float:
    try:
        v = (d or {}).get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _pick_validation(result: Dict[str, Any]) -> Dict[str, Any]:
    """Dürüst kıyas için OOS'u tercih et; yoksa in-sample'a düş (ama bayrakla)."""
    oos = result.get("oos") or result.get("oos_result")
    if oos:
        return dict(oos)
    return dict(result.get("in_sample") or result.get("in_sample_result") or {})


def reconcile_deploy_probability(
    *,
    confidence: int,
    forecast: Optional[Dict[str, Any]],
    beats_intended_hold: bool,
) -> Dict[str, Any]:
    """'MC %88' ile 'güven 12/100' çelişkisini tek bir kalibre olasılığa indir.

    - MC kâr olasılığını örneklem yetersizse (n<taban) 0.5'e (bilgisizlik) doğru çek.
    - Sonra model-güveniyle harmanla: güven düşükse sonuç 0.5'e çekilir.
    - Pasif tutmayı yenmiyorsa tavanla (dağıtıma değer olamaz).
    """
    fc = forecast or {}
    mc_p = fc.get("prob_profit")
    mc_n = int(_num(fc, "n_paths", 0))
    conf = max(0.0, min(1.0, confidence / 100.0))

    adequacy = max(0.0, min(1.0, mc_n / float(_MC_MIN_PATHS)))
    if mc_p is None:
        mc_adj = 0.5
    else:
        mc_p = max(0.0, min(1.0, float(mc_p)))
        # küçük örneklem -> 0.5'e çek (anlamsız kesinliği sönümle)
        mc_adj = 0.5 + (mc_p - 0.5) * adequacy

    # düşük güven -> 0.5'e (bilgisizlik) çek
    deploy_p = conf * mc_adj + (1.0 - conf) * 0.5

    capped = False
    if not beats_intended_hold:
        # pasif tutmayı yenmeyen set dağıtıma "değer" olamaz
        if deploy_p > 0.35:
            deploy_p = 0.35
            capped = True

    return {
        "deploy_probability": round(deploy_p, 3),
        "mc_prob_raw": (round(float(mc_p), 3) if mc_p is not None else None),
        "mc_paths": mc_n,
        "mc_adequacy": round(adequacy, 3),
        "confidence_frac": round(conf, 3),
        "capped_by_benchmark": capped,
        # UI bunu kullanmalı: örneklem tabanın (_MC_MIN_PATHS) altındaysa
        # deploy_probability'i YÜZDE olarak GÖSTERME — "MC örneklemi yetersiz" yaz.
        "probability_display": "percent" if mc_n >= _MC_MIN_PATHS else "insufficient_sample",
    }


def collect_red_flags(
    *,
    val: Dict[str, Any],
    in_sample: Dict[str, Any],
    forecast: Optional[Dict[str, Any]],
    confidence: int,
    honest: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Aşırı-uydurma / sahte-hassasiyet / kayma bayrakları (özellik DEĞİL, uyarı)."""
    flags: List[Dict[str, str]] = []
    fc = forecast or {}

    pf_is = _num(in_sample, "profit_factor", 0.0)
    if pf_is >= _PF_OVERFIT:
        flags.append({
            "code": "overfit_profit_factor",
            "severity": "high",
            "text": (
                f"In-sample profit factor {pf_is:.1f} — gerçek bir stratejide neredeyse "
                f"imkânsız. Bu bir satış argümanı değil, AŞIRI-UYDURMA kırmızı bayrağıdır."
            ),
        })

    mc_n = int(_num(fc, "n_paths", 0))
    if fc.get("prob_profit") is not None and mc_n < _MC_MIN_PATHS:
        flags.append({
            "code": "mc_underpowered",
            "severity": "medium",
            "text": (
                f"Monte Carlo örneklemi n={mc_n} (<{_MC_MIN_PATHS}) — 'kâr olasılığı' "
                f"istatistiksel olarak zayıf. İki-ondalık kesinlik yanıltıcıdır (çıpalama)."
            ),
        })

    in_ret = _num(in_sample, "return_pct", 0.0)
    oos_ret = _num(val, "return_pct", 0.0)
    if in_ret > 5.0 and oos_ret < -2.0:
        flags.append({
            "code": "sign_flip",
            "severity": "high",
            "text": (
                f"In-sample +%{in_ret:.1f} iken OOS %{oos_ret:.1f} (işaret değişimi) — "
                f"set tek döneme uymuş olabilir; aramayı genişletmek bunu DÜZELTMEZ."
            ),
        })

    drift = _num(val, "exposure_drift", 0.0)
    if abs(drift) > _DRIFT_CAP:
        intended = _num(val, "intended_base_frac", 0.0) * 100.0
        realized = _num(val, "exposure_frac", 0.0) * 100.0
        flags.append({
            "code": "exposure_drift",
            "severity": "high",
            "text": (
                f"Maruziyet kaydı: niyet %{intended:.0f} → gerçekleşen %{realized:.0f} "
                f"(kayma {drift*100:+.0f} puan). 'Grid alpha' bu kaymayla kirlenir; "
                f"kazanç beceriden değil gizli long'tan gelmiş olabilir."
            ),
        })

    if not honest.get("beats_intended_hold", False):
        flags.append({
            "code": "worse_than_passive",
            "severity": "high",
            "text": (
                f"Bu set, hedeflediğin tahsisi (%{honest.get('intended_base_pct', 0):.0f} "
                f"base) PASİF tutmaktan daha kötü: bot %{honest.get('bot_return_pct', 0):.1f} "
                f"vs pasif tutma %{honest.get('intended_hold_return_pct', 0):.1f}."
            ),
        })

    if confidence < _ABSTAIN_CONF:
        flags.append({
            "code": "low_confidence",
            "severity": "medium",
            "text": (
                f"Güven {confidence}/100 — düşük öncül-güveni kesin sayı üretmeyi değil "
                f"ÇEKİLMEYİ ya da dağıtımı genişletmeyi gerektirir."
            ),
        })

    return flags


def honest_benchmark(val: Dict[str, Any]) -> Dict[str, Any]:
    """Dürüst kıyas: bot vs 'hedeflenen tahsisi pasif tutma' (intended hold).

    grid_alpha_vs_intended_pct = bot_return - intended_static_return.
    Pozitifse: işlem yapmak, hedef portföyü öylece tutmaktan İYİ.
    """
    bot = _num(val, "return_pct", 0.0)
    intended_hold = _num(val, "intended_static_return_pct", 0.0)
    bh = _num(val, "buy_hold_return_pct", 0.0)
    honest_alpha = _num(val, "grid_alpha_vs_intended_pct", bot - intended_hold)
    return {
        "bot_return_pct": round(bot, 2),
        "intended_hold_return_pct": round(intended_hold, 2),
        "buy_hold_return_pct": round(bh, 2),
        "honest_alpha_pct": round(honest_alpha, 2),  # ASIL kıyas
        "naive_alpha_vs_buyhold_pct": round(_num(val, "alpha_pct", bot - bh), 2),
        "beats_intended_hold": honest_alpha > 0.0,
        "exposure_drift_pct": round(_num(val, "exposure_drift", 0.0) * 100.0, 1),
        "intended_base_pct": round(_num(val, "intended_base_frac", 0.0) * 100.0, 0),
    }


def _no_deployable_decision(reason: str = "no_deployable_candidate") -> Dict[str, Any]:
    """robust_engine hiçbir aday için hard gate'leri geçemediğinde (result_type=
    no_deployable_candidate) dönecek dürüst, tek karar. honest_benchmark/flags
    sıfırlardan hesaplanmış YANILTICI sayılar üretmesin — doğrudan kısa-devre."""
    headline = (
        "UYGULANABİLİR PARAMETRE BULUNAMADI. Aday havuzundaki hiçbir set canlıya "
        "uygunluk kapılarını (yapısal/maruziyet/OOS) geçemedi. Bu bir öneri DEĞİLDİR — "
        "reddedilen en iyi aday teşhis amaçlı raporlanır."
    )
    return {
        "decision": "abstain",
        "deployable": False,
        "headline": headline,
        "honest_benchmark": None,
        "deploy_probability": None,
        "probability_detail": {"probability_display": "not_applicable"},
        "red_flags": [],
        "severe_flag_count": 0,
        "precision": "coarse",
        "reasons": [headline],
        "reason_code": reason,
        "confidence": 0,
    }


def evaluate_decision(
    result: Dict[str, Any],
    *,
    confidence: int,
    has_oos: Optional[bool] = None,
    final_holdout: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tek ve dürüst karar: deploy | watch_only | abstain + manşet + olasılık + bayraklar.

    result: engine sonucu (in_sample/oos/forecast içerebilir) ya da robust sonucu.
    final_holdout: optimizer'ın HİÇ görmediği bağımsız son pencere (validation_oos'tan
    AYRI) — yalnız mesajlaşma için kullanılır, kararı KURTARMAZ (final="abstain" aynen
    kalır) ama validation_oos kötü/final_holdout iyiyken "karışık kanıt" diyerek
    yanıltıcı "işlem yapmak zararı artırmış" mesajının önüne geçer.
    """
    if result.get("result_type") == "no_deployable_candidate":
        return _no_deployable_decision()

    val = _pick_validation(result)
    in_sample = dict(result.get("in_sample") or result.get("in_sample_result") or {})
    forecast = result.get("forecast")
    oos_present = bool(result.get("oos") or result.get("oos_result")) if has_oos is None else has_oos

    honest = honest_benchmark(val)
    beats = honest["beats_intended_hold"]
    fh_return = _num(final_holdout, "return_pct", float("nan")) if final_holdout else None
    fh_mixed = bool(final_holdout) and fh_return is not None and fh_return == fh_return and fh_return > 0.0

    prob = reconcile_deploy_probability(
        confidence=confidence, forecast=forecast, beats_intended_hold=beats
    )
    flags = collect_red_flags(
        val=val, in_sample=in_sample, forecast=forecast,
        confidence=confidence, honest=honest,
    )
    severe = [f for f in flags if f.get("severity") == "high"]
    sign_flip = any(f["code"] == "sign_flip" for f in flags)

    # ——— KARAR ———
    reasons: List[str] = []
    reason_code = "deploy_ok"
    if not oos_present:
        decision = "abstain"
        reason_code = "no_oos"
        reasons.append("OOS (görülmemiş veri) doğrulaması yok — yalnız in-sample ile öneri verilmez.")
    elif not beats:
        decision = "abstain"
        if fh_mixed:
            reason_code = "mixed_evidence"
            reasons.append(
                "Karışık kanıt: validation_oos'ta hedef tahsisi pasif tutmayı yenmiyor "
                f"(bot %{honest['bot_return_pct']} vs pasif %{honest['intended_hold_return_pct']}), "
                f"ama bağımsız final_holdout pozitif (%{fh_return:.2f})."
            )
        else:
            reason_code = "worse_than_passive"
            reasons.append(
                f"OOS'ta hedef tahsisi pasif tutmayı yenmiyor "
                f"(bot %{honest['bot_return_pct']} vs pasif %{honest['intended_hold_return_pct']})."
            )
    elif confidence < _ABSTAIN_CONF:
        decision = "abstain"
        reason_code = "low_confidence"
        reasons.append(f"Güven {confidence}/100 çok düşük — çekilmek doğru karar.")
    elif sign_flip and confidence < _DEPLOY_CONF:
        decision = "abstain"
        reason_code = "sign_flip_low_confidence"
        reasons.append("In-sample/OOS işaret değişimi + düşük güven — şans uydurması riski yüksek.")
    elif confidence < _DEPLOY_CONF or len(severe) >= 1:
        decision = "watch_only"
        reason_code = "watch_only_borderline"
        reasons.append("Pasif tutmayı geçiyor ama güven/sağlamlık dağıtım için yeterli değil — izleme/kâğıt modu.")
    else:
        decision = "deploy"
        reasons.append("OOS'ta hedef tahsisi pasif tutmayı geçiyor, güven yeterli, ağır bayrak yok.")

    # ——— MANŞET (dürüst, en üstte) ———
    if decision == "abstain":
        if not beats and fh_mixed:
            headline = (
                f"KARIŞIK KANIT — önerilmiyor. Uzun doğrulama penceresinde (validation_oos) bu set "
                f"hedeflediğin portföyü pasif tutmaktan kötü (bot %{honest['bot_return_pct']} vs pasif "
                f"%{honest['intended_hold_return_pct']}), ama bağımsız final_holdout'ta pozitif "
                f"(%{fh_return:.2f}). Tek başına bu yeterli değil; sağlamlık testleri (PBO/Deflated "
                f"Sharpe/stres/plato) ayrıca geçmeli."
            )
        elif not beats:
            headline = (
                f"ÖNERİLMİYOR — çekil. Bu set OOS'ta hedeflediğin portföyü pasif "
                f"tutmaktan DAHA KÖTÜ (bot %{honest['bot_return_pct']} vs pasif "
                f"%{honest['intended_hold_return_pct']}). İşlem yapmak zararı artırmış."
            )
        else:
            headline = (
                f"ÖNERİLMİYOR — çekil. Güven {confidence}/100 ve/veya örneklem bu seti "
                f"dağıtıma değer kılacak kanıtı taşımıyor."
            )
    elif decision == "watch_only":
        headline = (
            f"İZLEME/KÂĞIT MODU — canlı ana öneri değil. OOS'ta hedef tutmayı "
            f"+%{honest['honest_alpha_pct']} geçiyor ama güven {confidence}/100 ve "
            f"sağlamlık dağıtım için sınırda."
        )
    else:
        headline = (
            f"DAĞITIMA UYGUN. OOS'ta hedef tahsisi pasif tutmayı +%{honest['honest_alpha_pct']} "
            f"geçiyor; güven {confidence}/100; ağır bayrak yok."
        )

    # ——— SAHTE HASSASİYET POLİTİKASI ———
    precision = "full" if decision == "deploy" and confidence >= _DEPLOY_CONF else "coarse"

    return {
        "decision": decision,                 # deploy | watch_only | abstain
        "deployable": decision == "deploy",
        "headline": headline,
        "honest_benchmark": honest,
        "deploy_probability": prob["deploy_probability"],
        "probability_detail": prob,
        "red_flags": flags,
        "severe_flag_count": len(severe),
        "precision": precision,               # full | coarse (sahte kesinliği bastır)
        "reasons": reasons,
        "reason_code": reason_code,
        "confidence": confidence,
    }


# ── P0-6: TEK NİHAİ KARAR ──────────────────────────────────────────────────────
# Sistemde üç ayrı "dağıt/dağıtma" sinyali vardı: decision (honest-alpha/güven),
# robust_engine.deploy_gate (sert kapı) ve robust_policy.deploy_gate (ayrı yeniden
# hesap). decision bunları okumadığından decision=deploy iken deploy_gate=False gibi
# ÇELİŞKİ mümkündü → UI'da tutarsız mesaj. build_final_recommendation hepsini TEK
# karara indirir; sert kapı bloklayıcısı varken deploy ASLA mümkün olmaz.

# Sert bloklayıcılar: bunlardan biri varsa nihai karar en fazla watch_only olur.
# İsimlendirme failed_checks formatında (geçen değil GEÇEMEYEN kontrolün adı) —
# eskiden "oos_positive"/"pbo_ok" gibi GEÇEN-kontrol adları false iken listeye
# giriyordu, bu kafa karıştırıyordu (madde 10).
def _hard_deploy_blockers(
    *,
    deploy_gate: Optional[Dict[str, Any]],
    oos: Optional[Dict[str, Any]],
) -> List[str]:
    blocking: List[str] = []
    checks = (deploy_gate or {}).get("checks") or {}
    if oos is not None:
        oos_ret = _num(oos, "return_pct", 0.0)
        if oos_ret < 0:
            blocking.append("oos_not_positive")
    # deploy_gate sert kontrolleri (False → blok). forecast_skill_positive bilinçli
    # olarak HARİÇ: climatology fallback ile sistem çalışır → uyarı, blok değil.
    if checks.get("pbo_ok") is False:
        blocking.append("pbo_high")
    if checks.get("deflated_sharpe_ok") is False:
        blocking.append("deflated_sharpe_failed")
    if checks.get("stress_ok") is False:
        blocking.append("stress_failed")
    if checks.get("plateau_ok") is False:
        blocking.append("plateau_failed")
    return blocking


def build_decision_trace(
    *,
    decision: Dict[str, Any],
    final: str,
    blocking: List[str],
    mc_underpowered: bool,
    final_holdout_present: bool,
    oos: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """İZLENEBİLİR karar zinciri: hangi metrik hangi sınırı tetikledi (§8 debug_audit).

    Saf/yan-etkisiz: yalnız okunan değerleri ve uyguladıkları etkiyi listeler. UI bunu
    'neden bu karar?' kutusunda satır satır gösterebilir; metni değil sayıyı kanıtlar.
    """
    hb = decision.get("honest_benchmark") or {}
    prob = decision.get("probability_detail") or {}
    conf = int(decision.get("confidence") or 0)
    trace: List[Dict[str, Any]] = []

    trace.append({
        "step": "oos_present",
        "value": oos is not None,
        "effect": "ok" if oos is not None else "abstain (OOS doğrulaması yok)",
    })
    if oos is not None:
        trace.append({
            "step": "oos_return_pct",
            "value": _num(oos, "return_pct", 0.0),
            "effect": "hard_block:oos_not_positive" if _num(oos, "return_pct", 0.0) < 0 else "ok",
        })
    trace.append({
        "step": "honest_alpha_pct",
        "value": hb.get("honest_alpha_pct"),
        "effect": "deploy_blocked (pasif tutmayı yenmiyor)"
        if not hb.get("beats_intended_hold", False) else "ok",
    })
    trace.append({
        "step": "exposure_drift_pct",
        "value": hb.get("exposure_drift_pct"),
        "effect": "red_flag:exposure_drift"
        if abs(_num(hb, "exposure_drift_pct", 0.0)) > _DRIFT_CAP * 100.0 else "ok",
    })
    trace.append({
        "step": "confidence",
        "value": conf,
        "effect": (
            "abstain (güven < %d)" % _ABSTAIN_CONF if conf < _ABSTAIN_CONF
            else ("watch_only_max (güven < %d)" % _DEPLOY_CONF if conf < _DEPLOY_CONF else "ok")
        ),
    })
    trace.append({
        "step": "mc_paths",
        "value": prob.get("mc_paths"),
        "effect": "watch_only_max (MC örneklemi < %d)" % _MC_MIN_PATHS if mc_underpowered else "ok",
    })
    trace.append({
        "step": "final_holdout_present",
        "value": final_holdout_present,
        "effect": "watch_only_max (bağımsız holdout yok)" if not final_holdout_present else "ok",
    })
    for code in blocking:
        trace.append({"step": "hard_gate", "value": code, "effect": "deploy_blocked"})
    trace.append({"step": "final_decision", "value": final, "effect": "result"})
    return trace


def build_performance_trace(
    *,
    decision: Dict[str, Any],
    oos: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Performans metriklerinin FORMÜLLERİ + gerçek değerleri (§8 performance_trace).

    Tek 'performans' sayısı yok: üç ayrı kıyas (buy&hold / hedef pasif tahsis /
    gerçekleşen maruziyet) açık formülleriyle gösterilir.
    """
    hb = decision.get("honest_benchmark") or {}
    return {
        "formulas": {
            "return_pct": "net_pnl / start_equity * 100",
            "buy_hold_return_pct": "(last_close - first_open) / first_open * 100",
            "intended_static_return_pct": "intended_base_frac * buy_hold_return_pct  (quote=USDT, %0)",
            "honest_alpha_pct": "return_pct - intended_static_return_pct",
            "naive_alpha_vs_buyhold_pct": "return_pct - buy_hold_return_pct",
            "static_exposure_return_pct": "exposure_frac * buy_hold_return_pct",
            "grid_alpha_pct": "return_pct - static_exposure_return_pct",
            "exposure_drift": "exposure_frac - intended_base_frac",
            "cost_drag_pct": "(fees_paid + slippage_cost) / start_equity * 100",
        },
        "values": {
            "return_pct": hb.get("bot_return_pct"),
            "buy_hold_return_pct": hb.get("buy_hold_return_pct"),
            "intended_static_return_pct": hb.get("intended_hold_return_pct"),
            "honest_alpha_pct": hb.get("honest_alpha_pct"),
            "naive_alpha_vs_buyhold_pct": hb.get("naive_alpha_vs_buyhold_pct"),
            "exposure_drift_pct": hb.get("exposure_drift_pct"),
            "cost_drag_pct": _num(oos, "cost_drag_pct", 0.0) if oos else None,
        },
    }


def build_final_recommendation(
    *,
    decision: Dict[str, Any],
    deploy_gate: Optional[Dict[str, Any]] = None,
    robust_policy_gate: Optional[Dict[str, Any]] = None,
    forecast: Optional[Dict[str, Any]] = None,
    oos: Optional[Dict[str, Any]] = None,
    final_holdout_present: bool = False,
    confidence_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """decision + iki deploy_gate'i TEK final_recommendation'a birleştir.

    Kural:
      * decision=abstain → final=abstain.
      * sert bloklayıcı (OOS<0 / pbo / DSR / stres) → deploy ise watch_only'ye indir.
      * MC zayıf (n<taban) veya bağımsız final_holdout yok → deploy ise watch_only.
      * aksi → decision.decision aynen.
    deployable yalnız final=deploy iken True; böylece UI asla "önerilir" + "deploy=false"
    çelişkisini göstermez.
    """
    dec = decision.get("decision", "abstain")
    conf = int(decision.get("confidence") or 0)
    fc = forecast or {}
    warnings: List[str] = list(confidence_warnings or [])

    blocking = _hard_deploy_blockers(deploy_gate=deploy_gate, oos=oos)

    checks = (deploy_gate or {}).get("checks") or {}
    if checks.get("forecast_skill_positive") is False:
        warnings.append("forecast_skill_not_positive_climatology_fallback")

    mc_n = int(_num(fc, "n_paths", 0))
    mc_underpowered = fc.get("prob_profit") is not None and mc_n < _MC_MIN_PATHS
    if mc_underpowered:
        warnings.append("mc_underpowered")
    if not final_holdout_present:
        warnings.append("final_holdout_missing")

    if dec == "abstain":
        final = "abstain"
    elif blocking:
        final = "watch_only" if dec == "deploy" else dec
    elif mc_underpowered or not final_holdout_present:
        final = "watch_only" if dec == "deploy" else dec
    else:
        final = dec

    deployable = final == "deploy"
    precision = "full" if (deployable and conf >= _DEPLOY_CONF) else "coarse"
    # UI: deploy_probability'i YÜZDE olarak göstermek için bu alanı kontrol et.
    # abstain'de "kapalı/uygulanamaz", MC örneklemi tabanın altındaysa "yetersiz
    # örneklem" — "%35 dağıtıma değer" gibi yanıltıcı bir sayı asla basılmaz.
    if final == "abstain":
        probability_display = "not_applicable"
    elif mc_underpowered:
        probability_display = "insufficient_sample"
    else:
        probability_display = "percent"
    decision_trace = build_decision_trace(
        decision=decision, final=final, blocking=blocking,
        mc_underpowered=mc_underpowered, final_holdout_present=final_holdout_present,
        oos=oos,
    )
    return {
        "decision": final,                    # deploy | watch_only | abstain (NİHAİ)
        "deployable": deployable,
        "confidence": conf,
        "probability": decision.get("deploy_probability"),
        "probability_display": probability_display,  # percent | insufficient_sample | not_applicable
        "precision": precision,
        "headline": decision.get("headline", ""),
        "blocking_reasons": blocking,
        "warnings": warnings,
        "evidence": {
            "honest_benchmark": decision.get("honest_benchmark"),
            "deploy_gate": deploy_gate,
            "robust_policy_gate": robust_policy_gate,
            "red_flags": decision.get("red_flags"),
        },
        # §8 debug_audit: kararın İZLENEBİLİR zinciri + performans formülleri. Sayıyı
        # değil metni kanıtlar; UI 'neden bu karar?' kutusunda satır satır gösterebilir.
        "debug_audit": {
            "decision_trace": decision_trace,
            "performance_trace": build_performance_trace(decision=decision, oos=oos),
        },
    }
