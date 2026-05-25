# -*- coding: utf-8 -*-
"""Reason Engine: servis durumuna göre kök neden teşhisi (Türkçe)."""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

_TR_TZ = ZoneInfo("Europe/Istanbul")

# Servis portları (teşhis için)
_SERVICE_PORTS = {"web": 8000, "engine": None, "manager": 7999}

# Pattern kuralları: (reason_code, re_pattern, confidence)
_RULES = [
    ("PORT_IN_USE", re.compile(r"Address already in use|EADDRINUSE|bind\s*\(\s*\)\s*failed|port.*in use", re.I), 0.95),
    ("MISSING_ENV", re.compile(r"KeyError:.*|Missing required environment variable|ValidationError", re.I), 0.9),
    ("CONFIG_ERROR", re.compile(r"ValidationError|config.*error|\.env.*not found", re.I), 0.85),
    ("MODULE_NOT_FOUND", re.compile(r"ModuleNotFoundError|ImportError.*No module", re.I), 0.95),
    ("IMPORT_ERROR", re.compile(r"ImportError", re.I), 0.85),
    ("PERMISSION", re.compile(r"Permission denied|PermissionError|EACCES|access denied", re.I), 0.9),
    ("DB_DOWN", re.compile(r"Connection refused|timeout|Name or service not known|could not connect|connection.*refused", re.I), 0.85),
    ("NETWORK", re.compile(r"Connection refused|timeout|Name or service not known", re.I), 0.8),
    ("OOM", re.compile(r"Killed|OOM|out of memory|MemoryError|exit.*137", re.I), 0.9),
]

# reason_code -> Türkçe metinler (title, summary, impact, actions, next_checks)
_TR = {
    "PORT_IN_USE": {
        "title_tr": "Port kullanımda",
        "summary_tr": "Servis hedef porta bağlanamadı; port başka bir süreç tarafından kullanılıyor.",
        "impact_tr": "Servis başlamıyor; ilgili özellikler çalışmaz.",
        "actions_tr": [
            "Portu kullanan süreci tespit et (Windows: netstat -ano | findstr :{port}; macOS/Linux: lsof -i :{port})",
            "Gerekirse o süreci durdur veya servis portunu değiştir",
            "Sonra yeniden başlat",
        ],
        "next_checks_tr": [
            "Aynı portta başka uygulama çalışıyor mu kontrol et",
            "Firewall/antivirus portu blokluyor mu bak",
        ],
    },
    "MISSING_ENV": {
        "title_tr": "Eksik ayar (ENV/Config)",
        "summary_tr": "Servis gerekli ortam değişkeni veya ayarı bulamadığı için başlatılamadı.",
        "impact_tr": "Servis ayağa kalkmaz.",
        "actions_tr": [
            "Eksik env değişkenlerini .env veya start script içinde tanımla",
            "Son log satırlarındaki eksik alan adlarını düzelt",
            "Tekrar başlat",
        ],
        "next_checks_tr": [
            ".env dosyası proje kökünde ve okunabilir mi kontrol et",
            "Gerekli env değerlerinin dokümantasyonunu incele",
        ],
    },
    "CONFIG_ERROR": {
        "title_tr": "Yapılandırma hatası",
        "summary_tr": "Ayar doğrulaması başarısız; config/env hatası.",
        "impact_tr": "Servis başlamaz.",
        "actions_tr": [
            "Config/env değerlerini kontrol et",
            "Son 8 log satırındaki hata alanını düzelt",
            "Tekrar başlat",
        ],
        "next_checks_tr": [
            "Config şeması veya .env.example ile karşılaştır",
        ],
    },
    "MODULE_NOT_FOUND": {
        "title_tr": "Eksik modül / import hatası",
        "summary_tr": "Gerekli Python modülü bulunamadı.",
        "impact_tr": "Servis başlamaz.",
        "actions_tr": [
            "Virtualenv doğru mu kontrol et",
            "pip install -r requirements.txt çalıştır",
            "Çalışma dizini proje kökü mü kontrol et",
        ],
        "next_checks_tr": [
            "Hangi modül eksik logda yazıyor; pip ile kur",
        ],
    },
    "IMPORT_ERROR": {
        "title_tr": "Import hatası",
        "summary_tr": "Modül içe aktarılırken hata oluştu.",
        "impact_tr": "Servis başlamaz.",
        "actions_tr": [
            "Virtualenv ve requirements.txt kontrol et",
            "pip install -r requirements.txt",
            "Çalışma dizinini kontrol et",
        ],
        "next_checks_tr": [
            "Logdaki import satırını incele",
        ],
    },
    "PERMISSION": {
        "title_tr": "Yetki problemi",
        "summary_tr": "Dosya/klasör veya port erişimi yetkisi yok.",
        "impact_tr": "Servis başlamaz veya çöker.",
        "actions_tr": [
            "Dosya/klasör izinlerini düzelt",
            "Port 1024 altındaysa yönetici/root gerekebilir",
            "Servisi uygun yetkiyle çalıştır",
        ],
        "next_checks_tr": [
            "Logda hangi dosya/port belirtilmiş kontrol et",
        ],
    },
    "DB_DOWN": {
        "title_tr": "Bağlantı problemi (DB/Ağ)",
        "summary_tr": "Veritabanı veya harici servise bağlanılamadı.",
        "impact_tr": "Servis başlamaz veya işlevleri çalışmaz.",
        "actions_tr": [
            "DB/Redis/harici servis ayakta mı kontrol et",
            "Firewall/DNS ayarlarını kontrol et",
            "Config’teki endpoint’leri doğrula",
        ],
        "next_checks_tr": [
            "ping veya telnet ile erişimi test et",
        ],
    },
    "NETWORK": {
        "title_tr": "Ağ bağlantı hatası",
        "summary_tr": "Uzak sunucuya veya servise bağlanılamadı.",
        "impact_tr": "İlgili özellikler çalışmaz.",
        "actions_tr": [
            "Hedef sunucu ayakta mı kontrol et",
            "Firewall/DNS kontrol et",
            "Config endpoint’lerini doğrula",
        ],
        "next_checks_tr": [
            "Ağ erişimini test et",
        ],
    },
    "OOM": {
        "title_tr": "Bellek yetersizliği (OOM)",
        "summary_tr": "Süreç bellek limiti aşıldığı için sonlandırıldı.",
        "impact_tr": "Servis çöker; yeniden başlayana kadar kullanılamaz.",
        "actions_tr": [
            "RAM kullanımını kontrol et",
            "Limitleri artır veya bellek sızıntısı araştır",
            "Son işlemleri / yoğun job’ları incele",
        ],
        "next_checks_tr": [
            "Sistem bellek ve swap kullanımına bak",
        ],
    },
    "MANUAL_STOP": {
        "title_tr": "Manuel durduruldu",
        "summary_tr": "Servis bir kullanıcı işlemi ile durduruldu.",
        "impact_tr": "Servis kapalı; gerekirse yeniden başlat.",
        "actions_tr": [
            "Gerekirse panelden veya script ile yeniden başlat",
        ],
        "next_checks_tr": [],
    },
    "CRASH_LOOP": {
        "title_tr": "Çökme döngüsü",
        "summary_tr": "Kısa sürede birden fazla yeniden başlatma; servis sürekli çöküyor.",
        "impact_tr": "Servis kararlı çalışmıyor.",
        "actions_tr": [
            "Önce hatayı düzeltmeden yeniden başlatma",
            "Son hata/olay kayıtlarını incele",
            "Config ve bağımlılıkları doğrula",
        ],
        "next_checks_tr": [
            "Diagnosis ve log export ile kök nedeni bul",
        ],
    },
    "UNKNOWN": {
        "title_tr": "Bilinmeyen sebep",
        "summary_tr": "Otomatik teşhis eşleşmedi; log ve exit bilgisi ile incele.",
        "impact_tr": "Servis çalışmıyor veya başlamıyor.",
        "actions_tr": [
            "Son 200 log satırını dışa aktarıp incele",
            "Exit code ve signal bilgisine bak",
            "Gerekirse diagnosis’i dışa aktar ve paylaş",
        ],
        "next_checks_tr": [
            "Log ve evidence alanlarını incele",
        ],
    },
}


def _last_n_lines(lines: List[str], n: int = 8) -> List[str]:
    return (lines or [])[-n:]


def _service_port(service: str) -> Optional[int]:
    return _SERVICE_PORTS.get(service)


def diagnose(
    service: str,
    state: str,
    last_lines: Optional[List[str]] = None,
    exit_code: Optional[int] = None,
    signal: Optional[str] = None,
    port: Optional[int] = None,
    restart_count_5m: int = 0,
    last_audit_was_stop: bool = False,
    pid: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Teşhis üretir. state: RUNNING | STOPPED | START_FAILED | CRASH_LOOP | DEGRADED.
    last_lines: son log satırları (ring buffer’dan, max 200). evidence.last_lines max 8.
    """
    last_lines = last_lines or []
    port = port if port is not None else _service_port(service)
    now_iso = datetime.fromtimestamp(time.time(), tz=_TR_TZ).strftime("%Y-%m-%dT%H:%M:%S")
    evidence = {
        "exit_code": exit_code,
        "signal": signal or None,
        "pid": pid,
        "port": port,
        "last_lines": _last_n_lines(last_lines, 8),
        "matched_rules": [],
    }
    reason_code = "UNKNOWN"
    confidence = 0.5

    if state == "RUNNING":
        return {
            "service": service,
            "state": state,
            "reason_code": "RUNNING",
            "title_tr": "Çalışıyor",
            "summary_tr": "Servis normal çalışıyor.",
            "impact_tr": "Yok.",
            "evidence": evidence,
            "actions_tr": [],
            "next_checks_tr": [],
            "confidence": 1.0,
            "ts": now_iso,
        }

    if last_audit_was_stop and state == "STOPPED":
        reason_code = "MANUAL_STOP"
        confidence = 0.95
        evidence["matched_rules"] = ["MANUAL_STOP"]
    elif restart_count_5m >= 3:
        reason_code = "CRASH_LOOP"
        confidence = 0.9
        evidence["matched_rules"] = ["CRASH_LOOP"]
    else:
        text = "\n".join(last_lines[-200:]) if last_lines else ""
        for code, pattern, conf in _RULES:
            if pattern.search(text):
                reason_code = code
                confidence = conf
                evidence["matched_rules"] = [code]
                break
        if not evidence["matched_rules"] and exit_code == 137:
            reason_code = "OOM"
            confidence = 0.9
            evidence["matched_rules"] = ["OOM"]
        elif not evidence["matched_rules"]:
            evidence["matched_rules"] = ["UNKNOWN"]

    tr = _TR.get(reason_code, _TR["UNKNOWN"])
    actions = list(tr.get("actions_tr") or [])[:6]
    next_checks = list(tr.get("next_checks_tr") or [])[:6]
    if port is not None and "{port}" in str(actions):
        actions = [a.replace("{port}", str(port)) for a in actions]
    if port is not None and "{port}" in str(next_checks):
        next_checks = [c.replace("{port}", str(port)) for c in next_checks]

    return {
        "service": service,
        "state": state,
        "reason_code": reason_code,
        "title_tr": tr.get("title_tr", "Bilinmeyen"),
        "summary_tr": tr.get("summary_tr", ""),
        "impact_tr": tr.get("impact_tr", ""),
        "evidence": evidence,
        "actions_tr": actions,
        "next_checks_tr": next_checks,
        "confidence": round(confidence, 2),
        "ts": now_iso,
    }
