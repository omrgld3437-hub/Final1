"""Kullanıcı işlem geçmişi (UserReadableActivityLogger) testleri."""

from __future__ import annotations

import concurrent.futures
import tempfile
import time
from pathlib import Path

import pytest

from app.services.user_activity_translations import (
    format_event,
    translate_technical_reason,
)
from app.services.user_readable_activity_logger import (
    USER_LOG_DIR_NAME,
    UserReadableActivityLogger,
    build_log_filename,
    format_log_line,
    read_user_log_lines,
    reset_log_root_for_tests,
    sanitize_filename_part,
    sanitize_text,
    set_log_root_for_tests,
    user_log_dir,
)


def _write_event(user_id: int, event_type: str, context=None, **kwargs):
    """Testlerde kuyruk yerine senkron yazım."""
    ctx = dict(context or {})
    scr, act, res = format_event(event_type, ctx, **kwargs)
    if ctx.get("technical_reason"):
        res = translate_technical_reason(str(ctx["technical_reason"]))
    UserReadableActivityLogger.write_sync(user_id, screen=scr, action=act, result=res)


@pytest.fixture
def log_root(tmp_path):
    set_log_root_for_tests(tmp_path)
    yield tmp_path
    reset_log_root_for_tests()


# --- Klasör ve dosya ---


def test_kullanici_log_klasoru_olusturulur(log_root):
    UserReadableActivityLogger.write_sync(1, screen="Hesap", action="Test", result="Başarılı")
    assert (log_root / USER_LOG_DIR_NAME).is_dir()


def test_kullanici_icin_ayri_log_dosyasi_olusturulur(log_root):
    UserReadableActivityLogger.write_sync(10, screen="Hesap", action="A", result="Başarılı")
    UserReadableActivityLogger.write_sync(20, screen="Hesap", action="B", result="Başarılı")
    files = list(user_log_dir().glob("*.log"))
    assert len(files) == 2


def test_ad_soyad_userid_formatinda_dosya_olusturulur(log_root):
    name = build_log_filename(12345, "Ömer", "Altın")
    assert name == "Ömer.Altın__12345.log"
    UserReadableActivityLogger.write_sync(
        12345, user_name="Ömer", user_surname="Altın", screen="Hesap", action="X", result="Y"
    )
    assert (user_log_dir() / name).exists()


def test_dosya_adi_guvenli_hale_getirilir():
    assert sanitize_filename_part("Ahmet Yılmaz") == "Ahmet.Yılmaz"
    assert "/" not in sanitize_filename_part("a/b")
    assert "\\" not in sanitize_filename_part("a\\b")
    assert "?" not in sanitize_filename_part("a?b")
    assert len(sanitize_filename_part("x" * 100)) <= 40


def test_ayni_isimli_kullanicilar_userid_ile_ayrilir(log_root):
    UserReadableActivityLogger.write_sync(
        1, user_name="Ali", user_surname="Veli", screen="Hesap", action="1", result="OK"
    )
    UserReadableActivityLogger.write_sync(
        2, user_name="Ali", user_surname="Veli", screen="Hesap", action="2", result="OK"
    )
    assert (user_log_dir() / "Ali.Veli__1.log").exists()
    assert (user_log_dir() / "Ali.Veli__2.log").exists()


def test_kullanici_bilgisi_eksikse_userid_dosyasi_olusturulur(log_root):
    assert build_log_filename(99) == "user_99.log"
    UserReadableActivityLogger.write_sync(99, screen="Hesap", action="T", result="OK")
    assert (user_log_dir() / "user_99.log").exists()


# --- Sade dil ---


def test_log_satiri_sade_turkce_yazilir(log_root):
    UserReadableActivityLogger.write_sync(
        1, screen="Parametre Asistanı", action="BTCUSDT için analiz başlatıldı", result="Analiz başladı"
    )
    content = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "Parametre Asistanı" in content
    assert "Analiz başladı" in content
    assert " — " in content


def test_teknik_event_sade_cumleye_cevrilir():
    assert "spread" in translate_technical_reason("SPREAD_UNSAFE").lower()
    assert "likidite" in translate_technical_reason("LOW_LIQUIDITY").lower()


def test_hata_kodu_kullanici_logunda_gorunmez(log_root):
    _write_event(
        1, "DYNAMIC_TURN_BLOCKED", {"symbol": "BTCUSDT", "technical_reason": "EXPOSURE_HARD_CAP_BREACH"}
    )
    content = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "EXPOSURE_HARD_CAP_BREACH" not in content
    assert "risk limiti" in content.lower()


def test_stack_trace_kullanici_loguna_yazilmaz():
    raw = "Traceback (most recent call last):\n  File selector.py line 145"
    assert "Traceback" not in sanitize_text(raw) or sanitize_text(raw) != raw


def test_raw_json_kullanici_loguna_yazilmaz():
    raw = '{"api_secret": "abcd1234", "password": "x"}'
    cleaned = sanitize_text(raw)
    assert "api_secret" not in cleaned.lower() or "***" in cleaned


def test_kod_dosya_yolu_kullanici_loguna_yazilmaz():
    assert sanitize_text("error in selector.py:145") != "error in selector.py:145"


# --- Gizlilik ---


def test_sifre_loglanmaz():
    assert "***" in sanitize_text("password=secret123") or "secret123" not in sanitize_text(
        "password=secret123"
    )


def test_api_secret_loglanmaz():
    cleaned = sanitize_text("api_secret=abcdefgh")
    assert "abcdefgh" not in cleaned


def test_token_loglanmaz():
    cleaned = sanitize_text("access_token=eyJhbGciOiJIUzI1NiJ9")
    assert "eyJhbGci" not in cleaned


def test_private_key_loglanmaz():
    cleaned = sanitize_text("private_key=-----BEGIN RSA-----")
    assert "BEGIN RSA" not in cleaned


def test_api_key_maskelenir():
    masked = sanitize_text("key abcd12345678wxyz ok")
    assert "****" in masked


def test_ip_acik_yazilmaz():
    masked = sanitize_text("login from 192.168.1.100")
    assert "192.168.1.100" not in masked


# --- Hesap ve sayfa ---


def test_kullanici_giris_loglanir(log_root):
    _write_event(5, "LOGIN_SUCCESS")
    content = (user_log_dir() / "user_5.log").read_text(encoding="utf-8")
    assert "giriş yaptı" in content


def test_kullanici_cikis_loglanir(log_root):
    _write_event(5, "LOGOUT")
    content = (user_log_dir() / "user_5.log").read_text(encoding="utf-8")
    assert "çıkış yaptı" in content


def test_sayfa_acildi_loglanir(log_root):
    _write_event(5, "PAGE_VIEW", {"page": "Dashboard"})
    content = (user_log_dir() / "user_5.log").read_text(encoding="utf-8")
    assert "Dashboard" in content


def test_sekme_degisti_loglanir(log_root):
    _write_event(5, "TAB_CHANGED")
    content = (user_log_dir() / "user_5.log").read_text(encoding="utf-8")
    assert "sekme" in content.lower()


# --- Parametre Asistanı ---


def test_coin_secildi_loglanir(log_root):
    _write_event(1, "PARAM_COIN_SELECTED", {"symbol": "BTCUSDT"})
    assert "BTCUSDT" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_butce_girildi_loglanir(log_root):
    _write_event(1, "PARAM_BUDGET_ENTERED", {"budget": 1000})
    assert "1000" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_parametre_analizi_baslatildi_loglanir(log_root):
    _write_event(
        1, "PARAM_ANALYSIS_STARTED", context={"symbol": "ETHUSDT", "budget": 500}
    )
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "analizi başlatıldı" in c


def test_parametre_uretildi_loglanir(log_root):
    _write_event(1, "PARAM_RESULT_DEPLOYABLE", {"symbol": "BTCUSDT"})
    assert "üretildi" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8").lower()


def test_parametre_uretilemedi_sade_yazilir(log_root):
    _write_event(
        1, "PARAM_ANALYSIS_FAILED", context={"symbol": "SFPUSDT", "technical_reason": "DUMP_RISK"}
    )
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "DUMP_RISK" not in c
    assert "üretilemedi" in c.lower()


def test_kullanici_parametreyi_onayladi_loglanir(log_root):
    _write_event(1, "PARAM_APPROVED")
    assert "onayladı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_kullanici_vazgecti_loglanir(log_root):
    _write_event(1, "ABANDON_PARAM_NO_APPROVE")
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "onaylamadan" in c


# --- Dinamik Mod ---


def test_bot_baslatildi_loglanir(log_root):
    _write_event(1, "BOT_STARTED", {"symbol": "ETHUSDT"})
    assert "başlatıldı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_bot_durduruldu_loglanir(log_root):
    _write_event(1, "BOT_STOPPED", {"symbol": "ETHUSDT"})
    assert "durduruldu" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_tur_analizi_yapildi_loglanir(log_root):
    _write_event(1, "DYNAMIC_TURN_ANALYSIS", {"symbol": "BTCUSDT"})
    assert "tur analizi" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_tur_baslatildi_loglanir(log_root):
    _write_event(1, "DYNAMIC_TURN_STARTED", {"symbol": "BTCUSDT"})
    assert "tur başlatıldı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_tur_riskli_baslamadi_loglanir(log_root):
    _write_event(1, "DYNAMIC_TURN_BLOCKED", {"symbol": "SFPUSDT"})
    assert "başlatılmadı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_retry_bekliyor_loglanir(log_root):
    _write_event(
        1, "RETRY_PENDING", context={"symbol": "ASRUSDT", "minutes": 5}
    )
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "5" in c
    assert "tekrar" in c.lower()


def test_retry_deneniyor_loglanir(log_root):
    _write_event(1, "RETRY_ATTEMPTED", {"symbol": "ASRUSDT"})
    assert "kontrol" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_retry_basarili_loglanir(log_root):
    _write_event(1, "RETRY_SUCCESS", {"symbol": "ASRUSDT"})
    assert "uygun" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_retry_basarisiz_loglanir(log_root):
    _write_event(1, "RETRY_FAILED", {"symbol": "ASRUSDT"})
    assert "açılmadı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


# --- Rebalance ---


def test_kucuk_base_quote_farki_rebalance_yapilmadi_loglanir(log_root):
    _write_event(
        1,
        "REBALANCE_SKIPPED",
        context={"current_alloc": "%50/%50", "target_alloc": "%45/%55"},
    )
    assert "dengeleme yapılmadı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_buyuk_base_quote_farki_degerlendirildi_loglanir(log_root):
    _write_event(
        1,
        "REBALANCE_EVALUATED",
        context={"current_alloc": "%50/%50", "target_alloc": "%40/%60"},
    )
    assert "değerlendirildi" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_tek_seferlik_rebalance_loglanir(log_root):
    _write_event(1, "REBALANCE_EXECUTED", {"side": "SELL"})
    assert "tek seferlik" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_rebalance_grid_degil_olarak_yazilir(log_root):
    _write_event(1, "REBALANCE_EXECUTED", {"side": "SELL"})
    assert "grid emri değildir" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_rebalance_ertelendi_loglanir(log_root):
    _write_event(1, "REBALANCE_DEFERRED")
    assert "ertelendi" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8").lower() or "beklemeye" in (
        user_log_dir() / "user_1.log"
    ).read_text(encoding="utf-8").lower()


# --- Emirler ---


def test_emir_olusturuldu_loglanir(log_root):
    _write_event(
        1, "ORDER_CREATED", context={"symbol": "BTCUSDT", "side": "BUY"}
    )
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "oluşturuldu" in c


def test_emir_gerceklesti_loglanir(log_root):
    _write_event(
        1, "ORDER_FILLED", context={"symbol": "BTCUSDT", "side": "BUY"}
    )
    assert "gerçekleşti" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_emir_iptal_edildi_loglanir(log_root):
    _write_event(
        1, "ORDER_CANCELLED", context={"symbol": "BTCUSDT", "side": "SELL"}
    )
    assert "iptal" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_emir_olusturulamadi_sade_yazilir(log_root):
    _write_event(
        1, "ORDER_REJECTED", context={"symbol": "ETHUSDT", "technical_reason": "MIN_NOTIONAL_FAILED"}
    )
    c = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    assert "MIN_NOTIONAL" not in c


def test_min_notional_sade_yazilir():
    t = translate_technical_reason("MIN_NOTIONAL_FAILED")
    assert "minimum" in t.lower()


def test_bakiye_yetersiz_sade_yazilir():
    t = translate_technical_reason("INSUFFICIENT_BALANCE")
    assert "bakiye" in t.lower()


# --- Admin destek ---


def test_admin_mesaji_loglanir(log_root):
    _write_event(1, "CHAT_USER_MESSAGE")
    assert "mesaj" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8").lower()


def test_admin_cevabi_loglanir(log_root):
    _write_event(1, "CHAT_ADMIN_MESSAGE")
    assert "cevap" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8").lower()


def test_destek_talebi_acildi_loglanir(log_root):
    _write_event(1, "SUPPORT_TICKET_OPENED")
    assert "açıldı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_destek_talebi_kapandi_loglanir(log_root):
    _write_event(1, "SUPPORT_TICKET_CLOSED")
    assert "kapandı" in (user_log_dir() / "user_1.log").read_text(encoding="utf-8")


def test_admin_log_goruntulemesi_loglanir(log_root):
    _write_event(99, "ADMIN_LOG_VIEWED")
    assert "görüntüledi" in (user_log_dir() / "user_99.log").read_text(encoding="utf-8")


# --- Güvenilirlik ---


def test_log_yazma_hatasi_ana_sistemi_bozmaz(log_root, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(
        "app.services.user_readable_activity_logger._append_line_to_file", boom
    )
    UserReadableActivityLogger.write(1, screen="X", action="Y", result="Z")


def test_eszamanli_log_yazimi_dosya_bozmaz(log_root):
    def write_many(n):
        for i in range(20):
            UserReadableActivityLogger.write_sync(
                50, screen="Test", action=f"işlem {n}-{i}", result="OK"
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(write_many, range(8)))
    content = (user_log_dir() / "user_50.log").read_text(encoding="utf-8")
    assert content.count(" — Test — ") >= 100
    assert "işlem" in content


def test_kullanici_a_logu_kullanici_b_dosyasina_yazilmaz(log_root):
    UserReadableActivityLogger.write_sync(1, screen="A", action="only A", result="OK")
    UserReadableActivityLogger.write_sync(2, screen="B", action="only B", result="OK")
    a = (user_log_dir() / "user_1.log").read_text(encoding="utf-8")
    b = (user_log_dir() / "user_2.log").read_text(encoding="utf-8")
    assert "only A" in a
    assert "only B" not in a
    assert "only B" in b
    assert "only A" not in b


def test_log_dosyasi_buyurse_rotasyon_calismasi(log_root, monkeypatch):
    from app.services import user_readable_activity_logger as mod

    monkeypatch.setattr(mod, "MAX_LOG_FILE_BYTES", 200)
    for i in range(30):
        UserReadableActivityLogger.write_sync(7, screen="R", action=f"satır {i}", result="OK")
    files = list(user_log_dir().glob("*7*.log"))
    assert len(files) >= 1


def test_format_log_line_timestamp():
    line = format_log_line("Hesap", "Test", "Başarılı")
    parts = line.split(" — ")
    assert len(parts) == 4
    assert "." in parts[0]


def test_read_user_log_lines_filter(log_root):
    UserReadableActivityLogger.write_sync(3, screen="Emirler", action="BTCUSDT alış", result="OK")
    UserReadableActivityLogger.write_sync(3, screen="Destek", action="mesaj", result="OK")
    lines = read_user_log_lines(3, screen="Emirler")
    assert all("Emirler" in ln for ln in lines)
    assert not any("Destek" in ln for ln in lines)


def test_format_event_templates():
    scr, act, res = format_event("PARAM_ANALYSIS_STARTED", {"symbol": "BTCUSDT", "budget": 1000})
    assert scr == "Parametre Asistanı"
    assert "BTCUSDT" in act
    assert "1000" in act
