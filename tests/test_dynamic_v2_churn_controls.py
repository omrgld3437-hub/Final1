"""
FILE: test_dynamic_v2_churn_controls.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Churn (saatlik değişim) limitlerinin gerçekten uygulandığını kilitler.

Neden: ``ParameterConstraintProjector.project()`` tek üretim çağrısında
``current`` argümanı hiç geçirilmiyordu. Sonuç: config'te tanımlı bütün
``hourly_*_change`` limitleri ve deadband'ler ölüydü; her saatlik tam analiz
grid tetiklerini, ağırlıkları ve trailing'i sınırsız oynatabiliyordu. Canlı bir
grid botunda bu, emirlerin her saat iptal edilip çok farklı seviyelere yeniden
konması demektir.

Ek olarak churn kontrolü içindeki ``zip()`` kullanımı, önceki tur daha az grid
içerdiğinde aday grid listesini sessizce kırpıyordu.
"""

from decimal import Decimal

import pytest

from app.botengine.dynamic_v2.config import DynamicV2Config
from app.botengine.dynamic_v2.constraints import (
    ParameterConstraintProjector,
    _limit_series,
)
from app.botengine.dynamic_v2.models import DynamicParameterCandidate
from app.botengine.dynamic_v2.service import DynamicModeV2

D = Decimal


def _candidate(
    *,
    base=D("0.5"),
    buy_triggers=None,
    sell_triggers=None,
    buy_weights=None,
    sell_weights=None,
    buy_trailing=D("1"),
    sell_trailing=D("1"),
    profit_buy_trigger=D("2"),
    profit_sell_trigger=D("2"),
    profit_buy_trailing=D("1"),
    profit_sell_trailing=D("1"),
) -> DynamicParameterCandidate:
    buy_triggers = buy_triggers or [D("1"), D("2"), D("3")]
    sell_triggers = sell_triggers or [D("1"), D("2"), D("3")]
    n_buy, n_sell = len(buy_triggers), len(sell_triggers)
    return DynamicParameterCandidate(
        target_base_ratio=base,
        target_quote_ratio=D("1") - base,
        buy_grid_trigger_percentages=list(buy_triggers),
        sell_grid_trigger_percentages=list(sell_triggers),
        buy_grid_amount_weights=buy_weights
        or [D("1") / D(n_buy) for _ in range(n_buy)],
        sell_grid_amount_weights=sell_weights
        or [D("1") / D(n_sell) for _ in range(n_sell)],
        buy_grid_amounts=[D("100") for _ in range(n_buy)],
        sell_grid_amounts=[D("1") for _ in range(n_sell)],
        buy_grid_trailing_percentage=buy_trailing,
        sell_grid_trailing_percentage=sell_trailing,
        profit_buy_trigger_percentage=profit_buy_trigger,
        profit_sell_trigger_percentage=profit_sell_trigger,
        profit_buy_trailing_percentage=profit_buy_trailing,
        profit_sell_trailing_percentage=profit_sell_trailing,
        confidence=D("0.9"),
    )


class TestLimitSeriesUzunlukGuvenli:
    def test_yeni_liste_uzunlugu_korunur(self):
        """Asıl regresyon: zip kullanımı listeyi kısaltıp grid kaybettiriyordu."""
        old = [D("1"), D("2")]
        new = [D("1"), D("2"), D("3"), D("4")]
        out = _limit_series(old, new, deadband=D("0"), maximum_change=D("0.10"))
        assert len(out) == 4

    def test_esi_olmayan_elemanlar_dokunulmaz(self):
        old = [D("1")]
        new = [D("1"), D("9")]
        out = _limit_series(old, new, deadband=D("0"), maximum_change=D("0.10"))
        assert out[1] == D("9")

    def test_onceki_daha_uzunsa_fazlalik_yayilmaz(self):
        old = [D("1"), D("2"), D("3")]
        new = [D("1"), D("2")]
        out = _limit_series(old, new, deadband=D("0"), maximum_change=D("0.10"))
        assert len(out) == 2

    def test_degisim_limiti_uygulanir(self):
        out = _limit_series(
            [D("10")], [D("100")], deadband=D("0"), maximum_change=D("0.15")
        )
        # %15 üst sınır: 10 → en fazla 11.5
        assert out[0] <= D("11.5")
        assert out[0] > D("10")

    def test_bos_listeler_patlamaz(self):
        assert _limit_series([], [], deadband=D("0"), maximum_change=D("0.1")) == []


class TestChurnProjectionSirasi:
    """Churn sert kısıtlardan ÖNCE çalışmalı; aksi halde invaryant bozulur."""

    def _project(self, candidate, current):
        cfg = DynamicV2Config()
        projector = ParameterConstraintProjector(cfg)
        return projector.project(
            candidate,
            reference=None,
            spread_pct=D("0.05"),
            atr_pct=D("1"),
            exchange_tick_gap_pct=D("0.001"),
            current=current,
        )

    def test_gridler_artan_sirada_kalir(self):
        current = _candidate(buy_triggers=[D("1"), D("2"), D("3")])
        candidate = _candidate(buy_triggers=[D("9"), D("1"), D("5")])
        out = self._project(candidate, current)
        triggers = out.buy_grid_trigger_percentages
        assert triggers == sorted(triggers), triggers

    def test_trailing_tetigin_altinda_kalir(self):
        current = _candidate()
        candidate = _candidate(buy_trailing=D("99"))
        out = self._project(candidate, current)
        assert out.buy_grid_trailing_percentage < min(
            out.buy_grid_trigger_percentages
        )

    def test_agirliklar_normalize_kalir(self):
        current = _candidate()
        candidate = _candidate(
            buy_weights=[D("0.9"), D("0.05"), D("0.05")]
        )
        out = self._project(candidate, current)
        assert abs(sum(out.buy_grid_amount_weights) - D("1")) < D("0.0001")

    def test_grid_sayisi_artinca_kayip_olmaz(self):
        current = _candidate(buy_triggers=[D("1"), D("2")])
        candidate = _candidate(buy_triggers=[D("1"), D("2"), D("3"), D("4")])
        out = self._project(candidate, current)
        assert len(out.buy_grid_trigger_percentages) == 4

    def test_current_yoksa_churn_atlanir(self):
        candidate = _candidate(buy_trailing=D("1"))
        out = self._project(candidate, None)
        assert out.buy_grid_trigger_percentages


class TestBaseRatioChurn:
    def test_base_ratio_saatlik_limitle_kisilir(self):
        cfg = DynamicV2Config()
        projector = ParameterConstraintProjector(cfg)
        current = _candidate(base=D("0.5"))
        candidate = _candidate(base=D("0.95"))
        projector.project(
            candidate,
            reference=None,
            spread_pct=D("0.05"),
            atr_pct=D("1"),
            exchange_tick_gap_pct=D("0.001"),
            current=current,
        )
        # hourly_base_change = 0.05 → 0.5'ten en fazla 0.55'e çıkabilir
        assert candidate.target_base_ratio <= D("0.55")
        assert candidate.target_quote_ratio == D("1") - candidate.target_base_ratio

    def test_deadband_altinda_degisim_yok_sayilir(self):
        cfg = DynamicV2Config()
        projector = ParameterConstraintProjector(cfg)
        current = _candidate(base=D("0.50"))
        candidate = _candidate(base=D("0.505"))  # base_deadband = 0.01
        projector.project(
            candidate,
            reference=None,
            spread_pct=D("0.05"),
            atr_pct=D("1"),
            exchange_tick_gap_pct=D("0.001"),
            current=current,
        )
        assert candidate.target_base_ratio == D("0.50")


class TestOncekiAdayGeriOkuma:
    def test_bos_state_none_doner(self):
        assert DynamicModeV2().previous_applied_candidate({}) is None

    def test_uygulanmis_aday_okunur(self):
        engine = DynamicModeV2()
        state = {
            "_dynamic_v2_last_applied_candidate": _candidate().to_dict()
        }
        out = engine.previous_applied_candidate(state)
        assert out is not None
        assert out.target_base_ratio == D("0.5")
        assert len(out.buy_grid_trigger_percentages) == 3

    def test_shadow_karari_referans_olmaz(self):
        """Gölge adaya göre kırpmak, olmayan bir geçmişe göre yumuşatmaktır."""
        engine = DynamicModeV2()
        state = {
            "dynamic_v2_snapshot": {
                "decision": "SHADOW",
                "candidate": _candidate().to_dict(),
            }
        }
        assert engine.previous_applied_candidate(state) is None

    def test_geriye_donuk_applied_snapshot_okunur(self):
        engine = DynamicModeV2()
        state = {
            "dynamic_v2_snapshot": {
                "decision": "APPLIED",
                "candidate": _candidate().to_dict(),
            }
        }
        assert engine.previous_applied_candidate(state) is not None

    @pytest.mark.parametrize(
        "bozuk",
        [
            {},
            {"target_base_ratio": None},
            {"target_base_ratio": "0.5"},  # diğer skalerler eksik
        ],
    )
    def test_eksik_alan_none_doner(self, bozuk):
        engine = DynamicModeV2()
        state = {"_dynamic_v2_last_applied_candidate": bozuk}
        assert engine.previous_applied_candidate(state) is None

    def test_bozuk_deger_patlamaz(self):
        engine = DynamicModeV2()
        raw = _candidate().to_dict()
        raw["target_base_ratio"] = "abc"
        state = {"_dynamic_v2_last_applied_candidate": raw}
        assert engine.previous_applied_candidate(state) is None

    def test_env_ile_kapatilabilir(self, monkeypatch):
        engine = DynamicModeV2()
        state = {"_dynamic_v2_last_applied_candidate": _candidate().to_dict()}
        assert engine.previous_applied_candidate(state) is not None
        monkeypatch.setenv("DYNAMIC_V2_CHURN_CONTROLS", "0")
        assert engine.previous_applied_candidate(state) is None


class TestKoordinatorReferansiYazar:
    def test_apply_son_adayi_kaydeder(self):
        from pathlib import Path

        src = Path("app/botengine/dynamic_v2/grid_update.py").read_text(
            encoding="utf-8"
        )
        assert 'state["_dynamic_v2_last_applied_candidate"]' in src

    def test_service_current_gecirir(self):
        from pathlib import Path

        src = Path("app/botengine/dynamic_v2/service.py").read_text(encoding="utf-8")
        assert "current=self.previous_applied_candidate(state)" in src
