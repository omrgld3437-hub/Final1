"""
FILE: test_dynamic_v2_kill_switch_recovery.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Dynamic Mode V2 kill switch'inin kalıcı latch olmadığını kilitler.

Neden: kill switch bir kez düştüğünde asla açılmıyordu. Sağlık geri dönse bile
V2 o bot için sessizce kapalı kalıyor, tek çıkış yolu elle DB düzenlemek
oluyordu. Geçici bir ağ hatası kalıcı devre dışı bırakmaya yol açmamalı.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.botengine.dynamic_v2.runtime import (
    KILL_SWITCH_KEY,
    RUNTIME_TRIP_COOLDOWN_SEC,
    kill_switch_active,
    micro_risk_check,
    trip_kill_switch,
)


def _iso(dt):
    return dt.isoformat()


class TestSaglikTemelliLatch:
    def test_saglik_bozulunca_kill_switch_duser(self):
        state = {"last_error_code": "BINANCE_-1021"}
        result = micro_risk_check(state)
        assert result["healthy"] is False
        assert "EXCHANGE_CONNECTION" in result["reasons"]
        assert kill_switch_active(state) is True

    def test_belirsiz_emir_ve_bakiye_sapmasi_da_tetikler(self):
        state = {"_reconciliation_unknown": True, "_balance_drift_detected": True}
        result = micro_risk_check(state)
        assert set(result["reasons"]) == {"ORDER_STATUS_UNCERTAIN", "BALANCE_MISMATCH"}
        assert kill_switch_active(state) is True

    def test_saglik_donunce_latch_acilir(self):
        """Asıl regresyon: eskiden bu latch sonsuza kadar aktif kalıyordu."""
        state = {"last_error_code": "BINANCE_-1021"}
        micro_risk_check(state)
        assert kill_switch_active(state) is True

        state.pop("last_error_code")
        result = micro_risk_check(state)

        assert result["healthy"] is True
        assert kill_switch_active(state) is False
        assert state[KILL_SWITCH_KEY]["active"] is False
        assert state[KILL_SWITCH_KEY]["cleared_at"]

    def test_saglik_kosulu_surdukce_latch_aktif_kalir(self):
        state = {"_balance_drift_detected": True}
        for _ in range(5):
            micro_risk_check(state)
            assert kill_switch_active(state) is True

    def test_saglikli_state_gereksiz_anahtar_yazmaz(self):
        state = {}
        micro_risk_check(state)
        assert (state.get(KILL_SWITCH_KEY) or {}).get("active") is not True


class TestRuntimeIstisnaCooldown:
    def test_runtime_hatasi_once_engeller(self):
        state = {}
        trip_kill_switch(state, ["RUNTIME_EXCEPTION"], detail="boom")
        assert kill_switch_active(state) is True
        assert state[KILL_SWITCH_KEY]["detail"] == "boom"

    def test_cooldown_sonrasi_kendiliginden_acilir(self):
        state = {}
        trip_kill_switch(state, ["RUNTIME_EXCEPTION"])
        state[KILL_SWITCH_KEY]["tripped_at"] = _iso(
            datetime.now(timezone.utc)
            - timedelta(seconds=RUNTIME_TRIP_COOLDOWN_SEC + 60)
        )
        assert kill_switch_active(state) is False

    def test_cooldown_icinde_hala_kapali(self):
        state = {}
        trip_kill_switch(state, ["RUNTIME_EXCEPTION"])
        state[KILL_SWITCH_KEY]["tripped_at"] = _iso(
            datetime.now(timezone.utc)
            - timedelta(seconds=RUNTIME_TRIP_COOLDOWN_SEC // 2)
        )
        assert kill_switch_active(state) is True

    def test_saglik_gerekcesi_cooldown_ile_acilmaz(self):
        """Sağlık kaynaklı latch zamanla değil, koşul düzelince açılır."""
        state = {}
        trip_kill_switch(state, ["BALANCE_MISMATCH"])
        state[KILL_SWITCH_KEY]["tripped_at"] = _iso(
            datetime.now(timezone.utc) - timedelta(days=30)
        )
        assert kill_switch_active(state) is True

    @pytest.mark.parametrize("bozuk", [None, "", "not-a-date", 12345])
    def test_zaman_damgasi_yoksa_veya_bozuksa_kilitli_kalmaz(self, bozuk):
        """Eski kayıtlar (tripped_at'siz) süresiz kilitli kalmamalı."""
        state = {
            KILL_SWITCH_KEY: {
                "active": True,
                "reasons": ["RUNTIME_EXCEPTION"],
                "tripped_at": bozuk,
            }
        }
        assert kill_switch_active(state) is False

    def test_z_sonlu_utc_damgasi_okunur(self):
        state = {
            KILL_SWITCH_KEY: {
                "active": True,
                "reasons": ["RUNTIME_EXCEPTION"],
                "tripped_at": datetime.now(timezone.utc)
                .replace(tzinfo=None)
                .isoformat()
                + "Z",
            }
        }
        assert kill_switch_active(state) is True

    def test_naive_damga_utc_sayilir(self):
        state = {
            KILL_SWITCH_KEY: {
                "active": True,
                "reasons": ["RUNTIME_EXCEPTION"],
                "tripped_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            }
        }
        assert kill_switch_active(state) is True


class TestBosVeBozukState:
    @pytest.mark.parametrize(
        "state",
        [
            {},
            {KILL_SWITCH_KEY: None},
            {KILL_SWITCH_KEY: {}},
            {KILL_SWITCH_KEY: {"active": False}},
        ],
    )
    def test_aktif_olmayan_latch_engellemez(self, state):
        assert kill_switch_active(state) is False

    def test_gerekce_listesi_yoksa_engeller(self):
        """Gerekçesi bilinmeyen aktif latch güvenli tarafta kalır."""
        assert kill_switch_active({KILL_SWITCH_KEY: {"active": True}}) is True


class TestOrchestratorEntegrasyonu:
    def test_orchestrator_yardimcilari_kullaniyor(self):
        """Ham dict kontrolüne geri dönülmesin (cooldown'ı baypas eder)."""
        from pathlib import Path

        src = Path("app/botengine/orchestrator.py").read_text(encoding="utf-8")
        assert "_dyn_v2_kill_active(state)" in src
        assert "_dyn_v2_trip(" in src
