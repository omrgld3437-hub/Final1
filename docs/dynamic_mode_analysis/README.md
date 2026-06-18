# Dinamik Mod — Mantıksal Derinlik Analizi (Soru-Cevap)

> **Kapsam:** `app/botengine/dynamic/` — rejim sınıflandırma, indikatörler, feature toplama, strateji (değer üretimi), risk motoru, smoothing, snapshot yaşam döngüsü.
> **Yöntem:** Her soru gerçek koda dayanır; cevaplar `✅ doğru / ⚠️ orta sorun / 🔴 önemli sorun` ile işaretlidir.
> **Toplam:** 320 soru-cevap, 4 tematik dosya.
> **Durum:** Bu analiz + `PROJECT_WIDE_AUDIT_REPORT.md`'deki bulguların **kod düzeltmeleri uygulandı** (P0/P1/P2). Ne değişti / ne bilinçli ertelendi → **[FIX_LOG.md](FIX_LOG.md)**. (265 test geçti, +31 yeni.)

---

## Dosyalar

| Dosya | Konu | Sorular |
|-------|------|---------|
| [01_rejim_siniflandirma.md](01_rejim_siniflandirma.md) | Rejimler, eşikler, histerezis, zamansal kararlılık | S1–S85 |
| [02_indikatorler_veri.md](02_indikatorler_veri.md) | ATR/ADX/BBW/RSI/EMA/vol-z, feature toplama, veri tazeliği, zaman dilimleri | S86–S170 |
| [03_strateji_deger_uretimi.md](03_strateji_deger_uretimi.md) | Grid step/qty, trailing, alloc, kâr/yeniden-giriş, agresiflik/pasiflik | S171–S255 |
| [04_risk_smoothing_uc_durumlar.md](04_risk_smoothing_uc_durumlar.md) | Risk clamp/rate-limit/anti-martingale, smoothing, snapshot, uç durumlar, sayısal kararlılık | S256–S320 |
| [PROJECT_WIDE_AUDIT_REPORT.md](PROJECT_WIDE_AUDIT_REPORT.md) | Proje-geneli kod/mantık hatası denetimi, gerçek etki, düzeltme sırası | Konsolide rapor |
| [FIX_LOG.md](FIX_LOG.md) | **Uygulanan düzeltmeler** — hangi bulgu, kök neden, dosya, test, ertelenen + gerekçe | Düzeltme kaydı |

---

## Yönetici özeti — bulgular (önem sırasına göre)

### 🔴 Önemli (mantık boşlukları)

1. **Son durum: grid qty yüzdeleri manuel korunuyor.** İlk raporda `buy_levels_mult` ölü config olarak işaretlenmişti; son ürün kararıyla bu alan kaldırıldı. Dinamik mod artık grid miktar yüzdelerini rejime göre yeniden dağıtmıyor; savunmayı base/quote hedefi ve grid mesafesiyle yapıyor. → S188, S213 tarihsel bağlam.

2. **Toplanan feature'ların yarısı karara girmiyor.** `rsi_5m, rsi_1h, realized_vol_5m, atr_pct_1h, wick_body_ratio_5m, spread_pct, volume_24h_usdt` hesaplanıp snapshot'a yazılır ama ne rejim ne strateji bunları kullanır. Özellikle **RSI (aşırı alım/satım) hiç kullanılmıyor** — bot aşırı alım bölgesine alım, aşırı satım bölgesine satış yapabilir. → S95, S150–S156.

3. **DUMP_RISK "flash crash" değil.** Sinyal = 1h EMA slope ≤ −2% (≈5 saatlik eğilim) **VE** 5m hacim z-score ≥ 2. Anlık/hızlı bir çöküşü (5m bar) 1h slope henüz yansıtmadığı için **geç yakalar veya kaçırır**; düşük hacimli sızıntı çöküşünü hiç görmez. → S40–S48.

4. **Yarı-oluşmuş (forming) son mum indikatöre dahil.** Binance klines'in son elemanı henüz kapanmamış mumdur; ATR/RSI/BBW/ADX onu içerir (yalnız `volume_zscore` dışlar). → gürültü, erken/yanlış tetik, tutarsız muamele. → S88, S133.

5. **Dinamik grid derinliği yapısal olarak ≤%8.** Grid trigger %'leri `step×(i+1)` liner üretilir ve risk `BOUNDS["grid_step_pct"]` ile her seviye **8%'e clamp**'lenir. Sonuç: yüksek ATR'de gridler 8%'de çöküp **tek seviyeye iner** (degenerate); düşük ATR'de gridler **fee'nin altında** (~0.17%) olabilir. Dinamik modda kullanıcı -%20 DCA derinliği **kuramaz**. → S180–S187, S262.

### 🟠 Orta

6. **Histerezis fiilen devre dışı (`MIN_DWELL_CYCLES=1`).** İlk farklı sınıflandırmada anında geçer; `confidence*0.5` dalı ve dwell mekanizması **ölü kod**. Turlar seyrek olduğu için kısmen tamponlanır ama tasarımdaki anti-flip-flop koruması yok. → S55–S68.

7. **`confidence` neredeyse dekoratif.** Yalnız `TRENDING_DOWN & confidence<0.6` durumunda base'i 35'e yumuşatır; step/trail/alloc/tp'yi ölçeklemez. 0.45 ve 0.90 güvenli rejim **aynı agresif** tuning'i alır. → S71–S74.

8. **SQUEEZE/BREAKOUT veri asimetrisi.** SQUEEZE yalnız `bbw_1h`'e bakar; BREAKOUT `bbw` (1h yoksa 5m). 1h verisi <40 mumsa: SQUEEZE hiç açılmaz, ADX None → trend rejimleri de açılmaz → rejim ATR'ye düşer. → S30, S37, S120.

9. **BREAKOUT yön-kör.** BBW patlaması + hacim "yukarı mı aşağı mı" ayırmaz; aşağı breakout (çöküş) bile **nötr %50 base** alır (savunma değil). → S35.

10. **Kâr/yeniden-giriş eşikleri kısmen rejim-kör.** Yalnız `tp_rise` rejimle ölçeklenir; `tp_drop, re_drop, re_rise` saf ATR (rejimden bağımsız). → S205–S210.

11. **Buy/sell simetrisi.** Grid step ve trailing buy ve sell için **birebir aynı**; rejim asimetrisi yalnız base_alloc + tp_rise'da. → S196, S201.

12. **EMA trend eşiği ±%0.4 çok hassas.** 1h EMA(20)'nin 5 bar değişimi; ±0.4% gürültüde trend yönü atayabilir. → S105, S109.

### 🟢 Doğru çalışan (onaylanan)

- ATR/ADX/RSI/BBW/realized-vol Wilder/standart formüllerle **doğru** hesaplanıyor, None-safe, hataya dayanıklı. → S86–S132.
- `volume_zscore` forming mumu doğru dışlıyor. → S133.
- Rejim→tuning **yönleri** mantıklı (TD/DUMP defansif base, TU agresif base, yüksek vol → geniş grid/trailing, TU → geç kâr alma). → S171–S195.
- Risk motoru clamp + monotonluk + anti-martingale + rate-limit (skaler) **sağlam**. → S256–S280.
- Stale fallback, immutable snapshot, manuel-taban (H0 sonrası) **sağlam**. → S291–S305.
- Manuel mod tamamen baypas; dinamik paket devreye girmez. → S318.

---

## "300 soru" haritası (tematik dağılım)

- Rejim **sayısı/kapsamı** yeterli mi → S1–S15
- Rejim **eşikleri** doğru mu → S16–S39
- **DUMP/BREAKOUT/SQUEEZE** özel mantığı → S40–S54
- **Histerezis & zamansal kararlılık** (anlık mı, eğilim mi) → S55–S70
- **Confidence** kullanımı → S71–S78
- Rejim **tutarlılığı/öncelik sırası** → S79–S85
- **İndikatör doğruluğu** (her biri ayrı) → S86–S140
- **Feature toplama & veri tazeliği & zaman dilimi** → S141–S170
- **Grid step/qty üretimi** → S171–S195
- **Trailing / alloc / kâr / yeniden-giriş** → S196–S225
- **Agresiflik/pasiflik dengesi** → S226–S255
- **Risk motoru** → S256–S280
- **Smoothing & turlar arası kararlılık** → S281–S290
- **Snapshot yaşam döngüsü** → S291–S305
- **Uç durumlar & sayısal kararlılık** → S306–S320
