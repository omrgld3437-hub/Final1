"""
Anomali (sıra dışı / olmaması gereken) durum kodları – tek referans.
Admin panelde "Hatalar" listesinde event_kind=anomaly kayıtları bu kodlarla filtrelenir ve etiketlenir.
Yeni kod eklerken: (Türkçe kısa açıklama, varsayılan level).
"""

from typing import Tuple

# anomaly_code -> (açıklama_tr, default_level)
# level: info (bilgi), warning (dikkat), critical (kritik – hemen bakılmalı)
ANOMALY_CODES: dict[str, Tuple[str, str]] = {
    # Giriş / kimlik
    "LOGIN_RATE_LIMIT": ("Giriş isteği limiti aşıldı (IP/telefon)", "warning"),
    "LOGIN_USER_NOT_FOUND": ("Bilinmeyen kullanıcı/telefon ile giriş denemesi", "info"),
    "REPEATED_LOGIN_FAILURE": ("Ardışık başarısız şifre denemesi", "warning"),
    "ACCOUNT_SUSPENDED_AFTER_FAILURES": (
        "Hesap 3 başarısız deneme sonrası askıya alındı",
        "critical",
    ),
    "LOGIN_SUSPENDED_ATTEMPT": ("Askıya alınmış hesapla giriş denemesi", "warning"),
    "LOGIN_PENDING_APPROVAL": ("Onay bekleyen kayıt ile giriş denemesi", "info"),
    "SESSION_IP_MISMATCH": ("Oturum farklı IP adresinden kullanıldı", "info"),
    "SESSION_INVALID_OR_EXPIRED": ("Geçersiz veya süresi dolmuş oturum isteği", "info"),
    "ADMIN_IP_NOT_ALLOWED": ("Admin girişi izinli IP dışından denendi", "warning"),
    # İstek / erişim
    "RATE_LIMITED": ("İstek limiti aşıldı (rate limit)", "warning"),
    "UNUSUAL_REQUEST_PATH": ("Alışılmadık istek yolu veya method", "info"),
    "MISSING_OR_INVALID_TOKEN": ("Eksik veya geçersiz kimlik bilgisi", "info"),
    "FORBIDDEN_ACCESS_ATTEMPT": ("Yetkisiz erişim denemesi", "warning"),
    # Binance / harici servis
    "BINANCE_RATE_LIMIT_NEAR": ("Binance istek limitine yaklaşıldı", "info"),
    "BINANCE_RATE_LIMIT_HIT": ("Binance istek limiti aşıldı", "warning"),
    "BINANCE_AUTH_FAILURE": ("Binance API kimlik doğrulama hatası", "warning"),
    "BINANCE_UNUSUAL_RESPONSE": ("Binance alışılmadık yanıt (veri/format)", "info"),
    # Hesap / kullanıcı
    "ACCOUNT_ISOLATED_ACCESS_ATTEMPT": (
        "Adminden izole hesaba erişim denemesi",
        "info",
    ),
    "PASSWORD_CHANGE_AFTER_RESET": (
        "Şifre sıfırlama sonrası değişiklik (beklenen)",
        "info",
    ),
    "BULK_ACTION_UNUSUAL": ("Alışılmadık toplu işlem (çok sayıda hedef)", "info"),
    # Sistem
    "CONFIG_MISSING_OR_INVALID": ("Eksik veya geçersiz yapılandırma değeri", "warning"),
    "EXTERNAL_SERVICE_DEGRADED": ("Harici servis yavaş veya hata dönüyor", "warning"),
    "REPEATED_ERROR_SAME_ENDPOINT": ("Aynı endpoint’te tekrarlayan hata", "warning"),
}


def get_anomaly_description(code: str) -> str:
    """Anomali kodunun Türkçe açıklaması. Bilinmeyen kodda kodun kendisi döner."""
    if not code:
        return ""
    entry = ANOMALY_CODES.get(code)
    return entry[0] if entry else code


def get_anomaly_level(code: str) -> str:
    """Varsayılan severity level: info, warning, critical."""
    if not code:
        return "info"
    entry = ANOMALY_CODES.get(code)
    return entry[1] if entry else "info"
