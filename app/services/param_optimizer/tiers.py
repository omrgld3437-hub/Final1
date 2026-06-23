"""
Analiz seviyeleri: SOFT / ORTA / YÜKSEK.

Her seviye veri çözünürlüğü, zaman bütçesi, Monte Carlo yoğunluğu, walk-forward
fold sayısı ve doğrulama derinliğini belirler. Yüksek seviye full CPU + uzun süre
(1-6 saat) kullanır; yakınsama kararı en az 1 saatlik gerçek aramadan sonra verilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class AnalysisTier:
    key: str
    label: str
    time_budget_sec: float  # arama için duvar-saati tavanı
    fine_interval: str  # yakın geçmiş çözünürlüğü
    fine_days: int
    coarse_interval: str  # uzak geçmiş çözünürlüğü
    max_days: int
    monte_carlo_paths: int  # 0 => gelecek simülasyonu kapalı
    mc_horizon_days: int
    mc_top_candidates: int  # en iyi kaç aday Monte Carlo'dan geçer
    walk_forward_folds: int  # 1 => sadece tek OOS
    validate_top: int
    early_stop: bool  # yakınsayınca erken dur
    requires_confirm: bool  # başlamadan önce kullanıcı onayı
    description: str
    min_runtime_sec: float = 0.0  # erken durmadan önce gerçek arama tabanı
    # Seçilen seti çok sayıda tarihsel OOS diliminde doğrula (tek 6-aylık OOS yerine).
    # Çapraz-dönem tutarlılık + toplam OOS tur sayısını yükseltir (n=3 -> onlarca/yüzlerce).
    walk_forward_oos_folds: int = 4


TIERS: Dict[str, AnalysisTier] = {
    "soft": AnalysisTier(
        key="soft",
        label="Düşük",
        time_budget_sec=75,
        fine_interval="1h",
        fine_days=365,
        coarse_interval="1d",
        max_days=1460,
        monte_carlo_paths=0,
        mc_horizon_days=120,
        mc_top_candidates=0,
        walk_forward_folds=1,
        validate_top=8,
        early_stop=True,
        requires_confirm=False,
        description="Sunucuda gerçek strateji backtest + son dönem doğrulama. Yerel hızlı tahmin değildir. ~1 dk.",
        walk_forward_oos_folds=3,
    ),
    "medium": AnalysisTier(
        key="medium",
        label="Orta",
        time_budget_sec=420,
        fine_interval="15m",
        fine_days=365,
        coarse_interval="1h",
        max_days=1460,
        monte_carlo_paths=240,
        mc_horizon_days=150,
        mc_top_candidates=10,
        walk_forward_folds=1,
        validate_top=14,
        early_stop=True,
        requires_confirm=False,
        description="15dk ince veri + OOS doğrulama + Monte Carlo gelecek simülasyonu. ~5-8 dk.",
        walk_forward_oos_folds=4,
    ),
    "high": AnalysisTier(
        key="high",
        label="Yüksek",
        time_budget_sec=21600,  # 6 saat tavan
        fine_interval="5m",
        fine_days=365,
        coarse_interval="1h",
        max_days=1460,
        monte_carlo_paths=2400,
        mc_horizon_days=180,
        mc_top_candidates=72,
        walk_forward_folds=6,
        validate_top=96,
        early_stop=True,
        requires_confirm=True,
        description="Derin analiz: 5dk son yıl + 1s tüm geçmiş + 6-fold walk-forward "
        "+ ağır Monte Carlo ilk 6 ay senaryoları. Full CPU; en az 1 saat, tavan 6 saat. "
        "Mantıksız kombinasyonlar elenir; yakınsama ancak 1 saatten sonra aramayı bitirebilir.",
        min_runtime_sec=3600,
        walk_forward_oos_folds=6,
    ),
}


def get_tier(key: Optional[str]) -> AnalysisTier:
    return TIERS.get((key or "high").strip().lower(), TIERS["high"])


def estimate_seconds(tier: AnalysisTier, n_workers: int = 0) -> Dict[str, float]:
    """Başlamadan önce kabaca tahmini süre aralığı (onay diyaloğu için).

    Çekirdek sayısı arttıkça arama hızlanır ama bütçe tavanı sabit kalır; bu yüzden
    tahmin, "veri çekme + tipik yakınsama" temelli kaba bir aralıktır.
    """
    nw = n_workers or max(1, (os.cpu_count() or 4))
    # veri çekme yükü (interval/gün'e göre kaba)
    fetch = {"soft": 6, "medium": 25, "high": 70}.get(tier.key, 25)
    cap = tier.time_budget_sec
    if tier.key == "soft":
        low, high = fetch + 25, fetch + cap
    elif tier.key == "medium":
        low, high = fetch + cap * 0.45, fetch + cap
    else:  # high: 1-6 saatlik derin otomatik profil
        low = max(tier.min_runtime_sec, fetch + cap * 0.16)
        high = cap
    return {
        "eta_low_sec": round(low, 0),
        "eta_high_sec": round(high, 0),
        "cap_sec": cap,
        "cores": nw,
    }
