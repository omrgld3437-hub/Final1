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
_MC_MIN_PATHS = 300        # MC kâr olasılığının istatistiksel olarak anlamlı sayılması için taban
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


def evaluate_decision(
    result: Dict[str, Any],
    *,
    confidence: int,
    has_oos: Optional[bool] = None,
) -> Dict[str, Any]:
    """Tek ve dürüst karar: deploy | watch_only | abstain + manşet + olasılık + bayraklar.

    result: engine sonucu (in_sample/oos/forecast içerebilir) ya da robust sonucu.
    """
    val = _pick_validation(result)
    in_sample = dict(result.get("in_sample") or result.get("in_sample_result") or {})
    forecast = result.get("forecast")
    oos_present = bool(result.get("oos") or result.get("oos_result")) if has_oos is None else has_oos

    honest = honest_benchmark(val)
    beats = honest["beats_intended_hold"]

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
    if not oos_present:
        decision = "abstain"
        reasons.append("OOS (görülmemiş veri) doğrulaması yok — yalnız in-sample ile öneri verilmez.")
    elif not beats:
        decision = "abstain"
        reasons.append(
            f"OOS'ta hedef tahsisi pasif tutmayı yenmiyor "
            f"(bot %{honest['bot_return_pct']} vs pasif %{honest['intended_hold_return_pct']})."
        )
    elif confidence < _ABSTAIN_CONF:
        decision = "abstain"
        reasons.append(f"Güven {confidence}/100 çok düşük — çekilmek doğru karar.")
    elif sign_flip and confidence < _DEPLOY_CONF:
        decision = "abstain"
        reasons.append("In-sample/OOS işaret değişimi + düşük güven — şans uydurması riski yüksek.")
    elif confidence < _DEPLOY_CONF or len(severe) >= 1:
        decision = "watch_only"
        reasons.append("Pasif tutmayı geçiyor ama güven/sağlamlık dağıtım için yeterli değil — izleme/kâğıt modu.")
    else:
        decision = "deploy"
        reasons.append("OOS'ta hedef tahsisi pasif tutmayı geçiyor, güven yeterli, ağır bayrak yok.")

    # ——— MANŞET (dürüst, en üstte) ———
    if decision == "abstain":
        if not beats:
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
        "confidence": confidence,
    }
