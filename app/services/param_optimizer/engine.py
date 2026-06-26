"""
Orchestrator: bütçe + parite -> en iyi bot parametreleri.

run_optimization():
    daily (feature) + backtest serisi (hibrit çözünürlük) al
    -> feature/rejim hesapla
    -> arama uzayı türet
    -> walk-forward bölümle (train / recent_in / oos)
    -> optimizer çalıştır (coarse-to-fine, çok çekirdek, zaman bütçeli)
    -> en iyi params + teşhis + insan-okur gerekçe
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.services.param_optimizer.indicators import compute_features, HistoryFeatures
from app.services.param_optimizer.space import build_space
from app.services.param_optimizer.objective import ObjectiveConfig, score_backtest
from app.services.param_optimizer.backtest import run_backtest
from app.services.param_optimizer.tiers import AnalysisTier, get_tier
from app.services.param_optimizer.robust_policy import build_robust_policy_report
from app.services.param_optimizer.robust_engine import optimize_robust
from app.services.param_optimizer.cancel import ParamOptimizerCancelled

logger = logging.getLogger(__name__)

_DAY_MS = 86_400_000

# Sonuç şema sürümü: UI eski/uyumsuz cache'i tanıyıp atabilsin diye sonuca gömülür.
# Şema kırıcı bir değişiklikte (alan adı/anlam) artır → frontend eşleşmeyen sürümü
# "bayat" sayar ve göstermez.
RESULT_SCHEMA_VERSION = "2.0"


def config_hash(symbol: str, budget: float, tier_key: str) -> str:
    """İSTEK kimliği: aynı (sembol, bütçe, seviye) → aynı hash.

    Bayat sonuç engeli: bir job sonucu yalnız bu hash'i üreten istekle eşleşirse
    gösterilmelidir. Sembol/bütçe/seviye değişince hash değişir → eski sonuç reddedilir.
    """
    try:
        b = float(budget or 0.0)
    except (TypeError, ValueError):
        b = 0.0
    payload = f"{(symbol or '').upper().strip()}|{b:.8f}|{(tier_key or '').strip().lower()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def market_data_hash(candles: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Backtest'e giren mum serisinin ucuz parmak izi (uzunluk + uç zaman/kapanış).

    Aynı sembol/seviye için veri değişirse (yeni mumlar, farklı pencere) hash değişir.
    UI/teşhis 'sonuç hangi veriyle üretildi?' sorusuna bununla bağ kurar.
    """
    seq = list(candles or [])
    if not seq:
        return ""
    first, last = seq[0], seq[-1]
    sig = (
        f"{len(seq)}|{first.get('t')}|{last.get('t')}|"
        f"{last.get('c')}|{first.get('o')}"
    )
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def json_safe(obj: Any) -> Any:
    """JSON uyumsuz float'ları (NaN, +Inf, -Inf) None'a çevirir.

    FastAPI/starlette JSONResponse allow_nan=False ile serileştirir; sonuçtaki
    tek bir NaN/Inf tüm yanıtı 500'e düşürür ("Out of range float values are not
    JSON compliant"). Backtest/forecast metriklerinde (0'a bölme, tek-yol std, vb.)
    nadiren non-finite üretilebildiğinden, sonucu serileştirme sınırında temizliyoruz.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def _split_by_days(candles: List[Dict[str, Any]], tail_days: float):
    """candles'ı (öncesi, son tail_days) olarak böl (zaman damgasına göre)."""
    if not candles:
        return [], []
    t_end = float(candles[-1].get("t") or 0.0)
    cut = t_end - tail_days * _DAY_MS
    head = [c for c in candles if float(c.get("t") or 0.0) < cut]
    tail = [c for c in candles if float(c.get("t") or 0.0) >= cut]
    return head, tail


def _segment_folds(
    candles: Sequence[Dict[str, Any]], n_folds: int, min_bars: int = 60
) -> List[List[Dict[str, Any]]]:
    """backtest serisini n_folds ardışık, ~eşit OOS dilimine böl (çapraz-dönem).

    Seçilen SABİT parametre setini birden çok tarihsel dönemde doğrular: tek
    6-aylık OOS yerine onlarca dönem -> tutarlılık + toplam tur sayısı artar.
    Dilim min_bars'tan kısa kalacaksa fold sayısı düşürülür; veri çok azsa boş döner.
    """
    n = len(candles)
    if n_folds < 2 or n < min_bars * 2:
        return []
    if n // n_folds < min_bars:
        n_folds = max(2, n // min_bars)
    seg = n // n_folds
    if seg < min_bars:
        return []
    folds: List[List[Dict[str, Any]]] = []
    for i in range(n_folds):
        a = i * seg
        b = (i + 1) * seg if i < n_folds - 1 else n
        if b - a >= min_bars:
            folds.append(list(candles[a:b]))
    return folds


def _walk_forward_eval(
    params: Dict[str, Any],
    candles: Sequence[Dict[str, Any]],
    n_folds: int,
    budget: float,
    symbol: str,
    *,
    fee: float,
    slippage: float,
    obj_cfg: ObjectiveConfig,
    taker_extra_bps: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Seçilen SABİT params'ı n_folds tarihsel dilimde backtest et; çapraz-dönem özet.

    Tek OOS (n=3 tur) yerine çok dönem: kaç dilim kârlı, toplam OOS turu, en kötü
    dilim, getiri tutarlılığı. 'Set yalnızca tek dönemde mi çalıştı?' sorusunu yanıtlar.
    """
    folds = _segment_folds(candles, n_folds)
    if not folds:
        return None
    per_fold: List[Dict[str, Any]] = []
    scores: List[float] = []
    rets: List[float] = []
    total_cycles = 0
    for idx, seg in enumerate(folds):
        r = run_backtest(
            seg, params, budget, symbol,
            fee_rate=fee, slippage_bps=slippage, taker_extra_bps=taker_extra_bps,
        )
        if not r.ok:
            continue
        scores.append(score_backtest(r, obj_cfg).score)
        rets.append(r.return_pct)
        total_cycles += int(r.cycles_closed)
        per_fold.append(
            {
                "fold": idx + 1,
                "return_pct": round(r.return_pct, 4),
                "cycles_closed": int(r.cycles_closed),
                "max_drawdown_pct": round(r.max_drawdown_pct, 4),
                "bars": len(seg),
            }
        )
    if not rets:
        return None
    n = len(rets)
    mean_ret = sum(rets) / n
    std_ret = (sum((x - mean_ret) ** 2 for x in rets) / n) ** 0.5
    sr = sorted(rets)
    median_ret = sr[n // 2] if n % 2 else (sr[n // 2 - 1] + sr[n // 2]) / 2.0
    n_prof = sum(1 for x in rets if x > 0)
    mean_sc = sum(scores) / len(scores)
    std_sc = (sum((x - mean_sc) ** 2 for x in scores) / len(scores)) ** 0.5
    return {
        "n_folds": n,
        "mean_return_pct": round(mean_ret, 4),
        "median_return_pct": round(median_ret, 4),
        "std_return_pct": round(std_ret, 4),
        "frac_profitable": round(n_prof / n, 4),
        "folds_profitable": n_prof,
        "worst_fold_return_pct": round(min(rets), 4),
        "best_fold_return_pct": round(max(rets), 4),
        "total_cycles": total_cycles,
        "consistency_score": round(mean_sc - 0.5 * std_sc, 4),
        "per_fold": per_fold,
    }


def run_optimization(
    symbol: str,
    budget: float,
    *,
    daily: Optional[Sequence[Dict[str, Any]]] = None,
    backtest_candles: Optional[Sequence[Dict[str, Any]]] = None,
    hourly: Optional[Sequence[Dict[str, Any]]] = None,
    time_budget_sec: float = 120.0,
    n_workers: int = 0,
    fee: float = 0.001,
    slippage_bps: float = 2.0,
    min_notional: float = 10.0,
    oos_days: float = 182.0,
    recent_in_days: float = 365.0,
    final_holdout_days: float = 60.0,
    tier: Optional[AnalysisTier] = None,
    tier_key: Optional[str] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    symbol = (symbol or "BTCUSDT").upper().strip()
    budget = float(budget)
    if tier is None:
        tier = get_tier(tier_key)

    def emit(stage: str, **kw):
        if progress_cb:
            try:
                progress_cb(
                    {"stage": stage, "elapsed": round(time.time() - t0, 1), **kw}
                )
            except ParamOptimizerCancelled:
                raise
            except Exception:
                pass

    # 1) Veri
    if (daily is None or backtest_candles is None) and fetcher is not None:
        emit("fetch", message="geçmiş veri çekiliyor")
        data = fetcher(symbol)
        daily = daily or data.get("daily")
        backtest_candles = backtest_candles or data.get("backtest")
        hourly = hourly or data.get("hourly")
    daily = list(daily or [])
    backtest_candles = list(backtest_candles or daily)
    if len(backtest_candles) < 60 or len(daily) < 30:
        return {
            "ok": False,
            "error": "insufficient_history",
            "symbol": symbol,
            "daily_bars": len(daily),
            "backtest_bars": len(backtest_candles),
        }

    # 2) Feature / rejim
    emit("features", message="indikatör ve rejim hesaplanıyor")
    features: HistoryFeatures = compute_features(daily, hourly)

    # 3) Arama uzayı
    space = build_space(features, budget, min_notional=min_notional, symbol=symbol)

    # 4) Üçlü walk-forward bölümleme (P0-2: veri sızıntısını kapat).
    #    final_holdout = en TAZE final_holdout_days gün; optimizer'a HİÇ verilmez,
    #    yani seçim onu görmez → tek GERÇEK bağımsız doğrulama penceresidir.
    #    Geri kalan (pre_holdout) train + validation(oos)'a bölünür; bunlar seçimde
    #    KULLANILIR (dolayısıyla "held-out" değildir, güveni tek başına yükseltemez).
    pre_holdout, final_holdout = _split_by_days(backtest_candles, final_holdout_days)
    if len(final_holdout) < 30 or len(pre_holdout) < 60:
        pre_holdout, final_holdout = backtest_candles, None  # holdout ayrılamıyor
    train, oos = _split_by_days(pre_holdout, oos_days)
    if len(train) < 50:  # OOS ayıracak kadar veri yoksa hepsini train yap
        train, oos = pre_holdout, None
    recent_in = None
    if train:
        _head, recent_in = _split_by_days(train, recent_in_days)
        if len(recent_in) < 30:
            recent_in = None
    emit(
        "split",
        message="walk-forward bölümlendi (train/validation/final-holdout)",
        train_bars=len(train),
        oos_bars=len(oos or []),
        recent_in_bars=len(recent_in or []),
        final_holdout_bars=len(final_holdout or []),
        regime=features.regime_label,
    )

    # 5) Robust v2 optimizasyon — serbest parametre taraması değil:
    #    forecast -> küçük yapısal varyantlar -> nested/purged WF -> MC/PBO/plato.
    obj_cfg = ObjectiveConfig()
    emit(
        "optimize",
        message="rejim-tahminli sağlam politika seçiliyor",
        regime=features.regime_label,
        tier=tier.key,
    )
    result = optimize_robust(
        train,
        oos,
        recent_in,
        space,
        features,
        budget,
        symbol,
        fee=fee,
        slippage=slippage_bps,
        obj_cfg=obj_cfg,
        tier=tier,
        time_budget_sec=time_budget_sec,
        progress_cb=progress_cb,
        n_workers=n_workers,
    )

    best_params = result.get("best_params")

    if best_params is None:
        # robust_engine hiçbir adayı için TÜM hard gate'leri geçemedi (result_type
        # = no_deployable_candidate). Walk-forward/final_holdout best_params'a
        # bağımlı olduğundan ANLAMSIZ — atlanır. Kısa devre: dürüst "uygulanabilir
        # parametre bulunamadı" kararı + reddedilen en iyi adayı teşhis amaçlı raporla.
        from app.services.param_optimizer.decision import (
            evaluate_decision,
            build_final_recommendation,
        )

        confidence = 0
        confidence_warnings: List[str] = ["no_deployable_candidate"]
        decision = evaluate_decision(result, confidence=confidence, has_oos=False)
        rationale = {
            "lines": [decision["headline"]],
            "summary": decision["headline"],
            "decision": decision["decision"],
        }
        # Rejim/forecast-skill teşhisi (climatology/transition/iskonto) HİÇBİR
        # adayın parametrelerine bağlı değil — best_params olmasa bile hesaplanır.
        robust_policy = build_robust_policy_report(
            features, result, fee_rate=fee, slippage_bps=slippage_bps,
        )
        final_recommendation = build_final_recommendation(
            decision=decision,
            deploy_gate=result.get("deploy_gate"),
            robust_policy_gate=(robust_policy or {}).get("deploy_gate"),
            forecast=None,
            oos=None,
            final_holdout_present=False,
            confidence_warnings=confidence_warnings,
        )
        # Reddedilen en iyi adayın gridlerini TEŞHİS amaçlı göster (öneri DEĞİL —
        # apply_policy.allowed=False bunu garanti eder). Kullanıcı denetimi: "UI'da
        # gridler gösterilecekse 'reddedilen en iyi aday' olarak gösterilmeli."
        _rejected_params = (result.get("rejected_best_candidate") or {}).get("params")
        ui_config = (
            to_ui_config(_rejected_params, budget, symbol)
            if _rejected_params
            else {"symbol": symbol, "budget_usd": round(budget, 2)}
        )
        # P0-8/P0-9: AYNI açık eşleme normal yoldaki gibi — burada da decision'ı
        # körü körüne "abstain" diye sabitleme (testlerde evaluate_decision/
        # build_final_recommendation monkeypatch'lenebilir; gerçek üretimde
        # decision.py'nin no_deployable_candidate kısa-devresi zaten abstain
        # döner, ama bu eşleme HER ZAMAN final_recommendation'ı baz almalı).
        _final_dec = final_recommendation["decision"]
        if _final_dec == "abstain":
            _allowed, _mode = False, "none"
        elif _final_dec == "watch_only":
            _allowed, _mode = True, "paper"
        else:  # deploy
            _allowed, _mode = True, "live"
        ui_config["apply_policy"] = {
            "allowed": _allowed,
            "recommended_mode": _mode,
            "decision": _final_dec,
            "reason": final_recommendation.get("headline", ""),
        }
        out = {
            "ok": True,
            "result_type": "no_deployable_candidate",
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "config_hash": config_hash(symbol, budget, tier.key),
            "market_data_hash": market_data_hash(backtest_candles),
            "symbol": symbol,
            "budget": budget,
            "tier": tier.key,
            "tier_label": tier.label,
            "params": None,
            "rejected_best_candidate": result.get("rejected_best_candidate"),
            "ui_config": ui_config,
            "features": features.to_dict(),
            "regime": {"code": features.regime_code, "label": features.regime_label},
            "confidence": confidence,
            "confidence_base": features.confidence,
            "decision": decision,
            "final_recommendation": final_recommendation,
            "in_sample": None,
            "oos": None,
            "forecast": None,
            "robust_policy": robust_policy,
            "robust_forecast": result.get("robust_forecast"),
            "causal_features": result.get("causal_features"),
            "deploy_gate": result.get("deploy_gate"),
            "pbo": result.get("pbo"),
            "deflated_sharpe_ok": result.get("deflated_sharpe_ok"),
            "plateau_ok": result.get("plateau_ok"),
            "stress_ok": result.get("stress_ok"),
            "walk_forward": None,
            "walk_forward_scope": "none",
            "final_holdout": None,
            "confidence_warnings": confidence_warnings,
            "score": None,
            "leaderboard": result.get("leaderboard"),
            "stats": result.get("stats"),
            "rationale": rationale,
            "elapsed_sec": round(time.time() - t0, 1),
        }
        emit("done", message="tamamlandı (uygulanabilir aday yok)", best_score=0.0)
        return json_safe(out)

    # 6) Walk-forward çapraz-dönem doğrulama: seçilen seti çok sayıda tarihsel OOS
    #    diliminde test et (tek 6-aylık OOS / n=3 tur yerine). Canlı botu DEĞİŞTİRMEZ;
    #    yalnızca seçilen setin tek döneme mi yoksa genele mi uyduğunu ölçer.
    # P0-2: çapraz-dönem walk-forward YALNIZ train üzerinde (oos/validation ve
    # final_holdout dahil DEĞİL) — seçim verisini yeniden test edip güveni şişirmesin.
    n_wf = int(getattr(tier, "walk_forward_oos_folds", 0) or 0)
    walk_forward = None
    wf_candles = train if (train and len(train) >= 120) else None
    if n_wf >= 2 and wf_candles:
        emit("walk_forward", message="çapraz-dönem doğrulama (walk-forward, yalnız train)", folds=n_wf)
        walk_forward = _walk_forward_eval(
            best_params, wf_candles, n_wf, budget, symbol,
            fee=fee, slippage=slippage_bps, obj_cfg=obj_cfg,
        )
    if walk_forward is not None:
        walk_forward["scope"] = "train_only"
    result["walk_forward"] = walk_forward

    # P0-2: GERÇEK bağımsız doğrulama — final_holdout optimizer tarafından HİÇ
    # görülmedi. Güven YALNIZCA bununla yükselebilir; yoksa/negatifse tavanlanır.
    final_holdout_result = None
    if final_holdout:
        _fhr = run_backtest(
            final_holdout, best_params, budget, symbol,
            fee_rate=fee, slippage_bps=slippage_bps,
        )
        final_holdout_result = _fhr.to_dict() if _fhr.ok else None

    confidence = adjust_confidence(
        features.confidence,
        result.get("oos_result"),
        result.get("in_sample_result"),
        result.get("forecast"),
        walk_forward=walk_forward,
    )
    confidence_warnings: List[str] = []
    if final_holdout_result is None:
        confidence = min(confidence, 55)
        confidence_warnings.append("final_holdout_missing_confidence_capped")
    elif float(final_holdout_result.get("return_pct") or 0.0) < 0:
        confidence = min(confidence, 55)
        confidence_warnings.append("final_holdout_negative_confidence_capped")
    rationale = build_rationale(symbol, budget, features, result, confidence=confidence)
    # KARAR KAPANIŞI: teşhis -> eylem. Dürüst kıyas (hedef tahsisi pasif tutma),
    # çekilme (abstention), tek kalibre olasılık, aşırı-uydurma bayrakları.
    from app.services.param_optimizer.decision import (
        evaluate_decision,
        build_final_recommendation,
    )

    decision = evaluate_decision(
        result, confidence=confidence, has_oos=bool(result.get("oos_result")),
        final_holdout=final_holdout_result,
    )
    # Dürüst manşeti EN ÜSTE koy (en parlak metriklerin altına gömme).
    try:
        if isinstance(rationale, dict):
            rationale.setdefault("lines", [])
            rationale["lines"].insert(0, decision["headline"])
            rationale["summary"] = decision["headline"]
            rationale["decision"] = decision["decision"]
    except Exception:
        pass
    robust_policy = build_robust_policy_report(
        features,
        result,
        fee_rate=fee,
        slippage_bps=slippage_bps,
    )
    # P0-6: decision + robust_engine.deploy_gate + robust_policy.deploy_gate → TEK
    # nihai karar. Sert bloklayıcı (OOS<0 / pbo / DSR / stres) varken deploy ASLA
    # mümkün olmaz; UI artık "önerilir" + "deploy=false" çelişkisini göstermez.
    final_recommendation = build_final_recommendation(
        decision=decision,
        deploy_gate=result.get("deploy_gate"),
        robust_policy_gate=(robust_policy or {}).get("deploy_gate"),
        forecast=result.get("forecast"),
        oos=result.get("oos_result"),
        final_holdout_present=final_holdout_result is not None,
        confidence_warnings=confidence_warnings,
    )
    ui_config = to_ui_config(best_params, budget, symbol)
    # P0-8/P0-9: NİHAİ karara göre AÇIK eşleme — abstain'de "live" YAZILAMAZ.
    # decision == abstain -> allowed=False, recommended_mode="none"
    # decision == watch_only -> allowed=True, recommended_mode="paper"
    # decision == deploy -> allowed=True, recommended_mode="live"
    _final_dec = final_recommendation["decision"]
    if _final_dec == "abstain":
        _allowed, _mode = False, "none"
    elif _final_dec == "watch_only":
        _allowed, _mode = True, "paper"
    else:  # deploy
        _allowed, _mode = True, "live"
    ui_config["apply_policy"] = {
        "allowed": _allowed,
        "recommended_mode": _mode,
        "decision": _final_dec,
        "reason": final_recommendation.get("headline", ""),
    }

    out = {
        "ok": True,
        "result_type": result.get("result_type", "ok"),
        "rejected_best_candidate": result.get("rejected_best_candidate"),
        # ── VERİ BÜTÜNLÜĞÜ / BAYAT SONUÇ ENGELİ ──────────────────────────────
        # UI bu üçlüyle "bu sonuç bu isteğe mi ait, şema uyumlu mu?" doğrular.
        # created_at/completed_at/job_id job katmanında (jobs.py) damgalanır.
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "config_hash": config_hash(symbol, budget, tier.key),
        "market_data_hash": market_data_hash(backtest_candles),
        "symbol": symbol,
        "budget": budget,
        "tier": tier.key,
        "tier_label": tier.label,
        "params": best_params,
        "ui_config": ui_config,
        "features": features.to_dict(),
        "regime": {"code": features.regime_code, "label": features.regime_label},
        "confidence": confidence,
        "confidence_base": features.confidence,
        "decision": decision,
        "final_recommendation": final_recommendation,
        "in_sample": result.get("in_sample_result"),
        "oos": result.get("oos_result"),
        "forecast": result.get("forecast"),
        "robust_policy": robust_policy,
        "robust_forecast": result.get("robust_forecast"),
        "causal_features": result.get("causal_features"),
        "deploy_gate": result.get("deploy_gate"),
        "pbo": result.get("pbo"),
        "deflated_sharpe_ok": result.get("deflated_sharpe_ok"),
        "plateau_ok": result.get("plateau_ok"),
        "stress_ok": result.get("stress_ok"),
        "walk_forward": walk_forward,
        "walk_forward_scope": (walk_forward or {}).get("scope", "none"),
        "final_holdout": final_holdout_result,
        "confidence_warnings": confidence_warnings,
        "score": result.get("best_score"),
        "leaderboard": result.get("leaderboard"),
        "stats": result.get("stats"),
        "rationale": rationale,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    emit(
        "done",
        message="tamamlandı",
        best_score=round((result.get("best_score") or {}).get("final_score", 0.0), 3),
    )
    # JSON sınırı: sonuçta NaN/Inf bırakma (aksi halde API 500 döner).
    return json_safe(out)


def to_ui_config(params: Dict[str, Any], budget: float, symbol: str) -> Dict[str, Any]:
    """Optimizer params'ını create-modal'ın beklediği config şemasına çevir."""
    up_grids = [
        {"trigger_pct": g["sell_grid_pct"], "qty_pct": g["sell_qty_pct_of_base"]}
        for g in params.get("sell_grids", [])
    ]
    down_grids = [
        {"trigger_pct": g["buy_grid_pct"], "qty_pct": g["buy_qty_pct_of_quote"]}
        for g in params.get("buy_grids", [])
    ]
    return {
        "symbol": symbol,
        "budget_usd": round(budget, 2),
        "base_alloc_pct": params["base_alloc_pct"],
        "quote_alloc_pct": params["quote_alloc_pct"],
        "up": {"grids": up_grids, "trail_pct": params["sell_trigger_trailing_pct"]},
        "down": {"grids": down_grids, "trail_pct": params["buy_trigger_trailing_pct"]},
        "profit": {
            "rebuy_trigger_pct": params["profit_reentry_drop_pct"],
            "rebuy_trail_pct": params["profit_reentry_rise_pct"],
            "resell_trigger_pct": params["profit_exit_rise_pct"],
            "resell_trail_pct": params["profit_exit_drop_pct"],
            "basis_mode": params.get("basis_mode", "grid_only"),
        },
        "max_buy_levels": params.get("max_buy_levels"),
        "min_net_profit_rate": params.get("min_net_profit_rate"),
    }


def _fmt(v, d=2):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _oos_reliability(n_oos: int, n_ref: int = 30) -> float:
    return 1.0 - math.exp(-max(0, n_oos) / max(1, n_ref))


def adjust_confidence(
    base_conf: float,
    oos: Optional[Dict[str, Any]],
    inr: Optional[Dict[str, Any]],
    forecast: Optional[Dict[str, Any]],
    walk_forward: Optional[Dict[str, Any]] = None,
) -> int:
    """İndikatör-netliği güvenini GERÇEK sonuçlarla hizala.

    features.confidence yalnızca geçmiş verinin okunabilirliğini ölçer; tek
    başına yüksek çıkabilir. Burada onu out-of-sample (görülmemiş dönem)
    performansı, kapanan tur sayısı, düşüş ve Monte Carlo ile cezalandırıp/
    ödüllendiriyoruz. Böylece OOS negatifken güven 90 kalamaz.
    """
    conf = float(base_conf)
    oos = oos or {}
    inr = inr or {}
    forecast = forecast or {}

    oos_ret = oos.get("return_pct")
    oos_cycles = int(oos.get("cycles_closed") or 0)
    oos_dd = oos.get("max_drawdown_pct")
    in_ret = inr.get("return_pct")
    prob = forecast.get("prob_profit")
    med = forecast.get("median_return_pct")
    n_paths = int(forecast.get("n_paths") or 0)

    c_signal = _clamp(conf / 100.0, 0.01, 1.0)
    if oos_ret is None:
        c_oos = 0.35
    else:
        risk_scale = max(8.0, abs(float(oos_dd or 0.0)), abs(float(oos_ret)) * 1.5)
        c_oos = _clamp(_norm_cdf((float(oos_ret) / risk_scale) * 2.2), 0.01, 1.0)
        if float(oos_ret) < 0:
            c_oos *= 0.72
    c_mc = 0.35
    if prob is not None:
        c_mc = _clamp(2.0 * (float(prob) - 0.5), 0.01, 1.0)
    if med is not None and float(med) < 0:
        c_mc *= 0.65
    if 0 < n_paths < 60:
        c_mc *= 0.75
    gap = 0.0
    if in_ret is not None and oos_ret is not None and float(in_ret) > float(oos_ret):
        gap = _clamp((float(in_ret) - float(oos_ret)) / max(abs(float(in_ret)), 1e-9), 0.0, 1.0)
    c_overfit = _clamp(1.0 - 0.6 * gap, 0.05, 1.0)

    comps = (c_signal, c_oos, c_mc, c_overfit)
    geo = math.exp(sum(math.log(max(c, 1e-6)) for c in comps) / len(comps))
    sample_mult = 0.2 + 0.8 * _oos_reliability(oos_cycles, 30)
    score = 100.0 * geo * sample_mult

    if oos_cycles <= 0:
        score = min(score, 35.0)
    elif oos_cycles == 1:
        score = min(score, 45.0)
    if oos_ret is not None and float(oos_ret) < 0:
        score = min(score, 55.0)
    if oos_dd is not None and float(oos_dd) > 25.0:
        score *= max(0.75, 1.0 - (float(oos_dd) - 25.0) / 100.0)

    # Walk-forward çapraz-dönem tutarlılığı (varsa): çoğu tarihsel dilim kârlıysa
    # hafif ödül, azınlığı kârlıysa ceza. Çok sayıda OOS turu tek-dönem bağımlılığını
    # azaltır -> küçük ek güven. walk_forward None ise skor DEĞİŞMEZ (geriye uyumlu).
    if walk_forward:
        fp = float(walk_forward.get("frac_profitable") or 0.0)
        wf_cycles = int(walk_forward.get("total_cycles") or 0)
        score *= _clamp(0.6 + 0.6 * fp, 0.6, 1.15)
        if wf_cycles >= 20 and fp >= 0.6:
            score = min(95.0, score + 3.0)

    return int(round(_clamp(score, 5.0, 95.0)))


def _hurst_label(f: HistoryFeatures) -> str:
    """Hurst'ü KENDİ eşiklerine göre etiketle (trend skoru/ADX ile karıştırma).

    Hurst sadece serinin kalıcılık/geri-dönüş karakterini ölçer:
      <0.45  -> mean-reversion eğilimi belirgin
      0.45-0.55 -> nötr (0.5 altı hafif mean-reverting, 0.5 ve üstü nötr/karışık)
      >0.55  -> trend devamlılığı eğilimi
    0.48 gibi bir değeri 'trendli' diye etiketlemek yanlıştır (hafif mean-reverting/nötrdür).
    """
    h = f.hurst if f.hurst is not None else 0.5
    if h < 0.45:
        return "mean-reversion eğilimi belirgin"
    if h <= 0.55:
        return "nötr / hafif mean-reverting" if h < 0.5 else "nötr / karışık"
    return "trend devamlılığı eğilimi"


def _alloc_word(base_pct: float) -> str:
    """Etiketi gerçek orana göre ver (trend tahminine değil)."""
    if base_pct >= 55:
        return "base ağırlıklı (yukarı eğilim)"
    if base_pct <= 40:
        return "quote ağırlıklı (savunma)"
    return "dengeli"


def _mc_return_percentile(realized, p05, p50, p95):
    """Gerçekleşen getirinin MC getiri dağılımındaki YAKLAŞIK percentile'i.

    DD ekseni uyarısı tek başına zayıftır (tanım gereği sonuçların ~%5'i p95'i
    aşar). Asıl sinyal GETİRİ eksenidir: gerçekleşen OOS getirisi MC dağılımının
    neresinde? Parçalı-doğrusal (p05->5, p50->50, p95->95); uç sol kuyruk (<~10)
    => MC merkezi (medyan) iyimser tohumlanmış demektir (in-sample benzeri rejimden
    resample edildiği için). None döner: yeterli MC verisi yok.
    """
    if p05 is None or p50 is None:
        return None
    try:
        realized = float(realized)
        p05 = float(p05)
        p50 = float(p50)
    except (TypeError, ValueError):
        return None
    if realized <= p05:
        # p05'in altı: sol uca doğru 0..5 aralığına sıkıştır
        span = max(abs(p05), 1e-9)
        return max(0.0, 5.0 * (1.0 - min(1.0, (p05 - realized) / span)))
    if realized <= p50:
        return 5.0 + (realized - p05) / max(p50 - p05, 1e-9) * 45.0
    if p95 is not None:
        p95 = float(p95)
        if realized <= p95:
            return 50.0 + (realized - p50) / max(p95 - p50, 1e-9) * 45.0
        return min(100.0, 95.0 + (realized - p95) / max(abs(p95), 1e-9) * 5.0)
    return min(95.0, 50.0 + (realized - p50) / max(abs(p50), 1e-9) * 45.0)


def build_rationale(
    symbol: str,
    budget: float,
    f: HistoryFeatures,
    result: Dict[str, Any],
    *,
    confidence: Optional[int] = None,
) -> Dict[str, Any]:
    """Asistan anlatısı: ne bulundu, neden bu parametreler. (Türkçe, UI besler.)"""
    p = result["best_params"]
    inr = result.get("in_sample_result") or {}
    oos = result.get("oos_result") or {}
    stats = result.get("stats") or {}
    fc = result.get("forecast") or {}
    sell_n = len(p.get("sell_grids", []))
    buy_n = len(p.get("buy_grids", []))

    lines: List[str] = []
    lines.append(
        f"{symbol} için tüm geçmişi taradım; rejim **{f.regime_label}**, "
        f"tipik kısa-vade swing ~%{_fmt(f.swing_pct)}, ATR ~%{_fmt(f.atr_pct)}, "
        f"trend skoru {_fmt(f.trend_score)}, mean-reversion {_fmt(f.mean_reversion)}, "
        f"grid uygunluk {_fmt(getattr(f, 'grid_suitability', 0.5), 2)}."
    )
    lines.append(
        f"İndikatör panosu: Hurst {_fmt(f.hurst)} "
        f"({_hurst_label(f)}), "
        f"RSI {_fmt(f.rsi, 0)}, Stochastic {_fmt(f.stoch_k, 0)}, MACD-hist %{_fmt(f.macd_hist, 3)}, "
        f"ADX {_fmt(f.adx, 0)}, Donchian genişlik %{_fmt(f.donchian_width_pct)}. "
        f"Etkili trend gücü {_fmt(getattr(f, 'effective_trend_strength', 0.0), 2)} "
        f"(trend skoru ADX ile kapılanır)."
    )
    # ADX trend GÜCÜNÜ ölçer, yön değil. Düşük ADX'te trend skoru negatif olsa bile
    # "güçlü aşağı trend" denemez. Güç (ADX) ile yön (trend skoru) ayrı yorumlanır.
    adx_v = f.adx if f.adx is not None else 0.0
    ts = f.trend_score
    yon = "aşağı" if ts < 0 else "yukarı"
    if adx_v >= 25 and abs(ts) >= 0.28:
        lines.append(
            f"Uyarı: ADX {_fmt(adx_v, 0)} ve trend skoru {_fmt(ts)} belirgin bir {yon} trende "
            f"işaret ediyor (ADX trend gücünü teyit ediyor); piyasa temiz yatay değil. Bu yüzden "
            f"set saf yatay-grid değil, trendli/oynak piyasada savunma + kademeli işlem mantığıyla kuruldu."
        )
    elif abs(ts) >= 0.25 and adx_v < 20:
        lines.append(
            f"Not: trend skoru {_fmt(ts)} hafif {yon} eğilim gösteriyor, ancak ADX {_fmt(adx_v, 0)} "
            f"çok düşük — trend GÜCÜ zayıf. Yani güçlü {yon} trend değil; piyasa yatay/dalgalı "
            f"(hafif {yon} eğimli) okunmalı. (ADX yön değil, yalnızca trend gücünü ölçer.)"
        )
    # P0-1 DÜRÜSTLÜK: bu bir "binlerce kombinasyon" brute-force taraması DEĞİLDİR.
    # Gerçek üretilen aday sayısı, gerçek backtest sayısı ve gerçek çekirdek sayısı
    # raporlanır (eski metin literal workers=1 ve aday sayısını "kombinasyon" diye basıyordu).
    _uniq = stats.get("unique_candidates_total", stats.get("evals_total", "—"))
    _valid = stats.get("validated_candidates_total", stats.get("validated", "—"))
    _bt = stats.get("candidate_backtests_total", "—")
    _cores = stats.get("workers_used", stats.get("workers", "—"))
    _mc_cand = stats.get("mc_candidates_total", 0)
    _mc_paths = stats.get("mc_paths_effective", stats.get("mc_paths", 0))
    _mc_txt = (
        f" Monte Carlo açıkken {_mc_cand} aday × {_mc_paths} sentetik fiyat yolu (gerçek değil, simülasyon) test edildi."
        if _mc_paths and int(_mc_paths or 0) > 0
        else ""
    )
    lines.append(
        "Bu analiz binlerce kombinasyonun brute-force taraması DEĞİLDİR: rejim/volatiliteden "
        f"türetilen {_uniq} benzersiz yapısal aday üretildi; {_valid} aday train/OOS/recent "
        f"backtest'inden geçti (yaklaşık {_bt} gerçek strateji backtest'i, {_cores} paralel "
        f"çekirdek, {_fmt(stats.get('elapsed_sec'), 1)} sn)." + _mc_txt
    )
    lines.append(
        f"Alloc: base %{_fmt(p['base_alloc_pct'], 1)} / quote %{_fmt(p['quote_alloc_pct'], 1)} "
        f"— {_alloc_word(p['base_alloc_pct'])}."
    )
    lines.append(
        f"Grid: {sell_n} satış / {buy_n} alım seviyesi; ilk adım satış ~%{_fmt(p['sell_grids'][0]['sell_grid_pct']) if sell_n else '—'}, "
        f"alım ~%{_fmt(p['buy_grids'][0]['buy_grid_pct']) if buy_n else '—'}. "
        f"Trail satış %{_fmt(p['sell_trigger_trailing_pct'])} / alım %{_fmt(p['buy_trigger_trailing_pct'])}."
    )
    # İlk grid seviyesi tipik swing/ATR bandından fazla uzaksa bot normal salınımlarda
    # tetiklenmez -> düşük işlem sıklığı (aktif grid'den çok savunmacı/bekleyen set).
    swing = f.swing_pct if f.swing_pct is not None else 0.0
    first_sell = p["sell_grids"][0]["sell_grid_pct"] if sell_n else None
    first_buy = p["buy_grids"][0]["buy_grid_pct"] if buy_n else None
    atr = f.atr_pct if f.atr_pct is not None else 0.0
    too_wide = (
        (swing > 0 and (
            (first_sell is not None and first_sell > swing * 1.35)
            or (first_buy is not None and first_buy > swing * 1.35)
        ))
        or (atr > 0 and (
            (first_sell is not None and first_sell > atr * 2.5)
            or (first_buy is not None and first_buy > atr * 2.5)
        ))
    )
    if too_wide:
        sell_atr = (first_sell / atr) if (first_sell is not None and atr > 0) else None
        buy_atr = (first_buy / atr) if (first_buy is not None and atr > 0) else None
        atr_txt = (
            f" Satış {_fmt(sell_atr, 2)}x ATR, alış {_fmt(buy_atr, 2)}x ATR."
            if atr > 0
            else ""
        )
        lines.append(
            f"Not: ilk grid seviyeleri (satış ~%{_fmt(first_sell)}, alış ~%{_fmt(first_buy)}) tipik "
            f"kısa-vade swing'e (~%{_fmt(swing)}) ve ATR'ye (~%{_fmt(atr)}) göre geniş kalıyor.{atr_txt} "
            f"Fiyat normal salınımlarda kalırsa bu seviyeler tetiklenmez; yani işlem sıklığı düşük olur. "
            f"Range piyasada grid adımı ATR'ye daha yakın olmalı; komisyon tabanı yalnızca alt sınırdır."
        )
    lines.append(
        f"Tur kapanışı: kâr-al tetik %{_fmt(p['profit_exit_rise_pct'])} (trail %{_fmt(p['profit_exit_drop_pct'])}), "
        f"yeniden-giriş tetik %{_fmt(p['profit_reentry_drop_pct'])} (trail %{_fmt(p['profit_reentry_rise_pct'])})."
    )
    if oos:
        oos_ret = oos.get("return_pct")
        oos_cycles = int(oos.get("cycles_closed") or 0)
        verdict = ""
        if oos_ret is not None and oos_ret < 0:
            verdict = (
                " — Dürüst değerlendirme: bu görülmemiş dönemde set ZARAR etti. "
                "Alpha pozitif olsa bile bu yalnızca 'piyasadan daha az kötü' demektir, kâr garantisi değil."
            )
        elif oos_cycles <= 1:
            verdict = (
                " — Ancak bu dönemde yalnızca "
                f"{oos_cycles} tur kapandı; örneklem çok zayıf, sonuca temkinli yaklaş."
            )
        alpha_full = oos.get("alpha_pct")
        alpha_grid = oos.get("grid_alpha_pct")
        cash_buf = oos.get("cash_buffer_alpha_pct")
        cash_share = oos.get("alpha_cash_share")
        alpha_txt = f"alpha %{_fmt(alpha_full)} (100% buy&hold'a göre)"
        if alpha_grid is not None:
            alpha_txt += (
                f"; maruziyet-eş statik kıyasa göre gerçek grid alpha %{_fmt(alpha_grid)}, "
                f"nakit tamponu etkisi %{_fmt(cash_buf)}"
            )
            if cash_share is not None:
                alpha_txt += f" (raporlanan alpha içinde nakit payı %{_fmt(float(cash_share) * 100, 0)})"
        lines.append(
            f"Doğrulama (görmediği son ~6 ay = botun ilk 6 ayı vekili): getiri %{_fmt(oos_ret)}, "
            f"{oos_cycles} tur, maks. düşüş %{_fmt(oos.get('max_drawdown_pct'))}, "
            f"{alpha_txt}." + verdict
        )
        # MARUZİYET KAYMASI: "maruziyet-eş grid alpha" ~0 görünse bile, gerçekleşen
        # maruziyet NİYET edilenin belirgin üstündeyse set gizlice long'a kaymıştır.
        # Bu, zarar/düşüşün asıl kaynağıdır ve nakit-payı metriği bunu örter.
        exp_frac = oos.get("exposure_frac")
        intended = oos.get("intended_base_frac")
        drift = oos.get("exposure_drift")
        alpha_intended = oos.get("grid_alpha_vs_intended_pct")
        if (
            drift is not None
            and intended is not None
            and exp_frac is not None
            and drift > 0.12
        ):
            lines.append(
                f"⚠ Maruziyet kayması: kurmak istediğin tahsis ~%{_fmt(intended * 100, 0)} base, "
                f"ama grid düşüşte dip alıp ortalama maruziyeti ~%{_fmt(exp_frac * 100, 0)} base'e "
                f"sürükledi (+{_fmt(drift * 100, 0)} puan) — set sessizce long'a kaydı. 'Maruziyet-eş "
                f"grid alpha' bu KAYMIŞ orana göre ölçüldüğünden ~0 çıkar ve sorunu örter; oysa NİYET "
                f"ettiğin ~%{_fmt(intended * 100, 0)}/{_fmt((1 - intended) * 100, 0)} tahsise göre grid "
                f"alpha %{_fmt(alpha_intended)}. Yani −%{_fmt(abs(oos_ret) if oos_ret else 0)} ve "
                f"düşüşün asıl kaynağı grid mekaniği değil, bu maruziyet kayması (simetrik grid + zayıf "
                f"aşağı drift = negatif taşıma). Yapısal çözüm: asimetrik grid + envanter tavanı + DD-stop."
            )
        if oos_cycles == 0:
            lines.append(
                "Önemli: bu set doğrulama döneminde HİÇ döngü kapatmadı (0 tur). Sermayeyi koruma "
                "eğilimi olabilir ama aktif grid stratejisi olarak işlem üretme başarısı DOĞRULANMADI. "
                "Bunu 'önerilen ana set' gibi değil, pasif/izleme seti olarak değerlendir — canlı ana öneri olmamalı."
            )
    in_dd = inr.get("max_drawdown_pct")
    in_cycles = int(inr.get("cycles_closed") or 0)
    in_note = " (in-sample parametre seçimi için kullanıldığından doğal olarak iyimserdir; asıl ölçüt OOS'tur)"
    if 0 < in_cycles < 8:
        in_note += (
            f". Win-rate yalnızca {in_cycles} tur üzerinden hesaplandığından istatistiksel güveni "
            f"sınırlıdır (bir tur değişse oran dramatik kayar)"
        )
    if in_dd is not None and in_dd >= 40:
        in_note += f". Dikkat: in-sample maks. düşüş %{_fmt(in_dd)} — yüksek getiri tek başına güvenli demek değil."
    lines.append(
        f"Geçmiş (in-sample): getiri %{_fmt(inr.get('return_pct'))}, {inr.get('cycles_closed', 0)} tur, "
        f"win-rate %{_fmt(inr.get('win_rate'), 1)}, maks. düşüş %{_fmt(in_dd)}" + in_note + "."
    )
    # BEKLENTİ: win-rate tek başına yanıltıcıdır (yüksek win-rate + büyük seyrek kayıp
    # = negatif beklenti). payoff başabaş eşiğini aşmazsa set kâr beklemez.
    in_payoff = inr.get("payoff")
    in_be = inr.get("breakeven_payoff")
    in_exp = inr.get("expectancy_per_cycle")
    if in_cycles > 0 and in_payoff is not None and in_be is not None:
        be_txt = (
            "∞"
            if (in_be is None or not math.isfinite(float(in_be)))
            else _fmt(in_be, 2)
        )
        neg = (in_exp is not None and float(in_exp) < 0) or (
            in_payoff is not None
            and in_be is not None
            and math.isfinite(float(in_be))
            and float(in_payoff) <= float(in_be)
        )
        lines.append(
            f"Beklenti (win-rate'i büyüklükle birlikte oku): ort. kazanç {_fmt(inr.get('avg_win'))} / "
            f"ort. kayıp {_fmt(inr.get('avg_loss'))} USDT, payoff {_fmt(in_payoff, 2)} "
            f"(başabaş için >{be_txt} gerek), tur başına beklenti {_fmt(in_exp)} USDT, "
            f"profit factor {_fmt(inr.get('profit_factor'), 2)}. "
            + (
                "Win-rate yüksek görünse de payoff başabaşı aşmıyor — beklenti zayıf/negatif."
                if neg
                else "Payoff başabaşı aşıyor; beklenti pozitif tarafta."
            )
        )
    # MALİYET SÜRTÜNMESİ: dar gridlerde komisyon+slipaj getirinin önemli kısmını yer.
    cd_in = inr.get("cost_drag_pct")
    cd_oos = oos.get("cost_drag_pct") if oos else None
    if cd_in is not None and float(cd_in) > 0:
        cd_txt = (
            f"Maliyet sürtünmesi (taker komisyon + slipaj; spot olduğundan funding yok): "
            f"in-sample ~%{_fmt(cd_in)} getiriden düşüyor"
        )
        if cd_oos is not None:
            cd_txt += f", OOS ~%{_fmt(cd_oos)}"
        cd_txt += (
            ". Grid daraldıkça bu sürtünme artar; trailing fill'leri taker (piyasa) emri "
            "olduğundan maker indirimi varsayılmaz. (Kısmi/garantisiz limit kuyruğu modellenmez.)"
        )
        lines.append(cd_txt)
    if fc and fc.get("n_paths"):
        n_paths = int(fc.get("n_paths") or 0)
        prob = (fc.get("prob_profit") or 0) * 100
        mc_close = "Seti gelecek senaryolarında dayanıklı (ne agresif ne pasif) olacak şekilde seçtim."
        if prob < 60 or n_paths < 60:
            extras = []
            if prob < 60:
                extras.append(f"kâr olasılığı %{_fmt(prob, 0)} güçlü bir avantaj göstermiyor")
            if n_paths < 60:
                extras.append(f"{n_paths} senaryo istatistiksel olarak sınırlı")
            mc_close = "Not: " + "; ".join(extras) + " — sonucu kesinlik değil, risk göstergesi olarak oku."
        lines.append(
            f"Gelecek tahmini (Monte Carlo, {n_paths} senaryo): medyan getiri "
            f"%{_fmt(fc.get('median_return_pct'))}, kötü senaryo (p5) %{_fmt(fc.get('p05_return_pct'))}, "
            f"kâr olasılığı %{_fmt(prob, 0)}, "
            f"medyan maks. düşüş %{_fmt(fc.get('median_max_dd_pct'))}, "
            f"p95 maks. düşüş %{_fmt(fc.get('worst_max_dd_pct'))}. " + mc_close
        )
        if oos and fc.get("worst_max_dd_pct") is not None and oos.get("max_drawdown_pct") is not None:
            if float(oos.get("max_drawdown_pct") or 0.0) > float(fc.get("worst_max_dd_pct") or 0.0):
                lines.append(
                    "Uyarı (düşüş ekseni): gerçek OOS düşüşü Monte Carlo p95 bandını aşıyor. Tek başına "
                    "zayıf kanıttır (tanım gereği sonuçların ~%5'i p95'i aşar); asıl doğrulama getiri ekseninden gelir."
                )
        # GETİRİ ekseni doğrulaması (asıl sinyal): gerçekleşen OOS getirisi MC getiri
        # dağılımının neresinde? Uç sol kuyruk => MC merkezi iyimser tohumlanmış.
        if oos and oos.get("return_pct") is not None:
            pctile = _mc_return_percentile(
                oos.get("return_pct"),
                fc.get("p05_return_pct"),
                fc.get("median_return_pct"),
                fc.get("p95_return_pct"),
            )
            if pctile is not None and pctile < 12.0:
                lines.append(
                    f"⚠ Asıl uyarı (getiri ekseni): gerçekleşen OOS getirisi %{_fmt(oos.get('return_pct'))}, "
                    f"MC getiri dağılımında ~p{_fmt(pctile, 0)} (uç sol kuyruk). Hem getiri (p{_fmt(pctile, 0)}) "
                    f"hem düşüş (p95+) aynı anda sol kuyruktaysa MC merkezi (medyan %{_fmt(fc.get('median_return_pct'))}) "
                    f"iyimser tohumlanmış demektir — medyanı beklenti değil, iyi-hal senaryosu gibi oku. "
                    f"({n_paths} senaryo p95/p5 kuyrukları için sınırlı; daha güvenilir kalibrasyon için ≥10.000 "
                    f"yol ve OOS-benzeri (yakın/olumsuz) rejime koşullu resample gerekir.)"
                )
    # ÇOKLU-TEST: daha çok kombinasyon overfit'i AZALTMAZ, çıtayı YÜKSELTİR. IS>>OOS
    # ve işaret değişimi, fazladan aramanın "şanslı" seti seçtiğinin belirtisidir.
    evals = int(stats.get("evals_total") or stats.get("search_evals") or 0)
    _in_ret = inr.get("return_pct")
    _oos_ret = oos.get("return_pct") if oos else None
    if (
        evals >= 50
        and _in_ret is not None
        and _oos_ret is not None
        and float(_in_ret) > 0
        and float(_oos_ret) < 0
    ):
        lines.append(
            f"Çoklu-test uyarısı: {evals} kombinasyon denenip en iyisi seçildi; in-sample %{_fmt(_in_ret)} "
            f"iken OOS %{_fmt(_oos_ret)} (işaret değişimi). Aramayı genişletmek overfit'i azaltmaz — 'şans "
            f"değil' demek için seçilen setin aşması gereken eşiği yükseltir (beklenen-maks Sharpe deneme "
            f"sayısıyla artar). Çözüm: arama uzayını büyütmek değil; walk-forward/nested-CV ile seçim ve "
            f"knob sayısını kuralla azaltmak (örn. trail=c·ATR, TP=dış grid, rebuy=iç grid)."
        )
    wf = result.get("walk_forward")
    if wf and wf.get("n_folds"):
        nf = int(wf.get("n_folds") or 0)
        fprof = int(wf.get("folds_profitable") or 0)
        verdict_wf = (
            "Çoğu dönemde kârlı — tek döneme ezber riski düşük."
            if nf and fprof / nf >= 0.6
            else (
                "Dilimlerin çoğu kârsız — set tek/az döneme bağlı; tek bir 6-aylık OOS yanıltabilir, "
                "canlıya almadan önce dikkatli ol."
            )
        )
        lines.append(
            f"Çapraz-dönem doğrulama (walk-forward, {nf} tarihsel dilim): {fprof}/{nf} dilim kârlı "
            f"(ort. getiri %{_fmt(wf.get('mean_return_pct'))}, medyan %{_fmt(wf.get('median_return_pct'))}, "
            f"en kötü dilim %{_fmt(wf.get('worst_fold_return_pct'))}), toplam {wf.get('total_cycles')} OOS turu "
            f"(tek dönemdeki az turdan çok daha güçlü örneklem). " + verdict_wf
        )
    if stats.get("walk_forward_folds", 1) and stats.get("walk_forward_folds", 1) > 1:
        lines.append(
            f"Walk-forward seçim: parametreyi {stats['walk_forward_folds']} farklı tarihsel dilimde test edip "
            f"tutarlı olanı seçtim (tek döneme ezber değil)."
        )
    if stats.get("stopped_early"):
        lines.append(
            "Skor yakınsadığı için aramayı erken bitirdim — daha fazla süre daha iyi sonuç vermiyordu."
        )
    if confidence is not None:
        oos_ret = oos.get("return_pct") if oos else None
        oos_cycles = int(oos.get("cycles_closed") or 0) if oos else 0
        if confidence >= 70:
            tone = "veri ve doğrulama büyük ölçüde uyumlu"
        elif confidence >= 50:
            tone = "sinyaller karışık; uygulamadan önce risk iştahını gözden geçir"
        else:
            tone = "doğrulama zayıf; bu seti canlıya almadan önce dikkatli ol"
        basis = []
        if oos_ret is not None:
            basis.append(f"OOS getiri %{_fmt(oos_ret)}")
        if oos:
            basis.append(f"{oos_cycles} OOS tur")
        if fc and fc.get("prob_profit") is not None:
            basis.append(f"MC kâr olasılığı %{_fmt((fc.get('prob_profit') or 0) * 100, 0)}")
        basis_txt = (" (" + ", ".join(basis) + ")") if basis else ""
        lines.append(
            f"Güven skoru {confidence}/100 — {tone}. Bu skoru yalnızca indikatör netliğine değil, "
            f"görülmemiş dönem performansına da bağladım{basis_txt}."
        )
    return {"lines": lines, "summary": lines[0]}
