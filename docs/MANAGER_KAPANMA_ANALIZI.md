# Manager (7999) Kendi Kendine Kapandı — Analiz

## Olası Nedenler

### 1. **Yakalanmamış exception (ana teknik neden)**
- **do_GET / do_POST** içinde (get_full_status, log parse, JSON, dosya okuma vb.) oluşan herhangi bir hata yakalanmıyordu; exception yukarı çıkıp sunucuyu düşürüyordu.
- **get_full_status()** ağır: 3 log dosyası parse, 8000’e HTTP isteği, sistem bilgisi (system_profiler vb.). Timeout, OSError, encoding veya beklenmeyen bir hata = Manager kapanması.
- **Çözüm (yapıldı):** do_GET ve do_POST artık genel try/except ile sarıldı; hata `_log_handler_error` ile `logs/manager_backend.log` (veya stderr) + traceback yazılıyor, 500 dönülüyor, **sunucu kapanmıyor**.

### 2. **Power OFF veya Tüm Yeniden Başlat yanlışlıkla tıklandı**
- Bu iki buton başlıkta yan yana (Restart sarı, Power OFF kırmızı)
- Tıklanınca confirm penceresi çıkıyor; "Tamam" denirse Manager 2 saniye sonra öldürülüyor
- Yanlışlıkla veya aceleyle onay verilmiş olabilir

### 3. **Log dosyası her başlangıçta siliniyor**
- Önceden Manager her başlangıçta log dosyasını truncate ediyordu; kapanma anı mesajları kayboluyordu.
- **Çözüm (yapıldı):** Log append modunda; audit log eklendi.

### 4. **Diğer olası nedenler**
- **KeyboardInterrupt (Ctrl+C):** Terminal açıkken Ctrl+C ile Manager durdurulmuş olabilir
- **Port çakışması:** Başka bir uygulama 7999’u kullanmaya başlarsa Manager başlayamaz (bu kapanma değil)
- **Sistem/OOM:** Çok nadir; Python HTTP sunucusu için olağan değil

## Yapılan Çözümler

1. **Handler exception yakalama** — do_GET ve do_POST’ta tüm exception’lar yakalanıyor; hata loglanıyor (traceback ile), 500 dönülüyor, sunucu çalışmaya devam ediyor.
2. **Log append modunda** — Manager artık log dosyasını her başlangıçta silmiyor; önceki oturumun logları korunuyor.
3. **Audit log** — `.run/manager_audit.log` dosyasına Power OFF ve All Restart tetiklemeleri append ediliyor; kapandıktan sonra bu dosyadan tetiklenen işlem görülebilir.
4. **Power OFF için çift onay** (opsiyonel) — Yanlış tıklamayı azaltmak için ikinci bir onay penceresi eklenebilir.

Kapanma tekrarlarsa: `logs/manager_backend.log` son satırlarına ve `.run/manager_audit.log` içeriğine bakın; exception veya “POWER_OFF / ALL_RESTART tetiklendi” satırı nedeni gösterir.
