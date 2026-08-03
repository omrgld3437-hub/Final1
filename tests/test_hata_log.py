"""
FILE: test_hata_log.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Kök klasördeki HATALAR.log sözleşmesi — tüm hatalar, tekrar bastırma, 90 gün.

Kritik gereksinim: hiçbir hata kaybolmayacak ama saniyede yüzlerce tekrarlayan bir
hata ne dosyayı şişirecek ne de sunucuyu yoracak.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from app.observability import hata_log


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Modülü geçici bir dosyaya yönlendir ve dedupe durumunu sıfırla."""
    path = tmp_path / "HATALAR.log"
    monkeypatch.setattr(hata_log, "HATA_LOG_PATH", path)
    monkeypatch.setattr(hata_log, "_last_prune_at", 0.0)
    hata_log._seen.clear()
    return path


def _body(path):
    if not path.exists():
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def test_error_is_written_with_header(log_file):
    hata_log.kaydet("error", "test", "bir şey patladı")
    content = log_file.read_text(encoding="utf-8")
    assert content.startswith("# HATALAR.log")
    lines = _body(log_file)
    assert len(lines) == 1
    assert "bir şey patladı" in lines[0]
    assert "ERROR" in lines[0]


def test_identical_error_written_once_in_window(log_file):
    """Aynı hata 500 kez gelse pencerede tek satır yazılır (şişme koruması)."""
    for _ in range(500):
        hata_log.kaydet("error", "test", "aynı hata tekrar ediyor")
    assert len(_body(log_file)) == 1


def test_repeat_count_reported_after_window(log_file, monkeypatch):
    """Pencere kapanınca bastırılan tekrar sayısı bildirilir; hata gizlenmez."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(hata_log.time, "monotonic", lambda: clock["t"])

    for _ in range(50):
        hata_log.kaydet("error", "test", "tekrarlayan hata")
    assert len(_body(log_file)) == 1

    clock["t"] += hata_log.DEDUPE_WINDOW_SEC + 1
    hata_log.kaydet("error", "test", "tekrarlayan hata")

    lines = _body(log_file)
    assert len(lines) == 2
    assert "tekrar=50" in lines[1]


def test_distinct_errors_are_all_written(log_file):
    """Farklı hatalar bastırılmaz — 'istisnasız hepsi yazılsın' gereksinimi."""
    for i in range(20):
        hata_log.kaydet("error", "test", f"farklı hata {i}")
    assert len(_body(log_file)) == 20


def test_volatile_ids_do_not_defeat_dedupe(log_file):
    """Sadece istek id'si değişen aynı hata tek parmak izi sayılır."""
    for i in range(30):
        hata_log.kaydet(
            "error", "test", f"Binance isteği başarısız request_id=9f2b1c4d5e6f7a8b9c0d1e2f{i:04d}"
        )
    assert len(_body(log_file)) == 1


def test_bot_ids_remain_distinct(log_file):
    """Farklı botun aynı hatası ayrı ayrı görünür; aşırı normalize etmiyoruz."""
    hata_log.kaydet("error", "test", "grid hatası bot_id=7")
    hata_log.kaydet("error", "test", "grid hatası bot_id=8")
    assert len(_body(log_file)) == 2


def test_multiline_detail_stays_on_one_line(log_file):
    """Traceback dosyayı bozmaz; tek satırda kalır."""
    hata_log.kaydet(
        "error", "test", "istisna", detail="Traceback:\n  satır 1\n  satır 2"
    )
    assert len(_body(log_file)) == 1


def test_prune_drops_entries_older_than_retention(log_file):
    old_day = (datetime.now() - timedelta(days=hata_log.RETENTION_DAYS + 5)).strftime(
        "%Y-%m-%d"
    )
    new_day = datetime.now().strftime("%Y-%m-%d")
    log_file.write_text(
        hata_log._HEADER.format(days=hata_log.RETENTION_DAYS)
        + f"{old_day} 10:00:00 | ERROR    | eski | çok eski hata\n"
        + f"{new_day} 10:00:00 | ERROR    | yeni | güncel hata\n",
        encoding="utf-8",
    )
    hata_log.prune(force=True)

    lines = _body(log_file)
    assert len(lines) == 1
    assert "güncel hata" in lines[0]


def test_fingerprint_table_is_bounded(log_file):
    """Parmak izi tablosu sınırsız büyüyüp RAM tüketmez."""
    for i in range(hata_log.MAX_FINGERPRINTS + 500):
        hata_log.kaydet("error", "test", f"eşsiz hata {i} {'x' * (i % 7)}")
    assert len(hata_log._seen) <= hata_log.MAX_FINGERPRINTS


def test_handler_captures_logger_errors(log_file):
    """logger.error/exception çağrıları dosyaya düşer (tüm hatalar yakalanır)."""
    handler = hata_log.HataLogHandler()
    test_logger = logging.getLogger("test.hata.capture")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.DEBUG)
    try:
        test_logger.error("logger üzerinden hata")
        test_logger.info("bu bilgi satırı yazılmamalı")
        try:
            raise ValueError("beklenen istisna")
        except ValueError:
            test_logger.exception("istisna yakalandı")
    finally:
        test_logger.removeHandler(handler)

    lines = _body(log_file)
    assert any("logger üzerinden hata" in line for line in lines)
    assert any("istisna yakalandı" in line for line in lines)
    assert not any("bu bilgi satırı" in line for line in lines)
    assert any("ValueError" in line for line in lines)


def test_logging_never_raises(log_file, monkeypatch):
    """Dosya yazılamasa bile uygulama akışı kesilmez."""
    monkeypatch.setattr(hata_log, "HATA_LOG_PATH", tmp_unwritable := log_file.parent / "yok" / "HATALAR.log")
    assert not tmp_unwritable.parent.exists()
    hata_log.kaydet("error", "test", "dosya yazılamaz")


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(hata_log, "_installed", False)
    root = logging.getLogger()
    before = len(root.handlers)
    hata_log.install()
    hata_log.install()
    added = len(root.handlers) - before
    assert added == 1
    for h in list(root.handlers):
        if isinstance(h, hata_log.HataLogHandler):
            root.removeHandler(h)
