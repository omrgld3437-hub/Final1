"""
FILE: test_dynamic_v2_spread_units.py
VERSION: v1
DATE: 2026-08-03
CHANGE: dynamic_v2 spread/ATR birim sözleşmesini kilitler.

Neden: modülde ``spread_pct`` adı iki farklı ölçekte kullanılıyor —
feature katmanında 0..1 normalize skor, kısıt katmanında yüzde puanı. Hesap
şu an doğru ama isim tuzaklı; biri yanlış katmana bağlarsa grid aralıkları
100 kat sapar ve bu sessizce gerçek para kaybettirir. Testler ölçeği sabitler.
"""

from decimal import Decimal

import pytest

from app.botengine.dynamic_v2.config import DynamicV2Config
from app.botengine.dynamic_v2.constraints import D as CONSTRAINTS_D  # noqa: F401
from app.botengine.dynamic_v2.math_engine import spread

D = Decimal


class TestMathEngineSpread:
    def test_oran_ve_bps_birlikte_doner(self):
        mid, oran, bps = spread(D("100"), D("100.05"))
        assert mid == D("100.025")
        # %0.05 spread → oran ~0.0005, bps ~5
        assert oran < D("0.001")
        assert D("4.9") < bps < D("5.1")
        assert bps == oran * D("10000")

    def test_oran_yuzde_degil(self):
        """Ham spread ORAN'dır: %1 spread 0.01 döner, 1 değil."""
        _, oran, _ = spread(D("100"), D("101"))
        assert D("0.009") < oran < D("0.011")

    @pytest.mark.parametrize(
        "bid,ask",
        [(D("0"), D("1")), (D("-1"), D("1")), (D("100"), D("100")), (D("100"), D("99"))],
    )
    def test_gecersiz_kotasyon_reddedilir(self, bid, ask):
        with pytest.raises(ValueError):
            spread(bid, ask)


class TestKisitKatmaniYuzdePuaniBekler:
    """``absolute_min_gap`` ve ``min_distance`` yüzde puanı ölçeğinde."""

    def test_config_sabitleri_yuzde_puani_olceginde(self):
        cfg = DynamicV2Config()
        # 0.05 = %0.05, 50 = %50. Oran ölçeğinde 50 anlamsız olurdu (%5000).
        assert cfg.absolute_min_gap == D("0.05")
        assert cfg.min_distance == D("0.05")
        assert cfg.max_grid_distance == D("50")
        assert cfg.max_buy_trailing == D("5")

    def test_spread_gap_factor_yuzde_puaniyla_anlamli(self):
        """%0.05 spread × 3 = %0.15 gap; oran verilse %0.0015 olurdu."""
        cfg = DynamicV2Config()
        _, oran, _ = spread(D("100"), D("100.05"))
        yuzde_puani = oran * D("100")
        gap = max(cfg.absolute_min_gap, yuzde_puani * cfg.spread_gap_factor)
        assert gap > cfg.absolute_min_gap
        assert D("0.1") < gap < D("0.2")

        hatali_gap = max(cfg.absolute_min_gap, oran * cfg.spread_gap_factor)
        # Oran verilirse spread tamamen yutulur: taban gap'e düşer.
        assert hatali_gap == cfg.absolute_min_gap


class TestServiceCevrimYapiyor:
    def test_service_yuzde_puanina_ceviriyor(self):
        from pathlib import Path

        src = Path("app/botengine/dynamic_v2/service.py").read_text(encoding="utf-8")
        assert 'spread_percentage_points = data.raw_spread_pct * D("100")' in src
        assert 'atr_percentage_points = feature_snapshot.atr_pct * D("100")' in src
        assert "spread_pct=spread_percentage_points" in src
        assert "atr_pct=atr_percentage_points" in src

    def test_birim_sozlesmesi_belgelenmis(self):
        """Sözleşme kodda yazılı olmalı; sonraki okuyucu yanlış bağlamasın."""
        from pathlib import Path

        constraints = Path("app/botengine/dynamic_v2/constraints.py").read_text(
            encoding="utf-8"
        )
        assert "BİRİM SÖZLEŞMESİ" in constraints
        collector = Path("app/botengine/dynamic_v2/collector.py").read_text(
            encoding="utf-8"
        )
        assert "0..1 normalize" in collector
