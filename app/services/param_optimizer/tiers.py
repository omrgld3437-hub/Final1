"""
Analiz modu: tek "Profesyonel Otomatik Analiz" (professional_auto).

Kullanıcıya süre/derinlik seçtirilmez (eski Düşük/Orta/Yüksek kaldırıldı — düşük
mod güvenilir değildi, orta mod kendi içinde "MC örneklemi zayıf" diyordu, yüksek
mod kullanıcıya seçtirmek yerine zaten tek doğru varsayılan olmalıydı). Tek mod
geniş aday taraması, çok-dönem OOS doğrulama, walk-forward, Monte Carlo, stres
testi ve final holdout'u otomatik çalıştırır; SÜREYE göre değil KANIT KALİTESİNE
göre biter (yakınsarsa erken durur, kanıt karışıksa tavana — 6 saat — kadar devam
eder). Full CPU kullanır; yakınsama kararı en az 30 dk gerçek aramadan sonra verilir.
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
    # MC örneklemi bu tabanın altındaysa deploy_probability yüzde olarak gösterilmez
    # ("MC örneklemi yetersiz" yazar) ve deploy hard-reject olur.
    mc_min_paths_for_deploy: int = 300


PROFESSIONAL_AUTO = AnalysisTier(
    key="professional_auto",
    label="Profesyonel Otomatik Analiz",
    time_budget_sec=21600,  # tavan 6 saat
    fine_interval="5m",
    fine_days=365,
    coarse_interval="1h",
    max_days=1460,
    monte_carlo_paths=2400,
    mc_horizon_days=180,
    mc_top_candidates=32,
    walk_forward_folds=8,
    validate_top=128,
    early_stop=True,
    requires_confirm=False,
    description=(
        "En iyi parametreleri bulmak için geniş aday taraması, çoklu OOS doğrulama, "
        "final holdout, Monte Carlo, stres testi ve canlıya uygunluk kapıları otomatik "
        "çalışır. Uygulanabilir aday yoksa parametre önermez. Süreye göre değil kanıt "
        "kalitesine göre biter; en az 30 dk, tavan 6 saat."
    ),
    min_runtime_sec=1800,
    walk_forward_oos_folds=8,
    mc_min_paths_for_deploy=600,
)

TIERS: Dict[str, AnalysisTier] = {"professional_auto": PROFESSIONAL_AUTO}


def get_tier(key: Optional[str] = None) -> AnalysisTier:
    """Geriye uyumluluk: eski soft/medium/high (ya da başka) ne gelirse gelsin
    tek profesyonel moda eşlenir — frontend yanlışlıkla eski bir anahtar gönderse
    bile backend her zaman professional_auto çalıştırır."""
    return PROFESSIONAL_AUTO


def estimate_seconds(tier: AnalysisTier, n_workers: int = 0) -> Dict[str, float]:
    """Başlamadan önce kabaca tahmini süre aralığı.

    Tek mod kanıt kalitesine göre biter: erken yakınsarsa taban (~30dk) civarında,
    karışık kanıtta tavana (6 saat) kadar sürebilir.
    """
    nw = n_workers or max(1, (os.cpu_count() or 4))
    cap = tier.time_budget_sec
    low = max(tier.min_runtime_sec, cap * 0.16)
    high = cap
    return {
        "eta_low_sec": round(low, 0),
        "eta_high_sec": round(high, 0),
        "cap_sec": cap,
        "cores": nw,
    }
