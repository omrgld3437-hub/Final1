"""
Parametre Optimizasyon Motoru (param_optimizer)
================================================

Bütçe + parite dışındaki TÜM bot parametrelerini, coinin geçmiş verisi üzerinde
GERÇEK strateji backtest'i çalıştırarak belirler. Frontend'deki eski heuristik
"parametre asistanı"nın yerini alır.

Akış (engine.run_optimization):
    1. history     -> Binance'ten derin geçmiş klines (hibrit çözünürlük) çek
    2. indicators  -> tüm geçmiş için zengin indikatör + rejim seti hesapla
    3. space       -> indikatör temelli akıllı parametre arama uzayı türet
    4. backtest    -> gerçek dca_grid_trailing motorunu fiyat yolu üzerinde sür
    5. objective   -> kâr + işlem sıklığı (son yıl ağırlıklı, OOS doğrulamalı) skor
    6. search      -> zaman bütçesine göre coarse-to-fine optimizasyon
    -> en iyi parametre seti + teşhis + insan-okur gerekçe

Tüm ağır hesap backend'de (Python) çalışır; asistan UI bir job başlatıp ilerlemeyi
poll eder (bkz. jobs.py + api routes).
"""

from __future__ import annotations

__all__ = [
    "run_backtest",
    "BacktestResult",
]

from app.services.param_optimizer.backtest import run_backtest, BacktestResult
