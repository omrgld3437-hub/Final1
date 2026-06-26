"""
Sade Türkçe kullanıcı işlem geçmişi — event_type ve teknik sebep çevirileri.
Kullanıcı log dosyasında teknik kod görünmez; bu modül iç çeviri sağlar.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# event_type → (screen, action_template, default_result)
# action_template: {symbol}, {budget}, {coin}, {minutes}, {side}, {levels}, {preview} vb.
EVENT_TRANSLATIONS: Dict[str, Tuple[str, str, str]] = {
    "USER_LOGIN": ("Hesap", "Kullanıcı sisteme giriş yaptı", "Başarılı"),
    "USER_LOGOUT": ("Hesap", "Kullanıcı sistemden çıkış yaptı", "Oturum kapandı"),
    "LOGIN_SUCCESS": ("Hesap", "Kullanıcı sisteme giriş yaptı", "Başarılı"),
    "LOGIN_FAILED": ("Hesap", "Başarısız giriş denemesi oldu", "İşlem yapılmadı"),
    "LOGOUT": ("Hesap", "Kullanıcı sistemden çıkış yaptı", "Oturum kapandı"),
    "SESSION_TIMEOUT": ("Hesap", "Kullanıcı oturumu zaman aşımına uğradı", "Oturum kapandı"),
    "USER_REGISTER": ("Hesap", "Kullanıcı kayıt oldu", "Başarılı"),
    "PROFILE_UPDATE": ("Hesap", "Kullanıcı profil bilgisini güncelledi", "Ayar kaydedildi"),
    "PASSWORD_CHANGE": ("Hesap", "Kullanıcı şifresini değiştirdi", "İşlem tamamlandı"),
    "API_KEY_ADDED": ("API Ayarları", "Kullanıcı API bağlantısı ekledi", "Bağlantı kaydedildi"),
    "API_KEY_TESTED": ("API Ayarları", "Kullanıcı Binance API bağlantısını test etti", "Bağlantı başarılı"),
    "API_KEY_DELETED": ("API Ayarları", "Kullanıcı Binance API bağlantısını sildi", "İşlem tamamlandı"),
    "ADMIN_USER_SUSPENDED": ("Admin", "Kullanıcı hesabı admin tarafından pasife alındı", "İşlem tamamlandı"),
    "ADMIN_USER_UNSUSPENDED": ("Admin", "Kullanıcı hesabı admin tarafından aktif edildi", "İşlem tamamlandı"),
    "PAGE_VIEW": ("Menü", "Kullanıcı {page} sayfasını açtı", "Sayfa görüntülendi"),
    "TAB_CHANGED": ("Menü", "Kullanıcı sekme değiştirdi", "Sayfa açıldı"),
    "PARAM_COIN_SELECTED": ("Parametre Asistanı", "Kullanıcı {symbol} seçti", "Coin seçildi"),
    "PARAM_BUDGET_ENTERED": ("Parametre Asistanı", "Kullanıcı {budget} USDT bütçe girdi", "Bütçe kaydedildi"),
    "PARAM_ANALYSIS_STARTED": (
        "Parametre Asistanı",
        "{symbol} için {budget} USDT bütçeyle parametre analizi başlatıldı",
        "Analiz başladı",
    ),
    "PARAM_ANALYSIS_COMPLETED": (
        "Parametre Asistanı",
        "{symbol} için parametre analizi tamamlandı",
        "Analiz tamamlandı",
    ),
    "PARAM_ANALYSIS_FAILED": (
        "Parametre Asistanı",
        "{symbol} için güvenli parametre üretilemedi",
        "İşlem başlatılmadı",
    ),
    "PARAM_RESULT_DEPLOYABLE": (
        "Parametre Asistanı",
        "{symbol} için güvenli grid parametresi üretildi",
        "Otomatik işlem açılabilir",
    ),
    "PARAM_RESULT_RECOMMENDED": (
        "Parametre Asistanı",
        "{symbol} için parametre üretildi ancak otomatik işlem için yeterli güvenlik oluşmadı",
        "Sadece öneri gösterildi",
    ),
    "PARAM_RESULT_NO_TRADE": (
        "Parametre Asistanı",
        "{symbol} için işlem önerilmedi",
        "İşlem yapılmadı",
    ),
    "PARAM_ABORTED": (
        "Parametre Asistanı",
        "Kullanıcı parametre sonucunu onaylamadan sayfadan çıktı",
        "İşlem yapılmadı",
    ),
    "PARAM_APPROVED": ("Parametre Asistanı", "Kullanıcı parametreyi onayladı", "İşlem tamamlandı"),
    "PARAM_REJECTED": ("Parametre Asistanı", "Kullanıcı parametreyi reddetti", "İşlem yapılmadı"),
    "BOT_STARTED": ("Dinamik Mod", "{symbol} için bot başlatıldı", "Bot aktif"),
    "BOT_STOPPED": ("Dinamik Mod", "{symbol} için bot durduruldu", "Bot durduruldu"),
    "BOT_START": ("Dinamik Mod", "{symbol} için bot başlatıldı", "Bot aktif"),
    "BOT_STOP": ("Dinamik Mod", "{symbol} için bot durduruldu", "Bot durduruldu"),
    "DYNAMIC_TURN_ANALYSIS": (
        "Dinamik Mod",
        "{symbol} için yeni tur analizi yapıldı",
        "Piyasa kontrol edildi",
    ),
    "DYNAMIC_TURN_STARTED": ("Dinamik Mod", "{symbol} için yeni tur başlatıldı", "Grid kuruldu"),
    "DYNAMIC_TURN_BLOCKED": (
        "Dinamik Mod",
        "{symbol} için yeni tur başlatılmadı",
        "Piyasa riskli, sistem daha sonra tekrar deneyecek",
    ),
    "RETRY_PENDING": (
        "Dinamik Mod",
        "{symbol} için tur başlatılamadı",
        "Piyasa güvenli değil, sistem {minutes} dakika sonra tekrar deneyecek",
    ),
    "RETRY_ATTEMPTED": ("Dinamik Mod", "{symbol} tekrar kontrol edildi", "Kontrol yapıldı"),
    "RETRY_SUCCESS": (
        "Dinamik Mod",
        "{symbol} tekrar kontrol edildi",
        "Şartlar uygun hale geldi, tur başlatıldı",
    ),
    "RETRY_FAILED": (
        "Dinamik Mod",
        "{symbol} tekrar kontrol edildi",
        "Şartlar hâlâ uygun değil, işlem açılmadı",
    ),
    "REBALANCE_SKIPPED": (
        "Dinamik Mod",
        "Mevcut dağılım {current_alloc}, yeni hedef {target_alloc}",
        "Fark küçük olduğu için dengeleme yapılmadı",
    ),
    "REBALANCE_EVALUATED": (
        "Dinamik Mod",
        "Mevcut dağılım {current_alloc}, yeni hedef {target_alloc}",
        "Fark büyük olduğu için dengeleme değerlendirildi",
    ),
    "REBALANCE_EXECUTED": (
        "Dinamik Mod",
        "Base/quote dengelemesi için tek seferlik kontrollü {side} emri hazırlandı",
        "Bu emir grid emri değildir",
    ),
    "REBALANCE_FILLED": (
        "Dinamik Mod",
        "Base/quote dengeleme emri gerçekleşti",
        "Yeni dağılım tekrar kontrol edilecek",
    ),
    "REBALANCE_DEFERRED": (
        "Dinamik Mod",
        "Base/quote hedefi değişti ancak piyasa güvenli olmadığı için dengeleme yapılmadı",
        "Sistem beklemeye geçti",
    ),
    "GRID_BUY_PLACED": ("Grid", "{symbol} için alış grid kuruldu", "{levels} kademe aktif"),
    "GRID_SELL_PLACED": ("Grid", "{symbol} için satış grid kuruldu", "{levels} kademe aktif"),
    "GRID_NOT_PLACED": (
        "Grid",
        "{symbol} için gerçek grid kurulamadı",
        "Otomatik işlem açılmadı",
    ),
    "ORDER_CREATED": ("Emirler", "{symbol} {side} emri oluşturuldu", "Beklemede"),
    "ORDER_FILLED": ("Emirler", "{symbol} {side} emri gerçekleşti", "Emir gerçekleşti"),
    "ORDER_CANCELLED": ("Emirler", "{symbol} {side} emri iptal edildi", "Emir iptal edildi"),
    "ORDER_REJECTED": ("Emirler", "{symbol} emri oluşturulamadı", "İşlem yapılmadı"),
    "ADMIN_MESSAGE_SENT": ("Destek", "Kullanıcı admine mesaj gönderdi", "Mesaj iletildi"),
    "ADMIN_REPLY_SENT": ("Destek", "Admin kullanıcıya cevap verdi", "Mesaj gönderildi"),
    "CHAT_USER_MESSAGE": ("Destek", "Kullanıcı admine mesaj gönderdi", "Mesaj iletildi"),
    "CHAT_ADMIN_MESSAGE": ("Destek", "Admin kullanıcıya cevap verdi", "Mesaj gönderildi"),
    "SUPPORT_TICKET_OPENED": ("Destek", "Destek talebi açıldı", "İşlem tamamlandı"),
    "SUPPORT_TICKET_CLOSED": ("Destek", "Destek talebi kapandı", "İşlem tamamlandı"),
    "ADMIN_LOG_VIEWED": (
        "Admin",
        "Admin kullanıcının işlem logunu görüntüledi",
        "Görüntülendi",
    ),
    "ABANDON_COIN_NO_ANALYSIS": (
        "Parametre Asistanı",
        "Kullanıcı {symbol} seçti ancak analiz başlatmadan sayfadan çıktı",
        "İşlem yapılmadı",
    ),
    "ABANDON_BUDGET_NO_ANALYSIS": (
        "Parametre Asistanı",
        "Kullanıcı {budget} USDT bütçe girdi ancak analizi başlatmadı",
        "İşlem yapılmadı",
    ),
    "ABANDON_PARAM_NO_APPROVE": (
        "Parametre Asistanı",
        "Kullanıcı parametre sonucunu onaylamadan kapattı",
        "Bot başlatılmadı",
    ),
    "ABANDON_BOT_NO_START": (
        "Dinamik Mod",
        "Kullanıcı bot başlatma ekranına geldi ancak botu başlatmadı",
        "İşlem yapılmadı",
    ),
    "ABANDON_MESSAGE_UNSENT": (
        "Destek",
        "Kullanıcı mesaj yazdı ancak göndermeden sayfadan çıktı",
        "Mesaj iletilmedi",
    ),
    "SECURITY_BLOCK": ("Risk Kontrolü", "Sistem güvenlik nedeniyle işlem açmadı", "İşlem yapılmadı"),
    "INVARIANT_BLOCK": (
        "Risk Kontrolü",
        "Sistem güvenlik kuralı nedeniyle işlemi durdurdu",
        "İşlem yapılmadı",
    ),
}

# Teknik sebep kodları → sade Türkçe açıklama
TECHNICAL_REASON_TRANSLATIONS: Dict[str, str] = {
    "SPREAD_UNSAFE": "Piyasa spreadi yüksek olduğu için işlem açılmadı",
    "LOW_LIQUIDITY": "Coin likiditesi düşük olduğu için işlem güvenli bulunmadı",
    "DUMP_RISK": "Ani düşüş riski görüldüğü için işlem açılmadı",
    "DATA_STALE": "Piyasa verisi güncel olmadığı için işlem yapılmadı",
    "DATA_GAP": "Piyasa verisi eksik olduğu için işlem yapılmadı",
    "NO_SELLABLE_BASE": "Kullanıcının elinde satılacak coin olmadığı için satış grid kurulmadı",
    "MIN_GRID_COUNT_NOT_MET": "Gerçek grid için yeterli kademe oluşturulamadı",
    "INVALID_DISTRIBUTION": "Grid dağılımı risk profiline uygun olmadığı için işlem açılmadı",
    "EXPOSURE_HARD_CAP_BREACH": "İşlem sonrası risk limiti aşılacağı için grid kurulmadı",
    "INSUFFICIENT_BALANCE": "Bakiye yetersiz olduğu için emir oluşturulmadı",
    "MIN_NOTIONAL_FAILED": "Minimum emir tutarı sağlanmadığı için emir oluşturulmadı",
    "PRECISION_ERROR": "Emir miktarı borsa kurallarına uygun olmadığı için emir gönderilmedi",
    "ORDER_REJECTED": "Borsa emri kabul etmedi, işlem yapılmadı",
    "API_TIMEOUT": "Borsa bağlantısı geçici olarak sağlanamadı",
    "WEBSOCKET_DISCONNECTED": "Canlı veri bağlantısı geçici olarak koptu",
    "RUNTIME_SYNTHETIC_USED": "Sistem güvenli geçici profil ile öneri üretti",
    "REBALANCE_SAFETY_BLOCKED": "Base/quote dengelemesi piyasa güvenli olmadığı için ertelendi",
    "SMALL_BASE_QUOTE_DELTA": "Base/quote farkı küçük olduğu için dengeleme yapılmadı",
    "START_BLOCKED_RETRY_PENDING": "Tur başlatılamadı, sistem daha sonra tekrar deneyecek",
    "NO_TRADE": "Piyasa koşulları uygun olmadığı için işlem açılmadı",
    "REBALANCE_COOLDOWN_ACTIVE": "Dengeleme bekleme süresi devam ettiği için yapılmadı",
    "REBALANCE_DISABLED": "Dengeleme kapalı olduğu için yapılmadı",
}

# Audit event_type → user activity event_type
AUDIT_EVENT_MAP: Dict[str, str] = {
    "LOGIN_SUCCESS": "LOGIN_SUCCESS",
    "LOGIN_FAILED": "LOGIN_FAILED",
    "LOGOUT": "LOGOUT",
    "BOT_START": "BOT_START",
    "BOT_STOP": "BOT_STOP",
    "CHAT_USER_MESSAGE": "CHAT_USER_MESSAGE",
    "CHAT_ADMIN_MESSAGE": "CHAT_ADMIN_MESSAGE",
    "PASSWORD_CHANGE": "PASSWORD_CHANGE",
    "ADMIN_USER_SUSPENDED": "ADMIN_USER_SUSPENDED",
    "ADMIN_USER_UNSUSPENDED": "ADMIN_USER_UNSUSPENDED",
}


def translate_technical_reason(code: str) -> str:
    key = (code or "").strip().upper().replace(" ", "_")
    return TECHNICAL_REASON_TRANSLATIONS.get(
        key, "İşlem güvenlik veya piyasa koşulları nedeniyle yapılmadı"
    )


def format_event(
    event_type: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    action_override: Optional[str] = None,
    result_override: Optional[str] = None,
    screen_override: Optional[str] = None,
) -> Tuple[str, str, str]:
    """event_type + context → (screen, action, result)."""
    ctx = dict(context or {})
    tpl = EVENT_TRANSLATIONS.get(event_type)
    if tpl:
        screen, action_tpl, result_tpl = tpl
        try:
            action = action_tpl.format(**_safe_format_ctx(ctx))
            result = result_tpl.format(**_safe_format_ctx(ctx))
        except (KeyError, ValueError):
            action = action_tpl
            result = result_tpl
    else:
        screen = screen_override or "Sistem"
        action = action_override or "Kullanıcı işlemi kaydedildi"
        result = result_override or "İşlem tamamlandı"

    if screen_override:
        screen = screen_override
    if action_override:
        action = action_override
    if result_override:
        result = result_override

    tech = ctx.get("technical_reason") or ctx.get("block_reason")
    if tech and not result_override:
        translated = translate_technical_reason(str(tech))
        if translated and result == (tpl[2] if tpl else result):
            result = translated

    return screen, action, result


def _safe_format_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in ctx.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (int, float)):
            if k == "budget":
                out[k] = f"{v:g}"
            else:
                out[k] = v
        else:
            out[k] = str(v)
    if "side" in out:
        s = str(out["side"]).upper()
        out["side"] = "alış" if s in ("BUY", "ALIS", "ALIŞ") else "satış" if s in ("SELL", "SATIS", "SATIŞ") else str(out["side"]).lower()
    return out
